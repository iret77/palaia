"""SQLite storage backend — zero-config default.

Uses stdlib ``sqlite3`` for metadata and WAL.  Optionally loads
``sqlite-vec`` for native vector KNN search; falls back to a pure-Python
cosine similarity implementation when the extension is unavailable.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import struct
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS entries (
    id TEXT PRIMARY KEY,
    title TEXT,
    tags TEXT DEFAULT '[]',
    scope TEXT,
    agent TEXT,
    project TEXT,
    type TEXT DEFAULT 'memory',
    status TEXT,
    priority TEXT,
    content_hash TEXT,
    created TEXT,
    accessed TEXT,
    access_count INTEGER DEFAULT 1,
    decay_score REAL,
    tier TEXT,
    instance TEXT,
    assignee TEXT,
    due_date TEXT
);

CREATE INDEX IF NOT EXISTS idx_entries_content_hash ON entries(content_hash);
CREATE INDEX IF NOT EXISTS idx_entries_tier ON entries(tier);
CREATE INDEX IF NOT EXISTS idx_entries_project ON entries(project);
CREATE INDEX IF NOT EXISTS idx_entries_type_status ON entries(type, status);
CREATE INDEX IF NOT EXISTS idx_entries_decay_score ON entries(decay_score);
CREATE INDEX IF NOT EXISTS idx_entries_scope ON entries(scope);
CREATE INDEX IF NOT EXISTS idx_entries_created ON entries(created);

CREATE TABLE IF NOT EXISTS embeddings (
    entry_id TEXT PRIMARY KEY,
    vector BLOB NOT NULL,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS wal_log (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    operation TEXT NOT NULL,
    target TEXT NOT NULL,
    payload_hash TEXT,
    status TEXT DEFAULT 'pending',
    payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_wal_status ON wal_log(status);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
"""

# Columns stored in the entries table (order matters for INSERT).
_ENTRY_COLS = [
    "id", "title", "tags", "scope", "agent", "project", "type", "status",
    "priority", "content_hash", "created", "accessed", "access_count",
    "decay_score", "tier", "instance", "assignee", "due_date",
]

# Valid ORDER BY columns (prevent SQL injection via order_by param).
_VALID_ORDER_COLS = {
    "decay_score", "created", "accessed", "access_count", "title", "type",
}


class SQLiteBackend:
    """Zero-config embedded storage backend.

    All data lives in a single ``palaia.db`` file inside the palaia root.
    """

    def __init__(self, palaia_root: Path) -> None:
        self.db_path = palaia_root / "palaia.db"
        self.conn = sqlite3.connect(
            str(self.db_path),
            isolation_level="DEFERRED",
            check_same_thread=False,
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=10000")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._has_vec = self._load_sqlite_vec()
        self._ensure_schema()

    # ── Setup ─────────────────────────────────────────────────────────

    def _load_sqlite_vec(self) -> bool:
        """Try to load sqlite-vec for native vector search."""
        try:
            import sqlite_vec  # type: ignore[import-untyped]

            self.conn.enable_load_extension(True)
            sqlite_vec.load(self.conn)
            self.conn.enable_load_extension(False)
            logger.debug("sqlite-vec loaded successfully")
            return True
        except (ImportError, Exception) as e:
            logger.debug("sqlite-vec not available (%s) — using Python fallback", e)
            return False

    def _ensure_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        self.conn.executescript(_SCHEMA_SQL)
        # Set schema version if not present.
        cur = self.conn.execute("SELECT version FROM schema_version LIMIT 1")
        row = cur.fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (_SCHEMA_VERSION,),
            )
        self.conn.commit()

    # ── Metadata ──────────────────────────────────────────────────────

    def upsert_entry(self, entry_id: str, meta: dict, tier: str) -> None:
        meta = dict(meta)
        meta["id"] = entry_id
        meta["tier"] = tier
        # Serialize tags list to JSON string.
        if isinstance(meta.get("tags"), list):
            meta["tags"] = json.dumps(meta["tags"])

        cols = ", ".join(_ENTRY_COLS)
        placeholders = ", ".join(["?"] * len(_ENTRY_COLS))
        updates = ", ".join(f"{c}=excluded.{c}" for c in _ENTRY_COLS if c != "id")
        sql = (
            f"INSERT INTO entries ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}"
        )
        values = [meta.get(c) for c in _ENTRY_COLS]
        self.conn.execute(sql, values)
        self.conn.commit()

    def get_entry(self, entry_id: str) -> dict | None:
        cur = self.conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def remove_entry(self, entry_id: str) -> None:
        self.conn.execute("DELETE FROM embeddings WHERE entry_id = ?", (entry_id,))
        self.conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        self.conn.commit()

    def find_by_hash(self, content_hash: str) -> str | None:
        cur = self.conn.execute(
            "SELECT id FROM entries WHERE content_hash = ? LIMIT 1",
            (content_hash,),
        )
        row = cur.fetchone()
        return row["id"] if row else None

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
        clauses: list[str] = []
        params: list[object] = []

        if tier is not None:
            clauses.append("tier = ?")
            params.append(tier)
        if project is not None:
            clauses.append("project = ?")
            params.append(project)
        if entry_type is not None:
            clauses.append("type = ?")
            params.append(entry_type)
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        if agent is not None:
            clauses.append("agent = ?")
            params.append(agent)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        # Validate order_by to prevent SQL injection.
        order_sql = self._safe_order_by(order_by)

        sql = f"SELECT * FROM entries{where} ORDER BY {order_sql}"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        cur = self.conn.execute(sql, params)
        return [self._row_to_dict(row) for row in cur.fetchall()]

    def all_entry_ids(self, include_cold: bool = False) -> list[str]:
        if include_cold:
            cur = self.conn.execute("SELECT id FROM entries")
        else:
            cur = self.conn.execute("SELECT id FROM entries WHERE tier != 'cold'")
        return [row["id"] for row in cur.fetchall()]

    def entry_count(self, tier: str | None = None) -> int:
        if tier:
            cur = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM entries WHERE tier = ?", (tier,)
            )
        else:
            cur = self.conn.execute("SELECT COUNT(*) as cnt FROM entries")
        return cur.fetchone()["cnt"]

    def cleanup_entries(self, valid_ids: set[str]) -> int:
        if not valid_ids:
            return 0
        # Get all IDs, then delete those not in valid_ids.
        cur = self.conn.execute("SELECT id FROM entries")
        all_ids = {row["id"] for row in cur.fetchall()}
        stale_ids = all_ids - valid_ids
        if not stale_ids:
            return 0
        placeholders = ",".join("?" * len(stale_ids))
        self.conn.execute(
            f"DELETE FROM entries WHERE id IN ({placeholders})",
            list(stale_ids),
        )
        self.conn.commit()
        return len(stale_ids)

    # ── Embeddings ────────────────────────────────────────────────────

    def get_embedding(self, entry_id: str) -> tuple[list[float], str, int] | None:
        cur = self.conn.execute(
            "SELECT vector, model, dim FROM embeddings WHERE entry_id = ?",
            (entry_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        vector = _blob_to_floats(row["vector"])
        return vector, row["model"], row["dim"]

    def set_embedding(
        self, entry_id: str, vector: list[float], model: str, dim: int
    ) -> None:
        blob = _floats_to_blob(vector)
        self.conn.execute(
            "INSERT INTO embeddings (entry_id, vector, model, dim) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(entry_id) DO UPDATE SET vector=excluded.vector, "
            "model=excluded.model, dim=excluded.dim",
            (entry_id, blob, model, dim),
        )
        self.conn.commit()

    def invalidate_embedding(self, entry_id: str) -> None:
        self.conn.execute(
            "DELETE FROM embeddings WHERE entry_id = ?", (entry_id,)
        )
        self.conn.commit()

    def cleanup_embeddings(self, valid_ids: set[str]) -> int:
        if not valid_ids:
            return 0
        cur = self.conn.execute("SELECT entry_id FROM embeddings")
        all_ids = {row["entry_id"] for row in cur.fetchall()}
        stale = all_ids - valid_ids
        if not stale:
            return 0
        placeholders = ",".join("?" * len(stale))
        self.conn.execute(
            f"DELETE FROM embeddings WHERE entry_id IN ({placeholders})",
            list(stale),
        )
        self.conn.commit()
        return len(stale)

    # ── Vector search ─────────────────────────────────────────────────

    def vector_search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        *,
        tier: str | None = None,
        entry_type: str | None = None,
    ) -> list[tuple[str, float]]:
        """Find nearest embedding vectors by cosine similarity.

        Uses Python-level brute-force (sufficient for <100K entries).
        """
        # Build filter for entry IDs if needed.
        if tier or entry_type:
            clauses: list[str] = []
            params: list[object] = []
            if tier:
                clauses.append("e.tier = ?")
                params.append(tier)
            if entry_type:
                clauses.append("e.type = ?")
                params.append(entry_type)
            where = " AND ".join(clauses)
            cur = self.conn.execute(
                f"SELECT emb.entry_id, emb.vector FROM embeddings emb "
                f"JOIN entries e ON emb.entry_id = e.id WHERE {where}",
                params,
            )
        else:
            cur = self.conn.execute("SELECT entry_id, vector FROM embeddings")

        results: list[tuple[str, float]] = []
        for row in cur.fetchall():
            stored = _blob_to_floats(row["vector"] if isinstance(row, sqlite3.Row) else row[1])
            entry_id = row["entry_id"] if isinstance(row, sqlite3.Row) else row[0]
            sim = _cosine_similarity(query_vector, stored)
            results.append((entry_id, sim))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    # ── WAL ───────────────────────────────────────────────────────────

    def log_wal(
        self,
        wal_id: str,
        operation: str,
        target: str,
        payload_hash: str,
        payload: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO wal_log (id, timestamp, operation, target, "
            "payload_hash, status, payload) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (wal_id, now, operation, target, payload_hash, payload),
        )
        self.conn.commit()

    def commit_wal(self, wal_id: str) -> None:
        self.conn.execute(
            "UPDATE wal_log SET status = 'committed' WHERE id = ?",
            (wal_id,),
        )
        self.conn.commit()

    def get_pending_wal(self) -> list[dict]:
        cur = self.conn.execute(
            "SELECT * FROM wal_log WHERE status = 'pending' ORDER BY timestamp"
        )
        return [dict(row) for row in cur.fetchall()]

    def cleanup_wal(self, max_age_days: int = 7) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        cur = self.conn.execute(
            "DELETE FROM wal_log WHERE status IN ('committed', 'rolled_back') "
            "AND timestamp < ?",
            (cutoff,),
        )
        self.conn.commit()
        return cur.rowcount

    # ── Lifecycle ─────────────────────────────────────────────────────

    def close(self) -> None:
        self.conn.close()

    def health_check(self) -> dict:
        try:
            cur = self.conn.execute("SELECT COUNT(*) as cnt FROM entries")
            count = cur.fetchone()["cnt"]
            return {
                "status": "ok",
                "backend": "sqlite",
                "path": str(self.db_path),
                "entries": count,
                "sqlite_vec": self._has_vec,
            }
        except Exception as e:
            return {"status": "error", "backend": "sqlite", "error": str(e)}

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        """Convert a sqlite3.Row to a plain dict with tags deserialized."""
        d = dict(row)
        # Deserialize tags from JSON string.
        if isinstance(d.get("tags"), str):
            try:
                d["tags"] = json.loads(d["tags"])
            except (json.JSONDecodeError, TypeError):
                d["tags"] = []
        return d

    @staticmethod
    def _safe_order_by(order_by: str) -> str:
        """Validate and return a safe ORDER BY clause."""
        parts = order_by.strip().split()
        if len(parts) == 1:
            col = parts[0]
            direction = "ASC"
        elif len(parts) == 2:
            col, direction = parts
        else:
            col, direction = "decay_score", "DESC"

        col = col.lower()
        direction = direction.upper()
        if col not in _VALID_ORDER_COLS:
            col = "decay_score"
        if direction not in ("ASC", "DESC"):
            direction = "DESC"
        return f"{col} {direction}"


# ── Vector serialization ──────────────────────────────────────────────


def _floats_to_blob(vector: list[float]) -> bytes:
    """Pack a list of floats into a compact binary blob (float32)."""
    return struct.pack(f"<{len(vector)}f", *vector)


def _blob_to_floats(blob: bytes) -> list[float]:
    """Unpack a binary blob back to a list of floats."""
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
