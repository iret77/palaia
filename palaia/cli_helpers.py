"""CLI helpers shared between cli.py and cli_commands.py."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from palaia.config import (
    find_palaia_root,
    get_aliases,
    get_instance,
    get_root,
    load_config,
    resolve_agent_with_aliases,
)


def json_out(data, args):
    """Print JSON if --json flag is set, return True if printed."""
    if getattr(args, "json", False):
        print(json.dumps(data, ensure_ascii=False))
        return True
    return False


def resolve_agent(args) -> str | None:
    """Resolve agent name: explicit --agent flag > config/env > detect > 'default'.

    In multi-agent mode, env var PALAIA_AGENT takes precedence over config
    to allow per-session identity. A warning is printed if multi-agent is
    detected but no agent identity is set.
    """
    explicit = getattr(args, "agent", None)
    if explicit:
        return explicit
    try:
        root = get_root()
        config = load_config(root)
        if config.get("multi_agent"):
            # Multi-agent: env var > config > detect > default
            resolved = (
                os.environ.get("PALAIA_AGENT")
                or config.get("agent")
                or detect_current_agent()
                or "default"
            )
            if resolved == "default":
                print("[palaia] WARNING: Multi-agent setup detected but no agent identity set.", file=sys.stderr)
                print("[palaia] Set PALAIA_AGENT env var or use --agent flag. Falling back to 'default'.", file=sys.stderr)
            return resolved
        else:
            # Single-agent: config > env var > detect > default
            config_agent = config.get("agent")
            if config_agent:
                return config_agent
    except FileNotFoundError:
        pass
    detected = detect_current_agent()
    return detected or "default"


def resolve_agent_names(agent: str | None) -> set[str] | None:
    """Resolve an agent name to all matching names via aliases."""
    if agent is None:
        return None
    try:
        root = get_root()
        aliases = get_aliases(root)
        if aliases:
            return resolve_agent_with_aliases(agent, aliases)
    except FileNotFoundError:
        pass
    return {agent}


def detect_current_agent() -> str | None:
    """Try to detect the current agent name from env or config."""
    agent = os.environ.get("PALAIA_AGENT")
    if agent:
        return agent
    agent_config = Path.home() / ".openclaw" / "config.json"
    if agent_config.exists():
        try:
            with open(agent_config, "r") as f:
                cfg = json.load(f)
            return cfg.get("agent_name")
        except (json.JSONDecodeError, OSError):
            pass
    return None


def resolve_instance_for_write(args) -> str | None:
    """Resolve instance: explicit --instance flag > config file > env var > None."""
    explicit = getattr(args, "instance", None)
    if explicit:
        return explicit
    try:
        root = get_root()
        return get_instance(root)
    except FileNotFoundError:
        pass
    return None


def check_version_nag():
    """Warn if installed palaia version is newer than store version."""
    try:
        from palaia import __version__

        root = find_palaia_root()
        if not root:
            return

        config_path = root / "config.json"
        if not config_path.exists():
            return

        config = json.loads(config_path.read_text())
        store_version = config.get("store_version", "")

        if not store_version:
            print("Warning: Palaia store has no version stamp. Run: palaia doctor --fix", file=sys.stderr)
            return

        if store_version != __version__:
            print(
                f"Warning: Palaia CLI is v{__version__} but store is v{store_version}. Run: palaia doctor --fix",
                file=sys.stderr,
            )
    except Exception:
        pass


def nudge_hint(hint_key: str, message: str, args) -> None:
    """Print an agent nudging hint if not in JSON mode and not recently shown."""
    if getattr(args, "json", False):
        return
    try:
        root = get_root()
        hints_file = root / ".hints_shown"
        shown = {}
        if hints_file.exists():
            import time

            shown = json.loads(hints_file.read_text())
            last_shown = shown.get(hint_key, 0)
            if time.time() - last_shown < 3600:
                return
        import time

        shown[hint_key] = time.time()
        hints_file.write_text(json.dumps(shown))
    except Exception:
        pass
    print(f"\nHint: {message}", file=sys.stderr)
