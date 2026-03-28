"""PostgreSQL + pgvector storage backend — for distributed agent teams.

Requires:
  pip install 'palaia[postgres]'     # installs psycopg
  PostgreSQL server with:  CREATE EXTENSION IF NOT EXISTS vector;
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """\
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS entries (
    id TEXT PRIMARY KEY,
    title TEXT,
    tags JSONB DEFAULT '[]',
    scope TEXT,
    agent TEXT,
    project TEXT,
    type TEXT DEFAULT 'memory',
    status TEXT,
    priority TEXT,
    content_hash TEXT,
    created TIMESTAMPTZ,
    accessed TIMESTAMPTZ,
    access_count INTEGER DEFAULT 1,
    decay_score DOUBLE PRECISION,
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

CREATE TABLE IF NOT EXISTS embeddings (
    entry_id TEXT PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
    vector vector,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS wal_log (
    id TEXT PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
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

# HNSW index created separately (needs entries first).
_HNSW_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_embeddings_vector
    ON embeddings USING hnsw (vector vector_cosine_ops);
"""

_ENTRY_COLS = [
    "id", "title", "tags", "scope", "agent", "project", "type", "status",
    "priority", "content_hash", "created", "accessed", "access_count",
    "decay_score", "tier", "instance", "assignee", "due_date",
]

_VALID_ORDER_COLS = {
    "decay_score", "created", "accessed", "access_count", "title", "type",
}


class PostgresBackend:
    """Production-grade storage for distributed agent teams.

    Activate via:
      PALAIA_DATABASE_URL=postgresql://user:pass@host/dbname
      palaia config set database_url postgresql://...
    """

    def __init__(self, database_url: str) -> None:
        import psycopg  # type: ignore[import-untyped]

        self.database_url = database_url
        self.conn = psycopg.connect(database_url, autocommit=False)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self.conn.cursor() as cur:
            # Split into individual statements (executescript not available).
            for stmt in _SCHEMA_SQL.split(";"):
                stmt = stmt.strip()
                if stmt:
                    cur.execute(stmt)
            # Check schema version.
            cur.execute("SELECT version FROM schema_version LIMIT 1")
            row = cur.fetchone()
            if row is None:
                cur.execute("INSERT INTO schema_version (version) VALUES (1)")
        self.conn.commit()

        # Try to create HNSW index (may fail if no embeddings yet — OK).
        try:
            with self.conn.cursor() as cur:
                cur.execute(_HNSW_INDEX_SQL)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            logger.debug("HNSW index creation deferred (no embeddings yet)")

    # ── Metadata ──────────────────────────────────────────────────────

    def upsert_entry(self, entry_id: str, meta: dict, tier: str) -> None:
        meta = dict(meta)
        meta["id"] = entry_id
        meta["tier"] = tier
        # Tags as JSONB.
        if isinstance(meta.get("tags"), list):
            meta["tags"] = json.dumps(meta["tags"])

        cols = ", ".join(_ENTRY_COLS)
        placeholders = ", ".join(["%s"] * len(_ENTRY_COLS))
        updates = ", ".join(
            f"{c}=EXCLUDED.{c}" for c in _ENTRY_COLS if c != "id"
        )
        sql = (
            f"INSERT INTO entries ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}"
        )
        values = [meta.get(c) for c in _ENTRY_COLS]
        with self.conn.cursor() as cur:
            cur.execute(sql, values)
        self.conn.commit()

    def get_entry(self, entry_id: str) -> dict | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM entries WHERE id = %s", (entry_id,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [desc[0] for desc in cur.description]
            return self._row_to_dict(dict(zip(cols, row)))

    def remove_entry(self, entry_id: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM embeddings WHERE entry_id = %s", (entry_id,))
            cur.execute("DELETE FROM entries WHERE id = %s", (entry_id,))
        self.conn.commit()

    def find_by_hash(self, content_hash: str) -> str | None:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM entries WHERE content_hash = %s LIMIT 1",
                (content_hash,),
            )
            row = cur.fetchone()
            return row[0] if row else None

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
            clauses.append("tier = %s")
            params.append(tier)
        if project is not None:
            clauses.append("project = %s")
            params.append(project)
        if entry_type is not None:
            clauses.append("type = %s")
            params.append(entry_type)
        if scope is not None:
            clauses.append("scope = %s")
            params.append(scope)
        if agent is not None:
            clauses.append("agent = %s")
            params.append(agent)
        if status is not None:
            clauses.append("status = %s")
            params.append(status)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        order_sql = self._safe_order_by(order_by)
        sql = f"SELECT * FROM entries{where} ORDER BY {order_sql}"
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)

        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [desc[0] for desc in cur.description]
            return [self._row_to_dict(dict(zip(cols, row))) for row in cur.fetchall()]

    def all_entry_ids(self, include_cold: bool = False) -> list[str]:
        with self.conn.cursor() as cur:
            if include_cold:
                cur.execute("SELECT id FROM entries")
            else:
                cur.execute("SELECT id FROM entries WHERE tier != 'cold'")
            return [row[0] for row in cur.fetchall()]

    def entry_count(self, tier: str | None = None) -> int:
        with self.conn.cursor() as cur:
            if tier:
                cur.execute(
                    "SELECT COUNT(*) FROM entries WHERE tier = %s", (tier,)
                )
            else:
                cur.execute("SELECT COUNT(*) FROM entries")
            return cur.fetchone()[0]

    def cleanup_entries(self, valid_ids: set[str]) -> int:
        if not valid_ids:
            return 0
        with self.conn.cursor() as cur:
            cur.execute("SELECT id FROM entries")
            all_ids = {row[0] for row in cur.fetchall()}
            stale_ids = all_ids - valid_ids
            if not stale_ids:
                return 0
            placeholders = ",".join(["%s"] * len(stale_ids))
            cur.execute(
                f"DELETE FROM entries WHERE id IN ({placeholders})",
                list(stale_ids),
            )
        self.conn.commit()
        return len(stale_ids)

    # ── Embeddings ────────────────────────────────────────────────────

    def get_embedding(self, entry_id: str) -> tuple[list[float], str, int] | None:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT vector, model, dim FROM embeddings WHERE entry_id = %s",
                (entry_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            # pgvector returns a list/string representation.
            vector = row[0]
            if isinstance(vector, str):
                vector = [float(x) for x in vector.strip("[]").split(",")]
            elif hasattr(vector, "tolist"):
                vector = vector.tolist()
            return list(vector), row[1], row[2]

    def set_embedding(
        self, entry_id: str, vector: list[float], model: str, dim: int
    ) -> None:
        # pgvector expects a string like '[0.1,0.2,0.3]'.
        vec_str = "[" + ",".join(str(v) for v in vector) + "]"
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO embeddings (entry_id, vector, model, dim) "
                "VALUES (%s, %s::vector, %s, %s) "
                "ON CONFLICT(entry_id) DO UPDATE SET vector=EXCLUDED.vector, "
                "model=EXCLUDED.model, dim=EXCLUDED.dim",
                (entry_id, vec_str, model, dim),
            )
        self.conn.commit()

    def invalidate_embedding(self, entry_id: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM embeddings WHERE entry_id = %s", (entry_id,)
            )
        self.conn.commit()

    def cleanup_embeddings(self, valid_ids: set[str]) -> int:
        if not valid_ids:
            return 0
        with self.conn.cursor() as cur:
            cur.execute("SELECT entry_id FROM embeddings")
            all_ids = {row[0] for row in cur.fetchall()}
            stale = all_ids - valid_ids
            if not stale:
                return 0
            placeholders = ",".join(["%s"] * len(stale))
            cur.execute(
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
        """ANN search using pgvector's cosine distance operator."""
        vec_str = "[" + ",".join(str(v) for v in query_vector) + "]"
        clauses: list[str] = []
        params: list[object] = [vec_str]

        if tier:
            clauses.append("e.tier = %s")
            params.append(tier)
        if entry_type:
            clauses.append("e.type = %s")
            params.append(entry_type)

        where = (" AND " + " AND ".join(clauses)) if clauses else ""
        params.append(top_k)

        sql = (
            "SELECT emb.entry_id, 1 - (emb.vector <=> %s::vector) AS similarity "
            "FROM embeddings emb "
            "JOIN entries e ON emb.entry_id = e.id "
            f"WHERE TRUE {where} "
            "ORDER BY emb.vector <=> %s::vector "
            "LIMIT %s"
        )
        # Need to pass vec_str twice (once for similarity calc, once for ORDER BY).
        all_params = [vec_str] + list(params[1:-1]) + [vec_str, top_k]

        with self.conn.cursor() as cur:
            cur.execute(sql, all_params)
            return [(row[0], float(row[1])) for row in cur.fetchall()]

    # ── WAL ───────────────────────────────────────────────────────────

    def log_wal(
        self,
        wal_id: str,
        operation: str,
        target: str,
        payload_hash: str,
        payload: str,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO wal_log (id, operation, target, payload_hash, "
                "status, payload) VALUES (%s, %s, %s, %s, 'pending', %s)",
                (wal_id, operation, target, payload_hash, payload),
            )
        self.conn.commit()

    def commit_wal(self, wal_id: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE wal_log SET status = 'committed' WHERE id = %s",
                (wal_id,),
            )
        self.conn.commit()

    def get_pending_wal(self) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM wal_log WHERE status = 'pending' "
                "ORDER BY timestamp"
            )
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def cleanup_wal(self, max_age_days: int = 7) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        with self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM wal_log WHERE status IN ('committed', 'rolled_back') "
                "AND timestamp < %s",
                (cutoff,),
            )
            count = cur.rowcount
        self.conn.commit()
        return count

    # ── Lifecycle ─────────────────────────────────────────────────────

    def close(self) -> None:
        self.conn.close()

    def health_check(self) -> dict:
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM entries")
                count = cur.fetchone()[0]
                # Check pgvector extension.
                cur.execute(
                    "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
                )
                vec_row = cur.fetchone()
                pgvector_version = vec_row[0] if vec_row else None
            return {
                "status": "ok",
                "backend": "postgres",
                "entries": count,
                "pgvector": pgvector_version,
            }
        except Exception as e:
            return {"status": "error", "backend": "postgres", "error": str(e)}

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(d: dict) -> dict:
        """Normalize a row dict (tags, timestamps)."""
        # Tags: JSONB returns as list already in psycopg3.
        if isinstance(d.get("tags"), str):
            try:
                d["tags"] = json.loads(d["tags"])
            except (json.JSONDecodeError, TypeError):
                d["tags"] = []
        # Timestamps: convert to ISO strings for compatibility.
        for key in ("created", "accessed"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = val.isoformat()
        return d

    @staticmethod
    def _safe_order_by(order_by: str) -> str:
        parts = order_by.strip().split()
        col = parts[0].lower() if parts else "decay_score"
        direction = parts[1].upper() if len(parts) > 1 else "DESC"
        if col not in _VALID_ORDER_COLS:
            col = "decay_score"
        if direction not in ("ASC", "DESC"):
            direction = "DESC"
        return f"{col} {direction}"
