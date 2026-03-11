"""Memory entry parsing and creation (ADR-006)."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def _parse_yaml_simple(text: str) -> dict:
    """Minimal YAML-like parser for frontmatter. No dependency needed.

    
    Handles: key: value, key: [a, b, c], quoted strings.
    """
    result = {}
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        # Only split on the FIRST colon to preserve colons in values (URLs, timestamps, etc.)
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        # List
        if value.startswith("[") and value.endswith("]"):
            items = value[1:-1].split(",")
            result[key] = [i.strip().strip("'\"") for i in items if i.strip()]
        # Number (int)
        elif value.isdigit():
            result[key] = int(value)
        # Float
        elif re.match(r"^\d+\.\d+$", value):
            result[key] = float(value)
        # Quoted string
        elif (value.startswith('"') and value.endswith('"')) or \
             (value.startswith("'") and value.endswith("'")):
            result[key] = value[1:-1]
        else:
            result[key] = value
    return result


def _to_yaml_simple(data: dict) -> str:
    """Minimal dict → YAML-like frontmatter string."""
    lines = []
    for k, v in data.items():
        if isinstance(v, list):
            items = ", ".join(str(i) for i in v)
            lines.append(f"{k}: [{items}]")
        elif isinstance(v, float):
            lines.append(f"{k}: {v}")
        elif isinstance(v, int):
            lines.append(f"{k}: {v}")
        else:
            lines.append(f"{k}: {v}")
    return "\n".join(lines)


def content_hash(text: str) -> str:
    """SHA-256 hash of content body."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def create_entry(
    body: str,
    scope: str = "team",
    agent: str | None = None,
    tags: list[str] | None = None,
    title: str | None = None,
) -> str:
    """Create a full memory entry string with frontmatter."""
    now = datetime.now(timezone.utc).isoformat()
    meta = {
        "id": str(uuid.uuid4()),
        "scope": scope,
        "created": now,
        "accessed": now,
        "access_count": 1,
        "decay_score": 1.0,
        "content_hash": content_hash(body),
    }
    if agent:
        meta["agent"] = agent
    if tags:
        meta["tags"] = tags
    if title:
        meta["title"] = title
    
    fm = _to_yaml_simple(meta)
    return f"---\n{fm}\n---\n\n{body}\n"


def parse_entry(text: str) -> tuple[dict, str]:
    """Parse a memory entry into (metadata, body)."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text.strip()
    meta = _parse_yaml_simple(m.group(1))
    body = text[m.end():].strip()
    return meta, body


def update_access(meta: dict) -> dict:
    """Update access metadata (timestamp, count, score)."""
    from palaia.decay import decay_score, days_since
    
    meta["accessed"] = datetime.now(timezone.utc).isoformat()
    meta["access_count"] = meta.get("access_count", 0) + 1
    d = days_since(meta.get("created", meta["accessed"]))
    meta["decay_score"] = decay_score(0, meta["access_count"])
    return meta


def serialize_entry(meta: dict, body: str) -> str:
    """Serialize metadata and body back to entry format."""
    fm = _to_yaml_simple(meta)
    return f"---\n{fm}\n---\n\n{body}\n"
