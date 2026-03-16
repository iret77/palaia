"""Tests for significance tagging (Issue #70)."""

from palaia.significance import SIGNIFICANCE_TAGS, detect_significance, significance_weight


class TestDetectSignificance:
    def test_empty_text(self):
        assert detect_significance("") == []
        assert detect_significance("   ") == []

    def test_decision_english(self):
        tags = detect_significance("We decided to use PostgreSQL for the main database.")
        assert "decision" in tags

    def test_decision_german(self):
        tags = detect_significance("Wir haben uns entschieden, Redis zu nutzen.")
        assert "decision" in tags

    def test_lesson_english(self):
        tags = detect_significance("Key lesson learned: always test with production data.")
        assert "lesson" in tags

    def test_lesson_german(self):
        tags = detect_significance("Erkenntnis: Nie ohne Backup deployen.")
        assert "lesson" in tags

    def test_surprise(self):
        tags = detect_significance("Surprising result: the old algorithm was 2x faster.")
        assert "surprise" in tags

    def test_commitment(self):
        tags = detect_significance("I promised to deliver the report by Friday deadline.")
        assert "commitment" in tags

    def test_correction(self):
        tags = detect_significance("Correction: the API endpoint was wrong, corrected now.")
        assert "correction" in tags

    def test_preference(self):
        tags = detect_significance("I prefer dark mode for all coding environments.")
        assert "preference" in tags

    def test_fact(self):
        tags = detect_significance("The API key for production is stored in vault.")
        assert "fact" in tags

    def test_multiple_categories(self):
        text = "We decided to switch. Lesson learned: test first. This was unexpected."
        tags = detect_significance(text)
        assert "decision" in tags
        assert "lesson" in tags
        assert "surprise" in tags

    def test_no_match(self):
        tags = detect_significance("The weather is nice today.")
        assert tags == []

    def test_adr_detected_as_decision(self):
        tags = detect_significance("ADR-005: Use event sourcing for audit trail.")
        assert "decision" in tags

    def test_case_insensitive(self):
        tags = detect_significance("DECIDED to go with option B")
        assert "decision" in tags


class TestSignificanceWeight:
    def test_no_tags(self):
        assert significance_weight(None) == 1.0
        assert significance_weight([]) == 1.0

    def test_no_significance_tags(self):
        assert significance_weight(["python", "backend"]) == 1.0

    def test_one_significance_tag(self):
        assert significance_weight(["decision"]) == 1.2

    def test_two_significance_tags(self):
        assert significance_weight(["decision", "lesson"]) == 1.4

    def test_mixed_tags(self):
        # Only significance tags count
        assert significance_weight(["python", "decision", "backend", "lesson"]) == 1.4

    def test_all_significance_tags(self):
        expected = 1.0 + 0.2 * len(SIGNIFICANCE_TAGS)
        assert significance_weight(list(SIGNIFICANCE_TAGS)) == expected


class TestSignificanceTags:
    def test_all_expected_tags_present(self):
        expected = {"decision", "lesson", "surprise", "commitment", "correction", "preference", "fact"}
        assert set(SIGNIFICANCE_TAGS) == expected
