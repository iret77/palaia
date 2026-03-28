# Palaia WebUI — Implementation Plan

## Vision
A lightweight, self-hosted web interface for browsing, searching, and managing Palaia memory entries. Runs locally alongside the CLI — zero external dependencies, zero cloud.

## Architecture Decision

### Framework: FastAPI + vanilla HTML/JS (no React/Vue)
- **FastAPI** — lightweight, async, auto-generates OpenAPI docs, great for API-first design
- **Frontend** — single-page app with vanilla JS + minimal CSS (no build step)
- **Served from** — `palaia ui` CLI command starts local server
- **Optional dep** — `pip install 'palaia[ui]'` installs fastapi + uvicorn

### Why not stdlib http.server?
- No routing, no JSON handling, no async — too much boilerplate
- FastAPI is 2 deps (fastapi + uvicorn) and gives us a proper REST API for free

## Features

### Phase 1: Read-Only Query UI (MVP)
- **Search bar** — semantic + BM25 hybrid search (same as CLI)
- **Entry list** — browse by tier (hot/warm/cold), type, project
- **Entry detail** — full markdown body + metadata sidebar
- **Filters** — type, status, project, tags, tier, date range
- **Stats dashboard** — entry counts, tier distribution, embedding status

### Phase 2: Priority Management
- **Priority editor** — view/edit entry priorities inline
- **Bulk actions** — multi-select for priority changes
- **Drag-and-drop** reordering (stretch goal)

### Phase 3: Future (out of scope for now)
- Entry editing
- Tag management
- GC controls
- Multi-agent views

## API Design (Phase 1)

```
GET  /api/status              → system status (entry counts, health)
GET  /api/entries              → list entries (query params: tier, type, project, limit, offset)
GET  /api/entries/{id}         → get single entry (full body + meta)
GET  /api/search?q=...        → hybrid search (query params: q, limit, type, project, etc.)
GET  /api/projects             → list projects
GET  /api/stats                → dashboard stats (tier distribution, type counts, etc.)
```

### Phase 2 additions:
```
PATCH /api/entries/{id}        → update priority/status
POST  /api/priorities          → bulk priority update
```

## File Structure

```
palaia/
├── web/
│   ├── __init__.py           # Package marker
│   ├── app.py                # FastAPI app factory
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── entries.py        # Entry CRUD routes
│   │   ├── search.py         # Search routes
│   │   └── status.py         # Status/stats routes
│   └── static/
│       ├── index.html        # Single-page app shell
│       ├── app.js            # Vanilla JS application
│       └── style.css         # Minimal styling
├── cli.py                    # Add `palaia ui` command
```

## UI Design (Phase 1)

```
┌─────────────────────────────────────────────────────────┐
│  🧠 Palaia Memory Explorer          [93 entries] [v2.2] │
├─────────────────────────────────────────────────────────┤
│  🔍 [Search memories...                        ] [Go]   │
│                                                         │
│  Filters: [All Types ▼] [All Projects ▼] [Hot ▼]       │
│                                                         │
│  ┌─────────────────────────────────────────────────────┐│
│  │ 📝 Agent Crash Detection Run             score: 0.87││
│  │    tags: [fact] [auto-capture]    tier: hot          ││
│  │    Agent crash detection cron run at 08:11 UTC...    ││
│  ├─────────────────────────────────────────────────────┤│
│  │ 📋 Deploy warm-up step added              score: 0.72││
│  │    tags: [commitment] [process]   tier: hot          ││
│  │    The deploy workflow now includes a post-deploy... ││
│  └─────────────────────────────────────────────────────┘│
│                                                         │
│  Entry Detail (click to expand)                         │
│  ┌─────────────────────────────────────────────────────┐│
│  │ Title: Agent Crash Detection Run                    ││
│  │ Type: memory  Scope: team  Tier: hot                ││
│  │ Created: 2026-03-17  Decay: 2.37                    ││
│  │ Tags: fact, auto-capture                            ││
│  │ ─────────────────────────────                       ││
│  │ ## Agent Crash Detection Run                        ││
│  │ Active sessions: 12 ...                             ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

## Implementation Steps

1. **Create `palaia/web/` package** with FastAPI app factory
2. **Build REST API routes** reusing existing services (query.py, status.py)
3. **Create static frontend** (index.html + app.js + style.css)
4. **Add `palaia ui` CLI command** — starts uvicorn on localhost:8384
5. **Add `[ui]` optional dep** to pyproject.toml
6. **Test** — verify search, list, get, stats all work via browser
7. **Polish** — responsive layout, dark mode, keyboard shortcuts

## Dependencies (optional install)

```toml
[project.optional-dependencies]
ui = ["fastapi>=0.100", "uvicorn>=0.20"]
```

## Port Convention
- Default: `localhost:8384` (P-A-L-A on phone keypad: 7-2-5-2 → 8384 is close enough and memorable)
- Configurable via `palaia ui --port 9000`

## Security
- Binds to `127.0.0.1` only (no network exposure)
- No auth needed (local-only, same trust model as CLI)
- Read-only in Phase 1 (no mutation endpoints)
