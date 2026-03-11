"""Palaia CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from palaia import __version__
from palaia.config import DEFAULT_CONFIG, get_root, load_config, save_config
from palaia.migrate import format_result, migrate
from palaia.project import ProjectManager
from palaia.search import SearchEngine
from palaia.store import Store
from palaia.sync import export_entries, import_entries


def _json_out(data, args):
    """Print JSON if --json flag is set, return True if printed."""
    if getattr(args, "json", False):
        print(json.dumps(data, ensure_ascii=False))
        return True
    return False


def cmd_init(args):
    """Initialize .palaia directory."""
    target = Path(args.path or ".") / ".palaia"
    if target.exists():
        if _json_out({"status": "exists", "path": str(target)}, args):
            return 0
        print(f"Already initialized: {target}")
        return 0

    target.mkdir(parents=True)
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (target / sub).mkdir()
    save_config(target, DEFAULT_CONFIG)
    if _json_out({"status": "created", "path": str(target)}, args):
        return 0
    print(f"Initialized Palaia at {target}")
    return 0


def cmd_write(args):
    """Write a memory entry."""
    root = get_root()
    store = Store(root)

    # Recovery check
    recovered = store.recover()
    if recovered and not getattr(args, "json", False):
        print(f"Recovered {recovered} pending entries from WAL.")

    entry_id = store.write(
        body=args.text,
        scope=args.scope,
        agent=args.agent,
        tags=args.tags.split(",") if args.tags else None,
        title=args.title,
        project=getattr(args, "project", None),
    )

    # Check if this was a dedup (existing entry returned)
    entry = store.read(entry_id)
    tier = "hot"
    scope = args.scope or "team"
    deduplicated = False
    if entry:
        meta, _ = entry
        scope = meta.get("scope", scope)
        # Check tier
        for t in ("hot", "warm", "cold"):
            if (root / t / f"{entry_id}.md").exists():
                tier = t
                break

    if _json_out(
        {
            "id": entry_id,
            "tier": tier,
            "scope": scope,
            "deduplicated": deduplicated,
        },
        args,
    ):
        return 0

    print(f"Written: {entry_id}")
    return 0


def cmd_query(args):
    """Search memories."""
    root = get_root()
    store = Store(root)
    store.recover()

    engine = SearchEngine(store)
    results = engine.search(
        args.query,
        top_k=args.limit,
        include_cold=args.all,
        project=getattr(args, "project", None),
    )

    if _json_out({"results": results}, args):
        return 0

    if not results:
        print("No results found.")
        return 0

    for r in results:
        tier_badge = {"hot": "🔥", "warm": "🌤", "cold": "❄️"}.get(r["tier"], "?")
        title = r["title"] or "(untitled)"
        print(f"\n{tier_badge} [{r['score']}] {title}")
        print(f"  ID: {r['id']}")
        print(f"  Scope: {r['scope']} | Decay: {r['decay_score']}")
        if r["tags"]:
            print(f"  Tags: {', '.join(r['tags'])}")
        print(f"  {r['body']}")

    print(f"\n{len(results)} result(s) found. (Search tier: BM25)")
    return 0


def cmd_get(args):
    """Read a specific memory entry by ID or path."""
    root = get_root()
    store = Store(root)
    store.recover()

    # Accept UUID or path like hot/uuid.md
    entry_id = args.path
    if "/" in entry_id:
        # Extract ID from path
        entry_id = entry_id.split("/")[-1].replace(".md", "")

    entry = store.read(entry_id)
    if entry is None:
        if _json_out({"error": "not_found", "id": entry_id}, args):
            return 1
        print(f"Entry not found: {entry_id}", file=sys.stderr)
        return 1

    meta, body = entry

    # Determine tier
    tier = "unknown"
    for t in ("hot", "warm", "cold"):
        if (root / t / f"{entry_id}.md").exists():
            tier = t
            break

    # Handle --from / --lines slicing
    lines = body.split("\n")
    from_line = getattr(args, "from_line", None)
    num_lines = getattr(args, "lines", None)
    if from_line is not None:
        lines = lines[max(0, from_line - 1) :]
    if num_lines is not None:
        lines = lines[:num_lines]
    sliced_body = "\n".join(lines)

    if _json_out(
        {
            "id": entry_id,
            "content": sliced_body,
            "meta": {
                "scope": meta.get("scope", "team"),
                "tier": tier,
                "title": meta.get("title", ""),
                "tags": meta.get("tags", []),
                "agent": meta.get("agent", ""),
                "created": meta.get("created", ""),
                "accessed": meta.get("accessed", ""),
                "decay_score": meta.get("decay_score", 0),
            },
        },
        args,
    ):
        return 0

    print(sliced_body)
    return 0


def cmd_recover(args):
    """Run WAL recovery."""
    root = get_root()
    store = Store(root)
    recovered = store.recover()

    if _json_out({"replayed": recovered, "errors": 0}, args):
        return 0

    if recovered:
        print(f"Recovered {recovered} pending entries from WAL.")
    else:
        print("No pending WAL entries.")
    return 0


def cmd_list(args):
    """List memories in a tier."""
    root = get_root()
    store = Store(root)
    store.recover()

    tier = args.tier or "hot"
    entries = store.list_entries(tier)

    # Filter by project if specified
    project_filter = getattr(args, "project", None)
    if project_filter:
        entries = [(meta, body) for meta, body in entries if meta.get("project") == project_filter]

    if _json_out(
        {
            "tier": tier,
            "entries": [
                {
                    "id": meta.get("id", "?"),
                    "title": meta.get("title", "(untitled)"),
                    "scope": meta.get("scope", "team"),
                    "decay_score": meta.get("decay_score", 0),
                    "preview": body[:80].replace("\n", " "),
                }
                for meta, body in entries
            ],
        },
        args,
    ):
        return 0

    if not entries:
        print(f"No entries in {tier}.")
        return 0

    for meta, body in entries:
        title = meta.get("title", "(untitled)")
        entry_id = meta.get("id", "?")
        scope = meta.get("scope", "team")
        score = meta.get("decay_score", 0)
        preview = body[:80].replace("\n", " ")
        print(f"  {entry_id[:8]}  [{scope}] {title} (score: {score})")
        print(f"           {preview}...")

    print(f"\n{len(entries)} entries in {tier}.")
    return 0


def cmd_status(args):
    """Show system status."""
    root = get_root()
    store = Store(root)
    recovered = store.recover()

    info = store.status()

    if _json_out(info, args):
        return 0

    print(f"Palaia v{__version__}")
    print(f"Root: {info['palaia_root']}")
    print("\nEntries:")
    print(f"  🔥 HOT:  {info['entries']['hot']}")
    print(f"  🌤  WARM: {info['entries']['warm']}")
    print(f"  ❄️  COLD: {info['entries']['cold']}")
    print(f"  Total: {info['total']}")
    if info["wal_pending"]:
        print(f"\n⚠️  WAL pending: {info['wal_pending']}")
    if recovered:
        print(f"  Recovered: {recovered} entries")

    # Embedding chain status
    from palaia.embeddings import build_embedding_chain

    chain = build_embedding_chain(store.config)
    statuses = chain.provider_status()

    chain_display = " → ".join(s["name"] for s in statuses)
    print(f"\nEmbedding chain: {chain_display}")
    for i, s in enumerate(statuses, 1):
        model_str = f" ({s['model']})" if s.get("model") else ""
        mark = "✓" if s["available"] else "✗"
        print(f"  {i}. {s['name']}{model_str} {mark} {s['status']}")

    # Determine active provider
    has_embed = any(s["available"] and s["name"] != "bm25" for s in statuses)
    if chain.fallback_reason:
        active = chain.active_provider_name or "bm25"
        print(f"Active: {active} (fallback — {chain.fallback_reason})")
    elif has_embed:
        # First available non-bm25
        active = next((s["name"] for s in statuses if s["available"] and s["name"] != "bm25"), "bm25")
        print(f"Active: {active} (primary)")
    else:
        print("Active: bm25 (keyword search)")

    return 0


def cmd_detect(args):
    """Detect available embedding providers."""
    import platform

    from palaia.embeddings import detect_providers

    sys_info = f"{platform.system()} {platform.machine()}"
    py_ver = platform.python_version()

    providers = detect_providers()

    if _json_out(
        {
            "system": sys_info,
            "python": py_ver,
            "providers": providers,
        },
        args,
    ):
        return 0

    print("Palaia Environment Detection")
    print("=" * 29)
    print(f"System: {sys_info}")
    print(f"Python: {py_ver}")
    print()
    print("Embedding providers found:")

    available = []
    for p in providers:
        name = p["name"]
        if name == "ollama":
            if p["server_running"]:
                has_nomic = p.get("has_nomic", False)
                model_status = (
                    f"nomic-embed-text: {'available ✓' if has_nomic else 'not pulled (ollama pull nomic-embed-text)'}"
                )
                mark = "✓" if p["available"] else "△"
                print(f"  {mark} ollama        — server running at localhost:11434")
                print(f"                    {model_status}")
                if p["available"]:
                    available.append("ollama")
            else:
                print(f"  ✗ ollama        — server not running ({p.get('install_hint', 'start with: ollama serve')})")
        elif name == "sentence-transformers":
            if p["available"]:
                print(f"  ✓ sentence-transformers {p['version']} — installed")
                available.append("sentence-transformers")
            else:
                print(f"  ✗ sentence-transformers — not installed ({p['install_hint']})")
        elif name == "fastembed":
            if p["available"]:
                print(f"  ✓ fastembed {p['version']} — installed")
                available.append("fastembed")
            else:
                print(f"  ✗ fastembed     — not installed ({p['install_hint']})")
        elif name == "openai":
            if p["available"]:
                print("  ✓ OpenAI API    — key found")
                available.append("openai")
            else:
                print("  ✗ OpenAI API    — no key found")
        elif name == "voyage":
            if p["available"]:
                print("  ✓ Voyage API    — key found")
                available.append("voyage")
            else:
                print("  ✗ Voyage API    — no key found")

    print()
    print("BM25 keyword search: always available ✓")

    if available:
        rec = available[0]
        rec_desc = {
            "ollama": "ollama (server running, nomic-embed-text available)",
            "sentence-transformers": "sentence-transformers (installed, best local quality)",
            "fastembed": "fastembed (installed, lightweight)",
            "openai": "OpenAI API (cloud-based)",
        }
        print(f"\nRecommendation: {rec_desc.get(rec, rec)}")
        if len(available) > 1:
            alt = available[1]
            print(f"Alternatively:  {rec_desc.get(alt, alt)}")
    else:
        print("\nNo embedding providers found. Using keyword search (BM25).")
        print("Install one for semantic search: pip install 'palaia[sentence-transformers]'")

    # Recommended chain
    has_openai = "openai" in available
    has_local = any(p in available for p in ("sentence-transformers", "fastembed", "ollama"))
    local_name = next((p for p in ("sentence-transformers", "fastembed", "ollama") if p in available), None)

    print()
    if has_openai and has_local:
        chain_parts = ["openai", local_name, "bm25"]
        chain_str = " → ".join(chain_parts)
        print(f"Recommended chain: {chain_str}")
        print("  (Best quality cloud + best local fallback + always-on keyword backup)")
    elif has_local:
        chain_parts = [local_name, "bm25"]
        chain_str = " → ".join(chain_parts)
        print(f"Recommended chain: {chain_str}")
        print("  (Local provider, no cloud dependency)")
    elif has_openai:
        chain_parts = ["openai", "bm25"]
        chain_str = " → ".join(chain_parts)
        print(f"Recommended chain: {chain_str}")
        print("  (Cloud-based. Install sentence-transformers for offline fallback)")
    else:
        chain_parts = ["bm25"]
        chain_str = "bm25"
        print(f"Recommended chain: {chain_str}")
        print("  (Keyword search. pip install 'palaia[sentence-transformers]' for better results)")

    cmd_str = " ".join(chain_parts)
    print(f"\nSet with: palaia config set-chain {cmd_str}")

    # Show current config
    try:
        root = get_root()
        config = load_config(root)
        chain_cfg = config.get("embedding_chain")
        provider_cfg = config.get("embedding_provider", "auto")
        if chain_cfg:
            print(f"\nCurrent config: embedding_chain = {' → '.join(chain_cfg)}")
        else:
            print(f"\nCurrent config: embedding_provider = {provider_cfg}")
    except FileNotFoundError:
        print("\nCurrent config: not initialized (run 'palaia init' first)")

    return 0


def cmd_config_set_chain(args):
    """Set the embedding fallback chain."""
    root = get_root()
    config = load_config(root)

    chain = args.providers
    valid_providers = {"openai", "sentence-transformers", "fastembed", "ollama", "bm25"}
    for p in chain:
        if p not in valid_providers:
            if _json_out({"error": f"Unknown provider: {p}. Valid: {', '.join(sorted(valid_providers))}"}, args):
                return 1
            print(f"Unknown provider: {p}", file=sys.stderr)
            print(f"Valid providers: {', '.join(sorted(valid_providers))}", file=sys.stderr)
            return 1

    # Ensure bm25 at the end if not present
    if "bm25" not in chain:
        chain = chain + ["bm25"]

    config["embedding_chain"] = chain
    save_config(root, config)

    chain_str = " → ".join(chain)
    if _json_out({"embedding_chain": chain}, args):
        return 0
    print(f"Embedding chain: {chain_str}")
    return 0


def cmd_config(args):
    """Get or set configuration values."""
    if args.action == "set-chain":
        return cmd_config_set_chain(args)
    if args.action == "get":
        root = get_root()
        config = load_config(root)
        key = args.key
        if key in config:
            if _json_out({"key": key, "value": config[key]}, args):
                return 0
            print(f"{key} = {config[key]}")
        else:
            if _json_out({"error": f"Unknown key: {key}"}, args):
                return 1
            print(f"Unknown config key: {key}", file=sys.stderr)
            return 1
    elif args.action == "set":
        root = get_root()
        config = load_config(root)
        key = args.key
        value = args.value

        # Type coercion based on default config
        if key in DEFAULT_CONFIG:
            default_val = DEFAULT_CONFIG[key]
            if isinstance(default_val, int):
                try:
                    value = int(value)
                except ValueError:
                    pass
            elif isinstance(default_val, float):
                try:
                    value = float(value)
                except ValueError:
                    pass

        config[key] = value
        save_config(root, config)
        if _json_out({"key": key, "value": value}, args):
            return 0
        print(f"{key} = {value}")
    elif args.action == "list":
        root = get_root()
        config = load_config(root)
        if _json_out(config, args):
            return 0
        for k, v in sorted(config.items()):
            print(f"{k} = {v}")
    return 0


def cmd_warmup(args):
    """Pre-download embedding models for instant first search."""
    root = get_root()
    config = load_config(root)
    from palaia.embeddings import warmup_providers

    results = warmup_providers(config)

    if _json_out({"providers": results}, args):
        return 0

    if not results:
        print("No embedding providers configured (using BM25 keyword search).")
        return 0

    for r in results:
        if r["status"] == "ready":
            print(f"✓ {r['name']}: {r['message']}")
        elif r["status"] == "skipped":
            print(f"– {r['name']}: {r['message']}")
        elif r["status"] == "action_needed":
            print(f"△ {r['name']}: {r['message']}")
        else:
            print(f"✗ {r['name']}: {r['message']}")

    return 0


def cmd_gc(args):
    """Run garbage collection / tier rotation."""
    root = get_root()
    store = Store(root)
    store.recover()

    result = store.gc()

    if _json_out(result, args):
        return 0

    total_moves = sum(v for k, v in result.items() if k != "wal_cleaned")
    print("GC complete.")
    if total_moves:
        for k, v in result.items():
            if v and k != "wal_cleaned":
                print(f"  {k}: {v}")
    else:
        print("  No tier changes needed.")
    if result.get("wal_cleaned"):
        print(f"  WAL cleaned: {result['wal_cleaned']} old entries")
    return 0


def cmd_export(args):
    """Export public entries."""
    result = export_entries(
        remote=args.remote,
        branch=args.branch,
        output_dir=args.output,
    )

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
    result = import_entries(
        source=args.source,
        dry_run=args.dry_run,
    )

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


def cmd_migrate(args):
    """Migrate from external memory formats."""
    root = get_root()
    store = Store(root)
    store.recover()

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


def cmd_project(args):
    """Manage projects."""
    root = get_root()
    pm = ProjectManager(root)
    store = Store(root)
    store.recover()
    action = args.project_action

    if action == "create":
        try:
            project = pm.create(
                name=args.name,
                description=args.description or "",
                default_scope=args.default_scope or "team",
            )
        except ValueError as e:
            if _json_out({"error": str(e)}, args):
                return 1
            print(f"Error: {e}", file=sys.stderr)
            return 1
        if _json_out(project.to_dict(), args):
            return 0
        print(f"Created project: {project.name}")
        if project.description:
            print(f"  Description: {project.description}")
        print(f"  Default scope: {project.default_scope}")
        return 0

    elif action == "list":
        projects = pm.list()
        if _json_out({"projects": [p.to_dict() for p in projects]}, args):
            return 0
        if not projects:
            print("No projects.")
            return 0
        for p in projects:
            desc = f" — {p.description}" if p.description else ""
            print(f"  {p.name} [{p.default_scope}]{desc}")
        print(f"\n{len(projects)} project(s).")
        return 0

    elif action == "show":
        project = pm.get(args.name)
        if not project:
            if _json_out({"error": f"Project '{args.name}' not found."}, args):
                return 1
            print(f"Project '{args.name}' not found.", file=sys.stderr)
            return 1
        entries = pm.get_project_entries(args.name, store)
        if _json_out({
            "project": project.to_dict(),
            "entries": [
                {
                    "id": meta.get("id", "?"),
                    "title": meta.get("title", "(untitled)"),
                    "scope": meta.get("scope", "team"),
                    "tier": tier,
                    "preview": body[:80].replace("\n", " "),
                }
                for meta, body, tier in entries
            ],
        }, args):
            return 0
        desc = f" — {project.description}" if project.description else ""
        print(f"Project: {project.name}{desc}")
        print(f"  Default scope: {project.default_scope}")
        print(f"  Created: {project.created_at}")
        if entries:
            print(f"\n  Entries ({len(entries)}):")
            for meta, body, tier in entries:
                title = meta.get("title", "(untitled)")
                entry_id = meta.get("id", "?")
                scope = meta.get("scope", "team")
                preview = body[:80].replace("\n", " ")
                tier_badge = {"hot": "🔥", "warm": "🌤", "cold": "❄️"}.get(tier, "?")
                print(f"    {tier_badge} {entry_id[:8]}  [{scope}] {title}")
                print(f"              {preview}...")
        else:
            print("\n  No entries yet.")
        return 0

    elif action == "write":
        project = pm.get(args.name)
        if not project:
            if _json_out({"error": f"Project '{args.name}' not found."}, args):
                return 1
            print(f"Project '{args.name}' not found.", file=sys.stderr)
            return 1
        entry_id = store.write(
            body=args.text,
            scope=args.scope,
            agent=args.agent,
            tags=args.tags.split(",") if args.tags else None,
            title=args.title,
            project=args.name,
        )
        if _json_out({"id": entry_id, "project": args.name}, args):
            return 0
        print(f"Written to project '{args.name}': {entry_id}")
        return 0

    elif action == "query":
        project = pm.get(args.name)
        if not project:
            if _json_out({"error": f"Project '{args.name}' not found."}, args):
                return 1
            print(f"Project '{args.name}' not found.", file=sys.stderr)
            return 1
        engine = SearchEngine(store)
        results = engine.search(args.query, top_k=args.limit or 10, project=args.name)
        if _json_out({"results": results, "project": args.name}, args):
            return 0
        if not results:
            print(f"No results in project '{args.name}'.")
            return 0
        for r in results:
            tier_badge = {"hot": "🔥", "warm": "🌤", "cold": "❄️"}.get(r["tier"], "?")
            title = r["title"] or "(untitled)"
            print(f"\n{tier_badge} [{r['score']}] {title}")
            print(f"  ID: {r['id']}")
            print(f"  {r['body']}")
        print(f"\n{len(results)} result(s) in project '{args.name}'.")
        return 0

    elif action == "set-scope":
        try:
            project = pm.set_scope(args.name, args.scope_value)
        except ValueError as e:
            if _json_out({"error": str(e)}, args):
                return 1
            print(f"Error: {e}", file=sys.stderr)
            return 1
        if _json_out({"project": args.name, "default_scope": project.default_scope}, args):
            return 0
        print(f"Project '{args.name}' default scope → {project.default_scope}")
        return 0

    elif action == "delete":
        if not pm.delete(args.name, store):
            if _json_out({"error": f"Project '{args.name}' not found."}, args):
                return 1
            print(f"Project '{args.name}' not found.", file=sys.stderr)
            return 1
        if _json_out({"deleted": args.name}, args):
            return 0
        print(f"Deleted project '{args.name}'. Entries preserved (project tag removed).")
        return 0

    else:
        print("Unknown project action.", file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(
        prog="palaia",
        description="Palaia — Local, cloud-free memory for OpenClaw agents.",
    )
    parser.add_argument("--version", action="version", version=f"palaia {__version__}")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Initialize .palaia directory")
    p_init.add_argument("--path", default=None, help="Target directory")
    p_init.add_argument("--json", action="store_true", help="Output as JSON")

    # write
    p_write = sub.add_parser("write", help="Write a memory entry")
    p_write.add_argument("text", help="Memory content")
    p_write.add_argument("--scope", default=None, help="Scope tag")
    p_write.add_argument("--agent", default=None, help="Agent name")
    p_write.add_argument("--tags", default=None, help="Comma-separated tags")
    p_write.add_argument("--title", default=None, help="Entry title")
    p_write.add_argument("--project", default=None, help="Assign to project (uses project default scope)")
    p_write.add_argument("--json", action="store_true", help="Output as JSON")

    # query
    p_query = sub.add_parser("query", help="Search memories")
    p_query.add_argument("query", help="Search query")
    p_query.add_argument("--limit", type=int, default=10, help="Max results")
    p_query.add_argument("--all", action="store_true", help="Include COLD tier")
    p_query.add_argument("--project", default=None, help="Filter by project")
    p_query.add_argument("--json", action="store_true", help="Output as JSON")

    # get
    p_get = sub.add_parser("get", help="Read a specific memory entry")
    p_get.add_argument("path", help="Entry UUID or path (e.g. hot/uuid.md)")
    p_get.add_argument("--from", type=int, default=None, dest="from_line", help="Start from line number (1-indexed)")
    p_get.add_argument("--lines", type=int, default=None, help="Number of lines to return")
    p_get.add_argument("--json", action="store_true", help="Output as JSON")

    # recover
    p_recover = sub.add_parser("recover", help="Run WAL recovery")
    p_recover.add_argument("--json", action="store_true", help="Output as JSON")

    # list
    p_list = sub.add_parser("list", help="List entries in a tier")
    p_list.add_argument("--tier", default="hot", choices=["hot", "warm", "cold"])
    p_list.add_argument("--project", default=None, help="Filter by project")
    p_list.add_argument("--json", action="store_true", help="Output as JSON")

    # status
    p_status = sub.add_parser("status", help="Show system status")
    p_status.add_argument("--json", action="store_true", help="Output as JSON")

    # warmup
    p_warmup = sub.add_parser("warmup", help="Pre-download embedding models")
    p_warmup.add_argument("--json", action="store_true", help="Output as JSON")

    # gc
    p_gc = sub.add_parser("gc", help="Run garbage collection / tier rotation")
    p_gc.add_argument("--json", action="store_true", help="Output as JSON")

    # project
    p_project = sub.add_parser("project", help="Manage projects")
    project_sub = p_project.add_subparsers(dest="project_action")

    p_proj_create = project_sub.add_parser("create", help="Create a project")
    p_proj_create.add_argument("name", help="Project name")
    p_proj_create.add_argument("--description", default=None, help="Project description")
    p_proj_create.add_argument("--default-scope", default=None, help="Default scope for entries")
    p_proj_create.add_argument("--json", action="store_true", help="Output as JSON")

    p_proj_list = project_sub.add_parser("list", help="List projects")
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

    p_proj_delete = project_sub.add_parser("delete", help="Delete project (entries preserved)")
    p_proj_delete.add_argument("name", help="Project name")
    p_proj_delete.add_argument("--json", action="store_true", help="Output as JSON")

    # export
    p_export = sub.add_parser("export", help="Export public entries")
    p_export.add_argument("--remote", default=None, help="Git remote URL")
    p_export.add_argument("--branch", default=None, help="Branch name")
    p_export.add_argument("--output", default=None, help="Output directory")
    p_export.add_argument("--project", default=None, help="Export only project entries")
    p_export.add_argument("--json", action="store_true", help="Output as JSON")

    # import
    p_import = sub.add_parser("import", help="Import entries from export")
    p_import.add_argument("source", help="Path or git URL to import from")
    p_import.add_argument("--dry-run", action="store_true", help="Preview without writing")
    p_import.add_argument("--json", action="store_true", help="Output as JSON")

    # detect
    p_detect = sub.add_parser("detect", help="Detect available embedding providers")
    p_detect.add_argument("--json", action="store_true", help="Output as JSON")

    # config
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

    # migrate
    p_migrate = sub.add_parser("migrate", help="Import from external memory formats")
    p_migrate.add_argument("source", help="Source path (directory or file)")
    p_migrate.add_argument("--dry-run", action="store_true", help="Preview without writing")
    p_migrate.add_argument(
        "--format",
        default=None,
        dest="format_name",
        choices=["smart-memory", "flat-file", "json-memory", "generic-md"],
        help="Force source format",
    )
    p_migrate.add_argument("--scope", default=None, help="Override scope for all entries")
    p_migrate.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "init": cmd_init,
        "write": cmd_write,
        "query": cmd_query,
        "get": cmd_get,
        "recover": cmd_recover,
        "list": cmd_list,
        "status": cmd_status,
        "gc": cmd_gc,
        "export": cmd_export,
        "import": cmd_import,
        "migrate": cmd_migrate,
        "detect": cmd_detect,
        "config": cmd_config,
        "warmup": cmd_warmup,
        "project": cmd_project,
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
