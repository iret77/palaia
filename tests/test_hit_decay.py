"""Tests for retrieval-hit decay (Issue #33)."""

import math

from palaia.decay import decay_score


def test_access_count_zero_gives_factor_one():
    """access_count=0 → hit_rate_bonus = 1.0 (no boost)."""
    score = decay_score(0, access_count=0)
    # time_decay=1.0, bonus=1+log(1+0)=1+0=1.0
    assert abs(score - 1.0) < 0.001


def test_access_count_10_gives_approx_3_4():
    """access_count=10 → bonus ≈ 3.4."""
    expected_bonus = 1 + math.log(1 + 10)  # ≈ 3.397
    score = decay_score(0, access_count=10)
    assert abs(score - expected_bonus) < 0.01


def test_access_count_100_gives_approx_5_6():
    """access_count=100 → bonus ≈ 5.6."""
    expected_bonus = 1 + math.log(1 + 100)  # ≈ 5.620
    score = decay_score(0, access_count=100)
    assert abs(score - expected_bonus) < 0.01


def test_hit_rate_slows_decay():
    """Entries with high access_count decay slower than low-access entries."""
    score_low = decay_score(30, access_count=0)
    score_high = decay_score(30, access_count=50)
    assert score_high > score_low * 3  # Significant difference


def test_fresh_entry_no_access_equals_one():
    """Fresh entry with 0 days and 0 access = 1.0."""
    score = decay_score(0, access_count=0)
    assert score == 1.0


def test_old_high_access_beats_old_low_access():
    """Old frequently-accessed entry beats old rarely-accessed entry."""
    score_rarely = decay_score(60, access_count=1)
    score_frequent = decay_score(60, access_count=100)
    assert score_frequent > score_rarely


def test_gc_score_includes_hit_rate(tmp_path):
    """GC score uses the updated decay formula with hit rate bonus."""
    from palaia.store import Store

    root = tmp_path / ".palaia"
    root.mkdir()
    for d in ("hot", "warm", "cold", "wal", "index"):
        (root / d).mkdir()
    import json

    (root / "config.json").write_text(json.dumps({"agent": "test"}))

    store = Store(root)

    # Write two entries
    id1 = store.write("Low access entry", agent="test")
    id2 = store.write("High access entry", agent="test")

    # Simulate high access on id2
    path2 = root / "hot" / f"{id2}.md"
    text = path2.read_text()
    text = text.replace("access_count: 1", "access_count: 50")
    path2.write_text(text)

    from palaia.entry import parse_entry

    meta2, body2 = parse_entry(path2.read_text())
    meta1, body1 = parse_entry((root / "hot" / f"{id1}.md").read_text())

    score1 = store.gc_score_entry(meta1, body1)
    score2 = store.gc_score_entry(meta2, body2)

    # High access entry should have higher GC score
    assert score2 > score1
