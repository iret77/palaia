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
from palaia.config import (  # noqa: E402
    DEFAULT_CONFIG,
    clear_instance,
    find_palaia_root,
    get_agent,
    get_instance,
    get_root,
    is_initialized,
    load_config,
    save_config,
    set_instance,
)
from palaia.doctor import apply_fixes, format_doctor_report, run_doctor  # noqa: E402
from palaia.ingest import DocumentIngestor, format_rag_output  # noqa: E402
from palaia.migrate import format_result, migrate  # noqa: E402
from palaia.project import ProjectManager  # noqa: E402
from palaia.search import SearchEngine  # noqa: E402
from palaia.store import Store  # noqa: E402
from palaia.sync import export_entries, import_entries  # noqa: E402
from palaia.ui import (  # noqa: E402
    format_size,
    print_header,
    relative_time,
    score_display,
    section,
    table_kv,
    table_multi,
    truncate,
)


def check_version_nag():
    """Warn if installed palaia version is newer than store version."""
    try:
        from palaia import __version__
        from palaia.config import find_palaia_root

        root = find_palaia_root()
        if not root:
            return

        config_path = root / "config.json"
        if not config_path.exists():
            return

        config = json.loads(config_path.read_text())
        store_version = config.get("store_version", "")

        if not store_version:
            # No store version = needs palaia doctor
            print("Warning: Palaia store has no version stamp. Run: palaia doctor --fix", file=sys.stderr)
            return

        if store_version != __version__:
            print(
                f"Warning: Palaia CLI is v{__version__} but store is v{store_version}. Run: palaia doctor --fix",
                file=sys.stderr,
            )
    except Exception:
        pass  # Never block normal operation


def _json_out(data, args):
    """Print JSON if --json flag is set, return True if printed."""
    if getattr(args, "json", False):
        print(json.dumps(data, ensure_ascii=False))
        return True
    return False


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
        "lock",
        "unlock",
        "setup",
        "warmup",
        "migrate",
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
        print("Palaia not initialized. Run: palaia init --agent YOUR_NAME", file=sys.stderr)
        return False
    if not is_initialized(root):
        print("Palaia not initialized. Run: palaia init --agent YOUR_NAME", file=sys.stderr)
        return False
    return True


def _resolve_agent(args) -> str | None:
    """Resolve agent name: explicit --agent flag > config > env var > None.

    For gated commands, config agent is always available (gatekeeper ensures init).
    """
    explicit = getattr(args, "agent", None)
    if explicit:
        return explicit
    try:
        root = get_root()
        config_agent = get_agent(root)
        if config_agent:
            return config_agent
    except FileNotFoundError:
        pass
    return _detect_current_agent()


def _resolve_instance_for_write(args) -> str | None:
    """Resolve instance: explicit --instance flag > config file > env var > None."""
    explicit = getattr(args, "instance", None)
    if explicit:
        return explicit
    try:
        root = get_root()
        return get_instance(root)
    except FileNotFoundError:
        pass
    return None


def _memo_nudge(args) -> None:
    """Check for unread memos and print a nudge if any exist.

    Frequency-limited to max once per hour. Suppressed in --json mode.
    """
    if getattr(args, "json", False):
        return
    try:
        import time

        root = get_root()
        hints_file = root / ".hints_shown"
        shown = {}
        if hints_file.exists():
            try:
                shown = json.loads(hints_file.read_text())
            except (json.JSONDecodeError, OSError):
                shown = {}
            last_nudge = shown.get("memo_nudge", 0)
            if time.time() - last_nudge < 3600:
                return

        # Check unread memo count
        agent = _resolve_agent(args)
        if not agent:
            return

        from palaia.memo import MemoManager

        mm = MemoManager(root)
        unread = mm.inbox(agent=agent, include_read=False)
        if not unread:
            return

        count = len(unread)
        print(f"\nYou have {count} unread memo(s). Run: palaia memo inbox", file=sys.stderr)

        # Update frequency limiter
        shown["memo_nudge"] = time.time()
        try:
            hints_file.write_text(json.dumps(shown))
        except OSError:
            pass
    except Exception:
        pass  # Never block normal operation


def _detect_agents() -> list[str]:
    """Detect OpenClaw agents by checking ~/.openclaw/agents/ directory."""
    agents_dir = Path.home() / ".openclaw" / "agents"
    if not agents_dir.is_dir():
        return []
    return [d.name for d in agents_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]


def cmd_init(args):
    """Initialize .palaia directory."""
    # Respect PALAIA_HOME if set and no explicit path given
    explicit_path = getattr(args, "path", None)
    if explicit_path:
        target = Path(explicit_path) / ".palaia"
    else:
        env_home = os.environ.get("PALAIA_HOME")
        if env_home:
            env_path = Path(env_home)
            if env_path.name == ".palaia":
                target = env_path
            else:
                target = env_path / ".palaia"
        else:
            target = Path(".") / ".palaia"
    is_reinit = target.exists()
    agent_name = getattr(args, "agent", None)

    # Block fresh init without --agent (Issue #46)
    if not is_reinit and not agent_name:
        msg = "Error: Agent name required. Run: palaia init --agent YOUR_NAME"
        if _json_out({"error": "agent_required", "message": msg}, args):
            return 1
        print(msg, file=sys.stderr)
        return 1

    # Block re-init without --agent if no agent is configured yet
    if is_reinit and not agent_name:
        try:
            existing_config = load_config(target)
            if not existing_config.get("agent"):
                msg = "Error: Agent name required. Run: palaia init --agent YOUR_NAME"
                if _json_out({"error": "agent_required", "message": msg}, args):
                    return 1
                print(msg, file=sys.stderr)
                return 1
        except (json.JSONDecodeError, OSError):
            pass

    if is_reinit:
        # Re-init: update only explicitly provided values
        existing_config = load_config(target)

        # Update agent if provided
        if agent_name:
            existing_config["agent"] = agent_name

        # Check if chain is already configured
        existing_chain = existing_config.get("embedding_chain")

        if existing_chain and len(existing_chain) > 0:
            # Chain exists, just save updated config (agent may have changed)
            save_config(target, existing_config)
            if _json_out({"status": "updated", "path": str(target), "agent": existing_config.get("agent")}, args):
                return 0
            print(f"Updated config: {target}")
            if existing_config.get("agent"):
                print(f"Agent: {existing_config['agent']}")
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

    # Store agent identity if provided
    if agent_name:
        config["agent"] = agent_name

    # Multi-agent detection
    agents = _detect_agents()
    if len(agents) > 1:
        store_mode = getattr(args, "store_mode", None)
        if store_mode == "isolated":
            config["store_mode"] = "isolated"
            print(f"Found {len(agents)} agents: {', '.join(agents)}")
            print("  Using isolated stores — each agent gets its own .palaia directory.")
        else:
            config["store_mode"] = "shared"
            print(f"Found {len(agents)} agents: {', '.join(agents)}")
            print(f"  Using shared store at {target}")
            print("  All agents will see team-scoped entries.")
            print("  Use --agent flag when writing so entries are attributed correctly.")
            if store_mode is None:
                print("  (Use 'palaia init --isolated' for separate stores per agent)")
    elif len(agents) == 1:
        print(f"Found 1 agent: {agents[0]}")
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
        print(f"Embedding chain: {' -> '.join(chain)} (no local fallback)")
        print("  If OpenAI is unavailable, search quality will drop significantly.")
        print("  Recommend: pip install sentence-transformers && palaia warmup")
    elif len(chain) > 1:
        print(f"Embedding chain configured: {' -> '.join(chain)}")
    else:
        print("No semantic search providers found. Using BM25 only.")
        print("  To enable semantic search, install one of:")
        print("  - sentence-transformers: pip install sentence-transformers")
        print("  - fastembed: pip install fastembed")
        print("  - ollama: https://ollama.ai (then: palaia config set-chain ollama bm25)")
        print("  - OpenAI: set OPENAI_API_KEY env var")
        print("  Then run: palaia warmup")

    # Post-init instructions for LLM agents
    print()
    print("SETUP REQUIRED — Continue with these steps:")
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


def _nudge_hint(hint_key: str, message: str, args) -> None:
    """Print an agent nudging hint if not in JSON mode and not recently shown."""
    if getattr(args, "json", False):
        return
    # Frequency limiting: use a simple file marker
    try:
        root = get_root()
        hints_file = root / ".hints_shown"
        shown = {}
        if hints_file.exists():
            import time

            shown = json.loads(hints_file.read_text())
            last_shown = shown.get(hint_key, 0)
            # Don't repeat within 1 hour
            if time.time() - last_shown < 3600:
                return
        import time

        shown[hint_key] = time.time()
        hints_file.write_text(json.dumps(shown))
    except Exception:
        pass
    print(f"\nHint: {message}", file=sys.stderr)


def cmd_write(args):
    """Write a memory entry."""
    check_version_nag()
    root = get_root()
    store = Store(root)

    # Recovery check
    recovered = store.recover()
    if recovered and not getattr(args, "json", False):
        print(f"Recovered {recovered} pending entries from WAL.")

    # Resolve agent from config if not explicitly set
    agent = _resolve_agent(args)
    instance = _resolve_instance_for_write(args)

    entry_type = getattr(args, "type", None)
    entry_id = store.write(
        body=args.text,
        scope=args.scope,
        agent=agent,
        tags=args.tags.split(",") if args.tags else None,
        title=args.title,
        project=getattr(args, "project", None),
        entry_type=entry_type,
        status=getattr(args, "status", None),
        priority=getattr(args, "priority", None),
        assignee=getattr(args, "assignee", None),
        due_date=getattr(args, "due_date", None),
        instance=instance,
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

    # Agent nudging: hint about --type if not specified (ADR-011)
    if not entry_type:
        _nudge_hint(
            "write_type",
            "Use --type (memory|process|task) to classify entries. Tasks support --status, --priority, --assignee.",
            args,
        )

    # Memo nudge (ADR-011)
    _memo_nudge(args)

    return 0


def cmd_edit(args):
    """Edit an existing memory entry."""
    check_version_nag()
    root = get_root()
    store = Store(root)
    store.recover()

    entry_id = args.entry_id
    # Accept short IDs (prefix match)
    if len(entry_id) < 36:
        entry_id = _resolve_short_id(store, entry_id)
        if entry_id is None:
            msg = f"No entry found matching: {args.entry_id}"
            if _json_out({"error": msg}, args):
                return 1
            print(msg, file=sys.stderr)
            return 1

    body = getattr(args, "text", None)
    tags = args.tags.split(",") if getattr(args, "tags", None) else None

    try:
        meta = store.edit(
            entry_id=entry_id,
            body=body,
            agent=getattr(args, "agent", None),
            tags=tags,
            title=getattr(args, "title", None),
            status=getattr(args, "status", None),
            priority=getattr(args, "priority", None),
            assignee=getattr(args, "assignee", None),
            due_date=getattr(args, "due_date", None),
            entry_type=getattr(args, "type", None),
        )
    except (ValueError, PermissionError) as e:
        if _json_out({"error": str(e)}, args):
            return 1
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if _json_out({"id": entry_id, "updated": True, "meta": meta}, args):
        return 0

    print(f"Updated: {entry_id}")
    # Show what changed
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
    for tier in ("hot", "warm", "cold"):
        tier_dir = store.root / tier
        if not tier_dir.exists():
            continue
        for p in tier_dir.glob("*.md"):
            if p.stem.startswith(short_id):
                return p.stem
    return None


def cmd_query(args):
    """Search memories."""
    check_version_nag()
    root = get_root()
    store = Store(root)
    store.recover()

    agent = _resolve_agent(args)

    engine = SearchEngine(store)
    results = engine.search(
        args.query,
        top_k=args.limit,
        include_cold=args.all,
        project=getattr(args, "project", None),
        agent=agent,
        entry_type=getattr(args, "type", None),
        status=getattr(args, "status", None),
        priority=getattr(args, "priority", None),
        assignee=getattr(args, "assignee", None),
        instance=getattr(args, "instance", None),
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
        print_header()
        print("\nNo results found.")
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

    search_tier = "hybrid" if engine.has_embeddings else "BM25"
    print(f"\n{len(results)} result(s) found. (Search tier: {search_tier})")

    # Memo nudge (ADR-011)
    _memo_nudge(args)

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

    print(f"  Chunking: {args.chunk_size} words, {args.chunk_overlap} overlap -> {result.total_chunks} chunks")
    print(f"\nDone in {result.duration_seconds}s")
    print(f"  {result.stored_chunks} chunks stored")
    if result.skipped_chunks:
        print(f"  {result.skipped_chunks} chunks skipped (too short)")
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
    check_version_nag()
    root = get_root()
    store = Store(root)
    store.recover()

    tier = args.tier or "hot"
    entries = store.list_entries(tier, agent=getattr(args, "agent", None))

    # Apply filters (#12, #40)
    project_filter = getattr(args, "project", None)
    tag_filter = getattr(args, "tag", None)
    scope_filter = getattr(args, "scope", None)
    agent_filter = getattr(args, "agent", None)
    type_filter = getattr(args, "type", None)
    status_filter = getattr(args, "status", None)
    priority_filter = getattr(args, "priority", None)
    assignee_filter = getattr(args, "assignee", None)
    instance_filter = getattr(args, "instance", None)

    if project_filter:
        entries = [(meta, body) for meta, body in entries if meta.get("project") == project_filter]
    if tag_filter:
        entries = [(meta, body) for meta, body in entries if tag_filter in (meta.get("tags") or [])]
    if scope_filter:
        entries = [(meta, body) for meta, body in entries if meta.get("scope") == scope_filter]
    if agent_filter:
        entries = [(meta, body) for meta, body in entries if meta.get("agent") == agent_filter]
    if type_filter:
        entries = [(meta, body) for meta, body in entries if meta.get("type", "memory") == type_filter]
    if status_filter:
        entries = [(meta, body) for meta, body in entries if meta.get("status") == status_filter]
    if priority_filter:
        entries = [(meta, body) for meta, body in entries if meta.get("priority") == priority_filter]
    if assignee_filter:
        entries = [(meta, body) for meta, body in entries if meta.get("assignee") == assignee_filter]
    if instance_filter:
        entries = [(meta, body) for meta, body in entries if meta.get("instance") == instance_filter]

    if _json_out(
        {
            "tier": tier,
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
        print_header()
        print(f"\nNo entries in {tier}.")
        return 0

    print_header()
    print(section(f"Entries ({tier})"))

    rows = []
    for meta, body in entries:
        title = meta.get("title", "(untitled)")
        entry_id = meta.get("id", "?")[:8]
        scope = meta.get("scope", "team")
        age = relative_time(meta.get("created", ""))
        rows.append((entry_id, scope, title, age))

    print(
        table_multi(
            headers=("ID", "Scope", "Title", "Age"),
            rows=rows,
            min_widths=(8, 6, 20, 8),
        )
    )

    print(f"\n{len(entries)} entries in {tier}.")
    return 0


def cmd_status(args):
    """Show system status."""
    check_version_nag()
    root = get_root()
    store = Store(root)
    recovered = store.recover()

    info = store.status()

    if _json_out(info, args):
        return 0

    print_header()

    # Calculate disk size
    disk_bytes = 0
    for tier in ("hot", "warm", "cold"):
        tier_dir = root / tier
        if tier_dir.exists():
            for f in tier_dir.iterdir():
                if f.is_file():
                    disk_bytes += f.stat().st_size

    # Count projects
    projects_file = root / "projects.json"
    project_count = 0
    if projects_file.exists():
        try:
            pdata = json.loads(projects_file.read_text())
            project_count = len(pdata) if isinstance(pdata, dict) else 0
        except Exception:
            pass

    # Last write / Last GC timestamps
    last_write = _find_latest_mtime(root, ("hot", "warm"))
    last_gc = _find_gc_time(root)

    entries_str = f"{info['entries']['hot']} hot"
    if info["entries"]["warm"]:
        entries_str += f" / {info['entries']['warm']} warm"
    if info["entries"]["cold"]:
        entries_str += f" / {info['entries']['cold']} cold"

    # Entry class breakdown (ADR-012)
    type_counts = {"memory": 0, "process": 0, "task": 0}
    task_status_counts = {}
    for tier_name in ("hot", "warm", "cold"):
        tier_dir = root / tier_name
        if not tier_dir.exists():
            continue
        for p in tier_dir.glob("*.md"):
            try:
                from palaia.entry import parse_entry as _pe

                text = p.read_text(encoding="utf-8")
                meta, _ = _pe(text)
                et = meta.get("type", "memory")
                type_counts[et] = type_counts.get(et, 0) + 1
                if et == "task":
                    st = meta.get("status", "open")
                    task_status_counts[st] = task_status_counts.get(st, 0) + 1
            except Exception:
                continue

    class_parts = []
    for et in ("memory", "process", "task"):
        if type_counts.get(et, 0) > 0:
            class_parts.append(f"{type_counts[et]} {et}")
    class_str = " / ".join(class_parts) if class_parts else "none"

    store_rows = [
        ("Root", str(info["palaia_root"])),
        ("Store version", f"v{__version__}"),
        ("Entries", entries_str),
        ("Classes", class_str),
        ("Projects", str(project_count)),
        ("Disk size", format_size(disk_bytes)),
        ("Last write", relative_time(last_write) if last_write else "never"),
        ("Last GC", relative_time(last_gc) if last_gc else "never"),
    ]

    if task_status_counts:
        task_parts = [f"{v} {k}" for k, v in sorted(task_status_counts.items())]
        store_rows.append(("Tasks", " / ".join(task_parts)))

    if info["wal_pending"]:
        store_rows.append(("WAL pending", str(info["wal_pending"])))
    if recovered:
        store_rows.append(("WAL recovered", f"{recovered} entries"))

    print(section("Store"))
    print(table_kv(store_rows))

    # Embedding chain status
    from palaia.embeddings import build_embedding_chain

    chain = build_embedding_chain(store.config)
    statuses = chain.provider_status()

    embed_rows = []
    labels = ["Primary", "Fallback", "Last resort"]
    for i, s in enumerate(statuses):
        label = labels[i] if i < len(labels) else f"Provider {i + 1}"
        model_str = f" ({s['model']})" if s.get("model") else ""
        avail = "ok" if s["available"] else "n/a"
        embed_rows.append((label, f"{s['name']}{model_str} [{avail}]"))

    # Index status
    try:
        from palaia.index import EmbeddingCache

        cache = EmbeddingCache(root)
        idx_count = len(cache._load()) if hasattr(cache, "_load") else "?"
    except Exception:
        idx_count = "?"
    embed_rows.append(("Index", f"{idx_count}/{info['total']} entries indexed"))

    print(section("Embeddings"))
    print(table_kv(embed_rows))

    # BM25-only warning
    has_embed = any(s["available"] and s["name"] != "bm25" for s in statuses)
    bm25_only = all(s["name"] == "bm25" for s in statuses) or not has_embed
    if bm25_only:
        print("\nNote: Semantic search is not enabled. Results are keyword-based only.")
        print("  Run 'palaia detect' to see available providers.")

    return 0


def _find_latest_mtime(root: Path, tiers: tuple[str, ...] = ("hot",)) -> str | None:
    """Find the latest file mtime across tiers, return as ISO string."""
    from datetime import datetime, timezone

    latest = 0.0
    for tier in tiers:
        tier_dir = root / tier
        if not tier_dir.exists():
            continue
        for f in tier_dir.iterdir():
            if f.is_file():
                mt = f.stat().st_mtime
                if mt > latest:
                    latest = mt
    if latest == 0.0:
        return None
    return datetime.fromtimestamp(latest, tz=timezone.utc).isoformat()


def _find_gc_time(root: Path) -> str | None:
    """Try to find the last GC run timestamp from config or file markers."""

    config_path = root / "config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            gc_ts = config.get("last_gc")
            if gc_ts:
                return gc_ts
        except Exception:
            pass
    return None


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

    print_header()
    print(section("Environment"))
    print(
        table_kv(
            [
                ("System", sys_info),
                ("Python", py_ver),
            ]
        )
    )

    # Build provider rows
    available = []
    provider_rows = []
    for p in providers:
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

    # Recommended chain
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

    # Show current config
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

    chain_str = " -> ".join(chain)
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

    print_header()
    print(section("Warmup"))
    warmup_rows = []
    for r in results:
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


def _cmd_migrate_suggest(store, root, args):
    """Suggest entry type assignments for existing entries without a type field."""
    from palaia.entry import parse_entry

    suggestions = []
    for tier in ("hot", "warm", "cold"):
        tier_dir = root / tier
        if not tier_dir.exists():
            continue
        for p in tier_dir.glob("*.md"):
            try:
                text = p.read_text(encoding="utf-8")
                meta, body = parse_entry(text)
                if "type" in meta:
                    continue  # Already has a type
                entry_id = meta.get("id", p.stem)
                title = meta.get("title", "(untitled)")
                # Simple heuristic for type suggestion
                suggested_type = _suggest_type(title, body, meta)
                suggestions.append(
                    {
                        "id": entry_id,
                        "title": title,
                        "tier": tier,
                        "suggested_type": suggested_type,
                    }
                )
            except Exception:
                continue

    if _json_out({"suggestions": suggestions, "total": len(suggestions)}, args):
        return 0

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


def _suggest_type(title: str, body: str, meta: dict) -> str:
    """Heuristic to suggest entry type based on content."""
    combined = f"{title} {body}".lower()
    # Task indicators
    task_keywords = ["todo", "task", "bug", "fix", "issue", "ticket", "deadline", "assigned", "blocker"]
    if any(kw in combined for kw in task_keywords):
        return "task"
    # Process indicators
    process_keywords = ["checklist", "sop", "procedure", "workflow", "step 1", "step 2", "how to", "guide", "runbook"]
    if any(kw in combined for kw in process_keywords):
        return "process"
    return "memory"


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
                print(f"  [skip] {agent_name}: .palaia already exists")
            continue

        if dry_run:
            if not getattr(args, "json", False):
                print(f"  [plan] {agent_name}: would create .palaia -> {store_path}")
            symlinks_created += 1
        else:
            try:
                symlink_path.symlink_to(store_path)
                symlinks_created += 1
                if not getattr(args, "json", False):
                    print(f"  [ok] {agent_name}: .palaia -> {store_path}")
            except OSError as e:
                if not getattr(args, "json", False):
                    print(f"  [error] {agent_name}: {e}")

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
                owner=getattr(args, "owner", None),
            )
        except ValueError as e:
            if _json_out({"error": str(e)}, args):
                return 1
            print(f"Error: {e}", file=sys.stderr)
            return 1
        if _json_out(project.to_dict(), args):
            return 0
        print(f"Created project: {project.name}")
        if project.owner:
            print(f"  Owner: {project.owner}")
        if project.description:
            print(f"  Description: {project.description}")
        print(f"  Default scope: {project.default_scope}")
        return 0

    elif action == "list":
        projects = pm.list()
        owner_filter = getattr(args, "owner", None)
        if owner_filter:
            projects = [p for p in projects if p.owner == owner_filter]
        if _json_out({"projects": [p.to_dict() for p in projects]}, args):
            return 0
        if not projects:
            print_header()
            print("\nNo projects.")
            return 0
        print_header()
        print(section("Projects"))
        rows = []
        for p in projects:
            owner_str = p.owner or ""
            desc = p.description or ""
            rows.append((p.name, p.default_scope, owner_str, desc))
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
        project = pm.get(args.name)
        if not project:
            if _json_out({"error": f"Project '{args.name}' not found."}, args):
                return 1
            print(f"Project '{args.name}' not found.", file=sys.stderr)
            return 1
        entries = pm.get_project_entries(args.name, store)
        contributors = pm.get_contributors(args.name, store)
        tier_counts = {}
        for _meta, _body, tier in entries:
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
        if _json_out(
            {
                "project": project.to_dict(),
                "contributors": contributors,
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
                "entry_count": len(entries),
                "tier_counts": tier_counts,
            },
            args,
        ):
            return 0
        print_header()
        print(section(f"Project: {project.name}"))
        info_rows = [
            ("Name", project.name),
            ("Description", project.description or "(none)"),
            ("Owner", project.owner or "(none)"),
            ("Default scope", project.default_scope),
            ("Contributors", ", ".join(contributors) if contributors else "(none)"),
            ("Created", project.created_at),
            ("Entries", str(len(entries))),
        ]
        print(table_kv(info_rows))

        if entries:
            print(section("Entries"))
            entry_rows = []
            for meta, body, tier in entries:
                title = meta.get("title", "(untitled)")
                entry_id = meta.get("id", "?")[:8]
                scope = meta.get("scope", "team")
                entry_rows.append((entry_id, tier, scope, title))
            print(
                table_multi(
                    headers=("ID", "Tier", "Scope", "Title"),
                    rows=entry_rows,
                    min_widths=(8, 4, 6, 20),
                )
            )
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

    elif action == "set-owner":
        try:
            if getattr(args, "clear", False):
                project = pm.clear_owner(args.name)
                if _json_out({"project": args.name, "owner": None}, args):
                    return 0
                print(f"Cleared owner for project '{args.name}'.")
            else:
                owner_value = getattr(args, "owner_value", None)
                if not owner_value:
                    print("Error: owner name required (or use --clear).", file=sys.stderr)
                    return 1
                project = pm.set_owner(args.name, owner_value)
                if _json_out({"project": args.name, "owner": project.owner}, args):
                    return 0
                print(f"Project '{args.name}' owner → {project.owner}")
        except ValueError as e:
            if _json_out({"error": str(e)}, args):
                return 1
            print(f"Error: {e}", file=sys.stderr)
            return 1
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


def cmd_instance(args):
    """Manage session instance identity."""
    root = get_root()
    action = args.instance_action

    if action == "set":
        set_instance(root, args.name)
        if _json_out({"instance": args.name, "status": "set"}, args):
            return 0
        print(f"Instance set: {args.name}")
        return 0

    elif action == "get":
        instance = get_instance(root)
        if _json_out({"instance": instance}, args):
            return 0
        if instance:
            print(f"Current instance: {instance}")
        else:
            print("No instance set.")
        return 0

    elif action == "clear":
        clear_instance(root)
        if _json_out({"instance": None, "status": "cleared"}, args):
            return 0
        print("Instance cleared.")
        return 0

    else:
        # No subcommand: show current instance
        instance = get_instance(root)
        if _json_out({"instance": instance}, args):
            return 0
        if instance:
            print(f"Current instance: {instance}")
        else:
            print("No instance set. Use: palaia instance set NAME")
        return 0


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

    result = f"Locked by {agent} since {time_str} ({age_str})"
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
        print(f"Locked project '{project}' for agent '{agent}'")
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
        print(f"Lock renewed for project '{project}' — expires {lock_data['expires']} ({ttl_min}min)")
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
            print(f"Lock for project '{project}' force-broken (was held by {old.get('agent', '?')})")
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
        print(f"Unlocked project '{project}'")
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

    # Resolve agent from config for all memo operations
    agent = _resolve_agent(args)

    if action == "send":
        meta = mm.send(
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
        meta = mm.broadcast(
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
        memos = mm.inbox(agent=agent, include_read=args.all)
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
        if args.all:
            count = mm.ack_all(agent=agent)
            if _json_out({"acked": count}, args):
                return 0
            print(f"Acknowledged {count} memo(s).")
            return 0
        if not args.memo_id:
            print("Error: memo ID required (or use --all)", file=sys.stderr)
            return 1
        ok = mm.ack(args.memo_id)
        if _json_out({"acked": ok, "id": args.memo_id}, args):
            return 0
        if ok:
            print(f"Memo {args.memo_id[:8]} acknowledged.")
        else:
            print(f"Memo {args.memo_id} not found.", file=sys.stderr)
            return 1
        return 0

    if action == "gc":
        stats = mm.gc()
        if _json_out(stats, args):
            return 0
        print(
            f"GC: removed {stats['removed_expired']} expired, "
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
    p_init.add_argument("--agent", default=None, help="Agent name (required for first init)")
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
    p_list.add_argument("--type", default=None, choices=["memory", "process", "task"], help="Filter by entry class")
    p_list.add_argument(
        "--status", default=None, choices=["open", "in-progress", "done", "wontfix"], help="Filter by task status"
    )
    p_list.add_argument(
        "--priority", default=None, choices=["critical", "high", "medium", "low"], help="Filter by priority"
    )
    p_list.add_argument("--assignee", default=None, help="Filter by assignee")
    p_list.add_argument("--instance", default=None, help="Filter by session identity")
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

    args = parser.parse_args()
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
        "memo": cmd_memo,
        "lock": cmd_lock,
        "unlock": cmd_unlock,
        "instance": cmd_instance,
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
