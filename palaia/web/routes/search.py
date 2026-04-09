"""Search route with BM25 fallback on embedding timeout.

Single-user local UI only. The BM25 fallback mutates engine.has_embeddings
which would race under concurrent load, but uvicorn defaults to one worker
and the UI is bound to 127.0.0.1.
"""

from __future__ import annotations

import concurrent.futures
import logging

from fastapi import APIRouter, Query, Request

logger = logging.getLogger(__name__)
router = APIRouter(tags=["search"])

SEARCH_TIMEOUT_SECONDS = 5.0

# Persistent executor so we can *abandon* slow workers instead of blocking on
# their shutdown. A `with ThreadPoolExecutor(...)` would call
# shutdown(wait=True) on exit, which undoes the whole point of the timeout.
_SEARCH_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="palaia-search")


@router.get("/search")
def search(
    request: Request,
    q: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    type: str | None = Query(None),
    project: str | None = Query(None),
    status: str | None = Query(None),
    priority: str | None = Query(None),
    include_cold: bool = Query(False),
    timeout: float = Query(SEARCH_TIMEOUT_SECONDS, ge=0.5, le=30),
) -> dict:
    """Hybrid search (BM25 + embeddings) with graceful BM25 fallback.

    If the full search does not return within `timeout` seconds, we abandon
    that worker (leaving it to finish in the background) and run a fresh
    BM25-only search synchronously. This guarantees the response time stays
    bounded regardless of embed-server cold starts.
    """
    from palaia.services.query import search_entries

    root = request.app.state.palaia_root

    def _run():
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
    future = _SEARCH_EXECUTOR.submit(_run)
    try:
        result = future.result(timeout=timeout)
    except (concurrent.futures.TimeoutError, TimeoutError):
        logger.warning("search exceeded %.1fs, falling back to BM25", timeout)
        timed_out = True
        # Abandon the slow worker: don't wait for it, don't cancel
        # (Python can't interrupt running threads). It will complete and
        # its result will be discarded when the future is garbage collected.
        try:
            result = _bm25_only(
                root, q,
                limit=limit, entry_type=type, project=project,
                status=status, priority=priority, include_cold=include_cold,
            )
        except Exception as exc:
            logger.error("BM25 fallback failed: %s", exc)
            result = {"results": [], "has_embeddings": False, "bm25_only": True}

    # Augment results with source flags
    from palaia.web.routes.entries import _detect_source

    for r in result.get("results", []):
        tags = r.get("tags", []) or []
        source = _detect_source(tags)
        r["source"] = source
        r["is_auto_capture"] = source == "auto"
        r["is_manual"] = source in ("webui", "cli")

    return {
        "query": q,
        "results": result.get("results", []),
        "has_embeddings": result.get("has_embeddings", False),
        "bm25_only": result.get("bm25_only", True),
        "timed_out": timed_out,
        "count": len(result.get("results", [])),
    }


def _bm25_only(
    root, query: str, *, limit: int, entry_type, project, status, priority, include_cold,
) -> dict:
    from palaia.search import SearchEngine
    from palaia.store import Store

    store = Store(root)
    store.recover()
    engine = SearchEngine(store)

    # Mutate: safe because single-worker localhost.
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

    return {"results": results, "has_embeddings": False, "bm25_only": True}
