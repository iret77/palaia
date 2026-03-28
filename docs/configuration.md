# Configuration

## Config File

palaia configuration lives in `.palaia/config.json`. Edit via CLI:

```bash
palaia config list                         # Show all settings
palaia config set <key> <value>            # Set a value
palaia config set-chain fastembed bm25     # Set embedding provider chain
```

## Configuration Keys

| Key | Default | Description |
|-----|---------|-------------|
| **Storage** | | |
| `database_backend` | `sqlite` | Storage backend: `sqlite` or `postgres` |
| `database_url` | *(none)* | PostgreSQL connection string (also via `PALAIA_DATABASE_URL` env) |
| **Search** | | |
| `embedding_chain` | *(auto)* | Ordered list of embedding providers |
| `embedding_provider` | `auto` | Legacy: single provider name |
| `embedding_models` | `{}` | Per-provider model overrides |
| **Tiering** | | |
| `hot_threshold_days` | `7` | Days before HOT → WARM |
| `warm_threshold_days` | `30` | Days before WARM → COLD |
| `hot_max_entries` | `50` | Max entries in HOT tier |
| `decay_lambda` | `0.1` | Decay rate for memory scores |
| **Scopes & Agent** | | |
| `default_scope` | `team` | Default visibility for new entries |
| `agent` | *(none)* | Agent name (also via `PALAIA_AGENT` env) |
| `multi_agent` | `false` | Enable multi-agent features |
| `aliases` | `{}` | Agent alias mappings |
| **Embed Server** | | |
| `embed_server_auto_start` | `true` | Auto-start daemon on first CLI query |
| `embed_server_idle_timeout` | `1800` | Daemon auto-shutdown after N seconds idle |
| **Budget** | | |
| `max_entries_per_tier` | *(none)* | Hard limit on entries per tier |
| `max_total_chars` | *(none)* | Hard limit on total character count |
| **GC** | | |
| `gc_type_weights` | `{"process": 2.0, "task": 1.5, "memory": 1.0}` | Type-specific GC scoring weights |
| `wal_retention_days` | `7` | WAL entry retention before cleanup |
| `lock_timeout_seconds` | `5` | File lock timeout for concurrent access |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `PALAIA_HOME` | Explicit path to `.palaia` directory |
| `PALAIA_AGENT` | Agent name (overrides config) |
| `PALAIA_INSTANCE` | Session identity tag |
| `PALAIA_DATABASE_URL` | PostgreSQL connection (overrides config) |

## Embedding Chain

The embedding chain defines which providers are tried in order:

```bash
# Single provider
palaia config set-chain fastembed bm25

# Multiple with fallback
palaia config set-chain openai fastembed bm25

# API-first, local fallback
palaia config set-chain gemini openai fastembed bm25
```

BM25 is always the implicit last resort. If all providers fail, keyword search still works.

Check available providers:
```bash
palaia detect
```

## Model Overrides

Override the default model for any provider:

```bash
palaia config set embedding_models '{
  "fastembed": "BAAI/bge-base-en-v1.5",
  "openai": "text-embedding-3-large",
  "sentence-transformers": "all-mpnet-base-v2"
}'
```

## OpenClaw Plugin Configuration

When using palaia as an OpenClaw plugin, additional settings go in `openclaw.json`:

| Key | Default | Description |
|-----|---------|-------------|
| `tier` | `hot` | Which tiers to search: `hot`, `warm`, `all` |
| `maxResults` | `10` | Max memories injected per query |
| `timeoutMs` | `3000` | Query timeout in milliseconds |
| `memoryInject` | `true` | Enable Auto-Recall |
| `autoCapture` | `true` | Enable Auto-Capture |
| `captureFrequency` | `significant` | When to capture: `always`, `significant`, `manual` |
| `embeddingServer` | `true` | Keep embedding model loaded |
| `showMemorySources` | `true` | Show memory source footnotes |
| `recallMode` | `query` | How to build recall queries |
| `recallMinScore` | `0.7` | Minimum score threshold |
