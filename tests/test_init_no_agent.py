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
    def test_fresh_init_without_agent_defaults_to_default(self, fresh_dir, monkeypatch, capsys):
        """palaia init without --agent on fresh store must succeed with agent='default'."""
        rc = _run_palaia(["init", "--path", str(fresh_dir)], monkeypatch)
        assert rc == 0
        assert (fresh_dir / ".palaia").exists()
        config = json.loads((fresh_dir / ".palaia" / "config.json").read_text())
        assert config["agent"] == "default"
        captured = capsys.readouterr()
        assert "use --agent NAME to customize" in captured.out

    def test_fresh_init_without_agent_gatekeeper_ok(self, fresh_dir, monkeypatch, capsys):
        """After init without --agent, gatekeeper must allow store commands."""
        rc = _run_palaia(["init", "--path", str(fresh_dir)], monkeypatch)
        assert rc == 0
        # is_initialized should return True
        from palaia.config import is_initialized

        assert is_initialized(fresh_dir / ".palaia") is True

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

    def test_reinit_without_agent_defaults_if_no_agent(self, tmp_path, monkeypatch, capsys):
        """Re-init without --agent when NO agent configured → defaults to 'default'."""
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
        assert rc == 0
        result_config = json.loads((store / "config.json").read_text())
        assert result_config["agent"] == "default"


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


class TestMultiAgentAutoDetectFallback:
    """Tests for multi-agent scenarios where auto-detect can't pick one → defaults to 'default'."""

    def test_multiple_agents_no_default_uses_default(self, tmp_path, monkeypatch, capsys):
        """Multiple agents without default:true → falls back to agent='default'."""
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
        assert rc == 0
        config = json.loads((work / ".palaia" / "config.json").read_text())
        assert config["agent"] == "default"

    def test_no_openclaw_config_uses_default(self, fresh_dir, monkeypatch, capsys):
        """No OpenClaw config → agent='default'."""
        rc = _run_palaia(["init", "--path", str(fresh_dir)], monkeypatch)
        assert rc == 0
        config = json.loads((fresh_dir / ".palaia" / "config.json").read_text())
        assert config["agent"] == "default"
        captured = capsys.readouterr()
        assert "use --agent NAME to customize" in captured.out


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


class TestMultiAgentScopeAndMemo:
    """UX-Audit: Verify scope isolation and memo routing in multi-agent shared store."""

    @pytest.fixture
    def shared_store(self, tmp_path):
        """Shared .palaia store with two agents."""
        store = tmp_path / ".palaia"
        store.mkdir()
        for sub in ("hot", "warm", "cold", "wal", "index", "memos"):
            (store / sub).mkdir()
        config = {
            "version": 1,
            "agent": "HAL",
            "embedding_chain": ["bm25"],
            "store_version": "1.7.0",
            "store_mode": "shared",
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
        return store

    def test_private_scope_isolation(self, shared_store):
        """Agent HAL's private entries should not be visible to JARVIS."""
        from palaia.store import Store

        store = Store(shared_store)

        # HAL writes a private entry
        eid = store.write(body="HAL's secret", scope="private", agent="HAL", title="Secret")

        # HAL can read it
        entry = store.read(eid, agent="HAL")
        assert entry is not None

        # JARVIS cannot
        entry = store.read(eid, agent="JARVIS")
        assert entry is None

    def test_team_scope_shared(self, shared_store):
        """Team-scoped entries are visible to all agents."""
        from palaia.store import Store

        store = Store(shared_store)

        eid = store.write(body="Team knowledge", scope="team", agent="HAL", title="Shared")

        # Both can read
        assert store.read(eid, agent="HAL") is not None
        assert store.read(eid, agent="JARVIS") is not None

    def test_memo_routing_correct(self, shared_store):
        """Memos to HAL should not appear in JARVIS's inbox."""
        from palaia.memo import MemoManager

        mm = MemoManager(shared_store)

        mm.send(to="HAL", message="For HAL only", from_agent="JARVIS")
        mm.send(to="JARVIS", message="For JARVIS only", from_agent="HAL")

        hal_inbox = mm.inbox(agent="HAL")
        jarvis_inbox = mm.inbox(agent="JARVIS")

        assert len(hal_inbox) == 1
        assert hal_inbox[0][1] == "For HAL only"
        assert len(jarvis_inbox) == 1
        assert jarvis_inbox[0][1] == "For JARVIS only"

    def test_memo_broadcast_reaches_all(self, shared_store):
        """Broadcast memos should reach all agents."""
        from palaia.memo import MemoManager

        mm = MemoManager(shared_store)
        mm.broadcast(message="Attention everyone", from_agent="SYSTEM")

        assert len(mm.inbox(agent="HAL")) == 1
        assert len(mm.inbox(agent="JARVIS")) == 1


class TestDefaultAgentWorkflow:
    """Test the full init→write→query workflow with default agent."""

    def test_init_write_query_without_agent(self, fresh_dir, monkeypatch, capsys):
        """palaia init without --agent, then write, then query → all work."""
        # Init
        rc = _run_palaia(["init", "--path", str(fresh_dir)], monkeypatch)
        assert rc == 0
        config = json.loads((fresh_dir / ".palaia" / "config.json").read_text())
        assert config["agent"] == "default"
        capsys.readouterr()  # clear

        # Write
        rc = _run_palaia(["write", "Test memory entry", "--title", "Test"], monkeypatch)
        assert rc == 0
        captured = capsys.readouterr()
        assert "Written:" in captured.out

        # Query
        rc = _run_palaia(["query", "Test memory", "--json"], monkeypatch)
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data["results"]) > 0

    def test_reinit_with_agent_changes_from_default(self, fresh_dir, monkeypatch, capsys):
        """palaia init without --agent, then re-init with --agent NAME → changes to NAME."""
        # First init → default
        rc = _run_palaia(["init", "--path", str(fresh_dir)], monkeypatch)
        assert rc == 0
        config = json.loads((fresh_dir / ".palaia" / "config.json").read_text())
        assert config["agent"] == "default"
        capsys.readouterr()

        # Re-init with --agent
        rc = _run_palaia(["init", "--path", str(fresh_dir), "--agent", "MyAgent"], monkeypatch)
        assert rc == 0
        config = json.loads((fresh_dir / ".palaia" / "config.json").read_text())
        assert config["agent"] == "MyAgent"
