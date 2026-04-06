# palaia for Claude Code

Use palaia as persistent, searchable memory for your Claude Code sessions. Knowledge survives across sessions, projects, and tools — no cloud, no external database, everything local.

## Why palaia instead of built-in memory?

Claude Code has a built-in auto-memory system (`~/.claude/projects/*/memory/`). It works well for personal preferences and conversation context. palaia adds capabilities that go beyond what built-in memory offers:

| Capability | Built-in Memory | palaia |
|------------|----------------|--------|
| **Semantic search** | No (file-based recall) | Yes — hybrid BM25 + vector search |
| **Structured types** | Free-form markdown | memory / process / task with status tracking |
| **Cross-tool sharing** | Claude Code only | Any MCP client (Claude Desktop, Cursor, etc.) |
| **Team scopes** | Per-user only | private / team / public |
| **Smart tiering** | Manual cleanup | Automatic HOT → WARM → COLD based on usage |
| **Search across projects** | No | Yes — `cross_project: true` |
| **Task management** | No | Status, priority, assignee, due dates |
| **WebUI browser** | No | `palaia ui` — visual entry explorer |

**When to use which:**

- **Built-in memory**: Personal preferences, editor settings, interaction style
- **palaia**: Project decisions, architecture knowledge, learnings, shared context, task tracking

They complement each other — use both.

## Quick Setup

### Option A: One command (recommended)

```bash
pip install "palaia[mcp,fastembed]"
palaia init
palaia setup claude-code
```

This automatically:
1. Adds palaia to your Claude Code MCP config (`~/.claude/settings.json`)
2. Creates a `CLAUDE.md` with instructions that teach Claude Code how to use palaia

Restart Claude Code after setup. The palaia tools appear automatically.

### Option B: Manual setup

```bash
pip install "palaia[mcp,fastembed]"
palaia init
```

Add to `~/.claude/settings.json`:
```json
{
  "mcpServers": {
    "palaia": {
      "command": "palaia-mcp"
    }
  }
}
```

If palaia is installed in a virtualenv, use the full path:
```json
{
  "mcpServers": {
    "palaia": {
      "command": "/path/to/.venv/bin/palaia-mcp"
    }
  }
}
```

Restart Claude Code.

### Verify

After restarting Claude Code, the following tools should be available:

| Tool | Purpose |
|------|---------|
| `palaia_search` | Find memories by meaning (semantic + keyword) |
| `palaia_store` | Save knowledge that should persist |
| `palaia_read` | Read a specific entry by ID |
| `palaia_list` | Browse entries by tier, type, or project |
| `palaia_edit` | Update an existing entry |
| `palaia_status` | Check store health and stats |
| `palaia_gc` | Run garbage collection (tier rotation) |

Run `palaia doctor` to check that everything is healthy.

## Setup Options

### `palaia setup claude-code`

| Flag | Description |
|------|-------------|
| `--global` | Write CLAUDE.md to `~/.claude/` instead of current directory |
| `--dry-run` | Preview changes without writing |
| `--json` | JSON output |

**Project-local vs. global**: By default, `CLAUDE.md` is created in the current directory (project-specific). Use `--global` to write it to `~/.claude/CLAUDE.md` so it applies to all Claude Code sessions.

## Daily Workflow

### Session start

Claude Code will automatically search palaia for relevant context (if CLAUDE.md is set up). You can also ask explicitly:

> "What do we know about the auth module?"
> "Show me open tasks for this project"

### During work

Store decisions, findings, and patterns:

> "Remember that we chose JWT over sessions because of the stateless API requirement"
> "Store a task: migrate the user table to the new schema"

### Across sessions

Knowledge persists. Next time you (or a teammate using Claude Desktop/Cursor) work on the same project, palaia recalls the relevant context automatically.

## Advanced: Sharing Knowledge with Other Tools

palaia stores are local files. The same `.palaia` directory can be accessed by:

- **Claude Code** (via MCP server)
- **Claude Desktop** (via MCP server)
- **Cursor** (via MCP server)
- **CLI** (`palaia query`, `palaia write`)
- **WebUI** (`palaia ui`)

All tools share the same knowledge store — write from one, recall from any.

### Multi-host access

For accessing palaia from a different machine (e.g., Claude Code on your laptop, palaia store on a VPS):

- **Shared PostgreSQL**: Point both instances to the same database via `PALAIA_DATABASE_URL`
- **Knowledge packages**: `palaia package export myapp` → transfer → `palaia package import`
- **Git sync**: `palaia sync export --remote <git-url>` → `palaia sync import` on the other end

## Updating

```bash
palaia upgrade
```

Auto-detects install method, preserves extras, runs health checks.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Tools don't appear in Claude Code | Check `~/.claude/settings.json` has palaia entry, restart Claude Code |
| "MCP SDK not installed" | `pip install 'palaia[mcp]'` |
| "No .palaia store found" | Run `palaia init` |
| Search returns no results | Check `palaia status` — are there entries? Check `palaia doctor` |
| Slow tool calls | Install sqlite-vec: `pip install 'palaia[sqlite-vec]'` |

See also: [MCP Server docs](mcp.md) for protocol details and read-only mode.
