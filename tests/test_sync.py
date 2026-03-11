"""Tests for export/import functionality."""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from palaia.config import DEFAULT_CONFIG, save_config
from palaia.store import Store
from palaia.sync import export_entries, import_entries, MANIFEST_NAME


@pytest.fixture
def palaia_root(tmp_path):
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    save_config(root, DEFAULT_CONFIG)
    return root


@pytest.fixture
def store(palaia_root):
    return Store(palaia_root)


def test_export_no_public_entries(palaia_root, store, monkeypatch):
    """Export with no public entries returns empty."""
    store.write("private stuff", scope="team")
    monkeypatch.chdir(palaia_root.parent)
    result = export_entries()
    assert result["exported"] == 0


def test_export_to_dir(palaia_root, store, monkeypatch, tmp_path):
    """Export public entries to a directory."""
    store.write("shared knowledge", scope="public", title="Shared")
    store.write("team only", scope="team")
    monkeypatch.chdir(palaia_root.parent)

    out = tmp_path / "export-test"
    result = export_entries(output_dir=str(out))
    assert result["exported"] == 1
    assert (out / MANIFEST_NAME).exists()
    assert (out / "entries").is_dir()
    assert len(list((out / "entries").glob("*.md"))) == 1

    # Check manifest
    with open(out / MANIFEST_NAME) as f:
        manifest = json.load(f)
    assert manifest["entry_count"] == 1


def test_import_from_dir(palaia_root, store, monkeypatch, tmp_path):
    """Import entries from exported directory."""
    # Create export
    store.write("exportable", scope="public", title="Import Me")
    monkeypatch.chdir(palaia_root.parent)
    out = tmp_path / "export-out"
    export_entries(output_dir=str(out))

    # New store for import
    root2 = tmp_path / "workspace2" / ".palaia"
    root2.mkdir(parents=True)
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root2 / sub).mkdir()
    save_config(root2, DEFAULT_CONFIG)
    monkeypatch.chdir(root2.parent)

    result = import_entries(str(out))
    assert result["imported"] == 1


def test_import_dry_run(palaia_root, store, monkeypatch, tmp_path):
    """Dry run shows what would be imported."""
    store.write("test entry", scope="public", title="DryRun")
    monkeypatch.chdir(palaia_root.parent)
    out = tmp_path / "export-dry"
    export_entries(output_dir=str(out))

    # Fresh workspace
    root2 = tmp_path / "ws2" / ".palaia"
    root2.mkdir(parents=True)
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root2 / sub).mkdir()
    save_config(root2, DEFAULT_CONFIG)
    monkeypatch.chdir(root2.parent)

    result = import_entries(str(out), dry_run=True)
    assert result["would_import"] == 1
    assert result["imported"] == 0


def test_import_dedup(palaia_root, store, monkeypatch, tmp_path):
    """Importing the same content twice deduplicates."""
    store.write("deduplicate me", scope="public")
    monkeypatch.chdir(palaia_root.parent)
    out = tmp_path / "export-dedup"
    export_entries(output_dir=str(out))

    # Import into same store
    result = import_entries(str(out))
    assert result["skipped_dedup"] == 1
    assert result["imported"] == 0


def test_import_rejects_team_scope(tmp_path, monkeypatch):
    """Importing team-scoped entries from foreign workspace raises error."""
    from palaia.entry import serialize_entry

    export_dir = tmp_path / "bad-export"
    entries_dir = export_dir / "entries"
    entries_dir.mkdir(parents=True)

    # Write a team-scoped entry (should not be in export, but test rejection)
    meta = {"id": "fake-id", "scope": "team", "content_hash": "abc123"}
    entry_text = serialize_entry(meta, "secret team knowledge")
    (entries_dir / "fake-id.md").write_text(entry_text)

    manifest = {"palaia_version": "0.1.0", "workspace": "foreign", "entry_count": 1, "content_hashes": ["abc123"]}
    with open(export_dir / MANIFEST_NAME, "w") as f:
        json.dump(manifest, f)

    # Target workspace
    root = tmp_path / "target" / ".palaia"
    root.mkdir(parents=True)
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    save_config(root, DEFAULT_CONFIG)
    monkeypatch.chdir(root.parent)

    with pytest.raises(ValueError, match="team-scoped"):
        import_entries(str(export_dir))
