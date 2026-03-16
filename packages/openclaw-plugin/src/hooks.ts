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
import { appendFileSync } from "node:fs";
import path from "node:path";
import os from "node:os";
import { run, runJson, recover, type RunnerOpts } from "./runner.js";
import type { PalaiaPluginConfig, RecallTypeWeights } from "./config.js";

const DEBUG_LOG = "/tmp/palaia-reactions-debug.log";
function debugLog(msg: string): void {
  try {
    appendFileSync(DEBUG_LOG, `[${new Date().toISOString()}] ${msg}\n`);
  } catch { /* ignore */ }
}

// ============================================================================
// Turn-level State (Issue #87: Transparency Features)
// ============================================================================
// Session-scoped state to prevent cross-session leakage (Issue #XX).
// Each agent session gets its own TurnState, keyed by sessionKey.

interface TurnState {
  /** Entries injected by before_prompt_build for footnote attribution. */
  lastInjectedEntries: Array<{ title: string; date: string }>;
  /** Summaries of auto-captured content from agent_end for confirmation display. */
  lastCapturedSummaries: string[];
  /** Whether recall (memory injection) occurred in this turn. */
  recallOccurred: boolean;
  /** Last inbound user message ID (for emoji reactions). */
  lastUserMessageId?: string;
  /** Channel ID from the last inbound event. */
  lastChannelId?: string;
  /** Timestamp when the turn started (Date.now()). */
  turnStartMs?: number;
}

function emptyTurnState(): TurnState {
  return { lastInjectedEntries: [], lastCapturedSummaries: [], recallOccurred: false };
}

/** Session-scoped turn state map. Key = sessionKey or "__default__". */
const _sessionTurnState = new Map<string, TurnState>();

const DEFAULT_SESSION_KEY = "__default__";

/** Get turn state for a session (creates if absent). */
function getTurnState(sessionKey?: string): TurnState {
  const key = sessionKey || DEFAULT_SESSION_KEY;
  let state = _sessionTurnState.get(key);
  if (!state) {
    state = emptyTurnState();
    _sessionTurnState.set(key, state);
  }
  return state;
}

/**
 * Extract session key from event or context.
 * Tries event.sessionKey, ctx.sessionKey, event.session?.key, ctx.session?.key.
 */
function resolveSessionKey(event?: Record<string, unknown>, ctx?: Record<string, unknown>): string {
  if (event) {
    if (typeof event.sessionKey === "string" && event.sessionKey) return event.sessionKey;
    if (event.session && typeof event.session === "object" && typeof (event.session as Record<string, unknown>).key === "string") {
      return (event.session as Record<string, unknown>).key as string;
    }
  }
  if (ctx) {
    if (typeof ctx.sessionKey === "string" && ctx.sessionKey) return ctx.sessionKey;
    if (ctx.session && typeof ctx.session === "object" && typeof (ctx.session as Record<string, unknown>).key === "string") {
      return (ctx.session as Record<string, unknown>).key as string;
    }
  }
  return DEFAULT_SESSION_KEY;
}

/** Reset turn state for all sessions (for testing). */
export function resetTurnState(): void {
  _sessionTurnState.clear();
}

// ============================================================================
// Plugin State Persistence (Issue #87: Recall counter for nudges)
// ============================================================================

interface PluginState {
  successfulRecalls: number;
  satisfactionNudged: boolean;
  transparencyNudged: boolean;
  firstRecallTimestamp: string | null;
}

const DEFAULT_PLUGIN_STATE: PluginState = {
  successfulRecalls: 0,
  satisfactionNudged: false,
  transparencyNudged: false,
  firstRecallTimestamp: null,
};

async function loadPluginState(workspace?: string): Promise<PluginState> {
  const dir = workspace || process.cwd();
  const statePath = path.join(dir, ".palaia", "plugin-state.json");
  try {
    const raw = await fs.readFile(statePath, "utf-8");
    return { ...DEFAULT_PLUGIN_STATE, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULT_PLUGIN_STATE };
  }
}

async function savePluginState(state: PluginState, workspace?: string): Promise<void> {
  const dir = workspace || process.cwd();
  const statePath = path.join(dir, ".palaia", "plugin-state.json");
  try {
    await fs.writeFile(statePath, JSON.stringify(state, null, 2));
  } catch {
    // Non-fatal
  }
}

// ============================================================================
// Emoji Reaction Helper (Issue #87 v2: Reactions instead of Footnotes)
// ============================================================================

/**
 * Send an emoji reaction via the OpenClaw Gateway HTTP API.
 * Fails silently (console.warn) — reactions are non-critical.
 * @param emoji - Emoji name without colons, e.g. "brain", "floppy_disk"
 * @param channelId - Channel provider name (e.g. "slack", "telegram")
 * @param messageId - Optional message ID to react to
 * @param target - Optional target (e.g. "channel:C0AKE2G15HV"), extracted from session key
 */
export async function sendReaction(
  emoji: string,
  channelId: string,
  messageId?: string,
  target?: string,
): Promise<boolean> {
  const gatewayPort = process.env.OPENCLAW_GATEWAY_PORT || "18789";
  const gatewayToken = process.env.OPENCLAW_GATEWAY_TOKEN || "";

  const body: Record<string, unknown> = {
    action: "react",
    channel: channelId,
    emoji,
  };
  if (messageId) {
    body.messageId = messageId;
  }
  if (target) {
    body.target = target;
  }

  debugLog(`sendReaction: emoji=${emoji}, channel=${channelId}, messageId=${messageId}, target=${target}, body=${JSON.stringify(body)}`);

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);

    const response = await fetch(`http://127.0.0.1:${gatewayPort}/api/message`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(gatewayToken ? { Authorization: `Bearer ${gatewayToken}` } : {}),
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });

    clearTimeout(timeout);

    if (!response.ok) {
      const respText = await response.text().catch(() => "");
      debugLog(`sendReaction: FAILED (${response.status}): ${emoji} on ${channelId} — ${respText}`);
      console.warn(`[palaia] Reaction failed (${response.status}): ${emoji} on ${channelId}`);
      return false;
    }
    debugLog(`sendReaction: OK ${emoji} on ${channelId}`);
    return true;
  } catch (error) {
    debugLog(`sendReaction: ERROR ${error}`);
    console.warn(`[palaia] Reaction error: ${error}`);
    return false;
  }
}

// ============================================================================
// Content-Hash Matching for Bot Reply Reactions
// ============================================================================

/**
 * Normalize text for content-based message matching.
 * Lowercases, strips markdown, collapses whitespace, trims, truncates to 80 chars.
 */
export function normalizeForMatch(text: string): string {
  return text
    .toLowerCase()
    .replace(/[*_`~\[\]()]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80);
}

/**
 * Extract channel target from a session key.
 * e.g. "agent:main:slack:channel:c0ake2g15hv" → "channel:C0AKE2G15HV"
 */
export function extractTargetFromSessionKey(sessionKey: string): string | undefined {
  // Pattern: ...:<targetType>:<targetId>
  const parts = sessionKey.split(":");
  // Find "channel" or "dm" or similar target type in the parts
  for (let i = 0; i < parts.length - 1; i++) {
    if (parts[i] === "channel" || parts[i] === "dm" || parts[i] === "group") {
      return `${parts[i]}:${parts[i + 1].toUpperCase()}`;
    }
  }
  return undefined;
}

/**
 * Extract channel provider from a session key.
 * e.g. "agent:main:slack:channel:c0ake2g15hv" → "slack"
 */
export function extractChannelFromSessionKey(sessionKey: string): string | undefined {
  const parts = sessionKey.split(":");
  // Pattern: agent:<name>:<channel>:<targetType>:<targetId>
  // The channel provider is at index 2
  if (parts.length >= 5 && parts[0] === "agent") {
    return parts[2];
  }
  return undefined;
}

/**
 * Find the bot's reply message by matching normalized content against recent channel messages.
 * Uses Gateway API to read recent messages, then prefix-matches normalized text.
 */
export async function findBotReplyByContent(
  channelId: string,
  responseText: string,
  sessionKey: string,
): Promise<string | undefined> {
  const needle = normalizeForMatch(responseText);
  if (!needle || needle.length < 10) {
    debugLog(`findBotReplyByContent: needle too short (${needle.length}), skipping`);
    return undefined;
  }
  const matchPrefix = needle.slice(0, 40);

  const target = extractTargetFromSessionKey(sessionKey);
  if (!target) {
    debugLog(`findBotReplyByContent: could not extract target from sessionKey=${sessionKey}`);
    return undefined;
  }

  const gatewayPort = process.env.OPENCLAW_GATEWAY_PORT || "18789";
  const gatewayToken = process.env.OPENCLAW_GATEWAY_TOKEN || "";

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);

    const body = {
      action: "read",
      channel: channelId,
      target,
      limit: 5,
    };

    debugLog(`findBotReplyByContent: POST /api/message body=${JSON.stringify(body)}`);

    const response = await fetch(`http://127.0.0.1:${gatewayPort}/api/message`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(gatewayToken ? { Authorization: `Bearer ${gatewayToken}` } : {}),
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });

    clearTimeout(timeout);

    if (!response.ok) {
      debugLog(`findBotReplyByContent: API returned ${response.status}`);
      return undefined;
    }

    const data = await response.json() as { messages?: Array<Record<string, unknown>> };
    const messages = data.messages || (Array.isArray(data) ? data : []) as Array<Record<string, unknown>>;

    debugLog(`findBotReplyByContent: got ${messages.length} messages`);

    for (const msg of messages) {
      const msgText = typeof msg.text === "string" ? msg.text
        : typeof msg.content === "string" ? msg.content
        : typeof msg.body === "string" ? msg.body
        : "";
      if (!msgText) continue;

      const normalized = normalizeForMatch(msgText);
      if (normalized.startsWith(matchPrefix)) {
        const msgId = (msg.id || msg.ts || msg.messageId) as string | undefined;
        debugLog(`findBotReplyByContent: MATCH found, msgId=${msgId}, normalized prefix=${normalized.slice(0, 40)}`);
        return msgId;
      }
    }

    debugLog(`findBotReplyByContent: no match found. needle prefix="${matchPrefix}"`);
    return undefined;
  } catch (error) {
    debugLog(`findBotReplyByContent: ERROR ${error}`);
    console.warn(`[palaia] findBotReplyByContent error: ${error}`);
    return undefined;
  }
}

// ============================================================================
// Footnote Helpers (Issue #87)
// ============================================================================

/**
 * Format an ISO date string as a short date: "Mar 16", "Feb 10".
 */
export function formatShortDate(isoDate: string): string {
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  try {
    const d = new Date(isoDate);
    if (isNaN(d.getTime())) return "";
    return `${months[d.getMonth()]} ${d.getDate()}`;
  } catch {
    return "";
  }
}

/**
 * Check if an injected entry is relevant to the response text.
 * Simple keyword overlap: split title into words, check if >=2 words appear
 * in the response (case-insensitive). Words shorter than 3 chars are skipped.
 */
export function isEntryRelevant(title: string, responseText: string): boolean {
  const responseLower = responseText.toLowerCase();
  const titleWords = title
    .toLowerCase()
    .split(/[\s\-_/]+/)
    .filter((w) => w.length >= 3);
  if (titleWords.length === 0) return false;
  // For single-word titles, require that one word to match
  const threshold = titleWords.length === 1 ? 1 : 2;
  let matches = 0;
  for (const word of titleWords) {
    if (responseLower.includes(word)) {
      matches++;
      if (matches >= threshold) return true;
    }
  }
  return false;
}

/**
 * Build a memory source footnote string from injected entries and response text.
 * Returns null if no relevant entries found.
 */
export function buildFootnote(
  entries: Array<{ title: string; date: string }>,
  _responseText: string,
  maxEntries = 3,
): string | null {
  // All injected entries were already selected by semantic search — no additional
  // keyword filtering needed. Show top-N as attribution footnotes.
  if (entries.length === 0) return null;

  const display = entries.slice(0, maxEntries);
  const parts = display.map((e) => {
    const dateStr = formatShortDate(e.date);
    return dateStr ? `"${e.title}" (${dateStr})` : `"${e.title}"`;
  });
  return `\n\n📎 Palaia: ${parts.join(", ")}`;
}

// ============================================================================
// Satisfaction / Transparency Nudge Helpers (Issue #87)
// ============================================================================

const SATISFACTION_THRESHOLD = 10;
const TRANSPARENCY_RECALL_THRESHOLD = 50;
const TRANSPARENCY_DAYS_THRESHOLD = 7;

const SATISFACTION_NUDGE_TEXT =
  "Dein User nutzt Palaia jetzt seit einer Weile. " +
  "Frag ihn dezent, ob er mit dem Memory-System zufrieden ist. " +
  "Bei Problemen: schlage `palaia doctor` vor.";

const TRANSPARENCY_NUDGE_TEXT =
  "Dein User sieht jetzt seit einigen Tagen Memory-Footnotes und Capture-Bestätigungen. " +
  "Frag ihn einmalig: 'Möchtest du die Memory-Quellenangaben und Speicher-Bestätigungen " +
  "weiterhin sehen, oder soll ich sie ausblenden? Du kannst das jederzeit wieder ändern.' " +
  "Je nach Antwort: `palaia config set showMemorySources true/false` und " +
  "`palaia config set showCaptureConfirm true/false`";

/**
 * Check which nudges (if any) should fire based on plugin state.
 * Returns nudge texts to prepend, and updates state accordingly.
 */
export function checkNudges(state: PluginState): { nudges: string[]; updated: boolean } {
  const nudges: string[] = [];
  let updated = false;

  // Satisfaction check: after 10 recalls, one-shot
  if (!state.satisfactionNudged && state.successfulRecalls >= SATISFACTION_THRESHOLD) {
    nudges.push(SATISFACTION_NUDGE_TEXT);
    state.satisfactionNudged = true;
    updated = true;
  }

  // Transparency preference: after 50 recalls OR 7 days, one-shot
  if (!state.transparencyNudged && state.firstRecallTimestamp) {
    const daysSinceFirst = (Date.now() - new Date(state.firstRecallTimestamp).getTime()) / (1000 * 60 * 60 * 24);
    if (state.successfulRecalls >= TRANSPARENCY_RECALL_THRESHOLD || daysSinceFirst >= TRANSPARENCY_DAYS_THRESHOLD) {
      nudges.push(TRANSPARENCY_NUDGE_TEXT);
      state.transparencyNudged = true;
      updated = true;
    }
  }

  return { nudges, updated };
}

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
 * Patterns that indicate machine/tool output rather than human knowledge.
 * Content matching these should not be captured as significant.
 */
const NOISE_PATTERNS: RegExp[] = [
  // Test output (pytest, vitest, jest, etc.)
  /(?:PASSED|FAILED|ERROR)\s+\[?\d+%\]?/i,
  /(?:test_\w+|tests?\/\w+\.(?:py|ts|js))\s*::/,
  /(?:pytest|vitest|jest|mocha)\s+(?:run|--)/i,
  /\d+ passed,?\s*\d* (?:failed|error|warning)/i,
  /^(?:=+\s*(?:test session|ERRORS|FAILURES|short test summary))/m,
  // Stack traces
  /(?:Traceback \(most recent call last\)|^\s+File ".*", line \d+)/m,
  /^\s+at\s+\S+\s+\(.*:\d+:\d+\)/m,
  // CLI output / file paths as main content
  /^(?:\/[\w/.-]+){3,}\s*$/m,
  // Build/CI output
  /(?:npm\s+(?:ERR|WARN)|pip\s+install|cargo\s+build)/i,
  /^(?:warning|error)\[?\w*\]?:\s/m,
];

/**
 * Check if text is predominantly machine/tool output (test results, stack traces, etc.).
 * Returns true if the text appears to be noise rather than human knowledge.
 */
export function isNoiseContent(text: string): boolean {
  let matchCount = 0;
  for (const pattern of NOISE_PATTERNS) {
    if (pattern.test(text)) {
      matchCount++;
      if (matchCount >= 2) return true; // 2+ noise signals = definitely noise
    }
  }

  // Also check: if >50% of lines look like file paths, it's noise
  const lines = text.split("\n").filter((l) => l.trim().length > 0);
  if (lines.length > 3) {
    const pathLines = lines.filter((l) => /^\s*(?:\/[\w/.-]+){2,}/.test(l.trim()));
    if (pathLines.length / lines.length > 0.5) return true;
  }

  return false;
}

/**
 * Pre-filter: Should this exchange even be considered for capture?
 * Returns false for trivial, too-short, system-generated, or noise content.
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

  // Skip machine/tool output (test results, stack traces, CI logs)
  if (isNoiseContent(trimmed)) return false;

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
  debugLog(`registerHooks: called, autoCapture=${config.autoCapture}, memoryInject=${config.memoryInject}, showMemorySources=${config.showMemorySources}, showCaptureConfirm=${config.showCaptureConfirm}`);
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
              // palaia query supports --limit but NOT --tier; use --all for tier=all
              const queryArgs: string[] = ["query", userMessage, "--limit", String(limit)];
              if (config.tier === "all") {
                queryArgs.push("--all");
              }
              const result = await runJson<QueryResult>(queryArgs, opts);
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
        // palaia list supports --tier but NOT --limit; use --all for tier=all
        if (entries.length === 0) {
          try {
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

        // Track injected entries and recall state (Issue #87)
        // Session-scoped to prevent cross-session leakage
        const sessionKey = resolveSessionKey(event, _ctx);
        const turnState = getTurnState(sessionKey);
        turnState.lastInjectedEntries = ranked.map((e) => {
          // Find original entry to get created date
          const orig = entries.find((o) => o.id === e.id);
          return {
            title: e.title,
            date: (orig as any)?.created || new Date().toISOString(),
          };
        });

        // Flag that recall occurred (for emoji reaction in agent_end)
        turnState.recallOccurred = true;

        // Track turn start time
        turnState.turnStartMs = Date.now();

        // Capture user message ID and channel for reactions
        if (event.messages && Array.isArray(event.messages)) {
          for (let i = event.messages.length - 1; i >= 0; i--) {
            const msg = event.messages[i] as Record<string, unknown>;
            if (msg?.role === "user") {
              if (typeof msg.id === "string") turnState.lastUserMessageId = msg.id;
              else if (typeof msg.messageId === "string") turnState.lastUserMessageId = msg.messageId;
              else if (typeof msg.ts === "string") turnState.lastUserMessageId = msg.ts;
              break;
            }
          }
        }
        // Capture channel ID from context
        if (_ctx && typeof _ctx === "object") {
          const ctx = _ctx as Record<string, unknown>;
          if (typeof ctx.channelId === "string") turnState.lastChannelId = ctx.channelId;
          else if (typeof ctx.sessionKey === "string") turnState.lastChannelId = ctx.sessionKey;
        }

        // Update recall counter for satisfaction/transparency nudges (Issue #87)
        let nudgeContext = "";
        try {
          const pluginState = await loadPluginState(config.workspace);
          pluginState.successfulRecalls++;
          if (!pluginState.firstRecallTimestamp) {
            pluginState.firstRecallTimestamp = new Date().toISOString();
          }
          const { nudges, updated } = checkNudges(pluginState);
          if (nudges.length > 0) {
            nudgeContext = "\n\n## Agent Nudge (Palaia)\n\n" + nudges.join("\n\n");
          }
          // Always save: recall count changed, nudges may have updated
          await savePluginState(pluginState, config.workspace);
        } catch {
          // Non-fatal: nudge tracking failure should not break recall
        }

        // Use prependContext for per-turn dynamic memory injection
        return { prependContext: text + nudgeContext };
      } catch (error) {
        // Non-fatal: if memory injection fails, agent continues without it
        console.warn(`[palaia] Memory injection failed: ${error}`);
      }
    });
  }

  // ── message_sending (Issue #81: Hint stripping) ──────────────────
  // Strip <palaia-hint /> tags from outgoing messages.
  // Footnotes and capture confirms are now handled via emoji reactions
  // in agent_end (Issue #87 v2) since message_sending is bypassed on Slack.
  api.on("message_sending", (_event: any, _ctx: any) => {
    const content = _event?.content;
    if (typeof content !== "string") return;

    // Strip capture hints
    const { hints, cleanedText } = parsePalaiaHints(content);
    if (hints.length > 0) {
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
              // Track for capture confirm (Issue #87) — session-scoped
              const captureSessionKey = resolveSessionKey(event, _ctx);
              const captureTurnState = getTurnState(captureSessionKey);
              captureTurnState.lastCapturedSummaries.push(r.content.slice(0, 80));
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
          // Track for capture confirm (Issue #87) — session-scoped
          const fallbackSessionKey = resolveSessionKey(event, _ctx);
          const fallbackTurnState = getTurnState(fallbackSessionKey);
          fallbackTurnState.lastCapturedSummaries.push(captureData.summary.slice(0, 80));
          console.log(
            `[palaia] Rule-based auto-captured: type=${captureData.type}, tags=${captureData.tags.join(",")}`
          );
        }
        // ── Emoji Reactions (Issue #87 v2) ────────────────────────
        // Send reactions on the BOT REPLY (content-matched), not the user message.
        const reactionSessionKey = resolveSessionKey(event, _ctx);
        const reactionTurnState = getTurnState(reactionSessionKey);

        debugLog(`agent_end (autoCapture): fired, sessionKey=${reactionSessionKey}, recallOccurred=${reactionTurnState.recallOccurred}, capturedCount=${reactionTurnState.lastCapturedSummaries.length}`);

        // Resolve channel provider for reactions (e.g. "slack", "telegram")
        const channelProvider = extractChannelFromSessionKey(reactionSessionKey);
        const channelTarget = extractTargetFromSessionKey(reactionSessionKey);

        // Fallback channel from context
        let reactionChannel = channelProvider || reactionTurnState.lastChannelId;
        if (!reactionChannel && _ctx && typeof _ctx === "object") {
          const ctx = _ctx as Record<string, unknown>;
          if (typeof ctx.channelId === "string") reactionChannel = ctx.channelId;
          else if (typeof ctx.sessionKey === "string") reactionChannel = ctx.sessionKey;
        }

        if (reactionChannel) {
          // Try to find the bot reply message by content matching
          let targetMessageId = reactionTurnState.lastUserMessageId; // fallback

          // Extract last assistant message text for content matching
          const lastAssistantText = (() => {
            if (!event.messages || !Array.isArray(event.messages)) return undefined;
            for (let i = event.messages.length - 1; i >= 0; i--) {
              const msg = event.messages[i] as Record<string, unknown>;
              if (msg?.role === "assistant" && typeof msg.content === "string") {
                return msg.content;
              }
            }
            return undefined;
          })();

          if (lastAssistantText && reactionChannel) {
            const botReplyId = await findBotReplyByContent(reactionChannel, lastAssistantText, reactionSessionKey);
            if (botReplyId) {
              targetMessageId = botReplyId;
              debugLog(`agent_end: using bot reply ID ${botReplyId}`);
            } else {
              debugLog(`agent_end: no bot reply match, falling back to user msg ${targetMessageId}`);
            }
          }

          // 💾 Capture confirm reaction
          if (config.showCaptureConfirm && reactionTurnState.lastCapturedSummaries.length > 0) {
            sendReaction("floppy_disk", reactionChannel, targetMessageId, channelTarget).catch(() => {});
          }

          // 🧠 Recall reaction
          if (config.showMemorySources && reactionTurnState.recallOccurred) {
            sendReaction("brain", reactionChannel, targetMessageId, channelTarget).catch(() => {});
          }
        }

        // Reset turn state after reactions
        reactionTurnState.lastCapturedSummaries = [];
        reactionTurnState.lastInjectedEntries = [];
        reactionTurnState.recallOccurred = false;
        reactionTurnState.lastUserMessageId = undefined;
      } catch (error) {
        // Non-fatal: capture failure should never break the agent
        console.warn(`[palaia] Auto-capture failed: ${error}`);
      }
    });
  }

  // ── agent_end: Recall-only reactions (when autoCapture is off) ──
  // If autoCapture is enabled, reactions are handled inside the autoCapture agent_end hook above.
  // This hook handles the case where only recall occurred (no capture).
  if (!config.autoCapture && config.memoryInject) {
    api.on("agent_end", async (event: any, _ctx: any) => {
      try {
        const sessionKey = resolveSessionKey(event, _ctx);
        const turnState = getTurnState(sessionKey);

        debugLog(`agent_end (recall-only): fired, sessionKey=${sessionKey}, recallOccurred=${turnState.recallOccurred}`);

        const channelProvider = extractChannelFromSessionKey(sessionKey);
        const channelTarget = extractTargetFromSessionKey(sessionKey);

        let reactionChannel = channelProvider || turnState.lastChannelId;
        if (!reactionChannel && _ctx && typeof _ctx === "object") {
          const ctx = _ctx as Record<string, unknown>;
          if (typeof ctx.channelId === "string") reactionChannel = ctx.channelId;
          else if (typeof ctx.sessionKey === "string") reactionChannel = ctx.sessionKey;
        }

        if (reactionChannel && config.showMemorySources && turnState.recallOccurred) {
          let targetMessageId = turnState.lastUserMessageId;

          // Try content-match for bot reply
          const lastAssistantText = (() => {
            if (!event.messages || !Array.isArray(event.messages)) return undefined;
            for (let i = event.messages.length - 1; i >= 0; i--) {
              const msg = event.messages[i] as Record<string, unknown>;
              if (msg?.role === "assistant" && typeof msg.content === "string") {
                return msg.content;
              }
            }
            return undefined;
          })();

          if (lastAssistantText && reactionChannel) {
            const botReplyId = await findBotReplyByContent(reactionChannel, lastAssistantText, sessionKey);
            if (botReplyId) {
              targetMessageId = botReplyId;
              debugLog(`agent_end (recall-only): using bot reply ID ${botReplyId}`);
            }
          }

          sendReaction("brain", reactionChannel, targetMessageId, channelTarget).catch(() => {});
        }

        // Reset
        turnState.recallOccurred = false;
        turnState.lastUserMessageId = undefined;
        turnState.lastInjectedEntries = [];
      } catch {
        // Non-fatal
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
