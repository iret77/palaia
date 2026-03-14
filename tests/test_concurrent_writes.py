"""Tests for concurrent write safety under parallel tool calling (#52)."""

from __future__ import annotations

import threading

import pytest

from palaia.config import DEFAULT_CONFIG, save_config
from palaia.store import Store
from palaia.wal import WAL


@pytest.fixture
def palaia_root(tmp_path):
    """Create a minimal .palaia directory."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()

    config = dict(DEFAULT_CONFIG)
    config["agent"] = "test"
    config["embedding_chain"] = ["bm25"]
    save_config(root, config)
    return root


def test_parallel_writes_no_entry_loss(palaia_root):
    """5 parallel writes must all succeed with no entry loss."""
    n_threads = 5
    results: dict[int, str] = {}
    errors: list[Exception] = []

    def write_entry(idx: int):
        try:
            store = Store(palaia_root)
            entry_id = store.write(
                body=f"Parallel entry number {idx}",
                tags=["parallel", f"thread-{idx}"],
                scope="team",
                title=f"Parallel Write {idx}",
            )
            results[idx] = entry_id
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=write_entry, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"Errors during parallel writes: {errors}"
    assert len(results) == n_threads, f"Expected {n_threads} results, got {len(results)}"

    # Verify all entries exist on disk
    store = Store(palaia_root)
    all_entries = store.all_entries_unfiltered(include_cold=False)
    entry_ids = {meta["id"] for meta, _, _ in all_entries}
    for idx, eid in results.items():
        assert eid in entry_ids, f"Entry from thread {idx} (id={eid}) missing from store"


def test_parallel_writes_wal_integrity(palaia_root):
    """WAL entries are consistent after parallel writes — no corruption."""
    n_threads = 5
    errors: list[Exception] = []

    def write_entry(idx: int):
        try:
            store = Store(palaia_root)
            store.write(
                body=f"WAL test entry {idx}",
                tags=["wal-test"],
                title=f"WAL Entry {idx}",
            )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=write_entry, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors

    # WAL should have no pending (all committed) or be recoverable
    wal = WAL(palaia_root / "wal")
    pending = wal.get_pending()
    # After successful writes, WAL entries should be committed (not pending)
    # Some may still be pending if cleanup hasn't run, but all should be parseable
    for entry in pending:
        assert entry.operation in ("write", "delete"), f"Unexpected WAL op: {entry.operation}"
        assert entry.target, "WAL entry missing target"


def test_parallel_writes_unique_ids(palaia_root):
    """Each parallel write produces a unique entry ID."""
    n_threads = 5
    ids: list[str] = []
    lock = threading.Lock()
    errors: list[Exception] = []

    def write_entry(idx: int):
        try:
            store = Store(palaia_root)
            entry_id = store.write(
                body=f"Unique ID test {idx}",
                tags=["id-test"],
                title=f"ID Test {idx}",
            )
            with lock:
                ids.append(entry_id)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=write_entry, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors
    assert len(ids) == n_threads
    assert len(set(ids)) == n_threads, f"Duplicate IDs detected: {ids}"


def test_parallel_writes_content_integrity(palaia_root):
    """Each entry's content matches what was written — no cross-contamination."""
    n_threads = 5
    results: dict[int, str] = {}
    errors: list[Exception] = []

    def write_entry(idx: int):
        try:
            store = Store(palaia_root)
            entry_id = store.write(
                body=f"MARKER_{idx}_UNIQUE_CONTENT",
                tags=[f"marker-{idx}"],
                title=f"Content Check {idx}",
            )
            results[idx] = entry_id
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=write_entry, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors
    assert len(results) == n_threads

    # Verify content
    store = Store(palaia_root)
    for idx, eid in results.items():
        meta, body = store.read(eid)
        assert f"MARKER_{idx}_UNIQUE_CONTENT" in body, f"Entry {eid} has wrong content: {body}"
        assert meta["title"] == f"Content Check {idx}"


def test_parallel_write_and_read(palaia_root):
    """Concurrent reads during writes don't crash or return corrupt data."""
    # Pre-populate some entries
    store = Store(palaia_root)
    pre_ids = []
    for i in range(3):
        eid = store.write(body=f"Pre-existing entry {i}", tags=["pre"], title=f"Pre {i}")
        pre_ids.append(eid)

    errors: list[Exception] = []
    read_results: list[int] = []
    lock = threading.Lock()

    def writer(idx: int):
        try:
            s = Store(palaia_root)
            s.write(body=f"Concurrent write {idx}", tags=["concurrent"], title=f"CW {idx}")
        except Exception as e:
            errors.append(e)

    def reader():
        try:
            s = Store(palaia_root)
            entries = s.all_entries_unfiltered(include_cold=False)
            with lock:
                read_results.append(len(entries))
        except Exception as e:
            errors.append(e)

    threads = []
    for i in range(3):
        threads.append(threading.Thread(target=writer, args=(i,)))
        threads.append(threading.Thread(target=reader))
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors
    # Reads should have returned at least the pre-existing entries
    for count in read_results:
        assert count >= 3, f"Reader saw only {count} entries, expected >= 3"
