"""Tests for the inter-agent memo subsystem (ADR-010)."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from palaia.config import DEFAULT_CONFIG, save_config
from palaia.memo import MemoManager


@pytest.fixture
def palaia_root(tmp_path):
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    save_config(root, DEFAULT_CONFIG)
    return root


@pytest.fixture
def mm(palaia_root):
    return MemoManager(palaia_root)


# --- Test 1: Send and inbox ---
def test_send_and_inbox(mm):
    """Sent memo appears in recipient's inbox."""
    mm.send("elliot", "PR #13 needs review", from_agent="cyberclaw")
    inbox = mm.inbox(agent="elliot")
    assert len(inbox) == 1
    meta, body = inbox[0]
    assert body == "PR #13 needs review"
    assert meta["from"] == "cyberclaw"
    assert meta["to"] == "elliot"
    assert meta["read"] is False


# --- Test 2: Send, ack, inbox ---
def test_send_ack_inbox(mm):
    """Acked memo disappears from default inbox."""
    meta = mm.send("elliot", "check this", from_agent="cyberclaw")
    mm.ack(meta["id"])

    inbox = mm.inbox(agent="elliot")
    assert len(inbox) == 0

    # But visible with include_read
    inbox_all = mm.inbox(agent="elliot", include_read=True)
    assert len(inbox_all) == 1
    assert inbox_all[0][0]["read"] is True
    assert inbox_all[0][0]["read_at"] is not None


# --- Test 3: Broadcast ---
def test_broadcast_visible_to_all(mm):
    """Broadcast memo visible to any agent."""
    mm.broadcast("deploy freeze until 18:00", from_agent="cyberclaw")

    inbox_elliot = mm.inbox(agent="elliot")
    inbox_tars = mm.inbox(agent="tars")

    assert len(inbox_elliot) == 1
    assert len(inbox_tars) == 1
    assert inbox_elliot[0][0]["to"] == "_broadcast"


# --- Test 4: Priority flag ---
def test_priority_flag(mm):
    """High priority memo has correct flag."""
    meta = mm.send("elliot", "urgent!", from_agent="cyberclaw", priority="high")
    assert meta["priority"] == "high"

    inbox = mm.inbox(agent="elliot")
    assert inbox[0][0]["priority"] == "high"


# --- Test 5: Priority sort order ---
def test_priority_sort_order(mm):
    """High priority memos appear before normal in inbox."""
    mm.send("elliot", "normal msg", from_agent="cyberclaw", priority="normal")
    mm.send("elliot", "urgent msg", from_agent="cyberclaw", priority="high")

    inbox = mm.inbox(agent="elliot")
    assert len(inbox) == 2
    assert inbox[0][0]["priority"] == "high"
    assert inbox[1][0]["priority"] == "normal"


# --- Test 6: TTL expiry ---
def test_ttl_expiry(mm):
    """Expired memo does not appear in inbox."""
    # Send with 0 TTL (expires immediately)
    meta = mm.send("elliot", "ephemeral", from_agent="cyberclaw", ttl_hours=0)

    # Need to wait a tiny bit for expiry
    time.sleep(0.01)
    inbox = mm.inbox(agent="elliot")
    assert len(inbox) == 0


# --- Test 7: ack_all ---
def test_ack_all(mm):
    """ack_all marks all unread memos as read."""
    mm.send("elliot", "msg 1", from_agent="cyberclaw")
    mm.send("elliot", "msg 2", from_agent="cyberclaw")
    mm.send("elliot", "msg 3", from_agent="cyberclaw")

    count = mm.ack_all(agent="elliot")
    assert count == 3

    inbox = mm.inbox(agent="elliot")
    assert len(inbox) == 0


# --- Test 8: gc removes expired ---
def test_gc_removes_expired(mm):
    """GC removes expired memos."""
    mm.send("elliot", "temp", from_agent="cyberclaw", ttl_hours=0)
    time.sleep(0.01)

    stats = mm.gc()
    assert stats["removed_expired"] >= 1
    assert stats["total_removed"] >= 1

    # Verify file is gone
    memos = list(mm.memos_dir.glob("*.md"))
    assert len(memos) == 0


# --- Test 9: gc removes read ---
def test_gc_removes_read(mm):
    """GC removes read memos."""
    meta = mm.send("elliot", "read me", from_agent="cyberclaw")
    mm.ack(meta["id"])

    stats = mm.gc()
    assert stats["removed_read"] >= 1


# --- Test 10: Agent filtering ---
def test_agent_filtering(mm):
    """Agent A does not see memos addressed to Agent B."""
    mm.send("elliot", "for elliot only", from_agent="cyberclaw")
    mm.send("tars", "for tars only", from_agent="cyberclaw")

    inbox_elliot = mm.inbox(agent="elliot")
    inbox_tars = mm.inbox(agent="tars")

    assert len(inbox_elliot) == 1
    assert inbox_elliot[0][1] == "for elliot only"
    assert len(inbox_tars) == 1
    assert inbox_tars[0][1] == "for tars only"


# --- Test 11: Get single memo ---
def test_get_memo(mm):
    """get() returns a specific memo by ID."""
    meta = mm.send("elliot", "specific msg", from_agent="cyberclaw")
    result = mm.get(meta["id"])
    assert result is not None
    m, body = result
    assert body == "specific msg"
    assert m["id"] == meta["id"]


# --- Test 12: Get nonexistent memo ---
def test_get_nonexistent(mm):
    """get() returns None for missing memo."""
    assert mm.get("nonexistent-id") is None


# --- Test 13: Invalid priority ---
def test_invalid_priority(mm):
    """Invalid priority raises ValueError."""
    with pytest.raises(ValueError, match="Invalid priority"):
        mm.send("elliot", "bad", from_agent="cyberclaw", priority="critical")


# --- Test 14: Empty message ---
def test_empty_message(mm):
    """Empty message raises ValueError."""
    with pytest.raises(ValueError, match="Message body is required"):
        mm.send("elliot", "", from_agent="cyberclaw")


# --- Test 15: Empty recipient ---
def test_empty_recipient(mm):
    """Empty recipient raises ValueError."""
    with pytest.raises(ValueError, match="Recipient"):
        mm.send("", "hello", from_agent="cyberclaw")


# --- Test 16: Memos dir created automatically ---
def test_memos_dir_autocreate(palaia_root):
    """MemoManager creates .palaia/memos/ if missing."""
    memos_dir = palaia_root / "memos"
    assert not memos_dir.exists()
    MemoManager(palaia_root)
    assert memos_dir.exists()


# --- Test 17: PALAIA_AGENT env var ---
def test_agent_env_var(mm, monkeypatch):
    """PALAIA_AGENT env var used as default agent."""
    monkeypatch.setenv("PALAIA_AGENT", "elliot")
    mm.send("elliot", "env test", from_agent="cyberclaw")
    inbox = mm.inbox()  # No agent param — uses env
    assert len(inbox) == 1


# --- Test 18: Inbox without agent raises ---
def test_inbox_no_agent(mm, monkeypatch):
    """inbox() without agent and no env var raises ValueError."""
    monkeypatch.delenv("PALAIA_AGENT", raising=False)
    with pytest.raises(ValueError, match="Agent name required"):
        mm.inbox()


# --- Test 19: Ack returns False for missing ---
def test_ack_missing_memo(mm):
    """ack() returns False for nonexistent memo."""
    assert mm.ack("does-not-exist") is False


# --- Test 20: Multiple memos ordering ---
def test_multiple_memos_newest_first(mm):
    """Multiple memos returned newest first within same priority."""
    mm.send("elliot", "first", from_agent="cyberclaw")
    time.sleep(0.01)
    mm.send("elliot", "second", from_agent="cyberclaw")

    inbox = mm.inbox(agent="elliot")
    assert len(inbox) == 2
    # Newest first
    assert inbox[0][1] == "second"
    assert inbox[1][1] == "first"


# --- Test 21: Broadcast + direct in same inbox ---
def test_broadcast_and_direct_mixed(mm):
    """Agent sees both direct memos and broadcasts."""
    mm.send("elliot", "direct msg", from_agent="cyberclaw")
    mm.broadcast("broadcast msg", from_agent="cyberclaw")

    inbox = mm.inbox(agent="elliot")
    assert len(inbox) == 2
    bodies = {b for _, b in inbox}
    assert "direct msg" in bodies
    assert "broadcast msg" in bodies


# --- Test 22: CLI JSON output for send ---
def test_cli_send_json(palaia_root, capsys):
    """CLI memo send --json returns valid JSON."""
    import argparse

    from palaia.cli import cmd_memo

    args = argparse.Namespace(
        memo_action="send",
        to="elliot",
        message="test msg",
        priority="normal",
        ttl_hours=72,
        agent="cyberclaw",
        json=True,
    )
    # Need to mock get_root
    import palaia.cli

    original_get_root = palaia.cli.get_root
    palaia.cli.get_root = lambda: palaia_root
    try:
        result = cmd_memo(args)
        assert result == 0
        output = capsys.readouterr().out
        data = json.loads(output)
        assert "id" in data
        assert data["to"] == "elliot"
    finally:
        palaia.cli.get_root = original_get_root


# --- Test 23: CLI JSON output for inbox ---
def test_cli_inbox_json(palaia_root, capsys):
    """CLI memo inbox --json returns valid JSON array."""
    import argparse

    from palaia.cli import cmd_memo

    mm = MemoManager(palaia_root)
    mm.send("elliot", "inbox test", from_agent="cyberclaw")

    import palaia.cli

    original_get_root = palaia.cli.get_root
    palaia.cli.get_root = lambda: palaia_root
    try:
        args = argparse.Namespace(
            memo_action="inbox",
            agent="elliot",
            all=False,
            json=True,
        )
        result = cmd_memo(args)
        assert result == 0
        output = capsys.readouterr().out
        data = json.loads(output)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["body"] == "inbox test"
    finally:
        palaia.cli.get_root = original_get_root


# --- Test 24: CLI JSON output for ack ---
def test_cli_ack_json(palaia_root, capsys):
    """CLI memo ack --json returns valid JSON."""
    import argparse

    from palaia.cli import cmd_memo

    mm = MemoManager(palaia_root)
    meta = mm.send("elliot", "ack test", from_agent="cyberclaw")

    import palaia.cli

    original_get_root = palaia.cli.get_root
    palaia.cli.get_root = lambda: palaia_root
    try:
        args = argparse.Namespace(
            memo_action="ack",
            memo_id=meta["id"],
            all=False,
            agent=None,
            json=True,
        )
        result = cmd_memo(args)
        assert result == 0
        output = capsys.readouterr().out
        data = json.loads(output)
        assert data["acked"] is True
    finally:
        palaia.cli.get_root = original_get_root


# --- Test 25: CLI JSON output for gc ---
def test_cli_gc_json(palaia_root, capsys):
    """CLI memo gc --json returns valid JSON with stats."""
    import argparse

    from palaia.cli import cmd_memo

    import palaia.cli

    original_get_root = palaia.cli.get_root
    palaia.cli.get_root = lambda: palaia_root
    try:
        args = argparse.Namespace(
            memo_action="gc",
            json=True,
        )
        result = cmd_memo(args)
        assert result == 0
        output = capsys.readouterr().out
        data = json.loads(output)
        assert "total_removed" in data
    finally:
        palaia.cli.get_root = original_get_root
