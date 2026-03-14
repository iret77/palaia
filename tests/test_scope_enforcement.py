"""Tests for scope enforcement audit (#39).

Verifies that all read/write operations respect scope boundaries.
"""

import pytest

from palaia.config import DEFAULT_CONFIG, save_config
from palaia.scope import can_access
from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    config = dict(DEFAULT_CONFIG)
    config["agent"] = "agent1"
    save_config(root, config)
    return root


@pytest.fixture
def store(palaia_root):
    return Store(palaia_root)


# --- store.read() scope enforcement ---


def test_read_team_scope_accessible(store):
    """Team-scoped entries are accessible to any agent."""
    entry_id = store.write("Team entry", scope="team", agent="agent1")
    result = store.read(entry_id, agent="agent2")
    assert result is not None


def test_read_private_scope_own_agent(store):
    """Private entries readable only by owning agent."""
    entry_id = store.write("Private entry", scope="private", agent="agent1")
    result = store.read(entry_id, agent="agent1")
    assert result is not None


def test_read_private_scope_other_agent(store):
    """Private entries NOT readable by other agents."""
    entry_id = store.write("Private entry", scope="private", agent="agent1")
    result = store.read(entry_id, agent="agent2")
    assert result is None


def test_read_private_scope_no_agent(store):
    """Private entries NOT readable when no agent specified."""
    entry_id = store.write("Private entry", scope="private", agent="agent1")
    result = store.read(entry_id, agent=None)
    assert result is None


def test_read_public_scope_accessible(store):
    """Public entries accessible to any agent."""
    entry_id = store.write("Public entry", scope="public", agent="agent1")
    result = store.read(entry_id, agent="anyone")
    assert result is not None


# --- store.list_entries() scope enforcement ---


def test_list_filters_private_entries(store):
    """list_entries should not include other agents' private entries."""
    store.write("Agent1 private", scope="private", agent="agent1")
    store.write("Agent2 private", scope="private", agent="agent2")
    store.write("Team entry", scope="team", agent="agent1")

    entries_a1 = store.list_entries("hot", agent="agent1")
    entries_a2 = store.list_entries("hot", agent="agent2")

    # agent1 sees their private + team
    assert len(entries_a1) == 2
    # agent2 sees their private + team
    assert len(entries_a2) == 2


def test_list_no_agent_sees_team_and_public(store):
    """Without agent, list returns team + public entries only."""
    store.write("Private", scope="private", agent="agent1")
    store.write("Team", scope="team", agent="agent1")
    store.write("Public", scope="public", agent="agent1")

    entries = store.list_entries("hot", agent=None)
    assert len(entries) == 2  # team + public, NOT private


# --- store.edit() scope enforcement ---


def test_edit_own_private_entry(store):
    """Agent can edit their own private entries."""
    entry_id = store.write("My private data", scope="private", agent="agent1")
    meta = store.edit(entry_id, body="Updated private data", agent="agent1")
    assert meta is not None


def test_edit_other_private_entry_blocked(store):
    """Agent cannot edit another agent's private entries."""
    entry_id = store.write("Agent1 private", scope="private", agent="agent1")
    with pytest.raises(PermissionError, match="Scope violation"):
        store.edit(entry_id, body="Hacked!", agent="agent2")


def test_edit_team_entry_allowed(store):
    """Any agent can edit team-scoped entries."""
    entry_id = store.write("Team data", scope="team", agent="agent1")
    meta = store.edit(entry_id, body="Updated team data", agent="agent2")
    assert meta is not None


def test_edit_no_scope_escalation(store):
    """Edit cannot change scope to escalate access."""
    # Note: store.edit doesn't currently accept scope changes
    # This is by design — scope is immutable after creation
    entry_id = store.write("Private", scope="private", agent="agent1")
    entry = store.read(entry_id, agent="agent1")
    assert entry is not None
    meta, _ = entry
    assert meta["scope"] == "private"


# --- all_entries() scope enforcement ---


def test_all_entries_respects_scope(store):
    """all_entries should filter by scope like list_entries."""
    store.write("Private A1", scope="private", agent="agent1")
    store.write("Private A2", scope="private", agent="agent2")
    store.write("Team entry", scope="team", agent="agent1")

    all_a1 = store.all_entries(include_cold=True, agent="agent1")
    all_a2 = store.all_entries(include_cold=True, agent="agent2")

    assert len(all_a1) == 2  # own private + team
    assert len(all_a2) == 2  # own private + team


# --- GC scope isolation ---


def test_gc_does_not_cross_scope_boundaries(store, palaia_root):
    """GC operates on all entries (system-level) but doesn't leak data."""
    store.write("Private A1", scope="private", agent="agent1")
    store.write("Team entry", scope="team", agent="agent1")

    result = store.gc()
    # GC should complete without errors
    assert isinstance(result, dict)

    # After GC, private entries are still only visible to owner
    entries = store.list_entries("hot", agent="agent2")
    private_entries = [(m, b) for m, b in entries if m.get("scope") == "private"]
    assert len(private_entries) == 0


# --- Export scope enforcement ---


def test_export_only_public(store, palaia_root):
    """Export only exports public entries, not team or private."""
    from palaia.scope import is_exportable

    store.write("Private entry", scope="private", agent="agent1")
    store.write("Team entry", scope="team", agent="agent1")
    store.write("Public entry", scope="public", agent="agent1")

    all_entries = store.all_entries(include_cold=True)
    exportable = [(m, b, t) for m, b, t in all_entries if is_exportable(m.get("scope", "team"))]
    assert len(exportable) == 1
    assert exportable[0][0]["scope"] == "public"


# --- can_access() unit tests ---


def test_can_access_team():
    assert can_access("team", "anyone", "owner") is True


def test_can_access_public():
    assert can_access("public", "anyone", "owner") is True


def test_can_access_private_owner():
    assert can_access("private", "owner", "owner") is True


def test_can_access_private_other():
    assert can_access("private", "other", "owner") is False


def test_can_access_private_no_agent():
    assert can_access("private", None, "owner") is False


def test_can_access_shared_project():
    assert can_access("shared:myproj", "anyone", "owner", projects=["myproj"]) is True


def test_can_access_shared_wrong_project():
    assert can_access("shared:myproj", "anyone", "owner", projects=["other"]) is False


def test_can_access_shared_no_projects():
    assert can_access("shared:myproj", "anyone", "owner", projects=None) is False


# --- Alias-aware scope enforcement ---


def test_private_access_via_alias(palaia_root):
    """Private entries accessible via aliased agent names."""
    from palaia.config import set_alias

    set_alias(palaia_root, "default", "agent1")
    store = Store(palaia_root)
    entry_id = store.write("Alias test", scope="private", agent="default")

    # Access via alias target
    result = store.read(entry_id, agent="agent1")
    assert result is not None

    # Access via alias source
    result = store.read(entry_id, agent="default")
    assert result is not None

    # Other agent still blocked
    result = store.read(entry_id, agent="agent2")
    assert result is None
