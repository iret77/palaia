"""Tests for embedding cache."""

from __future__ import annotations

import threading

import pytest

from palaia.index import EmbeddingCache


@pytest.fixture
def cache(tmp_path):
    root = tmp_path / ".palaia"
    root.mkdir()
    (root / "index").mkdir()
    return EmbeddingCache(root)


def test_set_and_get(cache):
    vec = [0.1, 0.2, 0.3]
    cache.set_cached("entry-1", vec, model="test-model")
    result = cache.get_cached("entry-1")
    assert result == vec


def test_get_missing(cache):
    assert cache.get_cached("nonexistent") is None


def test_invalidate(cache):
    cache.set_cached("entry-1", [1.0, 2.0])
    assert cache.invalidate("entry-1") is True
    assert cache.get_cached("entry-1") is None


def test_invalidate_missing(cache):
    assert cache.invalidate("nonexistent") is False


def test_cleanup(cache):
    cache.set_cached("keep-1", [1.0])
    cache.set_cached("keep-2", [2.0])
    cache.set_cached("stale-1", [3.0])

    removed = cache.cleanup({"keep-1", "keep-2"})
    assert removed == 1
    assert cache.get_cached("keep-1") is not None
    assert cache.get_cached("stale-1") is None


def test_stats(cache):
    cache.set_cached("a", [1.0], model="nomic")
    cache.set_cached("b", [2.0], model="openai")
    stats = cache.stats()
    assert stats["cached_entries"] == 2
    assert "nomic" in stats["models"]
    assert "openai" in stats["models"]


def test_persistence(tmp_path):
    """Cache survives re-instantiation."""
    root = tmp_path / ".palaia"
    root.mkdir()
    (root / "index").mkdir()

    c1 = EmbeddingCache(root)
    c1.set_cached("persist", [42.0])

    c2 = EmbeddingCache(root)
    assert c2.get_cached("persist") == [42.0]


def test_concurrent_writes(tmp_path):
    """Multiple threads writing simultaneously should not corrupt the cache."""
    root = tmp_path / ".palaia"
    root.mkdir()
    (root / "index").mkdir()

    errors = []
    num_threads = 8
    writes_per_thread = 20

    def writer(thread_idx):
        try:
            cache = EmbeddingCache(root)
            for i in range(writes_per_thread):
                entry_id = f"thread-{thread_idx}-entry-{i}"
                vec = [float(thread_idx), float(i)]
                cache.set_cached(entry_id, vec, model=f"model-{thread_idx}")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Concurrent writes raised errors: {errors}"

    # Verify the cache file is valid JSON and contains entries
    final_cache = EmbeddingCache(root)
    stats = final_cache.stats()
    assert stats["cached_entries"] > 0, "Cache should contain entries after concurrent writes"
