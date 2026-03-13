"""Tests for search.py respecting embedding_chain config."""

from __future__ import annotations

from unittest.mock import patch

from palaia.search import _resolve_semantic_provider


def _fake_detect_providers():
    """Return fake provider list with fastembed + sentence-transformers available."""
    return [
        {"name": "ollama", "available": False},
        {"name": "sentence-transformers", "available": True, "version": "2.0"},
        {"name": "fastembed", "available": True, "version": "0.3"},
        {"name": "openai", "available": False},
        {"name": "voyage", "available": False},
    ]


@patch("palaia.search.detect_providers", _fake_detect_providers)
def test_chain_respects_order_fastembed_first():
    """When chain = ['fastembed', 'bm25'], fastembed must be used — not sentence-transformers."""
    config = {"embedding_chain": ["fastembed", "bm25"]}
    provider = _resolve_semantic_provider(config)
    assert provider.name == "fastembed"


@patch("palaia.search.detect_providers", _fake_detect_providers)
def test_chain_respects_order_st_first():
    """When chain = ['sentence-transformers', 'fastembed', 'bm25'], ST is used."""
    config = {"embedding_chain": ["sentence-transformers", "fastembed", "bm25"]}
    provider = _resolve_semantic_provider(config)
    assert provider.name == "sentence-transformers"


@patch("palaia.search.detect_providers", _fake_detect_providers)
def test_chain_skips_unavailable_provider():
    """When first chain entry is unavailable, next one is used."""
    config = {"embedding_chain": ["ollama", "fastembed", "bm25"]}
    provider = _resolve_semantic_provider(config)
    assert provider.name == "fastembed"


@patch("palaia.search.detect_providers", _fake_detect_providers)
def test_chain_only_bm25_falls_back_to_auto():
    """When chain = ['bm25'], fallback to auto_detect_provider."""
    config = {"embedding_chain": ["bm25"]}
    with patch("palaia.search.auto_detect_provider") as mock_auto:
        mock_auto.return_value = type("FakeProvider", (), {"name": "auto-detected"})()
        provider = _resolve_semantic_provider(config)
        mock_auto.assert_called_once_with(config)
        assert provider.name == "auto-detected"


@patch("palaia.search.detect_providers", _fake_detect_providers)
def test_empty_chain_falls_back_to_auto():
    """When chain is empty, fallback to auto_detect_provider."""
    config = {"embedding_chain": []}
    with patch("palaia.search.auto_detect_provider") as mock_auto:
        mock_auto.return_value = type("FakeProvider", (), {"name": "auto-detected"})()
        _resolve_semantic_provider(config)
        mock_auto.assert_called_once_with(config)


def test_no_chain_config_falls_back_to_auto():
    """When no embedding_chain in config, fallback to auto_detect_provider."""
    config = {}
    with patch("palaia.search.auto_detect_provider") as mock_auto:
        mock_auto.return_value = type("FakeProvider", (), {"name": "auto-detected"})()
        _resolve_semantic_provider(config)
        mock_auto.assert_called_once_with(config)


@patch("palaia.search.detect_providers", _fake_detect_providers)
def test_chain_all_semantic_unavailable_falls_back():
    """When all semantic providers in chain are unavailable, fall back to auto_detect."""
    config = {"embedding_chain": ["ollama", "openai", "bm25"]}
    with patch("palaia.search.auto_detect_provider") as mock_auto:
        mock_auto.return_value = type("FakeProvider", (), {"name": "auto-detected"})()
        _resolve_semantic_provider(config)
        mock_auto.assert_called_once_with(config)
