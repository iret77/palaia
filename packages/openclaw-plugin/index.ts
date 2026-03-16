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
 * Activation:
 *   plugins: { slots: { memory: "palaia" } }
 */

import { resolveConfig, type PalaiaPluginConfig } from "./src/config.js";
import { registerTools } from "./src/tools.js";
import { registerHooks } from "./src/hooks.js";

export default function palaiaPlugin(api: any) {
  const rawConfig = api.getConfig?.("palaia") as
    | Partial<PalaiaPluginConfig>
    | undefined;
  const config = resolveConfig(rawConfig);

  // If workspace not set, use agent workspace from context
  if (!config.workspace && api.workspace) {
    config.workspace = api.workspace;
  }

  // Register agent tools (memory_search, memory_get, memory_write)
  registerTools(api, config);

  // Register lifecycle hooks (before_prompt_build, recovery service)
  registerHooks(api, config);
}
