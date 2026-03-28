# Embed Server

The embed-server is a background process that keeps the embedding model loaded in memory. Without it, every CLI call loads the model from scratch (~2-5s). With it: **<500ms per query**.

## How It Works

```
palaia query "..."
    ↓
Is embed-server running? ──yes──→ Delegate full search via Unix socket (~300ms)
    ↓ no
Load model in-process (~2-5s), execute search, exit
```

The server holds the `SearchEngine` and `Store` warm in RAM. CLI commands delegate the full search to it instead of loading everything from scratch.

## Usage

### Start manually

```bash
palaia embed-server --socket --daemon     # Background daemon
palaia embed-server --status              # Check if running
palaia embed-server --stop                # Stop
```

### Auto-start

When a local embedding provider (fastembed, sentence-transformers) is configured, the server auto-starts on the first CLI query. No manual action needed.

API-based providers (OpenAI, Gemini, Ollama) don't benefit from the embed-server — they don't load local models. Auto-start is skipped for them.

### Configuration

| Config key | Default | Description |
|------------|---------|-------------|
| `embed_server_auto_start` | `true` | Auto-start daemon on first CLI query |
| `embed_server_idle_timeout` | `1800` | Auto-shutdown after N seconds idle (default: 30 min) |

```bash
palaia config set embed_server_idle_timeout 3600    # 1 hour
palaia config set embed_server_auto_start false      # Disable auto-start
```

## Architecture

### Transport

- **stdio** (default): For the OpenClaw TypeScript plugin. Parent process spawns the server and communicates via stdin/stdout.
- **Unix socket**: For CLI and MCP server. Multiple clients connect to `~/.palaia/embed.sock`.

### Protocol

Newline-delimited JSON-RPC over the transport:

```json
{"method": "query", "params": {"text": "...", "top_k": 10}}
{"method": "embed", "params": {"texts": ["...", "..."]}}
{"method": "ping"}
{"method": "status"}
{"method": "warmup"}
{"method": "shutdown"}
```

### Lifecycle

- **PID file**: `~/.palaia/embed-server.pid` — tracks the running daemon
- **Socket file**: `~/.palaia/embed.sock` — Unix domain socket
- **Stale detection**: Background thread checks entry count every 30s, rebuilds index on changes
- **Warmup**: Indexes uncached entries in background on startup. Queries use BM25 fallback during warmup.
- **Idle timeout**: Auto-shutdown after configurable idle period (default 30 min)

### Multiple Stores

Each `.palaia/` directory gets its own embed-server instance (separate socket, separate PID file). Different projects can use different embedding models.

## Performance Budget

| Scenario | Without server | With server |
|----------|---------------|-------------|
| `palaia query` (fastembed) | ~5s | <500ms |
| `palaia write` (embedding) | ~3s | <500ms |
| First query after start | ~3s (model load) | <500ms (pre-warmed) |
| Memory overhead | 0 | ~200MB (one model instance) |

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Server won't start | Check `palaia embed-server --status`. If stale, `palaia embed-server --stop` clears PID/socket files. |
| "Address already in use" | Another server is running. Use `--stop` first, or check for stale `.palaia/embed.sock`. |
| High memory usage | The embedding model (~200MB) stays in RAM. Stop with `--stop` or reduce `embed_server_idle_timeout`. |
| Auto-start not working | Check `palaia config list` for `embed_server_auto_start`. Only triggers for local providers (fastembed, sentence-transformers). |
