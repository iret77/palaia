/**
 * Tests for context-engine.ts — privacy stripping in runAutoCapture.
 *
 * Verifies that <private>...</private> blocks are stripped from messages
 * before auto-capture processes them.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock the runner module
vi.mock("../src/runner.js", () => ({
  runJson: vi.fn().mockResolvedValue({ results: [] }),
  run: vi.fn().mockResolvedValue(""),
  detectBinary: vi.fn().mockResolvedValue("palaia"),
  recover: vi.fn().mockResolvedValue({ replayed: 0, errors: 0 }),
  resetCache: vi.fn(),
  getEmbedServerManager: vi.fn().mockReturnValue({
    start: vi.fn(),
    query: vi.fn(),
  }),
}));

// Mock priorities module
vi.mock("../src/priorities.js", () => ({
  loadPriorities: vi.fn().mockResolvedValue({}),
  resolvePriorities: vi.fn().mockReturnValue({
    recallTypeWeight: {},
    recallMinScore: 0.1,
    maxInjectedChars: 4000,
    tier: "hot",
    blocked: [],
  }),
  filterBlocked: vi.fn((entries: any[]) => entries),
}));

// Mock the LLM extraction to avoid needing real API calls — make it
// "fail" so the rule-based fallback path runs, which is where the
// privacy stripping actually matters for observable behavior.
vi.mock("../src/hooks/capture.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/hooks/capture.js")>();
  return {
    ...actual,
    extractWithLLM: vi.fn().mockRejectedValue(new Error("no LLM")),
    loadProjects: vi.fn().mockResolvedValue([]),
  };
});

import { createPalaiaContextEngine } from "../src/context-engine.js";
import { run } from "../src/runner.js";

const mockRun = vi.mocked(run);

function createMockApi() {
  return {
    logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
    config: {},
    on: vi.fn(),
    registerTool: vi.fn(),
    runtime: undefined,
  } as any;
}

const baseConfig = {
  binaryPath: "palaia",
  workspace: "/tmp/test",
  timeoutMs: 5000,
  autoCapture: true,
  captureScope: "team",
  captureMinTurns: 1,
  captureMinSignificance: 1,
  captureFrequency: "always",
  captureModel: undefined,
  captureProject: undefined,
  captureToolObservations: false,
  embeddingServer: false,
  maxResults: 10,
  maxInjectedChars: 4000,
  memoryInject: false,
  recallMode: "query",
  recallMinScore: 0.1,
  recallRecencyBoost: true,
  recallTypeWeight: {},
  sessionBriefing: false,
  sessionBriefingMaxChars: 1500,
  sessionSummary: false,
  tier: "hot",
} as any;

describe("ContextEngine privacy stripping", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("strips <private> blocks from messages before capture", async () => {
    const api = createMockApi();
    const engine = createPalaiaContextEngine(api, baseConfig);

    // Ingest messages containing private blocks
    const messages = [
      { role: "user", content: "Please help me with authentication. <private>My API key is sk-secret-12345</private>" },
      { role: "assistant", content: "I can help with authentication setup. Here is the recommended approach for securing API keys." },
      { role: "user", content: "Thanks, that approach works well. <private>Internal credential: pass123</private> I learned we should use env vars." },
      { role: "assistant", content: "Great! Using environment variables is a best practice for credential management." },
    ];

    for (const msg of messages) {
      await engine.ingest({ message: msg as any });
    }

    await engine.afterTurn({ messages: messages as any });

    // If run was called (capture happened), verify that private content
    // was NOT included in the captured text
    if (mockRun.mock.calls.length > 0) {
      for (const call of mockRun.mock.calls) {
        const args = call[0] as string[];
        const fullText = args.join(" ");
        expect(fullText).not.toContain("sk-secret-12345");
        expect(fullText).not.toContain("pass123");
        expect(fullText).not.toContain("<private>");
      }
    }
  });
});

/**
 * Direct unit test for stripPrivateBlocks — the function used by runAutoCapture.
 */
describe("stripPrivateBlocks", () => {
  // Import the actual function (not mocked)
  let stripPrivateBlocks: (text: string) => string;

  beforeEach(async () => {
    // Dynamic import to get the real implementation despite the mock above
    const mod = await vi.importActual<typeof import("../src/hooks/capture.js")>("../src/hooks/capture.js");
    stripPrivateBlocks = mod.stripPrivateBlocks;
  });

  it("removes single private block", () => {
    const input = "Public text <private>secret stuff</private> more public";
    expect(stripPrivateBlocks(input)).toBe("Public text  more public");
  });

  it("removes multiple private blocks", () => {
    const input = "A <private>secret1</private> B <private>secret2</private> C";
    expect(stripPrivateBlocks(input)).toBe("A  B  C");
  });

  it("handles multiline private blocks", () => {
    const input = "Before\n<private>\nline1\nline2\n</private>\nAfter";
    expect(stripPrivateBlocks(input)).toBe("Before\n\nAfter");
  });

  it("is case-insensitive", () => {
    const input = "Text <PRIVATE>hidden</PRIVATE> rest";
    expect(stripPrivateBlocks(input)).toBe("Text  rest");
  });

  it("returns original text when no private blocks", () => {
    const input = "Nothing private here";
    expect(stripPrivateBlocks(input)).toBe("Nothing private here");
  });
});
