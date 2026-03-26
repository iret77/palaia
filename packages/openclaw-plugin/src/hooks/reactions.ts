/**
 * Emoji reaction sending, Slack token resolution, and nudge tracking.
 *
 * Extracted from hooks.ts during Phase 1.5 decomposition.
 * No logic changes — pure structural refactoring.
 */

import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { REACTION_SUPPORTED_PROVIDERS } from "./state.js";

// ============================================================================
// Logger (Issue: api.logger integration)
// ============================================================================

/** Module-level logger — defaults to console, replaced via setLogger(). */
let logger: { info: (...args: any[]) => void; warn: (...args: any[]) => void } = {
  info: (...args: any[]) => console.log(...args),
  warn: (...args: any[]) => console.warn(...args),
};

/** Set the module-level logger (called from hooks/index.ts). */
export function setLogger(l: { info: (...args: any[]) => void; warn: (...args: any[]) => void }): void {
  logger = l;
}

// ============================================================================
// Emoji Reaction Helpers (Issue #87: Reactions)
// ============================================================================

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
/** Timestamp when the token was cached (for TTL expiry). */
let _slackTokenCachedAt = 0;
/** TTL for cached Slack bot token in milliseconds (5 minutes). */
const SLACK_TOKEN_CACHE_TTL_MS = 5 * 60 * 1000;

/**
 * Resolve the Slack bot token from environment or OpenClaw config file.
 * Caches the result with a 5-minute TTL — re-resolves after expiry.
 *
 * Resolution order:
 * 1. SLACK_BOT_TOKEN env var (explicit override)
 * 2. OpenClaw config: channels.slack.botToken (standard single-account)
 * 3. OpenClaw config: channels.slack.accounts.default.botToken (multi-account)
 *
 * Config path: OPENCLAW_CONFIG env var -> ~/.openclaw/openclaw.json
 */
async function resolveSlackBotToken(): Promise<string | null> {
  if (_cachedSlackToken !== undefined && (Date.now() - _slackTokenCachedAt) < SLACK_TOKEN_CACHE_TTL_MS) {
    return _cachedSlackToken;
  }

  // 1) Environment variable
  const envToken = process.env.SLACK_BOT_TOKEN?.trim();
  if (envToken) {
    _cachedSlackToken = envToken;
    _slackTokenCachedAt = Date.now();
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
        _slackTokenCachedAt = Date.now();
        return directToken;
      }

      // 2b) Multi-account path: channels.slack.accounts.default.botToken
      const accountToken = config?.channels?.slack?.accounts?.default?.botToken?.trim();
      if (accountToken) {
        _cachedSlackToken = accountToken;
        _slackTokenCachedAt = Date.now();
        return accountToken;
      }
    } catch {
      // Try next path
    }
  }

  _cachedSlackToken = null;
  _slackTokenCachedAt = Date.now();
  return null;
}

/** Reset cached token (for testing). */
export function resetSlackTokenCache(): void {
  _cachedSlackToken = undefined;
  _slackTokenCachedAt = 0;
}

async function sendSlackReaction(
  channelId: string,
  messageId: string,
  emoji: string,
): Promise<void> {
  const token = await resolveSlackBotToken();
  if (!token) {
    logger.warn("[palaia] Cannot send Slack reaction: no bot token found");
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
      logger.warn(`[palaia] Slack reaction failed: ${data.error} (${normalizedEmoji} on ${channelId})`);
    }
  } catch (err) {
    if ((err as Error).name !== "AbortError") {
      logger.warn(`[palaia] Slack reaction error (${normalizedEmoji}): ${err}`);
    }
  } finally {
    clearTimeout(timeout);
  }
}
