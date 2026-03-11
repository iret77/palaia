"""Tests for embedding providers and auto-detection."""

import pytest
from unittest.mock import patch, MagicMock

from palaia.embeddings import (
    OllamaProvider,
    SentenceTransformersProvider,
    FastEmbedProvider,
    OpenAIProvider,
    BM25Provider,
    auto_detect_provider,
    detect_providers,
    cosine_similarity,
    _check_ollama_available,
    _create_provider,
)


# --- Cosine Similarity ---

def test_cosine_similarity_identical():
    v = [1.0, 0.0, 0.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_similarity_zero_vector():
    a = [0.0, 0.0]
    b = [1.0, 1.0]
    assert cosine_similarity(a, b) == 0.0


# --- BM25Provider ---

def test_bm25_provider_search():
    bm25 = BM25Provider()
    bm25.index([
        ("doc1", "the cat sat on the mat"),
        ("doc2", "the dog played in the yard"),
        ("doc3", "cats and dogs are friends"),
    ])
    results = bm25.search("cat mat", top_k=2)
    assert len(results) > 0
    assert results[0][0] == "doc1"


def test_bm25_provider_embed_raises():
    bm25 = BM25Provider()
    with pytest.raises(NotImplementedError):
        bm25.embed(["hello"])
    with pytest.raises(NotImplementedError):
        bm25.embed_query("hello")


# --- OllamaProvider (mocked) ---

def test_ollama_provider_embed_mocked():
    provider = OllamaProvider(model="nomic-embed-text")
    mock_client = MagicMock()
    mock_client.embed.return_value = {"embeddings": [[0.1, 0.2, 0.3]]}
    provider._client = mock_client

    result = provider.embed(["hello world"])
    assert len(result) == 1
    assert result[0] == [0.1, 0.2, 0.3]
    mock_client.embed.assert_called_once()


def test_ollama_provider_embed_query_mocked():
    provider = OllamaProvider()
    mock_client = MagicMock()
    mock_client.embed.return_value = {"embeddings": [[0.5, 0.6]]}
    provider._client = mock_client

    result = provider.embed_query("test")
    assert result == [0.5, 0.6]


# --- SentenceTransformersProvider (mocked) ---

def test_sentence_transformers_provider_mocked():
    provider = SentenceTransformersProvider(model="all-MiniLM-L6-v2")
    # Use a mock that returns list-like objects (simulating numpy arrays with .tolist())
    mock_arr = MagicMock()
    mock_arr.__iter__ = lambda self: iter([MagicMock(tolist=lambda: [0.1, 0.2]), MagicMock(tolist=lambda: [0.3, 0.4])])
    
    class FakeArray:
        def __init__(self, data):
            self._data = data
        def __iter__(self):
            return iter(self._data)
        def tolist(self):
            return self._data
    
    class FakeResult:
        def __init__(self, rows):
            self._rows = [FakeArray(r) for r in rows]
        def __iter__(self):
            return iter(self._rows)
    
    mock_model = MagicMock()
    mock_model.encode.return_value = FakeResult([[0.1, 0.2], [0.3, 0.4]])
    provider._model = mock_model

    result = provider.embed(["hello", "world"])
    assert len(result) == 2
    assert result[0] == pytest.approx([0.1, 0.2])
    mock_model.encode.assert_called_once()


def test_sentence_transformers_query_mocked():
    provider = SentenceTransformersProvider()
    
    class FakeArray:
        def __init__(self, data):
            self._data = data
        def tolist(self):
            return self._data
    
    class FakeResult:
        def __init__(self, rows):
            self._rows = [FakeArray(r) for r in rows]
        def __iter__(self):
            return iter(self._rows)
    
    mock_model = MagicMock()
    mock_model.encode.return_value = FakeResult([[0.7, 0.8]])
    provider._model = mock_model

    result = provider.embed_query("test")
    assert result == pytest.approx([0.7, 0.8])


# --- FastEmbedProvider (mocked) ---

def test_fastembed_provider_mocked():
    provider = FastEmbedProvider(model="BAAI/bge-small-en-v1.5")
    
    class FakeArray:
        def __init__(self, data):
            self._data = data
        def tolist(self):
            return self._data
        def __iter__(self):
            return iter(self._data)
    
    mock_model = MagicMock()
    mock_model.embed.return_value = [FakeArray([0.1, 0.2]), FakeArray([0.3, 0.4])]
    provider._model = mock_model

    result = provider.embed(["hello", "world"])
    assert len(result) == 2
    assert result[0] == pytest.approx([0.1, 0.2])


# --- OpenAIProvider (mocked) ---

def test_openai_provider_mocked():
    provider = OpenAIProvider(model="text-embedding-3-small", api_key="test-key")
    mock_client = MagicMock()
    mock_data = MagicMock()
    mock_data.embedding = [0.1, 0.2, 0.3]
    mock_resp = MagicMock()
    mock_resp.data = [mock_data]
    mock_client.embeddings.create.return_value = mock_resp
    provider._client = mock_client

    result = provider.embed(["hello"])
    assert result == [[0.1, 0.2, 0.3]]


# --- Auto-Detect ---

def test_auto_detect_none_config():
    result = auto_detect_provider({"embedding_provider": "none"})
    assert isinstance(result, BM25Provider)


def test_auto_detect_explicit_bm25():
    result = auto_detect_provider({"embedding_provider": "bm25"})
    assert isinstance(result, BM25Provider)


def test_auto_detect_explicit_ollama():
    result = _create_provider("ollama", "nomic-embed-text")
    assert isinstance(result, OllamaProvider)
    assert result.model == "nomic-embed-text"


def test_auto_detect_explicit_sentence_transformers():
    result = _create_provider("sentence-transformers")
    assert isinstance(result, SentenceTransformersProvider)


def test_auto_detect_explicit_fastembed():
    result = _create_provider("fastembed")
    assert isinstance(result, FastEmbedProvider)


def test_auto_detect_explicit_openai():
    result = _create_provider("openai")
    assert isinstance(result, OpenAIProvider)


def test_auto_detect_unknown_provider():
    with pytest.raises(ValueError, match="Unknown embedding provider"):
        _create_provider("unknown_provider")


@patch("palaia.embeddings.detect_providers")
def test_auto_detect_prefers_ollama(mock_detect):
    mock_detect.return_value = [
        {"name": "ollama", "available": True},
        {"name": "sentence-transformers", "available": True},
        {"name": "fastembed", "available": False},
        {"name": "openai", "available": True},
        {"name": "voyage", "available": False},
    ]
    result = auto_detect_provider({"embedding_provider": "auto"})
    assert isinstance(result, OllamaProvider)


@patch("palaia.embeddings.detect_providers")
def test_auto_detect_falls_to_st_when_no_ollama(mock_detect):
    mock_detect.return_value = [
        {"name": "ollama", "available": False},
        {"name": "sentence-transformers", "available": True},
        {"name": "fastembed", "available": False},
        {"name": "openai", "available": False},
        {"name": "voyage", "available": False},
    ]
    result = auto_detect_provider({"embedding_provider": "auto"})
    assert isinstance(result, SentenceTransformersProvider)


@patch("palaia.embeddings.detect_providers")
def test_auto_detect_falls_to_bm25_when_nothing(mock_detect):
    mock_detect.return_value = [
        {"name": "ollama", "available": False},
        {"name": "sentence-transformers", "available": False},
        {"name": "fastembed", "available": False},
        {"name": "openai", "available": False},
        {"name": "voyage", "available": False},
    ]
    result = auto_detect_provider({"embedding_provider": "auto"})
    assert isinstance(result, BM25Provider)


@patch("palaia.embeddings.detect_providers")
def test_auto_detect_fastembed_over_openai(mock_detect):
    mock_detect.return_value = [
        {"name": "ollama", "available": False},
        {"name": "sentence-transformers", "available": False},
        {"name": "fastembed", "available": True},
        {"name": "openai", "available": True},
        {"name": "voyage", "available": False},
    ]
    result = auto_detect_provider({"embedding_provider": "auto"})
    assert isinstance(result, FastEmbedProvider)


# --- detect_providers ---

@patch("palaia.embeddings._check_ollama_available", return_value=(True, None, ["nomic-embed-text", "llama3"]))
@patch("palaia.embeddings.importlib.util.find_spec", return_value=None)
@patch("palaia.embeddings._check_openai_key", return_value=None)
@patch("palaia.embeddings._check_voyage_key", return_value=None)
def test_detect_providers_ollama_only(mock_voyage, mock_openai, mock_spec, mock_ollama):
    providers = detect_providers()
    ollama_p = next(p for p in providers if p["name"] == "ollama")
    assert ollama_p["available"] is True
    assert ollama_p["has_nomic"] is True


@patch("palaia.embeddings._check_ollama_available", return_value=(False, None, []))
@patch("palaia.embeddings.importlib.util.find_spec", return_value=None)
@patch("palaia.embeddings._check_openai_key", return_value=None)
@patch("palaia.embeddings._check_voyage_key", return_value=None)
def test_detect_providers_nothing_available(mock_voyage, mock_openai, mock_spec, mock_ollama):
    providers = detect_providers()
    for p in providers:
        assert p["available"] is False
