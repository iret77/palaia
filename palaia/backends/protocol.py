"""Storage backend protocol — the contract all backends implement."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    """Abstract storage backend for palaia metadata, embeddings, and WAL.

    Implementations must provide all methods below.  The two shipped backends
    are ``SQLiteBackend`` (zero-config default) and ``PostgresBackend``
    (scale-up for distributed agent teams).
    """

    # ── Metadata ──────────────────────────────────────────────────────

    def upsert_entry(self, entry_id: str, meta: dict, tier: str) -> None:
        """Insert or update entry metadata."""
        ...

    def get_entry(self, entry_id: str) -> dict | None:
        """Return metadata dict for *entry_id*, or ``None``."""
        ...

    def remove_entry(self, entry_id: str) -> None:
        """Delete entry metadata (and associated embedding)."""
        ...

    def find_by_hash(self, content_hash: str) -> str | None:
        """Return entry_id whose ``content_hash`` matches, or ``None``."""
        ...

    def query_entries(
        self,
        *,
        tier: str | None = None,
        project: str | None = None,
        entry_type: str | None = None,
        scope: str | None = None,
        agent: str | None = None,
        status: str | None = None,
        order_by: str = "decay_score DESC",
        limit: int | None = None,
    ) -> list[dict]:
        """Return metadata dicts matching the given filters."""
        ...

    def all_entry_ids(self, include_cold: bool = False) -> list[str]:
        """Return all entry IDs, optionally including cold tier."""
        ...

    def entry_count(self, tier: str | None = None) -> int:
        """Count entries, optionally filtered by tier."""
        ...

    def cleanup_entries(self, valid_ids: set[str]) -> int:
        """Remove metadata for entries not in *valid_ids*.  Returns count."""
        ...

    # ── Embeddings ────────────────────────────────────────────────────

    def get_embedding(self, entry_id: str) -> tuple[list[float], str, int] | None:
        """Return ``(vector, model, dim)`` or ``None``."""
        ...

    def set_embedding(
        self, entry_id: str, vector: list[float], model: str, dim: int
    ) -> None:
        """Store an embedding vector for *entry_id*."""
        ...

    def invalidate_embedding(self, entry_id: str) -> None:
        """Remove cached embedding for *entry_id*."""
        ...

    def cleanup_embeddings(self, valid_ids: set[str]) -> int:
        """Remove embeddings not in *valid_ids*.  Returns count."""
        ...

    # ── Vector search ─────────────────────────────────────────────────

    def vector_search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        *,
        tier: str | None = None,
        entry_type: str | None = None,
    ) -> list[tuple[str, float]]:
        """Return ``[(entry_id, similarity_score)]`` for nearest neighbours."""
        ...

    # ── WAL ───────────────────────────────────────────────────────────

    def log_wal(
        self,
        wal_id: str,
        operation: str,
        target: str,
        payload_hash: str,
        payload: str,
    ) -> None:
        """Write a pending WAL entry."""
        ...

    def commit_wal(self, wal_id: str) -> None:
        """Mark a WAL entry as committed."""
        ...

    def get_pending_wal(self) -> list[dict]:
        """Return all WAL entries with status ``'pending'``."""
        ...

    def cleanup_wal(self, max_age_days: int = 7) -> int:
        """Remove committed WAL entries older than *max_age_days*."""
        ...

    # ── Lifecycle ─────────────────────────────────────────────────────

    def close(self) -> None:
        """Release resources (connections, file handles)."""
        ...

    def health_check(self) -> dict:
        """Return ``{"status": "ok", "backend": "...", ...}`` or error info."""
        ...
