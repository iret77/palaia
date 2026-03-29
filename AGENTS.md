# Agent Instructions

These rules apply to all AI agents working on this repository (Codex, Claude, Copilot, etc.).

## Git Workflow

- **Never push directly to `main`.** All changes go through feature branches and pull requests.
- **Branch naming:** `feat/`, `fix/`, `refactor/`, `docs/`, `chore/` prefixes.
- **Conventional commits:** `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `release:`, `dev:`.
- **Never force-push** to any shared branch.
- **Never commit secrets** (.env, API keys, tokens, credentials).
- **Never skip hooks** (`--no-verify`).

## Pull Requests

- Keep PR titles short (<70 chars), use conventional prefix.
- One logical change per PR.
- Ensure tests pass before requesting merge.

## Project

- **Python + TypeScript** monorepo: `palaia/` (Python CLI/core) + `packages/openclaw-plugin/` (TS plugin).
- Tests: `python3 -m pytest tests/ -q` and `cd packages/openclaw-plugin && npx vitest run`.
- Dev server runs on **devhost** (Tailscale) — never use `localhost`.

## Pre-push Hook

A `.hooks/pre-push` hook blocks direct pushes to `main`/`master`. Override only when explicitly instructed:
```bash
ALLOW_PUSH_TO_MAIN=1 git push origin main
```
