"""Adaptive Nudging with Graduation System (Issue #68).

Palaia nudges agents toward better practices (e.g. using --type, --tags)
via CLI output hints. But nudges should educate agents toward independence,
not prop them up indefinitely. Once an agent demonstrates consistent good
behavior (3 consecutive successes), the nudge "graduates" and stops.

Regression detection: if a graduated agent falls back to bad habits,
the nudge is re-activated.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default patterns and their nudge messages
NUDGE_PATTERNS: dict[str, dict[str, str]] = {
    "write_without_type": {
        "message": (
            "Tip: Use --type (memory|process|task) for better recall. "
            "Save this hint to your memory so you won't need it next time."
        ),
    },
    "write_without_tags": {
        "message": (
            "Tip: Tags improve discoverability. Use --tags for categorization. "
            "Save this hint to your memory so you won't need it next time."
        ),
    },
    "write_without_project": {
        "message": (
            "Tip: In multi-project setups, --project helps with attribution. "
            "Save this hint to your memory so you won't need it next time."
        ),
    },
    "query_without_type_filter": {
        "message": (
            "Tip: Use --type (memory|process|task) to focus search results. "
            "Save this hint to your memory so you won't need it next time."
        ),
    },
    "satisfaction_check": {
        "message": (
            "Your user has been using Palaia for a while now. "
            "Ask them casually if they're happy with the memory system. "
            "If there are issues, suggest `palaia doctor`."
        ),
    },
    "transparency_preference": {
        "message": (
            "Your user has been seeing memory Footnotes and capture confirmations "
            "for several days now. Ask them once: 'Would you like to keep seeing "
            "memory source references and capture confirmations, or should I hide them? "
            "You can change this anytime.' "
            "Based on their answer: `palaia config set showMemorySources true/false` "
            "and `palaia config set showCaptureConfirm true/false`"
        ),
    },
    "curate_reminder": {
        "message": (
            "Tip: You have {count} entries, some dating back {days} days. "
            "Consider running `palaia curate analyze` to review, deduplicate, "
            "and clean up your knowledge base."
        ),
        "cooldown": 604800,  # 7 days
    },
    "priorities_hint": {
        "message": (
            "Tip: In multi-agent setups, use `palaia priorities` to control "
            "which memories each agent sees. This prevents cross-agent injection noise."
        ),
        "cooldown": 86400,  # 24 hours
    },
    "migration_success": {
        "message": (
            "[palaia] Storage upgraded to SQLite. Your entries are now faster "
            "to search and more reliable. No action needed."
        ),
        "cooldown": float("inf"),  # one-shot
        "one_shot": True,
    },
    "scope_hint": {
        "message": (
            "[palaia] Tip: Use --scope team for knowledge all agents should share, "
            "or --scope private for agent-specific notes."
        ),
        "cooldown": 259200,  # 3 days
    },
    "embed_provider_hint": {
        "message": (
            "[palaia] Semantic search disabled — using keyword matching only. "
            "Run 'palaia detect' to auto-configure embeddings for better recall."
        ),
        "cooldown": 604800,  # 7 days
    },
    "prune_reminder": {
        "message": (
            "[palaia] Agent '{agent}' has {count} auto-captured entries. "
            "After accepting a work package, clean up with: "
            "palaia prune --agent {agent} --tags auto-capture --protect-type process"
        ),
        "cooldown": 86400,  # 1x per day
    },
    "isolation_scope_mismatch": {
        "message": (
            "[palaia] This agent has scopeVisibility: {visibility} but wrote "
            "with --scope {scope}. This entry is invisible to you but visible to "
            "other agents. Use --scope private for isolated agents."
        ),
        "cooldown": 3600,
    },
}

# Graduation threshold: consecutive successes required
GRADUATION_THRESHOLD = 3

# Frequency limit: max 1 nudge per pattern per hour (seconds)
NUDGE_COOLDOWN_SECONDS = 3600

# Per-invocation throttle: only the first nudge fires per CLI call.
# In production each CLI call is a fresh process so this starts at 0.
# Keyed by str(root) so tests with different tmp dirs don't interfere.
_nudges_this_invocation: dict[str, int] = {}
MAX_NUDGES_PER_INVOCATION = 1


def reset_nudge_throttle(root_key: str | None = None) -> None:
    """Reset the per-invocation nudge counter.

    Called at CLI entry point (each palaia command is a fresh invocation).
    In tests, call with root_key=str(palaia_root) to reset for a specific root.
    """
    if root_key is None:
        _nudges_this_invocation.clear()
    else:
        _nudges_this_invocation.pop(root_key, None)


class NudgeTracker:
    """Tracks nudge state per agent with graduation and regression support.

    Storage: .palaia/nudge-state.json
    Schema per pattern_id:
        {
            "nudge_count": int,
            "success_count": int,
            "consecutive_success": int,
            "graduated": bool,
            "last_nudge": iso_timestamp | null,
            "last_regression": iso_timestamp | null
        }
    """

    def __init__(self, palaia_root: Path):
        self.root = palaia_root
        self._root_key = str(palaia_root)
        self.state_file = palaia_root / "nudge-state.json"
        self._state: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        """Load nudge state from disk."""
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save(self) -> None:
        """Persist nudge state to disk."""
        try:
            self.state_file.write_text(json.dumps(self._state, indent=2))
        except OSError:
            pass

    def _agent_key(self, agent: str) -> str:
        """Get the key for agent-level state."""
        return agent or "default"

    def _get_pattern_state(self, pattern_id: str, agent: str) -> dict[str, Any]:
        """Get or create state for a specific pattern+agent combo."""
        agent_key = self._agent_key(agent)
        agent_state = self._state.setdefault(agent_key, {})
        if pattern_id not in agent_state:
            agent_state[pattern_id] = {
                "nudge_count": 0,
                "success_count": 0,
                "consecutive_success": 0,
                "graduated": False,
                "last_nudge": None,
                "last_regression": None,
            }
        return agent_state[pattern_id]

    def should_nudge(self, pattern_id: str, agent: str) -> bool:
        """Check if a nudge should be shown for this pattern.

        Returns True if:
        - Per-invocation limit not reached (max 1 nudge per CLI call)
        - Pattern is not graduated
        - For one-shot nudges: has never been shown before
        - Cooldown period has elapsed (max 1 nudge per pattern per hour)
        """
        if _nudges_this_invocation.get(self._root_key, 0) >= MAX_NUDGES_PER_INVOCATION:
            return False

        state = self._get_pattern_state(pattern_id, agent)

        if state["graduated"]:
            return False

        # One-shot nudges: only fire once ever
        pattern = NUDGE_PATTERNS.get(pattern_id, {})
        if pattern.get("one_shot") and state.get("nudge_count", 0) > 0:
            return False

        # Frequency limit
        last_nudge = state.get("last_nudge")
        if last_nudge:
            try:
                from datetime import datetime, timezone

                last_time = datetime.fromisoformat(last_nudge)
                if last_time.tzinfo is None:
                    last_time = last_time.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                elapsed = (now - last_time).total_seconds()
                cooldown = pattern.get("cooldown", NUDGE_COOLDOWN_SECONDS)
                if elapsed < cooldown:
                    return False
            except (ValueError, TypeError):
                pass  # Invalid timestamp, allow nudge

        return True

    def record_nudge(self, pattern_id: str, agent: str) -> None:
        """Record that a nudge was shown."""
        from datetime import datetime, timezone

        state = self._get_pattern_state(pattern_id, agent)
        state["nudge_count"] = state.get("nudge_count", 0) + 1
        state["last_nudge"] = datetime.now(timezone.utc).isoformat()
        _nudges_this_invocation[self._root_key] = _nudges_this_invocation.get(self._root_key, 0) + 1
        self._save()

    def record_success(self, pattern_id: str, agent: str) -> None:
        """Record that the agent used the recommended feature.

        After GRADUATION_THRESHOLD consecutive successes, the pattern graduates.
        """
        state = self._get_pattern_state(pattern_id, agent)
        state["success_count"] = state.get("success_count", 0) + 1
        state["consecutive_success"] = state.get("consecutive_success", 0) + 1

        if state["consecutive_success"] >= GRADUATION_THRESHOLD:
            state["graduated"] = True

        self._save()

    def record_failure(self, pattern_id: str, agent: str) -> None:
        """Record that the agent did NOT use the recommended feature.

        Resets consecutive success counter. If graduated, triggers regression.
        """
        from datetime import datetime, timezone

        state = self._get_pattern_state(pattern_id, agent)
        state["consecutive_success"] = 0

        if state["graduated"]:
            state["graduated"] = False
            state["last_regression"] = datetime.now(timezone.utc).isoformat()

        self._save()

    def get_state(self, pattern_id: str, agent: str) -> dict[str, Any]:
        """Get the current state for a pattern+agent (read-only copy)."""
        return dict(self._get_pattern_state(pattern_id, agent))

    def get_all_states(self, agent: str) -> dict[str, dict[str, Any]]:
        """Get all pattern states for an agent."""
        agent_key = self._agent_key(agent)
        return dict(self._state.get(agent_key, {}))

    def get_nudge_message(self, pattern_id: str) -> str | None:
        """Get the nudge message for a pattern."""
        pattern = NUDGE_PATTERNS.get(pattern_id)
        if pattern:
            return pattern["message"]
        return None
