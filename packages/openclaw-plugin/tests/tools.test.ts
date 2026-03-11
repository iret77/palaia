/**
 * Tests for src/tools.ts — memory_search, memory_get, memory_write with mock runner.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock the runner module
vi.mock("../src/runner.js", () => ({
  runJson: vi.fn(),
  run: vi.fn(),
  detectBinary: vi.fn().mockResolvedValue("palaia"),
  recover: vi.fn().mockResolvedValue({ replayed: 0, errors: 0 }),
  resetCache: vi.fn(),
}));

import { registerTools } from "../src/tools.js";
import { runJson } from "../src/runner.js";
import { DEFAULT_CONFIG } from "../src/config.js";

const mockRunJson = vi.mocked(runJson);

/**
 * Fake plugin API that captures registered tools.
 */
function createMockApi() {
  const tools: Record<string, { def: any; opts?: any }> = {};
  return {
    tools,
    registerTool(def: any, opts?: any) {
      tools[def.name] = { def, opts };
    },
  };
}

describe("tools", () => {
  let api: ReturnType<typeof createMockApi>;

  beforeEach(() => {
    vi.clearAllMocks();
    api = createMockApi();
    registerTools(api, DEFAULT_CONFIG);
  });

  it("registers memory_search, memory_get, memory_write", () => {
    expect(api.tools["memory_search"]).toBeDefined();
    expect(api.tools["memory_get"]).toBeDefined();
    expect(api.tools["memory_write"]).toBeDefined();
  });

  it("memory_write is optional", () => {
    expect(api.tools["memory_write"].opts).toEqual({ optional: true });
  });

  it("memory_search and memory_get are required (no optional flag)", () => {
    expect(api.tools["memory_search"].opts).toBeUndefined();
    expect(api.tools["memory_get"].opts).toBeUndefined();
  });

  describe("memory_search", () => {
    it("returns formatted results", async () => {
      mockRunJson.mockResolvedValueOnce({
        results: [
          {
            id: "abc-123",
            body: "Test memory content",
            score: 0.92,
            tier: "hot",
            scope: "team",
            title: "Test Entry",
            path: "hot/abc-123.md",
          },
        ],
      });

      const execute = api.tools["memory_search"].def.execute;
      const result = await execute("call-1", { query: "test" });

      expect(result.content).toHaveLength(1);
      expect(result.content[0].type).toBe("text");
      expect(result.content[0].text).toContain("Test memory content");
      expect(result.content[0].text).toContain("Source: hot/abc-123.md");
      expect(result.content[0].text).toContain("score: 0.92");

      // Verify CLI args
      expect(mockRunJson).toHaveBeenCalledWith(
        ["query", "test", "--limit", "5"],
        expect.any(Object)
      );
    });

    it("respects maxResults param", async () => {
      mockRunJson.mockResolvedValueOnce({ results: [] });

      await api.tools["memory_search"].def.execute("call-2", {
        query: "test",
        maxResults: 20,
      });

      expect(mockRunJson).toHaveBeenCalledWith(
        ["query", "test", "--limit", "20"],
        expect.any(Object)
      );
    });

    it("passes --all for tier=all", async () => {
      mockRunJson.mockResolvedValueOnce({ results: [] });

      await api.tools["memory_search"].def.execute("call-3", {
        query: "test",
        tier: "all",
      });

      expect(mockRunJson).toHaveBeenCalledWith(
        expect.arrayContaining(["--all"]),
        expect.any(Object)
      );
    });

    it("returns 'No results found.' when empty", async () => {
      mockRunJson.mockResolvedValueOnce({ results: [] });

      const result = await api.tools["memory_search"].def.execute("call-4", {
        query: "nothing",
      });

      expect(result.content[0].text).toBe("No results found.");
    });
  });

  describe("memory_get", () => {
    it("returns entry content", async () => {
      mockRunJson.mockResolvedValueOnce({
        id: "abc-123",
        content: "Full entry content here",
        meta: { scope: "team", tier: "hot" },
      });

      const result = await api.tools["memory_get"].def.execute("call-5", {
        path: "abc-123",
      });

      expect(result.content[0].text).toBe("Full entry content here");
      expect(mockRunJson).toHaveBeenCalledWith(
        ["get", "abc-123"],
        expect.any(Object)
      );
    });

    it("passes --from and --lines", async () => {
      mockRunJson.mockResolvedValueOnce({
        id: "abc-123",
        content: "Line 5\nLine 6",
        meta: { scope: "team", tier: "hot" },
      });

      await api.tools["memory_get"].def.execute("call-6", {
        path: "abc-123",
        from: 5,
        lines: 2,
      });

      expect(mockRunJson).toHaveBeenCalledWith(
        ["get", "abc-123", "--from", "5", "--lines", "2"],
        expect.any(Object)
      );
    });
  });

  describe("memory_write", () => {
    it("writes and returns confirmation", async () => {
      mockRunJson.mockResolvedValueOnce({
        id: "new-456",
        tier: "hot",
        scope: "team",
        deduplicated: false,
      });

      const result = await api.tools["memory_write"].def.execute("call-7", {
        content: "Important note",
        scope: "team",
        tags: ["project", "idea"],
      });

      expect(result.content[0].text).toContain("new-456");
      expect(result.content[0].text).toContain("hot");
      expect(mockRunJson).toHaveBeenCalledWith(
        ["write", "Important note", "--scope", "team", "--tags", "project,idea"],
        expect.any(Object)
      );
    });

    it("works without optional params", async () => {
      mockRunJson.mockResolvedValueOnce({
        id: "new-789",
        tier: "hot",
        scope: "team",
        deduplicated: false,
      });

      await api.tools["memory_write"].def.execute("call-8", {
        content: "Simple note",
      });

      expect(mockRunJson).toHaveBeenCalledWith(
        ["write", "Simple note"],
        expect.any(Object)
      );
    });
  });
});
