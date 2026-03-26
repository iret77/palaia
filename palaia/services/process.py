"""Process service — process execution run business logic."""

from __future__ import annotations

from pathlib import Path

from palaia.store import Store


def process_run(
    root: Path,
    *,
    entry_id: str,
    agent: str | None = None,
    step: int | None = None,
    done: bool = False,
) -> dict:
    """Run or inspect a process entry.

    Returns dict with process run data, or error dict.
    """
    from palaia.process_runner import ProcessRunManager

    store = Store(root)
    store.recover()
    prm = ProcessRunManager(root)

    # Resolve short ID
    if len(entry_id) < 36:
        from palaia.services.query import _resolve_short_id

        resolved = _resolve_short_id(store, entry_id)
        if resolved is None:
            return {"error": f"No entry found matching: {entry_id}"}
        entry_id = resolved

    # Read the entry
    entry = store.read(entry_id, agent=agent)
    if entry is None:
        return {"error": f"Entry not found: {entry_id}"}

    meta, body = entry
    if meta.get("type") != "process":
        return {
            "error": f"Entry {entry_id[:8]} is not a process (type: {meta.get('type', 'memory')})"
        }

    run = prm.start(entry_id, body)

    # Handle --step N --done
    if step is not None and done:
        if not run.mark_done(step):
            return {"error": f"Invalid step index: {step}"}
        prm.save(run)

    return {
        "run": run.to_dict(),
        "meta": meta,
        "entry_id": entry_id,
        "steps": run.steps,
        "completed": run.completed,
        "progress_summary": run.progress_summary(),
    }


def process_list(root: Path) -> dict:
    """List active process runs. Returns dict with 'runs' list."""
    from palaia.process_runner import ProcessRunManager

    store = Store(root)
    store.recover()
    prm = ProcessRunManager(root)
    runs = prm.list_runs()

    run_data = []
    for r in runs:
        entry = store.read(r.entry_id)
        title = "(unknown)"
        if entry:
            meta, _ = entry
            title = meta.get("title", "(untitled)")
        run_data.append({
            "entry_id": r.entry_id,
            "title": title,
            "progress_summary": r.progress_summary(),
            "completed": r.completed,
            "started_at": r.started_at,
            "run": r.to_dict(),
        })

    return {"runs": run_data}
