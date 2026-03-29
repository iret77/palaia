"""Tests for SearchEngine cache invalidation by corpus params."""

from __future__ import annotations

import pytest

from palaia.config import DEFAULT_CONFIG, save_config
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


class TestSearchEngineCacheInvalidation:
    """Verify that build_index() rebuilds when corpus params change."""

    def test_cache_hit_same_params(self, store):
        store.write("Test entry for caching", tags=["test"], title="Cache Test")
        engine = SearchEngine(store)

        # First build — should read from disk
        docs1 = engine.build_index(include_cold=False, agent=None)
        assert len(docs1) > 0

        # Second build with same params — should use cache
        docs2 = engine.build_index(include_cold=False, agent=None)
        assert len(docs2) == len(docs1)
        assert not engine._index_dirty

    def test_cache_miss_on_include_cold_change(self, store):
        store.write("Hot entry", tags=["test"], title="Hot")
        engine = SearchEngine(store)

        # Build with include_cold=False
        engine.build_index(include_cold=False, agent=None)
        assert engine._index_cache_key == (False, None)

        # Build with include_cold=True — cache key differs, should rebuild
        engine.build_index(include_cold=True, agent=None)
        assert engine._index_cache_key == (True, None)

    def test_cache_miss_on_agent_change(self, store):
        store.write("Entry by agent-a", tags=["test"], agent="agent-a", title="A")
        store.write("Entry by agent-b", tags=["test"], agent="agent-b", title="B")
        engine = SearchEngine(store)

        # Build for agent-a
        engine.build_index(include_cold=False, agent="agent-a")
        key_a = engine._index_cache_key
        assert key_a == (False, "agent-a")

        # Build for agent-b — cache key changes, should rebuild
        engine.build_index(include_cold=False, agent="agent-b")
        key_b = engine._index_cache_key
        assert key_b == (False, "agent-b")
        assert key_a != key_b

    def test_invalidate_index_forces_rebuild(self, store):
        store.write("Test entry", tags=["test"], title="Invalidation Test")
        engine = SearchEngine(store)

        engine.build_index()
        assert not engine._index_dirty

        engine.invalidate_index()
        assert engine._index_dirty
        assert engine._index_cache is None

        # Rebuild after invalidation
        docs = engine.build_index()
        assert not engine._index_dirty
        assert len(docs) > 0

    def test_cache_key_combo_cold_and_agent(self, store):
        """Different (include_cold, agent) combos produce different cache keys."""
        store.write("Entry", tags=["test"], title="Combo Test")
        engine = SearchEngine(store)

        engine.build_index(include_cold=False, agent=None)
        assert engine._index_cache_key == (False, None)

        engine.build_index(include_cold=True, agent="bot")
        assert engine._index_cache_key == (True, "bot")

        engine.build_index(include_cold=False, agent="bot")
        assert engine._index_cache_key == (False, "bot")
