---
name: palaia
version: "1.6.1"
description: >
  Local, crash-safe persistent memory for OpenClaw agents.
  Replaces built-in memory-core with semantic search, projects, and scope-based access control.
  After installing or updating, run: palaia doctor --fix to complete setup.
metadata:
  openclaw:
    emoji: 🧠
    requires:
      bins: ["palaia"]
    install:
      - id: pip
        kind: pip
        package: "palaia[fastembed]"
        bins: ["palaia"]
        label: "Install Palaia with fastembed (pip)"
    postInstall:
      - command: "palaia init"
        label: "Initialize Palaia store"
    postUpdate:
      - command: "python3 -m pip install --upgrade palaia && palaia doctor --fix"
        label: "Upgrade Palaia and run health checks"
    plugin:
      slot: memory
      package: "@byte5ai/palaia"
---

# Palaia — Agent Memory Skill

## Auto-Check (run every time this skill is loaded)

**[INSTRUCTION for LLM]:** Before doing anything else with Palaia, run `palaia doctor` silently. If it reports ANY warnings (version mismatch, missing providers, legacy patterns, incomplete setup), address them immediately by following `palaia doctor --fix` recommendations. Do not proceed with other Palaia tasks until doctor reports no issues. This ensures the memory system is always up-to-date and correctly configured.

## Communication During Setup

- After each major step, send a brief status message to the user. Don't go silent.
- If a step takes longer than ~10 seconds, say what you're doing: "Installing sentence-transformers, this takes a moment…"
- If something unexpected happens (e.g. CUDA error, provider fails), explain what happened and what you're doing instead — immediately.
- Don't batch all steps and report at the end. Report after each step.

Example pacing:
1. "Installing Palaia…" → [runs pip install] → "Done. Initializing…"
2. "Checking your system for available search providers…" → [runs palaia doctor + detect] → "Found: [X]. Quick question:"
3. [Onboarding conversation — max 3 questions]
4. "Configuring chain… warming up model (this takes ~15 seconds)…" → "Ready."
5. "All set. Here's your setup: [one sentence summary]"

## Setup Flow (follow this exactly)

### Step 1: Install and initialize
```bash
python3 -m pip install "palaia[fastembed]"
palaia init
```

### Step 2: Check for existing memory systems (REQUIRED — do not skip)
```bash
palaia doctor
```

Review **every** warning before continuing. For each warning found by `palaia doctor`, immediately offer to fix it — do not wait for the user to ask:

**HEARTBEAT.md legacy patterns:**
→ Tell the user: "Your heartbeat still uses old memory patterns. Should I update it to use Palaia? (Takes a moment, no data loss)"
- If yes: update HEARTBEAT.md, replace `memory_search`/`memory_get`/direct file reads with `palaia query`/`palaia write` equivalents
- If no: skip, move to next warning

**Smart-Memory skill detected:**
→ Tell the user: "The old smart-memory skill is still installed. Should I remove it? (Only after confirming Palaia has your memories)"
- If yes: run `palaia migrate <workspace-path>`, then remove the smart-memory skill folder
- If no: continue, but both systems will run in parallel (not recommended)

**OpenClaw plugin still memory-core:**
→ Tell the user: "Palaia isn't connected to OpenClaw's memory system yet. Should I switch it? (Requires a quick OpenClaw restart)"
- If yes: update OpenClaw config (`plugins.slots.memory = "palaia"`), restart OpenClaw
- If no: Palaia runs standalone (no `memory_search`/`memory_get` tool integration)

**openai-only chain (no local fallback):**
→ Tell the user: "Your search has no local backup. Should I install fastembed as a fallback? (Small download, no GPU needed)"
- If yes: `pip install fastembed`, then `palaia warmup`, update chain to include fastembed before bm25
- If no: skip (warn: "Search may degrade when OpenAI is unavailable")

Rules:
- For each warning: ask immediately, one question at a time
- Do not batch all questions — address them in order
- Do not wait for the user to notice and ask
- After user answers yes/no, move to next warning
- Report when all warnings are resolved

**Do not proceed until all warnings are addressed or explicitly dismissed by the user.**

### Onboarding Conversation

After running `palaia doctor` and reviewing warnings, have a brief conversation with your user.
Keep it short — 3 questions max. No technical details unless the user asks.

**Script:**

Tell the user:
"I've set up Palaia for you — your memory is now crash-safe and searchable.
Quick setup: 3 short questions."

**Question 1 — Search quality:**

If an OpenAI API key is present AND a local model (sentence-transformers/fastembed/ollama) is also detected:
  → Just confirm: "I'll use your OpenAI key with a local backup model. Good setup."
  → No question needed.

If an OpenAI API key is present BUT no local model is installed:
  → Tell the user: "You have an OpenAI API key — great for search quality. But without a local backup, search quality drops significantly when OpenAI is unavailable. I recommend installing a small local model (300MB, free, runs offline). Should I do that?"
  → yes: pip install sentence-transformers (if CUDA issues: pip install fastembed instead — lighter, no GPU needed), then palaia warmup, chain = openai → sentence-transformers → bm25
  → no: chain = openai → bm25 (warn: "Note: search may fail or degrade without a local fallback.")

If no OpenAI key AND no local model:
  → Tell the user: "No search provider found yet. I recommend installing a free local model (300MB). Should I do that?"
  → yes: pip install sentence-transformers (if CUDA issues: pip install fastembed instead — lighter, no GPU needed), then palaia warmup, chain = sentence-transformers → bm25
  → no: BM25 only (warn: "Search will be keyword-based — you can improve this later with palaia detect.")

If no OpenAI key BUT local model detected:
  → Just confirm: "Using local search model — works offline, no API costs."
  → No question needed.

**Question 2 — Existing memory (only ask if legacy memory files exist OR smart-memory detected):**
  Ask: "You have existing memory. Should I bring it into Palaia?"
  → yes: run palaia migrate <workspace-path>
  → no: start fresh (existing files stay untouched)

**Question 3 — Projects (only ask if multiple project folders detected OR more than 1 agent present):**
  Ask: "Do you work on multiple projects? I can keep their memories separate."
  → yes: briefly explain: "Use 'palaia project create <name>' for each project. I'll remember which memories belong where."
  → no: skip

**Wrap up:**
Tell the user what was configured — one sentence:
"Done. [Search quality: OpenAI / local model / keyword-only]. [Migration: X entries imported / fresh start]. [Projects: configured / not used]."

Do not explain commands, WAL, BM25, embedding models, or any technical details unless the user explicitly asks.

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
pip install sentence-transformers   # Recommended for most systems
palaia warmup                       # pre-load model
```
If sentence-transformers fails or requires CUDA: use fastembed instead (`pip install fastembed`) — lighter, no GPU needed.

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

### Step 6: Add Palaia maintenance to your heartbeat (mandatory)

This is required. Palaia's tiering (HOT → WARM → COLD) only runs when triggered.
Without periodic maintenance, all entries stay HOT forever and search quality degrades over time.

Check if `HEARTBEAT.md` exists in the workspace (`~/.openclaw/workspace/HEARTBEAT.md`).

**If it exists:** Append the following block at the end (before any final comments):

```
# TASK: Palaia Maintenance (daily + weekly)
# [INSTRUCTION for LLM]:
# Daily: run `palaia gc` — moves entries between HOT/WARM/COLD based on age and access.
# Weekly (Sunday): run `palaia gc --aggressive` — also clears COLD tier.
# Fast operation, never blocks user queries. Only run if palaia is installed (check: which palaia).
```

**If it does not exist:** Create `HEARTBEAT.md` with the block above as its first task.

Tell the user: "I've added a Palaia maintenance task to your heartbeat schedule. This keeps your memory organized automatically — nothing you need to do."

## Troubleshooting: pip Not Found

On some hosts, `pip` is not available as a standalone command. Use these fallbacks in order:

```bash
# Option 1: python3 -m pip (most reliable)
python3 -m pip install --upgrade "palaia[fastembed]"

# Option 2: pipx (if installed)
pipx install "palaia[fastembed]"

# Option 3: Bootstrap pip first
python3 -m ensurepip --upgrade
python3 -m pip install --upgrade "palaia[fastembed]"

# Option 4: Install from git directly
python3 -m pip install "palaia[fastembed] @ git+https://github.com/iret77/palaia.git"
```

## Troubleshooting: Debian/Ubuntu (PEP 668)

On Debian-based systems (Debian 12+, Ubuntu 23.04+), pip may fail with "externally-managed-environment".
This is due to PEP 668 which prevents pip from modifying system Python packages.

Use one of these approaches:

```bash
# Option 1: User install (recommended)
python3 -m pip install --user "palaia[fastembed]"

# Option 2: Break system packages (use if you know what you're doing)
python3 -m pip install --break-system-packages "palaia[fastembed]"

# Option 3: pipx (cleanest isolation)
pipx install "palaia[fastembed]"

# Option 4: Virtual environment
python3 -m venv ~/.palaia-venv
~/.palaia-venv/bin/pip install "palaia[fastembed]"
alias palaia=~/.palaia-venv/bin/palaia
```

After upgrading, always run `palaia doctor --fix` to verify providers and update the store.

**Important:** If you had sentence-transformers or fastembed installed before upgrading,
verify they are still available after the upgrade:
```bash
palaia detect
```
If a provider is missing, reinstall it:
```bash
python3 -m pip install "palaia[sentence-transformers]"
palaia warmup
```

## Plugin Activation (OpenClaw Memory Backend)

After installing palaia, activate it as your memory backend:

### 1. Install the OpenClaw plugin
```bash
npm install -g @byte5ai/palaia
```

### 2. Configure OpenClaw

**Config path:** `plugins.entries.palaia.config` in your OpenClaw config (`openclaw.json`).

> **Warning:** Do NOT use `plugins.config.palaia` — that path does not exist.
> The correct structure is `plugins.entries.palaia.config`.

Patch your OpenClaw config (`openclaw.json`) to load and activate the plugin:

```json
{
  "plugins": {
    "load": {
      "paths": ["<path-to-npm-global>/node_modules/@byte5ai/palaia"]
    },
    "allow": ["..existing..", "palaia"],
    "slots": {
      "memory": "palaia"
    },
    "entries": {
      "palaia": {
        "enabled": true,
        "config": {
          "workspace": "/path/to/.openclaw/workspace"
        }
      }
    }
  }
}
```

Find your npm global path with: `npm root -g`

**Plugin config keys** (under `plugins.entries.palaia.config`):

| Key | Description |
|-----|-------------|
| `workspace` | Path to the OpenClaw workspace (where `.palaia/` lives) |

### 3. Restart OpenClaw Gateway
The config change requires a gateway restart to take effect.

### What changes
- `memory_search` and `memory_get` tools now search the Palaia store instead of MEMORY.md files
- MEMORY.md and workspace files continue to be loaded as project context (unchanged)
- All Palaia features (projects, scopes, tiering, semantic search) are available through the standard memory tools

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

### Document Ingestion (RAG)

```bash
# Index a file, URL, or directory into the knowledge base
palaia ingest <file-or-url> [--project X] [--scope X] [--tags a,b] [--chunk-size N] [--dry-run]

# Query with RAG-formatted context (ready for LLM injection)
palaia query "question" --project X --rag
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
| Index a document or website | `palaia ingest <file/url> --project <name>` |
| Search indexed documents for LLM context | `palaia query "..." --project <name> --rag` |

## Document Knowledge Base

Use `palaia ingest` to index external documents — PDFs, websites, text files, directories.
Indexed content is chunked, embedded, and stored as regular entries (searchable like memory).

**When to use:**
- User asks you to "remember" a document, manual, or website
- You need to search through a large document
- Building a project-specific knowledge base

**How to use:**
```bash
palaia ingest document.pdf --project my-project
palaia ingest https://docs.example.com --project api-docs --scope team
palaia ingest ./docs/ --project my-project --tags documentation

palaia query "How does X work?" --project my-project --rag
```

The `--rag` flag returns a formatted context block ready to insert into your LLM prompt.

**PDF support:** requires pdfplumber — install with: `pip install pdfplumber`

**Source attribution:** each chunk tracks its origin (file, page, URL) automatically.

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

## After Updating Palaia

Always run `palaia doctor` after updating. It checks your store for compatibility, suggests new features (like projects or embedding chain improvements), and handles version stamping. If the installed version differs from the store version, Palaia will warn you automatically on every CLI call until you run `palaia doctor`.

```bash
pip install --upgrade palaia
palaia doctor --fix
```

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
