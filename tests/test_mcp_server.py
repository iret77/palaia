"""Tests for Palaia MCP server tool handlers."""

from __future__ import annotations

import pytest

from palaia.config import DEFAULT_CONFIG, save_config
from palaia.store import Store

# Skip all if mcp not installed
mcp = pytest.importorskip("mcp")


@pytest.fixture
def palaia_root(tmp_path):
    """Create a minimal .palaia directory with BM25-only config."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()

    config = dict(DEFAULT_CONFIG)
    config["agent"] = "test-agent"
    config["embedding_chain"] = ["bm25"]
    save_config(root, config)
    return root


@pytest.fixture
def palaia_root_with_entries(palaia_root):
    """Create a .palaia directory with some test entries."""
    store = Store(palaia_root)
    store.write(body="Python best practices for API design", tags=["python", "api"], title="API Design")
    store.write(body="JavaScript async patterns", tags=["javascript"], title="JS Async", entry_type="process")
    store.write(
        body="Fix auth bug in login flow",
        tags=["bug"],
        title="Auth Bug",
        entry_type="task",
        status="open",
        priority="high",
    )
    return palaia_root


@pytest.fixture
def server(palaia_root_with_entries):
    """Create a configured MCP server."""
    from palaia.mcp.server import create_server

    return create_server(palaia_root_with_entries)


@pytest.fixture
def readonly_server(palaia_root_with_entries):
    """Create a read-only MCP server."""
    from palaia.mcp.server import create_server

    return create_server(palaia_root_with_entries, read_only=True)


def _get_tool_fn(server, name):
    """Get a tool function by name from the FastMCP server."""
    tools = server._tool_manager._tools
    if name not in tools:
        raise KeyError(f"Tool '{name}' not found. Available: {list(tools.keys())}")
    return tools[name].fn


# ── Tool registration ────────────────────────────────────────────

class TestToolRegistration:
    def test_read_write_tools_registered(self, server):
        tools = server._tool_manager._tools
        expected = {"palaia_search", "palaia_read", "palaia_list", "palaia_status",
                    "palaia_store", "palaia_edit", "palaia_gc"}
        assert expected.issubset(set(tools.keys()))

    def test_readonly_no_write_tools(self, readonly_server):
        tools = readonly_server._tool_manager._tools
        assert "palaia_search" in tools
        assert "palaia_read" in tools
        assert "palaia_list" in tools
        assert "palaia_status" in tools
        assert "palaia_store" not in tools
        assert "palaia_edit" not in tools
        assert "palaia_gc" not in tools


# ── palaia_search ────────────────────────────────────────────────

class TestSearch:
    def test_search_finds_entries(self, server):
        fn = _get_tool_fn(server, "palaia_search")
        result = fn(query="Python API", limit=5)
        assert "result" in result.lower() or "API Design" in result

    def test_search_no_results(self, server):
        fn = _get_tool_fn(server, "palaia_search")
        result = fn(query="xyzzy nonexistent topic 12345")
        assert "no matching" in result.lower() or "0 result" in result.lower() or "found" in result.lower()

    def test_search_with_type_filter(self, server):
        fn = _get_tool_fn(server, "palaia_search")
        result = fn(query="patterns", entry_type="process")
        assert isinstance(result, str)

    def test_search_with_status_filter(self, server):
        fn = _get_tool_fn(server, "palaia_search")
        result = fn(query="bug", status="open")
        assert isinstance(result, str)


# ── palaia_read ──────────────────────────────────────────────────

class TestRead:
    def test_read_entry(self, palaia_root_with_entries, server):
        store = Store(palaia_root_with_entries)
        entries = store.list_entries("hot")
        assert entries
        meta, _ = entries[0]
        entry_id = meta["id"]

        fn = _get_tool_fn(server, "palaia_read")
        result = fn(entry_id=entry_id)
        assert entry_id in result or entry_id[:8] in result

    def test_read_not_found(self, server):
        fn = _get_tool_fn(server, "palaia_read")
        result = fn(entry_id="00000000-0000-0000-0000-000000000000")
        assert "not found" in result.lower()


# ── palaia_list ──────────────────────────────────────────────────

class TestList:
    def test_list_hot(self, server):
        fn = _get_tool_fn(server, "palaia_list")
        result = fn(tier="hot")
        assert "3 entries" in result or "entries in hot" in result

    def test_list_empty_tier(self, server):
        fn = _get_tool_fn(server, "palaia_list")
        result = fn(tier="cold")
        assert "no entries" in result.lower() or "0 entries" in result.lower()

    def test_list_with_type_filter(self, server):
        fn = _get_tool_fn(server, "palaia_list")
        result = fn(entry_type="task")
        assert isinstance(result, str)


# ── palaia_status ────────────────────────────────────────────────

class TestStatus:
    def test_status(self, server):
        fn = _get_tool_fn(server, "palaia_status")
        result = fn()
        assert "hot=" in result
        assert "Embedding" in result or "embed" in result.lower()


# ── palaia_store ─────────────────────────────────────────────────

class TestStore:
    def test_store_entry(self, server, palaia_root_with_entries):
        fn = _get_tool_fn(server, "palaia_store")
        result = fn(content="New memory about testing", title="Test Memory", tags=["test"])
        assert "stored" in result.lower() or "entry" in result.lower()

        # Verify it was actually stored
        store = Store(palaia_root_with_entries)
        entries = store.list_entries("hot")
        assert len(entries) == 4

    def test_store_task(self, server):
        fn = _get_tool_fn(server, "palaia_store")
        result = fn(
            content="Implement new feature",
            entry_type="task",
            status="open",
            priority="medium",
        )
        assert "stored" in result.lower()


# ── palaia_edit ──────────────────────────────────────────────────

class TestEdit:
    def test_edit_entry(self, palaia_root_with_entries, server):
        store = Store(palaia_root_with_entries)
        entries = store.list_entries("hot")
        meta, _ = entries[0]
        entry_id = meta["id"]

        fn = _get_tool_fn(server, "palaia_edit")
        result = fn(entry_id=entry_id, title="Updated Title")
        assert "updated" in result.lower()

    def test_edit_not_found(self, server):
        fn = _get_tool_fn(server, "palaia_edit")
        result = fn(entry_id="00000000-0000-0000-0000-000000000000")
        assert "not found" in result.lower()


# ── palaia_gc ────────────────────────────────────────────────────

class TestGC:
    def test_gc_dry_run(self, server):
        fn = _get_tool_fn(server, "palaia_gc")
        result = fn(dry_run=True)
        assert isinstance(result, str)
        # With only 3 entries, nothing should move
        assert "nothing to do" in result.lower() or "dry run" in result.lower()


# ── Server creation ─────────────────────────────────────────────

class TestServerCreation:
    def test_create_server_returns_fastmcp(self, palaia_root):
        from mcp.server.fastmcp import FastMCP

        from palaia.mcp.server import create_server

        server = create_server(palaia_root)
        assert isinstance(server, FastMCP)

    def test_create_readonly_server(self, palaia_root):
        from palaia.mcp.server import create_server

        server = create_server(palaia_root, read_only=True)
        tools = server._tool_manager._tools
        assert "palaia_search" in tools
        assert "palaia_store" not in tools
