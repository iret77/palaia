"""Status, stats, projects, agents, and doctor routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request

router = APIRouter(tags=["status"])


@router.get("/status")
def get_status(request: Request) -> dict:
    """System overview: version, counts, tiers."""
    from palaia.services.status import collect_status

    root = request.app.state.palaia_root
    info = collect_status(root)
    return {
        "version": info.get("version", "unknown"),
        "entries": info.get("entries", {}),
        "total": info.get("total", 0),
        "total_chars": info.get("total_chars", 0),
        "disk_bytes": info.get("disk_bytes", 0),
        "project_count": info.get("project_count", 0),
        "type_counts": info.get("type_counts", {}),
        "task_status_counts": info.get("task_status_counts", {}),
        "wal_pending": info.get("wal_pending", 0),
        "last_write": info.get("last_write"),
    }


@router.get("/stats")
def get_stats(request: Request) -> dict:
    """Dashboard aggregates, including manual vs auto split."""
    from palaia.services.status import collect_status
    from palaia.store import Store

    root = request.app.state.palaia_root
    info = collect_status(root)

    # Manual vs auto-capture split (reads tier files directly via Store)
    store = Store(root)
    store.recover()
    manual = 0
    auto = 0
    for meta, _body, _tier in store.all_entries_unfiltered(include_cold=True):
        if "auto-capture" in (meta.get("tags") or []):
            auto += 1
        else:
            manual += 1

    return {
        "total_entries": info.get("total", 0),
        "by_tier": info.get("entries", {}),
        "by_type": info.get("type_counts", {}),
        "task_statuses": info.get("task_status_counts", {}),
        "total_chars": info.get("total_chars", 0),
        "disk_bytes": info.get("disk_bytes", 0),
        "projects": info.get("project_count", 0),
        "by_source": {"manual": manual, "auto_capture": auto},
    }


@router.get("/projects")
def list_projects(request: Request) -> dict:
    """List projects from projects.json."""
    root = request.app.state.palaia_root
    projects_file = root / "projects.json"
    projects: dict = {}
    if projects_file.exists():
        try:
            projects = json.loads(projects_file.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    return {"projects": projects}


@router.get("/agents")
def list_agents(request: Request) -> dict:
    """List distinct agent names found in entries."""
    from palaia.store import Store

    root = request.app.state.palaia_root
    store = Store(root)
    store.recover()
    agents: set[str] = set()
    for meta, _body, _tier in store.all_entries_unfiltered(include_cold=True):
        agent = meta.get("agent")
        if agent:
            agents.add(agent)
    return {"agents": sorted(agents)}


@router.get("/doctor")
def run_doctor(request: Request) -> dict:
    """Run palaia doctor and return results for the UI banner.

    Returns a summary (counts) and the full check list so the UI can show
    an actionable banner on warnings/errors without crowding the main view.
    """
    from palaia.doctor import run_doctor as _run_doctor

    root = request.app.state.palaia_root
    results = _run_doctor(root)

    counts = {"ok": 0, "info": 0, "warn": 0, "error": 0}
    for r in results:
        status = r.get("status", "ok")
        # Normalize 'warning' → 'warn' (one check uses the long form)
        if status == "warning":
            status = "warn"
        counts[status] = counts.get(status, 0) + 1

    return {
        "counts": counts,
        "has_issues": counts.get("warn", 0) + counts.get("error", 0) > 0,
        "checks": results,
    }
