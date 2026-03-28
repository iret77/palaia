"""Tests for audit fix items."""

import json
import time

import pytest

from palaia.entry import (
    _parse_yaml_simple,
    _quote_yaml_value,
    _sanitize_body,
    create_entry,
    parse_entry,
)
from palaia.lock import STALE_LOCK_SECONDS, PalaiaLock
from palaia.store import Store

# --- Audit Fix 1: Empty content raises ValueError ---


def test_write_empty_string_raises(palaia_root):
    store = Store(palaia_root)
    with pytest.raises(ValueError, match="empty content"):
        store.write("")


def test_write_whitespace_only_raises(palaia_root):
    store = Store(palaia_root)
    with pytest.raises(ValueError, match="empty content"):
        store.write("   \n\t  ")


def test_write_normal_content_works(palaia_root):
    store = Store(palaia_root)
    entry_id = store.write("Valid content here")
    assert entry_id is not None


# --- Audit Fix 3: YAML parsing with colons ---


def test_yaml_parse_url_value():
    yaml_text = "url: https://example.com:8080/path"
    result = _parse_yaml_simple(yaml_text)
    assert result["url"] == "https://example.com:8080/path"


def test_yaml_parse_title_with_colon():
    yaml_text = "title: Foo: Bar: Baz"
    result = _parse_yaml_simple(yaml_text)
    assert result["title"] == "Foo: Bar: Baz"


def test_yaml_parse_iso_timestamp():
    yaml_text = "created: 2026-03-11T10:24:00+00:00"
    result = _parse_yaml_simple(yaml_text)
    assert result["created"] == "2026-03-11T10:24:00+00:00"


def test_yaml_parse_multiple_colons():
    yaml_text = """id: abc-123
title: Fix: YAML: Parser
created: 2026-03-11T10:24:00+00:00"""
    result = _parse_yaml_simple(yaml_text)
    assert result["id"] == "abc-123"
    assert result["title"] == "Fix: YAML: Parser"
    assert "2026-03-11T10" in result["created"]


# --- Audit Fix 2: GC uses WAL ---


def test_gc_uses_wal(palaia_root):
    """Verify that GC tier moves are WAL-logged."""
    store = Store(palaia_root)

    # Write an entry
    entry_id = store.write("Test GC WAL", scope="team")

    # Manually age the entry to force tier move
    entry_path = palaia_root / "hot" / f"{entry_id}.md"
    text = entry_path.read_text()

    # Replace timestamps to make it 60 days old
    old_date = "2025-01-01T00:00:00+00:00"
    text = text.replace(text.split("created: ")[1].split("\n")[0], old_date).replace(
        text.split("accessed: ")[1].split("\n")[0], old_date
    )
    entry_path.write_text(text)

    # Run GC
    result = store.gc()

    # Should have moved from hot to cold/warm
    total_moves = sum(v for k, v in result.items() if k.startswith("hot_to"))

    # Verify WAL was used — check backend or filesystem depending on mode
    if store._backend:
        # SQLite/Postgres backend: WAL entries are in the database
        # If GC moved entries, the WAL should have logged+committed them
        # (no pending entries should remain)
        pending = store.wal.get_pending()
        assert len(pending) == 0, "No pending WAL entries should remain after GC"
    else:
        # Legacy JSON mode: WAL entries are files on disk
        wal_files = list((palaia_root / "wal").glob("*.json"))
        committed = 0
        for wf in wal_files:
            data = json.loads(wf.read_text())
            if data.get("status") == "committed" and data.get("operation") == "write":
                committed += 1
        if total_moves > 0:
            assert committed >= total_moves, "GC tier moves should be WAL-logged"


# --- Audit Fix 4: Lock stale detection ---


def test_stale_lock_detection(palaia_root, caplog):
    """Lock older than 60s should be detected as stale."""
    import logging

    lock = PalaiaLock(palaia_root, timeout=1.0)

    # Create a fake stale lock
    lock_path = palaia_root / ".lock"
    stale_ts = time.time() - (STALE_LOCK_SECONDS + 10)
    lock_path.write_text(json.dumps({"pid": 99999, "ts": stale_ts}))

    # Should be able to acquire despite stale lock
    with caplog.at_level(logging.WARNING, logger="palaia.lock"):
        lock.acquire()
        lock.release()

    # Should have logged a warning about stale lock
    stale_warnings = [r for r in caplog.records if "Stale lock" in r.message]
    assert len(stale_warnings) > 0


def test_fresh_lock_not_stale(palaia_root):
    """Lock that's fresh should not be flagged as stale."""
    lock = PalaiaLock(palaia_root, timeout=2.0)

    # Create a fresh lock (but don't actually flock it)
    lock_path = palaia_root / ".lock"
    lock_path.write_text(json.dumps({"pid": 99999, "ts": time.time()}))

    # The _check_stale should not remove a fresh lock
    is_stale = lock._check_stale()
    assert is_stale is False


# --- Audit Fix 5: Frontmatter injection prevention (Phase 0.3) ---


class TestFrontmatterInjection:
    """Body content containing '---' must not inject metadata."""

    def test_body_with_triple_dash_does_not_inject_scope(self):
        """A body containing '---\\nscope: private\\n---' must not override scope."""
        malicious_body = "Some text\n---\nscope: private\nagent: evil\n---\nMore text"
        entry_text = create_entry(malicious_body, scope="team")
        meta, body = parse_entry(entry_text)
        assert meta["scope"] == "team", "Body must not override frontmatter scope"
        assert meta.get("agent") != "evil", "Body must not inject agent field"

    def test_body_with_triple_dash_roundtrips(self):
        """Entry with '---' in body should roundtrip correctly."""
        body_with_dashes = "First paragraph\n---\nSecond paragraph"
        entry_text = create_entry(body_with_dashes, scope="team")
        meta, body = parse_entry(entry_text)
        # Body should contain the dashes (escaped or preserved)
        assert "Second paragraph" in body
        assert meta.get("scope") == "team"

    def test_sanitize_body_escapes_triple_dash(self):
        """_sanitize_body must escape lines that are just dashes."""
        result = _sanitize_body("hello\n---\nworld")
        assert "\n\\---\n" in result

    def test_sanitize_body_preserves_dashes_in_text(self):
        """Dashes within text lines should not be escaped."""
        result = _sanitize_body("hello --- world")
        assert result == "hello --- world"

    def test_quote_yaml_value_with_newline(self):
        """Values containing newlines must be quoted."""
        result = _quote_yaml_value("line1\nline2")
        assert result.startswith('"')
        assert "\\n" in result

    def test_quote_yaml_value_with_triple_dash(self):
        """Values containing '---' must be quoted."""
        result = _quote_yaml_value("before---after")
        assert result.startswith('"')

    def test_quote_yaml_value_normal(self):
        """Normal values should not be quoted."""
        result = _quote_yaml_value("normal value")
        assert result == "normal value"

    def test_title_with_newline_injection(self):
        """Title containing newline must not break frontmatter."""
        entry_text = create_entry("body", scope="team", title="Title\n---\nscope: private")
        meta, body = parse_entry(entry_text)
        assert meta["scope"] == "team"

    def test_store_write_with_malicious_body(self, palaia_root):
        """End-to-end: writing and reading back malicious content."""
        store = Store(palaia_root)
        malicious = "Normal text\n---\nscope: private\nagent: attacker\n---\nPayload"
        entry_id = store.write(malicious, scope="team")
        meta, body = store.read(entry_id)
        assert meta["scope"] == "team"
        assert meta.get("agent") != "attacker"
