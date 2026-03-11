"""Palaia CLI entry point."""

import argparse
import json
import sys
from pathlib import Path

from palaia import __version__
from palaia.config import DEFAULT_CONFIG, find_palaia_root, get_root, save_config
from palaia.store import Store
from palaia.search import SearchEngine


def cmd_init(args):
    """Initialize .palaia directory."""
    target = Path(args.path or ".") / ".palaia"
    if target.exists():
        print(f"Already initialized: {target}")
        return 0

    target.mkdir(parents=True)
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (target / sub).mkdir()
    save_config(target, DEFAULT_CONFIG)
    print(f"Initialized Palaia at {target}")
    return 0


def cmd_write(args):
    """Write a memory entry."""
    root = get_root()
    store = Store(root)
    
    # Recovery check
    recovered = store.recover()
    if recovered:
        print(f"Recovered {recovered} pending entries from WAL.")

    entry_id = store.write(
        body=args.text,
        scope=args.scope,
        agent=args.agent,
        tags=args.tags.split(",") if args.tags else None,
        title=args.title,
    )
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
    )

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


def cmd_list(args):
    """List memories in a tier."""
    root = get_root()
    store = Store(root)
    store.recover()

    tier = args.tier or "hot"
    entries = store.list_entries(tier)

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
    print(f"Palaia v{__version__}")
    print(f"Root: {info['palaia_root']}")
    print(f"\nEntries:")
    print(f"  🔥 HOT:  {info['entries']['hot']}")
    print(f"  🌤  WARM: {info['entries']['warm']}")
    print(f"  ❄️  COLD: {info['entries']['cold']}")
    print(f"  Total: {info['total']}")
    if info['wal_pending']:
        print(f"\n⚠️  WAL pending: {info['wal_pending']}")
    if recovered:
        print(f"  Recovered: {recovered} entries")

    from palaia.search import detect_search_tier
    tier = detect_search_tier()
    tier_names = {1: "BM25 (Python)", 2: "Ollama Embeddings", 3: "API Embeddings"}
    print(f"\nSearch: {tier_names[tier]}")
    return 0


def cmd_gc(args):
    """Run garbage collection / tier rotation."""
    root = get_root()
    store = Store(root)
    store.recover()

    result = store.gc()
    total_moves = sum(v for k, v in result.items() if k != "wal_cleaned")
    print(f"GC complete.")
    if total_moves:
        for k, v in result.items():
            if v and k != "wal_cleaned":
                print(f"  {k}: {v}")
    else:
        print("  No tier changes needed.")
    if result.get("wal_cleaned"):
        print(f"  WAL cleaned: {result['wal_cleaned']} old entries")
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="palaia",
        description="Palaia — Local, cloud-free memory for OpenClaw agents.",
    )
    parser.add_argument("--version", action="version", version=f"palaia {__version__}")

    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Initialize .palaia directory")
    p_init.add_argument("--path", default=None, help="Target directory")

    # write
    p_write = sub.add_parser("write", help="Write a memory entry")
    p_write.add_argument("text", help="Memory content")
    p_write.add_argument("--scope", default=None, help="Scope tag")
    p_write.add_argument("--agent", default=None, help="Agent name")
    p_write.add_argument("--tags", default=None, help="Comma-separated tags")
    p_write.add_argument("--title", default=None, help="Entry title")

    # query
    p_query = sub.add_parser("query", help="Search memories")
    p_query.add_argument("query", help="Search query")
    p_query.add_argument("--limit", type=int, default=10, help="Max results")
    p_query.add_argument("--all", action="store_true", help="Include COLD tier")

    # list
    p_list = sub.add_parser("list", help="List entries in a tier")
    p_list.add_argument("--tier", default="hot", choices=["hot", "warm", "cold"])

    # status
    sub.add_parser("status", help="Show system status")

    # gc
    sub.add_parser("gc", help="Run garbage collection / tier rotation")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "init": cmd_init,
        "write": cmd_write,
        "query": cmd_query,
        "list": cmd_list,
        "status": cmd_status,
        "gc": cmd_gc,
    }
    try:
        return commands[args.command](args)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
