"""Tests for WAL module."""

import json
import pytest
from pathlib import Path

from palaia.wal import WAL, WALEntry
from palaia.store import Store
from palaia.config import DEFAULT_CONFIG, save_config


@pytest.fixture
def palaia_root(tmp_path):
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    save_config(root, DEFAULT_CONFIG)
    return root


def test_wal_log_and_commit(palaia_root):
    wal = WAL(palaia_root)
    entry = WALEntry(operation="write", target="hot/test.md", payload_hash="abc123")
    path = wal.log(entry)
    assert path.exists()
    
    # Should be pending
    pending = wal.get_pending()
    assert len(pending) == 1
    assert pending[0].id == entry.id
    
    # Commit
    wal.commit(entry)
    pending = wal.get_pending()
    assert len(pending) == 0


def test_wal_recovery(palaia_root):
    """Test that pending WAL entries get recovered."""
    store = Store(palaia_root)
    wal = store.wal

    # Simulate a crash: WAL entry written but operation not completed
    content = "---\nid: test-123\nscope: team\ncreated: 2026-03-11T00:00:00+00:00\naccessed: 2026-03-11T00:00:00+00:00\naccess_count: 1\ndecay_score: 1.0\ncontent_hash: abc\n---\n\nTest recovery content\n"
    entry = WALEntry(
        operation="write",
        target="hot/test-123.md",
        payload_hash="abc",
        payload=content,
    )
    wal.log(entry)

    # File should NOT exist yet (simulating crash before write)
    assert not (palaia_root / "hot" / "test-123.md").exists()

    # Recovery should replay
    recovered = store.recover()
    assert recovered == 1
    assert (palaia_root / "hot" / "test-123.md").exists()

    # Verify content
    text = (palaia_root / "hot" / "test-123.md").read_text()
    assert "Test recovery content" in text


def test_wal_cleanup(palaia_root):
    wal = WAL(palaia_root)
    entry = WALEntry(operation="write", target="hot/x.md", payload_hash="h")
    wal.log(entry)
    wal.commit(entry)
    
    # Cleanup with 0 days should remove it
    removed = wal.cleanup(max_age_days=0)
    assert removed == 1
