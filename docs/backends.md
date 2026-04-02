# Storage & Search

## Database Backends

| Backend | Vector Search | Use Case | Install |
|---------|---------------|----------|---------|
| **SQLite** (default) | sqlite-vec (SIMD KNN) or Python fallback | Local, single-agent or small team | Included |
| **PostgreSQL** | pgvector (ANN, HNSW index) | Distributed teams, multiple hosts | `pip install 'palaia[postgres]'` |

### SQLite (default)

Zero-config. `palaia init` creates a single `palaia.db` file with WAL mode for crash safety. Works everywhere Python runs.

**sqlite-vec acceleration:**
```bash
pip install "palaia[sqlite-vec]"
```

sqlite-vec is a 161 KB SIMD-accelerated extension that replaces Python cosine similarity with native KNN search. Performance at scale:

| Entries | Python fallback | sqlite-vec |
|---------|----------------|------------|
| 1,000 | ~60ms | ~1.9ms |
| 10,000 | ~600ms | ~9ms |
| 100,000 | unusable | ~79ms |

Verify it's active:
```bash
palaia detect    # Shows "sqlite-vec: ok" or "n/a"
palaia status    # Shows "Backend: SQLITE — sqlite-vec (native KNN)"
```

### PostgreSQL + pgvector

For teams with agents on multiple machines sharing one store:

```bash
pip install "palaia[postgres]"
palaia config set database_url postgresql://user:pass@host/db
# or: export PALAIA_DATABASE_URL=postgresql://...
```

Requires PostgreSQL with the [pgvector](https://github.com/pgvector/pgvector) extension. palaia creates an HNSW index automatically for fast approximate nearest neighbor search.

### Migration

Existing flat-file stores (pre-v2.0) migrate to SQLite automatically on first use. No manual steps needed. `palaia doctor --fix` handles edge cases.

---

## Embedding Providers

palaia uses **hybrid search**: BM25 keyword matching (always active) combined with semantic vector embeddings (when a provider is configured).

### Provider Chain

Providers are tried in order. First available wins, with BM25 as implicit fallback:

| Provider | Type | Latency | Model | Install |
|----------|------|---------|-------|---------|
| fastembed | Local (CPU) | ~10ms/query | bge-small-en-v1.5 | `pip install 'palaia[fastembed]'` (default) |
| sentence-transformers | Local (CPU/GPU) | ~10ms/query | all-MiniLM-L6-v2 | `pip install 'palaia[sentence-transformers]'` |
| Ollama | Local (server) | ~50ms/query | nomic-embed-text | `ollama pull nomic-embed-text` |
| OpenAI | API | ~200ms/query | text-embedding-3-small | Set `OPENAI_API_KEY` |
| Gemini | API | ~200ms/query | embedding-001 | Set `GEMINI_API_KEY` |
| BM25 | Built-in | <1ms/query | — | Always available (keyword only) |

### Configure the chain

```bash
# Set explicit provider order
palaia config set-chain fastembed bm25

# Or with multiple providers (fallback order)
palaia config set-chain openai fastembed bm25

# Check what's available
palaia detect
```

### Model overrides

```bash
palaia config set embedding_models '{"fastembed": "BAAI/bge-base-en-v1.5", "openai": "text-embedding-3-large"}'
```

---

## Hybrid Ranking

Search results are scored by combining two signals:

- **BM25** (40% weight): Keyword frequency matching. Fast, always available.
- **Embeddings** (60% weight): Semantic similarity via vector cosine distance. Finds conceptually related content even without keyword overlap.

When no embedding provider is available, search falls back to BM25-only (still functional, just keyword-based).

---

## Embedding Cache

Embeddings are computed once per entry and cached in the database. Subsequent searches reuse cached vectors. The cache is invalidated automatically when entry content changes (via `palaia edit`).

Rebuild the cache:
```bash
palaia warmup    # Pre-compute all missing embeddings
```
