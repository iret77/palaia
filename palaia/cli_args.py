"""Argparse setup for Palaia CLI — extracted from cli.py for maintainability."""

from __future__ import annotations

import argparse

from palaia import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="palaia",
        description="Palaia — Local, cloud-free memory for OpenClaw agents.",
    )
    parser.add_argument("--version", action="version", version=f"palaia {__version__}")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")

    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Initialize .palaia directory")
    p_init.add_argument("--agent", default=None, help="Agent name (optional, auto-detected from OpenClaw config)")
    p_init.add_argument("--path", default=None, help="Target directory")
    p_init.add_argument("--json", action="store_true", help="Output as JSON")
    p_init.add_argument(
        "--isolated",
        action="store_const",
        const="isolated",
        dest="store_mode",
        help="Use isolated stores per agent (default: shared)",
    )
    p_init.add_argument(
        "--reset",
        action="store_true",
        help="Reset config to defaults (preserves entries)",
    )
    p_init.add_argument(
        "--capture-level",
        default=None,
        dest="capture_level",
        choices=["off", "minimal", "normal", "aggressive", "sparsam", "aggressiv"],
        help="Auto-capture level for OpenClaw plugin (off|minimal|normal|aggressive)",
    )

    # write
    p_write = sub.add_parser("write", help="Write a memory entry")
    p_write.add_argument("text", help="Memory content")
    p_write.add_argument("--scope", default=None, help="Scope tag")
    p_write.add_argument("--agent", default=None, help="Agent name")
    p_write.add_argument("--tags", default=None, help="Comma-separated tags")
    p_write.add_argument("--title", default=None, help="Entry title")
    p_write.add_argument("--project", default=None, help="Assign to project (uses project default scope)")
    p_write.add_argument("--type", default=None, choices=["memory", "process", "task"], help="Entry class")
    p_write.add_argument(
        "--status", default=None, choices=["open", "in-progress", "done", "wontfix"], help="Task status"
    )
    p_write.add_argument(
        "--priority", default=None, choices=["critical", "high", "medium", "low"], help="Task priority"
    )
    p_write.add_argument("--assignee", default=None, help="Task assignee")
    p_write.add_argument("--due-date", default=None, dest="due_date", help="Task due date (ISO-8601)")
    p_write.add_argument("--instance", default=None, help="Session identity name")
    p_write.add_argument("--json", action="store_true", help="Output as JSON")

    # edit
    p_edit = sub.add_parser("edit", help="Edit an existing memory entry")
    p_edit.add_argument("entry_id", help="Entry UUID (or short prefix)")
    p_edit.add_argument("text", nargs="?", default=None, help="New content (optional)")
    p_edit.add_argument("--agent", default=None, help="Agent name (for scope enforcement)")
    p_edit.add_argument("--tags", default=None, help="New comma-separated tags")
    p_edit.add_argument("--title", default=None, help="New title")
    p_edit.add_argument("--type", default=None, choices=["memory", "process", "task"], help="Change entry class")
    p_edit.add_argument(
        "--status", default=None, choices=["open", "in-progress", "done", "wontfix"], help="Set task status"
    )
    p_edit.add_argument(
        "--priority", default=None, choices=["critical", "high", "medium", "low"], help="Set task priority"
    )
    p_edit.add_argument("--assignee", default=None, help="Set task assignee")
    p_edit.add_argument("--due-date", default=None, dest="due_date", help="Set task due date (ISO-8601)")
    p_edit.add_argument("--json", action="store_true", help="Output as JSON")

    # query
    p_query = sub.add_parser("query", help="Search memories")
    p_query.add_argument("query", help="Search query")
    p_query.add_argument("--limit", type=int, default=10, help="Max results")
    p_query.add_argument("--all", action="store_true", help="Include COLD tier")
    p_query.add_argument("--project", default=None, help="Filter by project")
    p_query.add_argument("--agent", default=None, help="Agent name (for scope filtering)")
    p_query.add_argument("--type", default=None, choices=["memory", "process", "task"], help="Filter by entry class")
    p_query.add_argument(
        "--status", default=None, choices=["open", "in-progress", "done", "wontfix"], help="Filter by task status"
    )
    p_query.add_argument(
        "--priority", default=None, choices=["critical", "high", "medium", "low"], help="Filter by priority"
    )
    p_query.add_argument("--assignee", default=None, help="Filter by assignee")
    p_query.add_argument("--instance", default=None, help="Filter by session identity")
    p_query.add_argument("--before", default=None, help="Only entries created before this ISO timestamp")
    p_query.add_argument("--after", default=None, help="Only entries created after this ISO timestamp")
    p_query.add_argument(
        "--cross-project", action="store_true", dest="cross_project", help="Search across all projects"
    )
    p_query.add_argument("--rag", action="store_true", help="Output as RAG context block")
    p_query.add_argument("--json", action="store_true", help="Output as JSON")

    # ingest
    p_ingest = sub.add_parser(
        "ingest", help="Ingest documents for RAG search (creates a copy; source files are NOT modified or deleted)"
    )
    p_ingest.add_argument("source", help="File path, URL, or directory to ingest")
    p_ingest.add_argument("--project", default=None, help="Assign to project")
    p_ingest.add_argument("--scope", default=None, help="Scope (default: private)")
    p_ingest.add_argument("--tags", default=None, help="Comma-separated extra tags")
    p_ingest.add_argument("--chunk-size", type=int, default=500, help="Words per chunk (default: 500)")
    p_ingest.add_argument("--chunk-overlap", type=int, default=50, help="Overlap words (default: 50)")
    p_ingest.add_argument("--dry-run", action="store_true", help="Preview without storing")
    p_ingest.add_argument("--json", action="store_true", help="Output as JSON")

    # get
    p_get = sub.add_parser("get", help="Read a specific memory entry")
    p_get.add_argument("path", help="Entry UUID or path (e.g. hot/uuid.md)")
    p_get.add_argument("--from", type=int, default=None, dest="from_line", help="Start from line number (1-indexed)")
    p_get.add_argument("--lines", type=int, default=None, help="Number of lines to return")
    p_get.add_argument("--agent", default=None, help="Agent name (for scope filtering)")
    p_get.add_argument("--json", action="store_true", help="Output as JSON")

    # recover
    p_recover = sub.add_parser("recover", help="Run WAL recovery")
    p_recover.add_argument("--json", action="store_true", help="Output as JSON")

    # list
    p_list = sub.add_parser("list", help="List entries in a tier")
    p_list.add_argument("--tier", default=None, choices=["hot", "warm", "cold"], help="Tier to list (default: hot)")
    p_list.add_argument("--all", action="store_true", help="List across all tiers (hot+warm+cold)")
    p_list.add_argument("--project", default=None, help="Filter by project")
    p_list.add_argument("--tag", default=None, action="append", help="Filter by tag (repeatable, AND logic)")
    p_list.add_argument("--scope", default=None, help="Filter by scope")
    p_list.add_argument("--agent", default=None, help="Filter by agent")
    p_list.add_argument("--type", default=None, choices=["memory", "process", "task"], help="Filter by entry class")
    p_list.add_argument(
        "--status", default=None, choices=["open", "in-progress", "done", "wontfix"], help="Filter by task status"
    )
    p_list.add_argument(
        "--priority", default=None, choices=["critical", "high", "medium", "low"], help="Filter by priority"
    )
    p_list.add_argument("--assignee", default=None, help="Filter by assignee")
    p_list.add_argument("--instance", default=None, help="Filter by session identity")
    p_list.add_argument("--before", default=None, help="Only entries created before this ISO timestamp")
    p_list.add_argument("--after", default=None, help="Only entries created after this ISO timestamp")
    p_list.add_argument("--cross-project", action="store_true", dest="cross_project", help="List across all projects")
    p_list.add_argument("--json", action="store_true", help="Output as JSON")

    # status
    p_status = sub.add_parser("status", help="Show system status")
    p_status.add_argument("--json", action="store_true", help="Output as JSON")

    # warmup
    p_warmup = sub.add_parser("warmup", help="Pre-download embedding models")
    p_warmup.add_argument("--json", action="store_true", help="Output as JSON")

    # gc
    p_gc = sub.add_parser("gc", help="Run garbage collection / tier rotation")
    p_gc.add_argument("--dry-run", action="store_true", help="Show what would be pruned without changing anything")
    p_gc.add_argument("--budget", action="store_true", help="Prune entries to meet configured budget limits")
    p_gc.add_argument("--json", action="store_true", help="Output as JSON")

    # project
    _add_project_subparser(sub)

    # memo
    _add_memo_subparser(sub)

    # lock
    p_lock = sub.add_parser("lock", help="Manage project locks")
    p_lock.add_argument(
        "action_or_project",
        nargs="?",
        default=None,
        help="Subcommand (status|renew|break|list) or project name for acquire shorthand",
    )
    p_lock.add_argument("project", nargs="?", default=None, help="Project name (for status/renew/break subcommands)")
    p_lock.add_argument("--agent", default=None, help="Agent name")
    p_lock.add_argument("--reason", default="", help="Reason for locking")
    p_lock.add_argument("--ttl", type=int, default=None, help="TTL in seconds")
    p_lock.add_argument("--json", action="store_true", help="Output as JSON")

    # unlock
    p_unlock = sub.add_parser("unlock", help="Release a project lock")
    p_unlock.add_argument("project", help="Project name")
    p_unlock.add_argument("--json", action="store_true", help="Output as JSON")

    # instance
    p_instance = sub.add_parser("instance", help="Manage session identity")
    instance_sub = p_instance.add_subparsers(dest="instance_action")
    p_instance_set = instance_sub.add_parser("set", help="Set session instance name")
    p_instance_set.add_argument("name", help="Instance name (e.g. Claw-Palaia)")
    p_instance_set.add_argument("--json", action="store_true", help="Output as JSON")
    p_instance_get = instance_sub.add_parser("get", help="Show current instance")
    p_instance_get.add_argument("--json", action="store_true", help="Output as JSON")
    p_instance_clear = instance_sub.add_parser("clear", help="Clear session instance")
    p_instance_clear.add_argument("--json", action="store_true", help="Output as JSON")

    # setup
    p_setup = sub.add_parser("setup", help="Multi-agent setup")
    p_setup.add_argument("--multi-agent", default=None, help="Path to agents directory")
    p_setup.add_argument("--dry-run", action="store_true", help="Preview without creating symlinks")
    p_setup.add_argument("--json", action="store_true", help="Output as JSON")

    # doctor
    p_doctor = sub.add_parser("doctor", help="Diagnose Palaia instance and detect legacy systems")
    p_doctor.add_argument("--fix", action="store_true", help="Show guided fix instructions for each warning")
    p_doctor.add_argument("--json", action="store_true", help="Output as JSON")

    # export (deprecated)
    p_export = sub.add_parser("export", help="Export public entries")
    p_export.add_argument("--remote", default=None, help="Git remote URL")
    p_export.add_argument("--branch", default=None, help="Branch name")
    p_export.add_argument("--output", default=None, help="Output directory")
    p_export.add_argument("--project", default=None, help="Export only project entries")
    p_export.add_argument("--agent", default=None, help="Agent name (for scope filtering)")
    p_export.add_argument("--json", action="store_true", help="Output as JSON")

    # import (deprecated)
    p_import = sub.add_parser("import", help="Import entries from export")
    p_import.add_argument("source", help="Path or git URL to import from")
    p_import.add_argument("--dry-run", action="store_true", help="Preview without writing")
    p_import.add_argument("--json", action="store_true", help="Output as JSON")

    # detect
    p_detect = sub.add_parser("detect", help="Detect available embedding providers")
    p_detect.add_argument("--json", action="store_true", help="Output as JSON")

    # config
    _add_config_subparser(sub)

    # process
    p_process = sub.add_parser("process", help="Manage process execution runs")
    process_sub = p_process.add_subparsers(dest="process_action")
    p_proc_run = process_sub.add_parser("run", help="Run or inspect a process entry")
    p_proc_run.add_argument("entry_id", help="Entry UUID or short prefix")
    p_proc_run.add_argument("--step", type=int, default=None, help="Step index (0-based)")
    p_proc_run.add_argument("--done", action="store_true", help="Mark step as done (requires --step)")
    p_proc_run.add_argument("--agent", default=None, help="Agent name")
    p_proc_run.add_argument("--json", action="store_true", help="Output as JSON")
    p_proc_list = process_sub.add_parser("list", help="List active process runs")
    p_proc_list.add_argument("--json", action="store_true", help="Output as JSON")

    # package
    p_package = sub.add_parser("package", help="Export/import knowledge packages")
    package_sub = p_package.add_subparsers(dest="package_action")
    p_pkg_export = package_sub.add_parser("export", help="Export project knowledge as package")
    p_pkg_export.add_argument("project", help="Project name to export")
    p_pkg_export.add_argument("--output", default=None, help="Output file path")
    p_pkg_export.add_argument("--types", default=None, help="Comma-separated entry types to include")
    p_pkg_export.add_argument("--json", action="store_true", help="Output as JSON")
    p_pkg_import = package_sub.add_parser("import", help="Import knowledge package")
    p_pkg_import.add_argument("file", help="Package file path")
    p_pkg_import.add_argument("--project", default=None, help="Override target project")
    p_pkg_import.add_argument("--merge", default="skip", choices=["skip", "overwrite", "append"], help="Merge strategy")
    p_pkg_import.add_argument("--agent", default=None, help="Agent name to attribute imported entries to")
    p_pkg_import.add_argument("--json", action="store_true", help="Output as JSON")
    p_pkg_info = package_sub.add_parser("info", help="Show package metadata")
    p_pkg_info.add_argument("file", help="Package file path")
    p_pkg_info.add_argument("--json", action="store_true", help="Output as JSON")

    # upgrade
    sub.add_parser("upgrade", help="Upgrade palaia to latest version (auto-detects install method and extras)")

    # embed-server
    p_embed = sub.add_parser("embed-server", help="Start long-lived embedding server (JSON-RPC)")
    p_embed.add_argument("--socket", action="store_true", help="Use Unix socket transport instead of stdio")
    p_embed.add_argument("--daemon", action="store_true", help="Start as detached background process (requires --socket)")
    p_embed.add_argument("--idle-timeout", type=int, default=0, help="Auto-shutdown after N seconds idle (0=never, default for --daemon: 1800)")
    p_embed.add_argument("--stop", action="store_true", help="Stop a running embed-server daemon")
    p_embed.add_argument("--status", action="store_true", help="Check if embed-server is running")

    # mcp-server
    p_mcp = sub.add_parser("mcp-server", help="Start MCP server for Claude Desktop, Cursor, etc.")
    p_mcp.add_argument("--root", help="Path to .palaia directory")
    p_mcp.add_argument("--read-only", action="store_true", help="Disable write operations")

    # skill
    p_skill = sub.add_parser("skill", help="Print the SKILL.md agent documentation")
    p_skill.add_argument("--json", action="store_true", help="Output as JSON")

    # migrate
    p_migrate = sub.add_parser("migrate", help="Import from external memory formats or suggest type assignments")
    p_migrate.add_argument("source", nargs="?", default=None, help="Source path (directory or file)")
    p_migrate.add_argument("--dry-run", action="store_true", help="Preview without writing")
    p_migrate.add_argument("--suggest", action="store_true", help="Suggest entry type assignments for untyped entries")
    p_migrate.add_argument(
        "--format",
        default=None,
        dest="format_name",
        choices=["smart-memory", "flat-file", "json-memory", "generic-md"],
        help="Force source format",
    )
    p_migrate.add_argument("--scope", default=None, help="Override scope for all entries")
    p_migrate.add_argument("--json", action="store_true", help="Output as JSON")

    # priorities
    _add_priorities_subparser(sub)

    # curate
    p_curate = sub.add_parser("curate", help="Knowledge curation for instance migration")
    curate_sub = p_curate.add_subparsers(dest="curate_action")
    p_curate_analyze = curate_sub.add_parser("analyze", help="Analyze entries and generate curation report")
    p_curate_analyze.add_argument("--project", default=None, help="Filter by project")
    p_curate_analyze.add_argument("--agent", default=None, help="Filter by agent")
    p_curate_analyze.add_argument("--output", default=None, help="Output report path")
    p_curate_analyze.add_argument("--json", action="store_true", help="Output as JSON")
    p_curate_apply = curate_sub.add_parser("apply", help="Apply edited curation report")
    p_curate_apply.add_argument("report", help="Path to edited curation report")
    p_curate_apply.add_argument("--output", default=None, help="Output package path")
    p_curate_apply.add_argument("--json", action="store_true", help="Output as JSON")

    # sync
    p_sync = sub.add_parser("sync", help="Sync entries (export/import)")
    sync_sub = p_sync.add_subparsers(dest="sync_action")
    p_sync_export = sync_sub.add_parser("export", help="Export public entries")
    p_sync_export.add_argument("--remote", default=None, help="Git remote URL")
    p_sync_export.add_argument("--branch", default=None, help="Branch name")
    p_sync_export.add_argument("--output", default=None, help="Output directory")
    p_sync_export.add_argument("--project", default=None, help="Export only project entries")
    p_sync_export.add_argument("--agent", default=None, help="Agent name (for scope filtering)")
    p_sync_export.add_argument("--json", action="store_true", help="Output as JSON")
    p_sync_import = sync_sub.add_parser("import", help="Import entries from export")
    p_sync_import.add_argument("source", help="Path or git URL to import from")
    p_sync_import.add_argument("--dry-run", action="store_true", help="Preview without writing")
    p_sync_import.add_argument("--json", action="store_true", help="Output as JSON")

    return parser


def _add_project_subparser(sub):
    """Add project subcommand and its subparsers."""
    p_project = sub.add_parser("project", help="Manage projects")
    project_sub = p_project.add_subparsers(dest="project_action")

    p_proj_create = project_sub.add_parser("create", help="Create a project")
    p_proj_create.add_argument("name", help="Project name")
    p_proj_create.add_argument("--description", default=None, help="Project description")
    p_proj_create.add_argument("--default-scope", default=None, help="Default scope for entries")
    p_proj_create.add_argument("--owner", default=None, help="Project owner")
    p_proj_create.add_argument("--json", action="store_true", help="Output as JSON")

    p_proj_list = project_sub.add_parser("list", help="List projects")
    p_proj_list.add_argument("--owner", default=None, help="Filter by owner")
    p_proj_list.add_argument("--json", action="store_true", help="Output as JSON")

    p_proj_show = project_sub.add_parser("show", help="Show project details")
    p_proj_show.add_argument("name", help="Project name")
    p_proj_show.add_argument("--json", action="store_true", help="Output as JSON")

    p_proj_write = project_sub.add_parser("write", help="Write entry to project")
    p_proj_write.add_argument("name", help="Project name")
    p_proj_write.add_argument("text", help="Memory content")
    p_proj_write.add_argument("--scope", default=None, help="Override scope")
    p_proj_write.add_argument("--agent", default=None, help="Agent name")
    p_proj_write.add_argument("--tags", default=None, help="Comma-separated tags")
    p_proj_write.add_argument("--title", default=None, help="Entry title")
    p_proj_write.add_argument("--json", action="store_true", help="Output as JSON")

    p_proj_query = project_sub.add_parser("query", help="Search within project")
    p_proj_query.add_argument("name", help="Project name")
    p_proj_query.add_argument("query", help="Search query")
    p_proj_query.add_argument("--limit", type=int, default=10, help="Max results")
    p_proj_query.add_argument("--json", action="store_true", help="Output as JSON")

    p_proj_scope = project_sub.add_parser("set-scope", help="Change project default scope")
    p_proj_scope.add_argument("name", help="Project name")
    p_proj_scope.add_argument("scope_value", help="New default scope")
    p_proj_scope.add_argument("--json", action="store_true", help="Output as JSON")

    p_proj_owner = project_sub.add_parser("set-owner", help="Set or clear project owner")
    p_proj_owner.add_argument("name", help="Project name")
    p_proj_owner.add_argument("owner_value", nargs="?", default=None, help="New owner name")
    p_proj_owner.add_argument("--clear", action="store_true", help="Remove owner")
    p_proj_owner.add_argument("--json", action="store_true", help="Output as JSON")

    p_proj_delete = project_sub.add_parser("delete", help="Delete project (entries preserved)")
    p_proj_delete.add_argument("name", help="Project name")
    p_proj_delete.add_argument("--json", action="store_true", help="Output as JSON")


def _add_memo_subparser(sub):
    """Add memo subcommand and its subparsers."""
    p_memo = sub.add_parser("memo", help="Inter-agent messaging")
    memo_sub = p_memo.add_subparsers(dest="memo_action")

    p_memo_send = memo_sub.add_parser("send", help="Send a memo to an agent")
    p_memo_send.add_argument("to", help="Recipient agent name")
    p_memo_send.add_argument("message", help="Message body")
    p_memo_send.add_argument("--priority", default="normal", choices=["normal", "high"], help="Priority level")
    p_memo_send.add_argument("--ttl-hours", type=int, default=72, help="TTL in hours (default: 72)")
    p_memo_send.add_argument("--agent", default=None, help="Sender agent name")
    p_memo_send.add_argument("--json", action="store_true", help="Output as JSON")

    p_memo_broadcast = memo_sub.add_parser("broadcast", help="Broadcast memo to all agents")
    p_memo_broadcast.add_argument("message", help="Message body")
    p_memo_broadcast.add_argument("--priority", default="normal", choices=["normal", "high"], help="Priority level")
    p_memo_broadcast.add_argument("--ttl-hours", type=int, default=72, help="TTL in hours (default: 72)")
    p_memo_broadcast.add_argument("--agent", default=None, help="Sender agent name")
    p_memo_broadcast.add_argument("--json", action="store_true", help="Output as JSON")

    p_memo_inbox = memo_sub.add_parser("inbox", help="Show inbox")
    p_memo_inbox.add_argument("--all", action="store_true", help="Include read memos")
    p_memo_inbox.add_argument("--agent", default=None, help="Agent name")
    p_memo_inbox.add_argument("--json", action="store_true", help="Output as JSON")

    p_memo_ack = memo_sub.add_parser("ack", help="Acknowledge memo(s)")
    p_memo_ack.add_argument("memo_id", nargs="?", default=None, help="Memo ID to acknowledge")
    p_memo_ack.add_argument("--all", action="store_true", help="Acknowledge all unread memos")
    p_memo_ack.add_argument("--agent", default=None, help="Agent name (for --all)")
    p_memo_ack.add_argument("--json", action="store_true", help="Output as JSON")

    p_memo_gc = memo_sub.add_parser("gc", help="Remove expired and read memos")
    p_memo_gc.add_argument("--json", action="store_true", help="Output as JSON")


def _add_config_subparser(sub):
    """Add config subcommand and its subparsers."""
    p_config = sub.add_parser("config", help="Get or set configuration")
    config_sub = p_config.add_subparsers(dest="action")
    p_config_get = config_sub.add_parser("get", help="Get a config value")
    p_config_get.add_argument("key", help="Config key")
    p_config_get.add_argument("--json", action="store_true", help="Output as JSON")
    p_config_set = config_sub.add_parser("set", help="Set a config value")
    p_config_set.add_argument("key", help="Config key")
    p_config_set.add_argument("value", help="Config value")
    p_config_set.add_argument("--json", action="store_true", help="Output as JSON")
    p_config_list = config_sub.add_parser("list", help="List all config values")
    p_config_list.add_argument("--json", action="store_true", help="Output as JSON")
    p_config_set_chain = config_sub.add_parser("set-chain", help="Set the embedding fallback chain")
    p_config_set_chain.add_argument("providers", nargs="+", help="Provider names in priority order")
    p_config_set_chain.add_argument("--json", action="store_true", help="Output as JSON")

    p_config_set_alias = config_sub.add_parser("set-alias", help="Set an agent alias")
    p_config_set_alias.add_argument("from_name", help="Alias source name (e.g. 'default')")
    p_config_set_alias.add_argument("to_name", help="Alias target name (e.g. 'HAL')")
    p_config_set_alias.add_argument("--json", action="store_true", help="Output as JSON")

    p_config_get_aliases = config_sub.add_parser("get-aliases", help="Show all agent aliases")
    p_config_get_aliases.add_argument("--json", action="store_true", help="Output as JSON")

    p_config_remove_alias = config_sub.add_parser("remove-alias", help="Remove an agent alias")
    p_config_remove_alias.add_argument("from_name", help="Alias source name to remove")
    p_config_remove_alias.add_argument("--json", action="store_true", help="Output as JSON")


def _add_priorities_subparser(sub):
    """Add priorities subcommand and its subparsers."""
    p_priorities = sub.add_parser("priorities", help="View and manage injection priorities")
    priorities_sub = p_priorities.add_subparsers(dest="priorities_action")
    p_priorities.add_argument("query", nargs="?", default=None, help="Query to simulate injection")
    p_priorities.add_argument("--agent", default=None, help="Agent name")
    p_priorities.add_argument("--project", default=None, help="Project name")
    p_priorities.add_argument("--limit", type=int, default=10, help="Max entries (default: 10)")
    p_priorities.add_argument("--all", action="store_true", dest="include_cold", help="Include cold tier")
    p_priorities.add_argument("--json", action="store_true", help="Output as JSON")

    p_prio_block = priorities_sub.add_parser("block", help="Block an entry from injection")
    p_prio_block.add_argument("entry_id", help="Entry UUID (full or short prefix)")
    p_prio_block.add_argument("--agent", default=None, help="Block only for this agent")
    p_prio_block.add_argument("--project", default=None, help="Block only for this project")
    p_prio_block.add_argument("--json", action="store_true", help="Output as JSON")

    p_prio_unblock = priorities_sub.add_parser("unblock", help="Unblock an entry")
    p_prio_unblock.add_argument("entry_id", help="Entry UUID")
    p_prio_unblock.add_argument("--agent", default=None, help="Agent scope")
    p_prio_unblock.add_argument("--project", default=None, help="Project scope")
    p_prio_unblock.add_argument("--json", action="store_true", help="Output as JSON")

    p_prio_set = priorities_sub.add_parser("set", help="Set a priority parameter")
    p_prio_set.add_argument("key", help="Config key (recallMinScore, maxInjectedChars, tier, typeWeight.process, ...)")
    p_prio_set.add_argument("value", help="Value to set")
    p_prio_set.add_argument("--agent", default=None, help="Set for this agent only")
    p_prio_set.add_argument("--project", default=None, help="Set for this project only")
    p_prio_set.add_argument("--json", action="store_true", help="Output as JSON")

    p_prio_list = priorities_sub.add_parser("list-blocked", help="List blocked entries")
    p_prio_list.add_argument("--agent", default=None, help="Agent scope")
    p_prio_list.add_argument("--project", default=None, help="Project scope")
    p_prio_list.add_argument("--json", action="store_true", help="Output as JSON")

    p_prio_reset = priorities_sub.add_parser("reset", help="Reset priorities")
    p_prio_reset.add_argument("--agent", default=None, help="Reset only this agent's overrides")
    p_prio_reset.add_argument("--project", default=None, help="Reset only this project's overrides")
    p_prio_reset.add_argument("--json", action="store_true", help="Output as JSON")
