"""Tests for warmup embedding index build (#48)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from palaia.cli import _reindex_entries
from palaia.config import DEFAULT_CONFIG, save_config
from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    """Create a minimal .palaia directory with entries."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()

    config = dict(DEFAULT_CONFIG)
    config["agent"] = "test"
    config["embedding_chain"] = ["fastembed", "bm25"]
    save_config(root, config)
    return root


def _write_entry(root: Path, tier: str, entry_id: str, title: str, body: str, tags: list[str] | None = None):
    """Write a test entry to the store."""
    tags = tags or []
    tags_str = ", ".join(tags)
    content = f"""---
id: {entry_id}
title: {title}
tags: [{tags_str}]
scope: team
agent: test
created: 2026-01-01T00:00:00+00:00
accessed: 2026-01-01T00:00:00+00:00
access_count: 1
decay_score: 1.0
---
{body}"""
    (root / tier / f"{entry_id}.md").write_text(content)


class FakeArgs:
    json = False


class FakeArgsJson:
    json = True


class FakeProvider:
    name = "fastembed"
    model_name = "test-model"

    def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


def test_reindex_fills_empty_cache(palaia_root):
    """Warmup indexes all entries when cache is empty."""
    _write_entry(palaia_root, "hot", "aaaa-1111", "Test Entry 1", "Hello world")
    _write_entry(palaia_root, "hot", "aaaa-2222", "Test Entry 2", "Goodbye world")
    _write_entry(palaia_root, "warm", "aaaa-3333", "Test Entry 3", "Warm entry")

    config = json.loads((palaia_root / "config.json").read_text())
    with patch("palaia.embeddings.auto_detect_provider", return_value=FakeProvider()):
        stats = _reindex_entries(palaia_root, config, FakeArgs())

    assert stats["indexed"] == 3
    assert stats["new"] == 3
    assert stats["cached"] == 0

    # Verify cache is filled
    store = Store(palaia_root)
    for eid in ("aaaa-1111", "aaaa-2222", "aaaa-3333"):
        assert store.embedding_cache.get_cached(eid) is not None


def test_reindex_skips_cached_entries(palaia_root):
    """Warmup skips entries already in the cache."""
    _write_entry(palaia_root, "hot", "aaaa-1111", "Test Entry 1", "Hello world")
    _write_entry(palaia_root, "hot", "aaaa-2222", "Test Entry 2", "Goodbye world")

    # Pre-cache one entry
    store = Store(palaia_root)
    store.embedding_cache.set_cached("aaaa-1111", [0.5, 0.6, 0.7], model="pre-cached")

    config = json.loads((palaia_root / "config.json").read_text())

    fake_provider = FakeProvider()
    with patch("palaia.embeddings.auto_detect_provider", return_value=fake_provider):
        stats = _reindex_entries(palaia_root, config, FakeArgs())

    assert stats["indexed"] == 2
    assert stats["new"] == 1
    assert stats["cached"] == 1

    # Verify pre-cached entry was NOT overwritten
    vec = store.embedding_cache.get_cached("aaaa-1111")
    assert vec == [0.5, 0.6, 0.7]


def test_reindex_bm25_only_skips(palaia_root):
    """Warmup with BM25-only provider skips indexing without error."""
    _write_entry(palaia_root, "hot", "aaaa-1111", "Test Entry 1", "Hello world")

    config = json.loads((palaia_root / "config.json").read_text())
    config["embedding_chain"] = ["bm25"]

    from palaia.embeddings import BM25Provider

    with patch("palaia.embeddings.auto_detect_provider", return_value=BM25Provider()):
        stats = _reindex_entries(palaia_root, config, FakeArgs())

    assert stats["indexed"] == 0
    assert stats["new"] == 0
    assert stats["cached"] == 0


def test_reindex_no_entries(palaia_root):
    """Warmup with no entries returns zeroes."""
    config = json.loads((palaia_root / "config.json").read_text())

    with patch("palaia.embeddings.auto_detect_provider", return_value=FakeProvider()):
        stats = _reindex_entries(palaia_root, config, FakeArgs())

    assert stats["indexed"] == 0
    assert stats["new"] == 0
    assert stats["cached"] == 0


def test_warmup_json_output_contains_index_fields(palaia_root, capsys):
    """JSON output from warmup includes indexed/new/cached fields."""
    _write_entry(palaia_root, "hot", "aaaa-1111", "Test Entry 1", "Hello world")

    config = json.loads((palaia_root / "config.json").read_text())

    with patch("palaia.embeddings.auto_detect_provider", return_value=FakeProvider()):
        stats = _reindex_entries(palaia_root, config, FakeArgsJson())

    assert "indexed" in stats
    assert "new" in stats
    assert "cached" in stats


def test_reindex_uses_title_tags_body(palaia_root):
    """Verify that text passed to embed includes title, tags, and body."""
    _write_entry(palaia_root, "hot", "aaaa-1111", "My Title", "Body text here", tags=["tag1", "tag2"])

    config = json.loads((palaia_root / "config.json").read_text())
    embedded_texts = []

    class SpyProvider:
        name = "fastembed"
        model_name = "test-model"

        def embed(self, texts):
            embedded_texts.extend(texts)
            return [[0.1, 0.2, 0.3] for _ in texts]

        def embed_query(self, text):
            return [0.1, 0.2, 0.3]

    with patch("palaia.embeddings.auto_detect_provider", return_value=SpyProvider()):
        _reindex_entries(palaia_root, config, FakeArgs())

    assert len(embedded_texts) == 1
    text = embedded_texts[0]
    assert "My Title" in text
    assert "tag1" in text
    assert "tag2" in text
    assert "Body text here" in text
