"""Tests for backup restore: disk entries → DB rebuild (#fix/backup-restore)."""

from __future__ import annotations

import json
import sqlite3

import pytest

from palaia.backends.migrate import needs_migration
from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    """Create a minimal .palaia directory with SQLite DB but no entries.

    Uses Store() to initialise the DB with the correct schema, then verifies
    the DB is empty before returning.
    """
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    config = {"version": 1, "agent": "test", "embedding_chain": ["bm25"]}
    (root / "config.json").write_text(json.dumps(config))
    # Initialise DB with correct schema by creating a Store
    store = Store(root)
    # Ensure the DB exists and has the entries table
    db_path = root / "palaia.db"
    assert db_path.exists(), f"DB not at {db_path}"
    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT COUNT(*) FROM entries").fetchone()
    assert row[0] == 0
    conn.close()
    return root


def _write_fake_entry(root, entry_id, tier="hot", agent="test", tags=None):
    """Write a minimal .md entry file to a tier directory."""
    tags = tags or []
    meta = {"id": entry_id, "agent": agent, "tags": tags, "scope": "team"}
    header = json.dumps(meta)
    content = f"---\n{header}\n---\nTest body for {entry_id}"
    (root / tier / f"{entry_id}.md").write_text(content)


class TestNeedsMigrationDetectsOrphans:
    def test_empty_disk_empty_db(self, palaia_root):
        """No entries anywhere → no migration needed."""
        assert needs_migration(palaia_root) is False

    def test_disk_entries_empty_db(self, palaia_root):
        """Entries on disk but 0 in DB → migration needed."""
        _write_fake_entry(palaia_root, "abc-12345678")
        assert needs_migration(palaia_root) is True

    def test_disk_entries_populated_db(self, palaia_root):
        """Entries on disk AND in DB → no migration needed."""
        _write_fake_entry(palaia_root, "abc-12345678")
        db_path = palaia_root / "palaia.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO entries (id, tier) VALUES (?, ?)",
            ("abc-12345678", "hot"),
        )
        conn.commit()
        conn.close()
        assert needs_migration(palaia_root) is False

    def test_old_json_still_detected(self, palaia_root):
        """Old metadata.json still triggers migration (existing behavior)."""
        (palaia_root / "index" / "metadata.json").write_text("{}")
        assert needs_migration(palaia_root) is True


class TestDoctorFixRebuildsIndex:
    def test_fix_rebuilds_from_disk(self, palaia_root):
        """doctor --fix rebuilds DB from disk entries."""
        from palaia.doctor.fixes import apply_fixes

        # Place entries on disk
        _write_fake_entry(palaia_root, "entry-11111111", agent="worker")
        _write_fake_entry(palaia_root, "entry-22222222", agent="worker")
        _write_fake_entry(palaia_root, "entry-33333333", tier="warm", agent="bot")

        # Simulate the check result that doctor would produce
        results = [
            {
                "name": "storage_backend",
                "label": "Storage backend",
                "status": "error",
                "message": "3 entries on disk but 0 in database — migration may have failed",
                "fixable": True,
            }
        ]

        actions = apply_fixes(palaia_root, results)
        assert any("Rebuilt metadata index" in a for a in actions), f"Expected rebuild action, got: {actions}"
        assert any("3 entries" in a for a in actions), f"Expected 3 entries indexed, got: {actions}"

        # Verify DB now has entries
        db_path = palaia_root / "palaia.db"
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT COUNT(*) FROM entries").fetchone()
        conn.close()
        assert row[0] == 3

    def test_fix_no_action_when_no_orphans(self, palaia_root):
        """doctor --fix does nothing when there's no orphan problem."""
        from palaia.doctor.fixes import apply_fixes

        results = [
            {
                "name": "storage_backend",
                "label": "Storage backend",
                "status": "ok",
                "message": "SQLite OK (0 entries)",
            }
        ]

        actions = apply_fixes(palaia_root, results)
        assert not any("Rebuilt" in a for a in actions)


class TestAutoMigrateOnStoreInit:
    def test_store_init_triggers_rebuild(self, palaia_root):
        """Store() init detects orphaned disk entries and rebuilds."""
        _write_fake_entry(palaia_root, "restore-1111111")
        _write_fake_entry(palaia_root, "restore-2222222")

        from palaia.store import Store

        store = Store(palaia_root)
        # After init, the entries should be in the DB via _auto_migrate
        entry = store.read("restore-1111111")
        assert entry is not None, "Entry should be readable after auto-migrate"
