"""Tests for --agent flag on query, list, get, and export commands."""

import pytest

from palaia.config import DEFAULT_CONFIG, save_config
from palaia.search import SearchEngine
from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    save_config(root, DEFAULT_CONFIG)
    return root


@pytest.fixture
def store_with_entries(palaia_root):
    """Store with entries from different agents and scopes."""
    store = Store(palaia_root)
    # Private entry by agent "alice"
    store.write("Alice private note", scope="private", agent="alice", title="Alice Private")
    # Private entry by agent "bob"
    store.write("Bob private note", scope="private", agent="bob", title="Bob Private")
    # Team-scoped entry by alice (visible to all)
    store.write("Alice team note", scope="team", agent="alice", title="Alice Team")
    # Public entry
    store.write("Public note", scope="public", agent="alice", title="Public Note")
    return store


class TestListWithAgent:
    def test_list_no_agent_sees_team_and_public(self, store_with_entries):
        """Without --agent, list should see team and public entries but not private."""
        entries = store_with_entries.list_entries("hot", agent=None)
        titles = [meta.get("title") for meta, _ in entries]
        assert "Alice Team" in titles
        assert "Public Note" in titles
        # Private entries should NOT be visible without agent
        assert "Alice Private" not in titles
        assert "Bob Private" not in titles

    def test_list_with_agent_sees_own_private(self, store_with_entries):
        """With --agent=alice, should see alice's private entries."""
        entries = store_with_entries.list_entries("hot", agent="alice")
        titles = [meta.get("title") for meta, _ in entries]
        assert "Alice Private" in titles
        assert "Alice Team" in titles
        assert "Public Note" in titles
        # Should NOT see bob's private entries
        assert "Bob Private" not in titles

    def test_list_with_other_agent(self, store_with_entries):
        """With --agent=bob, should see bob's private but not alice's."""
        entries = store_with_entries.list_entries("hot", agent="bob")
        titles = [meta.get("title") for meta, _ in entries]
        assert "Bob Private" in titles
        assert "Alice Team" in titles
        assert "Public Note" in titles
        assert "Alice Private" not in titles


class TestGetWithAgent:
    def test_get_own_private(self, store_with_entries):
        """Agent can read their own private entry."""
        # Find alice's private entry
        entries = store_with_entries.list_entries("hot", agent="alice")
        alice_private_id = None
        for meta, _ in entries:
            if meta.get("title") == "Alice Private":
                alice_private_id = meta["id"]
                break
        assert alice_private_id is not None
        result = store_with_entries.read(alice_private_id, agent="alice")
        assert result is not None
        meta, body = result
        assert "Alice private note" in body

    def test_get_other_private_blocked(self, store_with_entries):
        """Agent cannot read another agent's private entry."""
        # Find bob's private entry via bob
        entries = store_with_entries.list_entries("hot", agent="bob")
        bob_private_id = None
        for meta, _ in entries:
            if meta.get("title") == "Bob Private":
                bob_private_id = meta["id"]
                break
        assert bob_private_id is not None
        # Alice tries to read bob's private → should return None
        result = store_with_entries.read(bob_private_id, agent="alice")
        assert result is None

    def test_get_no_agent_private_blocked(self, store_with_entries):
        """Without agent, private entries should not be readable."""
        entries = store_with_entries.list_entries("hot", agent="alice")
        alice_private_id = None
        for meta, _ in entries:
            if meta.get("title") == "Alice Private":
                alice_private_id = meta["id"]
                break
        assert alice_private_id is not None
        result = store_with_entries.read(alice_private_id, agent=None)
        assert result is None


class TestQueryWithAgent:
    def test_query_with_agent_filters(self, store_with_entries):
        """SearchEngine.search with agent should respect scope filtering."""
        engine = SearchEngine(store_with_entries)
        results = engine.search("note", top_k=10, agent="alice")
        ids_in_results = [r["id"] for r in results]
        # Alice should see her own entries + team/public
        # Get all entries alice can see
        alice_entries = store_with_entries.list_entries("hot", agent="alice")
        alice_ids = {meta["id"] for meta, _ in alice_entries}
        for rid in ids_in_results:
            assert rid in alice_ids, f"Result {rid} should be accessible by alice"

    def test_query_without_agent(self, store_with_entries):
        """SearchEngine.search without agent should not return private entries."""
        engine = SearchEngine(store_with_entries)
        results = engine.search("note", top_k=10, agent=None)
        titles = [r["title"] for r in results]
        assert "Alice Private" not in titles
        assert "Bob Private" not in titles


class TestAllEntriesWithAgent:
    def test_all_entries_with_agent(self, store_with_entries):
        """all_entries with agent should filter by scope."""
        entries = store_with_entries.all_entries(agent="alice")
        titles = [meta.get("title") for meta, _, _ in entries]
        assert "Alice Private" in titles
        assert "Bob Private" not in titles

    def test_all_entries_no_agent(self, store_with_entries):
        """all_entries without agent should not include private entries."""
        entries = store_with_entries.all_entries(agent=None)
        titles = [meta.get("title") for meta, _, _ in entries]
        assert "Alice Private" not in titles
        assert "Bob Private" not in titles
        assert "Alice Team" in titles
        assert "Public Note" in titles
