---
name: palaia
description: >
  Persistent memory for OpenClaw agents. Local, crash-safe, no API key needed.
  Agents remember things across sessions. You control what's shared between agents.
  Drop-in replacement for OpenClaw's built-in memory via @palaia/openclaw plugin.
metadata:
  openclaw:
    emoji: 🧠
    requires: { bins: ["python3"] }
---

# Palaia — Memory That Sticks

## What Palaia Does (plain English)

Palaia gives your agent a notebook that survives restarts. When your agent learns something — a preference, a project detail, a lesson — it writes it down. Next session, it's still there. Think of it as a filing cabinet: important stuff up front, old stuff in the back, nothing gets lost.

## Quick Install

```bash
pip install palaia
palaia init
palaia status
```

That's it. You now have a working memory system with keyword search. No API keys, no servers, no cloud.

## Setting Up Semantic Search

Keyword search works out of the box. But if you want your agent to find things by *meaning* (not just matching words), you'll want semantic search. Run this to see what's available on your machine:

```bash
palaia detect
```

This shows which embedding providers are installed, which are running, and what Palaia recommends.

### The Options — What's Right for You?

#### Option 1: No Setup (Keyword Search)

This is what you get by default. Palaia uses BM25 — a smart keyword matching algorithm. It's fast, needs zero setup, and works well when your queries use similar words to what's stored.

**When it's enough:** Most setups. If your agent writes "project deadline is Friday" and later asks "when is the deadline?", keyword search finds it.

**What's missing:** It won't find "project due date" if you stored "project deadline". That's where semantic search helps.

#### Option 2: ollama (Recommended for most)

Ollama is a local AI server that runs on your machine. It understands meaning, not just words. Your data never leaves your computer.

**Pros:** Private, fast after first load, no API costs, good quality  
**Cons:** Uses ~1GB RAM while running, needs initial setup  

```bash
# Install ollama (if not already)
curl -fsSL https://ollama.com/install.sh | sh

# Pull the embedding model
ollama pull nomic-embed-text

# Tell Palaia to use it
palaia config set embedding_provider ollama
palaia status
```

**Choose this when:** You want smart search without sending data to the cloud.

#### Option 3: sentence-transformers (Best quality, pure Python)

A Python library that runs AI models directly. No separate server needed. Best quality embeddings for local use.

**Pros:** Best local quality, no server to manage, works offline  
**Cons:** Slower first load (~30s), uses more RAM (~500MB), needs pip install  

```bash
pip install "palaia[sentence-transformers]"
palaia config set embedding_provider sentence-transformers
palaia status
```

**Choose this when:** You want the best local search quality and don't mind the RAM usage.

#### Option 4: fastembed (Lightweight option)

A lighter alternative to sentence-transformers. Smaller models, faster startup, less RAM.

**Pros:** Lightweight, fast startup, works offline  
**Cons:** Slightly lower quality than sentence-transformers  

```bash
pip install "palaia[fastembed]"
palaia config set embedding_provider fastembed
palaia status
```

**Choose this when:** You're on a machine with limited RAM or want faster startup.

#### Option 5: OpenAI or Voyage (Cloud-based)

Use OpenAI's or Voyage's embedding APIs. Best quality, but requires an API key and sends data to the cloud.

**Pros:** Highest quality, no local compute needed  
**Cons:** Costs money (small amounts), data leaves your machine, needs internet  

```bash
export OPENAI_API_KEY="sk-..."
palaia config set embedding_provider openai
palaia status
```

**Choose this when:** You already use OpenAI and don't mind cloud processing.

### Guided Setup Flow (Agent Instructions)

When setting up Palaia for a user, follow these steps:

1. **Run detection:** `palaia detect` — parse the output
2. **Present results** to the user in plain language: "You have ollama running with nomic-embed-text available. I can set that up for semantic search, or keyword search works fine too."
3. **Ask the user** which option they prefer. Don't assume.
4. **Install + configure** based on their choice:
   - If they chose a provider: install it, run `palaia config set embedding_provider <name>`
   - If they're fine with keyword search: do nothing, it's the default
5. **Confirm** with `palaia status` — show them the output

## Connecting to OpenClaw (the important bit)

Palaia integrates with OpenClaw through its plugin system:

```bash
# In your OpenClaw workspace
npm install @palaia/openclaw
```

Then add to your OpenClaw config:
```json
{
  "plugins": ["@palaia/openclaw"]
}
```

The plugin automatically routes memory operations through Palaia instead of OpenClaw's built-in memory.

## Core Commands

```bash
# Write a memory
palaia write "Christian prefers dark mode in all apps" --tags "preferences,ui"

# Search memories
palaia query "what does Christian prefer"

# List what's in active memory
palaia list --tier hot

# Check system status
palaia status

# Run garbage collection (moves old stuff to archive)
palaia gc

# Export public memories for sharing
palaia export --output ./shared-memories

# Import memories from another agent
palaia import ./shared-memories

# Detect available embedding providers
palaia detect

# Configure settings
palaia config set embedding_provider ollama
palaia config get embedding_provider
palaia config list
```

## Migrating from smart-memory

If you're already using OpenClaw's smart-memory system, Palaia can import everything:

```bash
# Preview what would be imported (safe, no changes)
palaia migrate . --dry-run

# Actually import
palaia migrate .

# Verify
palaia status
palaia list --tier hot
```

Palaia auto-detects the smart-memory format and maps layers to tiers:
- Active context → HOT (frequently accessed)
- Project files → WARM (referenced occasionally)
- Daily logs → COLD (archived but searchable)

## Sharing Memory Between Agents

Palaia uses scope tags to control who sees what:

- **`team`** (default) — All agents in the same workspace can read it
- **`private`** — Only the agent that wrote it can read it
- **`public`** — Can be exported and shared with other workspaces
- **`shared:<project>`** — Only agents working on that project can read it

```bash
# Write a private note
palaia write "My API key is stored in ~/.secrets" --scope private

# Write a team-visible note
palaia write "The deploy server is at 10.0.1.5" --scope team

# Share across workspaces
palaia write "Project uses Python 3.11" --scope public
palaia export --remote git@github.com:team/shared-memory.git
```

## Configuration Reference

Configuration lives in `.palaia/config.json`:

```json
{
  "version": 1,
  "decay_lambda": 0.1,
  "hot_threshold_days": 7,
  "warm_threshold_days": 30,
  "hot_max_entries": 50,
  "default_scope": "team",
  "embedding_provider": "auto",
  "embedding_model": ""
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `embedding_provider` | `auto` | `auto`, `ollama`, `sentence-transformers`, `fastembed`, `openai`, `none` |
| `embedding_model` | `""` | Override the default model for your provider (empty = provider's default) |
| `decay_lambda` | `0.1` | How fast memories fade (higher = faster decay) |
| `hot_threshold_days` | `7` | Days before a memory moves from active to warm |
| `warm_threshold_days` | `30` | Days before a memory moves from warm to archive |
| `default_scope` | `team` | Default scope for new memories |

Use `palaia config set <key> <value>` to change any setting.
