"""Ingest service — document ingestion business logic."""

from __future__ import annotations

from pathlib import Path

from palaia.ingest import DocumentIngestor
from palaia.project import ProjectManager
from palaia.store import Store


def ingest_document(
    root: Path,
    *,
    source: str,
    project: str | None = None,
    scope: str | None = None,
    tags: list[str] | None = None,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    dry_run: bool = False,
) -> dict:
    """Ingest a document for RAG. Returns result dict or error dict.

    The returned dict always includes 'source', 'total_chunks', 'stored_chunks',
    'skipped_chunks', 'project', 'entry_ids', 'duration_seconds', 'dry_run'.
    On error, returns dict with 'error' key.
    """
    store = Store(root)
    store.recover()
    ingestor = DocumentIngestor(store)

    # Auto-create project if specified and not dry run
    if project and not dry_run:
        pm = ProjectManager(root)
        pm.ensure(project)

    try:
        result = ingestor.ingest(
            source=source,
            project=project,
            scope=scope or "private",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            tags=tags,
            dry_run=dry_run,
        )
    except (ImportError, Exception) as e:
        return {"error": str(e)}

    return {
        "source": result.source,
        "total_chunks": result.total_chunks,
        "stored_chunks": result.stored_chunks,
        "skipped_chunks": result.skipped_chunks,
        "project": result.project,
        "entry_ids": result.entry_ids,
        "duration_seconds": result.duration_seconds,
        "dry_run": dry_run,
        "scope": scope or "private",
    }
