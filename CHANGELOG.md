# Changelog

## [1.7.2] — 2026-03-13

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
