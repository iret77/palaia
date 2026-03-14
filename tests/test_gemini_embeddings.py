"""Tests for GeminiProvider embedding support (#34)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from palaia.embeddings import (
    GeminiProvider,
    _check_gemini_key,
    _create_provider,
    build_embedding_chain,
    detect_providers,
)


class TestGeminiProvider:
    """Unit tests for GeminiProvider."""

    def test_init_with_api_key(self):
        provider = GeminiProvider(api_key="test-key")
        assert provider.name == "gemini"
        assert provider.api_key == "test-key"
        assert provider.model_name == "gemini-embedding-exp-03-07"

    def test_init_with_custom_model(self):
        provider = GeminiProvider(model="text-embedding-004", api_key="test-key")
        assert provider.model_name == "text-embedding-004"

    def test_init_without_key_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            # Remove GEMINI_API_KEY if present
            import os

            env = dict(os.environ)
            env.pop("GEMINI_API_KEY", None)
            with patch.dict("os.environ", env, clear=True):
                with pytest.raises(ValueError, match="GEMINI_API_KEY not set"):
                    GeminiProvider()

    def test_init_from_env(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "env-key"}):
            provider = GeminiProvider()
            assert provider.api_key == "env-key"

    def test_embed_calls_batch_api(self):
        provider = GeminiProvider(api_key="test-key")
        mock_response = {
            "embeddings": [
                {"values": [0.1, 0.2, 0.3]},
                {"values": [0.4, 0.5, 0.6]},
            ]
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            result = provider.embed(["hello", "world"])

        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]
        assert result[1] == [0.4, 0.5, 0.6]

        # Verify the URL contains the model name and API key
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert "gemini-embedding-exp-03-07" in req.full_url
        assert "key=test-key" in req.full_url

    def test_embed_query_returns_single_vector(self):
        provider = GeminiProvider(api_key="test-key")
        mock_response = {"embeddings": [{"values": [0.7, 0.8, 0.9]}]}

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = provider.embed_query("test query")

        assert result == [0.7, 0.8, 0.9]

    def test_embed_request_body_structure(self):
        """Verify the request body matches Gemini batchEmbedContents format."""
        provider = GeminiProvider(api_key="test-key", model="text-embedding-004")
        mock_response = {"embeddings": [{"values": [0.1]}]}

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            provider.embed(["test text"])

        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        assert "requests" in body
        assert len(body["requests"]) == 1
        assert body["requests"][0]["model"] == "models/text-embedding-004"
        assert body["requests"][0]["content"]["parts"][0]["text"] == "test text"


class TestGeminiDetection:
    """Tests for Gemini in the provider detection chain."""

    def test_detect_providers_includes_gemini(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            providers = detect_providers()
        names = [p["name"] for p in providers]
        assert "gemini" in names

    def test_detect_providers_gemini_available_with_key(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            providers = detect_providers()
        gemini = next(p for p in providers if p["name"] == "gemini")
        assert gemini["available"] is True

    def test_detect_providers_gemini_unavailable_without_key(self):
        import os

        env = dict(os.environ)
        env.pop("GEMINI_API_KEY", None)
        with patch.dict("os.environ", env, clear=True):
            providers = detect_providers()
        gemini = next(p for p in providers if p["name"] == "gemini")
        assert gemini["available"] is False

    def test_check_gemini_key_from_env(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "my-key"}):
            assert _check_gemini_key() == "my-key"

    def test_check_gemini_key_missing(self):
        import os

        env = dict(os.environ)
        env.pop("GEMINI_API_KEY", None)
        with patch.dict("os.environ", env, clear=True):
            assert _check_gemini_key() is None

    def test_create_provider_gemini(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            provider = _create_provider("gemini")
        assert isinstance(provider, GeminiProvider)
        assert provider.model_name == "gemini-embedding-exp-03-07"

    def test_create_provider_gemini_custom_model(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            provider = _create_provider("gemini", model="text-embedding-004")
        assert provider.model_name == "text-embedding-004"


class TestGeminiInChain:
    """Tests for Gemini integration in the embedding chain."""

    def test_explicit_chain_with_gemini(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            config = {"embedding_chain": ["gemini", "bm25"]}
            chain = build_embedding_chain(config)
        assert "gemini" in chain.chain_names

    def test_gemini_chain_embed_with_mock(self):
        """Gemini in a chain works end-to-end with mocked API."""
        mock_response = {"embeddings": [{"values": [0.1, 0.2, 0.3]}]}

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            config = {"embedding_chain": ["gemini", "bm25"]}
            chain = build_embedding_chain(config)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            vector, provider_name = chain.embed_query("test")

        assert provider_name == "gemini"
        assert vector == [0.1, 0.2, 0.3]

    def test_gemini_fallback_on_error(self):
        """Chain falls back to BM25 if Gemini API fails."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            config = {"embedding_chain": ["gemini", "bm25"]}
            chain = build_embedding_chain(config)

        with patch("urllib.request.urlopen", side_effect=Exception("API error")):
            vector, provider_name = chain.embed_query("test")

        assert provider_name == "bm25"
        assert vector == []
