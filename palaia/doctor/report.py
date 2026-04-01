"""Palaia doctor report formatting."""

from __future__ import annotations

from typing import Any


def format_doctor_report(results: list[dict[str, Any]], show_fix: bool = False) -> str:
    """Format doctor results as a modern, symbol-based report."""
    from palaia.ui import (
        bold,
        dim,
        header,
        status_label,
        sym_arrow,
        truncate,
    )

    lines = [f"\n  {header()}", f"\n  {bold('Health Report')}\n"]

    warnings = 0
    errors = 0

    for r in results:
        status = r["status"]
        label = r["label"]
        message = r["message"]

        sym = status_label(status)
        # Pad label for alignment
        label_str = label.ljust(24)
        lines.append(f"  {sym}  {label_str}{dim(message)}")

        if status == "warn":
            warnings += 1
        elif status == "error":
            errors += 1

    # Fix guidance
    if show_fix:
        fix_lines = []
        for r in results:
            if r["status"] in ("warn", "error") and "fix" in r:
                fix_lines.append(f"\n    {r['label']}:")
                for fl in r["fix"].split("\n"):
                    fix_lines.append(f"      {fl}")
        if fix_lines:
            lines.append(f"\n  {bold('Fix guidance:')}")
            lines.extend(fix_lines)
    else:
        for r in results:
            if r["status"] in ("warn", "error") and "fix" in r:
                first_fix = r["fix"].split("\n")[0]
                lines.append(f"    {sym_arrow()} {r['label']}: {dim(first_fix)}")

    # Summary
    if errors and warnings:
        lines.append(f"\n  {errors} error(s), {warnings} warning(s) {dim('— run')} palaia doctor --fix")
    elif errors:
        lines.append(f"\n  {errors} error(s) {dim('— fix before using palaia')}")
    elif warnings:
        suffix = dim("— see fixes above") if show_fix else dim("— run") + " palaia doctor --fix"
        lines.append(f"\n  {warnings} warning(s) {suffix}")
    else:
        lines.append(f"\n  {status_label('ok')} All clear")

    return "\n".join(lines)
