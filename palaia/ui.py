"""palaia UI — Modern CLI design system.

Zero external dependencies. ANSI colors with TTY detection and NO_COLOR support.
All CLI output flows through this module for consistency.

Design principles:
  - Symbols + color + text — never rely on one channel alone
  - TTY-aware: colors and symbols only in interactive terminals
  - NO_COLOR respected (https://no-color.org)
  - Whitespace over decoration — no box-drawing borders
  - Dim for secondary, bold for primary
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from typing import Sequence

logger = logging.getLogger(__name__)

from palaia import __version__

# ── Color system ────────────────────────────────────────────────────────────

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"


def is_tty(stream=None) -> bool:
    """Check if the given stream (default: stdout) is a TTY."""
    if stream is None:
        stream = sys.stdout
    try:
        return hasattr(stream, "isatty") and stream.isatty()
    except Exception:
        return False


def use_color(stream=None) -> bool:
    """Determine whether to use ANSI colors.

    Respects NO_COLOR env var (https://no-color.org) and FORCE_COLOR.
    """
    if os.environ.get("FORCE_COLOR"):
        return True
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return is_tty(stream)


def _c(code: str, text: str, stream=None) -> str:
    """Apply ANSI color code if colors are enabled."""
    if use_color(stream):
        return f"{code}{text}{_RESET}"
    return text


def green(text: str) -> str:
    """Green text (success)."""
    return _c(_GREEN, text)


def red(text: str) -> str:
    """Red text (error)."""
    return _c(_RED, text)


def yellow(text: str) -> str:
    """Yellow text (warning)."""
    return _c(_YELLOW, text)


def cyan(text: str) -> str:
    """Cyan text (info, links, values)."""
    return _c(_CYAN, text)


def dim(text: str) -> str:
    """Dim text (secondary info, IDs, paths)."""
    return _c(_DIM, text)


def bold(text: str) -> str:
    """Bold text (emphasis)."""
    return _c(_BOLD, text)


# ── Symbols ─────────────────────────────────────────────────────────────────

def _sym(colored: str, plain: str) -> str:
    """Return Unicode symbol if TTY, plain fallback otherwise."""
    if is_tty():
        return colored
    return plain


SYM_OK = property(lambda self: None)  # use sym_ok() instead


def sym_ok() -> str:
    return _sym(green("\u2713"), "ok")


def sym_err() -> str:
    return _sym(red("\u2717"), "error")


def sym_warn() -> str:
    return _sym(yellow("\u26a0"), "warn")


def sym_info() -> str:
    return _sym(cyan("\u2139"), "info")


def sym_arrow() -> str:
    return _sym(dim("\u2192"), "->")


def sym_bullet() -> str:
    return _sym(dim("\u25b8"), "-")


# ── Formatted output helpers ────────────────────────────────────────────────


def success(msg: str) -> str:
    """Format a success message: ✓ msg"""
    return f"  {sym_ok()} {msg}"


def error_msg(msg: str) -> str:
    """Format an error message: ✗ msg"""
    return f"  {sym_err()} {msg}"


def warn_msg(msg: str) -> str:
    """Format a warning message: ⚠ msg"""
    return f"  {sym_warn()} {msg}"


def info_msg(msg: str) -> str:
    """Format an info message: ℹ msg"""
    return f"  {sym_info()} {msg}"


def hint_msg(msg: str) -> str:
    """Format a hint (printed to stderr)."""
    return f"  {sym_info()} {dim('Hint:')} {msg}"


def error_block(title: str, explanation: str = "", fix: str = "") -> str:
    """Format a verbose error with explanation and fix suggestion.

    Example:
      ✗ No palaia store found

        Run palaia init to create one, or set PALAIA_ROOT.
    """
    lines = [error_msg(title)]
    if explanation:
        lines.append(f"\n    {explanation}")
    if fix:
        lines.append(f"    {bold(fix)}")
    return "\n".join(lines)


# ── Terminal helpers ─────────────────────────────────────────────────────────


def terminal_width() -> int:
    """Get terminal width, default 80 if unavailable."""
    try:
        return shutil.get_terminal_size((80, 24)).columns
    except Exception:
        return 80


def truncate(text: str, max_len: int, suffix: str = "..") -> str:
    """Truncate text to max_len, appending suffix if truncated."""
    if len(text) <= max_len:
        return text
    if max_len <= len(suffix):
        return text[:max_len]
    return text[: max_len - len(suffix)] + suffix


# ── Header / Branding ──────────────────────────────────────────────────────

HEADER_LINE = f"palaia v{__version__}"


def header() -> str:
    """Return compact version string."""
    return dim(HEADER_LINE)


def print_header() -> None:
    """Print the compact header."""
    print(f"\n  {header()}\n")


# ── Status label ────────────────────────────────────────────────────────────


def status_label(status: str) -> str:
    """Return a styled status label.

    ok    → ✓ (green)
    warn  → ⚠ (yellow)
    error → ✗ (red)
    info  → ℹ (cyan)
    skip  → - (dim)
    """
    labels = {
        "ok": sym_ok,
        "warn": sym_warn,
        "error": sym_err,
        "info": sym_info,
        "skip": lambda: dim("-"),
    }
    fn = labels.get(status, lambda: f"[{status}]")
    return fn()


# ── Table rendering (modern, borderless) ─────────────────────────────────


def table_kv(rows: Sequence[tuple[str, str]], key_min: int = 16, val_min: int = 20) -> str:
    """Render a key-value table (no borders, dim keys).

    Example output:
      Root             /home/user/.palaia
      Store version    v2.5.0
      Backend          SQLITE — sqlite-vec SIMD
    """
    if not rows:
        return ""

    tw = terminal_width()
    max_key = max((len(r[0]) for r in rows), default=key_min)
    kw = max(max_key, key_min)
    # Cap key width to leave room for value
    kw = min(kw, tw // 3)
    vw = tw - kw - 6  # 4 leading spaces + 2 gap

    lines: list[str] = []
    for key, val in rows:
        k = truncate(key, kw).ljust(kw)
        v = truncate(val, max(vw, val_min))
        lines.append(f"    {dim(k)}  {v}")

    return "\n".join(lines)


def _multi_col_widths(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    min_widths: Sequence[int] | None = None,
) -> list[int]:
    """Calculate column widths for a multi-column table."""
    tw = terminal_width()
    n = len(headers)
    if min_widths is None:
        min_widths = [6] * n

    widths = []
    for i in range(n):
        col_max = max(
            len(headers[i]),
            max((len(str(row[i])) for row in rows), default=0),
            min_widths[i],
        )
        widths.append(col_max)

    # Overhead: 4 leading spaces + 2-space gaps between columns
    overhead = 4 + (n - 1) * 2
    total = overhead + sum(widths)

    if total > tw and tw > overhead + sum(min_widths):
        budget = tw - overhead
        shares = [w / sum(widths) * budget for w in widths]
        for i in range(n):
            widths[i] = max(min_widths[i], min(widths[i], int(shares[i])))

    return widths


def table_multi(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    min_widths: Sequence[int] | None = None,
) -> str:
    """Render a multi-column table with dim header row (no borders).

    Example output:
      ID        Score   Tier  Title              Preview
      050d2e70  0.87    hot   Deploy process      staging env setup
      a1b2c3d4  0.72    warm  Production deploy   checklist for prod
    """
    if not headers:
        return ""

    n = len(headers)
    widths = _multi_col_widths(headers, rows, min_widths)
    lines: list[str] = []

    def format_row(cells: Sequence[str], is_header: bool = False) -> str:
        parts = []
        for i, cell in enumerate(cells):
            text = truncate(str(cell), widths[i]).ljust(widths[i])
            if is_header:
                text = dim(text)
            parts.append(text)
        return "    " + "  ".join(parts)

    # Header
    lines.append(format_row(headers, is_header=True))

    # Data rows
    for row in rows:
        padded = list(row) + [""] * (n - len(row))
        lines.append(format_row(padded[:n]))

    return "\n".join(lines)


# ── Section helpers ──────────────────────────────────────────────────────────


def section(title: str) -> str:
    """Return a section title (bold, indented)."""
    return f"\n  {bold(title)}"


# ── Age / relative time ─────────────────────────────────────────────────────


def relative_time(iso_str: str) -> str:
    """Convert an ISO datetime string to a relative time like '2m ago', '3h ago', '5d ago'."""
    if not iso_str:
        return "unknown"
    try:
        from datetime import datetime, timezone

        if iso_str.endswith("Z"):
            iso_str = iso_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - dt
        seconds = int(delta.total_seconds())

        if seconds < 0:
            return "just now"
        if seconds < 60:
            return f"{seconds}s ago"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        if seconds < 86400:
            return f"{seconds // 3600}h ago"
        days = seconds // 86400
        if days < 30:
            return f"{days}d ago"
        if days < 365:
            return f"{days // 30}mo ago"
        return f"{days // 365}y ago"
    except Exception:
        return "unknown"


# ── Disk size formatting ─────────────────────────────────────────────────────


def format_size(bytes_val: int) -> str:
    """Format bytes into human-readable size."""
    if bytes_val < 1024:
        return f"{bytes_val} B"
    if bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f} KB"
    if bytes_val < 1024 * 1024 * 1024:
        return f"{bytes_val / (1024 * 1024):.1f} MB"
    return f"{bytes_val / (1024 * 1024 * 1024):.1f} GB"


# ── Score bar ────────────────────────────────────────────────────────────────


def score_display(score: float, width: int = 10) -> str:
    """Render a score as a compact numeric value.

    Example: 0.87
    """
    return f"{score:.2f}"


# ── Backward compatibility ──────────────────────────────────────────────────

# Old constants preserved for any external consumers
HEADER_URL = ""

# Box-drawing chars (kept for any code that imports them directly)
B_TL = "\u250c"
B_TR = "\u2510"
B_BL = "\u2514"
B_BR = "\u2518"
B_H = "\u2500"
B_V = "\u2502"
B_LT = "\u251c"
B_RT = "\u2524"
B_TT = "\u252c"
B_BT = "\u2534"
B_X = "\u253c"
