# Palaia 🧠

[![CI](https://github.com/iret77/palaia/actions/workflows/ci.yml/badge.svg)](https://github.com/iret77/palaia/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/palaia)](https://pypi.org/project/palaia/)
[![Python](https://img.shields.io/pypi/pyversions/palaia)](https://pypi.org/project/palaia/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> *From Greek: "the old, the enduring"*

**Local, cloud-free memory for OpenClaw agents.**  
No API key. No cloud. No lock-in.

---

## What is Palaia?

Palaia is a persistent memory system for AI agents built on OpenClaw.  
It solves the fundamental problem of agents losing context between sessions — without sending your data anywhere.

### Core Principles

- **Local first** — runs fully offline
- **Zero hard dependencies** — Python stdlib is enough for the base layer
- **Crash-safe** — Write-Ahead Log (WAL) before every write
- **Multi-agent** — Scope tags control what each agent can see
- **No context bloat** — Query-on-demand, not everything-in-prompt

---

## Features

### MVP
- ✅ WAL protocol — crash recovery built-in
- ✅ HOT/WARM/COLD tiering — automatic memory temperature management
- ✅ Auto-deduplication — hash-based, no duplicate entries
- ✅ Memory decay scoring — older, unused memories fade automatically
- ✅ BM25 search — fast keyword search, zero install

### Extended
- 🔧 Scope tags — `private` / `team` / `shared:project` / `public`
- 🔧 Tiered semantic search — ollama → API → BM25 fallback
- 🔧 Git-based cross-team sync — share only what you choose

---

## Semantic Search (Tiered)

Palaia automatically uses the best available search:

| Tier | Requires | Quality |
|------|----------|---------|
| BM25/TF-IDF | Nothing (default) | Good |
| Local embeddings | `ollama` + `nomic-embed-text` | Great |
| API embeddings | OpenAI / Voyage AI key | Best |

No configuration needed — Palaia detects what's available.

---

## Cross-Team Knowledge Transfer via Git

Share knowledge between agent teams without a central server:

```bash
# Publish your public memories
palaia export --remote git@github.com:org/knowledge-base.git

# Import from another team
palaia import git@github.com:org/knowledge-base.git
```

Only memories tagged `scope: public` are ever exported.  
`scope: team` memories never leave your workspace.

---

## Scope Tags

Every memory entry carries a scope:

```yaml
---
scope: private      # only the writing agent
scope: team         # all agents in this workspace
scope: shared:proj  # agents with access to project "proj"
scope: public       # exportable via git
---
```

**Sharing is always explicit — never implicit.**

---

## Architecture

```
.palaia/
  hot/        active memories (< 7 days or high score)
  warm/       occasional access (7–30 days)
  cold/       archive (> 30 days, still searchable)
  wal/        write-ahead log (crash recovery)
  index/      search index (BM25 + optional embeddings)
```

---

## Installation

```bash
pip install palaia
```

## Status

**v0.1.0** — Core features complete. See [CHANGELOG](CHANGELOG.md) for details.  
Architecture Decision Records: [`docs/adr/`](docs/adr/)

---

## License

MIT — free to use, modify, and build on.

---

*Built for the [OpenClaw](https://github.com/openclaw/openclaw) ecosystem.*
