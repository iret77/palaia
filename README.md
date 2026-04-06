```
             .__         .__
___________  |  | _____  |__|____
\____ \__  \ |  | \__  \ |  \__  \
|  |_> > __ \|  |__/ __ \|  |/ __ \_
|   __(____  /____(____  /__(____  /
|__|       \/          \/        \/
```

# The Knowledge System for AI Agent Teams

**Your agents forget. palaia doesn't.**

[![CI](https://github.com/byte5ai/palaia/actions/workflows/ci.yml/badge.svg)](https://github.com/byte5ai/palaia/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/palaia)](https://pypi.org/project/palaia/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![OpenClaw Plugin](https://img.shields.io/badge/OpenClaw-Plugin-blueviolet)](https://openclaw.ai)

---

## What palaia Does

AI agents are stateless by default. Every session starts from scratch — no memory of past decisions, no shared knowledge between agents, no context that survives a restart.

palaia gives your agents a persistent, searchable knowledge store. They save what they learn. They find it again by meaning, not keyword. They share it across tools and sessions — automatically.

---

## What palaia Is Not

- Not a chatbot or prompt manager
- Not a cloud service (everything runs locally)
- Not a vector database you manage yourself (it manages itself)
- Not limited to one tool — works with OpenClaw, Claude Desktop, Cursor, and any MCP client

---

## What You Get

| Capability | What it means |
|------------|---------------|
| **Agents remember across sessions** | Knowledge survives restarts, tool switches, and team handoffs |
| **Find anything by meaning** | Hybrid BM25 + vector search across 6 embedding providers |
| **Zero-config local setup** | SQLite with native SIMD vector search — no separate database process |
| **Works everywhere via MCP** | One memory store for OpenClaw, Claude Desktop, Cursor, and more |
| **Multi-agent ready** | Private, team, and public scopes — agents see what they should |
| **Agent isolation** | `--isolated` mode for strict per-agent memory boundaries |
| **Crash-safe by default** | SQLite WAL mode survives power loss, kills, OOM |
| **Fast** | Embed server keeps model in RAM — CLI queries ~1.5s, MCP/Plugin <500ms |
| **WebUI memory explorer** | `palaia ui` — browse, search, create entries in the browser. Localhost only. |
| **Scales when needed** | Swap to PostgreSQL + pgvector for distributed teams, no code changes |

---

## Comparison

| Feature | palaia | claude-mem | Mem0 | Stock Memory |
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

## Install

### Recommended: Tell your agent

Paste this into your OpenClaw agent (works for install AND update):

> Install or update the palaia memory skill from ClawHub to the latest version (even if already present). Read the SKILL.md completely and follow it step by step. Run palaia init, then palaia doctor --fix and resolve all warnings — don't stop until the doctor report is clean. Set up completely.

The agent handles everything: ClawHub skill install, pip setup, plugin config, and verification.

### Manual Setup

```bash
pip install "palaia[fastembed]"
palaia init
openclaw plugins install @byte5ai/palaia
palaia doctor --fix
```

Then activate the memory slot in your OpenClaw config:
```json5
// openclaw.json
{
  plugins: {
    slots: { memory: "palaia" }
  }
}
```

Restart the gateway: `openclaw gateway restart`

Optional extras:
```bash
pip install "palaia[mcp]"          # MCP server for Claude Desktop, Cursor
pip install "palaia[curate]"       # Knowledge curation
pip install "palaia[postgres]"     # PostgreSQL + pgvector backend
```

Note: `palaia[fastembed]` already includes sqlite-vec for native vector search and the embed-server auto-starts on first query. No manual optimization needed.

**Upgrading?** `palaia upgrade` — auto-detects install method, preserves extras, runs doctor.

### Claude Code

Paste this into Claude Code:

> Install palaia for persistent memory in this Claude Code environment.
> Run: `pip install "palaia[mcp,fastembed]" && palaia init && palaia setup claude-code --global`
> Then tell me to restart Claude Code so the MCP tools become active.
> After restart, read the CLAUDE.md and follow its instructions.

See [Claude Code Integration](docs/claude-code.md) for the full guide.

### MCP Setup (Claude Desktop, Cursor — no OpenClaw needed)

```bash
pip install "palaia[mcp,fastembed]"
palaia init
```

Add to your MCP config:
- Claude Desktop: `~/.config/claude/claude_desktop_config.json`
- Cursor: `.cursor/mcp.json`
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

## Documentation

| Document | Description |
|----------|-------------|
| [Getting Started](docs/getting-started.md) | Installation, first steps, quick tour |
| [Storage & Search](docs/backends.md) | SQLite, PostgreSQL, sqlite-vec, pgvector, embedding providers |
| [Claude Code](docs/claude-code.md) | Claude Code integration, setup command, paste-this prompt |
| [MCP Server](docs/mcp.md) | Setup for Claude Desktop, Cursor, tool reference, read-only mode |
| [Embed Server](docs/embed-server.md) | Performance optimization, socket transport, daemon mode |
| [Multi-Agent](docs/multi-agent.md) | Scopes, agent identity, team setup, aliases |
| [Configuration](docs/configuration.md) | All config keys, embedding chain, tuning |
| [CLI Reference](docs/cli-reference.md) | All commands with flags and examples |
| [Migration Guide](docs/migration-guide.md) | Import from other systems, flat-file migration |
| [Architecture](ARCHITECTURE.md) | Module map, data flows, design decisions |
| [SKILL.md](palaia/SKILL.md) | Agent-facing documentation (what agents read) |
| [Contributing](CONTRIBUTING.md) | Versioning, release process, development setup |
| [Changelog](CHANGELOG.md) | Release history |

---

## Development

```bash
git clone https://github.com/byte5ai/palaia.git
cd palaia
pip install -e ".[dev]"
pytest
```

## Links

- [palaia.ai](https://palaia.ai) — Homepage
- [PyPI](https://pypi.org/project/palaia/) — Package registry
- [ClawHub](https://clawhub.com/skills/palaia) — Install via agent skill
- [OpenClaw](https://openclaw.ai) — The agent platform palaia is built for
- [CHANGELOG](CHANGELOG.md) — Release history

---

MIT — (c) 2026 [byte5 GmbH](https://byte5.de)
