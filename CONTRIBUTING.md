# Contributing to Palaia

Thanks for your interest in contributing to Palaia!

## Development Setup

```bash
git clone https://github.com/byte5ai/palaia.git
cd palaia
pip install -e ".[dev,fastembed]"
pytest tests/ -v
```

For TypeScript plugin development:
```bash
cd packages/openclaw-plugin
npm install
npx vitest run
```

## Code Style

We use [ruff](https://docs.astral.sh/ruff/) for linting. Configuration is in `pyproject.toml`.

```bash
ruff check palaia/ tests/        # Check
ruff check --fix palaia/ tests/  # Auto-fix
```

Intentional patterns in the codebase:
- `E402` (imports after code): Logger setup before palaia imports — suppressed globally
- `I001` (import sorting): Grouped imports with `# noqa` — suppressed globally
- `F401` with `# noqa`: Backward-compat re-exports (tests import from `palaia.cli`)

## Reporting Bugs

Open a [GitHub Issue](https://github.com/byte5ai/palaia/issues). Include:

- Python version (`python --version`)
- Palaia version (`palaia --version`)
- `palaia doctor --json` output
- Steps to reproduce
- Expected vs actual behavior

## Submitting Pull Requests

1. **Fork** the repository
2. **Create a branch** from `main`: `git checkout -b feat/my-feature`
3. **Write tests** for new functionality
4. **Run the test suite**: `pytest tests/ -v && cd packages/openclaw-plugin && npx vitest run`
5. **Lint your code**: `ruff check palaia/ tests/`
6. **Commit** with a clear message (see Commit Convention below)
7. **Open a PR** against `main`

### PR Requirements

- All tests must pass (Python 3.9-3.12 + TypeScript)
- Ruff lint clean
- New features need tests
- No force pushes to `main`

## Commit Convention

```
feat: add memory compression
fix: resolve race condition in embed-server startup
docs: update MCP server setup guide
perf: use sqlite-vec for native KNN search
release: palaia v2.4 — summary
dev: v2.4.dev1 — testing embed-server auto-start
```

## Versioning

Palaia uses **two-level versioning** (Major.Minor):

```
2.3      Stable release (public, all channels)
2.4      Next stable release
2.3.1    Hotfix (only for critical bugs: security, data loss, broken)
2.4.dev1 Development build (PyPI pre-release, for testing)
2.4b1    Beta (PyPI pre-release, opt-in)
```

**Rules:**
- No patch version (z) in normal development — fixes go into the next minor
- Patch version ONLY for critical hotfixes after a stable release
- Dev builds (`2.4.dev1`) are PyPI pre-releases: `pip install palaia==2.4.dev1`
- Regular `pip install palaia` always gets the latest stable

## Release Process

Releases are managed by maintainers. The process:

1. **Development**: Commits go to `main`, CI runs on every push
2. **Testing**: Dev builds (`v2.4.dev1` tags) publish to PyPI as pre-release
3. **Stable release**: Version bump → tag → PyPI → ClawHub → GitHub Release

### Channel order (important!)

```
1. git push --tags          → triggers PyPI CI
2. Wait for PyPI            → version must appear before next step
3. ClawHub publish          → only AFTER PyPI is live
4. GitHub Release           → last
```

ClawHub and GitHub Release NEVER get dev/beta versions.

### Version files (must all match)

| File | Field |
|------|-------|
| `pyproject.toml` | `project.version` |
| `palaia/__init__.py` | `__version__` |
| `packages/openclaw-plugin/package.json` | `version` |
| `palaia/SKILL.md` | YAML `version` |
| `SKILL.md` (root copy) | YAML `version` |
| `skills/palaia/SKILL.md` | YAML `version` |

### CI Workflows

| Workflow | Trigger | What it does |
|----------|---------|-------------|
| `ci.yml` | Push to main, PRs | Ruff lint + pytest (3.9-3.12) + vitest |
| `publish.yml` | `v*` tags | PyPI publish (all tags) + npm publish (stable only) |

npm is skipped for dev/beta tags (contains `dev`, `b`, or `rc` in tag name).

## Architecture

```
palaia/
  backends/        Storage backends (SQLite, PostgreSQL)
  services/        Business logic (write, query, status, admin)
  doctor/          Diagnostics (checks, fixes, detection)
  mcp/             MCP server (Claude Desktop, Cursor)
  hooks/           OpenClaw hook handlers
  embed_server.py  Background embedding server (stdio + socket)
  embed_client.py  Client for embed-server communication
  search.py        Hybrid search (BM25 + native vector search)
```

### Key design principles

- **No direct model loading in CLI paths**: All embedding operations go through the embed-server. Never import fastembed in a code path that runs on every CLI call.
- **Standard install = optimal performance**: `pip install palaia[fastembed]` must deliver the best possible setup without manual optimization.
- **Embed-server auto-starts**: First CLI query starts the daemon. No manual `palaia embed-server --socket --daemon` needed.
- **sqlite-vec bundled**: Part of `palaia[fastembed]`, not a separate extra.

### Architecture Decision Records

Significant changes should be proposed as an ADR in `docs/adr/`. See existing ADRs for the format.

## Documentation

| Document | Audience | Purpose |
|----------|----------|---------|
| `README.md` | Users + Contributors | Pitch, quickstart, links |
| `palaia/SKILL.md` | AI Agents | Complete operational guide |
| `docs/*.md` | Expert users | Detailed setup and configuration |
| `CONTRIBUTING.md` | Contributors | This file |
| `ARCHITECTURE.md` | Contributors | Module map, data flows |
