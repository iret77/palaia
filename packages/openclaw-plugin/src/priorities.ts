/**
 * Injection priority management for multi-agent setups (Issue #121).
 *
 * TypeScript-side integration: loads `.palaia/priorities.json`,
 * resolves layered config (global -> agent -> project), and provides
 * blocking/filtering utilities for recall injection.
 *
 * Mirrors the Python implementation in palaia/priorities.py.
 */

import { readFile } from "node:fs/promises";
import { join } from "node:path";

// ============================================================================
// Interfaces
// ============================================================================

export interface PrioritiesConfig {
  version: number;
  blocked: string[];
  recallTypeWeight?: Record<string, number>;
  recallMinScore?: number;
  maxInjectedChars?: number;
  tier?: string;
  agents?: Record<string, AgentPriorityOverride>;
  projects?: Record<string, ProjectPriorityOverride>;
}

export interface AgentPriorityOverride {
  blocked?: string[];
  recallTypeWeight?: Record<string, number>;
  recallMinScore?: number;
  maxInjectedChars?: number;
  tier?: string;
  scopeVisibility?: string[];  // Issue #145: agent isolation
  captureScope?: string;       // Issue #147: per-agent write scope
}

export interface ProjectPriorityOverride {
  blocked?: string[];
  recallTypeWeight?: Record<string, number>;
}

export interface ResolvedPriorities {
  blocked: Set<string>;
  recallTypeWeight: Record<string, number>;
  recallMinScore: number;
  maxInjectedChars: number;
  tier: string;
  scopeVisibility: string[] | null;  // Issue #145: agent isolation
  captureScope: string | null;       // Issue #147: per-agent write scope
}

// ============================================================================
// Defaults (match Python side)
// ============================================================================

const DEFAULT_TYPE_WEIGHTS: Record<string, number> = { process: 1.5, task: 1.2, memory: 1.0 };
const DEFAULT_MIN_SCORE = 0.0;
const DEFAULT_MAX_CHARS = 4000;
const DEFAULT_TIER = "hot";

// ============================================================================
// TTL Cache
// ============================================================================

const CACHE_TTL_MS = 30_000;

let _cache: {
  workspace: string;
  data: PrioritiesConfig | null;
  loadedAt: number;
} | null = null;

/** Reset cache (for testing). */
export function resetPrioritiesCache(): void {
  _cache = null;
}

// ============================================================================
// Load
// ============================================================================

/**
 * Load `.palaia/priorities.json` from the given workspace directory.
 * Returns null if the file does not exist or is invalid.
 * Results are cached with a 30-second TTL.
 */
export async function loadPriorities(workspace: string): Promise<PrioritiesConfig | null> {
  const now = Date.now();
  if (_cache && _cache.workspace === workspace && (now - _cache.loadedAt) < CACHE_TTL_MS) {
    return _cache.data;
  }

  const path = join(workspace, ".palaia", "priorities.json");
  let data: PrioritiesConfig | null = null;

  try {
    const raw = await readFile(path, "utf-8");
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      data = parsed as PrioritiesConfig;
    }
  } catch {
    // File doesn't exist or is invalid — return null
  }

  _cache = { workspace, data, loadedAt: now };
  return data;
}

// ============================================================================
// Resolve
// ============================================================================

export interface PriorityDefaults {
  recallTypeWeight: Record<string, number>;
  recallMinScore: number;
  maxInjectedChars: number;
  tier: string;
}

/**
 * Merge priority layers into a flat resolved config.
 *
 * Resolution order: plugin defaults -> global overrides -> agent overrides -> project overrides.
 * `blocked` is a union across all layers.
 * Type weights are merged (partial overrides fill from previous layer).
 * Scalar values are overridden (last layer wins).
 */
export function resolvePriorities(
  prio: PrioritiesConfig | null,
  defaults: PriorityDefaults,
  agentId?: string,
  project?: string,
): ResolvedPriorities {
  const resolved: ResolvedPriorities = {
    blocked: new Set<string>(),
    recallTypeWeight: { ...DEFAULT_TYPE_WEIGHTS, ...defaults.recallTypeWeight },
    recallMinScore: defaults.recallMinScore ?? DEFAULT_MIN_SCORE,
    maxInjectedChars: defaults.maxInjectedChars ?? DEFAULT_MAX_CHARS,
    tier: defaults.tier ?? DEFAULT_TIER,
    scopeVisibility: null,
    captureScope: null,
  };

  if (!prio) return resolved;

  // Layer 1: Global
  if (prio.blocked) {
    for (const b of prio.blocked) resolved.blocked.add(b);
  }
  if (prio.recallTypeWeight) {
    resolved.recallTypeWeight = { ...resolved.recallTypeWeight, ...prio.recallTypeWeight };
  }
  if (prio.recallMinScore !== undefined) {
    resolved.recallMinScore = Number(prio.recallMinScore);
  }
  if (prio.maxInjectedChars !== undefined) {
    resolved.maxInjectedChars = Number(prio.maxInjectedChars);
  }
  if (prio.tier !== undefined) {
    resolved.tier = prio.tier;
  }

  // Layer 2: Agent override
  if (agentId) {
    const agentCfg = prio.agents?.[agentId];
    if (agentCfg) {
      if (agentCfg.blocked) {
        for (const b of agentCfg.blocked) resolved.blocked.add(b);
      }
      if (agentCfg.recallTypeWeight) {
        resolved.recallTypeWeight = { ...resolved.recallTypeWeight, ...agentCfg.recallTypeWeight };
      }
      if (agentCfg.recallMinScore !== undefined) {
        resolved.recallMinScore = Number(agentCfg.recallMinScore);
      }
      if (agentCfg.maxInjectedChars !== undefined) {
        resolved.maxInjectedChars = Number(agentCfg.maxInjectedChars);
      }
      if (agentCfg.tier !== undefined) {
        resolved.tier = agentCfg.tier;
      }
      if (agentCfg.scopeVisibility) {
        resolved.scopeVisibility = [...agentCfg.scopeVisibility];
      }
      if (agentCfg.captureScope) {
        resolved.captureScope = agentCfg.captureScope;
      }
    }
  }

  // Layer 3: Project override (only blocked + recallTypeWeight)
  if (project) {
    const projCfg = prio.projects?.[project];
    if (projCfg) {
      if (projCfg.blocked) {
        for (const b of projCfg.blocked) resolved.blocked.add(b);
      }
      if (projCfg.recallTypeWeight) {
        resolved.recallTypeWeight = { ...resolved.recallTypeWeight, ...projCfg.recallTypeWeight };
      }
    }
  }

  return resolved;
}

// ============================================================================
// Blocking
// ============================================================================

/**
 * Check if an entry ID is blocked (exact or prefix match).
 * Prefix match requires the blocked prefix to be at least 8 chars.
 */
export function isBlocked(entryId: string, blocked: Set<string>): boolean {
  if (blocked.has(entryId)) return true;
  for (const b of blocked) {
    if (b.length >= 8 && entryId.startsWith(b)) return true;
  }
  return false;
}

/**
 * Filter out blocked entries from a list.
 * Each entry must have an `id` property.
 */
export function filterBlocked<T extends { id: string }>(entries: T[], blocked: Set<string>): T[] {
  if (blocked.size === 0) return entries;
  return entries.filter((e) => !isBlocked(e.id, blocked));
}
