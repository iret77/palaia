"""Scope-Tag parsing and enforcement (ADR-002).

Scopes: private, team, public.
Legacy shared:X scopes are treated as team for backward compatibility.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

VALID_SCOPES = {"private", "team", "public"}
# Legacy prefix — accepted but normalized to "team" on write.
_LEGACY_SHARED_PREFIX = "shared:"


def validate_scope(scope: str) -> bool:
    """Check if a scope string is valid."""
    if scope in VALID_SCOPES:
        return True
    # Accept legacy shared:X for backward compat (migration, old entries)
    if scope.startswith(_LEGACY_SHARED_PREFIX) and len(scope) > len(_LEGACY_SHARED_PREFIX):
        return True
    return False


def normalize_scope(scope: str | None, default: str = "team") -> str:
    """Normalize and validate a scope, returning default if None.

    Legacy shared:X scopes are silently normalized to 'team'.
    """
    if scope is None:
        return default
    scope = scope.strip().lower()
    if not validate_scope(scope):
        raise ValueError(f"Invalid scope: '{scope}'. Valid: private, team, public")
    # Normalize legacy shared:X → team
    if scope.startswith(_LEGACY_SHARED_PREFIX):
        logger.info("Normalizing legacy scope '%s' to 'team'", scope)
        return "team"
    return scope


def can_access(
    entry_scope: str,
    agent_name: str | None,
    entry_agent: str | None,
    projects: list[str] | None = None,
    agent_names: set[str] | None = None,
    scope_visibility: list[str] | None = None,
) -> bool:
    """Check if an agent can access an entry based on scope rules.

    Args:
        agent_names: Set of all agent names that should be treated as equivalent
                     (resolved via aliases). If provided, used for private scope
                     matching instead of exact agent_name comparison.
        scope_visibility: If set, only entries whose scope is in this list are
                          visible. This is a read-side filter for agent isolation
                          (Issue #145). When None, default visibility rules apply.
    """
    # Scope visibility filter: if set, entry scope must be in the allowed list.
    if scope_visibility is not None:
        scope_allowed = False
        for allowed in scope_visibility:
            if entry_scope == allowed:
                scope_allowed = True
                break
        if not scope_allowed:
            # Legacy: treat shared:X as team for visibility purposes
            if entry_scope.startswith(_LEGACY_SHARED_PREFIX) and "team" in scope_visibility:
                pass  # Allow access via team visibility
            else:
                return False

    # Normalize empty/missing scope to "team" — entries must never become
    # invisible just because scope was written as an empty string.
    if not entry_scope:
        entry_scope = "team"

    if entry_scope == "team":
        return True
    if entry_scope == "public":
        return True
    if entry_scope == "private":
        if agent_name is None:
            return False
        if agent_names:
            return entry_agent in agent_names
        return agent_name == entry_agent
    # Legacy shared:X entries are accessible like team entries
    if entry_scope.startswith(_LEGACY_SHARED_PREFIX):
        return True
    # Unknown scope: treat as team (safe default, never hide entries)
    return True


def is_exportable(scope: str) -> bool:
    """Only public memories can be exported."""
    return scope == "public"
