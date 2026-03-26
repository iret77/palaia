"""Memory entry parsing and creation (ADR-006, ADR-012)."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid
from datetime import datetime, timezone

from palaia.enums import EntryStatus, EntryType, Priority
from palaia.frontmatter import FRONTMATTER_RE, parse_yaml_simple, quote_yaml_value, to_yaml_simple

logger = logging.getLogger(__name__)

# Backward-compat aliases (tests and ingest.py import the underscore-prefixed names)
_parse_yaml_simple = parse_yaml_simple
_to_yaml_simple = to_yaml_simple
_quote_yaml_value = quote_yaml_value

# Entry class types (ADR-012)
VALID_TYPES = {e.value for e in EntryType}
DEFAULT_TYPE = "memory"

# Task-specific structured fields (ADR-012)
VALID_STATUSES = {e.value for e in EntryStatus}
VALID_PRIORITIES = {e.value for e in Priority}


def extract_title_from_content(body: str, max_length: int = 80) -> str | None:
    """Extract a title from the first non-empty line of content.

    Strips markdown header prefixes (e.g. '# ', '## ').
    Truncates at ~max_length characters.
    Returns None if no usable title can be extracted.
    """
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        # Strip markdown header prefixes (e.g. '# Title', '## Section')
        title = re.sub(r"^#{1,6}\s*", "", stripped)
        title = title.strip()
        if not title:
            continue
        if len(title) > max_length:
            title = title[:max_length].rsplit(" ", 1)[0] + "..."
        return title
    return None


def content_hash(text: str) -> str:
    """SHA-256 hash of content body."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_entry_type(entry_type: str | None) -> str:
    """Validate and return entry type, defaulting to 'memory'."""
    if entry_type is None:
        return DEFAULT_TYPE
    entry_type = entry_type.strip().lower()
    if entry_type not in VALID_TYPES:
        raise ValueError(f"Invalid entry type: '{entry_type}'. Valid: {', '.join(sorted(VALID_TYPES))}")
    return entry_type


def validate_status(status: str | None) -> str | None:
    """Validate task status."""
    if status is None:
        return None
    status = status.strip().lower()
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: '{status}'. Valid: {', '.join(sorted(VALID_STATUSES))}")
    return status


def validate_priority(priority: str | None) -> str | None:
    """Validate task priority."""
    if priority is None:
        return None
    priority = priority.strip().lower()
    if priority not in VALID_PRIORITIES:
        raise ValueError(f"Invalid priority: '{priority}'. Valid: {', '.join(sorted(VALID_PRIORITIES))}")
    return priority


def _resolve_instance() -> str | None:
    """Resolve instance name from PALAIA_INSTANCE env var.

    Note: CLI layer resolves instance from config file (palaia instance set).
    This function is the low-level fallback for programmatic use.
    """
    return os.environ.get("PALAIA_INSTANCE") or None


def create_entry(
    body: str,
    scope: str = "team",
    agent: str | None = None,
    tags: list[str] | None = None,
    title: str | None = None,
    project: str | None = None,
    entry_type: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    assignee: str | None = None,
    due_date: str | None = None,
    instance: str | None = None,
) -> str:
    """Create a full memory entry string with frontmatter."""
    now = datetime.now(timezone.utc).isoformat()
    entry_type = validate_entry_type(entry_type)

    meta = {
        "id": str(uuid.uuid4()),
        "type": entry_type,
        "scope": scope,
        "created": now,
        "accessed": now,
        "access_count": 1,
        "decay_score": 1.0,
        "content_hash": content_hash(body),
    }
    if agent:
        meta["agent"] = agent
    # Session identity (ADR-012)
    resolved_instance = instance or _resolve_instance()
    if resolved_instance:
        meta["instance"] = resolved_instance
    if tags:
        meta["tags"] = tags
    # Auto-extract title from content if not explicitly provided
    effective_title = title if title else extract_title_from_content(body)
    if effective_title:
        meta["title"] = effective_title
    if project:
        meta["project"] = project

    # Task-specific fields (only for type: task)
    if entry_type == "task":
        meta["status"] = validate_status(status) or "open"
        if priority:
            meta["priority"] = validate_priority(priority)
        if assignee:
            meta["assignee"] = assignee
        if due_date:
            meta["due_date"] = due_date

    fm = _to_yaml_simple(meta)
    sanitized_body = _sanitize_body(body)
    return f"---\n{fm}\n---\n\n{sanitized_body}\n"


def _sanitize_body(body: str) -> str:
    """Prevent body content from being parsed as frontmatter.

    A body starting with '---' on its own line could inject metadata fields
    if not properly separated from the real frontmatter. We ensure the body
    cannot contain a pattern that mimics a frontmatter block at its start.
    """
    lines = body.split("\n")
    sanitized = []
    for line in lines:
        # Escape lines that consist of only dashes (3+) optionally with whitespace
        # These could be mistaken for frontmatter delimiters on re-parse
        if re.match(r"^---+\s*$", line):
            sanitized.append(f"\\{line}")
        else:
            sanitized.append(line)
    return "\n".join(sanitized)


def parse_entry(text: str) -> tuple[dict, str]:
    """Parse a memory entry into (metadata, body)."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text.strip()
    meta = _parse_yaml_simple(m.group(1))
    body = text[m.end() :].strip()
    return meta, body


def update_access(meta: dict) -> dict:
    """Update access metadata (timestamp, count, score)."""
    from palaia.decay import days_since, decay_score

    meta["accessed"] = datetime.now(timezone.utc).isoformat()
    meta["access_count"] = meta.get("access_count", 0) + 1
    d = days_since(meta.get("created", meta["accessed"]))
    meta["decay_score"] = decay_score(d, meta["access_count"])
    return meta


def serialize_entry(meta: dict, body: str) -> str:
    """Serialize metadata and body back to entry format."""
    fm = _to_yaml_simple(meta)
    return f"---\n{fm}\n---\n\n{body}\n"
