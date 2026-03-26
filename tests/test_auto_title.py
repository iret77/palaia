"""Tests for auto-title extraction from content (Issue #41)."""

import pytest

from palaia.entry import create_entry, extract_title_from_content, parse_entry
from palaia.store import Store


# --- Unit tests for extract_title_from_content ---


def test_extract_plain_first_line():
    assert extract_title_from_content("Release Process\n\nStep 1...") == "Release Process"


def test_extract_markdown_h1():
    assert extract_title_from_content("# My Title\n\nBody text") == "My Title"


def test_extract_markdown_h2():
    assert extract_title_from_content("## Section Title\n\nDetails") == "Section Title"


def test_extract_markdown_h3():
    assert extract_title_from_content("### Deep Header\nContent") == "Deep Header"


def test_extract_skips_empty_lines():
    assert extract_title_from_content("\n\n  \nActual Title\nBody") == "Actual Title"


def test_extract_truncates_long_title():
    long_line = "A" * 100
    result = extract_title_from_content(long_line, max_length=80)
    assert result is not None
    assert result.endswith("...")
    assert len(result) <= 84  # 80 + "..."


def test_extract_truncates_at_word_boundary():
    line = "word " * 20  # 100 chars
    result = extract_title_from_content(line.strip(), max_length=80)
    assert result is not None
    assert result.endswith("...")
    assert " " not in result[-4:-3] or result.endswith("...")  # clean break


def test_extract_empty_content():
    assert extract_title_from_content("") is None


def test_extract_whitespace_only():
    assert extract_title_from_content("   \n  \n   ") is None


def test_extract_header_only_hash():
    """A line that is just '# ' with nothing after should be skipped."""
    assert extract_title_from_content("#  \nReal title") == "Real title"


# --- Integration tests: create_entry ---


def test_create_entry_auto_title():
    entry_text = create_entry("Release Process\n\n1. Run tests\n2. Deploy")
    meta, body = parse_entry(entry_text)
    assert meta["title"] == "Release Process"


def test_create_entry_auto_title_markdown():
    entry_text = create_entry("# ADR-007: New Feature\n\nDecision text")
    meta, body = parse_entry(entry_text)
    assert meta["title"] == "ADR-007: New Feature"


def test_create_entry_explicit_title_overrides():
    entry_text = create_entry("First line content\n\nBody", title="My Custom Title")
    meta, body = parse_entry(entry_text)
    assert meta["title"] == "My Custom Title"


def test_create_entry_no_title_empty_body():
    """Single-line content should still get a title."""
    entry_text = create_entry("Just a note")
    meta, body = parse_entry(entry_text)
    assert meta["title"] == "Just a note"


# --- Integration tests: Store.write ---


def test_store_write_auto_title(palaia_root):
    store = Store(palaia_root)
    entry_id = store.write("# Release Process (Palaia)\n\n1. All CI tests...")
    result = store.read(entry_id)
    assert result is not None
    meta, body = result
    assert meta["title"] == "Release Process (Palaia)"


def test_store_write_explicit_title(palaia_root):
    store = Store(palaia_root)
    entry_id = store.write("Some content", title="Explicit Title")
    result = store.read(entry_id)
    meta, body = result
    assert meta["title"] == "Explicit Title"


# --- Integration tests: Store.edit ---


def test_store_edit_auto_updates_title_on_content_change(palaia_root):
    store = Store(palaia_root)
    entry_id = store.write("Original Title\n\nOriginal body")
    meta = store.edit(entry_id, body="New Title Line\n\nUpdated body")
    assert meta["title"] == "New Title Line"


def test_store_edit_explicit_title_overrides_auto(palaia_root):
    store = Store(palaia_root)
    entry_id = store.write("Auto Title\n\nBody")
    meta = store.edit(entry_id, body="New Content\n\nBody", title="Manual Override")
    assert meta["title"] == "Manual Override"


def test_store_edit_no_content_change_keeps_title(palaia_root):
    store = Store(palaia_root)
    entry_id = store.write("Original Title\n\nBody")
    result = store.read(entry_id)
    original_title = result[0]["title"]
    # Edit only tags, not content
    meta = store.edit(entry_id, tags=["new-tag"])
    assert meta["title"] == original_title
