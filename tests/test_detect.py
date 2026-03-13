"""Tests for palaia detect CLI command output format."""

import sys
from io import StringIO
from unittest.mock import patch


def test_detect_output_format():
    """Test that palaia detect outputs the expected format with tables."""
    from palaia.cli import cmd_detect

    args = type("Args", (), {"json": False})()

    # Capture stdout
    captured = StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured

    try:
        with patch("palaia.embeddings._check_ollama_available", return_value=(False, None, [])):
            with patch("palaia.embeddings.importlib.util.find_spec", return_value=None):
                with patch("palaia.embeddings._check_openai_key", return_value=None):
                    with patch("palaia.embeddings._check_voyage_key", return_value=None):
                        cmd_detect(args)
    finally:
        sys.stdout = old_stdout

    output = captured.getvalue()

    # Check header
    assert "Palaia v" in output
    assert "Local memory for AI agents" in output
    # Check table sections
    assert "Environment" in output
    assert "Providers" in output
    assert "bm25" in output


def test_detect_json_output():
    """Test JSON output mode."""
    import json

    from palaia.cli import cmd_detect

    args = type("Args", (), {"json": True})()

    captured = StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured

    try:
        with patch("palaia.embeddings._check_ollama_available", return_value=(False, None, [])):
            with patch("palaia.embeddings.importlib.util.find_spec", return_value=None):
                with patch("palaia.embeddings._check_openai_key", return_value=None):
                    with patch("palaia.embeddings._check_voyage_key", return_value=None):
                        cmd_detect(args)
    finally:
        sys.stdout = old_stdout

    output = captured.getvalue()
    data = json.loads(output)

    assert "system" in data
    assert "python" in data
    assert "providers" in data
    assert isinstance(data["providers"], list)
    assert len(data["providers"]) == 5  # ollama, st, fastembed, openai, voyage


def test_detect_with_ollama_available():
    """Test detect when ollama is running."""
    from palaia.cli import cmd_detect

    args = type("Args", (), {"json": False})()

    captured = StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured

    try:
        with patch(
            "palaia.embeddings._check_ollama_available", return_value=(True, None, ["nomic-embed-text", "llama3"])
        ):
            with patch("palaia.embeddings.importlib.util.find_spec", return_value=None):
                with patch("palaia.embeddings._check_openai_key", return_value=None):
                    with patch("palaia.embeddings._check_voyage_key", return_value=None):
                        cmd_detect(args)
    finally:
        sys.stdout = old_stdout

    output = captured.getvalue()
    assert "ollama" in output
    assert "Recommendation" in output
