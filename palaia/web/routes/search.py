"""Search API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(tags=["search"])


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
) -> dict:
    """Hybrid search (BM25 + semantic embeddings)."""
    from palaia.services.query import search_entries

    root = request.app.state.palaia_root
    result = search_entries(
        root,
        q,
        limit=limit,
        entry_type=type,
        project=project,
        status=status,
        priority=priority,
        include_cold=include_cold,
    )

    return {
        "query": q,
        "results": result["results"],
        "has_embeddings": result["has_embeddings"],
        "bm25_only": result["bm25_only"],
        "count": len(result["results"]),
    }
