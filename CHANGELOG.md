# Changelog

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
