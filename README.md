# 🧠 Palaia

[![CI](https://github.com/iret77/palaia/actions/workflows/ci.yml/badge.svg)](https://github.com/iret77/palaia/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Memory for AI agents that actually sticks.**

Palaia gives your agent a persistent, local notebook. Write something today, find it next week. No cloud, no API keys, no setup beyond `pip install`.

## Why Palaia?

AI agents forget everything between sessions. Palaia fixes that:

- **Write once, remember forever** — Notes survive restarts, crashes, and updates
- **Find by meaning, not just keywords** — Semantic search understands what you meant (optional, works with ollama, sentence-transformers, or OpenAI)
- **Smart organization** — Palaia remembers what's important right now and quietly moves old, unused notes to the archive so they don't slow things down. They're still there when you need them.
- **Crash-safe** — Every write goes through a write-ahead log. If your machine dies mid-write, nothing is lost.
- **Private by default** — Everything stays on your machine. You choose what to share.

## Getting Started

### Recommended: Let your agent set it up

Tell your OpenClaw agent:

> "Install the Palaia memory skill from ClawHub"

Your agent will:
1. Install the skill (`clawhub install palaia`)
2. Run `palaia detect` to analyze your system
3. Recommend the best embedding setup for your hardware
4. Ask you which option you prefer
5. Configure everything automatically

This is the recommended path — your agent handles installation, configuration,
and picks the right embedding provider for your system.

### Manual installation

If you prefer to set things up yourself:

```bash
pip install palaia                 # or: pip install git+https://github.com/iret77/palaia.git
palaia init                        # create .palaia/ directory
palaia detect                      # see what's available on your system
palaia config set-chain sentence-transformers bm25  # configure embedding chain
palaia warmup                      # pre-download models for instant first search
```

That's it — write your first memory:

```bash
palaia write "The deploy server is at 10.0.1.5" --tags "infra,servers"
palaia query "where is the server"
```

## How It Works

Palaia organizes memories into three tiers, like a desk:

- 🔥 **Hot** — Things you use all the time. Right in front of you.
- 🌤 **Warm** — Things you used recently. In the drawer.
- ❄️ **Cold** — Old stuff. In the filing cabinet. Still searchable.

Memories automatically move between tiers based on how often you access them. No manual cleanup needed — just run `palaia gc` occasionally (or let your agent do it).

## Search Options

**Keyword search** works out of the box — zero setup, zero dependencies.

For smarter search that understands meaning (finding "due date" when you stored "deadline"):

```bash
# See what's available on your machine
palaia detect

# Option A: Local AI server (recommended)
ollama pull nomic-embed-text
palaia config set embedding_provider ollama

# Option B: Pure Python (no server needed)
pip install "palaia[sentence-transformers]"
palaia config set embedding_provider sentence-transformers

# Option C: Cloud (needs API key)
export OPENAI_API_KEY="sk-..."
palaia config set embedding_provider openai
```

When semantic search is active, Palaia combines keyword matching with meaning-based search for the best results.

## Sharing Between Agents

Control who sees what with scope tags:

```bash
palaia write "my secret" --scope private       # Only this agent
palaia write "team info" --scope team           # All agents in workspace
palaia write "public docs" --scope public       # Can be exported
palaia export --remote git@github.com:team/shared-memory.git
```

## OpenClaw Integration

Palaia is a drop-in replacement for OpenClaw's built-in memory:

```bash
npm install @palaia/openclaw
```

Add `"@palaia/openclaw"` to your plugins list and you're done.

## CLI Reference

| Command | Description |
|---------|-------------|
| `palaia init` | Set up a new memory store |
| `palaia write "text"` | Save a memory |
| `palaia query "search"` | Find memories |
| `palaia get <id>` | Read a specific memory |
| `palaia list` | List memories in a tier |
| `palaia status` | Check system health |
| `palaia gc` | Clean up and rotate tiers |
| `palaia detect` | Show available embedding providers |
| `palaia warmup` | Pre-download embedding models for instant first search |
| `palaia config set <k> <v>` | Change a setting |
| `palaia export` | Export public memories |
| `palaia import <path>` | Import shared memories |
| `palaia migrate <path>` | Import from other memory formats |
| `palaia recover` | Replay any interrupted writes |

## Migrating from smart-memory

```bash
palaia migrate . --dry-run   # Preview first
palaia migrate .             # Import everything
```

## Configuration

Settings live in `.palaia/config.json`. Change them with `palaia config set`:

```bash
palaia config set embedding_provider sentence-transformers
palaia config set hot_threshold_days 14
palaia config list
```

## Development

```bash
git clone https://github.com/iret77/palaia.git
cd palaia
pip install -e ".[dev]"
pytest
```

## License

MIT — do what you want with it.
