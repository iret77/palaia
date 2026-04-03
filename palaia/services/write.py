"""Write service — write and edit orchestration."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

from palaia.config import load_config
from palaia.store import Store


def write_entry(
    root: Path,
    *,
    body: str,
    scope: str | None = None,
    agent: str | None = None,
    tags: list[str] | None = None,
    title: str | None = None,
    project: str | None = None,
    entry_type: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    assignee: str | None = None,
    due_date: str | None = None,
    instance: str | None = None,
) -> dict:
    """Write a memory entry.

    Returns dict with id, tier, scope, deduplicated, and optional nudge/significance.
    """
    store = Store(root)

    # Recovery check
    recovered = store.recover()

    # Private scope requires an agent identity — reject early
    eff_scope = scope or "team"
    if eff_scope == "private" and (not agent or agent == "default"):
        config = load_config(root)
        if config.get("multi_agent") and not os.environ.get("PALAIA_AGENT"):
            return {
                "error": (
                    "Cannot write with scope 'private' without an agent identity. "
                    "Private entries are only accessible to their owning agent. "
                    "Set PALAIA_AGENT env var or run 'palaia init --agent NAME'."
                ),
            }

    # Similarity check for processes: warn before creating near-duplicates
    process_similarity_nudge: str | None = None
    if entry_type == "process":
        try:
            from palaia.search import SearchEngine

            engine = SearchEngine(store)
            results = engine.search(body, top_k=3, entry_type="process")
            for r in results:
                if r.get("score", 0) > 0.8:
                    similar_title = r.get("title", "(untitled)")
                    similar_id = r.get("id", "???")[:8]
                    process_similarity_nudge = (
                        f"[palaia] Similar process found: '{similar_title}' "
                        f"(id: {similar_id}, score: {r['score']:.2f}). "
                        f"Consider updating it with `palaia edit {similar_id}` instead."
                    )
                    break
        except Exception:
            pass  # Never block writes with nudge errors

    entry_id = store.write(
        body=body,
        scope=scope,
        agent=agent,
        tags=tags,
        title=title,
        project=project,
        entry_type=entry_type,
        status=status,
        priority=priority,
        assignee=assignee,
        due_date=due_date,
        instance=instance,
    )

    # Check dedup: Store.write() returns existing ID on hash collision
    # Compare with a fresh read to detect if this was a dedup or new write
    entry = store.read(entry_id)
    tier = "hot"
    actual_scope = scope or "team"
    deduplicated = False
    if entry:
        meta, _ = entry
        actual_scope = meta.get("scope", actual_scope)
        for t in ("hot", "warm", "cold"):
            if (root / t / f"{entry_id}.md").exists():
                tier = t
                break
        # If entry existed before write (non-hot tier or older timestamp),
        # it was deduplicated. Hot + just-created = new entry.
        if tier != "hot":
            deduplicated = True

    # --- Adaptive Nudging (Issue #68) ---
    nudge_messages: list[str] = []
    try:
        from palaia.nudge import NudgeTracker
        from palaia.project import ProjectManager

        tracker = NudgeTracker(root)
        agent_for_nudge = agent or "default"

        if entry_type:
            tracker.record_success("write_without_type", agent_for_nudge)
        else:
            tracker.record_failure("write_without_type", agent_for_nudge)
            if tracker.should_nudge("write_without_type", agent_for_nudge):
                msg = tracker.get_nudge_message("write_without_type")
                if msg:
                    nudge_messages.append(msg)
                    tracker.record_nudge("write_without_type", agent_for_nudge)

        if tags:
            tracker.record_success("write_without_tags", agent_for_nudge)
        else:
            tracker.record_failure("write_without_tags", agent_for_nudge)
            if tracker.should_nudge("write_without_tags", agent_for_nudge):
                msg = tracker.get_nudge_message("write_without_tags")
                if msg:
                    nudge_messages.append(msg)
                    tracker.record_nudge("write_without_tags", agent_for_nudge)

        # write_without_project: only nudge in multi-project setups
        try:
            pm = ProjectManager(root)
            projects = pm.list()
            if len(projects) > 1:
                if project:
                    tracker.record_success("write_without_project", agent_for_nudge)
                else:
                    tracker.record_failure("write_without_project", agent_for_nudge)
                    if tracker.should_nudge("write_without_project", agent_for_nudge):
                        msg = tracker.get_nudge_message("write_without_project")
                        if msg:
                            nudge_messages.append(msg)
                            tracker.record_nudge("write_without_project", agent_for_nudge)
        except Exception:
            pass

        # scope_hint: nudge in multi-agent setups when scope defaults
        if scope:
            # User explicitly used --scope → graduate
            tracker.record_success("scope_hint", agent_for_nudge)
        else:
            try:
                store_entries = store.all_entries(include_cold=False)
                agents_seen = set()
                for m, _, _ in store_entries:
                    a = m.get("agent")
                    if a:
                        agents_seen.add(a)
                    if len(agents_seen) > 1:
                        break
                if len(agents_seen) > 1:
                    tracker.record_failure("scope_hint", agent_for_nudge)
                    if tracker.should_nudge("scope_hint", agent_for_nudge):
                        msg = tracker.get_nudge_message("scope_hint")
                        if msg:
                            nudge_messages.append(msg)
                            tracker.record_nudge("scope_hint", agent_for_nudge)
            except Exception:
                pass

        # isolation_scope_mismatch: detect writes outside scopeVisibility (#148)
        try:
            from palaia.priorities import load_priorities, resolve_priorities

            prio = load_priorities(root)
            resolved_prio = resolve_priorities(prio, agent=agent_for_nudge)
            vis = resolved_prio.scope_visibility
            if vis:
                written_scope = scope or "team"
                # Check if written scope is visible to this agent
                scope_visible = any(written_scope == v for v in vis)
                if scope_visible:
                    tracker.record_success("isolation_scope_mismatch", agent_for_nudge)
                else:
                    tracker.record_failure("isolation_scope_mismatch", agent_for_nudge)
                    if tracker.should_nudge("isolation_scope_mismatch", agent_for_nudge):
                        msg = tracker.get_nudge_message("isolation_scope_mismatch")
                        if msg:
                            msg = msg.format(
                                visibility=",".join(vis),
                                scope=written_scope,
                            )
                            nudge_messages.append(msg)
                            tracker.record_nudge("isolation_scope_mismatch", agent_for_nudge)
        except Exception:
            pass

        # migration_success: one-shot nudge after flat-file → SQLite migration
        try:
            flag_file = root / ".migration_success"
            if flag_file.exists():
                if tracker.should_nudge("migration_success", agent_for_nudge):
                    msg = tracker.get_nudge_message("migration_success")
                    if msg:
                        nudge_messages.append(msg)
                        tracker.record_nudge("migration_success", agent_for_nudge)
                # Remove flag after first check (regardless of nudge shown)
                flag_file.unlink(missing_ok=True)
        except Exception:
            pass
    except Exception:
        pass  # Never block normal operation with nudge errors

    # --- Significance auto-detection (Issue #70) ---
    significance_detected: list[str] = []
    if not tags:
        try:
            from palaia.significance import detect_significance

            significance_detected = detect_significance(body)
        except Exception:
            pass

    result: dict = {
        "id": entry_id,
        "tier": tier,
        "scope": actual_scope,
        "deduplicated": deduplicated,
        "recovered": recovered,
    }
    if process_similarity_nudge:
        nudge_messages.append(process_similarity_nudge)
    if nudge_messages:
        result["nudge"] = nudge_messages
    if significance_detected:
        result["significance"] = significance_detected

    return result


def edit_entry(
    root: Path,
    entry_id: str,
    *,
    body: str | None = None,
    agent: str | None = None,
    tags: list[str] | None = None,
    title: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    assignee: str | None = None,
    due_date: str | None = None,
    entry_type: str | None = None,
) -> dict:
    """Edit an existing memory entry.

    Returns dict with id, updated, meta or error.
    """
    store = Store(root)
    store.recover()

    # Accept short IDs
    from palaia.services.query import _resolve_short_id

    if len(entry_id) < 36:
        resolved = _resolve_short_id(store, entry_id)
        if resolved is None:
            return {"error": f"No entry found matching: {entry_id}"}
        entry_id = resolved

    try:
        meta = store.edit(
            entry_id=entry_id,
            body=body,
            agent=agent,
            tags=tags,
            title=title,
            status=status,
            priority=priority,
            assignee=assignee,
            due_date=due_date,
            entry_type=entry_type,
        )
    except (ValueError, PermissionError) as e:
        return {"error": str(e)}

    # Task-as-Post-It: completed/cancelled tasks are ephemeral — delete on close
    effective_status = status or meta.get("status")
    effective_type = entry_type or meta.get("type")
    if effective_type == "task" and effective_status in ("done", "wontfix"):
        try:
            store.delete(entry_id)
            return {"id": entry_id, "deleted": True, "reason": "task completed"}
        except Exception as exc:
            logger.warning("Task deletion failed for %s: %s", entry_id, exc)

    return {"id": entry_id, "updated": True, "meta": meta}
