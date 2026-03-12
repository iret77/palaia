"""Palaia configuration management."""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_CONFIG = {
    "version": 1,
    "decay_lambda": 0.1,
    "hot_threshold_days": 7,
    "warm_threshold_days": 30,
    "hot_max_entries": 50,
    "hot_min_score": 0.5,
    "warm_min_score": 0.1,
    "default_scope": "team",
    "wal_retention_days": 7,
    "lock_timeout_seconds": 5,
    "embedding_provider": "auto",
    "embedding_model": "",
    "store_version": "",  # Set to palaia __version__ on init/upgrade
}


def find_palaia_root(start: str = ".") -> Path | None:
    """Walk up from start to find .palaia directory.

    Checks PALAIA_HOME env var first, then walks up from start.
    """
    # Check PALAIA_HOME env var first
    env_home = os.environ.get("PALAIA_HOME")
    if env_home:
        env_path = Path(env_home)
        # PALAIA_HOME points directly to a .palaia directory
        if env_path.is_dir() and env_path.name == ".palaia":
            return env_path
        # PALAIA_HOME points to parent dir containing .palaia
        candidate = env_path / ".palaia"
        if candidate.is_dir():
            return candidate

    # Walk up from start directory
    current = Path(start).resolve()
    while True:
        candidate = current / ".palaia"
        if candidate.is_dir():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


def get_root(start: str = ".") -> Path:
    """Get .palaia root or raise."""
    root = find_palaia_root(start)
    if root is None:
        raise FileNotFoundError("No .palaia directory found. Run 'palaia init' first.")
    return root


def load_config(palaia_root: Path) -> dict:
    """Load config from .palaia/config.json, merged with defaults."""
    config_path = palaia_root / "config.json"
    config = dict(DEFAULT_CONFIG)
    if config_path.exists():
        with open(config_path, "r") as f:
            user_config = json.load(f)
        config.update(user_config)
    return config


def save_config(palaia_root: Path, config: dict) -> None:
    """Save config to .palaia/config.json."""
    config_path = palaia_root / "config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
