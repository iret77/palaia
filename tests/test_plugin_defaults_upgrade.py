"""Tests for v1.x → v2.0 plugin defaults upgrade path (doctor check + fix)."""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def palaia_root(tmp_path):
    """Create a minimal .palaia directory with v1.x-style config."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    config = {
        "version": 1,
        "embedding_chain": ["bm25"],
        "agent": "TestAgent",
        "store_version": "1.9.0",
    }
    (root / "config.json").write_text(json.dumps(config))
    return root


class TestPluginDefaultsUpgradeCheck:
    """Test _check_plugin_defaults_upgrade detection."""

    def test_no_plugin_config_is_ok(self, palaia_root):
        """No plugin_config at all → ok (TS plugin defaults apply)."""
        from palaia.doctor import _check_plugin_defaults_upgrade

        result = _check_plugin_defaults_upgrade(palaia_root)
        assert result["status"] == "ok"
        assert "v2.0" in result["message"]

    def test_v1_defaults_detected(self, palaia_root):
        """plugin_config with autoCapture=false → warn (v1.x default)."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["plugin_config"] = {
            "autoCapture": False,
            "captureFrequency": "significant",
            "captureMinTurns": 2,
        }
        (palaia_root / "config.json").write_text(json.dumps(config))

        from palaia.doctor import _check_plugin_defaults_upgrade

        result = _check_plugin_defaults_upgrade(palaia_root)
        assert result["status"] == "warn"
        assert result.get("fixable") is True
        assert "autoCapture" in result["message"]

    def test_v2_defaults_already_set(self, palaia_root):
        """plugin_config with autoCapture=true → ok (already v2.0)."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["plugin_config"] = {
            "autoCapture": True,
            "captureFrequency": "significant",
            "captureMinTurns": 2,
        }
        (palaia_root / "config.json").write_text(json.dumps(config))

        from palaia.doctor import _check_plugin_defaults_upgrade

        result = _check_plugin_defaults_upgrade(palaia_root)
        assert result["status"] == "ok"

    def test_custom_values_not_flagged(self, palaia_root):
        """Custom autoCapture=true with custom frequency → ok (not v1.x default)."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["plugin_config"] = {
            "autoCapture": True,
            "captureFrequency": "every",
            "captureMinTurns": 1,
        }
        (palaia_root / "config.json").write_text(json.dumps(config))

        from palaia.doctor import _check_plugin_defaults_upgrade

        result = _check_plugin_defaults_upgrade(palaia_root)
        assert result["status"] == "ok"

    def test_none_root_is_ok(self):
        """None root → ok (not initialized)."""
        from palaia.doctor import _check_plugin_defaults_upgrade

        result = _check_plugin_defaults_upgrade(None)
        assert result["status"] == "ok"

    def test_memoryInject_false_detected(self, palaia_root):
        """memoryInject=false → warn (v1.x default)."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["plugin_config"] = {"memoryInject": False}
        (palaia_root / "config.json").write_text(json.dumps(config))

        from palaia.doctor import _check_plugin_defaults_upgrade

        result = _check_plugin_defaults_upgrade(palaia_root)
        assert result["status"] == "warn"
        assert "memoryInject" in result["message"]

    def test_maxInjectedChars_4000_detected(self, palaia_root):
        """maxInjectedChars=4000 → warn (v1.x default)."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["plugin_config"] = {"maxInjectedChars": 4000}
        (palaia_root / "config.json").write_text(json.dumps(config))

        from palaia.doctor import _check_plugin_defaults_upgrade

        result = _check_plugin_defaults_upgrade(palaia_root)
        assert result["status"] == "warn"
        assert "maxInjectedChars" in result["message"]

    def test_recallMode_list_detected(self, palaia_root):
        """recallMode=list → warn (v1.x default)."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["plugin_config"] = {"recallMode": "list"}
        (palaia_root / "config.json").write_text(json.dumps(config))

        from palaia.doctor import _check_plugin_defaults_upgrade

        result = _check_plugin_defaults_upgrade(palaia_root)
        assert result["status"] == "warn"
        assert "recallMode" in result["message"]

    def test_custom_maxInjectedChars_not_flagged(self, palaia_root):
        """maxInjectedChars=6000 (custom) → not flagged."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["plugin_config"] = {"maxInjectedChars": 6000}
        (palaia_root / "config.json").write_text(json.dumps(config))

        from palaia.doctor import _check_plugin_defaults_upgrade

        result = _check_plugin_defaults_upgrade(palaia_root)
        assert result["status"] == "ok"

    def test_all_v1_defaults_detected(self, palaia_root):
        """All v1.x defaults together → all flagged."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["plugin_config"] = {
            "autoCapture": False,
            "memoryInject": False,
            "maxInjectedChars": 4000,
            "recallMode": "list",
        }
        (palaia_root / "config.json").write_text(json.dumps(config))

        from palaia.doctor import _check_plugin_defaults_upgrade

        result = _check_plugin_defaults_upgrade(palaia_root)
        assert result["status"] == "warn"
        assert len(result["details"]["upgradeable"]) == 4


class TestPluginDefaultsUpgradeFix:
    """Test apply_fixes upgrades v1.x defaults correctly."""

    def test_fix_upgrades_autocapture(self, palaia_root):
        """--fix should upgrade autoCapture: false → true."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["plugin_config"] = {
            "autoCapture": False,
            "captureFrequency": "significant",
            "captureMinTurns": 2,
        }
        (palaia_root / "config.json").write_text(json.dumps(config))

        from palaia.doctor import _check_plugin_defaults_upgrade, apply_fixes

        results = [_check_plugin_defaults_upgrade(palaia_root)]
        actions = apply_fixes(palaia_root, results)

        # Verify fix was applied
        assert any("v2.0" in a for a in actions)

        # Verify config was updated
        updated = json.loads((palaia_root / "config.json").read_text())
        pc = updated["plugin_config"]
        assert pc["autoCapture"] is True
        # Other values preserved
        assert pc["captureFrequency"] == "significant"
        assert pc["captureMinTurns"] == 2

    def test_fix_preserves_custom_values(self, palaia_root):
        """--fix should NOT touch custom values the user explicitly set."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["plugin_config"] = {
            "autoCapture": True,  # already v2.0
            "captureFrequency": "every",  # custom
            "captureMinTurns": 1,  # custom
        }
        (palaia_root / "config.json").write_text(json.dumps(config))

        from palaia.doctor import _check_plugin_defaults_upgrade, apply_fixes

        results = [_check_plugin_defaults_upgrade(palaia_root)]
        actions = apply_fixes(palaia_root, results)

        # No upgrade actions should have been taken
        assert not any("v2.0" in a for a in actions)

        # Config unchanged
        updated = json.loads((palaia_root / "config.json").read_text())
        pc = updated["plugin_config"]
        assert pc["autoCapture"] is True
        assert pc["captureFrequency"] == "every"
        assert pc["captureMinTurns"] == 1

    def test_fix_only_upgrades_old_defaults(self, palaia_root):
        """Mixed config: autoCapture=false but custom captureMinTurns → only upgrade autoCapture."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["plugin_config"] = {
            "autoCapture": False,  # v1.x default → should upgrade
            "captureFrequency": "every",  # custom → should NOT touch
            "captureMinTurns": 10,  # custom → should NOT touch
        }
        (palaia_root / "config.json").write_text(json.dumps(config))

        from palaia.doctor import _check_plugin_defaults_upgrade, apply_fixes

        results = [_check_plugin_defaults_upgrade(palaia_root)]
        actions = apply_fixes(palaia_root, results)

        assert any("v2.0" in a for a in actions)

        updated = json.loads((palaia_root / "config.json").read_text())
        pc = updated["plugin_config"]
        assert pc["autoCapture"] is True  # upgraded
        assert pc["captureFrequency"] == "every"  # preserved
        assert pc["captureMinTurns"] == 10  # preserved

    def test_fix_upgrades_all_v1_defaults(self, palaia_root):
        """--fix should upgrade all v1.x defaults: memoryInject, maxInjectedChars, recallMode."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["plugin_config"] = {
            "autoCapture": False,
            "memoryInject": False,
            "maxInjectedChars": 4000,
            "recallMode": "list",
        }
        (palaia_root / "config.json").write_text(json.dumps(config))

        from palaia.doctor import _check_plugin_defaults_upgrade, apply_fixes

        results = [_check_plugin_defaults_upgrade(palaia_root)]
        actions = apply_fixes(palaia_root, results)

        assert any("v2.0" in a for a in actions)

        updated = json.loads((palaia_root / "config.json").read_text())
        pc = updated["plugin_config"]
        assert pc["autoCapture"] is True
        assert pc["memoryInject"] is True
        assert pc["maxInjectedChars"] == 8000
        assert pc["recallMode"] == "query"

    def test_fix_preserves_custom_maxInjectedChars(self, palaia_root):
        """--fix should NOT touch custom maxInjectedChars=6000."""
        config = json.loads((palaia_root / "config.json").read_text())
        config["plugin_config"] = {
            "autoCapture": False,
            "maxInjectedChars": 6000,  # custom → should NOT touch
        }
        (palaia_root / "config.json").write_text(json.dumps(config))

        from palaia.doctor import _check_plugin_defaults_upgrade, apply_fixes

        results = [_check_plugin_defaults_upgrade(palaia_root)]
        actions = apply_fixes(palaia_root, results)

        updated = json.loads((palaia_root / "config.json").read_text())
        pc = updated["plugin_config"]
        assert pc["autoCapture"] is True  # upgraded
        assert pc["maxInjectedChars"] == 6000  # preserved (custom)
