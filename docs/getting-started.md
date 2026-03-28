# Getting Started

## Installation

### With OpenClaw (recommended)

Paste this into your agent:

> Install or update the Palaia memory skill from ClawHub to the latest version (even if already present). Read the SKILL.md completely and follow it step by step. Run palaia init, then palaia doctor --fix and resolve all warnings — don't stop until the doctor report is clean. Set up completely.

### Manual (pip)

```bash
pip install "palaia[fastembed]"
palaia init
palaia doctor --fix
```

### With MCP (Claude Desktop, Cursor)

```bash
pip install "palaia[mcp,fastembed]"
palaia init
```

Add to your MCP config (see [MCP Server docs](mcp.md) for details):
```json
{
  "mcpServers": {
    "palaia": { "command": "palaia-mcp" }
  }
}
```

### Optional Extras

```bash
pip install "palaia[sqlite-vec]"      # ~30x faster vector search (SIMD)
pip install "palaia[mcp]"             # MCP server
pip install "palaia[curate]"          # Knowledge curation
pip install "palaia[postgres]"        # PostgreSQL + pgvector
```

Install multiple: `pip install "palaia[fastembed,mcp,sqlite-vec]"`

## First Steps

### Write a memory

```bash
palaia write "API rate limit is 100 req/min per user" \
  --type memory --tags api,limits --project myapp
```

### Search by meaning

```bash
palaia query "what's the rate limit"
```

Results are ranked by hybrid score (BM25 keyword + semantic embedding).

### Structured types

```bash
# Process (workflow / SOP)
palaia write "1. Build 2. Test 3. Deploy" --type process --project myapp

# Task with status tracking
palaia write "Fix auth bug in login" --type task --status open --priority high --assignee alice
```

### Check health

```bash
palaia status     # Entry counts, backend, embedding provider, upgrade command
palaia doctor     # Full diagnostics
palaia detect     # Available embedding providers
```

## Updating

```bash
palaia upgrade
```

Auto-detects install method, preserves all extras, runs `palaia doctor --fix`, upgrades OpenClaw plugin if present.

If `palaia upgrade` is not recognized (versions before v2.3.0), see the [SKILL.md update section](../palaia/SKILL.md) for manual instructions.

## Next Steps

- [Storage & Search](backends.md) — Backend options, embedding providers
- [MCP Server](mcp.md) — Claude Desktop / Cursor setup
- [Multi-Agent](multi-agent.md) — Team setup, scopes, aliases
- [CLI Reference](cli-reference.md) — All commands and flags
- [Configuration](configuration.md) — Tuning and config keys
