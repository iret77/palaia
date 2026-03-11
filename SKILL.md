---
name: palaia
description: >
  Local, crash-safe persistent memory for OpenClaw agents.
  Replaces built-in memory-core with semantic search, projects, and scope-based access control.
metadata:
  openclaw:
    emoji: 📦
    requires:
      bins: ["python3"]
    install:
      - id: pip
        kind: shell
        command: "pip install git+https://github.com/iret77/palaia.git"
        bins: ["palaia"]
        label: "Install Palaia"
---

# Palaia — Agent Memory Skill

## Setup Flow (follow this exactly)

### Step 1: Install and initialize
```bash
pip install git+https://github.com/iret77/palaia.git
palaia init
```

### Step 2: Check for existing memory systems (REQUIRED — do not skip)
```bash
palaia doctor
```

Review **every** warning before continuing. For each finding, ask the user explicitly:

**Memory skill(s) detected (e.g. smart-memory, context-store, recall-pro, …):**
Tell the user: "I found [N] installed memory skill(s): [names]. Palaia replaces these. Should I migrate your existing memories and deactivate the old skill(s)?"
- If yes: run `palaia migrate <workspace-path>` for each, then remove or archive the old skill folder(s)
- If no: continue, but multiple memory systems running in parallel is not recommended

**OpenClaw memory plugin still set to memory-core:**
Tell the user: "Should I switch OpenClaw to use Palaia as the memory system?"
- If yes: update OpenClaw config (`plugins.slots.memory = "palaia"`), restart OpenClaw
- If no: Palaia runs standalone (no `memory_search`/`memory_get` tool integration)

**HEARTBEAT.md legacy patterns:**
Tell the user: "Your heartbeat has old memory commands. Should I update them to use Palaia?"
- If yes: update HEARTBEAT.md, replace `memory_search`/`memory_get`/direct file reads with `palaia query`/`palaia write` equivalents

**Do not proceed to Step 3 until all warnings are addressed or explicitly dismissed by the user.**

### Step 3: Check embedding setup (auto-configured by init)
```bash
palaia detect
```
Review the detected providers and configured chain. `palaia init` automatically detects available providers
and configures the best embedding chain — you usually don't need to change anything.

If the chain looks wrong or you want to change it:
```bash
palaia config set-chain <provider1> [provider2] bm25
```

If only BM25 is shown and you want semantic search:
```bash
pip install sentence-transformers   # fast local option
palaia warmup                       # pre-load model
```

### Step 4: Warm up models
```bash
palaia warmup
```
This pre-downloads embedding models so the first search is instant. Always run after chain setup.

### Step 5: Optional — migrate additional memory files
```bash
palaia migrate <path> --dry-run   # Preview first
palaia migrate <path>             # Then import
```
Note: If smart-memory migration was already handled in Step 2, skip this unless there are other sources to import.

## Commands Reference

### Basic Memory

```bash
# Write a memory entry
palaia write "text" [--scope private|team|public] [--project NAME] [--tags a,b] [--title "Title"]

# Search memories (semantic + keyword)
palaia query "search term" [--project NAME] [--limit N] [--all]

# Read a specific entry by ID
palaia get <id> [--from LINE] [--lines N]

# List entries in a tier
palaia list [--tier hot|warm|cold] [--project NAME]

# System health and active providers
palaia status
```

### Projects

Projects group related entries. They're optional — everything works without them.

```bash
# Create a project
palaia project create <name> [--description "..."] [--default-scope team]

# List all projects
palaia project list

# Show project details + entries
palaia project show <name>

# Write an entry directly to a project
palaia project write <name> "text" [--scope X] [--tags a,b] [--title "Title"]

# Search within a project only
palaia project query <name> "search term" [--limit N]

# Change the project's default scope
palaia project set-scope <name> <scope>

# Delete a project (entries are preserved, just untagged)
palaia project delete <name>
```

### Configuration

```bash
# Show all settings
palaia config list

# Get/set a single value
palaia config set <key> <value>

# Set the embedding fallback chain (ordered by priority)
palaia config set-chain <provider1> [provider2] [...] bm25

# Detect available embedding providers on this system
palaia detect

# Pre-download embedding models
palaia warmup
```

### Diagnostics

```bash
# Check Palaia health and detect legacy systems
palaia doctor

# Show guided fix instructions for each warning
palaia doctor --fix

# Machine-readable output
palaia doctor --json
```

### Maintenance

```bash
# Tier rotation — moves old entries from HOT → WARM → COLD
palaia gc [--aggressive]

# Replay any interrupted writes from the write-ahead log
palaia recover
```

### Sync

```bash
# Export entries for sharing
palaia export [--project NAME] [--output DIR] [--remote GIT_URL]

# Import entries from an export
palaia import <path> [--dry-run]

# Import from other memory formats (smart-memory, flat-file, json-memory, generic-md)
palaia migrate <path> [--dry-run] [--format FORMAT] [--scope SCOPE]
```

### JSON Output

All commands support `--json` for machine-readable output:
```bash
palaia status --json
palaia query "search" --json
palaia project list --json
```

## Scope System

Every entry has a visibility scope:

- **`private`** — Only the agent that wrote it can read it
- **`team`** — All agents in the same workspace can read it (default)
- **`public`** — Can be exported and shared across workspaces

**Setting defaults:**
```bash
# Global default
palaia config set default_scope <scope>

# Per-project default
palaia project set-scope <name> <scope>
```

**Scope cascade** (how Palaia decides the scope for a new entry):
1. Explicit `--scope` flag → always wins
2. Project default scope → if entry belongs to a project
3. Global `default_scope` from config
4. Falls back to `team`

## Projects

- Projects are optional and purely additive — Palaia works fine without them
- Each project has its own default scope
- Writing with `--project NAME` or `palaia project write NAME` both assign to a project
- Deleting a project preserves its entries (they just lose the project tag)
- `palaia project show NAME` lists all entries with their tier and scope

## When to Use What

| Situation | Command |
|-----------|---------|
| Remember a simple fact | `palaia write "..."` |
| Remember something for a specific project | `palaia project write <name> "..."` |
| Find something you stored | `palaia query "..."` |
| Find something within a project | `palaia project query <name> "..."` |
| Check what's in active memory | `palaia list` |
| Check what's in archived memory | `palaia list --tier cold` |
| See system health | `palaia status` |
| Clean up old entries | `palaia gc` |

## Error Handling

| Problem | What to do |
|---------|-----------|
| Embedding provider not available | Chain automatically falls back to next provider. Check `palaia status` to see which is active. |
| Write-ahead log corrupted | Run `palaia recover` — replays any interrupted writes. |
| Entries seem missing | Run `palaia recover`, then `palaia list`. Check all tiers (`--tier warm`, `--tier cold`). |
| Search returns no results | Try `palaia query "..." --all` to include COLD tier. Check `palaia status` to confirm provider is active. |
| `.palaia` directory missing | Run `palaia init` to create a fresh store. |

## Tiering

Palaia organizes entries into three tiers based on access frequency:

- **HOT** (default: 7 days) — Frequently accessed, always searched
- **WARM** (default: 30 days) — Less active, still searched by default
- **COLD** — Archived, only searched with `--all` flag

Run `palaia gc` periodically (or let cron handle it) to rotate entries between tiers. `palaia gc --aggressive` forces more entries to lower tiers.

## Configuration Keys

| Key | Default | Description |
|-----|---------|-------------|
| `default_scope` | `team` | Default visibility for new entries |
| `embedding_chain` | *(auto)* | Ordered list of search providers |
| `embedding_provider` | `auto` | Legacy single-provider setting |
| `embedding_model` | — | Per-provider model overrides |
| `hot_threshold_days` | `7` | Days before HOT → WARM |
| `warm_threshold_days` | `30` | Days before WARM → COLD |
| `hot_max_entries` | `50` | Max entries in HOT tier |
| `decay_lambda` | `0.1` | Decay rate for memory scores |

---

© 2026 byte5 GmbH — MIT License
