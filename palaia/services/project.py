"""Project service — project management business logic."""

from __future__ import annotations

from pathlib import Path

from palaia.project import ProjectManager
from palaia.search import SearchEngine
from palaia.store import Store


def project_create(
    root: Path,
    *,
    name: str,
    description: str = "",
    default_scope: str = "team",
    owner: str | None = None,
) -> dict:
    """Create a project. Returns project dict or error dict."""
    pm = ProjectManager(root)
    try:
        project = pm.create(
            name=name,
            description=description,
            default_scope=default_scope,
            owner=owner,
        )
    except ValueError as e:
        return {"error": str(e)}
    return {"project": project.to_dict()}


def project_list(root: Path, *, owner: str | None = None) -> dict:
    """List projects. Returns dict with 'projects' list."""
    pm = ProjectManager(root)
    projects = pm.list()
    if owner:
        projects = [p for p in projects if p.owner == owner]
    return {"projects": [p.to_dict() for p in projects]}


def project_show(root: Path, *, name: str) -> dict:
    """Show project details with entries and contributors."""
    pm = ProjectManager(root)
    store = Store(root)
    store.recover()

    project = pm.get(name)
    if not project:
        return {"error": f"Project '{name}' not found."}

    entries = pm.get_project_entries(name, store)
    contributors = pm.get_contributors(name, store)
    tier_counts: dict[str, int] = {}
    for _meta, _body, tier in entries:
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    return {
        "project": project.to_dict(),
        "contributors": contributors,
        "entries": [
            {
                "id": meta.get("id", "?"),
                "title": meta.get("title", "(untitled)"),
                "scope": meta.get("scope", "team"),
                "tier": tier,
                "preview": body[:80].replace("\n", " "),
            }
            for meta, body, tier in entries
        ],
        "entry_count": len(entries),
        "tier_counts": tier_counts,
    }


def project_write(
    root: Path,
    *,
    name: str,
    text: str,
    scope: str | None = None,
    agent: str | None = None,
    tags: list[str] | None = None,
    title: str | None = None,
) -> dict:
    """Write an entry to a project."""
    pm = ProjectManager(root)
    store = Store(root)
    store.recover()

    project = pm.get(name)
    if not project:
        return {"error": f"Project '{name}' not found."}

    entry_id = store.write(
        body=text,
        scope=scope,
        agent=agent,
        tags=tags,
        title=title,
        project=name,
    )
    return {"id": entry_id, "project": name}


def project_query(
    root: Path,
    *,
    name: str,
    query: str,
    limit: int = 10,
) -> dict:
    """Search within a project."""
    pm = ProjectManager(root)
    store = Store(root)
    store.recover()

    project = pm.get(name)
    if not project:
        return {"error": f"Project '{name}' not found."}

    engine = SearchEngine(store)
    results = engine.search(query, top_k=limit, project=name)
    return {"results": results, "project": name}


def project_set_scope(root: Path, *, name: str, scope_value: str) -> dict:
    """Change project default scope."""
    pm = ProjectManager(root)
    try:
        project = pm.set_scope(name, scope_value)
    except ValueError as e:
        return {"error": str(e)}
    return {"project": name, "default_scope": project.default_scope}


def project_set_owner(
    root: Path,
    *,
    name: str,
    owner_value: str | None = None,
    clear: bool = False,
) -> dict:
    """Set or clear project owner."""
    pm = ProjectManager(root)
    try:
        if clear:
            pm.clear_owner(name)
            return {"project": name, "owner": None}
        if not owner_value:
            return {"error": "owner name required (or use --clear)."}
        project = pm.set_owner(name, owner_value)
        return {"project": name, "owner": project.owner}
    except ValueError as e:
        return {"error": str(e)}


def project_delete(root: Path, *, name: str) -> dict:
    """Delete a project (entries preserved)."""
    pm = ProjectManager(root)
    store = Store(root)
    store.recover()

    if not pm.delete(name, store):
        return {"error": f"Project '{name}' not found."}
    return {"deleted": name}
