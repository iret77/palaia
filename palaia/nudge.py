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
from pathlib import Path
from typing import Any

# Default patterns and their nudge messages
NUDGE_PATTERNS: dict[str, dict[str, str]] = {
    "write_without_type": {
        "message": (
            "Tipp: Nutze --type (memory|process|task) für besseres Recall. "
            "Speichere diesen Hinweis in deinem Memory, damit du ihn beim nächsten Mal nicht mehr brauchst."
        ),
    },
    "write_without_tags": {
        "message": (
            "Tipp: Tags verbessern die Auffindbarkeit. Nutze --tags für Kategorisierung. "
            "Speichere diesen Hinweis in deinem Memory, damit du ihn beim nächsten Mal nicht mehr brauchst."
        ),
    },
    "write_without_project": {
        "message": (
            "Tipp: In Multi-Projekt-Setups hilft --project bei der Zuordnung. "
            "Speichere diesen Hinweis in deinem Memory, damit du ihn beim nächsten Mal nicht mehr brauchst."
        ),
    },
    "query_without_type_filter": {
        "message": (
            "Tipp: Nutze --type (memory|process|task) um Suchergebnisse zu fokussieren. "
            "Speichere diesen Hinweis in deinem Memory, damit du ihn beim nächsten Mal nicht mehr brauchst."
        ),
    },
    "satisfaction_check": {
        "message": (
            "Dein User nutzt Palaia jetzt seit einer Weile. "
            "Frag ihn dezent, ob er mit dem Memory-System zufrieden ist. "
            "Bei Problemen: schlage `palaia doctor` vor."
        ),
    },
    "transparency_preference": {
        "message": (
            "Dein User sieht jetzt seit einigen Tagen Memory-Footnotes und "
            "Capture-Bestätigungen. Frag ihn einmalig: 'Möchtest du die "
            "Memory-Quellenangaben und Speicher-Bestätigungen weiterhin sehen, "
            "oder soll ich sie ausblenden? Du kannst das jederzeit wieder ändern.' "
            "Je nach Antwort: `palaia config set showMemorySources true/false` "
            "und `palaia config set showCaptureConfirm true/false`"
        ),
    },
}

# Graduation threshold: consecutive successes required
GRADUATION_THRESHOLD = 3

# Frequency limit: max 1 nudge per pattern per hour (seconds)
NUDGE_COOLDOWN_SECONDS = 3600


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
        - Pattern is not graduated
        - Cooldown period has elapsed (max 1 nudge per pattern per hour)
        """
        state = self._get_pattern_state(pattern_id, agent)

        if state["graduated"]:
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
                if elapsed < NUDGE_COOLDOWN_SECONDS:
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
