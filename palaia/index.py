"""Embedding cache for Tier 2/3 search (ADR-001).

Cache-only infrastructure. Embedding computation is handled by embeddings.py.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class EmbeddingCache:
    """File-backed embedding vector cache.

    Stores pre-computed embedding vectors keyed by entry ID.
    Cache lives at .palaia/index/embeddings.json.
    Thread-safe: all public methods are protected by a threading.Lock.
    """

    def __init__(self, palaia_root: Path, backend=None):
        self._backend = backend
        self.index_dir = palaia_root / "index"
        if not backend:
            self.index_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.index_dir / "embeddings.json"
        self._cache: dict[str, dict[str, Any]] | None = None
        self._lock = threading.Lock()

    def _load(self) -> dict[str, dict[str, Any]]:
        """Load cache from disk (lazy). Must be called with _lock held."""
        if self._cache is not None:
            return self._cache
        if self.cache_path.exists():
            try:
                with open(self.cache_path) as f:
                    self._cache = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._cache = {}
        else:
            self._cache = {}
        return self._cache

    def _save(self) -> None:
        """Persist cache to disk (atomic write). Must be called with _lock held."""
        if self._cache is None:
            return
        suffix = f".{os.getpid()}.{threading.get_ident()}.tmp"
        tmp = self.cache_path.with_suffix(suffix)
        with open(tmp, "w") as f:
            json.dump(self._cache, f)
            f.flush()
            os.fsync(f.fileno())
        tmp.rename(self.cache_path)

    def get_cached(self, entry_id: str) -> list[float] | None:
        """Get cached embedding vector for an entry.

        Returns:
            The embedding vector as a list of floats, or None if not cached.
        """
        if self._backend:
            result = self._backend.get_embedding(entry_id)
            return result[0] if result else None  # Return just the vector
        with self._lock:
            cache = self._load()
            entry = cache.get(entry_id)
            if entry is None:
                return None
            return entry.get("vector")

    def set_cached(self, entry_id: str, vector: list[float], model: str = "unknown") -> None:
        """Store an embedding vector in the cache.

        Args:
            entry_id: The memory entry ID.
            vector: The embedding vector.
            model: Name of the model that generated the embedding.
        """
        if self._backend:
            self._backend.set_embedding(entry_id, vector, model, len(vector))
            return
        with self._lock:
            cache = self._load()
            cache[entry_id] = {
                "vector": vector,
                "model": model,
                "dim": len(vector),
            }
            self._save()

    def invalidate(self, entry_id: str) -> bool:
        """Remove a cached embedding for an entry.

        Returns:
            True if an entry was removed, False if not found.
        """
        if self._backend:
            self._backend.invalidate_embedding(entry_id)
            return True
        with self._lock:
            cache = self._load()
            if entry_id in cache:
                del cache[entry_id]
                self._save()
                return True
            return False

    def reload(self) -> None:
        """Force reload of cache from disk on next access.

        Used by embed_server stale detection to pick up changes
        made by other processes.
        """
        with self._lock:
            self._cache = None

    def cleanup(self, valid_ids: set[str]) -> int:
        """Remove cache entries for IDs not in the valid set.

        Used by GC to prune embeddings for deleted entries.

        Returns:
            Number of stale cache entries removed.
        """
        if self._backend:
            return self._backend.cleanup_embeddings(valid_ids)
        with self._lock:
            cache = self._load()
            stale = [eid for eid in cache if eid not in valid_ids]
            for eid in stale:
                del cache[eid]
            if stale:
                self._save()
            return len(stale)

    def stats(self) -> dict:
        """Return cache statistics."""
        if self._backend:
            # Use backend health_check or query for stats
            try:
                health = self._backend.health_check()
                return {
                    "cached_entries": health.get("embeddings", 0),
                    "models": [],
                }
            except Exception:
                return {"cached_entries": 0, "models": []}
        with self._lock:
            cache = self._load()
            models = set()
            for entry in cache.values():
                models.add(entry.get("model", "unknown"))
            return {
                "cached_entries": len(cache),
                "models": sorted(models) if models else [],
            }
