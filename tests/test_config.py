"""Tests for palaia.config module."""

import importlib


def test_palaia_home_env_overrides_cwd(tmp_path, monkeypatch):
    """PALAIA_HOME env var should override CWD-based search."""
    # Create .palaia in a custom location
    store = tmp_path / "custom" / ".palaia"
    store.mkdir(parents=True)
    (store / "config.json").write_text("{}")

    monkeypatch.setenv("PALAIA_HOME", str(store))

    # Reload to pick up env change
    import palaia.config
    from palaia.config import find_palaia_root

    importlib.reload(palaia.config)

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


def test_fallback_home_palaia(tmp_path, monkeypatch):
    """~/.palaia should be found when cwd walk fails."""
    monkeypatch.delenv("PALAIA_HOME", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    # Create ~/.palaia
    home_store = tmp_path / ".palaia"
    home_store.mkdir()
    (home_store / "config.json").write_text("{}")

    import palaia.config

    importlib.reload(palaia.config)
    from palaia.config import find_palaia_root

    # Start from a directory with no .palaia above it
    nowhere = tmp_path / "somewhere" / "deep"
    nowhere.mkdir(parents=True)
    result = find_palaia_root(start=str(nowhere))
    # Should find either via cwd walk (since it's under tmp_path) or via home fallback
    assert result is not None
    assert result.name == ".palaia"


def test_fallback_openclaw_workspace(tmp_path, monkeypatch):
    """~/.openclaw/workspace/.palaia should be found as last fallback."""
    monkeypatch.delenv("PALAIA_HOME", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    # Create ~/.openclaw/workspace/.palaia
    oc_store = tmp_path / ".openclaw" / "workspace" / ".palaia"
    oc_store.mkdir(parents=True)
    (oc_store / "config.json").write_text("{}")

    import palaia.config

    importlib.reload(palaia.config)
    from palaia.config import find_palaia_root

    # Start from root (no .palaia in cwd walk, no ~/.palaia)
    result = find_palaia_root(start="/")
    assert result == oc_store


def test_cwd_walk_preferred_over_fallbacks(tmp_path, monkeypatch):
    """CWD walk should find .palaia before fallback paths."""
    monkeypatch.delenv("PALAIA_HOME", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    # Create both cwd .palaia and home .palaia
    cwd_store = tmp_path / "projects" / "myproject" / ".palaia"
    cwd_store.mkdir(parents=True)
    (cwd_store / "config.json").write_text("{}")

    home_store = tmp_path / ".palaia"
    home_store.mkdir()
    (home_store / "config.json").write_text("{}")

    import palaia.config

    importlib.reload(palaia.config)
    from palaia.config import find_palaia_root

    # Start from within the project
    result = find_palaia_root(start=str(tmp_path / "projects" / "myproject"))
    assert result == cwd_store
