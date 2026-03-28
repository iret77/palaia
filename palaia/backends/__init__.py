"""Pluggable storage backends for palaia.

Provider chain pattern (like embedding providers):
1. Config/env: database_url → PostgreSQL + pgvector
2. Default → SQLite + sqlite-vec (zero-config)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .protocol import StorageBackend

logger = logging.getLogger(__name__)


def create_backend(palaia_root: Path, config: dict) -> StorageBackend:
    """Create the appropriate storage backend.

    Detection order:
    1. Config key ``database_url`` → PostgreSQL + pgvector
    2. Env var ``PALAIA_DATABASE_URL`` → PostgreSQL + pgvector
    3. Config key ``database_backend`` forced to ``"sqlite"`` → SQLite
    4. Default → SQLite + sqlite-vec (zero-config)
    """

    forced = config.get("database_backend", "auto")
    database_url = config.get("database_url") or os.environ.get("PALAIA_DATABASE_URL")

    if database_url and forced != "sqlite":
        try:
            from .postgres import PostgresBackend

            backend = PostgresBackend(database_url)
            logger.info("Storage backend: PostgreSQL + pgvector (%s)", _mask_url(database_url))
            return backend
        except ImportError:
            logger.warning("psycopg not installed — falling back to SQLite. "
                           "Install with: pip install 'palaia[postgres]'")
        except Exception as e:
            logger.warning("PostgreSQL connection failed (%s) — falling back to SQLite", e)

    from .sqlite import SQLiteBackend

    backend = SQLiteBackend(palaia_root)
    logger.info("Storage backend: SQLite (%s)", backend.db_path)
    return backend


def _mask_url(url: str) -> str:
    """Mask password in database URL for logging."""
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    if parsed.password:
        masked = parsed._replace(
            netloc=f"{parsed.username}:****@{parsed.hostname}"
            + (f":{parsed.port}" if parsed.port else "")
        )
        return urlunparse(masked)
    return url
