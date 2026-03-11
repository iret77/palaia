---
name: palaia
description: >
  Persistent memory for OpenClaw agents. Local, crash-safe, no API key needed.
  Agents remember things across sessions. You control what's shared between agents.
  Drop-in replacement for OpenClaw's built-in memory via @palaia/openclaw plugin.
metadata:
  openclaw:
    emoji: 🧠
    requires:
      bins: ["python3"]
    install:
      - id: pip
        kind: pip
        package: palaia
        bins: ["palaia"]
        label: "Install Palaia"
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

After configuring an embedding chain (see below), always run:

```bash
palaia warmup
```

This pre-downloads embedding models so the first real search is instant. Not optional — part of setup.

## Setting Up Your Embedding Chain

Keyword search works out of the box. But if you want your agent to find things by *meaning* (not just matching words), you'll want semantic search.

An **embedding chain** is a priority list — Palaia tries the first provider. If it doesn't work (server down, rate limit, missing API key), it automatically moves to the next one. BM25 keyword search is always the last resort, so search never breaks.

### Quick Detection

```bash
palaia detect
```

This shows what's available on your machine and recommends a chain. The output includes a ready-to-paste command.

### Setting Your Chain

```bash
# Best setup: cloud + local fallback + keyword backup
palaia config set-chain openai sentence-transformers bm25

# Local only, no cloud
palaia config set-chain sentence-transformers bm25

# Just keyword search (always works, zero setup)
palaia config set-chain bm25
```

Check what's active:

```bash
palaia status
```

Output looks like:
```
Embedding chain: openai → sentence-transformers → bm25
  1. openai (text-embedding-3-large) ✓ API key found
  2. sentence-transformers (all-MiniLM-L6-v2) ✓ installed
  3. bm25 ✓ always available
Active: openai (primary)
```

If the primary provider fails, you'll see:
```
Active: sentence-transformers (fallback — openai: 429 Too Many Requests)
```

### The Providers

| Provider | Type | Pros | Cons |
|----------|------|------|------|
| **openai** | Cloud | Best quality, no local compute | Costs money, needs internet + API key |
| **sentence-transformers** | Local | Best local quality, works offline | ~500MB RAM, ~30s first load |
| **ollama** | Local | Private, good quality, no API costs | ~1GB RAM, needs server running |
| **fastembed** | Local | Lightweight, fast startup | Slightly lower quality |
| **bm25** | Built-in | Zero setup, always works | Keyword matching only (no meaning) |

### Installing Providers

```bash
# sentence-transformers
pip install "palaia[sentence-transformers]"

# fastembed
pip install "palaia[fastembed]"

# ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull nomic-embed-text

# OpenAI (just set the key)
export OPENAI_API_KEY="sk-..."
```

### Model Overrides

Each provider has a sensible default model. Override per provider if needed:

```json
{
  "embedding_chain": ["openai", "sentence-transformers", "bm25"],
  "embedding_model": {
    "openai": "text-embedding-3-large",
    "sentence-transformers": "all-MiniLM-L6-v2"
  }
}
```

### Backward Compatibility

The old `embedding_provider` setting still works:

```bash
# These still work exactly as before
palaia config set embedding_provider sentence-transformers
palaia config set embedding_provider auto
```

If both `embedding_chain` and `embedding_provider` are set, `embedding_chain` takes priority.

### Guided Setup Flow (Agent Instructions)

When setting up Palaia for a user, follow these steps:

1. **Run detection:** `palaia detect` — parse the output
2. **Explain** what's available in plain language
3. **Recommend** a chain based on what's detected (see decision tree below)
4. **Let the user decide** — recommend, don't force
5. **Apply** with `palaia config set-chain ...`
6. **Warm up models:** `palaia warmup` — pre-downloads embedding models so the first real search is instant
7. **Confirm** with `palaia status`

#### Agent Decision Tree (recommend, don't decide)

```
If OpenAI key + local provider installed (sentence-transformers/ollama/fastembed):
  → Recommend: openai → <local> → bm25
  → Say: "Best quality with local fallback. If OpenAI is unreachable,
          <local> takes over automatically."

If only local provider (no OpenAI key):
  → Recommend: <local> → bm25
  → Say: "Fully local, no cloud dependency."

If only ollama:
  → Recommend: ollama → bm25
  → Say: "Runs on your local ollama server."

If only OpenAI key (no local provider):
  → Recommend: openai → bm25
  → Say: "Cloud-based. I'd suggest also installing sentence-transformers
          for offline fallback: pip install 'palaia[sentence-transformers]'"

If nothing available:
  → Recommend: bm25
  → Say: "Keyword search works right away. For smarter search:
          pip install 'palaia[sentence-transformers]'"
```

The user always makes the final call. Explain trade-offs in context of their system.

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
  "embedding_chain": ["openai", "sentence-transformers", "bm25"],
  "embedding_model": {
    "openai": "text-embedding-3-large",
    "sentence-transformers": "all-MiniLM-L6-v2"
  }
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `embedding_chain` | (auto-detected) | Ordered list of providers to try. BM25 is always last resort. |
| `embedding_model` | `{}` | Per-provider model overrides (dict) or single model string (legacy) |
| `embedding_provider` | `"auto"` | Legacy: `auto`, `ollama`, `sentence-transformers`, `fastembed`, `openai`, `none`. Use `embedding_chain` instead. |
| `decay_lambda` | `0.1` | How fast memories fade (higher = faster decay) |
| `hot_threshold_days` | `7` | Days before a memory moves from active to warm |
| `warm_threshold_days` | `30` | Days before a memory moves from warm to archive |
| `default_scope` | `team` | Default scope for new memories |

Use `palaia config set <key> <value>` to change any setting.
