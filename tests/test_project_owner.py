"""Tests for project ownership feature (Issue #30)."""

from __future__ import annotations

import json

import pytest

from palaia.project import Project, ProjectManager
from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    """Create a minimal palaia root directory."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for tier in ("hot", "warm", "cold"):
        (root / tier).mkdir()
    return root


@pytest.fixture
def pm(palaia_root):
    return ProjectManager(palaia_root)


@pytest.fixture
def store(palaia_root):
    return Store(palaia_root)


# --- Model Tests ---


def test_create_project_with_owner(pm):
    """1. Create project with owner."""
    project = pm.create("clawsy", description="Mac App", owner="cyberclaw")
    assert project.owner == "cyberclaw"
    assert project.name == "clawsy"

    # Verify persisted
    reloaded = pm.get("clawsy")
    assert reloaded.owner == "cyberclaw"


def test_create_project_without_owner(pm):
    """2. Create project without owner (None)."""
    project = pm.create("myproject", description="Test")
    assert project.owner is None

    reloaded = pm.get("myproject")
    assert reloaded.owner is None


def test_set_owner(pm):
    """3. set-owner on existing project."""
    pm.create("clawsy")
    project = pm.set_owner("clawsy", "forrest")
    assert project.owner == "forrest"

    reloaded = pm.get("clawsy")
    assert reloaded.owner == "forrest"


def test_clear_owner(pm):
    """4. set-owner --clear."""
    pm.create("clawsy", owner="cyberclaw")
    project = pm.clear_owner("clawsy")
    assert project.owner is None

    reloaded = pm.get("clawsy")
    assert reloaded.owner is None


def test_list_shows_owner(pm):
    """5. project list shows Owner."""
    pm.create("clawsy", owner="cyberclaw")
    pm.create("culturebook", owner="forrest")
    projects = pm.list()
    owners = {p.name: p.owner for p in projects}
    assert owners["clawsy"] == "cyberclaw"
    assert owners["culturebook"] == "forrest"


def test_list_filter_by_owner(pm):
    """6. project list --owner filters correctly."""
    pm.create("clawsy", owner="cyberclaw")
    pm.create("culturebook", owner="forrest")
    pm.create("orphan")

    all_projects = pm.list()
    filtered = [p for p in all_projects if p.owner == "forrest"]
    assert len(filtered) == 1
    assert filtered[0].name == "culturebook"


def test_show_displays_owner(pm, store):
    """7. project show shows Owner."""
    pm.create("clawsy", owner="cyberclaw")
    project = pm.get("clawsy")
    assert project.owner == "cyberclaw"


def test_show_displays_contributors(pm, store):
    """8. project show shows Contributors (from Entries)."""
    pm.create("clawsy", owner="cyberclaw")

    # Write entries with different agents
    store.write(body="Entry 1", agent="cyberclaw", project="clawsy")
    store.write(body="Entry 2", agent="elliot", project="clawsy")
    store.write(body="Entry 3", agent="cyberclaw", project="clawsy")
    store.write(body="Entry 4", agent="forrest", project="clawsy")

    contributors = pm.get_contributors("clawsy", store)
    assert contributors == ["cyberclaw", "elliot", "forrest"]


def test_json_output_list_with_owner(pm):
    """9. JSON output on list with Owner."""
    pm.create("clawsy", owner="cyberclaw")
    pm.create("culturebook", owner="forrest")

    projects = pm.list()
    json_data = {"projects": [p.to_dict() for p in projects]}

    assert len(json_data["projects"]) == 2
    proj_map = {p["name"]: p for p in json_data["projects"]}
    assert proj_map["clawsy"]["owner"] == "cyberclaw"
    assert proj_map["culturebook"]["owner"] == "forrest"


def test_json_output_show_with_owner_and_contributors(pm, store):
    """10. JSON output on show with Owner + Contributors."""
    pm.create("clawsy", owner="cyberclaw")
    store.write(body="Entry 1", agent="cyberclaw", project="clawsy")
    store.write(body="Entry 2", agent="elliot", project="clawsy")

    project = pm.get("clawsy")
    contributors = pm.get_contributors("clawsy", store)
    entries = pm.get_project_entries("clawsy", store)

    json_data = {
        "project": project.to_dict(),
        "contributors": contributors,
        "entries": [{"id": meta.get("id", "?"), "tier": tier} for meta, body, tier in entries],
    }

    assert json_data["project"]["owner"] == "cyberclaw"
    assert json_data["contributors"] == ["cyberclaw", "elliot"]
    assert len(json_data["entries"]) == 2


def test_set_owner_nonexistent_project(pm):
    """11. set-owner on non-existent project → error."""
    with pytest.raises(ValueError, match="not found"):
        pm.set_owner("nonexistent", "someone")


def test_backward_compat_no_owner_field(palaia_root):
    """12. Backward compat: existing projects.json without owner field."""
    projects_file = palaia_root / "projects.json"
    legacy_data = {
        "legacy": {
            "name": "legacy",
            "description": "Old project",
            "default_scope": "team",
            "created_at": "2025-01-01T00:00:00+00:00",
            "members": [],
        }
    }
    projects_file.write_text(json.dumps(legacy_data))

    pm = ProjectManager(palaia_root)
    project = pm.get("legacy")
    assert project is not None
    assert project.owner is None
    assert project.name == "legacy"


def test_to_dict_includes_owner():
    """Project.to_dict() includes owner field."""
    p = Project(name="test", owner="alice")
    d = p.to_dict()
    assert "owner" in d
    assert d["owner"] == "alice"

    p2 = Project(name="test2")
    d2 = p2.to_dict()
    assert "owner" in d2
    assert d2["owner"] is None


def test_set_owner_overwrites(pm):
    """set-owner overwrites existing owner."""
    pm.create("clawsy", owner="cyberclaw")
    pm.set_owner("clawsy", "forrest")
    project = pm.get("clawsy")
    assert project.owner == "forrest"

    pm.set_owner("clawsy", "elliot")
    project = pm.get("clawsy")
    assert project.owner == "elliot"


def test_clear_owner_nonexistent_project(pm):
    """clear_owner on non-existent project → error."""
    with pytest.raises(ValueError, match="not found"):
        pm.clear_owner("nonexistent")


def test_get_contributors_empty(pm, store):
    """get_contributors with no entries returns empty list."""
    pm.create("empty_project")
    contributors = pm.get_contributors("empty_project", store)
    assert contributors == []
