"""Entry listing and detail API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(tags=["entries"])


@router.get("/entries")
def list_entries(
    request: Request,
    tier: str | None = Query(None, description="Filter by tier: hot, warm, cold"),
    type: str | None = Query(None, description="Filter by type: memory, process, task"),
    project: str | None = Query(None, description="Filter by project"),
    status: str | None = Query(None, description="Filter by task status"),
    priority: str | None = Query(None, description="Filter by priority"),
    tag: str | None = Query(None, description="Filter by tag"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """List entries with optional filters."""
    from palaia.services.query import list_entries as svc_list

    root = request.app.state.palaia_root
    tag_filters = [tag] if tag else None

    result = svc_list(
        root,
        tier=tier,
        list_all=(tier is None),
        entry_type=type,
        project=project,
        status=status,
        priority=priority,
        tag_filters=tag_filters,
    )

    entries = []
    for meta, body, entry_tier in result["entries_with_tier"]:
        entries.append({
            "id": meta.get("id", ""),
            "title": meta.get("title", ""),
            "type": meta.get("type", "memory"),
            "scope": meta.get("scope", "team"),
            "tier": entry_tier,
            "tags": meta.get("tags", []),
            "project": meta.get("project"),
            "status": meta.get("status"),
            "priority": meta.get("priority"),
            "assignee": meta.get("assignee"),
            "due_date": meta.get("due_date"),
            "created": meta.get("created", ""),
            "accessed": meta.get("accessed", ""),
            "access_count": meta.get("access_count", 0),
            "decay_score": meta.get("decay_score", 0),
            "body_preview": body[:200] + ("..." if len(body) > 200 else ""),
        })

    # Sort by decay_score descending
    entries.sort(key=lambda e: e.get("decay_score", 0), reverse=True)

    total = len(entries)
    entries = entries[offset:offset + limit]

    return {
        "entries": entries,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/entries/{entry_id}")
def get_entry(request: Request, entry_id: str) -> dict:
    """Get a single entry with full body."""
    from palaia.services.query import get_entry as svc_get

    root = request.app.state.palaia_root
    result = svc_get(root, entry_id)

    if "error" in result:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content=result)

    return result
