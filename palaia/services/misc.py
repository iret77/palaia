"""Misc services — lock/unlock, embed-server, skill business logic."""

from __future__ import annotations

from pathlib import Path


def lock_acquire(
    root: Path,
    *,
    project: str,
    agent: str,
    reason: str = "",
    ttl: int | None = None,
) -> dict:
    """Acquire a project lock. Returns lock data dict or error dict."""
    from palaia.locking import ProjectLockError, ProjectLockManager

    lm = ProjectLockManager(root)
    try:
        return lm.acquire(project, agent, reason, ttl)
    except ProjectLockError as e:
        return {"error": str(e), "locked": True}


def lock_status(root: Path, *, project: str | None = None) -> dict:
    """Check lock status. If project given, returns single lock or None.
    Otherwise returns all locks."""
    from palaia.locking import ProjectLockManager

    lm = ProjectLockManager(root)
    if project:
        info = lm.status(project)
        if info is None:
            return {"project": project, "locked": False}
        return info
    locks = lm.list_locks()
    return {"locks": locks}


def lock_renew(root: Path, *, project: str) -> dict:
    """Renew a project lock. Returns lock data or error dict."""
    from palaia.locking import ProjectLockError, ProjectLockManager

    lm = ProjectLockManager(root)
    try:
        return lm.renew(project)
    except ProjectLockError as e:
        return {"error": str(e)}


def lock_break(root: Path, *, project: str) -> dict:
    """Force-break a project lock. Returns result dict."""
    from palaia.locking import ProjectLockManager

    lm = ProjectLockManager(root)
    old = lm.break_lock(project)
    if old:
        return {"broken": True, "previous_lock": old}
    return {"broken": False, "project": project}


def lock_list(root: Path) -> dict:
    """List all active locks. Returns dict with 'locks' list."""
    from palaia.locking import ProjectLockManager

    lm = ProjectLockManager(root)
    return {"locks": lm.list_locks()}


def unlock_project(root: Path, *, project: str) -> dict:
    """Release a project lock. Returns result dict."""
    from palaia.locking import ProjectLockManager

    lm = ProjectLockManager(root)
    removed = lm.release(project)
    return {"unlocked": removed, "project": project}


def get_skill_content() -> dict:
    """Read and return SKILL.md content.

    Strips the install/update section (between ``<!-- begin:install -->``
    and ``<!-- end:install -->``) because ``palaia skill`` is only called
    when palaia is already installed — the install block wastes context window.
    ClawHub and GitHub still see the full file.

    Returns dict with 'skill' or 'error'.
    """
    import re

    skill_path = Path(__file__).parent.parent / "SKILL.md"
    if not skill_path.exists():
        return {
            "error": (
                "SKILL.md not found in this installation. "
                "View it online: https://github.com/byte5ai/palaia/blob/main/SKILL.md"
            )
        }
    content = skill_path.read_text(encoding="utf-8")
    # Strip install section — agent already has palaia installed
    content = re.sub(
        r"<!-- begin:install -->.*?<!-- end:install -->\n*",
        "",
        content,
        flags=re.DOTALL,
    )
    return {"skill": content}


def format_lock_human(lock_data: dict) -> str:
    """Format lock info for human-readable output."""
    from datetime import datetime

    agent = lock_data.get("agent", "unknown")
    acquired = lock_data.get("acquired", "?")
    reason = lock_data.get("reason", "")
    age = lock_data.get("age_seconds", 0)

    # Format age
    if age >= 3600:
        age_str = f"{age // 3600}h {(age % 3600) // 60}min ago"
    elif age >= 60:
        age_str = f"{age // 60}min ago"
    else:
        age_str = f"{age}s ago"

    # Format acquired time (show HH:MM)
    try:
        dt = datetime.fromisoformat(acquired)
        time_str = dt.strftime("%H:%M")
    except (ValueError, TypeError):
        time_str = acquired

    result = f"Locked by {agent} since {time_str} ({age_str})"
    if reason:
        result += f"\n   Reason: {reason}"
    return result
