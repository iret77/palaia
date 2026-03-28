# Vector DB Evaluation for Palaia

## Context
Palaia currently uses SQLite for metadata + embeddings + WAL storage. Vector search is
**brute-force Python cosine similarity** — the `backend.vector_search()` method exists
in the protocol but is never called by `SearchEngine`. This evaluation determines whether
to replace, augment, or fix the current approach.

## Benchmarks (384-dim vectors, same hardware)

| Approach | 1K search | 10K search | 100K search | Install size | Deps |
|----------|-----------|------------|-------------|-------------|------|
| **Python brute-force (current)** | 60ms | 606ms | ~6000ms | 0 | 0 |
| **sqlite-vec (SIMD brute-force)** | 1.9ms | 8.9ms | 79ms | 161 KB | 1 |
| **LanceDB (IVF_PQ)** | 8.8ms | 19.2ms | ~50ms* | 272 MB | 10 |
| **pgvector HNSW (existing)** | <5ms* | <5ms* | <10ms* | 0 (psycopg) | 1 |

*estimated from benchmarks/docs

## Candidate Evaluation

### 1. ChromaDB — ❌ NOT RECOMMENDED
- **40 dependencies** including gRPC, OpenTelemetry, kubernetes client, uvicorn
- 272+ MB install footprint
- Overkill for a CLI tool — designed for AI application servers
- Would make Palaia installation dramatically heavier
- **Verdict:** Wrong tool for the job

### 2. LanceDB — ⚠️ INTERESTING BUT HEAVY
- 10 deps, **272 MB** install (PyArrow: 146 MB, LanceDB: 117 MB)
- Nice file-based storage (like SQLite philosophy)
- Good embedded API, SQL-like filtering
- Rust core, decent performance
- **Problem:** PyArrow is a heavy dependency for a lightweight CLI tool
- **Problem:** Would need to keep SQLite for WAL + non-vector metadata anyway
- **Verdict:** Good tech, wrong weight class for Palaia's zero-config philosophy

### 3. Qdrant — ⚠️ CLIENT/SERVER BIAS
- 11 deps, embedded mode exists but is secondary
- Requires `qdrant_client[fastembed]` for embedded use
- HNSW index = great performance at scale
- **Problem:** Designed for client-server, embedded is an afterthought
- **Problem:** Adds gRPC dependency
- **Verdict:** Great vector DB, but wrong deployment model for default Palaia

### 4. Milvus Lite — ❌ NOT RECOMMENDED
- 8 deps but includes pandas (heavy)
- Embedded mode less mature than alternatives
- Adds significant complexity for marginal benefit
- **Verdict:** Not suitable for embedded CLI use

### 5. pgvector (PostgresBackend) — ✅ ALREADY IMPLEMENTED
- **Already exists** in `palaia/backends/postgres.py`
- HNSW index, true ANN search, full SQL metadata
- 1 dep (psycopg), lightweight client
- **Problem:** Requires external PostgreSQL server — not zero-config
- **Verdict:** Perfect scale-up path. Already done. Just needs SearchEngine wiring.

### 6. sqlite-vec (Fix Current) — ✅ RECOMMENDED DEFAULT
- **161 KB** single dependency, no transitive deps
- SIMD-accelerated C brute-force: **30-70x faster than Python**
- 1.9ms at 1K, 8.9ms at 10K, 79ms at 100K — more than fast enough
- Stays in palaia.db, zero additional config
- Already partially integrated (loaded but not used for search!)
- **Cost to implement:** Wire `vector_search()` in SQLiteBackend to use vec0 virtual table, then make SearchEngine call it
- **Verdict:** Maximum impact, minimum disruption

## Recommendation

### Strategy: **Fix & Wire, Don't Replace**

```
Tier 1 (default):  SQLite + sqlite-vec  — zero-config, <100K entries
Tier 2 (scale-up): PostgreSQL + pgvector — distributed teams, >100K entries
```

This is NOT a replacement — it's finishing what's already started:

1. **SQLiteBackend.vector_search()** → Use vec0 virtual table instead of Python cosine
2. **SearchEngine** → Call `backend.vector_search()` instead of manual cosine loop
3. **sqlite-vec** → Move from optional to recommended default
4. **PostgresBackend** → Already has proper pgvector HNSW search

### Implementation Plan

**Phase 1: Wire sqlite-vec properly**
- Add vec0 virtual table to SQLiteBackend schema
- Sync embeddings table → vec0 table on insert/update
- Implement `vector_search()` using `WHERE embedding MATCH ? AND k = ?`
- Fallback to Python cosine if sqlite-vec not available

**Phase 2: Wire SearchEngine to backend**
- Replace manual cosine loop in `SearchEngine.search()` with `backend.vector_search()`
- Keep BM25 component unchanged
- Keep hybrid scoring (0.4 BM25 + 0.6 semantic)

**Phase 3: Make pgvector path work end-to-end**
- Wire SearchEngine to use PostgresBackend.vector_search() when PG backend active
- Test full search pipeline with pgvector HNSW

### Why Not a Full Vector DB?

1. **Palaia is a CLI tool** — 272 MB PyArrow for LanceDB is absurd when 161 KB sqlite-vec does the job
2. **The bottleneck isn't search** — it's Python cosine. Fix that and search is <10ms for any realistic dataset
3. **The architecture already supports scale-up** — PostgresBackend + pgvector exists for production
4. **Zero-config matters** — Palaia's value prop is "just works," no server setup
5. **sqlite-vec at 100K = 79ms** — that's faster than most vector DBs for this scale
