"""Knowledge curation for instance migration — cluster, recommend, merge."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from palaia.bm25 import cosine_similarity as _cosine_similarity
from palaia.decay import days_since, decay_score
from palaia.significance import detect_significance

logger = logging.getLogger(__name__)

STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to",
    "for", "of", "and", "or", "with", "this", "that", "it", "from", "by",
    "as", "be", "has", "have", "had", "not", "but", "its", "no", "so",
    "if", "do", "up", "all",
})

SCOPE_ORDER = {"private": 0, "team": 1, "public": 2}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ClusterEntry:
    entry_id: str          # 8-char prefix
    full_id: str           # full UUID
    title: str | None
    entry_type: str        # memory | process | task
    scope: str
    agent: str | None
    created: str
    accessed: str
    access_count: int
    decay_score: float
    significance_tags: list[str]
    tags: list[str]
    content: str
    tier: str
    embedding: list[float] | None


@dataclass
class Cluster:
    cluster_id: int
    label: str
    entries: list[ClusterEntry]
    recommendation: str    # KEEP | MERGE | DROP
    reason: str
    duplicates: list[tuple[str, str, float]] = field(default_factory=list)


@dataclass
class ScopeMapping:
    source_scope: str
    source_agent: str | None
    target: str


@dataclass
class CurateReport:
    project: str | None
    generated_at: str
    total_entries: int
    clusters: list[Cluster]
    scope_mappings: list[ScopeMapping]
    unclustered: list[ClusterEntry]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# _cosine_similarity is imported from palaia.bm25


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def load_entries(store, project: str | None = None, agent: str | None = None) -> list[ClusterEntry]:
    """Load all entries from the store, optionally filtering by project/agent."""
    all_raw = store.all_entries_unfiltered(include_cold=True)
    entries: list[ClusterEntry] = []

    for meta, body, tier in all_raw:
        entry_project = meta.get("project")
        entry_agent = meta.get("agent")

        if project and entry_project != project:
            continue
        if agent and entry_agent != agent:
            continue

        entry_id = meta.get("id", "")
        short_id = entry_id[:8]

        accessed = meta.get("accessed", meta.get("created", ""))
        created = meta.get("created", "")

        if accessed:
            d = days_since(accessed)
            ac = meta.get("access_count", 1)
            dscore = decay_score(d, ac, 0.1)
        else:
            dscore = 0.0

        # Look up embedding
        embedding = None
        try:
            embedding = store.embedding_cache.get_cached(entry_id)
        except Exception:
            pass

        sig_tags = detect_significance(body)
        entry_tags = meta.get("tags", []) or []

        entries.append(ClusterEntry(
            entry_id=short_id,
            full_id=entry_id,
            title=meta.get("title"),
            entry_type=meta.get("type", "memory"),
            scope=meta.get("scope", "team"),
            agent=entry_agent,
            created=created,
            accessed=accessed,
            access_count=meta.get("access_count", 1),
            decay_score=dscore,
            significance_tags=sig_tags,
            tags=entry_tags,
            content=body,
            tier=tier,
            embedding=embedding,
        ))

    return entries


def cluster_entries(entries: list[ClusterEntry]) -> tuple[list[Cluster], list[ClusterEntry]]:
    """Cluster entries by embedding similarity.

    Returns (clusters, unclustered).
    Uses sklearn if available, otherwise a greedy fallback.
    """
    # Split into embeddable and non-embeddable
    with_emb = [e for e in entries if e.embedding is not None]
    without_emb = [e for e in entries if e.embedding is None]

    if not with_emb:
        return [], list(entries)

    try:
        import numpy as np
        from sklearn.cluster import AgglomerativeClustering

        X = np.array([e.embedding for e in with_emb])
        # Normalise rows for cosine distance
        norms = np.linalg.norm(X, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        X_norm = X / norms

        n = len(with_emb)
        if n < 2:
            clusters_out = [Cluster(
                cluster_id=0,
                label="",
                entries=list(with_emb),
                recommendation="KEEP",
                reason="",
            )]
            return clusters_out, without_emb

        clustering = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=0.3,  # 1 - 0.7 cosine sim
            metric="cosine",
            linkage="average",
        )
        labels = clustering.fit_predict(X_norm)

        label_groups: dict[int, list[ClusterEntry]] = {}
        for label_val, entry in zip(labels, with_emb):
            label_groups.setdefault(int(label_val), []).append(entry)

        clusters_out: list[Cluster] = []
        for cid, group in sorted(label_groups.items()):
            clusters_out.append(Cluster(
                cluster_id=cid,
                label="",
                entries=group,
                recommendation="KEEP",
                reason="",
            ))

        return clusters_out, without_emb

    except ImportError:
        pass

    # Greedy fallback
    return _cluster_greedy(with_emb, without_emb)


def _cluster_greedy(
    with_emb: list[ClusterEntry],
    without_emb: list[ClusterEntry],
) -> tuple[list[Cluster], list[ClusterEntry]]:
    """Greedy clustering: seed by highest decay_score, group by cosine sim > 0.7."""
    sorted_entries = sorted(with_emb, key=lambda e: e.decay_score, reverse=True)
    used: set[str] = set()
    clusters: list[Cluster] = []
    cluster_id = 0

    for entry in sorted_entries:
        if entry.full_id in used:
            continue
        group = [entry]
        used.add(entry.full_id)

        for other in sorted_entries:
            if other.full_id in used:
                continue
            sim = _cosine_similarity(entry.embedding, other.embedding)  # type: ignore[arg-type]
            if sim > 0.7:
                group.append(other)
                used.add(other.full_id)

        clusters.append(Cluster(
            cluster_id=cluster_id,
            label="",
            entries=group,
            recommendation="KEEP",
            reason="",
        ))
        cluster_id += 1

    return clusters, without_emb


def _label_cluster(entries: list[ClusterEntry]) -> str:
    """Extract a short label from entry titles (top 3 non-stopword terms)."""
    word_counts: dict[str, int] = {}
    for e in entries:
        title = e.title or ""
        words = re.findall(r"[a-zA-Z0-9_-]+", title.lower())
        for w in words:
            if w not in STOPWORDS and len(w) > 1:
                word_counts[w] = word_counts.get(w, 0) + 1

    if not word_counts:
        # Fall back to content words
        for e in entries:
            words = re.findall(r"[a-zA-Z0-9_-]+", e.content[:200].lower())
            for w in words:
                if w not in STOPWORDS and len(w) > 1:
                    word_counts[w] = word_counts.get(w, 0) + 1

    top = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    if not top:
        return "Unnamed cluster"
    return " ".join(w for w, _ in top)


def _find_duplicates(entries: list[ClusterEntry]) -> list[tuple[str, str, float]]:
    """Find near-duplicate pairs within a cluster (cosine sim > 0.85)."""
    dupes: list[tuple[str, str, float]] = []
    for i, a in enumerate(entries):
        if a.embedding is None:
            continue
        for b in entries[i + 1:]:
            if b.embedding is None:
                continue
            sim = _cosine_similarity(a.embedding, b.embedding)
            if sim > 0.85:
                dupes.append((a.entry_id, b.entry_id, round(sim, 4)))
    return dupes


def _recommend_cluster(cluster: Cluster) -> tuple[str, str]:
    """Determine recommendation for a cluster.

    Returns (recommendation, reason).
    """
    entries = cluster.entries

    # Check if any entry has significance tags
    has_significance = any(e.significance_tags for e in entries)

    # Check if any entry is recently accessed (<30 days)
    recently_accessed = False
    for e in entries:
        if e.accessed:
            try:
                d = days_since(e.accessed)
                if d < 30:
                    recently_accessed = True
                    break
            except (ValueError, OSError):
                pass

    # Check if any entry is a process
    has_process = any(e.entry_type == "process" for e in entries)

    # Check if all entries are old (>60 days)
    all_old = True
    for e in entries:
        if e.accessed:
            try:
                d = days_since(e.accessed)
                if d <= 60:
                    all_old = False
                    break
            except (ValueError, OSError):
                all_old = False
                break
        else:
            all_old = False
            break

    # DROP: all entries >60 days old AND no significance tags
    if all_old and not has_significance:
        return "DROP", "All entries older than 60 days with no significance tags"

    # MERGE: has near-duplicates (check before generic KEEP)
    if cluster.duplicates:
        return "MERGE", "Near-duplicate entries detected"

    # KEEP: has significance tags, or recently accessed, or type=process
    if has_significance:
        return "KEEP", "Contains significant entries"
    if recently_accessed:
        return "KEEP", "Recently accessed entries"
    if has_process:
        return "KEEP", "Contains process entries"

    # Default: KEEP
    return "KEEP", "Default recommendation"


# ---------------------------------------------------------------------------
# Analyze
# ---------------------------------------------------------------------------

def analyze(store, project: str | None = None, agent: str | None = None) -> CurateReport:
    """Run full curation analysis."""
    entries = load_entries(store, project=project, agent=agent)
    clusters, unclustered = cluster_entries(entries)

    # Re-number clusters sequentially
    for i, c in enumerate(clusters):
        c.cluster_id = i + 1

    # For each cluster: label, find duplicates, recommend
    for c in clusters:
        c.label = _label_cluster(c.entries)
        c.duplicates = _find_duplicates(c.entries)
        c.recommendation, c.reason = _recommend_cluster(c)

    # Build scope mapping from unique (scope, agent) pairs
    seen: set[tuple[str, str | None]] = set()
    scope_mappings: list[ScopeMapping] = []
    all_entries = entries  # all loaded entries
    for e in all_entries:
        key = (e.scope, e.agent)
        if key not in seen:
            seen.add(key)
            scope_mappings.append(ScopeMapping(
                source_scope=e.scope,
                source_agent=e.agent,
                target=e.scope,  # default: keep same
            ))

    return CurateReport(
        project=project,
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_entries=len(entries),
        clusters=clusters,
        scope_mappings=scope_mappings,
        unclustered=unclustered,
    )


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(report: CurateReport) -> str:
    """Render a CurateReport to Markdown."""
    lines: list[str] = []
    lines.append("# Curation Report")
    lines.append("")
    lines.append(f"- **Project:** {report.project or '(all)'}")
    lines.append(f"- **Generated:** {report.generated_at}")
    lines.append(f"- **Total entries:** {report.total_entries}")
    lines.append(f"- **Clusters:** {len(report.clusters)}")
    lines.append(f"- **Unclustered:** {len(report.unclustered)}")
    lines.append("")

    for c in report.clusters:
        n = len(c.entries)
        lines.append(f'## Cluster {c.cluster_id}: "{c.label}" ({n} entr{"y" if n == 1 else "ies"})')
        lines.append("")
        lines.append(f"**Recommendation:** {c.recommendation}")
        lines.append(f"**Reason:** {c.reason}")
        lines.append("")

        if c.duplicates:
            lines.append("**Duplicates:**")
            for a_id, b_id, sim in c.duplicates:
                lines.append(f"- [{a_id}] ~ [{b_id}] (sim={sim:.4f})")
            lines.append("")

        lines.append("**Entries:**")
        lines.append("")
        for e in c.entries:
            title_str = e.title or "(untitled)"
            sig = f" sig={','.join(e.significance_tags)}" if e.significance_tags else ""
            lines.append(
                f"- [{e.entry_id}] {title_str} "
                f"(type={e.entry_type}, scope={e.scope}, decay={e.decay_score:.4f}{sig}) "
                f"<!-- full:{e.full_id} -->"
            )
        lines.append("")

    # Unclustered
    if report.unclustered:
        lines.append("## Unclustered Entries")
        lines.append("")
        for e in report.unclustered:
            title_str = e.title or "(untitled)"
            lines.append(
                f"- [{e.entry_id}] {title_str} "
                f"(type={e.entry_type}, scope={e.scope}, decay={e.decay_score:.4f}) "
                f"<!-- full:{e.full_id} -->"
            )
        lines.append("")

    # Scope mapping table
    lines.append("## Scope Mapping")
    lines.append("")
    lines.append("| Source Scope | Source Agent | Target |")
    lines.append("|---|---|---|")
    for sm in report.scope_mappings:
        agent_str = sm.source_agent or "(none)"
        lines.append(f"| {sm.source_scope} | {agent_str} | {sm.target} |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report parsing
# ---------------------------------------------------------------------------

_RE_CLUSTER_HEADER = re.compile(r'^## Cluster (\d+): "(.+?)" \((\d+) entr')
_RE_RECOMMENDATION = re.compile(r'\*\*Recommendation:\*\*\s*(KEEP|MERGE|DROP)')
_RE_REASON = re.compile(r'\*\*Reason:\*\*\s*(.+)')
_RE_ENTRY_LINE = re.compile(r'\[([a-f0-9]{8})\].*<!-- full:(\S+) -->')
_RE_ENTRY_DETAILS = re.compile(
    r'\[([a-f0-9]{8})\]\s+(.+?)\s+\(type=(\w+),\s*scope=(\w+),\s*decay=([\d.]+)'
)
_RE_SCOPE_ROW = re.compile(r'^\|\s*(\S+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|')
_RE_DUPLICATE_LINE = re.compile(r'- \[([a-f0-9]{8})\] ~ \[([a-f0-9]{8})\] \(sim=([\d.]+)\)')
_RE_PROJECT = re.compile(r'- \*\*Project:\*\*\s*(.+)')
_RE_GENERATED = re.compile(r'- \*\*Generated:\*\*\s*(.+)')
_RE_TOTAL = re.compile(r'- \*\*Total entries:\*\*\s*(\d+)')


def parse_report(markdown: str) -> CurateReport:
    """Parse a Markdown curation report back into a CurateReport."""
    lines = markdown.split("\n")
    clusters: list[Cluster] = []
    unclustered: list[ClusterEntry] = []
    scope_mappings: list[ScopeMapping] = []
    project: str | None = None
    generated_at = ""
    total_entries = 0

    current_cluster: Cluster | None = None
    in_unclustered = False
    in_scope_mapping = False
    in_duplicates = False

    for line in lines:
        stripped = line.strip()

        # Parse header metadata
        m = _RE_PROJECT.match(stripped)
        if m:
            val = m.group(1).strip()
            project = None if val == "(all)" else val
            continue

        m = _RE_GENERATED.match(stripped)
        if m:
            generated_at = m.group(1).strip()
            continue

        m = _RE_TOTAL.match(stripped)
        if m:
            total_entries = int(m.group(1))
            continue

        # Cluster header
        m = _RE_CLUSTER_HEADER.match(stripped)
        if m:
            if current_cluster is not None:
                clusters.append(current_cluster)
            current_cluster = Cluster(
                cluster_id=int(m.group(1)),
                label=m.group(2),
                entries=[],
                recommendation="KEEP",
                reason="",
            )
            in_unclustered = False
            in_scope_mapping = False
            in_duplicates = False
            continue

        # Unclustered section
        if stripped == "## Unclustered Entries":
            if current_cluster is not None:
                clusters.append(current_cluster)
                current_cluster = None
            in_unclustered = True
            in_scope_mapping = False
            in_duplicates = False
            continue

        # Scope Mapping section
        if stripped == "## Scope Mapping":
            if current_cluster is not None:
                clusters.append(current_cluster)
                current_cluster = None
            in_unclustered = False
            in_scope_mapping = True
            in_duplicates = False
            continue

        # Recommendation
        m = _RE_RECOMMENDATION.search(stripped)
        if m and current_cluster is not None:
            current_cluster.recommendation = m.group(1)
            continue

        # Reason
        m = _RE_REASON.search(stripped)
        if m and current_cluster is not None:
            current_cluster.reason = m.group(1).strip()
            continue

        # Duplicates header
        if stripped == "**Duplicates:**" and current_cluster is not None:
            in_duplicates = True
            continue

        # Duplicate line
        m = _RE_DUPLICATE_LINE.match(stripped)
        if m and current_cluster is not None and in_duplicates:
            current_cluster.duplicates.append(
                (m.group(1), m.group(2), float(m.group(3)))
            )
            continue

        # Entries header resets duplicates mode
        if stripped == "**Entries:**":
            in_duplicates = False
            continue

        # Entry lines
        m = _RE_ENTRY_LINE.search(stripped)
        if m:
            short_id = m.group(1)
            full_id = m.group(2)

            # Parse details
            dm = _RE_ENTRY_DETAILS.search(stripped)
            title = ""
            entry_type = "memory"
            scope = "team"
            dscore = 0.0
            if dm:
                title = dm.group(2).strip()
                entry_type = dm.group(3)
                scope = dm.group(4)
                dscore = float(dm.group(5))

            # Parse significance tags from entry line
            sig_tags: list[str] = []
            sig_match = re.search(r'sig=([a-z,]+)', stripped)
            if sig_match:
                sig_tags = sig_match.group(1).split(",")

            entry = ClusterEntry(
                entry_id=short_id,
                full_id=full_id,
                title=title if title else None,
                entry_type=entry_type,
                scope=scope,
                agent=None,
                created="",
                accessed="",
                access_count=0,
                decay_score=dscore,
                significance_tags=sig_tags,
                tags=[],
                content="",
                tier="",
                embedding=None,
            )

            if in_unclustered:
                unclustered.append(entry)
            elif current_cluster is not None:
                current_cluster.entries.append(entry)
            continue

        # Scope mapping rows
        if in_scope_mapping:
            m = _RE_SCOPE_ROW.match(stripped)
            if m:
                src_scope = m.group(1).strip()
                src_agent = m.group(2).strip()
                target = m.group(3).strip()
                # Skip header separators
                if src_scope.startswith("-") or src_scope.lower() == "source":
                    continue
                scope_mappings.append(ScopeMapping(
                    source_scope=src_scope,
                    source_agent=None if src_agent == "(none)" else src_agent,
                    target=target,
                ))

    # Don't forget the last cluster
    if current_cluster is not None:
        clusters.append(current_cluster)

    return CurateReport(
        project=project,
        generated_at=generated_at,
        total_entries=total_entries,
        clusters=clusters,
        scope_mappings=scope_mappings,
        unclustered=unclustered,
    )


# ---------------------------------------------------------------------------
# Apply report
# ---------------------------------------------------------------------------

def merge_entries(entries: list[ClusterEntry]) -> dict:
    """Merge multiple entries into a single entry dict.

    Uses highest decay_score as base, combines content and tags.
    """
    if not entries:
        return {}

    sorted_entries = sorted(entries, key=lambda e: e.decay_score, reverse=True)
    base = sorted_entries[0]
    others = sorted_entries[1:]

    # Combine content
    combined_content = base.content
    if others:
        bullets = []
        for o in others:
            title = o.title or "(untitled)"
            bullets.append(f"- **{title}**: {o.content[:200]}")
        combined_content = base.content + "\n\n---\n\n" + "\n".join(bullets)

    # Tags: union
    all_tags: set[str] = set(base.tags)
    for o in others:
        all_tags.update(o.tags)

    # Scope: broadest
    best_scope = base.scope
    for o in sorted_entries:
        if SCOPE_ORDER.get(o.scope, 1) > SCOPE_ORDER.get(best_scope, 1):
            best_scope = o.scope

    # Created: earliest
    created_dates = []
    for e in sorted_entries:
        if e.created:
            created_dates.append(e.created)
    earliest_created = min(created_dates) if created_dates else base.created

    return {
        "content": combined_content,
        "type": base.entry_type,
        "scope": best_scope,
        "title": base.title,
        "tags": sorted(all_tags) if all_tags else None,
        "created": earliest_created,
    }


def apply_report(report: CurateReport, store) -> dict:
    """Process an edited curation report and produce package-compatible entries.

    Returns dict with keys: kept, merged, dropped, total_output, entries.
    """
    kept = 0
    merged = 0
    dropped = 0
    output_entries: list[dict] = []

    # Build scope mapping lookup
    scope_map: dict[tuple[str, str | None], str] = {}
    for sm in report.scope_mappings:
        scope_map[(sm.source_scope, sm.source_agent)] = sm.target

    def _apply_scope(entry_dict: dict, source_scope: str, source_agent: str | None) -> dict:
        """Apply scope mapping to an entry dict."""
        target = scope_map.get((source_scope, source_agent))
        if target and target != source_scope:
            entry_dict["scope"] = target
        return entry_dict

    def _entry_to_dict(entry: ClusterEntry) -> dict:
        """Convert a ClusterEntry to a package-compatible dict, reading content from store."""
        # Try to read full content from store
        content = entry.content
        if not content and entry.full_id:
            result = store.read(entry.full_id)
            if result:
                _meta, content = result

        d: dict = {"content": content}
        if entry.entry_type:
            d["type"] = entry.entry_type
        if entry.scope:
            d["scope"] = entry.scope
        if entry.title:
            d["title"] = entry.title
        if entry.tags:
            d["tags"] = entry.tags
        if entry.created:
            d["created"] = entry.created
        if entry.agent:
            d["agent"] = entry.agent
        if entry.significance_tags:
            d["significance_tags"] = entry.significance_tags

        return _apply_scope(d, entry.scope, entry.agent)

    for cluster in report.clusters:
        rec = cluster.recommendation.upper()

        if rec == "DROP":
            dropped += len(cluster.entries)
            continue

        if rec == "MERGE":
            merged_entry = merge_entries(cluster.entries)
            if merged_entry:
                merged_entry = _apply_scope(
                    merged_entry,
                    merged_entry.get("scope", "team"),
                    None,
                )
                output_entries.append(merged_entry)
            merged += len(cluster.entries)
            continue

        # KEEP (default)
        for entry in cluster.entries:
            output_entries.append(_entry_to_dict(entry))
            kept += 1

    # Unclustered entries are always kept
    for entry in report.unclustered:
        output_entries.append(_entry_to_dict(entry))
        kept += 1

    return {
        "kept": kept,
        "merged": merged,
        "dropped": dropped,
        "total_output": len(output_entries),
        "entries": output_entries,
    }
