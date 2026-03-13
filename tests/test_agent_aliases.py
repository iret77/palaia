"""Tests for Agent Alias System (aliases in config for default→named migration)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from palaia.config import (
    get_aliases,
    remove_alias,
    resolve_agent_with_aliases,
    set_alias,
)


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
    """Helper to write a minimal private entry file."""
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


def _write_team_entry(palaia_root: Path, tier: str, entry_id: str, agent: str, body: str = "test"):
    """Helper to write a minimal team-scoped entry file."""
    content = f"""---
id: {entry_id}
agent: {agent}
scope: team
title: Test entry {entry_id[:8]}
created: 2026-03-13T12:00:00+00:00
accessed: 2026-03-13T12:00:00+00:00
access_count: 1
content_hash: hash_{entry_id[:8]}
---

{body}
"""
    (palaia_root / tier / f"{entry_id}.md").write_text(content)


# --- Config Functions ---


class TestSetAlias:
    def test_set_alias_basic(self, palaia_root):
        set_alias(palaia_root, "default", "HAL")
        aliases = get_aliases(palaia_root)
        assert aliases == {"default": "HAL"}

    def test_set_alias_multiple(self, palaia_root):
        set_alias(palaia_root, "default", "HAL")
        set_alias(palaia_root, "old-agent", "HAL")
        aliases = get_aliases(palaia_root)
        assert aliases == {"default": "HAL", "old-agent": "HAL"}

    def test_set_alias_overwrite(self, palaia_root):
        set_alias(palaia_root, "default", "HAL")
        set_alias(palaia_root, "default", "DAVE")
        aliases = get_aliases(palaia_root)
        assert aliases == {"default": "DAVE"}

    def test_set_alias_empty_names_raises(self, palaia_root):
        with pytest.raises(ValueError):
            set_alias(palaia_root, "", "HAL")
        with pytest.raises(ValueError):
            set_alias(palaia_root, "default", "")

    def test_set_alias_same_name_raises(self, palaia_root):
        with pytest.raises(ValueError):
            set_alias(palaia_root, "HAL", "HAL")


class TestGetAliases:
    def test_no_aliases(self, palaia_root):
        assert get_aliases(palaia_root) == {}

    def test_with_aliases(self, palaia_root):
        set_alias(palaia_root, "default", "HAL")
        assert get_aliases(palaia_root) == {"default": "HAL"}


class TestRemoveAlias:
    def test_remove_existing(self, palaia_root):
        set_alias(palaia_root, "default", "HAL")
        assert remove_alias(palaia_root, "default") is True
        assert get_aliases(palaia_root) == {}

    def test_remove_nonexistent(self, palaia_root):
        assert remove_alias(palaia_root, "default") is False

    def test_remove_one_of_multiple(self, palaia_root):
        set_alias(palaia_root, "default", "HAL")
        set_alias(palaia_root, "old", "HAL")
        remove_alias(palaia_root, "default")
        assert get_aliases(palaia_root) == {"old": "HAL"}


# --- Resolve Agent With Aliases ---


class TestResolveAgentWithAliases:
    def test_no_aliases(self):
        names = resolve_agent_with_aliases("HAL", {})
        assert names == {"HAL"}

    def test_forward_alias(self):
        aliases = {"default": "HAL"}
        names = resolve_agent_with_aliases("default", aliases)
        assert names == {"default", "HAL"}

    def test_reverse_alias(self):
        aliases = {"default": "HAL"}
        names = resolve_agent_with_aliases("HAL", aliases)
        assert names == {"default", "HAL"}

    def test_unrelated_agent(self):
        aliases = {"default": "HAL"}
        names = resolve_agent_with_aliases("DAVE", aliases)
        assert names == {"DAVE"}

    def test_multiple_sources(self):
        aliases = {"default": "HAL", "old-agent": "HAL"}
        names = resolve_agent_with_aliases("HAL", aliases)
        assert names == {"default", "old-agent", "HAL"}

    def test_chain_does_not_propagate(self):
        """Aliases are direct mappings, not transitive chains."""
        aliases = {"a": "b", "b": "c"}
        names = resolve_agent_with_aliases("a", aliases)
        assert names == {"a", "b"}


# --- Store Access with Aliases ---


class TestStoreAccessWithAliases:
    """Test that store respects aliases for scope checks."""

    @pytest.fixture
    def aliased_store(self, palaia_root):
        """Store where 'default' is aliased to 'HAL'."""
        set_alias(palaia_root, "default", "HAL")
        return palaia_root

    def test_current_agent_reads_aliased_private_entries(self, aliased_store):
        """HAL can read private entries written as 'default' via alias."""
        from palaia.store import Store

        store = Store(aliased_store)
        eid = store.write(body="Old secret", scope="private", agent="default", title="Old")

        entry = store.read(eid, agent="HAL")
        assert entry is not None

    def test_aliased_name_reads_target_private_entries(self, aliased_store):
        """Querying as 'default' also sees HAL's private entries (bidirectional)."""
        from palaia.store import Store

        store = Store(aliased_store)
        eid = store.write(body="HAL secret", scope="private", agent="HAL", title="New")

        entry = store.read(eid, agent="default")
        assert entry is not None

    def test_other_agent_cannot_read_aliased_private(self, aliased_store):
        """JARVIS cannot read default/HAL private entries."""
        from palaia.store import Store

        store = Store(aliased_store)
        eid = store.write(body="Old secret", scope="private", agent="default", title="Old")

        entry = store.read(eid, agent="JARVIS")
        assert entry is None

    def test_team_entries_always_accessible(self, palaia_root):
        """Team entries are accessible regardless of aliases."""
        from palaia.store import Store

        store = Store(palaia_root)
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

    def test_no_aliases_no_cross_access(self, palaia_root):
        """Without aliases, no cross-agent access for private entries."""
        from palaia.store import Store

        store = Store(palaia_root)
        eid = store.write(body="Secret", scope="private", agent="default", title="Secret")

        entry = store.read(eid, agent="HAL")
        assert entry is None

    def test_edit_aliased_private_entry(self, aliased_store):
        """HAL can edit private entries from aliased agent 'default'."""
        from palaia.store import Store

        store = Store(aliased_store)
        eid = store.write(body="Old content", scope="private", agent="default", title="Old")

        store.edit(entry_id=eid, body="Updated content", agent="HAL")
        entry = store.read(eid, agent="HAL")
        assert entry is not None
        _, body = entry
        assert "Updated content" in body

    def test_other_agent_cannot_edit_aliased_private(self, aliased_store):
        """JARVIS cannot edit default/HAL private entries."""
        from palaia.store import Store

        store = Store(aliased_store)
        eid = store.write(body="Old content", scope="private", agent="default", title="Old")

        with pytest.raises(PermissionError):
            store.edit(entry_id=eid, body="Hacked", agent="JARVIS")


# --- CLI Integration Tests ---


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    """Set up environment for CLI testing."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for tier in ("hot", "warm", "cold", "wal", "index"):
        (root / tier).mkdir()
    config = {
        "version": 1,
        "agent": "HAL",
        "store_version": "0.1.0",
        "embedding_chain": ["bm25"],
    }
    (root / "config.json").write_text(json.dumps(config))
    monkeypatch.setenv("PALAIA_HOME", str(root))
    return root


def _run_cli(*args, env_override=None):
    """Run palaia CLI and return (returncode, stdout, stderr)."""
    import os

    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    result = subprocess.run(
        [sys.executable, "-m", "palaia", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


class TestCLIAliasCommands:
    def test_set_alias_cli(self, cli_env):
        rc, out, _ = _run_cli("config", "set-alias", "default", "HAL")
        assert rc == 0
        assert "default -> HAL" in out

    def test_get_aliases_empty(self, cli_env):
        rc, out, _ = _run_cli("config", "get-aliases")
        assert rc == 0
        assert "No aliases" in out

    def test_get_aliases_with_data(self, cli_env):
        _run_cli("config", "set-alias", "default", "HAL")
        rc, out, _ = _run_cli("config", "get-aliases")
        assert rc == 0
        assert "default -> HAL" in out

    def test_remove_alias_cli(self, cli_env):
        _run_cli("config", "set-alias", "default", "HAL")
        rc, out, _ = _run_cli("config", "remove-alias", "default")
        assert rc == 0
        assert "removed" in out.lower()

    def test_remove_nonexistent_alias(self, cli_env):
        rc, out, _ = _run_cli("config", "remove-alias", "nonexistent")
        assert rc == 1

    def test_set_alias_json(self, cli_env):
        rc, out, _ = _run_cli("config", "set-alias", "default", "HAL", "--json")
        assert rc == 0
        data = json.loads(out)
        assert data["alias"] == "default"
        assert data["target"] == "HAL"

    def test_get_aliases_json(self, cli_env):
        _run_cli("config", "set-alias", "default", "HAL")
        rc, out, _ = _run_cli("config", "get-aliases", "--json")
        assert rc == 0
        data = json.loads(out)
        assert data["aliases"] == {"default": "HAL"}


# --- Query with Alias Matching ---


class TestQueryWithAlias:
    def test_list_with_alias_matches_default_entries(self, cli_env):
        """When alias default->HAL is set, listing as HAL should also show default entries."""
        _write_entry(cli_env, "hot", "aaaa1111-0000-0000-0000-000000000001", "default", "entry by default agent")
        _write_entry(cli_env, "hot", "aaaa1111-0000-0000-0000-000000000002", "HAL", "entry by HAL")
        _write_entry(cli_env, "hot", "aaaa1111-0000-0000-0000-000000000003", "DAVE", "entry by DAVE")

        # Without alias: filtering by HAL should only show HAL's entry
        rc, out, _ = _run_cli("list", "--agent", "HAL", "--json")
        assert rc == 0
        data = json.loads(out)
        agents = [e["agent"] for e in data["entries"]]
        assert "HAL" in agents
        assert "default" not in agents

        # Set alias
        _run_cli("config", "set-alias", "default", "HAL")

        # With alias: filtering by HAL should show both HAL and default entries
        rc, out, _ = _run_cli("list", "--agent", "HAL", "--json")
        assert rc == 0
        data = json.loads(out)
        agents = [e["agent"] for e in data["entries"]]
        assert "HAL" in agents
        assert "default" in agents
        assert "DAVE" not in agents

    def test_list_without_agent_filter_shows_all_team(self, cli_env):
        """Without --agent filter, all team-scoped entries are visible."""
        _write_team_entry(cli_env, "hot", "bbbb1111-0000-0000-0000-000000000001", "default", "entry by default")
        _write_team_entry(cli_env, "hot", "bbbb1111-0000-0000-0000-000000000002", "HAL", "entry by HAL")

        rc, out, _ = _run_cli("list", "--json")
        assert rc == 0
        data = json.loads(out)
        agents = [e["agent"] for e in data["entries"]]
        assert "default" in agents
        assert "HAL" in agents


# --- Doctor Alias Nudge ---


class TestDoctorAliasNudge:
    def test_doctor_warns_default_entries_with_named_agents(self, cli_env):
        """Doctor should warn when default entries exist alongside named agents."""
        _write_entry(cli_env, "hot", "cccc1111-0000-0000-0000-000000000001", "default", "old entry")
        _write_entry(cli_env, "hot", "cccc1111-0000-0000-0000-000000000002", "HAL", "new entry")

        rc, out, _ = _run_cli("doctor", "--json")
        assert rc == 0
        data = json.loads(out)
        alias_check = next(c for c in data["checks"] if c["name"] == "default_agent_alias")
        assert alias_check["status"] == "warn"
        assert "default" in alias_check["message"]
        assert "set-alias" in alias_check.get("fix", "")

    def test_doctor_ok_when_alias_set(self, cli_env):
        """Doctor should be OK when alias exists for default entries."""
        _write_entry(cli_env, "hot", "dddd1111-0000-0000-0000-000000000001", "default", "old entry")
        _write_entry(cli_env, "hot", "dddd1111-0000-0000-0000-000000000002", "HAL", "new entry")
        _run_cli("config", "set-alias", "default", "HAL")

        rc, out, _ = _run_cli("doctor", "--json")
        assert rc == 0
        data = json.loads(out)
        alias_check = next(c for c in data["checks"] if c["name"] == "default_agent_alias")
        assert alias_check["status"] == "ok"

    def test_doctor_ok_no_default_entries(self, cli_env):
        """Doctor should be OK when there are no default entries."""
        _write_entry(cli_env, "hot", "eeee1111-0000-0000-0000-000000000001", "HAL", "entry")

        rc, out, _ = _run_cli("doctor", "--json")
        assert rc == 0
        data = json.loads(out)
        alias_check = next(c for c in data["checks"] if c["name"] == "default_agent_alias")
        assert alias_check["status"] == "ok"

    def test_doctor_ok_only_default_entries(self, cli_env):
        """Doctor should be OK when only default entries exist (no multi-agent)."""
        _write_entry(cli_env, "hot", "ffff1111-0000-0000-0000-000000000001", "default", "entry")

        rc, out, _ = _run_cli("doctor", "--json")
        assert rc == 0
        data = json.loads(out)
        alias_check = next(c for c in data["checks"] if c["name"] == "default_agent_alias")
        assert alias_check["status"] == "ok"


# --- Memo Inbox with Aliases ---


class TestMemoInboxWithAliases:
    def test_inbox_with_alias_matches_aliased_recipient(self, palaia_root):
        """Memo addressed to 'default' should appear in HAL's inbox when aliased."""
        from palaia.memo import MemoManager

        mm = MemoManager(palaia_root)

        mm.send(to="default", message="Hello from default", from_agent="DAVE")
        mm.send(to="HAL", message="Hello from HAL", from_agent="DAVE")

        # Without alias: HAL only sees memo addressed to HAL
        memos = mm.inbox(agent="HAL", include_read=False)
        assert len(memos) == 1
        assert memos[0][1] == "Hello from HAL"

        # With alias: HAL sees both
        aliases = {"default": "HAL"}
        memos = mm.inbox(agent="HAL", include_read=False, aliases=aliases)
        assert len(memos) == 2
        bodies = {m[1] for m in memos}
        assert "Hello from default" in bodies
        assert "Hello from HAL" in bodies

    def test_inbox_without_alias_unchanged(self, palaia_root):
        """Without aliases, inbox works as before."""
        from palaia.memo import MemoManager

        mm = MemoManager(palaia_root)
        mm.send(to="HAL", message="test", from_agent="DAVE")

        memos = mm.inbox(agent="HAL", include_read=False)
        assert len(memos) == 1
