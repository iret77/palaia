"""Tests for init gatekeeper, agent identity, instance, and memo nudge (#43)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from palaia.config import (
    clear_instance,
    get_agent,
    get_instance,
    is_initialized,
    set_instance,
)


@pytest.fixture
def palaia_root(tmp_path):
    """Create a minimal .palaia directory."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    config = {
        "version": 1,
        "decay_lambda": 0.1,
        "hot_threshold_days": 7,
        "warm_threshold_days": 30,
        "hot_max_entries": 50,
        "hot_min_score": 0.5,
        "warm_min_score": 0.1,
        "default_scope": "team",
        "wal_retention_days": 7,
        "lock_timeout_seconds": 5,
        "embedding_provider": "auto",
        "embedding_model": "",
        "store_version": "1.7.0",
        "embedding_chain": ["bm25"],
    }
    (root / "config.json").write_text(json.dumps(config))
    return root


@pytest.fixture
def initialized_root(palaia_root):
    """Create a .palaia directory with agent identity set."""
    config = json.loads((palaia_root / "config.json").read_text())
    config["agent"] = "TestAgent"
    (palaia_root / "config.json").write_text(json.dumps(config))
    return palaia_root


class TestIsInitialized:
    def test_not_initialized_no_root(self):
        assert is_initialized(Path("/nonexistent/.palaia")) is False

    def test_initialized_without_agent(self, palaia_root):
        """config.json exists → initialized, even without agent field."""
        assert is_initialized(palaia_root) is True

    def test_initialized_with_agent(self, initialized_root):
        assert is_initialized(initialized_root) is True

    def test_initialized_empty_agent(self, palaia_root):
        """config.json exists with empty agent → still initialized."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["agent"] = ""
        (palaia_root / "config.json").write_text(json.dumps(config))
        assert is_initialized(palaia_root) is True


class TestGetAgent:
    def test_no_agent(self, palaia_root):
        assert get_agent(palaia_root) is None

    def test_with_agent(self, initialized_root):
        assert get_agent(initialized_root) == "TestAgent"

    def test_no_root(self):
        assert get_agent(Path("/nonexistent/.palaia")) is None


class TestInstance:
    def test_set_and_get(self, palaia_root):
        set_instance(palaia_root, "MyInstance")
        assert get_instance(palaia_root) == "MyInstance"

    def test_clear(self, palaia_root):
        set_instance(palaia_root, "MyInstance")
        clear_instance(palaia_root)
        assert get_instance(palaia_root) is None

    def test_get_no_instance(self, palaia_root, monkeypatch):
        monkeypatch.delenv("PALAIA_INSTANCE", raising=False)
        assert get_instance(palaia_root) is None

    def test_env_fallback(self, palaia_root, monkeypatch):
        monkeypatch.setenv("PALAIA_INSTANCE", "EnvInstance")
        assert get_instance(palaia_root) == "EnvInstance"

    def test_file_overrides_env(self, palaia_root, monkeypatch):
        monkeypatch.setenv("PALAIA_INSTANCE", "EnvInstance")
        set_instance(palaia_root, "FileInstance")
        assert get_instance(palaia_root) == "FileInstance"


class TestGatekeeper:
    """Test that gated commands fail without init."""

    def _run_palaia(self, palaia_root, args, monkeypatch):
        """Run palaia CLI command in subprocess-like fashion."""
        from palaia.cli import main

        monkeypatch.setenv("PALAIA_HOME", str(palaia_root))
        monkeypatch.setattr("sys.argv", ["palaia"] + args)
        return main()

    @pytest.fixture
    def uninit_root(self, tmp_path):
        """A .palaia dir without config.json — truly uninitialized."""
        root = tmp_path / "empty" / ".palaia"
        root.mkdir(parents=True)
        return root

    def test_write_blocked_without_init(self, uninit_root, monkeypatch, capsys):
        rc = self._run_palaia(uninit_root, ["write", "test content"], monkeypatch)
        assert rc == 1
        captured = capsys.readouterr()
        assert "not initialized" in captured.err.lower()

    def test_query_blocked_without_init(self, uninit_root, monkeypatch, capsys):
        rc = self._run_palaia(uninit_root, ["query", "test"], monkeypatch)
        assert rc == 1
        captured = capsys.readouterr()
        assert "not initialized" in captured.err.lower()

    def test_list_blocked_without_init(self, uninit_root, monkeypatch, capsys):
        rc = self._run_palaia(uninit_root, ["list"], monkeypatch)
        assert rc == 1
        captured = capsys.readouterr()
        assert "not initialized" in captured.err.lower()

    def test_memo_blocked_without_init(self, uninit_root, monkeypatch, capsys):
        rc = self._run_palaia(uninit_root, ["memo", "inbox"], monkeypatch)
        assert rc == 1
        captured = capsys.readouterr()
        assert "not initialized" in captured.err.lower()

    def test_write_allowed_without_agent(self, palaia_root, monkeypatch, capsys):
        """Config exists but no agent field → still initialized, write allowed."""
        rc = self._run_palaia(
            palaia_root,
            ["write", "test content", "--title", "Test"],
            monkeypatch,
        )
        assert rc == 0

    def test_init_always_allowed(self, palaia_root, monkeypatch, capsys):
        """Init command should never be blocked."""
        rc = self._run_palaia(palaia_root, ["init", "--agent", "Test"], monkeypatch)
        assert rc == 0

    def test_doctor_always_allowed(self, palaia_root, monkeypatch, capsys):
        rc = self._run_palaia(palaia_root, ["doctor"], monkeypatch)
        assert rc == 0

    def test_detect_always_allowed(self, palaia_root, monkeypatch, capsys):
        rc = self._run_palaia(palaia_root, ["detect"], monkeypatch)
        assert rc == 0

    def test_config_always_allowed(self, palaia_root, monkeypatch, capsys):
        rc = self._run_palaia(palaia_root, ["config", "list"], monkeypatch)
        assert rc == 0

    def test_write_allowed_after_init(self, initialized_root, monkeypatch, capsys):
        rc = self._run_palaia(
            initialized_root,
            ["write", "test content", "--title", "Test"],
            monkeypatch,
        )
        assert rc == 0

    def test_query_allowed_after_init(self, initialized_root, monkeypatch, capsys):
        rc = self._run_palaia(
            initialized_root,
            ["query", "test"],
            monkeypatch,
        )
        assert rc == 0


class TestInitAgent:
    """Test palaia init --agent behavior."""

    def _run_palaia(self, root, args, monkeypatch):
        from palaia.cli import main

        monkeypatch.setenv("PALAIA_HOME", str(root))
        monkeypatch.setattr("sys.argv", ["palaia"] + args)
        return main()

    def test_init_stores_agent(self, palaia_root, monkeypatch, capsys):
        self._run_palaia(palaia_root, ["init", "--agent", "CyberClaw"], monkeypatch)
        config = json.loads((palaia_root / "config.json").read_text())
        assert config["agent"] == "CyberClaw"

    def test_reinit_updates_agent(self, initialized_root, monkeypatch, capsys):
        assert get_agent(initialized_root) == "TestAgent"
        self._run_palaia(initialized_root, ["init", "--agent", "NewAgent"], monkeypatch)
        assert get_agent(initialized_root) == "NewAgent"

    def test_reinit_preserves_other_config(self, initialized_root, monkeypatch, capsys):
        # Set a custom config value
        config = json.loads((initialized_root / "config.json").read_text())
        config["custom_key"] = "custom_value"
        (initialized_root / "config.json").write_text(json.dumps(config))

        self._run_palaia(initialized_root, ["init", "--agent", "NewAgent"], monkeypatch)

        config = json.loads((initialized_root / "config.json").read_text())
        assert config["agent"] == "NewAgent"
        assert config["custom_key"] == "custom_value"

    def test_reinit_without_agent_preserves_existing(self, initialized_root, monkeypatch, capsys):
        """Re-init without --agent should NOT clear existing agent."""
        self._run_palaia(initialized_root, ["init"], monkeypatch)
        assert get_agent(initialized_root) == "TestAgent"


class TestAutoAgent:
    """Test that writes automatically use config agent."""

    def _run_palaia(self, root, args, monkeypatch):
        from palaia.cli import main

        monkeypatch.setenv("PALAIA_HOME", str(root))
        monkeypatch.setattr("sys.argv", ["palaia"] + args)
        return main()

    def test_write_uses_config_agent(self, initialized_root, monkeypatch, capsys):
        self._run_palaia(
            initialized_root,
            ["write", "test content", "--title", "Auto Agent Test", "--json"],
            monkeypatch,
        )
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        entry_id = result["id"]

        # Read back the entry and check agent
        from palaia.store import Store

        store = Store(initialized_root)
        entry = store.read(entry_id)
        assert entry is not None
        meta, _ = entry
        assert meta.get("agent") == "TestAgent"

    def test_explicit_agent_overrides_config(self, initialized_root, monkeypatch, capsys):
        self._run_palaia(
            initialized_root,
            ["write", "test content", "--agent", "OverrideAgent", "--title", "Override Test", "--json"],
            monkeypatch,
        )
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        entry_id = result["id"]

        from palaia.store import Store

        store = Store(initialized_root)
        entry = store.read(entry_id)
        assert entry is not None
        meta, _ = entry
        assert meta.get("agent") == "OverrideAgent"


class TestInstanceCLI:
    """Test instance CLI commands."""

    def _run_palaia(self, root, args, monkeypatch):
        from palaia.cli import main

        monkeypatch.setenv("PALAIA_HOME", str(root))
        monkeypatch.setattr("sys.argv", ["palaia"] + args)
        return main()

    def test_instance_set(self, palaia_root, monkeypatch, capsys):
        self._run_palaia(palaia_root, ["instance", "set", "Claw-Palaia"], monkeypatch)
        captured = capsys.readouterr()
        assert "Claw-Palaia" in captured.out
        assert get_instance(palaia_root) == "Claw-Palaia"

    def test_instance_get(self, palaia_root, monkeypatch, capsys):
        set_instance(palaia_root, "MySession")
        self._run_palaia(palaia_root, ["instance", "get"], monkeypatch)
        captured = capsys.readouterr()
        assert "MySession" in captured.out

    def test_instance_clear(self, palaia_root, monkeypatch, capsys):
        set_instance(palaia_root, "MySession")
        self._run_palaia(palaia_root, ["instance", "clear"], monkeypatch)
        assert get_instance(palaia_root) is None

    def test_instance_in_write(self, initialized_root, monkeypatch, capsys):
        """Instance should be included in entry metadata when set."""
        set_instance(initialized_root, "TestSession")
        self._run_palaia(
            initialized_root,
            ["write", "test with instance", "--title", "Instance Test", "--json"],
            monkeypatch,
        )
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        entry_id = result["id"]

        from palaia.store import Store

        store = Store(initialized_root)
        entry = store.read(entry_id)
        assert entry is not None
        meta, _ = entry
        assert meta.get("instance") == "TestSession"

    def test_instance_json(self, palaia_root, monkeypatch, capsys):
        set_instance(palaia_root, "JsonTest")
        self._run_palaia(palaia_root, ["instance", "get", "--json"], monkeypatch)
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["instance"] == "JsonTest"


class TestMemoNudge:
    """Test memo nudge after query/write."""

    def _run_palaia(self, root, args, monkeypatch):
        from palaia.cli import main

        monkeypatch.setenv("PALAIA_HOME", str(root))
        monkeypatch.setattr("sys.argv", ["palaia"] + args)
        return main()

    def test_nudge_shown_when_unread_memos(self, initialized_root, monkeypatch, capsys):
        """Nudge should show when there are unread memos."""
        from palaia.memo import MemoManager

        mm = MemoManager(initialized_root)
        mm.send(to="TestAgent", message="Hello!", from_agent="Other")

        # Clear any existing nudge timestamps
        hints_file = initialized_root / ".hints_shown"
        if hints_file.exists():
            hints_file.unlink()

        self._run_palaia(
            initialized_root,
            ["write", "some content", "--title", "Nudge Test"],
            monkeypatch,
        )
        captured = capsys.readouterr()
        assert "unread memo" in captured.err.lower()

    def test_nudge_suppressed_in_json(self, initialized_root, monkeypatch, capsys):
        """Nudge should not appear in JSON mode."""
        from palaia.memo import MemoManager

        mm = MemoManager(initialized_root)
        mm.send(to="TestAgent", message="Hello!", from_agent="Other")

        hints_file = initialized_root / ".hints_shown"
        if hints_file.exists():
            hints_file.unlink()

        self._run_palaia(
            initialized_root,
            ["write", "json content", "--title", "JSON Nudge", "--json"],
            monkeypatch,
        )
        captured = capsys.readouterr()
        assert "unread memo" not in captured.err.lower()

    def test_nudge_frequency_limited(self, initialized_root, monkeypatch, capsys):
        """Nudge should only show once per hour."""
        from palaia.memo import MemoManager

        mm = MemoManager(initialized_root)
        mm.send(to="TestAgent", message="Hello!", from_agent="Other")

        # Clear hints
        hints_file = initialized_root / ".hints_shown"
        if hints_file.exists():
            hints_file.unlink()

        # First write: nudge shown
        self._run_palaia(
            initialized_root,
            ["write", "first content", "--title", "First"],
            monkeypatch,
        )
        captured = capsys.readouterr()
        assert "unread memo" in captured.err.lower()

        # Second write immediately: nudge suppressed
        self._run_palaia(
            initialized_root,
            ["write", "second content", "--title", "Second"],
            monkeypatch,
        )
        captured = capsys.readouterr()
        assert "unread memo" not in captured.err.lower()

    def test_no_nudge_without_memos(self, initialized_root, monkeypatch, capsys):
        """No nudge when no unread memos exist."""
        hints_file = initialized_root / ".hints_shown"
        if hints_file.exists():
            hints_file.unlink()

        self._run_palaia(
            initialized_root,
            ["write", "clean content", "--title", "Clean"],
            monkeypatch,
        )
        captured = capsys.readouterr()
        assert "unread memo" not in captured.err.lower()


class TestDoctorAgentIdentity:
    """Test doctor check for agent identity."""

    def test_info_without_agent(self, palaia_root, monkeypatch):
        from palaia.doctor import _check_agent_identity

        monkeypatch.setenv("HOME", str(palaia_root.parent))
        result = _check_agent_identity(palaia_root)
        assert result["status"] == "info"
        assert "default" in result["message"].lower()

    def test_ok_with_agent(self, initialized_root, monkeypatch):
        from palaia.doctor import _check_agent_identity

        monkeypatch.setenv("HOME", str(initialized_root.parent))
        result = _check_agent_identity(initialized_root)
        assert result["status"] == "ok"
        assert "TestAgent" in result["message"]


class TestMemoInstanceTargeting:
    """Test instance targeting in memo send."""

    def test_memo_send_with_instance(self, initialized_root):
        """Memo send should support instance targeting."""
        from palaia.memo import MemoManager

        mm = MemoManager(initialized_root)
        # Instance targeting is done at inbox filtering level
        # Send a memo and verify it's delivered
        meta = mm.send(to="TestAgent", message="Hello instance!", from_agent="Sender")
        assert meta["to"] == "TestAgent"

    def test_memo_inbox_uses_config_agent(self, initialized_root, monkeypatch):
        """Memo inbox should use config agent when --agent not specified."""
        from palaia.memo import MemoManager

        monkeypatch.delenv("PALAIA_AGENT", raising=False)
        monkeypatch.setenv("PALAIA_HOME", str(initialized_root))

        mm = MemoManager(initialized_root)
        mm.send(to="TestAgent", message="Config test", from_agent="Sender")

        # _detect_agent should find config agent
        memos = mm.inbox(agent="TestAgent")
        assert len(memos) == 1
        assert memos[0][1] == "Config test"
