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
    get_aliases,
    get_instance,
    get_root,
    is_initialized,
    load_config,
    remove_alias,
    resolve_agent_with_aliases,
    save_config,
    set_alias,
    set_instance,
)
from palaia.doctor import apply_fixes, format_doctor_report, run_doctor  # noqa: E402
from palaia.ingest import DocumentIngestor, format_rag_output  # noqa: E402
from palaia.migrate import format_result, migrate  # noqa: E402
from palaia.packages import PackageManager  # noqa: E402
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
        "process",
        "package",
        "lock",
        "unlock",
        "setup",
        "warmup",
        "migrate",
        "embed-server",
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


def _resolve_agent(args) -> str | None:
    """Resolve agent name: explicit --agent flag > config > env var > 'default'.

    For gated commands, config agent is always available (gatekeeper ensures init).
    Falls back to 'default' when no agent identity can be determined.
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
    detected = _detect_current_agent()
    return detected or "default"


def _resolve_agent_names(agent: str | None) -> set[str] | None:
    """Resolve an agent name to all matching names via aliases.

    Returns None if agent is None (no filtering), otherwise a set of
    agent names that should all be considered matches.
    """
    if agent is None:
        return None
    try:
        root = get_root()
        aliases = get_aliases(root)
        if aliases:
            return resolve_agent_with_aliases(agent, aliases)
    except FileNotFoundError:
        pass
    return {agent}


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
        try:
            memo_aliases = get_aliases(root)
        except Exception:
            memo_aliases = None
        unread = mm.inbox(agent=agent, include_read=False, aliases=memo_aliases or None)
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


def _process_nudge(context_text: str, context_tags: list[str] | None, args) -> None:
    """Check for process entries relevant to the current operation and nudge.

    Uses hybrid matching: embedding similarity OR exact tag overlap.
    Frequency-limited to max once per process per hour. Suppressed in --json mode.

    Args:
        context_text: The text from the current write/query operation.
        context_tags: Tags from the current operation (if any).
        args: Parsed CLI args (checked for --json flag).
    """
    if getattr(args, "json", False):
        return
    try:
        import time

        root = get_root()

        # Load frequency-limiting state
        nudge_state_file = root / "process-nudge-state.json"
        nudge_state: dict = {}
        if nudge_state_file.exists():
            try:
                nudge_state = json.loads(nudge_state_file.read_text())
            except (json.JSONDecodeError, OSError):
                nudge_state = {}

        # Get all process entries
        store = Store(root)
        all_entries = store.all_entries(include_cold=False)
        processes = [(meta, body, tier) for meta, body, tier in all_entries if meta.get("type") == "process"]

        if not processes:
            return

        now = time.time()
        best_match: tuple[float, dict] | None = None  # (score, meta)

        # Tag matching
        context_tag_set = set(context_tags) if context_tags else set()

        # Try embedding similarity
        has_embeddings = False
        context_vec: list[float] | None = None
        try:
            from palaia.embeddings import BM25Provider, auto_detect_provider, cosine_similarity

            provider = auto_detect_provider(store.config)
            if not isinstance(provider, BM25Provider):
                has_embeddings = True
                context_vec = provider.embed_query(context_text)
        except Exception:
            pass

        for meta, body, _tier in processes:
            proc_id = meta.get("id", "")
            short_id = proc_id[:8]

            # Frequency limit: skip if nudged within the last hour
            last_nudged = nudge_state.get(short_id, 0)
            if now - last_nudged < 3600:
                continue

            score = 0.0

            # Embedding similarity
            if has_embeddings and context_vec is not None:
                try:
                    proc_title = meta.get("title", "")
                    proc_tags = " ".join(meta.get("tags", []))
                    proc_text = f"{proc_title} {proc_tags} {body}"
                    # Check embedding cache first
                    cached = store.embedding_cache.get_cached(proc_id)
                    if cached:
                        sim = cosine_similarity(context_vec, cached)
                    else:
                        proc_vec = provider.embed_query(proc_text)
                        sim = cosine_similarity(context_vec, proc_vec)
                    score = max(score, sim)
                except Exception:
                    pass

            # Tag overlap (fallback or additional signal)
            if context_tag_set:
                proc_tags_set = set(meta.get("tags", []))
                if context_tag_set & proc_tags_set:
                    # Tag match: set a high score to ensure nudge
                    score = max(score, 0.5)

            # Threshold check
            if score >= 0.3:
                if best_match is None or score > best_match[0]:
                    best_match = (score, meta)

        if best_match is None:
            return

        _, best_meta = best_match
        proc_title = best_meta.get("title", "(untitled)")
        proc_short_id = best_meta.get("id", "")[:8]

        print(
            f"\nRelated process: {proc_title} (palaia get {proc_short_id})",
            file=sys.stderr,
        )

        # Update frequency limiter
        nudge_state[proc_short_id] = now
        try:
            nudge_state_file.write_text(json.dumps(nudge_state))
        except OSError:
            pass
    except Exception:
        pass  # Never block normal operation


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


def cmd_query(args):
    """Search memories."""
    from palaia.services.query import search_entries, enrich_rag_results

    check_version_nag()
    root = get_root()
    agent = _resolve_agent(args)

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

    if _json_out(
        {
            "results": results,
            **({"nudge": query_nudge_messages} if query_nudge_messages else {}),
        },
        args,
    ):
        return 0

    if not has_embeddings and bm25_only:
        print("Note: Keyword search only (BM25). For semantic search: pip install sentence-transformers")
        print()

    if not results:
        print_header()
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

    _memo_nudge(args)
    _process_nudge(args.query, [], args)

    return 0


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


def cmd_list(args):
    """List memories in a tier or across all tiers."""
    from palaia.services.query import list_entries

    check_version_nag()
    root = get_root()
    list_all = getattr(args, "all", False)
    scope_agent = _resolve_agent(args)
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
        agent_names=_resolve_agent_names(agent_filter) if agent_filter else None,
    )

    tier_label = svc_result["tier"]
    entries_with_tier = svc_result["entries_with_tier"]

    if _json_out(
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

    if _json_out(info, args):
        return 0

    print_header()

    # Build entries string
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

    # Embedding chain status
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

    # Budget info (Issue #71)
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

    # BM25-only warning
    has_embed = any(s["available"] and s["name"] != "bm25" for s in statuses)
    bm25_only = all(s["name"] == "bm25" for s in statuses) or not has_embed
    if bm25_only:
        print("\nNote: Semantic search is not enabled. Results are keyword-based only.")
        print("  Run 'palaia detect' to see available providers.")

    plugin_status = "active" if info["plugin_detected"] else "not detected"
    print(f"\nOpenClaw Plugin: {plugin_status}")

    return 0


def cmd_detect(args):
    """Detect available embedding providers."""
    from palaia.services.admin import detect_embedding_providers

    result = detect_embedding_providers()

    if _json_out(result, args):
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

    # Build provider rows
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


def cmd_config(args):
    """Get or set configuration values."""
    from palaia.services.admin import (
        config_set_chain,
        config_set_alias_svc,
        config_get_aliases_svc,
        config_remove_alias_svc,
        config_get,
        config_set,
        config_list_all,
    )

    root = get_root()

    if args.action == "set-chain":
        result = config_set_chain(root, args.providers)
        if "error" in result:
            if _json_out(result, args):
                return 1
            print(f"Unknown provider: {result['error']}", file=sys.stderr)
            return 1
        if _json_out(result, args):
            return 0
        print(f"Embedding chain: {' -> '.join(result['embedding_chain'])}")
        return 0

    if args.action == "set-alias":
        result = config_set_alias_svc(root, args.from_name, args.to_name)
        if "error" in result:
            if _json_out(result, args):
                return 1
            print(f"Error: {result['error']}", file=sys.stderr)
            return 1
        if _json_out(result, args):
            return 0
        print(f"Alias set: {args.from_name} -> {args.to_name}")
        return 0

    if args.action == "get-aliases":
        result = config_get_aliases_svc(root)
        if _json_out(result, args):
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
        if _json_out(result, args):
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
            if _json_out(result, args):
                return 1
            print(f"Unknown config key: {args.key}", file=sys.stderr)
            return 1
        if _json_out(result, args):
            return 0
        print(f"{result['key']} = {result['value']}")
        return 0

    if args.action == "set":
        result = config_set(root, args.key, args.value)
        if _json_out(result, args):
            return 0
        print(f"{result['key']} = {result['value']}")
        return 0

    if args.action == "list":
        result = config_list_all(root)
        if _json_out(result, args):
            return 0
        for k, v in sorted(result.items()):
            print(f"{k} = {v}")
        return 0

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
    # Scope enforcement: resolve agent from config (#39)
    agent = _resolve_agent(args)
    result = export_entries(
        remote=args.remote,
        branch=args.branch,
        output_dir=args.output,
        agent=agent,
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
        try:
            inbox_aliases = get_aliases(root)
        except Exception:
            inbox_aliases = None
        memos = mm.inbox(agent=agent, include_read=args.all, aliases=inbox_aliases or None)
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


def cmd_process(args):
    """Manage process execution runs (Issue #72)."""
    root = get_root()
    store = Store(root)
    store.recover()

    action = args.process_action

    if action == "run":
        from palaia.process_runner import ProcessRunManager

        prm = ProcessRunManager(root)
        entry_id = args.entry_id

        # Resolve short ID
        if len(entry_id) < 36:
            entry_id = _resolve_short_id(store, entry_id)
            if entry_id is None:
                msg = f"No entry found matching: {args.entry_id}"
                if _json_out({"error": msg}, args):
                    return 1
                print(msg, file=sys.stderr)
                return 1

        # Read the entry
        agent = _resolve_agent(args)
        entry = store.read(entry_id, agent=agent)
        if entry is None:
            msg = f"Entry not found: {entry_id}"
            if _json_out({"error": msg}, args):
                return 1
            print(msg, file=sys.stderr)
            return 1

        meta, body = entry
        if meta.get("type") != "process":
            msg = f"Entry {entry_id[:8]} is not a process (type: {meta.get('type', 'memory')})"
            if _json_out({"error": msg}, args):
                return 1
            print(msg, file=sys.stderr)
            return 1

        run = prm.start(entry_id, body)

        # Handle --step N --done
        step_idx = getattr(args, "step", None)
        if step_idx is not None:
            if getattr(args, "done", False):
                if not run.mark_done(step_idx):
                    msg = f"Invalid step index: {step_idx}"
                    if _json_out({"error": msg}, args):
                        return 1
                    print(msg, file=sys.stderr)
                    return 1
                prm.save(run)

        if _json_out(run.to_dict(), args):
            return 0

        # Human-readable output
        title = meta.get("title", "(untitled)")
        print(f"Process: {title} ({entry_id[:8]})")
        print(f"Progress: {run.progress_summary()}")
        print()
        for s in run.steps:
            marker = "[x]" if s["done"] else "[ ]"
            print(f"  {s['index']}. {marker} {s['text']}")
        if run.completed:
            print("\nAll steps completed!")
        return 0

    elif action == "list":
        from palaia.process_runner import ProcessRunManager

        prm = ProcessRunManager(root)
        runs = prm.list_runs()

        if _json_out({"runs": [r.to_dict() for r in runs]}, args):
            return 0

        if not runs:
            print("No active process runs.")
            return 0

        rows = []
        for r in runs:
            # Try to get title from store
            entry = store.read(r.entry_id)
            title = "(unknown)"
            if entry:
                meta, _ = entry
                title = meta.get("title", "(untitled)")
            rows.append(
                (
                    r.entry_id[:8],
                    title[:30],
                    r.progress_summary(),
                    "yes" if r.completed else "no",
                    r.started_at[:10] if r.started_at else "?",
                )
            )

        from palaia.ui import table_multi as _tm

        print(
            _tm(
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
    root = get_root()
    store = Store(root)
    store.recover()

    action = args.package_action

    if action == "export":
        pm_pkg = PackageManager(store)
        types_filter = None
        if getattr(args, "types", None):
            types_filter = [t.strip() for t in args.types.split(",")]
        result = pm_pkg.export_package(
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
        pm_pkg = PackageManager(store)
        result = pm_pkg.import_package(
            input_path=args.file,
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
        pm_pkg = PackageManager(store)
        try:
            info = pm_pkg.package_info(args.file)
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
    skill_path = Path(__file__).parent / "SKILL.md"
    if not skill_path.exists():
        fallback_msg = (
            "SKILL.md not found in this installation. "
            "View it online: https://github.com/iret77/palaia/blob/main/SKILL.md"
        )
        if getattr(args, "json", False):
            print(json.dumps({"error": fallback_msg}, ensure_ascii=False))
            return 1
        print(fallback_msg, file=sys.stderr)
        return 1

    content = skill_path.read_text(encoding="utf-8")
    if _json_out({"skill": content}, args):
        return 0
    print(content)
    return 0


def main():
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
    p_init.add_argument(
        "--capture-level",
        default=None,
        dest="capture_level",
        choices=["off", "sparsam", "normal", "aggressiv"],
        help="Auto-capture level for OpenClaw plugin (off|sparsam|normal|aggressiv)",
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

    p_config_set_alias = config_sub.add_parser("set-alias", help="Set an agent alias")
    p_config_set_alias.add_argument("from_name", help="Alias source name (e.g. 'default')")
    p_config_set_alias.add_argument("to_name", help="Alias target name (e.g. 'HAL')")
    p_config_set_alias.add_argument("--json", action="store_true", help="Output as JSON")

    p_config_get_aliases = config_sub.add_parser("get-aliases", help="Show all agent aliases")
    p_config_get_aliases.add_argument("--json", action="store_true", help="Output as JSON")

    p_config_remove_alias = config_sub.add_parser("remove-alias", help="Remove an agent alias")
    p_config_remove_alias.add_argument("from_name", help="Alias source name to remove")
    p_config_remove_alias.add_argument("--json", action="store_true", help="Output as JSON")

    # process (Issue #72)
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

    # package (Issue #73)
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

    # embed-server
    sub.add_parser("embed-server", help="Start long-lived embedding server (stdin/stdout JSON-RPC)")

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
