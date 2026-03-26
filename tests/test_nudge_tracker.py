"""Tests for Adaptive Nudging / Graduation System (Issue #68)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from palaia.nudge import GRADUATION_THRESHOLD, NudgeTracker, reset_nudge_throttle


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
        "agent": "TestAgent",
        "store_version": "1.9.0",
    }
    (root / "config.json").write_text(json.dumps(config))
    reset_nudge_throttle()  # Each test starts with a fresh throttle
    return root


class TestNudgeTrackerBasic:
    """Basic should_nudge / record_nudge / record_success / record_failure."""

    def test_initial_should_nudge(self, palaia_root):
        tracker = NudgeTracker(palaia_root)
        assert tracker.should_nudge("write_without_type", "TestAgent") is True

    def test_nudge_after_record(self, palaia_root):
        tracker = NudgeTracker(palaia_root)
        tracker.record_nudge("write_without_type", "TestAgent")
        # Immediately after nudge, cooldown should prevent re-nudge
        assert tracker.should_nudge("write_without_type", "TestAgent") is False

    def test_nudge_count_increments(self, palaia_root):
        tracker = NudgeTracker(palaia_root)
        tracker.record_nudge("write_without_type", "TestAgent")
        state = tracker.get_state("write_without_type", "TestAgent")
        assert state["nudge_count"] == 1
        # Manually reset cooldown for test
        agent_state = tracker._state["TestAgent"]["write_without_type"]
        agent_state["last_nudge"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        tracker._save()
        tracker.record_nudge("write_without_type", "TestAgent")
        state = tracker.get_state("write_without_type", "TestAgent")
        assert state["nudge_count"] == 2


class TestGraduation:
    """Graduation after consecutive successes."""

    def test_graduation_after_threshold(self, palaia_root):
        tracker = NudgeTracker(palaia_root)
        for _ in range(GRADUATION_THRESHOLD):
            tracker.record_success("write_without_type", "TestAgent")
        state = tracker.get_state("write_without_type", "TestAgent")
        assert state["graduated"] is True
        assert state["consecutive_success"] == GRADUATION_THRESHOLD

    def test_graduated_pattern_not_nudged(self, palaia_root):
        tracker = NudgeTracker(palaia_root)
        for _ in range(GRADUATION_THRESHOLD):
            tracker.record_success("write_without_type", "TestAgent")
        assert tracker.should_nudge("write_without_type", "TestAgent") is False

    def test_partial_success_not_graduated(self, palaia_root):
        tracker = NudgeTracker(palaia_root)
        for _ in range(GRADUATION_THRESHOLD - 1):
            tracker.record_success("write_without_type", "TestAgent")
        state = tracker.get_state("write_without_type", "TestAgent")
        assert state["graduated"] is False
        assert tracker.should_nudge("write_without_type", "TestAgent") is True

    def test_interrupted_consecutive_resets(self, palaia_root):
        tracker = NudgeTracker(palaia_root)
        tracker.record_success("write_without_type", "TestAgent")
        tracker.record_success("write_without_type", "TestAgent")
        tracker.record_failure("write_without_type", "TestAgent")
        state = tracker.get_state("write_without_type", "TestAgent")
        assert state["consecutive_success"] == 0
        assert state["success_count"] == 2
        assert state["graduated"] is False


class TestRegression:
    """Regression after graduation."""

    def test_regression_ungraduates(self, palaia_root):
        tracker = NudgeTracker(palaia_root)
        # Graduate first
        for _ in range(GRADUATION_THRESHOLD):
            tracker.record_success("write_without_type", "TestAgent")
        assert tracker.should_nudge("write_without_type", "TestAgent") is False

        # Regress
        tracker.record_failure("write_without_type", "TestAgent")
        state = tracker.get_state("write_without_type", "TestAgent")
        assert state["graduated"] is False
        assert state["last_regression"] is not None
        assert state["consecutive_success"] == 0

    def test_regression_allows_nudge_again(self, palaia_root):
        tracker = NudgeTracker(palaia_root)
        for _ in range(GRADUATION_THRESHOLD):
            tracker.record_success("write_without_type", "TestAgent")
        tracker.record_failure("write_without_type", "TestAgent")
        assert tracker.should_nudge("write_without_type", "TestAgent") is True

    def test_re_graduation_after_regression(self, palaia_root):
        tracker = NudgeTracker(palaia_root)
        # Graduate
        for _ in range(GRADUATION_THRESHOLD):
            tracker.record_success("write_without_type", "TestAgent")
        # Regress
        tracker.record_failure("write_without_type", "TestAgent")
        # Re-graduate
        for _ in range(GRADUATION_THRESHOLD):
            tracker.record_success("write_without_type", "TestAgent")
        state = tracker.get_state("write_without_type", "TestAgent")
        assert state["graduated"] is True


class TestFrequencyLimit:
    """Max 1 nudge per pattern per hour."""

    def test_cooldown_prevents_nudge(self, palaia_root):
        tracker = NudgeTracker(palaia_root)
        tracker.record_nudge("write_without_type", "TestAgent")
        assert tracker.should_nudge("write_without_type", "TestAgent") is False

    def test_cooldown_expires(self, palaia_root):
        tracker = NudgeTracker(palaia_root)
        tracker.record_nudge("write_without_type", "TestAgent")
        # Manually set last_nudge to >1 hour ago
        agent_state = tracker._state["TestAgent"]["write_without_type"]
        agent_state["last_nudge"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        tracker._save()
        # Simulate new CLI invocation (fresh process)
        reset_nudge_throttle()
        tracker2 = NudgeTracker(palaia_root)
        assert tracker2.should_nudge("write_without_type", "TestAgent") is True

    def test_different_patterns_independent_cooldown(self, palaia_root):
        tracker = NudgeTracker(palaia_root)
        tracker.record_nudge("write_without_type", "TestAgent")
        # Reset per-invocation throttle so we can test pattern independence
        reset_nudge_throttle()
        # Different pattern should still be nudgeable
        assert tracker.should_nudge("write_without_tags", "TestAgent") is True


class TestMultiAgent:
    """Nudge state is per-agent."""

    def test_separate_agents_separate_state(self, palaia_root):
        tracker = NudgeTracker(palaia_root)
        # Graduate agent A
        for _ in range(GRADUATION_THRESHOLD):
            tracker.record_success("write_without_type", "AgentA")
        assert tracker.should_nudge("write_without_type", "AgentA") is False
        # Agent B should still be nudgeable
        assert tracker.should_nudge("write_without_type", "AgentB") is True

    def test_agent_failure_doesnt_affect_other(self, palaia_root):
        tracker = NudgeTracker(palaia_root)
        tracker.record_failure("write_without_type", "AgentA")
        tracker.record_nudge("write_without_type", "AgentA")
        # Reset per-invocation throttle so we can test agent independence
        reset_nudge_throttle()
        # AgentB unaffected
        assert tracker.should_nudge("write_without_type", "AgentB") is True


class TestPersistence:
    """State survives across NudgeTracker instances."""

    def test_state_persists(self, palaia_root):
        tracker1 = NudgeTracker(palaia_root)
        tracker1.record_success("write_without_type", "TestAgent")
        tracker1.record_success("write_without_type", "TestAgent")

        # Reload from disk
        tracker2 = NudgeTracker(palaia_root)
        state = tracker2.get_state("write_without_type", "TestAgent")
        assert state["consecutive_success"] == 2
        assert state["success_count"] == 2

    def test_graduation_persists(self, palaia_root):
        tracker1 = NudgeTracker(palaia_root)
        for _ in range(GRADUATION_THRESHOLD):
            tracker1.record_success("write_without_type", "TestAgent")

        tracker2 = NudgeTracker(palaia_root)
        assert tracker2.should_nudge("write_without_type", "TestAgent") is False

    def test_corrupted_file_handled(self, palaia_root):
        (palaia_root / "nudge-state.json").write_text("not json!!!")
        tracker = NudgeTracker(palaia_root)
        # Should start fresh, not crash
        assert tracker.should_nudge("write_without_type", "TestAgent") is True


class TestNudgeMessages:
    """Test nudge message retrieval."""

    def test_known_pattern_message(self, palaia_root):
        tracker = NudgeTracker(palaia_root)
        msg = tracker.get_nudge_message("write_without_type")
        assert msg is not None
        assert "Save this hint" in msg

    def test_unknown_pattern_returns_none(self, palaia_root):
        tracker = NudgeTracker(palaia_root)
        msg = tracker.get_nudge_message("nonexistent_pattern")
        assert msg is None

    def test_all_patterns_have_messages(self, palaia_root):
        from palaia.nudge import NUDGE_PATTERNS

        tracker = NudgeTracker(palaia_root)
        for pattern_id in NUDGE_PATTERNS:
            msg = tracker.get_nudge_message(pattern_id)
            assert msg is not None, f"Pattern {pattern_id} has no message"
            assert len(msg) > 10, f"Pattern {pattern_id} has a suspiciously short message"

    def test_satisfaction_check_pattern(self, palaia_root):
        tracker = NudgeTracker(palaia_root)
        msg = tracker.get_nudge_message("satisfaction_check")
        assert msg is not None
        assert "happy with the memory system" in msg
        assert "doctor" in msg

    def test_transparency_preference_pattern(self, palaia_root):
        tracker = NudgeTracker(palaia_root)
        msg = tracker.get_nudge_message("transparency_preference")
        assert msg is not None
        assert "Footnotes" in msg
        assert "showMemorySources" in msg
        assert "showCaptureConfirm" in msg


class TestCLIIntegration:
    """Test nudge integration in CLI commands."""

    def _run_palaia(self, root, args, monkeypatch):
        from palaia.cli import main

        monkeypatch.setenv("PALAIA_HOME", str(root))
        monkeypatch.setattr("sys.argv", ["palaia"] + args)
        return main()

    def test_write_without_type_triggers_nudge_json(self, palaia_root, monkeypatch, capsys):
        self._run_palaia(palaia_root, ["write", "test entry", "--json"], monkeypatch)
        out = json.loads(capsys.readouterr().out)
        assert "nudge" in out
        assert len(out["nudge"]) > 0
        assert any("--type" in n for n in out["nudge"])

    def test_write_with_type_no_nudge(self, palaia_root, monkeypatch, capsys):
        self._run_palaia(palaia_root, ["write", "test entry", "--type", "memory", "--json"], monkeypatch)
        out = json.loads(capsys.readouterr().out)
        # No nudge for type, but might still have nudge for tags
        type_nudges = [n for n in out.get("nudge", []) if "--type" in n]
        assert len(type_nudges) == 0

    def test_write_with_tags_no_tags_nudge(self, palaia_root, monkeypatch, capsys):
        self._run_palaia(palaia_root, ["write", "test entry", "--tags", "test", "--json"], monkeypatch)
        out = json.loads(capsys.readouterr().out)
        tags_nudges = [n for n in out.get("nudge", []) if "--tags" in n]
        assert len(tags_nudges) == 0

    def test_graduation_stops_nudge_while_good(self, palaia_root, monkeypatch, capsys):
        """After graduation, writing WITH type should not produce type nudges."""
        # Graduate write_without_type by writing 3x with type
        for i in range(GRADUATION_THRESHOLD):
            self._run_palaia(
                palaia_root,
                ["write", f"entry {i}", "--type", "memory", "--json"],
                monkeypatch,
            )
            capsys.readouterr()  # clear output

        # Write WITH type again — should NOT nudge for type (still graduated)
        self._run_palaia(palaia_root, ["write", "test with type", "--type", "memory", "--json"], monkeypatch)
        out = json.loads(capsys.readouterr().out)
        type_nudges = [n for n in out.get("nudge", []) if "--type" in n]
        assert len(type_nudges) == 0

    def test_regression_re_enables_nudge(self, palaia_root, monkeypatch, capsys):
        """After graduation, writing WITHOUT type triggers regression and re-nudge."""
        # Graduate
        for i in range(GRADUATION_THRESHOLD):
            self._run_palaia(
                palaia_root,
                ["write", f"entry {i}", "--type", "memory", "--json"],
                monkeypatch,
            )
            capsys.readouterr()

        # Regress by writing without type
        self._run_palaia(palaia_root, ["write", "test no type", "--json"], monkeypatch)
        out = json.loads(capsys.readouterr().out)
        type_nudges = [n for n in out.get("nudge", []) if "--type" in n]
        assert len(type_nudges) > 0  # Regression re-enables nudge
