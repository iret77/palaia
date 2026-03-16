"""Tests for process runner (Issue #72)."""

from palaia.process_runner import ProcessRun, ProcessRunManager, parse_steps


class TestParseSteps:
    def test_numbered_list(self):
        content = """1. First step
2. Second step
3. Third step"""
        steps = parse_steps(content)
        assert len(steps) == 3
        assert steps[0]["text"] == "First step"
        assert steps[0]["index"] == 0
        assert steps[0]["done"] is False
        assert steps[2]["text"] == "Third step"

    def test_numbered_list_with_parens(self):
        content = """1) Step A
2) Step B"""
        steps = parse_steps(content)
        assert len(steps) == 2
        assert steps[0]["text"] == "Step A"

    def test_checkboxes_unchecked(self):
        content = """- [ ] Do this
- [ ] Do that
- [ ] Do the other"""
        steps = parse_steps(content)
        assert len(steps) == 3
        assert all(not s["done"] for s in steps)

    def test_checkboxes_mixed(self):
        content = """- [x] Already done
- [ ] Not yet
- [X] Also done"""
        steps = parse_steps(content)
        assert len(steps) == 3
        assert steps[0]["done"] is True
        assert steps[1]["done"] is False
        assert steps[2]["done"] is True

    def test_empty_content(self):
        assert parse_steps("") == []

    def test_no_steps_in_content(self):
        content = "This is just a paragraph with no steps."
        steps = parse_steps(content)
        assert steps == []

    def test_mixed_content(self):
        content = """# My Process

Some intro text.

1. Step one
2. Step two

Some more text.

3. Step three"""
        steps = parse_steps(content)
        assert len(steps) == 3

    def test_steps_with_blank_lines(self):
        content = """1. First

2. Second

3. Third"""
        steps = parse_steps(content)
        assert len(steps) == 3


class TestProcessRun:
    def test_create(self):
        steps = [
            {"index": 0, "text": "Step 1", "done": False, "done_at": None},
            {"index": 1, "text": "Step 2", "done": False, "done_at": None},
        ]
        run = ProcessRun(entry_id="test-123", steps=steps)
        assert run.completed is False
        assert run.progress_summary() == "0/2 steps completed"

    def test_mark_done(self):
        steps = [
            {"index": 0, "text": "Step 1", "done": False, "done_at": None},
            {"index": 1, "text": "Step 2", "done": False, "done_at": None},
        ]
        run = ProcessRun(entry_id="test-123", steps=steps)
        assert run.mark_done(0) is True
        assert run.steps[0]["done"] is True
        assert run.steps[0]["done_at"] is not None
        assert run.completed is False

    def test_mark_all_done_completes(self):
        steps = [
            {"index": 0, "text": "Step 1", "done": False, "done_at": None},
        ]
        run = ProcessRun(entry_id="test-123", steps=steps)
        run.mark_done(0)
        assert run.completed is True

    def test_mark_invalid_step(self):
        run = ProcessRun(entry_id="test-123", steps=[])
        assert run.mark_done(0) is False
        assert run.mark_done(-1) is False

    def test_serialization_roundtrip(self):
        steps = [
            {"index": 0, "text": "Step 1", "done": True, "done_at": "2025-01-01T00:00:00+00:00"},
            {"index": 1, "text": "Step 2", "done": False, "done_at": None},
        ]
        original = ProcessRun(entry_id="abc-123", steps=steps, started_at="2025-01-01T00:00:00+00:00")
        data = original.to_dict()
        restored = ProcessRun.from_dict(data)
        assert restored.entry_id == "abc-123"
        assert len(restored.steps) == 2
        assert restored.steps[0]["done"] is True


class TestProcessRunManager:
    def test_start_and_get(self, tmp_path):
        root = tmp_path / ".palaia"
        root.mkdir()
        prm = ProcessRunManager(root)

        run = prm.start("entry-1", "1. First\n2. Second")
        assert len(run.steps) == 2

        loaded = prm.get("entry-1")
        assert loaded is not None
        assert len(loaded.steps) == 2

    def test_start_idempotent(self, tmp_path):
        root = tmp_path / ".palaia"
        root.mkdir()
        prm = ProcessRunManager(root)

        run1 = prm.start("entry-1", "1. First\n2. Second")
        run1.mark_done(0)
        prm.save(run1)

        run2 = prm.start("entry-1", "1. First\n2. Second")
        assert run2.steps[0]["done"] is True  # Preserves state

    def test_list_runs(self, tmp_path):
        root = tmp_path / ".palaia"
        root.mkdir()
        prm = ProcessRunManager(root)

        prm.start("entry-1", "1. A\n2. B")
        prm.start("entry-2", "1. C\n2. D")

        runs = prm.list_runs()
        assert len(runs) == 2

    def test_delete(self, tmp_path):
        root = tmp_path / ".palaia"
        root.mkdir()
        prm = ProcessRunManager(root)

        prm.start("entry-1", "1. A")
        assert prm.delete("entry-1") is True
        assert prm.get("entry-1") is None
        assert prm.delete("entry-1") is False

    def test_get_nonexistent(self, tmp_path):
        root = tmp_path / ".palaia"
        root.mkdir()
        prm = ProcessRunManager(root)
        assert prm.get("nonexistent") is None

    def test_persistence(self, tmp_path):
        root = tmp_path / ".palaia"
        root.mkdir()
        prm = ProcessRunManager(root)

        run = prm.start("entry-1", "1. Step A\n2. Step B")
        run.mark_done(0)
        prm.save(run)

        # Create new manager instance (simulates restart)
        prm2 = ProcessRunManager(root)
        loaded = prm2.get("entry-1")
        assert loaded is not None
        assert loaded.steps[0]["done"] is True
        assert loaded.steps[1]["done"] is False
