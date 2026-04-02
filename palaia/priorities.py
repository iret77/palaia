"""Injection priority management for multi-agent setups (#121).

Provides per-agent and per-project overrides for recall behavior:
blocked entries, type weights, min scores, char limits, tier selection.

Config lives at ``.palaia/priorities.json`` with layered resolution:
plugin defaults → global overrides → agent overrides → project overrides.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default recall type weights (same as plugin defaults).
DEFAULT_TYPE_WEIGHTS = {"process": 1.5, "task": 1.2, "memory": 1.0}
DEFAULT_MIN_SCORE = 0.0  # Don't filter by default (plugin may override)
DEFAULT_MAX_CHARS = 4000
DEFAULT_TIER = "hot"


@dataclass
class ResolvedPriorities:
    """Flat, resolved priority config after merging all layers."""

    blocked: set[str] = field(default_factory=set)
    recall_type_weight: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_TYPE_WEIGHTS))
    recall_min_score: float = DEFAULT_MIN_SCORE
    max_injected_chars: int = DEFAULT_MAX_CHARS
    tier: str = DEFAULT_TIER
    scope_visibility: list[str] | None = None  # Issue #145: agent isolation
    capture_scope: str | None = None  # Issue #147: per-agent write scope

    def to_dict(self) -> dict:
        d = {
            "blocked": sorted(self.blocked),
            "recallTypeWeight": self.recall_type_weight,
            "recallMinScore": self.recall_min_score,
            "maxInjectedChars": self.max_injected_chars,
            "tier": self.tier,
        }
        if self.scope_visibility is not None:
            d["scopeVisibility"] = self.scope_visibility
        if self.capture_scope is not None:
            d["captureScope"] = self.capture_scope
        return d


def _empty_priorities() -> dict:
    return {"version": 1, "blocked": [], "agents": {}, "projects": {}}


def load_priorities(root: Path) -> dict:
    """Load priorities.json. Returns empty structure if not found."""
    path = root / "priorities.json"
    if not path.exists():
        return _empty_priorities()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _empty_priorities()
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load priorities.json: %s", e)
        return _empty_priorities()


def save_priorities(root: Path, priorities: dict) -> None:
    """Write priorities.json atomically."""
    path = root / "priorities.json"
    tmp = path.with_suffix(".tmp")
    priorities.setdefault("version", 1)
    with open(tmp, "w") as f:
        json.dump(priorities, f, indent=2)
        f.flush()
    tmp.rename(path)


def resolve_priorities(
    priorities: dict,
    agent: str | None = None,
    project: str | None = None,
) -> ResolvedPriorities:
    """Merge priority layers into a flat resolved config.

    Resolution order: global → agent → project.
    ``blocked`` is a union across all layers.
    Type weights are merged (partial overrides fill from previous layer).
    Scalar values are overridden (last layer wins).
    """
    resolved = ResolvedPriorities()

    # Layer 1: Global
    resolved.blocked = set(priorities.get("blocked", []))
    if "recallTypeWeight" in priorities:
        resolved.recall_type_weight = {**resolved.recall_type_weight, **priorities["recallTypeWeight"]}
    if "recallMinScore" in priorities:
        resolved.recall_min_score = float(priorities["recallMinScore"])
    if "maxInjectedChars" in priorities:
        resolved.max_injected_chars = int(priorities["maxInjectedChars"])
    if "tier" in priorities:
        resolved.tier = priorities["tier"]

    # Layer 2: Agent override
    if agent:
        agent_cfg = priorities.get("agents", {}).get(agent, {})
        resolved.blocked |= set(agent_cfg.get("blocked", []))
        if "recallTypeWeight" in agent_cfg:
            resolved.recall_type_weight = {**resolved.recall_type_weight, **agent_cfg["recallTypeWeight"]}
        if "recallMinScore" in agent_cfg:
            resolved.recall_min_score = float(agent_cfg["recallMinScore"])
        if "maxInjectedChars" in agent_cfg:
            resolved.max_injected_chars = int(agent_cfg["maxInjectedChars"])
        if "tier" in agent_cfg:
            resolved.tier = agent_cfg["tier"]
        if "scopeVisibility" in agent_cfg:
            resolved.scope_visibility = list(agent_cfg["scopeVisibility"])
        if "captureScope" in agent_cfg:
            resolved.capture_scope = str(agent_cfg["captureScope"])

    # Layer 3: Project override
    if project:
        proj_cfg = priorities.get("projects", {}).get(project, {})
        resolved.blocked |= set(proj_cfg.get("blocked", []))
        if "recallTypeWeight" in proj_cfg:
            resolved.recall_type_weight = {**resolved.recall_type_weight, **proj_cfg["recallTypeWeight"]}

    return resolved


def is_blocked(entry_id: str, blocked: set[str]) -> bool:
    """Check if an entry ID is blocked (exact or prefix match)."""
    if entry_id in blocked:
        return True
    return any(entry_id.startswith(b) for b in blocked if len(b) >= 8)


def block_entry(
    root: Path, entry_id: str, *, agent: str | None = None, project: str | None = None
) -> dict:
    """Add an entry ID to the blocked list at the appropriate level."""
    prio = load_priorities(root)
    target = _get_level(prio, agent=agent, project=project)
    blocked = target.setdefault("blocked", [])
    if entry_id not in blocked:
        blocked.append(entry_id)
    save_priorities(root, prio)
    return prio


def unblock_entry(
    root: Path, entry_id: str, *, agent: str | None = None, project: str | None = None
) -> dict:
    """Remove an entry ID from the blocked list."""
    prio = load_priorities(root)
    target = _get_level(prio, agent=agent, project=project)
    blocked = target.get("blocked", [])
    target["blocked"] = [b for b in blocked if b != entry_id]
    save_priorities(root, prio)
    return prio


def set_priority_value(
    root: Path, key: str, value: Any, *, agent: str | None = None, project: str | None = None
) -> dict:
    """Set a priority config value at the appropriate level.

    Supports dotted keys for type weights: ``typeWeight.process``.
    """
    prio = load_priorities(root)
    target = _get_level(prio, agent=agent, project=project)

    if key.startswith("typeWeight."):
        type_name = key.split(".", 1)[1]
        weights = target.setdefault("recallTypeWeight", {})
        weights[type_name] = float(value)
    elif key == "recallMinScore":
        target["recallMinScore"] = float(value)
    elif key == "maxInjectedChars":
        target["maxInjectedChars"] = int(value)
    elif key == "tier":
        if value not in ("hot", "warm", "all"):
            raise ValueError(f"Invalid tier: {value}. Valid: hot, warm, all")
        target["tier"] = value
    elif key == "captureScope":
        from palaia.scope import validate_scope
        value = str(value).strip().lower()
        if not validate_scope(value):
            raise ValueError(f"Invalid captureScope: {value}. Valid: private, team, public, shared:<name>")
        target["captureScope"] = value
    elif key == "scopeVisibility":
        if isinstance(value, str):
            value = [s.strip() for s in value.split(",")]
        if not isinstance(value, list):
            raise ValueError("scopeVisibility must be a list of scopes or comma-separated string")
        valid = {"private", "team", "public", "shared"}
        for s in value:
            base = s.split(":")[0] if ":" in s else s
            if base not in valid:
                raise ValueError(f"Invalid scope in scopeVisibility: {s}. Valid: private, team, public, shared:<name>")
        target["scopeVisibility"] = value
    else:
        raise ValueError(f"Unknown priority key: {key}")

    save_priorities(root, prio)
    return prio


def reset_priorities(
    root: Path, *, agent: str | None = None, project: str | None = None
) -> dict:
    """Reset priorities at the given level."""
    if agent is None and project is None:
        # Reset everything
        path = root / "priorities.json"
        if path.exists():
            path.unlink()
        return _empty_priorities()

    prio = load_priorities(root)
    if agent:
        prio.get("agents", {}).pop(agent, None)
    if project:
        prio.get("projects", {}).pop(project, None)
    save_priorities(root, prio)
    return prio


def _get_level(prio: dict, *, agent: str | None, project: str | None) -> dict:
    """Get the dict for the appropriate config level."""
    if agent:
        agents = prio.setdefault("agents", {})
        return agents.setdefault(agent, {})
    if project:
        projects = prio.setdefault("projects", {})
        return projects.setdefault(project, {})
    return prio
