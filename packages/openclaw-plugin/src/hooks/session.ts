/**
 * Session lifecycle hooks for palaia v3.
 *
 * Handles session_start, session_end, before_reset, llm_input, llm_output,
 * and after_tool_call hooks to provide:
 * - Session briefing on session start (context restoration)
 * - Automatic session summaries on session end/reset
 * - LLM model switch detection
 * - Tool observation tracking
 * - Token usage tracking
 */

import type { OpenClawPluginApi } from "../types.js";
import type { PalaiaPluginConfig } from "../config.js";
import { run, type RunnerOpts, getEmbedServerManager } from "../runner.js";
import {
  getOrCreateSessionState,
  deleteSessionState,
  resolveSessionKeyFromCtx,
  type PendingBriefing,
  type ToolObservation,
} from "./state.js";
import {
  stripPalaiaInjectedContext,
  trimToRecentExchanges,
  extractWithLLM,
  extractSignificance,
} from "./capture.js";
import { extractMessageTexts } from "./recall.js";

function buildRunnerOpts(config: PalaiaPluginConfig): RunnerOpts {
  return {
    binaryPath: config.binaryPath,
    workspace: config.workspace,
    timeoutMs: config.timeoutMs,
  };
}

// ── Session Briefing ────────────────────────────────────────���───────────

/**
 * Load session briefing data (last session summary + open tasks).
 * Called during session_start to prepare context for the first turn.
 */
export async function loadSessionBriefing(
  config: PalaiaPluginConfig,
  logger: { info(...a: unknown[]): void; warn(...a: unknown[]): void },
): Promise<PendingBriefing> {
  const opts = buildRunnerOpts(config);
  let summary: string | null = null;
  const openTasks: string[] = [];

  // Load last session summary
  try {
    const { runJson } = await import("../runner.js");
    const result = await runJson<{ results: Array<{ title: string; body: string; created: string }> }>(
      ["query", "session-summary", "--limit", "1", "--tags", "session-summary"],
      { ...opts, timeoutMs: 5000 },
    );
    if (result?.results?.[0]) {
      summary = result.results[0].body;
    }
  } catch {
    // Non-fatal — no summary available
  }

  // Load open tasks
  try {
    const { runJson } = await import("../runner.js");
    const result = await runJson<{ results: Array<{ title: string; body: string; priority?: string }> }>(
      ["list", "--type", "task", "--status", "open", "--limit", "5"],
      { ...opts, timeoutMs: 5000 },
    );
    if (result?.results) {
      for (const task of result.results) {
        const prio = task.priority ? ` (${task.priority})` : "";
        openTasks.push(`${task.title}${prio}`);
      }
    }
  } catch {
    // Non-fatal
  }

  return { summary, openTasks, timestamp: Date.now() };
}

/**
 * Format a pending briefing into injectable text.
 */
export function formatBriefing(briefing: PendingBriefing, maxChars: number): string {
  if (!briefing.summary && briefing.openTasks.length === 0) return "";

  const parts: string[] = ["## Session Briefing (Palaia)\n"];

  if (briefing.summary) {
    const agoMs = Date.now() - briefing.timestamp;
    const agoMin = Math.round(agoMs / 60_000);
    const agoStr = agoMin < 1 ? "gerade eben" :
      agoMin < 60 ? `vor ${agoMin} Min.` :
      `vor ${Math.round(agoMin / 60)} Std.`;
    parts.push(`Letzte Session (${agoStr}):`);
    parts.push(briefing.summary);
    parts.push("");
  }

  if (briefing.openTasks.length > 0) {
    parts.push("Offene Aufgaben:");
    for (const task of briefing.openTasks) {
      parts.push(`- ${task}`);
    }
    parts.push("");
  }

  const text = parts.join("\n");
  return text.length <= maxChars ? text : text.slice(0, maxChars - 3) + "...";
}

// ── Session Summary Capture ─────────────────────────────────────────────

/**
 * Extract and save a session summary from conversation messages.
 * Called during before_reset (with messages) or session_end (without).
 */
export async function captureSessionSummary(
  messages: unknown[] | undefined,
  sessionKey: string,
  api: OpenClawPluginApi,
  config: PalaiaPluginConfig,
  logger: { info(...a: unknown[]): void; warn(...a: unknown[]): void },
): Promise<void> {
  const opts = buildRunnerOpts(config);
  const state = getOrCreateSessionState(sessionKey);
  let summaryText: string | null = null;

  if (messages && messages.length > 0) {
    // Try LLM-based summary extraction
    try {
      const results = await extractWithLLM(messages, api.config, {
        captureModel: config.captureModel,
      }, []);

      if (results.length > 0) {
        summaryText = results[0].content;
      }
    } catch {
      // Fall through to rule-based
    }

    // Rule-based fallback: last 3 user+assistant pairs
    if (!summaryText) {
      const allTexts = extractMessageTexts(messages);
      const cleaned = allTexts.map((t: { role: string; text: string }) =>
        t.role === "user"
          ? { ...t, text: stripPalaiaInjectedContext(t.text) }
          : t
      );
      const recent = trimToRecentExchanges(cleaned, 3);
      if (recent.length > 0) {
        summaryText = recent
          .map(t => `[${t.role}]: ${t.text.slice(0, 200)}`)
          .join("\n")
          .slice(0, 500);
      }
    }
  } else {
    // No messages available (session_end without before_reset).
    // Use accumulated tool observations as summary.
    if (state.toolObservations.length > 0) {
      summaryText = state.toolObservations
        .map(o => `${o.toolName}: ${o.resultSummary}`)
        .join("\n")
        .slice(0, 500);
    }
  }

  if (!summaryText) return;

  // Save session summary
  try {
    const args: string[] = [
      "write", summaryText,
      "--type", "memory",
      "--tags", "session-summary,auto-capture",
      "--scope", config.captureScope || "team",
    ];
    if (state.autoSessionId) args.push("--instance", state.autoSessionId);
    const agentName = process.env.PALAIA_AGENT || undefined;
    if (agentName) args.push("--agent", agentName);

    await run(args, { ...opts, timeoutMs: 10_000 });
    logger.info(`[palaia] Session summary saved (${summaryText.length} chars)`);
  } catch (error) {
    logger.warn(`[palaia] Failed to save session summary: ${error}`);
  }
}

// ── Tool Observations ─────────────────────────────────────────────────���─

/** Tools worth tracking for observations. */
const TRACKED_TOOLS = new Set([
  // File operations
  "memory_search", "memory_get", "memory_write",
  "read_file", "write_file", "edit_file",
  "search_files", "list_files",
  // Shell
  "bash", "shell", "terminal",
  // Web
  "web_search", "fetch_url",
]);

/**
 * Process an after_tool_call event into a tool observation.
 * Returns null if the tool isn't worth tracking.
 */
export function processToolCall(
  toolName: string,
  params: Record<string, unknown>,
  result: unknown,
  durationMs: number,
): ToolObservation | null {
  // Only track relevant tools (skip internal/framework tools)
  if (!TRACKED_TOOLS.has(toolName) && !toolName.startsWith("palaia_")) {
    return null;
  }

  // Skip errored tool calls
  if (!result) return null;

  // Summarize params (keep it short)
  const paramKeys = Object.keys(params).slice(0, 3);
  const paramsSummary = paramKeys
    .map(k => {
      const v = params[k];
      const s = typeof v === "string" ? v.slice(0, 80) : JSON.stringify(v)?.slice(0, 80);
      return `${k}=${s}`;
    })
    .join(", ");

  // Summarize result
  let resultSummary: string;
  if (typeof result === "string") {
    resultSummary = result.slice(0, 200);
  } else if (typeof result === "object" && result !== null) {
    resultSummary = JSON.stringify(result).slice(0, 200);
  } else {
    resultSummary = String(result).slice(0, 200);
  }

  return {
    toolName,
    paramsSummary,
    resultSummary,
    durationMs,
    timestamp: Date.now(),
  };
}

// ── Hook Registration ───────────────────────────────────────────────────

/**
 * Register all session lifecycle hooks.
 * Called from hooks/index.ts during plugin registration.
 */
export function registerSessionHooks(
  api: OpenClawPluginApi,
  config: PalaiaPluginConfig,
): void {
  const logger = api.logger;

  // ── session_start: Load briefing for context restoration ──────────
  if (config.sessionBriefing) {
    api.on("session_start", async (event: any, ctx: any) => {
      const sessionKey = ctx?.sessionKey || ctx?.sessionId || "unknown";
      const state = getOrCreateSessionState(sessionKey);

      try {
        state.pendingBriefing = await loadSessionBriefing(config, logger);
        if (state.pendingBriefing.summary || state.pendingBriefing.openTasks.length > 0) {
          logger.info(`[palaia] Session briefing loaded for ${sessionKey}`);
        }
      } catch (error) {
        logger.warn(`[palaia] Failed to load session briefing: ${error}`);
      }
    });
  }

  // ── session_end: Save session summary ─────────────────────────────
  if (config.sessionSummary) {
    api.on("session_end", async (event: any, ctx: any) => {
      const sessionKey = ctx?.sessionKey || ctx?.sessionId || "unknown";
      const state = getOrCreateSessionState(sessionKey);

      try {
        // Only save summary if session had meaningful interaction
        const messageCount = (event as any)?.messageCount ?? 0;
        if (messageCount >= 4) { // At least 2 user + 2 assistant messages
          await captureSessionSummary(undefined, sessionKey, api, config, logger);
        }
      } catch (error) {
        logger.warn(`[palaia] session_end summary failed: ${error}`);
      } finally {
        deleteSessionState(sessionKey);
      }
    });
  }

  // ── before_reset: Save session summary with messages (priority) ───
  if (config.sessionSummary) {
    api.on("before_reset", async (event: any, ctx: any) => {
      const sessionKey = ctx?.sessionKey || ctx?.sessionId || "unknown";

      try {
        const messages = (event as any)?.messages;
        if (messages && Array.isArray(messages) && messages.length >= 4) {
          await captureSessionSummary(messages, sessionKey, api, config, logger);
        }
      } catch (error) {
        logger.warn(`[palaia] before_reset summary failed: ${error}`);
      }
    });
  }

  // ── llm_input: Model switch detection ─────────────────────────────
  api.on("llm_input", (event: any, ctx: any) => {
    const sessionKey = ctx?.sessionKey || ctx?.sessionId;
    if (!sessionKey) return;
    const state = getOrCreateSessionState(sessionKey);

    const model = (event as any)?.model;
    if (!model) return;

    if (state.lastModel && model !== state.lastModel) {
      state.modelSwitchDetected = true;
      logger.info(`[palaia] Model switch detected: ${state.lastModel} → ${model}`);

      // Re-load briefing for next assemble
      if (config.sessionBriefing && !state.pendingBriefing) {
        loadSessionBriefing(config, logger).then(briefing => {
          state.pendingBriefing = briefing;
          state.briefingDelivered = false;
        }).catch(() => {});
      }
    }
    state.lastModel = model;
  });

  // ── llm_output: Token usage tracking ──────────────────────────────
  api.on("llm_output", (event: any, ctx: any) => {
    const sessionKey = ctx?.sessionKey || ctx?.sessionId;
    if (!sessionKey) return;
    const state = getOrCreateSessionState(sessionKey);

    const usage = (event as any)?.usage;
    if (usage) {
      state.tokenUsage.input += usage.input || 0;
      state.tokenUsage.output += usage.output || 0;
    }
  });

  // ── after_tool_call: Tool observation tracking ────────────────��───
  if (config.captureToolObservations) {
    api.on("after_tool_call", (event: any, ctx: any) => {
      const sessionKey = ctx?.sessionKey || ctx?.sessionId;
      if (!sessionKey) return;
      const state = getOrCreateSessionState(sessionKey);

      const obs = processToolCall(
        (event as any)?.toolName || "",
        (event as any)?.params || {},
        (event as any)?.result,
        (event as any)?.durationMs || 0,
      );

      if (obs) {
        state.toolObservations.push(obs);
        // Keep max 50 observations per session to prevent memory bloat
        if (state.toolObservations.length > 50) {
          state.toolObservations.shift();
        }
      }
    });
  }

  // ── subagent_spawning: Pass session context to sub-agent ──────
  api.on("subagent_spawning", async (event: any, _ctx: any) => {
    try {
      const childKey = (event as any)?.childSessionKey;
      if (!childKey) return;

      // Set PALAIA_INSTANCE so sub-agent shares the session scope
      const parentKey = _ctx?.requesterSessionKey;
      if (parentKey) {
        const parentState = getOrCreateSessionState(parentKey);
        process.env.PALAIA_INSTANCE = parentState.autoSessionId;
      }
    } catch {
      // Non-fatal
    }
  });

  // ── subagent_ended: Capture sub-agent results ─────────────────
  if (config.autoCapture) {
    api.on("subagent_ended", async (event: any, _ctx: any) => {
      try {
        const outcome = (event as any)?.outcome;
        if (outcome !== "ok") return;

        const childKey = (event as any)?.targetSessionKey;
        if (!childKey || !api.runtime?.subagent?.getSessionMessages) return;

        const result = await api.runtime.subagent.getSessionMessages({
          sessionKey: childKey,
          limit: 10,
        });
        if (!result?.messages?.length) return;

        const { extractMessageTexts } = await import("./recall.js");
        const texts = extractMessageTexts(result.messages);
        const summaryParts = texts.slice(-4).map(
          (t: { role: string; text: string }) => `[${t.role}]: ${t.text.slice(0, 200)}`
        );
        if (summaryParts.length === 0) return;

        const summaryText = `Sub-agent result:\n${summaryParts.join("\n")}`.slice(0, 500);
        await run([
          "write", summaryText,
          "--type", "memory",
          "--tags", "subagent-result,auto-capture",
          "--scope", config.captureScope || "team",
        ], { ...buildRunnerOpts(config), timeoutMs: 10_000 });
        logger.info(`[palaia] Sub-agent result captured (${summaryText.length} chars)`);
      } catch (error) {
        logger.warn(`[palaia] Sub-agent result capture failed: ${error}`);
      }
    });
  }
}
