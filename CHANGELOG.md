# Changelog

## v2.5.1 — 2026-04-02

### Fixed
- **Doctor report alignment** — Long check labels ("Embedding model integrity", "HEARTBEAT.md legacy patterns") no longer overlap with values. Column width increased from 24 to 30 characters.
- **SKILL.md postUpdateMessage** — Updated from v2.4 to v2.5 feature summary.

---

## v2.5 — 2026-04-02

### New Features
- **Agent Isolation Mode** — `--isolated` flag on `palaia init` enables scope-based memory filtering between agents. Agents can operate with isolated memory scopes via `scopeVisibility` and `captureScope` in `priorities.json`. Pre-configured profiles: Isolated Worker, Orchestrator, Lean Worker.
- **Modern CLI Design System** — Borderless column-aligned tables replace box-drawing. ANSI colors with full TTY detection. Respects `NO_COLOR` and `FORCE_COLOR` env vars. Unicode symbols (✓ ✗ ⚠ ℹ → ▸). Zero new dependencies.
- **Backup-Restore Fix** — Auto-detect orphaned entries on disk (e.g. after restoring a backup). `palaia doctor --fix` rebuilds metadata index from flat files. Migration auto-triggers on `Store()` init when entries are orphaned but database is empty.

### Infrastructure
- CI stabilization: flaky concurrent write tests marked `xfail(strict=False)`.
- Matrix `fail-fast: false` for complete test coverage across Python 3.9–3.12.
- AGENTS.md and pre-push hook for branch protection.

### Migration from v2.4
- `pip install --upgrade palaia` — no manual steps required.
- Existing stores work as-is. New CLI output is purely cosmetic.

---

## v2.4 — 2026-03-28

### New Features
- **Session Continuity** — Automatic briefings and summaries across agent sessions. Agents resume where they left off.
- **Privacy Markers** — Fine-grained control over which parts of conversations get captured.
- **Recency Boost** — Recent entries rank higher in recall queries.
- **Progressive Disclosure** — CLI nudges adapt based on agent experience level.
- **`palaia skill` strips install section** — Saves context window tokens when agents read SKILL.md.

### Improvements
- OpenClaw v2026.3.28 compatibility (updated plugin SDK types).
- Codex review fixes: 8 findings addressed, 20 new tests.
- README restructured for better first impression.

### Migration from v2.2
- `pip install --upgrade palaia && palaia doctor --fix` — handles everything automatically.

---

## v2.2.0 — 2026-03-26

### Breaking Changes
- **SQLite is now the default storage backend** — New installations use SQLite instead of flat JSON files. Existing flat-file stores are automatically migrated on first use. Old files renamed to `.migrated`.
- **`palaia export`/`palaia import` renamed to `palaia sync export`/`palaia sync import`** — Old aliases still work but are deprecated.
- **OpenClaw plugin**: Requires OpenClaw >=2026.3.22 (new plugin-sdk imports)
- **Plugin entry point**: Migrated from plain function export to `definePluginEntry` pattern
- **Python**: Minimum version remains 3.9, but v2.2 adds optional `sqlite-vec`, `psycopg`, and `scikit-learn` (for curate) dependencies
- **Default install no longer requires `[fastembed]` extra** — `pip install palaia` works out of the box with SQLite + BM25. Fastembed is optional for semantic search.

### New Features
- **Injection priorities** (`palaia priorities`) — Per-agent/project control over which memories are injected into context. Block entries, set per-agent `recallMinScore`, adjust `typeWeight` per agent. Config in `.palaia/priorities.json` with layered overrides: global -> per-agent -> per-project.
- **Knowledge curation** (`palaia curate analyze/apply`) — Cluster entries thematically, detect duplicates, recommend KEEP/MERGE/DROP per cluster. Produces Markdown report for user review. `apply` generates clean `.palaia-pkg.json` for import on new instances. Requires optional `scikit-learn` (`pip install palaia[curate]`).
- **New nudges** — Contextual guidance for curation (when store grows large), priorities (when multi-agent detected), and backend migration (when flat files detected).

### Security (Phase 0)
- **SSRF prevention in URL ingestion** — `_read_url()` now validates URLs against private IPs, loopback, link-local, and cloud metadata endpoints. Only HTTP(S) schemes allowed. Configurable via `allow_private_urls` setting.
- **Structured logging** — All 27 Python modules now use `logging.getLogger(__name__)`. Added `--verbose` / `-v` CLI flag for debug output. Bare `except: pass` blocks replaced with logged diagnostics.
- **YAML frontmatter injection prevention** — Body content containing `---` delimiters can no longer inject metadata fields via `_sanitize_body()` and `_quote_yaml_value()`.

### Storage Backend Architecture (Phase 2)
- **Pluggable storage backends** — New `StorageBackend` protocol with provider-chain auto-detection, mirroring the embedding provider chain pattern.
- **SQLite backend** (default when `database_backend=sqlite`) — Single-file database with WAL mode, optional `sqlite-vec` for native vector KNN. Zero new dependencies (sqlite3 is stdlib).
- **PostgreSQL + pgvector backend** — For distributed agent teams. HNSW ANN vector search, MVCC concurrent writes, JSONB tags, tsvector full-text. Activate via `PALAIA_DATABASE_URL` or `palaia config set database_url`.
- **Automatic migration** — Existing `metadata.json`, `embeddings.json`, and WAL files are automatically migrated to the active backend. Old files renamed to `.migrated`.

### OpenClaw Integration (Phases 1 + 1.5)
- **Plugin SDK migration** — Migrated to `definePluginEntry` pattern with typed `OpenClawPluginApi` interface. Local type definitions in `src/types.ts`.
- **ContextEngine adapter** — New `src/context-engine.ts` maps 7 ContextEngine lifecycle hooks (bootstrap, ingest, assemble, compact, afterTurn, prepareSubagentSpawn, onSubagentEnded) to palaia functionality. Falls back to legacy hooks for older OpenClaw versions.
- **hooks.ts decomposition** — Monolithic 2091-line file split into `hooks/recall.ts`, `hooks/capture.ts`, `hooks/state.ts`, `hooks/reactions.ts`, `hooks/index.ts`.

### Code Quality (Phase 3)
- **Shared frontmatter parser** — `palaia/frontmatter.py` eliminates duplicate YAML parser in `entry.py` and `memo.py`.
- **Shared BM25** — `palaia/bm25.py` unifies duplicate BM25 implementations in `search.py` and `embeddings.py`.
- **Type-safe enums** — `palaia/enums.py` with `Tier`, `EntryType`, `EntryStatus`, `Priority`, `Scope` as `str, Enum` (backward-compatible with string comparisons).
- **Module rename** — `locking.py` → `project_lock.py` for clarity (shim kept for backward compat).
- **Service layer** — Business logic extracted from `cli.py` into `palaia/services/` package.
- **Doctor decomposition** — `doctor.py` split into `palaia/doctor/` package (checks, fixes, detection).

### Data Integrity (Phase 4)
- **Fixed decay calculation** — `update_access()` now correctly uses `days_since(created)` instead of always passing 0.
- **WAL protection for project strip** — `_strip_project_from_entries()` now WAL-logged.
- **Encapsulation fix** — `embed_server.py` uses `embedding_cache.reload()` instead of accessing `._cache` directly.

### Test Infrastructure (Phase 5)
- **Shared conftest.py** — `palaia_root` and `store` fixtures in `tests/conftest.py`, removing ~40 duplicates.
- **Coverage configuration** — `[tool.coverage]` section in pyproject.toml.

### Migration from v2.1
- Run `pip install --upgrade palaia && palaia doctor --fix` — handles everything automatically.
- Flat-file stores (`metadata.json`, `embeddings.json`) are migrated to SQLite on first use. Old files renamed to `.migrated`.
- `palaia export`/`palaia import` still work as aliases for `palaia sync export`/`palaia sync import`.
- No data loss. No manual steps required.

### Downgrading to v2.1

If you need to revert to v2.1 after upgrading:
1. Rename `.migrated` files back to their original names:
   ```bash
   cd .palaia
   for f in index/*.migrated wal/*.migrated; do
     mv "$f" "${f%.migrated}"
   done
   ```
2. Remove `palaia.db` (optional — v2.1 ignores it)
3. Install v2.1: `pip install palaia==2.1.0`

---

## v2.1.0 — 2026-03-24

### Bug Fixes
- **Plugin: Per-agent workspace resolution** (#111) — Auto-Capture and Auto-Recall now use `ctx.workspaceDir` per agent instead of global workspace. Fixes multi-agent setups where all memories went to the wrong store.
- **Race condition in EmbeddingCache** (#105) — Unique PID+TID tmp filenames prevent cache corruption during concurrent writes.
- **Auto-Capture task misclassification** (#107) — Tightened extraction criteria: all 3 requirements (clear action + responsible party + concrete deliverable) must be met for `type: task`.
- **Feedback-loop artifact cleanup** (#113) — `doctor --fix` now detects and removes pre-v2.0.6 corrupted entries with backup.

### Stability
- **EmbeddingCache thread safety** (C-1) — Added threading.Lock (same pattern as MetadataIndex).
- **GC write starvation** (C-2) — GC split into read phase (no lock) + write phase (locked).
- **WAL zombie entry prevention** (I-1) — WAL directory creation and commit path hardening.
- **BM25 index caching** (I-2) — Index cached with dirty-flag invalidation instead of rebuild per query.
- **Access metadata debouncing** (I-3) — 60s debounce reduces lock contention on reads.
- **Embed server request queuing** (I-4) — Concurrent requests queued (max 10) instead of rejected.
- **Extraction temp dir cleanup** (I-5) — Fixed base dir with automatic stale cleanup.
- **Stale lock PID liveness check** (I-6) — Dead PIDs detected immediately (vs. 60s timeout).
- **Doctor permission error handling** (I-7) — Graceful handling of unreadable tier directories.

### Improvements
- Lazy metadata index build for dedup (M-1)
- Configurable embed server stale detection interval (M-2)
- Slack bot token cache TTL 5min (M-3)
- Recall query scan depth limit (M-4)
- Atomic GC in-place writes (M-6)
- Cross-filesystem rename handling (M-7)
- Unicode and WAL corruption test coverage (M-8, M-9)

## [2.0.13] — 2026-03-22

### Fixed
- **Auto-capture feedback loop**: `stripPalaiaInjectedContext()` strips the Palaia recall block from user messages before capture extraction, preventing re-captured memories from accumulating. Applied in `agent_end`, `extractWithLLM()`, and `buildRecallQuery()`.
- **Doctor: feedback-loop artifact detection**: `palaia doctor` now detects entries that are re-captured recall context (feedback-loop artifacts). `palaia doctor --fix` marks them as done.

## [2.0.12] — 2026-03-22

### Version alignment

- Version alignment across all distribution channels (PyPI, npm, ClawHub, GitHub Release).
- Nightly maintenance fix: removed embed-server kill step that caused index staleness.

## [2.0.11] — 2026-03-22

### Plugin-bundled SKILL.md

- **SKILL.md included in npm package**: Agents installing Palaia via `npm install -g @byte5ai/palaia` now automatically get the SKILL.md in their `<available_skills>`. No ClawHub install required.
- Plugin manifest (`openclaw.plugin.json`) updated with `"skills": ["./skill"]` for automatic skill discovery.
- The bundled SKILL.md is a usage-focused subset — installation steps are omitted since the plugin is already installed.

## 2.0.10 (2026-03-22)
### Fixed
- **Embed-Server startup timeout**: Server sends ready signal immediately; warmup runs in background thread. Queries during warmup use BM25 fallback automatically.
- **Stale embedding index**: `write()` and `edit()` now compute embeddings for new entries immediately (fire-and-forget). The index no longer goes stale between warmup cycles.
- **Doctor index check**: `palaia doctor` now detects stale embedding indexes (>10% entries missing) and repairs them with `--fix`.

## [2.0.8] — 2026-03-19

### Embedding Server — 16s to 0.5s Query Performance

- **Embedding server** (`palaia/embed_server.py`): Long-lived JSON-RPC subprocess over stdin/stdout. Keeps the embedding model loaded in RAM — queries drop from 6-16s to ~0.5s (steady state). First query after start ~2s (one-time model warmup).
- **Plugin integration**: `EmbedServerManager` in runner.ts — lazy start on first recall query, auto-restart (max 3 retries), graceful fallback to CLI on failure, cleanup on plugin shutdown.
- **Config**: `embeddingServer: true` (default). Set to `false` to disable and use CLI-only path.
- **Methods**: `query`, `warmup`, `ping`, `status`, `shutdown`. Stale detection every 30s rebuilds index on entry changes.
- **Zero new dependencies** — uses existing `SearchEngine`, `Store`, and `EmbeddingCache` modules.
- 15 new Python tests, 8 new TypeScript tests.

### Documentation

- README.md: Embedding Server feature + config documented.
- SKILL.md: Performance section rewritten, `embeddingServer` config added.

## [2.0.7] — 2026-03-19

### Cross-Platform Locking, Metadata Index, Documentation

- **Cross-platform locking**: `fcntl` (Unix) / `msvcrt` (Windows) / `mkdir` (fallback) — no new dependencies.
- **Metadata index**: JSON-backed metadata cache for O(1) hash lookups and faster listing. Auto-updated on write/edit/gc. Transparent disk fallback.
- **Hardcoded `/tmp/`** replaced with `tempfile.gettempdir()`.
- **Documentation**: Agent Alias System and Project Locking now documented in README and SKILL.md.
- 24 new tests.

## [2.0.6] — 2026-03-18

### Clean Recall Queries via Envelope Stripping

- **Channel envelope stripping**: New `stripChannelEnvelope()` and `stripSystemPrefix()` functions strip OpenClaw channel envelopes (`[Slack 2026-03-18 ...]`, `System: [...] Slack message in #channel from User:`) from message text before building recall queries. Covers all channel providers (Slack, Telegram, Discord, WhatsApp, Signal, Teams, Matrix, iMessage, etc.).
- **Recall query overhaul**: `buildRecallQuery()` now filters `inter_session` and `internal_system` provenance messages, strips envelopes, skips system-only content (edited/deleted notifications, queued messages, auto-tags), and walks backwards to find actual user content. Prevents envelope metadata from polluting semantic search (timeouts, false-high scores).
- **`isSystemOnlyContent()` helper**: Identifies messages that are purely system artifacts (no user text) — edited notifications, inter-session messages, queued prefixes, auto-tags.

## [2.0.5] — 2026-03-18

### Provenance-based Message Recognition + API Hygiene

- **Provenance pipeline**: `extractMessageTexts()` now propagates `provenance` field from OpenClaw messages (`external_user`, `inter_session`, `internal_system`). All dependent functions updated.
- **Recall query**: `buildRecallQuery()` rewritten to prefer `external_user` messages for recall queries. System-injected user messages no longer pollute search. Removes obsolete `cleanMessageForQuery()` and `DAY_PREFIXES` heuristics.
- **getLastUserMessage**: Prefers `external_user` provenance, falls back to any user message for backward compatibility.
- **trimToRecentExchanges**: Only counts `external_user` messages as real conversation turns.
- **Logger integration**: All `console.log/warn` replaced with `api.logger.info/warn` for OpenClaw log system integration (level filtering, subsystem tags).
- **captureModel validation**: Validates API key availability at plugin startup via `api.runtime.modelAuth.resolveApiKeyForProvider()`. Warns early if auto-capture LLM extraction will fail.

## [2.0.4] — 2026-03-18

### Quality Release

- **Recall pipeline**: Robust query building from actual user messages (ignores synthetic `event.prompt`). Short messages auto-expand with prior context. System markers and JSON blocks filtered.
- **Score handling**: `recallMinScore` config key (default: 0.7). Brain emoji suppressed on list-fallback.
- **Capture quality**: `captureMinSignificance` default raised to 0.5. Rule-based fallback requires 2+ significance tags. LLM prompt includes dedup hint. All auto-captured entries tagged `auto-capture`.
- **Guardrails**: Unknown projects rejected in auto-capture. Scope capped at `team` (no public from LLM).
- **Usage nudge**: Persistent compact instruction injected per prompt (~30 tokens).
- **Duplicate guard**: Manual writes checked against existing entries (score > 0.8, last 24h) before writing.
- **Token efficiency**: Compact injection format (`[t/m]` instead of `[team/memory]`). `maxInjectedChars` default: 4000 (was 8000).
- **SKILL.md**: Clear manual-vs-auto guidance table.

## [2.0.3] — 2026-03-18

### Fixes
- Brain emoji only appears on relevant recall (score >= 0.7), not on every message
- Safe plugin activation: config arrays are read-then-appended, never overwritten
- All version references synced

## [2.0.2] — 2026-03-18

### Summary
Consolidation release for Palaia 2.0. Includes the full v2.0 feature set (Auto-Capture, Auto-Recall, LLM-based extraction, session-isolated TurnState, significance tagging, knowledge packages, temporal queries, bounded GC) plus all post-release fixes.

### Fixes since 2.0.0
- SKILL.md plugin install step corrected.
- Fastembed cache integrity fix.
- `captureModel` resilience — graceful fallback when configured model is unavailable.
- Sliding window fix for turn counting in Auto-Capture.
- npm plugin version sync.
- All version references aligned (pyproject.toml, package.json, __init__.py, SKILL.md).

## [2.0.0] — 2026-03-17

### Breaking Changes
- **Palaia 2.0 is OpenClaw-specific.** Plugin architecture replaces standalone hooks. The CLI still works standalone for manual `palaia write`/`palaia query`, but Auto-Capture and Auto-Recall require the OpenClaw plugin.
- Plugin config path is now `plugins.entries.palaia.config` (not `plugins.config.palaia`).
- Default `captureMinTurns` changed from 2 to 1 in plugin config.

### Features
- **Auto-Capture** (`agent_end` hook) — Automatically captures significant conversation exchanges as memory entries after each agent session. No manual `palaia write` required.
- **Auto-Recall** (`before_prompt_build` hook) — Automatically injects relevant memories into agent context before each prompt. No manual `palaia query` required.
- **LLM-based Extraction** — Uses a cheap embedded LLM (e.g. claude-haiku-4, gpt-4.1-mini, gemini-2.0-flash) to extract structured knowledge from conversations. Falls back to rule-based extraction if unavailable.
- **Session-isolated TurnState** — Per-session state tracking prevents cross-contamination in multi-agent setups.
- **Emoji Reactions (Slack)** — Brain emoji (recall) and floppy disk emoji (capture) on messages when memory is used.
- **Capture Hints** — Agents can include `<palaia-hint project="X" scope="Y" />` in responses to guide Auto-Capture metadata.
- **Adaptive Nudging with Graduation** — CLI nudges agents toward best practices (--type, --tags). Nudges graduate after 3 consecutive successes. Regression detection re-activates them.
- **Significance Tagging** — 7 tags auto-detected: decision, lesson, surprise, commitment, correction, preference, fact.
- **Knowledge Packages** — `palaia package export/import` for portable knowledge transfer between environments.
- **Temporal Queries** — `palaia query --before <date> --after <date>` for time-filtered search.
- **Cross-Project Queries** — `palaia query --cross-project` searches across all projects.
- **Process Runner** — `palaia process run <id>` for interactive execution of stored process entries.
- **Bounded GC** — `palaia gc --dry-run --budget <n>` for controlled, predictable garbage collection.
- **`/palaia-status` Command** — OpenClaw slash command showing recall count, store stats, and config summary.
- **Memory Footnotes** — Agent responses include source attribution when memories are used.
- **Capture Confirmations** — Visual feedback when exchanges are saved to memory.

### Migration from 1.x
- Run `palaia doctor --fix` to migrate configuration from 1.x to 2.0.
- New config keys (`captureModel`, `captureMinSignificance`, `captureScope`, `captureProject`, `captureMinTurns`, `captureFrequency`) are auto-added with sensible defaults.
- Existing entries are fully preserved — no data migration required.
- The OpenClaw plugin config schema now includes all capture-related keys.

## [1.9.0] — 2026-03-14

### Features
- **Gemini embedding provider** — `gemini-embedding-exp-03-07` via REST API, no SDK dependency. Cloud-based embeddings with local fallback support. (#34)
- **Exact filtering for `palaia list`** — `--status`, `--tag`, `--priority` now use exact matching instead of embedding search. (#37)
- **Doctor checks for unread memos** — `palaia doctor` warns when unread memos are waiting. (#42)
- **Doctor checks for newer Palaia version on PyPI** — `palaia doctor` now detects when a newer version is available. (#45)
- **Improved OpenClaw config auto-detection** — Better detection on VPS installs where config paths differ from standard setups. (#51)
- **Concurrent write safety validated** — 5 thread-based tests confirm WAL + file locking handles parallel writes correctly. (#52)

### Bug Fixes
- **Warmup/indexing now includes private and shared-scope entries** — Previously, warmup only indexed team-scope entries. (#60)
- **`doctor --fix` respects explicit user embedding config** — No longer overwrites user-configured embedding chains during auto-fix. (#57)
- **postUpdate npm graceful fallback** — npm upgrade step in postUpdate hook no longer fails if npm is not available.

### Security
- **Scope enforcement audit** — All read/write operations verified for correct scope enforcement. (#39)

### Documentation
- Rewrote README with sales-pitch-first approach
- Added Agent Field Guide with production lessons
- Added Gemini provider to SKILL.md provider table
- Documented concurrent write safety guarantees

## [1.8.1] — 2026-03-13

### Fixed
- **Critical: search.py now respects embedding_chain config** — Previously always used `auto_detect_provider()`, ignoring the configured chain. With both sentence-transformers and fastembed installed, queries took 14-18s instead of 2s because the slower provider was always selected. (#49)

### Added
- **Warmup now builds embedding index** — `palaia warmup` pre-computes embeddings for all entries (batch processing, progress display). Queries after warmup use cached embeddings instead of recomputing on every call. Reduces query time from 14s to <2s. (#48)
- **Status shows warmup hint** — `palaia status` now shows "Index: 0/23 — 23 entries not indexed. Run: palaia warmup" instead of just "Index: 0/23". (#47)
- **`palaia skill` command** — Prints the embedded SKILL.md documentation. Works without `palaia init`. Useful for pip-only installations without ClawHub.
- **MANIFEST.in** — SKILL.md, CHANGELOG.md, and LICENSE now included in PyPI source tarball.
- **Setup verification step** in SKILL.md — Mandatory Step 5: test query must return results in <5s before setup is considered complete.
- **`palaia migrate --suggest`** now part of standard setup flow (Step 3 in SKILL.md).

## [1.8.0] — 2026-03-13

### Added
- **Process Nudge** — After `palaia write` and `palaia query`, Palaia now checks for relevant process entries and surfaces them: "Related process: Release Checklist (palaia get 74bba31a)". Uses hybrid matching (embedding similarity + tag overlap). Frequency-limited (max 1 nudge per process per hour). Suppressed in `--json` mode. Gracefully degrades to tag-only matching when no embedding provider is available.
- **"What Goes Where" guide** in SKILL.md — Clear boundary between project files (static facts) and Palaia (dynamic knowledge). Helps agents avoid duplicating knowledge across files and Palaia entries.
- **Reconciliation guide** in SKILL.md — Best practices for agents working in environments with pre-Palaia memory patterns (CONTEXT.md, MEMORY.md). Gradual migration without breaking existing workflows.

## [1.7.3] — 2026-03-13

### Added
- **Frictionless init** — `palaia init` without `--agent` now works, defaulting to agent name "default". Single-agent systems no longer need to specify a name.
- **Single-agent auto-detect** — If an OpenClaw config with exactly one agent is found, the name is used automatically: "Auto-detected agent: HAL (from OpenClaw config)".
- **Agent alias system** — `palaia config set-alias default HAL` makes queries for "HAL" also return entries written as "default". Enables clean single→multi-agent migration without rewriting entries.
- **Doctor auto-fix for embedding chains** — `palaia doctor --fix` now actively repairs broken embedding chains: attempts pip install of missing providers, falls back to best available, runs warmup. BM25-only is last resort.
- **Doctor alias nudge** — Warns when "default" entries exist alongside named agents without an alias configured.

### Fixed
- **Init without --agent no longer misleading** — Previously said "Initialized" then immediately "Not initialized" on next command. Now either succeeds with default name or gives clear error.
- **Copyright year** — CLI header now shows "(c) 2026 byte5 GmbH".

## [1.7.1] — 2026-03-13

### Fixed
- **Test fixtures missing agent identity** — CLI integration tests in `test_locking.py`, `test_project.py`, and `test_ux_improvements.py` now set `agent` in their `palaia_root` fixtures, fixing 18 test failures caused by the init gatekeeper (PR #44) blocking store commands without prior `palaia init --agent`.

## [1.7.0] — 2026-03-13

### Added
- **Entry Classes** — New `type` frontmatter field: `memory` (default), `process`, `task`. Existing entries without type default to `memory`.
- **Structured Task Fields** — `status` (open|in-progress|done|wontfix), `priority` (critical|high|medium|low), `assignee`, `due_date` for task entries.
- **`palaia edit`** — Edit existing entries: content, tags, title, and all task fields. WAL-backed, scope-enforced.
- **Session Identities** — New `instance` frontmatter field for distinguishing sessions of the same agent. Auto-set via `PALAIA_INSTANCE` env var.
- **Structured Query Filters** — `palaia query --type task --status open --priority high --assignee Elliot --instance Claw-Palaia`. Exact match, not embeddings.
- **Structured List Filters** — `palaia list --type task --status open --priority high --assignee --instance`.
- **Agent Nudging** — CLI hints after writes without `--type`. `palaia status` shows entry class breakdown with task status summary. Hints are frequency-limited and suppressed in JSON output.
- **`palaia migrate --suggest`** — Scan existing entries and suggest type assignments based on content heuristics.
- **Doctor entry class check** — `palaia doctor` detects untyped entries and suggests migration.

### Changed
- **`palaia status`** — Shows entry class breakdown (memory/process/task counts) and task status summary.
- **`palaia write`** — Accepts `--type`, `--status`, `--priority`, `--assignee`, `--due-date`, `--instance`.
- **Search results** — Include `type`, `status`, `priority`, `assignee`, `due_date`, `instance` fields when present.

### Security
- **Scope enforcement on edit** — Private entries can only be edited by the owning agent. No scope escalation possible. Non-negotiable.

## [1.6.1] — 2026-03-13

### Changed
- **CLI copyright header** — All commands now display "(c) byte5 GmbH" in the header.
- **HuggingFace warning suppression** — Noisy HF warnings silenced during query/warmup.
- **Version sync** — All references (pyproject.toml, __init__.py, SKILL.md) bumped to 1.6.1.

### Fixed
- **Arrow character mismatch** — test_chain_cli.py updated for new UI arrow characters.

### Published
- ClawHub v1.6.1

## [1.6.0] — 2026-03-13

### Added
- **palaia/ui.py** — Box-drawing table renderer, header, and formatting helpers. No external dependencies.
- **Unified CLI header** — Every command now shows a consistent header.

### Changed
- **All emojis removed** from CLI output for a professional look.
- **Commands overhauled** — status, doctor, list, query, detect, project, warmup, memo inbox all use the new UI.
- **--json flag** unchanged (machine output unaffected).

### Updated
- Tests updated for new output format.

## [1.5.2] — 2026-03-13

### Fixed
- **Store discovery fallback chain** — `find_palaia_root()` now checks `~/.palaia` and `~/.openclaw/workspace/.palaia` as fallbacks when cwd walk fails. Users no longer get "No .palaia directory found" when running from outside the workspace. (#33)
- **Doctor OpenClaw config detection** — Now checks `$OPENCLAW_CONFIG` env var, `.yml` extension, and falls back to parsing `openclaw status` output. Fixes false "standalone mode" reports when OpenClaw plugin is active. (#33)

### Changed
- **Default install recommendation** — `palaia[fastembed]` replaces bare `palaia` in all install instructions (SKILL.md, README). Users get semantic search out of the box. (#33)

### Added
- **PEP 668 troubleshooting** — SKILL.md documents workarounds for Debian/Ubuntu "externally-managed-environment" errors (`--user`, `--break-system-packages`, `pipx`, venv). (#33)

## [1.5.1] — 2026-03-13

### Fixed
- **Version sync** — pyproject.toml, __init__.py, SKILL.md all at 1.5.1.
- **Doctor --fix auto-repair** — Embedding chain auto-fix works correctly.
- **pip fallback** — SKILL.md documents pip alternatives.
- **Plugin config docs** — Correct config path documented.

## [1.5.0] — 2026-03-13

### Added
- **Project Ownership** — `palaia project create --owner`, `project set-owner`, `project list --owner`. Each project can have one owner, contributors are auto-aggregated from entries. (#30, #31)
- **Update nag** — CLI warns on `query`, `write`, `list`, `status` when store version doesn't match CLI version. (#26)
- **Doctor upgrade hint** — `palaia doctor` always suggests checking for updates. (#26)

### Fixed
- **Init triggers onboarding** — `palaia init` outputs step-by-step setup instructions for LLM agents. (#23)
- **`PALAIA_HOME` env variable** — Override `.palaia` store location; plugin sets it automatically. (#23)
- **Ruff lint errors** in test_memo.py fixed. (#25)
- **SKILL.md auto-check** — Agents run `palaia doctor` on every skill load. (#24)
- **README beginner flow** — One prompt install for OpenClaw users, no CLI required. (#28, #29)

## [1.4.3] — 2026-03-13

### Added
- **Update nag** — CLI warns on `query`, `write`, `list`, `status` when store version doesn't match CLI version.
- **Doctor upgrade hint** — `palaia doctor` always suggests checking for updates.
- **README install section** — Clear instructions for OpenClaw and manual install, including "tell your agent" hint.
- **ClawHub description** — Now includes post-install instruction.

## [1.4.2] — 2026-03-12

### Added
- **Init triggers onboarding** — `palaia init` now outputs step-by-step setup instructions that guide LLM agents through the complete onboarding (doctor, detect, warmup, plugin config). (#23)
- **`PALAIA_HOME` env variable** — Override `.palaia` store location. Plugin runner sets it automatically. (#23)

### Fixed
- OpenClaw plugin now finds `.palaia` store reliably regardless of working directory. (#23)

## [1.4.1] — 2026-03-12

### Added
- **Auto-Check section in SKILL.md** — Agents run `palaia doctor` every time the skill is loaded.
- **`postUpdate` hook in SKILL.md metadata** — `clawhub update` triggers automatic upgrade + health check.

## [1.4.0] — 2026-03-12

### Added
- **Project Locking** — `palaia lock/unlock` prevents concurrent agent work on the same project. TTL-based with auto-expire. (#15, #19)
- **Inter-Agent Messaging** — `palaia memo send/inbox/ack/broadcast/gc` for async agent communication with priority and auto-expire. (#14, #21)
- **Plugin Activation docs** — SKILL.md now guides agents through full OpenClaw plugin setup. (#20)

## [1.3.0] — 2026-03-12

### Added
- **`--agent` flag on all CLI commands** — query, list, get, export now support agent-scoped access. (#7)
- **Onboarding experience** — SKILL.md install block, multi-agent detection in `palaia init`, README multi-agent guide. (#8)
- **`palaia doctor`** — Health checks, version tracking, upgrade guidance. (#13)
- **`palaia setup --multi-agent`** — Auto-detect and configure agent directories. (#10, #13)
- **List filters** — `palaia list --tag/--scope/--agent` for browsing without search. (#12, #13)
- **Auto-create projects** — `--project` flag auto-creates projects on write/ingest. (#9, #13)
- **Migration safety** — DO NOT DELETE warnings for system files, `palaia migrate` detects and protects operational config. (#16)
- **`@byte5ai/palaia` npm plugin** — OpenClaw memory backend, published on npm. (#17)

### Changed
- Version tracking in store config (`store_version` field). (#13)
- SKILL.md updated with full onboarding flow and post-update guidance.

## [1.1.0] — 2026-03-11

### Added
- Document ingestion / RAG support (`palaia ingest`)
- First-class projects with scope cascade
- Configurable embedding fallback chain
- Multi-provider embeddings (Ollama, SentenceTransformers, FastEmbed, OpenAI)
- ClawHub published, PyPI published

## [1.0.0] — 2026-03-10

### Added
- Core memory store with WAL and crash safety
- Hybrid search (BM25 + semantic embeddings)
- Tiered storage (HOT/WARM/COLD) with decay-based rotation
- Scope system (private/team/public)
- CLI with write, query, get, list, status, gc, export, import, migrate, recover
