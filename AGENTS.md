# Agent Instructions

These rules apply to all AI agents working on this repository (Codex, Claude, Copilot, etc.).

## Git Workflow

- **Never push directly to `main`.** All changes go through feature branches and pull requests.
- **Branch naming:** `feat/`, `fix/`, `refactor/`, `docs/`, `chore/` prefixes.
- **Conventional commits:** `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `release:`, `dev:`.
- **Never force-push** to any shared branch.
- **Never commit secrets** (.env, API keys, tokens, credentials).
- **Never skip hooks** (`--no-verify`).

## Bugfix Verification

Every bugfix **must** include a regression test that reproduces the **exact user-reported symptom**, not just a related scenario.

1. **Reproduce first:** Before writing the fix, write a test that fails with the exact symptom the user described. "User does X, expects Y, gets Z" → the test must assert Y and currently produce Z.
2. **Fix, then re-run:** Apply the fix, confirm the test passes.
3. **Green suite is necessary, not sufficient:** All existing tests passing does not prove the reported bug is fixed. The regression test is what proves it.

> **Why this rule exists:** v2.7.3 shipped a doctor fix that used `all_entries_unfiltered()` instead of `all_entries()`. All tests were green, but the actual bug (phantom stale tasks invisible to `palaia list`) was not fixed because no test reproduced the specific scenario (private scope + different agent).

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
