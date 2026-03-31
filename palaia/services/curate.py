"""Curation service layer — bridge between CLI and curate module."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from palaia import __version__
from palaia.curate import analyze, apply_report, generate_report, parse_report
from palaia.store import Store

logger = logging.getLogger(__name__)


def analyze_svc(root: Path, project: str | None = None, agent: str | None = None, output: str | None = None) -> dict:
    """Run curation analysis. Returns {report_path, cluster_count, entry_count}."""
    store = Store(root)
    report = analyze(store, project=project, agent=agent)
    markdown = generate_report(report)

    output_path = output or str(root / "curation-report.md")
    Path(output_path).write_text(markdown, encoding="utf-8")

    return {
        "report_path": output_path,
        "cluster_count": len(report.clusters),
        "entry_count": report.total_entries,
        "unclustered": len(report.unclustered),
    }


def apply_svc(root: Path, report_path: str, output: str | None = None, *, force: bool = False) -> dict:
    """Apply edited curation report. Returns {output_path, kept, merged, dropped}."""
    store = Store(root)
    markdown = Path(report_path).read_text(encoding="utf-8")
    report = parse_report(markdown)
    result = apply_report(report, store, force=force)

    output_path = output or str(root / "curated.palaia-pkg.json")
    package = {
        "palaia_package": "1.0",
        "palaia_version": __version__,
        "project": report.project,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "entry_count": len(result["entries"]),
        "entries": result["entries"],
    }
    Path(output_path).write_text(json.dumps(package, indent=2), encoding="utf-8")

    return {
        "output_path": output_path,
        "kept": result["kept"],
        "merged": result["merged"],
        "dropped": result["dropped"],
        "total_output": len(result["entries"]),
    }
