# Palaia v2.2 — The Knowledge OS for OpenClaw Agent Teams

**Crash-safe. Local-first. Zero-cloud. The memory system that makes your agents smarter over time.**

[![CI](https://github.com/iret77/palaia/actions/workflows/ci.yml/badge.svg)](https://github.com/iret77/palaia/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/palaia)](https://pypi.org/project/palaia/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![OpenClaw Plugin](https://img.shields.io/badge/OpenClaw-Plugin-blueviolet)](https://openclaw.ai)

---

## Install

### Recommended: Tell your agent

Paste this into your OpenClaw agent:

> Install palaia for me. Set up memory so it works across sessions.

The agent handles everything: `pip install "palaia[fastembed]"`, `palaia init`, plugin setup, and verification.

### Manual / Expert Setup

```bash
pip install "palaia[fastembed]"
palaia init
palaia doctor --fix
```

For the OpenClaw plugin (Auto-Capture + Auto-Recall):
```bash
npm install -g @byte5ai/palaia@latest
```
Then configure `openclaw.json` — see [SKILL.md](palaia/SKILL.md) for details.

For knowledge curation features:
```bash
pip install "palaia[curate]"
```

**Upgrading?** `pip install --upgrade "palaia[fastembed]" && palaia doctor --fix` — migration is automatic.

## Quick Start

```bash
palaia init                                         # Initialize (SQLite store)
palaia write "API rate limit is 100 req/min" \
  --type memory --tags api,limits                   # Save knowledge
palaia query "what's the rate limit"                # Find it by meaning
```

---

## What's New in v2.2

- **SQLite as default backend** — Zero-config, single-file database with WAL mode. Replaces flat JSON files. Existing stores migrate automatically.
- **Injection priorities** — Per-agent/project control over which memories get injected (`palaia priorities`).
- **Knowledge curation** — `palaia curate analyze/apply` for clustering, dedup, and clean migration.
- **ContextEngine integration** — New OpenClaw ContextEngine adapter with 7 lifecycle hooks.
- **Service layer** — Business logic extracted into `palaia/services/` package.
- **Doctor decomposition** — `palaia/doctor/` package with modular checks, fixes, detection.
- **New nudges** — Contextual guidance for curation, priorities, and backend migration.

See [CHANGELOG.md](CHANGELOG.md) for full details.

---

## Why Palaia?

| Feature | Details |
|---------|---------|
| **SQLite-Backed Storage** | Single-file database with WAL mode. Zero dependencies (sqlite3 is stdlib). Optional PostgreSQL for distributed teams. |
| **Semantic Search** | Hybrid BM25 + embeddings. Providers: fastembed, sentence-transformers, OpenAI, Gemini, Ollama |
| **Crash-Safe Writes** | WAL-backed — survives power loss, kills, OOM |
| **Auto-Capture** | OpenClaw plugin captures significant exchanges automatically |
| **Structured Types** | memory, process, task — with status, priority, assignee fields |
| **Multi-Agent** | Shared store, scopes (private/team/public), agent aliases, per-agent priorities |
| **Smart Tiering** | HOT -> WARM -> COLD rotation based on access patterns |
| **Injection Priorities** | Per-agent/project control over what gets injected into context |
| **Knowledge Curation** | Cluster, deduplicate, and clean up accumulated knowledge for migration |
| **Adaptive Nudging** | Teaches agents best practices, graduates when they learn |
| **Zero-Cloud** | Everything runs locally. No API keys required for core functionality |

---

## Architecture

```
palaia/
  backends/        Storage backends (SQLite, PostgreSQL)
  services/        Business logic (write, query, status, admin)
  doctor/          Diagnostics (checks, fixes, detection)
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
palaia status                                         System health
palaia doctor [--fix]                                 Diagnose + fix
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
palaia detect                                         Available providers
palaia warmup                                         Pre-build search index
```

All commands support `--json` for machine-readable output.

---

## Comparison

| Feature | Palaia | Stock Memory | Mem0 | Engram |
|---------|--------|-------------|------|--------|
| Local-first | Yes | Yes | No (cloud) | Yes |
| Crash-safe (WAL) | Yes | No | N/A | No |
| SQLite Backend | Yes (default) | No | No | No |
| Auto-Capture | Yes (plugin) | No | Yes | No |
| Structured Types | Yes (memory/process/task) | No | No | No |
| Multi-Agent Scopes | Yes (private/team/public) | No | Per-user | No |
| Per-Agent Priorities | Yes | No | No | No |
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
