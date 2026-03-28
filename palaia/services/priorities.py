"""Service layer for injection priority management (#121)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from palaia.priorities import (
    block_entry,
    is_blocked,
    load_priorities,
    reset_priorities,
    resolve_priorities,
    set_priority_value,
    unblock_entry,
)


def show_priorities(
    root: Path,
    query: str | None = None,
    agent: str | None = None,
    project: str | None = None,
    limit: int = 10,
    include_cold: bool = False,
) -> dict:
    """Simulate what would be injected and return score breakdown.

    Returns a dict with resolved config, blocked entries, and ranked results
    including BM25, embedding, combined, and weighted scores.
    """
    from palaia.config import load_config
    from palaia.store import Store

    prio = load_priorities(root)
    resolved = resolve_priorities(prio, agent=agent, project=project)

    config = load_config(root)
    store = Store(root)

    results: list[dict] = []
    blocked_entries: list[dict] = []

    if query:
        from palaia.search import SearchEngine

        engine = SearchEngine(store, config)
        search_results = engine.search(
            query,
            top_k=limit * 2,  # Fetch extra to account for blocked entries
            include_cold=include_cold,
            agent=agent,
            project=project,
        )

        for r in search_results:
            entry_id = r.get("id", "")
            type_name = r.get("type", "memory")
            type_weight = resolved.recall_type_weight.get(type_name, 1.0)
            weighted_score = r.get("score", 0) * type_weight

            entry = {
                "id": entry_id,
                "title": r.get("title", "(untitled)"),
                "type": type_name,
                "scope": r.get("scope", "team"),
                "tier": r.get("tier", "hot"),
                "bm25_score": r.get("bm25_score", 0.0),
                "embed_score": r.get("embed_score", 0.0),
                "combined_score": r.get("score", 0.0),
                "type_weight": type_weight,
                "weighted_score": round(weighted_score, 4),
                "body_preview": r.get("body", "")[:100],
            }

            if is_blocked(entry_id, resolved.blocked):
                entry["blocked"] = True
                blocked_entries.append(entry)
            else:
                results.append(entry)

        # Sort by weighted score descending
        results.sort(key=lambda x: x["weighted_score"], reverse=True)
        results = results[:limit]

    # Track sources of resolved values
    sources = _trace_sources(prio, agent, project)

    return {
        "agent": agent,
        "project": project,
        "resolved": resolved.to_dict(),
        "sources": sources,
        "results": results,
        "blocked_entries": blocked_entries,
        "total_results": len(results),
        "total_blocked": len(blocked_entries),
    }


def block_entry_svc(
    root: Path, entry_id: str, *, agent: str | None = None, project: str | None = None
) -> dict:
    """Block an entry from injection."""
    block_entry(root, entry_id, agent=agent, project=project)
    level = "agent" if agent else ("project" if project else "global")
    return {"blocked": entry_id, "level": level, "scope": agent or project or "global"}


def unblock_entry_svc(
    root: Path, entry_id: str, *, agent: str | None = None, project: str | None = None
) -> dict:
    """Unblock an entry."""
    unblock_entry(root, entry_id, agent=agent, project=project)
    level = "agent" if agent else ("project" if project else "global")
    return {"unblocked": entry_id, "level": level, "scope": agent or project or "global"}


def set_priority_svc(
    root: Path, key: str, value: Any, *, agent: str | None = None, project: str | None = None
) -> dict:
    """Set a priority parameter."""
    prio = set_priority_value(root, key, value, agent=agent, project=project)
    level = "agent" if agent else ("project" if project else "global")
    resolved = resolve_priorities(prio, agent=agent, project=project)
    return {"key": key, "value": value, "level": level, "resolved": resolved.to_dict()}


def list_blocked_svc(
    root: Path, *, agent: str | None = None, project: str | None = None
) -> dict:
    """List all blocked entries for the given scope."""
    prio = load_priorities(root)
    resolved = resolve_priorities(prio, agent=agent, project=project)

    # Show where each blocked entry comes from
    global_blocked = set(prio.get("blocked", []))
    agent_blocked = set(prio.get("agents", {}).get(agent, {}).get("blocked", [])) if agent else set()
    _ = set(prio.get("projects", {}).get(project, {}).get("blocked", [])) if project else set()

    entries = []
    for bid in sorted(resolved.blocked):
        source = "global" if bid in global_blocked else ("agent" if bid in agent_blocked else "project")
        entries.append({"id": bid, "source": source})

    return {"blocked": entries, "total": len(entries)}


def reset_priorities_svc(
    root: Path, *, agent: str | None = None, project: str | None = None
) -> dict:
    """Reset priorities."""
    reset_priorities(root, agent=agent, project=project)
    level = "agent" if agent else ("project" if project else "all")
    return {"reset": level, "scope": agent or project or "all"}


def _trace_sources(prio: dict, agent: str | None, project: str | None) -> dict:
    """Trace where each resolved value comes from."""
    sources = {}
    agent_cfg = prio.get("agents", {}).get(agent, {}) if agent else {}
    proj_cfg = prio.get("projects", {}).get(project, {}) if project else {}

    for key in ("recallMinScore", "maxInjectedChars", "tier"):
        if key in proj_cfg:
            sources[key] = "project override"
        elif key in agent_cfg:
            sources[key] = "agent override"
        elif key in prio:
            sources[key] = "global override"
        else:
            sources[key] = "default"

    if "recallTypeWeight" in proj_cfg:
        sources["recallTypeWeight"] = "project override"
    elif "recallTypeWeight" in agent_cfg:
        sources["recallTypeWeight"] = "agent override"
    elif "recallTypeWeight" in prio:
        sources["recallTypeWeight"] = "global override"
    else:
        sources["recallTypeWeight"] = "default"

    return sources
