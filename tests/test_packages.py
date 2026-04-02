"""Tests for Knowledge Packages — export/import (Issue #73)."""

from __future__ import annotations

import json

import pytest

from palaia.config import DEFAULT_CONFIG, save_config
from palaia.packages import PackageManager
from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    root = tmp_path / ".palaia"
    root.mkdir()
    for d in ("hot", "warm", "cold", "wal", "index"):
        (root / d).mkdir()
    config = dict(DEFAULT_CONFIG)
    config["store_version"] = "2.0.0"
    save_config(root, config)
    return root


@pytest.fixture
def store(palaia_root):
    return Store(palaia_root)


@pytest.fixture
def populated_store(store):
    """Store with entries in two projects."""
    store.write(
        "Architecture decision: use PostgreSQL",
        project="alpha",
        tags=["decision"],
        entry_type="memory",
        title="DB Choice",
    )
    store.write(
        "Deploy via Docker Compose", project="alpha", tags=["deployment"], entry_type="process", title="Deploy Process"
    )
    store.write("Fix login bug", project="alpha", entry_type="task", title="Login Bug")
    store.write("Beta project note", project="beta", entry_type="memory", title="Beta Note")
    return store


class TestExportPackage:
    def test_export_all_entries(self, populated_store, tmp_path):
        pm = PackageManager(populated_store)
        out = str(tmp_path / "alpha.palaia-pkg.json")
        result = pm.export_package("alpha", output_path=out)

        assert result["entry_count"] == 3
        assert result["project"] == "alpha"

        pkg = json.loads((tmp_path / "alpha.palaia-pkg.json").read_text())
        assert pkg["palaia_package"] == "1.0"
        assert pkg["entry_count"] == 3
        assert pkg["project"] == "alpha"
        assert len(pkg["entries"]) == 3

    def test_export_filtered_by_type(self, populated_store, tmp_path):
        pm = PackageManager(populated_store)
        out = str(tmp_path / "alpha-mem.palaia-pkg.json")
        result = pm.export_package("alpha", output_path=out, include_types=["memory"])

        assert result["entry_count"] == 1
        pkg = json.loads((tmp_path / "alpha-mem.palaia-pkg.json").read_text())
        assert all(e["type"] == "memory" for e in pkg["entries"])

    def test_export_default_filename(self, populated_store):
        pm = PackageManager(populated_store)
        result = pm.export_package("alpha")
        assert result["path"] == "alpha.palaia-pkg.json"
        import os

        os.unlink("alpha.palaia-pkg.json")  # cleanup

    def test_export_empty_project(self, populated_store, tmp_path):
        pm = PackageManager(populated_store)
        out = str(tmp_path / "empty.palaia-pkg.json")
        result = pm.export_package("nonexistent", output_path=out)
        assert result["entry_count"] == 0

    def test_entry_format(self, populated_store, tmp_path):
        pm = PackageManager(populated_store)
        out = str(tmp_path / "alpha.palaia-pkg.json")
        pm.export_package("alpha", output_path=out)
        pkg = json.loads((tmp_path / "alpha.palaia-pkg.json").read_text())

        for entry in pkg["entries"]:
            assert "content" in entry
            assert "type" in entry
            assert entry["content"].strip()  # non-empty


class TestImportPackage:
    def test_import_roundtrip(self, populated_store, tmp_path):
        pm = PackageManager(populated_store)
        out = str(tmp_path / "alpha.palaia-pkg.json")
        pm.export_package("alpha", output_path=out)

        # Import into a new project
        result = pm.import_package(out, target_project="alpha-copy", merge_strategy="append")
        assert result["imported"] == 3
        assert result["project"] == "alpha-copy"

    def test_import_skip_duplicates(self, populated_store, tmp_path):
        pm = PackageManager(populated_store)
        out = str(tmp_path / "alpha.palaia-pkg.json")
        pm.export_package("alpha", output_path=out)

        # Import into same project — should skip all (same content)
        result = pm.import_package(out, target_project="alpha", merge_strategy="skip")
        assert result["skipped"] == 3
        assert result["imported"] == 0

    def test_import_overwrite(self, populated_store, tmp_path):
        pm = PackageManager(populated_store)
        out = str(tmp_path / "alpha.palaia-pkg.json")
        pm.export_package("alpha", output_path=out)

        # Import with overwrite into same project
        result = pm.import_package(out, target_project="alpha", merge_strategy="overwrite")
        assert result["overwritten"] == 3

    def test_import_append_always(self, populated_store, tmp_path):
        pm = PackageManager(populated_store)
        out = str(tmp_path / "alpha.palaia-pkg.json")
        pm.export_package("alpha", output_path=out)

        # Append creates duplicates
        result = pm.import_package(out, target_project="alpha", merge_strategy="append")
        assert result["imported"] == 3

    def test_import_uses_package_project(self, populated_store, tmp_path):
        pm = PackageManager(populated_store)
        out = str(tmp_path / "alpha.palaia-pkg.json")
        pm.export_package("alpha", output_path=out)

        result = pm.import_package(out, merge_strategy="append")
        assert result["project"] == "alpha"

    def test_import_invalid_merge_strategy(self, populated_store, tmp_path):
        pm = PackageManager(populated_store)
        out = str(tmp_path / "alpha.palaia-pkg.json")
        pm.export_package("alpha", output_path=out)

        with pytest.raises(ValueError, match="Invalid merge strategy"):
            pm.import_package(out, merge_strategy="invalid")

    def test_import_file_not_found(self, populated_store):
        pm = PackageManager(populated_store)
        with pytest.raises(FileNotFoundError):
            pm.import_package("/nonexistent/file.json")

    def test_import_invalid_package(self, populated_store, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text('{"not": "a package"}')
        pm = PackageManager(populated_store)
        with pytest.raises(ValueError, match="Not a valid palaia package"):
            pm.import_package(str(bad_file))


class TestPackageInfo:
    def test_info_shows_metadata(self, populated_store, tmp_path):
        pm = PackageManager(populated_store)
        out = str(tmp_path / "alpha.palaia-pkg.json")
        pm.export_package("alpha", output_path=out)

        info = pm.package_info(out)
        assert info["palaia_package"] == "1.0"
        assert info["project"] == "alpha"
        assert info["entry_count"] == 3
        assert "exported_at" in info
        assert info["type_breakdown"]["memory"] == 1
        assert info["type_breakdown"]["process"] == 1
        assert info["type_breakdown"]["task"] == 1

    def test_info_file_not_found(self, populated_store):
        pm = PackageManager(populated_store)
        with pytest.raises(FileNotFoundError):
            pm.package_info("/nonexistent/file.json")

    def test_info_invalid_package(self, populated_store, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text('{"hello": "world"}')
        pm = PackageManager(populated_store)
        with pytest.raises(ValueError):
            pm.package_info(str(bad_file))


class TestImportAgentAttribution:
    """Tests for Issue #85: agent attribution on package import."""

    def test_import_with_agent(self, store, tmp_path):
        """Importing with --agent should attribute all entries to that agent."""
        # Create a standalone package with unique content (avoids store-level dedup)
        package = {
            "palaia_package": "1.0",
            "palaia_version": "2.0.0",
            "project": "agent-test",
            "exported_at": "2026-03-16",
            "entry_count": 2,
            "entries": [
                {"content": "Unique entry for agent test one", "type": "memory", "tags": ["test"]},
                {"content": "Unique entry for agent test two", "type": "process", "tags": ["test"]},
            ],
        }
        pkg_file = tmp_path / "agent-test.palaia-pkg.json"
        pkg_file.write_text(json.dumps(package))

        pm = PackageManager(store)
        result = pm.import_package(
            str(pkg_file),
            target_project="agent-test",
            merge_strategy="append",
            agent="Elliot",
        )
        assert result["imported"] == 2

        # Verify entries have the agent set
        all_entries = store.all_entries_unfiltered(include_cold=True)
        agent_entries = [
            meta
            for meta, body, tier in all_entries
            if meta.get("project") == "agent-test" and meta.get("agent") == "Elliot"
        ]
        assert len(agent_entries) == 2

    def test_import_without_agent(self, store, tmp_path):
        """Importing without --agent should not set agent field."""
        package = {
            "palaia_package": "1.0",
            "palaia_version": "2.0.0",
            "project": "noagent-test",
            "exported_at": "2026-03-16",
            "entry_count": 1,
            "entries": [
                {"content": "Unique entry without agent attribution", "type": "memory"},
            ],
        }
        pkg_file = tmp_path / "noagent-test.palaia-pkg.json"
        pkg_file.write_text(json.dumps(package))

        pm = PackageManager(store)
        result = pm.import_package(
            str(pkg_file),
            target_project="noagent-test",
            merge_strategy="append",
        )
        assert result["imported"] == 1
