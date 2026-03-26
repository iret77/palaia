# Palaia Release Process

## Version Locations (must be in sync)

| File | Field | Example |
|------|-------|---------|
| `pyproject.toml` | `project.version` | `"2.2.0"` |
| `palaia/__init__.py` | `__version__` | `"2.2.0"` |
| `packages/openclaw-plugin/package.json` | `version` | `"2.2.0"` |

## Distribution Channels

| Channel | Package | Trigger | Auth |
|---------|---------|---------|------|
| **PyPI** | `palaia` | `v*` git tag → CI `publish.yml` | `PYPI_TOKEN` secret |
| **npm** | `@byte5ai/palaia` | `v*` git tag → CI `publish.yml` (after PyPI) | `NPM_TOKEN` secret |
| **GitHub** | Release + tag | Manual `gh release create` | gh auth |
| **ClawHub** | `palaia` skill | Manual `clawhub update palaia` | ClawHub auth |

## Pre-Release Checklist

```
[ ] All tests pass: `python -m pytest tests/ -x -q` (expect 1000+ passed)
[ ] TypeScript tests pass: `cd packages/openclaw-plugin && npx vitest run`
[ ] No TODOs/FIXMEs in new code: `grep -rn 'TODO\|FIXME' palaia/ --include='*.py'`
[ ] CHANGELOG.md updated with release notes
[ ] SKILL.md synced to all 3 locations (palaia/, root, packages/openclaw-plugin/skill/)
[ ] Version numbers match in all 3 files (see table above)
```

## Release Steps

### 1. Bump Version

Update all 3 version locations to the new version:

```bash
NEW_VERSION="X.Y.Z"

# pyproject.toml
sed -i "s/^version = \".*\"/version = \"$NEW_VERSION\"/" pyproject.toml

# palaia/__init__.py
sed -i "s/__version__ = \".*\"/__version__ = \"$NEW_VERSION\"/" palaia/__init__.py

# package.json
cd packages/openclaw-plugin
npm version "$NEW_VERSION" --no-git-tag-version
cd ../..
```

### 2. Sync SKILL.md

```bash
cp palaia/SKILL.md SKILL.md
cp palaia/SKILL.md packages/openclaw-plugin/skill/SKILL.md
```

### 3. Commit & Tag

```bash
git add -A
git commit -m "release: v$NEW_VERSION"
git tag "v$NEW_VERSION"
```

### 4. Push (triggers CI publish)

```bash
git push origin main
git push origin "v$NEW_VERSION"
```

This triggers `.github/workflows/publish.yml`:
- **Job 1**: Build Python sdist/wheel → upload to PyPI via twine
- **Job 2** (after Job 1): Run vitest → `npm publish --access public`

### 5. Create GitHub Release

```bash
gh release create "v$NEW_VERSION" \
  --title "Palaia v$NEW_VERSION" \
  --notes-file CHANGELOG.md
```

### 6. Update ClawHub

```bash
clawhub update palaia
```

*Note: This is currently manual. Future automation via CI is planned.*

### 7. Verify

```bash
# PyPI
pip install palaia==$NEW_VERSION && palaia --version

# npm
npm info @byte5ai/palaia version

# GitHub
gh release view "v$NEW_VERSION"
```

## Post-Release

- [ ] Verify `palaia doctor` works on a fresh install
- [ ] Verify `palaia init` creates SQLite store by default
- [ ] Test upgrade path: `pip install palaia==OLD && pip install --upgrade palaia`
- [ ] Monitor GitHub Issues for migration problems

## CI/CD Files

- `.github/workflows/ci.yml` — Tests on push/PR (Python 3.9-3.12 + Node 22)
- `.github/workflows/publish.yml` — Publish on `v*` tag (PyPI + npm)

## Known Gaps (for future improvement)

1. **No automated version bump** — Consider `bump2version` or a Makefile target
2. **No GitHub Release in CI** — `publish.yml` could add `gh release create`
3. **No ClawHub CI step** — Needs ClawHub CLI integration in workflow
4. **No MANIFEST.in validation** — Could add `check-manifest` to CI
