/**
 * Lifecycle hooks for the Palaia OpenClaw plugin.
 *
 * - before_prompt_build: Query-based contextual recall (Issue #65).
 * - agent_end: Auto-capture of significant exchanges (Issue #64).
 *   Now with LLM-based extraction via OpenClaw's runEmbeddedPiAgent,
 *   falling back to rule-based extraction if the LLM is unavailable.
 * - palaia-recovery service: Replays WAL on startup.
 */

import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { run, runJson, recover, type RunnerOpts } from "./runner.js";
import type { PalaiaPluginConfig, RecallTypeWeights } from "./config.js";

// ============================================================================
// Capture Hints (Issue #81)
// ============================================================================

/** Parsed palaia-hint tag attributes */
export interface PalaiaHint {
  project?: string;
  scope?: string;
  type?: string;
  tags?: string[];
}

/**
 * Parse `<palaia-hint ... />` tags from text.
 * Returns extracted hints and cleaned text with hints removed.
 */
export function parsePalaiaHints(text: string): { hints: PalaiaHint[]; cleanedText: string } {
  const hints: PalaiaHint[] = [];
  const regex = /<palaia-hint\s+([^/]*)\s*\/>/gi;

  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    const attrs = match[1];
    const hint: PalaiaHint = {};

    const projectMatch = attrs.match(/project\s*=\s*"([^"]*)"/i);
    if (projectMatch) hint.project = projectMatch[1];

    const scopeMatch = attrs.match(/scope\s*=\s*"([^"]*)"/i);
    if (scopeMatch) hint.scope = scopeMatch[1];

    const typeMatch = attrs.match(/type\s*=\s*"([^"]*)"/i);
    if (typeMatch) hint.type = typeMatch[1];

    const tagsMatch = attrs.match(/tags\s*=\s*"([^"]*)"/i);
    if (tagsMatch) hint.tags = tagsMatch[1].split(",").map((t) => t.trim()).filter(Boolean);

    hints.push(hint);
  }

  const cleanedText = text.replace(/<palaia-hint\s+[^/]*\s*\/>/gi, "").trim();
  return { hints, cleanedText };
}

// ============================================================================
// Project Cache (Issue #81)
// ============================================================================

interface CachedProject {
  name: string;
  description?: string;
}

let _cachedProjects: CachedProject[] | null = null;
let _projectCacheTime = 0;
const PROJECT_CACHE_TTL_MS = 60_000; // 1 minute

/** Reset project cache (for testing). */
export function resetProjectCache(): void {
  _cachedProjects = null;
  _projectCacheTime = 0;
}

/**
 * Load known projects from CLI, with caching.
 */
async function loadProjects(opts: import("./runner.js").RunnerOpts): Promise<CachedProject[]> {
  const now = Date.now();
  if (_cachedProjects && (now - _projectCacheTime) < PROJECT_CACHE_TTL_MS) {
    return _cachedProjects;
  }

  try {
    const result = await runJson<{ projects: Array<{ name: string; description?: string }> }>(
      ["project", "list"],
      opts,
    );
    _cachedProjects = (result.projects || []).map((p) => ({
      name: p.name,
      description: p.description,
    }));
    _projectCacheTime = now;
    return _cachedProjects;
  } catch {
    // Non-fatal: return empty if project list fails
    return _cachedProjects || [];
  }
}

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
// LLM-based Extraction (Issue #64 upgrade)
// ============================================================================

/** Result from LLM-based knowledge extraction */
export interface ExtractionResult {
  content: string;
  type: "memory" | "process" | "task";
  tags: string[];
  significance: number;
  project?: string | null;
  scope?: string | null;
}

type RunEmbeddedPiAgentFn = (params: Record<string, unknown>) => Promise<unknown>;

/** Cached loader result (null = not yet attempted, Error = load failed) */
let _embeddedPiAgentLoader: Promise<RunEmbeddedPiAgentFn> | null = null;

/**
 * Load runEmbeddedPiAgent from OpenClaw internals.
 * Mirrors the import pattern used by the llm-task extension.
 */
async function loadRunEmbeddedPiAgent(): Promise<RunEmbeddedPiAgentFn> {
  // Source checkout (tests/dev)
  try {
    const mod = await import("../../../src/agents/pi-embedded-runner.js");
    if (typeof (mod as any).runEmbeddedPiAgent === "function") {
      return (mod as any).runEmbeddedPiAgent;
    }
  } catch {
    // ignore — not in source tree
  }

  // Bundled install
  const distPath = "../../../dist/extensionAPI.js";
  const mod = (await import(distPath)) as { runEmbeddedPiAgent?: unknown };
  const fn = (mod as any).runEmbeddedPiAgent;
  if (typeof fn !== "function") {
    throw new Error("runEmbeddedPiAgent not available in this OpenClaw installation");
  }
  return fn as RunEmbeddedPiAgentFn;
}

/**
 * Get a cached reference to runEmbeddedPiAgent.
 * Returns the function or throws if unavailable.
 */
export function getEmbeddedPiAgent(): Promise<RunEmbeddedPiAgentFn> {
  if (!_embeddedPiAgentLoader) {
    _embeddedPiAgentLoader = loadRunEmbeddedPiAgent();
  }
  return _embeddedPiAgentLoader;
}

/** Reset cached loader (for testing). */
export function resetEmbeddedPiAgentLoader(): void {
  _embeddedPiAgentLoader = null;
}

const EXTRACTION_SYSTEM_PROMPT_BASE = `You are a knowledge extraction engine. Analyze the following conversation exchange and identify information worth remembering long-term.

For each piece of knowledge, return a JSON array of objects:
- "content": concise summary of the knowledge (1-3 sentences)
- "type": "memory" (facts, decisions, preferences), "process" (workflows, procedures, steps), or "task" (action items, todos, commitments)
- "tags": array of significance tags from: ["decision", "lesson", "surprise", "commitment", "correction", "preference", "fact"]
- "significance": 0.0-1.0 how important this is for long-term recall
- "project": which project this belongs to (from known projects list, or null if unclear)
- "scope": "private" (personal preference, agent-specific), "team" (shared knowledge), or "public" (documentation)

Only extract genuinely significant knowledge. Skip small talk, acknowledgments, routine exchanges.
Return empty array [] if nothing is worth remembering.
Return ONLY valid JSON, no markdown fences.`;

/**
 * Build the full extraction prompt, including known projects if available.
 */
function buildExtractionPrompt(projects: CachedProject[]): string {
  if (projects.length === 0) return EXTRACTION_SYSTEM_PROMPT_BASE;
  const projectList = projects
    .map((p) => `${p.name}${p.description ? ` (${p.description})` : ""}`)
    .join(", ");
  return `${EXTRACTION_SYSTEM_PROMPT_BASE}\n\nKnown projects: ${projectList}`;
}

/** Known cheap models per provider */
const CHEAP_MODELS: Record<string, string> = {
  anthropic: "claude-haiku-4",
  openai: "gpt-4.1-mini",
  google: "gemini-2.0-flash",
};

/**
 * Resolve the model to use for extraction based on config.
 * Returns { provider, model } or undefined if no model can be resolved.
 */
export function resolveCaptureModel(
  config: any,
  captureModel?: string,
): { provider: string; model: string } | undefined {
  // 1. Explicit captureModel in plugin config
  if (captureModel && captureModel !== "cheap") {
    const parts = captureModel.split("/");
    if (parts.length >= 2) {
      return { provider: parts[0], model: parts.slice(1).join("/") };
    }
    // If no slash, treat as model name — need provider from defaults
    const defaultsModel = config?.agents?.defaults?.model;
    const primary = typeof defaultsModel === "string"
      ? defaultsModel.trim()
      : (defaultsModel?.primary?.trim() ?? "");
    const defaultProvider = primary.split("/")[0];
    if (defaultProvider) {
      return { provider: defaultProvider, model: captureModel };
    }
  }

  // 2. "cheap" or no captureModel: pick cheapest available model
  const defaultsModel = config?.agents?.defaults?.model;
  const primary = typeof defaultsModel === "string"
    ? defaultsModel.trim()
    : (defaultsModel?.primary?.trim() ?? "");
  const defaultProvider = primary.split("/")[0];
  const defaultModel = primary.split("/").slice(1).join("/");

  if (defaultProvider && CHEAP_MODELS[defaultProvider]) {
    return { provider: defaultProvider, model: CHEAP_MODELS[defaultProvider] };
  }

  // Fallback: use the default model directly
  if (defaultProvider && defaultModel) {
    return { provider: defaultProvider, model: defaultModel };
  }

  return undefined;
}

/**
 * Strip markdown code fences from LLM response.
 */
function stripCodeFences(s: string): string {
  const trimmed = s.trim();
  const m = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  if (m) return (m[1] ?? "").trim();
  return trimmed;
}

/**
 * Collect text payloads from runEmbeddedPiAgent result.
 */
function collectText(payloads: Array<{ text?: string; isError?: boolean }> | undefined): string {
  return (payloads ?? [])
    .filter((p) => !p.isError && typeof p.text === "string")
    .map((p) => p.text ?? "")
    .join("\n")
    .trim();
}

/**
 * Extract knowledge from messages using LLM via runEmbeddedPiAgent.
 * Throws if the LLM call fails (caller should fall back to rule-based).
 */
export async function extractWithLLM(
  messages: unknown[],
  config: any,
  pluginConfig?: { captureModel?: string },
  knownProjects?: CachedProject[],
): Promise<ExtractionResult[]> {
  const runEmbeddedPiAgent = await getEmbeddedPiAgent();

  const resolved = resolveCaptureModel(config, pluginConfig?.captureModel);
  if (!resolved) {
    throw new Error("No model available for LLM extraction");
  }

  // Build exchange text from messages
  const texts = extractMessageTexts(messages);
  const exchangeText = texts
    .filter((t) => t.role === "user" || t.role === "assistant")
    .map((t) => `[${t.role}]: ${t.text}`)
    .join("\n");

  if (!exchangeText.trim()) {
    return [];
  }

  const systemPrompt = buildExtractionPrompt(knownProjects || []);
  const prompt = `${systemPrompt}\n\n--- CONVERSATION ---\n${exchangeText}\n--- END ---`;

  let tmpDir: string | null = null;
  try {
    tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), "palaia-extract-"));
    const sessionId = `palaia-extract-${Date.now()}`;
    const sessionFile = path.join(tmpDir, "session.json");

    const result = await runEmbeddedPiAgent({
      sessionId,
      sessionFile,
      workspaceDir: config?.agents?.defaults?.workspace ?? process.cwd(),
      config,
      prompt,
      timeoutMs: 15_000,
      runId: `palaia-extract-${Date.now()}`,
      provider: resolved.provider,
      model: resolved.model,
      disableTools: true,
      streamParams: { maxTokens: 2048 },
    });

    const text = collectText((result as any).payloads);
    if (!text) return [];

    const raw = stripCodeFences(text);
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      throw new Error(`LLM returned invalid JSON: ${raw.slice(0, 200)}`);
    }

    if (!Array.isArray(parsed)) {
      throw new Error(`LLM returned non-array: ${typeof parsed}`);
    }

    // Validate and normalize each result
    const results: ExtractionResult[] = [];
    for (const item of parsed) {
      if (!item || typeof item !== "object") continue;
      const content = typeof item.content === "string" ? item.content.trim() : "";
      if (!content) continue;

      const validTypes = new Set(["memory", "process", "task"]);
      const type = validTypes.has(item.type) ? item.type : "memory";

      const validTags = new Set([
        "decision", "lesson", "surprise", "commitment",
        "correction", "preference", "fact",
      ]);
      const tags = Array.isArray(item.tags)
        ? item.tags.filter((t: unknown) => typeof t === "string" && validTags.has(t))
        : [];

      const significance = typeof item.significance === "number"
        ? Math.max(0, Math.min(1, item.significance))
        : 0.5;

      const project = typeof item.project === "string" && item.project.trim()
        ? item.project.trim()
        : null;

      const validScopes = new Set(["private", "team", "public"]);
      const scope = typeof item.scope === "string" && validScopes.has(item.scope)
        ? item.scope
        : null;

      results.push({ content, type, tags, significance, project, scope });
    }

    return results;
  } finally {
    if (tmpDir) {
      try { await fs.rm(tmpDir, { recursive: true, force: true }); } catch { /* ignore */ }
    }
  }
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
 * NOTE: This is the rule-based fallback. Primary extraction uses extractWithLLM()
 * via OpenClaw's runEmbeddedPiAgent. Rule-based kicks in when LLM is unavailable.
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

  // ── message_sending (Issue #81: Strip capture hints) ─────────
  // Removes <palaia-hint ... /> tags from outgoing messages so they
  // don't appear in the final output sent to the user.
  api.on("message_sending", (_event: any, _ctx: any) => {
    const content = _event?.content;
    if (typeof content !== "string") return;

    const { hints, cleanedText } = parsePalaiaHints(content);
    if (hints.length > 0 && cleanedText !== content) {
      return { content: cleanedText };
    }
  });

  // ── agent_end (Issue #64 + #81: Auto-Capture with Metadata) ───
  // Analyzes completed exchanges and captures significant content via palaia CLI.
  // Strategy: LLM-based extraction first, rule-based fallback if LLM unavailable.
  // Issue #81 adds: agent attribution, project/scope detection, capture hints.
  if (config.autoCapture) {
    api.on("agent_end", async (event: any, _ctx: any) => {
      if (!event.success || !event.messages || event.messages.length === 0) {
        return;
      }

      try {
        // Resolve agent name from environment
        const agentName = process.env.PALAIA_AGENT || undefined;

        const allTexts = extractMessageTexts(event.messages);

        // Check minimum turns requirement
        const userTurns = allTexts.filter((t) => t.role === "user").length;
        if (userTurns < config.captureMinTurns) return;

        // ── Parse capture hints from all messages (Issue #81) ────
        const collectedHints: PalaiaHint[] = [];
        for (const t of allTexts) {
          const { hints } = parsePalaiaHints(t.text);
          collectedHints.push(...hints);
        }

        // Build exchange text from user + assistant messages
        const exchangeParts: string[] = [];
        for (const t of allTexts) {
          if (t.role === "user" || t.role === "assistant") {
            // Strip hints from exchange text for LLM analysis
            const { cleanedText } = parsePalaiaHints(t.text);
            exchangeParts.push(`[${t.role}]: ${cleanedText}`);
          }
        }
        const exchangeText = exchangeParts.join("\n");

        // Pre-filter: skip trivial exchanges (fast, free)
        if (!shouldAttemptCapture(exchangeText)) return;

        // Load known projects for LLM context
        const knownProjects = await loadProjects(opts);

        // Helper: build CLI args with metadata (agent, project, scope)
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

          // Scope priority: config override > hint > LLM > "team" default
          const scope = config.captureScope || itemScope || "team";
          args.push("--scope", scope);

          // Project priority: config override > hint > LLM
          const project = config.captureProject || itemProject;
          if (project) {
            args.push("--project", project);
          }

          // Agent attribution from env
          if (agentName) {
            args.push("--agent", agentName);
          }

          return args;
        };

        // ── LLM-based extraction (primary) ───────────────────────
        let llmHandled = false;
        try {
          const results = await extractWithLLM(event.messages, api.config, {
            captureModel: config.captureModel,
          }, knownProjects);

          for (const r of results) {
            if (r.significance >= config.captureMinSignificance) {
              // Apply hint overrides: hints take priority over LLM results
              const hintForProject = collectedHints.find((h) => h.project);
              const hintForScope = collectedHints.find((h) => h.scope);

              const effectiveProject = hintForProject?.project || r.project;
              const effectiveScope = hintForScope?.scope || r.scope;

              const args = buildWriteArgs(
                r.content,
                r.type,
                r.tags,
                effectiveProject,
                effectiveScope,
              );
              await run(args, opts);
              console.log(
                `[palaia] LLM auto-captured: type=${r.type}, significance=${r.significance}, tags=${r.tags.join(",")}, project=${effectiveProject || "none"}, scope=${effectiveScope || "team"}`
              );
            }
          }

          llmHandled = true;
        } catch (llmError) {
          console.warn(`[palaia] LLM extraction failed, using rule-based fallback: ${llmError}`);
        }

        // ── Rule-based fallback ──────────────────────────────────
        if (!llmHandled) {
          let captureData: { tags: string[]; type: string; summary: string } | null = null;

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

          // Hint overrides for fallback (no LLM project detection)
          const hintForProject = collectedHints.find((h) => h.project);
          const hintForScope = collectedHints.find((h) => h.scope);

          const args = buildWriteArgs(
            captureData.summary,
            captureData.type,
            captureData.tags,
            hintForProject?.project,
            hintForScope?.scope,
          );

          await run(args, opts);
          console.log(
            `[palaia] Rule-based auto-captured: type=${captureData.type}, tags=${captureData.tags.join(",")}`
          );
        }
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
