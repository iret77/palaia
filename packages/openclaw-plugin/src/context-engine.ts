/**
 * ContextEngine adapter for deeper OpenClaw integration.
 *
 * Maps the 7 ContextEngine lifecycle hooks to palaia functionality,
 * using the decomposed hooks modules as the implementation layer.
 *
 * Phase 1.5: Created as a thin adapter over existing recall/capture logic.
 */

import type { OpenClawPluginApi } from "./types.js";
import type { PalaiaPluginConfig } from "./config.js";
import { run, recover, type RunnerOpts, getEmbedServerManager } from "./runner.js";

import {
  extractMessageTexts,
  buildRecallQuery,
  rerankByTypeWeight,
  checkNudges,
  type QueryResult,
} from "./hooks/recall.js";

import {
  extractWithLLM,
  shouldAttemptCapture,
  extractSignificance,
  stripPalaiaInjectedContext,
  trimToRecentExchanges,
  parsePalaiaHints,
  loadProjects,
  resolveCaptureModel,
  type ExtractionResult,
} from "./hooks/capture.js";

import {
  loadPluginState,
  savePluginState,
  resolvePerAgentContext,
  sanitizeScope,
  isValidScope,
} from "./hooks/state.js";

import { sendReaction } from "./hooks/reactions.js";

/**
 * ContextEngine adapter for deeper OpenClaw integration.
 * Maps the 7 ContextEngine lifecycle hooks to palaia functionality.
 */
export interface PalaiaContextEngine {
  bootstrap(): Promise<void>;
  ingest(messages: unknown[]): Promise<void>;
  assemble(budget: { maxTokens: number }): Promise<{ content: string; tokenEstimate: number }>;
  compact(): Promise<void>;
  afterTurn(turn: unknown): Promise<void>;
  prepareSubagentSpawn(parentContext: unknown): Promise<unknown>;
  onSubagentEnded(result: unknown): Promise<void>;
}

function buildRunnerOpts(config: PalaiaPluginConfig, overrides?: { workspace?: string }): RunnerOpts {
  return {
    binaryPath: config.binaryPath,
    workspace: overrides?.workspace || config.workspace,
    timeoutMs: config.timeoutMs,
  };
}

/** Rough token estimate: ~4 chars per token for English text. */
function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

export function createPalaiaContextEngine(
  api: OpenClawPluginApi,
  config: PalaiaPluginConfig,
): PalaiaContextEngine {
  const logger = api.logger;
  const opts = buildRunnerOpts(config);

  /** Last messages seen via ingest(), used by assemble() for query building. */
  let _lastMessages: unknown[] = [];

  /** State from the last assemble() call, used by afterTurn(). */
  let _lastAssembleState: {
    recallOccurred: boolean;
    capturedInThisTurn: boolean;
  } = { recallOccurred: false, capturedInThisTurn: false };

  return {
    /**
     * Bootstrap: WAL recovery + embed-server start.
     * Maps to the palaia-recovery service from runner.ts.
     */
    async bootstrap(): Promise<void> {
      try {
        const result = await recover(opts);
        if (result.replayed > 0) {
          logger.info(`[palaia] WAL recovery: replayed ${result.replayed} entries`);
        }
        if (result.errors > 0) {
          logger.warn(`[palaia] WAL recovery completed with ${result.errors} error(s)`);
        }
      } catch (error) {
        logger.warn(`[palaia] Bootstrap WAL recovery failed: ${error}`);
      }

      // Start embed server if configured (lazy — first query will start it)
      if (config.embeddingServer) {
        try {
          getEmbedServerManager(opts);
        } catch {
          // Non-fatal — embed server start is lazy
        }
      }
    },

    /**
     * Ingest: auto-capture logic from hooks/capture.ts.
     * Called with the turn's messages after the agent responds.
     */
    async ingest(messages: unknown[]): Promise<void> {
      _lastMessages = messages;

      if (!config.autoCapture) return;
      if (!messages || messages.length === 0) return;

      try {
        const allTexts = extractMessageTexts(messages);
        const userTurns = allTexts.filter((t) => t.role === "user").length;
        if (userTurns < config.captureMinTurns) return;

        // Parse capture hints
        const collectedHints: { project?: string; scope?: string }[] = [];
        for (const t of allTexts) {
          const { hints } = parsePalaiaHints(t.text);
          collectedHints.push(...hints);
        }

        // Strip injected context and trim to recent
        const cleanedTexts = allTexts.map(t =>
          t.role === "user"
            ? { ...t, text: stripPalaiaInjectedContext(t.text) }
            : t
        );
        const recentTexts = trimToRecentExchanges(cleanedTexts);
        const exchangeParts: string[] = [];
        for (const t of recentTexts) {
          const { cleanedText } = parsePalaiaHints(t.text);
          exchangeParts.push(`[${t.role}]: ${cleanedText}`);
        }
        const exchangeText = exchangeParts.join("\n");

        if (!shouldAttemptCapture(exchangeText)) return;

        const hookOpts = buildRunnerOpts(config);
        const knownProjects = await loadProjects(hookOpts);
        const agentName = process.env.PALAIA_AGENT || undefined;

        // LLM-based extraction (primary)
        let llmHandled = false;
        try {
          const results = await extractWithLLM(messages, api.config, {
            captureModel: config.captureModel,
          }, knownProjects);

          for (const r of results) {
            if (r.significance >= config.captureMinSignificance) {
              const hintProject = collectedHints.find((h) => h.project)?.project;
              const hintScope = collectedHints.find((h) => h.scope)?.scope;
              const effectiveProject = hintProject || r.project;
              const scope = config.captureScope
                ? sanitizeScope(config.captureScope, "team", true)
                : sanitizeScope(hintScope || r.scope, "team", false);
              const tags = [...r.tags];
              if (!tags.includes("auto-capture")) tags.push("auto-capture");

              const args: string[] = [
                "write", r.content,
                "--type", r.type,
                "--tags", tags.join(",") || "auto-capture",
                "--scope", scope,
              ];
              const project = config.captureProject || effectiveProject;
              if (project) args.push("--project", project);
              if (agentName) args.push("--agent", agentName);

              await run(args, { ...hookOpts, timeoutMs: 10_000 });
            }
          }
          llmHandled = true;
        } catch {
          // Fall through to rule-based
        }

        // Rule-based fallback
        if (!llmHandled) {
          if (config.captureFrequency === "significant") {
            const significance = extractSignificance(exchangeText);
            if (!significance) return;
            const tags = [...significance.tags];
            if (!tags.includes("auto-capture")) tags.push("auto-capture");
            const scope = config.captureScope
              ? sanitizeScope(config.captureScope, "team", true)
              : "team";
            const args: string[] = [
              "write", significance.summary,
              "--type", significance.type,
              "--tags", tags.join(","),
              "--scope", scope,
            ];
            if (agentName) args.push("--agent", agentName);
            await run(args, { ...hookOpts, timeoutMs: 10_000 });
          } else {
            const summary = exchangeParts.slice(-4).map(p => p.slice(0, 200)).join(" | ").slice(0, 500);
            const args: string[] = [
              "write", summary,
              "--type", "memory",
              "--tags", "auto-capture",
              "--scope", config.captureScope || "team",
            ];
            if (agentName) args.push("--agent", agentName);
            await run(args, { ...hookOpts, timeoutMs: 10_000 });
          }
        }

        _lastAssembleState.capturedInThisTurn = true;
      } catch (error) {
        logger.warn(`[palaia] ContextEngine ingest failed: ${error}`);
      }
    },

    /**
     * Assemble: recall logic with token budget awareness from hooks/recall.ts.
     * Returns memory context string and token estimate, respecting the budget.
     */
    async assemble(budget: { maxTokens: number }): Promise<{ content: string; tokenEstimate: number }> {
      _lastAssembleState = { recallOccurred: false, capturedInThisTurn: _lastAssembleState.capturedInThisTurn };

      if (!config.memoryInject) {
        return { content: "", tokenEstimate: 0 };
      }

      try {
        // Convert token budget to char budget (~4 chars per token)
        const maxChars = Math.min(config.maxInjectedChars || 4000, budget.maxTokens * 4);
        const limit = Math.min(config.maxResults || 10, 20);
        let entries: QueryResult["results"] = [];

        if (config.recallMode === "query" && _lastMessages.length > 0) {
          const userMessage = buildRecallQuery(_lastMessages);
          if (userMessage && userMessage.length >= 5) {
            // Try embed server first
            let serverQueried = false;
            if (config.embeddingServer) {
              try {
                const mgr = getEmbedServerManager(opts);
                const resp = await mgr.query({
                  text: userMessage,
                  top_k: limit,
                  include_cold: config.tier === "all",
                }, config.timeoutMs || 3000);
                if (resp?.result?.results && Array.isArray(resp.result.results)) {
                  entries = resp.result.results;
                  serverQueried = true;
                }
              } catch {
                // Fall through to CLI
              }
            }

            if (!serverQueried) {
              try {
                const { runJson } = await import("./runner.js");
                const queryArgs: string[] = ["query", userMessage, "--limit", String(limit)];
                if (config.tier === "all") queryArgs.push("--all");
                const result = await runJson<QueryResult>(queryArgs, { ...opts, timeoutMs: 15000 });
                if (result && Array.isArray(result.results)) {
                  entries = result.results;
                }
              } catch {
                // Fall through to list
              }
            }
          }
        }

        // List fallback
        if (entries.length === 0) {
          try {
            const { runJson } = await import("./runner.js");
            const listArgs: string[] = ["list"];
            if (config.tier === "all") {
              listArgs.push("--all");
            } else {
              listArgs.push("--tier", config.tier || "hot");
            }
            const result = await runJson<QueryResult>(listArgs, opts);
            if (result && Array.isArray(result.results)) {
              entries = result.results;
            }
          } catch {
            return { content: "", tokenEstimate: 0 };
          }
        }

        if (entries.length === 0) {
          return { content: "", tokenEstimate: 0 };
        }

        // Apply type-weighted reranking
        const ranked = rerankByTypeWeight(entries, config.recallTypeWeight);

        // Build context string
        const SCOPE_SHORT: Record<string, string> = { team: "t", private: "p", public: "pub" };
        const TYPE_SHORT: Record<string, string> = { memory: "m", process: "pr", task: "tk" };

        let text = "## Active Memory (Palaia)\n\n";
        let chars = text.length;

        for (const entry of ranked) {
          const scopeKey = SCOPE_SHORT[entry.scope] || entry.scope;
          const typeKey = TYPE_SHORT[entry.type] || entry.type;
          const prefix = `[${scopeKey}/${typeKey}]`;

          let line: string;
          if (entry.body.toLowerCase().startsWith(entry.title.toLowerCase())) {
            line = `${prefix} ${entry.body}\n\n`;
          } else {
            line = `${prefix} ${entry.title}\n${entry.body}\n\n`;
          }

          if (chars + line.length > maxChars) break;
          text += line;
          chars += line.length;
        }

        const USAGE_NUDGE = "[palaia] auto-capture=on. Manual write: --type process (SOPs/checklists) or --type task (todos with assignee/deadline) only. Conversation knowledge is auto-captured — do not duplicate with manual writes.";
        text += USAGE_NUDGE + "\n\n";

        // Nudges
        try {
          const pluginState = await loadPluginState(config.workspace);
          pluginState.successfulRecalls++;
          if (!pluginState.firstRecallTimestamp) {
            pluginState.firstRecallTimestamp = new Date().toISOString();
          }
          const { nudges } = checkNudges(pluginState);
          if (nudges.length > 0) {
            text += "\n\n## Agent Nudge (Palaia)\n\n" + nudges.join("\n\n");
          }
          await savePluginState(pluginState, config.workspace);
        } catch {
          // Non-fatal
        }

        _lastAssembleState.recallOccurred = entries.some(
          (e) => typeof e.score === "number" && e.score >= config.recallMinScore,
        );

        return {
          content: text,
          tokenEstimate: estimateTokens(text),
        };
      } catch (error) {
        logger.warn(`[palaia] ContextEngine assemble failed: ${error}`);
        return { content: "", tokenEstimate: 0 };
      }
    },

    /**
     * Compact: trigger `palaia gc` via runner.
     */
    async compact(): Promise<void> {
      try {
        await run(["gc"], { ...opts, timeoutMs: 30_000 });
        logger.info("[palaia] GC compaction completed");
      } catch (error) {
        logger.warn(`[palaia] GC compaction failed: ${error}`);
      }
    },

    /**
     * AfterTurn: state save + emoji reactions.
     * Called after each agent turn completes.
     */
    async afterTurn(turn: unknown): Promise<void> {
      // State save is handled implicitly by assemble() nudge logic.
      // Reset for next turn.
      _lastAssembleState = { recallOccurred: false, capturedInThisTurn: false };
      _lastMessages = [];
    },

    /**
     * PrepareSubagentSpawn: pass workspace + agent identity.
     * Returns context for the sub-agent to inherit.
     */
    async prepareSubagentSpawn(parentContext: unknown): Promise<unknown> {
      const workspace = typeof api.workspace === "string"
        ? api.workspace
        : api.workspace?.dir;
      const agentId = process.env.PALAIA_AGENT || undefined;

      return {
        palaiaWorkspace: workspace || config.workspace,
        palaiaAgentId: agentId,
        parentContext,
      };
    },

    /**
     * OnSubagentEnded: placeholder for future sub-agent memory merge.
     * Will eventually merge sub-agent captures into parent context.
     */
    async onSubagentEnded(_result: unknown): Promise<void> {
      // Future: merge sub-agent memory captures into parent agent's context.
      // For now, sub-agents write to the same palaia store, so no merge needed.
    },
  };
}
