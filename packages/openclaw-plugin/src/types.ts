/**
 * OpenClaw Plugin SDK types.
 *
 * These interfaces define the contract with OpenClaw's plugin system.
 * They are maintained locally to avoid a build-time dependency on the
 * openclaw package (which is a peerDependency loaded at runtime).
 *
 * Based on OpenClaw v2026.3.28 plugin-sdk.
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

export type ToolFactory = ToolDefinition | ((ctx: Record<string, unknown>) => ToolDefinition | ToolDefinition[] | null);

// ── Hook Types ─────────────��────────────────────────────────────────────

/**
 * All hook names supported by OpenClaw v2026.3.28.
 * palaia registers handlers for a subset of these.
 */
export type HookName =
  // Session lifecycle
  | "session_start"
  | "session_end"
  // Agent & LLM
  | "before_model_resolve"
  | "before_prompt_build"
  | "before_agent_start"
  | "llm_input"
  | "llm_output"
  | "agent_end"
  // Context management
  | "before_compaction"
  | "after_compaction"
  | "before_reset"
  // Messages
  | "inbound_claim"
  | "before_dispatch"
  | "message_received"
  | "message_sending"
  | "message_sent"
  // Tool execution
  | "before_tool_call"
  | "after_tool_call"
  | "tool_result_persist"
  | "before_message_write"
  // Subagents
  | "subagent_spawning"
  | "subagent_delivery_target"
  | "subagent_spawned"
  | "subagent_ended"
  // Gateway
  | "gateway_start"
  | "gateway_stop";

export type HookHandler = (event: unknown, ctx: unknown) => unknown | Promise<unknown>;

export interface HookOptions {
  priority?: number;
}

// ── Hook Event Types ────────────────────────────────────────────────────

/** session_start event. */
export type SessionStartEvent = {
  sessionId: string;
  sessionKey?: string;
  resumedFrom?: string;
};

/** session_end event. */
export type SessionEndEvent = {
  sessionId: string;
  sessionKey?: string;
  messageCount: number;
  durationMs?: number;
};

/** before_prompt_build event. */
export type BeforePromptBuildEvent = {
  prompt: string;
  messages: unknown[];
};

/** before_prompt_build result. */
export type BeforePromptBuildResult = {
  systemPrompt?: string;
  prependContext?: string;
  prependSystemContext?: string;
  appendSystemContext?: string;
};

/** before_reset event. */
export type BeforeResetEvent = {
  sessionFile?: string;
  messages?: unknown[];
  reason?: string;
};

/** agent_end event. */
export type AgentEndEvent = {
  messages: unknown[];
  success: boolean;
  error?: string;
  durationMs?: number;
};

/** llm_input event — fired before each LLM call. */
export type LlmInputEvent = {
  runId: string;
  sessionId: string;
  provider: string;
  model: string;
  systemPrompt?: string;
  prompt: string;
  historyMessages: unknown[];
  imagesCount: number;
};

/** llm_output event — fired after each LLM response. */
export type LlmOutputEvent = {
  runId: string;
  sessionId: string;
  provider: string;
  model: string;
  assistantTexts: string[];
  lastAssistant?: unknown;
  usage?: {
    input?: number;
    output?: number;
    cacheRead?: number;
    cacheWrite?: number;
    total?: number;
  };
};

/** after_tool_call event. */
export type AfterToolCallEvent = {
  toolName: string;
  params: Record<string, unknown>;
  runId?: string;
  toolCallId?: string;
  result?: unknown;
  error?: string;
  durationMs?: number;
};

/** message_received event. */
export type MessageReceivedEvent = {
  from: string;
  content: string;
  timestamp?: number;
  metadata?: Record<string, unknown>;
};

/** message_sending event. */
export type MessageSendingEvent = {
  to: string;
  content: string;
  metadata?: Record<string, unknown>;
};

/** message_sending result. */
export type MessageSendingResult = {
  content?: string;
  cancel?: boolean;
};

/** subagent_spawning event. */
export type SubagentSpawningEvent = {
  childSessionKey: string;
  agentId: string;
  label?: string;
  mode: "run" | "session";
  requester?: {
    channel?: string;
    accountId?: string;
    to?: string;
    threadId?: string | number;
  };
  threadRequested: boolean;
};

/** subagent_ended event. */
export type SubagentEndedEvent = {
  targetSessionKey: string;
  targetKind: "subagent" | "acp";
  reason: string;
  sendFarewell?: boolean;
  accountId?: string;
  runId?: string;
  endedAt?: number;
  outcome?: "ok" | "error" | "timeout" | "killed" | "reset" | "deleted";
  error?: string;
};

// ── Hook Context Types ──────────────��───────────────────────────────────

export type AgentContext = {
  agentId?: string;
  sessionKey?: string;
  sessionId?: string;
  workspaceDir?: string;
  messageProvider?: string;
  trigger?: string;
  channelId?: string;
};

export type MessageContext = {
  channelId: string;
  accountId?: string;
  conversationId?: string;
};

export type SessionContext = {
  agentId?: string;
  sessionId: string;
  sessionKey?: string;
};

export type ToolContext = {
  agentId?: string;
  sessionKey?: string;
  sessionId?: string;
  runId?: string;
  toolName: string;
  toolCallId?: string;
};

export type SubagentContext = {
  runId?: string;
  childSessionKey?: string;
  requesterSessionKey?: string;
};

// ── Command Types ───���───────────────────────────────────────────────────

export interface CommandDefinition {
  name: string;
  description: string;
  handler(args: string): Promise<{ text: string }> | { text: string };
}

// ── Service Types ─────────────────────────────────────���─────────────────

export interface ServiceContext {
  config: Record<string, unknown>;
  workspaceDir?: string;
  stateDir: string;
  logger: PluginLogger;
}

export interface ServiceDefinition {
  id: string;
  start(ctx: ServiceContext): Promise<void>;
  stop?(ctx: ServiceContext): Promise<void>;
}

// ���─ Context Engine Types ────────────���───────────────────────────────────

/** Opaque message type from OpenClaw's agent runtime. */
export type AgentMessage = unknown;

export interface ContextEngineInfo {
  id: string;
  name: string;
  version?: string;
  ownsCompaction?: boolean;
}

export type BootstrapResult = {
  bootstrapped: boolean;
  importedMessages?: number;
  reason?: string;
};

export type IngestResult = {
  ingested: boolean;
};

export type AssembleResult = {
  messages: AgentMessage[];
  estimatedTokens: number;
  systemPromptAddition?: string;
};

export type CompactResult = {
  ok: boolean;
  compacted: boolean;
  reason?: string;
  result?: {
    summary?: string;
    firstKeptEntryId?: string;
    tokensBefore: number;
    tokensAfter?: number;
    details?: unknown;
  };
};

export type SubagentSpawnPreparation = {
  rollback: () => void | Promise<void>;
};

export type SubagentEndReason = "deleted" | "completed" | "swept" | "released";

/**
 * ContextEngine interface — matches OpenClaw v2026.3.28.
 *
 * This is the full interface. palaia implements a subset;
 * optional methods are marked with `?`.
 */
export interface ContextEngine {
  readonly info: ContextEngineInfo;

  bootstrap?(params: {
    sessionId: string;
    sessionKey?: string;
    sessionFile: string;
  }): Promise<BootstrapResult>;

  maintain?(params: {
    sessionId: string;
    sessionKey?: string;
    sessionFile: string;
    runtimeContext?: Record<string, unknown>;
  }): Promise<unknown>;

  ingest(params: {
    sessionId: string;
    sessionKey?: string;
    message: AgentMessage;
    isHeartbeat?: boolean;
  }): Promise<IngestResult>;

  ingestBatch?(params: {
    sessionId: string;
    sessionKey?: string;
    messages: AgentMessage[];
    isHeartbeat?: boolean;
  }): Promise<{ ingestedCount: number }>;

  afterTurn?(params: {
    sessionId: string;
    sessionKey?: string;
    sessionFile: string;
    messages: AgentMessage[];
    prePromptMessageCount: number;
    autoCompactionSummary?: string;
    isHeartbeat?: boolean;
    tokenBudget?: number;
    runtimeContext?: Record<string, unknown>;
  }): Promise<void>;

  assemble(params: {
    sessionId: string;
    sessionKey?: string;
    messages: AgentMessage[];
    tokenBudget?: number;
    model?: string;
    prompt?: string;
  }): Promise<AssembleResult>;

  compact(params: {
    sessionId: string;
    sessionKey?: string;
    sessionFile: string;
    tokenBudget?: number;
    force?: boolean;
    currentTokenCount?: number;
    compactionTarget?: "budget" | "threshold";
    customInstructions?: string;
    runtimeContext?: Record<string, unknown>;
  }): Promise<CompactResult>;

  prepareSubagentSpawn?(params: {
    parentSessionKey: string;
    childSessionKey: string;
    ttlMs?: number;
  }): Promise<SubagentSpawnPreparation | undefined>;

  onSubagentEnded?(params: {
    childSessionKey: string;
    reason: SubagentEndReason;
  }): Promise<void>;

  dispose?(): Promise<void>;
}

/**
 * Legacy ContextEngine interface for backward compatibility.
 * Used when OpenClaw < 2026.3.24 registers via the old signature.
 */
export interface LegacyContextEngine {
  bootstrap?(): Promise<void>;
  ingest?(messages: unknown[]): Promise<void>;
  assemble(budget: { maxTokens: number }): Promise<{ content: string; tokenEstimate: number }>;
  compact?(): Promise<void>;
  afterTurn?(turn: unknown): Promise<void>;
  prepareSubagentSpawn?(parentContext: unknown): Promise<unknown>;
  onSubagentEnded?(result: unknown): Promise<void>;
}

export type ContextEngineFactory = () => ContextEngine | Promise<ContextEngine>;

// ── Memory Prompt Section ───────────────────────────────────────────────

export type MemoryPromptSectionBuilder = (params: {
  availableTools: Set<string>;
  citationsMode?: string;
}) => string[];

// ── Logger ──────────────���───────────────────────────────────────────────

export interface PluginLogger {
  info(message: string): void;
  warn(message: string): void;
  error(message: string): void;
  debug?(message: string): void;
}

// ���─ Runtime ───────────────��─────────────────────────────���───────────────

export interface PluginRuntime {
  version?: string;
  agent?: {
    runEmbeddedPiAgent?(params: Record<string, unknown>): Promise<unknown>;
    session?: {
      resolveStorePath?(...args: unknown[]): string;
      loadSessionStore?(...args: unknown[]): Promise<unknown>;
    };
  };
  subagent?: {
    run?(params: {
      sessionKey: string;
      message: string;
      provider?: string;
      model?: string;
      extraSystemPrompt?: string;
    }): Promise<{ runId: string }>;
    getSessionMessages?(params: {
      sessionKey: string;
      limit?: number;
    }): Promise<{ messages: unknown[] }>;
  };
  modelAuth?: {
    resolveApiKeyForProvider(params: {
      provider: string;
      cfg?: Record<string, unknown>;
    }): Promise<string | null>;
  };
  system?: {
    requestHeartbeatNow?(): void;
  };
  events?: {
    onSessionTranscriptUpdate?(handler: (event: unknown) => void): void;
  };
}

// ── Main Plugin API ─────────────────────────────────────────────────────

export interface OpenClawPluginApi {
  id: string;
  name: string;
  version?: string;
  source?: string;
  registrationMode?: string;

  registerTool(definition: ToolDefinition | ToolFactory, options?: ToolOptions): void;
  registerCommand(command: CommandDefinition): void;
  registerService(service: ServiceDefinition): void;
  registerContextEngine?(id: string, factory: ContextEngineFactory): void;
  registerMemoryPromptSection?(builder: MemoryPromptSectionBuilder): void;
  registerHook?(events: string | string[], handler: HookHandler, opts?: HookOptions): void;
  on(hook: HookName | string, handler: HookHandler, opts?: HookOptions): void;
  logger: PluginLogger;
  runtime: PluginRuntime;
  config: Record<string, unknown>;
  pluginConfig?: Record<string, unknown>;
  workspace?: { dir: string; agentId?: string } | string;
}

// ── Plugin Entry ────────���───────────────────────────────────────────────

export interface OpenClawPluginEntry {
  id: string;
  name: string;
  register(api: OpenClawPluginApi): void | Promise<void>;
}
