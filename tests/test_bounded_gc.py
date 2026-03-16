"""Tests for bounded memory and intelligent GC (Issues #33, #70, #71)."""

import json

from palaia.store import Store


def _make_store(tmp_path, config_extra=None):
    """Create a minimal store for testing."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for d in ("hot", "warm", "cold", "wal", "index"):
        (root / d).mkdir()
    config = {"agent": "test"}
    if config_extra:
        config.update(config_extra)
    (root / "config.json").write_text(json.dumps(config))
    return Store(root)


class TestGCScore:
    def test_gc_score_basic(self, tmp_path):
        store = _make_store(tmp_path)
        eid = store.write("Basic entry", agent="test")
        from palaia.entry import parse_entry

        text = (store.root / "hot" / f"{eid}.md").read_text()
        meta, body = parse_entry(text)
        score = store.gc_score_entry(meta, body)
        assert score > 0

    def test_gc_score_process_higher_than_memory(self, tmp_path):
        store = _make_store(tmp_path)
        id_mem = store.write("Memory entry", agent="test", entry_type="memory")
        id_proc = store.write("1. Step one\n2. Step two", agent="test", entry_type="process")

        from palaia.entry import parse_entry

        meta_mem, body_mem = parse_entry((store.root / "hot" / f"{id_mem}.md").read_text())
        meta_proc, body_proc = parse_entry((store.root / "hot" / f"{id_proc}.md").read_text())

        score_mem = store.gc_score_entry(meta_mem, body_mem)
        score_proc = store.gc_score_entry(meta_proc, body_proc)

        # Process entries should have higher GC score (type_weight: 2.0 vs 1.0)
        assert score_proc > score_mem

    def test_gc_score_with_significance_tags(self, tmp_path):
        store = _make_store(tmp_path)
        id_plain = store.write("Plain entry", agent="test")
        id_tagged = store.write("Important decision", agent="test", tags=["decision", "lesson"])

        from palaia.entry import parse_entry

        meta_p, body_p = parse_entry((store.root / "hot" / f"{id_plain}.md").read_text())
        meta_t, body_t = parse_entry((store.root / "hot" / f"{id_tagged}.md").read_text())

        score_p = store.gc_score_entry(meta_p, body_p)
        score_t = store.gc_score_entry(meta_t, body_t)

        # Tagged entry should have higher score (significance_weight > 1.0)
        assert score_t > score_p


class TestGCDryRun:
    def test_dry_run_returns_candidates(self, tmp_path):
        store = _make_store(tmp_path)
        store.write("Entry one", agent="test")
        store.write("Entry two", agent="test")

        result = store.gc(dry_run=True)
        assert result["dry_run"] is True
        assert len(result["candidates"]) == 2

    def test_dry_run_does_not_modify(self, tmp_path):
        store = _make_store(tmp_path)
        eid = store.write("Entry", agent="test")

        before = (store.root / "hot" / f"{eid}.md").read_text()

        store.gc(dry_run=True)

        after = (store.root / "hot" / f"{eid}.md").read_text()
        assert before == after

    def test_dry_run_candidates_sorted_by_score(self, tmp_path):
        store = _make_store(tmp_path)
        store.write("Plain entry", agent="test")
        store.write("Decision entry", agent="test", tags=["decision"])

        result = store.gc(dry_run=True)
        candidates = result["candidates"]
        scores = [c["score"] for c in candidates]
        assert scores == sorted(scores)  # Ascending order


class TestBudgetEnforcement:
    def test_max_entries_per_tier(self, tmp_path):
        store = _make_store(tmp_path, {"max_entries_per_tier": 2})
        # Write 4 entries to hot tier
        store.write("Entry 1", agent="test")
        store.write("Entry 2", agent="test")
        store.write("Entry 3", agent="test")
        store.write("Entry 4", agent="test")

        result = store.gc(budget=True)
        assert result.get("pruned", 0) == 2  # Should prune 2 to meet limit of 2

        # Verify only 2 remain in hot
        remaining = list((store.root / "hot").glob("*.md"))
        assert len(remaining) == 2

    def test_max_total_chars(self, tmp_path):
        store = _make_store(tmp_path, {"max_total_chars": 100})
        # Write entries with known content sizes
        store.write("A" * 60, agent="test")
        store.write("B" * 60, agent="test")
        store.write("C" * 60, agent="test")

        result = store.gc(budget=True)
        assert result.get("pruned", 0) > 0

    def test_budget_preserves_high_score_entries(self, tmp_path):
        store = _make_store(tmp_path, {"max_entries_per_tier": 1})
        store.write("Low importance entry", agent="test")
        id_high = store.write("High importance decision", agent="test", tags=["decision", "lesson"])

        store.gc(budget=True)

        # High-scored entry should survive
        remaining = list((store.root / "hot").glob("*.md"))
        assert len(remaining) == 1
        assert remaining[0].stem == id_high

    def test_no_budget_no_pruning(self, tmp_path):
        store = _make_store(tmp_path)  # No budget limits set
        store.write("Entry 1", agent="test")
        store.write("Entry 2", agent="test")

        result = store.gc(budget=True)
        assert result.get("pruned", 0) == 0


class TestStatusBudget:
    def test_status_shows_budget_when_configured(self, tmp_path):
        store = _make_store(tmp_path, {"max_entries_per_tier": 50, "max_total_chars": 10000})
        store.write("Test entry", agent="test")
        status = store.status()
        assert "budget" in status
        assert status["budget"]["max_entries_per_tier"] == 50
        assert status["budget"]["max_total_chars"] == 10000

    def test_status_no_budget_when_unconfigured(self, tmp_path):
        store = _make_store(tmp_path)
        status = store.status()
        assert "budget" not in status

    def test_status_includes_total_chars(self, tmp_path):
        store = _make_store(tmp_path)
        store.write("Hello world", agent="test")
        status = store.status()
        assert status["total_chars"] > 0
