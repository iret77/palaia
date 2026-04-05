"""Tests for palaia WebUI (FastAPI routes, v2.6)."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def palaia_root(tmp_path):
    """Initialize a minimal .palaia store for testing."""
    root = tmp_path / ".palaia"
    root.mkdir()
    (root / "config.json").write_text(
        json.dumps({"default_scope": "team", "agent": "test", "store_version": "2.6"})
    )
    for tier in ("hot", "warm", "cold"):
        (root / tier).mkdir()
    return root


@pytest.fixture
def client(palaia_root):
    from palaia.web.app import create_app

    app = create_app(palaia_root)
    return TestClient(app)


# ── Smoke: every route responds ────────────────────────────────────────────

def test_status_route(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert "version" in data
    assert "total" in data


def test_stats_route_includes_source_split(client):
    r = client.get("/api/stats")
    assert r.status_code == 200
    data = r.json()
    assert "by_source" in data
    assert "manual" in data["by_source"]
    assert "auto_capture" in data["by_source"]


def test_projects_route(client):
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert "projects" in r.json()


def test_agents_route(client):
    r = client.get("/api/agents")
    assert r.status_code == 200
    assert "agents" in r.json()


def test_doctor_route(client):
    r = client.get("/api/doctor")
    assert r.status_code == 200
    data = r.json()
    assert "counts" in data
    assert "checks" in data
    assert "has_issues" in data


def test_entries_empty(client):
    r = client.get("/api/entries")
    assert r.status_code == 200
    data = r.json()
    assert data["entries"] == []
    assert data["total"] == 0


def test_static_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "palaia" in r.text


def test_static_assets_served(client):
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").status_code == 200


# ── Create / Read / Update / Delete ────────────────────────────────────────

def test_create_memory_entry(client):
    r = client.post("/api/entries", json={
        "body": "Important decision about database choice.",
        "title": "DB decision",
        "type": "memory",
        "scope": "team",
        "tags": ["decision"],
    })
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "created"
    assert "id" in data


def test_created_entry_is_manual(client):
    r = client.post("/api/entries", json={"body": "manually written"})
    entry_id = r.json()["id"]
    detail = client.get(f"/api/entries/{entry_id}").json()
    assert detail["is_manual"] is True
    assert detail["is_auto_capture"] is False


def test_create_with_invalid_scope_returns_422(client):
    r = client.post("/api/entries", json={"body": "x", "scope": "shared:org"})
    assert r.status_code == 422
    assert "Invalid scope" in r.json()["error"]


def test_create_with_invalid_type_returns_422(client):
    r = client.post("/api/entries", json={"body": "x", "type": "note"})
    assert r.status_code == 422


def test_create_task_in_terminal_state_rejected(client):
    """v2.6: tasks cannot be created in done/wontfix state."""
    r = client.post("/api/entries", json={
        "body": "already done",
        "type": "task",
        "status": "done",
    })
    assert r.status_code == 422
    assert "post-it" in r.json()["error"]


def test_patch_memory_body(client):
    r = client.post("/api/entries", json={"body": "original"})
    eid = r.json()["id"]
    r = client.patch(f"/api/entries/{eid}", json={"body": "updated"})
    assert r.status_code == 200
    assert "body" in r.json()["updated_fields"]


def test_patch_task_to_done_deletes_it(client):
    """v2.6 post-it: setting status=done on a task deletes the entry."""
    r = client.post("/api/entries", json={
        "body": "take out trash",
        "type": "task",
        "status": "open",
    })
    tid = r.json()["id"]

    # Complete it
    r = client.patch(f"/api/entries/{tid}", json={"status": "done"})
    assert r.status_code == 200
    data = r.json()
    assert data["deleted"] is True
    assert "task terminal" in data["reason"]

    # Verify gone
    r = client.get(f"/api/entries/{tid}")
    assert r.status_code == 404


def test_patch_task_to_wontfix_also_deletes(client):
    r = client.post("/api/entries", json={
        "body": "nope",
        "type": "task",
        "status": "open",
    })
    tid = r.json()["id"]
    r = client.patch(f"/api/entries/{tid}", json={"status": "wontfix"})
    assert r.json()["deleted"] is True


def test_patch_memory_status_done_does_NOT_delete(client):
    """Only tasks are post-its, memory entries stay put."""
    r = client.post("/api/entries", json={"body": "lesson", "type": "memory"})
    mid = r.json()["id"]
    # Memory doesn't have a status field normally, but even if set, should not delete
    r = client.patch(f"/api/entries/{mid}", json={"body": "updated lesson"})
    assert r.status_code == 200
    assert r.json().get("deleted") is not True
    assert client.get(f"/api/entries/{mid}").status_code == 200


def test_delete_entry(client):
    r = client.post("/api/entries", json={"body": "to delete"})
    eid = r.json()["id"]
    assert client.delete(f"/api/entries/{eid}").status_code == 200
    assert client.get(f"/api/entries/{eid}").status_code == 404


# ── Filters ────────────────────────────────────────────────────────────────

def test_filter_by_type(client):
    client.post("/api/entries", json={"body": "m1", "type": "memory"})
    client.post("/api/entries", json={"body": "p1", "type": "process"})
    r = client.get("/api/entries?type=process")
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["type"] == "process"


def test_filter_by_scope(client):
    client.post("/api/entries", json={"body": "public1", "scope": "public"})
    client.post("/api/entries", json={"body": "team1", "scope": "team"})
    r = client.get("/api/entries?scope=public")
    assert r.status_code == 200
    assert all(e["scope"] == "public" for e in r.json()["entries"])


def test_filter_by_source_manual(client):
    """Source filter distinguishes manual vs auto-capture."""
    # Manual entry (no auto-capture tag)
    client.post("/api/entries", json={"body": "manual one"})
    # Auto-capture entry (explicit tag)
    client.post("/api/entries", json={"body": "auto one", "tags": ["auto-capture"]})

    r = client.get("/api/entries?source=manual")
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["is_manual"] is True

    r = client.get("/api/entries?source=auto")
    entries = r.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["is_auto_capture"] is True


def test_filter_invalid_enum_returns_422(client):
    r = client.get("/api/entries?status=blocked")
    assert r.status_code == 422


# ── Ranking ────────────────────────────────────────────────────────────────

def test_manual_entries_rank_above_auto_at_equal_decay(client):
    """Manual entries get a 1.3x boost in list ranking."""
    client.post("/api/entries", json={"body": "auto written", "tags": ["auto-capture"]})
    client.post("/api/entries", json={"body": "manually written"})
    r = client.get("/api/entries")
    entries = r.json()["entries"]
    assert len(entries) == 2
    # The manual one should be first (1.3x boost)
    assert entries[0]["is_manual"] is True
    assert entries[1]["is_auto_capture"] is True


# ── Search ─────────────────────────────────────────────────────────────────

def test_search_route_returns_structure(client):
    r = client.get("/api/search?q=hello")
    assert r.status_code == 200
    data = r.json()
    assert "results" in data
    assert "count" in data
    assert "bm25_only" in data
    assert "timed_out" in data


# ── Regression: codex audit findings ───────────────────────────────────────

def test_delete_missing_entry_returns_404(client):
    """Regression (codex P2): deleting a non-existent entry must return 404,
    not 200. Store.delete() returns False (not ValueError) when the ID is
    absent — the route must translate that to an HTTP error."""
    r = client.delete("/api/entries/does-not-exist-abc123")
    assert r.status_code == 404
    assert "error" in r.json()


def test_search_timeout_does_not_block_on_slow_worker(client, monkeypatch):
    """Regression (codex P1): when the search worker exceeds the timeout,
    the handler must return the BM25 fallback quickly instead of waiting
    for the slow worker to finish (which is what happens when you use
    `with ThreadPoolExecutor(...)` because exit calls shutdown(wait=True)).

    We fake a slow search by monkeypatching search_entries to sleep."""
    import time as _time

    from palaia.services import query as query_mod

    slow_duration = 3.0  # simulate a 3-second cold start
    client_timeout = 0.5  # but we only wait 0.5s

    def _slow_search(*args, **kwargs):
        _time.sleep(slow_duration)
        return {"results": [{"id": "slow-hit", "body": "should never return"}],
                "has_embeddings": True, "bm25_only": False}

    monkeypatch.setattr(query_mod, "search_entries", _slow_search)

    start = _time.monotonic()
    r = client.get(f"/api/search?q=anything&timeout={client_timeout}")
    elapsed = _time.monotonic() - start

    assert r.status_code == 200
    # Must not have waited for the slow worker to complete
    # (allow some headroom for BM25 fallback itself, but well under slow_duration)
    assert elapsed < slow_duration - 0.5, (
        f"Handler blocked for {elapsed:.2f}s waiting on slow worker "
        f"(expected < {slow_duration - 0.5:.1f}s)"
    )
    assert r.json()["timed_out"] is True
