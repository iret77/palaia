"""Search API routes with timeout guard for embedding startup."""

from __future__ import annotations

import concurrent.futures
import logging

from fastapi import APIRouter, Query, Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search"])

# Timeout for search (seconds). If embeddings aren't ready, fall back to BM25.
SEARCH_TIMEOUT_SECONDS = 5.0


@router.get("/search")
def search(
    request: Request,
    q: str = Query(..., description="Search query"),
    limit: int = Query(10, ge=1, le=100),
    type: str | None = Query(None, description="Filter by type"),
    project: str | None = Query(None, description="Filter by project"),
    status: str | None = Query(None, description="Filter by status"),
    priority: str | None = Query(None, description="Filter by priority"),
    include_cold: bool = Query(False, description="Include cold tier"),
    timeout: float = Query(SEARCH_TIMEOUT_SECONDS, ge=0.5, le=30, description="Search timeout in seconds"),
) -> dict:
    """Hybrid search (BM25 + semantic embeddings) with timeout guard.

    If embedding search takes longer than `timeout` seconds (e.g. embed server
    cold start), returns BM25-only results instead of hanging.
    """
    from palaia.services.query import search_entries

    root = request.app.state.palaia_root

    def _run_search():
        return search_entries(
            root,
            q,
            limit=limit,
            entry_type=type,
            project=project,
            status=status,
            priority=priority,
            include_cold=include_cold,
        )

    timed_out = False
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run_search)
            result = future.result(timeout=timeout)
    except (concurrent.futures.TimeoutError, TimeoutError):
        # Embedding search hung (probably cold-starting embed server).
        # Fall back to BM25-only search.
        logger.warning("Search timed out after %.1fs, falling back to BM25-only", timeout)
        timed_out = True
        try:
            result = _bm25_fallback(root, q, limit=limit, entry_type=type, project=project,
                                     status=status, priority=priority, include_cold=include_cold)
        except Exception as fallback_err:
            logger.error("BM25 fallback also failed: %s", fallback_err)
            result = {"results": [], "has_embeddings": False, "bm25_only": True}

    return {
        "query": q,
        "results": result["results"],
        "has_embeddings": result.get("has_embeddings", False),
        "bm25_only": result.get("bm25_only", True),
        "timed_out": timed_out,
        "count": len(result["results"]),
    }


def _bm25_fallback(
    root,
    query: str,
    *,
    limit: int = 10,
    entry_type: str | None = None,
    project: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    include_cold: bool = False,
) -> dict:
    """BM25-only search fallback when embeddings time out."""
    from palaia.store import Store
    from palaia.search import SearchEngine

    store = Store(root)
    store.recover()
    engine = SearchEngine(store)

    # Force BM25-only by temporarily disabling embeddings
    original = engine.has_embeddings
    engine.has_embeddings = False
    try:
        results = engine.search(
            query,
            top_k=limit,
            include_cold=include_cold,
            project=project,
            entry_type=entry_type,
            status=status,
            priority=priority,
        )
    finally:
        engine.has_embeddings = original

    return {
        "results": results,
        "has_embeddings": False,
        "bm25_only": True,
    }
