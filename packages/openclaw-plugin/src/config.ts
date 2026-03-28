/**
 * Plugin configuration schema and defaults for @byte5ai/palaia.
 */

export interface RecallTypeWeights {
  process: number;
  task: number;
  memory: number;
  [key: string]: number;
}

export interface PalaiaPluginConfig {
  /** Path to palaia binary (default: auto-detect) */
  binaryPath?: string;
  /** Palaia workspace path (default: agent workspace) */
  workspace?: string;
  /** Default tier filter: "hot" | "warm" | "all" */
  tier: string;
  /** Default max results for queries */
  maxResults: number;
  /** Timeout for CLI calls in milliseconds */
  timeoutMs: number;
  /** Inject HOT memory into agent context on prompt build */
  memoryInject: boolean;
  /** Max characters for injected memory context */
  maxInjectedChars: number;

  // ── Auto-Capture (Issue #64) ─────────────────────────────────
  /** Enable automatic memory capture after agent exchanges */
  autoCapture: boolean;
  /** How often to capture: "every" | "significant" (default: "significant") */
  captureFrequency: "every" | "significant";
  /** Minimum exchange turns before capture is attempted */
  captureMinTurns: number;
  /** Model override for LLM-based extraction (e.g. "anthropic/claude-haiku-3", or "cheap") */
  captureModel?: string;
  /** Minimum significance score for LLM-extracted items (0.0-1.0, default: 0.3) */
  captureMinSignificance: number;

  // ── Metadata Overrides (Issue #81) ─────────────────────────
  /** Static scope override for auto-capture (default: undefined → LLM detection) */
  captureScope?: string;
  /** Static project override for auto-capture (default: undefined → LLM detection) */
  captureProject?: string;

  // ── Transparency Features (Issue #87) ────────────────────────
  /** Show memory source footnotes in agent responses (default: true) */
  showMemorySources: boolean;
  /** Show capture confirmation in agent responses (default: true) */
  showCaptureConfirm: boolean;

  // ── Query-based Recall (Issue #65) ───────────────────────────
  /** Recall mode: "list" (context-independent) or "query" (context-relevant) */
  recallMode: "list" | "query";
  /** Type-aware weighting for recall results */
  recallTypeWeight: RecallTypeWeights;

  // ── Recall Quality (Issue #65) ───────────────────────────────
  /** Minimum score for a recall result to be considered relevant (default: 0.7) */
  recallMinScore: number;

  // ── Embedding Server (v2.0.8) ──────────────────────────────
  /** Enable long-lived embedding server subprocess for fast queries (default: true) */
  embeddingServer: boolean;

  // ── Session Continuity (v3.0) ─────────────────────────────
  /** Enable automatic session summaries on session end/reset (default: true) */
  sessionSummary: boolean;
  /** Enable session briefing injection on session start (default: true) */
  sessionBriefing: boolean;
  /** Max characters for session briefing (default: 1500) */
  sessionBriefingMaxChars: number;
  /** Enable tool observation tracking via after_tool_call hook (default: true) */
  captureToolObservations: boolean;
  /** Recency boost factor for recall (0 = off, 0.3 = 30% boost for <24h entries) */
  recallRecencyBoost: number;
}

export const DEFAULT_RECALL_TYPE_WEIGHTS: RecallTypeWeights = {
  process: 1.5,
  task: 1.2,
  memory: 1.0,
};

export const DEFAULT_CONFIG: PalaiaPluginConfig = {
  tier: "hot",
  maxResults: 10,
  timeoutMs: 3000,
  memoryInject: true,
  maxInjectedChars: 4000,
  autoCapture: true,
  captureFrequency: "significant",
  captureMinTurns: 2,
  captureMinSignificance: 0.5,
  showMemorySources: true,
  showCaptureConfirm: true,
  recallMode: "query",
  recallTypeWeight: { ...DEFAULT_RECALL_TYPE_WEIGHTS },
  recallMinScore: 0.7,
  embeddingServer: true,
  sessionSummary: true,
  sessionBriefing: true,
  sessionBriefingMaxChars: 1500,
  captureToolObservations: true,
  recallRecencyBoost: 0.3,
};

/**
 * Merge user config with defaults. Unknown keys are ignored.
 */
export function resolveConfig(
  userConfig: Partial<PalaiaPluginConfig> | undefined
): PalaiaPluginConfig {
  const base = { ...DEFAULT_CONFIG, ...userConfig };
  // Deep-merge recallTypeWeight
  if (userConfig?.recallTypeWeight) {
    base.recallTypeWeight = {
      ...DEFAULT_RECALL_TYPE_WEIGHTS,
      ...userConfig.recallTypeWeight,
    };
  }
  return base;
}
