"""Memory decay scoring and tier rotation (ADR-004)."""

import math
from datetime import datetime, timezone
from pathlib import Path


def decay_score(
    days_since_access: float,
    access_count: int = 1,
    lambda_val: float = 0.1,
) -> float:
    """Calculate decay score. Higher = more relevant.
    
    score = recency_factor * log(1 + access_count)
    recency_factor = exp(-lambda * days_since_access)
    """
    recency = math.exp(-lambda_val * days_since_access)
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
