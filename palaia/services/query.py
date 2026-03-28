"""Query service — search, get, list orchestration."""

from __future__ import annotations

from pathlib import Path

from palaia.config import load_config
from palaia.search import SearchEngine
from palaia.store import Store


def _resolve_short_id(store: Store, short_id: str) -> str | None:
    """Resolve a short ID prefix to full UUID."""
    for tier in ("hot", "warm", "cold"):
        tier_dir = store.root / tier
        if not tier_dir.exists():
            continue
        for p in tier_dir.glob("*.md"):
            if p.stem.startswith(short_id):
                return p.stem
    return None


# ---------------------------------------------------------------------------
# search / query
# ---------------------------------------------------------------------------

def search_entries(
    root: Path,
    query: str,
    *,
    limit: int = 10,
    include_cold: bool = False,
    project: str | None = None,
    agent: str | None = None,
    entry_type: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    assignee: str | None = None,
    instance: str | None = None,
    before: str | None = None,
    after: str | None = None,
    cross_project: bool = False,
) -> dict:
    """Search memories.

    Returns dict with results list, has_embeddings flag, and bm25_only flag.

    When an embed-server is running, delegates the full search to it for speed.
    Falls back to direct SearchEngine if the server is unavailable.
    """
    # Fast path: delegate to embed-server (auto-start if needed)
    try:
        import logging as _log

        from palaia.embed_client import EmbedServerClient, auto_start_server, is_server_running, should_auto_start
        from palaia.embed_server import get_socket_path

        _config = load_config(root)
        if not is_server_running(root) and should_auto_start(_config):
            _log.getLogger(__name__).info("Auto-starting embed server...")
            auto_start_server(root)

        if is_server_running(root):
            with EmbedServerClient(get_socket_path(root)) as client:
                params = {"text": query, "top_k": limit, "include_cold": include_cold}
                if project:
                    params["project"] = project
                if agent:
                    params["agent"] = agent
                if entry_type:
                    params["type"] = entry_type
                if status:
                    params["status"] = status
                if priority:
                    params["priority"] = priority
                if assignee:
                    params["assignee"] = assignee
                if instance:
                    params["instance"] = instance
                if cross_project:
                    params["cross_project"] = True
                result = client.query(params, timeout=5.0)
                chain_cfg = _config.get("embedding_chain", [])
                bm25_only = not chain_cfg or chain_cfg == ["bm25"]
                return {
                    "results": result.get("results", []),
                    "has_embeddings": True,
                    "bm25_only": bm25_only,
                }
    except Exception as e:
        import logging as _log
        import traceback as _tb

        _log.getLogger(__name__).warning("Embed server delegation failed: %s\n%s", e, _tb.format_exc())
        # Fall through to direct search

    # Direct path: load model in-process
    store = Store(root)
    store.recover()

    engine = SearchEngine(store)
    results = engine.search(
        query,
        top_k=limit,
        include_cold=include_cold,
        project=project,
        agent=agent,
        entry_type=entry_type,
        status=status,
        priority=priority,
        assignee=assignee,
        instance=instance,
        before=before,
        after=after,
        cross_project=cross_project,
    )

    # Check BM25-only status
    config = load_config(root)
    chain_cfg = config.get("embedding_chain", [])
    bm25_only = not chain_cfg or chain_cfg == ["bm25"]

    return {
        "results": results,
        "has_embeddings": engine.has_embeddings,
        "bm25_only": bm25_only,
    }


def get_entry(
    root: Path,
    entry_path: str,
    *,
    agent: str | None = None,
    from_line: int | None = None,
    num_lines: int | None = None,
) -> dict:
    """Read a specific memory entry by ID or path.

    Returns dict with id, content, meta or error.
    """
    store = Store(root)
    store.recover()

    entry_id = entry_path
    if "/" in entry_id:
        entry_id = entry_id.split("/")[-1].replace(".md", "")

    if len(entry_id) < 36:
        resolved = _resolve_short_id(store, entry_id)
        if resolved:
            entry_id = resolved

    entry = store.read(entry_id, agent=agent)
    if entry is None:
        return {"error": "not_found", "id": entry_id}

    meta, body = entry

    # Determine tier
    tier = "unknown"
    for t in ("hot", "warm", "cold"):
        if (root / t / f"{entry_id}.md").exists():
            tier = t
            break

    # Handle slicing
    lines = body.split("\n")
    if from_line is not None:
        lines = lines[max(0, from_line - 1) :]
    if num_lines is not None:
        lines = lines[:num_lines]
    sliced_body = "\n".join(lines)

    return {
        "id": entry_id,
        "content": sliced_body,
        "meta": {
            "type": meta.get("type", "memory"),
            "scope": meta.get("scope", "team"),
            "tier": tier,
            "title": meta.get("title", ""),
            "tags": meta.get("tags", []),
            "agent": meta.get("agent", ""),
            "project": meta.get("project"),
            "status": meta.get("status"),
            "priority": meta.get("priority"),
            "assignee": meta.get("assignee"),
            "due_date": meta.get("due_date"),
            "created": meta.get("created", ""),
            "accessed": meta.get("accessed", ""),
            "access_count": meta.get("access_count", 0),
            "decay_score": meta.get("decay_score", 0),
        },
    }


def enrich_rag_results(root: Path, results: list[dict]) -> list[dict]:
    """Enrich search results with full body and source metadata for RAG output."""
    store = Store(root)
    enriched = []
    for r in results:
        entry = store.read(r["id"])
        if entry:
            meta, body = entry
            r["full_body"] = body
            r["source"] = meta.get("source", "")
            r["chunk_index"] = meta.get("chunk_index", 0) if isinstance(meta.get("chunk_index"), int) else 0
            r["chunk_total"] = meta.get("chunk_total", 0) if isinstance(meta.get("chunk_total"), int) else 0
        enriched.append(r)
    return enriched


def list_entries(
    root: Path,
    *,
    tier: str | None = None,
    list_all: bool = False,
    agent: str | None = None,
    project: str | None = None,
    tag_filters: list[str] | None = None,
    scope: str | None = None,
    agent_filter: str | None = None,
    entry_type: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    assignee: str | None = None,
    instance: str | None = None,
    before: str | None = None,
    after: str | None = None,
    cross_project: bool = False,
    agent_names: set[str] | None = None,
) -> dict:
    """List memories in a tier or across all tiers.

    Args:
        agent: Agent for scope enforcement (access control).
        agent_filter: Agent for explicit --agent filtering.
        agent_names: Pre-resolved set of agent names (from aliases) for agent_filter.

    Returns dict with tier label and entries list.
    """
    store = Store(root)
    store.recover()

    if list_all:
        raw_entries = store.all_entries(include_cold=True, agent=agent)
        entries_with_tier = [(meta, body, t) for meta, body, t in raw_entries]
        tier_label = "all tiers"
    else:
        use_tier = tier or "hot"
        raw = store.list_entries(use_tier, agent=agent)
        entries_with_tier = [(meta, body, use_tier) for meta, body in raw]
        tier_label = use_tier

    # Apply filters
    if project and not cross_project:
        entries_with_tier = [(m, b, t) for m, b, t in entries_with_tier if m.get("project") == project]
    if tag_filters:
        for tag in tag_filters:
            entries_with_tier = [(m, b, t) for m, b, t in entries_with_tier if tag in (m.get("tags") or [])]
    if scope:
        entries_with_tier = [(m, b, t) for m, b, t in entries_with_tier if m.get("scope") == scope]
    if agent_filter and agent_names:
        entries_with_tier = [(m, b, t) for m, b, t in entries_with_tier if m.get("agent") in agent_names]
    if entry_type:
        entries_with_tier = [(m, b, t) for m, b, t in entries_with_tier if m.get("type", "memory") == entry_type]
    if status:
        entries_with_tier = [(m, b, t) for m, b, t in entries_with_tier if m.get("status") == status]
    if priority:
        entries_with_tier = [(m, b, t) for m, b, t in entries_with_tier if m.get("priority") == priority]
    if assignee:
        entries_with_tier = [(m, b, t) for m, b, t in entries_with_tier if m.get("assignee") == assignee]
    if instance:
        entries_with_tier = [(m, b, t) for m, b, t in entries_with_tier if m.get("instance") == instance]

    # Temporal filters
    if before:
        entries_with_tier = [(m, b, t) for m, b, t in entries_with_tier if m.get("created", "") < before]
    if after:
        entries_with_tier = [(m, b, t) for m, b, t in entries_with_tier if m.get("created", "") > after]

    return {
        "tier": "all" if list_all else tier_label,
        "entries_with_tier": entries_with_tier,
    }
