"""Tests for knowledge curation (palaia curate)."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from palaia.config import DEFAULT_CONFIG, save_config
from palaia.curate import (
    Cluster,
    ClusterEntry,
    CurateReport,
    ScopeMapping,
    _cosine_similarity,
    _find_duplicates,
    _label_cluster,
    _recommend_cluster,
    analyze,
    apply_report,
    cluster_entries,
    generate_report,
    load_entries,
    merge_entries,
    parse_report,
)
from palaia.store import Store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(
    entry_id: str = "abcd1234",
    full_id: str = "abcd1234-5678-9abc-def0-123456789abc",
    title: str | None = "Test entry",
    entry_type: str = "memory",
    scope: str = "team",
    agent: str | None = None,
    created: str = "",
    accessed: str = "",
    access_count: int = 1,
    decay_score: float = 0.5,
    significance_tags: list[str] | None = None,
    tags: list[str] | None = None,
    content: str = "Some test content",
    tier: str = "hot",
    embedding: list[float] | None = None,
) -> ClusterEntry:
    now = datetime.now(timezone.utc).isoformat()
    return ClusterEntry(
        entry_id=entry_id,
        full_id=full_id,
        title=title,
        entry_type=entry_type,
        scope=scope,
        agent=agent,
        created=created or now,
        accessed=accessed or now,
        access_count=access_count,
        decay_score=decay_score,
        significance_tags=significance_tags or [],
        tags=tags or [],
        content=content,
        tier=tier,
        embedding=embedding,
    )


def _make_embedding(seed: int, dim: int = 8) -> list[float]:
    """Generate a deterministic unit-ish embedding vector from a seed."""
    vec = [math.sin(seed + i) for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


@pytest.fixture
def populated_store(palaia_root):
    """Store with 10+ entries for curation testing."""
    store = Store(palaia_root)
    now = datetime.now(timezone.utc)
    entries = [
        ("API endpoint documentation — we decided to use REST", {"scope": "team", "tags": ["decision"], "entry_type": "process"}),
        ("Deploy checklist v2 — process for deployment", {"scope": "team", "tags": ["process"], "entry_type": "process"}),
        ("Database schema notes", {"scope": "team", "tags": [], "entry_type": "memory"}),
        ("Frontend component patterns", {"scope": "public", "tags": [], "entry_type": "memory"}),
        ("API error handling patterns", {"scope": "team", "tags": ["lesson"], "entry_type": "memory"}),
        ("Security review checklist", {"scope": "private", "tags": ["commitment"], "entry_type": "process", "agent": "alice"}),
        ("Team standup notes", {"scope": "team", "tags": [], "entry_type": "memory"}),
        ("Performance optimization guidelines", {"scope": "public", "tags": ["fact"], "entry_type": "memory"}),
        ("Code review standards", {"scope": "team", "tags": [], "entry_type": "process"}),
        ("Legacy migration plan", {"scope": "team", "tags": ["decision"], "entry_type": "memory"}),
        ("Testing strategy document", {"scope": "team", "tags": ["process"], "entry_type": "process"}),
    ]
    ids = []
    for body, kwargs in entries:
        eid = store.write(body, **kwargs)
        ids.append(eid)
    return store, ids


# ---------------------------------------------------------------------------
# Test _cosine_similarity
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert abs(_cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert abs(_cosine_similarity(a, b) - (-1.0)) < 1e-6

    def test_different_lengths(self):
        a = [1.0, 2.0]
        b = [1.0, 2.0, 3.0]
        assert _cosine_similarity(a, b) == 0.0

    def test_zero_vector(self):
        a = [0.0, 0.0]
        b = [1.0, 2.0]
        assert _cosine_similarity(a, b) == 0.0


# ---------------------------------------------------------------------------
# Test load_entries
# ---------------------------------------------------------------------------

class TestLoadEntries:
    def test_load_entries_all(self, populated_store):
        store, ids = populated_store
        entries = load_entries(store)
        assert len(entries) == 11
        for e in entries:
            assert len(e.entry_id) == 8
            assert len(e.full_id) > 8

    def test_load_entries_project_filter(self, palaia_root):
        store = Store(palaia_root)
        store.write("Project A entry", project="alpha")
        store.write("Project B entry", project="beta")
        store.write("No project entry")

        entries_alpha = load_entries(store, project="alpha")
        assert len(entries_alpha) == 1
        assert "Project A" in entries_alpha[0].content

    def test_load_entries_agent_filter(self, palaia_root):
        store = Store(palaia_root)
        store.write("Alice entry", agent="alice")
        store.write("Bob entry", agent="bob")

        entries = load_entries(store, agent="alice")
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# Test cluster_entries
# ---------------------------------------------------------------------------

class TestClusterEntries:
    def test_cluster_entries_greedy(self):
        """Greedy clustering groups similar entries together."""
        base_emb = _make_embedding(42)
        similar_emb = [x + 0.01 for x in base_emb]  # Very similar
        different_emb = _make_embedding(999)

        e1 = _make_entry(entry_id="aaaa1111", full_id="aaaa1111-full", embedding=base_emb, decay_score=0.9)
        e2 = _make_entry(entry_id="aaaa2222", full_id="aaaa2222-full", embedding=similar_emb, decay_score=0.8)
        e3 = _make_entry(entry_id="bbbb3333", full_id="bbbb3333-full", embedding=different_emb, decay_score=0.5)

        clusters, unclustered = cluster_entries([e1, e2, e3])
        assert len(unclustered) == 0
        # At least 1 cluster formed
        assert len(clusters) >= 1
        # All entries should be in some cluster
        total = sum(len(c.entries) for c in clusters)
        assert total == 3

    def test_cluster_entries_no_embeddings_unclustered(self):
        """Entries without embeddings go to unclustered."""
        e1 = _make_entry(entry_id="aaaa1111", full_id="aaaa1111-full", embedding=None)
        e2 = _make_entry(entry_id="aaaa2222", full_id="aaaa2222-full", embedding=None)

        clusters, unclustered = cluster_entries([e1, e2])
        assert len(clusters) == 0
        assert len(unclustered) == 2

    def test_cluster_mixed_embeddings(self):
        """Mix of entries with and without embeddings."""
        e1 = _make_entry(entry_id="aaaa1111", full_id="aaaa1111-full", embedding=_make_embedding(1))
        e2 = _make_entry(entry_id="aaaa2222", full_id="aaaa2222-full", embedding=None)

        clusters, unclustered = cluster_entries([e1, e2])
        assert len(unclustered) == 1
        assert unclustered[0].entry_id == "aaaa2222"


# ---------------------------------------------------------------------------
# Test _recommend_cluster
# ---------------------------------------------------------------------------

class TestRecommendCluster:
    def test_recommend_keep_significance(self):
        """Entries with significance tags should be recommended KEEP."""
        e = _make_entry(significance_tags=["decision"])
        c = Cluster(cluster_id=1, label="test", entries=[e], recommendation="", reason="")
        rec, reason = _recommend_cluster(c)
        assert rec == "KEEP"

    def test_recommend_keep_recent(self):
        """Recently accessed entries should be KEEP."""
        now = datetime.now(timezone.utc).isoformat()
        e = _make_entry(accessed=now)
        c = Cluster(cluster_id=1, label="test", entries=[e], recommendation="", reason="")
        rec, reason = _recommend_cluster(c)
        assert rec == "KEEP"

    def test_recommend_keep_process(self):
        """Process entries should be KEEP."""
        old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        e = _make_entry(entry_type="process", accessed=old)
        c = Cluster(cluster_id=1, label="test", entries=[e], recommendation="", reason="")
        rec, reason = _recommend_cluster(c)
        assert rec == "KEEP"

    def test_recommend_drop_old(self):
        """Old entries with no significance should be DROP."""
        old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        e = _make_entry(accessed=old, significance_tags=[], entry_type="memory")
        c = Cluster(cluster_id=1, label="test", entries=[e], recommendation="", reason="")
        rec, reason = _recommend_cluster(c)
        assert rec == "DROP"

    def test_recommend_merge_duplicates(self):
        """Clusters with near-duplicates should be MERGE."""
        now = datetime.now(timezone.utc).isoformat()
        e1 = _make_entry(entry_id="aaaa1111", accessed=now)
        e2 = _make_entry(entry_id="aaaa2222", accessed=now)
        c = Cluster(
            cluster_id=1, label="test", entries=[e1, e2],
            recommendation="", reason="",
            duplicates=[("aaaa1111", "aaaa2222", 0.92)],
        )
        rec, reason = _recommend_cluster(c)
        assert rec == "MERGE"


# ---------------------------------------------------------------------------
# Test _find_duplicates
# ---------------------------------------------------------------------------

class TestFindDuplicates:
    def test_find_duplicates_high_sim(self):
        """Pairs with cosine sim > 0.85 are flagged."""
        emb = _make_embedding(42)
        # Tiny perturbation -> very high similarity
        similar_emb = [x + 0.001 for x in emb]
        e1 = _make_entry(entry_id="aaaa1111", embedding=emb)
        e2 = _make_entry(entry_id="aaaa2222", embedding=similar_emb)

        dupes = _find_duplicates([e1, e2])
        assert len(dupes) == 1
        assert dupes[0][0] == "aaaa1111"
        assert dupes[0][1] == "aaaa2222"
        assert dupes[0][2] > 0.85

    def test_find_duplicates_low_sim(self):
        """Pairs with low similarity are not flagged."""
        e1 = _make_entry(entry_id="aaaa1111", embedding=_make_embedding(1))
        e2 = _make_entry(entry_id="aaaa2222", embedding=_make_embedding(100))

        dupes = _find_duplicates([e1, e2])
        # May or may not be empty depending on seed, but check it's a list
        for d in dupes:
            assert d[2] > 0.85  # Only high-sim pairs

    def test_find_duplicates_no_embeddings(self):
        """Entries without embeddings produce no duplicates."""
        e1 = _make_entry(entry_id="aaaa1111", embedding=None)
        e2 = _make_entry(entry_id="aaaa2222", embedding=None)
        assert _find_duplicates([e1, e2]) == []


# ---------------------------------------------------------------------------
# Test _label_cluster
# ---------------------------------------------------------------------------

class TestLabelCluster:
    def test_label_cluster_from_titles(self):
        """Label extracts common non-stopword terms."""
        e1 = _make_entry(title="API endpoint documentation")
        e2 = _make_entry(title="API error handling")
        label = _label_cluster([e1, e2])
        assert "api" in label.lower()

    def test_label_cluster_no_titles(self):
        """Falls back to content when no titles."""
        e1 = _make_entry(title=None, content="Database migration strategy")
        e2 = _make_entry(title=None, content="Database schema design")
        label = _label_cluster([e1, e2])
        assert "database" in label.lower()

    def test_label_cluster_empty(self):
        """Empty entries produce a fallback label."""
        e = _make_entry(title=None, content="")
        label = _label_cluster([e])
        assert len(label) > 0


# ---------------------------------------------------------------------------
# Test report roundtrip
# ---------------------------------------------------------------------------

class TestReportRoundtrip:
    def _make_report(self) -> CurateReport:
        now = datetime.now(timezone.utc).isoformat()
        e1 = _make_entry(
            entry_id="abcd1234", full_id="abcd1234-5678-9abc-def0-123456789abc",
            title="Test entry one", entry_type="memory", scope="team",
            decay_score=0.7500, significance_tags=["decision"],
        )
        e2 = _make_entry(
            entry_id="ef005678", full_id="ef005678-9abc-def0-1234-56789abcdef0",
            title="Test entry two", entry_type="process", scope="public",
            decay_score=0.3000,
        )
        e3 = _make_entry(
            entry_id="aa001234", full_id="aa001234-3456-7890-abcd-ef0123456789",
            title="Unclustered entry", entry_type="memory", scope="team",
            decay_score=0.1000,
        )
        cluster = Cluster(
            cluster_id=1, label="test entries", entries=[e1, e2],
            recommendation="KEEP", reason="Contains significant entries",
            duplicates=[("abcd1234", "ef005678", 0.9100)],
        )
        return CurateReport(
            project="myproject",
            generated_at=now,
            total_entries=3,
            clusters=[cluster],
            scope_mappings=[
                ScopeMapping(source_scope="team", source_agent=None, target="team"),
                ScopeMapping(source_scope="public", source_agent="alice", target="public"),
            ],
            unclustered=[e3],
        )

    def test_report_roundtrip(self):
        """generate -> parse -> verify key fields."""
        report = self._make_report()
        md = generate_report(report)
        parsed = parse_report(md)

        assert parsed.project == report.project
        assert parsed.total_entries == report.total_entries
        assert len(parsed.clusters) == 1
        assert len(parsed.clusters[0].entries) == 2
        assert parsed.clusters[0].recommendation == "KEEP"
        assert parsed.clusters[0].label == "test entries"
        assert len(parsed.unclustered) == 1
        assert parsed.unclustered[0].entry_id == "aa001234"

    def test_report_parse_edited(self):
        """Parse after user changed recommendation."""
        report = self._make_report()
        md = generate_report(report)
        # User edits: change KEEP to DROP
        md = md.replace("**Recommendation:** KEEP", "**Recommendation:** DROP")
        parsed = parse_report(md)
        assert parsed.clusters[0].recommendation == "DROP"

    def test_scope_mapping_parse(self):
        """Scope mapping table is correctly parsed."""
        report = self._make_report()
        md = generate_report(report)
        parsed = parse_report(md)

        assert len(parsed.scope_mappings) == 2
        assert parsed.scope_mappings[0].source_scope == "team"
        assert parsed.scope_mappings[0].source_agent is None
        assert parsed.scope_mappings[0].target == "team"
        assert parsed.scope_mappings[1].source_agent == "alice"

    def test_duplicate_parse(self):
        """Duplicate pairs survive roundtrip."""
        report = self._make_report()
        md = generate_report(report)
        parsed = parse_report(md)

        assert len(parsed.clusters[0].duplicates) == 1
        a_id, b_id, sim = parsed.clusters[0].duplicates[0]
        assert a_id == "abcd1234"
        assert b_id == "ef005678"
        assert abs(sim - 0.91) < 0.01


# ---------------------------------------------------------------------------
# Test apply_report
# ---------------------------------------------------------------------------

class TestApplyReport:
    def test_apply_keep(self, palaia_root):
        """KEEP entries are included in output."""
        store = Store(palaia_root)
        e1 = _make_entry(content="Keep this content", title="Keep me")
        cluster = Cluster(
            cluster_id=1, label="keep", entries=[e1],
            recommendation="KEEP", reason="test",
        )
        report = CurateReport(
            project=None, generated_at="", total_entries=1,
            clusters=[cluster], scope_mappings=[], unclustered=[],
        )
        result = apply_report(report, store)
        assert result["kept"] == 1
        assert result["dropped"] == 0
        assert result["merged"] == 0
        assert len(result["entries"]) == 1
        assert result["entries"][0]["content"] == "Keep this content"

    def test_apply_drop(self, palaia_root):
        """DROP entries are excluded from output."""
        store = Store(palaia_root)
        e1 = _make_entry(content="Drop this")
        cluster = Cluster(
            cluster_id=1, label="drop", entries=[e1],
            recommendation="DROP", reason="test",
        )
        report = CurateReport(
            project=None, generated_at="", total_entries=1,
            clusters=[cluster], scope_mappings=[], unclustered=[],
        )
        result = apply_report(report, store)
        assert result["dropped"] == 1
        assert result["kept"] == 0
        assert len(result["entries"]) == 0

    def test_apply_merge(self, palaia_root):
        """MERGE produces a single combined entry."""
        store = Store(palaia_root)
        e1 = _make_entry(
            entry_id="aaaa1111", content="Primary content",
            title="Primary", tags=["tag1"], decay_score=0.9,
            scope="team",
        )
        e2 = _make_entry(
            entry_id="aaaa2222", content="Secondary content",
            title="Secondary", tags=["tag2"], decay_score=0.5,
            scope="public",
        )
        cluster = Cluster(
            cluster_id=1, label="merge", entries=[e1, e2],
            recommendation="MERGE", reason="test",
        )
        report = CurateReport(
            project=None, generated_at="", total_entries=2,
            clusters=[cluster], scope_mappings=[], unclustered=[],
        )
        result = apply_report(report, store)
        assert result["merged"] == 2
        assert len(result["entries"]) == 1
        merged = result["entries"][0]
        assert "Primary content" in merged["content"]
        assert "Secondary" in merged["content"]
        # Tags should be union
        assert "tag1" in merged["tags"]
        assert "tag2" in merged["tags"]
        # Scope should be broadest (public > team)
        assert merged["scope"] == "public"

    def test_apply_scope_mapping(self, palaia_root):
        """Scope remapping is applied to output entries."""
        store = Store(palaia_root)
        e1 = _make_entry(content="Remap me", scope="private", agent="alice")
        cluster = Cluster(
            cluster_id=1, label="remap", entries=[e1],
            recommendation="KEEP", reason="test",
        )
        report = CurateReport(
            project=None, generated_at="", total_entries=1,
            clusters=[cluster],
            scope_mappings=[
                ScopeMapping(source_scope="private", source_agent="alice", target="team"),
            ],
            unclustered=[],
        )
        result = apply_report(report, store)
        assert result["entries"][0]["scope"] == "team"

    def test_unclustered_always_kept(self, palaia_root):
        """Unclustered entries are always included."""
        store = Store(palaia_root)
        e1 = _make_entry(content="Orphan entry")
        report = CurateReport(
            project=None, generated_at="", total_entries=1,
            clusters=[], scope_mappings=[], unclustered=[e1],
        )
        result = apply_report(report, store)
        assert result["kept"] == 1
        assert len(result["entries"]) == 1


# ---------------------------------------------------------------------------
# Test merge_entries
# ---------------------------------------------------------------------------

class TestMergeEntries:
    def test_merge_basic(self):
        now = datetime.now(timezone.utc).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        e1 = _make_entry(
            content="Main content", title="Main", tags=["a"],
            decay_score=0.9, scope="team", created=now,
        )
        e2 = _make_entry(
            content="Extra content", title="Extra", tags=["b"],
            decay_score=0.3, scope="public", created=old,
        )
        merged = merge_entries([e1, e2])
        assert "Main content" in merged["content"]
        assert "Extra" in merged["content"]
        assert "a" in merged["tags"]
        assert "b" in merged["tags"]
        assert merged["scope"] == "public"  # broadest
        assert merged["created"] == old  # earliest

    def test_merge_empty(self):
        assert merge_entries([]) == {}

    def test_merge_single(self):
        e = _make_entry(content="Only one", title="Solo")
        merged = merge_entries([e])
        assert merged["content"] == "Only one"


# ---------------------------------------------------------------------------
# Test output compatibility
# ---------------------------------------------------------------------------

class TestOutputCompatibility:
    def test_output_is_valid_package(self, palaia_root):
        """Output from apply_svc is a valid .palaia-pkg.json."""
        from palaia.services.curate import apply_svc

        store = Store(palaia_root)
        store.write("Test entry for package", scope="team")

        # Generate a report
        report = analyze(store)
        md = generate_report(report)
        report_path = str(palaia_root / "test-report.md")
        (palaia_root / "test-report.md").write_text(md, encoding="utf-8")

        output_path = str(palaia_root / "test-output.palaia-pkg.json")
        result = apply_svc(palaia_root, report_path, output=output_path)

        # Verify the output is valid JSON
        import json
        pkg = json.loads((palaia_root / "test-output.palaia-pkg.json").read_text())
        assert "palaia_package" in pkg
        assert "entries" in pkg
        assert pkg["palaia_package"] == "1.0"
        assert isinstance(pkg["entries"], list)

        # Verify it can be imported
        pm = PackageManager(store)
        # This should not raise
        info = pm.package_info(output_path)
        assert info["palaia_package"] == "1.0"


# ---------------------------------------------------------------------------
# Test analyze integration
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_analyze_returns_report(self, populated_store):
        store, ids = populated_store
        report = analyze(store)
        assert report.total_entries == 11
        # All entries should be accounted for (in clusters or unclustered)
        total = sum(len(c.entries) for c in report.clusters) + len(report.unclustered)
        assert total == 11

    def test_analyze_with_project_filter(self, palaia_root):
        store = Store(palaia_root)
        store.write("Alpha entry", project="alpha")
        store.write("Beta entry", project="beta")

        report = analyze(store, project="alpha")
        assert report.total_entries == 1
        assert report.project == "alpha"


# Import for package compat test
from palaia.packages import PackageManager
