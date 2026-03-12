"""Tests for UX improvements: issues #9, #10, #11, #12 + version tracking."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from palaia import __version__
from palaia.config import DEFAULT_CONFIG, load_config, save_config
from palaia.doctor import run_doctor
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
    config = dict(DEFAULT_CONFIG)
    config["store_version"] = __version__
    save_config(root, config)
    return root


@pytest.fixture
def pm(palaia_root):
    return ProjectManager(palaia_root)


@pytest.fixture
def store(palaia_root):
    return Store(palaia_root)


# --- Issue #9: Auto-create projects ---


class TestAutoCreateProject:
    def test_ensure_creates_new_project(self, pm):
        """ensure() should create a project that doesn't exist."""
        project = pm.ensure("new-proj")
        assert project.name == "new-proj"
        assert project.default_scope == "team"
        # Should be persisted
        assert pm.get("new-proj") is not None

    def test_ensure_returns_existing_project(self, pm):
        """ensure() should return existing project without error."""
        pm.create("existing", description="Already here", default_scope="private")
        project = pm.ensure("existing")
        assert project.name == "existing"
        assert project.description == "Already here"
        assert project.default_scope == "private"

    def test_ensure_respects_default_scope(self, pm):
        """ensure() should pass default_scope when creating."""
        project = pm.ensure("scoped", default_scope="private")
        assert project.default_scope == "private"

    def test_store_write_auto_creates_project(self, store, pm):
        """store.write() with --project should auto-create the project."""
        entry_id = store.write("auto-create test", project="auto-proj")
        assert entry_id
        # Project should now exist
        project = pm.get("auto-proj")
        assert project is not None
        assert project.name == "auto-proj"

    def test_store_write_auto_create_uses_project_scope(self, store, pm):
        """Auto-created project should use global default scope, then entry uses it."""
        entry_id = store.write("scoped entry", project="scoped-proj")
        path = store.root / "hot" / f"{entry_id}.md"
        meta, _ = parse_entry(path.read_text())
        assert meta["project"] == "scoped-proj"
        assert meta["scope"] == "team"  # global default

    def test_store_write_existing_project_not_recreated(self, store, pm):
        """Writing to existing project should not raise or recreate."""
        pm.create("existing", description="Original", default_scope="private")
        entry_id = store.write("test", project="existing")
        assert entry_id
        # Description should be preserved (not overwritten)
        project = pm.get("existing")
        assert project.description == "Original"


# --- Issue #10: Multi-Agent Setup ---


class TestMultiAgentSetup:
    def test_setup_creates_symlinks(self, palaia_root, tmp_path):
        """setup should create .palaia symlinks in agent dirs."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "main").mkdir()
        (agents_dir / "elliot").mkdir()
        (agents_dir / "saul").mkdir()

        # Call the setup function directly
        from palaia.cli import cmd_setup

        class Args:
            multi_agent = str(agents_dir)
            dry_run = False
            json = True

        import io
        from contextlib import redirect_stdout

        # Need to mock get_root
        import palaia.cli

        original_get_root = palaia.cli.get_root
        palaia.cli.get_root = lambda: palaia_root

        try:
            f = io.StringIO()
            with redirect_stdout(f):
                ret = cmd_setup(Args())
            output = f.getvalue()
            data = json.loads(output)
            assert ret == 0
            assert set(data["agents"]) == {"main", "elliot", "saul"}
            assert data["symlinks_created"] == 3

            # Verify symlinks exist
            for agent in ("main", "elliot", "saul"):
                link = agents_dir / agent / ".palaia"
                assert link.is_symlink()
                assert link.resolve() == palaia_root.resolve()
        finally:
            palaia.cli.get_root = original_get_root

    def test_setup_dry_run(self, palaia_root, tmp_path):
        """--dry-run should not create symlinks."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "agent1").mkdir()

        from palaia.cli import cmd_setup

        class Args:
            multi_agent = str(agents_dir)
            dry_run = True
            json = True

        import io
        from contextlib import redirect_stdout

        import palaia.cli

        original_get_root = palaia.cli.get_root
        palaia.cli.get_root = lambda: palaia_root

        try:
            f = io.StringIO()
            with redirect_stdout(f):
                ret = cmd_setup(Args())
            data = json.loads(f.getvalue())
            assert ret == 0
            assert data["dry_run"] is True
            assert data["symlinks_created"] == 1
            # Symlink should NOT exist
            assert not (agents_dir / "agent1" / ".palaia").exists()
        finally:
            palaia.cli.get_root = original_get_root

    def test_setup_skips_existing(self, palaia_root, tmp_path):
        """setup should skip dirs that already have .palaia."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        agent_dir = agents_dir / "existing"
        agent_dir.mkdir()
        (agent_dir / ".palaia").symlink_to(palaia_root)

        from palaia.cli import cmd_setup

        class Args:
            multi_agent = str(agents_dir)
            dry_run = False
            json = True

        import io
        from contextlib import redirect_stdout

        import palaia.cli

        original_get_root = palaia.cli.get_root
        palaia.cli.get_root = lambda: palaia_root

        try:
            f = io.StringIO()
            with redirect_stdout(f):
                ret = cmd_setup(Args())
            data = json.loads(f.getvalue())
            assert ret == 0
            assert data["symlinks_created"] == 0
        finally:
            palaia.cli.get_root = original_get_root

    def test_setup_ignores_dotdirs(self, palaia_root, tmp_path):
        """setup should ignore hidden directories."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / ".hidden").mkdir()
        (agents_dir / "visible").mkdir()

        from palaia.cli import cmd_setup

        class Args:
            multi_agent = str(agents_dir)
            dry_run = False
            json = True

        import io
        from contextlib import redirect_stdout

        import palaia.cli

        original_get_root = palaia.cli.get_root
        palaia.cli.get_root = lambda: palaia_root

        try:
            f = io.StringIO()
            with redirect_stdout(f):
                cmd_setup(Args())
            data = json.loads(f.getvalue())
            assert "visible" in data["agents"]
            assert ".hidden" not in data["agents"]
        finally:
            palaia.cli.get_root = original_get_root


# --- Issue #12: List Filters ---


class TestListFilters:
    def test_filter_by_project(self, store, pm):
        pm.create("alpha")
        store.write("alpha entry", project="alpha")
        store.write("no project entry")

        entries = store.list_entries("hot")
        filtered = [(m, b) for m, b in entries if m.get("project") == "alpha"]
        assert len(filtered) == 1

    def test_filter_by_tag(self, store):
        store.write("tagged", tags=["important", "daily"])
        store.write("untagged")

        entries = store.list_entries("hot")
        filtered = [(m, b) for m, b in entries if "important" in (m.get("tags") or [])]
        assert len(filtered) == 1

    def test_filter_by_scope(self, store):
        store.write("team entry", scope="team")
        store.write("public entry", scope="public")

        entries = store.list_entries("hot")
        filtered = [(m, b) for m, b in entries if m.get("scope") == "public"]
        assert len(filtered) == 1

    def test_filter_by_agent(self, store):
        store.write("agent1 entry", agent="agent1")
        store.write("agent2 entry", agent="agent2")

        entries = store.list_entries("hot")
        filtered = [(m, b) for m, b in entries if m.get("agent") == "agent1"]
        assert len(filtered) == 1

    def test_combined_filters(self, store, pm):
        pm.create("proj")
        store.write("match", project="proj", tags=["daily"], agent="bot1")
        store.write("wrong project", project="other", tags=["daily"], agent="bot1")
        store.write("wrong tag", project="proj", tags=["weekly"], agent="bot1")

        entries = store.list_entries("hot")
        filtered = [
            (m, b)
            for m, b in entries
            if m.get("project") == "proj" and "daily" in (m.get("tags") or [])
        ]
        assert len(filtered) == 1

    def test_cli_list_filters_json(self, palaia_root, pm):
        """CLI integration: list with --tag, --scope, --agent filters."""
        store = Store(palaia_root)
        store.write("entry1", tags=["bug"], scope="team", agent="bot1")
        store.write("entry2", tags=["feature"], scope="public", agent="bot2")

        def _run(*args):
            result = subprocess.run(
                [sys.executable, "-m", "palaia"] + list(args) + ["--json"],
                capture_output=True,
                text=True,
                cwd=str(palaia_root.parent),
            )
            return result

        # Filter by tag
        r = _run("list", "--tag", "bug")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["entries"]) == 1
        assert "bug" in data["entries"][0]["tags"]

        # Filter by agent
        r = _run("list", "--agent", "bot2")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["entries"]) == 1
        assert data["entries"][0]["agent"] == "bot2"

        # Filter by scope
        r = _run("list", "--scope", "public")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["entries"]) == 1

        # No match
        r = _run("list", "--tag", "nonexistent")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["entries"]) == 0


# --- Version Tracking + Doctor ---


class TestVersionTracking:
    def test_store_version_set_on_init(self, palaia_root):
        config = load_config(palaia_root)
        assert config.get("store_version") == __version__

    def test_doctor_stamps_legacy_store(self, tmp_path):
        """Doctor should stamp stores missing store_version."""
        root = tmp_path / ".palaia"
        root.mkdir()
        for sub in ("hot", "warm", "cold", "wal", "index"):
            (root / sub).mkdir()
        # Save config without store_version
        config = dict(DEFAULT_CONFIG)
        del config["store_version"]
        save_config(root, config)

        results = run_doctor(root)
        ver_check = next(r for r in results if r["name"] == "store_version")
        assert ver_check["status"] == "info"
        assert "stamped" in ver_check["message"]

        # Should now be stamped
        config = load_config(root)
        assert config["store_version"] == __version__

    def test_doctor_detects_version_mismatch(self, tmp_path):
        """Doctor should detect and upgrade store version."""
        root = tmp_path / ".palaia"
        root.mkdir()
        for sub in ("hot", "warm", "cold", "wal", "index"):
            (root / sub).mkdir()
        config = dict(DEFAULT_CONFIG)
        config["store_version"] = "0.9.0"
        save_config(root, config)

        results = run_doctor(root)
        ver_check = next(r for r in results if r["name"] == "store_version")
        assert ver_check["status"] == "info"
        assert "Upgraded" in ver_check["message"]
        assert "0.9.0" in ver_check["message"]

    def test_doctor_ok_when_versions_match(self, palaia_root):
        results = run_doctor(palaia_root)
        ver_check = next(r for r in results if r["name"] == "store_version")
        assert ver_check["status"] == "ok"

    def test_doctor_checks_projects_usage(self, palaia_root):
        results = run_doctor(palaia_root)
        proj_check = next(r for r in results if r["name"] == "projects_usage")
        assert proj_check["status"] == "info"  # Not used yet

        # Create a project
        pm = ProjectManager(palaia_root)
        pm.create("test")
        results = run_doctor(palaia_root)
        proj_check = next(r for r in results if r["name"] == "projects_usage")
        assert proj_check["status"] == "ok"

    def test_doctor_checks_deprecated_config(self, palaia_root):
        results = run_doctor(palaia_root)
        cfg_check = next(r for r in results if r["name"] == "deprecated_config")
        assert cfg_check["status"] == "ok"


# --- Issue #9 CLI Integration ---


class TestAutoCreateProjectCLI:
    def _run(self, palaia_root, *args):
        result = subprocess.run(
            [sys.executable, "-m", "palaia"] + list(args) + ["--json"],
            capture_output=True,
            text=True,
            cwd=str(palaia_root.parent),
        )
        return result

    def test_write_autocreates_project(self, palaia_root):
        """palaia write --project X should auto-create project X."""
        r = self._run(palaia_root, "write", "test entry", "--project", "auto-created")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert "id" in data

        # Verify project exists
        r = self._run(palaia_root, "project", "show", "auto-created")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["project"]["name"] == "auto-created"

    def test_write_existing_project_works(self, palaia_root):
        """Writing to existing project should still work."""
        self._run(palaia_root, "project", "create", "existing")
        r = self._run(palaia_root, "write", "test", "--project", "existing")
        assert r.returncode == 0
