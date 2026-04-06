"""Tests for palaia setup claude-code command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from palaia.doctor.checks import _check_claude_code_config
from palaia.services.admin import CLAUDE_CODE_TEMPLATE, setup_claude_code


@pytest.fixture
def palaia_root(tmp_path):
    """Create a minimal .palaia directory."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    config = {
        "version": 1,
        "embedding_chain": ["bm25"],
        "agent": "test",
    }
    (root / "config.json").write_text(json.dumps(config))
    return root


# ── setup_claude_code service tests ──────────────────────────────────────


class TestSetupClaudeCode:
    def test_dry_run_creates_nothing(self, palaia_root, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)
        result = setup_claude_code(palaia_root, dry_run=True)

        assert result["status"] == "ok"
        assert result["dry_run"] is True
        # Nothing should actually be written
        assert not (tmp_path / ".claude" / "settings.json").exists()
        assert not (tmp_path / "CLAUDE.md").exists()
        # But actions should be planned
        actions = {a["action"] for a in result["actions"]}
        assert "plan" in actions

    def test_creates_settings_and_claude_md(self, palaia_root, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)
        result = setup_claude_code(palaia_root)

        assert result["status"] == "ok"

        # Check settings.json was created
        settings_path = tmp_path / ".claude" / "settings.json"
        assert settings_path.exists()
        settings = json.loads(settings_path.read_text())
        assert "palaia" in settings["mcpServers"]
        assert "palaia-mcp" in settings["mcpServers"]["palaia"]["command"]

        # Check CLAUDE.md was created
        claude_md = tmp_path / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "palaia_search" in content
        assert "palaia_store" in content

    def test_skips_if_already_configured(self, palaia_root, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)

        # Pre-create settings with palaia configured
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir(parents=True)
        (settings_dir / "settings.json").write_text(json.dumps({
            "mcpServers": {"palaia": {"command": "custom-palaia-mcp"}}
        }))

        result = setup_claude_code(palaia_root)

        assert result["already_configured"] is True
        # Should not overwrite the existing config
        settings = json.loads((settings_dir / "settings.json").read_text())
        assert settings["mcpServers"]["palaia"]["command"] == "custom-palaia-mcp"

    def test_preserves_existing_settings(self, palaia_root, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)

        # Pre-create settings with other MCP servers
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir(parents=True)
        (settings_dir / "settings.json").write_text(json.dumps({
            "mcpServers": {"other-tool": {"command": "other-mcp"}},
            "customSetting": True,
        }))

        setup_claude_code(palaia_root)

        settings = json.loads((settings_dir / "settings.json").read_text())
        assert "palaia" in settings["mcpServers"]
        assert "other-tool" in settings["mcpServers"]
        assert settings["customSetting"] is True

    def test_appends_to_existing_claude_md(self, palaia_root, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)

        # Pre-create CLAUDE.md without palaia
        existing = "# My Project\n\nExisting instructions.\n"
        (tmp_path / "CLAUDE.md").write_text(existing)

        setup_claude_code(palaia_root)

        content = (tmp_path / "CLAUDE.md").read_text()
        assert content.startswith("# My Project")
        assert "palaia_search" in content
        assert "Existing instructions." in content

    def test_skips_claude_md_if_already_has_palaia(self, palaia_root, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)

        existing = "# My Project\n\nUse palaia for memory.\n"
        (tmp_path / "CLAUDE.md").write_text(existing)

        setup_claude_code(palaia_root)

        content = (tmp_path / "CLAUDE.md").read_text()
        assert content == existing

    def test_global_config_writes_to_claude_dir(self, palaia_root, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)
        result = setup_claude_code(palaia_root, global_config=True)

        assert result["status"] == "ok"
        assert (tmp_path / ".claude" / "CLAUDE.md").exists()
        assert not (tmp_path / "CLAUDE.md").exists()

    def test_error_when_palaia_mcp_not_found(self, palaia_root, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)

        import shutil
        monkeypatch.setattr(shutil, "which", lambda x: None)

        import sys
        fake_exe = tmp_path / "nonexistent" / "python"
        monkeypatch.setattr(sys, "executable", str(fake_exe))

        result = setup_claude_code(palaia_root)
        assert "error" in result
        assert "palaia-mcp" in result["error"]


# ── Doctor check tests ───────────────────────────────────────────────────


class TestDoctorClaudeCodeConfig:
    def test_no_settings_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = _check_claude_code_config(None)
        assert result["status"] == "info"
        assert "setup claude-code" in result["message"]

    def test_settings_without_palaia(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        (settings_dir / "settings.json").write_text(json.dumps({
            "mcpServers": {"other": {"command": "other"}}
        }))
        result = _check_claude_code_config(None)
        assert result["status"] == "info"

    def test_settings_with_palaia(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        (settings_dir / "settings.json").write_text(json.dumps({
            "mcpServers": {"palaia": {"command": "palaia-mcp"}}
        }))
        result = _check_claude_code_config(None)
        assert result["status"] == "ok"
        assert "palaia-mcp" in result["message"]

    def test_invalid_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        (settings_dir / "settings.json").write_text("not json {{{")
        result = _check_claude_code_config(None)
        assert result["status"] == "warn"


# ── CLAUDE.md template tests ────────────────────────────────────────────


class TestClaudeMdTemplate:
    def test_template_contains_essential_tools(self):
        assert "palaia_search" in CLAUDE_CODE_TEMPLATE
        assert "palaia_store" in CLAUDE_CODE_TEMPLATE
        assert "palaia_read" in CLAUDE_CODE_TEMPLATE
        assert "palaia_edit" in CLAUDE_CODE_TEMPLATE

    def test_template_has_guidance_sections(self):
        assert "Session start routine" in CLAUDE_CODE_TEMPLATE
        assert "When NOT to store" in CLAUDE_CODE_TEMPLATE
        assert "built-in memory" in CLAUDE_CODE_TEMPLATE
        assert "First session" in CLAUDE_CODE_TEMPLATE

    def test_template_instructs_proactive_storage(self):
        assert "Store proactively" in CLAUDE_CODE_TEMPLATE
