"""Migrate flat-file indexes to storage backend.

Reads existing metadata.json, embeddings.json, and wal/ files,
inserts them into the active backend, and renames old files to .migrated.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class MigrationResult:
    entries_migrated: int = 0
    embeddings_migrated: int = 0
    wal_entries_migrated: int = 0
    errors: list[str] | None = None

    @property
    def total(self) -> int:
        return self.entries_migrated + self.embeddings_migrated + self.wal_entries_migrated


def needs_migration(palaia_root: Path) -> bool:
    """Check if there are flat-file indexes that should be migrated."""
    metadata_json = palaia_root / "index" / "metadata.json"
    embeddings_json = palaia_root / "index" / "embeddings.json"
    wal_dir = palaia_root / "wal"

    has_json = metadata_json.exists() or embeddings_json.exists()
    has_wal_files = wal_dir.exists() and any(wal_dir.glob("*.json"))

    return has_json or has_wal_files


def migrate_to_backend(palaia_root: Path, backend: object) -> MigrationResult:
    """Migrate flat-file data into the active storage backend.

    This function is idempotent — running it multiple times is safe.
    Old files are renamed to ``.migrated`` (not deleted).
    """
    result = MigrationResult(errors=[])

    # 1. Migrate metadata.json → entries table
    metadata_json = palaia_root / "index" / "metadata.json"
    if metadata_json.exists():
        result.entries_migrated = _migrate_metadata(metadata_json, backend, result.errors)

    # 2. Migrate embeddings.json → embeddings table
    embeddings_json = palaia_root / "index" / "embeddings.json"
    if embeddings_json.exists():
        result.embeddings_migrated = _migrate_embeddings(embeddings_json, backend, result.errors)

    # 3. Migrate wal/*.json → wal_log table
    wal_dir = palaia_root / "wal"
    if wal_dir.exists():
        result.wal_entries_migrated = _migrate_wal(wal_dir, backend, result.errors)

    # 4. If no metadata.json was found, do a full disk scan
    if not metadata_json.exists() and result.entries_migrated == 0:
        result.entries_migrated = _scan_entries_from_disk(palaia_root, backend, result.errors)

    if result.total > 0:
        logger.info(
            "Migration complete: %d entries, %d embeddings, %d WAL entries",
            result.entries_migrated, result.embeddings_migrated, result.wal_entries_migrated,
        )

    if result.errors:
        logger.warning("Migration had %d errors", len(result.errors))

    return result


def _migrate_metadata(path: Path, backend: object, errors: list[str]) -> int:
    """Read metadata.json and insert into backend."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        errors.append(f"metadata.json: {e}")
        return 0

    count = 0
    for entry_id, meta in data.items():
        try:
            tier = meta.pop("tier", "hot")
            backend.upsert_entry(entry_id, meta, tier)
            count += 1
        except Exception as e:
            errors.append(f"entry {entry_id}: {e}")

    # Rename source file.
    _safe_rename(path)
    return count


def _migrate_embeddings(path: Path, backend: object, errors: list[str]) -> int:
    """Read embeddings.json and insert into backend."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        errors.append(f"embeddings.json: {e}")
        return 0

    count = 0
    for entry_id, info in data.items():
        try:
            vector = info.get("vector", [])
            model = info.get("model", "unknown")
            dim = info.get("dim", len(vector))
            if vector:
                backend.set_embedding(entry_id, vector, model, dim)
                count += 1
        except Exception as e:
            errors.append(f"embedding {entry_id}: {e}")

    _safe_rename(path)
    return count


def _migrate_wal(wal_dir: Path, backend: object, errors: list[str]) -> int:
    """Read WAL JSON files and insert into backend."""
    count = 0
    for wal_file in sorted(wal_dir.glob("*.json")):
        try:
            data = json.loads(wal_file.read_text(encoding="utf-8"))
            backend.log_wal(
                wal_id=data["id"],
                operation=data.get("operation", "write"),
                target=data.get("target", ""),
                payload_hash=data.get("payload_hash", ""),
                payload=data.get("payload", ""),
            )
            if data.get("status") == "committed":
                backend.commit_wal(data["id"])
            _safe_rename(wal_file)
            count += 1
        except Exception as e:
            errors.append(f"wal {wal_file.name}: {e}")

    return count


def _scan_entries_from_disk(palaia_root: Path, backend: object, errors: list[str]) -> int:
    """Full disk scan of tier directories as fallback."""
    from palaia.entry import parse_entry

    count = 0
    for tier in ("hot", "warm", "cold"):
        tier_dir = palaia_root / tier
        if not tier_dir.exists():
            continue
        for entry_file in tier_dir.glob("*.md"):
            try:
                text = entry_file.read_text(encoding="utf-8")
                meta, _body = parse_entry(text)
                if meta.get("id"):
                    backend.upsert_entry(meta["id"], meta, tier)
                    count += 1
            except Exception as e:
                errors.append(f"disk scan {entry_file.name}: {e}")

    return count


def _safe_rename(path: Path) -> None:
    """Rename a file to .migrated (idempotent)."""
    target = path.with_suffix(path.suffix + ".migrated")
    try:
        if not target.exists():
            path.rename(target)
            logger.debug("Renamed %s → %s", path.name, target.name)
    except OSError as e:
        logger.warning("Could not rename %s: %s", path.name, e)
