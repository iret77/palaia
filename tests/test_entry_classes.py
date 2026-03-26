"""Tests for entry classes, structured fields, session identities, and edit (v1.7.0)."""

from __future__ import annotations

import pytest

from palaia.config import DEFAULT_CONFIG, save_config
from palaia.entry import (
    VALID_PRIORITIES,
    VALID_STATUSES,
    VALID_TYPES,
    create_entry,
    parse_entry,
    validate_entry_type,
    validate_priority,
    validate_status,
)
from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    root = tmp_path / ".palaia"
    root.mkdir()
    for d in ("hot", "warm", "cold", "wal", "index"):
        (root / d).mkdir()
    config = dict(DEFAULT_CONFIG)
    config["store_version"] = "1.7.0"
    save_config(root, config)
    return root


@pytest.fixture
def store(palaia_root):
    return Store(palaia_root)


# --- Entry type validation ---


class TestValidation:
    def test_valid_types(self):
        assert validate_entry_type("memory") == "memory"
        assert validate_entry_type("process") == "process"
        assert validate_entry_type("task") == "task"

    def test_default_type(self):
        assert validate_entry_type(None) == "memory"

    def test_invalid_type(self):
        with pytest.raises(ValueError, match="Invalid entry type"):
            validate_entry_type("invalid")

    def test_valid_statuses(self):
        for s in VALID_STATUSES:
            assert validate_status(s) == s

    def test_invalid_status(self):
        with pytest.raises(ValueError, match="Invalid status"):
            validate_status("invalid")

    def test_valid_priorities(self):
        for p in VALID_PRIORITIES:
            assert validate_priority(p) == p

    def test_invalid_priority(self):
        with pytest.raises(ValueError, match="Invalid priority"):
            validate_priority("invalid")

    def test_none_status_priority(self):
        assert validate_status(None) is None
        assert validate_priority(None) is None


# --- Entry creation with new fields ---


class TestCreateEntry:
    def test_default_type_memory(self):
        text = create_entry("test body")
        meta, body = parse_entry(text)
        assert meta["type"] == "memory"
        assert body == "test body"

    def test_explicit_type(self):
        for t in VALID_TYPES:
            text = create_entry("body", entry_type=t)
            meta, _ = parse_entry(text)
            assert meta["type"] == t

    def test_task_fields(self):
        text = create_entry(
            "fix the bug",
            entry_type="task",
            status="open",
            priority="high",
            assignee="Elliot",
            due_date="2026-04-01",
        )
        meta, body = parse_entry(text)
        assert meta["type"] == "task"
        assert meta["status"] == "open"
        assert meta["priority"] == "high"
        assert meta["assignee"] == "Elliot"
        assert meta["due_date"] == "2026-04-01"

    def test_task_default_status(self):
        text = create_entry("task body", entry_type="task")
        meta, _ = parse_entry(text)
        assert meta["status"] == "open"

    def test_memory_no_task_fields(self):
        text = create_entry("memory body", entry_type="memory")
        meta, _ = parse_entry(text)
        assert "status" not in meta
        assert "priority" not in meta
        assert "assignee" not in meta

    def test_instance_field(self):
        text = create_entry("body", instance="Claw-Palaia")
        meta, _ = parse_entry(text)
        assert meta["instance"] == "Claw-Palaia"

    def test_instance_from_env(self, monkeypatch):
        monkeypatch.setenv("PALAIA_INSTANCE", "TestInstance")
        text = create_entry("body")
        meta, _ = parse_entry(text)
        assert meta["instance"] == "TestInstance"

    def test_instance_explicit_overrides_env(self, monkeypatch):
        monkeypatch.setenv("PALAIA_INSTANCE", "EnvInstance")
        text = create_entry("body", instance="ExplicitInstance")
        meta, _ = parse_entry(text)
        assert meta["instance"] == "ExplicitInstance"

    def test_no_instance_when_not_set(self, monkeypatch):
        monkeypatch.delenv("PALAIA_INSTANCE", raising=False)
        text = create_entry("body")
        meta, _ = parse_entry(text)
        assert "instance" not in meta


# --- Store write with new fields ---


class TestStoreWrite:
    def test_write_with_type(self, store):
        eid = store.write("task content", entry_type="task", status="open", priority="high")
        entry = store.read(eid)
        assert entry is not None
        meta, body = entry
        assert meta["type"] == "task"
        assert meta["status"] == "open"
        assert meta["priority"] == "high"

    def test_write_with_instance(self, store):
        eid = store.write("body", instance="MyInstance")
        meta, _ = store.read(eid)
        assert meta["instance"] == "MyInstance"

    def test_write_process_type(self, store):
        eid = store.write("SOP checklist", entry_type="process")
        meta, _ = store.read(eid)
        assert meta["type"] == "process"


# --- Store edit ---


class TestStoreEdit:
    def test_edit_content(self, store):
        eid = store.write("original content")
        store.edit(eid, body="updated content")
        entry = store.read(eid)
        _, body = entry
        assert body == "updated content"

    def test_edit_tags(self, store):
        eid = store.write("body", tags=["old"])
        store.edit(eid, tags=["new", "tags"])
        entry = store.read(eid)
        m, _ = entry
        assert m["tags"] == ["new", "tags"]

    def test_edit_title(self, store):
        eid = store.write("body", title="Old Title")
        store.edit(eid, title="New Title")
        m, _ = store.read(eid)
        assert m["title"] == "New Title"

    def test_edit_task_status(self, store):
        eid = store.write("task", entry_type="task", status="open")
        store.edit(eid, status="done")
        m, _ = store.read(eid)
        assert m["status"] == "done"

    def test_edit_task_priority(self, store):
        eid = store.write("task", entry_type="task", priority="low")
        store.edit(eid, priority="critical")
        m, _ = store.read(eid)
        assert m["priority"] == "critical"

    def test_edit_task_assignee(self, store):
        eid = store.write("task", entry_type="task")
        store.edit(eid, assignee="CyberClaw")
        m, _ = store.read(eid)
        assert m["assignee"] == "CyberClaw"

    def test_edit_task_due_date(self, store):
        eid = store.write("task", entry_type="task")
        store.edit(eid, due_date="2026-12-31")
        m, _ = store.read(eid)
        assert m["due_date"] == "2026-12-31"

    def test_edit_change_type(self, store):
        eid = store.write("body")
        store.edit(eid, entry_type="process")
        m, _ = store.read(eid)
        assert m["type"] == "process"

    def test_edit_not_found(self, store):
        with pytest.raises(ValueError, match="Entry not found"):
            store.edit("nonexistent-id", body="new")

    def test_edit_invalid_status(self, store):
        eid = store.write("task", entry_type="task")
        with pytest.raises(ValueError, match="Invalid status"):
            store.edit(eid, status="invalid-status")

    def test_edit_invalid_priority(self, store):
        eid = store.write("task", entry_type="task")
        with pytest.raises(ValueError, match="Invalid priority"):
            store.edit(eid, priority="invalid-priority")

    def test_edit_scope_enforcement_private(self, store):
        eid = store.write("private data", scope="private", agent="AgentA")
        # Different agent cannot edit private entry
        with pytest.raises(PermissionError, match="Scope violation"):
            store.edit(eid, body="hacked", agent="AgentB")

    def test_edit_scope_enforcement_private_owner_ok(self, store):
        eid = store.write("private data", scope="private", agent="AgentA")
        # Owner can edit
        meta = store.edit(eid, body="updated", agent="AgentA")
        assert meta is not None

    def test_edit_team_scope_any_agent(self, store):
        eid = store.write("team data", scope="team", agent="AgentA")
        # Any agent can edit team-scoped entries
        meta = store.edit(eid, body="updated by B", agent="AgentB")
        assert meta is not None

    def test_edit_content_invalidates_embeddings(self, store):
        eid = store.write("original")
        # Simulate cached embedding with a known fake vector
        store.embedding_cache.set_cached(eid, [0.1, 0.2], model="test")
        cached_before = store.embedding_cache.get_cached(eid)
        assert cached_before is not None
        assert cached_before == pytest.approx([0.1, 0.2], abs=1e-6)
        # Edit content should invalidate the old embedding
        # (may be re-indexed with a new vector if a provider is available)
        store.edit(eid, body="new content")
        cached_after = store.embedding_cache.get_cached(eid)
        # The old fake vector must be gone — either None or a fresh real vector
        assert cached_after != [0.1, 0.2]

    def test_edit_metadata_no_invalidate(self, store):
        eid = store.write("original")
        store.embedding_cache.set_cached(eid, [0.1, 0.2], model="test")
        # Edit only metadata (no body change)
        store.edit(eid, title="New Title")
        cached = store.embedding_cache.get_cached(eid)
        assert cached is not None  # Should still be cached

    def test_edit_wal_backed(self, store):
        eid = store.write("original")
        store.edit(eid, body="updated via WAL")
        # Verify the edit persisted
        m, body = store.read(eid)
        assert body == "updated via WAL"


# --- Backward compatibility ---


class TestBackwardCompat:
    def test_old_entry_without_type(self, store):
        """Entries without type field should default to 'memory'."""
        # Manually create an old-style entry without type
        from palaia.entry import content_hash

        old_entry = (
            "---\n"
            "id: test-old-entry-uuid\n"
            "scope: team\n"
            "created: 2026-01-01T00:00:00+00:00\n"
            "accessed: 2026-01-01T00:00:00+00:00\n"
            "access_count: 1\n"
            "decay_score: 1.0\n"
            f"content_hash: {content_hash('old body')}\n"
            "---\n\n"
            "old body\n"
        )
        (store.root / "hot" / "test-old-entry-uuid.md").write_text(old_entry)
        entry = store.read("test-old-entry-uuid")
        assert entry is not None
        meta, body = entry
        # No type field in meta, but system treats as memory
        assert meta.get("type", "memory") == "memory"

    def test_old_entry_editable(self, store):
        """Old entries without type should be editable."""
        from palaia.entry import content_hash

        old_entry = (
            "---\n"
            "id: test-edit-old-uuid\n"
            "scope: team\n"
            "created: 2026-01-01T00:00:00+00:00\n"
            "accessed: 2026-01-01T00:00:00+00:00\n"
            "access_count: 1\n"
            "decay_score: 1.0\n"
            f"content_hash: {content_hash('old body')}\n"
            "---\n\n"
            "old body\n"
        )
        (store.root / "hot" / "test-edit-old-uuid.md").write_text(old_entry)
        meta = store.edit("test-edit-old-uuid", body="updated body")
        assert meta is not None
        _, body = store.read("test-edit-old-uuid")
        assert body == "updated body"


# --- Structured query filters ---


class TestStructuredFilters:
    def test_list_filter_by_type(self, store):
        store.write("memory entry")
        store.write("task entry", entry_type="task")
        store.write("process entry", entry_type="process")

        entries = store.list_entries("hot")
        # Filter manually like CLI does
        tasks = [(m, b) for m, b in entries if m.get("type", "memory") == "task"]
        assert len(tasks) == 1
        processes = [(m, b) for m, b in entries if m.get("type", "memory") == "process"]
        assert len(processes) == 1
        memories = [(m, b) for m, b in entries if m.get("type", "memory") == "memory"]
        assert len(memories) == 1

    def test_list_filter_by_status(self, store):
        store.write("open task", entry_type="task", status="open")
        store.write("done task", entry_type="task", status="done")

        entries = store.list_entries("hot")
        open_tasks = [(m, b) for m, b in entries if m.get("status") == "open"]
        assert len(open_tasks) == 1
        done_tasks = [(m, b) for m, b in entries if m.get("status") == "done"]
        assert len(done_tasks) == 1

    def test_list_filter_by_priority(self, store):
        store.write("high prio", entry_type="task", priority="high")
        store.write("low prio", entry_type="task", priority="low")

        entries = store.list_entries("hot")
        high = [(m, b) for m, b in entries if m.get("priority") == "high"]
        assert len(high) == 1

    def test_list_filter_by_instance(self, store):
        store.write("entry A", instance="InstanceA")
        store.write("entry B", instance="InstanceB")

        entries = store.list_entries("hot")
        inst_a = [(m, b) for m, b in entries if m.get("instance") == "InstanceA"]
        assert len(inst_a) == 1


# --- Search engine with structured filters ---


class TestSearchFilters:
    def test_search_filter_by_type(self, store):
        from palaia.search import SearchEngine

        store.write("memory about cats", entry_type="memory", title="Cat Memory")
        store.write("task about cats", entry_type="task", title="Cat Task")

        engine = SearchEngine(store)
        results = engine.search("cats", entry_type="task")
        assert len(results) == 1
        assert results[0]["type"] == "task"

    def test_search_filter_by_status(self, store):
        from palaia.search import SearchEngine

        store.write("open bug", entry_type="task", status="open", title="Bug")
        store.write("done bug", entry_type="task", status="done", title="Old Bug")

        engine = SearchEngine(store)
        results = engine.search("bug", status="open")
        assert len(results) == 1
        assert results[0]["status"] == "open"

    def test_search_filter_by_priority(self, store):
        from palaia.search import SearchEngine

        store.write("critical issue", entry_type="task", priority="critical", title="Critical")
        store.write("low issue", entry_type="task", priority="low", title="Low")

        engine = SearchEngine(store)
        results = engine.search("issue", priority="critical")
        assert len(results) == 1

    def test_search_filter_by_instance(self, store):
        from palaia.search import SearchEngine

        store.write("from instance A", instance="A", title="A Entry")
        store.write("from instance B", instance="B", title="B Entry")

        engine = SearchEngine(store)
        results = engine.search("instance", instance="A")
        assert len(results) == 1
        assert results[0]["instance"] == "A"

    def test_search_combined_filters(self, store):
        from palaia.search import SearchEngine

        store.write("critical open task", entry_type="task", status="open", priority="critical", title="Urgent")
        store.write("low open task", entry_type="task", status="open", priority="low", title="Minor")
        store.write("critical done task", entry_type="task", status="done", priority="critical", title="Resolved")

        engine = SearchEngine(store)
        results = engine.search("task", entry_type="task", status="open", priority="critical")
        assert len(results) == 1
        assert results[0]["title"] == "Urgent"

    def test_search_results_include_type(self, store):
        from palaia.search import SearchEngine

        store.write("a memory entry about testing", entry_type="memory", title="Test Memory")

        engine = SearchEngine(store)
        results = engine.search("testing")
        assert len(results) >= 1
        assert "type" in results[0]
        assert results[0]["type"] == "memory"


# --- Doctor entry class check ---


class TestDoctorEntryClasses:
    def test_doctor_detects_untyped(self, palaia_root):
        from palaia.doctor import _check_entry_classes
        from palaia.entry import content_hash

        # Create an old-style entry without type
        old_entry = (
            "---\n"
            "id: untyped-entry-uuid\n"
            "scope: team\n"
            "created: 2026-01-01T00:00:00+00:00\n"
            "accessed: 2026-01-01T00:00:00+00:00\n"
            f"content_hash: {content_hash('body')}\n"
            "---\n\nbody\n"
        )
        (palaia_root / "hot" / "untyped-entry-uuid.md").write_text(old_entry)

        result = _check_entry_classes(palaia_root)
        assert result["status"] == "info"
        assert "untyped" in result["message"]

    def test_doctor_all_typed(self, store, palaia_root):
        store.write("typed entry", entry_type="memory")

        from palaia.doctor import _check_entry_classes

        result = _check_entry_classes(palaia_root)
        assert result["status"] == "ok"

    def test_doctor_no_entries(self, palaia_root):
        from palaia.doctor import _check_entry_classes

        result = _check_entry_classes(palaia_root)
        assert result["status"] == "info"
        assert "No entries" in result["message"]


# --- Migrate --suggest ---


class TestMigrateSuggest:
    def test_suggest_heuristics(self):
        from palaia.cli import _suggest_type

        assert _suggest_type("Fix login bug", "Users can't log in", {}) == "task"
        assert _suggest_type("Deployment Checklist", "Step 1: ...", {}) == "process"
        assert _suggest_type("Meeting Notes", "We discussed...", {}) == "memory"
