/**
 * Agent tools: memory_search, memory_get, memory_write.
 *
 * These tools are the core of the palaia OpenClaw integration.
 * They shell out to the palaia CLI with --json and return results
 * in the format OpenClaw agents expect.
 */

import { Type } from "@sinclair/typebox";
import { run, runJson, getEmbedServerManager, type RunnerOpts } from "./runner.js";
import type { PalaiaPluginConfig } from "./config.js";
import { sanitizeScope, isValidScope } from "./hooks/index.js";
import { loadPriorities, resolvePriorities } from "./priorities.js";
import type { OpenClawPluginApi } from "./types.js";

/** Shape returned by `palaia query --json` */
interface QueryResult {
  results: Array<{
    id: string;
    content?: string;
    body?: string;
    score: number;
    tier: string;
    scope: string;
    title?: string;
    tags?: string[];
    path?: string;
    decay_score?: number;
  }>;
}

/** Shape returned by `palaia get --json` */
interface GetResult {
  id: string;
  content: string;
  meta: {
    scope: string;
    tier: string;
    title?: string;
    tags?: string[];
    [key: string]: unknown;
  };
}

/** Shape returned by `palaia write --json` */
interface WriteResult {
  id: string;
  tier: string;
  scope: string;
  deduplicated: boolean;
}

/**
 * Build RunnerOpts from plugin config.
 */
function buildRunnerOpts(config: PalaiaPluginConfig): RunnerOpts {
  return {
    binaryPath: config.binaryPath,
    workspace: config.workspace,
    timeoutMs: config.timeoutMs,
  };
}

/**
 * Register all palaia agent tools on the given plugin API.
 */
export function registerTools(api: OpenClawPluginApi, config: PalaiaPluginConfig): void {
  const opts = buildRunnerOpts(config);

  // ── memory_search ──────────────────────────────────────────────
  api.registerTool({
    name: "memory_search",
    description:
      "Semantically search palaia memory for relevant notes and context.",
    parameters: Type.Object({
      query: Type.String({ description: "Search query" }),
      maxResults: Type.Optional(
        Type.Number({ description: "Max results (default: 5)", default: 5 })
      ),
      tier: Type.Optional(
        Type.String({
          description: "hot|warm|all (default: hot+warm)",
        })
      ),
      type: Type.Optional(
        Type.String({
          description: "Filter by entry type: memory|process|task",
        })
      ),
    }),
    async execute(
      _id: string,
      params: {
        query: string;
        maxResults?: number;
        tier?: string;
        type?: string;
      }
    ) {
      // Load scope visibility from priorities (Issue #145: agent isolation)
      let scopeVisibility: string[] | null = null;
      try {
        const prio = await loadPriorities(config.workspace || "");
        const agentId = process.env.PALAIA_AGENT || undefined;
        const resolvedPrio = resolvePriorities(prio, {
          recallTypeWeight: config.recallTypeWeight,
          recallMinScore: config.recallMinScore,
          maxInjectedChars: config.maxInjectedChars,
          tier: config.tier,
        }, agentId);
        scopeVisibility = resolvedPrio.scopeVisibility;
      } catch {
        // Non-fatal: proceed without scope filtering
      }

      const limit = params.maxResults || config.maxResults || 5;
      const includeCold = params.tier === "all" || config.tier === "all";

      // Try embed server first — its queue correctly handles concurrent requests
      // without counting wait time against the timeout.
      let result: QueryResult | null = null;
      if (config.embeddingServer) {
        try {
          const mgr = getEmbedServerManager(opts);
          const resp = await mgr.query({
            text: params.query,
            top_k: limit,
            include_cold: includeCold,
            ...(params.type ? { type: params.type } : {}),
          }, config.timeoutMs || 3000);
          if (resp?.result?.results && Array.isArray(resp.result.results)) {
            result = { results: resp.result.results };
          }
        } catch {
          // Fall through to CLI
        }
      }

      // CLI fallback — longer timeout since it includes process spawn overhead
      if (!result) {
        const args: string[] = ["query", params.query, "--limit", String(limit)];
        if (includeCold) {
          args.push("--all");
        }
        if (params.type) {
          args.push("--type", params.type);
        }
        result = await runJson<QueryResult>(args, { ...opts, timeoutMs: 15000 });
      }

      // Apply scope visibility filter (Issue #145: agent isolation)
      let filteredResults = result.results || [];
      if (scopeVisibility) {
        filteredResults = filteredResults.filter((r) => {
          const scope = r.scope || "team";
          // Legacy shared:X entries are treated as team
          const effectiveScope = scope.startsWith("shared:") ? "team" : scope;
          return scopeVisibility!.includes(effectiveScope);
        });
      }

      // Format as memory_search compatible output
      const snippets = filteredResults.map((r) => {
        const body = r.content || r.body || "";
        const path = r.path || `${r.tier}/${r.id}.md`;
        return {
          text: body,
          path,
          score: r.score,
          tier: r.tier,
          scope: r.scope,
        };
      });

      // Build text output compatible with memory-core format
      const textParts = snippets.map(
        (s) =>
          `${s.text}\n— Source: ${s.path} (score: ${s.score}, tier: ${s.tier})`
      );
      const text =
        textParts.length > 0
          ? textParts.join("\n\n")
          : "No results found.";

      return {
        content: [{ type: "text" as const, text }],
      };
    },
  });

  // ── memory_get ─────────────────────────────────────────────────
  api.registerTool({
    name: "memory_get",
    description: "Read a specific palaia memory entry by path or id.",
    parameters: Type.Object({
      path: Type.String({ description: "Memory path or UUID" }),
      from: Type.Optional(
        Type.Number({ description: "Start from line number (1-indexed)" })
      ),
      lines: Type.Optional(
        Type.Number({ description: "Number of lines to return" })
      ),
    }),
    async execute(
      _id: string,
      params: { path: string; from?: number; lines?: number }
    ) {
      const args: string[] = ["get", params.path];
      if (params.from != null) {
        args.push("--from", String(params.from));
      }
      if (params.lines != null) {
        args.push("--lines", String(params.lines));
      }

      const result = await runJson<GetResult>(args, opts);

      return {
        content: [
          {
            type: "text" as const,
            text: result.content,
          },
        ],
      };
    },
  });

  // ── memory_write (optional, opt-in) ───────────────────────────
  api.registerTool(
    {
      name: "memory_write",
      description:
        "Write a new memory entry to palaia. WAL-backed, crash-safe.",
      parameters: Type.Object({
        content: Type.String({ description: "Memory content to write" }),
        scope: Type.Optional(
          Type.String({
            description: "Scope: private|team|public (default: team)",
            default: "team",
          })
        ),
        tags: Type.Optional(
          Type.Array(Type.String(), {
            description: "Tags for categorization",
          })
        ),
        type: Type.Optional(
          Type.String({
            description: "Entry type: memory|process|task (default: memory)",
          })
        ),
        project: Type.Optional(
          Type.String({
            description: "Project name to associate this entry with",
          })
        ),
        title: Type.Optional(
          Type.String({
            description: "Title for the entry",
          })
        ),
        force: Type.Optional(
          Type.Boolean({
            description: "Skip duplicate check and write anyway",
            default: false,
          })
        ),
      }),
      async execute(
        _id: string,
        params: {
          content: string;
          scope?: string;
          tags?: string[];
          type?: string;
          project?: string;
          title?: string;
          force?: boolean;
        }
      ) {
        // Duplicate guard: check for similar recent entries before writing
        if (!params.force) {
          try {
            const dupCheckResult = await runJson<QueryResult>(
              ["query", params.content, "--limit", "5"],
              { ...opts, timeoutMs: 2000 },
            );
            if (dupCheckResult && Array.isArray(dupCheckResult.results)) {
              const now = Date.now();
              const oneDayMs = 24 * 60 * 60 * 1000;
              for (const r of dupCheckResult.results) {
                if (r.score > 0.8) {
                  // Check if created in last 24h — use any available date field
                  const meta = r as any;
                  const createdStr = meta.created_at || meta.createdAt || meta.date || "";
                  if (createdStr) {
                    const createdTime = new Date(createdStr).getTime();
                    if (!isNaN(createdTime) && (now - createdTime) < oneDayMs) {
                      const title = r.title || (r.content || r.body || "").slice(0, 60);
                      const dateStr = new Date(createdTime).toISOString().split("T")[0];
                      return {
                        content: [
                          {
                            type: "text" as const,
                            text: `Similar entry already exists (score: ${r.score.toFixed(2)}, created: ${dateStr}): '${title}'. Use palaia edit ${r.id} to update, or confirm with --force to write anyway.`,
                          },
                        ],
                      };
                    }
                  }
                }
              }
            }
          } catch {
            // Duplicate check timed out or failed — proceed with write
          }
        }

        const args: string[] = ["write", params.content];
        if (params.scope) {
          if (!isValidScope(params.scope)) {
            return {
              content: [
                {
                  type: "text" as const,
                  text: `Invalid scope "${params.scope}". Valid scopes: private, team, public`,
                },
              ],
            };
          }
          args.push("--scope", sanitizeScope(params.scope));
        }
        if (params.tags && params.tags.length > 0) {
          args.push("--tags", params.tags.join(","));
        }
        if (params.type) {
          args.push("--type", params.type);
        }
        if (params.project) {
          args.push("--project", params.project);
        }
        if (params.title) {
          args.push("--title", params.title);
        }

        const result = await runJson<WriteResult>(args, opts);

        return {
          content: [
            {
              type: "text" as const,
              text: `Memory written: ${result.id} (tier: ${result.tier}, scope: ${result.scope})`,
            },
          ],
        };
      },
    },
    { optional: true }
  );
}
