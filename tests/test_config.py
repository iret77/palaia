"""Tests for palaia.config module."""

import importlib

import pytest


def test_palaia_home_env_overrides_cwd(tmp_path, monkeypatch):
    """PALAIA_HOME env var should override CWD-based search."""
    # Create .palaia in a custom location
    store = tmp_path / "custom" / ".palaia"
    store.mkdir(parents=True)
    (store / "config.json").write_text("{}")

    monkeypatch.setenv("PALAIA_HOME", str(store))

    from palaia.config import find_palaia_root

    # Reload to pick up env change
    import palaia.config
    importlib.reload(palaia.config)
    from palaia.config import find_palaia_root

    result = find_palaia_root(start="/tmp/nowhere")
    assert result == store


def test_palaia_home_parent_dir(tmp_path, monkeypatch):
    """PALAIA_HOME pointing to parent dir containing .palaia."""
    parent = tmp_path / "workspace"
    store = parent / ".palaia"
    store.mkdir(parents=True)
    (store / "config.json").write_text("{}")

    monkeypatch.setenv("PALAIA_HOME", str(parent))

    import palaia.config
    importlib.reload(palaia.config)
    from palaia.config import find_palaia_root

    result = find_palaia_root(start="/tmp/nowhere")
    assert result == store


def test_palaia_home_invalid_ignored(tmp_path, monkeypatch):
    """Invalid PALAIA_HOME should fall back to CWD walk."""
    monkeypatch.setenv("PALAIA_HOME", "/nonexistent/path")

    # Create .palaia in tmp_path
    store = tmp_path / ".palaia"
    store.mkdir()
    (store / "config.json").write_text("{}")

    import palaia.config
    importlib.reload(palaia.config)
    from palaia.config import find_palaia_root

    result = find_palaia_root(start=str(tmp_path))
    assert result == store
