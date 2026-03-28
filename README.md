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

### Manual Setup

```bash
pip install "palaia[fastembed]"
palaia init
palaia doctor --fix
```

Optional extras:
```bash
pip install "palaia[mcp]"          # MCP server for Claude Desktop, Cursor
pip install "palaia[curate]"       # Knowledge curation
pip install "palaia[postgres]"     # PostgreSQL + pgvector backend
```

Note: `palaia[fastembed]` already includes sqlite-vec for native vector search and the embed-server auto-starts on first query. No manual optimization needed.

**Upgrading?** `palaia upgrade` — auto-detects install method, preserves extras, runs doctor.

### MCP Setup (Claude Desktop, Cursor — no OpenClaw needed)

```bash
pip install "palaia[mcp,fastembed]"
palaia init
```

Add to `~/.config/claude/claude_desktop_config.json` (Claude Desktop) or `.cursor/mcp.json` (Cursor):
```json
{
  "mcpServers": {
    "palaia": {
      "command": "palaia-mcp"
    }
  }
}
```

## Quick Start

```bash
palaia write "API rate limit is 100 req/min" \
  --type memory --tags api,limits                   # Save knowledge
palaia query "what's the rate limit"                # Find it by meaning
palaia status                                        # Check health
```

---

## Why Palaia?

| Feature | Details |
|---------|---------|
| **Semantic Search** | Hybrid BM25 + vector embeddings. 6 providers: fastembed, sentence-transformers, Ollama, OpenAI, Gemini, BM25. |
| **Native Vector Search** | sqlite-vec (SIMD KNN) or pgvector (ANN/HNSW). Not Python cosine — real database-level acceleration. |
| **MCP Server** | `palaia-mcp` — standalone memory for Claude Desktop, Cursor, any MCP host. No OpenClaw required. |
| **Multi-Backend** | SQLite (default, zero-config) or PostgreSQL + pgvector for distributed teams. |
| **Crash-Safe** | SQLite WAL mode — survives power loss, kills, OOM. |
| **Auto-Capture** | OpenClaw plugin captures significant exchanges automatically. |
| **Structured Types** | memory, process, task — with status, priority, assignee, due date. |
| **Multi-Agent** | Shared store, scopes (private/team/public), agent aliases, per-agent injection priorities. |
| **Smart Tiering** | HOT/WARM/COLD rotation based on decay scores and access patterns. |
| **Embed Server** | Background process holds model in RAM. CLI queries: ~1.5s (was ~3-5s). MCP/Plugin: <500ms. |
| **Zero-Cloud** | Everything local. No API keys needed for core functionality. |

---

## Comparison

| Feature | Palaia | claude-mem | Mem0 | Stock Memory |
|---------|--------|-----------|------|--------------|
| Local-first | Yes | Yes | No (cloud) | Yes |
| Cross-tool (MCP) | Yes (any MCP client) | No (Claude Code only) | No | No |
| Native Vector Search | sqlite-vec / pgvector | ChromaDB (separate) | Cloud | No |
| Structured Types | memory/process/task | decisions/bugfixes | No | No |
| Multi-Agent Scopes | private/team/public | No | Per-user | No |
| Smart Tiering | HOT/WARM/COLD | No | No | No |
| Embedding Providers | 6 (configurable) | 1 (fixed) | Cloud | None |
| Open Source | MIT | AGPL-3.0 | Partial | N/A |
| Crash-safe (WAL) | Yes | Partial | N/A | No |

---

## Documentation

| Document | Description |
|----------|-------------|
| [Getting Started](docs/getting-started.md) | Installation, first steps, quick tour |
| [Storage & Search](docs/backends.md) | SQLite, PostgreSQL, sqlite-vec, pgvector, embedding providers |
| [MCP Server](docs/mcp.md) | Setup for Claude Desktop, Cursor, tool reference, read-only mode |
| [Embed Server](docs/embed-server.md) | Performance optimization, socket transport, daemon mode |
| [Multi-Agent](docs/multi-agent.md) | Scopes, agent identity, team setup, aliases |
| [Configuration](docs/configuration.md) | All config keys, embedding chain, tuning |
| [CLI Reference](docs/cli-reference.md) | All commands with flags and examples |
| [Migration Guide](docs/migration-guide.md) | Import from other systems, flat-file migration |
| [Architecture](ARCHITECTURE.md) | Module map, data flows, design decisions |
| [SKILL.md](palaia/SKILL.md) | Agent-facing documentation (what agents read) |

---

## Development

```bash
git clone https://github.com/iret77/palaia.git
cd palaia
pip install -e ".[dev]"
pytest
```

## Links

- [palaia.ai](https://palaia.ai) — Homepage
- [PyPI](https://pypi.org/project/palaia/) — Package registry
- [ClawHub](https://clawhub.com/skills/palaia) — Install via agent skill
- [OpenClaw](https://openclaw.ai) — The agent platform Palaia is built for
- [CHANGELOG](CHANGELOG.md) — Release history

---

MIT — (c) 2026 [byte5 GmbH](https://byte5.de)
