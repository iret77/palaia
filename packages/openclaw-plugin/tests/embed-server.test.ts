/**
 * Tests for EmbedServerManager in runner.ts.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { spawn } from "node:child_process";
import { EventEmitter, Readable, Writable } from "node:stream";

// Mock child_process
vi.mock("node:child_process", () => ({
  execFile: vi.fn(),
  spawn: vi.fn(),
}));

// Mock fs/promises for access checks
vi.mock("node:fs/promises", () => ({
  access: vi.fn().mockRejectedValue(new Error("ENOENT")),
  constants: { X_OK: 1 },
}));

import {
  EmbedServerManager,
  resetCache,
  resetEmbedServerManager,
} from "../src/runner.js";

const mockSpawn = vi.mocked(spawn);
const { execFile: mockExecFile } = await import("node:child_process");

function setupExecFile(stdout: string, stderr = "", exitCode = 0) {
  (mockExecFile as any).mockImplementation(
    (_cmd: any, _args: any, _opts: any, callback: any) => {
      callback(exitCode ? { code: exitCode } : null, stdout, stderr);
      return { on: vi.fn(), kill: vi.fn() } as any;
    }
  );
}

function createMockProcess() {
  const stdin = new Writable({
    write(_chunk, _encoding, callback) {
      callback();
    },
  });
  const stdout = new Readable({ read() {} });
  const stderr = new Readable({ read() {} });
  const proc = new EventEmitter() as any;
  proc.stdin = stdin;
  proc.stdout = stdout;
  proc.stderr = stderr;
  proc.kill = vi.fn();
  proc.pid = 12345;
  return proc;
}

describe("EmbedServerManager", () => {
  beforeEach(() => {
    resetCache();
    vi.clearAllMocks();
    // Default: palaia is in PATH
    setupExecFile("palaia 2.0.8\n");
  });

  afterEach(async () => {
    await resetEmbedServerManager();
  });

  it("should start subprocess and wait for ready signal", async () => {
    const mockProc = createMockProcess();
    mockSpawn.mockReturnValue(mockProc as any);

    const manager = new EmbedServerManager();
    const startPromise = manager.start();

    // Simulate ready signal
    setTimeout(() => {
      mockProc.stdout.push('{"result":"ready"}\n');
    }, 10);

    await startPromise;
    expect(manager.isRunning).toBe(true);
    expect(mockSpawn).toHaveBeenCalledWith(
      "palaia",
      ["embed-server"],
      expect.objectContaining({
        stdio: ["pipe", "pipe", "pipe"],
      })
    );
  });

  it("should handle ping request", async () => {
    const mockProc = createMockProcess();
    mockSpawn.mockReturnValue(mockProc as any);

    const manager = new EmbedServerManager();
    const startPromise = manager.start();

    setTimeout(() => {
      mockProc.stdout.push('{"result":"ready"}\n');
    }, 10);

    await startPromise;

    // Send ping
    const pingPromise = manager.ping();

    // Simulate response
    setTimeout(() => {
      mockProc.stdout.push('{"result":"pong"}\n');
    }, 10);

    const result = await pingPromise;
    expect(result).toBe(true);
  });

  it("should handle query request", async () => {
    const mockProc = createMockProcess();
    mockSpawn.mockReturnValue(mockProc as any);

    const manager = new EmbedServerManager();
    const startPromise = manager.start();

    setTimeout(() => {
      mockProc.stdout.push('{"result":"ready"}\n');
    }, 10);

    await startPromise;

    const queryPromise = manager.query({ text: "test query", top_k: 5 });

    setTimeout(() => {
      mockProc.stdout.push('{"result":{"results":[{"id":"abc","score":0.8,"title":"Test"}]}}\n');
    }, 10);

    const result = await queryPromise;
    expect(result.result.results).toHaveLength(1);
    expect(result.result.results[0].title).toBe("Test");
  });

  it("should timeout on slow request", async () => {
    const mockProc = createMockProcess();
    mockSpawn.mockReturnValue(mockProc as any);

    const manager = new EmbedServerManager();
    const startPromise = manager.start();

    setTimeout(() => {
      mockProc.stdout.push('{"result":"ready"}\n');
    }, 10);

    await startPromise;

    // Short timeout, no response
    await expect(
      manager.query({ text: "test" }, 50)
    ).rejects.toThrow("timed out");
  });

  it("should stop subprocess gracefully", async () => {
    const mockProc = createMockProcess();
    mockSpawn.mockReturnValue(mockProc as any);

    const manager = new EmbedServerManager();
    const startPromise = manager.start();

    setTimeout(() => {
      mockProc.stdout.push('{"result":"ready"}\n');
    }, 10);

    await startPromise;

    // Stop: send shutdown request, simulate response, then verify stop
    const stopPromise = manager.stop();
    setTimeout(() => {
      mockProc.stdout.push('{"result":"shutting_down"}\n');
    }, 10);

    await stopPromise;
    // After stop(), kill is called to ensure cleanup
    expect(mockProc.kill).toHaveBeenCalledWith("SIGTERM");
    expect(manager.isRunning).toBe(false);
  });

  it("should auto-restart on crash up to max retries", async () => {
    const mockProc1 = createMockProcess();
    const mockProc2 = createMockProcess();
    let spawnCount = 0;
    mockSpawn.mockImplementation(() => {
      spawnCount++;
      return spawnCount === 1 ? mockProc1 as any : mockProc2 as any;
    });

    const manager = new EmbedServerManager();

    // First start
    const start1 = manager.start();
    setTimeout(() => mockProc1.stdout.push('{"result":"ready"}\n'), 10);
    await start1;

    // Simulate crash
    mockProc1.emit("exit", 1);

    // Should auto-restart on next use
    const start2 = manager.ping();
    setTimeout(() => {
      mockProc2.stdout.push('{"result":"ready"}\n');
      setTimeout(() => {
        mockProc2.stdout.push('{"result":"pong"}\n');
      }, 10);
    }, 10);

    const result = await start2;
    expect(result).toBe(true);
    expect(spawnCount).toBe(2);
  });

  it("should fail after max restarts", async () => {
    const manager = new EmbedServerManager();
    // Manually exhaust retries
    (manager as any).restartCount = 3;
    (manager as any).maxRestarts = 3;

    await expect(manager.query({ text: "test" })).rejects.toThrow(
      "max restarts"
    );
  });

  it("should handle server error responses", async () => {
    const mockProc = createMockProcess();
    mockSpawn.mockReturnValue(mockProc as any);

    const manager = new EmbedServerManager();
    const startPromise = manager.start();
    setTimeout(() => mockProc.stdout.push('{"result":"ready"}\n'), 10);
    await startPromise;

    const queryPromise = manager.query({ text: "" });
    setTimeout(() => {
      mockProc.stdout.push('{"error":"Missing \'text\' parameter"}\n');
    }, 10);

    await expect(queryPromise).rejects.toThrow("Missing 'text' parameter");
  });
});
