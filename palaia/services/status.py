"""Status service — system status collection."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from palaia import __version__
from palaia.store import Store


def _find_latest_mtime(root: Path, tiers: tuple[str, ...] = ("hot",)) -> str | None:
    """Find the latest file mtime across tiers, return as ISO string."""
    latest = 0.0
    for tier in tiers:
        tier_dir = root / tier
        if not tier_dir.exists():
            continue
        for f in tier_dir.iterdir():
            if f.is_file():
                mt = f.stat().st_mtime
                if mt > latest:
                    latest = mt
    if latest == 0.0:
        return None
    return datetime.fromtimestamp(latest, tz=timezone.utc).isoformat()


def _find_gc_time(root: Path) -> str | None:
    """Try to find the last GC run timestamp from config or file markers."""
    config_path = root / "config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            gc_ts = config.get("last_gc")
            if gc_ts:
                return gc_ts
        except Exception:
            pass
    return None


def collect_status(root: Path) -> dict:
    """Collect full system status information.

    Returns a dict with all status data needed for both JSON and human output.
    """
    store = Store(root)
    recovered = store.recover()

    info = store.status()

    # Compute index hint
    try:
        _cache = store.embedding_cache
        _idx_count = _cache.stats().get("cached_entries", None)
    except Exception:
        _idx_count = None
    _total = info["total"]
    if isinstance(_idx_count, int) and isinstance(_total, int):
        _not_indexed = _total - _idx_count
        if _not_indexed > 0:
            info["index_hint"] = (
                f"Index: {_idx_count}/{_total} — {_not_indexed} entries not indexed. Run: palaia warmup"
            )
        else:
            info["index_hint"] = f"Index: {_idx_count}/{_total} — fully indexed"
    else:
        info["index_hint"] = None

    # Disk size
    disk_bytes = 0
    for tier in ("hot", "warm", "cold"):
        tier_dir = root / tier
        if tier_dir.exists():
            for f in tier_dir.iterdir():
                if f.is_file():
                    disk_bytes += f.stat().st_size
    info["disk_bytes"] = disk_bytes

    # Project count
    projects_file = root / "projects.json"
    project_count = 0
    if projects_file.exists():
        try:
            pdata = json.loads(projects_file.read_text())
            project_count = len(pdata) if isinstance(pdata, dict) else 0
        except Exception:
            pass
    info["project_count"] = project_count

    # Timestamps
    info["last_write"] = _find_latest_mtime(root, ("hot", "warm"))
    info["last_gc"] = _find_gc_time(root)

    # Entry class breakdown (ADR-012)
    type_counts: dict[str, int] = {"memory": 0, "process": 0, "task": 0}
    task_status_counts: dict[str, int] = {}
    for tier_name in ("hot", "warm", "cold"):
        tier_dir = root / tier_name
        if not tier_dir.exists():
            continue
        for p in tier_dir.glob("*.md"):
            try:
                from palaia.entry import parse_entry as _pe

                text = p.read_text(encoding="utf-8")
                meta, _ = _pe(text)
                et = meta.get("type", "memory")
                type_counts[et] = type_counts.get(et, 0) + 1
                if et == "task":
                    st = meta.get("status", "open")
                    task_status_counts[st] = task_status_counts.get(st, 0) + 1
            except Exception:
                continue
    info["type_counts"] = type_counts
    info["task_status_counts"] = task_status_counts

    # Embedding chain status
    from palaia.embeddings import build_embedding_chain

    chain = build_embedding_chain(store.config)
    statuses = chain.provider_status()
    info["embedding_statuses"] = statuses

    # Index count
    try:
        from palaia.index import EmbeddingCache

        cache = EmbeddingCache(root)
        idx_count = len(cache._load()) if hasattr(cache, "_load") else "?"
    except Exception:
        idx_count = "?"
    info["idx_count"] = idx_count

    # Backend info
    backend_info = {"type": "sqlite", "vector_search": "python-fallback"}
    try:
        if hasattr(store, "_backend"):
            backend = store._backend
            backend_type = getattr(backend, "backend_type", None) or type(backend).__name__
            backend_info["type"] = backend_type.lower().replace("backend", "").strip() or "sqlite"
            if hasattr(backend, "_has_vec"):
                backend_info["vector_search"] = "sqlite-vec (native KNN)" if backend._has_vec else "python cosine similarity"
            elif "postgres" in backend_info["type"]:
                backend_info["vector_search"] = "pgvector (ANN)"
            health = getattr(backend, "health_check", lambda: {})()
            if isinstance(health, dict):
                backend_info["status"] = health.get("status", "ok")
                if "sqlite_vec" in health:
                    backend_info["sqlite_vec"] = health["sqlite_vec"]
    except Exception:
        pass
    info["backend"] = backend_info

    # Embed-server status
    try:
        from palaia.embed_client import is_server_running

        info["embed_server_running"] = is_server_running(root)
    except Exception:
        info["embed_server_running"] = False

    # Installed extras detection (for upgrade commands)
    installed_extras = ["fastembed"]  # always assumed as base
    try:
        import fastembed  # noqa: F401
    except ImportError:
        installed_extras = []
    for mod, extra in [("mcp", "mcp"), ("sqlite_vec", "sqlite-vec"), ("sklearn", "curate")]:
        try:
            __import__(mod)
            installed_extras.append(extra)
        except ImportError:
            pass
    info["installed_extras"] = installed_extras
    info["upgrade_spec"] = f"palaia[{','.join(installed_extras)}]" if installed_extras else "palaia"

    # WAL recovery
    info["recovered"] = recovered

    # OpenClaw Plugin detection (L-2)
    plugin_detected = False
    try:
        plugin_config_candidates = [
            root.parent / "openclaw.json",
            Path.home() / ".openclaw" / "openclaw.json",
        ]
        env_config = os.environ.get("OPENCLAW_CONFIG")
        if env_config:
            plugin_config_candidates.insert(0, Path(env_config))
        for candidate in plugin_config_candidates:
            if candidate.exists():
                cfg_data = json.loads(candidate.read_text())
                if "palaia" in json.dumps(cfg_data.get("plugins", {})):
                    plugin_detected = True
                    break
    except Exception:
        pass
    info["plugin_detected"] = plugin_detected

    info["version"] = __version__

    return info
