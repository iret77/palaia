"""Tests for significance tagging and retrieval-hit decay (Issue #33)."""

from __future__ import annotations

import json

import pytest

from palaia.decay import (
    decay_score,
    recall_multiplier,
    significance_multiplier,
)
from palaia.entry import (
    VALID_SIGNIFICANCE,
    create_entry,
    parse_entry,
    serialize_entry,
    validate_significance,
)

# ---------- validate_significance ----------


class TestValidateSignificance:
    def test_none_returns_none(self):
        assert validate_significance(None) is None

    def test_empty_list_returns_none(self):
        assert validate_significance([]) is None

    def test_single_valid_tag(self):
        assert validate_significance(["decision"]) == ["decision"]

    def test_multiple_valid_tags(self):
        result = validate_significance(["decision", "lesson"])
        assert result == ["decision", "lesson"]

    def test_all_valid_tags(self):
        result = validate_significance(list(VALID_SIGNIFICANCE))
        assert set(result) == VALID_SIGNIFICANCE

    def test_invalid_tag_raises(self):
        with pytest.raises(ValueError, match="Invalid significance tag"):
            validate_significance(["invalid_tag"])

    def test_mixed_valid_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid significance tag"):
            validate_significance(["decision", "bogus"])

    def test_case_insensitive(self):
        assert validate_significance(["DECISION"]) == ["decision"]
        assert validate_significance(["Lesson"]) == ["lesson"]

    def test_strips_whitespace(self):
        assert validate_significance([" decision "]) == ["decision"]

    def test_dedup(self):
        result = validate_significance(["decision", "decision", "lesson"])
        assert result == ["decision", "lesson"]


# ---------- significance_multiplier ----------


class TestSignificanceMultiplier:
    def test_none_returns_1(self):
        assert significance_multiplier(None) == 1.0

    def test_empty_returns_1(self):
        assert significance_multiplier([]) == 1.0

    def test_decision_returns_3(self):
        assert significance_multiplier(["decision"]) == 3.0

    def test_lesson_returns_2(self):
        assert significance_multiplier(["lesson"]) == 2.0

    def test_identity_returns_3(self):
        assert significance_multiplier(["identity"]) == 3.0

    def test_surprise_returns_1_5(self):
        assert significance_multiplier(["surprise"]) == 1.5

    def test_human_returns_2_5(self):
        assert significance_multiplier(["human"]) == 2.5

    def test_multiple_takes_max(self):
        # decision=3.0, lesson=2.0 → max is 3.0
        assert significance_multiplier(["decision", "lesson"]) == 3.0

    def test_unknown_tag_returns_1(self):
        assert significance_multiplier(["unknown"]) == 1.0


# ---------- recall_multiplier ----------


class TestRecallMultiplier:
    def test_zero_returns_1(self):
        assert recall_multiplier(0) == 1.0

    def test_negative_returns_1(self):
        assert recall_multiplier(-1) == 1.0

    def test_positive_count_increases(self):
        result = recall_multiplier(5)
        assert result > 1.0

    def test_higher_count_higher_multiplier(self):
        m5 = recall_multiplier(5)
        m50 = recall_multiplier(50)
        assert m50 > m5

    def test_diminishing_returns(self):
        # Growth rate slows: gap from 100→1000 smaller than 1→100
        diff_low = recall_multiplier(100) - recall_multiplier(1)
        diff_high = recall_multiplier(1000) - recall_multiplier(100)
        assert diff_low > diff_high


# ---------- decay_score with significance/recall ----------


class TestDecayScoreWithSignificance:
    def test_no_significance_same_as_before(self):
        score_plain = decay_score(10, access_count=1)
        score_none = decay_score(10, access_count=1, significance=None, recall_count=0)
        assert score_plain == score_none

    def test_significance_slows_decay(self):
        score_plain = decay_score(30, access_count=1)
        score_decision = decay_score(30, access_count=1, significance=["decision"])
        # Decision tag should make the score higher (slower decay)
        assert score_decision > score_plain

    def test_recall_count_slows_decay(self):
        score_plain = decay_score(30, access_count=1)
        score_recalled = decay_score(30, access_count=1, recall_count=10)
        assert score_recalled > score_plain

    def test_both_combined(self):
        score_plain = decay_score(30, access_count=1)
        score_both = decay_score(30, access_count=1, significance=["decision"], recall_count=10)
        assert score_both > score_plain

    def test_identity_tag_strong_protection(self):
        """Identity entries (agent self-model) should be strongly protected."""
        score_plain = decay_score(60, access_count=1)
        score_identity = decay_score(60, access_count=1, significance=["identity"])
        # At 60 days, identity tag should make a big difference
        assert score_identity > score_plain * 2


# ---------- create_entry with significance ----------


class TestCreateEntrySignificance:
    def test_no_significance(self):
        text = create_entry("test content")
        meta, _ = parse_entry(text)
        assert "significance" not in meta

    def test_with_significance(self):
        text = create_entry("test content", significance=["decision", "lesson"])
        meta, _ = parse_entry(text)
        assert meta["significance"] == ["decision", "lesson"]

    def test_invalid_significance_raises(self):
        with pytest.raises(ValueError):
            create_entry("test content", significance=["invalid"])

    def test_significance_roundtrip(self):
        """Significance survives serialize → parse roundtrip."""
        text = create_entry("test content", significance=["decision", "human"])
        meta, body = parse_entry(text)
        assert meta["significance"] == ["decision", "human"]

        # Re-serialize and re-parse
        text2 = serialize_entry(meta, body)
        meta2, body2 = parse_entry(text2)
        assert meta2["significance"] == ["decision", "human"]
        assert body2 == body


# ---------- Store integration ----------


class TestStoreSignificance:
    @pytest.fixture
    def store(self, tmp_path):
        from palaia.store import Store

        palaia_dir = tmp_path / ".palaia"
        palaia_dir.mkdir()
        for sub in ("hot", "warm", "cold", "wal", "index"):
            (palaia_dir / sub).mkdir()
        config = {
            "agent": "test",
            "default_scope": "team",
            "embedding_chain": ["bm25"],
            "lock_timeout_seconds": 5,
            "decay_lambda": 0.1,
            "hot_threshold_days": 7,
            "warm_threshold_days": 30,
            "hot_min_score": 0.5,
            "warm_min_score": 0.1,
            "wal_retention_days": 7,
        }
        (palaia_dir / "config.json").write_text(json.dumps(config))
        return Store(palaia_dir)

    def test_write_with_significance(self, store):
        eid = store.write("important decision", significance=["decision"])
        entry = store.read(eid)
        assert entry is not None
        meta, _ = entry
        assert meta["significance"] == ["decision"]

    def test_write_without_significance(self, store):
        eid = store.write("normal entry")
        entry = store.read(eid)
        assert entry is not None
        meta, _ = entry
        assert "significance" not in meta

    def test_edit_add_significance(self, store):
        eid = store.write("some content")
        meta = store.edit(eid, significance=["lesson", "human"])
        assert meta["significance"] == ["lesson", "human"]

    def test_edit_remove_significance(self, store):
        eid = store.write("content", significance=["decision"])
        # Edit with empty list should remove significance
        meta = store.edit(eid, significance=[])
        assert "significance" not in meta

    def test_gc_significance_aware(self, store):
        """GC should use significance tags when computing decay scores."""
        from palaia.entry import parse_entry

        eid = store.write("important", significance=["decision"])
        # Run GC
        store.gc()
        # Read entry back — decay_score should account for significance
        path = store._find_entry(eid)
        text = path.read_text()
        meta, _ = parse_entry(text)
        # The entry should still be in hot (it's brand new)
        assert (store.root / "hot" / f"{eid}.md").exists()


# ---------- Search integration ----------


class TestSearchSignificanceFilter:
    @pytest.fixture
    def store(self, tmp_path):
        from palaia.store import Store

        palaia_dir = tmp_path / ".palaia"
        palaia_dir.mkdir()
        for sub in ("hot", "warm", "cold", "wal", "index"):
            (palaia_dir / sub).mkdir()
        config = {
            "agent": "test",
            "default_scope": "team",
            "embedding_chain": ["bm25"],
            "lock_timeout_seconds": 5,
            "decay_lambda": 0.1,
            "hot_threshold_days": 7,
            "warm_threshold_days": 30,
            "hot_min_score": 0.5,
            "warm_min_score": 0.1,
            "wal_retention_days": 7,
        }
        (palaia_dir / "config.json").write_text(json.dumps(config))
        return Store(palaia_dir)

    def test_query_filter_by_significance(self, store):
        from palaia.search import SearchEngine

        store.write("alpha decision made", significance=["decision"])
        store.write("beta lesson learned", significance=["lesson"])
        store.write("gamma no significance")

        engine = SearchEngine(store)
        results = engine.search("decision lesson", significance="decision")
        # Should only return the decision entry
        assert len(results) >= 1
        for r in results:
            assert "decision" in r.get("significance", [])

    def test_query_no_significance_filter_returns_all(self, store):
        from palaia.search import SearchEngine

        store.write("alpha something", significance=["decision"])
        store.write("alpha something else")

        engine = SearchEngine(store)
        results = engine.search("alpha something")
        assert len(results) >= 1  # At least the matching entries

    def test_recall_tracking(self, store):
        """Query results should increment recall_count and last_recalled."""
        from palaia.search import SearchEngine

        eid = store.write("recall test content unique")
        engine = SearchEngine(store)

        # Query twice
        engine.search("recall test content unique")
        engine.search("recall test content unique")

        # Read entry and check recall fields
        path = store._find_entry(eid)
        text = path.read_text()
        meta, _ = parse_entry(text)
        # recall_count should be >= 2 (from the two queries, plus read() calls)
        assert meta.get("recall_count", 0) >= 2
        assert "last_recalled" in meta
