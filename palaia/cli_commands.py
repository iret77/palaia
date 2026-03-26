"""Large CLI command handlers — extracted from cli.py for maintainability.

Each function follows the same pattern: parse args, call service, format output.
Helpers are imported from cli_helpers to avoid circular dependencies.
"""

from __future__ import annotations

import json
import sys

from palaia.cli_helpers import (
    check_version_nag,
    detect_current_agent,
    json_out,
    resolve_agent,
    resolve_agent_names,
    resolve_instance_for_write,
)
from palaia.config import get_aliases, get_root, load_config
from palaia.store import Store
from palaia.ui import (
    format_size,
    print_header,
    relative_time,
    score_display,
    section,
    table_kv,
    table_multi,
    truncate,
)


def cmd_query(args):
    """Search memories."""
    from palaia.ingest import format_rag_output
    from palaia.services.query import enrich_rag_results, search_entries

    check_version_nag()
    root = get_root()
    agent = resolve_agent(args)

    svc_result = search_entries(
        root,
        args.query,
        limit=args.limit,
        include_cold=args.all,
        project=getattr(args, "project", None),
        agent=agent,
        entry_type=getattr(args, "type", None),
        status=getattr(args, "status", None),
        priority=getattr(args, "priority", None),
        assignee=getattr(args, "assignee", None),
        instance=getattr(args, "instance", None),
        before=getattr(args, "before", None),
        after=getattr(args, "after", None),
        cross_project=getattr(args, "cross_project", False),
    )

    results = svc_result["results"]
    has_embeddings = svc_result["has_embeddings"]
    bm25_only = svc_result["bm25_only"]

    # --- Adaptive Nudging for query (Issue #68) ---
    query_nudge_messages = []
    try:
        from palaia.nudge import NudgeTracker

        tracker = NudgeTracker(root)
        agent_for_nudge = agent or "default"
        query_type = getattr(args, "type", None)

        if query_type:
            tracker.record_success("query_without_type_filter", agent_for_nudge)
        else:
            has_typed = False
            try:
                store = Store(root)
                all_entries = store.all_entries(include_cold=False)
                has_typed = any(m.get("type") for m, _, _ in all_entries)
            except Exception:
                pass
            if has_typed:
                tracker.record_failure("query_without_type_filter", agent_for_nudge)
                if tracker.should_nudge("query_without_type_filter", agent_for_nudge):
                    msg = tracker.get_nudge_message("query_without_type_filter")
                    if msg:
                        query_nudge_messages.append(msg)
                        tracker.record_nudge("query_without_type_filter", agent_for_nudge)
    except Exception:
        pass

    if json_out(
        {
            "results": results,
            **({"nudge": query_nudge_messages} if query_nudge_messages else {}),
        },
        args,
    ):
        return 0

    # --- embed_provider_hint nudge (v2.2) ---
    if bm25_only and not has_embeddings:
        try:
            from palaia.nudge import NudgeTracker

            tracker_embed = NudgeTracker(root)
            agent_embed = agent or "default"
            if tracker_embed.should_nudge("embed_provider_hint", agent_embed):
                embed_msg = tracker_embed.get_nudge_message("embed_provider_hint")
                if embed_msg:
                    query_nudge_messages.append(embed_msg)
                    tracker_embed.record_nudge("embed_provider_hint", agent_embed)
        except Exception:
            pass
    elif not bm25_only:
        try:
            from palaia.nudge import NudgeTracker

            tracker_embed = NudgeTracker(root)
            agent_embed = agent or "default"
            for _ in range(3):
                tracker_embed.record_success("embed_provider_hint", agent_embed)
        except Exception:
            pass

    if not results:
        print_header()
        # M5: guide on first query with empty store
        try:
            store = Store(root)
            all_entries = store.all_entries(include_cold=True)
            if len(all_entries) == 0:
                print("[palaia] Your memory is empty. Knowledge will be auto-captured from conversations, or write explicitly: palaia write 'your text'", file=sys.stderr)
        except Exception:
            pass
        print("\nNo results found.")
        return 0

    if getattr(args, "rag", False):
        enriched = enrich_rag_results(root, results)
        print(format_rag_output(args.query, enriched))
        return 0

    print_header()
    print(section(f"Results for: {args.query}"))

    rows = []
    for r in results:
        title = r["title"] or "(untitled)"
        score_str = score_display(r["score"])
        body_preview = truncate(r["body"].replace("\n", " "), 50)
        rows.append((r["id"][:8], score_str, r["tier"], title, body_preview))

    print(
        table_multi(
            headers=("ID", "Score", "Tier", "Title", "Preview"),
            rows=rows,
            min_widths=(8, 18, 4, 16, 20),
        )
    )

    search_tier = "hybrid" if has_embeddings else "BM25"
    print(f"\n{len(results)} result(s) found. (Search tier: {search_tier})")

    for nudge_msg in query_nudge_messages:
        print(f"\nHint: {nudge_msg}", file=sys.stderr)

    # --- priorities_hint nudge (v2.2) ---
    if results:
        try:
            from palaia.nudge import NudgeTracker

            tracker = NudgeTracker(root)
            agent_for_nudge = agent or "default"
            priorities_path = root / "priorities.json"
            if not priorities_path.exists():
                store = Store(root)
                agents = set()
                for meta, _, _ in store.all_entries(include_cold=False):
                    a = meta.get("agent")
                    if a:
                        agents.add(a)
                    if len(agents) > 1:
                        break
                if len(agents) > 1:
                    if tracker.should_nudge("priorities_hint", agent_for_nudge):
                        msg = tracker.get_nudge_message("priorities_hint")
                        if msg:
                            print(f"\n{msg}", file=sys.stderr)
                            tracker.record_nudge("priorities_hint", agent_for_nudge)
            else:
                tracker.record_success("priorities_hint", agent_for_nudge)
                tracker.record_success("priorities_hint", agent_for_nudge)
                tracker.record_success("priorities_hint", agent_for_nudge)
        except Exception:
            pass

    # Import nudge functions locally to avoid circular imports
    from palaia.cli_nudge import memo_nudge, process_nudge
    memo_nudge(args, resolve_agent_fn=resolve_agent, get_root_fn=get_root, get_aliases_fn=get_aliases)
    process_nudge(args.query, [], args, get_root_fn=get_root)

    return 0


def cmd_list(args):
    """List memories in a tier or across all tiers."""
    from palaia.services.query import list_entries

    check_version_nag()
    root = get_root()
    list_all = getattr(args, "all", False)
    scope_agent = resolve_agent(args)
    agent_filter = getattr(args, "agent", None)

    svc_result = list_entries(
        root,
        tier=getattr(args, "tier", None),
        list_all=list_all,
        agent=scope_agent,
        project=getattr(args, "project", None),
        tag_filters=getattr(args, "tag", None),
        scope=getattr(args, "scope", None),
        agent_filter=agent_filter,
        entry_type=getattr(args, "type", None),
        status=getattr(args, "status", None),
        priority=getattr(args, "priority", None),
        assignee=getattr(args, "assignee", None),
        instance=getattr(args, "instance", None),
        before=getattr(args, "before", None),
        after=getattr(args, "after", None),
        cross_project=getattr(args, "cross_project", False),
        agent_names=resolve_agent_names(agent_filter) if agent_filter else None,
    )

    tier_label = svc_result["tier"]
    entries_with_tier = svc_result["entries_with_tier"]

    if json_out(
        {
            "tier": tier_label,
            "entries": [
                {
                    "id": meta.get("id", "?"),
                    "type": meta.get("type", "memory"),
                    "title": meta.get("title", "(untitled)"),
                    "scope": meta.get("scope", "team"),
                    "agent": meta.get("agent", ""),
                    "instance": meta.get("instance", ""),
                    "tags": meta.get("tags", []),
                    "project": meta.get("project", ""),
                    "status": meta.get("status", ""),
                    "priority": meta.get("priority", ""),
                    "assignee": meta.get("assignee", ""),
                    "due_date": meta.get("due_date", ""),
                    "tier": t,
                    "decay_score": meta.get("decay_score", 0),
                    "preview": body[:80].replace("\n", " "),
                }
                for meta, body, t in entries_with_tier
            ],
        },
        args,
    ):
        return 0

    if not entries_with_tier:
        print_header()
        print(f"\nNo entries in {tier_label}.")
        return 0

    print_header()
    print(section(f"Entries ({tier_label})"))

    rows = []
    for meta, body, t in entries_with_tier:
        title = meta.get("title", "(untitled)")
        entry_id = meta.get("id", "?")[:8]
        scope = meta.get("scope", "team")
        age = relative_time(meta.get("created", ""))
        if list_all:
            rows.append((entry_id, t, scope, title, age))
        else:
            rows.append((entry_id, scope, title, age))

    if list_all:
        print(
            table_multi(
                headers=("ID", "Tier", "Scope", "Title", "Age"),
                rows=rows,
                min_widths=(8, 4, 6, 16, 8),
            )
        )
    else:
        print(
            table_multi(
                headers=("ID", "Scope", "Title", "Age"),
                rows=rows,
                min_widths=(8, 6, 20, 8),
            )
        )

    print(f"\n{len(entries_with_tier)} entries in {tier_label}.")
    return 0


def cmd_status(args):
    """Show system status."""
    from palaia.services.status import collect_status

    check_version_nag()
    root = get_root()
    info = collect_status(root)

    if json_out(info, args):
        return 0

    print_header()

    entries_str = f"{info['entries']['hot']} hot"
    if info["entries"]["warm"]:
        entries_str += f" / {info['entries']['warm']} warm"
    if info["entries"]["cold"]:
        entries_str += f" / {info['entries']['cold']} cold"

    type_counts = info["type_counts"]
    task_status_counts = info["task_status_counts"]
    class_parts = []
    for et in ("memory", "process", "task"):
        if type_counts.get(et, 0) > 0:
            class_parts.append(f"{type_counts[et]} {et}")
    class_str = " / ".join(class_parts) if class_parts else "none"

    last_write = info["last_write"]
    last_gc = info["last_gc"]

    store_rows = [
        ("Root", str(info["palaia_root"])),
        ("Store version", f"v{info['version']}"),
        ("Entries", entries_str),
        ("Classes", class_str),
        ("Projects", str(info["project_count"])),
        ("Disk size", format_size(info["disk_bytes"])),
        ("Last write", relative_time(last_write) if last_write else "never"),
        ("Last GC", relative_time(last_gc) if last_gc else "never"),
    ]

    if task_status_counts:
        task_parts = [f"{v} {k}" for k, v in sorted(task_status_counts.items())]
        store_rows.append(("Tasks", " / ".join(task_parts)))

    if info["wal_pending"]:
        store_rows.append(("WAL pending", str(info["wal_pending"])))
    if info["recovered"]:
        store_rows.append(("WAL recovered", f"{info['recovered']} entries"))

    print(section("Store"))
    print(table_kv(store_rows))

    statuses = info["embedding_statuses"]
    embed_rows = []
    labels = ["Primary", "Fallback", "Last resort"]
    for i, s in enumerate(statuses):
        label = labels[i] if i < len(labels) else f"Provider {i + 1}"
        model_str = f" ({s['model']})" if s.get("model") else ""
        avail = "ok" if s["available"] else "n/a"
        embed_rows.append((label, f"{s['name']}{model_str} [{avail}]"))

    embed_rows.append(("Index", f"{info['idx_count']}/{info['total']} entries indexed"))

    print(section("Embeddings"))
    print(table_kv(embed_rows))

    if info.get("index_hint"):
        print(info["index_hint"], file=sys.stderr)

    budget_info = info.get("budget")
    if budget_info:
        print(section("Budget"))
        budget_rows = []
        if "max_entries_per_tier" in budget_info:
            budget_rows.append(("Max entries/tier", str(budget_info["max_entries_per_tier"])))
            for t, usage in budget_info.get("tier_usage", {}).items():
                budget_rows.append((f"  {t}", usage))
        if "max_total_chars" in budget_info:
            budget_rows.append(("Max total chars", str(budget_info["max_total_chars"])))
            budget_rows.append(("  Usage", budget_info.get("chars_usage", "?")))
        print(table_kv(budget_rows))

    plugin_status = "active" if info["plugin_detected"] else "not detected"
    print(f"\nOpenClaw Plugin: {plugin_status}")

    # --- curate_reminder nudge (v2.2) ---
    try:
        from palaia.nudge import NudgeTracker

        total_count = info.get("total", 0)
        if total_count > 100:
            tracker = NudgeTracker(root)
            agent_for_nudge = info.get("config", {}).get("agent", "default")
            if tracker.should_nudge("curate_reminder", agent_for_nudge):
                store = Store(root)
                oldest_days = 0
                for tier in ("hot", "warm", "cold"):
                    tier_dir = root / tier
                    if tier_dir.exists():
                        for f in tier_dir.iterdir():
                            if f.is_file():
                                import time
                                age_days = (time.time() - f.stat().st_mtime) / 86400
                                if age_days > oldest_days:
                                    oldest_days = age_days
                if oldest_days >= 90:
                    msg = tracker.get_nudge_message("curate_reminder")
                    if msg:
                        msg = msg.format(count=total_count, days=int(oldest_days))
                        print(f"\n{msg}", file=sys.stderr)
                        tracker.record_nudge("curate_reminder", agent_for_nudge)
    except Exception:
        pass

    return 0


def cmd_detect(args):
    """Detect available embedding providers."""
    from palaia.services.admin import detect_embedding_providers

    result = detect_embedding_providers()

    if json_out(result, args):
        return 0

    print_header()
    print(section("Environment"))
    print(
        table_kv(
            [
                ("System", result["system"]),
                ("Python", result["python"]),
            ]
        )
    )

    available = []
    provider_rows = []
    for p in result["providers"]:
        name = p["name"]
        if name == "ollama":
            if p["server_running"]:
                status = "running"
                if p["available"]:
                    available.append("ollama")
                    status = "ok"
            else:
                status = "not running"
            provider_rows.append((name, "ok" if p["available"] else "n/a", status))
        elif name in ("sentence-transformers", "fastembed"):
            if p["available"]:
                available.append(name)
                provider_rows.append((name, "ok", f"v{p['version']}"))
            else:
                provider_rows.append((name, "n/a", p.get("install_hint", "not installed")))
        elif name in ("openai", "voyage"):
            if p["available"]:
                available.append(name)
                provider_rows.append((name, "ok", "key found"))
            else:
                provider_rows.append((name, "n/a", "no key"))

    provider_rows.append(("bm25", "ok", "always available"))

    print(section("Providers"))
    print(
        table_multi(
            headers=("Provider", "Status", "Details"),
            rows=provider_rows,
            min_widths=(22, 6, 30),
        )
    )

    has_openai = "openai" in available
    has_local = any(p in available for p in ("sentence-transformers", "fastembed", "ollama"))
    local_name = next((p for p in ("sentence-transformers", "fastembed", "ollama") if p in available), None)

    if has_openai and has_local:
        chain_parts = ["openai", local_name, "bm25"]
    elif has_local:
        chain_parts = [local_name, "bm25"]
    elif has_openai:
        chain_parts = ["openai", "bm25"]
    else:
        chain_parts = ["bm25"]

    chain_str = " -> ".join(chain_parts)
    cmd_str = " ".join(chain_parts)

    print(section("Recommendation"))
    print(
        table_kv(
            [
                ("Chain", chain_str),
                ("Set with", f"palaia config set-chain {cmd_str}"),
            ]
        )
    )

    try:
        root = get_root()
        config = load_config(root)
        chain_cfg = config.get("embedding_chain")
        provider_cfg = config.get("embedding_provider", "auto")
        if chain_cfg:
            print(f"\nCurrent config: embedding_chain = {' -> '.join(chain_cfg)}")
        else:
            print(f"\nCurrent config: embedding_provider = {provider_cfg}")
    except FileNotFoundError:
        print("\nCurrent config: not initialized (run 'palaia init' first)")

    return 0


def cmd_config(args):
    """Get or set configuration values."""
    from palaia.services.admin import (
        config_get,
        config_get_aliases_svc,
        config_list_all,
        config_remove_alias_svc,
        config_set,
        config_set_alias_svc,
        config_set_chain,
    )

    root = get_root()

    if args.action == "set-chain":
        result = config_set_chain(root, args.providers)
        if "error" in result:
            if json_out(result, args):
                return 1
            print(f"Unknown provider: {result['error']}", file=sys.stderr)
            return 1
        if json_out(result, args):
            return 0
        print(f"Embedding chain: {' -> '.join(result['embedding_chain'])}")
        return 0

    if args.action == "set-alias":
        result = config_set_alias_svc(root, args.from_name, args.to_name)
        if "error" in result:
            if json_out(result, args):
                return 1
            print(f"Error: {result['error']}", file=sys.stderr)
            return 1
        if json_out(result, args):
            return 0
        print(f"Alias set: {args.from_name} -> {args.to_name}")
        return 0

    if args.action == "get-aliases":
        result = config_get_aliases_svc(root)
        if json_out(result, args):
            return 0
        aliases = result["aliases"]
        if not aliases:
            print("No aliases configured.")
            return 0
        for src, tgt in sorted(aliases.items()):
            print(f"  {src} -> {tgt}")
        return 0

    if args.action == "remove-alias":
        result = config_remove_alias_svc(root, args.from_name)
        if json_out(result, args):
            return 0
        if result["removed"]:
            print(f"Alias removed: {args.from_name}")
        else:
            print(f"No alias found for: {args.from_name}")
            return 1
        return 0

    if args.action == "get":
        result = config_get(root, args.key)
        if "error" in result:
            if json_out(result, args):
                return 1
            print(f"Unknown config key: {args.key}", file=sys.stderr)
            return 1
        if json_out(result, args):
            return 0
        print(f"{result['key']} = {result['value']}")
        return 0

    if args.action == "set":
        result = config_set(root, args.key, args.value)
        if json_out(result, args):
            return 0
        print(f"{result['key']} = {result['value']}")
        return 0

    if args.action == "list":
        result = config_list_all(root)
        if json_out(result, args):
            return 0
        for k, v in sorted(result.items()):
            print(f"{k} = {v}")
        return 0

    return 0


def cmd_project(args):
    """Manage projects."""
    from palaia.services.project import (
        project_create,
        project_delete,
        project_list,
        project_query,
        project_set_owner,
        project_set_scope,
        project_show,
        project_write,
    )

    root = get_root()
    action = args.project_action

    if action == "create":
        result = project_create(
            root,
            name=args.name,
            description=args.description or "",
            default_scope=args.default_scope or "team",
            owner=getattr(args, "owner", None),
        )
        if "error" in result:
            if json_out({"error": result["error"]}, args):
                return 1
            print(f"Error: {result['error']}", file=sys.stderr)
            return 1
        proj = result["project"]
        if json_out(proj, args):
            return 0
        print(f"Created project: {proj['name']}")
        if proj.get("owner"):
            print(f"  Owner: {proj['owner']}")
        if proj.get("description"):
            print(f"  Description: {proj['description']}")
        print(f"  Default scope: {proj['default_scope']}")
        return 0

    elif action == "list":
        result = project_list(root, owner=getattr(args, "owner", None))
        projects = result["projects"]
        if json_out({"projects": projects}, args):
            return 0
        if not projects:
            print_header()
            print("\nNo projects.")
            return 0
        print_header()
        print(section("Projects"))
        rows = []
        for p in projects:
            rows.append((p["name"], p["default_scope"], p.get("owner", ""), p.get("description", "")))
        print(
            table_multi(
                headers=("Name", "Scope", "Owner", "Description"),
                rows=rows,
                min_widths=(12, 6, 8, 20),
            )
        )
        print(f"\n{len(projects)} project(s).")
        return 0

    elif action == "show":
        result = project_show(root, name=args.name)
        if "error" in result:
            if json_out({"error": result["error"]}, args):
                return 1
            print(result["error"], file=sys.stderr)
            return 1
        if json_out(result, args):
            return 0
        proj = result["project"]
        print_header()
        print(section(f"Project: {proj['name']}"))
        info_rows = [
            ("Name", proj["name"]),
            ("Description", proj.get("description") or "(none)"),
            ("Owner", proj.get("owner") or "(none)"),
            ("Default scope", proj["default_scope"]),
            ("Contributors", ", ".join(result["contributors"]) if result["contributors"] else "(none)"),
            ("Created", proj.get("created_at", "")),
            ("Entries", str(result["entry_count"])),
        ]
        print(table_kv(info_rows))

        if result["entries"]:
            print(section("Entries"))
            entry_rows = []
            for e in result["entries"]:
                entry_rows.append((e["id"][:8], e["tier"], e["scope"], e["title"]))
            print(
                table_multi(
                    headers=("ID", "Tier", "Scope", "Title"),
                    rows=entry_rows,
                    min_widths=(8, 4, 6, 20),
                )
            )
        return 0

    elif action == "write":
        result = project_write(
            root,
            name=args.name,
            text=args.text,
            scope=args.scope,
            agent=args.agent,
            tags=args.tags.split(",") if args.tags else None,
            title=args.title,
        )
        if "error" in result:
            if json_out({"error": result["error"]}, args):
                return 1
            print(result["error"], file=sys.stderr)
            return 1
        if json_out(result, args):
            return 0
        print(f"Written to project '{args.name}': {result['id']}")
        return 0

    elif action == "query":
        result = project_query(
            root,
            name=args.name,
            query=args.query,
            limit=args.limit or 10,
        )
        if "error" in result:
            if json_out({"error": result["error"]}, args):
                return 1
            print(result["error"], file=sys.stderr)
            return 1
        results = result["results"]
        if json_out({"results": results, "project": args.name}, args):
            return 0
        if not results:
            print_header()
            print(f"\nNo results in project '{args.name}'.")
            return 0
        print_header()
        print(section(f"Results in project '{args.name}'"))
        rows = []
        for r in results:
            title = r["title"] or "(untitled)"
            score_str = score_display(r["score"])
            body_preview = truncate(r["body"].replace("\n", " "), 50)
            rows.append((r["id"][:8], score_str, r["tier"], title, body_preview))
        print(
            table_multi(
                headers=("ID", "Score", "Tier", "Title", "Preview"),
                rows=rows,
                min_widths=(8, 18, 4, 16, 20),
            )
        )
        print(f"\n{len(results)} result(s) in project '{args.name}'.")
        return 0

    elif action == "set-scope":
        result = project_set_scope(root, name=args.name, scope_value=args.scope_value)
        if "error" in result:
            if json_out({"error": result["error"]}, args):
                return 1
            print(f"Error: {result['error']}", file=sys.stderr)
            return 1
        if json_out(result, args):
            return 0
        print(f"Project '{args.name}' default scope \u2192 {result['default_scope']}")
        return 0

    elif action == "set-owner":
        result = project_set_owner(
            root,
            name=args.name,
            owner_value=getattr(args, "owner_value", None),
            clear=getattr(args, "clear", False),
        )
        if "error" in result:
            if json_out({"error": result["error"]}, args):
                return 1
            print(f"Error: {result['error']}", file=sys.stderr)
            return 1
        if json_out(result, args):
            return 0
        if result.get("owner") is None:
            print(f"Cleared owner for project '{args.name}'.")
        else:
            print(f"Project '{args.name}' owner \u2192 {result['owner']}")
        return 0

    elif action == "delete":
        result = project_delete(root, name=args.name)
        if "error" in result:
            if json_out({"error": result["error"]}, args):
                return 1
            print(result["error"], file=sys.stderr)
            return 1
        if json_out(result, args):
            return 0
        print(f"Deleted project '{args.name}'. Entries preserved (project tag removed).")
        return 0

    else:
        print("Unknown project action.", file=sys.stderr)
        return 1


def cmd_priorities(args):
    """View and manage injection priorities (#121)."""
    from palaia.config import find_palaia_root
    from palaia.services.priorities import (
        block_entry_svc,
        list_blocked_svc,
        reset_priorities_svc,
        set_priority_svc,
        show_priorities,
        unblock_entry_svc,
    )

    root = find_palaia_root()
    action = getattr(args, "priorities_action", None)
    agent = getattr(args, "agent", None)
    project = getattr(args, "project", None)

    if action == "block":
        result = block_entry_svc(root, args.entry_id, agent=agent, project=project)
        if json_out(result, args):
            return 0
        scope = f" (agent: {agent})" if agent else (f" (project: {project})" if project else "")
        print(f"Blocked: {args.entry_id}{scope}")
        return 0

    if action == "unblock":
        result = unblock_entry_svc(root, args.entry_id, agent=agent, project=project)
        if json_out(result, args):
            return 0
        print(f"Unblocked: {args.entry_id}")
        return 0

    if action == "set":
        try:
            result = set_priority_svc(root, args.key, args.value, agent=agent, project=project)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        if json_out(result, args):
            return 0
        scope = agent or project or "global"
        print(f"Set {args.key} = {args.value} (scope: {scope})")
        return 0

    if action == "list-blocked":
        result = list_blocked_svc(root, agent=agent, project=project)
        if json_out(result, args):
            return 0
        if not result["blocked"]:
            print("No blocked entries.")
        else:
            for b in result["blocked"]:
                print(f"  {b['id']}  (source: {b['source']})")
        return 0

    if action == "reset":
        result = reset_priorities_svc(root, agent=agent, project=project)
        if json_out(result, args):
            return 0
        print(f"Priorities reset ({result['reset']})")
        return 0

    # Default: show priorities (simulate injection)
    query = getattr(args, "query", None)
    limit = getattr(args, "limit", 10)
    include_cold = getattr(args, "include_cold", False)

    result = show_priorities(root, query=query, agent=agent, project=project,
                             limit=limit, include_cold=include_cold)

    if json_out(result, args):
        return 0

    resolved = result["resolved"]
    sources = result.get("sources", {})

    agent_str = result.get("agent") or "-"
    proj_str = result.get("project") or "-"
    print(f"Injection Priorities (agent: {agent_str}, project: {proj_str})\n")

    print("Config:")
    for key in ("recallMinScore", "maxInjectedChars", "tier"):
        val = resolved.get(key, "?")
        src = sources.get(key, "default")
        print(f"  {key:20s} {val}  ({src})")
    tw = resolved.get("recallTypeWeight", {})
    tw_str = " ".join(f"{k}={v}" for k, v in sorted(tw.items()))
    print(f"  {'typeWeights':20s} {tw_str}  ({sources.get('recallTypeWeight', 'default')})")

    blocked = resolved.get("blocked", [])
    if blocked:
        print(f"\nBlocked: {', '.join(blocked)}")

    entries = result.get("results", [])
    if entries:
        print(f"\nSimulated injection (query: \"{query or '(none)'}\"):")
        print(f"{'ID':10s} {'BM25':>6s} {'Embed':>6s} {'Comb':>6s} {'TyWt':>6s} {'Final':>7s}  {'Type':8s} Title")
        for e in entries:
            eid = e["id"][:8] + ".."
            print(
                f"{eid:10s} {e.get('bm25_score', 0):6.2f} {e.get('embed_score', 0):6.2f} "
                f"{e.get('combined_score', 0):6.2f} x{e.get('type_weight', 1.0):<5.1f} "
                f"{e.get('weighted_score', 0):7.4f}  {e.get('type', '?'):8s} {e.get('title', '')[:40]}"
            )
        print(f"\n{len(entries)} entries would be injected")

    blocked_entries = result.get("blocked_entries", [])
    if blocked_entries:
        print(f"{len(blocked_entries)} entries blocked (not shown)")

    if not entries and not query:
        print("\nTip: Pass a query to simulate injection: palaia priorities \"your query here\"")

    return 0
