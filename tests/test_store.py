"""Tests for the memory store."""

import pytest
from pathlib import Path

from palaia.config import DEFAULT_CONFIG, save_config
from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    save_config(root, DEFAULT_CONFIG)
    return root


def test_write_and_read(palaia_root):
    store = Store(palaia_root)
    entry_id = store.write("Hello memory world", scope="team", agent="test")
    assert entry_id is not None
    
    result = store.read(entry_id)
    assert result is not None
    meta, body = result
    assert "Hello memory world" in body
    assert meta["scope"] == "team"


def test_dedup(palaia_root):
    store = Store(palaia_root)
    id1 = store.write("Same content here")
    id2 = store.write("Same content here")
    assert id1 == id2  # Deduplicated


def test_write_with_tags(palaia_root):
    store = Store(palaia_root)
    entry_id = store.write(
        "Tagged memory",
        scope="public",
        tags=["test", "example"],
        title="Test Entry",
    )
    result = store.read(entry_id)
    assert result is not None
    meta, body = result
    assert meta["scope"] == "public"


def test_list_entries(palaia_root):
    store = Store(palaia_root)
    store.write("Entry 1")
    store.write("Entry 2")
    store.write("Entry 3")
    
    entries = store.list_entries("hot")
    assert len(entries) == 3


def test_status(palaia_root):
    store = Store(palaia_root)
    store.write("Test")
    info = store.status()
    assert info["entries"]["hot"] == 1
    assert info["total"] == 1


def test_scope_enforcement_private(palaia_root):
    store = Store(palaia_root)
    entry_id = store.write("Secret stuff", scope="private", agent="agent1")
    
    # Same agent can read
    result = store.read(entry_id, agent="agent1")
    assert result is not None
    
    # Different agent cannot
    result = store.read(entry_id, agent="agent2")
    assert result is None
