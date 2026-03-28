"""Tests for injection priority management (#121)."""

from __future__ import annotations

import pytest

from palaia.priorities import (
    ResolvedPriorities,
    block_entry,
    is_blocked,
    load_priorities,
    reset_priorities,
    resolve_priorities,
    save_priorities,
    set_priority_value,
    unblock_entry,
)


@pytest.fixture
def prio_root(tmp_path):
    root = tmp_path / ".palaia"
    root.mkdir()
    return root


# ── Load/Save ──────────────────────────────────────────────────────


class TestLoadSave:
    def test_load_missing_returns_empty(self, prio_root):
        prio = load_priorities(prio_root)
        assert prio["version"] == 1
        assert prio["blocked"] == []

    def test_save_and_load_roundtrip(self, prio_root):
        data = {"version": 1, "blocked": ["abc"], "agents": {}, "projects": {}}
        save_priorities(prio_root, data)
        loaded = load_priorities(prio_root)
        assert loaded["blocked"] == ["abc"]

    def test_load_corrupt_returns_empty(self, prio_root):
        (prio_root / "priorities.json").write_text("not json")
        prio = load_priorities(prio_root)
        assert prio["version"] == 1


# ── Resolve ────────────────────────────────────────────────────────


class TestResolve:
    def test_resolve_empty(self):
        prio = {"version": 1, "blocked": [], "agents": {}, "projects": {}}
        resolved = resolve_priorities(prio)
        assert resolved.blocked == set()
        assert resolved.recall_type_weight == {"process": 1.5, "task": 1.2, "memory": 1.0}

    def test_resolve_global_overrides(self):
        prio = {
            "version": 1,
            "blocked": ["entry-1"],
            "recallMinScore": 0.8,
            "maxInjectedChars": 3000,
            "tier": "warm",
        }
        resolved = resolve_priorities(prio)
        assert "entry-1" in resolved.blocked
        assert resolved.recall_min_score == 0.8
        assert resolved.max_injected_chars == 3000
        assert resolved.tier == "warm"

    def test_resolve_agent_overrides(self):
        prio = {
            "version": 1,
            "blocked": ["global-1"],
            "recallMinScore": 0.5,
            "agents": {
                "orchestrator": {
                    "blocked": ["agent-1"],
                    "recallMinScore": 0.9,
                    "recallTypeWeight": {"process": 0.5},
                }
            },
        }
        resolved = resolve_priorities(prio, agent="orchestrator")
        assert resolved.blocked == {"global-1", "agent-1"}
        assert resolved.recall_min_score == 0.9  # Agent overrides global
        assert resolved.recall_type_weight["process"] == 0.5  # Agent override
        assert resolved.recall_type_weight["task"] == 1.2  # Default preserved

    def test_resolve_project_overrides(self):
        prio = {
            "version": 1,
            "blocked": [],
            "projects": {
                "alpha": {
                    "blocked": ["proj-1"],
                    "recallTypeWeight": {"task": 2.5},
                }
            },
        }
        resolved = resolve_priorities(prio, project="alpha")
        assert "proj-1" in resolved.blocked
        assert resolved.recall_type_weight["task"] == 2.5

    def test_resolve_agent_and_project(self):
        prio = {
            "version": 1,
            "blocked": ["g1"],
            "agents": {"bot": {"blocked": ["a1"], "recallMinScore": 0.8}},
            "projects": {"proj": {"blocked": ["p1"], "recallTypeWeight": {"memory": 0.5}}},
        }
        resolved = resolve_priorities(prio, agent="bot", project="proj")
        assert resolved.blocked == {"g1", "a1", "p1"}
        assert resolved.recall_min_score == 0.8
        assert resolved.recall_type_weight["memory"] == 0.5

    def test_resolve_unknown_agent_uses_global(self):
        prio = {
            "version": 1,
            "blocked": ["g1"],
            "recallMinScore": 0.6,
            "agents": {"other": {"recallMinScore": 0.9}},
        }
        resolved = resolve_priorities(prio, agent="unknown")
        assert resolved.recall_min_score == 0.6  # Global, not "other"
        assert resolved.blocked == {"g1"}


# ── is_blocked ─────────────────────────────────────────────────────


class TestIsBlocked:
    def test_exact_match(self):
        assert is_blocked("abc-123", {"abc-123"})

    def test_prefix_match(self):
        assert is_blocked("abc-123-456-789", {"abc-123-"})

    def test_short_prefix_ignored(self):
        """Prefixes shorter than 8 chars are ignored to prevent accidental blocks."""
        assert not is_blocked("abc-123-456", {"abc"})

    def test_not_blocked(self):
        assert not is_blocked("xyz-999", {"abc-123"})


# ── Block/Unblock ──────────────────────────────────────────────────


class TestBlockUnblock:
    def test_block_global(self, prio_root):
        block_entry(prio_root, "entry-1")
        prio = load_priorities(prio_root)
        assert "entry-1" in prio["blocked"]

    def test_block_agent(self, prio_root):
        block_entry(prio_root, "entry-2", agent="bot")
        prio = load_priorities(prio_root)
        assert "entry-2" in prio["agents"]["bot"]["blocked"]
        assert "entry-2" not in prio.get("blocked", [])

    def test_block_project(self, prio_root):
        block_entry(prio_root, "entry-3", project="proj")
        prio = load_priorities(prio_root)
        assert "entry-3" in prio["projects"]["proj"]["blocked"]

    def test_block_idempotent(self, prio_root):
        block_entry(prio_root, "entry-1")
        block_entry(prio_root, "entry-1")
        prio = load_priorities(prio_root)
        assert prio["blocked"].count("entry-1") == 1

    def test_unblock(self, prio_root):
        block_entry(prio_root, "entry-1")
        unblock_entry(prio_root, "entry-1")
        prio = load_priorities(prio_root)
        assert "entry-1" not in prio["blocked"]


# ── Set Priority ───────────────────────────────────────────────────


class TestSetPriority:
    def test_set_min_score(self, prio_root):
        set_priority_value(prio_root, "recallMinScore", 0.85)
        prio = load_priorities(prio_root)
        assert prio["recallMinScore"] == 0.85

    def test_set_max_chars(self, prio_root):
        set_priority_value(prio_root, "maxInjectedChars", 2000)
        prio = load_priorities(prio_root)
        assert prio["maxInjectedChars"] == 2000

    def test_set_tier(self, prio_root):
        set_priority_value(prio_root, "tier", "all")
        prio = load_priorities(prio_root)
        assert prio["tier"] == "all"

    def test_set_invalid_tier_raises(self, prio_root):
        with pytest.raises(ValueError, match="Invalid tier"):
            set_priority_value(prio_root, "tier", "invalid")

    def test_set_type_weight(self, prio_root):
        set_priority_value(prio_root, "typeWeight.process", 2.0)
        prio = load_priorities(prio_root)
        assert prio["recallTypeWeight"]["process"] == 2.0

    def test_set_for_agent(self, prio_root):
        set_priority_value(prio_root, "recallMinScore", 0.9, agent="bot")
        prio = load_priorities(prio_root)
        assert prio["agents"]["bot"]["recallMinScore"] == 0.9

    def test_set_unknown_key_raises(self, prio_root):
        with pytest.raises(ValueError, match="Unknown"):
            set_priority_value(prio_root, "nonexistent", "value")


# ── Reset ──────────────────────────────────────────────────────────


class TestReset:
    def test_reset_all(self, prio_root):
        block_entry(prio_root, "entry-1")
        reset_priorities(prio_root)
        assert not (prio_root / "priorities.json").exists()

    def test_reset_agent(self, prio_root):
        block_entry(prio_root, "g1")
        block_entry(prio_root, "a1", agent="bot")
        reset_priorities(prio_root, agent="bot")
        prio = load_priorities(prio_root)
        assert "bot" not in prio.get("agents", {})
        assert "g1" in prio["blocked"]  # Global untouched


# ── ResolvedPriorities ─────────────────────────────────────────────


class TestResolvedPriorities:
    def test_to_dict(self):
        rp = ResolvedPriorities(
            blocked={"a", "b"},
            recall_type_weight={"process": 1.5, "task": 1.0, "memory": 1.0},
            recall_min_score=0.8,
            max_injected_chars=3000,
            tier="warm",
        )
        d = rp.to_dict()
        assert d["blocked"] == ["a", "b"]
        assert d["recallMinScore"] == 0.8
        assert d["tier"] == "warm"
