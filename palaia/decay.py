"""Memory decay scoring and tier rotation (ADR-004, Issue #33)."""

from __future__ import annotations

import math
from datetime import datetime, timezone

# Significance decay multipliers (Issue #33)
# Higher = slower decay (multiplier on effective lambda denominator)
SIGNIFICANCE_DECAY_BONUS: dict[str, float] = {
    "decision": 3.0,
    "identity": 3.0,
    "human": 2.5,
    "lesson": 2.0,
    "surprise": 1.5,
}


def significance_multiplier(significance: list[str] | None) -> float:
    """Calculate the combined significance decay multiplier.

    Takes the maximum bonus from all significance tags.
    Returns 1.0 if no significance tags are present (no bonus).
    """
    if not significance:
        return 1.0
    max_bonus = max(SIGNIFICANCE_DECAY_BONUS.get(tag, 1.0) for tag in significance)
    return max_bonus


def recall_multiplier(recall_count: int) -> float:
    """Calculate recall-based decay multiplier.

    Frequently recalled entries decay slower.
    Uses log(1 + recall_count) to provide diminishing returns.
    Returns >= 1.0 (1.0 = no bonus).
    """
    if recall_count <= 0:
        return 1.0
    return 1.0 + 0.3 * math.log(1 + recall_count)


def decay_score(
    days_since_access: float,
    access_count: int = 1,
    lambda_val: float = 0.1,
    significance: list[str] | None = None,
    recall_count: int = 0,
) -> float:
    """Calculate decay score. Higher = more relevant.

    score = recency_factor * log(1 + access_count)
    recency_factor = exp(-lambda * days_since_access / sig_mult / recall_mult)

    Significance tags and recall count slow down the decay rate.
    """
    sig_mult = significance_multiplier(significance)
    rec_mult = recall_multiplier(recall_count)
    effective_lambda = lambda_val / (sig_mult * rec_mult)
    recency = math.exp(-effective_lambda * days_since_access)
    frequency = math.log(1 + access_count)
    return round(recency * frequency, 6)


def classify_tier(
    days_since_access: float,
    score: float,
    hot_threshold_days: int = 7,
    warm_threshold_days: int = 30,
    hot_min_score: float = 0.5,
    warm_min_score: float = 0.1,
) -> str:
    """Determine which tier a memory belongs to."""
    if days_since_access <= hot_threshold_days or score >= hot_min_score:
        return "hot"
    if days_since_access <= warm_threshold_days or score >= warm_min_score:
        return "warm"
    return "cold"


def days_since(dt_str: str) -> float:
    """Calculate days since a given ISO-8601 timestamp."""
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = now - dt
    return delta.total_seconds() / 86400.0
