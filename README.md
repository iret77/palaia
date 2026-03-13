# Palaia

Persistent, local memory for AI agents — write something today, find it next week.

[![CI](https://github.com/iret77/palaia/actions/workflows/ci.yml/badge.svg)](https://github.com/iret77/palaia/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Released March 2026](https://img.shields.io/badge/released-March%202026-brightgreen.svg)]()

## What's New in 1.7.0

- **Entry Classes** — Classify entries as `memory`, `process`, or `task` with `--type`.
- **Structured Task Fields** — `--status`, `--priority`, `--assignee`, `--due-date` for task entries.
- **`palaia edit`** — Edit existing entries (content, tags, metadata). WAL-backed, scope-enforced.
- **Session Identities** — `--instance` field to distinguish different sessions of the same agent.
- **Structured Filters** — `palaia query --type task --status open --priority high`. Exact match, not embeddings.
- **Agent Nudging** — CLI hints for undiscovered features. `palaia status` shows class breakdown.
- **`palaia migrate --suggest`** — Get type recommendations for untyped entries.
- **Doctor entry class check** — Detects untyped entries and suggests migration.

See [CHANGELOG.md](CHANGELOG.md) for full details.

## Installation

### For OpenClaw users (recommended)

Tell your agent:

> "Install or update the Palaia memory skill from ClawHub to the latest version (even if already present). Read the SKILL.md completely and follow it step by step. Run `palaia init --agent YOUR_NAME`, then `palaia doctor --fix` and resolve all warnings — don't stop until the doctor report is clean. Set up completely."

This prompt works for both first-time installations and updates. Your agent will handle installation, configuration, and onboarding automatically.

### Manual install
```bash
pip install "palaia[fastembed]"
palaia init
palaia doctor --fix
```

### After updating
```bash
pip install --upgrade "palaia[fastembed]"
palaia doctor --fix
```
Your agent can also do this — just say: **"Update Palaia"**

## What Palaia Does

AI agents forget everything between sessions. Every restart is a blank slate — context from yesterday, decisions from last week, lessons learned an hour ago — all gone. Palaia fixes that.

Palaia gives your agent a local notebook. When something worth remembering comes up — a user preference, a project decision, a configuration detail — the agent writes it down. Next session, it can search for it and find it again. No cloud service, no API keys required, everything stays on your machine.

Palaia is built for [OpenClaw](https://openclaw.ai) agents but works with any Python-based agent framework via CLI or Python API.

Search works in two ways: plain keyword matching (always available, zero setup) and semantic search that understands meaning. With semantic search enabled, searching for "deployment address" finds an entry about "server IP" even though the words don't match. You choose which search providers to use based on what's available on your system.

Palaia also manages memory over time. Frequently accessed entries stay in the "hot" tier where they're instantly available. Entries that haven't been touched in a while automatically move to "warm" and eventually "cold" storage. Nothing gets deleted — old memories are still searchable, they just don't clutter the active workspace.

## Why Palaia?

Most memory solutions for AI agents depend on cloud APIs, external databases, or complex infrastructure.
Palaia is different:

| | Palaia | Cloud Memory | Vector DB |
|---|---|---|---|
| Runs offline | ✅ | ❌ | ❌ |
| No external API required | ✅ | ❌ | Depends |
| Survives crashes (WAL) | ✅ | Depends | Depends |
| Automatic forgetting (decay) | ✅ | ❌ | ❌ |
| Built for agents | ✅ | Sometimes | ❌ |
| Open source | ✅ | Sometimes | ✅ |

Palaia works on any machine, any network, with zero infrastructure.
Your agent's memory stays local — private by default, shareable when you choose.

## Getting Started

### Recommended: Let your agent set it up

If you're using [OpenClaw](https://openclaw.ai), tell your agent:

> "Install or update the Palaia memory skill from ClawHub to the latest version (even if already present). Read the SKILL.md completely and follow it step by step. Run `palaia init --agent YOUR_NAME`, then `palaia doctor --fix` and resolve all warnings — don't stop until the doctor report is clean. Set up completely."

This prompt works for both first-time installations and updates. The agent will install Palaia, check what's available on your system, recommend the best search setup, and configure everything. You just confirm what you want.

### Manual installation

```bash
pip install git+https://github.com/iret77/palaia.git
palaia init
palaia detect
palaia config set-chain sentence-transformers bm25
palaia warmup
```

That's it. Write your first memory:

```bash
palaia write "The deploy server is at 10.0.1.5" --tags "infra,servers"
palaia query "where is the server"
```

> **⚠️ Important:** Palaia supplements your existing files — it does not replace them.
> Files like `CONTEXT.md`, `SOUL.md`, and `MEMORY.md` are living documents read by agents
> at runtime. `palaia ingest` and `palaia migrate` create searchable copies, but the
> originals must stay on disk. See [Migration Guide](docs/migration-guide.md) for details.

## Features

### Memory Entries

The basics: write, search, and list memories.

```bash
# Save something
palaia write "Christian prefers dark mode" --tags "preferences"

# Find it later
palaia query "what does Christian like"

# See what's in active memory
palaia list

# Read a specific entry
palaia get abc123
```

Every entry can have tags for organization and a scope that controls who can see it (more on scopes below).

### Projects

When you're working on multiple things, projects let you keep memories organized and separate. A "website-redesign" project won't pollute search results when you're looking for "server setup" notes.

Projects are optional — you can use Palaia without them. They're useful when:
- An agent works on several distinct tasks
- You want different visibility defaults per topic (e.g., infra notes are team-visible, personal preferences are private)
- You need to export or clean up memories for one area without touching others

```bash
# Create a project
palaia project create website-redesign --description "Q2 redesign" --default-scope team

# Write to it
palaia project write website-redesign "Homepage needs to load under 2s"

# Search within it
palaia project query website-redesign "performance targets"

# See project details and entries
palaia project show website-redesign

# List all projects
palaia project list

# Change who can see project entries by default
palaia project set-scope website-redesign private

# Remove a project (entries are preserved, just untagged)
palaia project delete website-redesign
```

**Scope cascade:** When writing an entry, Palaia decides its visibility in this order:
1. Explicit `--scope` flag (always wins)
2. The project's default scope (if the entry belongs to a project)
3. The global default scope from your config
4. Falls back to `team`

### Document Knowledge Base

Palaia can also index external documents — PDFs, websites, text files — and search them alongside your agent memory.

```bash
# Ingest a file
palaia ingest document.pdf --project company-docs

# Ingest a URL
palaia ingest https://example.com/docs/api.html --project api-docs

# Ingest a directory
palaia ingest ./docs/ --project my-project --tags documentation

# Preview without storing
palaia ingest document.pdf --dry-run

# Adjust chunk size
palaia ingest document.pdf --chunk-size 300 --chunk-overlap 30

# Search ingested documents
palaia query "How does X work?" --project api-docs

# Get RAG-formatted output for LLM injection
palaia query "How does X work?" --project api-docs --rag
```

Documents are chunked, embedded, and stored as regular Palaia entries. They appear in search results with source attribution (file, page, URL). Use `--rag` for a formatted context block ready for LLM injection.

**Note:** `ingest` creates a copy in the Palaia store. Source files are NOT modified or deleted.

PDF support requires an optional dependency: `pip install 'palaia[pdf]'`

### Semantic Search

Regular text search matches exact words. Semantic search understands meaning — it converts text into numerical representations (embeddings) and finds entries that are conceptually similar, even when the words differ.

For example, if you stored "The deadline is March 15th", a semantic search for "due date" would find it. Keyword search wouldn't.

**Available providers:**

| Provider | Type | What you need |
|----------|------|---------------|
| `openai` | Cloud | API key + internet |
| `sentence-transformers` | Local | `pip install "palaia[sentence-transformers]"` (~500MB) |
| `ollama` | Local | Ollama server + `nomic-embed-text` model |
| `fastembed` | Local | `pip install "palaia[fastembed]"` (lightweight) |
| `bm25` | Built-in | Nothing — keyword matching, always works |

**Detection and setup:**

```bash
# See what's available on your system
palaia detect

# Set up a fallback chain — tries providers in order
palaia config set-chain openai sentence-transformers bm25

# Pre-download models so the first search is instant
palaia warmup
```

**Fallback chain:** You configure a list of providers in priority order. Palaia uses the first one that works. If it fails (server down, rate limit, missing key), the next one takes over automatically. Keyword search (`bm25`) is always available as a last resort, so search never breaks completely.

### Scopes

Scopes control who can see a memory entry:

- **`private`** — Only the agent that wrote it
- **`team`** — All agents in the same workspace (this is the default)
- **`public`** — Can be exported and shared with other workspaces

```bash
# Write with a specific scope
palaia write "my secret notes" --scope private
palaia write "team knows this" --scope team

# Change the global default scope
palaia config set default_scope private

# Set a per-project default
palaia project set-scope my-project private
```

### Tiering (HOT / WARM / COLD)

Palaia automatically manages memory over time using three tiers:

- **HOT** — Entries you access frequently. Fast, always in active search results.
- **WARM** — Entries untouched for about a week. Still searched by default.
- **COLD** — Entries untouched for about a month. Archived but still searchable with `--all`.

Each entry has a decay score based on how recently and how often it's been accessed. Over time, scores decrease and entries move to lower tiers. Nothing is ever deleted.

Run garbage collection to trigger tier rotation:

```bash
palaia gc              # Normal rotation
palaia gc --aggressive # Force more entries to lower tiers
```

### Multi-Agent Setup

When multiple agents share a workspace, Palaia can either use a shared store (default) or isolated stores per agent.

**Shared store (default):**
All agents read and write to the same `.palaia` directory. Entries with `team` scope are visible to every agent. This is the recommended setup for collaborative agent teams.

```bash
palaia init            # Auto-detects agents, uses shared store
```

If multiple agents are detected, `palaia init` shows:
```
🤖 Found 3 agents: cyberclaw, elliot, carrie
   Using shared store at .palaia
   All agents will see team-scoped entries.
```

**Isolated stores:**
Each agent gets its own `.palaia` directory. Use this when agents work on unrelated tasks and shouldn't see each other's memories.

```bash
palaia init --isolated
```

**Scope tags for multi-agent setups:**

| Scope | Visibility | Use case |
|-------|-----------|----------|
| `private` | Only the writing agent | Personal notes, drafts |
| `team` | All agents in the workspace | Shared knowledge (default) |
| `public` | Exportable across workspaces | Documentation, references |

**Best practice:** Use the `--agent` flag when writing entries so they are attributed to the writing agent:

```bash
palaia write "deploy key rotated" --agent elliot --scope team
```

This makes it easy to trace who stored what, especially in shared stores.

### Migration

If you're coming from OpenClaw's built-in smart-memory or other systems, Palaia can import your existing data:

```bash
palaia migrate . --dry-run   # Preview what would be imported
palaia migrate .             # Import everything
```

Supported formats: `smart-memory`, `flat-file`, `json-memory`, `generic-md`. Palaia auto-detects the format, or you can specify it with `--format`.

### Git Sync

Export and import memories for sharing between workspaces or backing up:

```bash
# Export public entries
palaia export --output ./shared-memories
palaia export --remote git@github.com:team/shared-memory.git

# Export just one project
palaia export --project website-redesign

# Import from another workspace
palaia import ./shared-memories
palaia import https://github.com/team/shared-memory.git
```

## CLI Reference

| Command | What it does |
|---------|-------------|
| `palaia init` | Create a new `.palaia` directory |
| `palaia write "text"` | Save a memory entry |
| `palaia query "search"` | Search memories by meaning or keywords |
| `palaia get <id>` | Read a specific entry |
| `palaia list` | List entries (default: hot tier) |
| `palaia status` | Show system health and active providers |
| `palaia detect` | Show available embedding providers |
| `palaia warmup` | Pre-download embedding models |
| `palaia gc` | Run tier rotation and cleanup |
| `palaia recover` | Replay interrupted writes from the log |
| `palaia config list` | Show all settings |
| `palaia config set <key> <value>` | Change a setting |
| `palaia config set-chain <providers...>` | Set the embedding fallback chain |
| `palaia project create <name>` | Create a project |
| `palaia project list` | List all projects |
| `palaia project show <name>` | Show project details and entries |
| `palaia project write <name> "text"` | Write an entry to a project |
| `palaia project query <name> "search"` | Search within a project |
| `palaia project set-scope <name> <scope>` | Change a project's default scope |
| `palaia project delete <name>` | Delete a project (entries preserved) |
| `palaia export` | Export entries for sharing |
| `palaia import <path>` | Import entries from an export |
| `palaia migrate <path>` | Import from other memory formats |
| `palaia ingest <path>` | Ingest documents for RAG search |
| `palaia doctor` | Check and fix legacy data issues |

All commands support `--json` for machine-readable output.

## OpenClaw Plugin

Palaia can replace OpenClaw's built-in memory system:

```bash
npm install @byte5ai/palaia
```

Add it to your OpenClaw config:

```json
{
  "plugins": ["@byte5ai/palaia"]
}
```

Memory operations are then automatically routed through Palaia.

## Configuration

Settings live in `.palaia/config.json`. Manage them with the `config` command:

```bash
palaia config list                 # Show all settings
palaia config set <key> <value>    # Change a setting
palaia config set-chain <providers...>  # Set embedding fallback chain
```

**Available settings:**

| Setting | Default | Description |
|---------|---------|-------------|
| `default_scope` | `team` | Default visibility for new entries |
| `embedding_chain` | *(auto-detected)* | Ordered list of search providers to try |
| `embedding_provider` | `auto` | Legacy single-provider setting |
| `embedding_model` | — | Per-provider model overrides |
| `hot_threshold_days` | `7` | Days before an entry moves from HOT to WARM |
| `warm_threshold_days` | `30` | Days before an entry moves from WARM to COLD |
| `hot_max_entries` | `50` | Maximum entries in the HOT tier |
| `decay_lambda` | `0.1` | How fast memory scores decrease over time |

## Roadmap

**Released (v1.1.1)**
- [x] WAL-backed crash-safe storage
- [x] HOT/WARM/COLD tiering with automatic decay
- [x] Multi-provider semantic search (OpenAI, sentence-transformers, fastembed, ollama)
- [x] Configurable fallback chain
- [x] Projects with per-project scope
- [x] `palaia doctor` for legacy cleanup
- [x] Document ingestion (RAG) — `palaia ingest`
- [x] Native OpenClaw plugin (`@byte5ai/palaia`)
- [x] Git-based knowledge sync (`palaia export/import`)

**Planned**
- [ ] Memory compression for COLD tier
- [ ] Embedding cache (avoid re-computing unchanged entries)
- [ ] palaia.ai documentation site
- [ ] ClawHub skill registry integration (auto-update)
- [ ] Multi-agent shared memory via git sync

## Links

- [ClawHub](https://clawhub.com/skills/palaia) — Install via agent
- [GitHub](https://github.com/iret77/palaia) — Source + Issues
- [OpenClaw](https://openclaw.ai) — The agent platform Palaia is built for

If you find Palaia useful, a ⭐ on GitHub goes a long way.

## Multi-Agent Setup

If you run multiple agents that should share the same memory store, use the setup command:

```bash
# Preview what would happen
palaia setup --multi-agent ~/.openclaw/agents/ --dry-run

# Create .palaia symlinks for all agent directories
palaia setup --multi-agent ~/.openclaw/agents/
```

This scans the agents directory for subdirectories and creates `.palaia` symlinks pointing to your current store. All agents then share the same memory while maintaining their own identity via the `--agent` flag on writes.

## Migration Guide

Moving from another memory system? See [`docs/migration-guide.md`](docs/migration-guide.md) for a step-by-step guide covering inventory, bulk import, verification, and cleanup.

## Development

```bash
git clone https://github.com/iret77/palaia.git
cd palaia
pip install -e ".[dev]"
pytest
```

## License

MIT

© 2026 [byte5 GmbH](https://byte5.de) — MIT License
