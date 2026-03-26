/**
 * Tests for src/priorities.ts — priority resolution, blocking, and filtering.
 */

import { describe, it, expect } from "vitest";
import {
  resolvePriorities,
  isBlocked,
  filterBlocked,
  type PrioritiesConfig,
  type PriorityDefaults,
} from "../src/priorities.js";

const DEFAULTS: PriorityDefaults = {
  recallTypeWeight: { process: 1.5, task: 1.2, memory: 1.0 },
  recallMinScore: 0.7,
  maxInjectedChars: 4000,
  tier: "hot",
};

describe("resolvePriorities", () => {
  it("returns defaults when config is null", () => {
    const result = resolvePriorities(null, DEFAULTS);
    expect(result.blocked.size).toBe(0);
    expect(result.recallTypeWeight).toEqual({ process: 1.5, task: 1.2, memory: 1.0 });
    expect(result.recallMinScore).toBe(0.7);
    expect(result.maxInjectedChars).toBe(4000);
    expect(result.tier).toBe("hot");
  });

  it("applies global overrides", () => {
    const prio: PrioritiesConfig = {
      version: 1,
      blocked: ["entry-abc-123"],
      recallTypeWeight: { process: 2.0 },
      recallMinScore: 0.5,
      maxInjectedChars: 8000,
      tier: "warm",
    };
    const result = resolvePriorities(prio, DEFAULTS);
    expect(result.blocked.has("entry-abc-123")).toBe(true);
    expect(result.recallTypeWeight.process).toBe(2.0);
    expect(result.recallTypeWeight.task).toBe(1.2); // unchanged from defaults
    expect(result.recallMinScore).toBe(0.5);
    expect(result.maxInjectedChars).toBe(8000);
    expect(result.tier).toBe("warm");
  });

  it("merges agent overrides correctly", () => {
    const prio: PrioritiesConfig = {
      version: 1,
      blocked: ["global-blocked"],
      recallTypeWeight: { process: 2.0 },
      agents: {
        "agent-1": {
          blocked: ["agent-blocked"],
          recallTypeWeight: { task: 3.0 },
          recallMinScore: 0.9,
          maxInjectedChars: 2000,
          tier: "all",
        },
      },
    };
    const result = resolvePriorities(prio, DEFAULTS, "agent-1");
    // blocked is union of global + agent
    expect(result.blocked.has("global-blocked")).toBe(true);
    expect(result.blocked.has("agent-blocked")).toBe(true);
    expect(result.blocked.size).toBe(2);
    // type weights are merged: global process=2.0, agent task=3.0, default memory=1.0
    expect(result.recallTypeWeight.process).toBe(2.0);
    expect(result.recallTypeWeight.task).toBe(3.0);
    expect(result.recallTypeWeight.memory).toBe(1.0);
    // agent scalar overrides
    expect(result.recallMinScore).toBe(0.9);
    expect(result.maxInjectedChars).toBe(2000);
    expect(result.tier).toBe("all");
  });

  it("ignores agent overrides for non-matching agentId", () => {
    const prio: PrioritiesConfig = {
      version: 1,
      blocked: [],
      agents: {
        "agent-1": {
          recallMinScore: 0.9,
        },
      },
    };
    const result = resolvePriorities(prio, DEFAULTS, "agent-2");
    expect(result.recallMinScore).toBe(0.7); // defaults
  });

  it("merges project overrides (only blocked + recallTypeWeight)", () => {
    const prio: PrioritiesConfig = {
      version: 1,
      blocked: ["global-blocked"],
      projects: {
        "my-project": {
          blocked: ["proj-blocked"],
          recallTypeWeight: { memory: 2.5 },
        },
      },
    };
    const result = resolvePriorities(prio, DEFAULTS, undefined, "my-project");
    expect(result.blocked.has("global-blocked")).toBe(true);
    expect(result.blocked.has("proj-blocked")).toBe(true);
    expect(result.recallTypeWeight.memory).toBe(2.5);
    // scalars unchanged (project doesn't override them)
    expect(result.recallMinScore).toBe(0.7);
    expect(result.maxInjectedChars).toBe(4000);
    expect(result.tier).toBe("hot");
  });

  it("merges all three layers: global -> agent -> project", () => {
    const prio: PrioritiesConfig = {
      version: 1,
      blocked: ["g1"],
      recallTypeWeight: { process: 2.0 },
      tier: "warm",
      agents: {
        "a1": {
          blocked: ["a1-blocked"],
          tier: "all",
        },
      },
      projects: {
        "p1": {
          blocked: ["p1-blocked"],
          recallTypeWeight: { task: 5.0 },
        },
      },
    };
    const result = resolvePriorities(prio, DEFAULTS, "a1", "p1");
    expect(result.blocked).toEqual(new Set(["g1", "a1-blocked", "p1-blocked"]));
    expect(result.tier).toBe("all"); // agent overrides global
    expect(result.recallTypeWeight.process).toBe(2.0); // global
    expect(result.recallTypeWeight.task).toBe(5.0); // project
  });
});

describe("isBlocked", () => {
  it("returns true for exact match", () => {
    const blocked = new Set(["abc123"]);
    expect(isBlocked("abc123", blocked)).toBe(true);
  });

  it("returns false for non-matching entry", () => {
    const blocked = new Set(["abc123"]);
    expect(isBlocked("xyz789", blocked)).toBe(false);
  });

  it("returns true for prefix match with >= 8 char prefix", () => {
    const blocked = new Set(["abcdefgh"]); // 8 chars
    expect(isBlocked("abcdefgh-suffix", blocked)).toBe(true);
  });

  it("returns false for prefix match with < 8 char prefix", () => {
    const blocked = new Set(["abcdefg"]); // 7 chars
    expect(isBlocked("abcdefg-suffix", blocked)).toBe(false);
  });

  it("handles empty blocked set", () => {
    expect(isBlocked("anything", new Set())).toBe(false);
  });
});

describe("filterBlocked", () => {
  it("removes blocked entries", () => {
    const entries = [
      { id: "keep-1", body: "a" },
      { id: "blocked-entry", body: "b" },
      { id: "keep-2", body: "c" },
    ];
    const blocked = new Set(["blocked-entry"]);
    const result = filterBlocked(entries, blocked);
    expect(result).toHaveLength(2);
    expect(result.map((e) => e.id)).toEqual(["keep-1", "keep-2"]);
  });

  it("removes prefix-blocked entries", () => {
    const entries = [
      { id: "12345678-full-id", body: "a" },
      { id: "keep-me", body: "b" },
    ];
    const blocked = new Set(["12345678"]); // 8 chars prefix
    const result = filterBlocked(entries, blocked);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("keep-me");
  });

  it("returns all entries when blocked is empty", () => {
    const entries = [
      { id: "a", body: "1" },
      { id: "b", body: "2" },
    ];
    const result = filterBlocked(entries, new Set());
    expect(result).toHaveLength(2);
  });

  it("returns empty array when all entries are blocked", () => {
    const entries = [
      { id: "blocked-1", body: "a" },
      { id: "blocked-2", body: "b" },
    ];
    const blocked = new Set(["blocked-1", "blocked-2"]);
    const result = filterBlocked(entries, blocked);
    expect(result).toHaveLength(0);
  });
});
