"""Tests for multi-agent agent resolution (resolve_agent, init multi-agent, private scope guard)."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from palaia.config import (
    DEFAULT_CONFIG,
    find_palaia_root,
    load_config,
    resolve_agent,
    save_config,
)


@pytest.fixture
def palaia_root(tmp_path):
    """Create a minimal .palaia directory with config."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    config = dict(DEFAULT_CONFIG)
    config["agent"] = "elliot"
    save_config(root, config)
    return root


@pytest.fixture
def multi_agent_root(tmp_path):
    """Create a multi-agent .palaia directory (agent=null, multi_agent=true)."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    config = dict(DEFAULT_CONFIG)
    config["agent"] = None
    config["multi_agent"] = True
    save_config(root, config)
    return root


class TestResolveAgent:
    """Tests for config.resolve_agent()."""

    def test_env_var_takes_precedence(self, palaia_root):
        """PALAIA_AGENT env var overrides config.json agent."""
        with patch.dict(os.environ, {"PALAIA_AGENT": "cyberclaw"}):
            result = resolve_agent(palaia_root)
        assert result == "cyberclaw"

    def test_config_agent_used_when_no_env(self, palaia_root):
        """Falls back to config.json agent when PALAIA_AGENT is not set."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove PALAIA_AGENT if present
            env = dict(os.environ)
            env.pop("PALAIA_AGENT", None)
            with patch.dict(os.environ, env, clear=True):
                result = resolve_agent(palaia_root)
        assert result == "elliot"

    def test_returns_none_when_no_agent(self, multi_agent_root):
        """Returns None when no env var and config agent is null."""
        env = dict(os.environ)
        env.pop("PALAIA_AGENT", None)
        with patch.dict(os.environ, env, clear=True):
            result = resolve_agent(multi_agent_root)
        assert result is None

    def test_require_raises_when_no_agent(self, multi_agent_root):
        """Raises ValueError when require=True and no agent can be resolved."""
        env = dict(os.environ)
        env.pop("PALAIA_AGENT", None)
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="Cannot resolve agent identity"):
                resolve_agent(multi_agent_root, require=True)

    def test_require_ok_with_env_var(self, multi_agent_root):
        """require=True succeeds when PALAIA_AGENT is set."""
        with patch.dict(os.environ, {"PALAIA_AGENT": "elliot"}):
            result = resolve_agent(multi_agent_root, require=True)
        assert result == "elliot"

    def test_empty_env_var_ignored(self, multi_agent_root):
        """Empty PALAIA_AGENT is treated as unset."""
        with patch.dict(os.environ, {"PALAIA_AGENT": "  "}):
            result = resolve_agent(multi_agent_root)
        assert result is None


class TestCmdWritePrivateScope:
    """Tests for private scope guard in cmd_write."""

    def test_private_write_without_agent_in_multi_agent_errors(self, multi_agent_root, capsys):
        """Private write in multi-agent setup without PALAIA_AGENT should error."""
        from palaia.cli import cmd_write

        # Build minimal args
        class Args:
            text = "test content"
            scope = "private"
            agent = None
            tags = None
            title = None
            project = None
            type = None
            status = None
            priority = None
            assignee = None
            due_date = None
            instance = None
            json = False

        env = dict(os.environ)
        env.pop("PALAIA_AGENT", None)
        env["PALAIA_HOME"] = str(multi_agent_root)

        with patch.dict(os.environ, env, clear=True):
            with patch("palaia.cli.get_root", return_value=multi_agent_root):
                with patch("palaia.cli.check_version_nag"):
                    result = cmd_write(Args())

        assert result == 1
        captured = capsys.readouterr()
        assert "Cannot write with scope 'private' without an agent identity" in captured.err

    def test_team_write_without_agent_in_multi_agent_ok(self, multi_agent_root):
        """Team write in multi-agent setup without PALAIA_AGENT should succeed."""
        from palaia.cli import cmd_write
        from palaia.store import Store

        class Args:
            text = "team content that is long enough to not be trivial"
            scope = "team"
            agent = None
            tags = None
            title = None
            project = None
            type = None
            status = None
            priority = None
            assignee = None
            due_date = None
            instance = None
            json = False

        env = dict(os.environ)
        env.pop("PALAIA_AGENT", None)
        env["PALAIA_HOME"] = str(multi_agent_root)

        with patch.dict(os.environ, env, clear=True):
            with patch("palaia.cli.get_root", return_value=multi_agent_root):
                with patch("palaia.cli.check_version_nag"):
                    result = cmd_write(Args())

        # Should succeed (return 0 or None)
        assert result is None or result == 0


class TestInitMultiAgent:
    """Tests for init multi-agent detection."""

    def test_init_multi_agent_sets_null_agent(self, tmp_path):
        """When multiple agents are detected, config.agent should be None."""
        target = tmp_path / ".palaia"
        target.mkdir()
        for sub in ("hot", "warm", "cold", "wal", "index"):
            (target / sub).mkdir()

        config = dict(DEFAULT_CONFIG)
        config["agent"] = None
        config["multi_agent"] = True
        save_config(target, config)

        loaded = load_config(target)
        assert loaded.get("agent") is None
        assert loaded.get("multi_agent") is True

    def test_init_single_agent_keeps_agent(self, tmp_path):
        """When single agent, config.agent should be set normally."""
        target = tmp_path / ".palaia"
        target.mkdir()

        config = dict(DEFAULT_CONFIG)
        config["agent"] = "main"
        config["multi_agent"] = False
        save_config(target, config)

        loaded = load_config(target)
        assert loaded["agent"] == "main"
        assert loaded["multi_agent"] is False


class TestDoctorMultiAgentStatic:
    """Tests for doctor multi-agent static agent warning."""

    def test_warns_on_static_agent_in_multi_agent(self, tmp_path):
        """Doctor should warn when multi_agent=true but agent is set."""
        from palaia.doctor import _check_multi_agent_static

        root = tmp_path / ".palaia"
        root.mkdir()
        config = dict(DEFAULT_CONFIG)
        config["agent"] = "elliot"
        config["multi_agent"] = True
        save_config(root, config)

        result = _check_multi_agent_static(root)
        assert result["status"] == "warn"
        assert "static agent" in result["message"]

    def test_ok_when_multi_agent_no_static(self, tmp_path):
        """Doctor should be OK when multi_agent=true and no static agent."""
        from palaia.doctor import _check_multi_agent_static

        root = tmp_path / ".palaia"
        root.mkdir()
        config = dict(DEFAULT_CONFIG)
        config["agent"] = None
        config["multi_agent"] = True
        save_config(root, config)

        result = _check_multi_agent_static(root)
        assert result["status"] == "ok"

    def test_ok_when_single_agent(self, tmp_path):
        """Doctor should be OK for single-agent setups."""
        from palaia.doctor import _check_multi_agent_static

        root = tmp_path / ".palaia"
        root.mkdir()
        config = dict(DEFAULT_CONFIG)
        config["agent"] = "main"
        config["multi_agent"] = False
        save_config(root, config)

        result = _check_multi_agent_static(root)
        assert result["status"] == "ok"
