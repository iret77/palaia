# Claude Code Integration

palaia works as a fully autonomous memory system for Claude Code. One command sets up everything — MCP server config, agent instructions, and proactive memory behavior.

## Quick Start

Paste this into Claude Code:

> Install palaia for persistent memory in this Claude Code environment.
> Run: `pip install "palaia[mcp,fastembed]" && palaia init && palaia setup claude-code --global`
> Then tell me to restart Claude Code so the MCP tools become active.
> After restart, read the CLAUDE.md and follow its instructions.

That's it. After the restart, Claude Code has 7 memory tools and knows how to use them proactively.

## What `palaia setup claude-code` Does

1. **MCP server config** — adds `palaia` to `~/.claude/settings.json` so Claude Code loads the memory tools at startup
2. **CLAUDE.md** — generates agent instructions that teach Claude Code when and how to store and recall knowledge

```bash
palaia setup claude-code            # CLAUDE.md in current directory
palaia setup claude-code --global   # CLAUDE.md in ~/.claude/ (recommended)
palaia setup claude-code --dry-run  # Preview without writing files
```

`--global` is recommended because it makes palaia available in every project, not just the current directory.

## Why Two Sessions?

Claude Code loads MCP servers only at startup. After `palaia setup claude-code` writes the config, you need to restart Claude Code for the tools to become available. This is a Claude Code limitation — there's no way around it.

**Session 1**: Install + setup (tools not yet active)
**Session 2+**: palaia tools available, agent stores and recalls knowledge automatically

## What Claude Code Gets

After setup, Claude Code has access to 7 MCP tools:

| Tool | Purpose |
|------|---------|
| `palaia_search` | Find memories by meaning (hybrid BM25 + vector) |
| `palaia_store` | Save knowledge (decisions, tasks, processes) |
| `palaia_read` | Read a specific entry by ID |
| `palaia_edit` | Update entries (close tasks, add context) |
| `palaia_list` | Browse entries by tier, type, or project |
| `palaia_status` | Check store health and entry counts |
| `palaia_gc` | Run garbage collection (tier rotation) |

The CLAUDE.md instructions teach Claude Code to:
- **Search at session start** — load relevant context before working
- **Store proactively** — save decisions, discoveries, and tasks without being asked
- **Use structured types** — memory, process, task with appropriate metadata

## Manual Setup

If you prefer to configure manually instead of using the setup command:

### 1. MCP Config

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

If palaia is in a virtualenv, use the full path:
```json
{
  "mcpServers": {
    "palaia": {
      "command": "/path/to/.venv/bin/palaia-mcp"
    }
  }
}
```

### 2. CLAUDE.md

The setup command generates a CLAUDE.md with session-start routines, storage triggers, and tool reference. Without it, Claude Code has the tools but doesn't know *when* to use them. You can write your own or use the generated one as a starting point.

## Flags

| Flag | Effect |
|------|--------|
| `--global` | Write CLAUDE.md to `~/.claude/CLAUDE.md` (all projects) |
| `--dry-run` | Preview planned actions without writing files |
| `--json` | Output result as JSON (for scripting) |

## Diagnostics

`palaia doctor` checks Claude Code configuration automatically:

```bash
palaia doctor
# ...
# ✓ claude_code_config: palaia-mcp configured in ~/.claude/settings.json
```

If the config is missing, doctor suggests running `palaia setup claude-code`.

## Comparison with OpenClaw

| Aspect | OpenClaw | Claude Code |
|--------|----------|-------------|
| Install | Paste prompt → ClawHub → fully autonomous | Paste prompt → pip + setup → restart |
| Agent instructions | SKILL.md via ClawHub | CLAUDE.md via setup command |
| Auto-capture | ContextEngine hooks (every turn) | Agent-driven (via CLAUDE.md guidance) |
| Nudging | Adaptive nudging system | CLAUDE.md instructions |
| Sessions | 1 (immediate) | 2 (restart required for MCP) |
| Memory tools | Plugin API (7 tools) | MCP protocol (7 tools) |

Both platforms get the same 7 tools and the same knowledge store. The difference is in how the agent learns to use them — OpenClaw has deep lifecycle hooks, Claude Code relies on CLAUDE.md instructions.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Tools not available after setup | Restart Claude Code — MCP loads at startup only |
| `palaia-mcp` not found | `pip install 'palaia[mcp]'` or use full path in config |
| Store empty after first session | Normal — knowledge accumulates over time |
| Agent not storing proactively | Check CLAUDE.md exists and mentions palaia |
| Doctor shows warning | Run `palaia setup claude-code --global` |

## See Also

- [MCP Server](mcp.md) — Full MCP tool reference and transport options
- [Getting Started](getting-started.md) — Installation overview
- [Multi-Agent](multi-agent.md) — Team setup with scopes and isolation
