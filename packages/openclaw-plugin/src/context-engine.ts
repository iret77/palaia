/**
 * ContextEngine adapter for OpenClaw integration.
 *
 * Implements the OpenClaw v2026.3.24 ContextEngine interface,
 * mapping lifecycle hooks to palaia functionality via the
 * decomposed hooks modules.
 *
 * Supports both the modern ContextEngine interface (v2026.3.24+)
 * and the legacy interface for backward compatibility.
 */

import type {
  OpenClawPluginApi,
  ContextEngine,
  AgentMessage,
} from "./types.js";
import type { PalaiaPluginConfig } from "./config.js";
import { run, recover, type RunnerOpts, getEmbedServerManager } from "./runner.js";
import { getOrCreateSessionState } from "./hooks/state.js";
import { formatBriefing } from "./hooks/session.js";

import {
  extractMessageTexts,
  buildRecallQuery,
  rerankByTypeWeight,
  checkNudges,
  formatEntryLine,
  shouldUseCompactMode,
  type QueryResult,
} from "./hooks/recall.js";

import {
  extractWithLLM,
  shouldAttemptCapture,
  extractSignificance,
  strippalaiaInjectedContext,
  stripPrivateBlocks,
  trimToRecentExchanges,
  parsePalaiaHints,
  loadProjects,
} from "./hooks/capture.js";

import {
  loadPluginState,
  savePluginState,
  sanitizeScope,
} from "./hooks/state.js";

import {
  loadPriorities,
  resolvePriorities,
  filterBlocked,
} from "./priorities.js";

/**
 * Resolve the effective capture scope from priorities (per-agent override)
 * falling back to plugin config, then to "team".
 */
async function getEffectiveCaptureScope(config: PalaiaPluginConfig): Promise<string> {
  try {
    const prio = await loadPriorities(config.workspace || "");
    const agentId = process.env.PALAIA_AGENT || undefined;
    const resolved = resolvePriorities(prio, {
      recallTypeWeight: config.recallTypeWeight,
      recallMinScore: config.recallMinScore,
      maxInjectedChars: config.maxInjectedChars,
      tier: config.tier,
    }, agentId);
    if (resolved.captureScope) return resolved.captureScope;
  } catch {
    // Fall through to config default
  }
  return config.captureScope || "team";
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

/**
 * Build the memory context string from recall results.
 * Used by the ContextEngine assemble() method.
 */
async function buildMemoryContext(
  config: PalaiaPluginConfig,
  opts: RunnerOpts,
  messages: unknown[],
  maxChars: number,
): Promise<{ text: string; recallOccurred: boolean; recallMinScore: number }> {
  // Load and resolve priorities (Issue #121)
  const prio = await loadPriorities(config.workspace || "");
  const agentId = process.env.PALAIA_AGENT || undefined;
  const project = config.captureProject || undefined;
  const resolvedPrio = resolvePriorities(prio, {
    recallTypeWeight: config.recallTypeWeight,
    recallMinScore: config.recallMinScore,
    maxInjectedChars: config.maxInjectedChars,
    tier: config.tier,
  }, agentId, project);

  const effectiveMaxChars = Math.min(resolvedPrio.maxInjectedChars || 4000, maxChars);
  const limit = Math.min(config.maxResults || 10, 20);
  let entries: QueryResult["results"] = [];

  if (config.recallMode === "query" && messages.length > 0) {
    const userMessage = buildRecallQuery(messages);
    if (userMessage && userMessage.length >= 5) {
      // Try embed server first
      let serverQueried = false;
      if (config.embeddingServer) {
        try {
          const mgr = getEmbedServerManager(opts);
          const resp = await mgr.query({
            text: userMessage,
            top_k: limit,
            include_cold: resolvedPrio.tier === "all",
            ...(resolvedPrio.scopeVisibility ? { scope_visibility: resolvedPrio.scopeVisibility } : {}),
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
          if (resolvedPrio.tier === "all") queryArgs.push("--all");
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
      if (resolvedPrio.tier === "all") {
        listArgs.push("--all");
      } else {
        listArgs.push("--tier", resolvedPrio.tier || "hot");
      }
      const result = await runJson<QueryResult>(listArgs, opts);
      if (result && Array.isArray(result.results)) {
        entries = result.results;
      }
    } catch {
      return { text: "", recallOccurred: false, recallMinScore: resolvedPrio.recallMinScore };
    }
  }

  if (entries.length === 0) {
    return { text: "", recallOccurred: false, recallMinScore: resolvedPrio.recallMinScore };
  }

  // Apply type-weighted reranking and blocked filtering (Issue #121)
  const rankedRaw = rerankByTypeWeight(entries, resolvedPrio.recallTypeWeight, config.recallRecencyBoost, config.manualEntryBoost);
  const ranked = filterBlocked(rankedRaw, resolvedPrio.blocked);

  // Build context string — progressive disclosure for large stores
  const compact = shouldUseCompactMode(ranked.length);
  let text = "## Active Memory (palaia)\n\n";
  if (compact) {
    text += "_Compact mode — use `memory_get <id>` for full details._\n\n";
  }
  let chars = text.length;

  for (const entry of ranked) {
    const line = formatEntryLine(entry, compact);
    if (chars + line.length > effectiveMaxChars) break;
    text += line;
    chars += line.length;
  }

  // Build nudge text and check remaining budget before appending
  const USAGE_NUDGE = "[palaia] auto-capture=on. Manual writes rank higher in recall. Use --type process for reusable workflows, --type task for sticky-note reminders (auto-deleted when done), --type memory for important facts.";
  let agentNudges = "";
  try {
    const pluginState = await loadPluginState(config.workspace);
    pluginState.successfulRecalls++;
    if (!pluginState.firstRecallTimestamp) {
      pluginState.firstRecallTimestamp = new Date().toISOString();
    }
    const { nudges } = checkNudges(pluginState);
    if (nudges.length > 0) {
      agentNudges = "\n\n## Agent Nudge (palaia)\n\n" + nudges.join("\n\n");
    }
    await savePluginState(pluginState, config.workspace);
  } catch {
    // Non-fatal
  }

  // --- Isolation workflow nudges (#148) ---
  let isolationNudges = "";

  // 1. missing_agent_identity: scopeVisibility configured but no PALAIA_AGENT
  if (resolvedPrio.scopeVisibility && !process.env.PALAIA_AGENT) {
    isolationNudges += "\n\n⚠️ scopeVisibility is configured but PALAIA_AGENT is not set. " +
      "Scope filtering cannot work without agent identity. Set PALAIA_AGENT env var.";
  }

  // 2. recall_noise_ratio: >80% auto-capture entries for isolated agents
  if (resolvedPrio.scopeVisibility && ranked.length >= 5) {
    const autoCaptureCount = ranked.filter(e =>
      (e.tags || []).includes("auto-capture")
    ).length;
    if (autoCaptureCount / ranked.length > 0.8) {
      isolationNudges += "\n\n[palaia] Most recall results are auto-captured session data. " +
        "Ask the orchestrator to run: palaia prune --agent " +
        (process.env.PALAIA_AGENT || "<agent>") +
        " --tags auto-capture --protect-type process";
    }
  }

  const nudgeText = USAGE_NUDGE + "\n\n" + agentNudges + isolationNudges;
  if (chars + nudgeText.length <= effectiveMaxChars) {
    text += nudgeText;
  }

  const recallOccurred = entries.some(
    (e) => typeof e.score === "number" && e.score >= resolvedPrio.recallMinScore,
  );

  return { text, recallOccurred, recallMinScore: resolvedPrio.recallMinScore };
}

/**
 * Run auto-capture logic on a set of messages.
 * Used by the ContextEngine afterTurn() method.
 */
async function runAutoCapture(
  messages: unknown[],
  api: OpenClawPluginApi,
  config: PalaiaPluginConfig,
  logger: { info(...a: unknown[]): void; warn(...a: unknown[]): void },
): Promise<boolean> {
  if (!config.autoCapture) return false;
  if (!messages || messages.length === 0) {
    logger.info("[palaia] Auto-capture skipped: no messages");
    return false;
  }

  const allTexts = extractMessageTexts(messages);
  const userTurns = allTexts.filter((t) => t.role === "user").length;
  if (userTurns < config.captureMinTurns) {
    logger.info(`[palaia] Auto-capture skipped: ${userTurns} user turns < captureMinTurns=${config.captureMinTurns}`);
    return false;
  }

  // Parse capture hints
  const collectedHints: { project?: string; scope?: string }[] = [];
  for (const t of allTexts) {
    const { hints } = parsePalaiaHints(t.text);
    collectedHints.push(...hints);
  }

  // Strip injected context and private blocks, then trim to recent
  const cleanedTexts = allTexts.map(t => ({
    ...t,
    text: stripPrivateBlocks(
      t.role === "user" ? strippalaiaInjectedContext(t.text) : t.text
    ),
  }));
  const recentTexts = trimToRecentExchanges(cleanedTexts);
  const exchangeParts: string[] = [];
  for (const t of recentTexts) {
    const { cleanedText } = parsePalaiaHints(t.text);
    exchangeParts.push(`[${t.role}]: ${cleanedText}`);
  }
  const exchangeText = exchangeParts.join("\n");

  if (!shouldAttemptCapture(exchangeText)) {
    logger.info(`[palaia] Auto-capture skipped: content did not pass significance filter (${exchangeText.length} chars)`);
    return false;
  }

  const hookOpts = buildRunnerOpts(config);
  const knownProjects = await loadProjects(hookOpts);
  const agentName = process.env.PALAIA_AGENT || undefined;
  const effectiveCaptureScope = await getEffectiveCaptureScope(config);

  // LLM-based extraction (primary)
  let llmHandled = false;
  try {
    const results = await extractWithLLM(messages, api.config, {
      captureModel: config.captureModel,
      workspace: config.workspace,
    }, knownProjects);

    for (const r of results) {
      if (r.significance >= config.captureMinSignificance) {
        const hintProject = collectedHints.find((h) => h.project)?.project;
        const hintScope = collectedHints.find((h) => h.scope)?.scope;
        const effectiveProject = hintProject || r.project;
        const scope = effectiveCaptureScope !== "team"
          ? sanitizeScope(effectiveCaptureScope, "team", true)
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
      if (!significance) {
        logger.info("[palaia] Auto-capture skipped: rule-based extraction found no significance (need ≥2 distinct tags)");
        return false;
      }
      const tags = [...significance.tags];
      if (!tags.includes("auto-capture")) tags.push("auto-capture");
      const scope = effectiveCaptureScope !== "team"
        ? sanitizeScope(effectiveCaptureScope, "team", true)
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
        "--scope", effectiveCaptureScope,
      ];
      if (agentName) args.push("--agent", agentName);
      await run(args, { ...hookOpts, timeoutMs: 10_000 });
    }
  }

  return true;
}

/**
 * Create a palaia ContextEngine implementing OpenClaw v2026.3.24 interface.
 */
export function createPalaiaContextEngine(
  api: OpenClawPluginApi,
  config: PalaiaPluginConfig,
): ContextEngine {
  const logger = api.logger;
  const opts = buildRunnerOpts(config);

  /** Last messages seen via ingest(), used by assemble() for query building. */
  let _lastMessages: AgentMessage[] = [];

  /** Whether the last assemble() call found relevant memories. */
  let _lastRecallOccurred = false;

  const engine: ContextEngine = {
    info: {
      id: "palaia",
      name: "palaia Memory",
      version: "2.3",
      ownsCompaction: true,
    },

    /**
     * Bootstrap: WAL recovery + embed-server start.
     */
    async bootstrap(_params) {
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

      // Pre-start embed server so first query is fast (~0.3s instead of ~3s)
      if (config.embeddingServer) {
        try {
          const mgr = getEmbedServerManager(opts);
          await mgr.start();
          logger.info("[palaia] Embed server started (pre-warmed for fast queries)");
        } catch (err) {
          logger.info(`[palaia] Embed server pre-start skipped: ${err}`);
        }
      }

      return { bootstrapped: true };
    },

    /**
     * Ingest: process a single message for auto-capture.
     * Called per-message by the ContextEngine lifecycle.
     * Accumulates messages; capture runs in afterTurn().
     */
    async ingest(params) {
      if (params.message) {
        _lastMessages.push(params.message);
      }
      return { ingested: true };
    },

    /**
     * AfterTurn: run auto-capture on accumulated messages.
     */
    async afterTurn(params) {
      // Use params.messages if available (richer), else fall back to accumulated
      const messages = params?.messages?.length ? params.messages : _lastMessages;

      try {
        await runAutoCapture(messages, api, config, logger);
      } catch (error) {
        logger.warn(`[palaia] ContextEngine afterTurn capture failed: ${error}`);
      }

      // Reset for next turn
      _lastRecallOccurred = false;
      _lastMessages = [];
    },

    /**
     * Assemble: recall logic with token budget awareness.
     * Returns memory context via systemPromptAddition.
     */
    async assemble(params) {
      _lastRecallOccurred = false;

      if (!config.memoryInject) {
        return {
          messages: params.messages || [],
          estimatedTokens: 0,
        };
      }

      try {
        const tokenBudget = params.tokenBudget || 4000;
        const maxChars = tokenBudget * 4;

        // Use params.messages for query building (richer than accumulated)
        const queryMessages = params.messages?.length ? params.messages : _lastMessages;

        const { text, recallOccurred } = await buildMemoryContext(
          config, opts, queryMessages, maxChars,
        );

        _lastRecallOccurred = recallOccurred;

        // Inject session briefing if pending (session_start or model switch)
        let briefingText = "";
        if (config.sessionBriefing && params.sessionKey) {
          const sessionState = getOrCreateSessionState(params.sessionKey);
          if (sessionState.pendingBriefing && !sessionState.briefingDelivered) {
            // Wait for briefing to be ready (with timeout)
            if (sessionState.briefingReady) {
              await Promise.race([
                sessionState.briefingReady,
                new Promise<void>(r => setTimeout(r, 3000)),
              ]);
            }
            if (sessionState.pendingBriefing) {
              const remainingChars = maxChars - (text?.length || 0);
              briefingText = formatBriefing(
                sessionState.pendingBriefing,
                Math.min(config.sessionBriefingMaxChars || 1500, remainingChars),
              );
              if (briefingText) {
                sessionState.briefingDelivered = true;
              }
            }
          }
        }

        const combined = [briefingText, text].filter(Boolean).join("\n\n");

        if (!combined) {
          return {
            messages: params.messages || [],
            estimatedTokens: 0,
          };
        }

        return {
          messages: params.messages || [],
          estimatedTokens: estimateTokens(combined),
          systemPromptAddition: combined,
        };
      } catch (error) {
        logger.warn(`[palaia] ContextEngine assemble failed: ${error}`);
        return {
          messages: params.messages || [],
          estimatedTokens: 0,
        };
      }
    },

    /**
     * Compact: trigger `palaia gc` via runner.
     */
    async compact(_params) {
      try {
        await run(["gc"], { ...opts, timeoutMs: 30_000 });
        logger.info("[palaia] GC compaction completed");
        return { ok: true, compacted: true };
      } catch (error) {
        logger.warn(`[palaia] GC compaction failed: ${error}`);
        return { ok: false, compacted: false, reason: String(error) };
      }
    },

    /**
     * PrepareSubagentSpawn: load session summary for sub-agent context.
     */
    async prepareSubagentSpawn(_params) {
      // Sub-agents share the same palaia store via workspace,
      // so no explicit context passing is needed.
      // Future: use OpenClaw's extraSystemPrompt to pass session summary.
      return undefined;
    },

    /**
     * OnSubagentEnded: capture sub-agent result as memory.
     */
    async onSubagentEnded(params) {
      if (!config.autoCapture) return;
      // Only capture results for successfully completed sub-agents
      if (params?.reason !== "completed") return;
      try {
        // Try to get sub-agent's last messages for summary
        if (api.runtime?.subagent?.getSessionMessages && params?.childSessionKey) {
          const result = await api.runtime.subagent.getSessionMessages({
            sessionKey: params.childSessionKey,
            limit: 10,
          });
          if (result?.messages?.length) {
            const texts = extractMessageTexts(result.messages);
            const summaryParts = texts.slice(-4).map(
              (t: { role: string; text: string }) => `[${t.role}]: ${t.text.slice(0, 200)}`
            );
            if (summaryParts.length > 0) {
              const summaryText = `Sub-agent result:\n${summaryParts.join("\n")}`.slice(0, 500);
              const subagentScope = await getEffectiveCaptureScope(config);
              await run([
                "write", summaryText,
                "--type", "memory",
                "--tags", "subagent-result,auto-capture",
                "--scope", subagentScope,
              ], { ...opts, timeoutMs: 10_000 });
              logger.info(`[palaia] Sub-agent result captured (${summaryText.length} chars)`);
            }
          }
        }
      } catch (error) {
        logger.warn(`[palaia] Sub-agent result capture failed: ${error}`);
      }
    },
  };

  return engine;
}
