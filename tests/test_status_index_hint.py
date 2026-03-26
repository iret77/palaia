"""Tests for index hint in palaia status (#47)."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from palaia import __version__
from palaia.config import DEFAULT_CONFIG, save_config
from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    """Create a fresh .palaia directory with agent set."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    config = dict(DEFAULT_CONFIG)
    config["store_version"] = __version__
    config["agent"] = "TestAgent"
    save_config(root, config)
    return root


def _run_status(palaia_root, *, json_mode=False):
    """Run palaia status via subprocess, return (stdout, stderr, returncode)."""
    cmd = [sys.executable, "-m", "palaia", "status"]
    if json_mode:
        cmd.append("--json")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env={**dict(__import__("os").environ), "PALAIA_HOME": str(palaia_root)},
    )
    return result.stdout, result.stderr, result.returncode


def test_hint_when_index_behind(palaia_root):
    """When entries exist but none are indexed, hint should mention warmup."""
    import uuid

    # Create entry files directly to bypass incremental indexing on write
    for i in range(3):
        eid = str(uuid.uuid4())[:8]
        content = f"---\nid: {eid}\ntitle: Entry {i}\nagent: test-agent\nscope: team\n---\nEntry {i}"
        (palaia_root / "hot" / f"{eid}.md").write_text(content)

    stdout, stderr, rc = _run_status(palaia_root)
    assert rc == 0
    assert "not indexed" in stderr
    assert "palaia warmup" in stderr


def test_no_hint_when_fully_indexed(palaia_root):
    """When all entries are indexed, hint should say fully indexed."""
    store = Store(palaia_root)
    eid1 = store.write("Entry one")
    eid2 = store.write("Entry two")

    # Manually populate the embedding cache via store's backend-aware cache
    store.embedding_cache.set_cached(eid1, [0.1, 0.2, 0.3], model="test")
    store.embedding_cache.set_cached(eid2, [0.4, 0.5, 0.6], model="test")

    stdout, stderr, rc = _run_status(palaia_root)
    assert rc == 0
    assert "fully indexed" in stderr
    assert "not indexed" not in stderr


def test_json_contains_index_hint(palaia_root):
    """JSON output should contain index_hint field."""
    import uuid

    # Create entry file directly to bypass incremental indexing on write
    eid = str(uuid.uuid4())[:8]
    content = f"---\nid: {eid}\ntitle: Entry one\nagent: test-agent\nscope: team\n---\nEntry one"
    (palaia_root / "hot" / f"{eid}.md").write_text(content)

    stdout, stderr, rc = _run_status(palaia_root, json_mode=True)
    assert rc == 0
    data = json.loads(stdout)
    assert "index_hint" in data
    assert "1 entries not indexed" in data["index_hint"]
    assert "palaia warmup" in data["index_hint"]


def test_json_index_hint_fully_indexed(palaia_root):
    """JSON output index_hint should say fully indexed when all cached."""
    store = Store(palaia_root)
    eid = store.write("Entry one")

    store.embedding_cache.set_cached(eid, [0.1, 0.2], model="test")

    stdout, stderr, rc = _run_status(palaia_root, json_mode=True)
    assert rc == 0
    data = json.loads(stdout)
    assert "index_hint" in data
    assert "fully indexed" in data["index_hint"]
