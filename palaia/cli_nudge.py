"""CLI nudge helpers — extracted from cli.py for maintainability."""

from __future__ import annotations

import json
import sys


def memo_nudge(args, *, resolve_agent_fn, get_root_fn, get_aliases_fn) -> None:
    """Check for unread memos and print a nudge if any exist.

    Frequency-limited to max once per hour. Suppressed in --json mode.
    """
    if getattr(args, "json", False):
        return
    try:
        import time

        root = get_root_fn()
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
        agent = resolve_agent_fn(args)
        if not agent:
            return

        from palaia.memo import MemoManager

        mm = MemoManager(root)
        try:
            memo_aliases = get_aliases_fn(root)
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


def process_nudge(context_text: str, context_tags: list[str] | None, args,
                  *, get_root_fn) -> None:
    """Check for process entries relevant to the current operation and nudge.

    Uses hybrid matching: embedding similarity OR exact tag overlap.
    Frequency-limited to max once per process per hour. Suppressed in --json mode.
    """
    if getattr(args, "json", False):
        return
    try:
        import time

        from palaia.store import Store

        root = get_root_fn()

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
