"""Tests for Temporal Queries — point-in-time snapshots (Issue #74)."""

from __future__ import annotations

import pytest

from palaia.config import DEFAULT_CONFIG, save_config
from palaia.entry import parse_entry, serialize_entry
from palaia.search import SearchEngine
from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    root = tmp_path / ".palaia"
    root.mkdir()
    for d in ("hot", "warm", "cold", "wal", "index"):
        (root / d).mkdir()
    config = dict(DEFAULT_CONFIG)
    config["store_version"] = "2.0.0"
    save_config(root, config)
    return root


@pytest.fixture
def store(palaia_root):
    return Store(palaia_root)


def _backdate_entry(store, entry_id, iso_timestamp):
    """Helper: change the created timestamp of an entry."""
    path = store._find_entry(entry_id)
    text = path.read_text(encoding="utf-8")
    meta, body = parse_entry(text)
    meta["created"] = iso_timestamp
    path.write_text(serialize_entry(meta, body), encoding="utf-8")


@pytest.fixture
def temporal_store(store):
    """Store with entries at different timestamps."""
    id1 = store.write("Early architecture decision", tags=["architecture"], title="Early Decision")
    _backdate_entry(store, id1, "2026-01-15T10:00:00+00:00")

    id2 = store.write("Mid-project update", tags=["update"], title="Mid Update")
    _backdate_entry(store, id2, "2026-02-15T10:00:00+00:00")

    id3 = store.write("Late deployment plan", tags=["deployment"], title="Late Plan")
    _backdate_entry(store, id3, "2026-03-15T10:00:00+00:00")

    return store, [id1, id2, id3]


class TestTemporalSearch:
    def test_before_filter(self, temporal_store):
        store, ids = temporal_store
        engine = SearchEngine(store)
        results = engine.search("decision update plan", before="2026-02-01")
        # Only the Jan entry should match
        result_ids = [r["id"] for r in results]
        assert ids[0] in result_ids
        assert ids[1] not in result_ids
        assert ids[2] not in result_ids

    def test_after_filter(self, temporal_store):
        store, ids = temporal_store
        engine = SearchEngine(store)
        results = engine.search("decision update plan", after="2026-03-01")
        result_ids = [r["id"] for r in results]
        assert ids[2] in result_ids
        assert ids[0] not in result_ids
        assert ids[1] not in result_ids

    def test_time_window(self, temporal_store):
        store, ids = temporal_store
        engine = SearchEngine(store)
        results = engine.search("decision update plan", after="2026-02-01", before="2026-03-01")
        result_ids = [r["id"] for r in results]
        assert ids[1] in result_ids
        assert ids[0] not in result_ids
        assert ids[2] not in result_ids

    def test_no_results_in_window(self, temporal_store):
        store, ids = temporal_store
        engine = SearchEngine(store)
        results = engine.search("decision update plan", after="2026-04-01")
        assert len(results) == 0

    def test_future_before(self, temporal_store):
        store, ids = temporal_store
        engine = SearchEngine(store)
        results = engine.search("decision update plan", before="2027-01-01")
        # All entries should match
        assert len(results) == 3

    def test_exact_boundary_excluded(self, temporal_store):
        store, ids = temporal_store
        engine = SearchEngine(store)
        # before is exclusive (< not <=)
        results = engine.search("Early Decision", before="2026-01-15T10:00:00+00:00")
        result_ids = [r["id"] for r in results]
        assert ids[0] not in result_ids

    def test_after_boundary_excluded(self, temporal_store):
        store, ids = temporal_store
        engine = SearchEngine(store)
        # after is exclusive (> not >=)
        results = engine.search("Late Plan", after="2026-03-15T10:00:00+00:00")
        result_ids = [r["id"] for r in results]
        assert ids[2] not in result_ids
