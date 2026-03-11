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


def _check_embedding_chain(palaia_root: Path | None) -> dict[str, Any]:
    """Check configured embedding chain."""
    if palaia_root is None:
        return {
            "name": "embedding_chain",
            "label": "Embedding chain",
            "status": "error",
            "message": "Not initialized",
        }

    from palaia.config import load_config

    config = load_config(palaia_root)
    chain = config.get("embedding_chain")
    provider = config.get("embedding_provider", "auto")

    if chain:
        chain_str = " → ".join(chain)
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
        }


def _check_openclaw_plugin() -> dict[str, Any]:
    """Check which OpenClaw memory plugin is active."""
    # Try reading OpenClaw config files
    config_candidates = [
        Path.home() / ".openclaw" / "config.json",
        Path.home() / ".openclaw" / "config.yaml",
    ]

    for config_path in config_candidates:
        if not config_path.exists():
            continue

        try:
            if config_path.suffix == ".json":
                with open(config_path) as f:
                    oc_config = json.load(f)
            elif config_path.suffix == ".yaml":
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
                    "fix": (
                        'Set plugins.slots.memory = "palaia" in OpenClaw config\n'
                        "Then restart OpenClaw."
                    ),
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
            "fix": (
                "Remove or archive after Palaia is verified working:\n"
                f"  rm -rf {skill_path}"
            ),
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
                '  memory/*.md reads → palaia query / palaia write'
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


def run_doctor(palaia_root: Path | None = None) -> list[dict[str, Any]]:
    """Run all doctor checks. Returns list of check results."""
    results = [
        _check_palaia_init(palaia_root),
        _check_embedding_chain(palaia_root),
        _check_openclaw_plugin(),
        _check_smart_memory_skill(),
        _check_legacy_memory_files(),
        _check_heartbeat_legacy(),
        _check_wal_health(palaia_root),
    ]
    return results


def format_doctor_report(results: list[dict[str, Any]], show_fix: bool = False) -> str:
    """Format doctor results as a human-readable report."""
    status_icons = {
        "ok": "✅",
        "warn": "⚠️ ",
        "error": "❌",
        "info": "ℹ️ ",
    }

    lines = [
        "palaia doctor",
        "─────────────────────────────────",
        "Palaia Health Report",
        "─────────────────────────────────",
    ]

    warnings = 0
    errors = 0

    for r in results:
        icon = status_icons.get(r["status"], "?")
        lines.append(f"{icon} {r['label']}: {r['message']}")

        if r["status"] == "warn":
            warnings += 1
            if show_fix and "fix" in r:
                for fix_line in r["fix"].split("\n"):
                    lines.append(f"    Fix: {fix_line}" if fix_line == r["fix"].split("\n")[0] else f"    {fix_line}")
            elif "fix" in r:
                lines.append(f"   → {r['fix'].split(chr(10))[0]}")
        elif r["status"] == "error":
            errors += 1

    lines.append("─────────────────────────────────")

    if errors:
        lines.append(f"Errors: {errors} — fix before using Palaia")
    elif warnings:
        lines.append(f"Action required: {warnings} warning(s)" + (" — see fixes above" if show_fix else " — run with --fix for guided cleanup"))
    else:
        lines.append("All clear! Palaia is healthy. 🎉")

    return "\n".join(lines)
