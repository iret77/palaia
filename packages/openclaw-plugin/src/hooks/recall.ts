/**
 * Query-based recall logic for the before_prompt_build hook.
 *
 * Extracted from hooks.ts during Phase 1.5 decomposition.
 * No logic changes — pure structural refactoring.
 */

import type { RecallTypeWeights } from "../config.js";
import { strippalaiaInjectedContext } from "./capture.js";

// ============================================================================
// Types
// ============================================================================

/** Shape returned by `palaia query --json` or `palaia list --json` */
export interface QueryResult {
  results: Array<{
    id: string;
    body?: string;
    content?: string;
    score: number;
    bm25_score?: number;
    embed_score?: number;
    tier: string;
    scope: string;
    title?: string;
    type?: string;
    tags?: string[];
    created?: string;
  }>;
}

/** Message shape from OpenClaw event.messages */
export interface Message {
  role?: string;
  content?: string | Array<{ type?: string; text?: string }>;
}

// ============================================================================
// Footnote Helpers (Issue #87)
// ============================================================================

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
  return `\n\n\u{1f4ce} palaia: ${parts.join(", ")}`;
}

// Re-export formatShortDate from state for use here
import { formatShortDate } from "./state.js";

// ============================================================================
// Satisfaction / Transparency Nudge Helpers (Issue #87)
// ============================================================================

import type { PluginState } from "./state.js";

const SATISFACTION_THRESHOLD = 10;
const TRANSPARENCY_RECALL_THRESHOLD = 50;
const TRANSPARENCY_DAYS_THRESHOLD = 7;

const SATISFACTION_NUDGE_TEXT =
  "Your user has been using palaia for a while now. " +
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
// Message Text Extraction
// ============================================================================

export function extractMessageTexts(messages: unknown[]): Array<{ role: string; text: string; provenance?: string }> {
  const result: Array<{ role: string; text: string; provenance?: string }> = [];

  for (const msg of messages) {
    if (!msg || typeof msg !== "object") continue;
    const m = msg as Message;
    const role = m.role;
    if (!role || typeof role !== "string") continue;

    // Extract provenance kind (string or object with .kind)
    const rawProvenance = (m as any).provenance?.kind ?? (m as any).provenance;
    const provenance = typeof rawProvenance === "string" ? rawProvenance : undefined;

    if (typeof m.content === "string" && m.content.trim()) {
      result.push({ role, text: m.content.trim(), provenance });
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
          result.push({ role, text: block.text.trim(), provenance });
        }
      }
    }
  }

  return result;
}

export function getLastUserMessage(messages: unknown[]): string | null {
  const texts = extractMessageTexts(messages);
  // Prefer external_user provenance (real human input)
  for (let i = texts.length - 1; i >= 0; i--) {
    if (texts[i].role === "user" && texts[i].provenance === "external_user")
      return texts[i].text;
  }
  // Fallback: any user message (backward compat for OpenClaw without provenance)
  for (let i = texts.length - 1; i >= 0; i--) {
    if (texts[i].role === "user") return texts[i].text;
  }
  return null;
}

// ============================================================================
// Channel Envelope Stripping (v2.0.6)
// ============================================================================

/**
 * Strip OpenClaw channel envelope from message text.
 * Matches the pattern: [TIMESTAMP] or [CHANNEL TIMESTAMP] prefix
 * that OpenClaw adds to inbound messages from all channels.
 * Based on OpenClaw's internal stripEnvelope() logic.
 */
const ENVELOPE_PREFIX_RE = /^\[([^\]]+)\]\s*/;
const ENVELOPE_CHANNELS = [
  "WebChat", "WhatsApp", "Telegram", "Signal", "Slack",
  "Discord", "Google Chat", "iMessage", "Teams", "Matrix",
  "Zalo", "Zalo Personal", "BlueBubbles",
];

function looksLikeEnvelopeHeader(header: string): boolean {
  // ISO timestamp pattern
  if (/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z\b/.test(header)) return true;
  // Space-separated timestamp
  if (/\d{4}-\d{2}-\d{2} \d{2}:\d{2}\b/.test(header)) return true;
  // Channel prefix
  return ENVELOPE_CHANNELS.some(ch => header.startsWith(`${ch} `));
}

export function stripChannelEnvelope(text: string): string {
  const match = text.match(ENVELOPE_PREFIX_RE);
  if (!match) return text;
  if (!looksLikeEnvelopeHeader(match[1] ?? "")) return text;
  return text.slice(match[0].length);
}

/**
 * Strip "System: [timestamp] Channel message in #channel from User: " prefix.
 * OpenClaw wraps inbound messages with this pattern for all channel providers.
 */
const SYSTEM_PREFIX_RE = /^System:\s*\[\d{4}-\d{2}-\d{2}[^\]]*\]\s*(?:Slack message|Telegram message|Discord message|WhatsApp message|Signal message|message).*?(?:from \w+:\s*)?/i;

export function stripSystemPrefix(text: string): string {
  const match = text.match(SYSTEM_PREFIX_RE);
  if (match) return text.slice(match[0].length);
  return text;
}

// ============================================================================
// Recall Query Builder (v2.0.6: envelope-aware, provenance-based)
// ============================================================================

/**
 * Messages that are purely system content (no user text).
 * Used to skip edited notifications, sync events, inter-session messages, etc.
 */
function isSystemOnlyContent(text: string): boolean {
  if (!text) return true;
  if (text.startsWith("System:")) return true;
  if (text.startsWith("[Queued")) return true;
  if (text.startsWith("[Inter-session")) return true;
  if (/^Slack message (edited|deleted)/.test(text)) return true;
  if (/^\[auto\]/.test(text)) return true;
  if (text.length < 3) return true;
  return false;
}

/**
 * Build a recall query from message history.
 *
 * v2.0.6: Strips OpenClaw channel envelopes (System: [...] Slack message from ...:)
 * and inter-session prefixes before building the query. This prevents envelope
 * metadata from polluting semantic search and causing timeouts / false-high scores.
 *
 * - Filters out inter_session and internal_system provenance messages.
 * - Falls back to any user message for backward compat (OpenClaw without provenance).
 * - Strips channel envelopes and system prefixes from message text.
 * - Skips system-only content (edited notifications, sync events).
 * - Short messages (< 30 chars): prepends previous for context.
 * - Hard-caps at 500 characters.
 */
export function buildRecallQuery(messages: unknown[]): string {
  const texts = extractMessageTexts(messages).map(t =>
    t.role === "user"
      ? { ...t, text: strippalaiaInjectedContext(t.text) }
      : t
  );

  // Step 1: Filter out inter_session messages (sub-agent results, sessions_send)
  const candidates = texts.filter(
    t => t.role === "user" && t.provenance !== "inter_session" && t.provenance !== "internal_system"
  );

  // Fallback: if no messages without provenance, use all user messages
  const allUserMsgs = candidates.length > 0
    ? candidates
    : texts.filter(t => t.role === "user");

  if (allUserMsgs.length === 0) return "";

  // Early exit: only scan the last 3 user messages or 2000 chars, whichever comes first
  const MAX_SCAN_MSGS = 3;
  const MAX_SCAN_CHARS = 2000;
  let userMsgs: typeof allUserMsgs;
  if (allUserMsgs.length <= MAX_SCAN_MSGS) {
    userMsgs = allUserMsgs;
  } else {
    userMsgs = allUserMsgs.slice(-MAX_SCAN_MSGS);
    // Extend backwards if total chars < MAX_SCAN_CHARS and more messages available
    let totalChars = userMsgs.reduce((sum, m) => sum + m.text.length, 0);
    let startIdx = allUserMsgs.length - MAX_SCAN_MSGS;
    while (startIdx > 0 && totalChars < MAX_SCAN_CHARS) {
      startIdx--;
      totalChars += allUserMsgs[startIdx].text.length;
      userMsgs = allUserMsgs.slice(startIdx);
    }
  }

  // Step 2: Strip envelopes from the last user message(s)
  let lastText = stripSystemPrefix(stripChannelEnvelope(userMsgs[userMsgs.length - 1].text.trim()));

  // Skip system-only messages (edited notifications, sync events, etc.)
  // Walk backwards to find a message with actual content
  let idx = userMsgs.length - 1;
  while (idx >= 0 && (!lastText || isSystemOnlyContent(lastText))) {
    idx--;
    if (idx >= 0) {
      lastText = stripSystemPrefix(stripChannelEnvelope(userMsgs[idx].text.trim()));
    }
  }

  if (!lastText) return "";

  // Step 3: Short messages -> include previous for context
  if (lastText.length < 30 && idx > 0) {
    const prevText = stripSystemPrefix(stripChannelEnvelope(userMsgs[idx - 1].text.trim()));
    if (prevText && !isSystemOnlyContent(prevText)) {
      return `${prevText} ${lastText}`.slice(0, 500);
    }
  }

  return lastText.slice(0, 500);
}

// ============================================================================
// Query-based Recall: Type-weighted reranking (Issue #65)
// ============================================================================

export interface RankedEntry {
  id: string;
  body: string;
  title: string;
  scope: string;
  tier: string;
  type: string;
  score: number;
  bm25Score?: number;
  embedScore?: number;
  weightedScore: number;
  created?: string;
  tags?: string[];
}

/**
 * Calculate recency boost factor.
 * Returns a multiplier: 1.0 (no boost) to 1.0 + boostFactor (max boost for very recent).
 * Formula: 1 + boostFactor * exp(-hoursAgo / 24)
 */
function calcRecencyBoost(created: string | undefined, boostFactor: number): number {
  if (!boostFactor || !created) return 1.0;
  try {
    const hoursAgo = (Date.now() - new Date(created).getTime()) / (1000 * 60 * 60);
    if (hoursAgo < 0 || isNaN(hoursAgo)) return 1.0;
    return 1.0 + boostFactor * Math.exp(-hoursAgo / 24);
  } catch {
    return 1.0;
  }
}

export function rerankByTypeWeight(
  results: QueryResult["results"],
  weights: Record<string, number>,
  recencyBoost = 0,
  manualEntryBoost = 1.3,
): RankedEntry[] {
  return results
    .map((r) => {
      const type = r.type || "memory";
      const weight = weights[type] ?? 1.0;
      const recency = calcRecencyBoost(r.created, recencyBoost);
      // Human-created entries (webui/cli tags) get a boost over auto-captured and agent entries.
      // This ensures intentionally stored knowledge ranks higher than conversation noise.
      const tags = r.tags ?? [];
      const isHumanCreated = tags.includes("webui") || tags.includes("cli");
      const sourceBoost = isHumanCreated ? manualEntryBoost : 1.0;
      return {
        id: r.id,
        body: r.content || r.body || "",
        title: r.title || "(untitled)",
        scope: r.scope,
        tier: r.tier,
        type,
        score: r.score,
        bm25Score: r.bm25_score,
        embedScore: r.embed_score,
        weightedScore: r.score * weight * recency * sourceBoost,
        created: r.created,
        tags: r.tags,
      };
    })
    .sort((a, b) => b.weightedScore - a.weightedScore);
}

// ── Context Formatting ──────────────────────────────────────────────────

const SCOPE_SHORT: Record<string, string> = { team: "t", private: "p", public: "pub" };
const TYPE_SHORT: Record<string, string> = { memory: "m", process: "pr", task: "tk" };

/**
 * Format a ranked entry as an injectable context line.
 *
 * In compact mode (progressive disclosure), only title + first line + ID are shown.
 * The agent can use `memory_get <id>` for the full entry.
 */
export function formatEntryLine(entry: RankedEntry, compact: boolean): string {
  const scopeKey = SCOPE_SHORT[entry.scope] || entry.scope;
  const typeKey = TYPE_SHORT[entry.type] || entry.type;
  const prefix = `[${scopeKey}/${typeKey}]`;

  if (compact) {
    // Compact: title + first line of body + ID reference
    const firstLine = entry.body.split("\n")[0]?.slice(0, 120) || "";
    const titlePart = entry.body.toLowerCase().startsWith(entry.title.toLowerCase())
      ? firstLine
      : `${entry.title} — ${firstLine}`;
    return `${prefix} ${titlePart} [id:${entry.id}]\n`;
  }

  // Full: title + complete body
  if (entry.body.toLowerCase().startsWith(entry.title.toLowerCase())) {
    return `${prefix} ${entry.body}\n\n`;
  }
  return `${prefix} ${entry.title}\n${entry.body}\n\n`;
}

/**
 * Determine if compact mode should be used based on result count.
 * Above threshold, use compact mode to fit more entries in budget.
 */
export function shouldUseCompactMode(totalResults: number, threshold = 100): boolean {
  return totalResults > threshold;
}
