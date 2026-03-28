"""Status and stats API routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["status"])


@router.get("/status")
def get_status(request: Request) -> dict:
    """System status overview."""
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
        "index_hint": info.get("index_hint"),
        "last_write": info.get("last_write"),
        "embedding_statuses": info.get("embedding_statuses", []),
    }


@router.get("/stats")
def get_stats(request: Request) -> dict:
    """Dashboard statistics."""
    from palaia.services.status import collect_status

    root = request.app.state.palaia_root
    info = collect_status(root)

    return {
        "total_entries": info.get("total", 0),
        "by_tier": info.get("entries", {}),
        "by_type": info.get("type_counts", {}),
        "task_statuses": info.get("task_status_counts", {}),
        "total_chars": info.get("total_chars", 0),
        "disk_bytes": info.get("disk_bytes", 0),
        "projects": info.get("project_count", 0),
    }


@router.get("/projects")
def list_projects(request: Request) -> dict:
    """List all projects."""
    import json

    root = request.app.state.palaia_root
    projects_file = root / "projects.json"

    projects = {}
    if projects_file.exists():
        try:
            projects = json.loads(projects_file.read_text())
        except Exception:
            pass

    return {"projects": projects}
