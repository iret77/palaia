/**
 * Palaia CLI subprocess runner.
 *
 * Executes palaia CLI commands, parses JSON output, handles binary detection
 * and timeouts. This is the bridge between the OpenClaw plugin and the
 * palaia Python CLI.
 */

import { execFile } from "node:child_process";
import { access, constants } from "node:fs/promises";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

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

/** Version mismatch warning (set once during first binary detection) */
let versionMismatchWarning: string | null = null;

/**
 * Extract semver (Major.Minor.Patch) from a version string.
 * Strips leading 'v', trailing suffixes like -dev, +build, etc.
 */
function parseSemver(raw: string): string | null {
  const match = raw.trim().match(/v?(\d+\.\d+\.\d+)/);
  return match ? match[1] : null;
}

/**
 * Read the plugin's own version from its package.json.
 */
async function getPluginVersion(): Promise<string | null> {
  try {
    const pkgPath = join(dirname(fileURLToPath(import.meta.url)), "..", "package.json");
    const content = await readFile(pkgPath, "utf-8");
    const pkg = JSON.parse(content);
    return parseSemver(pkg.version || "");
  } catch {
    return null;
  }
}

/**
 * Check CLI version against plugin version. Logs warning on mismatch.
 * Called once during first binary detection.
 */
async function checkVersionMismatch(cliVersionOutput: string): Promise<void> {
  const cliVersion = parseSemver(cliVersionOutput);
  const pluginVersion = await getPluginVersion();

  if (!cliVersion || !pluginVersion) return;
  if (cliVersion === pluginVersion) return;

  versionMismatchWarning =
    `Palaia CLI version (${cliVersion}) does not match plugin version (${pluginVersion}). ` +
    `Update with: pip install --upgrade palaia (or: uv tool upgrade palaia), ` +
    `then run: palaia doctor --fix`;

  console.warn(`[palaia] ${versionMismatchWarning}`);
}

/**
 * Get the version mismatch warning, if any.
 * Returns null if versions match or haven't been checked yet.
 */
export function getVersionMismatchWarning(): string | null {
  return versionMismatchWarning;
}

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
      await checkVersionMismatch(result.stdout);
      return "palaia";
    }
  } catch {
    // Not in PATH
  }

  // Try ~/.local/bin/palaia (pipx default)
  const pipxPath = join(homedir(), ".local", "bin", "palaia");
  try {
    await access(pipxPath, constants.X_OK);
    // Get version for mismatch check
    const pipxResult = await execCommand(pipxPath, ["--version"], { timeoutMs: 5000 });
    if (pipxResult.exitCode === 0) {
      await checkVersionMismatch(pipxResult.stdout);
    }
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
      await checkVersionMismatch(result.stdout);
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

// ============================================================================
// EmbedServerManager (v2.0.8)
// ============================================================================

import { spawn, type ChildProcess } from "node:child_process";
import { createInterface, type Interface as ReadlineInterface } from "node:readline";

export interface EmbedServerQueryParams {
  text: string;
  top_k?: number;
  agent?: string;
  project?: string;
  scope?: string;
  type?: string;
  status?: string;
  priority?: string;
  assignee?: string;
  instance?: string;
  include_cold?: boolean;
  cross_project?: boolean;
}

interface PendingRequest {
  resolve: (value: any) => void;
  reject: (reason: any) => void;
  timer: ReturnType<typeof setTimeout>;
}

/**
 * Manages a long-lived `palaia embed-server` subprocess.
 *
 * The subprocess loads the embedding model once and serves queries over
 * stdin/stdout JSON-RPC, reducing query time from ~14s to ~0.5s.
 *
 * Features:
 * - Lazy start on first use
 * - Auto-restart on crash (max 3 retries)
 * - Graceful shutdown on process exit
 * - Timeout per request with fallback to CLI
 */
export class EmbedServerManager {
  private proc: ChildProcess | null = null;
  private rl: ReadlineInterface | null = null;
  private ready = false;
  private starting = false;
  private restartCount = 0;
  private maxRestarts = 3;
  private opts: RunnerOpts;
  private pendingRequest: PendingRequest | null = null;
  private cleanupRegistered = false;

  constructor(opts: RunnerOpts = {}) {
    this.opts = opts;
  }

  /**
   * Start the embed-server subprocess. Resolves when the server signals ready.
   */
  async start(): Promise<void> {
    if (this.ready || this.starting) return;
    this.starting = true;

    try {
      const binary = await detectBinary(this.opts.binaryPath);
      let cmd: string;
      let args: string[];

      if (isPythonModule(binary)) {
        cmd = binary;
        args = ["-m", "palaia", "embed-server"];
      } else {
        cmd = binary;
        args = ["embed-server"];
      }

      this.proc = spawn(cmd, args, {
        stdio: ["pipe", "pipe", "pipe"],
        cwd: this.opts.workspace,
        env: {
          ...process.env,
          ...(this.opts.workspace ? { PALAIA_HOME: this.opts.workspace } : {}),
        },
      });

      this.rl = createInterface({ input: this.proc.stdout! });

      // Wait for the "ready" signal
      await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => {
          reject(new Error("Embed server startup timed out"));
        }, 30_000);

        const onLine = (line: string) => {
          try {
            const msg = JSON.parse(line);
            if (msg.result === "ready") {
              clearTimeout(timeout);
              this.ready = true;
              this.starting = false;
              this.restartCount = 0;
              // Set up ongoing line handler
              this.rl!.on("line", (l) => this.handleLine(l));
              resolve();
            }
          } catch {
            // Ignore non-JSON lines during startup
          }
        };

        this.rl!.once("line", onLine);

        this.proc!.on("error", (err) => {
          clearTimeout(timeout);
          reject(err);
        });
      });

      // Handle crash
      this.proc.on("exit", (code) => {
        this.ready = false;
        this.proc = null;
        this.rl = null;
        // Reject any pending request
        if (this.pendingRequest) {
          this.pendingRequest.reject(new Error(`Embed server exited with code ${code}`));
          clearTimeout(this.pendingRequest.timer);
          this.pendingRequest = null;
        }
      });

      // Register cleanup
      if (!this.cleanupRegistered) {
        this.cleanupRegistered = true;
        process.on("exit", () => this.stopSync());
      }
    } catch (err) {
      this.starting = false;
      throw err;
    }
  }

  /**
   * Send a query to the embed server.
   */
  async query(params: EmbedServerQueryParams, timeoutMs = 3000): Promise<any> {
    await this.ensureRunning();
    return this.sendRequest({ method: "query", params }, timeoutMs);
  }

  /**
   * Trigger warmup (index missing entries).
   */
  async warmup(timeoutMs = 60_000): Promise<any> {
    await this.ensureRunning();
    return this.sendRequest({ method: "warmup" }, timeoutMs);
  }

  /**
   * Health check.
   */
  async ping(timeoutMs = 3000): Promise<boolean> {
    try {
      await this.ensureRunning();
      const resp = await this.sendRequest({ method: "ping" }, timeoutMs);
      return resp?.result === "pong";
    } catch {
      return false;
    }
  }

  /**
   * Get server status.
   */
  async status(timeoutMs = 3000): Promise<any> {
    await this.ensureRunning();
    return this.sendRequest({ method: "status" }, timeoutMs);
  }

  /**
   * Stop the subprocess gracefully.
   */
  async stop(): Promise<void> {
    if (!this.proc) return;
    try {
      await this.sendRequest({ method: "shutdown" }, 3000);
    } catch {
      // Force kill if shutdown request fails
    }
    this.stopSync();
  }

  /**
   * Synchronous stop (for process.on('exit')).
   */
  private stopSync(): void {
    if (this.proc) {
      try {
        this.proc.kill("SIGTERM");
      } catch {
        // Already dead
      }
      this.proc = null;
      this.rl = null;
      this.ready = false;
    }
  }

  /**
   * Whether the server is currently running and ready.
   */
  get isRunning(): boolean {
    return this.ready && this.proc !== null;
  }

  private async ensureRunning(): Promise<void> {
    if (this.ready && this.proc) return;
    if (this.restartCount >= this.maxRestarts) {
      throw new Error("Embed server max restarts exceeded");
    }
    this.restartCount++;
    await this.start();
  }

  private sendRequest(request: Record<string, unknown>, timeoutMs: number): Promise<any> {
    return new Promise((resolve, reject) => {
      if (!this.proc?.stdin?.writable) {
        reject(new Error("Embed server not running"));
        return;
      }

      // Only one request at a time (sequential protocol)
      if (this.pendingRequest) {
        reject(new Error("Embed server busy"));
        return;
      }

      const timer = setTimeout(() => {
        this.pendingRequest = null;
        reject(new Error(`Embed server request timed out after ${timeoutMs}ms`));
      }, timeoutMs);

      this.pendingRequest = { resolve, reject, timer };

      const line = JSON.stringify(request) + "\n";
      this.proc.stdin!.write(line);
    });
  }

  private handleLine(line: string): void {
    if (!this.pendingRequest) return;
    try {
      const msg = JSON.parse(line);
      const pending = this.pendingRequest;
      this.pendingRequest = null;
      clearTimeout(pending.timer);
      if (msg.error) {
        pending.reject(new Error(msg.error));
      } else {
        pending.resolve(msg);
      }
    } catch {
      // Ignore non-JSON lines
    }
  }
}

/** Singleton embed server manager instance. */
let _embedServerManager: EmbedServerManager | null = null;

/**
 * Get or create the singleton EmbedServerManager.
 */
export function getEmbedServerManager(opts?: RunnerOpts): EmbedServerManager {
  if (!_embedServerManager) {
    _embedServerManager = new EmbedServerManager(opts);
  }
  return _embedServerManager;
}

/**
 * Reset the singleton (for testing).
 */
export async function resetEmbedServerManager(): Promise<void> {
  if (_embedServerManager) {
    await _embedServerManager.stop();
    _embedServerManager = null;
  }
}
