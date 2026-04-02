# Multi-Agent Setup

palaia supports multiple agents sharing a single store with controlled visibility.

## Agent Identity

Every agent needs a name:

```bash
# Via environment variable (recommended for multi-agent)
export PALAIA_AGENT=alice

# Or via config (single-agent setups)
palaia init --agent alice
```

Without an agent name, palaia uses "default". This works fine for single-agent setups.

## Scopes

Every entry has a scope that controls who can read and edit it:

| Scope | Who can read | Who can edit | Default |
|-------|-------------|-------------|---------|
| `team` | All agents | All agents | Yes |
| `private` | Only the owner (+ aliases) | Only the owner | No |
| `public` | All agents + exportable | All agents | No |
| `shared:<name>` | Agents in the shared group | Agents in the group | No |

```bash
palaia write "Secret rotation procedure" --scope private
palaia write "Team coding standards" --scope team
palaia write "Public API docs" --scope public
```

## Agent Aliases

An agent can have aliases — useful when the same person uses different agent identities:

```bash
palaia config set aliases '{"alice": ["alice-dev", "alice-review"]}'
```

Now `alice`, `alice-dev`, and `alice-review` can all read each other's private entries.

## Instance Identity

For tracking which session created what:

```bash
export PALAIA_INSTANCE=laptop-session-1
```

This tags entries with the instance, useful for filtering:
```bash
palaia query "bugs" --instance laptop-session-1
```

## Inter-Agent Messaging

Agents can send memos to each other:

```bash
palaia memo send bob "Deploy is ready for review"
palaia memo inbox                   # Check incoming
palaia memo ack <memo-id>           # Acknowledge
palaia memo broadcast "New release" # Notify all agents
```

## Injection Priorities

Control which memories get injected into an agent's context:

```bash
palaia priorities                          # Show current priorities
palaia priorities block <entry-id>         # Block entry from injection
palaia priorities set <entry-id> high      # Set priority level
```

Priority levels work per-agent and per-project.

## Setting Up Additional Agents

When a new agent joins an existing workspace:

1. **Set agent identity:**
   ```bash
   export PALAIA_AGENT=new-agent-name
   ```

2. **Add palaia skill** (via ClawHub or manual config)

3. **Verify connectivity:**
   ```bash
   palaia doctor
   palaia memo inbox
   ```

4. **Announce to team:**
   ```bash
   palaia memo broadcast "New agent <name> is online"
   ```

Agents without palaia will not auto-capture conversations, not benefit from shared knowledge, and may duplicate work.

## Agent Isolation Mode

For strict memory separation between agents, use isolation mode:

```bash
palaia init --agent alice --isolated
```

This configures the agent with:
- **`captureScope: private`** — all captured entries are private by default
- **`scopeVisibility: own`** — agent only sees its own entries in recall

### Pre-configured Profiles

Configure via `priorities.json`:

| Profile | `captureScope` | `scopeVisibility` | Use case |
|---------|---------------|-------------------|----------|
| **Isolated Worker** | `private` | `own` | Default for `--isolated`. Agent works alone. |
| **Orchestrator** | `team` | `all` | Coordinator that reads all, writes team-visible. |
| **Lean Worker** | `private` | `team` | Reads team knowledge, captures privately. |

### Example: Mixed team

```bash
# Worker agents — isolated
palaia init --agent coder --isolated
palaia init --agent reviewer --isolated

# Orchestrator — sees everything
palaia init --agent lead
# Then in priorities.json: set scopeVisibility: "all" for lead
```

Isolation mode is purely additive — it doesn't affect existing entries or other agents.

---

## Project-Level Isolation

Entries can be scoped to projects:

```bash
palaia write "Use React 18" --project frontend
palaia query "react" --project frontend         # Only frontend memories
palaia query "react" --cross-project            # Search all projects
```

Project locks prevent concurrent modifications:
```bash
palaia lock myproject --reason "Deploying"
palaia unlock myproject
```
