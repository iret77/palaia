/**
 * Session-isolated turn state, plugin state persistence, and session key helpers.
 *
 * Extracted from hooks.ts during Phase 1.5 decomposition.
 * No logic changes — pure structural refactoring.
 */

import fs from "node:fs/promises";
import path from "node:path";
import type { PalaiaPluginConfig } from "../config.js";

// ============================================================================
// Plugin State Persistence (Issue #87: Recall counter for nudges)
// ============================================================================

export interface PluginState {
  successfulRecalls: number;
  satisfactionNudged: boolean;
  transparencyNudged: boolean;
  firstRecallTimestamp: string | null;
}

export const DEFAULT_PLUGIN_STATE: PluginState = {
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
export async function loadPluginState(workspace?: string): Promise<PluginState> {
  const dir = workspace || process.cwd();
  const statePath = path.join(dir, ".palaia", "plugin-state.json");
  try {
    const raw = await fs.readFile(statePath, "utf-8");
    return { ...DEFAULT_PLUGIN_STATE, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULT_PLUGIN_STATE };
  }
}

export async function savePluginState(state: PluginState, workspace?: string): Promise<void> {
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
export interface TurnState {
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
 * Session-isolated turn state map. Keyed by sessionKey.
 * Set in before_prompt_build / message_received, consumed + deleted in agent_end.
 * NEVER use global variables for turn data — race condition with multi-agent.
 */
export const turnStateBySession = new Map<string, TurnState>();

// ============================================================================
// Inbound Message ID Store (for emoji reactions)
// ============================================================================

/**
 * Stores the most recent inbound message ID per channel.
 * Keyed by channelId (e.g. "C0AKE2G15HV"), value is the message ts.
 * Written by message_received, consumed by agent_end.
 * Entries are short-lived and cleaned up after agent_end.
 */
export const lastInboundMessageByChannel = new Map<string, { messageId: string; provider: string; timestamp: number }>();

/** Channels that support emoji reactions. */
export const REACTION_SUPPORTED_PROVIDERS = new Set(["slack", "discord"]);

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
  // Also prune stale session state (orphaned sessions)
  pruneStaleSessionState();
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

/** Reset all turn state, inbound message store (for testing and cleanup). */
export function resetTurnState(): void {
  turnStateBySession.clear();
  lastInboundMessageByChannel.clear();
}

// ============================================================================
// Session Continuity State (v3.0)
// ============================================================================

/** Accumulated tool observation from after_tool_call hooks. */
export interface ToolObservation {
  toolName: string;
  paramsSummary: string;
  resultSummary: string;
  durationMs: number;
  timestamp: number;
}

/** Pending session briefing, cached between session_start and first before_prompt_build. */
export interface PendingBriefing {
  summary: string | null;
  openTasks: string[];
  timestamp: number;
}

/** Session-level state that persists across turns within a session. */
export interface SessionState {
  /** Auto-generated session ID for instance tracking. */
  autoSessionId: string;
  /** Last known LLM model (for switch detection). */
  lastModel: string | null;
  /** True when model switch detected, cleared after briefing re-injection. */
  modelSwitchDetected: boolean;
  /** Pending briefing to inject on next before_prompt_build. */
  pendingBriefing: PendingBriefing | null;
  /** Accumulated tool observations for the session (used in session summary). */
  toolObservations: ToolObservation[];
  /** Timestamp of session start. */
  startedAt: number;
  /** Whether the first turn briefing has been delivered. */
  briefingDelivered: boolean;
  /** Whether a session summary has already been saved (prevents double-save). */
  summarySaved: boolean;
  /** Promise that resolves when session_start briefing load is complete. */
  briefingReady: Promise<void> | null;
  /** Resolver for briefingReady promise. */
  briefingReadyResolve: (() => void) | null;
}

/** Session state map. Keyed by sessionKey. */
export const sessionStateByKey = new Map<string, SessionState>();

/** Maximum age for session state entries before pruning (1 hour). */
const SESSION_STATE_TTL_MS = 60 * 60 * 1000;

/**
 * Remove stale entries from sessionStateByKey.
 * Called alongside pruneStaleEntries() to prevent memory leaks from
 * sessions that ended without firing session_end (crash/kill).
 */
export function pruneStaleSessionState(): void {
  const now = Date.now();
  for (const [key, state] of sessionStateByKey) {
    if (now - state.startedAt > SESSION_STATE_TTL_MS) {
      sessionStateByKey.delete(key);
    }
  }
}

/** Generate an auto session ID. */
export function generateAutoSessionId(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const date = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
  const time = `${pad(now.getHours())}${pad(now.getMinutes())}`;
  const hex = Math.floor(Math.random() * 0xffff).toString(16).padStart(4, "0");
  return `auto-${date}-${time}-${hex}`;
}

/** Get or create session state for a session key. */
export function getOrCreateSessionState(sessionKey: string): SessionState {
  let state = sessionStateByKey.get(sessionKey);
  if (!state) {
    state = {
      autoSessionId: generateAutoSessionId(),
      lastModel: null,
      modelSwitchDetected: false,
      pendingBriefing: null,
      toolObservations: [],
      startedAt: Date.now(),
      briefingDelivered: false,
      summarySaved: false,
      briefingReady: null,
      briefingReadyResolve: null,
    };
    sessionStateByKey.set(sessionKey, state);
  }
  return state;
}

/** Delete session state (cleanup). */
export function deleteSessionState(sessionKey: string): void {
  sessionStateByKey.delete(sessionKey);
}

// ============================================================================
// Session Key Helpers
// ============================================================================

/**
 * Extract channel target from a session key.
 * e.g. "agent:main:slack:channel:c0ake2g15hv" -> "channel:C0AKE2G15HV"
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
 * e.g. "agent:main:slack:channel:c0ake2g15hv" -> "slack"
 */
export function extractChannelFromSessionKey(sessionKey: string): string | undefined {
  const parts = sessionKey.split(":");
  if (parts.length >= 5 && parts[0] === "agent") {
    return parts[2];
  }
  return undefined;
}

/**
 * Extract the Slack channel ID from a session key.
 * e.g. "agent:main:slack:channel:c0ake2g15hv" -> "C0AKE2G15HV"
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
 * Extract the real Slack channel ID from event metadata or ctx.
 * OpenClaw stores the channel in "channel:C0AKE2G15HV" format in:
 *   - event.metadata.to
 *   - event.metadata.originatingTo
 *   - ctx.conversationId
 *
 * ctx.channelId is the PROVIDER NAME ("slack"), not the channel ID.
 * ctx.sessionKey is null during message_received.
 */
export function extractChannelIdFromEvent(event: any, ctx: any): string | undefined {
  const rawTo = event?.metadata?.to
    ?? event?.metadata?.originatingTo
    ?? ctx?.conversationId
    ?? "";
  const match = String(rawTo).match(/^(?:channel|dm|group):([A-Z0-9]+)$/i);
  return match ? match[1].toUpperCase() : undefined;
}

/**
 * Resolve the session key for the current turn from available ctx.
 * Tries ctx.sessionKey first, then falls back to sessionId.
 */
export function resolveSessionKeyFromCtx(ctx: any): string | undefined {
  const sk = ctx?.sessionKey?.trim?.();
  if (sk) return sk;
  const sid = ctx?.sessionId?.trim?.();
  return sid || undefined;
}

// ============================================================================
// Scope Validation (Issue #90)
// ============================================================================

const VALID_SCOPES = ["private", "team", "public"];

/**
 * Check if a scope string is valid for palaia write.
 * Valid: "private", "team", "public".
 * Legacy shared:X is accepted but normalized to "team" by the CLI.
 */
export function isValidScope(s: string): boolean {
  return VALID_SCOPES.includes(s);
}

/**
 * Sanitize a scope value -- returns the value if valid, otherwise fallback.
 * Enforces: LLM may suggest private or team, but NEVER public (unless explicitly configured).
 */
export function sanitizeScope(rawScope: string | null | undefined, fallback = "team", allowPublic = false): string {
  if (!rawScope || !isValidScope(rawScope)) return fallback;
  // Block public scope unless explicitly allowed (config-level override)
  if (rawScope === "public" && !allowPublic) return fallback;
  return rawScope;
}

// ============================================================================
// Hook helpers
// ============================================================================

/**
 * Resolve per-agent workspace and agentId from hook context.
 * Fallback chain: ctx.workspaceDir -> config.workspace -> cwd
 * Agent chain: ctx.agentId -> PALAIA_AGENT env var -> undefined
 */
export function resolvePerAgentContext(ctx: any, config: PalaiaPluginConfig) {
  return {
    workspace: ctx?.workspaceDir || config.workspace,
    agentId: ctx?.agentId || process.env.PALAIA_AGENT || undefined,
  };
}

// ============================================================================
// /palaia status command -- Format helpers
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

export function formatStatusResponse(
  state: PluginState,
  stats: Record<string, unknown>,
  config: PalaiaPluginConfig,
): string {
  const lines: string[] = ["palaia Memory Status", ""];

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
