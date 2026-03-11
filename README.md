# Palaia

Persistent, local memory for AI agents — write something today, find it next week.

[![CI](https://github.com/iret77/palaia/actions/workflows/ci.yml/badge.svg)](https://github.com/iret77/palaia/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Getting Started

### Recommended: Let your agent set it up

If you're using [OpenClaw](https://github.com/openclaw), tell your agent:

> "Install the Palaia memory skill from ClawHub"

The agent will install Palaia, check what's available on your system, recommend the best search setup, and configure everything. You just confirm what you want.

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

## What Palaia Does

AI agents forget everything between sessions. Every restart is a blank slate — context from yesterday, decisions from last week, lessons learned an hour ago — all gone. Palaia fixes that.

Palaia gives your agent a local notebook. When something worth remembering comes up — a user preference, a project decision, a configuration detail — the agent writes it down. Next session, it can search for it and find it again. No cloud service, no API keys required, everything stays on your machine.

Search works in two ways: plain keyword matching (always available, zero setup) and semantic search that understands meaning. With semantic search enabled, searching for "deployment address" finds an entry about "server IP" even though the words don't match. You choose which search providers to use based on what's available on your system.

Palaia also manages memory over time. Frequently accessed entries stay in the "hot" tier where they're instantly available. Entries that haven't been touched in a while automatically move to "warm" and eventually "cold" storage. Nothing gets deleted — old memories are still searchable, they just don't clutter the active workspace.

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

All commands support `--json` for machine-readable output.

## OpenClaw Plugin

Palaia can replace OpenClaw's built-in memory system:

```bash
npm install @palaia/openclaw
```

Add it to your OpenClaw config:

```json
{
  "plugins": ["@palaia/openclaw"]
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

## Development

```bash
git clone https://github.com/iret77/palaia.git
cd palaia
pip install -e ".[dev]"
pytest
```

## License

MIT
