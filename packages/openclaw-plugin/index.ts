/**
 * @byte5ai/palaia — Palaia Memory Backend for OpenClaw
 *
 * Plugin entry point. Loaded by OpenClaw via jiti (no build step needed).
 *
 * Registers:
 * - Tools: memory_search, memory_get, memory_write
 * - MemoryPromptSection: Guided tool usage hints
 * - Session hooks (always): session_start, session_end, before_reset,
 *   llm_input, llm_output, after_tool_call, subagent_spawning, subagent_ended
 * - ContextEngine (modern) OR legacy hooks (before_prompt_build, agent_end,
 *   message_received, message_sending)
 *
 * v3.0 Features:
 * - Session continuity: Auto-briefing on session start / LLM switch
 * - Session summaries: Auto-saved on session end / reset
 * - Tool observations: Tracked via after_tool_call
 * - Progressive disclosure: Compact mode for large memory stores
 * - Privacy markers: <private> blocks excluded from capture
 * - Recency boost: Fresh memories ranked higher
 *
 * Activation:
 *   plugins: { slots: { memory: "palaia" } }
 */

import { resolveConfig, type PalaiaPluginConfig } from "./src/config.js";
import { registerTools } from "./src/tools.js";
import { registerHooks } from "./src/hooks/index.js";
import { registerSessionHooks } from "./src/hooks/session.js";
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
    // See: https://github.com/byte5ai/palaia/issues/66
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

    // Register MemoryPromptSection for guided memory tool usage (v3.0)
    if (api.registerMemoryPromptSection) {
      api.registerMemoryPromptSection(({ availableTools }) => {
        const lines: string[] = [];
        if (availableTools.has("memory_search")) {
          lines.push("Use `memory_search` to find relevant memories by semantic query.");
        }
        if (availableTools.has("memory_get")) {
          lines.push("Use `memory_get <id>` to retrieve full memory details by ID.");
        }
        if (availableTools.has("memory_write")) {
          lines.push("Use `memory_write` for processes/SOPs and tasks only — conversation knowledge is auto-captured.");
        }
        return lines;
      });
    }

    // Session lifecycle hooks are always registered (session_start, session_end,
    // before_reset, llm_input, llm_output, after_tool_call).
    // These work independently of the ContextEngine vs legacy hooks choice.
    registerSessionHooks(api, config);

    // Register ContextEngine when available, otherwise use legacy hooks
    if (api.registerContextEngine) {
      api.registerContextEngine("palaia", () => createPalaiaContextEngine(api, config));
    } else {
      registerHooks(api, config);  // Legacy fallback
    }
  },
};

export default palaiaPlugin;
