"""Tests for MetadataIndex (metadata_index.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from palaia.metadata_index import MetadataIndex


@pytest.fixture
def idx(tmp_path):
    """Create a MetadataIndex in a temp directory."""
    return MetadataIndex(tmp_path)


@pytest.fixture
def populated_idx(tmp_path):
    """Create a MetadataIndex with some entries on disk + index."""
    # Create tier directories with .md files
    for tier in ("hot", "warm"):
        tier_dir = tmp_path / tier
        tier_dir.mkdir()

    # Write fake entry files
    (tmp_path / "hot" / "entry-001.md").write_text(
        "---\nid: entry-001\ntitle: First\ntags: [test]\nscope: team\ncontent_hash: abc123\n---\nBody one"
    )
    (tmp_path / "hot" / "entry-002.md").write_text(
        "---\nid: entry-002\ntitle: Second\ntags: [demo]\nscope: private\nagent: hal\ncontent_hash: def456\n---\nBody two"
    )
    (tmp_path / "warm" / "entry-003.md").write_text(
        "---\nid: entry-003\ntitle: Third\ntags: [old]\nscope: team\ncontent_hash: ghi789\n---\nBody three"
    )

    idx = MetadataIndex(tmp_path)
    return idx


def _mock_parse(text: str):
    """Simple parse that splits on --- markers and extracts YAML-ish frontmatter."""
    import re

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm_text = parts[1].strip()
    body = parts[2].strip()
    meta = {}
    for line in fm_text.split("\n"):
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            # Handle YAML lists
            if val.startswith("[") and val.endswith("]"):
                val = [v.strip() for v in val[1:-1].split(",")]
            meta[key] = val
    return meta, body


class TestMetadataIndexBuild:
    """Test building the index from disk."""

    def test_rebuild_from_disk(self, populated_idx, tmp_path):
        count = populated_idx.rebuild(_mock_parse)
        assert count == 3
        assert populated_idx.is_populated()

    def test_rebuild_indexes_all_fields(self, populated_idx):
        populated_idx.rebuild(_mock_parse)
        entry = populated_idx.get("entry-001")
        assert entry is not None
        assert entry["title"] == "First"
        assert entry["scope"] == "team"
        assert entry["content_hash"] == "abc123"
        assert entry["tier"] == "hot"

    def test_rebuild_warm_tier(self, populated_idx):
        populated_idx.rebuild(_mock_parse)
        entry = populated_idx.get("entry-003")
        assert entry is not None
        assert entry["tier"] == "warm"


class TestMetadataIndexLookup:
    """Test index lookup operations."""

    def test_get_nonexistent(self, idx):
        assert idx.get("does-not-exist") is None

    def test_update_and_get(self, idx):
        meta = {"id": "test-1", "title": "Test", "scope": "team", "content_hash": "hash1"}
        idx.update("test-1", meta, "hot")
        result = idx.get("test-1")
        assert result is not None
        assert result["title"] == "Test"
        assert result["tier"] == "hot"

    def test_find_by_hash(self, idx):
        meta = {"id": "test-1", "title": "Test", "content_hash": "unique_hash"}
        idx.update("test-1", meta, "hot")
        assert idx.find_by_hash("unique_hash") == "test-1"
        assert idx.find_by_hash("nonexistent") is None

    def test_remove(self, idx):
        meta = {"id": "test-1", "title": "Test"}
        idx.update("test-1", meta, "hot")
        assert idx.remove("test-1") is True
        assert idx.get("test-1") is None
        assert idx.remove("test-1") is False


class TestMetadataIndexStaleDetection:
    """Test stale entry detection and cleanup."""

    def test_cleanup_removes_stale(self, idx):
        for i in range(5):
            meta = {"id": f"entry-{i}", "title": f"Entry {i}"}
            idx.update(f"entry-{i}", meta, "hot")

        # Only entry-0 and entry-2 are valid
        valid = {"entry-0", "entry-2"}
        removed = idx.cleanup(valid)
        assert removed == 3
        assert idx.get("entry-0") is not None
        assert idx.get("entry-1") is None
        assert idx.get("entry-2") is not None

    def test_cleanup_no_stale(self, idx):
        meta = {"id": "entry-0", "title": "Entry 0"}
        idx.update("entry-0", meta, "hot")
        removed = idx.cleanup({"entry-0"})
        assert removed == 0


class TestMetadataIndexFallback:
    """Test transparent fallback when index is empty or corrupt."""

    def test_empty_index_not_populated(self, idx):
        assert not idx.is_populated()

    def test_corrupt_index_file(self, tmp_path):
        """Corrupt JSON should result in empty index (graceful degradation)."""
        index_dir = tmp_path / "index"
        index_dir.mkdir(parents=True)
        (index_dir / "metadata.json").write_text("{{not valid json")
        idx = MetadataIndex(tmp_path)
        assert not idx.is_populated()
        # Should still work — just empty
        assert idx.get("anything") is None

    def test_missing_index_file(self, tmp_path):
        """Missing index file should result in empty index."""
        idx = MetadataIndex(tmp_path)
        assert not idx.is_populated()


class TestMetadataIndexPersistence:
    """Test that index survives save/reload."""

    def test_persist_and_reload(self, tmp_path):
        idx1 = MetadataIndex(tmp_path)
        meta = {"id": "persist-1", "title": "Persisted", "content_hash": "ph1"}
        idx1.update("persist-1", meta, "hot")

        # Create new instance — should load from disk
        idx2 = MetadataIndex(tmp_path)
        result = idx2.get("persist-1")
        assert result is not None
        assert result["title"] == "Persisted"

    def test_all_entries_respects_cold_filter(self, idx):
        idx.update("h1", {"id": "h1"}, "hot")
        idx.update("w1", {"id": "w1"}, "warm")
        idx.update("c1", {"id": "c1"}, "cold")

        without_cold = idx.all_entries(include_cold=False)
        assert len(without_cold) == 2

        with_cold = idx.all_entries(include_cold=True)
        assert len(with_cold) == 3

    def test_stats(self, idx):
        idx.update("h1", {"id": "h1"}, "hot")
        idx.update("h2", {"id": "h2"}, "hot")
        idx.update("w1", {"id": "w1"}, "warm")
        stats = idx.stats()
        assert stats["indexed_entries"] == 3
        assert stats["by_tier"]["hot"] == 2
        assert stats["by_tier"]["warm"] == 1
