"""Tests for doctor index-staleness check (Fix 3)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from palaia.doctor import _check_index_staleness, run_doctor
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
def palaia_root_semantic(tmp_path):
    """Create a palaia store with semantic embeddings configured."""
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


class TestDoctorIndexStaleness:
    def test_bm25_only_reports_ok(self, palaia_root):
        """BM25-only config should report ok (no semantic index needed)."""
        result = _check_index_staleness(palaia_root)
        assert result["status"] == "ok"
        assert "BM25-only" in result["message"]

    def test_no_entries_reports_ok(self, palaia_root_semantic):
        """Empty store should report ok."""
        with patch("palaia.embeddings.build_embedding_chain") as mock:
            from unittest.mock import MagicMock

            chain = MagicMock()
            chain.providers = [MagicMock()]  # Non-BM25 provider
            mock.return_value = chain

            result = _check_index_staleness(palaia_root_semantic)
            assert result["status"] == "ok"

    def test_detects_stale_index(self, palaia_root_semantic):
        """Should warn when >10% of entries are missing from cache."""
        # Create entry files directly (bypass store.write to avoid auto-indexing)
        import uuid

        for i in range(10):
            eid = str(uuid.uuid4())[:8]
            content = f"---\nid: {eid}\ntitle: Entry {i}\nagent: test-agent\nscope: team\n---\nEntry {i}"
            (palaia_root_semantic / "hot" / f"{eid}.md").write_text(content)

        with patch("palaia.embeddings.build_embedding_chain") as mock:
            from unittest.mock import MagicMock

            chain = MagicMock()
            chain.providers = [MagicMock()]  # Non-BM25 provider
            mock.return_value = chain

            result = _check_index_staleness(palaia_root_semantic)
            assert result["status"] == "warn"
            assert "not indexed" in result["message"]
            assert result.get("fixable") is True

    def test_fully_indexed_reports_ok(self, palaia_root_semantic):
        """Should report ok when all entries are in cache."""
        store = Store(palaia_root_semantic)
        entry_id = store.write("Only entry", agent="test-agent", title="Only")
        # Manually add to cache
        store.embedding_cache.set_cached(entry_id, [0.1] * 10, model="test")

        with patch("palaia.embeddings.build_embedding_chain") as mock:
            from unittest.mock import MagicMock

            chain = MagicMock()
            chain.providers = [MagicMock()]  # Non-BM25 provider
            mock.return_value = chain

            result = _check_index_staleness(palaia_root_semantic)
            assert result["status"] == "ok"

    def test_staleness_in_full_doctor_run(self, palaia_root):
        """Index staleness check should be included in full doctor run."""
        results = run_doctor(palaia_root)
        names = [r["name"] for r in results]
        assert "index_staleness" in names

    def test_not_initialized(self):
        """Should handle None root gracefully."""
        result = _check_index_staleness(None)
        assert result["status"] == "error"
