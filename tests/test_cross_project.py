"""Tests for Cross-Project Queries (Issue #38)."""

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


@pytest.fixture
def multi_project_store(store):
    """Store with entries across multiple projects."""
    id1 = store.write(
        "Deploy to production using Docker", project="frontend", tags=["deployment"], title="Frontend Deploy"
    )
    id2 = store.write(
        "Deploy backend services via Kubernetes", project="backend", tags=["deployment"], title="Backend Deploy"
    )
    id3 = store.write("Database migration strategy", project="backend", tags=["database"], title="DB Migration")
    id4 = store.write(
        "General deployment checklist",
        project="ops",
        tags=["deployment", "checklist"],
        entry_type="process",
        title="Deploy Checklist",
    )
    return store, [id1, id2, id3, id4]


class TestCrossProjectSearch:
    def test_cross_project_finds_all(self, multi_project_store):
        store, ids = multi_project_store
        engine = SearchEngine(store)
        results = engine.search("deployment", cross_project=True)

        result_ids = [r["id"] for r in results]
        # Should find entries from frontend, backend, and ops
        assert ids[0] in result_ids  # frontend
        assert ids[1] in result_ids  # backend
        assert ids[3] in result_ids  # ops

    def test_cross_project_includes_project_field(self, multi_project_store):
        store, ids = multi_project_store
        engine = SearchEngine(store)
        results = engine.search("deployment", cross_project=True)

        projects_found = {r.get("project") for r in results if r.get("project")}
        assert "frontend" in projects_found
        assert "backend" in projects_found
        assert "ops" in projects_found

    def test_normal_search_respects_project(self, multi_project_store):
        store, ids = multi_project_store
        engine = SearchEngine(store)
        results = engine.search("deployment", project="frontend")

        result_ids = [r["id"] for r in results]
        assert ids[0] in result_ids
        assert ids[1] not in result_ids  # backend only
        assert ids[3] not in result_ids  # ops only

    def test_cross_project_ignores_project_filter(self, multi_project_store):
        store, ids = multi_project_store
        engine = SearchEngine(store)
        # Even with project="frontend", cross_project=True should search everywhere
        results = engine.search("deployment", project="frontend", cross_project=True)

        result_ids = [r["id"] for r in results]
        assert ids[0] in result_ids
        assert ids[1] in result_ids
        assert ids[3] in result_ids

    def test_cross_project_with_type_filter(self, multi_project_store):
        store, ids = multi_project_store
        engine = SearchEngine(store)
        results = engine.search("deployment", cross_project=True, entry_type="process")

        result_ids = [r["id"] for r in results]
        # Only the process entry should match
        assert ids[3] in result_ids
        assert ids[0] not in result_ids
        assert ids[1] not in result_ids

    def test_cross_project_no_entries_without_project(self, palaia_root):
        """Entries without a project are still found in cross-project search."""
        store = Store(palaia_root)
        store.write("orphan entry about deployment", title="Orphan")
        store.write("project entry about deployment", project="proj1", title="Proj1")

        engine = SearchEngine(store)
        results = engine.search("deployment", cross_project=True)
        titles = [r["title"] for r in results]
        assert "Orphan" in titles
        assert "Proj1" in titles
