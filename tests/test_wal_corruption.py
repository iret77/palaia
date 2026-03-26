"""Tests for WAL corruption recovery — graceful degradation."""

import json

import pytest

from palaia.store import Store
from palaia.wal import WAL, WALEntry


# ── Corrupt JSON in WAL files ─────────────────────────────────


def test_get_pending_skips_corrupt_json(palaia_root):
    """Corrupt WAL files should be skipped, not crash get_pending."""
    wal = WAL(palaia_root)

    # Write a valid pending entry
    valid = WALEntry(
        operation="write",
        target="hot/valid.md",
        payload_hash="abc",
        payload="valid content",
    )
    wal.log(valid)

    # Write a corrupt WAL file (invalid JSON)
    corrupt_path = palaia_root / "wal" / "2026-01-01T00-00-00+00-00-corrupt-id.json"
    corrupt_path.write_text("{broken json!!! not valid", encoding="utf-8")

    # get_pending should return only the valid entry
    pending = wal.get_pending()
    assert len(pending) == 1
    assert pending[0].id == valid.id


def test_get_pending_skips_missing_keys(palaia_root):
    """WAL files with missing required keys should be skipped."""
    wal = WAL(palaia_root)

    # Write a WAL file with missing required keys
    incomplete_path = palaia_root / "wal" / "2026-01-01T00-00-00+00-00-incomplete.json"
    incomplete_path.write_text(json.dumps({"status": "pending"}), encoding="utf-8")

    # Should not crash, returns empty list
    pending = wal.get_pending()
    assert len(pending) == 0


# ── Partial / truncated writes ────────────────────────────────


def test_get_pending_skips_truncated_json(palaia_root):
    """Truncated JSON (simulating crash mid-write) should be skipped."""
    wal = WAL(palaia_root)

    # Valid entry first
    valid = WALEntry(
        operation="write",
        target="hot/test.md",
        payload_hash="def",
        payload="test content",
    )
    wal.log(valid)

    # Truncated JSON (simulates crash during write)
    truncated_path = palaia_root / "wal" / "2026-01-02T00-00-00+00-00-truncated.json"
    truncated_data = json.dumps(
        {
            "id": "truncated-id",
            "timestamp": "2026-01-02T00:00:00+00:00",
            "operation": "write",
            "target": "hot/truncated.md",
            "payload_hash": "xyz",
            "status": "pending",
            "payload": "some con",  # truncated payload
        }
    )
    # Write only first half of the JSON to simulate crash
    truncated_path.write_text(truncated_data[: len(truncated_data) // 2], encoding="utf-8")

    pending = wal.get_pending()
    # Should only get the valid entry, truncated is skipped
    assert len(pending) == 1
    assert pending[0].id == valid.id


def test_recover_skips_corrupt_wal_entries(palaia_root):
    """Recovery should skip corrupt WAL files and continue with valid ones."""
    store = Store(palaia_root)
    wal = store.wal

    # Write a valid recoverable entry
    content = (
        "---\nid: recover-ok\nscope: team\n"
        "created: 2026-03-11T00:00:00+00:00\n"
        "accessed: 2026-03-11T00:00:00+00:00\n"
        "access_count: 1\ndecay_score: 1.0\n"
        "content_hash: aaa\n---\n\nRecoverable content\n"
    )
    valid = WALEntry(
        operation="write",
        target="hot/recover-ok.md",
        payload_hash="aaa",
        payload=content,
    )
    wal.log(valid)

    # Write corrupt WAL file
    corrupt_path = palaia_root / "wal" / "2026-01-03T00-00-00+00-00-corrupt.json"
    corrupt_path.write_text("not json at all", encoding="utf-8")

    # Recovery should handle both gracefully
    recovered = store.recover()
    assert recovered == 1

    # Verify the valid entry was written
    assert (palaia_root / "hot" / "recover-ok.md").exists()


# ── WAL referencing deleted entries ───────────────────────────


def test_recover_write_to_deleted_path(palaia_root):
    """WAL write entry for a path that doesn't exist yet should create it."""
    store = Store(palaia_root)
    wal = store.wal

    content = (
        "---\nid: ghost-entry\nscope: team\n"
        "created: 2026-03-11T00:00:00+00:00\n"
        "accessed: 2026-03-11T00:00:00+00:00\n"
        "access_count: 1\ndecay_score: 1.0\n"
        "content_hash: ghost\n---\n\nGhost content\n"
    )
    entry = WALEntry(
        operation="write",
        target="hot/ghost-entry.md",
        payload_hash="ghost",
        payload=content,
    )
    wal.log(entry)

    # Recover — file doesn't exist yet, should be created
    recovered = store.recover()
    assert recovered == 1
    assert (palaia_root / "hot" / "ghost-entry.md").exists()


def test_recover_delete_already_gone(palaia_root):
    """WAL delete entry for an already-deleted file should succeed silently."""
    store = Store(palaia_root)
    wal = store.wal

    entry = WALEntry(
        operation="delete",
        target="hot/already-gone.md",
        payload_hash="",
    )
    wal.log(entry)

    # File doesn't exist — recovery should not crash
    recovered = store.recover()
    assert recovered == 1


def test_recover_no_payload_rolls_back(palaia_root):
    """WAL write entry without payload should be rolled back."""
    store = Store(palaia_root)
    wal = store.wal

    entry = WALEntry(
        operation="write",
        target="hot/no-payload.md",
        payload_hash="nope",
        # No payload — can't recover
    )
    wal.log(entry)

    recovered = store.recover()
    assert recovered == 0  # Can't recover without payload

    # Verify the WAL entry is no longer pending (rolled back / committed)
    pending = wal.get_pending()
    assert len(pending) == 0


# ── Cleanup handles corrupt files ────────────────────────────


def test_cleanup_skips_corrupt_files(palaia_root):
    """WAL cleanup should skip corrupt files without crashing."""
    wal = WAL(palaia_root)

    # Write corrupt file
    corrupt_path = palaia_root / "wal" / "corrupt-cleanup.json"
    corrupt_path.write_text("}{bad", encoding="utf-8")

    # Write valid committed entry (old enough to clean)
    old = WALEntry(
        operation="write",
        target="hot/old.md",
        payload_hash="old",
    )
    old.status = "committed"
    old.timestamp = "2020-01-01T00:00:00+00:00"
    path = wal._entry_path(old)
    path.write_text(json.dumps(old.to_dict()), encoding="utf-8")

    # Cleanup should handle both without crashing
    removed = wal.cleanup(max_age_days=1)
    assert removed == 1  # Only the valid committed entry
    # Corrupt file should still exist (not touched by cleanup)
    assert corrupt_path.exists()
