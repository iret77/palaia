"""Hybrid search: BM25 + semantic embeddings (ADR-001)."""

from __future__ import annotations

import logging

from palaia.bm25 import BM25, tokenize  # noqa: F401 — re-exported for backward compat
from palaia.embeddings import (
    BM25Provider,
    _create_provider,
    _resolve_embedding_models,
    auto_detect_provider,
    cosine_similarity,
    detect_providers,
    get_provider_display_info,
)

logger = logging.getLogger(__name__)


def detect_search_tier() -> int:
    """Detect best available search tier.

    Returns:
        1: BM25 only
        2: Local embeddings (ollama, sentence-transformers, fastembed)
        3: API embeddings (OpenAI)
    """
    from palaia.embeddings import detect_providers

    providers = detect_providers()
    for p in providers:
        if p["available"]:
            if p["name"] == "openai":
                return 3
            elif p["name"] in ("ollama", "sentence-transformers", "fastembed"):
                return 2
    return 1


def _resolve_semantic_provider(config: dict):
    """Resolve the semantic embedding provider respecting embedding_chain config.

    Reads ``embedding_chain`` from *config*, iterates over its entries (skipping
    ``"bm25"``), and returns the first provider that can be instantiated.
    Falls back to ``auto_detect_provider()`` when the chain is absent, empty,
    contains only ``"bm25"``, or none of its semantic entries are available.
    """
    chain = config.get("embedding_chain")
    if chain and isinstance(chain, list):
        models = _resolve_embedding_models(config)
        available = {p["name"] for p in detect_providers() if p["available"]}
        for name in chain:
            if name == "bm25":
                continue
            if name not in available:
                continue
            try:
                return _create_provider(name, models.get(name))
            except (ImportError, ValueError):
                continue
    # No chain configured or no chain provider available → legacy fallback
    return auto_detect_provider(config)


class SearchEngine:
    """Unified hybrid search: BM25 + semantic embeddings."""

    def __init__(self, store, config: dict | None = None):
        self.store = store
        self.bm25 = BM25()
        self.config = config or store.config
        self._provider = None
        self._index_cache: list[tuple[str, str, dict]] | None = None
        self._index_dirty = True
        self._index_cache_key: tuple | None = None  # (include_cold, agent) for cache validity

    @property
    def provider(self):
        if self._provider is None:
            self._provider = _resolve_semantic_provider(self.config)
        return self._provider

    @property
    def has_embeddings(self) -> bool:
        return not isinstance(self.provider, BM25Provider)

    def invalidate_index(self) -> None:
        """Mark the cached BM25 index as dirty. Call after store modifications."""
        self._index_dirty = True
        self._index_cache = None

    def build_index(self, include_cold: bool = False, agent: str | None = None) -> list[tuple[str, str, dict]]:
        """Build search index from store entries. Returns (doc_id, full_text, meta) list.

        Uses a cached index when available. Call invalidate_index() after
        write/edit/gc operations to force a rebuild.
        """
        cache_key = (include_cold, agent)
        if not self._index_dirty and self._index_cache is not None and self._index_cache_key == cache_key:
            # Re-index BM25 from cache (cheap — no disk reads)
            self.bm25.index([(did, text) for did, text, _meta in self._index_cache])
            return list(self._index_cache)

        entries = self.store.all_entries(include_cold=include_cold, agent=agent)
        docs = []
        docs_with_meta = []
        for meta, body, tier in entries:
            doc_id = meta.get("id", "unknown")
            title = meta.get("title", "")
            tags = " ".join(meta.get("tags", []))
            full_text = f"{title} {tags} {body}"
            docs.append((doc_id, full_text))
            docs_with_meta.append((doc_id, full_text, meta))
        self.bm25.index(docs)
        self._index_cache = docs_with_meta
        self._index_cache_key = cache_key
        self._index_dirty = False
        return docs_with_meta

    def search(
        self,
        query: str,
        top_k: int = 10,
        include_cold: bool = False,
        project: str | None = None,
        agent: str | None = None,
        entry_type: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        assignee: str | None = None,
        instance: str | None = None,
        before: str | None = None,
        after: str | None = None,
        cross_project: bool = False,
    ) -> list[dict]:
        """Search memories using hybrid ranking (BM25 + embeddings when available).

        Structured filters (type, status, priority, assignee, instance) use exact match,
        not embeddings.

        Temporal filters (before, after) filter by entry created timestamp.
        cross_project=True ignores project filter and searches across all projects.
        """
        docs_with_meta = self.build_index(include_cold=include_cold, agent=agent)

        # Apply structured filters (exact match, pre-BM25)
        if project and not cross_project:
            docs_with_meta = [(did, text, meta) for did, text, meta in docs_with_meta if meta.get("project") == project]
        if entry_type:
            docs_with_meta = [
                (did, text, meta) for did, text, meta in docs_with_meta if meta.get("type", "memory") == entry_type
            ]
        if status:
            docs_with_meta = [(did, text, meta) for did, text, meta in docs_with_meta if meta.get("status") == status]
        if priority:
            docs_with_meta = [
                (did, text, meta) for did, text, meta in docs_with_meta if meta.get("priority") == priority
            ]
        if assignee:
            docs_with_meta = [
                (did, text, meta) for did, text, meta in docs_with_meta if meta.get("assignee") == assignee
            ]
        if instance:
            docs_with_meta = [
                (did, text, meta) for did, text, meta in docs_with_meta if meta.get("instance") == instance
            ]

        # Temporal filters (Issue #74)
        if before:
            docs_with_meta = [
                (did, text, meta) for did, text, meta in docs_with_meta if meta.get("created", "") < before
            ]
        if after:
            docs_with_meta = [
                (did, text, meta) for did, text, meta in docs_with_meta if meta.get("created", "") > after
            ]

        if project or entry_type or status or priority or assignee or instance or before or after:
            # Rebuild BM25 index with filtered docs
            self.bm25.index([(did, text) for did, text, meta in docs_with_meta])

        # BM25 scores
        bm25_results = self.bm25.search(query, top_k=top_k * 2)  # get more candidates for hybrid
        bm25_scores = {doc_id: score for doc_id, score in bm25_results}

        # Normalize BM25 scores to [0, 1]
        max_bm25 = max(bm25_scores.values()) if bm25_scores else 1.0
        bm25_norm = {k: v / max_bm25 for k, v in bm25_scores.items()} if max_bm25 > 0 else {}

        # Embedding scores (if available)
        embed_norm = {}
        if self.has_embeddings and docs_with_meta:
            try:
                query_vec = self.provider.embed_query(query)

                # Fast path: use backend-native vector search (sqlite-vec / pgvector)
                backend = getattr(self.store, "_backend", None)
                is_postgres = backend is not None and type(backend).__name__ == "PostgresBackend"
                has_native_vec = (
                    backend is not None
                    and hasattr(backend, "vector_search")
                    and (getattr(backend, "_has_vec", False) or is_postgres)
                )

                if has_native_vec:
                    # Embed any uncached BM25 candidates first so they're in the DB
                    candidate_ids = set(bm25_scores.keys())
                    texts_to_embed = []
                    ids_to_embed = []
                    for doc_id, full_text, meta in docs_with_meta:
                        cached = self.store.embedding_cache.get_cached(doc_id)
                        if cached is None and (doc_id in candidate_ids or len(texts_to_embed) < top_k):
                            texts_to_embed.append(full_text)
                            ids_to_embed.append(doc_id)

                    if texts_to_embed:
                        vectors = self.provider.embed(texts_to_embed)
                        model_name = getattr(self.provider, "model_name", None) or getattr(
                            self.provider, "model", "unknown"
                        )
                        for doc_id, vec in zip(ids_to_embed, vectors):
                            self.store.embedding_cache.set_cached(doc_id, vec, model=model_name)

                    # Native KNN search (SIMD-accelerated)
                    vec_results = backend.vector_search(query_vec, top_k=top_k * 2)
                    embed_norm = {doc_id: sim for doc_id, sim in vec_results}
                else:
                    # Fallback: Python cosine similarity (no native vector search)
                    candidate_ids = set(bm25_scores.keys())
                    texts_to_embed = []
                    ids_to_embed = []
                    for doc_id, full_text, meta in docs_with_meta:
                        cached = self.store.embedding_cache.get_cached(doc_id)
                        if cached:
                            sim = cosine_similarity(query_vec, cached)
                            embed_norm[doc_id] = sim
                        elif doc_id in candidate_ids or len(texts_to_embed) < top_k:
                            texts_to_embed.append(full_text)
                            ids_to_embed.append(doc_id)

                    if texts_to_embed:
                        vectors = self.provider.embed(texts_to_embed)
                        model_name = getattr(self.provider, "model_name", None) or getattr(
                            self.provider, "model", "unknown"
                        )
                        for doc_id, vec in zip(ids_to_embed, vectors):
                            self.store.embedding_cache.set_cached(doc_id, vec, model=model_name)
                            sim = cosine_similarity(query_vec, vec)
                            embed_norm[doc_id] = sim
            except Exception as e:
                # If embedding fails, fall back to BM25 only
                logger.warning("Embedding search failed, using BM25 only: %s", e)
                embed_norm = {}

        # Combine scores: hybrid ranking
        all_ids = set(bm25_norm.keys()) | set(embed_norm.keys())
        combined = {}
        for doc_id in all_ids:
            bm25_s = bm25_norm.get(doc_id, 0.0)
            embed_s = embed_norm.get(doc_id, 0.0)
            if embed_norm:
                # Weighted combination: 40% BM25 + 60% embedding
                combined[doc_id] = 0.4 * bm25_s + 0.6 * embed_s
            else:
                combined[doc_id] = bm25_s

        # Sort by combined score
        ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)[:top_k]

        # Build output
        output = []
        for doc_id, score in ranked:
            entry = self.store.read(doc_id)
            if entry:
                meta, body = entry
                result_entry = {
                    "id": doc_id,
                    "score": round(score, 4),
                    "bm25_score": round(bm25_norm.get(doc_id, 0.0), 4),
                    "embed_score": round(embed_norm.get(doc_id, 0.0), 4),
                    "type": meta.get("type", "memory"),
                    "scope": meta.get("scope", "team"),
                    "title": meta.get("title", ""),
                    "tags": meta.get("tags", []),
                    "body": body[:200] + ("..." if len(body) > 200 else ""),
                    "tier": self._get_tier(doc_id),
                    "decay_score": meta.get("decay_score", 0),
                }
                # Include task fields if present
                if meta.get("status"):
                    result_entry["status"] = meta["status"]
                if meta.get("priority"):
                    result_entry["priority"] = meta["priority"]
                if meta.get("assignee"):
                    result_entry["assignee"] = meta["assignee"]
                if meta.get("due_date"):
                    result_entry["due_date"] = meta["due_date"]
                if meta.get("instance"):
                    result_entry["instance"] = meta["instance"]
                if meta.get("project"):
                    result_entry["project"] = meta["project"]
                output.append(result_entry)
        return output

    def _get_tier(self, entry_id: str) -> str:
        """Determine which tier an entry is in."""
        for tier in ("hot", "warm", "cold"):
            if (self.store.root / tier / f"{entry_id}.md").exists():
                return tier
        return "unknown"

    def search_info(self) -> dict:
        """Get info about current search configuration."""
        provider = self.provider
        provider_display = get_provider_display_info(provider)
        has_embed = self.has_embeddings
        return {
            "provider": provider_display,
            "has_embeddings": has_embed,
            "bm25_active": True,
            "semantic_active": has_embed,
        }
