/**
 * Tests for src/hooks/session.ts — session briefing CLI commands.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock the runner module BEFORE importing the module under test
vi.mock("../src/runner.js", () => ({
  runJson: vi.fn(),
  run: vi.fn(),
  detectBinary: vi.fn().mockResolvedValue("palaia"),
  recover: vi.fn().mockResolvedValue({ replayed: 0, errors: 0 }),
  resetCache: vi.fn(),
}));

import { loadSessionBriefing } from "../src/hooks/session.js";
import { runJson } from "../src/runner.js";

const mockRunJson = vi.mocked(runJson);

const baseConfig = {
  binaryPath: "palaia",
  workspace: "/tmp/test-workspace",
  timeoutMs: 5000,
  sessionBriefing: true,
  sessionSummary: true,
  autoCapture: false,
  captureScope: "team",
  captureMinTurns: 2,
  captureMinSignificance: 3,
  captureFrequency: "significant" as const,
  captureModel: undefined,
  captureProject: undefined,
  captureToolObservations: false,
  embeddingServer: false,
  maxResults: 10,
  maxInjectedChars: 4000,
  memoryInject: true,
  recallMode: "query" as const,
  recallMinScore: 0.1,
  recallRecencyBoost: true,
  recallTypeWeight: {},
  sessionBriefingMaxChars: 1500,
  tier: "hot" as const,
};

const logger = {
  info: vi.fn(),
  warn: vi.fn(),
};

describe("loadSessionBriefing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls runJson with correct CLI args for session summary", async () => {
    mockRunJson.mockResolvedValue({ results: [] } as any);

    await loadSessionBriefing(baseConfig as any, logger);

    // Verify the session summary query
    expect(mockRunJson).toHaveBeenCalledWith(
      ["query", "session-summary", "--limit", "1", "--tags", "session-summary"],
      expect.objectContaining({ timeoutMs: 5000 }),
    );
  });

  it("calls runJson with correct CLI args for open tasks", async () => {
    mockRunJson.mockResolvedValue({ results: [] } as any);

    await loadSessionBriefing(baseConfig as any, logger);

    // Verify the open tasks list
    expect(mockRunJson).toHaveBeenCalledWith(
      ["list", "--type", "task", "--status", "open", "--limit", "5"],
      expect.objectContaining({ timeoutMs: 5000 }),
    );
  });

  it("returns summary text from the first result", async () => {
    mockRunJson
      .mockResolvedValueOnce({
        results: [{ title: "Session", body: "Last session we fixed bugs", created: "2026-03-28T10:00:00Z" }],
      } as any)
      .mockResolvedValueOnce({ results: [] } as any);

    const briefing = await loadSessionBriefing(baseConfig as any, logger);

    expect(briefing.summary).toBe("Last session we fixed bugs");
    expect(briefing.openTasks).toEqual([]);
  });

  it("returns open tasks with priority annotations", async () => {
    mockRunJson
      .mockResolvedValueOnce({ results: [] } as any)
      .mockResolvedValueOnce({
        results: [
          { title: "Fix login bug", body: "", priority: "high" },
          { title: "Update docs", body: "" },
        ],
      } as any);

    const briefing = await loadSessionBriefing(baseConfig as any, logger);

    expect(briefing.summary).toBeNull();
    expect(briefing.openTasks).toEqual([
      "Fix login bug (high)",
      "Update docs",
    ]);
  });

  it("handles rejected promises gracefully", async () => {
    mockRunJson
      .mockRejectedValueOnce(new Error("timeout"))
      .mockRejectedValueOnce(new Error("timeout"));

    const briefing = await loadSessionBriefing(baseConfig as any, logger);

    expect(briefing.summary).toBeNull();
    expect(briefing.openTasks).toEqual([]);
  });

  it("passes workspace and binaryPath from config", async () => {
    mockRunJson.mockResolvedValue({ results: [] } as any);

    await loadSessionBriefing(baseConfig as any, logger);

    // Both calls should use runner opts from config
    for (const call of mockRunJson.mock.calls) {
      expect(call[1]).toEqual(
        expect.objectContaining({
          binaryPath: "palaia",
          workspace: "/tmp/test-workspace",
        }),
      );
    }
  });
});
