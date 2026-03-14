"""Tests for doctor version check (#45)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from palaia import __version__
from palaia.config import DEFAULT_CONFIG, save_config
from palaia.doctor import _check_version_available, run_doctor


@pytest.fixture
def palaia_root(tmp_path):
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index", "memos"):
        (root / sub).mkdir()
    config = dict(DEFAULT_CONFIG)
    config["agent"] = "test"
    save_config(root, config)
    return root


def _mock_pypi_response(version: str):
    """Create a mock urllib response with a specific version."""
    data = json.dumps({"info": {"version": version}}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = data
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def test_version_up_to_date(palaia_root):
    """Doctor reports ok when installed version matches PyPI."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_pypi_response(__version__)
        result = _check_version_available(palaia_root)

    assert result["status"] == "ok"
    assert "(latest)" in result["message"]


def test_version_update_available(palaia_root):
    """Doctor warns when a newer version is available."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_pypi_response("99.0.0")
        result = _check_version_available(palaia_root)

    assert result["status"] == "warn"
    assert "Update available" in result["message"]
    assert "99.0.0" in result["message"]
    assert "pip install --upgrade palaia" in result.get("fix", "")


def test_version_check_offline(palaia_root):
    """Doctor handles network failure gracefully."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = Exception("Network error")
        result = _check_version_available(palaia_root)

    assert result["status"] == "ok"
    assert "offline" in result["message"]


def test_version_check_timeout(palaia_root):
    """Doctor handles timeout gracefully."""
    import urllib.error

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = urllib.error.URLError("timeout")
        result = _check_version_available(palaia_root)

    assert result["status"] == "ok"
    assert "offline" in result["message"]


def test_version_check_in_run_doctor(palaia_root):
    """Version check is included in run_doctor results."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_pypi_response(__version__)
        results = run_doctor(palaia_root)

    names = [r["name"] for r in results]
    assert "version_check" in names


def test_version_check_details(palaia_root):
    """Version check includes installed and latest in details."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_pypi_response("99.0.0")
        result = _check_version_available(palaia_root)

    assert result["details"]["installed"] == __version__
    assert result["details"]["latest"] == "99.0.0"


def test_version_check_count(palaia_root):
    """run_doctor now has 15 checks (was 14)."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_pypi_response(__version__)
        results = run_doctor(palaia_root)

    assert len(results) == 15
