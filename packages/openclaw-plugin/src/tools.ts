/**
 * Agent tools: memory_search, memory_get, memory_write.
 *
 * These tools are the core of the Palaia OpenClaw integration.
 * They shell out to the palaia CLI with --json and return results
 * in the format OpenClaw agents expect.
 */

import { Type } from "@sinclair/typebox";
import { runJson, type RunnerOpts } from "./runner.js";
import type { PalaiaPluginConfig } from "./config.js";

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
 * Register all Palaia agent tools on the given plugin API.
 */
export function registerTools(api: any, config: PalaiaPluginConfig): void {
  const opts = buildRunnerOpts(config);

  // ── memory_search ──────────────────────────────────────────────
  api.registerTool({
    name: "memory_search",
    description:
      "Semantically search Palaia memory for relevant notes and context.",
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
      scope: Type.Optional(
        Type.String({
          description: "Filter by scope: private|team|shared:X|public",
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
        scope?: string;
        type?: string;
      }
    ) {
      const limit = params.maxResults || config.maxResults || 5;
      const args: string[] = ["query", params.query, "--limit", String(limit)];

      // --all flag includes cold tier
      if (params.tier === "all" || config.tier === "all") {
        args.push("--all");
      }

      // Type filter (Issue #82)
      if (params.type) {
        args.push("--type", params.type);
      }

      const result = await runJson<QueryResult>(args, opts);

      // Format as memory_search compatible output
      const snippets = (result.results || []).map((r) => {
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
    description: "Read a specific Palaia memory entry by path or id.",
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
        "Write a new memory entry to Palaia. WAL-backed, crash-safe.",
      parameters: Type.Object({
        content: Type.String({ description: "Memory content to write" }),
        scope: Type.Optional(
          Type.String({
            description: "Scope: private|team|shared:X|public (default: team)",
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
        }
      ) {
        const args: string[] = ["write", params.content];
        if (params.scope) {
          args.push("--scope", params.scope);
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
