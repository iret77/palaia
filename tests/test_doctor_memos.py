"""Tests for doctor unread memos check (#42)."""

import pytest

from palaia.config import DEFAULT_CONFIG, save_config
from palaia.doctor import run_doctor
from palaia.memo import MemoManager


@pytest.fixture
def palaia_root(tmp_path):
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index", "memos"):
        (root / sub).mkdir()
    config = dict(DEFAULT_CONFIG)
    config["agent"] = "testbot"
    save_config(root, config)
    return root


def _find_check(results, name):
    """Find a specific check result by name."""
    for r in results:
        if r["name"] == name:
            return r
    return None


def test_doctor_no_memos(palaia_root):
    """Doctor reports ok when no memos exist."""
    results = run_doctor(palaia_root)
    check = _find_check(results, "unread_memos")
    assert check is not None
    assert check["status"] == "ok"
    assert "No unread" in check["message"]


def test_doctor_unread_memos(palaia_root):
    """Doctor warns when unread memos exist."""
    mm = MemoManager(palaia_root)
    mm.send(to="testbot", message="Hey testbot, check this!", from_agent="cyberclaw")

    results = run_doctor(palaia_root)
    check = _find_check(results, "unread_memos")
    assert check is not None
    assert check["status"] == "warn"
    assert "1 unread" in check["message"]
    assert check["fix"] == "Run: palaia memo inbox"


def test_doctor_multiple_unread_memos(palaia_root):
    """Doctor shows count of multiple unread memos."""
    mm = MemoManager(palaia_root)
    mm.send(to="testbot", message="First memo", from_agent="agent1")
    mm.send(to="testbot", message="Second memo", from_agent="agent2")
    mm.send(to="_broadcast", message="Broadcast memo", from_agent="agent3")

    results = run_doctor(palaia_root)
    check = _find_check(results, "unread_memos")
    assert check is not None
    assert check["status"] == "warn"
    assert "3 unread" in check["message"]


def test_doctor_read_memos_not_counted(palaia_root):
    """Doctor doesn't count already-read memos."""
    mm = MemoManager(palaia_root)
    meta = mm.send(to="testbot", message="Read this", from_agent="cyberclaw")
    mm.ack(meta["id"])

    results = run_doctor(palaia_root)
    check = _find_check(results, "unread_memos")
    assert check is not None
    assert check["status"] == "ok"


def test_doctor_memos_for_other_agent(palaia_root):
    """Doctor doesn't count memos addressed to other agents."""
    mm = MemoManager(palaia_root)
    mm.send(to="otheragent", message="Not for you", from_agent="cyberclaw")

    results = run_doctor(palaia_root)
    check = _find_check(results, "unread_memos")
    assert check is not None
    assert check["status"] == "ok"


def test_doctor_memo_previews_in_details(palaia_root):
    """Doctor includes memo previews in details for --fix display."""
    mm = MemoManager(palaia_root)
    mm.send(to="testbot", message="Important update about deployment", from_agent="cyberclaw", priority="high")

    results = run_doctor(palaia_root)
    check = _find_check(results, "unread_memos")
    assert check is not None
    assert "previews" in check.get("details", {})
    previews = check["details"]["previews"]
    assert len(previews) == 1
    assert "cyberclaw" in previews[0]
    assert "[high]" in previews[0]


def test_doctor_no_init(tmp_path):
    """Doctor handles uninitialized state gracefully."""
    results = run_doctor(None)
    check = _find_check(results, "unread_memos")
    assert check is not None
    assert check["status"] == "ok"
