/**
 * Palaia CLI subprocess runner.
 *
 * Executes palaia CLI commands, parses JSON output, handles binary detection
 * and timeouts. This is the bridge between the OpenClaw plugin and the
 * palaia Python CLI.
 */

import { execFile } from "node:child_process";
import { access, constants } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

export interface RunnerOpts {
  /** Working directory for palaia (sets PALAIA_ROOT context) */
  workspace?: string;
  /** Timeout in milliseconds */
  timeoutMs?: number;
  /** Override binary path */
  binaryPath?: string;
}

export interface RunResult {
  stdout: string;
  stderr: string;
  exitCode: number;
}

/** Cached binary path after first detection */
let cachedBinary: string | null = null;

/**
 * Detect the palaia binary location.
 *
 * Search order:
 * 1. Explicit binaryPath from config
 * 2. `palaia` in PATH
 * 3. `~/.local/bin/palaia` (pipx default)
 * 4. `python3 -m palaia` as fallback
 * 5. Error with clear message
 */
export async function detectBinary(
  explicitPath?: string
): Promise<string> {
  if (explicitPath) {
    try {
      await access(explicitPath, constants.X_OK);
      return explicitPath;
    } catch {
      throw new Error(
        `Configured palaia binary not found or not executable: ${explicitPath}`
      );
    }
  }

  if (cachedBinary) return cachedBinary;

  // Try `palaia` in PATH
  try {
    const result = await execCommand("palaia", ["--version"], {
      timeoutMs: 5000,
    });
    if (result.exitCode === 0) {
      cachedBinary = "palaia";
      return "palaia";
    }
  } catch {
    // Not in PATH
  }

  // Try ~/.local/bin/palaia (pipx default)
  const pipxPath = join(homedir(), ".local", "bin", "palaia");
  try {
    await access(pipxPath, constants.X_OK);
    cachedBinary = pipxPath;
    return pipxPath;
  } catch {
    // Not installed via pipx
  }

  // Try python3 -m palaia
  try {
    const result = await execCommand("python3", ["-m", "palaia", "--version"], {
      timeoutMs: 5000,
    });
    if (result.exitCode === 0) {
      cachedBinary = "python3";
      return "python3"; // Will need `-m palaia` prefix
    }
  } catch {
    // Not available
  }

  throw new Error(
    "Palaia binary not found. Install with: pip install palaia\n" +
      "Or set binaryPath in plugin config."
  );
}

/**
 * Check if the detected binary requires `python3 -m palaia` invocation.
 */
function isPythonModule(binary: string): boolean {
  return binary === "python3" || binary.endsWith("/python3");
}

/**
 * Execute a raw command and return result.
 */
function execCommand(
  cmd: string,
  args: string[],
  opts: { timeoutMs?: number; cwd?: string } = {}
): Promise<RunResult> {
  return new Promise((resolve, reject) => {
    const timeout = opts.timeoutMs || 10000;
    const child = execFile(
      cmd,
      args,
      {
        timeout,
        maxBuffer: 1024 * 1024, // 1MB
        cwd: opts.cwd,
        env: {
          ...process.env,
          ...(opts.cwd ? { PALAIA_HOME: opts.cwd } : {}),
        },
      },
      (error, stdout, stderr) => {
        if (error && (error as any).killed) {
          reject(
            new Error(`Palaia command timed out after ${timeout}ms: ${cmd} ${args.join(" ")}`)
          );
          return;
        }
        resolve({
          stdout: stdout?.toString() || "",
          stderr: stderr?.toString() || "",
          exitCode: error ? (error as any).code || 1 : 0,
        });
      }
    );
  });
}

/**
 * Run a palaia CLI command and return raw output.
 */
export async function run(
  args: string[],
  opts: RunnerOpts = {}
): Promise<string> {
  const binary = await detectBinary(opts.binaryPath);
  const timeoutMs = opts.timeoutMs || 3000;

  let cmd: string;
  let cmdArgs: string[];

  if (isPythonModule(binary)) {
    cmd = binary;
    cmdArgs = ["-m", "palaia", ...args];
  } else {
    cmd = binary;
    cmdArgs = [...args];
  }

  let result = await execCommand(cmd, cmdArgs, {
    timeoutMs,
    cwd: opts.workspace,
  });

  // Retry once on lock/timeout errors (L-5: concurrent CLI write safety)
  if (result.exitCode !== 0) {
    const errMsg = result.stderr.trim() || result.stdout.trim();
    const errLower = errMsg.toLowerCase();
    if (errLower.includes("lock") || errLower.includes("timeout")) {
      await new Promise((r) => setTimeout(r, 500));
      result = await execCommand(cmd, cmdArgs, {
        timeoutMs,
        cwd: opts.workspace,
      });
    }
  }

  if (result.exitCode !== 0) {
    const errMsg = result.stderr.trim() || result.stdout.trim();
    throw new Error(`Palaia CLI error (exit ${result.exitCode}): ${errMsg}`);
  }

  return result.stdout;
}

/**
 * Run a palaia CLI command and parse JSON output.
 */
export async function runJson<T = unknown>(
  args: string[],
  opts: RunnerOpts = {}
): Promise<T> {
  const stdout = await run([...args, "--json"], opts);
  try {
    return JSON.parse(stdout) as T;
  } catch {
    throw new Error(
      `Failed to parse palaia JSON output: ${stdout.slice(0, 200)}`
    );
  }
}

/**
 * Run WAL recovery on startup.
 */
export async function recover(opts: RunnerOpts = {}): Promise<{
  replayed: number;
  errors: number;
}> {
  try {
    return await runJson<{ replayed: number; errors: number }>(
      ["recover"],
      { ...opts, timeoutMs: opts.timeoutMs || 10000 }
    );
  } catch (error) {
    // Recovery failure is non-fatal — log and continue
    console.warn(`[palaia] WAL recovery warning: ${error}`);
    return { replayed: 0, errors: 1 };
  }
}

/**
 * Reset cached binary (for testing).
 */
export function resetCache(): void {
  cachedBinary = null;
}
