# MCP Server

palaia works as a standalone MCP memory server for Claude Desktop, Cursor, and any MCP-compatible host. **No OpenClaw required** — palaia as a standalone memory layer.

## Installation

```bash
pip install "palaia[mcp,fastembed]"
palaia init
palaia doctor --fix
```

## Configuration

### Claude Desktop

Add to `~/.config/claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "palaia": {
      "command": "palaia-mcp"
    }
  }
}
```

With explicit store path:
```json
{
  "mcpServers": {
    "palaia": {
      "command": "palaia-mcp",
      "args": ["--root", "/path/to/.palaia"]
    }
  }
}
```

### Cursor

Settings → MCP Servers → Add:
- **Command**: `palaia-mcp`
- **Arguments**: (none, or `--root /path/to/.palaia`)

Or add to `.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "palaia": {
      "command": "palaia-mcp"
    }
  }
}
```

### Claude Code

The easiest way to set up Claude Code is the automated setup command:

```bash
palaia setup claude-code --global
```

This configures `~/.claude/settings.json` and generates a CLAUDE.md with agent instructions. Restart Claude Code after setup.

See [Claude Code Integration](claude-code.md) for the full guide, including the paste-this prompt for fully autonomous setup.

For manual configuration, add to `~/.claude/settings.json`:
```json
{
  "mcpServers": {
    "palaia": {
      "command": "palaia-mcp"
    }
  }
}
```

### Other MCP Hosts

Any MCP-compatible host that supports stdio transport can use palaia:
```bash
palaia-mcp                              # stdio transport (default)
palaia-mcp --root /path/to/.palaia      # explicit store
palaia-mcp --read-only                  # no writes
```

## Available Tools

| Tool | Purpose | Read-only |
|------|---------|-----------|
| `palaia_search` | Semantic + keyword search across memories | Available |
| `palaia_read` | Read a specific entry by ID (full or short prefix) | Available |
| `palaia_list` | List entries by tier, type, or project | Available |
| `palaia_status` | Store health: entry counts, provider info, backend | Available |
| `palaia_store` | Save a new memory (fact, process, task) | Blocked |
| `palaia_edit` | Update an existing entry | Blocked |
| `palaia_gc` | Run garbage collection (tier rotation) | Blocked |

### palaia_search

Find relevant memories by meaning:

| Parameter | Required | Description |
|-----------|----------|-------------|
| `query` | Yes | Search text |
| `limit` | No | Max results (default: 10) |
| `project` | No | Filter by project |
| `entry_type` | No | Filter: memory, process, task |
| `status` | No | Filter: open, in-progress, done, wontfix |
| `priority` | No | Filter: critical, high, medium, low |
| `assignee` | No | Filter by assignee |
| `include_cold` | No | Include archived entries |
| `cross_project` | No | Search across all projects |

### palaia_store

Save knowledge that should persist:

| Parameter | Required | Description |
|-----------|----------|-------------|
| `content` | Yes | Memory content |
| `title` | No | Short title |
| `tags` | No | List of tags |
| `entry_type` | No | memory (default), process, task |
| `scope` | No | team (default), private, public |
| `project` | No | Project name |
| `status` | No | Task status |
| `priority` | No | Task priority |

### palaia_read

Read a single entry:

| Parameter | Required | Description |
|-----------|----------|-------------|
| `entry_id` | Yes | Full UUID or short prefix (8+ chars) |

### palaia_edit

Update an existing entry (only provided fields change):

| Parameter | Required | Description |
|-----------|----------|-------------|
| `entry_id` | Yes | Entry to edit |
| `content` | No | New content |
| `title` | No | New title |
| `tags` | No | New tags (replaces) |
| `status` | No | New status |
| `priority` | No | New priority |
| `assignee` | No | New assignee |

### palaia_gc

Run garbage collection:

| Parameter | Required | Description |
|-----------|----------|-------------|
| `dry_run` | No | Preview only (default: true) |

## Read-Only Mode

```bash
palaia-mcp --read-only
```

Disables `palaia_store`, `palaia_edit`, and `palaia_gc`. Use this when connecting untrusted AI tools that should read memories but not modify them.

## Store Discovery

The MCP server finds the `.palaia` store using the same logic as the CLI:

1. `--root` argument (explicit)
2. `PALAIA_HOME` environment variable
3. Walk up from current directory looking for `.palaia/`
4. `~/.palaia` (home directory)
5. `~/.openclaw/workspace/.palaia` (OpenClaw default)

If no store is found, the server exits with an error message suggesting `palaia init`.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "MCP SDK not installed" | `pip install 'palaia[mcp]'` |
| "No .palaia store found" | Run `palaia init` first, or use `--root` |
| Tool calls are slow | Install sqlite-vec: `pip install 'palaia[sqlite-vec]'` |
| No semantic results | Check `palaia detect` for embedding provider |
| Permission errors | Check file permissions on `.palaia/` directory |
