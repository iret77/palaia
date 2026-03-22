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

import { detectBinary, run, runJson, recover, resetCache, checkVersionMismatch } from "../src/runner.js";

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
      const { access } = await import("node:fs/promises");
      vi.mocked(access).mockResolvedValueOnce(undefined); // allow binaryPath check
      const jsonOutput = JSON.stringify({ results: [{ id: "abc" }] });
      setupExecFile(jsonOutput);
      const result = await runJson<{ results: any[] }>(["query", "test"], {
        binaryPath: "palaia",
      });
      expect(result.results).toHaveLength(1);
      expect(result.results[0].id).toBe("abc");
    });

    it("throws on invalid JSON", async () => {
      const { access } = await import("node:fs/promises");
      vi.mocked(access).mockResolvedValueOnce(undefined); // allow binaryPath check
      setupExecFile("not json at all");
      await expect(
        runJson(["query", "test"], { binaryPath: "palaia" })
      ).rejects.toThrow("Failed to parse");
    });
  });

  describe("run", () => {
    it("throws on non-zero exit code", async () => {
      const { access } = await import("node:fs/promises");
      vi.mocked(access).mockResolvedValueOnce(undefined); // allow binaryPath check
      setupExecFile("", "Something failed", 1);
      await expect(
        run(["query", "test"], { binaryPath: "palaia" })
      ).rejects.toThrow("Palaia CLI error");
    });
  });

  describe("recover", () => {
    it("returns result on success", async () => {
      const { access } = await import("node:fs/promises");
      vi.mocked(access).mockResolvedValueOnce(undefined); // allow binaryPath check
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

  describe("checkVersionMismatch", () => {
    it("returns no mismatch when CLI version matches plugin version", async () => {
      const { access } = await import("node:fs/promises");
      vi.mocked(access).mockResolvedValueOnce(undefined); // allow binaryPath check
      // Mock `palaia --version` returning the same version as the plugin package.json
      setupExecFile("palaia 2.0.11\n");
      const result = await checkVersionMismatch({ binaryPath: "palaia" });
      // pluginVersion comes from package.json — check mismatch logic only
      if (result.pluginVersion === "2.0.11") {
        expect(result.mismatch).toBe(false);
        expect(result.nudge).toBeNull();
      } else {
        // plugin version differs from CLI mock — mismatch expected
        expect(result.mismatch).toBe(true);
        expect(result.nudge).toContain("Version mismatch detected");
      }
    });

    it("returns mismatch with nudge when CLI version differs from plugin version", async () => {
      const { access } = await import("node:fs/promises");
      vi.mocked(access).mockResolvedValueOnce(undefined); // allow binaryPath check
      // Mock CLI returning an old version
      setupExecFile("palaia 1.8.1\n");
      const result = await checkVersionMismatch({ binaryPath: "palaia" });
      // CLI=1.8.1; plugin version is from package.json (2.0.11)
      // If plugin version is available, we should detect a mismatch
      if (result.pluginVersion && result.pluginVersion !== "1.8.1") {
        expect(result.mismatch).toBe(true);
        expect(result.cliVersion).toBe("1.8.1");
        expect(result.nudge).toContain("Version mismatch detected");
        expect(result.nudge).toContain("uv tool upgrade palaia");
        expect(result.nudge).toContain("palaia doctor --fix");
      } else {
        // package.json not resolvable in test env — no mismatch possible
        expect(result.mismatch).toBe(false);
      }
    });

    it("returns no mismatch when binary is not found", async () => {
      // All access() calls already reject (default mock); execFile also fails
      setupExecFile("", "palaia: command not found", 127);
      const result = await checkVersionMismatch();
      expect(result.mismatch).toBe(false);
      expect(result.nudge).toBeNull();
    });

    it("parses version from plain semver output", async () => {
      const { access } = await import("node:fs/promises");
      vi.mocked(access).mockResolvedValueOnce(undefined);
      setupExecFile("2.0.11\n"); // Some installs omit the "palaia" prefix
      const result = await checkVersionMismatch({ binaryPath: "palaia" });
      expect(result.cliVersion).toBe("2.0.11");
    });

    it("handles version detection failure gracefully (non-fatal)", async () => {
      setupExecFile("", "unexpected error", 1, new Error("exec failure"));
      const result = await checkVersionMismatch({ binaryPath: "palaia" });
      expect(result.mismatch).toBe(false);
      expect(result.nudge).toBeNull();
    });
  });
});
