# Palaia — The Knowledge OS for AI Agent Teams

**Crash-safe. Local-first. Zero-cloud. The memory system that makes your agents smarter over time.**

[![CI](https://github.com/iret77/palaia/actions/workflows/ci.yml/badge.svg)](https://github.com/iret77/palaia/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/palaia)](https://pypi.org/project/palaia/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![OpenClaw Plugin](https://img.shields.io/badge/OpenClaw-Plugin-blueviolet)](https://openclaw.ai)

---

## Install

### Recommended: Tell your agent

Paste this into your OpenClaw agent (works for install AND update):

> Install or update the Palaia memory skill from ClawHub to the latest version (even if already present). Read the SKILL.md completely and follow it step by step. Run palaia init, then palaia doctor --fix and resolve all warnings — don't stop until the doctor report is clean. Set up completely.

The agent handles everything: ClawHub skill install, pip setup, plugin config, and verification.

### Manual / Expert Setup

```bash
pip install "palaia[fastembed]"
palaia init
palaia doctor --fix
```

Optional extras:
```bash
pip install "palaia[sqlite-vec]"   # Native SIMD vector search (~30x faster)
pip install "palaia[mcp]"          # MCP server for Claude Desktop, Cursor
pip install "palaia[curate]"       # Knowledge curation
pip install "palaia[postgres]"     # PostgreSQL + pgvector backend
```

For the OpenClaw plugin (Auto-Capture + Auto-Recall):
```bash
npm install -g @byte5ai/palaia@latest
```
Then configure `openclaw.json` — see [SKILL.md](palaia/SKILL.md) for details.

**Upgrading?** `palaia upgrade` — auto-detects install method, preserves extras, runs doctor.

## Quick Start

```bash
palaia init                                         # Initialize (SQLite store)
palaia write "API rate limit is 100 req/min" \
  --type memory --tags api,limits                   # Save knowledge
palaia query "what's the rate limit"                # Find it by meaning
```

---

## Why Palaia?

| Feature | Details |
|---------|---------|
| **SQLite + sqlite-vec** | Single-file database with WAL mode. Optional SIMD-accelerated vector KNN via sqlite-vec. |
| **PostgreSQL + pgvector** | Distributed teams: ANN search with HNSW index. `palaia config set database_url postgresql://...` |
| **Semantic Search** | Hybrid BM25 + embeddings. Providers: fastembed, sentence-transformers, OpenAI, Gemini, Ollama |
| **MCP Server** | `palaia-mcp` — standalone memory for Claude Desktop, Cursor, any MCP host. No OpenClaw required. |
| **Embed Server** | Background process holds model in RAM. CLI queries drop from ~5s to <500ms. |
| **Crash-Safe Writes** | WAL-backed — survives power loss, kills, OOM |
| **Auto-Capture** | OpenClaw plugin captures significant exchanges automatically |
| **Structured Types** | memory, process, task — with status, priority, assignee fields |
| **Multi-Agent** | Shared store, scopes (private/team/public), agent aliases, per-agent priorities |
| **Smart Tiering** | HOT -> WARM -> COLD rotation based on access patterns |
| **Knowledge Curation** | Cluster, deduplicate, and clean up accumulated knowledge for migration |
| **Zero-Cloud** | Everything runs locally. No API keys required for core functionality |

---

## Storage & Search

### Backends

| Backend | Vector Search | Use Case | Install |
|---------|---------------|----------|---------|
| **SQLite** (default) | sqlite-vec (SIMD KNN) or Python fallback | Local, single-agent or small team | Included |
| **PostgreSQL** | pgvector (ANN, HNSW) | Distributed teams, multiple hosts | `pip install 'palaia[postgres]'` |

SQLite is zero-config. For PostgreSQL:
```bash
pip install "palaia[postgres]"
palaia config set database_url postgresql://user:pass@host/db
```

### Embedding Providers

| Provider | Type | Install |
|----------|------|---------|
| fastembed | Local (CPU) | `pip install 'palaia[fastembed]'` (default) |
| sentence-transformers | Local (CPU/GPU) | `pip install 'palaia[sentence-transformers]'` |
| Ollama | Local (server) | `ollama pull nomic-embed-text` |
| OpenAI | API | Set `OPENAI_API_KEY` |
| Gemini | API | Set `GEMINI_API_KEY` |
| BM25 | Built-in | Always available (keyword only) |

### Embed Server (Performance)

The embed-server keeps the embedding model loaded in memory for fast CLI queries:
```bash
palaia embed-server --socket --daemon   # Start background server
palaia embed-server --status            # Check if running
```
Without server: ~5s per query. With server: **<500ms**. Auto-starts on first CLI query when a local provider is configured.

### MCP Server (Claude Desktop, Cursor)

Palaia works as a standalone MCP memory server — **no OpenClaw required**:
```bash
pip install "palaia[mcp]"
palaia-mcp                              # Start MCP server (stdio)
palaia-mcp --read-only                  # No writes (untrusted hosts)
```

Claude Desktop config (`~/.config/claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "palaia": {
      "command": "palaia-mcp",
      "args": []
    }
  }
}
```

7 MCP tools: `palaia_search`, `palaia_store`, `palaia_read`, `palaia_edit`, `palaia_list`, `palaia_status`, `palaia_gc`.

---

## Architecture

```
palaia/
  backends/        Storage backends (SQLite, PostgreSQL)
  services/        Business logic (write, query, status, admin)
  doctor/          Diagnostics (checks, fixes, detection)
  mcp/             MCP server (Claude Desktop, Cursor)
  hooks/           OpenClaw hook handlers (recall, capture, state, reactions)
  context-engine   ContextEngine adapter (7 lifecycle hooks)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full module map and data flows.

---

## CLI Reference

```
palaia init                                          Initialize store (SQLite)
palaia write "text" [--type TYPE] [--tags a,b]       Save knowledge
palaia query "search" [--type TYPE] [--project P]    Search by meaning
palaia get <id>                                       Read specific entry
palaia list [--tier T] [--type T] [--status S]       List entries
palaia edit <id> [--status done]                      Edit entry
palaia status                                         System health + upgrade command
palaia doctor [--fix]                                 Diagnose + fix
palaia upgrade                                        Update to latest (preserves extras)
palaia project create|list|show|query|delete          Manage projects
palaia memo send|inbox|ack|broadcast                  Inter-agent messaging
palaia priorities [block|set]                         Injection priorities
palaia curate analyze|apply                           Knowledge curation
palaia sync export|import                             Git-based exchange
palaia package export|import|info                     Portable packages
palaia process list|run                               Process tracking
palaia gc [--aggressive] [--budget N]                 Garbage collection
palaia config list|set|set-chain                      Configuration
palaia ingest <source> [--project P]                  Index documents (RAG)
palaia detect                                         Available providers + sqlite-vec
palaia warmup                                         Pre-build search index
palaia embed-server [--socket] [--daemon]             Background embedding server
palaia mcp-server [--read-only]                       MCP server for AI tools
```

All commands support `--json` for machine-readable output.

---

## Comparison

| Feature | Palaia | Stock Memory | Mem0 | Engram |
|---------|--------|-------------|------|--------|
| Local-first | Yes | Yes | No (cloud) | Yes |
| Crash-safe (WAL) | Yes | No | N/A | No |
| Native Vector Search | Yes (sqlite-vec/pgvector) | No | No | No |
| MCP Server | Yes | No | No | No |
| Auto-Capture | Yes (plugin) | No | Yes | No |
| Structured Types | Yes (memory/process/task) | No | No | No |
| Multi-Agent Scopes | Yes (private/team/public) | No | Per-user | No |
| Smart Tiering | Yes (HOT/WARM/COLD) | No | No | No |
| Knowledge Curation | Yes | No | No | No |
| Semantic Search | Hybrid (embedding + BM25) | None | Embedding | Embedding |
| Zero-Cloud | Yes | Yes | No | Yes |

---

## Development

```bash
git clone https://github.com/iret77/palaia.git
cd palaia
pip install -e ".[dev]"
pytest
```

## Links

- [GitHub](https://github.com/iret77/palaia) — Source + Issues
- [PyPI](https://pypi.org/project/palaia/) — Package registry
- [ClawHub](https://clawhub.com/skills/palaia) — Install via agent skill
- [OpenClaw](https://openclaw.ai) — The agent platform Palaia is built for
- [CHANGELOG](CHANGELOG.md) — Release history

---

MIT — (c) 2026 [byte5 GmbH](https://byte5.de)
