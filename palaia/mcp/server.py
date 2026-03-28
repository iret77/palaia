"""Palaia MCP Server — tool definitions and server setup."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def create_server(root: Path, read_only: bool = False, auth_token: str | None = None) -> FastMCP:
    """Create and configure the Palaia MCP server.

    Args:
        root: Path to .palaia directory.
        read_only: Disable write operations.
        auth_token: Bearer token for SSE authentication (None = no auth).
    """
    mcp = FastMCP(
        name="palaia",
        instructions=(
            "Palaia is a local, crash-safe memory system for AI agents. "
            "Use palaia_search to find relevant memories before answering questions. "
            "Use palaia_store to save important context, decisions, and learnings. "
            "Memories persist across sessions and are available to all connected agents."
        ),
    )

    # Store auth token for middleware use
    _auth_token = auth_token

    # Lazy-init store and search engine (avoid import cost at module level)
    _store = None
    _engine = None

    def _get_store():
        nonlocal _store
        if _store is None:
            from palaia.store import Store

            _store = Store(root)
            _store.recover()
        return _store

    def _get_engine():
        nonlocal _engine
        if _engine is None:
            from palaia.search import SearchEngine

            _engine = SearchEngine(_get_store())
        return _engine

    # ── Read tools (always available) ────────────────────────────

    @mcp.tool()
    def palaia_search(
        query: Annotated[str, "Search query text"],
        limit: Annotated[int, "Max results to return"] = 10,
        project: Annotated[str | None, "Filter by project name"] = None,
        entry_type: Annotated[str | None, "Filter by type: memory, process, task"] = None,
        status: Annotated[str | None, "Filter by status: open, in-progress, done, wontfix"] = None,
        priority: Annotated[str | None, "Filter by priority: critical, high, medium, low"] = None,
        assignee: Annotated[str | None, "Filter by assignee"] = None,
        include_cold: Annotated[bool, "Include archived entries"] = False,
        cross_project: Annotated[bool, "Search across all projects"] = False,
    ) -> str:
        """Search palaia memory using semantic and keyword search.

        Returns the most relevant memories matching your query. Use this to find
        context, past decisions, known issues, and learned patterns.
        """
        from palaia.services.query import search_entries

        result = search_entries(
            root,
            query,
            limit=limit,
            project=project,
            entry_type=entry_type,
            status=status,
            priority=priority,
            assignee=assignee,
            include_cold=include_cold,
            cross_project=cross_project,
        )

        entries = result.get("results", [])
        if not entries:
            return "No matching memories found."

        lines = []
        for r in entries:
            score = r.get("score", 0)
            title = r.get("title", "untitled")
            body = r.get("body", "")
            eid = r.get("id", "?")[:8]
            tier = r.get("tier", "?")
            etype = r.get("type", "memory")
            tags = ", ".join(r.get("tags", []))
            lines.append(
                f"[{eid}] ({etype}, {tier}, score={score:.2f}) {title}\n"
                f"  Tags: {tags}\n"
                f"  {body}"
            )

        header = f"Found {len(entries)} result(s)"
        if result.get("bm25_only"):
            header += " (keyword search only — no embedding provider)"
        return header + "\n\n" + "\n\n".join(lines)

    @mcp.tool()
    def palaia_read(
        entry_id: Annotated[str, "Entry ID (full UUID or short prefix)"],
    ) -> str:
        """Read a specific memory entry by ID. Returns the full content and metadata."""
        from palaia.services.query import get_entry

        result = get_entry(root, entry_id)

        if "error" in result:
            if result["error"] == "not_found":
                return f"Entry not found: {result.get('id', entry_id)}"
            return f"Error: {result['error']}"

        meta = result.get("meta", {})
        content = result.get("content", "")

        header_parts = [
            f"ID: {result['id']}",
            f"Title: {meta.get('title', 'untitled')}",
            f"Type: {meta.get('scope', 'team')}",
            f"Tier: {meta.get('tier', '?')}",
            f"Tags: {', '.join(meta.get('tags', []))}",
            f"Created: {meta.get('created', '?')}",
            f"Agent: {meta.get('agent', '?')}",
        ]

        return "\n".join(header_parts) + "\n\n" + content

    @mcp.tool()
    def palaia_list(
        tier: Annotated[str | None, "Tier to list: hot, warm, cold, or all"] = None,
        entry_type: Annotated[str | None, "Filter by type: memory, process, task"] = None,
        project: Annotated[str | None, "Filter by project name"] = None,
        status: Annotated[str | None, "Filter by status"] = None,
        limit: Annotated[int, "Max entries to return"] = 50,
    ) -> str:
        """List memory entries. Shows a summary of entries in the specified tier."""
        from palaia.services.query import list_entries

        list_all = tier == "all"
        result = list_entries(
            root,
            tier=tier if not list_all else None,
            list_all=list_all,
            entry_type=entry_type,
            project=project if project else None,
            status=status,
        )

        entries = result.get("entries_with_tier", [])
        if not entries:
            return f"No entries in {result.get('tier', 'hot')} tier."

        entries = entries[:limit]
        lines = []
        for meta, body, t in entries:
            eid = meta.get("id", "?")[:8]
            title = meta.get("title", "untitled")
            etype = meta.get("type", "memory")
            tags = ", ".join(meta.get("tags", []))
            created = meta.get("created", "?")[:10]
            lines.append(f"[{eid}] ({etype}, {t}) {title} [{created}] tags:{tags}")

        return f"{len(entries)} entries in {result.get('tier', 'hot')}:\n\n" + "\n".join(lines)

    @mcp.tool()
    def palaia_status() -> str:
        """Show palaia store status: entry counts, tiers, embedding provider info."""
        store = _get_store()
        status = store.status()

        lines = [
            f"Entries: hot={status.get('hot', 0)}, warm={status.get('warm', 0)}, cold={status.get('cold', 0)}",
            f"Total chars: {status.get('total_chars', 0):,}",
            f"WAL pending: {status.get('wal_pending', 0)}",
        ]

        config = status.get("config", {})
        chain = config.get("embedding_chain", [])
        if chain:
            lines.append(f"Embedding chain: {', '.join(chain)}")
        provider = config.get("embedding_provider", "auto")
        lines.append(f"Embedding provider: {provider}")

        # Embed-server status
        from palaia.embed_client import is_server_running

        if is_server_running(root):
            lines.append("Embed server: running")
        else:
            lines.append("Embed server: not running")

        return "\n".join(lines)

    # ── Write tools (disabled in read-only mode) ─────────────────

    if not read_only:

        @mcp.tool()
        def palaia_store(
            content: Annotated[str, "Memory content to store"],
            title: Annotated[str | None, "Short title for the entry"] = None,
            tags: Annotated[list[str] | None, "Tags for categorization"] = None,
            entry_type: Annotated[str | None, "Type: memory (default), process, task"] = None,
            scope: Annotated[str | None, "Scope: team (default), private, public"] = None,
            project: Annotated[str | None, "Project name"] = None,
            agent: Annotated[str | None, "Agent name (auto-detected if not set)"] = None,
            status: Annotated[str | None, "Task status: open, in-progress, done"] = None,
            priority: Annotated[str | None, "Task priority: critical, high, medium, low"] = None,
        ) -> str:
            """Store a new memory entry. Use this to save context, decisions, patterns,
            or any knowledge that should persist across sessions."""
            store = _get_store()
            entry_id = store.write(
                body=content,
                title=title,
                tags=tags,
                entry_type=entry_type,
                scope=scope,
                project=project,
                agent=agent,
                status=status,
                priority=priority,
            )
            return f"Stored entry {entry_id[:8]} ({entry_type or 'memory'})"

        @mcp.tool()
        def palaia_edit(
            entry_id: Annotated[str, "Entry ID to edit (full UUID or short prefix)"],
            content: Annotated[str | None, "New content (replaces existing)"] = None,
            title: Annotated[str | None, "New title"] = None,
            tags: Annotated[list[str] | None, "New tags (replaces existing)"] = None,
            status: Annotated[str | None, "New status"] = None,
            priority: Annotated[str | None, "New priority"] = None,
            assignee: Annotated[str | None, "New assignee"] = None,
        ) -> str:
            """Edit an existing memory entry. Only provided fields are updated."""
            store = _get_store()
            try:
                store.edit(
                    entry_id=entry_id,
                    body=content,
                    title=title,
                    tags=tags,
                    status=status,
                    priority=priority,
                    assignee=assignee,
                )
                return f"Updated entry {entry_id[:8]}"
            except (FileNotFoundError, ValueError):
                return f"Entry not found: {entry_id}"
            except PermissionError as e:
                return f"Permission denied: {e}"

        @mcp.tool()
        def palaia_gc(
            dry_run: Annotated[bool, "Preview without making changes"] = True,
        ) -> str:
            """Run garbage collection — rotate entries between tiers based on decay scores."""
            store = _get_store()
            result = store.gc(dry_run=dry_run, budget=True)

            moves = result.get("moves", [])
            pruned = result.get("pruned", 0)

            if not moves and not pruned:
                return "GC: nothing to do — all entries are in their correct tier."

            lines = []
            if dry_run:
                lines.append("GC dry run (no changes made):")
            else:
                lines.append("GC completed:")

            for move in moves:
                lines.append(
                    f"  {move.get('id', '?')[:8]}: {move.get('from', '?')} -> {move.get('to', '?')} "
                    f"(score={move.get('score', 0):.2f})"
                )

            if pruned:
                lines.append(f"  Pruned: {pruned} entries")

            return "\n".join(lines)

    return mcp
