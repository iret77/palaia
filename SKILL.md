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

1. **Install:**
   ```bash
   pip install git+https://github.com/iret77/palaia.git
   ```

2. **Initialize:**
   ```bash
   palaia init
   ```

3. **Detect available providers:**
   ```bash
   palaia detect
   ```
   Show the user the results. Explain what's available in plain language.

4. **Recommend a chain** based on detect output:
   - OpenAI key + local provider → `openai <local> bm25` ("Best quality with local fallback")
   - Only local provider → `<local> bm25` ("Fully local, no cloud")
   - Only OpenAI key → `openai bm25` (suggest also installing sentence-transformers)
   - Nothing detected → `bm25` (suggest `pip install "palaia[sentence-transformers]"`)

5. **Configure:**
   ```bash
   palaia config set-chain <provider1> [provider2] bm25
   ```

6. **Warm up models:**
   ```bash
   palaia warmup
   ```
   This pre-downloads embedding models so the first search is instant. Always run after chain setup.

7. **Optional — migrate existing memory files:**
   ```bash
   palaia migrate <path> --dry-run   # Preview first
   palaia migrate <path>             # Then import
   ```

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
