/**
 * Tests for src/runner.ts — binary detection, timeout handling, JSON parsing.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { execFile } from "node:child_process";

// Mock child_process
vi.mock("node:child_process", () => ({
  execFile: vi.fn(),
}));

// Mock fs/promises for access checks
vi.mock("node:fs/promises", () => ({
  access: vi.fn().mockRejectedValue(new Error("ENOENT")),
  constants: { X_OK: 1 },
}));

import { detectBinary, run, runJson, recover, resetCache } from "../src/runner.js";

const mockExecFile = vi.mocked(execFile);

function setupExecFile(
  stdout: string,
  stderr = "",
  exitCode = 0,
  error: any = null
) {
  mockExecFile.mockImplementation(
    (_cmd: any, _args: any, _opts: any, callback: any) => {
      if (exitCode !== 0 && !error) {
        error = Object.assign(new Error(stderr), { code: exitCode });
      }
      callback(error, stdout, stderr);
      return {} as any;
    }
  );
}

describe("runner", () => {
  beforeEach(() => {
    resetCache();
    vi.clearAllMocks();
  });

  describe("detectBinary", () => {
    it("returns explicit path when provided", async () => {
      const { access } = await import("node:fs/promises");
      vi.mocked(access).mockResolvedValueOnce(undefined);

      const result = await detectBinary("/usr/local/bin/palaia");
      expect(result).toBe("/usr/local/bin/palaia");
    });

    it("throws when explicit path not found", async () => {
      await expect(detectBinary("/nonexistent/palaia")).rejects.toThrow(
        "not found or not executable"
      );
    });

    it("detects palaia in PATH", async () => {
      setupExecFile("palaia 0.3.0\n");
      const result = await detectBinary();
      expect(result).toBe("palaia");
    });
  });

  describe("runJson", () => {
    it("parses valid JSON output", async () => {
      const jsonOutput = JSON.stringify({ results: [{ id: "abc" }] });
      setupExecFile(jsonOutput);
      resetCache();
      // Pre-seed binary cache
      setupExecFile(jsonOutput);

      // Need to detect binary first
      setupExecFile("palaia 0.3.0\n");
      await detectBinary();

      setupExecFile(jsonOutput);
      const result = await runJson<{ results: any[] }>(["query", "test"], {
        binaryPath: "palaia",
      });
      expect(result.results).toHaveLength(1);
      expect(result.results[0].id).toBe("abc");
    });

    it("throws on invalid JSON", async () => {
      setupExecFile("not json at all");
      await expect(
        runJson(["query", "test"], { binaryPath: "palaia" })
      ).rejects.toThrow("Failed to parse");
    });
  });

  describe("run", () => {
    it("throws on non-zero exit code", async () => {
      setupExecFile("", "Something failed", 1);
      await expect(
        run(["query", "test"], { binaryPath: "palaia" })
      ).rejects.toThrow("Palaia CLI error");
    });
  });

  describe("recover", () => {
    it("returns result on success", async () => {
      const jsonOutput = JSON.stringify({ replayed: 2, errors: 0 });
      setupExecFile(jsonOutput);
      const result = await recover({ binaryPath: "palaia" });
      expect(result.replayed).toBe(2);
      expect(result.errors).toBe(0);
    });

    it("returns fallback on failure", async () => {
      setupExecFile("", "fail", 1, new Error("fail"));
      const result = await recover({ binaryPath: "palaia" });
      expect(result.replayed).toBe(0);
      expect(result.errors).toBe(1);
    });
  });
});
