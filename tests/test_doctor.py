"""Tests for palaia doctor command."""

from __future__ import annotations

import json

import pytest

from palaia.doctor import (
    _check_embedding_chain,
    _check_heartbeat_legacy,
    _check_openclaw_plugin,
    _check_palaia_init,
    _check_smart_memory_skill,
    _check_wal_health,
    format_doctor_report,
    run_doctor,
)


@pytest.fixture
def palaia_root(tmp_path):
    """Create a minimal .palaia directory."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    # Write default config
    config = {
        "version": 1,
        "embedding_chain": ["openai", "bm25"],
        "default_scope": "team",
        "decay_lambda": 0.1,
        "hot_threshold_days": 7,
        "warm_threshold_days": 30,
        "hot_max_entries": 50,
        "hot_min_score": 0.5,
        "warm_min_score": 0.1,
        "wal_retention_days": 7,
        "lock_timeout_seconds": 5,
        "embedding_provider": "auto",
        "embedding_model": "",
    }
    (root / "config.json").write_text(json.dumps(config))
    return root


@pytest.fixture
def workspace(tmp_path):
    """Create a mock workspace for legacy checks."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


class TestCheckPalaiaInit:
    def test_not_initialized(self):
        result = _check_palaia_init(None)
        assert result["status"] == "error"
        assert "palaia init" in result["message"]

    def test_initialized_empty(self, palaia_root):
        result = _check_palaia_init(palaia_root)
        assert result["status"] == "ok"
        assert "0 entries" in result["message"]

    def test_initialized_with_entries(self, palaia_root):
        # Create some entries
        for i in range(3):
            (palaia_root / "hot" / f"entry-{i}.md").write_text(f"test {i}")
        (palaia_root / "warm" / "entry-w.md").write_text("warm entry")

        result = _check_palaia_init(palaia_root)
        assert result["status"] == "ok"
        assert "4 entries" in result["message"]


class TestCheckEmbeddingChain:
    def test_not_initialized(self):
        result = _check_embedding_chain(None)
        assert result["status"] == "error"

    def test_chain_ok(self, palaia_root, monkeypatch):
        """Chain with openai AND local model → status ok."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["embedding_chain"] = ["openai", "sentence-transformers", "bm25"]
        (palaia_root / "config.json").write_text(json.dumps(config))

        # Mock detect_providers to report all providers as available
        monkeypatch.setattr(
            "palaia.embeddings.detect_providers",
            lambda: [
                {"name": "openai", "available": True},
                {"name": "sentence-transformers", "available": True},
                {"name": "bm25", "available": True},
            ],
        )

        result = _check_embedding_chain(palaia_root)
        assert result["status"] == "ok"
        assert "openai → sentence-transformers → bm25" in result["message"]

    def test_chain_missing_provider(self, palaia_root, monkeypatch):
        """Chain with a provider that is no longer installed → status warn."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["embedding_chain"] = ["openai", "sentence-transformers", "bm25"]
        (palaia_root / "config.json").write_text(json.dumps(config))

        # sentence-transformers not available
        monkeypatch.setattr(
            "palaia.embeddings.detect_providers",
            lambda: [
                {"name": "openai", "available": True},
                {"name": "sentence-transformers", "available": False},
                {"name": "bm25", "available": True},
            ],
        )

        result = _check_embedding_chain(palaia_root)
        assert result["status"] == "warn"
        assert "MISSING" in result["message"]
        assert result.get("fixable") is True

    def test_chain_warn_no_local_fallback(self, palaia_root, monkeypatch):
        """Chain with openai ONLY (no local model) → status warn."""
        # Mock detect_providers: openai available, no local missing from chain
        monkeypatch.setattr(
            "palaia.embeddings.detect_providers",
            lambda: [
                {"name": "openai", "available": True},
                {"name": "bm25", "available": True},
            ],
        )
        result = _check_embedding_chain(palaia_root)
        assert result["status"] == "warn"
        assert "openai → bm25" in result["message"]
        assert "no local fallback" in result["message"]

    def test_auto_detect(self, palaia_root):
        # Rewrite config without chain
        config = json.loads((palaia_root / "config.json").read_text())
        del config["embedding_chain"]
        config["embedding_provider"] = "auto"
        (palaia_root / "config.json").write_text(json.dumps(config))

        result = _check_embedding_chain(palaia_root)
        assert result["status"] == "warn"
        assert "auto-detect" in result["message"]

    def test_single_provider(self, palaia_root):
        config = json.loads((palaia_root / "config.json").read_text())
        del config["embedding_chain"]
        config["embedding_provider"] = "sentence-transformers"
        (palaia_root / "config.json").write_text(json.dumps(config))

        result = _check_embedding_chain(palaia_root)
        assert result["status"] == "ok"
        assert "sentence-transformers" in result["message"]


class TestCheckOpenClawPlugin:
    def test_no_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        result = _check_openclaw_plugin()
        assert result["status"] == "info"
        assert "not found" in result["message"]

    def test_palaia_active(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        oc_dir = tmp_path / ".openclaw"
        oc_dir.mkdir()
        config = {"plugins": {"slots": {"memory": "palaia"}}}
        (oc_dir / "config.json").write_text(json.dumps(config))

        result = _check_openclaw_plugin()
        assert result["status"] == "ok"
        assert "palaia is active" in result["message"]

    def test_memory_core_active(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        oc_dir = tmp_path / ".openclaw"
        oc_dir.mkdir()
        config = {"plugins": {"slots": {"memory": "memory-core"}}}
        (oc_dir / "config.json").write_text(json.dumps(config))

        result = _check_openclaw_plugin()
        assert result["status"] == "warn"
        assert "memory-core" in result["message"]
        assert "fix" in result


    def test_openclaw_config_env_var(self, tmp_path, monkeypatch):
        """OPENCLAW_CONFIG env var should be checked for config location."""
        monkeypatch.setenv("HOME", str(tmp_path))
        config_path = tmp_path / "custom" / "openclaw.json"
        config_path.parent.mkdir(parents=True)
        config = {"plugins": {"slots": {"memory": "palaia"}}}
        config_path.write_text(json.dumps(config))

        monkeypatch.setenv("OPENCLAW_CONFIG", str(config_path))
        result = _check_openclaw_plugin()
        assert result["status"] == "ok"
        assert "palaia is active" in result["message"]

    def test_yaml_config(self, tmp_path, monkeypatch):
        """YAML config should be parsed if yaml is available."""
        monkeypatch.setenv("HOME", str(tmp_path))
        oc_dir = tmp_path / ".openclaw"
        oc_dir.mkdir()

        try:
            import yaml  # noqa: F401

            config_content = "plugins:\n  slots:\n    memory: palaia\n"
            (oc_dir / "config.yaml").write_text(config_content)
            result = _check_openclaw_plugin()
            assert result["status"] == "ok"
        except ImportError:
            pytest.skip("yaml not installed")


class TestCheckSmartMemorySkill:
    def test_not_installed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        result = _check_smart_memory_skill()
        assert result["status"] == "ok"
        assert "Not installed" in result["message"]

    def test_installed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        skill_dir = tmp_path / ".openclaw" / "workspace" / "skills" / "smart-memory"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Smart Memory")

        result = _check_smart_memory_skill()
        assert result["status"] == "warn"
        assert "Detected" in result["message"]


class TestCheckHeartbeatLegacy:
    def test_no_heartbeat(self, workspace):
        result = _check_heartbeat_legacy(workspace)
        assert result["status"] == "ok"

    def test_clean_heartbeat(self, workspace):
        (workspace / "HEARTBEAT.md").write_text("# Heartbeat\nCheck weather\nCheck emails\n")
        result = _check_heartbeat_legacy(workspace)
        assert result["status"] == "ok"

    def test_legacy_patterns(self, workspace):
        content = """# Heartbeat Tasks
- Check emails
- memory_search for recent context
- Read memory/active-context.md
- Update MEMORY.md
"""
        (workspace / "HEARTBEAT.md").write_text(content)
        result = _check_heartbeat_legacy(workspace)
        assert result["status"] == "warn"
        assert result["details"]["patterns_found"]
        assert "fix" in result


class TestCheckWalHealth:
    def test_not_initialized(self):
        result = _check_wal_health(None)
        assert result["status"] == "error"

    def test_clean_wal(self, palaia_root):
        result = _check_wal_health(palaia_root)
        assert result["status"] == "ok"
        assert "Clean" in result["message"]

    def test_pending_wal(self, palaia_root):
        # Create a pending WAL entry
        wal_entry = {
            "id": "test-123",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "operation": "write",
            "target": "hot/test.md",
            "payload_hash": "abc",
            "status": "pending",
        }
        (palaia_root / "wal" / "2025-01-01T00-00-00p00-00-test-123.json").write_text(json.dumps(wal_entry))
        result = _check_wal_health(palaia_root)
        assert result["status"] == "warn"
        assert "1 unflushed" in result["message"]


class TestFormatReport:
    def test_all_clean(self):
        results = [
            {"name": "test", "label": "Test check", "status": "ok", "message": "All good"},
        ]
        report = format_doctor_report(results)
        assert "All clear" in report
        assert "✅" in report

    def test_with_warnings(self):
        results = [
            {"name": "ok_check", "label": "Good check", "status": "ok", "message": "Fine"},
            {
                "name": "warn_check",
                "label": "Warn check",
                "status": "warn",
                "message": "Problem",
                "fix": "Do something",
            },
        ]
        report = format_doctor_report(results)
        assert "1 warning" in report
        assert "--fix" in report

    def test_with_fix_flag(self):
        results = [
            {
                "name": "warn_check",
                "label": "Warn check",
                "status": "warn",
                "message": "Problem",
                "fix": "Step 1: Do this\nStep 2: Do that",
            },
        ]
        report = format_doctor_report(results, show_fix=True)
        assert "Fix:" in report
        assert "Step 1" in report


class TestRunDoctor:
    def test_run_all_checks(self, palaia_root, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        results = run_doctor(palaia_root)
        assert len(results) == 10
        assert all("status" in r for r in results)
        assert all("name" in r for r in results)

    def test_run_without_init(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        results = run_doctor(None)
        assert results[0]["status"] == "error"  # palaia_init


class TestDoctorCLI:
    """Test the doctor command via CLI entry point."""

    def test_doctor_json(self, palaia_root, tmp_path, monkeypatch):
        """Test --json output."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.chdir(palaia_root.parent)

        import io
        import sys

        from palaia.cli import main

        captured = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured)
        monkeypatch.setattr(sys, "argv", ["palaia", "doctor", "--json"])

        main()

        output = captured.getvalue()
        data = json.loads(output)
        assert "checks" in data
        assert isinstance(data["checks"], list)

    def test_doctor_fix(self, palaia_root, tmp_path, monkeypatch):
        """Test --fix flag."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.chdir(palaia_root.parent)

        # Create a smart-memory skill to trigger a warning
        skill_dir = tmp_path / ".openclaw" / "workspace" / "skills" / "smart-memory"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Smart Memory")

        import io
        import sys

        from palaia.cli import main

        captured = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured)
        monkeypatch.setattr(sys, "argv", ["palaia", "doctor", "--fix"])

        main()

        output = captured.getvalue()
        assert "Fix:" in output
