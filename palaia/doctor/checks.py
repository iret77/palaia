"""palaia doctor checks — all _check_* diagnostic functions."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _check_palaia_init(palaia_root: Path | None) -> dict[str, Any]:
    """Check if .palaia/ exists and count entries."""
    if palaia_root is None:
        return {
            "name": "palaia_init",
            "label": "palaia initialized",
            "status": "error",
            "message": ".palaia/ not found — run: palaia init",
        }

    total = 0
    for tier in ("hot", "warm", "cold"):
        tier_dir = palaia_root / tier
        if tier_dir.exists():
            try:
                total += len(list(tier_dir.glob("*.md")))
            except (PermissionError, OSError) as e:
                return {
                    "name": "palaia_init",
                    "label": "palaia initialized",
                    "status": "warn",
                    "message": f".palaia/ found but {tier}/ not readable: {e}",
                    "details": {"path": str(palaia_root), "error": str(e)},
                }

    return {
        "name": "palaia_init",
        "label": "palaia initialized",
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
                    "fix": "openclaw plugins install @byte5ai/palaia",
                    "details": {"plugin": memory_plugin, "config_path": str(config_path)},
                }
            else:
                return {
                    "name": "openclaw_plugin",
                    "label": "OpenClaw plugin",
                    "status": "warn",
                    "message": "No memory plugin registered (palaia not active)",
                    "fix": "openclaw plugins install @byte5ai/palaia",
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
            "fix": (f"Remove or archive after palaia is verified working:\n  rm -rf {skill_path}"),
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

    # OpenClaw system files that MUST stay in memory/ (spawn injection, agent
    # profiles, project context).  These are not palaia-migratable.
    # Pattern: agents/*.md, systems/*.md → all system
    #          projects/*/CONTEXT.md → system, other project files → migratable
    #          active-context.md, CONTEXT.md (root) → system
    SYSTEM_ONLY_DIRS = {"agents", "systems"}
    SYSTEM_ROOT_FILES = {"CONTEXT.md", "active-context.md"}

    def _is_system_file(f: Path) -> bool:
        rel = f.relative_to(memory_dir)
        parts = rel.parts
        # Root-level system files
        if len(parts) == 1 and parts[0] in SYSTEM_ROOT_FILES:
            return True
        # All files under agents/ and systems/ are system files
        if parts[0] in SYSTEM_ONLY_DIRS:
            return True
        # Only CONTEXT.md under projects/*/ is system
        if parts[0] == "projects" and f.name == "CONTEXT.md":
            return True
        return False

    all_md = list(memory_dir.rglob("*.md"))
    migratable = [f for f in all_md if not _is_system_file(f)]
    system_count = len(all_md) - len(migratable)

    if not all_md:
        return {
            "name": "legacy_memory_files",
            "label": "Legacy memory files",
            "status": "ok",
            "message": "memory/ exists but no .md files",
        }

    if not migratable:
        return {
            "name": "legacy_memory_files",
            "label": "Legacy memory files",
            "status": "ok",
            "message": f"{system_count} OpenClaw system files in memory/ (expected)",
        }

    return {
        "name": "legacy_memory_files",
        "label": "Legacy memory files",
        "status": "info",
        "message": (
            f"{len(migratable)} .md files in memory/ — "
            "run `palaia migrate memory/` if not yet imported"
            + (f" ({system_count} system files excluded)" if system_count else "")
        ),
        "details": {
            "migratable": len(migratable),
            "system": system_count,
            "path": str(memory_dir),
        },
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
                "Replace legacy memory commands with palaia equivalents:\n"
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


LOOP_ARTIFACT_PATTERNS = [
    re.compile(r"## Active Memory \(palaia\)"),
    re.compile(r"\[t/(m|pr|tk)\]"),
    re.compile(r"\[palaia\] auto-capture=on"),
    re.compile(r"(?:^|\s)\*{4,}", re.MULTILINE),  # accumulated markdown (not inside words)
]

# Enhanced heuristics for #113: detect feedback-loop corrupted entries
_CORRUPTED_PREFIX_RE = re.compile(r"^\[t/")
_CORRUPTED_TAG_RE = re.compile(r"\[t/(?:tk|m|pr)\]")
_CORRUPTED_AUTO_CAPTURE_RE = re.compile(r"\[palaia\] auto-capture=on")
_CORRUPTED_NUDGE_RE = re.compile(r"Manual write: --type process")


def _is_loop_artifact(meta: dict, body: str) -> bool:
    """Check if an entry is a feedback-loop artifact (re-captured recall context).

    Uses two detection strategies:
    1. Legacy: requires at least 2 pattern matches from LOOP_ARTIFACT_PATTERNS
    2. Enhanced (#113): entry must have 'auto-capture' tag AND match any of:
       - Body starts with [t/ prefix
       - Body contains 3+ occurrences of [t/tk], [t/m], or [t/pr]
       - Body contains literal '[palaia] auto-capture=on'
       - Body contains 'Manual write: --type process' (nudge text)
    """
    text = f"{meta.get('title', '')}\n{body}"

    # Legacy detection (2+ pattern matches)
    legacy_matches = sum(1 for p in LOOP_ARTIFACT_PATTERNS if p.search(text))
    if legacy_matches >= 2:
        return True

    # Enhanced #113 detection: requires auto-capture tag
    raw_tags = meta.get("tags", [])
    tags = raw_tags if isinstance(raw_tags, list) else str(raw_tags).split(",")
    tags = [t.strip() for t in tags]
    if "auto-capture" not in tags:
        return False

    # Check enhanced heuristics (any single match is sufficient with auto-capture tag)
    if _CORRUPTED_PREFIX_RE.search(body):
        return True
    if len(_CORRUPTED_TAG_RE.findall(body)) >= 3:
        return True
    if _CORRUPTED_AUTO_CAPTURE_RE.search(body):
        return True
    if _CORRUPTED_NUDGE_RE.search(body):
        return True

    return False


def _check_loop_artifacts(palaia_root: Path | None) -> dict[str, Any]:
    """Check for feedback-loop artifacts (re-captured recall context)."""
    if palaia_root is None:
        return {
            "name": "loop_artifacts",
            "label": "Feedback-loop artifacts",
            "status": "error",
            "message": "Not initialized",
        }

    from palaia.entry import parse_entry

    artifact_ids: list[str] = []

    for tier in ("hot", "warm", "cold"):
        tier_dir = palaia_root / tier
        if not tier_dir.exists():
            continue
        try:
            files = list(tier_dir.glob("*.md"))
        except (PermissionError, OSError):
            continue
        for p in files:
            try:
                text = p.read_text(encoding="utf-8")
                meta, body = parse_entry(text)
                # Skip already-cleaned entries (idempotent)
                if meta.get("status") == "done":
                    continue
                if _is_loop_artifact(meta, body):
                    artifact_ids.append(p.stem)
            except Exception:
                continue

    if not artifact_ids:
        return {
            "name": "loop_artifacts",
            "label": "Feedback-loop artifacts",
            "status": "ok",
            "message": "No feedback-loop artifacts detected",
        }

    return {
        "name": "loop_artifacts",
        "label": "Corrupted Entries",
        "status": "warn",
        "fixable": True,
        "message": f"Found {len(artifact_ids)} feedback-loop artifacts. Run doctor --fix to clean up.",
        "fix": "Run: palaia doctor --fix  to back up and remove corrupted entries",
        "details": {"artifact_ids": artifact_ids},
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


def _check_binary_path(palaia_root: Path | None) -> dict[str, Any]:
    """Check if the palaia binary in PATH matches the installed version."""
    import shutil
    import subprocess

    from palaia import __version__

    binary = shutil.which("palaia")
    if not binary:
        return {
            "name": "binary_path",
            "label": "Binary path",
            "status": "info",
            "message": "palaia not found in PATH (running as python -m palaia)",
        }

    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True, text=True, timeout=5,
        )
        cli_version = result.stdout.strip().replace("palaia ", "")
    except Exception:
        cli_version = "unknown"

    if cli_version == __version__:
        return {
            "name": "binary_path",
            "label": "Binary path",
            "status": "ok",
            "message": f"v{cli_version} at {binary}",
            "details": {"binary": binary, "version": cli_version},
        }

    return {
        "name": "binary_path",
        "label": "Binary path",
        "status": "warning",
        "message": (
            f"Version mismatch: CLI at {binary} reports v{cli_version}, "
            f"but installed library is v{__version__}. "
            f"A stale binary may be shadowing the new version. "
            f"Check `which -a palaia` and update or remove the old one."
        ),
        "details": {
            "binary": binary,
            "cli_version": cli_version,
            "lib_version": __version__,
        },
    }


def _check_plugin_version_match() -> dict[str, Any]:
    """Detect CLI/plugin version mismatch (#99)."""
    from palaia import __version__
    from palaia.config import VPS_OPENCLAW_BASE

    _home = Path.home()
    _base_dirs = [_home / ".openclaw"]
    if VPS_OPENCLAW_BASE != _home / ".openclaw" and VPS_OPENCLAW_BASE.is_dir():
        _base_dirs.append(VPS_OPENCLAW_BASE)

    # Find plugin package.json
    for base in _base_dirs:
        for candidate in [
            base / "node_modules" / "@byte5ai" / "palaia" / "package.json",
            base / "plugins" / "palaia" / "package.json",
        ]:
            if not candidate.exists():
                continue
            try:
                with open(candidate) as f:
                    pkg = json.load(f)
                plugin_version = pkg.get("version", "unknown")

                if plugin_version == __version__:
                    return {
                        "name": "plugin_version_match",
                        "label": "Plugin/CLI version",
                        "status": "ok",
                        "message": f"v{__version__} (CLI = plugin)",
                    }

                return {
                    "name": "plugin_version_match",
                    "label": "Plugin/CLI version",
                    "status": "warn",
                    "message": (
                        f"Version mismatch: CLI v{__version__}, "
                        f"plugin v{plugin_version}. "
                        "Run: pip install --upgrade palaia && palaia doctor --fix"
                    ),
                    "details": {
                        "cli_version": __version__,
                        "plugin_version": plugin_version,
                        "plugin_path": str(candidate),
                    },
                }
            except (json.JSONDecodeError, OSError):
                continue

    return {
        "name": "plugin_version_match",
        "label": "Plugin/CLI version",
        "status": "ok",
        "message": "Plugin not found locally (skipped)",
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
        try:
            files = list(tier_dir.glob("*.md"))
        except (PermissionError, OSError):
            continue
        for p in files:
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
        try:
            files = list(tier_dir.glob("*.md"))
        except (PermissionError, OSError):
            continue
        for p in files:
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
    """Check if a newer palaia version is available on PyPI."""
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
            "palaia 2.0 has optimized defaults for zero-config UX.\n"
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
        "fix": "Set capture level with: palaia init --capture-level <off|minimal|normal|aggressive>\n"
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
                "status": "warn",
                "message": (
                    "No captureModel set — auto-capture uses the primary model, "
                    "wasting tokens. Set a cheap model (e.g. claude-haiku-4-5) "
                    "in openclaw.json → plugins.entries.palaia.config.captureModel"
                ),
            }
        except (json.JSONDecodeError, OSError, KeyError):
            continue

    return {
        "name": "capture_model",
        "label": "Capture model",
        "status": "ok",
        "message": "OpenClaw/palaia plugin not detected (skipped)",
    }


def _check_capture_health(palaia_root: Path | None) -> dict[str, Any]:
    """Detect silent auto-capture failure: autoCapture=true but no captured entries."""
    if palaia_root is None:
        return {
            "name": "capture_health",
            "label": "Capture health",
            "status": "ok",
            "message": "Not initialized (skipped)",
        }

    from palaia.config import load_config

    config = load_config(palaia_root)
    plugin_config = config.get("plugin_config")

    # Only relevant when autoCapture is enabled
    auto_capture = False
    if plugin_config and isinstance(plugin_config, dict):
        auto_capture = plugin_config.get("autoCapture", False)

    if not auto_capture:
        return {
            "name": "capture_health",
            "label": "Capture health",
            "status": "ok",
            "message": "autoCapture is off (skipped)",
        }

    # Count auto-captured entries
    import sqlite3

    db_path = palaia_root / "palaia.db"
    capture_count = 0
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            row = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE tags LIKE '%auto-capture%'"
            ).fetchone()
            capture_count = row[0] if row else 0
            conn.close()
        except Exception:
            pass
    else:
        # Legacy flat-file: check for auto-capture tag in .md files
        for tier in ("hot", "warm", "cold"):
            tier_dir = palaia_root / tier
            if tier_dir.exists():
                for md_file in tier_dir.glob("*.md"):
                    try:
                        content = md_file.read_text(encoding="utf-8", errors="ignore")
                        if "auto-capture" in content:
                            capture_count += 1
                            break  # One is enough to confirm it works
                    except (PermissionError, OSError):
                        pass
                if capture_count > 0:
                    break

    if capture_count == 0:
        return {
            "name": "capture_health",
            "label": "Capture health",
            "status": "warn",
            "message": (
                "autoCapture=true but no auto-captured entries found. "
                "Auto-capture may not be firing. "
                "Check plugin config and agent workspace setup."
            ),
        }

    return {
        "name": "capture_health",
        "label": "Capture health",
        "status": "ok",
        "message": f"autoCapture=true, {capture_count} auto-captured entries",
    }


def _check_embedding_model_integrity(palaia_root: Path | None) -> dict[str, Any]:
    """Check fastembed model cache integrity (corrupted symlinks cause ONNX errors)."""
    if palaia_root is None:
        return {
            "name": "embedding_model_integrity",
            "label": "Embedding model integrity",
            "status": "ok",
            "message": "Not initialized",
        }

    from palaia.config import load_config

    config = load_config(palaia_root)
    chain = config.get("embedding_chain", [])

    if "fastembed" not in chain:
        return {
            "name": "embedding_model_integrity",
            "label": "Embedding model integrity",
            "status": "ok",
            "message": "fastembed not in chain (skipped)",
        }

    # Resolve model name from config
    models = config.get("embedding_models", {})
    model_name = models.get("fastembed", "BAAI/bge-small-en-v1.5")

    # Convert model name to cache dir name: BAAI/bge-small-en-v1.5 → qdrant--bge-small-en-v1.5-onnx-q
    # fastembed uses qdrant HF repos with -onnx-q suffix
    model_short = model_name.split("/")[-1] if "/" in model_name else model_name
    cache_dir_name = f"models--qdrant--{model_short}-onnx-q"
    import tempfile

    cache_base = Path(tempfile.gettempdir()) / "fastembed_cache"
    cache_dir = cache_base / cache_dir_name

    if not cache_dir.exists():
        # Not cached yet — warmup will download it
        return {
            "name": "embedding_model_integrity",
            "label": "Embedding model integrity",
            "status": "ok",
            "message": "Cache not present yet (run: palaia warmup)",
        }

    # Look for ONNX model file in the cache
    onnx_files = list(cache_dir.rglob("model_optimized.onnx")) + list(cache_dir.rglob("model.onnx"))

    if not onnx_files:
        return {
            "name": "embedding_model_integrity",
            "label": "Embedding model integrity",
            "status": "warn",
            "message": "fastembed model cache is corrupted (no ONNX file found). Run: palaia doctor --fix",
            "fixable": True,
            "details": {"cache_dir": str(cache_dir), "model": model_name},
        }

    # Check each ONNX file: must be a real file, not a broken symlink
    for onnx_file in onnx_files:
        if onnx_file.is_symlink():
            target = onnx_file.resolve()
            if not target.exists():
                return {
                    "name": "embedding_model_integrity",
                    "label": "Embedding model integrity",
                    "status": "warn",
                    "message": "fastembed model cache is corrupted (broken symlink). Run: palaia doctor --fix",
                    "fixable": True,
                    "details": {
                        "cache_dir": str(cache_dir),
                        "broken_file": str(onnx_file),
                        "model": model_name,
                    },
                }
        elif not onnx_file.is_file():
            return {
                "name": "embedding_model_integrity",
                "label": "Embedding model integrity",
                "status": "warn",
                "message": "fastembed model cache is corrupted. Run: palaia doctor --fix",
                "fixable": True,
                "details": {"cache_dir": str(cache_dir), "model": model_name},
            }

    return {
        "name": "embedding_model_integrity",
        "label": "Embedding model integrity",
        "status": "ok",
        "message": f"Cache OK ({model_short})",
        "details": {"cache_dir": str(cache_dir), "model": model_name},
    }


def _check_index_staleness(palaia_root: Path | None) -> dict[str, Any]:
    """Check if embedding index is stale (entries missing from cache)."""
    if palaia_root is None:
        return {
            "name": "index_staleness",
            "label": "Embedding index",
            "status": "error",
            "message": "Not initialized",
        }

    from palaia.config import load_config

    config = load_config(palaia_root)

    # Check config directly — don't instantiate providers (avoids ~3s model load)
    chain_cfg = config.get("embedding_chain", [])
    has_semantic = bool(chain_cfg and any(p != "bm25" for p in chain_cfg))
    if not has_semantic:
        # Also check legacy embedding_provider
        provider_cfg = config.get("embedding_provider", "auto")
        has_semantic = provider_cfg not in ("bm25", "none", "")
    if not has_semantic:
        return {
            "name": "index_staleness",
            "label": "Embedding index",
            "status": "ok",
            "message": "BM25-only (no semantic index needed)",
        }

    # Count entries across hot+warm
    total_entries = 0
    for tier in ("hot", "warm"):
        tier_dir = palaia_root / tier
        if tier_dir.exists():
            total_entries += sum(1 for _ in tier_dir.glob("*.md"))

    if total_entries == 0:
        return {
            "name": "index_staleness",
            "label": "Embedding index",
            "status": "ok",
            "message": "No entries to index",
        }

    # Use Store to get the backend-aware EmbeddingCache
    from palaia.store import Store

    store = Store(palaia_root)
    cache = store.embedding_cache
    cache_stats = cache.stats()
    cached_count = cache_stats.get("cached_entries", 0)
    missing = total_entries - cached_count

    if missing <= 0:
        return {
            "name": "index_staleness",
            "label": "Embedding index",
            "status": "ok",
            "message": f"{cached_count}/{total_entries} entries indexed",
            "details": {"total": total_entries, "cached": cached_count},
        }

    pct_missing = missing / total_entries
    if pct_missing > 0.1:
        return {
            "name": "index_staleness",
            "label": "Embedding index",
            "status": "warn",
            "message": f"{missing} entries not indexed. Semantic search quality degraded.",
            "fix": "Run: palaia warmup",
            "fixable": True,
            "details": {"total": total_entries, "cached": cached_count, "missing": missing},
        }

    return {
        "name": "index_staleness",
        "label": "Embedding index",
        "status": "ok",
        "message": f"{cached_count}/{total_entries} entries indexed ({missing} pending)",
        "details": {"total": total_entries, "cached": cached_count, "missing": missing},
    }


def _check_storage_backend(palaia_root: Path | None) -> dict[str, Any]:
    """Check storage backend health and migration status."""
    if palaia_root is None:
        return {
            "name": "storage_backend",
            "label": "Storage backend",
            "status": "error",
            "message": "Not initialized",
        }

    findings: list[dict[str, Any]] = []
    db_path = palaia_root / "palaia.db"

    # Check 1: Is SQLite DB present?
    if not db_path.exists():
        metadata_json = palaia_root / "index" / "metadata.json"
        if metadata_json.exists():
            return {
                "name": "storage_backend",
                "label": "Storage backend",
                "status": "warn",
                "message": "Flat-file storage detected. Migration to SQLite pending.",
                "fix": "Run palaia status to trigger auto-migration",
            }
        return {
            "name": "storage_backend",
            "label": "Storage backend",
            "status": "ok",
            "message": "No SQLite database (legacy or not yet initialized)",
        }

    # Check 2: DB integrity
    import sqlite3

    try:
        conn = sqlite3.connect(str(db_path))
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if result[0] != "ok":
            findings.append(f"integrity check failed: {result[0]}")
        conn.close()
    except Exception as e:
        return {
            "name": "storage_backend",
            "label": "Storage backend",
            "status": "error",
            "message": f"Cannot open SQLite database: {e}",
        }

    # Check 3: Orphaned .migrated files
    try:
        migrated_files = list(palaia_root.glob("**/*.migrated"))
    except (PermissionError, OSError):
        migrated_files = []

    # Check 4: Entry count consistency
    disk_count = 0
    for tier in ("hot", "warm", "cold"):
        tier_dir = palaia_root / tier
        if tier_dir.exists():
            try:
                disk_count += sum(1 for _ in tier_dir.glob("*.md"))
            except (PermissionError, OSError):
                pass

    db_count = 0
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT COUNT(*) FROM entries").fetchone()
        db_count = row[0] if row else 0
        conn.close()
    except Exception:
        pass

    if disk_count > 0 and db_count == 0:
        findings.append(
            f"{disk_count} entries on disk but 0 in database — migration may have failed"
        )

    # Build result
    if findings:
        fixable = any("entries on disk but 0 in database" in f for f in findings)
        return {
            "name": "storage_backend",
            "label": "Storage backend",
            "status": "error" if any("integrity" in f or "migration may" in f for f in findings) else "warn",
            "message": "; ".join(findings),
            **({"fixable": True} if fixable else {}),
        }

    parts = [f"SQLite OK ({db_count} entries)"]
    if migrated_files:
        parts.append(f"{len(migrated_files)} .migrated backup(s)")

    return {
        "name": "storage_backend",
        "label": "Storage backend",
        "status": "ok",
        "message": ", ".join(parts),
    }


def _check_native_vector_search(palaia_root: Path | None) -> dict[str, Any]:
    """Check if native vector search (sqlite-vec) is available for faster queries."""
    try:
        import sqlite_vec  # noqa: F401

        return {
            "name": "native_vector_search",
            "label": "Native vector search",
            "status": "ok",
            "message": "sqlite-vec installed — SIMD-accelerated KNN active",
        }
    except ImportError:
        return {
            "name": "native_vector_search",
            "label": "Native vector search",
            "status": "info",
            "message": "sqlite-vec not installed. Install for ~30x faster vector search: pip install 'palaia[sqlite-vec]'",
            "fix": "pip install 'palaia[sqlite-vec]'",
        }


def _check_mcp_server(palaia_root: Path | None) -> dict[str, Any]:
    """Check if MCP server is available for Claude Desktop / Cursor integration."""
    try:
        import mcp  # noqa: F401

        return {
            "name": "mcp_server",
            "label": "MCP server",
            "status": "ok",
            "message": "MCP SDK installed — palaia-mcp available for Claude Desktop, Cursor",
        }
    except ImportError:
        return {
            "name": "mcp_server",
            "label": "MCP server",
            "status": "info",
            "message": "MCP SDK not installed. For Claude Desktop / Cursor: pip install 'palaia[mcp]'",
        }


def _check_stale_unassigned_tasks(palaia_root: Path | None) -> dict[str, Any]:
    """Check for auto-captured tasks without assignee/due_date older than 7 days."""
    if palaia_root is None:
        return {
            "name": "stale_unassigned_tasks",
            "label": "Stale unassigned tasks",
            "status": "ok",
            "message": "Not initialized",
        }

    from datetime import datetime, timezone

    from palaia.entry import parse_entry

    now = datetime.now(tz=timezone.utc)
    stale_ids: list[str] = []

    for tier in ("hot", "warm"):
        tier_dir = palaia_root / tier
        if not tier_dir.exists():
            continue
        for p in tier_dir.glob("*.md"):
            try:
                text = p.read_text(encoding="utf-8")
                meta, _body = parse_entry(text)
                if meta.get("type") != "task":
                    continue
                if meta.get("assignee") or meta.get("due_date"):
                    continue
                raw_tags = meta.get("tags", [])
                tags = raw_tags if isinstance(raw_tags, list) else str(raw_tags).split(",")
                tags = [t.strip() for t in tags]
                if "auto-capture" not in tags:
                    continue
                created = meta.get("created", "")
                if not created:
                    continue
                created_dt = datetime.fromisoformat(created)
                if (now - created_dt).days >= 7:
                    stale_ids.append(p.stem)
            except Exception:
                continue

    if not stale_ids:
        return {
            "name": "stale_unassigned_tasks",
            "label": "Stale unassigned tasks",
            "status": "ok",
            "message": "No stale unassigned tasks",
        }

    return {
        "name": "stale_unassigned_tasks",
        "label": "Stale unassigned tasks",
        "status": "warn",
        "message": (
            f"{len(stale_ids)} auto-captured task(s) without assignee or due_date, "
            f"older than 7 days. Consider reclassifying as memory."
        ),
        "fix": "Review with: palaia list --type task --all\n"
        "  Reclassify with: palaia edit <id> --type memory",
        "details": {"stale_task_ids": stale_ids},
    }
