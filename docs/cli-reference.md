# CLI Reference

All commands support `--json` for machine-readable output.

## Quick Reference

```
palaia init                                          Initialize store
palaia write "text" [--type TYPE] [--tags a,b]       Save knowledge
palaia query "search" [--type TYPE] [--project P]    Search by meaning
palaia get <id>                                       Read entry
palaia list [--tier T] [--type T] [--status S]       List entries
palaia edit <id> [--status done]                      Edit entry
palaia status                                         System health
palaia doctor [--fix]                                 Diagnose + fix
palaia upgrade                                        Update palaia
palaia project create|list|show|query|delete          Projects
palaia memo send|inbox|ack|broadcast                  Messaging
palaia priorities [block|set]                         Injection control
palaia curate analyze|apply                           Knowledge curation
palaia gc [--aggressive] [--budget N]                 Garbage collection
palaia config list|set|set-chain                      Configuration
palaia detect                                         Provider detection
palaia warmup                                         Pre-build index
palaia embed-server [--socket] [--daemon]             Embedding server
palaia mcp-server [--read-only]                       MCP server
palaia ingest <source> [--project P]                  Document indexing
palaia sync export|import                             Git-based exchange
palaia package export|import|info                     Portable packages
palaia process list|run                               Process tracking
```

---

## Core Commands

### `palaia init`

Initialize a `.palaia` store in the current directory.

```bash
palaia init                    # Default setup
palaia init --agent alice      # With agent identity
```

### `palaia write`

Save structured knowledge.

```bash
palaia write "text" [flags]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--type` | `memory` | Entry type: `memory`, `process`, `task` |
| `--scope` | `team` | Visibility: `private`, `team`, `public` |
| `--tags` | — | Comma-separated tags |
| `--title` | — | Short title (auto-extracted if omitted) |
| `--project` | — | Project name |
| `--agent` | — | Agent name |
| `--status` | — | Task status: `open`, `in-progress`, `done`, `wontfix` |
| `--priority` | — | Task priority: `critical`, `high`, `medium`, `low` |
| `--assignee` | — | Task assignee |
| `--due-date` | — | Task due date |

### `palaia query`

Search memories using hybrid BM25 + semantic ranking.

```bash
palaia query "search text" [flags]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--limit` | `10` | Max results |
| `--all` | — | Include COLD tier |
| `--type` | — | Filter by type |
| `--project` | — | Filter by project |
| `--status` | — | Filter by status |
| `--priority` | — | Filter by priority |
| `--assignee` | — | Filter by assignee |
| `--cross-project` | — | Search all projects |
| `--before` | — | Created before (ISO date) |
| `--after` | — | Created after (ISO date) |

### `palaia get`

Read a specific entry by ID.

```bash
palaia get <id>                    # Full UUID or short prefix
palaia get <id> --from-line 10     # Start at line 10
palaia get <id> --num-lines 5      # Limit lines
```

### `palaia list`

List entries in a tier.

```bash
palaia list                        # HOT tier (default)
palaia list --tier warm            # WARM tier
palaia list --all                  # All tiers
palaia list --type task --status open  # Filter
```

### `palaia edit`

Edit an existing entry.

```bash
palaia edit <id> --status done
palaia edit <id> --title "New title"
palaia edit <id> --tags new,tags
```

### `palaia status`

Show system health, entry counts, backend info, and upgrade command.

```bash
palaia status          # Human-readable
palaia status --json   # Machine-readable
```

### `palaia doctor`

Run diagnostics and auto-fix issues.

```bash
palaia doctor           # Check only
palaia doctor --fix     # Check and fix
palaia doctor --json    # Machine-readable
```

### `palaia upgrade`

Update palaia to the latest version.

```bash
palaia upgrade
```

Auto-detects install method (pip/uv/pipx/brew), preserves all installed extras, runs `palaia doctor --fix`, upgrades OpenClaw plugin if present.

---

## Project Management

### `palaia project`

```bash
palaia project create myapp                # Create project
palaia project list                        # List all
palaia project show myapp                  # Project details
palaia project query myapp "search text"   # Search within project
palaia project delete myapp                # Delete project
```

---

## Knowledge Management

### `palaia gc`

Garbage collection — rotate entries between tiers.

```bash
palaia gc                      # Normal rotation
palaia gc --dry-run            # Preview
palaia gc --aggressive         # Also clear COLD tier
palaia gc --budget 200         # Keep max N entries
```

### `palaia curate`

Knowledge curation for large stores.

```bash
palaia curate analyze                      # Generate curation report
palaia curate analyze --project myapp      # Project-scoped
palaia curate apply report.md              # Apply curation decisions
```

### `palaia ingest`

Index external documents for RAG.

```bash
palaia ingest ./docs/ --project myapp      # Index directory
palaia ingest file.pdf --project myapp     # Index PDF
```

---

## Communication

### `palaia memo`

Inter-agent messaging.

```bash
palaia memo send bob "Deploy ready"        # Send to agent
palaia memo inbox                          # Check messages
palaia memo ack <id>                       # Acknowledge
palaia memo broadcast "Release v2.3"       # Notify all
```

---

## Infrastructure

### `palaia config`

```bash
palaia config list                         # Show all
palaia config set <key> <value>            # Set value
palaia config set-chain openai fastembed bm25  # Provider chain
palaia config get <key>                    # Get value
```

### `palaia detect`

Show available embedding providers and sqlite-vec status.

### `palaia warmup`

Pre-compute embeddings for all entries. Run after provider changes or on first setup.

### `palaia embed-server`

Background embedding server for fast queries.

```bash
palaia embed-server --socket --daemon      # Start daemon
palaia embed-server --status               # Check status
palaia embed-server --stop                 # Stop daemon
palaia embed-server --idle-timeout 3600    # Custom timeout
```

### `palaia mcp-server`

MCP server for Claude Desktop, Cursor, etc.

```bash
palaia mcp-server                          # Start (stdio)
palaia mcp-server --read-only              # No writes
palaia mcp-server --root /path/to/.palaia  # Explicit store
```

---

## Data Exchange

### `palaia sync`

Git-based knowledge exchange (public entries only).

```bash
palaia sync export                         # Export to local dir
palaia sync export --remote git@...        # Push to git
palaia sync import ./export/               # Import from dir
```

### `palaia package`

Portable packages (all scopes).

```bash
palaia package export --project myapp      # Create package
palaia package import package.json         # Import package
palaia package info package.json           # Show metadata
```
