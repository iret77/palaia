"""Palaia CLI entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Suppress noisy HuggingFace / tokenizers / safetensors warnings before any ML imports.
# Must run before palaia.* imports which may trigger sentence_transformers loading.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")

import logging as _logging  # noqa: E402
import warnings as _warnings  # noqa: E402

_warnings.filterwarnings("ignore", module="huggingface_hub")
_warnings.filterwarnings("ignore", module="transformers")
_warnings.filterwarnings("ignore", module="sentence_transformers")
for _name in ("sentence_transformers", "transformers", "huggingface_hub", "torch", "safetensors"):
    _logging.getLogger(_name).setLevel(_logging.ERROR)

from palaia import __version__  # noqa: E402
from palaia.cli_helpers import (  # noqa: E402
    check_version_nag,
    detect_current_agent as _detect_current_agent,
    json_out as _json_out,
    nudge_hint as _nudge_hint,
    resolve_agent as _resolve_agent,
    resolve_agent_names as _resolve_agent_names,
    resolve_instance_for_write as _resolve_instance_for_write,
)
from palaia.config import (  # noqa: E402
    find_palaia_root,
    get_aliases,
    get_root,
    is_initialized,
)
from palaia.doctor import apply_fixes, format_doctor_report, run_doctor  # noqa: E402
from palaia.migrate import format_result, migrate  # noqa: E402
from palaia.store import Store  # noqa: E402
from palaia.ui import (  # noqa: E402
    print_header,
    relative_time,
    section,
    table_kv,
    table_multi,
)
# Import large cmd_* functions from cli_commands
from palaia.cli_commands import (  # noqa: E402
    cmd_config,
    cmd_detect,
    cmd_list,
    cmd_priorities,
    cmd_project,
    cmd_query,
    cmd_status,
)


# Commands that require a valid init (agent identity set)
GATED_COMMANDS = frozenset(
    {
        "write",
        "query",
        "list",
        "edit",
        "memo",
        "gc",
        "export",
        "import",
        "ingest",
        "get",
        "recover",
        "status",
        "project",
        "process",
        "package",
        "lock",
        "unlock",
        "setup",
        "warmup",
        "migrate",
        "embed-server",
        "priorities",
        "curate",
        "sync",
    }
)

# Commands that are always allowed without init
UNGATED_COMMANDS = frozenset(
    {
        "init",
        "detect",
        "doctor",
        "config",
        "instance",
        "skill",
    }
)


def _check_gatekeeper(command: str) -> bool:
    """Check if the command requires init and if init is valid.

    Returns True if the command can proceed, False if it should be blocked.
    Prints error message and returns False if blocked.
    """
    if command in UNGATED_COMMANDS:
        return True
    if command not in GATED_COMMANDS:
        return True  # Unknown commands pass through (argparse will handle them)

    root = find_palaia_root()
    if root is None:
        print("Palaia not initialized. Run: palaia init", file=sys.stderr)
        return False
    if not is_initialized(root):
        print("Palaia not initialized. Run: palaia init", file=sys.stderr)
        return False
    return True


def _memo_nudge(args) -> None:
    """Check for unread memos and print a nudge if any exist."""
    from palaia.cli_nudge import memo_nudge
    memo_nudge(args, resolve_agent_fn=_resolve_agent, get_root_fn=get_root, get_aliases_fn=get_aliases)


def _process_nudge(context_text: str, context_tags: list[str] | None, args) -> None:
    """Check for process entries relevant to the current operation and nudge."""
    from palaia.cli_nudge import process_nudge
    process_nudge(context_text, context_tags, args, get_root_fn=get_root)


# Backward-compat: agent detection moved to services.admin
from palaia.services.admin import (  # noqa: E402
    _AgentDetectResult,
    _detect_agents,
    _detect_agent_from_openclaw_config,
    _detect_agent_from_openclaw_config_ext,
    CAPTURE_LEVEL_MAP,
)


def cmd_init(args):
    """Initialize .palaia directory."""
    from palaia.services.admin import init_palaia

    result = init_palaia(
        path=getattr(args, "path", None),
        agent=getattr(args, "agent", None),
        store_mode=getattr(args, "store_mode", None),
        capture_level=getattr(args, "capture_level", None),
        reset=getattr(args, "reset", False),
    )

    # For re-init with existing chain (early return path)
    if result["status"] == "updated" and "embedding_chain" not in result:
        if _json_out({"status": "updated", "path": result["path"], "agent": result.get("agent")}, args):
            return 0
        # Print messages from service
        if not getattr(args, "json", False):
            for msg in result.get("messages", []):
                print(msg)
        print(f"Updated config: {result['path']}")
        if result.get("agent"):
            print(f"Agent: {result['agent']}")
        return 0

    # Fresh init or re-init with chain reconfiguration
    if result["status"] == "created":
        if _json_out(
            {
                "status": "created",
                "path": result["path"],
                "embedding_chain": result.get("embedding_chain", []),
                "agents": result.get("agents", []),
                "store_mode": result.get("store_mode", "shared"),
            },
            args,
        ):
            return 0
        print(f"Initialized Palaia at {result['path']}")
        if result.get("used_default"):
            print("Initialized with agent: default (use --agent NAME to customize)")

    # Print all messages from service (chain info, capture level, setup instructions)
    if not getattr(args, "json", False):
        for msg in result.get("messages", []):
            print(msg)

    return 0


def cmd_write(args):
    """Write a memory entry."""
    from palaia.services.write import write_entry

    check_version_nag()
    root = get_root()
    agent = _resolve_agent(args)
    instance = _resolve_instance_for_write(args)
    tags = args.tags.split(",") if args.tags else None

    result = write_entry(
        root,
        body=args.text,
        scope=args.scope,
        agent=agent,
        tags=tags,
        title=args.title,
        project=getattr(args, "project", None),
        entry_type=getattr(args, "type", None),
        status=getattr(args, "status", None),
        priority=getattr(args, "priority", None),
        assignee=getattr(args, "assignee", None),
        due_date=getattr(args, "due_date", None),
        instance=instance,
    )

    # Handle error from service (e.g. private scope without agent)
    if "error" in result:
        if _json_out({"error": result["error"]}, args):
            return 1
        print(f"Error: {result['error']}", file=sys.stderr)
        return 1

    # Recovery message
    if result.get("recovered") and not getattr(args, "json", False):
        print(f"Recovered {result['recovered']} pending entries from WAL.")

    nudge_messages = result.get("nudge", [])
    significance_detected = result.get("significance", [])

    if _json_out(
        {
            "id": result["id"],
            "tier": result["tier"],
            "scope": result["scope"],
            "deduplicated": result["deduplicated"],
            **({"nudge": nudge_messages} if nudge_messages else {}),
            **({"significance": significance_detected} if significance_detected else {}),
        },
        args,
    ):
        return 0

    print(f"Written: {result['id']}")

    if significance_detected:
        tags_str = ", ".join(significance_detected)
        print(f"\nDetected significance: [{tags_str}]. Use --tags to confirm.", file=sys.stderr)

    for nudge_msg in nudge_messages:
        print(f"\nHint: {nudge_msg}", file=sys.stderr)

    _memo_nudge(args)

    write_title = getattr(args, "title", None) or ""
    write_tags = args.tags.split(",") if args.tags else []
    _process_nudge(f"{write_title} {args.text}", write_tags, args)

    return 0


def cmd_edit(args):
    """Edit an existing memory entry."""
    from palaia.services.write import edit_entry

    check_version_nag()
    root = get_root()
    agent = _resolve_agent(args)
    body = getattr(args, "text", None)
    tags = args.tags.split(",") if getattr(args, "tags", None) else None

    result = edit_entry(
        root,
        args.entry_id,
        body=body,
        agent=agent,
        tags=tags,
        title=getattr(args, "title", None),
        status=getattr(args, "status", None),
        priority=getattr(args, "priority", None),
        assignee=getattr(args, "assignee", None),
        due_date=getattr(args, "due_date", None),
        entry_type=getattr(args, "type", None),
    )

    if "error" in result:
        if _json_out({"error": result["error"]}, args):
            return 1
        print(f"Error: {result['error']}", file=sys.stderr)
        return 1

    if _json_out(result, args):
        return 0

    print(f"Updated: {result['id']}")
    changes = []
    if body is not None:
        changes.append("content")
    if tags is not None:
        changes.append("tags")
    for field in ("title", "status", "priority", "assignee", "due_date", "type"):
        if getattr(args, field, None) is not None:
            changes.append(field)
    if changes:
        print(f"  Changed: {', '.join(changes)}")
    return 0


def _resolve_short_id(store, short_id: str) -> str | None:
    """Resolve a short ID prefix to full UUID."""
    from palaia.services.query import _resolve_short_id as _svc_resolve
    return _svc_resolve(store, short_id)


def cmd_get(args):
    """Read a specific memory entry by ID or path."""
    from palaia.services.query import get_entry

    root = get_root()
    agent = _resolve_agent(args)

    result = get_entry(
        root,
        args.path,
        agent=agent,
        from_line=getattr(args, "from_line", None),
        num_lines=getattr(args, "lines", None),
    )

    if "error" in result:
        if _json_out(result, args):
            return 1
        print(f"Entry not found: {result['id']}", file=sys.stderr)
        return 1

    if _json_out(result, args):
        return 0

    print(result["content"])
    return 0


def cmd_ingest(args):
    """Ingest documents for RAG."""
    from palaia.services.ingest import ingest_document

    root = get_root()
    source = args.source

    if not getattr(args, "json", False) and not args.dry_run:
        print(f"Ingesting: {source}")

    result = ingest_document(
        root,
        source=source,
        project=args.project,
        scope=args.scope,
        tags=args.tags.split(",") if args.tags else None,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        dry_run=args.dry_run,
    )

    if "error" in result:
        if _json_out({"error": result["error"]}, args):
            return 1
        print(f"Error: {result['error']}", file=sys.stderr)
        return 1

    if _json_out(
        {
            "source": result["source"],
            "total_chunks": result["total_chunks"],
            "stored_chunks": result["stored_chunks"],
            "skipped_chunks": result["skipped_chunks"],
            "project": result["project"],
            "entry_ids": result["entry_ids"],
            "duration_seconds": result["duration_seconds"],
            "dry_run": args.dry_run,
        },
        args,
    ):
        return 0

    if args.dry_run:
        print(f"  Dry run: {result['total_chunks']} chunks would be created")
        print(f"  Skipped (too short): {result['skipped_chunks']}")
        return 0

    print(f"  Chunking: {args.chunk_size} words, {args.chunk_overlap} overlap -> {result['total_chunks']} chunks")
    print(f"\nDone in {result['duration_seconds']}s")
    print(f"  {result['stored_chunks']} chunks stored")
    if result["skipped_chunks"]:
        print(f"  {result['skipped_chunks']} chunks skipped (too short)")
    if result["project"]:
        print(f"  Project: {result['project']}")
    print(f"  Scope: {result['scope']}")
    if result["project"]:
        print(f'\nSearch with: palaia query "your question" --project {result["project"]}')
    else:
        print('\nSearch with: palaia query "your question"')

    return 0


def cmd_recover(args):
    """Run WAL recovery."""
    from palaia.services.admin import recover

    root = get_root()
    result = recover(root)

    if _json_out(result, args):
        return 0

    if result["replayed"]:
        print(f"Recovered {result['replayed']} pending entries from WAL.")
    else:
        print("No pending WAL entries.")
    return 0


def _reindex_entries(root, config, args) -> dict:
    """Build embedding index for all HOT+WARM entries missing from cache.

    Backward-compat wrapper around palaia.services.admin.reindex_entries.
    Returns dict with keys: indexed, new, cached.
    """
    from palaia.services.admin import reindex_entries

    return reindex_entries(root, config)


def cmd_warmup(args):
    """Pre-download embedding models for instant first search."""
    from palaia.services.admin import warmup as warmup_svc

    root = get_root()
    result = warmup_svc(root)
    is_json = getattr(args, "json", False)

    if not is_json:
        print(f"Metadata index: {result['meta_count']} entries indexed", file=sys.stderr)
        if result["new"] > 0 or result["cached"] > 0:
            print(
                f"Indexed {result['indexed']}/{result['indexed']} entries "
                f"({result['new']} new, {result['cached']} cached)",
                file=sys.stderr,
            )

    providers = result["providers"]
    if _json_out({"providers": providers, "indexed": result["indexed"], "new": result["new"], "cached": result["cached"]}, args):
        return 0

    if not providers:
        print("No embedding providers configured (using BM25 keyword search).")
        return 0

    print_header()
    print(section("Warmup"))
    warmup_rows = []
    for r in providers:
        status = {"ready": "ok", "skipped": "skip", "action_needed": "warn"}.get(r["status"], "error")
        warmup_rows.append((r["name"], f"[{status}]", r["message"]))
    print(
        table_multi(
            headers=("Provider", "Status", "Details"),
            rows=warmup_rows,
            min_widths=(22, 8, 30),
        )
    )

    return 0


def cmd_gc(args):
    """Run garbage collection / tier rotation."""
    from palaia.services.admin import run_gc

    root = get_root()
    dry_run = getattr(args, "dry_run", False)
    budget = getattr(args, "budget", False)

    result = run_gc(root, dry_run=dry_run, budget=budget)

    if _json_out(result, args):
        return 0

    if dry_run:
        candidates = result.get("candidates", [])
        if not candidates:
            print("No entries found.")
            return 0
        rows = [(c["id"], c["title"][:30], f"{c['score']:.4f}", c["tier"], c["reason"]) for c in candidates]
        print(
            table_multi(
                headers=("ID", "Title", "Score", "Tier", "Reason"),
                rows=rows,
                min_widths=(8, 30, 8, 4, 20),
            )
        )
        print(f"\n{len(candidates)} entries scored. Lowest score = first prune candidate.")
        return 0

    skip_keys = {"wal_cleaned", "pruned", "pruned_entries"}
    total_moves = sum(v for k, v in result.items() if k not in skip_keys and isinstance(v, int))
    print("GC complete.")
    if total_moves:
        for k, v in result.items():
            if v and k not in skip_keys and isinstance(v, int):
                print(f"  {k}: {v}")
    else:
        print("  No tier changes needed.")
    if result.get("wal_cleaned"):
        print(f"  WAL cleaned: {result['wal_cleaned']} old entries")
    if result.get("pruned"):
        print(f"  Pruned (budget): {result['pruned']} entries")
    return 0


def cmd_doctor(args):
    """Run diagnostics on the local Palaia instance."""
    palaia_root = find_palaia_root()

    results = run_doctor(palaia_root)
    show_fix = getattr(args, "fix", False)

    # Apply automatic fixes when --fix is passed
    fix_actions: list[str] = []
    if show_fix and palaia_root:
        fix_actions = apply_fixes(palaia_root, results)
        if fix_actions:
            # Re-run checks after fixes to show updated state
            results = run_doctor(palaia_root)

    if _json_out({"checks": results, "fixes_applied": fix_actions}, args):
        return 0

    print(format_doctor_report(results, show_fix=show_fix))

    if fix_actions:
        print("\nFixes applied:")
        for action in fix_actions:
            print(f"  [ok] {action}")
        print()

    return 0


def cmd_export(args):
    """Export public entries."""
    from palaia.services.package import sync_export

    if getattr(args, "command", None) == "export":
        print("Warning: 'palaia export' is deprecated. Use 'palaia sync export' instead.", file=sys.stderr)
    agent = _resolve_agent(args)
    result = sync_export(remote=args.remote, branch=args.branch, output_dir=args.output, agent=agent)
    if _json_out(result, args):
        return 0
    if result.get("exported", 0) == 0:
        print(result.get("message", "Nothing exported."))
        return 0
    print(f"Exported {result['exported']} entries.")
    if result.get("remote"):
        print(f"  Remote: {result['remote']}")
        print(f"  Branch: {result['branch']}")
    else:
        print(f"  Target: {result['target']}")
    return 0


def cmd_import(args):
    """Import entries from export."""
    from palaia.services.package import sync_import

    if getattr(args, "command", None) == "import":
        print("Warning: 'palaia import' is deprecated. Use 'palaia sync import' instead.", file=sys.stderr)
    result = sync_import(source=args.source, dry_run=args.dry_run)
    if _json_out(result, args):
        return 0
    if args.dry_run:
        count = result.get("would_import", 0)
        print(f"Dry run: {count} entries would be imported.")
        if result.get("entries"):
            for e in result["entries"]:
                print(f"  {e['id'][:8]}  [{e['scope']}] {e['title']}")
    else:
        print(f"Imported {result['imported']} entries.")
    if result.get("skipped_dedup"):
        print(f"  Skipped (duplicate): {result['skipped_dedup']}")
    if result.get("skipped_scope"):
        print(f"  Skipped (scope): {result['skipped_scope']}")
    print(f"  Source workspace: {result['source_workspace']}")
    return 0


def cmd_curate(args):
    """Knowledge curation for instance migration."""
    root = get_root()
    action = getattr(args, "curate_action", None)

    if action == "analyze":
        from palaia.services.curate import analyze_svc

        result = analyze_svc(
            root,
            project=getattr(args, "project", None),
            agent=getattr(args, "agent", None),
            output=getattr(args, "output", None),
        )
        if _json_out(result, args):
            return 0
        print(f"Curation report generated: {result['report_path']}")
        print(f"  Entries: {result['entry_count']}")
        print(f"  Clusters: {result['cluster_count']}")
        print(f"  Unclustered: {result['unclustered']}")
        print("\nEdit the report, then apply with: palaia curate apply <report.md>")
        return 0

    elif action == "apply":
        from palaia.services.curate import apply_svc

        result = apply_svc(
            root,
            report_path=args.report,
            output=getattr(args, "output", None),
        )
        if _json_out(result, args):
            return 0
        print(f"Curation applied: {result['output_path']}")
        print(f"  Kept: {result['kept']}")
        print(f"  Merged: {result['merged']}")
        print(f"  Dropped: {result['dropped']}")
        print(f"  Total output entries: {result['total_output']}")
        return 0

    else:
        print("Usage: palaia curate {analyze|apply}", file=sys.stderr)
        return 1


def cmd_sync(args):
    """Sync (export/import) entries — replaces deprecated export/import commands."""
    action = getattr(args, "sync_action", None)

    if action == "export":
        return cmd_export(args)
    elif action == "import":
        return cmd_import(args)
    else:
        print("Usage: palaia sync {export|import}", file=sys.stderr)
        return 1


def cmd_migrate(args):
    """Migrate from external memory formats."""
    root = get_root()
    store = Store(root)
    store.recover()

    # --suggest mode: scan existing entries and suggest type assignments
    if getattr(args, "suggest", False):
        return _cmd_migrate_suggest(store, root, args)

    result = migrate(
        source=args.source,
        store=store,
        format_name=args.format_name,
        scope_override=args.scope,
        dry_run=args.dry_run,
    )

    if _json_out(result, args):
        return 0

    print(format_result(result))
    return 0


# Backward-compat: _suggest_type moved to services.admin
def _suggest_type(title: str, body: str, meta: dict) -> str:
    from palaia.services.admin import suggest_type
    return suggest_type(title, body, meta)


def _cmd_migrate_suggest(store, root, args):
    """Suggest entry type assignments for existing entries without a type field."""
    from palaia.services.admin import migrate_suggest

    result = migrate_suggest(root)

    if _json_out(result, args):
        return 0

    suggestions = result["suggestions"]
    if not suggestions:
        print("All entries already have a type assigned.")
        return 0

    print_header()
    print(section(f"Type suggestions for {len(suggestions)} untyped entries"))

    rows = []
    for s in suggestions:
        rows.append((s["id"][:8], s["tier"], s["suggested_type"], s["title"]))

    print(
        table_multi(
            headers=("ID", "Tier", "Suggested", "Title"),
            rows=rows,
            min_widths=(8, 4, 10, 20),
        )
    )

    print(f"\n{len(suggestions)} entries without type field.")
    print("Apply with: palaia edit <id> --type <type>")
    return 0


def cmd_setup(args):
    """Multi-agent setup: create .palaia symlinks for agent directories."""
    from palaia.services.admin import setup_multi_agent

    if not args.multi_agent:
        print("Usage: palaia setup --multi-agent <agents-dir>", file=sys.stderr)
        return 1

    root = get_root()
    result = setup_multi_agent(
        root,
        args.multi_agent,
        dry_run=getattr(args, "dry_run", False),
    )

    if "error" in result:
        if _json_out(result, args):
            return 1
        print(f"Error: {result['error']}", file=sys.stderr)
        return 1

    # Print action details
    if not getattr(args, "json", False):
        for action in result.get("actions", []):
            label = action["action"]
            agent = action["agent"]
            if label == "skip":
                print(f"  [skip] {agent}: {action.get('reason', '')}")
            elif label == "plan":
                print(f"  [plan] {agent}: would create .palaia -> {action.get('target', '')}")
            elif label == "ok":
                print(f"  [ok] {agent}: .palaia -> {action.get('target', '')}")
            elif label == "error":
                print(f"  [error] {agent}: {action.get('error', '')}")

    if _json_out(
        {
            "agents": result["agents"],
            "symlinks_created": result["symlinks_created"],
            "store_path": result["store_path"],
            "dry_run": result["dry_run"],
        },
        args,
    ):
        return 0

    if not result["dry_run"]:
        print(f"\n{result['symlinks_created']} symlink(s) created for {len(result['agents'])} agent(s).")
    else:
        print(f"\nDry run: {result['symlinks_created']} symlink(s) would be created for {len(result['agents'])} agent(s).")
    return 0


def cmd_instance(args):
    """Manage session instance identity."""
    from palaia.services.admin import instance_set, instance_get, instance_clear

    root = get_root()
    action = args.instance_action

    if action == "set":
        result = instance_set(root, args.name)
        if _json_out(result, args):
            return 0
        print(f"Instance set: {args.name}")
        return 0

    elif action == "get":
        result = instance_get(root)
        if _json_out(result, args):
            return 0
        if result["instance"]:
            print(f"Current instance: {result['instance']}")
        else:
            print("No instance set.")
        return 0

    elif action == "clear":
        result = instance_clear(root)
        if _json_out(result, args):
            return 0
        print("Instance cleared.")
        return 0

    else:
        result = instance_get(root)
        if _json_out(result, args):
            return 0
        if result["instance"]:
            print(f"Current instance: {result['instance']}")
        else:
            print("No instance set. Use: palaia instance set NAME")
        return 0


def _format_lock_human(lock_data: dict) -> str:
    """Format lock info for human-readable output. Backward-compat wrapper."""
    from palaia.services.misc import format_lock_human
    return format_lock_human(lock_data)


def cmd_lock(args):
    """Manage project locks."""
    from palaia.services.misc import (
        format_lock_human,
        lock_acquire,
        lock_break,
        lock_list,
        lock_renew,
        lock_status,
    )

    root = get_root()

    # Parse action_or_project: if it's a known subcommand, use it; otherwise treat as project name
    known_actions = {"status", "renew", "break", "list"}
    aop = getattr(args, "action_or_project", None)
    project_arg = getattr(args, "project", None)

    if aop in known_actions:
        action = aop
        project = project_arg
    elif aop is not None:
        action = "acquire"
        project = aop
    else:
        action = None
        project = None

    if action == "acquire":
        agent = getattr(args, "agent", None) or _detect_current_agent()
        reason = getattr(args, "reason", "") or ""
        ttl = getattr(args, "ttl", None)

        if not agent:
            if _json_out({"error": "No agent specified. Use --agent or set PALAIA_AGENT env var."}, args):
                return 1
            print("Error: No agent specified. Use --agent or set PALAIA_AGENT env var.", file=sys.stderr)
            return 1

        result = lock_acquire(root, project=project, agent=agent, reason=reason, ttl=ttl)
        if "error" in result:
            if _json_out(result, args):
                return 1
            print(f"Error: {result['error']}", file=sys.stderr)
            return 1
        if _json_out(result, args):
            return 0
        print(f"Locked project '{project}' for agent '{agent}'")
        if reason:
            print(f"   Reason: {reason}")
        ttl_min = result.get("ttl_seconds", 1800) // 60
        print(f"   TTL: {ttl_min} minutes (expires {result['expires']})")
        return 0

    elif action == "status":
        result = lock_status(root, project=project)
        if _json_out(result, args):
            return 0
        if project:
            if not result.get("locked", True):
                print(f"Project '{project}' is not locked.")
            else:
                print(format_lock_human(result))
        else:
            locks = result.get("locks", [])
            if not locks:
                print("No active locks.")
            else:
                for lock in locks:
                    print(f"  {lock['project']}: {format_lock_human(lock)}")
                print(f"\n{len(locks)} active lock(s).")
        return 0

    elif action == "renew":
        if not project:
            if _json_out({"error": "Project name required"}, args):
                return 1
            print("Error: Project name required.", file=sys.stderr)
            return 1
        result = lock_renew(root, project=project)
        if "error" in result:
            if _json_out({"error": result["error"]}, args):
                return 1
            print(f"Error: {result['error']}", file=sys.stderr)
            return 1
        if _json_out(result, args):
            return 0
        ttl_min = result.get("ttl_seconds", 1800) // 60
        print(f"Lock renewed for project '{project}' — expires {result['expires']} ({ttl_min}min)")
        return 0

    elif action == "break":
        if not project:
            if _json_out({"error": "Project name required"}, args):
                return 1
            print("Error: Project name required.", file=sys.stderr)
            return 1
        result = lock_break(root, project=project)
        if _json_out(result, args):
            return 0
        if result["broken"]:
            old = result["previous_lock"]
            print(f"Lock for project '{project}' force-broken (was held by {old.get('agent', '?')})")
        else:
            print(f"No lock found for project '{project}'.")
        return 0

    elif action == "list" or action is None:
        result = lock_list(root)
        locks = result["locks"]
        if _json_out(result, args):
            return 0
        if not locks:
            print("No active locks.")
            return 0
        for lock in locks:
            print(f"  {lock['project']}: {format_lock_human(lock)}")
        print(f"\n{len(locks)} active lock(s).")
        return 0

    else:
        print("Unknown lock action. Use: acquire, status, renew, break, list", file=sys.stderr)
        return 1


def cmd_unlock(args):
    """Release a project lock."""
    from palaia.services.misc import unlock_project

    root = get_root()
    result = unlock_project(root, project=args.project)
    if _json_out(result, args):
        return 0
    if result["unlocked"]:
        print(f"Unlocked project '{args.project}'")
    else:
        print(f"Project '{args.project}' was not locked.")
    return 0


def cmd_memo(args):
    """Manage inter-agent memos."""
    from palaia.services.memo import memo_ack, memo_broadcast, memo_gc, memo_inbox, memo_send

    root = get_root()
    action = args.memo_action
    agent = _resolve_agent(args)

    if action == "send":
        meta = memo_send(
            root,
            to=args.to,
            message=args.message,
            from_agent=agent,
            priority=args.priority,
            ttl_hours=args.ttl_hours,
        )
        if _json_out(meta, args):
            return 0
        prio_label = " [high]" if meta["priority"] == "high" else ""
        print(f"Memo sent to '{meta['to']}'{prio_label} (id: {meta['id'][:8]})")
        return 0

    if action == "broadcast":
        meta = memo_broadcast(
            root,
            message=args.message,
            from_agent=agent,
            priority=args.priority,
            ttl_hours=args.ttl_hours,
        )
        if _json_out(meta, args):
            return 0
        print(f"Broadcast sent (id: {meta['id'][:8]})")
        return 0

    if action == "inbox":
        try:
            inbox_aliases = get_aliases(root)
        except Exception:
            inbox_aliases = None
        memos = memo_inbox(root, agent=agent, include_read=args.all, aliases=inbox_aliases)
        if _json_out(
            [{"meta": m, "body": b} for m, b in memos],
            args,
        ):
            return 0
        if not memos:
            print("No memos.")
            return 0
        print(f"{len(memos)} memo(s):\n")
        rows = []
        for meta, body in memos:
            prio = "[high]" if meta.get("priority") == "high" else ""
            read_mark = "[read]" if meta.get("read") else "[new]"
            first_line = body.split("\n")[0][:60] if body else ""
            rows.append(
                (
                    meta["id"][:8],
                    meta.get("from", "?"),
                    read_mark,
                    prio,
                    first_line,
                )
            )
        print(
            table_multi(
                headers=("ID", "From", "State", "Prio", "Message"),
                rows=rows,
                min_widths=(8, 8, 6, 6, 20),
            )
        )
        return 0

    if action == "ack":
        result = memo_ack(root, memo_id=getattr(args, "memo_id", None), ack_all=args.all, agent=agent)
        if "error" in result:
            print(f"Error: {result['error']}", file=sys.stderr)
            return 1
        if _json_out(result, args):
            return 0
        if args.all:
            print(f"Acknowledged {result['acked']} memo(s).")
        elif result["acked"]:
            print(f"Memo {args.memo_id[:8]} acknowledged.")
        else:
            print(f"Memo {args.memo_id} not found.", file=sys.stderr)
            return 1
        return 0

    if action == "gc":
        stats = memo_gc(root)
        if _json_out(stats, args):
            return 0
        print(
            f"GC: removed {stats['removed_expired']} expired, "
            f"{stats['removed_read']} read ({stats['total_removed']} total)"
        )
        return 0

    print("Unknown memo action. Use: send, broadcast, inbox, ack, gc", file=sys.stderr)
    return 1


def cmd_process(args):
    """Manage process execution runs (Issue #72)."""
    from palaia.services.process import process_list, process_run

    root = get_root()
    action = args.process_action

    if action == "run":
        agent = _resolve_agent(args)
        result = process_run(
            root,
            entry_id=args.entry_id,
            agent=agent,
            step=getattr(args, "step", None),
            done=getattr(args, "done", False),
        )
        if "error" in result:
            if _json_out({"error": result["error"]}, args):
                return 1
            print(result["error"], file=sys.stderr)
            return 1
        if _json_out(result["run"], args):
            return 0
        meta = result["meta"]
        title = meta.get("title", "(untitled)")
        print(f"Process: {title} ({result['entry_id'][:8]})")
        print(f"Progress: {result['progress_summary']}")
        print()
        for s in result["steps"]:
            marker = "[x]" if s["done"] else "[ ]"
            print(f"  {s['index']}. {marker} {s['text']}")
        if result["completed"]:
            print("\nAll steps completed!")
        return 0

    elif action == "list":
        result = process_list(root)
        runs = result["runs"]
        if _json_out({"runs": [r["run"] for r in runs]}, args):
            return 0
        if not runs:
            print("No active process runs.")
            return 0
        rows = []
        for r in runs:
            rows.append(
                (
                    r["entry_id"][:8],
                    r["title"][:30],
                    r["progress_summary"],
                    "yes" if r["completed"] else "no",
                    r["started_at"][:10] if r["started_at"] else "?",
                )
            )
        print(
            table_multi(
                headers=("ID", "Title", "Progress", "Done", "Started"),
                rows=rows,
                min_widths=(8, 30, 15, 4, 10),
            )
        )
        print(f"\n{len(runs)} process run(s).")
        return 0

    else:
        print("Unknown process action. Use: run, list", file=sys.stderr)
        return 1


def cmd_package(args):
    """Manage knowledge packages (Issue #73)."""
    from palaia.services.package import package_export, package_import, package_info

    root = get_root()
    action = args.package_action

    if action == "export":
        types_filter = None
        if getattr(args, "types", None):
            types_filter = [t.strip() for t in args.types.split(",")]
        result = package_export(
            root,
            project=args.project,
            output_path=getattr(args, "output", None),
            include_types=types_filter,
        )
        if _json_out(result, args):
            return 0
        print(f"Exported {result['entry_count']} entries from project '{result['project']}'")
        print(f"  Package: {result['path']}")
        return 0

    elif action == "import":
        result = package_import(
            root,
            file=args.file,
            target_project=getattr(args, "project", None),
            merge_strategy=getattr(args, "merge", "skip"),
            agent=getattr(args, "agent", None),
        )
        if _json_out(result, args):
            return 0
        print(f"Imported {result['imported']} entries into project '{result['project']}'")
        if result["skipped"]:
            print(f"  Skipped (duplicates): {result['skipped']}")
        if result.get("overwritten"):
            print(f"  Overwritten: {result['overwritten']}")
        return 0

    elif action == "info":
        try:
            info = package_info(root, file=args.file)
        except (FileNotFoundError, ValueError) as e:
            if _json_out({"error": str(e)}, args):
                return 1
            print(f"Error: {e}", file=sys.stderr)
            return 1
        if _json_out(info, args):
            return 0
        print(f"Package: {args.file}")
        print(f"  Format: v{info['palaia_package']}")
        print(f"  Palaia version: {info['palaia_version']}")
        print(f"  Project: {info['project']}")
        print(f"  Exported: {info['exported_at']}")
        print(f"  Entries: {info['entry_count']}")
        if info.get("type_breakdown"):
            types_str = ", ".join(f"{v} {k}" for k, v in info["type_breakdown"].items())
            print(f"  Types: {types_str}")
        return 0

    print("Unknown package action. Use: export, import, info", file=sys.stderr)
    return 1


def cmd_embed_server(args):
    """Start long-lived embedding server for fast queries."""
    from palaia.embed_server import main as embed_server_main

    embed_server_main()
    return 0


def cmd_skill(args):
    """Print the embedded SKILL.md documentation."""
    from palaia.services.misc import get_skill_content

    result = get_skill_content()
    if "error" in result:
        if getattr(args, "json", False):
            print(json.dumps({"error": result["error"]}, ensure_ascii=False))
            return 1
        print(result["error"], file=sys.stderr)
        return 1
    if _json_out(result, args):
        return 0
    print(result["skill"])
    return 0


def main():
    from palaia.cli_args import build_parser

    parser = build_parser()
    args = parser.parse_args()

    _logging.basicConfig(
        level=_logging.DEBUG if args.verbose else _logging.WARNING,
        format="%(name)s: %(message)s",
    )

    if not args.command:
        parser.print_help()
        return 1

    # Gatekeeper: block store commands without valid init
    if not _check_gatekeeper(args.command):
        return 1

    commands = {
        "init": cmd_init,
        "write": cmd_write,
        "edit": cmd_edit,
        "query": cmd_query,
        "ingest": cmd_ingest,
        "get": cmd_get,
        "recover": cmd_recover,
        "list": cmd_list,
        "status": cmd_status,
        "gc": cmd_gc,
        "setup": cmd_setup,
        "doctor": cmd_doctor,
        "export": cmd_export,
        "import": cmd_import,
        "migrate": cmd_migrate,
        "detect": cmd_detect,
        "config": cmd_config,
        "warmup": cmd_warmup,
        "project": cmd_project,
        "process": cmd_process,
        "package": cmd_package,
        "memo": cmd_memo,
        "lock": cmd_lock,
        "unlock": cmd_unlock,
        "instance": cmd_instance,
        "embed-server": cmd_embed_server,
        "skill": cmd_skill,
        "priorities": cmd_priorities,
        "curate": cmd_curate,
        "sync": cmd_sync,
    }
    try:
        return commands[args.command](args)
    except FileNotFoundError as e:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(e)}))
        else:
            print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(e)}))
        else:
            print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
