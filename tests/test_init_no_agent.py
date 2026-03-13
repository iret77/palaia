"""Tests for palaia init without --agent (Issue #46)."""

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
    # Prevent fallback to real home .palaia
    monkeypatch.delenv("HOME", raising=False)
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
        """Re-init without --agent when NO agent configured must fail."""
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

        rc = _run_palaia(["init"], monkeypatch)
        assert rc == 1
        captured = capsys.readouterr()
        assert "agent name required" in captured.err.lower()
