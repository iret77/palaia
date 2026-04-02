"""Admin service — init, gc, config, recover, warmup, migrate, detect, setup."""

from __future__ import annotations

import json
import os
from pathlib import Path

from palaia import __version__
from palaia.config import (
    DEFAULT_CONFIG,
    clear_instance,
    get_aliases,
    get_instance,
    load_config,
    remove_alias,
    save_config,
    set_alias,
    set_instance,
)
from palaia.store import Store

# ---------------------------------------------------------------------------
# Agent detection helpers (moved from cli.py)
# ---------------------------------------------------------------------------

class _AgentDetectResult:
    """Result of OpenClaw agent auto-detection."""

    __slots__ = ("agent", "status", "count")

    def __init__(self, agent: str | None, status: str, count: int = 0):
        self.agent = agent
        # status: "found" | "multiple" | "no_config" | "no_agents"
        self.status = status
        self.count = count


def _detect_agents() -> list[str]:
    """Detect OpenClaw agents by checking ~/.openclaw/agents/ directory."""
    agents_dir = Path.home() / ".openclaw" / "agents"
    if not agents_dir.is_dir():
        return []
    return [d.name for d in agents_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]


def _detect_agent_from_openclaw_config() -> str | None:
    """Try to auto-detect agent name from OpenClaw config file.

    Convenience wrapper around _detect_agent_from_openclaw_config_ext().
    Returns agent name or None.
    """
    result = _detect_agent_from_openclaw_config_ext()
    return result.agent


def _detect_agent_from_openclaw_config_ext() -> _AgentDetectResult:
    """Try to auto-detect agent name from OpenClaw config file.

    Reads ~/.openclaw/openclaw.json, config.json (or .yaml) and inspects agents.
    Supports two formats:
    - agents.list: [{id, name, default, ...}, ...]  (standard OpenClaw format)
    - agents as object: {agentId: {name: ..., ...}, ...}  (legacy/alternative)

    Returns _AgentDetectResult with status info for better error messages.
    """
    # Standard OpenClaw paths + VPS fallback (#51)
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

    # Also check OPENCLAW_CONFIG env var
    env_config = os.environ.get("OPENCLAW_CONFIG")
    if env_config:
        config_candidates.insert(0, Path(env_config))

    for config_path in config_candidates:
        if not config_path.exists():
            continue
        try:
            if config_path.suffix == ".json":
                with open(config_path) as f:
                    data = json.load(f)
            elif config_path.suffix in (".yaml", ".yml"):
                try:
                    import yaml  # type: ignore[import-untyped]

                    with open(config_path) as f:
                        data = yaml.safe_load(f)
                except ImportError:
                    continue
            else:
                continue

            agents_section = data.get("agents", {})
            if not isinstance(agents_section, dict):
                continue

            # Format 1: agents.list = [{id, name, ...}, ...]
            agent_list = agents_section.get("list")
            if isinstance(agent_list, list) and agent_list:
                if len(agent_list) == 1:
                    name = agent_list[0].get("name") or agent_list[0].get("id")
                    return _AgentDetectResult(name, "found", 1)

                # Multiple agents → look for default:true
                for agent in agent_list:
                    if agent.get("default") is True:
                        name = agent.get("name") or agent.get("id")
                        return _AgentDetectResult(name, "found", len(agent_list))

                return _AgentDetectResult(None, "multiple", len(agent_list))

            # Format 2: agents = {agentId: {name: ..., ...}, ...}
            # (Object with agent-IDs as keys, excluding known meta-keys)
            meta_keys = {"defaults", "list", "version"}
            agent_keys = [k for k in agents_section if k not in meta_keys]
            if agent_keys:
                if len(agent_keys) == 1:
                    key = agent_keys[0]
                    val = agents_section[key]
                    name = val.get("name", key) if isinstance(val, dict) else key
                    return _AgentDetectResult(name, "found", 1)

                # Multiple → look for default:true
                for key in agent_keys:
                    val = agents_section[key]
                    if isinstance(val, dict) and val.get("default") is True:
                        name = val.get("name", key)
                        return _AgentDetectResult(name, "found", len(agent_keys))

                return _AgentDetectResult(None, "multiple", len(agent_keys))

            # Config exists but no agents found
            return _AgentDetectResult(None, "no_agents", 0)
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            continue

    return _AgentDetectResult(None, "no_config", 0)


CAPTURE_LEVEL_MAP = {
    "off": {
        "autoCapture": False,
    },
    "minimal": {
        "autoCapture": True,
        "captureFrequency": "significant",
        "captureMinTurns": 5,
    },
    "sparsam": {  # legacy alias for minimal
        "autoCapture": True,
        "captureFrequency": "significant",
        "captureMinTurns": 5,
    },
    "normal": {
        "autoCapture": True,
        "captureFrequency": "significant",
        "captureMinTurns": 2,
    },
    "aggressive": {
        "autoCapture": True,
        "captureFrequency": "every",
        "captureMinTurns": 1,
    },
    "aggressiv": {  # legacy alias for aggressive
        "autoCapture": True,
        "captureFrequency": "every",
        "captureMinTurns": 1,
    },
}


def _is_openclaw_environment() -> bool:
    """Detect if we're running in an OpenClaw environment."""
    openclaw_dir = Path.home() / ".openclaw"
    if openclaw_dir.is_dir():
        return True
    if os.environ.get("OPENCLAW_HOME"):
        return True
    return False


# ---------------------------------------------------------------------------
# recover
# ---------------------------------------------------------------------------

def recover(root: Path) -> dict:
    """Run WAL recovery.

    Returns dict with keys: replayed, errors.
    """
    store = Store(root)
    recovered = store.recover()
    return {"replayed": recovered, "errors": 0}


# ---------------------------------------------------------------------------
# gc
# ---------------------------------------------------------------------------

def run_gc(root: Path, *, dry_run: bool = False, budget: bool = False) -> dict:
    """Run garbage collection / tier rotation.

    Returns the result dict from store.gc().
    """
    store = Store(root)
    store.recover()
    return store.gc(dry_run=dry_run, budget=budget)


def run_prune(
    root: Path,
    *,
    agent: str,
    tags: list[str],
    protect_types: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """Selectively delete entries matching agent + tags.

    Returns dict with pruned count and entry details.
    """
    store = Store(root)
    store.recover()
    return store.prune(agent=agent, tags=tags, protect_types=protect_types, dry_run=dry_run)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

def config_set_chain(root: Path, providers: list[str]) -> dict:
    """Set the embedding fallback chain.

    Returns dict with embedding_chain or error.
    """
    config = load_config(root)
    valid_providers = {"openai", "sentence-transformers", "fastembed", "ollama", "bm25"}
    for p in providers:
        if p not in valid_providers:
            return {"error": f"Unknown provider: {p}. Valid: {', '.join(sorted(valid_providers))}"}

    chain = list(providers)
    if "bm25" not in chain:
        chain = chain + ["bm25"]

    config["embedding_chain"] = chain
    save_config(root, config)
    return {"embedding_chain": chain}


def config_set_alias_svc(root: Path, from_name: str, to_name: str) -> dict:
    """Set an agent alias. Returns dict."""
    try:
        set_alias(root, from_name, to_name)
    except ValueError as e:
        return {"error": str(e)}
    return {"alias": from_name, "target": to_name}


def config_get_aliases_svc(root: Path) -> dict:
    """Get all agent aliases. Returns dict."""
    aliases = get_aliases(root)
    return {"aliases": aliases}


def config_remove_alias_svc(root: Path, from_name: str) -> dict:
    """Remove an agent alias. Returns dict."""
    removed = remove_alias(root, from_name)
    return {"removed": removed, "alias": from_name}


def config_get(root: Path, key: str) -> dict:
    """Get a single config value. Returns dict."""
    config = load_config(root)
    if key in config:
        return {"key": key, "value": config[key]}
    return {"error": f"Unknown key: {key}"}


def config_set(root: Path, key: str, value: str) -> dict:
    """Set a config value with type coercion. Returns dict."""
    config = load_config(root)
    coerced_value: str | int | float = value
    if key in DEFAULT_CONFIG:
        default_val = DEFAULT_CONFIG[key]
        if isinstance(default_val, int):
            try:
                coerced_value = int(value)
            except ValueError:
                pass
        elif isinstance(default_val, float):
            try:
                coerced_value = float(value)
            except ValueError:
                pass

    config[key] = coerced_value
    save_config(root, config)
    return {"key": key, "value": coerced_value}


def config_list_all(root: Path) -> dict:
    """List all config. Returns the config dict."""
    return load_config(root)


# ---------------------------------------------------------------------------
# warmup + reindex
# ---------------------------------------------------------------------------

def reindex_entries(root: Path, config: dict) -> dict:
    """Build embedding index for all HOT+WARM entries missing from cache.

    Uses embed-server if running (fast, model already in RAM). Falls back to
    direct provider loading only if no server is available (explicit warmup
    is the one case where direct loading is acceptable — user asked for it).

    Returns dict with keys: indexed, new, cached.
    """
    store = Store(root)

    # Fast path: delegate to embed-server warmup if running
    try:
        from palaia.embed_client import EmbedServerClient, is_server_running
        from palaia.embed_server import get_socket_path

        if is_server_running(root):
            with EmbedServerClient(get_socket_path(root)) as client:
                result = client.warmup(timeout=120.0)
                return result
    except Exception:
        pass

    # Slow path: load provider directly (user explicitly asked for warmup)
    from palaia.embeddings import BM25Provider, auto_detect_provider

    try:
        provider = auto_detect_provider(config)
    except Exception:
        provider = BM25Provider()

    if isinstance(provider, BM25Provider):
        return {"indexed": 0, "new": 0, "cached": 0}

    entries = store.all_entries_unfiltered(include_cold=False)
    total = len(entries)
    if total == 0:
        return {"indexed": 0, "new": 0, "cached": 0}

    # Separate entries into cached and uncached
    uncached_entries = []
    cached_count = 0
    for meta, body, _tier in entries:
        entry_id = meta.get("id", "")
        if not entry_id:
            continue
        if store.embedding_cache.get_cached(entry_id) is not None:
            cached_count += 1
        else:
            title = meta.get("title", "")
            tags = " ".join(meta.get("tags", []))
            full_text = f"{title} {tags} {body}"
            uncached_entries.append((entry_id, full_text))

    if not uncached_entries:
        return {"indexed": total, "new": 0, "cached": cached_count}

    # Batch embed uncached entries
    model_name = getattr(provider, "model_name", None) or getattr(provider, "model", "unknown")
    batch_size = 32
    new_count = 0

    for i in range(0, len(uncached_entries), batch_size):
        batch = uncached_entries[i : i + batch_size]
        texts = [text for _, text in batch]
        ids = [eid for eid, _ in batch]

        try:
            vectors = provider.embed(texts)
            for eid, vec in zip(ids, vectors):
                store.embedding_cache.set_cached(eid, vec, model=model_name)
                new_count += 1
        except Exception:
            break

    indexed = cached_count + new_count
    return {"indexed": indexed, "new": new_count, "cached": cached_count}


def warmup(root: Path) -> dict:
    """Pre-download embedding models and reindex entries.

    Returns dict with providers and index stats.
    """
    config = load_config(root)
    from palaia.embeddings import warmup_providers
    from palaia.entry import parse_entry

    results = warmup_providers(config)

    # Rebuild metadata index from disk
    store = Store(root)
    meta_count = store.metadata_index.rebuild(parse_entry)

    # Reindex entries after model warmup
    index_stats = reindex_entries(root, config)

    return {"providers": results, "meta_count": meta_count, **index_stats}


# ---------------------------------------------------------------------------
# detect
# ---------------------------------------------------------------------------

def detect_embedding_providers() -> dict:
    """Detect available embedding providers.

    Returns dict with system, python, providers.
    """
    import platform

    from palaia.embeddings import detect_providers

    sys_info = f"{platform.system()} {platform.machine()}"
    py_ver = platform.python_version()
    providers = detect_providers()

    return {
        "system": sys_info,
        "python": py_ver,
        "providers": providers,
    }


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def init_palaia(
    *,
    path: str | None = None,
    agent: str | None = None,
    store_mode: str | None = None,
    capture_level: str | None = None,
    reset: bool = False,
) -> dict:
    """Initialize .palaia directory.

    Returns a result dict with status, path, messages, etc.
    """
    # Respect PALAIA_HOME if set and no explicit path given
    if path:
        target = Path(path) / ".palaia"
    else:
        env_home = os.environ.get("PALAIA_HOME")
        if env_home:
            env_path = Path(env_home)
            if env_path.name == ".palaia":
                target = env_path
            else:
                target = env_path / ".palaia"
        else:
            target = Path(".") / ".palaia"

    is_reinit = target.exists()
    agent_name = agent
    used_default = False
    messages: list[str] = []

    # Resolve agent name when not explicitly provided
    if not agent_name:
        if is_reinit:
            try:
                existing_config = load_config(target)
                if existing_config.get("agent"):
                    agent_name = None  # Will be preserved in re-init path
                else:
                    detected = _detect_agent_from_openclaw_config()
                    if detected:
                        agent_name = detected
                        messages.append(f"Auto-detected agent: {agent_name} (from OpenClaw config)")
                    else:
                        agent_name = "default"
                        used_default = True
            except (json.JSONDecodeError, OSError):
                detected = _detect_agent_from_openclaw_config()
                if detected:
                    agent_name = detected
                    messages.append(f"Auto-detected agent: {agent_name} (from OpenClaw config)")
                else:
                    agent_name = "default"
                    used_default = True
        else:
            detected = _detect_agent_from_openclaw_config()
            if detected:
                agent_name = detected
                messages.append(f"Auto-detected agent: {agent_name} (from OpenClaw config)")
            else:
                agent_name = "default"
                used_default = True

    if is_reinit:
        existing_config = load_config(target)

        if agent_name:
            existing_config["agent"] = agent_name

        existing_chain = existing_config.get("embedding_chain")

        if existing_chain and len(existing_chain) > 0:
            if capture_level and capture_level in CAPTURE_LEVEL_MAP:
                existing_config["plugin_config"] = CAPTURE_LEVEL_MAP[capture_level]
                messages.append(f"Capture level set to: {capture_level}")

            save_config(target, existing_config)

            return {
                "status": "updated",
                "path": str(target),
                "agent": existing_config.get("agent"),
                "messages": messages,
            }

        config = existing_config
    else:
        target.mkdir(parents=True)
        for sub in ("hot", "warm", "cold", "wal", "index"):
            (target / sub).mkdir()
        config = dict(DEFAULT_CONFIG)

    # Auto-detect providers and configure the best chain
    from palaia.embeddings import detect_providers

    detected = detect_providers()
    detected_map = {p["name"]: p["available"] for p in detected}

    chain: list[str] = []
    if detected_map.get("openai"):
        chain.append("openai")
    if detected_map.get("gemini"):
        chain.append("gemini")
    if detected_map.get("fastembed"):
        chain.append("fastembed")
    elif detected_map.get("sentence-transformers"):
        chain.append("sentence-transformers")
    elif detected_map.get("ollama"):
        chain.append("ollama")
    chain.append("bm25")

    config["embedding_chain"] = chain

    # Multi-agent detection
    agents = _detect_agents()
    if len(agents) > 1:
        config["agent"] = None
        config["multi_agent"] = True
        if store_mode == "isolated":
            config["store_mode"] = "isolated"
            messages.append(f"Found {len(agents)} agents: {', '.join(agents)}")
            messages.append("  Using isolated stores — each agent gets its own .palaia directory.")
        else:
            config["store_mode"] = "shared"
            messages.append(f"Found {len(agents)} agents: {', '.join(agents)}")
            messages.append(f"  Using shared store at {target}")
            messages.append("  All agents will see team-scoped entries.")
            messages.append("  Each agent MUST set PALAIA_AGENT env var for correct attribution.")
            if store_mode is None:
                messages.append("  (Use 'palaia init --isolated' for separate stores per agent)")
    else:
        if agent_name:
            config["agent"] = agent_name
        config["multi_agent"] = False
        if len(agents) == 1:
            messages.append(f"Found 1 agent: {agents[0]}")
        config["store_mode"] = "shared"

    config["store_version"] = __version__
    save_config(target, config)

    result: dict = {
        "status": "created" if not is_reinit else "updated",
        "path": str(target),
        "embedding_chain": chain,
        "agents": agents,
        "store_mode": config.get("store_mode", "shared"),
        "used_default": used_default,
        "messages": messages,
        "agent": config.get("agent"),
    }

    # Chain info messages
    has_local = any(p in chain for p in ("sentence-transformers", "fastembed", "ollama"))
    has_openai = "openai" in chain
    if has_openai and not has_local:
        messages.append(f"Embedding chain: {' -> '.join(chain)} (no local fallback)")
        messages.append("  If OpenAI is unavailable, search quality will drop significantly.")
        messages.append("  Recommend: pip install sentence-transformers && palaia warmup")
    elif len(chain) > 1:
        messages.append(f"Embedding chain configured: {' -> '.join(chain)}")
    else:
        messages.append("No semantic search providers found. Using BM25 keyword search.")

    # Capture-level
    if capture_level and capture_level in CAPTURE_LEVEL_MAP:
        config_for_capture = load_config(target)
        config_for_capture["plugin_config"] = CAPTURE_LEVEL_MAP[capture_level]
        save_config(target, config_for_capture)
        messages.append(f"\nCapture level set to: {capture_level}")
        level_config = CAPTURE_LEVEL_MAP[capture_level]
        if level_config.get("autoCapture"):
            freq = level_config.get("captureFrequency", "significant")
            turns = level_config.get("captureMinTurns", 2)
            messages.append(f"  autoCapture=true, frequency={freq}, minTurns={turns}")
        else:
            messages.append("  autoCapture=off (no automatic knowledge capture)")
    elif capture_level is None and _is_openclaw_environment():
        messages.append("\nOpenClaw environment detected.")
        messages.append("Configure auto-capture with: palaia init --capture-level <off|minimal|normal|aggressive>")
        messages.append("  off        — No automatic capture")
        messages.append("  minimal    — Capture significant exchanges (minTurns=5)")
        messages.append("  normal     — Capture significant exchanges (minTurns=2) [recommended]")
        messages.append("  aggressive — Capture every exchange (minTurns=1)")

    # Clean post-init summary (agent-friendly, no expert wall)
    messages.append("")
    messages.append(f"[palaia] Initialized at {target}")
    messages.append(f"[palaia] Agent: {config.get('agent', 'default')}")
    messages.append("[palaia] Storage: SQLite (automatic)")
    if chain and chain != ["bm25"]:
        messages.append(f"[palaia] Embeddings: {', '.join(chain)}")
    else:
        messages.append("[palaia] Embeddings: BM25 keyword search (run 'palaia detect' for semantic search)")
    messages.append("[palaia] Ready. Auto-capture is active.")

    return result


# ---------------------------------------------------------------------------
# migrate suggest helper
# ---------------------------------------------------------------------------

def suggest_type(title: str, body: str, meta: dict) -> str:
    """Heuristic to suggest entry type based on content."""
    combined = f"{title} {body}".lower()
    task_keywords = ["todo", "task", "bug", "fix", "issue", "ticket", "deadline", "assigned", "blocker"]
    if any(kw in combined for kw in task_keywords):
        return "task"
    process_keywords = ["checklist", "sop", "procedure", "workflow", "step 1", "step 2", "how to", "guide", "runbook"]
    if any(kw in combined for kw in process_keywords):
        return "process"
    return "memory"


def migrate_suggest(root: Path) -> dict:
    """Suggest entry type assignments for existing entries without a type field.

    Returns dict with suggestions list and total count.
    """
    from palaia.entry import parse_entry

    suggestions = []
    for tier in ("hot", "warm", "cold"):
        tier_dir = root / tier
        if not tier_dir.exists():
            continue
        for p in tier_dir.glob("*.md"):
            try:
                text = p.read_text(encoding="utf-8")
                meta, body = parse_entry(text)
                if "type" in meta:
                    continue
                entry_id = meta.get("id", p.stem)
                title = meta.get("title", "(untitled)")
                suggested = suggest_type(title, body, meta)
                suggestions.append(
                    {
                        "id": entry_id,
                        "title": title,
                        "tier": tier,
                        "suggested_type": suggested,
                    }
                )
            except Exception:
                continue

    return {"suggestions": suggestions, "total": len(suggestions)}


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

def setup_multi_agent(
    root: Path,
    agents_dir_path: str,
    *,
    dry_run: bool = False,
) -> dict:
    """Create .palaia symlinks for agent directories.

    Returns dict with agents, symlinks_created, store_path, dry_run.
    """
    agents_dir = Path(agents_dir_path)
    if not agents_dir.is_dir():
        return {"error": f"Directory not found: {agents_dir}"}

    store_path = root

    agent_dirs = sorted([d for d in agents_dir.iterdir() if d.is_dir() and not d.name.startswith(".")])

    if not agent_dirs:
        return {"error": f"No agent directories found in {agents_dir}", "agents": []}

    agents = []
    symlinks_created = 0
    actions: list[dict] = []

    for agent_dir in agent_dirs:
        agent_name = agent_dir.name
        symlink_path = agent_dir / ".palaia"
        agents.append(agent_name)

        if symlink_path.exists() or symlink_path.is_symlink():
            actions.append({"agent": agent_name, "action": "skip", "reason": ".palaia already exists"})
            continue

        if dry_run:
            actions.append({"agent": agent_name, "action": "plan", "target": str(store_path)})
            symlinks_created += 1
        else:
            try:
                symlink_path.symlink_to(store_path)
                symlinks_created += 1
                actions.append({"agent": agent_name, "action": "ok", "target": str(store_path)})
            except OSError as e:
                actions.append({"agent": agent_name, "action": "error", "error": str(e)})

    return {
        "agents": agents,
        "symlinks_created": symlinks_created,
        "store_path": str(store_path),
        "dry_run": dry_run,
        "actions": actions,
    }


# ---------------------------------------------------------------------------
# instance
# ---------------------------------------------------------------------------

def instance_set(root: Path, name: str) -> dict:
    """Set session instance identity."""
    set_instance(root, name)
    return {"instance": name, "status": "set"}


def instance_get(root: Path) -> dict:
    """Get current session instance identity."""
    instance = get_instance(root)
    return {"instance": instance}


def instance_clear(root: Path) -> dict:
    """Clear session instance identity."""
    clear_instance(root)
    return {"instance": None, "status": "cleared"}
