/**
 * Auto-capture logic: LLM-based and rule-based extraction.
 *
 * Extracted from hooks.ts during Phase 1.5 decomposition.
 * No logic changes — pure structural refactoring.
 */

import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import type { RunnerOpts } from "../runner.js";
import { isValidScope } from "./state.js";
import { extractMessageTexts } from "./recall.js";

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

export interface CachedProject {
  name: string;
  description?: string;
}

let _cachedProjects: CachedProject[] | null = null;
let _projectCacheTime = 0;
const PROJECT_CACHE_TTL_MS = 60_000;

/** Reset project cache (for testing). */
export function resetProjectCache(): void {
  _cachedProjects = null;
  _projectCacheTime = 0;
}

/**
 * Load known projects from CLI, with caching.
 */
export async function loadProjects(opts: RunnerOpts): Promise<CachedProject[]> {
  const now = Date.now();
  if (_cachedProjects && (now - _projectCacheTime) < PROJECT_CACHE_TTL_MS) {
    return _cachedProjects;
  }

  try {
    const { runJson } = await import("../runner.js");
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
    return _cachedProjects || [];
  }
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

let _embeddedPiAgentLoader: Promise<RunEmbeddedPiAgentFn> | null = null;
/** Whether the LLM import failure has already been logged (to avoid spam). */
let _llmImportFailureLogged = false;

/**
 * Resolve the path to OpenClaw's extensionAPI module.
 * Uses multiple strategies for portability across installation layouts.
 */
function resolveExtensionAPIPath(): string | null {
  // Strategy 1: require.resolve with openclaw package exports
  try {
    return require.resolve("openclaw/dist/extensionAPI.js");
  } catch {
    // Not resolvable via standard module resolution
  }

  // Strategy 2: Resolve openclaw main entry, then navigate to dist/extensionAPI.js
  try {
    const openclawMain = require.resolve("openclaw");
    const candidate = path.join(path.dirname(openclawMain), "extensionAPI.js");
    if (require("node:fs").existsSync(candidate)) return candidate;
  } catch {
    // openclaw not resolvable at all
  }

  // Strategy 3: Sibling in global node_modules (plugin installed alongside openclaw)
  try {
    // __dirname is always available in CJS (our tsconfig module); the ESM
    // fallback via import.meta.url is kept for jiti/ESM loaders at runtime.
    // @ts-expect-error import.meta is valid at runtime under jiti/ESM but TS module=commonjs rejects it
    const thisFile: string = typeof __dirname !== "undefined" ? __dirname : path.dirname(new URL(import.meta.url).pathname);
    // Walk up from plugin src/dist to node_modules, then into openclaw
    let dir = thisFile;
    for (let i = 0; i < 6; i++) {
      const candidate = path.join(dir, "openclaw", "dist", "extensionAPI.js");
      if (require("node:fs").existsSync(candidate)) return candidate;
      const parent = path.dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
  } catch {
    // Traversal failed
  }

  // Strategy 4: Well-known global install paths
  const globalCandidates = [
    path.join(os.homedir(), ".openclaw", "node_modules", "openclaw", "dist", "extensionAPI.js"),
    "/home/linuxbrew/.linuxbrew/lib/node_modules/openclaw/dist/extensionAPI.js",
    "/usr/local/lib/node_modules/openclaw/dist/extensionAPI.js",
    "/usr/lib/node_modules/openclaw/dist/extensionAPI.js",
  ];
  for (const candidate of globalCandidates) {
    try {
      if (require("node:fs").existsSync(candidate)) return candidate;
    } catch {
      // skip
    }
  }

  return null;
}

async function loadRunEmbeddedPiAgent(): Promise<RunEmbeddedPiAgentFn> {
  const resolved = resolveExtensionAPIPath();
  if (!resolved) {
    throw new Error("Could not locate openclaw/dist/extensionAPI.js — tried module resolution, sibling lookup, and global paths");
  }

  const mod = (await import(resolved)) as { runEmbeddedPiAgent?: unknown };
  const fn = (mod as any).runEmbeddedPiAgent;
  if (typeof fn !== "function") {
    throw new Error(`runEmbeddedPiAgent not exported from ${resolved}`);
  }
  return fn as RunEmbeddedPiAgentFn;
}

export function getEmbeddedPiAgent(): Promise<RunEmbeddedPiAgentFn> {
  if (!_embeddedPiAgentLoader) {
    _embeddedPiAgentLoader = loadRunEmbeddedPiAgent();
  }
  return _embeddedPiAgentLoader;
}

/** Reset cached loader (for testing). */
export function resetEmbeddedPiAgentLoader(): void {
  _embeddedPiAgentLoader = null;
  _llmImportFailureLogged = false;
}

/** Override the cached loader with a custom promise (for testing). */
export function setEmbeddedPiAgentLoader(loader: Promise<RunEmbeddedPiAgentFn> | null): void {
  _embeddedPiAgentLoader = loader;
}

/** Expose _llmImportFailureLogged for index.ts to read/write. */
export function getLlmImportFailureLogged(): boolean {
  return _llmImportFailureLogged;
}
export function setLlmImportFailureLogged(value: boolean): void {
  _llmImportFailureLogged = value;
}

const EXTRACTION_SYSTEM_PROMPT_BASE = `You are a knowledge extraction engine. Analyze the following conversation exchange and identify information worth remembering long-term.

For each piece of knowledge, return a JSON array of objects:
- "content": concise summary of the knowledge (1-3 sentences)
- "type": "memory" (facts, decisions, preferences), "process" (workflows, procedures, steps), or "task" (action items, todos, commitments)
- "tags": array of significance tags from: ["decision", "lesson", "surprise", "commitment", "correction", "preference", "fact"]
- "significance": 0.0-1.0 how important this is for long-term recall
- "project": which project this belongs to (from known projects list, or null if unclear)
- "scope": "private" (personal preference, agent-specific), "team" (shared knowledge), or "public" (documentation)

WHAT TO CAPTURE (be thorough — capture anything worth remembering):
- Decisions and agreements ("we decided to...", "let's go with...", "agreed on...")
- Technical discoveries and debugging insights ("the root cause was...", "turns out the issue is...")
- Creative outcomes: naming decisions, design concepts, UX choices, brainstorming results, color schemes, architecture patterns
- User preferences and feedback ("I prefer...", "I like/don't like...", "always use...")
- Project context changes: scope changes, timeline shifts, requirement updates, priority changes
- Workflow patterns the user established ("my process is...", "I always do X before Y")

IMPORTANT: Never classify as "task". Tasks are manually created sticky notes (post-its) — they must only come from explicit user/agent intent via palaia write --type task. Auto-capture must use "memory" or "process" only.
Observations, learnings, insights, opinions, action items, and general knowledge are ALWAYS "memory" or "process", never "task".

Only extract genuinely significant knowledge. Skip small talk, acknowledgments, routine exchanges.
Do NOT extract if similar knowledge was likely captured in a recent exchange. Prefer quality over quantity. Skip routine status updates and acknowledgments.
Return empty array [] if nothing is worth remembering.
Return ONLY valid JSON, no markdown fences.`;

export function buildExtractionPrompt(projects: CachedProject[]): string {
  if (projects.length === 0) return EXTRACTION_SYSTEM_PROMPT_BASE;
  const projectList = projects
    .map((p) => `${p.name}${p.description ? ` (${p.description})` : ""}`)
    .join(", ");
  return `${EXTRACTION_SYSTEM_PROMPT_BASE}\n\nKnown projects: ${projectList}`;
}

/** Whether the captureModel fallback warning has already been logged (to avoid spam). */
let _captureModelFallbackWarned = false;

/** Whether the captureModel->primary model fallback warning has been logged (max 1x per gateway lifetime). */
let _captureModelFailoverWarned = false;

/** Reset captureModel fallback warning flag (for testing). */
export function resetCaptureModelFallbackWarning(): void {
  _captureModelFallbackWarned = false;
  _captureModelFailoverWarned = false;
}

/** Module-level logger reference — set by setLogger(). */
let logger: { info: (...args: any[]) => void; warn: (...args: any[]) => void } = {
  info: (...args: any[]) => console.log(...args),
  warn: (...args: any[]) => console.warn(...args),
};

/** Set the module-level logger (called from hooks/index.ts). */
export function setLogger(l: { info: (...args: any[]) => void; warn: (...args: any[]) => void }): void {
  logger = l;
}

/** Expose _captureModelFailoverWarned for index.ts to read/write. */
export function getCaptureModelFailoverWarned(): boolean {
  return _captureModelFailoverWarned;
}
export function setCaptureModelFailoverWarned(value: boolean): void {
  _captureModelFailoverWarned = value;
}

/**
 * Heuristic patterns to identify cheap/small models from their name.
 * Avoids hardcoded model IDs that go stale — instead matches naming
 * conventions that providers consistently use for their smaller tiers.
 *
 * Patterns are matched as word boundaries (separated by `-`, `.`, `/`,
 * or string edges) to avoid false positives like "ge*mini*" matching "mini".
 */
const CHEAP_MODEL_PATTERNS = [
  "haiku",     // Anthropic's smallest tier
  "flash",     // Google's smallest tier
  "mini",      // OpenAI's smallest tier (gpt-4o-mini, gpt-4.1-mini, ...)
  "small",     // Mistral's smallest tier
  "nano",      // Future small models
  "lite",      // Various providers
  "instant",   // Anthropic legacy
];

/** Check if a model name matches any cheap pattern (word-boundary aware). */
function isCheapModel(modelName: string): boolean {
  const lower = modelName.toLowerCase();
  // Split on common separators: dash, dot, slash, underscore
  const parts = lower.split(/[-./_ ]/);
  return CHEAP_MODEL_PATTERNS.some((p) => parts.includes(p));
}

/**
 * Resolve the model to use for LLM-based capture extraction.
 *
 * Strategy (prefer cheapest available model for cost efficiency):
 * 1. If captureModel is set explicitly (e.g. "anthropic/claude-haiku-4-5"): use it directly.
 * 2. If captureModel is "cheap" or unset: detect the primary model's provider,
 *    then pick the cheapest known model for that provider.
 * 3. If no cheap model is known for the provider, fall back to primary model
 *    with a one-time warning.
 */
export function resolveCaptureModel(
  config: any,
  captureModel?: string,
): { provider: string; model: string } | undefined {
  // Case 1: explicit model ID provided (not "cheap")
  if (captureModel && captureModel !== "cheap") {
    const parts = captureModel.split("/");
    if (parts.length >= 2) {
      return { provider: parts[0], model: parts.slice(1).join("/") };
    }
    // No slash — treat as model name with provider from primary config
    const defaultsModel = config?.agents?.defaults?.model;
    const primary = typeof defaultsModel === "string"
      ? defaultsModel.trim()
      : (defaultsModel?.primary?.trim() ?? "");
    const defaultProvider = primary.split("/")[0];
    if (defaultProvider) {
      return { provider: defaultProvider, model: captureModel };
    }
  }

  // Case 2: "cheap" or unset — use primary model, but check if it's already cheap
  const defaultsModel = config?.agents?.defaults?.model;

  const primary = typeof defaultsModel === "string"
    ? defaultsModel.trim()
    : (typeof defaultsModel === "object" && defaultsModel !== null
      ? String(defaultsModel.primary ?? "").trim()
      : "");

  if (primary) {
    const parts = primary.split("/");
    if (parts.length >= 2) {
      const provider = parts[0];
      const modelName = parts.slice(1).join("/");

      // Check if the primary model is already cheap (e.g., user runs haiku as main)
      if (isCheapModel(modelName)) {
        return { provider, model: modelName };
      }

      // Primary is expensive — check if the runtime exposes available models
      // so we can pick a cheap one from the same provider dynamically.
      const runtimeModels: string[] = config?.runtime?.availableModels
        ?? config?.models
        ?? [];
      const cheapFromRuntime = runtimeModels.find((m: string) => {
        const lower = m.toLowerCase();
        return lower.startsWith(provider + "/") && isCheapModel(m);
      });
      if (cheapFromRuntime) {
        const rParts = cheapFromRuntime.split("/");
        return { provider: rParts[0], model: rParts.slice(1).join("/") };
      }

      // No cheap alternative found — use primary model with one-time hint
      if (!_captureModelFallbackWarned) {
        _captureModelFallbackWarned = true;
        logger.warn(`[palaia] Using primary model for capture extraction. Set captureModel in plugin config (e.g. "anthropic/claude-haiku-4-5") for cost savings.`);
      }
      return { provider, model: modelName };
    }
  }

  return undefined;
}

function stripCodeFences(s: string): string {
  const trimmed = s.trim();
  const m = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  if (m) return (m[1] ?? "").trim();
  return trimmed;
}

function collectText(payloads: Array<{ text?: string; isError?: boolean }> | undefined): string {
  return (payloads ?? [])
    .filter((p) => !p.isError && typeof p.text === "string")
    .map((p) => p.text ?? "")
    .join("\n")
    .trim();
}

/**
 * Trim message texts to a recent window for LLM extraction.
 * Only extract from recent exchanges — full history causes LLM timeouts
 * and dilutes extraction quality.
 *
 * Strategy: keep last N user+assistant pairs (skip toolResult roles),
 * then hard-cap at maxChars from the end (newest messages kept).
 */
export function trimToRecentExchanges(
  texts: Array<{ role: string; text: string; provenance?: string }>,
  maxPairs = 5,
  maxChars = 10_000,
): Array<{ role: string; text: string; provenance?: string }> {
  // Filter to only user + assistant messages (skip tool, toolResult, system, etc.)
  const exchanges = texts.filter((t) => t.role === "user" || t.role === "assistant");

  // Keep the last N pairs (a pair = one user + one assistant message)
  // Only count external_user messages as real user turns.
  // System-injected user messages (inter_session, internal_system) don't count as conversation turns.
  // Walk backwards, count pairs
  let pairCount = 0;
  let lastRole = "";
  let cutIndex = 0; // default: keep everything
  for (let i = exchanges.length - 1; i >= 0; i--) {
    const isRealUser = exchanges[i].role === "user" && (
      exchanges[i].provenance === "external_user" ||
      !exchanges[i].provenance // backward compat: no provenance = treat as real user
    );
    // Count a new pair when we see a real user message after having seen an assistant
    if (isRealUser && lastRole === "assistant") {
      pairCount++;
      if (pairCount > maxPairs) {
        cutIndex = i + 1; // keep from next message onwards
        break;
      }
    }
    if (exchanges[i].role !== lastRole) {
      lastRole = exchanges[i].role;
    }
  }
  let trimmed = exchanges.slice(cutIndex);

  // Hard cap: max chars from the end (keep newest)
  let totalChars = trimmed.reduce((sum, t) => sum + t.text.length + t.role.length + 5, 0);
  while (totalChars > maxChars && trimmed.length > 1) {
    const removed = trimmed.shift()!;
    totalChars -= removed.text.length + removed.role.length + 5;
  }

  return trimmed;
}

export async function extractWithLLM(
  messages: unknown[],
  config: any,
  pluginConfig?: { captureModel?: string; workspace?: string },
  knownProjects?: CachedProject[],
): Promise<ExtractionResult[]> {
  const runEmbeddedPiAgent = await getEmbeddedPiAgent();

  const resolved = resolveCaptureModel(config, pluginConfig?.captureModel);
  if (!resolved) {
    throw new Error("No model available for LLM extraction");
  }

  const allTexts = extractMessageTexts(messages);
  // Strip palaia-injected recall context and private blocks from user messages
  const cleanedTexts = allTexts.map(t =>
    t.role === "user"
      ? { ...t, text: stripPrivateBlocks(strippalaiaInjectedContext(t.text)) }
      : { ...t, text: stripPrivateBlocks(t.text) }
  );
  // Only extract from recent exchanges — full history causes LLM timeouts
  // and dilutes extraction quality
  const recentTexts = trimToRecentExchanges(cleanedTexts);
  const exchangeText = recentTexts
    .map((t) => `[${t.role}]: ${t.text}`)
    .join("\n");

  if (!exchangeText.trim()) {
    return [];
  }

  const systemPrompt = buildExtractionPrompt(knownProjects || []);
  const prompt = `${systemPrompt}\n\n--- CONVERSATION ---\n${exchangeText}\n--- END ---`;

  let tmpDir: string | null = null;
  try {
    // Use a fixed base directory for extraction temp dirs and clean up stale ones
    const extractBaseDir = path.join(os.tmpdir(), "palaia-extractions");
    await fs.mkdir(extractBaseDir, { recursive: true });
    // Clean up stale extraction dirs (older than 5 minutes)
    try {
      const entries = await fs.readdir(extractBaseDir, { withFileTypes: true });
      const now = Date.now();
      for (const entry of entries) {
        if (entry.isDirectory()) {
          try {
            const stat = await fs.stat(path.join(extractBaseDir, entry.name));
            if (now - stat.mtimeMs > 5 * 60 * 1000) {
              await fs.rm(path.join(extractBaseDir, entry.name), { recursive: true, force: true });
            }
          } catch { /* ignore individual cleanup errors */ }
        }
      }
    } catch { /* ignore cleanup errors */ }
    tmpDir = await fs.mkdtemp(path.join(extractBaseDir, "ext-"));
    const sessionId = `palaia-extract-${Date.now()}`;
    const sessionFile = path.join(tmpDir, "session.json");

    const result = await runEmbeddedPiAgent({
      sessionId,
      sessionFile,
      workspaceDir: pluginConfig?.workspace || config?.agents?.defaults?.workspace || process.cwd(),
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

    const results: ExtractionResult[] = [];
    for (const item of parsed) {
      if (!item || typeof item !== "object") continue;
      const content = typeof item.content === "string" ? item.content.trim() : "";
      if (!content) continue;

      const validTypes = new Set(["memory", "process"]);
      // Tasks are manual-only (post-its) — auto-capture never creates tasks
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

      const scope = typeof item.scope === "string" && isValidScope(item.scope)
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

const TRIVIAL_RESPONSES = new Set([
  "ok", "ja", "nein", "yes", "no", "sure", "klar", "danke", "thanks",
  "thx", "k", "\u{1f44d}", "\u{1f44e}", "ack", "nope", "yep", "yup", "alright",
  "fine", "gut", "passt", "okay", "hmm", "hm", "ah", "aha",
]);

const SIGNIFICANCE_RULES: Array<{
  pattern: RegExp;
  tag: string;
  type: "memory" | "process" | "task";
}> = [
  // Decisions and agreements
  { pattern: /(?:we decided|entschieden|decision:|beschlossen|let'?s go with|wir nehmen|agreed on)/i, tag: "decision", type: "memory" },
  { pattern: /(?:will use|werden nutzen|going forward|ab jetzt|from now on)/i, tag: "decision", type: "memory" },
  // Creative outcomes: naming, design, UX, brainstorming
  { pattern: /(?:(?:we|i|let'?s)\s+(?:decided to |chose to )?(?:name|call|rename)\s+(?:it|this|the))/i, tag: "decision", type: "memory" },
  { pattern: /(?:the design should|design concept|color scheme|colour scheme|UX flow|user flow|wireframe|mockup)/i, tag: "decision", type: "memory" },
  { pattern: /(?:brainstorming results|brainstorm(?:ed)?|ideas?\s+(?:for|are)|naming convention)/i, tag: "decision", type: "memory" },
  { pattern: /(?:the (?:logo|icon|brand|theme|layout|style)\s+(?:should|will|is))/i, tag: "decision", type: "memory" },
  // Technical discoveries and debugging insights
  { pattern: /(?:root cause|the (?:issue|bug|problem) (?:was|is)|figured out|the fix (?:is|was)|debugging showed)/i, tag: "lesson", type: "memory" },
  { pattern: /(?:learned|gelernt|lesson:|erkenntnis|takeaway|insight|turns out|it seems)/i, tag: "lesson", type: "memory" },
  { pattern: /(?:mistake was|fehler war|should have|hätten sollen|next time)/i, tag: "lesson", type: "memory" },
  // Surprises
  { pattern: /(?:surprising|überraschend|unexpected|unerwartet|didn'?t expect|nicht erwartet|plot twist)/i, tag: "surprise", type: "memory" },
  // Commitments (captured as memory — tasks are manual-only post-its)
  { pattern: /(?:i will|ich werde|todo:|action item|must do|muss noch|need to|commit to|verspreche)/i, tag: "commitment", type: "memory" },
  { pattern: /(?:deadline|frist|due date|bis zum|by end of|spätestens)/i, tag: "commitment", type: "memory" },
  // Processes and workflows
  { pattern: /(?:the process is|der prozess|steps?:|workflow:|how to|anleitung|recipe:|checklist)/i, tag: "process", type: "process" },
  { pattern: /(?:first,?\s.*then|schritt \d|step \d|1\.\s.*2\.\s)/i, tag: "process", type: "process" },
  // User preferences and feedback
  { pattern: /(?:(?:i|the user)\s+prefer|i (?:like|don'?t like|always use|never use)|my (?:go-to|default|standard))/i, tag: "preference", type: "memory" },
  { pattern: /(?:bevorzug|mag ich|immer nutzen|standard(?:mäßig)?(?:\s+ist|\s+nutze))/i, tag: "preference", type: "memory" },
  // Project context changes
  { pattern: /(?:scope (?:change|creep|update)|timeline (?:shift|change|update)|requirement(?:s)? (?:change|update)|priority (?:change|shift))/i, tag: "decision", type: "memory" },
  { pattern: /(?:pivot(?:ed|ing)?|(?:re)?scoped|descoped|deferred|postponed|moved to (?:next|later))/i, tag: "decision", type: "memory" },
];

const NOISE_PATTERNS: RegExp[] = [
  /(?:PASSED|FAILED|ERROR)\s+\[?\d+%\]?/i,
  /(?:test_\w+|tests?\/\w+\.(?:py|ts|js))\s*::/,
  /(?:pytest|vitest|jest|mocha)\s+(?:run|--)/i,
  /\d+ passed,?\s*\d* (?:failed|error|warning)/i,
  /^(?:=+\s*(?:test session|ERRORS|FAILURES|short test summary))/m,
  /(?:Traceback \(most recent call last\)|^\s+File ".*", line \d+)/m,
  /^\s+at\s+\S+\s+\(.*:\d+:\d+\)/m,
  /^(?:\/[\w/.-]+){3,}\s*$/m,
  /(?:npm\s+(?:ERR|WARN)|pip\s+install|cargo\s+build)/i,
  /^(?:warning|error)\[?\w*\]?:\s/m,
];

export function isNoiseContent(text: string): boolean {
  let matchCount = 0;
  for (const pattern of NOISE_PATTERNS) {
    if (pattern.test(text)) {
      matchCount++;
      if (matchCount >= 2) return true;
    }
  }

  const lines = text.split("\n").filter((l) => l.trim().length > 0);
  if (lines.length > 3) {
    const pathLines = lines.filter((l) => /^\s*(?:\/[\w/.-]+){2,}/.test(l.trim()));
    if (pathLines.length / lines.length > 0.5) return true;
  }

  return false;
}

export function shouldAttemptCapture(
  exchangeText: string,
  minChars = 100,
): boolean {
  const trimmed = exchangeText.trim();

  if (trimmed.length < minChars) return false;

  const words = trimmed.toLowerCase().split(/\s+/);
  if (words.length <= 3 && words.every((w) => TRIVIAL_RESPONSES.has(w))) {
    return false;
  }

  if (trimmed.includes("<relevant-memories>")) return false;
  if (trimmed.startsWith("<") && trimmed.includes("</")) return false;

  if (isNoiseContent(trimmed)) return false;

  return true;
}

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

  // Require at least 2 different significance tags for rule-based capture
  const uniqueTags = new Set(matched.map((m) => m.tag));
  if (uniqueTags.size < 2) return null;

  const typePriority: Record<string, number> = { task: 3, process: 2, memory: 1 };
  const primaryType = matched.reduce(
    (best, m) => (typePriority[m.type] > typePriority[best] ? m.type : best),
    "memory" as "memory" | "process" | "task",
  );

  const tags = [...new Set(matched.map((m) => m.tag))];

  const sentences = exchangeText
    .split(/[.!?\n]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 20 && s.length < 500);

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
 * Strip palaia-injected recall context from message text.
 * The recall block is prepended to user messages by before_prompt_build via prependContext.
 * OpenClaw merges it into the user message, so agent_end sees it as user content.
 * Without stripping, auto-capture re-captures the injected memories -> feedback loop.
 *
 * The block has a stable structure:
 * - Starts with "## Active Memory (palaia)"
 * - Contains [t/m], [t/pr], [t/tk] prefixed entries
 * - Ends with "[palaia] auto-capture=on..." nudge line
 */
export function strippalaiaInjectedContext(text: string): string {
  // Pattern: "## Active Memory (palaia)" ... "[palaia] auto-capture=on..." + optional trailing newlines
  // The nudge line is always present and marks the end of the injected block
  const PALAIA_BLOCK_RE = /## Active Memory \(palaia\)[\s\S]*?\[palaia\][^\n]*\n*/;
  // Also strip Session Briefing blocks
  const BRIEFING_BLOCK_RE = /## Session Briefing \(palaia\)[\s\S]*?(?=\n##|\n\n\n|$)/;
  return text
    .replace(PALAIA_BLOCK_RE, '')
    .replace(BRIEFING_BLOCK_RE, '')
    .trim();
}

/**
 * Strip <private>...</private> blocks from text.
 * Content inside private tags is excluded from memory capture.
 * Inspired by claude-mem's privacy marker system.
 */
export function stripPrivateBlocks(text: string): string {
  return text.replace(/<private>[\s\S]*?<\/private>/gi, '').trim();
}
