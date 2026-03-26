"""Tests for flat-file → backend migration."""

from __future__ import annotations

import json

import pytest

from palaia.backends.migrate import MigrationResult, migrate_to_backend, needs_migration
from palaia.backends.sqlite import SQLiteBackend


@pytest.fixture
def palaia_root(tmp_path):
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    return root


@pytest.fixture
def backend(palaia_root):
    return SQLiteBackend(palaia_root)


class TestNeedsMigration:
    def test_no_files_no_migration(self, palaia_root):
        assert needs_migration(palaia_root) is False

    def test_metadata_json_triggers(self, palaia_root):
        (palaia_root / "index" / "metadata.json").write_text("{}")
        assert needs_migration(palaia_root) is True

    def test_embeddings_json_triggers(self, palaia_root):
        (palaia_root / "index" / "embeddings.json").write_text("{}")
        assert needs_migration(palaia_root) is True

    def test_wal_files_trigger(self, palaia_root):
        (palaia_root / "wal" / "test.json").write_text("{}")
        assert needs_migration(palaia_root) is True


class TestMigrateMetadata:
    def test_migrate_metadata(self, palaia_root, backend):
        metadata = {
            "entry-1": {
                "id": "entry-1",
                "title": "Test Entry",
                "scope": "team",
                "type": "memory",
                "content_hash": "abc123",
                "tier": "hot",
                "tags": ["tag1"],
            },
            "entry-2": {
                "id": "entry-2",
                "title": "Second",
                "scope": "private",
                "type": "task",
                "tier": "warm",
                "tags": [],
            },
        }
        (palaia_root / "index" / "metadata.json").write_text(json.dumps(metadata))

        result = migrate_to_backend(palaia_root, backend)
        assert result.entries_migrated == 2

        # Verify entries are in backend
        e1 = backend.get_entry("entry-1")
        assert e1 is not None
        assert e1["title"] == "Test Entry"
        assert e1["tier"] == "hot"

        e2 = backend.get_entry("entry-2")
        assert e2 is not None
        assert e2["tier"] == "warm"

        # Source file renamed
        assert not (palaia_root / "index" / "metadata.json").exists()
        assert (palaia_root / "index" / "metadata.json.migrated").exists()


class TestMigrateEmbeddings:
    def test_migrate_embeddings(self, palaia_root, backend):
        # Need entries first for FK
        backend.upsert_entry("e1", {"content_hash": "h1"}, "hot")

        embeddings = {
            "e1": {
                "vector": [0.1, 0.2, 0.3],
                "model": "test-model",
                "dim": 3,
            }
        }
        (palaia_root / "index" / "embeddings.json").write_text(json.dumps(embeddings))

        result = migrate_to_backend(palaia_root, backend)
        assert result.embeddings_migrated == 1

        emb = backend.get_embedding("e1")
        assert emb is not None
        vec, model, dim = emb
        assert model == "test-model"
        assert len(vec) == 3


class TestMigrateWAL:
    def test_migrate_wal(self, palaia_root, backend):
        wal_entry = {
            "id": "wal-1",
            "timestamp": "2026-03-26T10:00:00+00:00",
            "operation": "write",
            "target": "hot/entry-1.md",
            "payload_hash": "abc",
            "status": "committed",
            "payload": "---\nid: entry-1\n---\n\nBody",
        }
        (palaia_root / "wal" / "wal-1.json").write_text(json.dumps(wal_entry))

        result = migrate_to_backend(palaia_root, backend)
        assert result.wal_entries_migrated == 1

        # WAL file renamed
        assert not (palaia_root / "wal" / "wal-1.json").exists()
        assert (palaia_root / "wal" / "wal-1.json.migrated").exists()


class TestDiskScanFallback:
    def test_scan_entries_from_disk(self, palaia_root, backend):
        """When no metadata.json exists, scan tier directories."""
        entry_text = "---\nid: disk-1\ntitle: Disk Entry\nscope: team\n---\n\nBody text\n"
        (palaia_root / "hot" / "disk-1.md").write_text(entry_text)

        result = migrate_to_backend(palaia_root, backend)
        assert result.entries_migrated == 1

        e = backend.get_entry("disk-1")
        assert e is not None
        assert e["title"] == "Disk Entry"


class TestIdempotency:
    def test_double_migration(self, palaia_root, backend):
        """Running migration twice should be safe."""
        metadata = {"e1": {"id": "e1", "title": "T", "tier": "hot"}}
        (palaia_root / "index" / "metadata.json").write_text(json.dumps(metadata))

        r1 = migrate_to_backend(palaia_root, backend)
        assert r1.entries_migrated == 1

        # Second run — file is already .migrated
        r2 = migrate_to_backend(palaia_root, backend)
        assert r2.entries_migrated == 0
