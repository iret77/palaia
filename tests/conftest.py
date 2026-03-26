"""Shared test fixtures for palaia."""

import pytest
from pathlib import Path

from palaia.config import DEFAULT_CONFIG, save_config
from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    """Create a minimal .palaia directory for testing."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    save_config(root, dict(DEFAULT_CONFIG))
    return root


@pytest.fixture
def store(palaia_root):
    """Create a Store instance for testing."""
    return Store(palaia_root)
