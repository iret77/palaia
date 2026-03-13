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

    # Build list of config candidates
    config_candidates = [
        Path.home() / ".openclaw" / "config.json",
        Path.home() / ".openclaw" / "config.yaml",
    ]

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


def run_doctor(palaia_root: Path | None = None) -> list[dict[str, Any]]:
    """Run all doctor checks. Returns list of check results."""
    results = [
        _check_palaia_init(palaia_root),
        _check_store_version(palaia_root),
        _check_embedding_chain(palaia_root),
        _check_entry_classes(palaia_root),
        _check_projects_usage(palaia_root),
        _check_deprecated_config(palaia_root),
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

    for r in results:
        if r.get("status") != "warn":
            continue

        # Fix: embedding chain has missing providers → re-detect and rebuild chain
        if r.get("name") == "embedding_chain" and r.get("fixable"):
            detected = detect_providers()
            detected_map = {p["name"]: p["available"] for p in detected}
            old_chain = config.get("embedding_chain", [])

            # Strategy: keep providers that are available, drop missing ones
            new_chain = [p for p in old_chain if p == "bm25" or detected_map.get(p, False)]

            # If chain is empty or only bm25, auto-detect available providers
            if not new_chain or new_chain == ["bm25"]:
                new_chain = []
                for p in detected:
                    if p["available"] and p["name"] not in ("voyage",):
                        new_chain.append(p["name"])
                new_chain.append("bm25")

            if "bm25" not in new_chain:
                new_chain.append("bm25")

            config["embedding_chain"] = new_chain
            save_config(palaia_root, config)
            actions.append(f"Updated embedding chain: {' → '.join(new_chain)}")

    return actions


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

    lines.append("\nTo check for updates: pip install --upgrade palaia")

    return "\n".join(lines)
