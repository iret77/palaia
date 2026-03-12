"""Tests for palaia migrate — format detection, adapters, dry-run, dedup."""

from __future__ import annotations

import json

import pytest

from palaia.config import DEFAULT_CONFIG, save_config
from palaia.migrate import (
    FlatFileAdapter,
    GenericMarkdownAdapter,
    JsonMemoryAdapter,
    SmartMemoryAdapter,
    detect_format,
    migrate,
)
from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    root = tmp_path / "workspace" / ".palaia"
    root.mkdir(parents=True)
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    save_config(root, DEFAULT_CONFIG)
    return root


@pytest.fixture
def store(palaia_root):
    return Store(palaia_root)


# === SmartMemoryAdapter ===


@pytest.fixture
def smart_memory_source(tmp_path):
    src = tmp_path / "smart-src"
    src.mkdir()
    (src / "MEMORY.md").write_text("# Memory\nTop-level rules and context.\n")
    mem = src / "memory"
    mem.mkdir()
    (mem / "active-context.md").write_text(
        "# Active Context\n\n"
        "## [OPEN] Clawsy Build Sprint\nDetails about clawsy sprint.\n\n"
        "## [OPEN] Palaia Migration\nDetails about palaia migration.\n"
    )
    projects = mem / "projects" / "clawsy"
    projects.mkdir(parents=True)
    (projects / "CONTEXT.md").write_text("# Clawsy Project\nProject context here.\n")
    agents = mem / "agents"
    agents.mkdir()
    (agents / "coding.md").write_text("# Coding Agent\nCoding agent context.\n")
    (mem / "2026-03-10.md").write_text("# 2026-03-10\nDaily log entry.\n")
    return src


def test_smart_memory_detect(smart_memory_source):
    assert SmartMemoryAdapter.detect(smart_memory_source) is True


def test_smart_memory_detect_negative(tmp_path):
    assert SmartMemoryAdapter.detect(tmp_path) is False


def test_smart_memory_extract(smart_memory_source):
    entries = SmartMemoryAdapter.extract(smart_memory_source)
    assert len(entries) == 6  # MEMORY.md + 2 OPEN blocks + project + agent + daily

    titles = [e.title for e in entries]
    assert "MEMORY.md" in titles
    assert "Clawsy Build Sprint" in titles
    assert "Palaia Migration" in titles
    assert "Project: clawsy" in titles
    assert "Agent: coding" in titles
    assert "Daily: 2026-03-10" in titles

    # Check scopes
    by_title = {e.title: e for e in entries}
    assert by_title["Project: clawsy"].scope == "shared:clawsy"
    assert by_title["Agent: coding"].tier == "warm"
    assert by_title["Daily: 2026-03-10"].tier == "cold"


def test_smart_memory_format_detection(smart_memory_source):
    assert detect_format(smart_memory_source) == "smart-memory"


# === FlatFileAdapter ===


@pytest.fixture
def flat_file_source(tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("# Part One\nFirst section.\n---\n# Part Two\nSecond section.\n")
    return f


def test_flat_file_detect(flat_file_source):
    assert FlatFileAdapter.detect(flat_file_source) is True


def test_flat_file_extract(flat_file_source):
    entries = FlatFileAdapter.extract(flat_file_source)
    assert len(entries) == 2
    assert entries[0].title == "Part One"
    assert entries[1].title == "Part Two"


def test_flat_file_single_section(tmp_path):
    f = tmp_path / "single.md"
    f.write_text("# My Note\nJust one section.\n")
    entries = FlatFileAdapter.extract(f)
    assert len(entries) == 1
    assert entries[0].title == "My Note"


# === JsonMemoryAdapter ===


@pytest.fixture
def json_memory_source(tmp_path):
    f = tmp_path / "memories.json"
    data = [
        {"content": "Memory one", "title": "First", "metadata": {"scope": "team", "tags": ["test"]}},
        {"content": "Memory two", "metadata": {"scope": "public"}},
    ]
    f.write_text(json.dumps(data))
    return f


def test_json_memory_detect(json_memory_source):
    assert JsonMemoryAdapter.detect(json_memory_source) is True


def test_json_memory_detect_negative(tmp_path):
    f = tmp_path / "not-memory.json"
    f.write_text('{"key": "value"}')
    assert JsonMemoryAdapter.detect(f) is False


def test_json_memory_extract(json_memory_source):
    entries = JsonMemoryAdapter.extract(json_memory_source)
    assert len(entries) == 2
    assert entries[0].body == "Memory one"
    assert entries[0].title == "First"
    assert entries[0].tags == ["test"]
    assert entries[1].scope == "public"


def test_json_memory_dir(tmp_path):
    d = tmp_path / "jsondir"
    d.mkdir()
    (d / "a.json").write_text(json.dumps([{"content": "A"}]))
    (d / "b.json").write_text(json.dumps([{"content": "B"}]))
    assert JsonMemoryAdapter.detect(d) is True
    entries = JsonMemoryAdapter.extract(d)
    assert len(entries) == 2


# === GenericMarkdownAdapter ===


def test_generic_md_detect(tmp_path):
    d = tmp_path / "mddir"
    d.mkdir()
    (d / "notes.md").write_text("# Notes\nSome notes.\n")
    assert GenericMarkdownAdapter.detect(d) is True


def test_generic_md_extract_tier_heuristics(tmp_path):
    d = tmp_path / "mddir"
    d.mkdir()
    (d / "active-context.md").write_text("Active stuff")
    (d / "2025-01-15.md").write_text("Old daily")
    (d / "archive-notes.md").write_text("Archived")
    (d / "general.md").write_text("General notes")

    entries = GenericMarkdownAdapter.extract(d)
    by_title = {e.source_file: e for e in entries}
    assert by_title["active-context.md"].tier == "hot"
    assert by_title["2025-01-15.md"].tier == "cold"
    assert by_title["archive-notes.md"].tier == "cold"


def test_generic_md_scope_heuristics(tmp_path):
    d = tmp_path / "mddir"
    d.mkdir()
    (d / "private-diary.md").write_text("Secrets")
    (d / "public-faq.md").write_text("FAQ")
    (d / "notes.md").write_text("Team notes")

    entries = GenericMarkdownAdapter.extract(d)
    by_file = {e.source_file: e for e in entries}
    assert by_file["private-diary.md"].scope == "private"
    assert by_file["public-faq.md"].scope == "public"
    assert by_file["notes.md"].scope == "team"


# === Format Detection Priority ===


def test_detect_format_smart_memory_over_generic(smart_memory_source):
    """Smart-memory should win over generic-md."""
    assert detect_format(smart_memory_source) == "smart-memory"


def test_detect_format_json_over_generic(json_memory_source):
    assert detect_format(json_memory_source) == "json-memory"


def test_detect_format_flat_file(flat_file_source):
    assert detect_format(flat_file_source) == "flat-file"


def test_detect_format_fallback(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    (d / "readme.md").write_text("Hello")
    assert detect_format(d) == "generic-md"


# === migrate() integration ===


def test_migrate_smart_memory(store, smart_memory_source):
    result = migrate(smart_memory_source, store)
    assert result["format"] == "smart-memory"
    assert result["imported"] == 6
    assert result["skipped_dedup"] == 0


def test_migrate_dry_run(store, smart_memory_source):
    result = migrate(smart_memory_source, store, dry_run=True)
    assert result["dry_run"] is True
    assert result["imported"] == 0
    assert len(result["entries"]) == 6
    # Nothing actually written
    assert len(store.list_entries("hot")) == 0


def test_migrate_dedup(store, smart_memory_source):
    result1 = migrate(smart_memory_source, store)
    assert result1["imported"] == 6
    result2 = migrate(smart_memory_source, store)
    assert result2["imported"] == 0
    assert result2["skipped_dedup"] == 6


def test_migrate_scope_override(store, smart_memory_source):
    result = migrate(smart_memory_source, store, scope_override="public")
    assert result["scopes"] == {"public": 6}


def test_migrate_force_format(store, smart_memory_source):
    result = migrate(smart_memory_source, store, format_name="generic-md")
    assert result["format"] == "generic-md"
    assert result["imported"] > 0


def test_migrate_json(store, json_memory_source):
    result = migrate(json_memory_source, store)
    assert result["format"] == "json-memory"
    assert result["imported"] == 2


def test_migrate_flat_file(store, flat_file_source):
    result = migrate(flat_file_source, store)
    assert result["format"] == "flat-file"
    assert result["imported"] == 2


def test_migrate_not_found(store, tmp_path):
    with pytest.raises(FileNotFoundError):
        migrate(tmp_path / "nonexistent", store)


# === System file detection ===


def test_migrate_detects_system_files(store, smart_memory_source):
    """System files like MEMORY.md and CONTEXT.md should be flagged in result."""
    result = migrate(smart_memory_source, store)
    sys_files = result.get("system_files_detected", [])
    assert "MEMORY.md" in sys_files
    # CONTEXT.md is inside memory/projects/clawsy/
    assert any("CONTEXT.md" in f for f in sys_files)


def test_migrate_system_files_in_dry_run(store, smart_memory_source):
    """System files should also be flagged in dry-run mode."""
    result = migrate(smart_memory_source, store, dry_run=True)
    sys_files = result.get("system_files_detected", [])
    assert len(sys_files) > 0
    assert "MEMORY.md" in sys_files


def test_is_system_file():
    from palaia.migrate import is_system_file

    assert is_system_file("MEMORY.md") is True
    assert is_system_file("CONTEXT.md") is True
    assert is_system_file("memory/projects/clawsy/CONTEXT.md") is True
    assert is_system_file("SOUL.md") is True
    assert is_system_file("AGENTS.md") is True
    assert is_system_file("TOOLS.md") is True
    assert is_system_file("USER.md") is True
    assert is_system_file("IDENTITY.md") is True
    assert is_system_file("2026-03-10.md") is False
    assert is_system_file("random-notes.md") is False


def test_format_result_shows_system_file_warnings():
    from palaia.migrate import format_result

    result = {
        "format": "smart-memory",
        "total_entries": 6,
        "files_scanned": 5,
        "tiers": {"hot": 4, "warm": 1, "cold": 1},
        "scopes": {"team": 5, "shared:clawsy": 1},
        "imported": 6,
        "skipped_dedup": 0,
        "dry_run": False,
        "system_files_detected": ["MEMORY.md", "memory/projects/clawsy/CONTEXT.md"],
    }
    output = format_result(result)
    assert "⚠️  System file detected: MEMORY.md" in output
    assert "⚠️  System file detected: memory/projects/clawsy/CONTEXT.md" in output
    assert "Do not remove it manually" in output
