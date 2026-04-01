"""Tests for isolation workflow nudges (#148)."""

import json

from palaia.nudge import NudgeTracker, reset_nudge_throttle


def _make_root(tmp_path, config_extra=None):
    """Create a minimal palaia root."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for d in ("hot", "warm", "cold", "wal", "index"):
        (root / d).mkdir()
    config = {"agent": "test"}
    if config_extra:
        config.update(config_extra)
    (root / "config.json").write_text(json.dumps(config))
    return root


class TestPruneReminderNudge:
    def test_pattern_exists(self):
        """prune_reminder pattern is registered."""
        from palaia.nudge import NUDGE_PATTERNS
        assert "prune_reminder" in NUDGE_PATTERNS
        assert "{agent}" in NUDGE_PATTERNS["prune_reminder"]["message"]
        assert "{count}" in NUDGE_PATTERNS["prune_reminder"]["message"]

    def test_should_nudge_initially(self, tmp_path):
        """prune_reminder can fire for new agents."""
        root = _make_root(tmp_path)
        reset_nudge_throttle(str(root))
        tracker = NudgeTracker(root)
        assert tracker.should_nudge("prune_reminder", "orchestrator")

    def test_graduation_after_pruning(self, tmp_path):
        """3 consecutive prune runs graduate the nudge."""
        root = _make_root(tmp_path)
        tracker = NudgeTracker(root)
        for _ in range(3):
            tracker.record_success("prune_reminder", "orchestrator")
        state = tracker.get_state("prune_reminder", "orchestrator")
        assert state["graduated"] is True

    def test_message_format(self, tmp_path):
        """prune_reminder message supports {agent} and {count} placeholders."""
        root = _make_root(tmp_path)
        tracker = NudgeTracker(root)
        msg = tracker.get_nudge_message("prune_reminder")
        assert msg is not None
        formatted = msg.format(agent="worker", count=15)
        assert "worker" in formatted
        assert "15" in formatted
        assert "palaia prune" in formatted


class TestIsolationScopeMismatchNudge:
    def test_pattern_exists(self):
        """isolation_scope_mismatch pattern is registered."""
        from palaia.nudge import NUDGE_PATTERNS
        assert "isolation_scope_mismatch" in NUDGE_PATTERNS
        assert "{visibility}" in NUDGE_PATTERNS["isolation_scope_mismatch"]["message"]
        assert "{scope}" in NUDGE_PATTERNS["isolation_scope_mismatch"]["message"]

    def test_should_nudge_initially(self, tmp_path):
        """isolation_scope_mismatch can fire for new agents."""
        root = _make_root(tmp_path)
        reset_nudge_throttle(str(root))
        tracker = NudgeTracker(root)
        assert tracker.should_nudge("isolation_scope_mismatch", "worker")

    def test_graduation_stops_nudge(self, tmp_path):
        """3 correct-scope writes graduate the nudge."""
        root = _make_root(tmp_path)
        tracker = NudgeTracker(root)
        for _ in range(3):
            tracker.record_success("isolation_scope_mismatch", "worker")
        state = tracker.get_state("isolation_scope_mismatch", "worker")
        assert state["graduated"] is True

    def test_regression_reactivates(self, tmp_path):
        """Wrong-scope write after graduation triggers regression."""
        root = _make_root(tmp_path)
        reset_nudge_throttle(str(root))
        tracker = NudgeTracker(root)
        for _ in range(3):
            tracker.record_success("isolation_scope_mismatch", "worker")
        assert tracker.get_state("isolation_scope_mismatch", "worker")["graduated"] is True

        tracker.record_failure("isolation_scope_mismatch", "worker")
        state = tracker.get_state("isolation_scope_mismatch", "worker")
        assert state["graduated"] is False
        assert state.get("last_regression") is not None

    def test_message_format(self, tmp_path):
        """Message supports {visibility} and {scope} placeholders."""
        root = _make_root(tmp_path)
        tracker = NudgeTracker(root)
        msg = tracker.get_nudge_message("isolation_scope_mismatch")
        assert msg is not None
        formatted = msg.format(visibility="private,team", scope="public")
        assert "private,team" in formatted
        assert "public" in formatted


class TestWriteServiceScopeMismatch:
    """Integration test: write service triggers isolation_scope_mismatch."""

    def test_mismatch_detected(self, tmp_path):
        """Write with scope outside visibility triggers nudge."""
        root = _make_root(tmp_path)
        reset_nudge_throttle(str(root))

        # Graduate other nudges so they don't consume the per-invocation slot
        tracker = NudgeTracker(root)
        for pattern in ("write_without_type", "write_without_tags", "scope_hint"):
            for _ in range(3):
                tracker.record_success(pattern, "worker")

        # Set up priorities with scopeVisibility
        (root / "priorities.json").write_text(json.dumps({
            "version": 1,
            "blocked": [],
            "agents": {
                "worker": {"scopeVisibility": ["private"]},
            },
        }))

        from palaia.services.write import write_entry

        # Reset throttle again — the graduation checks may have triggered one
        reset_nudge_throttle(str(root))

        result = write_entry(
            root,
            body="Some note",
            scope="team",
            agent="worker",
            tags=["auto-capture"],
            entry_type="memory",
        )
        assert "error" not in result
        nudges = result.get("nudge", [])
        # Nudge should fire because "team" is outside ["private"]
        assert any("scopeVisibility" in n for n in nudges), f"Expected scope mismatch nudge, got: {nudges}"

    def test_correct_scope_no_nudge(self, tmp_path):
        """Write with scope inside visibility records success."""
        root = _make_root(tmp_path)
        reset_nudge_throttle(str(root))

        (root / "priorities.json").write_text(json.dumps({
            "version": 1,
            "blocked": [],
            "agents": {
                "worker": {"scopeVisibility": ["private"]},
            },
        }))

        from palaia.services.write import write_entry

        result = write_entry(
            root,
            body="Private note",
            scope="private",
            agent="worker",
            tags=["auto-capture"],
        )
        assert "error" not in result
        nudges = result.get("nudge", [])
        # No mismatch nudge for correct scope
        assert not any("scopeVisibility" in n for n in nudges), f"Unexpected nudge: {nudges}"
