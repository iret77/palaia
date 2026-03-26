/**
 * @byte5ai/palaia — Palaia Memory Backend for OpenClaw
 *
 * Plugin entry point. Loaded by OpenClaw via jiti (no build step needed).
 *
 * Registers:
 * - memory_search: Semantic search over Palaia memory
 * - memory_get: Read a specific memory entry
 * - memory_write: Write new entries (optional, opt-in)
 * - before_prompt_build: Query-based contextual recall (opt-in, Issue #65)
 * - agent_end: Auto-capture of significant exchanges (opt-in, Issue #64)
 * - palaia-recovery: WAL replay on startup
 *
 * Phase 1.5: ContextEngine adapter support. When the host provides
 * api.registerContextEngine, palaia registers as a ContextEngine.
 * Otherwise, falls back to legacy hook-based integration.
 *
 * Activation:
 *   plugins: { slots: { memory: "palaia" } }
 */

import { resolveConfig, type PalaiaPluginConfig } from "./src/config.js";
import { registerTools } from "./src/tools.js";
import { registerHooks } from "./src/hooks/index.js";
import { createPalaiaContextEngine } from "./src/context-engine.js";
import type { OpenClawPluginApi, OpenClawPluginEntry } from "./src/types.js";

// Plugin entry point compatible with OpenClaw plugin-sdk definePluginEntry
const palaiaPlugin: OpenClawPluginEntry = {
  id: "palaia",
  name: "Palaia Memory",
  async register(api: OpenClawPluginApi) {
    // Issue #66: Plugin config is currently resolved GLOBALLY via api.getConfig("palaia").
    // OpenClaw does NOT provide per-agent config resolution — all agents share the same
    // plugin config from openclaw.json → plugins.config.palaia.
    // A per-agent resolver would require an OpenClaw upstream change where api.getConfig()
    // accepts an agentId parameter or automatically scopes to the current agent context.
    // See: https://github.com/iret77/palaia/issues/66
    const rawConfig = api.getConfig?.("palaia") as
      | Partial<PalaiaPluginConfig>
      | undefined;
    const config = resolveConfig(rawConfig);

    // If workspace not set, use agent workspace from context
    if (!config.workspace && api.workspace) {
      config.workspace = typeof api.workspace === "string"
        ? api.workspace
        : api.workspace.dir;
    }

    // Register agent tools (memory_search, memory_get, memory_write)
    registerTools(api, config);

    // Register ContextEngine when available, otherwise use legacy hooks
    if (api.registerContextEngine) {
      api.registerContextEngine("palaia", createPalaiaContextEngine(api, config));
    } else {
      registerHooks(api, config);  // Legacy fallback
    }
  },
};

export default palaiaPlugin;
