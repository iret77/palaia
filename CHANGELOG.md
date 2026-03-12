# Changelog

All notable changes to Palaia will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-03-11

### Added
- **Document Ingestion (RAG):** `palaia ingest <file/url/dir>` — chunk, embed, and store external documents
- Supported formats: `.txt`, `.md`, `.html`, URLs, directories, `.pdf` (optional `pdfplumber` dep)
- Sliding-window chunking with configurable size and overlap, respecting sentence boundaries
- Source attribution in entry frontmatter (`source`, `source_page`, `chunk_index`, `chunk_total`, `ingested_at`)
- `palaia query --rag` output format for LLM context injection
- `--dry-run` flag for ingestion preview
- ADR-009: RAG Ingestion architecture decision
- 20+ new tests for ingestion, chunking, RAG output, and edge cases

### Copyright
© 2026 byte5 GmbH — MIT License

## [1.0.0] - 2026-03-11

First stable release.

### Features
- WAL-backed, crash-safe persistent memory store
- HOT/WARM/COLD tiering with configurable decay
- Multi-provider semantic search (OpenAI, sentence-transformers, fastembed, ollama)
- Configurable embedding fallback chain
- Projects: organize memory by project with per-project default scope
- Scope system: private, team, public with cascade
- `palaia doctor` for legacy system detection and cleanup guidance
- `palaia warmup` for embedding model preloading
- `palaia migrate` with 4 adapters (smart-memory, flat-file, json, generic-md)
- `palaia export/import` for git-based knowledge sync
- `@byte5ai/palaia` plugin for native OpenClaw memory integration
- 185 tests, fully green CI

### Copyright
© 2026 byte5 GmbH — MIT License

## [0.1.0] - 2026-03-11

### Added
- CLI with commands: `init`, `write`, `query`, `list`, `status`, `gc`, `export`, `import`
- Write-Ahead Log (WAL) for crash-safe writes
- HOT/WARM/COLD tiering with automatic decay-based rotation
- BM25 keyword search (zero dependencies)
- Scope tags: `private`, `team`, `shared:<name>`, `public`
- Content-hash deduplication
- `fcntl`-based file locking for multi-agent safety
- `palaia export` / `palaia import` for cross-team knowledge transfer via git
- Embedding cache infrastructure (`.palaia/index/embeddings.json`)
- CI/CD: GitHub Actions for testing (Python 3.9–3.12) and PyPI release
- Documentation: Getting Started, CLI Reference, Architecture, 7 ADRs
- Community: CONTRIBUTING.md, issue templates, PR template

[0.1.0]: https://github.com/iret77/palaia/releases/tag/v0.1.0
