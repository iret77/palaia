# @palaia/openclaw

**Palaia memory backend for OpenClaw.**

Replace OpenClaw's built-in `memory-core` with Palaia — local, cloud-free, WAL-backed agent memory with tier routing and semantic search.

## Installation

```bash
# Install Palaia (Python CLI)
pip install palaia

# Install the OpenClaw plugin
openclaw plugins install @palaia/openclaw
```

## Configuration

Activate the plugin by setting the memory slot in your OpenClaw config:

```json5
// openclaw.config.json5
{
  plugins: {
    slots: { memory: "palaia" }
  }
}
```

Restart the gateway after changing config:

```bash
openclaw gateway restart
```

### Plugin Options

All options are optional — sensible defaults are used:

```json5
{
  plugins: {
    config: {
      palaia: {
        binaryPath: "/path/to/palaia",  // default: auto-detect
        workspace: "/path/to/workspace", // default: agent workspace
        tier: "hot",                      // default: "hot" (hot|warm|all)
        maxResults: 10,                   // default: 10
        timeoutMs: 3000,                  // default: 3000
        memoryInject: false,              // default: false (inject HOT into context)
        maxInjectedChars: 4000,           // default: 4000
      }
    }
  }
}
```

## Agent Tools

### `memory_search` (always available)

Semantically search Palaia memory:

```
memory_search({ query: "deployment process", maxResults: 5, tier: "all" })
```

### `memory_get` (always available)

Read a specific memory entry:

```
memory_get({ path: "abc-123-uuid", from: 1, lines: 50 })
```

### `memory_write` (optional, opt-in)

Write new memory entries. Enable per-agent:

```json5
{
  agents: {
    list: [{
      id: "main",
      tools: { allow: ["memory_write"] }
    }]
  }
}
```

Then agents can write:

```
memory_write({ content: "Important finding", scope: "team", tags: ["project-x"] })
```

## Features

- **Zero breaking changes** — Drop-in replacement for `memory-core`
- **WAL-backed writes** — Crash-safe, recovers on startup
- **Tier routing** — HOT → WARM → COLD with automatic decay
- **Scope isolation** — private, team, shared:X, public
- **BM25 search** — Fast local search, no external API needed
- **HOT memory injection** — Opt-in: inject active memory into agent context
- **Auto binary detection** — Finds `palaia` in PATH, pipx, or venv

## Architecture

```
OpenClaw Agent
  └─ @palaia/openclaw (plugin)
       └─ palaia CLI (subprocess, --json)
            └─ .palaia/ (local storage)
                 ├─ hot/    (active memory)
                 ├─ warm/   (recent, less active)
                 ├─ cold/   (archived)
                 ├─ wal/    (write-ahead log)
                 └─ index/  (search index)
```

## Development

```bash
# Clone the repo
git clone https://github.com/iret77/palaia.git
cd palaia/packages/openclaw-plugin

# Install deps
npm install

# Run tests
npx vitest run
```

## License

MIT
