# Palaia Architecture

## Overview

Palaia is a local, crash-safe memory and knowledge system for single- and multi-agent AI setups. It integrates natively with OpenClaw as a memory plugin (ContextEngine) and provides a standalone CLI for direct use.

**Key principles:**
- Flat files for entry content (human-readable, debuggable)
- Pluggable storage backends (SQLite default, PostgreSQL for scale)
- Provider-chain patterns for embeddings and storage
- Zero hard dependencies for core functionality

## Core Design Decisions

| ADR | Topic | Status |
|-----|-------|--------|
| [001](docs/adr/001-semantic-search-tiered.md) | Tiered Semantic Search | Accepted |
| [002](docs/adr/002-scope-tags-knowledge-transfer.md) | Scope Tags + Knowledge Transfer | Accepted |
| [003](docs/adr/003-wal-protocol.md) | WAL Protocol | Accepted |
| [004](docs/adr/004-hot-warm-cold-tiering.md) | HOT/WARM/COLD Tiering | Accepted |
| [005](docs/adr/005-git-as-knowledge-exchange.md) | Git as Knowledge Exchange | Accepted |
| [006](docs/adr/006-memory-entry-format.md) | Memory Entry Format | Accepted |
| [007](docs/adr/007-concurrent-write-locking.md) | Concurrent Write Locking | Accepted |

## Directory Structure

```
.palaia/
├── config.json          # Configuration
├── palaia.db            # SQLite backend (when database_backend=sqlite)
├── .lock                # Advisory file lock
├── hot/                 # Active memories (< 7 days or high score)
│   └── <uuid>.md
├── warm/                # Occasional access (7-30 days)
│   └── <uuid>.md
├── cold/                # Archive (> 30 days)
│   └── <uuid>.md
├── wal/                 # Write-Ahead Log entries (legacy, migrated to DB)
├── index/               # JSON indexes (legacy, migrated to DB)
│   ├── metadata.json    # → entries table in palaia.db
│   └── embeddings.json  # → embeddings table in palaia.db
├── memos/               # Inter-agent messages
├── projects.json        # Project definitions
├── locks/               # Project-level advisory locks
└── runs/                # Process execution state
```

## Module Map

```
palaia/
├── __init__.py          # Version
├── cli.py               # CLI entry point (argparse + thin command handlers)
├── config.py            # Configuration loading/saving, root detection
├── enums.py             # Type-safe string enums (Tier, EntryType, Scope, ...)
├── frontmatter.py       # Shared YAML frontmatter parser/serializer
│
├── # ── Core Storage ──
├── store.py             # Memory store with tier routing, WAL, locking
├── entry.py             # Entry format (YAML frontmatter + markdown body)
├── wal.py               # Write-Ahead Log (delegates to backend)
├── lock.py              # File-based advisory locking (fcntl/msvcrt)
├── project_lock.py      # Project-level advisory locks for multi-agent
│
├── # ── Storage Backends ──
├── backends/
│   ├── __init__.py      # Factory + auto-detection (provider chain)
│   ├── protocol.py      # StorageBackend Protocol (abstract contract)
│   ├── sqlite.py        # SQLite + sqlite-vec backend (zero-config default)
│   ├── postgres.py       # PostgreSQL + pgvector backend (distributed teams)
│   └── migrate.py       # Flat-file → backend migration
│
├── # ── Search & Embeddings ──
├── search.py            # SearchEngine: hybrid BM25 + semantic search
├── bm25.py              # Shared BM25 implementation
├── embeddings.py        # Multi-provider embedding chain (OpenAI, Gemini, FastEmbed, Ollama, ...)
├── index.py             # EmbeddingCache (delegates to backend)
├── metadata_index.py    # MetadataIndex (delegates to backend)
├── embed_server.py      # Long-lived embedding subprocess (JSON-RPC)
│
├── # ── Services ──
├── services/
│   ├── __init__.py
│   ├── write.py         # Write/edit orchestration
│   ├── query.py         # Search/get/list orchestration
│   ├── status.py        # System status collection
│   └── admin.py         # Init, GC, config, recovery
│
├── # ── Features ──
├── decay.py             # Decay scoring + tier classification
├── scope.py             # Scope validation + access control
├── significance.py      # Significance scoring for auto-capture
├── nudge.py             # Adaptive agent coaching
├── memo.py              # Inter-agent messaging (ADR-010)
├── project.py           # Project management (ADR-008)
├── process_runner.py    # Process step execution
├── ingest.py            # Document ingestion / RAG (ADR-009)
├── packages.py          # Knowledge package export/import
├── sync.py              # Entry import/export
├── migrate.py           # Format migration from external sources
├── priorities.py        # Injection priority management (per-agent/project)
├── curate.py            # Knowledge curation (clustering, dedup, KEEP/MERGE/DROP)
├── ui.py                # Terminal formatting utilities
│
├── # ── Diagnostics ──
├── doctor/
│   ├── __init__.py      # Public API: run_doctor(), apply_fixes()
│   ├── checks.py        # Health check functions
│   ├── fixes.py         # Auto-repair logic
│   └── detection.py     # Legacy system detection
│
└── SKILL.md             # Agent skill documentation

packages/openclaw-plugin/
├── index.ts             # Plugin entry point (definePluginEntry)
├── src/
│   ├── context-engine.ts  # ContextEngine adapter (7 lifecycle hooks)
│   ├── hooks/
│   │   ├── index.ts       # Hook registration
│   │   ├── recall.ts      # Memory injection (before_prompt_build)
│   │   ├── capture.ts     # Auto-capture (agent_end)
│   │   ├── state.ts       # Session state management
│   │   └── reactions.ts   # Emoji reactions (Slack)
│   ├── runner.ts          # CLI subprocess runner + embed server manager
│   └── types.ts           # Local type definitions (OpenClawPluginApi)
├── skill/SKILL.md         # Bundled agent skill documentation
└── openclaw.plugin.json   # Plugin manifest
```

## Storage Backend Architecture

```
Detection order (provider chain):
1. Config: database_url → PostgreSQL + pgvector
2. Env: PALAIA_DATABASE_URL → PostgreSQL + pgvector
3. Default → SQLite (zero-config, single file, WAL mode)
4. Legacy fallback → JSON files (backward compatible, auto-migrated to SQLite)

StorageBackend Protocol
├── SQLiteBackend        — Zero-config, embedded, single file
│   ├── sqlite3 (stdlib) — Metadata + WAL
│   ├── sqlite-vec       — Vector KNN search (optional)
│   └── FTS5             — Full-text search (built-in)
│
└── PostgresBackend      — Production, distributed teams
    ├── psycopg           — Connection (pip install 'palaia[postgres]')
    ├── pgvector HNSW     — ANN vector search (millions of entries)
    └── tsvector          — Language-aware full-text search
```

## Data Flow

### Write Path
```
1. Validate body (non-empty)
2. Scope cascade: explicit > project default > config default > "team"
3. Dedup check via backend.find_by_hash() [O(1) with index]
4. Create entry (UUID, frontmatter, auto-title)
5. Acquire lock
6. WAL: log pending entry (with payload for recovery)
7. Write .md file to hot/ (atomic: write tmp → fsync → rename)
8. WAL: mark committed
9. Release lock
10. Update metadata index + compute embedding (fire-and-forget)
```

### Search Path
```
1. Build BM25 index from hot + warm (cached, invalidated on write)
2. Apply structured filters (project, type, status, ...)
3. BM25 keyword ranking
4. Semantic embedding ranking (cached vectors, cosine similarity)
5. Hybrid combination: 0.4 × BM25 + 0.6 × embedding
6. Return top-K with full metadata
```

### GC / Tier Rotation
```
1. Phase 1 (unlocked): Scan all entries, compute decay scores
2. Phase 2 (locked): Move entries between tiers via WAL
3. Budget enforcement: Prune lowest gc_score entries if over limits
4. Cleanup: WAL, embedding cache, metadata index
```

## OpenClaw Integration

```
OpenClaw Agent
  ↓ registerContextEngine("palaia")
PalaiaContextEngine
  ├── bootstrap()           → WAL recovery + embed-server start
  ├── ingest(messages)      → Auto-capture (LLM + rule-based extraction)
  ├── assemble(budget)      → Token-budget-aware contextual recall
  ├── compact()             → palaia gc
  ├── afterTurn(turn)       → State cleanup + emoji reactions
  ├── prepareSubagentSpawn  → Scope/workspace propagation
  └── onSubagentEnded       → Sub-agent memory merge

Agent Tools:
  ├── memory_search(query)  → palaia query --json
  ├── memory_get(path)      → palaia get --json
  └── memory_write(content) → palaia write --json (with dedup guard)
```

## Crash Safety

The WAL guarantees that no write is lost:
- Every write logs intent + payload to WAL before touching data
- On startup, `recover()` replays any pending entries
- Atomic file writes (tmp + fsync + rename) prevent partial writes
- File locking prevents concurrent corruption
- SQLite backend uses native WAL mode for additional safety
