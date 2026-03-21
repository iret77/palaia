"""Tests for incremental embedding indexing on write (Fix 2)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    """Create a minimal palaia store for testing."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for d in ("hot", "warm", "cold", "wal", "index"):
        (root / d).mkdir()
    config = {
        "agent": "test-agent",
        "default_scope": "team",
        "embedding_provider": "none",
        "embedding_chain": ["bm25"],
        "decay_lambda": 0.1,
        "hot_threshold_days": 7,
        "warm_threshold_days": 30,
        "hot_min_score": 0.3,
        "warm_min_score": 0.1,
        "lock_timeout_seconds": 5,
        "wal_retention_days": 7,
    }
    (root / "config.json").write_text(json.dumps(config))
    return root


@pytest.fixture
def palaia_root_with_embeddings(tmp_path):
    """Create a palaia store with a semantic embedding chain configured."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for d in ("hot", "warm", "cold", "wal", "index"):
        (root / d).mkdir()
    config = {
        "agent": "test-agent",
        "default_scope": "team",
        "embedding_provider": "sentence-transformers",
        "embedding_chain": ["sentence-transformers", "bm25"],
        "decay_lambda": 0.1,
        "hot_threshold_days": 7,
        "warm_threshold_days": 30,
        "hot_min_score": 0.3,
        "warm_min_score": 0.1,
        "lock_timeout_seconds": 5,
        "wal_retention_days": 7,
    }
    (root / "config.json").write_text(json.dumps(config))
    return root


class TestIncrementalIndexing:
    def test_write_does_not_fail_without_embedding_provider(self, palaia_root):
        """Write must succeed even when no embedding provider is available (BM25-only)."""
        store = Store(palaia_root)
        entry_id = store.write("Test content", agent="test-agent", title="Test")
        assert entry_id
        # No embedding should be cached (BM25 doesn't produce vectors)
        assert store.embedding_cache.get_cached(entry_id) is None

    def test_write_indexes_entry_when_provider_available(self, palaia_root_with_embeddings):
        """After write, the new entry should have an embedding in cache."""
        # Mock the embedding chain to avoid needing real sentence-transformers
        mock_vector = [0.1] * 384

        with patch("palaia.embeddings.build_embedding_chain") as mock_chain_fn:
            mock_chain = MagicMock()
            mock_provider = MagicMock()
            mock_provider.model_name = "test-model"
            mock_chain.providers = [mock_provider]
            mock_chain.embed.return_value = ([mock_vector], "sentence-transformers")
            mock_chain_fn.return_value = mock_chain

            store = Store(palaia_root_with_embeddings)
            entry_id = store.write("Test content for embedding", agent="test-agent", title="Test")

        assert entry_id
        cached = store.embedding_cache.get_cached(entry_id)
        assert cached is not None
        assert len(cached) == 384

    def test_write_succeeds_when_embedding_fails(self, palaia_root_with_embeddings):
        """Write must not fail if embedding computation raises an exception."""
        with patch("palaia.embeddings.build_embedding_chain") as mock_chain_fn:
            mock_chain = MagicMock()
            mock_provider = MagicMock()
            mock_chain.providers = [mock_provider]
            mock_chain.embed.side_effect = RuntimeError("GPU out of memory")
            mock_chain_fn.return_value = mock_chain

            store = Store(palaia_root_with_embeddings)
            entry_id = store.write("Content that should still be saved", agent="test-agent", title="Test")

        assert entry_id
        # Entry should exist on disk even though embedding failed
        assert (palaia_root_with_embeddings / "hot" / f"{entry_id}.md").exists()

    def test_index_single_entry_returns_false_for_bm25_only(self, palaia_root):
        """_index_single_entry should return False when only BM25 is available."""
        store = Store(palaia_root)
        result = store._index_single_entry("test-id", {"title": "Test"}, "body")
        assert result is False
