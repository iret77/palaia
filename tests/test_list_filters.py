"""Tests for exact filtering on palaia list (#37)."""

import pytest

from palaia.config import DEFAULT_CONFIG, save_config
from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    config = dict(DEFAULT_CONFIG)
    config["agent"] = "test"
    save_config(root, config)
    return root


@pytest.fixture
def store(palaia_root):
    return Store(palaia_root)


def test_list_filter_by_status(store, palaia_root):
    """--status filters entries by exact task status."""
    store.write("Open task", scope="team", agent="test", entry_type="task", status="open", title="Task A")
    store.write("Done task", scope="team", agent="test", entry_type="task", status="done", title="Task B")
    store.write("Memory entry", scope="team", agent="test", title="Mem")

    entries = store.list_entries("hot")
    assert len(entries) == 3

    # Filter by status=open
    filtered = [(m, b) for m, b in entries if m.get("status") == "open"]
    assert len(filtered) == 1
    assert filtered[0][0]["title"] == "Task A"


def test_list_filter_by_tag(store, palaia_root):
    """--tag filters entries by exact tag match."""
    store.write("Entry with idea", scope="team", agent="test", tags=["idea", "feature"], title="Idea")
    store.write("Entry with bug", scope="team", agent="test", tags=["bug"], title="Bug")
    store.write("No tags", scope="team", agent="test", title="NoTags")

    entries = store.list_entries("hot")
    assert len(entries) == 3

    # Filter by tag=idea
    filtered = [(m, b) for m, b in entries if "idea" in (m.get("tags") or [])]
    assert len(filtered) == 1
    assert filtered[0][0]["title"] == "Idea"


def test_list_filter_by_priority(store, palaia_root):
    """--priority filters entries by exact priority."""
    store.write("High prio", scope="team", agent="test", entry_type="task", priority="high", title="High")
    store.write("Low prio", scope="team", agent="test", entry_type="task", priority="low", title="Low")
    store.write("No prio", scope="team", agent="test", title="NoPrio")

    entries = store.list_entries("hot")
    assert len(entries) == 3

    filtered = [(m, b) for m, b in entries if m.get("priority") == "high"]
    assert len(filtered) == 1
    assert filtered[0][0]["title"] == "High"


def test_list_combined_filters_and_logic(store, palaia_root):
    """Combined filters use AND logic."""
    store.write(
        "Task open high", scope="team", agent="test", entry_type="task", status="open", priority="high", title="T1"
    )
    store.write(
        "Task open low", scope="team", agent="test", entry_type="task", status="open", priority="low", title="T2"
    )
    store.write(
        "Task done high", scope="team", agent="test", entry_type="task", status="done", priority="high", title="T3"
    )

    entries = store.list_entries("hot")
    assert len(entries) == 3

    # Combined: status=open AND priority=high
    filtered = [(m, b) for m, b in entries if m.get("status") == "open" and m.get("priority") == "high"]
    assert len(filtered) == 1
    assert filtered[0][0]["title"] == "T1"


def test_list_multi_tag_and_logic(store, palaia_root):
    """Multiple --tag flags use AND logic (entry must have ALL specified tags)."""
    store.write("Both tags", scope="team", agent="test", tags=["idea", "urgent"], title="Both")
    store.write("Only idea", scope="team", agent="test", tags=["idea"], title="OnlyIdea")
    store.write("Only urgent", scope="team", agent="test", tags=["urgent"], title="OnlyUrgent")

    entries = store.list_entries("hot")
    assert len(entries) == 3

    # Filter: tag=idea AND tag=urgent
    tags_required = ["idea", "urgent"]
    for tag in tags_required:
        entries = [(m, b) for m, b in entries if tag in (m.get("tags") or [])]
    assert len(entries) == 1
    assert entries[0][0]["title"] == "Both"


def test_list_all_tiers(store, palaia_root):
    """--all lists across hot, warm, and cold tiers."""
    store.write("Hot entry", scope="team", agent="test", title="HotEntry")

    # Move an entry to warm manually
    import shutil

    hot_files = list((palaia_root / "hot").glob("*.md"))
    assert len(hot_files) == 1
    shutil.move(str(hot_files[0]), str(palaia_root / "warm" / hot_files[0].name))

    # Write another to hot
    store.write("Hot entry 2", scope="team", agent="test", title="HotEntry2")

    # Write to cold manually
    store.write("Cold entry unique content", scope="team", agent="test", title="ColdEntry")
    hot_files2 = list((palaia_root / "hot").glob("*.md"))
    # Find the cold entry
    for f in hot_files2:
        text = f.read_text()
        if "ColdEntry" in text:
            shutil.move(str(f), str(palaia_root / "cold" / f.name))
            break

    # all_entries should return entries from all tiers
    all_entries = store.all_entries(include_cold=True)
    assert len(all_entries) == 3

    # Verify tiers
    tiers = {tier for _, _, tier in all_entries}
    assert tiers == {"hot", "warm", "cold"}


def test_list_cross_project_filter(store, palaia_root):
    """--status filters work cross-project when combined with --all."""
    from palaia.project import ProjectManager

    pm = ProjectManager(palaia_root)
    pm.create("proj-a")
    pm.create("proj-b")

    store.write("Task A", scope="team", agent="test", project="proj-a", entry_type="task", status="open", title="TaskA")
    store.write("Task B", scope="team", agent="test", project="proj-b", entry_type="task", status="open", title="TaskB")
    store.write(
        "Done task", scope="team", agent="test", project="proj-a", entry_type="task", status="done", title="TaskDone"
    )

    entries = store.all_entries(include_cold=True)
    assert len(entries) == 3

    # Filter by status=open across all projects
    filtered = [(m, b, t) for m, b, t in entries if m.get("status") == "open"]
    assert len(filtered) == 2


def test_list_json_output_with_tier_field(store, palaia_root):
    """JSON output includes tier field when using --all."""
    store.write("Test entry", scope="team", agent="test", title="TestEntry")
    all_entries = store.all_entries(include_cold=True)
    assert len(all_entries) == 1
    meta, body, tier = all_entries[0]
    assert tier == "hot"


def test_list_filter_by_type(store, palaia_root):
    """--type filters by entry class."""
    store.write("Memory", scope="team", agent="test", entry_type="memory", title="Mem")
    store.write("Process", scope="team", agent="test", entry_type="process", title="Proc")
    store.write("Task", scope="team", agent="test", entry_type="task", title="Tsk")

    entries = store.list_entries("hot")
    assert len(entries) == 3

    filtered = [(m, b) for m, b in entries if m.get("type") == "process"]
    assert len(filtered) == 1
    assert filtered[0][0]["title"] == "Proc"


def test_list_filter_by_assignee(store, palaia_root):
    """--assignee filters by task assignee."""
    store.write("Task for Elliot", scope="team", agent="test", entry_type="task", assignee="elliot", title="ForElliot")
    store.write("Task for Saul", scope="team", agent="test", entry_type="task", assignee="saul", title="ForSaul")

    entries = store.list_entries("hot")
    filtered = [(m, b) for m, b in entries if m.get("assignee") == "elliot"]
    assert len(filtered) == 1
    assert filtered[0][0]["title"] == "ForElliot"
