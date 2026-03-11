"""Tests for project management (ADR-008)."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from palaia.config import DEFAULT_CONFIG, save_config
from palaia.entry import parse_entry
from palaia.project import ProjectManager
from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    """Create a fresh .palaia directory."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    save_config(root, DEFAULT_CONFIG)
    return root


@pytest.fixture
def pm(palaia_root):
    return ProjectManager(palaia_root)


@pytest.fixture
def store(palaia_root):
    return Store(palaia_root)


# --- Project CRUD ---


class TestProjectCRUD:
    def test_create_project(self, pm):
        p = pm.create("clawsy", description="Mac Companion", default_scope="team")
        assert p.name == "clawsy"
        assert p.description == "Mac Companion"
        assert p.default_scope == "team"
        assert p.created_at

    def test_create_duplicate(self, pm):
        pm.create("clawsy")
        with pytest.raises(ValueError, match="already exists"):
            pm.create("clawsy")

    def test_create_empty_name(self, pm):
        with pytest.raises(ValueError, match="empty"):
            pm.create("")

    def test_create_invalid_scope(self, pm):
        with pytest.raises(ValueError, match="Invalid scope"):
            pm.create("test", default_scope="bogus")

    def test_list_projects(self, pm):
        pm.create("alpha")
        pm.create("beta", description="Second")
        projects = pm.list()
        names = [p.name for p in projects]
        assert "alpha" in names
        assert "beta" in names

    def test_list_empty(self, pm):
        assert pm.list() == []

    def test_get_project(self, pm):
        pm.create("clawsy", description="Test")
        p = pm.get("clawsy")
        assert p is not None
        assert p.name == "clawsy"

    def test_get_nonexistent(self, pm):
        assert pm.get("nope") is None

    def test_delete_project(self, pm, store):
        pm.create("clawsy")
        # Write an entry with project tag
        store.write("test entry", project="clawsy")
        assert pm.delete("clawsy", store)
        assert pm.get("clawsy") is None

        # Entry should still exist but without project tag
        entries = store.list_entries("hot")
        assert len(entries) == 1
        meta, body = entries[0]
        assert "project" not in meta

    def test_delete_nonexistent(self, pm, store):
        assert not pm.delete("nope", store)

    def test_set_scope(self, pm):
        pm.create("clawsy", default_scope="team")
        p = pm.set_scope("clawsy", "private")
        assert p.default_scope == "private"

    def test_set_scope_nonexistent(self, pm):
        with pytest.raises(ValueError, match="not found"):
            pm.set_scope("nope", "team")

    def test_set_scope_invalid(self, pm):
        pm.create("clawsy")
        with pytest.raises(ValueError, match="Invalid scope"):
            pm.set_scope("clawsy", "bogus")


# --- Project Write + Default Scope ---


class TestProjectWrite:
    def test_write_uses_project_default_scope(self, pm, store):
        pm.create("clawsy", default_scope="private")
        entry_id = store.write("secret note", project="clawsy")
        store.read(entry_id, agent=None)
        # Private entries need agent match; read raw instead
        path = store.root / "hot" / f"{entry_id}.md"
        text = path.read_text()
        meta, body = parse_entry(text)
        assert meta["scope"] == "private"
        assert meta["project"] == "clawsy"

    def test_write_explicit_scope_overrides_project(self, pm, store):
        pm.create("clawsy", default_scope="team")
        entry_id = store.write("private note", scope="private", project="clawsy")
        path = store.root / "hot" / f"{entry_id}.md"
        text = path.read_text()
        meta, body = parse_entry(text)
        assert meta["scope"] == "private"
        assert meta["project"] == "clawsy"

    def test_write_nonexistent_project_uses_global_default(self, store):
        # Writing to a project that doesn't exist falls back to global default
        entry_id = store.write("note", project="nonexistent")
        path = store.root / "hot" / f"{entry_id}.md"
        text = path.read_text()
        meta, body = parse_entry(text)
        assert meta["scope"] == "team"  # global default
        assert meta["project"] == "nonexistent"

    def test_project_tag_in_frontmatter(self, pm, store):
        pm.create("clawsy")
        entry_id = store.write("tagged entry", project="clawsy")
        path = store.root / "hot" / f"{entry_id}.md"
        text = path.read_text()
        meta, body = parse_entry(text)
        assert meta["project"] == "clawsy"

    def test_entry_without_project(self, store):
        entry_id = store.write("plain entry")
        path = store.root / "hot" / f"{entry_id}.md"
        text = path.read_text()
        meta, body = parse_entry(text)
        assert "project" not in meta


# --- Scope Cascade ---


class TestScopeCascade:
    def test_explicit_scope_wins(self, pm, store):
        pm.create("proj", default_scope="team")
        eid = store.write("test", scope="public", project="proj")
        path = store.root / "hot" / f"{eid}.md"
        meta, _ = parse_entry(path.read_text())
        assert meta["scope"] == "public"

    def test_project_scope_over_global(self, pm, store):
        pm.create("proj", default_scope="private")
        eid = store.write("test", project="proj")
        path = store.root / "hot" / f"{eid}.md"
        meta, _ = parse_entry(path.read_text())
        assert meta["scope"] == "private"

    def test_global_default_when_no_project(self, palaia_root, store):
        # Change global default
        config = store.config.copy()
        config["default_scope"] = "public"
        save_config(palaia_root, config)
        store2 = Store(palaia_root)
        eid = store2.write("test")
        path = palaia_root / "hot" / f"{eid}.md"
        meta, _ = parse_entry(path.read_text())
        assert meta["scope"] == "public"

    def test_fallback_is_team(self, store):
        eid = store.write("test")
        path = store.root / "hot" / f"{eid}.md"
        meta, _ = parse_entry(path.read_text())
        assert meta["scope"] == "team"


# --- Project Query Filter ---


class TestProjectQuery:
    def test_get_project_entries(self, pm, store):
        pm.create("alpha")
        pm.create("beta")
        store.write("alpha entry 1", project="alpha")
        store.write("alpha entry 2", project="alpha")
        store.write("beta entry", project="beta")
        store.write("no project entry")

        alpha_entries = pm.get_project_entries("alpha", store)
        assert len(alpha_entries) == 2

        beta_entries = pm.get_project_entries("beta", store)
        assert len(beta_entries) == 1

    def test_search_with_project_filter(self, pm, store):
        from palaia.search import SearchEngine

        pm.create("alpha")
        store.write("architecture design patterns", project="alpha")
        store.write("architecture legacy code", project="alpha")
        store.write("architecture unrelated")

        engine = SearchEngine(store)
        results = engine.search("architecture", project="alpha")
        assert len(results) == 2
        for r in results:
            # All results should be from the alpha project
            path = store.root / "hot" / f"{r['id']}.md"
            meta, _ = parse_entry(path.read_text())
            assert meta.get("project") == "alpha"


# --- Backward Compatibility ---


class TestBackwardCompatibility:
    def test_entries_without_project_work(self, store):
        eid = store.write("old style entry", scope="team")
        entry = store.read(eid)
        assert entry is not None
        meta, body = entry
        assert body == "old style entry"
        assert "project" not in meta

    def test_list_entries_still_works(self, store):
        store.write("entry 1")
        store.write("entry 2")
        entries = store.list_entries("hot")
        assert len(entries) == 2

    def test_search_without_project(self, store):
        from palaia.search import SearchEngine

        store.write("hello world test")
        engine = SearchEngine(store)
        results = engine.search("hello")
        assert len(results) >= 1


# --- Corrupt projects.json ---


class TestCorruptProjects:
    def test_corrupt_json(self, palaia_root):
        projects_file = palaia_root / "projects.json"
        projects_file.write_text("not valid json {{{")
        pm = ProjectManager(palaia_root)
        # Should not crash, returns empty
        assert pm.list() == []

    def test_invalid_type(self, palaia_root):
        projects_file = palaia_root / "projects.json"
        projects_file.write_text('"just a string"')
        pm = ProjectManager(palaia_root)
        assert pm.list() == []


# --- CLI Integration ---


class TestProjectCLI:
    def _run(self, palaia_root, *args):
        """Run palaia CLI command."""
        result = subprocess.run(
            [sys.executable, "-m", "palaia"] + list(args) + ["--json"],
            capture_output=True,
            text=True,
            cwd=str(palaia_root.parent),
        )
        return result

    def test_cli_project_create(self, palaia_root):
        r = self._run(palaia_root, "project", "create", "test", "--description", "Test Project")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["name"] == "test"

    def test_cli_project_list(self, palaia_root):
        self._run(palaia_root, "project", "create", "alpha")
        self._run(palaia_root, "project", "create", "beta")
        r = self._run(palaia_root, "project", "list")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["projects"]) == 2

    def test_cli_project_show(self, palaia_root):
        self._run(palaia_root, "project", "create", "demo")
        self._run(palaia_root, "project", "write", "demo", "test entry")
        r = self._run(palaia_root, "project", "show", "demo")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["project"]["name"] == "demo"
        assert len(data["entries"]) == 1

    def test_cli_project_write(self, palaia_root):
        self._run(palaia_root, "project", "create", "demo", "--default-scope", "private")
        r = self._run(palaia_root, "project", "write", "demo", "secret note")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert "id" in data
        assert data["project"] == "demo"

    def test_cli_project_delete(self, palaia_root):
        self._run(palaia_root, "project", "create", "temp")
        r = self._run(palaia_root, "project", "delete", "temp")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["deleted"] == "temp"

    def test_cli_project_set_scope(self, palaia_root):
        self._run(palaia_root, "project", "create", "demo")
        r = self._run(palaia_root, "project", "set-scope", "demo", "private")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["default_scope"] == "private"

    def test_cli_write_with_project_flag(self, palaia_root):
        self._run(palaia_root, "project", "create", "demo")
        r = self._run(palaia_root, "write", "hello world", "--project", "demo")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert "id" in data

    def test_cli_list_with_project_filter(self, palaia_root):
        self._run(palaia_root, "project", "create", "demo")
        self._run(palaia_root, "project", "write", "demo", "proj entry")
        self._run(palaia_root, "write", "no project entry")
        r = self._run(palaia_root, "list", "--project", "demo")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["entries"]) == 1
