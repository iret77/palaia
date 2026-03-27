/**
 * Lifecycle hooks for the Palaia OpenClaw plugin.
 *
 * - before_prompt_build: Query-based contextual recall (Issue #65).
 *   Returns appendSystemContext with brain instruction when memory is used.
 * - agent_end: Auto-capture of significant exchanges (Issue #64).
 *   Now with LLM-based extraction via OpenClaw's runEmbeddedPiAgent,
 *   falling back to rule-based extraction if the LLM is unavailable.
 * - message_received: Captures inbound message ID for emoji reactions.
 * - palaia-recovery service: Replays WAL on startup.
 * - /palaia command: Show memory status.
 *
 * Phase 1.5: Decomposed from monolithic hooks.ts into focused modules.
 * This file is the orchestrator — it imports from state, recall, capture,
 * and reactions modules, then registers the hooks with the API.
 */

import { run, runJson, recover, type RunnerOpts, getEmbedServerManager } from "../runner.js";
import type { PalaiaPluginConfig } from "../config.js";
import type { OpenClawPluginApi } from "../types.js";

// ── Re-export everything for backward compatibility ──────────────────────

// State exports
export {
  type PluginState,
  type TurnState,
  turnStateBySession,
  lastInboundMessageByChannel,
  REACTION_SUPPORTED_PROVIDERS,
  pruneStaleEntries,
  getOrCreateTurnState,
  deleteTurnState,
  resetTurnState,
  extractTargetFromSessionKey,
  extractChannelFromSessionKey,
  extractSlackChannelIdFromSessionKey,
  extractChannelIdFromEvent,
  resolveSessionKeyFromCtx,
  isValidScope,
  sanitizeScope,
  resolvePerAgentContext,
  formatShortDate,
  formatStatusResponse,
  loadPluginState,
  savePluginState,
} from "./state.js";

// Recall exports
export {
  type QueryResult,
  type Message,
  type RankedEntry,
  isEntryRelevant,
  buildFootnote,
  checkNudges,
  extractMessageTexts,
  getLastUserMessage,
  stripChannelEnvelope,
  stripSystemPrefix,
  buildRecallQuery,
  rerankByTypeWeight,
} from "./recall.js";

// Capture exports
export {
  type PalaiaHint,
  type ExtractionResult,
  type CachedProject,
  parsePalaiaHints,
  resetProjectCache,
  loadProjects,
  getEmbeddedPiAgent,
  resetEmbeddedPiAgentLoader,
  setEmbeddedPiAgentLoader,
  buildExtractionPrompt,
  resetCaptureModelFallbackWarning,
  resolveCaptureModel,
  trimToRecentExchanges,
  extractWithLLM,
  isNoiseContent,
  shouldAttemptCapture,
  extractSignificance,
  stripPalaiaInjectedContext,
} from "./capture.js";

// Reaction exports
export {
  sendReaction,
  resetSlackTokenCache,
} from "./reactions.js";

// ── Internal imports for hook registration ───────────────────────────────

import {
  pruneStaleEntries,
  getOrCreateTurnState,
  deleteTurnState,
  resetTurnState,
  extractTargetFromSessionKey,
  extractChannelFromSessionKey,
  extractSlackChannelIdFromSessionKey,
  extractChannelIdFromEvent,
  resolveSessionKeyFromCtx,
  isValidScope,
  sanitizeScope,
  resolvePerAgentContext,
  formatStatusResponse,
  loadPluginState,
  savePluginState,
  turnStateBySession,
  lastInboundMessageByChannel,
  REACTION_SUPPORTED_PROVIDERS,
} from "./state.js";

import {
  type QueryResult,
  checkNudges,
  extractMessageTexts,
  buildRecallQuery,
  rerankByTypeWeight,
} from "./recall.js";

import {
  parsePalaiaHints,
  loadProjects,
  extractWithLLM,
  resolveCaptureModel,
  shouldAttemptCapture,
  extractSignificance,
  stripPalaiaInjectedContext,
  trimToRecentExchanges,
  setLogger as setCaptureLogger,
  getLlmImportFailureLogged,
  setLlmImportFailureLogged,
  getCaptureModelFailoverWarned,
  setCaptureModelFailoverWarned,
  type ExtractionResult,
  type PalaiaHint,
} from "./capture.js";

import {
  sendReaction,
  resetSlackTokenCache,
  setLogger as setReactionsLogger,
} from "./reactions.js";

import {
  loadPriorities,
  resolvePriorities,
  filterBlocked,
} from "../priorities.js";

// ============================================================================
// Logger (Issue: api.logger integration)
// ============================================================================

/** Module-level logger — defaults to console, replaced by api.logger in registerHooks. */
let logger: { info: (...args: any[]) => void; warn: (...args: any[]) => void } = {
  info: (...args: any[]) => console.log(...args),
  warn: (...args: any[]) => console.warn(...args),
};

// ============================================================================
// Helper
// ============================================================================

function buildRunnerOpts(config: PalaiaPluginConfig, overrides?: { workspace?: string }): RunnerOpts {
  return {
    binaryPath: config.binaryPath,
    workspace: overrides?.workspace || config.workspace,
    timeoutMs: config.timeoutMs,
  };
}

// ============================================================================
// Hook registration
// ============================================================================

/**
 * Register lifecycle hooks on the plugin API.
 */
export function registerHooks(api: OpenClawPluginApi, config: PalaiaPluginConfig): void {
  // Store api.logger for module-wide use (integrates into OpenClaw log system)
  if (api.logger && typeof api.logger.info === "function") {
    logger = api.logger;
    setCaptureLogger(api.logger);
    setReactionsLogger(api.logger);
  }

  const opts = buildRunnerOpts(config);

  // ── Startup checks (H-2, H-3, captureModel validation) ────────
  (async () => {
    // H-2: Warn if no agent is configured
    if (!process.env.PALAIA_AGENT) {
      try {
        const statusOut = await run(["config", "get", "agent"], { ...opts, timeoutMs: 3000 });
        if (!statusOut.trim()) {
          logger.warn(
            "[palaia] No agent configured. Set PALAIA_AGENT env var or run 'palaia init --agent <name>'. " +
            "Auto-captured entries will have no agent attribution."
          );
        }
      } catch {
        logger.warn(
          "[palaia] No agent configured. Set PALAIA_AGENT env var or run 'palaia init --agent <name>'. " +
          "Auto-captured entries will have no agent attribution."
        );
      }
    }

    // H-3: Warn if no embedding provider beyond BM25
    try {
      const statusJson = await run(["status", "--json"], { ...opts, timeoutMs: 5000 });
      if (statusJson && statusJson.trim()) {
        const status = JSON.parse(statusJson);
        // embedding_chain can be at top level OR nested under config
        const chain = status.embedding_chain
          || status.embeddingChain
          || status.config?.embedding_chain
          || status.config?.embeddingChain
          || [];
        const hasSemanticProvider = Array.isArray(chain)
          ? chain.some((p: string) => p !== "bm25")
          : false;
        // Also check embedding_provider as a fallback signal
        const hasProviderConfig = !!(
          status.embedding_provider
          || status.config?.embedding_provider
        );
        if (!hasSemanticProvider && !hasProviderConfig) {
          logger.warn(
            "[palaia] No embedding provider configured. Semantic search is inactive (BM25 keyword-only). " +
            "Run 'pip install palaia[fastembed]' and 'palaia doctor --fix' for better recall quality."
          );
        }
      }
      // If statusJson is empty/null, skip warning (CLI may not be available)
    } catch {
      // Non-fatal — status check failed, skip warning (avoid false positive)
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

    // Validate captureModel auth at plugin startup via modelAuth API
    if (config.captureModel && api.runtime?.modelAuth) {
      try {
        const resolved = resolveCaptureModel(api.config, config.captureModel);
        if (resolved?.provider) {
          const key = await api.runtime.modelAuth.resolveApiKeyForProvider({ provider: resolved.provider, cfg: api.config });
          if (!key) {
            logger.warn(`[palaia] captureModel provider "${resolved.provider}" has no API key — auto-capture LLM extraction will fail`);
          }
        }
      } catch { /* non-fatal */ }
    }
  })();

  // ── /palaia status command ─────────────────────────────────────
  api.registerCommand({
    name: "palaia-status",
    description: "Show Palaia memory status",
    async handler(_args: string) {
      try {
        const state = await loadPluginState(config.workspace);

        let stats: Record<string, unknown> = {};
        try {
          const statsOutput = await run(["status", "--json"], opts);
          stats = JSON.parse(statsOutput || "{}");
        } catch {
          // Non-fatal
        }

        return { text: formatStatusResponse(state, stats, config) };
      } catch (error) {
        return { text: `Palaia status error: ${error}` };
      }
    },
  });

  // ── message_received (capture inbound message ID for reactions) ─
  api.on("message_received", (event: any, ctx: any) => {
    try {
      const messageId = event?.metadata?.messageId;
      const provider = event?.metadata?.provider;

      // ctx.channelId returns the provider name ("slack"), NOT the actual channel ID.
      // ctx.sessionKey is null during message_received.
      // Extract the real channel ID from event.metadata.to / ctx.conversationId.
      const channelId = extractChannelIdFromEvent(event, ctx)
        ?? (resolveSessionKeyFromCtx(ctx) ? extractSlackChannelIdFromSessionKey(resolveSessionKeyFromCtx(ctx)!) : undefined);
      const sessionKey = resolveSessionKeyFromCtx(ctx);


      if (messageId && channelId && provider && REACTION_SUPPORTED_PROVIDERS.has(provider)) {
        // Normalize channelId to UPPERCASE for consistent lookups
        // (extractSlackChannelIdFromSessionKey returns uppercase)
        const normalizedChannelId = String(channelId).toUpperCase();
        lastInboundMessageByChannel.set(normalizedChannelId, {
          messageId: String(messageId),
          provider,
          timestamp: Date.now(),
        });

        // Also populate turnState if sessionKey is available
        if (sessionKey) {
          const turnState = getOrCreateTurnState(sessionKey);
          turnState.lastInboundMessageId = String(messageId);
          turnState.lastInboundChannelId = normalizedChannelId;
          turnState.channelProvider = provider;
        }
      }
    } catch {
      // Non-fatal — never block message flow
    }
  });

  // ── before_prompt_build (Issue #65: Query-based Recall) ────────
  if (config.memoryInject) {
    api.on("before_prompt_build", async (event: any, ctx: any) => {
      // Prune stale entries to prevent memory leaks from crashed sessions (C-2)
      pruneStaleEntries();

      // Per-agent workspace resolution (Issue #111)
      const resolved = resolvePerAgentContext(ctx, config);
      const hookOpts = buildRunnerOpts(config, { workspace: resolved.workspace });

      try {
        // Load and resolve priorities (Issue #121)
        const prio = await loadPriorities(resolved.workspace);
        const project = config.captureProject || undefined;
        const resolvedPrio = resolvePriorities(prio, {
          recallTypeWeight: config.recallTypeWeight,
          recallMinScore: config.recallMinScore,
          maxInjectedChars: config.maxInjectedChars,
          tier: config.tier,
        }, resolved.agentId, project);

        const maxChars = resolvedPrio.maxInjectedChars || 4000;
        const limit = Math.min(config.maxResults || 10, 20);
        let entries: QueryResult["results"] = [];

        if (config.recallMode === "query") {
          const userMessage = event.messages
            ? buildRecallQuery(event.messages)
            : (event.prompt || null);

          if (userMessage && userMessage.length >= 5) {
            // Try embed server first (fast path: ~0.5s), then CLI fallback (~3-14s)
            let serverQueried = false;
            if (config.embeddingServer) {
              try {
                const mgr = getEmbedServerManager(hookOpts);
                // If embed server workspace differs from resolved workspace, skip server and use CLI
                const serverWorkspace = hookOpts.workspace;
                const embedOpts = buildRunnerOpts(config);
                if (serverWorkspace !== embedOpts.workspace) {
                  logger.info(`[palaia] Embed server workspace mismatch (agent=${resolved.workspace}), falling back to CLI`);
                } else {
                  const resp = await mgr.query({
                    text: userMessage,
                    top_k: limit,
                    include_cold: resolvedPrio.tier === "all",
                  }, config.timeoutMs || 3000);
                  if (resp?.result?.results && Array.isArray(resp.result.results)) {
                    entries = resp.result.results;
                    serverQueried = true;
                  }
                }
              } catch (serverError) {
                logger.warn(`[palaia] Embed server query failed, falling back to CLI: ${serverError}`);
              }
            }

            // CLI fallback
            if (!serverQueried) {
              try {
                const queryArgs: string[] = ["query", userMessage, "--limit", String(limit)];
                if (resolvedPrio.tier === "all") {
                  queryArgs.push("--all");
                }
                const result = await runJson<QueryResult>(queryArgs, { ...hookOpts, timeoutMs: 15000 });
                if (result && Array.isArray(result.results)) {
                  entries = result.results;
                }
              } catch (queryError) {
                logger.warn(`[palaia] Query recall failed, falling back to list: ${queryError}`);
              }
            }
          }
        }

        // Fallback: list mode (no emoji — list-based recall is not query-relevant)
        let isListFallback = false;
        if (entries.length === 0) {
          isListFallback = true;
          try {
            const listArgs: string[] = ["list"];
            if (resolvedPrio.tier === "all") {
              listArgs.push("--all");
            } else {
              listArgs.push("--tier", resolvedPrio.tier || "hot");
            }
            const result = await runJson<QueryResult>(listArgs, hookOpts);
            if (result && Array.isArray(result.results)) {
              entries = result.results;
            }
          } catch {
            return;
          }
        }

        if (entries.length === 0) return;

        // Apply type-weighted reranking and blocked filtering (Issue #121)
        const rankedRaw = rerankByTypeWeight(entries, resolvedPrio.recallTypeWeight);
        const ranked = filterBlocked(rankedRaw, resolvedPrio.blocked);

        // Build context string with char budget (compact format for token efficiency)
        const SCOPE_SHORT: Record<string, string> = { team: "t", private: "p", public: "pub" };
        const TYPE_SHORT: Record<string, string> = { memory: "m", process: "pr", task: "tk" };

        let text = "## Active Memory (Palaia)\n\n";
        let chars = text.length;

        for (const entry of ranked) {
          const scopeKey = SCOPE_SHORT[entry.scope] || entry.scope;
          const typeKey = TYPE_SHORT[entry.type] || entry.type;
          const prefix = `[${scopeKey}/${typeKey}]`;

          // If body starts with title (common), skip title to save tokens
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

        // Build nudge text and check remaining budget before appending
        const USAGE_NUDGE = "[palaia] auto-capture=on. Manual write: --type process (SOPs/checklists) or --type task (todos with assignee/deadline) only. Conversation knowledge is auto-captured — do not duplicate with manual writes.";
        let nudgeContext = "";
        try {
          const pluginState = await loadPluginState(resolved.workspace);
          pluginState.successfulRecalls++;
          if (!pluginState.firstRecallTimestamp) {
            pluginState.firstRecallTimestamp = new Date().toISOString();
          }
          const { nudges } = checkNudges(pluginState);
          if (nudges.length > 0) {
            nudgeContext = "\n\n## Agent Nudge (Palaia)\n\n" + nudges.join("\n\n");
          }
          await savePluginState(pluginState, resolved.workspace);
        } catch {
          // Non-fatal
        }

        // Before adding nudges, check remaining budget
        const nudgeText = USAGE_NUDGE + "\n\n" + nudgeContext;
        if (chars + nudgeText.length <= maxChars) {
          text += nudgeText;
        }
        // If nudges don't fit, skip them — the recall content is more important

        // Track recall in session-isolated turn state for emoji reactions
        // Only flag recall as meaningful if at least one result scores above threshold
        // List-fallback never triggers brain emoji (not query-relevant)
        const hasRelevantRecall = !isListFallback && entries.some(
          (e) => typeof e.score === "number" && e.score >= resolvedPrio.recallMinScore,
        );
        const sessionKey = resolveSessionKeyFromCtx(ctx);
        if (sessionKey && hasRelevantRecall) {
          const turnState = getOrCreateTurnState(sessionKey);
          turnState.recallOccurred = true;

          // Populate channel info — prefer event metadata, fall back to sessionKey
          const provider = extractChannelFromSessionKey(sessionKey);
          if (provider) turnState.channelProvider = provider;
          const slackChannel = extractChannelIdFromEvent(event, ctx)
            ?? extractSlackChannelIdFromSessionKey(sessionKey);
          if (slackChannel) turnState.lastInboundChannelId = slackChannel;

          // Try to get the inbound message ID from the message_received store
          if (slackChannel) {
            const inbound = lastInboundMessageByChannel.get(slackChannel);
            if (inbound && (Date.now() - inbound.timestamp) < 30_000) {
              turnState.lastInboundMessageId = inbound.messageId;
            }
          }
        }

        // Return prependContext + appendSystemContext for recall emoji
        return {
          prependContext: text + nudgeContext,
          appendSystemContext: config.showMemorySources
            ? "You used Palaia memory in this turn. Add \u{1f9e0} at the very end of your response (after everything else, on its own line)."
            : undefined,
        };
      } catch (error) {
        logger.warn(`[palaia] Memory injection failed: ${error}`);
      }
    });
  }

  // ── message_sending (Issue #81: Hint stripping) ──────────────────
  api.on("message_sending", (_event: any, _ctx: any) => {
    const content = _event?.content;
    if (typeof content !== "string") return;

    const { hints, cleanedText } = parsePalaiaHints(content);
    if (hints.length > 0) {
      return { content: cleanedText };
    }
  });

  // ── agent_end (Issue #64 + #81: Auto-Capture with Metadata + Reactions) ───
  if (config.autoCapture) {
    api.on("agent_end", async (event: any, ctx: any) => {
      // Resolve session key for turn state
      const sessionKey = resolveSessionKeyFromCtx(ctx);

      // Per-agent workspace resolution (Issue #111)
      const resolved = resolvePerAgentContext(ctx, config);
      const hookOpts = buildRunnerOpts(config, { workspace: resolved.workspace });

      if (!event.success || !event.messages || event.messages.length === 0) {
        return;
      }

      try {
        const agentName = resolved.agentId;

        const allTexts = extractMessageTexts(event.messages);

        const userTurns = allTexts.filter((t) => t.role === "user").length;
        if (userTurns < config.captureMinTurns) {
          return;
        }

        // Parse capture hints from all messages (Issue #81)
        const collectedHints: PalaiaHint[] = [];
        for (const t of allTexts) {
          const { hints } = parsePalaiaHints(t.text);
          collectedHints.push(...hints);
        }

        // Strip Palaia-injected recall context from user messages to prevent feedback loop.
        // The recall block is prepended to user messages by before_prompt_build.
        // Without stripping, auto-capture would re-capture previously recalled memories.
        const cleanedTexts = allTexts.map(t =>
          t.role === "user"
            ? { ...t, text: stripPalaiaInjectedContext(t.text) }
            : t
        );

        // Only extract from recent exchanges — full history causes LLM timeouts
        // and dilutes extraction quality
        const recentTexts = trimToRecentExchanges(cleanedTexts);

        // Build exchange text from recent window only
        const exchangeParts: string[] = [];
        for (const t of recentTexts) {
          const { cleanedText } = parsePalaiaHints(t.text);
          exchangeParts.push(`[${t.role}]: ${cleanedText}`);
        }
        const exchangeText = exchangeParts.join("\n");

        if (!shouldAttemptCapture(exchangeText)) {
          return;
        }

        const knownProjects = await loadProjects(hookOpts);

        // Helper: build CLI args with metadata
        const buildWriteArgs = (
          content: string,
          type: string,
          tags: string[],
          itemProject?: string | null,
          itemScope?: string | null,
        ): string[] => {
          const args: string[] = [
            "write",
            content,
            "--type", type,
            "--tags", tags.join(",") || "auto-capture",
          ];

          // Scope guardrail: config.captureScope overrides everything; otherwise max team (no public)
          const scope = config.captureScope
            ? sanitizeScope(config.captureScope, "team", true)
            : sanitizeScope(itemScope, "team", false);
          args.push("--scope", scope);

          const project = config.captureProject || itemProject;
          if (project) {
            args.push("--project", project);
          }

          if (agentName) {
            args.push("--agent", agentName);
          }

          return args;
        };

        // Helper: store LLM extraction results
        const storeLLMResults = async (results: ExtractionResult[]) => {
          for (const r of results) {
            if (r.significance >= config.captureMinSignificance) {
              const hintForProject = collectedHints.find((h) => h.project);
              const hintForScope = collectedHints.find((h) => h.scope);

              const effectiveProject = hintForProject?.project || r.project;
              const effectiveScope = hintForScope?.scope || r.scope;

              // Project validation: reject unknown projects
              let validatedProject = effectiveProject;
              if (validatedProject && knownProjects.length > 0) {
                const isKnown = knownProjects.some(
                  (p) => p.name.toLowerCase() === validatedProject!.toLowerCase(),
                );
                if (!isKnown) {
                  logger.info(`[palaia] Auto-capture: unknown project "${validatedProject}" ignored`);
                  validatedProject = null;
                }
              }

              // Always include auto-capture tag for GC identification
              const tags = [...r.tags];
              if (!tags.includes("auto-capture")) tags.push("auto-capture");

              const args = buildWriteArgs(
                r.content,
                r.type,
                tags,
                validatedProject,
                effectiveScope,
              );
              await run(args, { ...hookOpts, timeoutMs: 10_000 });
              logger.info(
                `[palaia] LLM auto-captured: type=${r.type}, significance=${r.significance}, tags=${tags.join(",")}, project=${validatedProject || "none"}, scope=${effectiveScope || "team"}`
              );
            }
          }
        };

        // LLM-based extraction (primary)
        let llmHandled = false;
        try {
          const results = await extractWithLLM(event.messages, api.config, {
            captureModel: config.captureModel,
          }, knownProjects);

          await storeLLMResults(results);
          llmHandled = true;
        } catch (llmError) {
          // Check if this is a model-availability error (not a generic import failure)
          const errStr = String(llmError);
          const isModelError = /FailoverError|Unknown model|unknown model|401|403|model.*not found|not_found|model_not_found/i.test(errStr);

          if (isModelError && config.captureModel) {
            // captureModel is broken — try primary model as fallback
            if (!getCaptureModelFailoverWarned()) {
              setCaptureModelFailoverWarned(true);
              logger.warn(`[palaia] WARNING: captureModel failed (${errStr}). Using primary model as fallback. Please update captureModel in your config.`);
            }
            try {
              // Retry without captureModel -> resolveCaptureModel will use primary model
              const fallbackResults = await extractWithLLM(event.messages, api.config, {
                captureModel: undefined,
              }, knownProjects);
              await storeLLMResults(fallbackResults);
              llmHandled = true;
            } catch (fallbackError) {
              if (!getLlmImportFailureLogged()) {
                logger.warn(`[palaia] LLM extraction failed (primary model fallback also failed): ${fallbackError}`);
                setLlmImportFailureLogged(true);
              }
            }
          } else {
            if (!getLlmImportFailureLogged()) {
              logger.warn(`[palaia] LLM extraction failed, using rule-based fallback: ${llmError}`);
              setLlmImportFailureLogged(true);
            }
          }
        }

        // Rule-based fallback (max 1 per turn)
        if (!llmHandled) {
          let captureData: { tags: string[]; type: string; summary: string } | null = null;

          if (config.captureFrequency === "significant") {
            const significance = extractSignificance(exchangeText);
            if (!significance) {
              return;
            }
            captureData = significance;
          } else {
            const summary = exchangeParts
              .slice(-4)
              .map((p) => p.slice(0, 200))
              .join(" | ")
              .slice(0, 500);
            captureData = { tags: ["auto-capture"], type: "memory", summary };
          }

          // Always include auto-capture tag for GC identification
          if (!captureData.tags.includes("auto-capture")) {
            captureData.tags.push("auto-capture");
          }

          const hintForProject = collectedHints.find((h) => h.project);
          const hintForScope = collectedHints.find((h) => h.scope);

          const args = buildWriteArgs(
            captureData.summary,
            captureData.type,
            captureData.tags,
            hintForProject?.project,
            hintForScope?.scope,
          );

          await run(args, { ...hookOpts, timeoutMs: 10_000 });
          logger.info(
            `[palaia] Rule-based auto-captured: type=${captureData.type}, tags=${captureData.tags.join(",")}`
          );
        }

        // Mark that capture occurred in this turn
        if (sessionKey) {
          const turnState = getOrCreateTurnState(sessionKey);
          turnState.capturedInThisTurn = true;
        } else {
        }
      } catch (error) {
        logger.warn(`[palaia] Auto-capture failed: ${error}`);
      }

      // ── Emoji Reactions (Issue #87) ──────────────────────────
      // Send reactions AFTER capture completes, using turn state.
      if (sessionKey) {
        try {
          const turnState = turnStateBySession.get(sessionKey);
          if (turnState) {
            const provider = turnState.channelProvider
              || extractChannelFromSessionKey(sessionKey)
              || (ctx?.channelId as string | undefined);
            const channelId = turnState.lastInboundChannelId
              || extractChannelIdFromEvent(event, ctx)
              || extractSlackChannelIdFromSessionKey(sessionKey);
            const messageId = turnState.lastInboundMessageId;


            if (provider && REACTION_SUPPORTED_PROVIDERS.has(provider) && channelId && messageId) {
              // Capture confirmation: floppy_disk
              if (turnState.capturedInThisTurn && config.showCaptureConfirm) {
                await sendReaction(channelId, messageId, "floppy_disk", provider);
              }

              // Recall indicator: brain
              if (turnState.recallOccurred && config.showMemorySources) {
                await sendReaction(channelId, messageId, "brain", provider);
              }
            } else {
            }
          }
        } catch (reactionError) {
          logger.warn(`[palaia] Reaction sending failed: ${reactionError}`);
        } finally {
          // Always clean up turn state
          deleteTurnState(sessionKey);
        }
      }
    });
  }

  // ── agent_end: Recall-only reactions (when autoCapture is off) ─
  if (!config.autoCapture && config.showMemorySources) {
    api.on("agent_end", async (_event: any, ctx: any) => {
      const sessionKey = resolveSessionKeyFromCtx(ctx);
      if (!sessionKey) return;

      try {
        const turnState = turnStateBySession.get(sessionKey);
        if (turnState?.recallOccurred) {
          const provider = turnState.channelProvider
            || extractChannelFromSessionKey(sessionKey);
          const channelId = turnState.lastInboundChannelId
            || extractChannelIdFromEvent(_event, ctx)
            || extractSlackChannelIdFromSessionKey(sessionKey);
          const messageId = turnState.lastInboundMessageId;

          if (provider && REACTION_SUPPORTED_PROVIDERS.has(provider) && channelId && messageId) {
            await sendReaction(channelId, messageId, "brain", provider);
          }
        }
      } catch (err) {
        logger.warn(`[palaia] Recall reaction failed: ${err}`);
      } finally {
        deleteTurnState(sessionKey);
      }
    });
  }

  // ── Startup Recovery Service ───────────────────────────────────
  api.registerService({
    id: "palaia-recovery",
    start: async () => {
      const result = await recover(opts);
      if (result.replayed > 0) {
        logger.info(`[palaia] WAL recovery: replayed ${result.replayed} entries`);
      }
      if (result.errors > 0) {
        logger.warn(`[palaia] WAL recovery completed with ${result.errors} error(s)`);
      }
    },
  });
}
