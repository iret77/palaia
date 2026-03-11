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


def test_is_exportable():
    assert is_exportable("public") is True
    assert is_exportable("team") is False
    assert is_exportable("private") is False
    assert is_exportable("shared:x") is False
