# CLI Reference

All commands support `--json` for machine-readable output and `-v` / `--verbose` for debug logging.

## Quick Reference

```
palaia init [--agent NAME]                           Initialize store
palaia write "text" [--type TYPE] [--tags a,b]       Save knowledge
palaia query "search" [--type TYPE] [--project P]    Search by meaning
palaia get <id> [--from N] [--lines N]               Read entry
palaia list [--tier T] [--type T] [--status S]       List entries
palaia edit <id> [--status done] [--title T]         Edit entry
palaia status                                         System health
palaia doctor [--fix]                                 Diagnose + fix
palaia upgrade                                        Update palaia
palaia project create|list|show|write|query|...      Projects
palaia memo send|inbox|ack|broadcast|gc              Messaging
palaia priorities [block|unblock|set|list-blocked]   Injection control
palaia curate analyze|apply                           Knowledge curation
palaia gc [--aggressive] [--budget]                  Garbage collection
palaia config list|get|set|set-chain|set-alias|...   Configuration
palaia detect                                         Provider detection
palaia warmup                                         Pre-build index
palaia embed-server [--socket] [--daemon]             Embedding server
palaia mcp-server [--read-only]                       MCP server
palaia ingest <source> [--project P]                  Document indexing
palaia sync export|import                             Git-based exchange
palaia package export|import|info                     Portable packages
palaia process list|run                               Process tracking
palaia lock|unlock                                    Project locks
palaia instance set|get|clear                         Session identity
palaia migrate [--format F]                           Import from other systems
palaia skill                                          Print SKILL.md
```

---

## Core Commands

### `palaia init`

Initialize a `.palaia` store.

| Flag | Default | Description |
|------|---------|-------------|
| `--agent` | auto-detect | Agent name |
| `--path` | `.` | Target directory |
| `--isolated` | — | Use isolated stores per agent |
| `--reset` | — | Reset config to defaults (preserves entries) |
| `--capture-level` | — | Auto-capture level: `off`, `minimal`, `normal`, `aggressive` |

### `palaia write`

Save structured knowledge.

| Arg/Flag | Default | Description |
|----------|---------|-------------|
| `text` | (required) | Memory content |
| `--type` | `memory` | Type: `memory`, `process`, `task` |
| `--scope` | `team` | Scope: `private`, `team`, `public` |
| `--tags` | — | Comma-separated tags |
| `--title` | auto-extract | Short title |
| `--project` | — | Project name |
| `--agent` | — | Agent name |
| `--status` | — | Task: `open`, `in-progress`, `done`, `wontfix` |
| `--priority` | — | Task: `critical`, `high`, `medium`, `low` |
| `--assignee` | — | Task assignee |
| `--due-date` | — | Task due date (ISO-8601) |
| `--instance` | — | Session identity |

### `palaia query`

Search using hybrid BM25 + semantic ranking.

| Arg/Flag | Default | Description |
|----------|---------|-------------|
| `query` | (required) | Search text |
| `--limit` | `10` | Max results |
| `--all` | — | Include COLD tier |
| `--type` | — | Filter: `memory`, `process`, `task` |
| `--project` | — | Filter by project |
| `--status` | — | Filter: `open`, `in-progress`, `done`, `wontfix` |
| `--priority` | — | Filter: `critical`, `high`, `medium`, `low` |
| `--assignee` | — | Filter by assignee |
| `--instance` | — | Filter by session |
| `--before` | — | Created before (ISO timestamp) |
| `--after` | — | Created after (ISO timestamp) |
| `--cross-project` | — | Search all projects |
| `--rag` | — | Output as RAG context block |
| `--agent` | — | Agent for scope filtering |

### `palaia get`

Read a specific entry.

| Arg/Flag | Default | Description |
|----------|---------|-------------|
| `path` | (required) | Entry UUID or short prefix |
| `--from` | — | Start at line number (1-indexed) |
| `--lines` | — | Number of lines to return |
| `--agent` | — | Agent for scope filtering |

### `palaia list`

List entries in a tier.

| Flag | Default | Description |
|------|---------|-------------|
| `--tier` | `hot` | Tier: `hot`, `warm`, `cold` |
| `--all` | — | All tiers |
| `--type` | — | Filter by type |
| `--project` | — | Filter by project |
| `--tag` | — | Filter by tag (repeatable, AND logic) |
| `--scope` | — | Filter by scope |
| `--agent` | — | Filter by agent |
| `--status` | — | Filter by status |
| `--priority` | — | Filter by priority |
| `--assignee` | — | Filter by assignee |
| `--instance` | — | Filter by session |
| `--before` | — | Created before (ISO) |
| `--after` | — | Created after (ISO) |
| `--cross-project` | — | List across all projects |

### `palaia edit`

Edit an existing entry.

| Arg/Flag | Default | Description |
|----------|---------|-------------|
| `entry_id` | (required) | Entry UUID or short prefix |
| `text` | — | New content |
| `--tags` | — | New tags (replaces) |
| `--title` | — | New title |
| `--type` | — | Change type |
| `--status` | — | Set status |
| `--priority` | — | Set priority |
| `--assignee` | — | Set assignee |
| `--due-date` | — | Set due date |
| `--agent` | — | Agent for scope enforcement |

---

## System Commands

### `palaia status`

Show system health, entry counts, backend type, vector search method, embed-server status, and upgrade command.

### `palaia doctor`

| Flag | Default | Description |
|------|---------|-------------|
| `--fix` | — | Show guided fix instructions |

### `palaia upgrade`

Update palaia to latest version. Auto-detects install method, preserves extras, runs doctor, upgrades OpenClaw plugin.

### `palaia detect`

Show available embedding providers, embed-server status, and sqlite-vec availability.

### `palaia warmup`

Pre-compute embeddings for all entries. Run after provider changes.

---

## Project Management

### `palaia project create`

| Arg/Flag | Description |
|----------|-------------|
| `name` | Project name |
| `--description` | Project description |
| `--default-scope` | Default scope for entries |
| `--owner` | Project owner |

### `palaia project list`

| Flag | Description |
|------|-------------|
| `--owner` | Filter by owner |

### `palaia project show <name>`

### `palaia project write`

| Arg/Flag | Description |
|----------|-------------|
| `name` | Project name |
| `text` | Memory content |
| `--scope`, `--agent`, `--tags`, `--title` | Same as `palaia write` |

### `palaia project query`

| Arg/Flag | Description |
|----------|-------------|
| `name` | Project name |
| `query` | Search text |
| `--limit` | Max results (default: 10) |

### `palaia project set-scope <name> <scope>`

### `palaia project set-owner <name> [owner]`

| Flag | Description |
|------|-------------|
| `--clear` | Remove owner |

### `palaia project delete <name>`

---

## Messaging

### `palaia memo send`

| Arg/Flag | Default | Description |
|----------|---------|-------------|
| `to` | (required) | Recipient agent |
| `message` | (required) | Message body |
| `--priority` | `normal` | `normal` or `high` |
| `--ttl-hours` | `72` | TTL in hours |
| `--agent` | — | Sender agent |

### `palaia memo broadcast`

| Arg/Flag | Default | Description |
|----------|---------|-------------|
| `message` | (required) | Message body |
| `--priority` | `normal` | `normal` or `high` |
| `--ttl-hours` | `72` | TTL in hours |
| `--agent` | — | Sender agent |

### `palaia memo inbox`

| Flag | Description |
|------|-------------|
| `--all` | Include read memos |
| `--agent` | Agent name |

### `palaia memo ack`

| Arg/Flag | Description |
|----------|-------------|
| `memo_id` | Memo ID (or `--all`) |
| `--all` | Acknowledge all unread |
| `--agent` | Agent name |

### `palaia memo gc`

Clean up expired memos.

---

## Injection Priorities

### `palaia priorities`

Simulate injection for a query.

| Arg/Flag | Default | Description |
|----------|---------|-------------|
| `query` | — | Query to simulate |
| `--agent` | — | Agent name |
| `--project` | — | Project name |
| `--limit` | `10` | Max entries |
| `--all` | — | Include cold tier |

### `palaia priorities block <entry_id>`

| Flag | Description |
|------|-------------|
| `--agent` | Block only for this agent |
| `--project` | Block only for this project |

### `palaia priorities unblock <entry_id>`

Same flags as `block`.

### `palaia priorities set <key> <value>`

| Flag | Description |
|------|-------------|
| `--agent` | Set for this agent only |
| `--project` | Set for this project only |

Keys: `recallMinScore`, `maxInjectedChars`, `tier`, `typeWeight.process`, etc.

### `palaia priorities list-blocked`

| Flag | Description |
|------|-------------|
| `--agent` | Agent scope |
| `--project` | Project scope |

### `palaia priorities reset`

| Flag | Description |
|------|-------------|
| `--agent` | Reset this agent's overrides |
| `--project` | Reset this project's overrides |

---

## Knowledge Management

### `palaia gc`

| Flag | Description |
|------|-------------|
| `--dry-run` | Preview without changes |
| `--budget` | Enforce `max_entries_per_tier` and `max_total_chars` limits |

### `palaia curate analyze`

| Flag | Description |
|------|-------------|
| `--project` | Filter by project |
| `--agent` | Filter by agent |
| `--output` | Output report path |

### `palaia curate apply <report>`

| Flag | Description |
|------|-------------|
| `--output` | Output package path |

### `palaia ingest`

| Arg/Flag | Default | Description |
|----------|---------|-------------|
| `source` | (required) | File, URL, or directory |
| `--project` | — | Target project |
| `--scope` | `private` | Scope for ingested entries |
| `--tags` | — | Extra tags |
| `--chunk-size` | `500` | Words per chunk |
| `--chunk-overlap` | `50` | Overlap words |
| `--dry-run` | — | Preview without storing |

---

## Configuration

### `palaia config list`

### `palaia config get <key>`

### `palaia config set <key> <value>`

### `palaia config set-chain <providers...>`

```bash
palaia config set-chain openai fastembed bm25
```

### `palaia config set-alias <from> <to>`

```bash
palaia config set-alias default alice
```

### `palaia config get-aliases`

### `palaia config remove-alias <from>`

---

## Infrastructure

### `palaia embed-server`

| Flag | Default | Description |
|------|---------|-------------|
| `--socket` | — | Unix socket transport |
| `--daemon` | — | Detached background process (requires `--socket`) |
| `--idle-timeout` | `0` | Auto-shutdown after N seconds idle |
| `--stop` | — | Stop running daemon |
| `--status` | — | Check if running |

### `palaia mcp-server`

| Flag | Default | Description |
|------|---------|-------------|
| `--root` | auto-detect | Path to `.palaia` directory |
| `--read-only` | — | Disable write operations |

---

## Data Exchange

### `palaia sync export`

| Flag | Description |
|------|-------------|
| `--remote` | Git remote URL |
| `--branch` | Branch name |
| `--output` | Local output directory |
| `--project` | Export only this project |
| `--agent` | Agent for scope filtering |

### `palaia sync import <source>`

| Flag | Description |
|------|-------------|
| `--dry-run` | Preview without writing |

### `palaia package export <project>`

| Flag | Description |
|------|-------------|
| `--output` | Output file path |
| `--types` | Comma-separated types to include |

### `palaia package import <file>`

| Flag | Default | Description |
|------|---------|-------------|
| `--project` | — | Override target project |
| `--merge` | `skip` | Strategy: `skip`, `overwrite`, `append` |
| `--agent` | — | Agent for attribution |

### `palaia package info <file>`

---

## Other Commands

### `palaia lock`

| Arg/Flag | Description |
|----------|-------------|
| `project` | Project name (shorthand for acquire) |
| `status <project>` | Show lock status |
| `renew <project>` | Extend lock TTL |
| `break <project>` | Force-break a lock |
| `list` | List all locks |
| `--agent` | Agent name |
| `--reason` | Lock reason |
| `--ttl` | TTL in seconds |

### `palaia unlock <project>`

### `palaia instance set <name>`

### `palaia instance get`

### `palaia instance clear`

### `palaia process list`

### `palaia process run <entry_id>`

| Flag | Description |
|------|-------------|
| `--step` | Step index (0-based) |
| `--done` | Mark step as done (requires `--step`) |
| `--agent` | Agent name |

### `palaia migrate`

| Arg/Flag | Default | Description |
|----------|---------|-------------|
| `source` | — | Source path or file |
| `--format` | auto-detect | Format: `smart-memory`, `flat-file`, `json-memory`, `generic-md` |
| `--scope` | — | Override scope for all entries |
| `--dry-run` | — | Preview without writing |
| `--suggest` | — | Suggest type assignments for untyped entries |

### `palaia recover`

Replay pending WAL entries.

### `palaia skill`

Print the embedded SKILL.md documentation.

### `palaia setup`

| Flag | Description |
|------|-------------|
| `--multi-agent <path>` | Path to agents directory |
| `--dry-run` | Preview without creating symlinks |
