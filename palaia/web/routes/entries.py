"""Entry listing, detail, create, edit, and delete API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

router = APIRouter(tags=["entries"])


# --- Models ---

class EntryCreate(BaseModel):
    body: str
    title: str | None = None
    type: str = "memory"
    scope: str = "team"
    tags: list[str] = []
    project: str | None = None
    status: str | None = None
    priority: str | None = None
    assignee: str | None = None
    due_date: str | None = None


class EntryPatch(BaseModel):
    body: str | None = None
    title: str | None = None
    type: str | None = None
    tags: list[str] | None = None
    status: str | None = None
    priority: str | None = None
    assignee: str | None = None
    due_date: str | None = None


# --- Routes ---

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


@router.post("/entries", status_code=201)
def create_entry(request: Request, payload: EntryCreate) -> dict:
    """Create a new memory entry."""
    from palaia.store import Store

    root = request.app.state.palaia_root
    store = Store(root)
    store.recover()

    try:
        entry_id = store.write(
            body=payload.body,
        title=payload.title,
        entry_type=payload.type,
        scope=payload.scope,
        tags=payload.tags or None,
        project=payload.project,
        status=payload.status,
        priority=payload.priority,
        assignee=payload.assignee,
            due_date=payload.due_date,
        )
    except ValueError as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=422, content={"error": str(e)})

    return {"id": entry_id, "status": "created"}


@router.patch("/entries/{entry_id}")
def patch_entry(request: Request, entry_id: str, payload: EntryPatch) -> dict:
    """Update fields on an existing entry (partial update)."""
    from palaia.store import Store
    from fastapi.responses import JSONResponse

    root = request.app.state.palaia_root
    store = Store(root)
    store.recover()

    # Build kwargs from non-None fields
    kwargs = {}
    if payload.body is not None:
        kwargs["body"] = payload.body
    if payload.title is not None:
        kwargs["title"] = payload.title
    if payload.type is not None:
        kwargs["entry_type"] = payload.type
    if payload.tags is not None:
        kwargs["tags"] = payload.tags
    if payload.status is not None:
        kwargs["status"] = payload.status
    if payload.priority is not None:
        kwargs["priority"] = payload.priority
    if payload.assignee is not None:
        kwargs["assignee"] = payload.assignee
    if payload.due_date is not None:
        kwargs["due_date"] = payload.due_date

    if not kwargs:
        return JSONResponse(status_code=400, content={"error": "No fields to update"})

    try:
        meta = store.edit(entry_id, **kwargs)
    except ValueError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except PermissionError as e:
        return JSONResponse(status_code=403, content={"error": str(e)})

    return {
        "id": meta.get("id", entry_id),
        "status": "updated",
        "updated_fields": list(kwargs.keys()),
    }


@router.delete("/entries/{entry_id}")
def delete_entry(request: Request, entry_id: str) -> dict:
    """Delete an entry by ID."""
    from palaia.store import Store
    from fastapi.responses import JSONResponse

    root = request.app.state.palaia_root
    store = Store(root)
    store.recover()

    # Find the entry across tiers
    path = store._find_entry(entry_id)
    if path is None:
        return JSONResponse(status_code=404, content={"error": f"Entry not found: {entry_id}"})

    relative = str(path.relative_to(root))

    # WAL-backed delete
    from palaia.wal import WALEntry
    with store.lock:
        wal_entry = WALEntry(
            operation="delete",
            target=relative,
            payload_hash="",
            payload="",
        )
        store.wal.log(wal_entry)
        store.delete_raw(relative)
        store.wal.commit(wal_entry)

    # Clean up metadata index
    store.metadata_index.remove(entry_id)

    return {"id": entry_id, "status": "deleted"}
