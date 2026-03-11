"""Scope-Tag parsing and enforcement (ADR-002)."""

from __future__ import annotations

VALID_SCOPES = {"private", "team", "public"}
SHARED_PREFIX = "shared:"


def validate_scope(scope: str) -> bool:
    """Check if a scope string is valid."""
    if scope in VALID_SCOPES:
        return True
    if scope.startswith(SHARED_PREFIX) and len(scope) > len(SHARED_PREFIX):
        return True
    return False


def normalize_scope(scope: str | None, default: str = "team") -> str:
    """Normalize and validate a scope, returning default if None."""
    if scope is None:
        return default
    scope = scope.strip().lower()
    if not validate_scope(scope):
        raise ValueError(
            f"Invalid scope: '{scope}'. "
            f"Valid: private, team, shared:<name>, public"
        )
    return scope


def can_access(entry_scope: str, agent_name: str | None, entry_agent: str | None, projects: list[str] | None = None) -> bool:
    """Check if an agent can access an entry based on scope rules."""
    if entry_scope == "team":
        return True
    if entry_scope == "public":
        return True
    if entry_scope == "private":
        return agent_name is not None and agent_name == entry_agent
    if entry_scope.startswith(SHARED_PREFIX):
        project = entry_scope[len(SHARED_PREFIX):]
        return projects is not None and project in projects
    return False


def is_exportable(scope: str) -> bool:
    """Only public memories can be exported."""
    return scope == "public"
