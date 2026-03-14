# Palaia

**Your agent forgets everything. Every. Single. Session.**

Yesterday's decisions, last week's server IP, that config you spent 20 minutes debugging — gone. Your agent starts over from scratch, makes the same mistakes, asks the same questions.

Palaia gives your agent a memory that actually works. Local. Private. Instant.

[![CI](https://github.com/iret77/palaia/actions/workflows/ci.yml/badge.svg)](https://github.com/iret77/palaia/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Get Started

Tell your agent:

> "Install or update the Palaia memory skill from ClawHub to the latest version (even if already present). Read the SKILL.md completely and follow it step by step. Run `palaia init`, then `palaia doctor --fix` and resolve all warnings — don't stop until the doctor report is clean. Set up completely."

That's it. Your agent handles everything. You just confirm.

No cloud. No API keys. No database server. Everything stays on your machine.

---

## Why Palaia?

**Because the alternatives suck.**

Cloud memory services need API keys, internet, and trust. Vector databases need infrastructure. Dumping everything into markdown files works until you have 200 of them and can't find anything.

Palaia runs on your machine, survives crashes (WAL-backed), and finds things by meaning — not just keywords. Search for "due date" and it finds "the deadline is March 15th."

| | Palaia | Cloud Memory | Vector DB | Markdown Files |
|---|---|---|---|---|
| Works offline | Yes | No | No | Yes |
| Semantic search | Yes | Sometimes | Yes | No |
| Survives crashes | Yes | Depends | Depends | No |
| Zero infrastructure | Yes | No | No | Yes |
| Finds things by meaning | Yes | Sometimes | Yes | No |
| Auto-organizes over time | Yes | No | No | No |

## Core Concepts

### Write, Search, Find

```bash
# Save something worth remembering
palaia write "Customer prefers CSV exports over PDF" --tags "preferences"

# Find it weeks later
palaia query "what format does the customer want"

# See what's in active memory
palaia list
```

### Projects

Keep memories organized when juggling multiple tasks:

```bash
palaia project create website-redesign --description "Q2 redesign"
palaia project write website-redesign "Homepage must load under 2s"
palaia project query website-redesign "performance targets"
```

### Entry Types

Classify what you store:

```bash
palaia write "Always run migrations before deploy" --type process --tags "deploy"
palaia write "Switch to FastAPI decided 2026-03-01" --type memory --tags "decision,adr"
palaia write "Fix login timeout bug" --type task --status open --priority high
```

### Scopes

Control visibility:

- **`private`** — Only the agent that wrote it
- **`team`** — All agents in the workspace (default)
- **`public`** — Exportable across workspaces

### Smart Tiering

Palaia auto-manages memory over time:
- **HOT** — Frequently accessed, always in search results
- **WARM** — Untouched for ~7 days, still searchable
- **COLD** — Untouched for ~30 days, archived but retrievable

Nothing gets deleted. Old memories fade quietly to the background.

## Semantic Search

Palaia finds things by meaning, not just keywords. Available providers:

| Provider | Type | Best for |
|----------|------|----------|
| `fastembed` | Local | Most systems — lightweight, fast, no GPU needed |
| `sentence-transformers` | Local | GPU systems — heavier but accurate |
| `gemini` | Cloud | Google Gemini API — no local compute needed |
| `openai` | Cloud | When you have an OpenAI API key |
| `ollama` | Local | When you run Ollama already |
| `bm25` | Built-in | Always works — keyword fallback |

```bash
palaia detect                                    # See what's available
palaia config set-chain fastembed bm25           # Set provider priority
palaia warmup                                    # Pre-build search index
```

## Multi-Agent Setup

Multiple agents can share one memory store:

```bash
palaia init                          # Auto-detects agents
palaia write "note" --agent elliot   # Attribute to specific agent
palaia write "secret" --scope private  # Only visible to the writer
```

## Document Ingestion (RAG)

Index external documents alongside agent memory:

```bash
palaia ingest document.pdf --project docs
palaia ingest https://example.com/api.html --project api-docs
palaia query "How does auth work?" --project api-docs --rag
```

## CLI Reference

| Command | What it does |
|---------|-------------|
| `palaia init` | Create a new store |
| `palaia write "text"` | Save a memory |
| `palaia query "search"` | Search by meaning or keywords |
| `palaia get <id>` | Read a specific entry |
| `palaia list` | List entries |
| `palaia edit <id>` | Edit an entry |
| `palaia status` | System health + active providers |
| `palaia detect` | Available embedding providers |
| `palaia warmup` | Pre-build search index |
| `palaia doctor` | Diagnose and fix issues |
| `palaia skill` | Print agent instructions (SKILL.md) |
| `palaia project *` | Manage projects |
| `palaia memo *` | Inter-agent messaging |
| `palaia ingest` | Index documents for RAG |
| `palaia export/import` | Share memories via git |
| `palaia migrate` | Import from other memory systems |

All commands support `--json` for machine-readable output.

## OpenClaw Plugin

Replace OpenClaw's built-in memory with Palaia:

```bash
npm install @byte5ai/palaia
```

Add to your OpenClaw config:
```json
{ "plugins": ["@byte5ai/palaia"] }
```

## Manual Install (without OpenClaw)

```bash
pip install "palaia[fastembed]"    # or: uv tool install "palaia[fastembed]"
palaia init
palaia doctor --fix
palaia warmup                      # pre-builds search index — don't skip this
```

## Development

```bash
git clone https://github.com/iret77/palaia.git
cd palaia
pip install -e ".[dev]"
pytest
```

640+ tests. Contributions welcome.

## Links

- [CHANGELOG](CHANGELOG.md) — What's new in each version
- [ClawHub](https://clawhub.com/skills/palaia) — Install via agent
- [GitHub](https://github.com/iret77/palaia) — Source + Issues
- [OpenClaw](https://openclaw.ai) — The agent platform Palaia is built for

---

MIT — © 2026 [byte5 GmbH](https://byte5.de)
