"""Tests for Agent Alias System (previous_agents in config for default→named migration)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from palaia.config import get_agent_aliases, load_config, save_config


@pytest.fixture
def palaia_root(tmp_path):
    """Create a minimal .palaia directory for testing."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for tier in ("hot", "warm", "cold", "wal", "index"):
        (root / tier).mkdir()
    config = {
        "version": 1,
        "agent": "HAL",
        "store_version": "0.1.0",
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
    (root / "config.json").write_text(json.dumps(config))
    return root


def _write_entry(palaia_root: Path, tier: str, entry_id: str, agent: str, body: str = "test"):
    """Helper to write a minimal entry file."""
    content = f"""---
id: {entry_id}
agent: {agent}
scope: private
title: Test entry {entry_id[:8]}
created: 2026-03-13T12:00:00+00:00
accessed: 2026-03-13T12:00:00+00:00
access_count: 1
content_hash: hash_{entry_id[:8]}
---

{body}
"""
    (palaia_root / tier / f"{entry_id}.md").write_text(content)


# --- Config: get_agent_aliases ---


class TestGetAgentAliases:
    def test_no_aliases(self, palaia_root):
        assert get_agent_aliases(palaia_root) == []

    def test_with_previous_agents(self, palaia_root):
        config = load_config(palaia_root)
        config["previous_agents"] = ["default", "old-name"]
        save_config(palaia_root, config)
        assert get_agent_aliases(palaia_root) == ["default", "old-name"]

    def test_invalid_previous_agents_type(self, palaia_root):
        config = load_config(palaia_root)
        config["previous_agents"] = "not-a-list"
        save_config(palaia_root, config)
        assert get_agent_aliases(palaia_root) == []

    def test_no_root(self):
        assert get_agent_aliases(Path("/nonexistent/.palaia")) == []


# --- Store: Private Access with Aliases ---


class TestStoreAccessWithAliases:
    """Test that store respects previous_agents for scope checks."""

    @pytest.fixture
    def aliased_store(self, palaia_root):
        """Store where HAL was previously 'default'."""
        config = load_config(palaia_root)
        config["previous_agents"] = ["default"]
        save_config(palaia_root, config)
        return palaia_root

    def test_current_agent_reads_old_private_entries(self, aliased_store):
        """HAL can read private entries written as 'default'."""
        from palaia.store import Store

        store = Store(aliased_store)
        eid = store.write(body="Old secret", scope="private", agent="default", title="Old")

        entry = store.read(eid, agent="HAL")
        assert entry is not None

    def test_other_agent_cannot_read_aliased_private(self, aliased_store):
        """JARVIS cannot read HAL's old 'default' private entries."""
        from palaia.store import Store

        store = Store(aliased_store)
        eid = store.write(body="Old secret", scope="private", agent="default", title="Old")

        entry = store.read(eid, agent="JARVIS")
        assert entry is None

    def test_current_agent_reads_own_private(self, aliased_store):
        """HAL can still read its own private entries."""
        from palaia.store import Store

        store = Store(aliased_store)
        eid = store.write(body="HAL secret", scope="private", agent="HAL", title="New")

        entry = store.read(eid, agent="HAL")
        assert entry is not None

    def test_team_entries_always_accessible(self, aliased_store):
        """Team entries are accessible regardless of aliases."""
        from palaia.store import Store

        store = Store(aliased_store)
        eid = store.write(body="Team stuff", scope="team", agent="default", title="Team")

        assert store.read(eid, agent="HAL") is not None
        assert store.read(eid, agent="JARVIS") is not None

    def test_list_includes_aliased_private(self, aliased_store):
        """list_entries includes private entries from aliased agent names."""
        from palaia.store import Store

        store = Store(aliased_store)
        store.write(body="Old private", scope="private", agent="default", title="Old Private")
        store.write(body="New private", scope="private", agent="HAL", title="New Private")

        entries = store.list_entries("hot", agent="HAL")
        titles = [meta.get("title") for meta, _ in entries]
        assert "Old Private" in titles
        assert "New Private" in titles

    def test_list_excludes_for_non_aliased_agent(self, aliased_store):
        """list_entries excludes private entries from aliased names for other agents."""
        from palaia.store import Store

        store = Store(aliased_store)
        store.write(body="Old private", scope="private", agent="default", title="Old Private")

        entries = store.list_entries("hot", agent="JARVIS")
        titles = [meta.get("title") for meta, _ in entries]
        assert "Old Private" not in titles

    def test_no_aliases_no_access(self, palaia_root):
        """Without previous_agents, no alias access is granted."""
        from palaia.store import Store

        store = Store(palaia_root)
        eid = store.write(body="Secret", scope="private", agent="default", title="Secret")

        # HAL is config agent but no previous_agents set
        entry = store.read(eid, agent="HAL")
        assert entry is None

    def test_edit_aliased_private_entry(self, aliased_store):
        """HAL can edit private entries from aliased agent 'default'."""
        from palaia.store import Store

        store = Store(aliased_store)
        eid = store.write(body="Old content", scope="private", agent="default", title="Old")

        # HAL should be able to edit it
        store.edit(entry_id=eid, body="Updated content", agent="HAL")
        entry = store.read(eid, agent="HAL")
        assert entry is not None
        _, body = entry
        assert "Updated content" in body

    def test_other_agent_cannot_edit_aliased_private(self, aliased_store):
        """JARVIS cannot edit HAL's old 'default' private entries."""
        from palaia.store import Store

        store = Store(aliased_store)
        eid = store.write(body="Old content", scope="private", agent="default", title="Old")

        with pytest.raises(PermissionError):
            store.edit(entry_id=eid, body="Hacked", agent="JARVIS")


# --- Multiple Previous Agents ---


class TestMultiplePreviousAgents:
    def test_multiple_aliases(self, palaia_root):
        """Agent with multiple previous names can access all old private entries."""
        from palaia.store import Store

        config = load_config(palaia_root)
        config["previous_agents"] = ["default", "old-name"]
        save_config(palaia_root, config)

        store = Store(palaia_root)
        eid1 = store.write(body="From default", scope="private", agent="default", title="Default Entry")
        eid2 = store.write(body="From old-name", scope="private", agent="old-name", title="Old Name Entry")

        assert store.read(eid1, agent="HAL") is not None
        assert store.read(eid2, agent="HAL") is not None
