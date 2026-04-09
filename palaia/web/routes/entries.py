"""Entry CRUD routes.

v2.6+ semantics:
- Tasks are post-its: setting status=done/wontfix on a task deletes it.
- Source tags: 'webui' (created in browser), 'cli' (palaia add/write),
  'auto-capture' (passive capture). No source tag = agent (MCP/tool).
  Human-created entries (webui, cli) rank 30% higher in recall.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(tags=["entries"])


# Valid values (match palaia core enums — no drift)
VALID_TYPES = {"memory", "process", "task"}
VALID_SCOPES = {"private", "team", "public"}
VALID_STATUSES = {"open", "in-progress", "done", "wontfix"}
VALID_PRIORITIES = {"low", "medium", "high", "critical"}

# Task statuses that trigger deletion (post-it behavior)
TASK_TERMINAL_STATUSES = {"done", "wontfix"}


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


def _validate_enum(value: str | None, valid: set[str], field: str) -> str | None:
    if value is None:
        return None
    if value not in valid:
        raise ValueError(f"Invalid {field}: {value!r}. Allowed: {sorted(valid)}")
    return value


def _detect_source(tags: list[str]) -> str:
    """Detect entry source from tags: webui, cli, auto-capture, or agent."""
    if "webui" in tags:
        return "webui"
    if "cli" in tags:
        return "cli"
    if "auto-capture" in tags:
        return "auto"
    return "agent"


def _entry_to_dict(meta: dict, body: str, tier: str, *, preview: bool = True) -> dict:
    """Convert store entry to JSON-serializable dict with source flags."""
    tags = meta.get("tags", []) or []
    source = _detect_source(tags)
    return {
        "id": meta.get("id", ""),
        "title": meta.get("title", ""),
        "type": meta.get("type", "memory"),
        "scope": meta.get("scope", "team"),
        "tier": tier,
        "tags": tags,
        "project": meta.get("project"),
        "status": meta.get("status"),
        "priority": meta.get("priority"),
        "assignee": meta.get("assignee"),
        "due_date": meta.get("due_date"),
        "agent": meta.get("agent"),
        "created": meta.get("created", ""),
        "accessed": meta.get("accessed", ""),
        "access_count": meta.get("access_count", 0),
        "decay_score": meta.get("decay_score", 0),
        "source": source,
        "is_auto_capture": source == "auto",
        "is_manual": source in ("webui", "cli"),
        "body_preview": (body[:200] + "…") if preview and len(body) > 200 else body,
    }


@router.get("/entries")
def list_entries(
    request: Request,
    tier: str | None = Query(None, description="hot|warm|cold"),
    type: str | None = Query(None, description="memory|process|task"),
    scope: str | None = Query(None, description="private|team|public"),
    project: str | None = Query(None),
    status: str | None = Query(None),
    priority: str | None = Query(None),
    agent: str | None = Query(None, description="Filter by agent attribution"),
    tag: str | None = Query(None),
    source: str | None = Query(None, description="manual|auto"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """List entries with filters. v2.6 adds scope, agent, and source (manual/auto) filters."""
    from palaia.services.query import list_entries as svc_list

    root = request.app.state.palaia_root
    tag_filters = [tag] if tag else None

    try:
        _validate_enum(type, VALID_TYPES, "type")
        _validate_enum(scope, VALID_SCOPES, "scope")
        _validate_enum(status, VALID_STATUSES, "status")
        _validate_enum(priority, VALID_PRIORITIES, "priority")
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})

    result = svc_list(
        root,
        tier=tier,
        list_all=(tier is None),
        entry_type=type,
        project=project,
        status=status,
        priority=priority,
        scope=scope,
        tag_filters=tag_filters,
        agent_filter=agent,
        agent_names={agent} if agent else None,
    )

    entries = [_entry_to_dict(meta, body, t) for meta, body, t in result["entries_with_tier"]]

    # Filter by source (manual|auto) — post-query because it's a computed flag
    if source == "manual":
        entries = [e for e in entries if e["is_manual"]]
    elif source == "auto":
        entries = [e for e in entries if e["is_auto_capture"]]

    # Sort: manual entries get 1.3x boost to reflect recall ranking
    def _rank(e: dict) -> float:
        base = e.get("decay_score") or 0.0
        return base * (1.3 if e["is_manual"] else 1.0)

    entries.sort(key=_rank, reverse=True)

    total = len(entries)
    entries = entries[offset : offset + limit]

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
        return JSONResponse(status_code=404, content=result)

    # Augment with source flags
    meta = result.get("meta", {}) or {}
    tags = meta.get("tags", []) or []
    source = _detect_source(tags)
    result["source"] = source
    result["is_auto_capture"] = source == "auto"
    result["is_manual"] = source in ("webui", "cli")
    return result


@router.post("/entries", status_code=201)
def create_entry(request: Request, payload: EntryCreate) -> dict:
    """Create a new entry. Scope and type are validated server-side."""
    from palaia.store import Store

    try:
        _validate_enum(payload.type, VALID_TYPES, "type")
        _validate_enum(payload.scope, VALID_SCOPES, "scope")
        _validate_enum(payload.status, VALID_STATUSES, "status")
        _validate_enum(payload.priority, VALID_PRIORITIES, "priority")
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})

    # v2.6: creating a task in terminal state makes no sense
    if payload.type == "task" and payload.status in TASK_TERMINAL_STATUSES:
        return JSONResponse(
            status_code=422,
            content={"error": f"Cannot create task with status={payload.status!r} — tasks are post-its, use status=open"},
        )

    root = request.app.state.palaia_root
    store = Store(root)
    store.recover()

    # Tag entries created via WebUI so recall can distinguish source
    tags = list(payload.tags) if payload.tags else []
    if "webui" not in tags:
        tags.append("webui")

    try:
        entry_id = store.write(
            body=payload.body,
            title=payload.title,
            entry_type=payload.type,
            scope=payload.scope,
            tags=tags or None,
            project=payload.project,
            status=payload.status,
            priority=payload.priority,
            assignee=payload.assignee,
            due_date=payload.due_date,
        )
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})

    return {"id": entry_id, "status": "created"}


@router.patch("/entries/{entry_id}")
def patch_entry(request: Request, entry_id: str, payload: EntryPatch) -> dict:
    """Update fields on an entry (partial).

    v2.6: if current type is 'task' and new status is done/wontfix, the entry
    is deleted (post-it behavior). Response includes deleted=True.
    """
    from palaia.services.query import get_entry as svc_get
    from palaia.store import Store

    try:
        _validate_enum(payload.type, VALID_TYPES, "type")
        _validate_enum(payload.status, VALID_STATUSES, "status")
        _validate_enum(payload.priority, VALID_PRIORITIES, "priority")
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})

    root = request.app.state.palaia_root

    # Check if this patch triggers post-it deletion
    existing = svc_get(root, entry_id)
    if "error" in existing:
        return JSONResponse(status_code=404, content=existing)

    existing_meta = existing.get("meta", {}) or {}
    existing_type = existing_meta.get("type", "memory")
    new_type = payload.type or existing_type

    if new_type == "task" and payload.status in TASK_TERMINAL_STATUSES:
        # Post-it: delete instead of update
        store = Store(root)
        store.recover()
        try:
            store.delete(entry_id)
        except ValueError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})
        return {
            "id": entry_id,
            "status": "deleted",
            "deleted": True,
            "reason": f"task terminal status ({payload.status})",
        }

    # Normal update path
    kwargs: dict = {}
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

    store = Store(root)
    store.recover()

    try:
        meta = store.edit(entry_id, **kwargs)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    except PermissionError as exc:
        return JSONResponse(status_code=403, content={"error": str(exc)})

    return {
        "id": meta.get("id", entry_id),
        "status": "updated",
        "updated_fields": list(kwargs.keys()),
    }


@router.delete("/entries/{entry_id}")
def delete_entry(request: Request, entry_id: str) -> dict:
    """Delete an entry by ID. Returns 404 if the entry does not exist."""
    from palaia.store import Store

    root = request.app.state.palaia_root
    store = Store(root)
    store.recover()

    try:
        deleted = store.delete(entry_id)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})

    if not deleted:
        return JSONResponse(
            status_code=404,
            content={"error": f"Entry not found: {entry_id}"},
        )

    return {"id": entry_id, "status": "deleted"}
