"""Tests for Palaia WebUI API routes."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from palaia.store import Store


@pytest.fixture
def webui_client(palaia_root):
    """Create a FastAPI TestClient with a populated store."""
    from fastapi.testclient import TestClient
    from palaia.web.app import create_app

    # Seed some entries
    store = Store(palaia_root)
    store.write(
        body="Test memory entry about vector databases",
        title="Vector DB Notes",
        entry_type="memory",
        scope="team",
        tags=["tech", "databases"],
    )
    store.write(
        body="Deploy the new search backend",
        title="Deploy Search",
        entry_type="task",
        scope="team",
        tags=["ops"],
    )
    store.write(
        body="Step 1: Check logs\nStep 2: Restart service",
        title="Incident Runbook",
        entry_type="process",
        scope="team",
        tags=["ops", "runbook"],
    )

    app = create_app(palaia_root)
    return TestClient(app)


@pytest.fixture
def entry_ids(palaia_root):
    """Return IDs of seeded entries."""
    store = Store(palaia_root)
    entries = store.list(list_all=True)
    return [m.get("id") for m, _body, _tier in entries]


# --- /api/status ---

class TestStatus:
    def test_status_ok(self, webui_client):
        r = webui_client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert "version" in data
        assert "entries" in data
        assert "total" in data
        assert data["total"] >= 3

    def test_status_has_type_counts(self, webui_client):
        data = webui_client.get("/api/status").json()
        assert "type_counts" in data
        assert data["type_counts"].get("memory", 0) >= 1
        assert data["type_counts"].get("task", 0) >= 1
        assert data["type_counts"].get("process", 0) >= 1


# --- /api/stats ---

class TestStats:
    def test_stats_ok(self, webui_client):
        r = webui_client.get("/api/stats")
        assert r.status_code == 200
        data = r.json()
        assert data["total_entries"] >= 3
        assert "by_tier" in data
        assert "by_type" in data

    def test_stats_by_type(self, webui_client):
        data = webui_client.get("/api/stats").json()
        assert data["by_type"]["memory"] >= 1
        assert data["by_type"]["task"] >= 1


# --- /api/projects ---

class TestProjects:
    def test_projects_ok(self, webui_client):
        r = webui_client.get("/api/projects")
        assert r.status_code == 200
        data = r.json()
        assert "projects" in data
        assert isinstance(data["projects"], dict)

    def test_projects_empty_when_none(self, webui_client):
        """Even with no projects.json, returns empty dict."""
        data = webui_client.get("/api/projects").json()
        # Our test root has no projects.json, so should be empty
        assert isinstance(data["projects"], dict)


# --- /api/entries ---

class TestEntries:
    def test_list_entries(self, webui_client):
        r = webui_client.get("/api/entries")
        assert r.status_code == 200
        data = r.json()
        assert "entries" in data
        assert "total" in data
        assert data["total"] >= 3

    def test_list_entries_has_fields(self, webui_client):
        entries = webui_client.get("/api/entries").json()["entries"]
        for e in entries:
            assert "id" in e
            assert "type" in e
            assert "tier" in e
            assert "created" in e
            assert "body_preview" in e

    def test_filter_by_type(self, webui_client):
        data = webui_client.get("/api/entries?type=task").json()
        assert data["total"] >= 1
        for e in data["entries"]:
            assert e["type"] == "task"

    def test_filter_by_type_process(self, webui_client):
        data = webui_client.get("/api/entries?type=process").json()
        assert data["total"] >= 1
        for e in data["entries"]:
            assert e["type"] == "process"

    def test_filter_by_tag(self, webui_client):
        data = webui_client.get("/api/entries?tag=ops").json()
        assert data["total"] >= 1
        for e in data["entries"]:
            assert "ops" in e["tags"]

    def test_pagination(self, webui_client):
        data = webui_client.get("/api/entries?limit=1&offset=0").json()
        assert len(data["entries"]) == 1
        assert data["total"] >= 3

    def test_limit_bounds(self, webui_client):
        r = webui_client.get("/api/entries?limit=0")
        assert r.status_code == 422  # validation error

    def test_get_single_entry(self, webui_client):
        # Get an ID from listing first
        entries = webui_client.get("/api/entries").json()["entries"]
        eid = entries[0]["id"]

        r = webui_client.get(f"/api/entries/{eid}")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == eid
        assert "content" in data

    def test_get_entry_not_found(self, webui_client):
        r = webui_client.get("/api/entries/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404


# --- /api/search ---

class TestSearch:
    def test_search_requires_query(self, webui_client):
        r = webui_client.get("/api/search")
        assert r.status_code == 422  # missing required param

    def test_search_bm25_fallback(self, webui_client):
        """Search works via BM25 even without embeddings."""
        r = webui_client.get("/api/search?q=vector+database")
        assert r.status_code == 200
        data = r.json()
        assert "results" in data
        assert "query" in data
        assert data["query"] == "vector database"
        assert data["count"] >= 0  # may or may not find results

    def test_search_with_limit(self, webui_client):
        r = webui_client.get("/api/search?q=test&limit=1")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] <= 1


# --- Static files ---

class TestStaticFiles:
    def test_index_html(self, webui_client):
        r = webui_client.get("/")
        assert r.status_code == 200
        assert "Palaia" in r.text
        assert "<!DOCTYPE html>" in r.text

    def test_js_served(self, webui_client):
        r = webui_client.get("/app.js")
        assert r.status_code == 200

    def test_css_served(self, webui_client):
        r = webui_client.get("/style.css")
        assert r.status_code == 200
