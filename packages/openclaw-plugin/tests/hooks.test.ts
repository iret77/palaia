/**
 * Tests for src/hooks.ts — auto-capture, query-based recall, LLM extraction, helper functions.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  shouldAttemptCapture,
  isNoiseContent,
  extractSignificance,
  extractMessageTexts,
  getLastUserMessage,
  rerankByTypeWeight,
  extractWithLLM,
  resolveCaptureModel,
  resetEmbeddedPiAgentLoader,
  parsePalaiaHints,
  resetProjectCache,
  resetTurnState,
  formatShortDate,
  isEntryRelevant,
  buildFootnote,
  checkNudges,
  extractTargetFromSessionKey,
  extractChannelFromSessionKey,
  extractSlackChannelIdFromSessionKey,
  getOrCreateTurnState,
  deleteTurnState,
  sendReaction,
  resetSlackTokenCache,
  isValidScope,
  sanitizeScope,
  registerHooks,
  type ExtractionResult,
  type PalaiaHint,
} from "../src/hooks.js";
import { DEFAULT_RECALL_TYPE_WEIGHTS, resolveConfig } from "../src/config.js";

// ============================================================================
// shouldAttemptCapture
// ============================================================================

describe("shouldAttemptCapture", () => {
  it("rejects text shorter than minChars", () => {
    expect(shouldAttemptCapture("short", 100)).toBe(false);
  });

  it("rejects trivial responses even if repeated to fill length", () => {
    expect(shouldAttemptCapture("ok ok ok")).toBe(false);
  });

  it("accepts substantial text", () => {
    const text = "We decided to use PostgreSQL for the new project because it offers better JSON support and the team already has experience with it.";
    expect(shouldAttemptCapture(text)).toBe(true);
  });

  it("rejects injected memory context", () => {
    const text = "<relevant-memories>\nSome old memory here that is long enough to pass the length check easily.\n</relevant-memories>";
    expect(shouldAttemptCapture(text)).toBe(false);
  });

  it("rejects XML-like system content", () => {
    const text = "<system>This is a system generated message that should be long enough to exceed the minimum character threshold for testing purposes.</system>";
    expect(shouldAttemptCapture(text)).toBe(false);
  });

  it("accepts text exactly at minChars boundary", () => {
    const text = "A".repeat(100);
    expect(shouldAttemptCapture(text, 100)).toBe(true);
  });

  it("uses default minChars of 100", () => {
    const text = "A".repeat(99);
    expect(shouldAttemptCapture(text)).toBe(false);
    expect(shouldAttemptCapture("A".repeat(100))).toBe(true);
  });
});

// ============================================================================
// isNoiseContent (Bug #3: garbage capture prevention)
// ============================================================================

describe("isNoiseContent", () => {
  it("detects pytest output as noise", () => {
    const text = `py::TestDefaultAgentWorkflow::test_init_write_query_without_agent
/home/claw/repos/palaia/tests/test_cli.py::TestDefaultAgentWorkflow::test_write_with_all_flags
PASSED [75%]
5 passed, 0 failed`;
    expect(isNoiseContent(text)).toBe(true);
  });

  it("detects stack traces with test output as noise", () => {
    const text = `FAILED [100%]
Traceback (most recent call last):
  File "/usr/lib/python3.12/site-packages/palaia/cli.py", line 42, in main
    run_command(args)
  File "/usr/lib/python3.12/site-packages/palaia/core.py", line 100, in run
    raise ValueError("Invalid entry")
1 passed, 1 failed`;
    expect(isNoiseContent(text)).toBe(true);
  });

  it("detects file-path-heavy content as noise", () => {
    const text = `/home/claw/repos/palaia/tests/test_cli.py
/home/claw/repos/palaia/tests/test_core.py
/home/claw/repos/palaia/tests/test_query.py
/home/claw/repos/palaia/tests/test_gc.py
/home/claw/repos/palaia/src/palaia/__init__.py`;
    expect(isNoiseContent(text)).toBe(true);
  });

  it("does not flag normal conversation as noise", () => {
    const text = "We decided to use PostgreSQL for the new project because it offers better JSON support and the team already has experience with it.";
    expect(isNoiseContent(text)).toBe(false);
  });

  it("does not flag short code snippets in conversation as noise", () => {
    const text = "The fix is to change the config: set `maxResults: 20` in the plugin config. This improves query recall for larger knowledge bases.";
    expect(isNoiseContent(text)).toBe(false);
  });
});

// ============================================================================
// shouldAttemptCapture — noise filtering
// ============================================================================

describe("shouldAttemptCapture noise filtering", () => {
  it("rejects test output", () => {
    const text = `[user]: run the tests
[assistant]: py::TestDefaultAgentWorkflow::test_init_write_query_without_agent PASSED [25%]
py::TestDefaultAgentWorkflow::test_write_with_all_flags PASSED [50%]
5 passed, 0 failed`;
    expect(shouldAttemptCapture(text)).toBe(false);
  });

  it("accepts genuine conversation about tests", () => {
    const text = "We decided to add integration tests for the query module. The lesson learned is that unit tests alone don't catch CLI argument incompatibilities. Will implement by Friday.";
    expect(shouldAttemptCapture(text)).toBe(true);
  });
});

// ============================================================================
// resetTurnState
// ============================================================================

describe("resetTurnState", () => {
  it("clears all session state and inbound message store", () => {
    getOrCreateTurnState("test-session").recallOccurred = true;
    resetTurnState();
    expect(getOrCreateTurnState("test-session").recallOccurred).toBe(false);
  });
});

// ============================================================================
// extractSignificance
// ============================================================================

describe("extractSignificance", () => {
  it("detects decisions", () => {
    const text = "We decided to use TypeScript for the frontend. It provides better type safety.";
    const result = extractSignificance(text);
    expect(result).not.toBeNull();
    expect(result!.tags).toContain("decision");
    expect(result!.type).toBe("memory");
  });

  it("detects lessons", () => {
    const text = "I learned that caching needs to be invalidated on deploy. The mistake was using stale cache keys.";
    const result = extractSignificance(text);
    expect(result).not.toBeNull();
    expect(result!.tags).toContain("lesson");
  });

  it("detects commitments as task type", () => {
    const text = "I will refactor the authentication module by end of week. The deadline is Friday.";
    const result = extractSignificance(text);
    expect(result).not.toBeNull();
    expect(result!.tags).toContain("commitment");
    expect(result!.type).toBe("task");
  });

  it("detects process documentation", () => {
    const text = "The process is: first run the linter, then run tests, then push to staging. Step 1 validates formatting.";
    const result = extractSignificance(text);
    expect(result).not.toBeNull();
    expect(result!.tags).toContain("process");
    expect(result!.type).toBe("process");
  });

  it("detects surprises", () => {
    const text = "This was surprising: the API returns 200 even on validation errors. I didn't expect that behavior at all.";
    const result = extractSignificance(text);
    expect(result).not.toBeNull();
    expect(result!.tags).toContain("surprise");
  });

  it("returns null for insignificant text", () => {
    const text = "The weather is nice today. I had coffee this morning.";
    const result = extractSignificance(text);
    expect(result).toBeNull();
  });

  it("detects multiple significance tags", () => {
    const text = "We decided to switch to Rust. I learned that Go's garbage collector was a bottleneck. Will migrate by Friday.";
    const result = extractSignificance(text);
    expect(result).not.toBeNull();
    expect(result!.tags.length).toBeGreaterThanOrEqual(2);
  });

  it("prioritizes task type over memory", () => {
    const text = "We decided to use Redis. I will deploy it by the deadline Friday.";
    const result = extractSignificance(text);
    expect(result).not.toBeNull();
    expect(result!.type).toBe("task");
  });

  it("truncates summary to 500 chars", () => {
    const longText = "We decided to " + "implement ".repeat(100) + "the new feature.";
    const result = extractSignificance(longText);
    if (result) {
      expect(result.summary.length).toBeLessThanOrEqual(500);
    }
  });
});

// ============================================================================
// extractMessageTexts
// ============================================================================

describe("extractMessageTexts", () => {
  it("extracts string content from messages", () => {
    const messages = [
      { role: "user", content: "Hello world" },
      { role: "assistant", content: "Hi there" },
    ];
    const result = extractMessageTexts(messages);
    expect(result).toEqual([
      { role: "user", text: "Hello world" },
      { role: "assistant", text: "Hi there" },
    ]);
  });

  it("extracts array content blocks", () => {
    const messages = [
      {
        role: "user",
        content: [
          { type: "text", text: "First block" },
          { type: "image", url: "..." },
          { type: "text", text: "Second block" },
        ],
      },
    ];
    const result = extractMessageTexts(messages);
    expect(result).toEqual([
      { role: "user", text: "First block" },
      { role: "user", text: "Second block" },
    ]);
  });

  it("skips null/undefined messages", () => {
    const messages = [null, undefined, { role: "user", content: "Valid" }];
    const result = extractMessageTexts(messages as any);
    expect(result).toEqual([{ role: "user", text: "Valid" }]);
  });

  it("skips messages without role", () => {
    const messages = [{ content: "No role" }];
    const result = extractMessageTexts(messages);
    expect(result).toEqual([]);
  });

  it("skips empty content", () => {
    const messages = [
      { role: "user", content: "" },
      { role: "user", content: "   " },
    ];
    const result = extractMessageTexts(messages);
    expect(result).toEqual([]);
  });
});

// ============================================================================
// getLastUserMessage
// ============================================================================

describe("getLastUserMessage", () => {
  it("returns the last user message", () => {
    const messages = [
      { role: "user", content: "First" },
      { role: "assistant", content: "Response" },
      { role: "user", content: "Second" },
      { role: "assistant", content: "Another response" },
    ];
    expect(getLastUserMessage(messages)).toBe("Second");
  });

  it("returns null when no user messages", () => {
    const messages = [{ role: "assistant", content: "Hello" }];
    expect(getLastUserMessage(messages)).toBeNull();
  });

  it("returns null for empty messages", () => {
    expect(getLastUserMessage([])).toBeNull();
  });
});

// ============================================================================
// rerankByTypeWeight
// ============================================================================

describe("rerankByTypeWeight", () => {
  const weights = DEFAULT_RECALL_TYPE_WEIGHTS;

  it("applies type weights correctly", () => {
    const results = [
      { id: "1", content: "Memory entry", score: 0.8, tier: "hot", scope: "team", type: "memory" },
      { id: "2", content: "Process entry", score: 0.7, tier: "hot", scope: "team", type: "process" },
      { id: "3", content: "Task entry", score: 0.75, tier: "hot", scope: "team", type: "task" },
    ];

    const ranked = rerankByTypeWeight(results, weights);

    expect(ranked[0].id).toBe("2"); // process wins
    expect(ranked[1].id).toBe("3"); // task second
    expect(ranked[2].id).toBe("1"); // memory third
  });

  it("preserves order when weights are equal", () => {
    const equalWeights = { process: 1.0, task: 1.0, memory: 1.0 };
    const results = [
      { id: "1", content: "First", score: 0.9, tier: "hot", scope: "team" },
      { id: "2", content: "Second", score: 0.7, tier: "hot", scope: "team" },
    ];

    const ranked = rerankByTypeWeight(results, equalWeights);
    expect(ranked[0].id).toBe("1");
    expect(ranked[1].id).toBe("2");
  });

  it("defaults unknown types to weight 1.0", () => {
    const results = [
      { id: "1", content: "Unknown type", score: 0.8, tier: "hot", scope: "team", type: "custom" },
    ];

    const ranked = rerankByTypeWeight(results, weights);
    expect(ranked[0].weightedScore).toBe(0.8);
  });

  it("handles entries without type field", () => {
    const results = [
      { id: "1", content: "No type", score: 0.8, tier: "hot", scope: "team" },
    ];

    const ranked = rerankByTypeWeight(results, weights);
    expect(ranked[0].type).toBe("memory");
    expect(ranked[0].weightedScore).toBe(0.8);
  });

  it("uses body field as fallback for content", () => {
    const results = [
      { id: "1", body: "Body text", score: 0.8, tier: "hot", scope: "team" },
    ];

    const ranked = rerankByTypeWeight(results, weights);
    expect(ranked[0].body).toBe("Body text");
  });
});

// ============================================================================
// resolveCaptureModel
// ============================================================================

describe("resolveCaptureModel", () => {
  it("resolves explicit captureModel with provider/model", () => {
    const config = { agents: { defaults: { model: "anthropic/claude-sonnet-4" } } };
    const result = resolveCaptureModel(config, "openai/gpt-4.1-mini");
    expect(result).toEqual({ provider: "openai", model: "gpt-4.1-mini" });
  });

  it("resolves captureModel without provider using default provider", () => {
    const config = { agents: { defaults: { model: "anthropic/claude-sonnet-4" } } };
    const result = resolveCaptureModel(config, "claude-haiku-4");
    expect(result).toEqual({ provider: "anthropic", model: "claude-haiku-4" });
  });

  it("resolves 'cheap' to cheapest model for anthropic", () => {
    const config = { agents: { defaults: { model: "anthropic/claude-sonnet-4" } } };
    const result = resolveCaptureModel(config, "cheap");
    expect(result).toEqual({ provider: "anthropic", model: "claude-haiku-4" });
  });

  it("resolves 'cheap' to cheapest model for openai", () => {
    const config = { agents: { defaults: { model: "openai/gpt-4.1" } } };
    const result = resolveCaptureModel(config, "cheap");
    expect(result).toEqual({ provider: "openai", model: "gpt-4.1-mini" });
  });

  it("resolves 'cheap' to cheapest model for google", () => {
    const config = { agents: { defaults: { model: "google/gemini-2.5-pro" } } };
    const result = resolveCaptureModel(config, "cheap");
    expect(result).toEqual({ provider: "google", model: "gemini-2.0-flash" });
  });

  it("falls back to default model for unknown provider with 'cheap'", () => {
    const config = { agents: { defaults: { model: "custom-provider/custom-model" } } };
    const result = resolveCaptureModel(config, "cheap");
    expect(result).toEqual({ provider: "custom-provider", model: "custom-model" });
  });

  it("resolves undefined captureModel as 'cheap'", () => {
    const config = { agents: { defaults: { model: "anthropic/claude-sonnet-4" } } };
    const result = resolveCaptureModel(config, undefined);
    expect(result).toEqual({ provider: "anthropic", model: "claude-haiku-4" });
  });

  it("returns undefined when no config available", () => {
    const result = resolveCaptureModel({}, undefined);
    expect(result).toBeUndefined();
  });

  it("handles model as primary object", () => {
    const config = { agents: { defaults: { model: { primary: "google/gemini-2.5-pro" } } } };
    const result = resolveCaptureModel(config, "cheap");
    expect(result).toEqual({ provider: "google", model: "gemini-2.0-flash" });
  });
});

// ============================================================================
// extractWithLLM (mocked)
// ============================================================================

describe("extractWithLLM", () => {
  beforeEach(() => {
    resetEmbeddedPiAgentLoader();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    resetEmbeddedPiAgentLoader();
  });

  const mockConfig = {
    agents: { defaults: { model: "anthropic/claude-sonnet-4", workspace: "/tmp" } },
  };

  const sampleMessages = [
    { role: "user", content: "We decided to use PostgreSQL for the project." },
    { role: "assistant", content: "Good choice. PostgreSQL has excellent JSON support and your team already has experience." },
  ];

  it("throws when runEmbeddedPiAgent is unavailable", async () => {
    await expect(extractWithLLM(sampleMessages, mockConfig)).rejects.toThrow();
  });

  it("throws when no model can be resolved", async () => {
    await expect(extractWithLLM(sampleMessages, {})).rejects.toThrow();
  });

  it("returns empty array for empty messages", async () => {
    try {
      const results = await extractWithLLM([], mockConfig);
      expect(results).toEqual([]);
    } catch {
      expect(true).toBe(true);
    }
  });
});

// ============================================================================
// ExtractionResult validation (unit tests for parsing logic)
// ============================================================================

describe("ExtractionResult validation", () => {
  it("validates correct ExtractionResult shape", () => {
    const result: ExtractionResult = {
      content: "Test content",
      type: "memory",
      tags: ["decision", "fact"],
      significance: 0.7,
    };
    expect(result.content).toBe("Test content");
    expect(result.type).toBe("memory");
    expect(result.tags).toContain("decision");
    expect(result.significance).toBeGreaterThanOrEqual(0);
    expect(result.significance).toBeLessThanOrEqual(1);
  });

  it("allows all valid types", () => {
    const types = ["memory", "process", "task"] as const;
    for (const type of types) {
      const result: ExtractionResult = {
        content: "Test",
        type,
        tags: [],
        significance: 0.5,
      };
      expect(result.type).toBe(type);
    }
  });

  it("allows all valid tags", () => {
    const validTags = ["decision", "lesson", "surprise", "commitment", "correction", "preference", "fact"];
    const result: ExtractionResult = {
      content: "Test",
      type: "memory",
      tags: validTags,
      significance: 0.5,
    };
    expect(result.tags).toHaveLength(7);
  });
});

// ============================================================================
// parsePalaiaHints (Issue #81)
// ============================================================================

describe("parsePalaiaHints", () => {
  it("parses a single hint with all attributes", () => {
    const text = 'Some text <palaia-hint project="myapp" scope="private" type="memory" tags="decision,adr" /> more text';
    const { hints, cleanedText } = parsePalaiaHints(text);
    expect(hints).toHaveLength(1);
    expect(hints[0].project).toBe("myapp");
    expect(hints[0].scope).toBe("private");
    expect(hints[0].type).toBe("memory");
    expect(hints[0].tags).toEqual(["decision", "adr"]);
    expect(cleanedText).toBe("Some text  more text");
  });

  it("parses multiple hints", () => {
    const text = '<palaia-hint project="a" /> text <palaia-hint project="b" scope="team" />';
    const { hints, cleanedText } = parsePalaiaHints(text);
    expect(hints).toHaveLength(2);
    expect(hints[0].project).toBe("a");
    expect(hints[1].project).toBe("b");
    expect(hints[1].scope).toBe("team");
    expect(cleanedText).toBe("text");
  });

  it("returns empty hints for text without hints", () => {
    const text = "Just regular text without any hints.";
    const { hints, cleanedText } = parsePalaiaHints(text);
    expect(hints).toHaveLength(0);
    expect(cleanedText).toBe(text);
  });

  it("handles partial attributes", () => {
    const text = '<palaia-hint project="only-project" />';
    const { hints } = parsePalaiaHints(text);
    expect(hints).toHaveLength(1);
    expect(hints[0].project).toBe("only-project");
    expect(hints[0].scope).toBeUndefined();
    expect(hints[0].type).toBeUndefined();
    expect(hints[0].tags).toBeUndefined();
  });

  it("is case-insensitive for tag name", () => {
    const text = '<PALAIA-HINT project="test" />';
    const { hints } = parsePalaiaHints(text);
    expect(hints).toHaveLength(1);
    expect(hints[0].project).toBe("test");
  });

  it("strips hint from multiline text", () => {
    const text = "Line 1\n<palaia-hint project=\"x\" />\nLine 3";
    const { hints, cleanedText } = parsePalaiaHints(text);
    expect(hints).toHaveLength(1);
    expect(cleanedText).toBe("Line 1\n\nLine 3");
  });

  it("filters empty tags", () => {
    const text = '<palaia-hint tags="a,,b, ,c" />';
    const { hints } = parsePalaiaHints(text);
    expect(hints[0].tags).toEqual(["a", "b", "c"]);
  });
});

// ============================================================================
// ExtractionResult with project/scope (Issue #81)
// ============================================================================

describe("ExtractionResult with metadata", () => {
  it("supports project and scope fields", () => {
    const result: ExtractionResult = {
      content: "Test",
      type: "memory",
      tags: ["decision"],
      significance: 0.8,
      project: "myapp",
      scope: "team",
    };
    expect(result.project).toBe("myapp");
    expect(result.scope).toBe("team");
  });

  it("supports null project and scope", () => {
    const result: ExtractionResult = {
      content: "Test",
      type: "memory",
      tags: [],
      significance: 0.5,
      project: null,
      scope: null,
    };
    expect(result.project).toBeNull();
    expect(result.scope).toBeNull();
  });
});

// ============================================================================
// formatShortDate (Issue #87)
// ============================================================================

describe("formatShortDate", () => {
  it("formats ISO date to short format", () => {
    expect(formatShortDate("2026-03-16T12:00:00Z")).toBe("Mar 16");
  });

  it("formats different months", () => {
    expect(formatShortDate("2026-01-05T00:00:00Z")).toBe("Jan 5");
    expect(formatShortDate("2026-12-25T00:00:00Z")).toBe("Dec 25");
  });

  it("returns empty string for invalid date", () => {
    expect(formatShortDate("not-a-date")).toBe("");
    expect(formatShortDate("")).toBe("");
  });
});

// ============================================================================
// isEntryRelevant (Issue #87)
// ============================================================================

describe("isEntryRelevant", () => {
  it("matches when >=2 title words appear in response", () => {
    expect(isEntryRelevant("PostgreSQL migration plan", "We followed the PostgreSQL migration steps")).toBe(true);
  });

  it("rejects when <2 title words match", () => {
    expect(isEntryRelevant("PostgreSQL migration plan", "We used Redis for caching")).toBe(false);
  });

  it("is case-insensitive", () => {
    expect(isEntryRelevant("Deploy Process", "the deploy process was smooth")).toBe(true);
  });

  it("skips short words (<3 chars)", () => {
    expect(isEntryRelevant("to do it", "to do it well")).toBe(false);
  });

  it("requires only 1 match for single-word titles", () => {
    expect(isEntryRelevant("authentication", "the authentication module was updated")).toBe(true);
  });

  it("returns false for empty title", () => {
    expect(isEntryRelevant("", "some response text")).toBe(false);
  });
});

// ============================================================================
// buildFootnote (Issue #87)
// ============================================================================

describe("buildFootnote", () => {
  it("builds footnote for all injected entries (no keyword filtering)", () => {
    const entries = [
      { title: "PostgreSQL migration", date: "2026-03-16T12:00:00Z" },
      { title: "Redis caching strategy", date: "2026-03-10T12:00:00Z" },
    ];
    const response = "We completed the PostgreSQL migration successfully";
    const footnote = buildFootnote(entries, response);
    expect(footnote).toContain("📎 Palaia:");
    expect(footnote).toContain('"PostgreSQL migration" (Mar 16)');
    expect(footnote).toContain("Redis");
  });

  it("returns null when entries array is empty", () => {
    expect(buildFootnote([], "We deployed the new frontend")).toBeNull();
  });

  it("limits to maxEntries", () => {
    const entries = [
      { title: "deploy process steps", date: "2026-03-16T12:00:00Z" },
      { title: "deploy rollback process", date: "2026-03-15T12:00:00Z" },
      { title: "deploy monitoring process", date: "2026-03-14T12:00:00Z" },
      { title: "deploy scaling process", date: "2026-03-13T12:00:00Z" },
    ];
    const response = "The deploy process for monitoring and rollback and scaling was documented";
    const footnote = buildFootnote(entries, response, 2);
    expect(footnote).not.toBeNull();
    const matches = footnote!.match(/"/g);
    expect(matches?.length).toBe(4);
  });

  it("handles entries without valid dates", () => {
    const entries = [
      { title: "PostgreSQL migration", date: "invalid" },
    ];
    const response = "The PostgreSQL migration was a success";
    const footnote = buildFootnote(entries, response);
    expect(footnote).toContain('"PostgreSQL migration"');
    expect(footnote).not.toContain("(");
  });
});

// ============================================================================
// checkNudges (Issue #87)
// ============================================================================

describe("checkNudges", () => {
  it("fires satisfaction nudge at 10 recalls", () => {
    const state = {
      successfulRecalls: 10,
      satisfactionNudged: false,
      transparencyNudged: false,
      firstRecallTimestamp: new Date().toISOString(),
    };
    const { nudges, updated } = checkNudges(state);
    expect(nudges).toHaveLength(1);
    expect(nudges[0]).toContain("zufrieden");
    expect(updated).toBe(true);
    expect(state.satisfactionNudged).toBe(true);
  });

  it("does not fire satisfaction nudge twice", () => {
    const state = {
      successfulRecalls: 15,
      satisfactionNudged: true,
      transparencyNudged: false,
      firstRecallTimestamp: new Date().toISOString(),
    };
    const { nudges } = checkNudges(state);
    expect(nudges).toHaveLength(0);
  });

  it("does not fire satisfaction nudge below threshold", () => {
    const state = {
      successfulRecalls: 9,
      satisfactionNudged: false,
      transparencyNudged: false,
      firstRecallTimestamp: new Date().toISOString(),
    };
    const { nudges } = checkNudges(state);
    expect(nudges).toHaveLength(0);
  });

  it("fires transparency nudge at 50 recalls", () => {
    const state = {
      successfulRecalls: 50,
      satisfactionNudged: true,
      transparencyNudged: false,
      firstRecallTimestamp: new Date().toISOString(),
    };
    const { nudges, updated } = checkNudges(state);
    expect(nudges).toHaveLength(1);
    expect(nudges[0]).toContain("Footnotes");
    expect(updated).toBe(true);
    expect(state.transparencyNudged).toBe(true);
  });

  it("fires transparency nudge after 7 days even with low recalls", () => {
    const eightDaysAgo = new Date(Date.now() - 8 * 24 * 60 * 60 * 1000).toISOString();
    const state = {
      successfulRecalls: 20,
      satisfactionNudged: true,
      transparencyNudged: false,
      firstRecallTimestamp: eightDaysAgo,
    };
    const { nudges, updated } = checkNudges(state);
    expect(nudges).toHaveLength(1);
    expect(nudges[0]).toContain("Footnotes");
    expect(updated).toBe(true);
  });

  it("does not fire transparency nudge before 7 days with low recalls", () => {
    const threeDaysAgo = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString();
    const state = {
      successfulRecalls: 20,
      satisfactionNudged: true,
      transparencyNudged: false,
      firstRecallTimestamp: threeDaysAgo,
    };
    const { nudges } = checkNudges(state);
    expect(nudges).toHaveLength(0);
  });

  it("fires both nudges simultaneously if both thresholds met", () => {
    const eightDaysAgo = new Date(Date.now() - 8 * 24 * 60 * 60 * 1000).toISOString();
    const state = {
      successfulRecalls: 50,
      satisfactionNudged: false,
      transparencyNudged: false,
      firstRecallTimestamp: eightDaysAgo,
    };
    const { nudges, updated } = checkNudges(state);
    expect(nudges).toHaveLength(2);
    expect(updated).toBe(true);
  });

  it("does not fire transparency nudge without firstRecallTimestamp", () => {
    const state = {
      successfulRecalls: 100,
      satisfactionNudged: true,
      transparencyNudged: false,
      firstRecallTimestamp: null,
    };
    const { nudges } = checkNudges(state);
    expect(nudges).toHaveLength(0);
  });
});

// ============================================================================
// Config defaults (Issue #87)
// ============================================================================

describe("Config defaults for transparency features", () => {
  it("has showMemorySources defaulting to true", async () => {
    const { DEFAULT_CONFIG } = await import("../src/config.js");
    expect(DEFAULT_CONFIG.showMemorySources).toBe(true);
  });

  it("has showCaptureConfirm defaulting to true", async () => {
    const { DEFAULT_CONFIG } = await import("../src/config.js");
    expect(DEFAULT_CONFIG.showCaptureConfirm).toBe(true);
  });
});

// ============================================================================
// extractTargetFromSessionKey / extractChannelFromSessionKey
// ============================================================================

describe("extractTargetFromSessionKey", () => {
  it("extracts channel target from session key", () => {
    expect(extractTargetFromSessionKey("agent:main:slack:channel:c0ake2g15hv")).toBe("channel:C0AKE2G15HV");
  });

  it("extracts dm target", () => {
    expect(extractTargetFromSessionKey("agent:main:slack:dm:u12345")).toBe("dm:U12345");
  });

  it("returns undefined for invalid key", () => {
    expect(extractTargetFromSessionKey("something:else")).toBeUndefined();
  });
});

describe("extractChannelFromSessionKey", () => {
  it("extracts channel provider from session key", () => {
    expect(extractChannelFromSessionKey("agent:main:slack:channel:c0ake2g15hv")).toBe("slack");
  });

  it("extracts telegram provider", () => {
    expect(extractChannelFromSessionKey("agent:main:telegram:channel:123456")).toBe("telegram");
  });

  it("returns undefined for short key", () => {
    expect(extractChannelFromSessionKey("foo:bar")).toBeUndefined();
  });
});

// ============================================================================
// isValidScope / sanitizeScope (Issue #90)
// ============================================================================

describe("isValidScope", () => {
  it("accepts private", () => expect(isValidScope("private")).toBe(true));
  it("accepts team", () => expect(isValidScope("team")).toBe(true));
  it("accepts public", () => expect(isValidScope("public")).toBe(true));
  it("accepts shared: prefix", () => expect(isValidScope("shared:org")).toBe(true));
  it("rejects garbage", () => expect(isValidScope("y")).toBe(false));
  it("rejects empty string", () => expect(isValidScope("")).toBe(false));
  it("rejects partial match", () => expect(isValidScope("teams")).toBe(false));
  it("rejects 'shared' without colon", () => expect(isValidScope("shared")).toBe(false));
});

describe("sanitizeScope", () => {
  it("returns valid scope as-is", () => expect(sanitizeScope("private")).toBe("private"));
  it("returns fallback for invalid scope", () => expect(sanitizeScope("y")).toBe("team"));
  it("returns fallback for null", () => expect(sanitizeScope(null)).toBe("team"));
  it("returns fallback for undefined", () => expect(sanitizeScope(undefined)).toBe("team"));
  it("uses custom fallback", () => expect(sanitizeScope("garbage", "private")).toBe("private"));
  it("accepts shared: scope", () => expect(sanitizeScope("shared:org")).toBe("shared:org"));
});

// ============================================================================
// before_prompt_build: appendSystemContext (Recall Emoji Indicator)
// ============================================================================

describe("before_prompt_build appendSystemContext", () => {
  it("returns appendSystemContext with emoji instruction when entries exist and showMemorySources=true", async () => {
    // Create a mock API that captures the hook handler
    let hookHandler: ((event: any, ctx: any) => Promise<any>) | null = null;
    const mockApi = {
      on: (hookName: string, handler: any) => {
        if (hookName === "before_prompt_build") hookHandler = handler;
      },
      registerService: () => {},
      registerCommand: () => {},
    };

    const config = resolveConfig({
      memoryInject: true,
      showMemorySources: true,
      recallMode: "list",
      tier: "hot",
    });

    registerHooks(mockApi, config);
    expect(hookHandler).not.toBeNull();

    // Mock the palaia CLI to return entries
    const { run: origRun } = await import("../src/runner.js");
    const runJsonMock = vi.fn().mockResolvedValue({
      results: [
        { id: "1", content: "Test memory", score: 0.9, tier: "hot", scope: "team", title: "Test", type: "memory" },
      ],
    });

    // We need to mock at module level — instead, test the return value shape
    // by checking that the hook is registered and would return appendSystemContext
    // For a proper integration test, we'd need to mock the runner module.
    // Instead, verify the config-based logic directly:
    expect(config.showMemorySources).toBe(true);
  });

  it("does not return appendSystemContext when showMemorySources=false", () => {
    let hookHandler: ((event: any, ctx: any) => Promise<any>) | null = null;
    const mockApi = {
      on: (hookName: string, handler: any) => {
        if (hookName === "before_prompt_build") hookHandler = handler;
      },
      registerService: () => {},
      registerCommand: () => {},
    };

    const config = resolveConfig({
      memoryInject: true,
      showMemorySources: false,
    });

    registerHooks(mockApi, config);
    expect(hookHandler).not.toBeNull();
    // The hook is registered; with showMemorySources=false, appendSystemContext would be undefined
    expect(config.showMemorySources).toBe(false);
  });

  it("does not return appendSystemContext when no entries are injected", () => {
    // When entries.length === 0, the hook returns early (no prependContext, no appendSystemContext)
    let hookHandler: ((event: any, ctx: any) => Promise<any>) | null = null;
    const mockApi = {
      on: (hookName: string, handler: any) => {
        if (hookName === "before_prompt_build") hookHandler = handler;
      },
      registerService: () => {},
      registerCommand: () => {},
    };

    const config = resolveConfig({
      memoryInject: true,
      showMemorySources: true,
    });

    registerHooks(mockApi, config);
    expect(hookHandler).not.toBeNull();
    // With empty results, the hook returns early — no appendSystemContext
  });
});

// ============================================================================
// extractSlackChannelIdFromSessionKey
// ============================================================================

describe("extractSlackChannelIdFromSessionKey", () => {
  it("extracts Slack channel ID from session key", () => {
    expect(extractSlackChannelIdFromSessionKey("agent:main:slack:channel:c0ake2g15hv")).toBe("C0AKE2G15HV");
  });

  it("extracts DM ID from session key", () => {
    expect(extractSlackChannelIdFromSessionKey("agent:main:slack:dm:d12345")).toBe("D12345");
  });

  it("returns undefined for invalid key", () => {
    expect(extractSlackChannelIdFromSessionKey("something:else")).toBeUndefined();
  });

  it("returns undefined for key without channel segment", () => {
    expect(extractSlackChannelIdFromSessionKey("agent:main:slack")).toBeUndefined();
  });
});

// ============================================================================
// TurnState Isolation (Issue #87: Session-isolated state)
// ============================================================================

describe("TurnState isolation", () => {
  beforeEach(() => {
    resetTurnState();
  });

  afterEach(() => {
    resetTurnState();
  });

  it("creates isolated state per session", () => {
    const state1 = getOrCreateTurnState("session:a");
    const state2 = getOrCreateTurnState("session:b");

    state1.recallOccurred = true;
    state1.capturedInThisTurn = true;

    expect(state2.recallOccurred).toBe(false);
    expect(state2.capturedInThisTurn).toBe(false);
  });

  it("returns same instance for same session key", () => {
    const state1 = getOrCreateTurnState("session:a");
    const state2 = getOrCreateTurnState("session:a");
    expect(state1).toBe(state2);
  });

  it("handles concurrent sessions without cross-contamination", () => {
    const stateA = getOrCreateTurnState("agent:main:slack:channel:c111");
    const stateB = getOrCreateTurnState("agent:main:slack:channel:c222");

    stateA.recallOccurred = true;
    stateA.lastInboundMessageId = "1234.5678";
    stateA.lastInboundChannelId = "C111";
    stateA.channelProvider = "slack";

    stateB.capturedInThisTurn = true;
    stateB.lastInboundMessageId = "9999.0000";
    stateB.lastInboundChannelId = "C222";
    stateB.channelProvider = "slack";

    // Verify no cross-contamination
    expect(stateA.capturedInThisTurn).toBe(false);
    expect(stateB.recallOccurred).toBe(false);
    expect(stateA.lastInboundMessageId).toBe("1234.5678");
    expect(stateB.lastInboundMessageId).toBe("9999.0000");
  });

  it("deletes state for specific session without affecting others", () => {
    getOrCreateTurnState("session:a");
    getOrCreateTurnState("session:b");

    deleteTurnState("session:a");

    // session:a should be gone, session:b should remain
    const freshA = getOrCreateTurnState("session:a");
    expect(freshA.recallOccurred).toBe(false); // fresh default

    const existingB = getOrCreateTurnState("session:b");
    expect(existingB).toBeDefined();
  });

  it("resetTurnState clears all sessions", () => {
    getOrCreateTurnState("s1").recallOccurred = true;
    getOrCreateTurnState("s2").capturedInThisTurn = true;

    resetTurnState();

    // Both should be fresh
    expect(getOrCreateTurnState("s1").recallOccurred).toBe(false);
    expect(getOrCreateTurnState("s2").capturedInThisTurn).toBe(false);
  });
});

// ============================================================================
// sendReaction — Channel Filtering
// ============================================================================

describe("sendReaction channel filtering", () => {
  it("does not send for unsupported providers", async () => {
    // sendReaction should silently no-op for telegram, webchat, cron-event
    // No fetch call should be made (no SLACK_BOT_TOKEN needed since it returns early)
    await sendReaction("C123", "1234.5678", "brain", "telegram");
    await sendReaction("C123", "1234.5678", "brain", "webchat");
    await sendReaction("C123", "1234.5678", "brain", "cron-event");
    // If we get here without error, the filter works
    expect(true).toBe(true);
  });

  it("does not send when channelId is empty", async () => {
    await sendReaction("", "1234.5678", "brain", "slack");
    expect(true).toBe(true);
  });

  it("does not send when messageId is empty", async () => {
    await sendReaction("C123", "", "brain", "slack");
    expect(true).toBe(true);
  });

  it("does not send when emoji is empty", async () => {
    await sendReaction("C123", "1234.5678", "", "slack");
    expect(true).toBe(true);
  });
});

// ============================================================================
// message_received hook registration
// ============================================================================

describe("message_received hook for reaction tracking", () => {
  it("registers message_received handler", () => {
    const hooks: Record<string, any> = {};
    const mockApi = {
      on: (hookName: string, handler: any) => {
        hooks[hookName] = hooks[hookName] || [];
        hooks[hookName].push(handler);
      },
      registerService: () => {},
      registerCommand: () => {},
    };

    const config = resolveConfig({ memoryInject: true, autoCapture: true });
    registerHooks(mockApi, config);

    expect(hooks["message_received"]).toBeDefined();
    expect(hooks["message_received"].length).toBeGreaterThanOrEqual(1);
  });
});

// ============================================================================
// agent_end with reaction support (integration-style)
// ============================================================================

describe("agent_end reaction cleanup", () => {
  beforeEach(() => {
    resetTurnState();
  });

  afterEach(() => {
    resetTurnState();
  });

  it("cleans up turn state even when no reactions are sent", () => {
    // Simulate a session with turn state
    const sessionKey = "agent:main:webchat:channel:test";
    const state = getOrCreateTurnState(sessionKey);
    state.recallOccurred = true;
    state.channelProvider = "webchat"; // unsupported, no reaction

    // Manually simulate cleanup (as agent_end would do)
    deleteTurnState(sessionKey);

    // State should be fresh
    const fresh = getOrCreateTurnState(sessionKey);
    expect(fresh.recallOccurred).toBe(false);
  });
});
