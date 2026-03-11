/**
 * Plugin configuration schema and defaults for @palaia/openclaw.
 */

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
}

export const DEFAULT_CONFIG: PalaiaPluginConfig = {
  tier: "hot",
  maxResults: 10,
  timeoutMs: 3000,
  memoryInject: false,
  maxInjectedChars: 4000,
};

/**
 * Merge user config with defaults. Unknown keys are ignored.
 */
export function resolveConfig(
  userConfig: Partial<PalaiaPluginConfig> | undefined
): PalaiaPluginConfig {
  return { ...DEFAULT_CONFIG, ...userConfig };
}
