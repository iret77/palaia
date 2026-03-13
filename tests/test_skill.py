"""Tests for the `palaia skill` command."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _run_skill(*extra_args: str) -> subprocess.CompletedProcess:
    """Run `palaia skill` as a subprocess."""
    return subprocess.run(
        [sys.executable, "-m", "palaia", "skill", *extra_args],
        capture_output=True,
        text=True,
    )


def test_skill_prints_content():
    """palaia skill should print SKILL.md content to stdout."""
    result = _run_skill()
    assert result.returncode == 0
    assert "palaia" in result.stdout.lower()
    # Check for expected markers in the SKILL.md
    assert "memory" in result.stdout.lower() or "Memory" in result.stdout


def test_skill_json():
    """palaia skill --json should return valid JSON with 'skill' key."""
    result = _run_skill("--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "skill" in data
    assert isinstance(data["skill"], str)
    assert len(data["skill"]) > 100  # SKILL.md should be substantial


def test_skill_json_contains_markers():
    """JSON output should contain expected SKILL.md content markers."""
    result = _run_skill("--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    content = data["skill"]
    # The SKILL.md frontmatter has name: palaia
    assert "palaia" in content.lower()


def test_skill_no_init_required():
    """palaia skill should work without palaia init (ungated command)."""
    import tempfile

    # Run in a temp directory with no .palaia
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [sys.executable, "-m", "palaia", "skill"],
            capture_output=True,
            text=True,
            cwd=tmpdir,
        )
        assert result.returncode == 0
        assert "palaia" in result.stdout.lower()


def test_skill_missing_file_error():
    """If SKILL.md is missing, show error with GitHub URL."""
    skill_path = Path(__file__).parent.parent / "palaia" / "SKILL.md"
    if not skill_path.exists():
        pytest.skip("SKILL.md not in expected location")

    backup = skill_path.with_suffix(".md.bak")
    try:
        skill_path.rename(backup)
        result = _run_skill()
        assert result.returncode == 1
        assert "github.com" in result.stderr.lower()

        # Also test JSON mode
        result_json = _run_skill("--json")
        assert result_json.returncode == 1
        data = json.loads(result_json.stdout)
        assert "error" in data
        assert "github.com" in data["error"].lower()
    finally:
        backup.rename(skill_path)
