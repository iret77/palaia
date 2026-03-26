"""Memo service — inter-agent messaging business logic."""

from __future__ import annotations

from pathlib import Path

from palaia.memo import MemoManager


def memo_send(
    root: Path,
    *,
    to: str,
    message: str,
    from_agent: str | None = None,
    priority: str = "normal",
    ttl_hours: int = 72,
) -> dict:
    """Send a memo to an agent. Returns memo metadata dict."""
    mm = MemoManager(root)
    return mm.send(
        to=to,
        message=message,
        from_agent=from_agent,
        priority=priority,
        ttl_hours=ttl_hours,
    )


def memo_broadcast(
    root: Path,
    *,
    message: str,
    from_agent: str | None = None,
    priority: str = "normal",
    ttl_hours: int = 72,
) -> dict:
    """Broadcast a memo to all agents. Returns memo metadata dict."""
    mm = MemoManager(root)
    return mm.broadcast(
        message=message,
        from_agent=from_agent,
        priority=priority,
        ttl_hours=ttl_hours,
    )


def memo_inbox(
    root: Path,
    *,
    agent: str | None = None,
    include_read: bool = False,
    aliases: dict | None = None,
) -> list[tuple[dict, str]]:
    """Get inbox memos. Returns list of (meta, body) tuples."""
    mm = MemoManager(root)
    return mm.inbox(agent=agent, include_read=include_read, aliases=aliases or None)


def memo_ack(
    root: Path,
    *,
    memo_id: str | None = None,
    ack_all: bool = False,
    agent: str | None = None,
) -> dict:
    """Acknowledge memo(s). Returns result dict."""
    mm = MemoManager(root)
    if ack_all:
        count = mm.ack_all(agent=agent)
        return {"acked": count}
    if not memo_id:
        return {"error": "memo ID required (or use --all)"}
    ok = mm.ack(memo_id)
    return {"acked": ok, "id": memo_id}


def memo_gc(root: Path) -> dict:
    """Run memo garbage collection. Returns stats dict."""
    mm = MemoManager(root)
    return mm.gc()
