# Migration Guide

This guide covers migrating from OpenClaw's built-in smart-memory (or other formats) to Palaia.

## Quick Migration

```bash
# 1. Install Palaia
pip install git+https://github.com/iret77/palaia.git

# 2. Initialize
palaia init

# 3. Preview what would be imported
palaia migrate . --dry-run

# 4. Run the migration
palaia migrate .

# 5. Verify
palaia status
palaia list
```

Supported formats: `smart-memory`, `flat-file`, `json-memory`, `generic-md`.
Palaia auto-detects the format, or you can force it with `--format`.

## ⚠️ Important: Do NOT Delete System Files

After migrating to Palaia, these files MUST remain on disk — they are living documents read by agents at runtime, not historical data:

- `CONTEXT.md` (project context, injected into subagent prompts)
- `SOUL.md` (agent personality/identity)
- `MEMORY.md` (orchestrator core memory)
- `AGENTS.md` (workspace config)
- `TOOLS.md` (tool config)
- `USER.md` (user preferences)
- `IDENTITY.md` (agent identity)

`palaia ingest` creates a **searchable copy** in the store. The original file continues to be the source of truth. Deleting it breaks agent workflows.

**Safe to archive after migration:**
- Daily logs (`memory/YYYY-MM-DD.md`) — historical, not read at runtime
- Old chat logs (`memory/chat-*.md`)
- One-off notes that have been fully ingested

## What Happens During Migration

`palaia migrate` reads your existing memory files, converts them to Palaia entries, and stores them in the Palaia database. **Source files are NOT modified or deleted.**

For smart-memory format, files are mapped as follows:

| Source File | Palaia Tier | Scope |
|---|---|---|
| `MEMORY.md` | HOT | team |
| `memory/active-context.md` | HOT (per block) | team |
| `memory/projects/*/CONTEXT.md` | HOT | shared:{project} |
| `memory/agents/*.md` | WARM | team |
| `memory/YYYY-MM-DD.md` | COLD | team |

## Post-Migration

After migration, Palaia and your existing files coexist:

- **Palaia** provides semantic search across all your memory
- **Original files** continue to be loaded by OpenClaw at agent startup
- Both systems work together — Palaia supplements, it does not replace

Do **not** "clean up" by deleting source files. See the system files list above.
