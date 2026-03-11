"""Tests for audit fix items."""

import json
import time
import warnings

import pytest

from palaia.config import DEFAULT_CONFIG, save_config
from palaia.entry import _parse_yaml_simple
from palaia.lock import STALE_LOCK_SECONDS, PalaiaLock
from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    save_config(root, DEFAULT_CONFIG)
    return root


# --- Audit Fix 1: Empty content raises ValueError ---


def test_write_empty_string_raises(palaia_root):
    store = Store(palaia_root)
    with pytest.raises(ValueError, match="empty content"):
        store.write("")


def test_write_whitespace_only_raises(palaia_root):
    store = Store(palaia_root)
    with pytest.raises(ValueError, match="empty content"):
        store.write("   \n\t  ")


def test_write_normal_content_works(palaia_root):
    store = Store(palaia_root)
    entry_id = store.write("Valid content here")
    assert entry_id is not None


# --- Audit Fix 3: YAML parsing with colons ---


def test_yaml_parse_url_value():
    yaml_text = "url: https://example.com:8080/path"
    result = _parse_yaml_simple(yaml_text)
    assert result["url"] == "https://example.com:8080/path"


def test_yaml_parse_title_with_colon():
    yaml_text = "title: Foo: Bar: Baz"
    result = _parse_yaml_simple(yaml_text)
    assert result["title"] == "Foo: Bar: Baz"


def test_yaml_parse_iso_timestamp():
    yaml_text = "created: 2026-03-11T10:24:00+00:00"
    result = _parse_yaml_simple(yaml_text)
    assert result["created"] == "2026-03-11T10:24:00+00:00"


def test_yaml_parse_multiple_colons():
    yaml_text = """id: abc-123
title: Fix: YAML: Parser
created: 2026-03-11T10:24:00+00:00"""
    result = _parse_yaml_simple(yaml_text)
    assert result["id"] == "abc-123"
    assert result["title"] == "Fix: YAML: Parser"
    assert "2026-03-11T10" in result["created"]


# --- Audit Fix 2: GC uses WAL ---


def test_gc_uses_wal(palaia_root):
    """Verify that GC tier moves are WAL-logged."""
    store = Store(palaia_root)

    # Write an entry
    entry_id = store.write("Test GC WAL", scope="team")

    # Manually age the entry to force tier move
    entry_path = palaia_root / "hot" / f"{entry_id}.md"
    text = entry_path.read_text()

    # Replace timestamps to make it 60 days old
    old_date = "2025-01-01T00:00:00+00:00"
    text = text.replace(text.split("created: ")[1].split("\n")[0], old_date).replace(
        text.split("accessed: ")[1].split("\n")[0], old_date
    )
    entry_path.write_text(text)

    # Run GC
    result = store.gc()

    # Should have moved from hot to cold/warm
    total_moves = sum(v for k, v in result.items() if k.startswith("hot_to"))
    # Check that WAL has committed entries for the move
    wal_files = list((palaia_root / "wal").glob("*.json"))
    committed = 0
    for wf in wal_files:
        data = json.loads(wf.read_text())
        if data.get("status") == "committed" and data.get("operation") == "write":
            committed += 1

    if total_moves > 0:
        assert committed >= total_moves, "GC tier moves should be WAL-logged"


# --- Audit Fix 4: Lock stale detection ---


def test_stale_lock_detection(palaia_root):
    """Lock older than 60s should be detected as stale."""
    lock = PalaiaLock(palaia_root, timeout=1.0)

    # Create a fake stale lock
    lock_path = palaia_root / ".lock"
    stale_ts = time.time() - (STALE_LOCK_SECONDS + 10)
    lock_path.write_text(json.dumps({"pid": 99999, "ts": stale_ts}))

    # Should be able to acquire despite stale lock
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        lock.acquire()
        lock.release()

    # Should have warned about stale lock
    stale_warnings = [x for x in w if "Stale lock" in str(x.message)]
    assert len(stale_warnings) > 0


def test_fresh_lock_not_stale(palaia_root):
    """Lock that's fresh should not be flagged as stale."""
    lock = PalaiaLock(palaia_root, timeout=2.0)

    # Create a fresh lock (but don't actually flock it)
    lock_path = palaia_root / ".lock"
    lock_path.write_text(json.dumps({"pid": 99999, "ts": time.time()}))

    # The _check_stale should not remove a fresh lock
    is_stale = lock._check_stale()
    assert is_stale is False
