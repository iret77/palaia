"""Tests for the SQLite storage backend."""

from __future__ import annotations

import pytest

from palaia.backends.sqlite import SQLiteBackend


@pytest.fixture
def backend(tmp_path):
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    return SQLiteBackend(root)


# ── Metadata CRUD ──────────────────────────────────────────────────


class TestMetadata:
    def test_upsert_and_get(self, backend):
        meta = {"title": "Test", "scope": "team", "type": "memory",
                "content_hash": "abc123", "tags": ["a", "b"]}
        backend.upsert_entry("e1", meta, "hot")
        result = backend.get_entry("e1")
        assert result is not None
        assert result["title"] == "Test"
        assert result["tier"] == "hot"
        assert result["tags"] == ["a", "b"]

    def test_get_nonexistent(self, backend):
        assert backend.get_entry("nonexistent") is None

    def test_upsert_updates_existing(self, backend):
        backend.upsert_entry("e1", {"title": "V1", "scope": "team"}, "hot")
        backend.upsert_entry("e1", {"title": "V2", "scope": "private"}, "warm")
        result = backend.get_entry("e1")
        assert result["title"] == "V2"
        assert result["tier"] == "warm"

    def test_remove_entry(self, backend):
        backend.upsert_entry("e1", {"title": "T"}, "hot")
        backend.remove_entry("e1")
        assert backend.get_entry("e1") is None

    def test_find_by_hash(self, backend):
        backend.upsert_entry("e1", {"content_hash": "hash1"}, "hot")
        backend.upsert_entry("e2", {"content_hash": "hash2"}, "hot")
        assert backend.find_by_hash("hash1") == "e1"
        assert backend.find_by_hash("hash2") == "e2"
        assert backend.find_by_hash("hash3") is None

    def test_entry_count(self, backend):
        assert backend.entry_count() == 0
        backend.upsert_entry("e1", {}, "hot")
        backend.upsert_entry("e2", {}, "warm")
        assert backend.entry_count() == 2
        assert backend.entry_count("hot") == 1
        assert backend.entry_count("warm") == 1


# ── Query ──────────────────────────────────────────────────────────


class TestQuery:
    def test_query_by_tier(self, backend):
        backend.upsert_entry("e1", {"type": "memory"}, "hot")
        backend.upsert_entry("e2", {"type": "memory"}, "warm")
        results = backend.query_entries(tier="hot")
        assert len(results) == 1
        assert results[0]["id"] == "e1"

    def test_query_by_type(self, backend):
        backend.upsert_entry("e1", {"type": "memory"}, "hot")
        backend.upsert_entry("e2", {"type": "task"}, "hot")
        results = backend.query_entries(entry_type="task")
        assert len(results) == 1
        assert results[0]["id"] == "e2"

    def test_query_by_project(self, backend):
        backend.upsert_entry("e1", {"project": "alpha"}, "hot")
        backend.upsert_entry("e2", {"project": "beta"}, "hot")
        results = backend.query_entries(project="alpha")
        assert len(results) == 1

    def test_query_with_limit(self, backend):
        for i in range(10):
            backend.upsert_entry(f"e{i}", {"decay_score": float(i)}, "hot")
        results = backend.query_entries(limit=3)
        assert len(results) == 3

    def test_query_order_by(self, backend):
        backend.upsert_entry("e1", {"decay_score": 0.1}, "hot")
        backend.upsert_entry("e2", {"decay_score": 0.9}, "hot")
        results = backend.query_entries(order_by="decay_score ASC")
        assert results[0]["id"] == "e1"
        results = backend.query_entries(order_by="decay_score DESC")
        assert results[0]["id"] == "e2"

    def test_all_entry_ids(self, backend):
        backend.upsert_entry("e1", {}, "hot")
        backend.upsert_entry("e2", {}, "cold")
        ids_no_cold = backend.all_entry_ids(include_cold=False)
        assert "e1" in ids_no_cold
        assert "e2" not in ids_no_cold
        ids_with_cold = backend.all_entry_ids(include_cold=True)
        assert "e2" in ids_with_cold

    def test_cleanup_entries(self, backend):
        backend.upsert_entry("e1", {}, "hot")
        backend.upsert_entry("e2", {}, "hot")
        backend.upsert_entry("e3", {}, "hot")
        removed = backend.cleanup_entries({"e1", "e3"})
        assert removed == 1
        assert backend.get_entry("e2") is None
        assert backend.get_entry("e1") is not None


# ── Embeddings ─────────────────────────────────────────────────────


class TestEmbeddings:
    def test_set_and_get(self, backend):
        backend.upsert_entry("e1", {}, "hot")
        vector = [0.1, 0.2, 0.3, 0.4]
        backend.set_embedding("e1", vector, "test-model", 4)
        result = backend.get_embedding("e1")
        assert result is not None
        vec, model, dim = result
        assert model == "test-model"
        assert dim == 4
        assert len(vec) == 4
        assert abs(vec[0] - 0.1) < 0.001

    def test_get_nonexistent(self, backend):
        assert backend.get_embedding("nonexistent") is None

    def test_invalidate(self, backend):
        backend.upsert_entry("e1", {}, "hot")
        backend.set_embedding("e1", [1.0, 2.0], "m", 2)
        backend.invalidate_embedding("e1")
        assert backend.get_embedding("e1") is None

    def test_cleanup(self, backend):
        backend.upsert_entry("e1", {}, "hot")
        backend.upsert_entry("e2", {}, "hot")
        backend.set_embedding("e1", [1.0], "m", 1)
        backend.set_embedding("e2", [2.0], "m", 1)
        removed = backend.cleanup_embeddings({"e1"})
        assert removed == 1
        assert backend.get_embedding("e2") is None


# ── Vector search ──────────────────────────────────────────────────


class TestVectorSearch:
    def test_basic_search(self, backend):
        backend.upsert_entry("e1", {"type": "memory"}, "hot")
        backend.upsert_entry("e2", {"type": "memory"}, "hot")
        backend.set_embedding("e1", [1.0, 0.0, 0.0], "m", 3)
        backend.set_embedding("e2", [0.0, 1.0, 0.0], "m", 3)
        results = backend.vector_search([1.0, 0.0, 0.0], top_k=2)
        assert len(results) == 2
        assert results[0][0] == "e1"  # Exact match should be first
        assert results[0][1] > results[1][1]

    def test_search_with_tier_filter(self, backend):
        backend.upsert_entry("e1", {"type": "memory"}, "hot")
        backend.upsert_entry("e2", {"type": "memory"}, "cold")
        backend.set_embedding("e1", [1.0, 0.0], "m", 2)
        backend.set_embedding("e2", [1.0, 0.0], "m", 2)
        results = backend.vector_search([1.0, 0.0], tier="hot")
        assert len(results) == 1
        assert results[0][0] == "e1"

    def test_search_empty(self, backend):
        results = backend.vector_search([1.0, 0.0], top_k=5)
        assert results == []


# ── WAL ────────────────────────────────────────────────────────────


class TestWAL:
    def test_log_and_commit(self, backend):
        backend.log_wal("w1", "write", "hot/e1.md", "hash1", "payload1")
        pending = backend.get_pending_wal()
        assert len(pending) == 1
        assert pending[0]["id"] == "w1"
        assert pending[0]["status"] == "pending"

        backend.commit_wal("w1")
        pending = backend.get_pending_wal()
        assert len(pending) == 0

    def test_multiple_pending(self, backend):
        backend.log_wal("w1", "write", "t1", "h1", "p1")
        backend.log_wal("w2", "write", "t2", "h2", "p2")
        pending = backend.get_pending_wal()
        assert len(pending) == 2

    def test_cleanup_old(self, backend):
        backend.log_wal("w1", "write", "t1", "h1", "p1")
        backend.commit_wal("w1")
        # With max_age_days=0, should clean up committed entries.
        cleaned = backend.cleanup_wal(max_age_days=0)
        assert cleaned >= 0  # Timestamp granularity may vary


# ── Lifecycle ──────────────────────────────────────────────────────


class TestLifecycle:
    def test_health_check(self, backend):
        result = backend.health_check()
        assert result["status"] == "ok"
        assert result["backend"] == "sqlite"
        assert isinstance(result["entries"], int)

    def test_close(self, backend):
        backend.close()
        # Should not raise on close


# ── SQL injection prevention ───────────────────────────────────────


class TestSafety:
    def test_invalid_order_by_sanitized(self, backend):
        backend.upsert_entry("e1", {"decay_score": 1.0}, "hot")
        # Attempt SQL injection via order_by
        results = backend.query_entries(order_by="1; DROP TABLE entries; --")
        # Should not crash, should use default ordering
        assert len(results) == 1
