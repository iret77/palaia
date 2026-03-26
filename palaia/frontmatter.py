"""Shared YAML frontmatter parsing and serialization.

Provides a minimal YAML-like parser and serializer used by both
``entry.py`` and ``memo.py``.  No external YAML dependency required.
"""

from __future__ import annotations

import re

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def parse_yaml_simple(text: str) -> dict:
    """Minimal YAML-like parser for frontmatter. No dependency needed.

    Handles: key: value, key: [a, b, c], quoted strings,
    booleans (true/false), null, integers, floats.
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
        # Booleans
        if value == "true":
            result[key] = True
            continue
        if value == "false":
            result[key] = False
            continue
        # Null
        if value == "null":
            result[key] = None
            continue
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
        elif (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            result[key] = value[1:-1]
        else:
            result[key] = value
    return result


def quote_yaml_value(value: str) -> str:
    """Quote a YAML value if it contains characters that could break parsing.

    Prevents frontmatter injection via values containing newlines, '---',
    or other YAML-special patterns.
    """
    if "\n" in value or "---" in value or value.startswith("[") or value.startswith("{"):
        # Double-quote and escape internal quotes/newlines
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    return value


def to_yaml_simple(data: dict) -> str:
    """Minimal dict -> YAML-like frontmatter string.

    Handles lists, booleans, None, ints, floats, and strings.
    Strings are quoted when they contain special characters.
    """
    lines = []
    for k, v in data.items():
        if v is None:
            lines.append(f"{k}: null")
        elif isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, list):
            items = ", ".join(quote_yaml_value(str(i)) for i in v)
            lines.append(f"{k}: [{items}]")
        elif isinstance(v, float):
            lines.append(f"{k}: {v}")
        elif isinstance(v, int):
            lines.append(f"{k}: {v}")
        else:
            lines.append(f"{k}: {quote_yaml_value(str(v))}")
    return "\n".join(lines)
