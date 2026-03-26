/**
 * OpenClaw Plugin SDK types.
 *
 * These interfaces define the contract with OpenClaw's plugin system.
 * They are maintained locally to avoid a build-time dependency on the
 * openclaw package (which is a peerDependency loaded at runtime).
 *
 * Based on OpenClaw v2026.3.22 plugin-sdk.
 */

import type { TObject } from "@sinclair/typebox";

// ── Tool Types ──────────────────────────────────────────────────────────

export interface ToolDefinition {
  name: string;
  description: string;
  parameters: TObject;
  execute(id: string, params: Record<string, unknown>): Promise<ToolResult>;
}

export interface ToolResult {
  content: Array<{ type: "text"; text: string }>;
}

export interface ToolOptions {
  /** Mark this tool as optional (not registered by default). */
  optional?: boolean;
}

export type ToolFactory = ToolDefinition;

// ── Hook Types ──────────────────────────────────────────────────────────

export type HookName =
  | "before_prompt_build"
  | "agent_end"
  | "message_received"
  | "message_sending";

export type HookHandler = (event: unknown, ctx: unknown) => void | Promise<unknown>;

export interface HookOptions {
  priority?: number;
}

// ── Command Types ───────────────────────────────────────────────────────

export interface CommandDefinition {
  name: string;
  description: string;
  handler(args: string): Promise<{ text: string }> | { text: string };
}

// ── Service Types ───────────────────────────────────────────────────────

export interface ServiceDefinition {
  id: string;
  start(): Promise<void>;
  stop?(): Promise<void>;
}

// ── Context Engine Types ────────────────────────────────────────────────

export interface ContextEngine {
  bootstrap?(): Promise<void>;
  ingest?(messages: unknown[]): Promise<void>;
  assemble(budget: { maxTokens: number }): Promise<{ content: string; tokenEstimate: number }>;
  compact?(): Promise<void>;
  afterTurn?(turn: unknown): Promise<void>;
  prepareSubagentSpawn?(parentContext: unknown): Promise<unknown>;
  onSubagentEnded?(result: unknown): Promise<void>;
}

// ── Logger ──────────────────────────────────────────────────────────────

export interface PluginLogger {
  info(...args: unknown[]): void;
  warn(...args: unknown[]): void;
  error?(...args: unknown[]): void;
  debug?(...args: unknown[]): void;
}

// ── Runtime ─────────────────────────────────────────────────────────────

export interface PluginRuntime {
  agent?: {
    runEmbeddedPiAgent?(params: Record<string, unknown>): Promise<unknown>;
  };
  modelAuth?: {
    resolveApiKeyForProvider(params: {
      provider: string;
      cfg: Record<string, unknown>;
    }): Promise<string | null>;
  };
}

// ── Main Plugin API ─────────────────────────────────────────────────────

export interface OpenClawPluginApi {
  registerTool(definition: ToolDefinition, options?: ToolOptions): void;
  registerCommand(command: CommandDefinition): void;
  registerService(service: ServiceDefinition): void;
  registerContextEngine?(id: string, engine: ContextEngine): void;
  on(hook: HookName | string, handler: HookHandler): void;
  getConfig(pluginId: string): Record<string, unknown> | undefined;
  logger: PluginLogger;
  runtime: PluginRuntime;
  config: Record<string, unknown>;
  workspace?: { dir: string; agentId?: string } | string;
}

// ── Plugin Entry ────────────────────────────────────────────────────────

export interface OpenClawPluginEntry {
  id: string;
  name: string;
  register(api: OpenClawPluginApi): void | Promise<void>;
}
