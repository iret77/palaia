"""Tests for palaia init without --agent (Issue #46) + Single-Agent Auto-Detect."""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def fresh_dir(tmp_path, monkeypatch):
    """A fresh directory with no .palaia — simulates first-time init."""
    work = tmp_path / "workspace"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("PALAIA_HOME", str(work))
    # Prevent fallback to real home .palaia and OpenClaw config auto-detect
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.delenv("OPENCLAW_CONFIG", raising=False)
    return work


@pytest.fixture
def existing_store(tmp_path, monkeypatch):
    """A directory with an existing .palaia and agent configured."""
    store = tmp_path / ".palaia"
    store.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (store / sub).mkdir()
    config = {
        "version": 1,
        "agent": "ExistingAgent",
        "embedding_chain": ["bm25"],
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
    }
    (store / "config.json").write_text(json.dumps(config))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PALAIA_HOME", str(store))
    return store


def _run_palaia(args, monkeypatch):
    """Run palaia CLI and return exit code."""
    from palaia.cli import main

    monkeypatch.setattr("sys.argv", ["palaia"] + args)
    return main()


class TestInitWithoutAgent:
    def test_fresh_init_without_agent_fails(self, fresh_dir, monkeypatch, capsys):
        """palaia init without --agent on fresh store must fail with clear error."""
        rc = _run_palaia(["init", "--path", str(fresh_dir)], monkeypatch)
        assert rc == 1
        captured = capsys.readouterr()
        assert "agent name required" in captured.err.lower()
        assert "palaia init --agent" in captured.err
        # .palaia directory should NOT have been created
        assert not (fresh_dir / ".palaia").exists()

    def test_fresh_init_without_agent_json(self, fresh_dir, monkeypatch, capsys):
        """JSON mode should return error too."""
        rc = _run_palaia(["init", "--path", str(fresh_dir), "--json"], monkeypatch)
        assert rc == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["error"] == "agent_required"

    def test_fresh_init_with_agent_succeeds(self, fresh_dir, monkeypatch, capsys):
        """palaia init --agent NAME on fresh store must succeed."""
        rc = _run_palaia(["init", "--path", str(fresh_dir), "--agent", "TestBot"], monkeypatch)
        assert rc == 0
        assert (fresh_dir / ".palaia").exists()
        config = json.loads((fresh_dir / ".palaia" / "config.json").read_text())
        assert config["agent"] == "TestBot"

    def test_reinit_without_agent_succeeds_if_agent_set(self, existing_store, monkeypatch, capsys):
        """Re-init without --agent when agent already configured must succeed."""
        rc = _run_palaia(["init"], monkeypatch)
        assert rc == 0
        # Agent should be preserved
        config = json.loads((existing_store / "config.json").read_text())
        assert config["agent"] == "ExistingAgent"

    def test_reinit_without_agent_fails_if_no_agent(self, tmp_path, monkeypatch, capsys):
        """Re-init without --agent when NO agent configured and no auto-detect must fail."""
        store = tmp_path / ".palaia"
        store.mkdir()
        for sub in ("hot", "warm", "cold", "wal", "index"):
            (store / sub).mkdir()
        config = {
            "version": 1,
            "embedding_chain": ["bm25"],
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
        }
        (store / "config.json").write_text(json.dumps(config))
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PALAIA_HOME", str(store))
        # Prevent auto-detect from OpenClaw config
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.delenv("OPENCLAW_CONFIG", raising=False)

        rc = _run_palaia(["init"], monkeypatch)
        assert rc == 1
        captured = capsys.readouterr()
        assert "agent name required" in captured.err.lower()


class TestSingleAgentAutoDetect:
    """Tests for auto-detecting agent from OpenClaw config."""

    def test_auto_detect_single_agent_list_format(self, tmp_path, monkeypatch, capsys):
        """Single agent in agents.list → auto-detect with confirmation message."""
        oc_dir = tmp_path / ".openclaw"
        oc_dir.mkdir()
        oc_config = {"agents": {"list": [{"id": "hal", "name": "HAL", "workspace": "/home/hal"}]}}
        (oc_dir / "openclaw.json").write_text(json.dumps(oc_config))
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.delenv("OPENCLAW_CONFIG", raising=False)

        work = tmp_path / "workspace"
        work.mkdir()
        monkeypatch.setenv("PALAIA_HOME", str(work))

        rc = _run_palaia(["init", "--path", str(work)], monkeypatch)
        assert rc == 0
        config = json.loads((work / ".palaia" / "config.json").read_text())
        assert config["agent"] == "HAL"
        captured = capsys.readouterr()
        assert "Auto-detected agent: HAL (from OpenClaw config)" in captured.out

    def test_auto_detect_single_agent_object_format(self, tmp_path, monkeypatch, capsys):
        """Single agent as object key → auto-detect."""
        oc_dir = tmp_path / ".openclaw"
        oc_dir.mkdir()
        oc_config = {"agents": {"hal": {"name": "HAL", "workspace": "/home/hal"}}}
        (oc_dir / "openclaw.json").write_text(json.dumps(oc_config))
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.delenv("OPENCLAW_CONFIG", raising=False)

        work = tmp_path / "workspace"
        work.mkdir()
        monkeypatch.setenv("PALAIA_HOME", str(work))

        rc = _run_palaia(["init", "--path", str(work)], monkeypatch)
        assert rc == 0
        config = json.loads((work / ".palaia" / "config.json").read_text())
        assert config["agent"] == "HAL"
        captured = capsys.readouterr()
        assert "Auto-detected agent: HAL (from OpenClaw config)" in captured.out

    def test_auto_detect_single_agent_config_json(self, tmp_path, monkeypatch, capsys):
        """Auto-detect from ~/.openclaw/config.json (alternative config path)."""
        oc_dir = tmp_path / ".openclaw"
        oc_dir.mkdir()
        oc_config = {"agents": {"list": [{"id": "hal", "name": "HAL"}]}}
        (oc_dir / "config.json").write_text(json.dumps(oc_config))
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.delenv("OPENCLAW_CONFIG", raising=False)

        work = tmp_path / "workspace"
        work.mkdir()
        monkeypatch.setenv("PALAIA_HOME", str(work))

        rc = _run_palaia(["init", "--path", str(work)], monkeypatch)
        assert rc == 0
        config = json.loads((work / ".palaia" / "config.json").read_text())
        assert config["agent"] == "HAL"

    def test_auto_detect_default_agent_multi(self, tmp_path, monkeypatch, capsys):
        """Multiple agents with default:true → pick the default."""
        oc_dir = tmp_path / ".openclaw"
        oc_dir.mkdir()
        oc_config = {
            "agents": {
                "list": [
                    {"id": "main", "name": "CyberClaw", "default": True},
                    {"id": "elliot", "name": "Elliot"},
                    {"id": "saul", "name": "Saul"},
                ]
            }
        }
        (oc_dir / "openclaw.json").write_text(json.dumps(oc_config))
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.delenv("OPENCLAW_CONFIG", raising=False)

        work = tmp_path / "workspace"
        work.mkdir()
        monkeypatch.setenv("PALAIA_HOME", str(work))

        rc = _run_palaia(["init", "--path", str(work)], monkeypatch)
        assert rc == 0
        config = json.loads((work / ".palaia" / "config.json").read_text())
        assert config["agent"] == "CyberClaw"


class TestMultiAgentErrors:
    """Tests for multi-agent error messages."""

    def test_multiple_agents_no_default_list_format(self, tmp_path, monkeypatch, capsys):
        """Multiple agents without default:true → 'Multiple agents found' error."""
        oc_dir = tmp_path / ".openclaw"
        oc_dir.mkdir()
        oc_config = {
            "agents": {
                "list": [
                    {"id": "agent1", "name": "Agent1"},
                    {"id": "agent2", "name": "Agent2"},
                ]
            }
        }
        (oc_dir / "openclaw.json").write_text(json.dumps(oc_config))
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.delenv("OPENCLAW_CONFIG", raising=False)

        work = tmp_path / "workspace"
        work.mkdir()
        monkeypatch.setenv("PALAIA_HOME", str(work))

        rc = _run_palaia(["init", "--path", str(work)], monkeypatch)
        assert rc == 1
        captured = capsys.readouterr()
        assert "multiple agents found" in captured.err.lower()
        assert "palaia init --agent" in captured.err

    def test_multiple_agents_no_default_object_format(self, tmp_path, monkeypatch, capsys):
        """Multiple agents as object without default:true → 'Multiple agents found'."""
        oc_dir = tmp_path / ".openclaw"
        oc_dir.mkdir()
        oc_config = {"agents": {"hal": {"name": "HAL"}, "jarvis": {"name": "JARVIS"}}}
        (oc_dir / "openclaw.json").write_text(json.dumps(oc_config))
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.delenv("OPENCLAW_CONFIG", raising=False)

        work = tmp_path / "workspace"
        work.mkdir()
        monkeypatch.setenv("PALAIA_HOME", str(work))

        rc = _run_palaia(["init", "--path", str(work)], monkeypatch)
        assert rc == 1
        captured = capsys.readouterr()
        assert "multiple agents found" in captured.err.lower()

    def test_no_openclaw_config_fails(self, fresh_dir, monkeypatch, capsys):
        """No OpenClaw config → generic 'Agent name required' error."""
        rc = _run_palaia(["init", "--path", str(fresh_dir)], monkeypatch)
        assert rc == 1
        captured = capsys.readouterr()
        assert "agent name required" in captured.err.lower()
        assert "palaia init --agent" in captured.err


class TestSingleToMultiMigration:
    """UX-Audit: Single→Multi agent migration scenarios."""

    def test_reinit_agent_name_change_preserves_old_entries(self, existing_store, monkeypatch, capsys):
        """Re-init with different agent name must NOT rewrite existing entries."""
        config = json.loads((existing_store / "config.json").read_text())
        assert config["agent"] == "ExistingAgent"

        # Write an entry with the old agent name
        hot_dir = existing_store / "hot"
        entry = {
            "id": "test-entry-1",
            "text": "Test entry",
            "agent": "ExistingAgent",
            "scope": "private",
        }
        (hot_dir / "test-entry-1.json").write_text(json.dumps(entry))

        # Re-init with new agent name
        rc = _run_palaia(["init", "--agent", "NewAgent"], monkeypatch)
        assert rc == 0
        new_config = json.loads((existing_store / "config.json").read_text())
        assert new_config["agent"] == "NewAgent"

        # Old entry still has old agent name — no rewrite!
        old_entry = json.loads((hot_dir / "test-entry-1.json").read_text())
        assert old_entry["agent"] == "ExistingAgent"

    def test_second_agent_init_shared_store(self, existing_store, monkeypatch, capsys):
        """Second agent can init on same shared store with explicit --agent."""
        config = json.loads((existing_store / "config.json").read_text())
        assert config["agent"] == "ExistingAgent"

        # Re-init with a different agent name (simulating second agent)
        rc = _run_palaia(["init", "--agent", "JARVIS"], monkeypatch)
        assert rc == 0
        new_config = json.loads((existing_store / "config.json").read_text())
        assert new_config["agent"] == "JARVIS"

    def test_reinit_without_agent_preserves_existing(self, existing_store, monkeypatch, capsys):
        """Re-init without --agent when agent already set → preserve existing agent."""
        rc = _run_palaia(["init"], monkeypatch)
        assert rc == 0
        config = json.loads((existing_store / "config.json").read_text())
        assert config["agent"] == "ExistingAgent"

    def test_reinit_without_agent_multi_config_existing_agent_ok(self, tmp_path, monkeypatch, capsys):
        """Re-init without --agent with multi-agent OpenClaw config but agent already set → OK."""
        store = tmp_path / ".palaia"
        store.mkdir()
        for sub in ("hot", "warm", "cold", "wal", "index"):
            (store / sub).mkdir()
        config = {
            "version": 1,
            "agent": "HAL",
            "embedding_chain": ["bm25"],
        }
        (store / "config.json").write_text(json.dumps(config))
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PALAIA_HOME", str(store))

        # Multi-agent OpenClaw config
        oc_dir = tmp_path / ".openclaw"
        oc_dir.mkdir()
        oc_config = {
            "agents": {
                "list": [
                    {"id": "hal", "name": "HAL"},
                    {"id": "jarvis", "name": "JARVIS"},
                ]
            }
        }
        (oc_dir / "openclaw.json").write_text(json.dumps(oc_config))
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.delenv("OPENCLAW_CONFIG", raising=False)

        # Re-init without --agent should succeed since agent already configured
        rc = _run_palaia(["init"], monkeypatch)
        assert rc == 0
        result_config = json.loads((store / "config.json").read_text())
        assert result_config["agent"] == "HAL"
