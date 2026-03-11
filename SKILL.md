# Palaia — Agent Memory Skill

> Local, cloud-free persistent memory for OpenClaw agents.

## Quick Start

```bash
# Initialize (once per workspace)
palaia init

# Write a memory
palaia write "The API endpoint changed to /v2/data" --scope team --tags "api,migration"

# Search memories
palaia query "API endpoint"

# List active memories
palaia list

# System status
palaia status

# Garbage collect (tier rotation)
palaia gc
```

## Agent Usage Patterns

### Writing Memories

Use `palaia write` after learning something worth remembering:

```bash
# Simple write (default scope: team)
palaia write "Christian prefers short responses, no sycophancy"

# With metadata
palaia write "Clawsy uses WebSocket on port 3456" \
  --scope shared:clawsy \
  --agent cyberclaw \
  --tags "clawsy,config" \
  --title "Clawsy WebSocket Port"

# Private memory (only this agent can read)
palaia write "My SSH key is stored at ~/.ssh/id_ed25519" --scope private --agent elliot
```

### Querying Memories

```bash
# Basic search (searches HOT + WARM tiers)
palaia query "websocket port"

# Include archived (COLD) memories
palaia query "old deployment config" --all

# Limit results
palaia query "API" --limit 5
```

### Scope Rules

| Scope | Visible to | Exportable |
|-------|-----------|------------|
| `private` | Only the writing agent | No |
| `team` | All agents in workspace | No |
| `shared:<name>` | Agents in that project | No |
| `public` | All agents | Yes (via git) |

**Default scope is `team`** — visible to all agents, not exported.

### Memory Lifecycle

Memories automatically move between tiers based on access patterns:

- **🔥 HOT** — Active, recently accessed (< 7 days or high score)
- **🌤 WARM** — Occasionally used (7-30 days)
- **❄️ COLD** — Archived (> 30 days, still searchable with `--all`)

Run `palaia gc` periodically to trigger tier rotation.

## When to Use Palaia

**Write when:**
- Learning a new fact about the user or project
- Discovering a configuration detail
- Making an important decision (with rationale)
- Completing a task (for audit trail)

**Query when:**
- Starting a new session (recall context)
- Before making decisions (check past learnings)
- When a topic comes up that might have history

## Installation

```bash
cd /path/to/palaia
pip install -e .
```

Requires Python 3.10+. No external dependencies for core functionality.

## Search Tiers

Palaia auto-detects the best available search:

1. **BM25** (always) — keyword search, zero install
2. **Ollama** (if available) — local embeddings via nomic-embed-text
3. **API** (if key set) — OpenAI/Voyage embeddings

No configuration needed — quality improves automatically.
