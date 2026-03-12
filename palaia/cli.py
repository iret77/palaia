"""Palaia CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from palaia import __version__
from palaia.config import DEFAULT_CONFIG, find_palaia_root, get_root, load_config, save_config
from palaia.doctor import format_doctor_report, run_doctor
from palaia.ingest import DocumentIngestor, format_rag_output
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


def _detect_agents() -> list[str]:
    """Detect OpenClaw agents by checking ~/.openclaw/agents/ directory."""
    agents_dir = Path.home() / ".openclaw" / "agents"
    if not agents_dir.is_dir():
        return []
    return [d.name for d in agents_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]


def cmd_init(args):
    """Initialize .palaia directory."""
    target = Path(args.path or ".") / ".palaia"
    is_reinit = target.exists()

    if is_reinit:
        # Re-init: check if chain is already configured
        existing_config = load_config(target)
        existing_chain = existing_config.get("embedding_chain")
        if _json_out({"status": "exists", "path": str(target)}, args):
            return 0
        print(f"Already initialized: {target}")
        # Only auto-configure if no chain is set yet
        if existing_chain and len(existing_chain) > 0:
            return 0
        # Fall through to auto-configure chain
        config = existing_config
    else:
        target.mkdir(parents=True)
        for sub in ("hot", "warm", "cold", "wal", "index"):
            (target / sub).mkdir()
        config = dict(DEFAULT_CONFIG)

    # Auto-detect providers and configure the best chain
    from palaia.embeddings import detect_providers

    detected = detect_providers()
    detected_map = {p["name"]: p["available"] for p in detected}

    chain = []
    if detected_map.get("openai"):
        chain.append("openai")
    if detected_map.get("sentence-transformers"):
        chain.append("sentence-transformers")
    elif detected_map.get("fastembed"):
        chain.append("fastembed")
    elif detected_map.get("ollama"):
        chain.append("ollama")
    chain.append("bm25")  # always last

    config["embedding_chain"] = chain

    # Multi-agent detection
    agents = _detect_agents()
    if len(agents) > 1:
        store_mode = getattr(args, "store_mode", None)
        if store_mode == "isolated":
            config["store_mode"] = "isolated"
            print(f"🤖 Found {len(agents)} agents: {', '.join(agents)}")
            print("   Using isolated stores — each agent gets its own .palaia directory.")
        else:
            config["store_mode"] = "shared"
            print(f"🤖 Found {len(agents)} agents: {', '.join(agents)}")
            print(f"   Using shared store at {target}")
            print("   All agents will see team-scoped entries.")
            print("   Use --agent flag when writing so entries are attributed correctly.")
            if store_mode is None:
                print("   (Use 'palaia init --isolated' for separate stores per agent)")
    elif len(agents) == 1:
        print(f"🤖 Found 1 agent: {agents[0]}")
        config["store_mode"] = "shared"

    config["store_version"] = __version__
    save_config(target, config)

    if not is_reinit:
        if _json_out(
            {
                "status": "created",
                "path": str(target),
                "embedding_chain": chain,
                "agents": agents,
                "store_mode": config.get("store_mode", "shared"),
            },
            args,
        ):
            return 0
        print(f"Initialized Palaia at {target}")

    # Show chain info
    has_local = any(p in chain for p in ("sentence-transformers", "fastembed", "ollama"))
    has_openai = "openai" in chain
    if has_openai and not has_local:
        print(f"⚠️  Embedding chain: {' → '.join(chain)} (no local fallback)")
        print("   If OpenAI is unavailable, search quality will drop significantly.")
        print("   Recommend: pip install sentence-transformers && palaia warmup")
    elif len(chain) > 1:
        print(f"✅ Embedding chain configured: {' → '.join(chain)}")
    else:
        print("⚠️  No semantic search providers found. Using BM25 only.")
        print("   To enable semantic search, install one of:")
        print("   • sentence-transformers: pip install sentence-transformers")
        print("   • fastembed: pip install fastembed")
        print("   • ollama: https://ollama.ai (then: palaia config set-chain ollama bm25)")
        print("   • OpenAI: set OPENAI_API_KEY env var")
        print("   Then run: palaia warmup")

    # Post-init instructions for LLM agents
    print()
    print("⚠️  SETUP REQUIRED — Continue with these steps:")
    print("1. Run: palaia doctor --fix")
    print("   (Checks your system, fixes common issues, configures version tracking)")
    print("2. Run: palaia detect")
    print("   (Finds available search providers on your system)")
    print("3. Run: palaia warmup")
    print("   (Pre-downloads embedding models for instant search)")
    print("4. Read the palaia SKILL.md section 'Plugin Activation' and configure the OpenClaw memory plugin")
    print("   (npm install -g @byte5ai/palaia, then patch openclaw.json, then restart gateway)")
    print("5. Report your setup results to the user")
    print()
    print("Do NOT skip these steps. The memory system is not fully operational until all steps are complete.")

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
        agent=getattr(args, "agent", None),
    )

    if _json_out({"results": results}, args):
        return 0

    # BM25-only note
    if not engine.has_embeddings and not getattr(args, "json", False):
        config = load_config(root)
        chain_cfg = config.get("embedding_chain", [])
        bm25_only = not chain_cfg or chain_cfg == ["bm25"]
        if bm25_only:
            print("Note: Keyword search only (BM25). For semantic search: pip install sentence-transformers")
            print()

    if not results:
        print("No results found.")
        return 0

    # RAG output format
    if getattr(args, "rag", False):
        # Enrich results with full body and source metadata for RAG
        enriched = []
        for r in results:
            entry = store.read(r["id"])
            if entry:
                meta, body = entry
                r["full_body"] = body
                r["source"] = meta.get("source", "")
                r["chunk_index"] = meta.get("chunk_index", 0) if isinstance(meta.get("chunk_index"), int) else 0
                r["chunk_total"] = meta.get("chunk_total", 0) if isinstance(meta.get("chunk_total"), int) else 0
            enriched.append(r)
        print(format_rag_output(args.query, enriched))
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

    search_tier = "hybrid" if engine.has_embeddings else "BM25"
    print(f"\n{len(results)} result(s) found. (Search tier: {search_tier})")
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

    entry = store.read(entry_id, agent=getattr(args, "agent", None))
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


def cmd_ingest(args):
    """Ingest documents for RAG."""
    root = get_root()
    store = Store(root)
    store.recover()

    ingestor = DocumentIngestor(store)
    source = args.source

    # Auto-create project if specified and doesn't exist (#9)
    if args.project and not args.dry_run:
        pm = ProjectManager(root)
        pm.ensure(args.project)

    if not getattr(args, "json", False) and not args.dry_run:
        print(f"Ingesting: {source}")

    try:
        result = ingestor.ingest(
            source=source,
            project=args.project,
            scope=args.scope or "private",
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
            tags=args.tags.split(",") if args.tags else None,
            dry_run=args.dry_run,
        )
    except ImportError as e:
        if _json_out({"error": str(e)}, args):
            return 1
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        if _json_out({"error": str(e)}, args):
            return 1
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if _json_out(
        {
            "source": result.source,
            "total_chunks": result.total_chunks,
            "stored_chunks": result.stored_chunks,
            "skipped_chunks": result.skipped_chunks,
            "project": result.project,
            "entry_ids": result.entry_ids,
            "duration_seconds": result.duration_seconds,
            "dry_run": args.dry_run,
        },
        args,
    ):
        return 0

    if args.dry_run:
        print(f"  Dry run: {result.total_chunks} chunks would be created")
        print(f"  Skipped (too short): {result.skipped_chunks}")
        return 0

    print(f"  Chunking: {args.chunk_size} words, {args.chunk_overlap} overlap → {result.total_chunks} chunks")
    print(f"\nDone in {result.duration_seconds}s")
    print(f"  ✅ {result.stored_chunks} chunks stored")
    if result.skipped_chunks:
        print(f"  ⏭  {result.skipped_chunks} chunks skipped (too short)")
    if result.project:
        print(f"  Project: {result.project}")
    print(f"  Scope: {args.scope or 'private'}")
    if result.project:
        print(f'\nSearch with: palaia query "your question" --project {result.project}')
    else:
        print('\nSearch with: palaia query "your question"')

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
    entries = store.list_entries(tier, agent=getattr(args, "agent", None))

    # Apply filters (#12)
    project_filter = getattr(args, "project", None)
    tag_filter = getattr(args, "tag", None)
    scope_filter = getattr(args, "scope", None)
    agent_filter = getattr(args, "agent", None)

    if project_filter:
        entries = [(meta, body) for meta, body in entries if meta.get("project") == project_filter]
    if tag_filter:
        entries = [(meta, body) for meta, body in entries if tag_filter in (meta.get("tags") or [])]
    if scope_filter:
        entries = [(meta, body) for meta, body in entries if meta.get("scope") == scope_filter]
    if agent_filter:
        entries = [(meta, body) for meta, body in entries if meta.get("agent") == agent_filter]

    if _json_out(
        {
            "tier": tier,
            "entries": [
                {
                    "id": meta.get("id", "?"),
                    "title": meta.get("title", "(untitled)"),
                    "scope": meta.get("scope", "team"),
                    "agent": meta.get("agent", ""),
                    "tags": meta.get("tags", []),
                    "project": meta.get("project", ""),
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

    # BM25-only warning
    bm25_only = all(s["name"] == "bm25" for s in statuses) or not has_embed
    if bm25_only:
        print()
        print("⚠️  Semantic search is not enabled.")
        print("   Results are keyword-based only.")
        print("   Run 'palaia detect' to see available providers.")
        print("   Run 'palaia warmup' after adding a provider.")

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


def cmd_doctor(args):
    """Run diagnostics on the local Palaia instance."""
    palaia_root = find_palaia_root()

    results = run_doctor(palaia_root)

    if _json_out({"checks": results}, args):
        return 0

    show_fix = getattr(args, "fix", False)
    print(format_doctor_report(results, show_fix=show_fix))
    return 0


def cmd_export(args):
    """Export public entries."""
    result = export_entries(
        remote=args.remote,
        branch=args.branch,
        output_dir=args.output,
        agent=getattr(args, "agent", None),
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


def cmd_setup(args):
    """Multi-agent setup: create .palaia symlinks for agent directories."""
    if not args.multi_agent:
        print("Usage: palaia setup --multi-agent <agents-dir>", file=sys.stderr)
        return 1

    agents_dir = Path(args.multi_agent)
    if not agents_dir.is_dir():
        msg = f"Directory not found: {agents_dir}"
        if _json_out({"error": msg}, args):
            return 1
        print(f"Error: {msg}", file=sys.stderr)
        return 1

    root = get_root()
    store_path = root  # The .palaia directory itself

    # Scan for agent subdirectories
    agent_dirs = sorted([d for d in agents_dir.iterdir() if d.is_dir() and not d.name.startswith(".")])

    if not agent_dirs:
        msg = f"No agent directories found in {agents_dir}"
        if _json_out({"error": msg, "agents": []}, args):
            return 1
        print(f"No agent directories found in {agents_dir}", file=sys.stderr)
        return 1

    dry_run = getattr(args, "dry_run", False)
    agents = []
    symlinks_created = 0

    for agent_dir in agent_dirs:
        agent_name = agent_dir.name
        symlink_path = agent_dir / ".palaia"
        agents.append(agent_name)

        if symlink_path.exists() or symlink_path.is_symlink():
            if not dry_run and not getattr(args, "json", False):
                print(f"  ⏭  {agent_name}: .palaia already exists")
            continue

        if dry_run:
            if not getattr(args, "json", False):
                print(f"  🔗 {agent_name}: would create .palaia → {store_path}")
            symlinks_created += 1
        else:
            try:
                symlink_path.symlink_to(store_path)
                symlinks_created += 1
                if not getattr(args, "json", False):
                    print(f"  ✅ {agent_name}: .palaia → {store_path}")
            except OSError as e:
                if not getattr(args, "json", False):
                    print(f"  ❌ {agent_name}: {e}")

    result = {
        "agents": agents,
        "symlinks_created": symlinks_created,
        "store_path": str(store_path),
        "dry_run": dry_run,
    }

    if _json_out(result, args):
        return 0

    if not dry_run:
        print(f"\n{symlinks_created} symlink(s) created for {len(agents)} agent(s).")
    else:
        print(f"\nDry run: {symlinks_created} symlink(s) would be created for {len(agents)} agent(s).")
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
        if _json_out(
            {
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
            },
            args,
        ):
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


def _format_lock_human(lock_data: dict) -> str:
    """Format lock info for human-readable output."""
    from datetime import datetime

    agent = lock_data.get("agent", "unknown")
    acquired = lock_data.get("acquired", "?")
    reason = lock_data.get("reason", "")
    age = lock_data.get("age_seconds", 0)

    # Format age
    if age >= 3600:
        age_str = f"{age // 3600}h {(age % 3600) // 60}min ago"
    elif age >= 60:
        age_str = f"{age // 60}min ago"
    else:
        age_str = f"{age}s ago"

    # Format acquired time (show HH:MM)
    try:
        dt = datetime.fromisoformat(acquired)
        time_str = dt.strftime("%H:%M")
    except (ValueError, TypeError):
        time_str = acquired

    result = f"🔒 Locked by {agent} since {time_str} ({age_str})"
    if reason:
        result += f"\n   Reason: {reason}"
    return result


def cmd_lock(args):
    """Manage project locks."""
    from palaia.locking import ProjectLockError, ProjectLockManager

    root = get_root()
    lm = ProjectLockManager(root)

    # Parse action_or_project: if it's a known subcommand, use it; otherwise treat as project name
    known_actions = {"status", "renew", "break", "list"}
    aop = getattr(args, "action_or_project", None)
    project_arg = getattr(args, "project", None)

    if aop in known_actions:
        action = aop
        project = project_arg  # may be None for status/list
    elif aop is not None:
        # It's a project name → acquire shorthand
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

        try:
            lock_data = lm.acquire(project, agent, reason, ttl)
        except ProjectLockError as e:
            if _json_out({"error": str(e), "locked": True}, args):
                return 1
            print(f"Error: {e}", file=sys.stderr)
            return 1

        if _json_out(lock_data, args):
            return 0
        print(f"🔒 Locked project '{project}' for agent '{agent}'")
        if reason:
            print(f"   Reason: {reason}")
        ttl_min = lock_data.get("ttl_seconds", 1800) // 60
        print(f"   TTL: {ttl_min} minutes (expires {lock_data['expires']})")
        return 0

    elif action == "status":
        if project:
            info = lm.status(project)
            if info is None:
                if _json_out({"project": project, "locked": False}, args):
                    return 0
                print(f"Project '{project}' is not locked.")
                return 0
            if _json_out(info, args):
                return 0
            print(_format_lock_human(info))
            return 0
        else:
            # All projects
            locks = lm.list_locks()
            if _json_out({"locks": locks}, args):
                return 0
            if not locks:
                print("No active locks.")
                return 0
            for lock in locks:
                print(f"  {lock['project']}: {_format_lock_human(lock)}")
            print(f"\n{len(locks)} active lock(s).")
            return 0

    elif action == "renew":
        if not project:
            if _json_out({"error": "Project name required"}, args):
                return 1
            print("Error: Project name required.", file=sys.stderr)
            return 1
        try:
            lock_data = lm.renew(project)
        except ProjectLockError as e:
            if _json_out({"error": str(e)}, args):
                return 1
            print(f"Error: {e}", file=sys.stderr)
            return 1
        if _json_out(lock_data, args):
            return 0
        ttl_min = lock_data.get("ttl_seconds", 1800) // 60
        print(f"🔄 Lock renewed for project '{project}' — expires {lock_data['expires']} ({ttl_min}min)")
        return 0

    elif action == "break":
        if not project:
            if _json_out({"error": "Project name required"}, args):
                return 1
            print("Error: Project name required.", file=sys.stderr)
            return 1
        old = lm.break_lock(project)
        if old:
            if _json_out({"broken": True, "previous_lock": old}, args):
                return 0
            print(f"⚠️  Lock for project '{project}' force-broken (was held by {old.get('agent', '?')})")
        else:
            if _json_out({"broken": False, "project": project}, args):
                return 0
            print(f"No lock found for project '{project}'.")
        return 0

    elif action == "list":
        locks = lm.list_locks()
        if _json_out({"locks": locks}, args):
            return 0
        if not locks:
            print("No active locks.")
            return 0
        for lock in locks:
            print(f"  {lock['project']}: {_format_lock_human(lock)}")
        print(f"\n{len(locks)} active lock(s).")
        return 0

    elif action is None:
        # palaia lock (no args) — show all lock statuses
        locks = lm.list_locks()
        if _json_out({"locks": locks}, args):
            return 0
        if not locks:
            print("No active locks.")
            return 0
        for lock in locks:
            print(f"  {lock['project']}: {_format_lock_human(lock)}")
        print(f"\n{len(locks)} active lock(s).")
        return 0

    else:
        print("Unknown lock action. Use: acquire, status, renew, break, list", file=sys.stderr)
        return 1


def cmd_unlock(args):
    """Release a project lock."""
    from palaia.locking import ProjectLockManager

    root = get_root()
    lm = ProjectLockManager(root)
    project = args.project

    removed = lm.release(project)
    if removed:
        if _json_out({"unlocked": True, "project": project}, args):
            return 0
        print(f"🔓 Unlocked project '{project}'")
    else:
        if _json_out({"unlocked": False, "project": project}, args):
            return 0
        print(f"Project '{project}' was not locked.")
    return 0


def cmd_memo(args):
    """Manage inter-agent memos."""
    from palaia.memo import MemoManager

    root = get_root()
    mm = MemoManager(root)
    action = args.memo_action

    if action == "send":
        meta = mm.send(
            to=args.to,
            message=args.message,
            from_agent=args.agent,
            priority=args.priority,
            ttl_hours=args.ttl_hours,
        )
        if _json_out(meta, args):
            return 0
        prio_icon = "🔴" if meta["priority"] == "high" else "📨"
        print(f"{prio_icon} Memo sent to '{meta['to']}' (id: {meta['id'][:8]}…)")
        return 0

    if action == "broadcast":
        meta = mm.broadcast(
            message=args.message,
            from_agent=args.agent,
            priority=args.priority,
            ttl_hours=args.ttl_hours,
        )
        if _json_out(meta, args):
            return 0
        print(f"📢 Broadcast sent (id: {meta['id'][:8]}…)")
        return 0

    if action == "inbox":
        memos = mm.inbox(agent=args.agent, include_read=args.all)
        if _json_out(
            [{"meta": m, "body": b} for m, b in memos],
            args,
        ):
            return 0
        if not memos:
            print("📭 No memos.")
            return 0
        print(f"📬 {len(memos)} memo(s):\n")
        for meta, body in memos:
            prio = " 🔴" if meta.get("priority") == "high" else ""
            read_mark = " ✓" if meta.get("read") else ""
            print(f"  [{meta['id'][:8]}…] from {meta.get('from', '?')}{prio}{read_mark}")
            print(f"    {meta.get('sent', '?')}")
            # Show first line of body
            first_line = body.split("\n")[0][:80] if body else ""
            print(f"    {first_line}")
            print()
        return 0

    if action == "ack":
        if args.all:
            count = mm.ack_all(agent=args.agent)
            if _json_out({"acked": count}, args):
                return 0
            print(f"✅ Acknowledged {count} memo(s).")
            return 0
        if not args.memo_id:
            print("Error: memo ID required (or use --all)", file=sys.stderr)
            return 1
        ok = mm.ack(args.memo_id)
        if _json_out({"acked": ok, "id": args.memo_id}, args):
            return 0
        if ok:
            print(f"✅ Memo {args.memo_id[:8]}… acknowledged.")
        else:
            print(f"Memo {args.memo_id} not found.", file=sys.stderr)
            return 1
        return 0

    if action == "gc":
        stats = mm.gc()
        if _json_out(stats, args):
            return 0
        print(
            f"🧹 GC: removed {stats['removed_expired']} expired, "
            f"{stats['removed_read']} read ({stats['total_removed']} total)"
        )
        return 0

    print("Unknown memo action. Use: send, broadcast, inbox, ack, gc", file=sys.stderr)
    return 1


def _detect_current_agent() -> str | None:
    """Try to detect the current agent name from env or config."""
    import os

    # Check environment variable first
    agent = os.environ.get("PALAIA_AGENT")
    if agent:
        return agent

    # Try to read from OpenClaw agent config
    agent_config = Path.home() / ".openclaw" / "config.json"
    if agent_config.exists():
        try:
            with open(agent_config, "r") as f:
                cfg = json.load(f)
            return cfg.get("agent_name")
        except (json.JSONDecodeError, OSError):
            pass

    return None


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
    p_init.add_argument(
        "--isolated",
        action="store_const",
        const="isolated",
        dest="store_mode",
        help="Use isolated stores per agent (default: shared)",
    )

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
    p_query.add_argument("--agent", default=None, help="Agent name (for scope filtering)")
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
    p_list.add_argument("--tier", default="hot", choices=["hot", "warm", "cold"])
    p_list.add_argument("--project", default=None, help="Filter by project")
    p_list.add_argument("--tag", default=None, help="Filter by tag")
    p_list.add_argument("--scope", default=None, help="Filter by scope")
    p_list.add_argument("--agent", default=None, help="Filter by agent")
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

    # memo
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

    # lock — first positional is action_or_project (allows "palaia lock <project>" shorthand)
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

    # unlock (shorthand for lock release)
    p_unlock = sub.add_parser("unlock", help="Release a project lock")
    p_unlock.add_argument("project", help="Project name")
    p_unlock.add_argument("--json", action="store_true", help="Output as JSON")

    # setup
    p_setup = sub.add_parser("setup", help="Multi-agent setup")
    p_setup.add_argument("--multi-agent", default=None, help="Path to agents directory")
    p_setup.add_argument("--dry-run", action="store_true", help="Preview without creating symlinks")
    p_setup.add_argument("--json", action="store_true", help="Output as JSON")

    # doctor
    p_doctor = sub.add_parser("doctor", help="Diagnose Palaia instance and detect legacy systems")
    p_doctor.add_argument("--fix", action="store_true", help="Show guided fix instructions for each warning")
    p_doctor.add_argument("--json", action="store_true", help="Output as JSON")

    # export
    p_export = sub.add_parser("export", help="Export public entries")
    p_export.add_argument("--remote", default=None, help="Git remote URL")
    p_export.add_argument("--branch", default=None, help="Branch name")
    p_export.add_argument("--output", default=None, help="Output directory")
    p_export.add_argument("--project", default=None, help="Export only project entries")
    p_export.add_argument("--agent", default=None, help="Agent name (for scope filtering)")
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

    # Version drift warning (skip for init/doctor/detect)
    if args.command not in ("init", "doctor", "detect") and not getattr(args, "json", False):
        try:
            root = find_palaia_root()
            if root:
                cfg = load_config(root)
                store_ver = cfg.get("store_version", "")
                if store_ver and store_ver != __version__:
                    print(
                        f"⚠️  Store created with v{store_ver}, running v{__version__}. "
                        "Run `palaia doctor` for upgrade checks.",
                        file=sys.stderr,
                    )
        except Exception:
            pass

    commands = {
        "init": cmd_init,
        "write": cmd_write,
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
        "memo": cmd_memo,
        "lock": cmd_lock,
        "unlock": cmd_unlock,
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
