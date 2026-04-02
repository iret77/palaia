"""Tests for scope enforcement."""

import pytest

from palaia.scope import can_access, is_exportable, normalize_scope, validate_scope


def test_validate_scope():
    assert validate_scope("private") is True
    assert validate_scope("team") is True
    assert validate_scope("public") is True
    assert validate_scope("shared:myproject") is True
    assert validate_scope("shared:") is False
    assert validate_scope("invalid") is False
    assert validate_scope("") is False


def test_normalize_scope():
    assert normalize_scope(None) == "team"
    assert normalize_scope("TEAM") == "team"
    assert normalize_scope("  public  ") == "public"
    with pytest.raises(ValueError):
        normalize_scope("invalid")


def test_can_access_team():
    assert can_access("team", "agent1", "agent2") is True


def test_can_access_public():
    assert can_access("public", "agent1", "agent2") is True


def test_can_access_private():
    assert can_access("private", "agent1", "agent1") is True
    assert can_access("private", "agent1", "agent2") is False
    assert can_access("private", None, "agent1") is False


def test_can_access_shared():
    assert can_access("shared:proj1", "agent1", "agent2", ["proj1"]) is True
    assert can_access("shared:proj1", "agent1", "agent2", ["proj2"]) is False
    assert can_access("shared:proj1", "agent1", "agent2", None) is False


def test_can_access_private_with_agent_names():
    """Agent names set allows access to private entries from aliased agents."""
    # HAL can access "default"'s private entries via resolved names set
    assert can_access("private", "HAL", "default", agent_names={"HAL", "default"}) is True
    # But not some random agent's entries
    assert can_access("private", "HAL", "JARVIS", agent_names={"HAL", "default"}) is False
    # Without agent_names, falls back to exact match
    assert can_access("private", "HAL", "default") is False
    assert can_access("private", "HAL", "default", agent_names=set()) is False
    assert can_access("private", "HAL", "default", agent_names=None) is False


def test_is_exportable():
    assert is_exportable("public") is True
    assert is_exportable("team") is False
    assert is_exportable("private") is False
    assert is_exportable("shared:x") is False


# ---------------------------------------------------------------------------
# scopeVisibility tests (Issue #145: agent isolation)
# ---------------------------------------------------------------------------

class TestScopeVisibility:
    def test_visibility_none_is_default(self):
        """No scopeVisibility means default behavior."""
        assert can_access("team", "a", "b", scope_visibility=None) is True
        assert can_access("public", "a", "b", scope_visibility=None) is True

    def test_private_only(self):
        """scopeVisibility=['private'] hides team and public."""
        assert can_access("private", "a", "a", scope_visibility=["private"]) is True
        assert can_access("team", "a", "b", scope_visibility=["private"]) is False
        assert can_access("public", "a", "b", scope_visibility=["private"]) is False

    def test_private_and_team(self):
        """scopeVisibility=['private', 'team'] hides only public."""
        assert can_access("private", "a", "a", scope_visibility=["private", "team"]) is True
        assert can_access("team", "a", "b", scope_visibility=["private", "team"]) is True
        assert can_access("public", "a", "b", scope_visibility=["private", "team"]) is False

    def test_shared_exact(self):
        """Exact shared:X match in scopeVisibility."""
        assert can_access("shared:proj1", "a", "b", ["proj1"], scope_visibility=["private", "shared:proj1"]) is True
        assert can_access("shared:proj2", "a", "b", ["proj2"], scope_visibility=["private", "shared:proj1"]) is False

    def test_shared_wildcard(self):
        """'shared' in scopeVisibility matches any shared:X."""
        assert can_access("shared:proj1", "a", "b", ["proj1"], scope_visibility=["private", "shared"]) is True
        assert can_access("shared:proj2", "a", "b", ["proj2"], scope_visibility=["private", "shared"]) is True

    def test_private_scope_still_enforced(self):
        """scopeVisibility allows private, but agent ownership still checked."""
        assert can_access("private", "a", "a", scope_visibility=["private"]) is True
        assert can_access("private", "a", "b", scope_visibility=["private"]) is False

    def test_empty_visibility_blocks_all(self):
        """Empty scopeVisibility blocks everything."""
        assert can_access("team", "a", "b", scope_visibility=[]) is False
        assert can_access("private", "a", "a", scope_visibility=[]) is False
        assert can_access("public", "a", "b", scope_visibility=[]) is False
