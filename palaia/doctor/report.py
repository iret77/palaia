"""Palaia doctor report formatting."""

from __future__ import annotations

from typing import Any


def format_doctor_report(results: list[dict[str, Any]], show_fix: bool = False) -> str:
    """Format doctor results as a human-readable report using box-drawing tables."""
    from palaia.ui import header, section, table_multi

    lines = [header()]
    lines.append(section("Health Report"))

    # Build table rows
    table_rows = []
    warnings = 0
    errors = 0

    for r in results:
        status = r["status"]
        label = r["label"]
        message = r["message"]
        status_str = f"[{status}]"
        table_rows.append((status_str, label, message))

        if status == "warn":
            warnings += 1
        elif status == "error":
            errors += 1

    lines.append(
        table_multi(
            headers=("Status", "Check", "Details"),
            rows=table_rows,
            min_widths=(8, 22, 30),
        )
    )

    # Show fix details below table if requested
    if show_fix:
        fix_lines = []
        for r in results:
            if r["status"] == "warn" and "fix" in r:
                fix_lines.append(f"\n  {r['label']}:")
                for fl in r["fix"].split("\n"):
                    fix_lines.append(f"    {fl}")
        if fix_lines:
            lines.append("\nFix guidance:")
            lines.extend(fix_lines)
    else:
        # Show inline fix hints for warnings
        for r in results:
            if r["status"] == "warn" and "fix" in r:
                first_fix = r["fix"].split("\n")[0]
                lines.append(f"  {r['label']}: {first_fix}")

    # Summary
    if errors:
        lines.append(f"\nErrors: {errors} — fix before using Palaia")
    elif warnings:
        suffix = " — see fixes above" if show_fix else " — run with --fix for guided cleanup"
        lines.append(f"\nAction required: {warnings} warning(s){suffix}")
    else:
        lines.append("\nAll clear. Palaia is healthy.")

    return "\n".join(lines)
