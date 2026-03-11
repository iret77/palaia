/**
 * Lifecycle hooks for the Palaia OpenClaw plugin.
 *
 * - before_prompt_build: Injects HOT memory into agent context (opt-in).
 * - palaia-recovery service: Replays WAL on startup.
 */

import { runJson, recover, type RunnerOpts } from "./runner.js";
import type { PalaiaPluginConfig } from "./config.js";

/** Shape returned by `palaia query --json` */
interface QueryResult {
  results: Array<{
    id: string;
    body?: string;
    content?: string;
    score: number;
    tier: string;
    scope: string;
    title?: string;
  }>;
}

/**
 * Build RunnerOpts from plugin config.
 */
function buildRunnerOpts(config: PalaiaPluginConfig): RunnerOpts {
  return {
    binaryPath: config.binaryPath,
    workspace: config.workspace,
    timeoutMs: config.timeoutMs,
  };
}

/**
 * Register lifecycle hooks on the plugin API.
 */
export function registerHooks(api: any, config: PalaiaPluginConfig): void {
  const opts = buildRunnerOpts(config);

  // ── before_prompt_build ────────────────────────────────────────
  // Injects top HOT entries into agent system context.
  // Only active when config.memoryInject === true (default: false).
  if (config.memoryInject) {
    api.on("before_prompt_build", async (event: any, ctx: any) => {
      try {
        const maxChars = config.maxInjectedChars || 4000;
        const limit = Math.min(config.maxResults || 10, 20);

        const result = await runJson<QueryResult>(
          ["list", "--tier", "hot", "--limit", String(limit)],
          opts
        );

        if (!result || !Array.isArray(result.results) || result.results.length === 0) {
          // Fallback: try query with empty string for recent entries
          return;
        }

        const entries = result.results;
        let text = "## Active Memory (Palaia)\n\n";
        let chars = text.length;

        for (const entry of entries) {
          const body = entry.content || entry.body || "";
          const title = entry.title || "(untitled)";
          const line = `**${title}** [${entry.scope}]\n${body}\n\n`;

          if (chars + line.length > maxChars) break;
          text += line;
          chars += line.length;
        }

        if (ctx.prependSystemContext) {
          ctx.prependSystemContext(text);
        }
      } catch (error) {
        // Non-fatal: if memory injection fails, agent continues without it
        console.warn(`[palaia] Memory injection failed: ${error}`);
      }
    });
  }

  // ── Startup Recovery Service ───────────────────────────────────
  // Replays pending WAL entries on plugin startup.
  api.registerService({
    id: "palaia-recovery",
    start: async () => {
      const result = await recover(opts);
      if (result.replayed > 0) {
        console.log(`[palaia] WAL recovery: replayed ${result.replayed} entries`);
      }
      if (result.errors > 0) {
        console.warn(`[palaia] WAL recovery completed with ${result.errors} error(s)`);
      }
    },
  });
}
