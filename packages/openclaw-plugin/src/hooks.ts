/**
 * Lifecycle hooks for the Palaia OpenClaw plugin.
 *
 * - before_prompt_build: Query-based contextual recall (Issue #65).
 *   Returns appendSystemContext with 🧠 instruction when memory is used.
 * - agent_end: Auto-capture of significant exchanges (Issue #64).
 *   Now with LLM-based extraction via OpenClaw's runEmbeddedPiAgent,
 *   falling back to rule-based extraction if the LLM is unavailable.
 * - message_received: Captures inbound message ID for emoji reactions.
 * - palaia-recovery service: Replays WAL on startup.
 * - /palaia command: Show memory status.
 */

import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { run, runJson, recover, type RunnerOpts } from "./runner.js";
import type { PalaiaPluginConfig, RecallTypeWeights } from "./config.js";

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

/**
 * Load plugin state from disk.
 *
 * Note: No file locking is applied here. The plugin-state.json file stores
 * non-critical counters (recall count, nudge flags). In the worst case of a
 * race condition between multiple agents, a nudge fires one recall too early
 * or too late. This is acceptable given the low-stakes nature of the data
 * and the complexity cost of adding advisory locks in Node.js.
 */
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
// Session-isolated Turn State (Issue #87: Emoji Reactions)
// ============================================================================

/** Per-session turn state for tracking recall/capture across hooks. */
interface TurnState {
  recallOccurred: boolean;
  lastInboundMessageId: string | null;
  lastInboundChannelId: string | null;
  channelProvider: string | null;
  capturedInThisTurn: boolean;
  /** Timestamp when this entry was created (for TTL-based pruning). */
  createdAt: number;
}

function createDefaultTurnState(): TurnState {
  return {
    recallOccurred: false,
    lastInboundMessageId: null,
    lastInboundChannelId: null,
    channelProvider: null,
    capturedInThisTurn: false,
    createdAt: Date.now(),
  };
}

/** Maximum age for turn state entries before they are pruned (5 minutes). */
const TURN_STATE_TTL_MS = 5 * 60 * 1000;
/** Maximum age for inbound message entries before they are pruned (5 minutes). */
const INBOUND_MESSAGE_TTL_MS = 5 * 60 * 1000;

/**
 * Remove stale entries from turnStateBySession and lastInboundMessageByChannel.
 * Called at the start of before_prompt_build to prevent memory leaks from
 * sessions that were killed/crashed without firing agent_end.
 */
export function pruneStaleEntries(): void {
  const now = Date.now();
  for (const [key, state] of turnStateBySession) {
    if (now - state.createdAt > TURN_STATE_TTL_MS) {
      turnStateBySession.delete(key);
    }
  }
  for (const [key, entry] of lastInboundMessageByChannel) {
    if (now - entry.timestamp > INBOUND_MESSAGE_TTL_MS) {
      lastInboundMessageByChannel.delete(key);
    }
  }
}

/**
 * Session-isolated turn state map. Keyed by sessionKey.
 * Set in before_prompt_build / message_received, consumed + deleted in agent_end.
 * NEVER use global variables for turn data — race condition with multi-agent.
 */
const turnStateBySession = new Map<string, TurnState>();

// ============================================================================
// Inbound Message ID Store (for emoji reactions)
// ============================================================================

/**
 * Stores the most recent inbound message ID per channel.
 * Keyed by channelId (e.g. "C0AKE2G15HV"), value is the message ts.
 * Written by message_received, consumed by agent_end.
 * Entries are short-lived and cleaned up after agent_end.
 */
const lastInboundMessageByChannel = new Map<string, { messageId: string; provider: string; timestamp: number }>();

/** Channels that support emoji reactions. */
const REACTION_SUPPORTED_PROVIDERS = new Set(["slack", "discord"]);

// ============================================================================
// Scope Validation (Issue #90)
// ============================================================================

const VALID_SCOPES = ["private", "team", "public"];

/**
 * Check if a scope string is valid for palaia write.
 * Valid: "private", "team", "public", or any "shared:*" prefix.
 */
export function isValidScope(s: string): boolean {
  return VALID_SCOPES.includes(s) || s.startsWith("shared:");
}

/**
 * Sanitize a scope value — returns the value if valid, otherwise fallback.
 */
export function sanitizeScope(rawScope: string | null | undefined, fallback = "team"): string {
  if (rawScope && isValidScope(rawScope)) return rawScope;
  return fallback;
}

// ============================================================================
// Session Key Helpers
// ============================================================================

/**
 * Extract channel target from a session key.
 * e.g. "agent:main:slack:channel:c0ake2g15hv" → "channel:C0AKE2G15HV"
 */
export function extractTargetFromSessionKey(sessionKey: string): string | undefined {
  const parts = sessionKey.split(":");
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
  if (parts.length >= 5 && parts[0] === "agent") {
    return parts[2];
  }
  return undefined;
}

// ============================================================================
// Emoji Reaction Helpers (Issue #87: Reactions)
// ============================================================================

/**
 * Extract the Slack channel ID from a session key.
 * e.g. "agent:main:slack:channel:c0ake2g15hv" → "C0AKE2G15HV"
 */
export function extractSlackChannelIdFromSessionKey(sessionKey: string): string | undefined {
  const parts = sessionKey.split(":");
  for (let i = 0; i < parts.length - 1; i++) {
    if (parts[i] === "channel" || parts[i] === "dm") {
      return parts[i + 1].toUpperCase();
    }
  }
  return undefined;
}

/**
 * Resolve the session key for the current turn from available ctx.
 * Tries ctx.sessionKey first, then falls back to sessionId.
 */
function resolveSessionKeyFromCtx(ctx: any): string | undefined {
  const sk = ctx?.sessionKey?.trim?.();
  if (sk) return sk;
  const sid = ctx?.sessionId?.trim?.();
  return sid || undefined;
}

/**
 * Get or create turn state for a session.
 */
export function getOrCreateTurnState(sessionKey: string): TurnState {
  let state = turnStateBySession.get(sessionKey);
  if (!state) {
    state = createDefaultTurnState();
    turnStateBySession.set(sessionKey, state);
  }
  return state;
}

/**
 * Delete turn state for a session (cleanup after agent_end).
 */
export function deleteTurnState(sessionKey: string): void {
  turnStateBySession.delete(sessionKey);
}

/**
 * Send an emoji reaction to a message via the Slack Web API (or Discord API).
 * Only fires for supported channels (slack, discord). Silently no-ops for others.
 *
 * For Slack, calls reactions.add via the @slack/web-api client.
 * Requires SLACK_BOT_TOKEN in the environment.
 */
export async function sendReaction(
  channelId: string,
  messageId: string,
  emoji: string,
  provider: string,
): Promise<void> {
  if (!channelId || !messageId || !emoji) return;
  if (!REACTION_SUPPORTED_PROVIDERS.has(provider)) return;

  if (provider === "slack") {
    await sendSlackReaction(channelId, messageId, emoji);
  }
  // Discord: future implementation
}

/** Cached Slack bot token resolved from env or OpenClaw config. */
let _cachedSlackToken: string | null | undefined;

/**
 * Resolve the Slack bot token from environment or OpenClaw config file.
 * Caches the result for the lifetime of the process.
 *
 * Resolution order:
 * 1. SLACK_BOT_TOKEN env var (explicit override)
 * 2. OpenClaw config: channels.slack.botToken (standard single-account)
 * 3. OpenClaw config: channels.slack.accounts.default.botToken (multi-account)
 *
 * Config path: OPENCLAW_CONFIG env var → ~/.openclaw/openclaw.json
 */
async function resolveSlackBotToken(): Promise<string | null> {
  if (_cachedSlackToken !== undefined) return _cachedSlackToken;

  // 1) Environment variable
  const envToken = process.env.SLACK_BOT_TOKEN?.trim();
  if (envToken) {
    _cachedSlackToken = envToken;
    return envToken;
  }

  // 2) OpenClaw config file — OPENCLAW_CONFIG takes precedence over default path
  const configPaths = [
    process.env.OPENCLAW_CONFIG || "",
    path.join(os.homedir(), ".openclaw", "openclaw.json"),
  ].filter(Boolean);

  for (const configPath of configPaths) {
    try {
      const raw = await fs.readFile(configPath, "utf-8");
      const config = JSON.parse(raw);

      // 2a) Standard path: channels.slack.botToken
      const directToken = config?.channels?.slack?.botToken?.trim();
      if (directToken) {
        _cachedSlackToken = directToken;
        return directToken;
      }

      // 2b) Multi-account path: channels.slack.accounts.default.botToken
      const accountToken = config?.channels?.slack?.accounts?.default?.botToken?.trim();
      if (accountToken) {
        _cachedSlackToken = accountToken;
        return accountToken;
      }
    } catch {
      // Try next path
    }
  }

  _cachedSlackToken = null;
  return null;
}

/** Reset cached token (for testing). */
export function resetSlackTokenCache(): void {
  _cachedSlackToken = undefined;
}

async function sendSlackReaction(
  channelId: string,
  messageId: string,
  emoji: string,
): Promise<void> {
  const token = await resolveSlackBotToken();
  if (!token) {
    console.warn("[palaia] Cannot send Slack reaction: no bot token found");
    return;
  }

  const normalizedEmoji = emoji.replace(/^:/, "").replace(/:$/, "");

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);

  try {
    const response = await fetch("https://slack.com/api/reactions.add", {
      method: "POST",
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        channel: channelId,
        timestamp: messageId,
        name: normalizedEmoji,
      }),
      signal: controller.signal,
    });
    const data = await response.json() as { ok: boolean; error?: string };
    if (!data.ok && data.error !== "already_reacted") {
      console.warn(`[palaia] Slack reaction failed: ${data.error} (${normalizedEmoji} on ${channelId})`);
    }
  } catch (err) {
    if ((err as Error).name !== "AbortError") {
      console.warn(`[palaia] Slack reaction error (${normalizedEmoji}): ${err}`);
    }
  } finally {
    clearTimeout(timeout);
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
  "Your user has been using Palaia for a while now. " +
  "Ask them casually if they're happy with the memory system. " +
  "If there are issues, suggest `palaia doctor`.";

const TRANSPARENCY_NUDGE_TEXT =
  "Your user has been seeing memory Footnotes and capture confirmations for several days. " +
  "Ask them once: 'Would you like to keep seeing memory source references and capture " +
  "confirmations, or should I hide them? You can change this anytime.' " +
  "Based on their answer: `palaia config set showMemorySources true/false` and " +
  "`palaia config set showCaptureConfirm true/false`";

/**
 * Check which nudges (if any) should fire based on plugin state.
 * Returns nudge texts to prepend, and updates state accordingly.
 */
export function checkNudges(state: PluginState): { nudges: string[]; updated: boolean } {
  const nudges: string[] = [];
  let updated = false;

  if (!state.satisfactionNudged && state.successfulRecalls >= SATISFACTION_THRESHOLD) {
    nudges.push(SATISFACTION_NUDGE_TEXT);
    state.satisfactionNudged = true;
    updated = true;
  }

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
const PROJECT_CACHE_TTL_MS = 60_000;

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
    const thisFile = typeof __dirname !== "undefined" ? __dirname : path.dirname(new URL(import.meta.url).pathname);
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

function buildExtractionPrompt(projects: CachedProject[]): string {
  if (projects.length === 0) return EXTRACTION_SYSTEM_PROMPT_BASE;
  const projectList = projects
    .map((p) => `${p.name}${p.description ? ` (${p.description})` : ""}`)
    .join(", ");
  return `${EXTRACTION_SYSTEM_PROMPT_BASE}\n\nKnown projects: ${projectList}`;
}

const CHEAP_MODELS: Record<string, string> = {
  anthropic: "claude-haiku-4",
  openai: "gpt-4.1-mini",
  google: "gemini-2.0-flash",
};

export function resolveCaptureModel(
  config: any,
  captureModel?: string,
): { provider: string; model: string } | undefined {
  if (captureModel && captureModel !== "cheap") {
    const parts = captureModel.split("/");
    if (parts.length >= 2) {
      return { provider: parts[0], model: parts.slice(1).join("/") };
    }
    const defaultsModel = config?.agents?.defaults?.model;
    const primary = typeof defaultsModel === "string"
      ? defaultsModel.trim()
      : (defaultsModel?.primary?.trim() ?? "");
    const defaultProvider = primary.split("/")[0];
    if (defaultProvider) {
      return { provider: defaultProvider, model: captureModel };
    }
  }

  const defaultsModel = config?.agents?.defaults?.model;
  const primary = typeof defaultsModel === "string"
    ? defaultsModel.trim()
    : (defaultsModel?.primary?.trim() ?? "");
  const defaultProvider = primary.split("/")[0];
  const defaultModel = primary.split("/").slice(1).join("/");

  if (defaultProvider && CHEAP_MODELS[defaultProvider]) {
    return { provider: defaultProvider, model: CHEAP_MODELS[defaultProvider] };
  }

  if (defaultProvider && defaultModel) {
    return { provider: defaultProvider, model: defaultModel };
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
  "thx", "k", "👍", "👎", "ack", "nope", "yep", "yup", "alright",
  "fine", "gut", "passt", "okay", "hmm", "hm", "ah", "aha",
]);

const SIGNIFICANCE_RULES: Array<{
  pattern: RegExp;
  tag: string;
  type: "memory" | "process" | "task";
}> = [
  { pattern: /(?:we decided|entschieden|decision:|beschlossen|let'?s go with|wir nehmen|agreed on)/i, tag: "decision", type: "memory" },
  { pattern: /(?:will use|werden nutzen|going forward|ab jetzt|from now on)/i, tag: "decision", type: "memory" },
  { pattern: /(?:learned|gelernt|lesson:|erkenntnis|takeaway|insight|turns out|it seems)/i, tag: "lesson", type: "memory" },
  { pattern: /(?:mistake was|fehler war|should have|hätten sollen|next time)/i, tag: "lesson", type: "memory" },
  { pattern: /(?:surprising|überraschend|unexpected|unerwartet|didn'?t expect|nicht erwartet|plot twist)/i, tag: "surprise", type: "memory" },
  { pattern: /(?:i will|ich werde|todo:|action item|must do|muss noch|need to|commit to|verspreche)/i, tag: "commitment", type: "task" },
  { pattern: /(?:deadline|frist|due date|bis zum|by end of|spätestens)/i, tag: "commitment", type: "task" },
  { pattern: /(?:the process is|der prozess|steps?:|workflow:|how to|anleitung|recipe:|checklist)/i, tag: "process", type: "process" },
  { pattern: /(?:first,?\s.*then|schritt \d|step \d|1\.\s.*2\.\s)/i, tag: "process", type: "process" },
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

function buildRunnerOpts(config: PalaiaPluginConfig): RunnerOpts {
  return {
    binaryPath: config.binaryPath,
    workspace: config.workspace,
    timeoutMs: config.timeoutMs,
  };
}

// ============================================================================
// /palaia status command — Format helpers
// ============================================================================

function formatStatusResponse(
  state: PluginState,
  stats: Record<string, unknown>,
  config: PalaiaPluginConfig,
): string {
  const lines: string[] = ["Palaia Memory Status", ""];

  // Recall count
  const sinceDate = state.firstRecallTimestamp
    ? formatShortDate(state.firstRecallTimestamp)
    : "n/a";
  lines.push(`Recalls: ${state.successfulRecalls} successful (since ${sinceDate})`);

  // Store stats from palaia status --json
  const totalEntries = stats.total_entries ?? stats.totalEntries ?? "?";
  const hotEntries = stats.hot ?? stats.hotEntries ?? "?";
  const warmEntries = stats.warm ?? stats.warmEntries ?? "?";
  lines.push(`Store: ${totalEntries} entries (${hotEntries} hot, ${warmEntries} warm)`);

  // Recall indicator
  lines.push(`Recall indicator: ${config.showMemorySources ? "ON" : "OFF"}`);

  // Config summary
  lines.push(`Config: autoCapture=${config.autoCapture}, captureScope=${config.captureScope || "team"}`);

  return lines.join("\n");
}

// ============================================================================
// Legacy exports kept for tests
// ============================================================================

/** Reset all turn state, inbound message store, and cached tokens (for testing and cleanup). */
export function resetTurnState(): void {
  turnStateBySession.clear();
  lastInboundMessageByChannel.clear();
  resetSlackTokenCache();
}

// ============================================================================
// Hook registration
// ============================================================================

/**
 * Register lifecycle hooks on the plugin API.
 */
export function registerHooks(api: any, config: PalaiaPluginConfig): void {
  const opts = buildRunnerOpts(config);

  // ── Startup checks (H-2, H-3) ─────────────────────────────────
  (async () => {
    // H-2: Warn if no agent is configured
    if (!process.env.PALAIA_AGENT) {
      try {
        const statusOut = await run(["config", "get", "agent"], { ...opts, timeoutMs: 3000 });
        if (!statusOut.trim()) {
          console.warn(
            "[palaia] No agent configured. Set PALAIA_AGENT env var or run 'palaia init --agent <name>'. " +
            "Auto-captured entries will have no agent attribution."
          );
        }
      } catch {
        console.warn(
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
          console.warn(
            "[palaia] No embedding provider configured. Semantic search is inactive (BM25 keyword-only). " +
            "Run 'pip install palaia[fastembed]' and 'palaia doctor --fix' for better recall quality."
          );
        }
      }
      // If statusJson is empty/null, skip warning (CLI may not be available)
    } catch {
      // Non-fatal — status check failed, skip warning (avoid false positive)
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
      const channelId = ctx?.channelId;

      if (messageId && channelId && provider && REACTION_SUPPORTED_PROVIDERS.has(provider)) {
        lastInboundMessageByChannel.set(channelId, {
          messageId: String(messageId),
          provider,
          timestamp: Date.now(),
        });
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

      try {
        const maxChars = config.maxInjectedChars || 4000;
        const limit = Math.min(config.maxResults || 10, 20);
        let entries: QueryResult["results"] = [];

        if (config.recallMode === "query") {
          const userMessage = event.prompt
            || (event.messages ? getLastUserMessage(event.messages) : null);

          if (userMessage && userMessage.length >= 5) {
            try {
              const queryArgs: string[] = ["query", userMessage, "--limit", String(limit)];
              if (config.tier === "all") {
                queryArgs.push("--all");
              }
              const result = await runJson<QueryResult>(queryArgs, opts);
              if (result && Array.isArray(result.results)) {
                entries = result.results;
              }
            } catch (queryError) {
              console.warn(`[palaia] Query recall failed, falling back to list: ${queryError}`);
            }
          }
        }

        // Fallback: list mode
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

        // Update recall counter for satisfaction/transparency nudges (Issue #87)
        let nudgeContext = "";
        try {
          const pluginState = await loadPluginState(config.workspace);
          pluginState.successfulRecalls++;
          if (!pluginState.firstRecallTimestamp) {
            pluginState.firstRecallTimestamp = new Date().toISOString();
          }
          const { nudges } = checkNudges(pluginState);
          if (nudges.length > 0) {
            nudgeContext = "\n\n## Agent Nudge (Palaia)\n\n" + nudges.join("\n\n");
          }
          await savePluginState(pluginState, config.workspace);
        } catch {
          // Non-fatal
        }

        // Track recall in session-isolated turn state for emoji reactions
        const sessionKey = resolveSessionKeyFromCtx(ctx);
        if (sessionKey) {
          const turnState = getOrCreateTurnState(sessionKey);
          turnState.recallOccurred = true;

          // Populate channel info from sessionKey for reaction routing
          const provider = extractChannelFromSessionKey(sessionKey);
          if (provider) turnState.channelProvider = provider;
          const slackChannel = extractSlackChannelIdFromSessionKey(sessionKey);
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
            ? "You used Palaia memory in this turn. Add 🧠 at the very end of your response (after everything else, on its own line)."
            : undefined,
        };
      } catch (error) {
        console.warn(`[palaia] Memory injection failed: ${error}`);
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
      if (!event.success || !event.messages || event.messages.length === 0) {
        return;
      }

      // Resolve session key for turn state
      const sessionKey = resolveSessionKeyFromCtx(ctx);

      try {
        const agentName = process.env.PALAIA_AGENT || undefined;

        const allTexts = extractMessageTexts(event.messages);

        const userTurns = allTexts.filter((t) => t.role === "user").length;
        if (userTurns < config.captureMinTurns) return;

        // Parse capture hints from all messages (Issue #81)
        const collectedHints: PalaiaHint[] = [];
        for (const t of allTexts) {
          const { hints } = parsePalaiaHints(t.text);
          collectedHints.push(...hints);
        }

        // Build exchange text
        const exchangeParts: string[] = [];
        for (const t of allTexts) {
          if (t.role === "user" || t.role === "assistant") {
            const { cleanedText } = parsePalaiaHints(t.text);
            exchangeParts.push(`[${t.role}]: ${cleanedText}`);
          }
        }
        const exchangeText = exchangeParts.join("\n");

        if (!shouldAttemptCapture(exchangeText)) return;

        const knownProjects = await loadProjects(opts);

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

          const scope = sanitizeScope(config.captureScope || itemScope, config.captureScope || "team");
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

        // LLM-based extraction (primary)
        let llmHandled = false;
        try {
          const results = await extractWithLLM(event.messages, api.config, {
            captureModel: config.captureModel,
          }, knownProjects);

          for (const r of results) {
            if (r.significance >= config.captureMinSignificance) {
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
              await run(args, { ...opts, timeoutMs: 10_000 });
              console.log(
                `[palaia] LLM auto-captured: type=${r.type}, significance=${r.significance}, tags=${r.tags.join(",")}, project=${effectiveProject || "none"}, scope=${effectiveScope || "team"}`
              );
            }
          }

          llmHandled = true;
        } catch (llmError) {
          if (!_llmImportFailureLogged) {
            console.warn(`[palaia] LLM extraction failed, using rule-based fallback: ${llmError}`);
            _llmImportFailureLogged = true;
          }
        }

        // Rule-based fallback
        if (!llmHandled) {
          let captureData: { tags: string[]; type: string; summary: string } | null = null;

          if (config.captureFrequency === "significant") {
            const significance = extractSignificance(exchangeText);
            if (!significance) return;
            captureData = significance;
          } else {
            const summary = exchangeParts
              .slice(-4)
              .map((p) => p.slice(0, 200))
              .join(" | ")
              .slice(0, 500);
            captureData = { tags: ["auto-capture"], type: "memory", summary };
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

          await run(args, { ...opts, timeoutMs: 10_000 });
          console.log(
            `[palaia] Rule-based auto-captured: type=${captureData.type}, tags=${captureData.tags.join(",")}`
          );
        }

        // Mark that capture occurred in this turn
        if (sessionKey) {
          const turnState = getOrCreateTurnState(sessionKey);
          turnState.capturedInThisTurn = true;
        }
      } catch (error) {
        console.warn(`[palaia] Auto-capture failed: ${error}`);
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
              || extractSlackChannelIdFromSessionKey(sessionKey);
            const messageId = turnState.lastInboundMessageId;

            if (provider && REACTION_SUPPORTED_PROVIDERS.has(provider) && channelId && messageId) {
              // Capture confirmation: 💾
              if (turnState.capturedInThisTurn && config.showCaptureConfirm) {
                await sendReaction(channelId, messageId, "floppy_disk", provider);
              }

              // Recall indicator: 🧠
              if (turnState.recallOccurred && config.showMemorySources) {
                await sendReaction(channelId, messageId, "brain", provider);
              }
            }
          }
        } catch (reactionError) {
          console.warn(`[palaia] Reaction sending failed: ${reactionError}`);
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
            || extractSlackChannelIdFromSessionKey(sessionKey);
          const messageId = turnState.lastInboundMessageId;

          if (provider && REACTION_SUPPORTED_PROVIDERS.has(provider) && channelId && messageId) {
            await sendReaction(channelId, messageId, "brain", provider);
          }
        }
      } catch (err) {
        console.warn(`[palaia] Recall reaction failed: ${err}`);
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
        console.log(`[palaia] WAL recovery: replayed ${result.replayed} entries`);
      }
      if (result.errors > 0) {
        console.warn(`[palaia] WAL recovery completed with ${result.errors} error(s)`);
      }
    },
  });
}
