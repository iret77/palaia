/**
 * Tests for src/hooks.ts — auto-capture, query-based recall, helper functions.
 */

import { describe, it, expect } from "vitest";
import {
  shouldAttemptCapture,
  extractSignificance,
  extractMessageTexts,
  getLastUserMessage,
  rerankByTypeWeight,
} from "../src/hooks.js";
import { DEFAULT_RECALL_TYPE_WEIGHTS } from "../src/config.js";

// ============================================================================
// shouldAttemptCapture
// ============================================================================

describe("shouldAttemptCapture", () => {
  it("rejects text shorter than minChars", () => {
    expect(shouldAttemptCapture("short", 100)).toBe(false);
  });

  it("rejects trivial responses even if repeated to fill length", () => {
    // "ok ok ok" — 3 trivial words, short
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
    expect(result!.type).toBe("task"); // task > memory
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

    // Process: 0.7 * 1.5 = 1.05
    // Task: 0.75 * 1.2 = 0.9
    // Memory: 0.8 * 1.0 = 0.8
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
    expect(ranked[0].weightedScore).toBe(0.8); // 0.8 * 1.0
  });

  it("handles entries without type field", () => {
    const results = [
      { id: "1", content: "No type", score: 0.8, tier: "hot", scope: "team" },
    ];

    const ranked = rerankByTypeWeight(results, weights);
    expect(ranked[0].type).toBe("memory"); // defaults to "memory"
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
