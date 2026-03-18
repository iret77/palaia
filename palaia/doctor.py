"""Palaia doctor — diagnose local instance and detect legacy memory systems."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _check_palaia_init(palaia_root: Path | None) -> dict[str, Any]:
    """Check if .palaia/ exists and count entries."""
    if palaia_root is None:
        return {
            "name": "palaia_init",
            "label": "Palaia initialized",
            "status": "error",
            "message": ".palaia/ not found — run: palaia init",
        }

    total = 0
    for tier in ("hot", "warm", "cold"):
        tier_dir = palaia_root / tier
        if tier_dir.exists():
            total += len(list(tier_dir.glob("*.md")))

    return {
        "name": "palaia_init",
        "label": "Palaia initialized",
        "status": "ok",
        "message": f".palaia/ found, {total} entries",
        "details": {"path": str(palaia_root), "entries": total},
    }


def _check_agent_identity(palaia_root: Path | None) -> dict[str, Any]:
    """Check if agent identity is configured."""
    if palaia_root is None:
        return {
            "name": "agent_identity",
            "label": "Agent identity",
            "status": "error",
            "message": "Not initialized",
        }

    from palaia.config import load_config

    config = load_config(palaia_root)
    agent = config.get("agent")

    if not agent:
        # No agent at all — still functional with "default" but worth noting
        return {
            "name": "agent_identity",
            "label": "Agent identity",
            "status": "info",
            "message": 'No agent configured (using "default")',
            "fix": "Customize with: palaia init --agent YOUR_NAME",
        }

    if agent == "default":
        return {
            "name": "agent_identity",
            "label": "Agent identity",
            "status": "ok",
            "message": "Agent: default (use --agent NAME to customize)",
            "details": {"agent": agent},
        }

    return {
        "name": "agent_identity",
        "label": "Agent identity",
        "status": "ok",
        "message": f"Agent: {agent}",
        "details": {"agent": agent},
    }


def _check_multi_agent_static(palaia_root: Path | None) -> dict[str, Any]:
    """Check for static agent in multi-agent setups."""
    if palaia_root is None:
        return {
            "name": "multi_agent_static",
            "label": "Multi-agent setup",
            "status": "skip",
            "message": "Not initialized",
        }

    from palaia.config import load_config

    config = load_config(palaia_root)
    is_multi = config.get("multi_agent", False)
    static_agent = config.get("agent")

    if not is_multi:
        return {
            "name": "multi_agent_static",
            "label": "Multi-agent setup",
            "status": "ok",
            "message": "Single-agent or not detected",
        }

    if static_agent:
        return {
            "name": "multi_agent_static",
            "label": "Multi-agent setup",
            "status": "warn",
            "message": (
                f"Multi-agent setup detected but config.json has a static agent '{static_agent}'. "
                "This agent is used as fallback when PALAIA_AGENT is not set. "
                "In multi-agent setups, each agent should set PALAIA_AGENT explicitly."
            ),
            "fix": "Remove static agent: palaia config set agent '' — or ensure all agents set PALAIA_AGENT env var.",
        }

    return {
        "name": "multi_agent_static",
        "label": "Multi-agent setup",
        "status": "ok",
        "message": "Multi-agent setup, no static agent (correct)",
    }


def _check_embedding_chain(palaia_root: Path | None) -> dict[str, Any]:
    """Check configured embedding chain and verify providers are actually installed."""
    if palaia_root is None:
        return {
            "name": "embedding_chain",
            "label": "Embedding chain",
            "status": "error",
            "message": "Not initialized",
        }

    from palaia.config import load_config
    from palaia.embeddings import detect_providers

    config = load_config(palaia_root)
    chain = config.get("embedding_chain")
    provider = config.get("embedding_provider", "auto")

    if chain:
        chain_str = " → ".join(chain)
        has_local = any(p in chain for p in ("sentence-transformers", "fastembed", "ollama"))
        has_openai = "openai" in chain

        # Verify that non-bm25 providers in the chain are actually available
        detected = {p["name"]: p["available"] for p in detect_providers()}
        missing = [p for p in chain if p != "bm25" and not detected.get(p, False)]

        if missing:
            missing_str = ", ".join(missing)
            fix_hints = []
            for m in missing:
                if m == "sentence-transformers":
                    fix_hints.append('pip install "palaia[sentence-transformers]"')
                elif m == "fastembed":
                    fix_hints.append('pip install "palaia[fastembed]"')
                elif m == "ollama":
                    fix_hints.append("ollama serve && ollama pull nomic-embed-text")
                elif m == "openai":
                    fix_hints.append("Set OPENAI_API_KEY environment variable")
            return {
                "name": "embedding_chain",
                "label": "Embedding chain",
                "status": "warn",
                "message": f"{chain_str} — MISSING: {missing_str}",
                "fix": "Reinstall missing providers:\n  "
                + "\n  ".join(fix_hints)
                + "\nOr re-detect and update chain: palaia detect",
                "fixable": True,
                "details": {"chain": chain, "missing": missing},
            }

        if has_openai and not has_local:
            return {
                "name": "embedding_chain",
                "label": "Embedding chain",
                "status": "warn",
                "message": f"{chain_str} (no local fallback)",
                "fix": "pip install sentence-transformers && palaia warmup",
                "details": {"chain": chain},
            }
        return {
            "name": "embedding_chain",
            "label": "Embedding chain",
            "status": "ok",
            "message": chain_str,
            "details": {"chain": chain},
        }
    elif provider and provider != "auto":
        return {
            "name": "embedding_chain",
            "label": "Embedding chain",
            "status": "ok",
            "message": f"{provider} (single provider)",
            "details": {"provider": provider},
        }
    else:
        return {
            "name": "embedding_chain",
            "label": "Embedding chain",
            "status": "warn",
            "message": "No chain configured (using auto-detect)",
            "fix": "Run: palaia detect && palaia config set-chain <providers> bm25",
            "fixable": True,
        }


def _check_openclaw_plugin() -> dict[str, Any]:
    """Check which OpenClaw memory plugin is active."""
    import os as _os

    # Build list of config candidates — standard OpenClaw paths + VPS fallback (#51)
    from palaia.config import VPS_OPENCLAW_BASE

    _home = Path.home()
    _base_dirs = [_home / ".openclaw"]
    # Add VPS standard path as fallback when home dir differs
    if VPS_OPENCLAW_BASE != _home / ".openclaw" and VPS_OPENCLAW_BASE.is_dir():
        _base_dirs.append(VPS_OPENCLAW_BASE)

    config_candidates: list[Path] = []
    for base in _base_dirs:
        config_candidates.extend(
            [
                base / "openclaw.json",
                base / "openclaw.yaml",
                base / "openclaw.yml",
                base / "config.json",
                base / "config.yaml",
                base / "config.yml",
            ]
        )

    # Also check $OPENCLAW_CONFIG env var
    env_config = _os.environ.get("OPENCLAW_CONFIG")
    if env_config:
        env_path = Path(env_config)
        if env_path not in config_candidates:
            config_candidates.insert(0, env_path)

    for config_path in config_candidates:
        if not config_path.exists():
            continue

        try:
            if config_path.suffix == ".json":
                with open(config_path) as f:
                    oc_config = json.load(f)
            elif config_path.suffix in (".yaml", ".yml"):
                # Try yaml if available
                try:
                    import yaml  # type: ignore[import-untyped]

                    with open(config_path) as f:
                        oc_config = yaml.safe_load(f)
                except ImportError:
                    continue
            else:
                continue

            # Navigate to plugins.slots.memory
            plugins = oc_config.get("plugins", {})
            slots = plugins.get("slots", {})
            memory_plugin = slots.get("memory")

            if memory_plugin == "palaia":
                return {
                    "name": "openclaw_plugin",
                    "label": "OpenClaw plugin",
                    "status": "ok",
                    "message": "palaia is active",
                    "details": {"plugin": "palaia", "config_path": str(config_path)},
                }
            elif memory_plugin:
                return {
                    "name": "openclaw_plugin",
                    "label": "OpenClaw plugin",
                    "status": "warn",
                    "message": f"{memory_plugin} is active (not palaia)",
                    "fix": ('Set plugins.slots.memory = "palaia" in OpenClaw config\nThen restart OpenClaw.'),
                    "details": {"plugin": memory_plugin, "config_path": str(config_path)},
                }
            else:
                return {
                    "name": "openclaw_plugin",
                    "label": "OpenClaw plugin",
                    "status": "info",
                    "message": "No memory plugin configured",
                    "details": {"config_path": str(config_path)},
                }
        except (json.JSONDecodeError, OSError, KeyError):
            continue

    # Fallback: try running `openclaw status` to detect if OpenClaw is running
    try:
        import subprocess

        result = subprocess.run(
            ["openclaw", "status"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout:
            output = result.stdout.lower()
            if "memory" in output and "palaia" in output:
                return {
                    "name": "openclaw_plugin",
                    "label": "OpenClaw plugin",
                    "status": "ok",
                    "message": "palaia is active (detected via openclaw status)",
                    "details": {"source": "openclaw status"},
                }
            elif "memory" in output:
                return {
                    "name": "openclaw_plugin",
                    "label": "OpenClaw plugin",
                    "status": "info",
                    "message": "OpenClaw running (memory plugin status unclear)",
                    "details": {"source": "openclaw status"},
                }
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    return {
        "name": "openclaw_plugin",
        "label": "OpenClaw plugin",
        "status": "info",
        "message": "OpenClaw config not found (standalone mode)",
    }


def _check_smart_memory_skill() -> dict[str, Any]:
    """Check if smart-memory skill is still installed."""
    skill_path = Path.home() / ".openclaw" / "workspace" / "skills" / "smart-memory"

    if skill_path.exists() and skill_path.is_dir():
        return {
            "name": "smart_memory_skill",
            "label": "Smart-Memory skill",
            "status": "warn",
            "message": f"Detected: {skill_path}",
            "fix": (f"Remove or archive after Palaia is verified working:\n  rm -rf {skill_path}"),
            "details": {"path": str(skill_path)},
        }

    return {
        "name": "smart_memory_skill",
        "label": "Smart-Memory skill",
        "status": "ok",
        "message": "Not installed (clean)",
    }


def _check_legacy_memory_files() -> dict[str, Any]:
    """Check if legacy memory/*.md files are present in workspace."""
    workspace = Path.home() / ".openclaw" / "workspace"
    memory_dir = workspace / "memory"

    if not memory_dir.exists():
        return {
            "name": "legacy_memory_files",
            "label": "Legacy memory files",
            "status": "ok",
            "message": "No memory/ directory found",
        }

    md_files = list(memory_dir.rglob("*.md"))
    if not md_files:
        return {
            "name": "legacy_memory_files",
            "label": "Legacy memory files",
            "status": "ok",
            "message": "memory/ exists but no .md files",
        }

    return {
        "name": "legacy_memory_files",
        "label": "Legacy memory files",
        "status": "info",
        "message": f"{len(md_files)} .md files in memory/",
        "details": {"count": len(md_files), "path": str(memory_dir)},
    }


def _check_heartbeat_legacy(workspace: Path | None = None) -> dict[str, Any]:
    """Check if HEARTBEAT.md contains legacy memory patterns."""
    if workspace is None:
        workspace = Path.home() / ".openclaw" / "workspace"

    heartbeat_path = workspace / "HEARTBEAT.md"
    if not heartbeat_path.exists():
        return {
            "name": "heartbeat_legacy",
            "label": "HEARTBEAT.md legacy patterns",
            "status": "ok",
            "message": "No HEARTBEAT.md found",
        }

    try:
        content = heartbeat_path.read_text(encoding="utf-8")
    except OSError:
        return {
            "name": "heartbeat_legacy",
            "label": "HEARTBEAT.md legacy patterns",
            "status": "ok",
            "message": "Could not read HEARTBEAT.md",
        }

    patterns = [
        r"memory_search",
        r"memory_get",
        r"memory/",
        r"MEMORY\.md",
        r"active-context\.md",
        r"Read.*memory/",
        r"memory/agents/",
    ]

    found = []
    for pattern in patterns:
        if re.search(pattern, content):
            found.append(pattern)

    if found:
        return {
            "name": "heartbeat_legacy",
            "label": "HEARTBEAT.md legacy patterns",
            "status": "warn",
            "message": f"Found {len(found)} legacy pattern(s)",
            "fix": (
                "Replace legacy memory commands with Palaia equivalents:\n"
                '  memory_search/memory_get → palaia query "search term"\n'
                "  memory/*.md reads → palaia query / palaia write"
            ),
            "details": {"patterns_found": found},
        }

    return {
        "name": "heartbeat_legacy",
        "label": "HEARTBEAT.md legacy patterns",
        "status": "ok",
        "message": "No legacy patterns found",
    }


def _check_wal_health(palaia_root: Path | None) -> dict[str, Any]:
    """Check for unflushed WAL entries."""
    if palaia_root is None:
        return {
            "name": "wal_health",
            "label": "WAL health",
            "status": "error",
            "message": "Not initialized",
        }

    from palaia.wal import WAL

    wal = WAL(palaia_root)
    pending = wal.get_pending()

    if pending:
        return {
            "name": "wal_health",
            "label": "WAL health",
            "status": "warn",
            "message": f"{len(pending)} unflushed entries",
            "fix": "Run: palaia recover",
            "details": {"pending": len(pending)},
        }

    return {
        "name": "wal_health",
        "label": "WAL health",
        "status": "ok",
        "message": "Clean (no unflushed entries)",
    }


def _check_store_version(palaia_root: Path | None) -> dict[str, Any]:
    """Check if store version matches installed version."""
    if palaia_root is None:
        return {
            "name": "store_version",
            "label": "Store version",
            "status": "error",
            "message": "Not initialized",
        }

    from palaia import __version__
    from palaia.config import load_config, save_config

    config = load_config(palaia_root)
    store_ver = config.get("store_version", "")

    if not store_ver:
        # Legacy store without version tracking — stamp it now
        config["store_version"] = __version__
        save_config(palaia_root, config)
        return {
            "name": "store_version",
            "label": "Store version",
            "status": "info",
            "message": f"No store_version found — stamped as v{__version__}",
            "details": {"installed": __version__, "store": __version__},
        }

    if store_ver == __version__:
        return {
            "name": "store_version",
            "label": "Store version",
            "status": "ok",
            "message": f"v{__version__} (up to date)",
            "details": {"installed": __version__, "store": store_ver},
        }

    # Version mismatch — update store_version to current
    config["store_version"] = __version__
    save_config(palaia_root, config)
    return {
        "name": "store_version",
        "label": "Store version",
        "status": "info",
        "message": f"Upgraded store: v{store_ver} → v{__version__}",
        "details": {"installed": __version__, "store": store_ver},
    }


def _check_projects_usage(palaia_root: Path | None) -> dict[str, Any]:
    """Check if projects feature is being used."""
    if palaia_root is None:
        return {
            "name": "projects_usage",
            "label": "Projects",
            "status": "error",
            "message": "Not initialized",
        }

    projects_file = palaia_root / "projects.json"
    if not projects_file.exists():
        return {
            "name": "projects_usage",
            "label": "Projects",
            "status": "info",
            "message": "Not used yet — organize entries with: palaia project create <name>",
        }

    try:
        import json as _json

        data = _json.loads(projects_file.read_text())
        count = len(data) if isinstance(data, dict) else 0
        if count == 0:
            return {
                "name": "projects_usage",
                "label": "Projects",
                "status": "info",
                "message": "Empty — create projects with: palaia project create <name>",
            }
        return {
            "name": "projects_usage",
            "label": "Projects",
            "status": "ok",
            "message": f"{count} project(s) configured",
            "details": {"count": count},
        }
    except Exception:
        return {
            "name": "projects_usage",
            "label": "Projects",
            "status": "warn",
            "message": "projects.json exists but unreadable",
        }


def _check_deprecated_config(palaia_root: Path | None) -> dict[str, Any]:
    """Check for deprecated or missing config keys."""
    if palaia_root is None:
        return {
            "name": "deprecated_config",
            "label": "Config keys",
            "status": "error",
            "message": "Not initialized",
        }

    from palaia.config import load_config

    config = load_config(palaia_root)
    issues = []

    # Check for legacy embedding_provider without chain
    if config.get("embedding_provider") and config.get("embedding_provider") != "auto":
        if not config.get("embedding_chain"):
            issues.append(
                "embedding_provider is set but embedding_chain is not — "
                "run: palaia detect && palaia config set-chain <providers> bm25"
            )

    if issues:
        return {
            "name": "deprecated_config",
            "label": "Config keys",
            "status": "warn",
            "message": f"{len(issues)} issue(s)",
            "fix": "\n".join(issues),
            "details": {"issues": issues},
        }

    return {
        "name": "deprecated_config",
        "label": "Config keys",
        "status": "ok",
        "message": "All config keys current",
    }


def _check_entry_classes(palaia_root: Path | None) -> dict[str, Any]:
    """Check entry class adoption and suggest migration for untyped entries."""
    if palaia_root is None:
        return {
            "name": "entry_classes",
            "label": "Entry classes",
            "status": "error",
            "message": "Not initialized",
        }

    from palaia.entry import parse_entry

    total = 0
    untyped = 0
    type_counts: dict[str, int] = {}

    for tier in ("hot", "warm", "cold"):
        tier_dir = palaia_root / tier
        if not tier_dir.exists():
            continue
        for p in tier_dir.glob("*.md"):
            try:
                text = p.read_text(encoding="utf-8")
                meta, _ = parse_entry(text)
                total += 1
                et = meta.get("type")
                if et is None:
                    untyped += 1
                    et = "memory"
                type_counts[et] = type_counts.get(et, 0) + 1
            except Exception:
                continue

    if total == 0:
        return {
            "name": "entry_classes",
            "label": "Entry classes",
            "status": "info",
            "message": "No entries yet",
        }

    parts = [f"{v} {k}" for k, v in sorted(type_counts.items())]
    class_str = ", ".join(parts)

    if untyped > 0:
        return {
            "name": "entry_classes",
            "label": "Entry classes",
            "status": "info",
            "message": f"{class_str} ({untyped} untyped, default to memory)",
            "fix": "Run: palaia migrate --suggest  to get type recommendations",
            "details": {"total": total, "untyped": untyped, "types": type_counts},
        }

    return {
        "name": "entry_classes",
        "label": "Entry classes",
        "status": "ok",
        "message": class_str,
        "details": {"total": total, "types": type_counts},
    }


def _check_default_agent_alias(palaia_root: Path | None) -> dict[str, Any]:
    """Check if entries with agent='default' exist alongside named agents without an alias."""
    if palaia_root is None:
        return {
            "name": "default_agent_alias",
            "label": "Agent aliases",
            "status": "ok",
            "message": "Not initialized",
        }

    from palaia.config import load_config
    from palaia.entry import parse_entry

    config = load_config(palaia_root)
    aliases = config.get("aliases", {})

    # Scan all entries for agent names
    agents_seen: dict[str, int] = {}
    for tier in ("hot", "warm", "cold"):
        tier_dir = palaia_root / tier
        if not tier_dir.exists():
            continue
        for p in tier_dir.glob("*.md"):
            try:
                text = p.read_text(encoding="utf-8")
                meta, _ = parse_entry(text)
                agent = meta.get("agent", "")
                if agent:
                    agents_seen[agent] = agents_seen.get(agent, 0) + 1
            except Exception:
                continue

    default_count = agents_seen.get("default", 0)
    named_agents = {a for a in agents_seen if a != "default"}

    if default_count == 0 or not named_agents:
        return {
            "name": "default_agent_alias",
            "label": "Agent aliases",
            "status": "ok",
            "message": "No alias issues detected",
        }

    # Check if "default" has an alias set
    if "default" in aliases:
        target = aliases["default"]
        return {
            "name": "default_agent_alias",
            "label": "Agent aliases",
            "status": "ok",
            "message": f"default -> {target} ({default_count} entries aliased)",
        }

    # default entries exist + named agents exist + no alias
    return {
        "name": "default_agent_alias",
        "label": "Agent aliases",
        "status": "warn",
        "message": (
            f"You have {default_count} entries with agent='default' "
            f"but also named agents ({', '.join(sorted(named_agents))}). "
            f"These entries won't appear in agent-filtered queries."
        ),
        "fix": "Set an alias: palaia config set-alias default YOUR_NAME",
    }


def _check_version_available(palaia_root: Path | None) -> dict[str, Any]:
    """Check if a newer Palaia version is available on PyPI."""
    from palaia import __version__

    try:
        import urllib.request

        url = "https://pypi.org/pypi/palaia/json"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            import json as _json

            data = _json.loads(resp.read())
            latest = data.get("info", {}).get("version", "")

        if not latest:
            return {
                "name": "version_check",
                "label": "Version check",
                "status": "ok",
                "message": f"v{__version__} (could not determine latest)",
            }

        if latest == __version__:
            return {
                "name": "version_check",
                "label": "Version check",
                "status": "ok",
                "message": f"v{__version__} (latest)",
                "details": {"installed": __version__, "latest": latest},
            }

        # Compare versions
        from packaging.version import InvalidVersion, Version

        try:
            if Version(latest) > Version(__version__):
                return {
                    "name": "version_check",
                    "label": "Version check",
                    "status": "warn",
                    "message": f"Update available: v{__version__} -> v{latest}",
                    "fix": "Run: pip install --upgrade palaia && palaia doctor --fix",
                    "details": {"installed": __version__, "latest": latest},
                }
        except InvalidVersion:
            pass

        return {
            "name": "version_check",
            "label": "Version check",
            "status": "ok",
            "message": f"v{__version__} (latest: v{latest})",
            "details": {"installed": __version__, "latest": latest},
        }
    except Exception:
        # Network failure, timeout, etc. — don't block doctor
        return {
            "name": "version_check",
            "label": "Version check",
            "status": "ok",
            "message": f"v{__version__} (offline — could not check PyPI)",
        }


def _check_unread_memos(palaia_root: Path | None) -> dict[str, Any]:
    """Check for unread memos addressed to the current agent."""
    if palaia_root is None:
        return {
            "name": "unread_memos",
            "label": "Unread memos",
            "status": "ok",
            "message": "Not initialized",
        }

    try:
        from palaia.config import get_agent, get_aliases
        from palaia.memo import MemoManager

        agent = get_agent(palaia_root)
        if not agent:
            agent = "default"

        mm = MemoManager(palaia_root)
        try:
            aliases = get_aliases(palaia_root)
        except Exception:
            aliases = None

        unread = mm.inbox(agent=agent, include_read=False, aliases=aliases or None)
        count = len(unread)

        if count == 0:
            return {
                "name": "unread_memos",
                "label": "Unread memos",
                "status": "ok",
                "message": "No unread memos",
            }

        # Collect preview of unread memos for --fix display
        previews = []
        for meta, body in unread:
            sender = meta.get("from", "?")
            prio = " [high]" if meta.get("priority") == "high" else ""
            first_line = body.split("\n")[0][:60] if body else ""
            previews.append(f"From {sender}{prio}: {first_line}")

        return {
            "name": "unread_memos",
            "label": "Unread memos",
            "status": "warn",
            "message": f"{count} unread memo(s)",
            "fix": "Run: palaia memo inbox",
            "details": {"count": count, "previews": previews},
        }
    except Exception:
        return {
            "name": "unread_memos",
            "label": "Unread memos",
            "status": "ok",
            "message": "Could not check memos",
        }


def _check_plugin_defaults_upgrade(palaia_root: Path | None) -> dict[str, Any]:
    """Check if plugin defaults need upgrading from v1.x to v2.0."""
    if palaia_root is None:
        return {
            "name": "plugin_defaults_upgrade",
            "label": "Plugin defaults",
            "status": "ok",
            "message": "Not initialized",
        }

    from palaia.config import load_config

    config = load_config(palaia_root)
    plugin_config = config.get("plugin_config")

    # Only relevant if plugin_config exists (user ran init --capture-level or
    # had explicit settings). If no plugin_config at all, the TypeScript plugin
    # defaults apply (which are already v2.0 defaults after this release).
    if not plugin_config:
        return {
            "name": "plugin_defaults_upgrade",
            "label": "Plugin defaults",
            "status": "ok",
            "message": "Using plugin defaults (v2.0)",
        }

    # Detect v1.x default values that need upgrading.
    # Only suggest upgrade for values that match the OLD defaults exactly —
    # if the user set custom values, respect them.
    upgradeable: list[str] = []
    # autoCapture: false → true (only if user has the old default)
    if plugin_config.get("autoCapture") is False:
        upgradeable.append("autoCapture: false → true")
    # memoryInject: false → true (only if user has the old default)
    if plugin_config.get("memoryInject") is False:
        upgradeable.append("memoryInject: false → true")
    # maxInjectedChars: 4000 → 8000 (only if user has the old default)
    if plugin_config.get("maxInjectedChars") == 4000:
        upgradeable.append("maxInjectedChars: 4000 → 8000")
    # recallMode: list → query (only if user has the old default)
    if plugin_config.get("recallMode") == "list":
        upgradeable.append("recallMode: list → query")
    # showMemorySources: false → true (v2.0 transparency feature, default is true)
    if plugin_config.get("showMemorySources") is False:
        upgradeable.append("showMemorySources: false → true")
    # showCaptureConfirm: false → true (v2.0 transparency feature, default is true)
    if plugin_config.get("showCaptureConfirm") is False:
        upgradeable.append("showCaptureConfirm: false → true")
    # captureMinSignificance: old value > 0.5 → 0.3 (v2.0 default is 0.3 — more inclusive)
    min_sig = plugin_config.get("captureMinSignificance")
    if isinstance(min_sig, (int, float)) and min_sig > 0.5:
        upgradeable.append(f"captureMinSignificance: {min_sig} → 0.3")

    if not upgradeable:
        return {
            "name": "plugin_defaults_upgrade",
            "label": "Plugin defaults",
            "status": "ok",
            "message": "Plugin config is up to date",
        }

    changes_summary = ", ".join(upgradeable)
    return {
        "name": "plugin_defaults_upgrade",
        "label": "Plugin defaults",
        "status": "warn",
        "message": f"v1.x defaults detected: {changes_summary}",
        "fix": (
            "Palaia 2.0 has optimized defaults for zero-config UX.\n"
            f"  Run: palaia doctor --fix  to upgrade your config.\n"
            f"  Changes: {changes_summary}\n"
            "  Custom values you've set will NOT be touched."
        ),
        "fixable": True,
        "details": {"upgradeable": upgradeable},
    }


def _check_capture_level(palaia_root: Path | None) -> dict[str, Any]:
    """Check if capture-level is configured in an OpenClaw environment (Issue #67)."""
    if palaia_root is None:
        return {
            "name": "capture_level",
            "label": "Capture level",
            "status": "info",
            "message": "Not initialized",
        }

    from palaia.config import load_config

    config = load_config(palaia_root)
    plugin_config = config.get("plugin_config")

    # Only relevant in OpenClaw environments
    import os

    is_openclaw = (Path.home() / ".openclaw").is_dir() or bool(os.environ.get("OPENCLAW_HOME"))

    if not is_openclaw:
        return {
            "name": "capture_level",
            "label": "Capture level",
            "status": "ok",
            "message": "Not an OpenClaw environment (skipped)",
        }

    if plugin_config and "autoCapture" in plugin_config:
        auto = plugin_config.get("autoCapture", False)
        if auto:
            freq = plugin_config.get("captureFrequency", "significant")
            turns = plugin_config.get("captureMinTurns", 2)
            return {
                "name": "capture_level",
                "label": "Capture level",
                "status": "ok",
                "message": f"autoCapture=true, frequency={freq}, minTurns={turns}",
            }
        else:
            return {
                "name": "capture_level",
                "label": "Capture level",
                "status": "ok",
                "message": "autoCapture=off",
            }

    return {
        "name": "capture_level",
        "label": "Capture level",
        "status": "info",
        "message": "No capture level configured",
        "fix": "Set capture level with: palaia init --capture-level <off|sparsam|normal|aggressiv>\n"
        "  Recommended: palaia init --capture-level normal",
    }


def _check_capture_model() -> dict[str, Any]:
    """Check if captureModel is configured when autoCapture is active."""
    import os as _os

    from palaia.config import VPS_OPENCLAW_BASE

    _home = Path.home()
    _base_dirs = [_home / ".openclaw"]
    if VPS_OPENCLAW_BASE != _home / ".openclaw" and VPS_OPENCLAW_BASE.is_dir():
        _base_dirs.append(VPS_OPENCLAW_BASE)

    config_candidates: list[Path] = []
    for base in _base_dirs:
        config_candidates.extend(
            [
                base / "openclaw.json",
                base / "openclaw.yaml",
                base / "openclaw.yml",
                base / "config.json",
                base / "config.yaml",
                base / "config.yml",
            ]
        )

    env_config = _os.environ.get("OPENCLAW_CONFIG")
    if env_config:
        env_path = Path(env_config)
        if env_path not in config_candidates:
            config_candidates.insert(0, env_path)

    for config_path in config_candidates:
        if not config_path.exists():
            continue

        try:
            if config_path.suffix == ".json":
                with open(config_path) as f:
                    oc_config = json.load(f)
            elif config_path.suffix in (".yaml", ".yml"):
                try:
                    import yaml  # type: ignore[import-untyped]

                    with open(config_path) as f:
                        oc_config = yaml.safe_load(f)
                except ImportError:
                    continue
            else:
                continue

            # Check if palaia plugin is active
            plugins = oc_config.get("plugins", {})
            slots = plugins.get("slots", {})
            memory_plugin = slots.get("memory")

            if memory_plugin != "palaia":
                continue

            # Get palaia plugin config
            entries = plugins.get("entries", {})
            palaia_entry = entries.get("palaia", {})
            palaia_config = palaia_entry.get("config", {})

            # autoCapture defaults to true
            auto_capture = palaia_config.get("autoCapture", True)
            if not auto_capture:
                return {
                    "name": "capture_model",
                    "label": "Capture model",
                    "status": "ok",
                    "message": "autoCapture is off (captureModel not needed)",
                }

            capture_model = palaia_config.get("captureModel")
            if capture_model:
                # Validate that the provider has an auth profile configured
                provider_name = capture_model.split("/")[0] if "/" in capture_model else None
                if provider_name:
                    auth_profiles = oc_config.get("auth", {}).get("profiles", {})
                    # Check if any auth profile matches the provider
                    provider_has_auth = any(
                        provider_name.lower() in str(profile_key).lower()
                        or provider_name.lower() in str(profile_val).lower()
                        for profile_key, profile_val in (
                            auth_profiles.items() if isinstance(auth_profiles, dict) else []
                        )
                    )
                    # Also check for provider-specific env vars or top-level auth keys
                    provider_auth_keys = oc_config.get("auth", {})
                    has_provider_section = provider_name.lower() in str(provider_auth_keys).lower()

                    if not provider_has_auth and not has_provider_section:
                        return {
                            "name": "capture_model",
                            "label": "Capture model",
                            "status": "warn",
                            "message": (
                                f"captureModel provider '{provider_name}' has no auth profile "
                                "configured — capture may fail"
                            ),
                            "details": {
                                "captureModel": capture_model,
                                "provider": provider_name,
                            },
                        }

                return {
                    "name": "capture_model",
                    "label": "Capture model",
                    "status": "ok",
                    "message": f"captureModel: {capture_model}",
                }

            return {
                "name": "capture_model",
                "label": "Capture model",
                "status": "info",
                "message": (
                    "No captureModel set — using primary model. "
                    "Consider setting a cheaper model (e.g. claude-haiku-4-5) "
                    "in openclaw.json \u2192 plugins.entries.palaia.config.captureModel"
                ),
            }
        except (json.JSONDecodeError, OSError, KeyError):
            continue

    return {
        "name": "capture_model",
        "label": "Capture model",
        "status": "ok",
        "message": "OpenClaw/Palaia plugin not detected (skipped)",
    }


def run_doctor(palaia_root: Path | None = None) -> list[dict[str, Any]]:
    """Run all doctor checks. Returns list of check results."""
    results = [
        _check_palaia_init(palaia_root),
        _check_agent_identity(palaia_root),
        _check_multi_agent_static(palaia_root),
        _check_store_version(palaia_root),
        _check_version_available(palaia_root),
        _check_embedding_chain(palaia_root),
        _check_entry_classes(palaia_root),
        _check_projects_usage(palaia_root),
        _check_deprecated_config(palaia_root),
        _check_default_agent_alias(palaia_root),
        _check_unread_memos(palaia_root),
        _check_capture_level(palaia_root),
        _check_capture_model(),
        _check_plugin_defaults_upgrade(palaia_root),
        _check_openclaw_plugin(),
        _check_smart_memory_skill(),
        _check_legacy_memory_files(),
        _check_heartbeat_legacy(),
        _check_wal_health(palaia_root),
    ]
    return results


def apply_fixes(palaia_root: Path | None, results: list[dict[str, Any]]) -> list[str]:
    """Apply automatic fixes for fixable warnings. Returns list of actions taken."""
    actions: list[str] = []
    if palaia_root is None:
        return actions

    from palaia.config import load_config, save_config
    from palaia.embeddings import detect_providers

    config = load_config(palaia_root)
    ran_warmup = False

    for r in results:
        if r.get("status") != "warn":
            continue

        # Fix: embedding chain has missing providers
        if r.get("name") == "embedding_chain" and r.get("fixable"):
            missing = r.get("details", {}).get("missing", [])
            old_chain = config.get("embedding_chain", [])

            # Guard: respect explicit user embedding config (#57)
            # If embedding_provider is explicitly set (not "auto") and the
            # provider is still available, do NOT touch the chain or provider.
            explicit_provider = config.get("embedding_provider", "auto")
            if explicit_provider and explicit_provider != "auto":
                detected_guard = detect_providers()
                detected_guard_map = {p["name"]: p["available"] for p in detected_guard}
                if detected_guard_map.get(explicit_provider, False):
                    # Explicit provider is still functional — preserve config.
                    # Only remove broken providers from chain, keep the rest.
                    new_chain = [p for p in old_chain if p == "bm25" or detected_guard_map.get(p, False)]
                    if not new_chain or new_chain == ["bm25"]:
                        # At minimum, keep the explicit provider + bm25
                        new_chain = [explicit_provider, "bm25"]
                    elif "bm25" not in new_chain:
                        new_chain.append("bm25")

                    if new_chain != old_chain:
                        config["embedding_chain"] = new_chain
                        save_config(palaia_root, config)
                        chain_str = " → ".join(new_chain)
                        actions.append(f"Cleaned chain (kept explicit provider {explicit_provider}): {chain_str}")
                    else:
                        actions.append(f"Explicit provider {explicit_provider} is available — config unchanged")
                    # Still need warmup if semantic providers present
                    if any(p != "bm25" for p in new_chain):
                        ran_warmup = True
                    continue

            installed_providers: list[str] = []

            # Step 1: Try to install missing providers via pip
            for provider_name in missing:
                install_cmd = _pip_install_cmd(provider_name)
                if install_cmd:
                    print(f"  Attempting: {install_cmd}")
                    success = _try_pip_install(install_cmd)
                    if success:
                        installed_providers.append(provider_name)
                        actions.append(f"Installed {provider_name}")
                        print(f"  Installed {provider_name} successfully.")
                    else:
                        print(f"  Could not install {provider_name}.")

            # Step 2: Re-detect providers after installation attempts
            detected = detect_providers()
            detected_map = {p["name"]: p["available"] for p in detected}

            # Step 3: Build new chain — keep available providers from old chain
            # preserving original order (user's preference)
            new_chain = [p for p in old_chain if p == "bm25" or detected_map.get(p, False)]

            # If chain is empty or only bm25, build best available chain
            # _build_best_chain() only as last resort when NO valid chain exists
            if not new_chain or new_chain == ["bm25"]:
                new_chain = _build_best_chain(detected)

            if "bm25" not in new_chain:
                new_chain.append("bm25")

            config["embedding_chain"] = new_chain
            save_config(palaia_root, config)

            chain_str = " → ".join(new_chain)
            if installed_providers:
                actions.append(f"Chain: {chain_str}")
            else:
                still_missing = [p for p in missing if not detected_map.get(p, False)]
                if still_missing:
                    actions.append(f"{', '.join(still_missing)} not available, chain updated to {chain_str}")
                else:
                    actions.append(f"Updated embedding chain: {chain_str}")

            # Step 4: Run warmup to download models
            if any(p != "bm25" for p in new_chain):
                ran_warmup = True

        # Fix: no chain configured → auto-detect and set
        if r.get("name") == "embedding_chain" and r.get("fixable") and not r.get("details", {}).get("missing"):
            # Guard: if explicit provider is set and available, build chain around it
            explicit_provider = config.get("embedding_provider", "auto")
            detected = detect_providers()
            detected_map = {p["name"]: p["available"] for p in detected}

            if explicit_provider and explicit_provider != "auto" and detected_map.get(explicit_provider, False):
                new_chain = [explicit_provider, "bm25"]
            else:
                new_chain = _build_best_chain(detected)

            config["embedding_chain"] = new_chain
            save_config(palaia_root, config)
            actions.append(f"Auto-configured chain: {' → '.join(new_chain)}")
            if any(p != "bm25" for p in new_chain):
                ran_warmup = True

    # Fix: upgrade v1.x plugin defaults to v2.0
    for r in results:
        if r.get("name") == "plugin_defaults_upgrade" and r.get("fixable") and r.get("status") == "warn":
            plugin_config = config.get("plugin_config", {})
            upgraded = []

            # Only upgrade values that match old v1.x defaults exactly
            if plugin_config.get("autoCapture") is False:
                plugin_config["autoCapture"] = True
                upgraded.append("autoCapture: false → true")
            if plugin_config.get("memoryInject") is False:
                plugin_config["memoryInject"] = True
                upgraded.append("memoryInject: false → true")
            if plugin_config.get("maxInjectedChars") == 4000:
                plugin_config["maxInjectedChars"] = 8000
                upgraded.append("maxInjectedChars: 4000 → 8000")
            if plugin_config.get("recallMode") == "list":
                plugin_config["recallMode"] = "query"
                upgraded.append("recallMode: list → query")
            if plugin_config.get("showMemorySources") is False:
                plugin_config["showMemorySources"] = True
                upgraded.append("showMemorySources: false → true")
            if plugin_config.get("showCaptureConfirm") is False:
                plugin_config["showCaptureConfirm"] = True
                upgraded.append("showCaptureConfirm: false → true")
            min_sig = plugin_config.get("captureMinSignificance")
            if isinstance(min_sig, (int, float)) and min_sig > 0.5:
                plugin_config["captureMinSignificance"] = 0.3
                upgraded.append(f"captureMinSignificance: {min_sig} → 0.3")

            if upgraded:
                config["plugin_config"] = plugin_config
                save_config(palaia_root, config)
                actions.append(f"Upgraded plugin defaults to v2.0: {', '.join(upgraded)}")

    # Run warmup + reindex after all fixes if we have semantic providers
    if ran_warmup:
        try:
            from palaia.embeddings import warmup_providers

            print("  Running warmup to pre-download models...")
            warmup_results = warmup_providers(config)
            for wr in warmup_results:
                status_label = "ok" if wr["status"] == "ready" else wr["status"]
                print(f"    [{status_label}] {wr['name']}: {wr['message']}")
            actions.append("Warmup complete")

            # Reindex entries to fill embedding cache
            try:
                from palaia.cli import _reindex_entries

                class _FakeArgs:
                    json = False

                print("  Building embedding index...")
                index_stats = _reindex_entries(palaia_root, config, _FakeArgs())
                if index_stats.get("new", 0) > 0:
                    actions.append(
                        f"Indexed {index_stats['indexed']} entries "
                        f"({index_stats['new']} new, {index_stats['cached']} cached)"
                    )
            except Exception as e:
                actions.append(f"Reindex failed: {e}")
        except Exception as e:
            actions.append(f"Warmup failed: {e}")

    return actions


def _pip_install_cmd(provider_name: str) -> str | None:
    """Return the pip install command for a provider, or None if not pip-installable."""
    install_map = {
        "sentence-transformers": 'pip install "palaia[sentence-transformers]"',
        "fastembed": 'pip install "palaia[fastembed]"',
    }
    return install_map.get(provider_name)


def _try_pip_install(cmd: str) -> bool:
    """Try to run a pip install command. Returns True on success."""
    import subprocess
    import sys

    # Extract package spec from the command (e.g. 'pip install "palaia[st]"' -> 'palaia[st]')
    parts = cmd.split()
    if len(parts) < 3:
        return False
    # Use the current Python interpreter's pip to ensure correct environment
    pkg = parts[2].strip('"').strip("'")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg],
            capture_output=True,
            text=True,
            timeout=300,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _build_best_chain(detected: list[dict[str, Any]]) -> list[str]:
    """Build the best available embedding chain from detected providers.

    Prefers semantic providers. BM25-only is the last resort.
    Priority: openai > sentence-transformers > fastembed > ollama > bm25
    """
    chain: list[str] = []
    priority_order = ["openai", "sentence-transformers", "fastembed", "ollama"]
    detected_map = {p["name"]: p["available"] for p in detected}

    for name in priority_order:
        if detected_map.get(name, False):
            chain.append(name)

    chain.append("bm25")
    return chain


def format_doctor_report(results: list[dict[str, Any]], show_fix: bool = False) -> str:
    """Format doctor results as a human-readable report using box-drawing tables."""
    from palaia.ui import header, section, table_multi

    lines = [header()]
    lines.append(section("Health Report"))

    # Build table rows
    table_rows = []
    warnings = 0
    errors = 0

    for r in results:
        status = r["status"]
        label = r["label"]
        message = r["message"]
        status_str = f"[{status}]"
        table_rows.append((status_str, label, message))

        if status == "warn":
            warnings += 1
        elif status == "error":
            errors += 1

    lines.append(
        table_multi(
            headers=("Status", "Check", "Details"),
            rows=table_rows,
            min_widths=(8, 22, 30),
        )
    )

    # Show fix details below table if requested
    if show_fix:
        fix_lines = []
        for r in results:
            if r["status"] == "warn" and "fix" in r:
                fix_lines.append(f"\n  {r['label']}:")
                for fl in r["fix"].split("\n"):
                    fix_lines.append(f"    {fl}")
        if fix_lines:
            lines.append("\nFix guidance:")
            lines.extend(fix_lines)
    else:
        # Show inline fix hints for warnings
        for r in results:
            if r["status"] == "warn" and "fix" in r:
                first_fix = r["fix"].split("\n")[0]
                lines.append(f"  {r['label']}: {first_fix}")

    # Summary
    if errors:
        lines.append(f"\nErrors: {errors} — fix before using Palaia")
    elif warnings:
        suffix = " — see fixes above" if show_fix else " — run with --fix for guided cleanup"
        lines.append(f"\nAction required: {warnings} warning(s){suffix}")
    else:
        lines.append("\nAll clear. Palaia is healthy.")

    return "\n".join(lines)
