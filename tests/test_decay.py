"""Tests for decay scoring."""

from palaia.decay import decay_score, classify_tier


def test_decay_score_fresh():
    score = decay_score(0, access_count=1)
    assert score > 0.6  # Fresh entry with 1 access


def test_decay_score_old():
    score = decay_score(60, access_count=1)
    assert score < 0.01  # 60 days old, rarely accessed


def test_decay_score_frequently_accessed():
    score_low = decay_score(10, access_count=1)
    score_high = decay_score(10, access_count=50)
    assert score_high > score_low  # More access = higher score


def test_classify_tier_hot():
    assert classify_tier(2, 0.8) == "hot"


def test_classify_tier_warm():
    assert classify_tier(15, 0.3) == "warm"


def test_classify_tier_cold():
    assert classify_tier(60, 0.01) == "cold"


def test_classify_high_score_stays_hot():
    # Even if old, high score keeps it hot
    assert classify_tier(20, 0.6) == "hot"
