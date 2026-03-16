/**
 * Lifecycle hooks for the Palaia OpenClaw plugin.
 *
 * - before_prompt_build: Query-based contextual recall (Issue #65).
 * - agent_end: Auto-capture of significant exchanges (Issue #64).
 * - palaia-recovery service: Replays WAL on startup.
 */

import { run, runJson, recover, type RunnerOpts } from "./runner.js";
import type { PalaiaPluginConfig, RecallTypeWeights } from "./config.js";

// ============================================================================
// Types
// ============================================================================

/** Shape returned by `palaia query --json` or `palaia list --json` */
interface QueryResult {
  results: Array<{
    id: string;
    body?: string;
    content?: string;
    score: number;
    tier: string;
    scope: string;
    title?: string;
    type?: string;
    tags?: string[];
  }>;
}

/** Message shape from OpenClaw event.messages */
interface Message {
  role?: string;
  content?: string | Array<{ type?: string; text?: string }>;
}

// ============================================================================
// Auto-Capture: Rule-based extraction (Issue #64)
// ============================================================================

/** Trivial responses that should never be captured */
const TRIVIAL_RESPONSES = new Set([
  "ok", "ja", "nein", "yes", "no", "sure", "klar", "danke", "thanks",
  "thx", "k", "👍", "👎", "ack", "nope", "yep", "yup", "alright",
  "fine", "gut", "passt", "okay", "hmm", "hm", "ah", "aha",
]);

/**
 * Significance patterns that indicate content worth capturing.
 * Each pattern maps to a tag and type.
 */
const SIGNIFICANCE_RULES: Array<{
  pattern: RegExp;
  tag: string;
  type: "memory" | "process" | "task";
}> = [
  // Decisions
  { pattern: /(?:we decided|entschieden|decision:|beschlossen|let'?s go with|wir nehmen|agreed on)/i, tag: "decision", type: "memory" },
  { pattern: /(?:will use|werden nutzen|going forward|ab jetzt|from now on)/i, tag: "decision", type: "memory" },

  // Lessons / Learnings
  { pattern: /(?:learned|gelernt|lesson:|erkenntnis|takeaway|insight|turns out|it seems)/i, tag: "lesson", type: "memory" },
  { pattern: /(?:mistake was|fehler war|should have|hätten sollen|next time)/i, tag: "lesson", type: "memory" },

  // Surprises / Unexpected findings
  { pattern: /(?:surprising|überraschend|unexpected|unerwartet|didn'?t expect|nicht erwartet|plot twist)/i, tag: "surprise", type: "memory" },

  // Commitments / Action items
  { pattern: /(?:i will|ich werde|todo:|action item|must do|muss noch|need to|commit to|verspreche)/i, tag: "commitment", type: "task" },
  { pattern: /(?:deadline|frist|due date|bis zum|by end of|spätestens)/i, tag: "commitment", type: "task" },

  // Process documentation
  { pattern: /(?:the process is|der prozess|steps?:|workflow:|how to|anleitung|recipe:|checklist)/i, tag: "process", type: "process" },
  { pattern: /(?:first,?\s.*then|schritt \d|step \d|1\.\s.*2\.\s)/i, tag: "process", type: "process" },
];

/**
 * Pre-filter: Should this exchange even be considered for capture?
 * Returns false for trivial, too-short, or system-generated content.
 */
export function shouldAttemptCapture(
  exchangeText: string,
  minChars = 100,
): boolean {
  const trimmed = exchangeText.trim();

  // Too short
  if (trimmed.length < minChars) return false;

  // Check if it's just trivial responses
  const words = trimmed.toLowerCase().split(/\s+/);
  if (words.length <= 3 && words.every((w) => TRIVIAL_RESPONSES.has(w))) {
    return false;
  }

  // Skip system-generated / injected content
  if (trimmed.includes("<relevant-memories>")) return false;
  if (trimmed.startsWith("<") && trimmed.includes("</")) return false;

  return true;
}

/**
 * Extract significance from exchange text using rule-based matching.
 * Returns null if nothing significant is detected.
 *
 * TODO: Upgrade to LLM-based extraction when Plugin API supports direct LLM calls.
 * The rule-based approach covers common patterns but misses nuanced significance.
 */
export function extractSignificance(
  exchangeText: string,
): { tags: string[]; type: "memory" | "process" | "task"; summary: string } | null {
  const matched: Array<{ tag: string; type: "memory" | "process" | "task" }> = [];

  for (const rule of SIGNIFICANCE_RULES) {
    if (rule.pattern.test(exchangeText)) {
      matched.push({ tag: rule.tag, type: rule.type });
    }
  }

  if (matched.length === 0) return null;

  // Determine primary type by priority: task > process > memory
  const typePriority: Record<string, number> = { task: 3, process: 2, memory: 1 };
  const primaryType = matched.reduce(
    (best, m) => (typePriority[m.type] > typePriority[best] ? m.type : best),
    "memory" as "memory" | "process" | "task",
  );

  const tags = [...new Set(matched.map((m) => m.tag))];

  // Build a summary: take the most relevant sentences
  const sentences = exchangeText
    .split(/[.!?\n]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 20 && s.length < 500);

  // Pick sentences that match our significance rules
  const relevantSentences = sentences.filter((s) =>
    SIGNIFICANCE_RULES.some((r) => r.pattern.test(s)),
  );

  const summary = (relevantSentences.length > 0 ? relevantSentences : sentences)
    .slice(0, 3)
    .join(". ")
    .slice(0, 500);

  if (!summary) return null;

  return { tags, type: primaryType, summary };
}

/**
 * Extract text content from OpenClaw message objects.
 */
export function extractMessageTexts(messages: unknown[]): Array<{ role: string; text: string }> {
  const result: Array<{ role: string; text: string }> = [];

  for (const msg of messages) {
    if (!msg || typeof msg !== "object") continue;
    const m = msg as Message;
    const role = m.role;
    if (!role || typeof role !== "string") continue;

    if (typeof m.content === "string" && m.content.trim()) {
      result.push({ role, text: m.content.trim() });
      continue;
    }

    if (Array.isArray(m.content)) {
      for (const block of m.content) {
        if (
          block &&
          typeof block === "object" &&
          block.type === "text" &&
          typeof block.text === "string" &&
          block.text.trim()
        ) {
          result.push({ role, text: block.text.trim() });
        }
      }
    }
  }

  return result;
}

/**
 * Get the last user message from event messages.
 */
export function getLastUserMessage(messages: unknown[]): string | null {
  const texts = extractMessageTexts(messages);
  for (let i = texts.length - 1; i >= 0; i--) {
    if (texts[i].role === "user") return texts[i].text;
  }
  return null;
}

// ============================================================================
// Query-based Recall: Type-weighted reranking (Issue #65)
// ============================================================================

interface RankedEntry {
  id: string;
  body: string;
  title: string;
  scope: string;
  tier: string;
  type: string;
  score: number;
  weightedScore: number;
}

/**
 * Rerank query results by applying type-based weights.
 */
export function rerankByTypeWeight(
  results: QueryResult["results"],
  weights: RecallTypeWeights,
): RankedEntry[] {
  return results
    .map((r) => {
      const type = r.type || "memory";
      const weight = weights[type] ?? 1.0;
      return {
        id: r.id,
        body: r.content || r.body || "",
        title: r.title || "(untitled)",
        scope: r.scope,
        tier: r.tier,
        type,
        score: r.score,
        weightedScore: r.score * weight,
      };
    })
    .sort((a, b) => b.weightedScore - a.weightedScore);
}

// ============================================================================
// Hook helpers
// ============================================================================

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

// ============================================================================
// Hook registration
// ============================================================================

/**
 * Register lifecycle hooks on the plugin API.
 */
export function registerHooks(api: any, config: PalaiaPluginConfig): void {
  const opts = buildRunnerOpts(config);

  // ── before_prompt_build (Issue #65: Query-based Recall) ────────
  // Injects contextually relevant HOT entries into agent system context.
  // Supports two modes: "query" (semantic search) and "list" (tier-based).
  if (config.memoryInject) {
    api.on("before_prompt_build", async (event: any, _ctx: any) => {
      try {
        const maxChars = config.maxInjectedChars || 4000;
        const limit = Math.min(config.maxResults || 10, 20);
        let entries: QueryResult["results"] = [];

        if (config.recallMode === "query") {
          // Extract the last user message for contextual query
          const userMessage = event.prompt
            || (event.messages ? getLastUserMessage(event.messages) : null);

          if (userMessage && userMessage.length >= 5) {
            try {
              const result = await runJson<QueryResult>(
                ["query", userMessage, "--tier", config.tier || "hot", "--limit", String(limit)],
                opts,
              );
              if (result && Array.isArray(result.results)) {
                entries = result.results;
              }
            } catch (queryError) {
              // Fallback to list mode if query fails
              console.warn(`[palaia] Query recall failed, falling back to list: ${queryError}`);
            }
          }
        }

        // Fallback: list mode (original behavior)
        if (entries.length === 0) {
          try {
            const result = await runJson<QueryResult>(
              ["list", "--tier", config.tier || "hot", "--limit", String(limit)],
              opts,
            );
            if (result && Array.isArray(result.results)) {
              entries = result.results;
            }
          } catch {
            // Non-fatal: if list also fails, agent continues without memory
            return;
          }
        }

        if (entries.length === 0) return;

        // Apply type-weighted reranking
        const ranked = rerankByTypeWeight(entries, config.recallTypeWeight);

        // Build context string with char budget
        let text = "## Active Memory (Palaia)\n\n";
        let chars = text.length;

        for (const entry of ranked) {
          const line = `**${entry.title}** [${entry.scope}/${entry.type}]\n${entry.body}\n\n`;
          if (chars + line.length > maxChars) break;
          text += line;
          chars += line.length;
        }

        // Use prependContext for per-turn dynamic memory injection
        return { prependContext: text };
      } catch (error) {
        // Non-fatal: if memory injection fails, agent continues without it
        console.warn(`[palaia] Memory injection failed: ${error}`);
      }
    });
  }

  // ── agent_end (Issue #64: Auto-Capture) ────────────────────────
  // Analyzes completed exchanges and captures significant content via palaia CLI.
  if (config.autoCapture) {
    api.on("agent_end", async (event: any, _ctx: any) => {
      if (!event.success || !event.messages || event.messages.length === 0) {
        return;
      }

      try {
        const allTexts = extractMessageTexts(event.messages);

        // Check minimum turns requirement
        const userTurns = allTexts.filter((t) => t.role === "user").length;
        if (userTurns < config.captureMinTurns) return;

        // Build exchange text from user + assistant messages
        const exchangeParts: string[] = [];
        for (const t of allTexts) {
          if (t.role === "user" || t.role === "assistant") {
            exchangeParts.push(`[${t.role}]: ${t.text}`);
          }
        }
        const exchangeText = exchangeParts.join("\n");

        // Pre-filter: skip trivial exchanges
        if (!shouldAttemptCapture(exchangeText)) return;

        // For "significant" mode, require rule-based significance detection
        // For "every" mode, capture with a generic "exchange" tag
        let captureData: { tags: string[]; type: string; summary: string };

        if (config.captureFrequency === "significant") {
          const significance = extractSignificance(exchangeText);
          if (!significance) return; // Nothing significant detected
          captureData = significance;
        } else {
          // "every" mode: capture a summary of the exchange
          const summary = exchangeParts
            .slice(-4) // Last 4 messages
            .map((p) => p.slice(0, 200))
            .join(" | ")
            .slice(0, 500);
          captureData = { tags: ["auto-capture"], type: "memory", summary };
        }

        // Write to Palaia via CLI
        const args: string[] = [
          "write",
          captureData.summary,
          "--type", captureData.type,
          "--tags", captureData.tags.join(","),
          "--scope", "team",
        ];

        await run(args, opts);

        console.log(
          `[palaia] Auto-captured: type=${captureData.type}, tags=${captureData.tags.join(",")}`
        );
      } catch (error) {
        // Non-fatal: capture failure should never break the agent
        console.warn(`[palaia] Auto-capture failed: ${error}`);
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
