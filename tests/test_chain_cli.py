"""Tests for the config set-chain CLI command and chain integration."""

import json
import subprocess
import sys

import pytest

from palaia.config import load_config, save_config


@pytest.fixture
def palaia_dir(tmp_path):
    """Create a minimal .palaia directory."""
    pd = tmp_path / ".palaia"
    pd.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (pd / sub).mkdir()
    save_config(
        pd,
        {
            "version": 1,
            "embedding_provider": "auto",
            "embedding_model": "",
        },
    )
    return pd


def _run_palaia(args, cwd):
    """Run palaia CLI as subprocess."""
    result = subprocess.run(
        [sys.executable, "-m", "palaia.cli"] + args,
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )
    return result


def test_set_chain_writes_config(palaia_dir):
    """palaia config set-chain writes embedding_chain to config.json."""
    result = _run_palaia(
        ["config", "set-chain", "openai", "sentence-transformers", "bm25"],
        cwd=palaia_dir.parent,
    )
    assert result.returncode == 0
    assert "openai -> sentence-transformers -> bm25" in result.stdout

    config = load_config(palaia_dir)
    assert config["embedding_chain"] == ["openai", "sentence-transformers", "bm25"]


def test_set_chain_auto_appends_bm25(palaia_dir):
    """If bm25 not specified, it gets appended."""
    result = _run_palaia(
        ["config", "set-chain", "sentence-transformers"],
        cwd=palaia_dir.parent,
    )
    assert result.returncode == 0

    config = load_config(palaia_dir)
    assert config["embedding_chain"] == ["sentence-transformers", "bm25"]


def test_set_chain_invalid_provider(palaia_dir):
    """Unknown provider name → error."""
    result = _run_palaia(
        ["config", "set-chain", "magic-provider"],
        cwd=palaia_dir.parent,
    )
    assert result.returncode == 1
    assert "Unknown provider" in result.stderr


def test_set_chain_json_output(palaia_dir):
    """--json flag returns JSON."""
    result = _run_palaia(
        ["config", "set-chain", "--json", "openai", "bm25"],
        cwd=palaia_dir.parent,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["embedding_chain"] == ["openai", "bm25"]


def test_backward_compat_embedding_provider(palaia_dir):
    """Legacy embedding_provider still works when no embedding_chain."""
    save_config(
        palaia_dir,
        {
            "version": 1,
            "embedding_provider": "sentence-transformers",
            "embedding_model": "",
        },
    )
    from palaia.embeddings import build_embedding_chain

    config = load_config(palaia_dir)
    chain = build_embedding_chain(config)
    assert chain.chain_names == ["sentence-transformers", "bm25"]


def test_embedding_chain_overrides_provider(palaia_dir):
    """When both are set, embedding_chain wins."""
    save_config(
        palaia_dir,
        {
            "version": 1,
            "embedding_provider": "ollama",
            "embedding_chain": ["openai", "bm25"],
        },
    )
    from palaia.embeddings import build_embedding_chain

    config = load_config(palaia_dir)
    chain = build_embedding_chain(config)
    assert chain.chain_names == ["openai", "bm25"]
