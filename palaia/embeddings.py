"""Multi-provider embedding support for semantic search.

Providers are detected automatically in this order:
1. ollama (local server with nomic-embed-text)
2. sentence-transformers (pure Python)
3. fastembed (lightweight)
4. OpenAI API (cloud, needs key)
5. BM25 (always available, keyword-based fallback)
"""

from __future__ import annotations

import importlib.metadata as _importlib_metadata
import importlib.util
import math
import os
import re
import warnings
from collections import Counter
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for embedding providers."""

    name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns list of vectors."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query text. Returns a vector."""
        ...


class OllamaProvider:
    """Embedding via local ollama server."""

    name = "ollama"
    default_model = "nomic-embed-text"

    def __init__(self, model: str | None = None, base_url: str = "http://localhost:11434"):
        self.model = model or self.default_model
        self.base_url = base_url
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import ollama as ollama_lib
                self._client = ollama_lib.Client(host=self.base_url)
            except ImportError:
                # Fall back to raw HTTP
                self._client = "http"
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        client = self._get_client()
        if client == "http":
            return [self._embed_http(t) for t in texts]
        results = []
        for text in texts:
            resp = client.embed(model=self.model, input=text)
            # ollama returns {"embeddings": [[...]]}
            if isinstance(resp, dict) and "embeddings" in resp:
                results.append(resp["embeddings"][0])
            else:
                results.append(resp.embeddings[0] if hasattr(resp, 'embeddings') else [])
        return results

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def _embed_http(self, text: str) -> list[float]:
        import json
        import urllib.request
        data = json.dumps({"model": self.model, "input": text}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        return result.get("embeddings", [[]])[0]


class SentenceTransformersProvider:
    """Embedding via sentence-transformers library."""

    name = "sentence-transformers"
    default_model = "all-MiniLM-L6-v2"

    def __init__(self, model: str | None = None):
        self.model_name = model or self.default_model
        self._model = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        embeddings = model.encode(texts, convert_to_numpy=True)
        return [e.tolist() for e in embeddings]

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]


class FastEmbedProvider:
    """Embedding via fastembed library."""

    name = "fastembed"
    default_model = "BAAI/bge-small-en-v1.5"

    def __init__(self, model: str | None = None):
        self.model_name = model or self.default_model
        self._model = None

    def _get_model(self):
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        embeddings = list(model.embed(texts))
        return [e.tolist() if hasattr(e, 'tolist') else list(e) for e in embeddings]

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]


class OpenAIProvider:
    """Embedding via OpenAI API."""

    name = "openai"
    default_model = "text-embedding-3-small"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model_name = model or self.default_model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key)
            except ImportError:
                self._client = "http"
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        client = self._get_client()
        if client == "http":
            return self._embed_http(texts)
        resp = client.embeddings.create(model=self.model_name, input=texts)
        return [d.embedding for d in resp.data]

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def _embed_http(self, texts: list[str]) -> list[list[float]]:
        import json
        import urllib.request
        data = json.dumps({"model": self.model_name, "input": texts}).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/embeddings",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        return [d["embedding"] for d in result["data"]]


class BM25Provider:
    """Keyword-based search provider. Always available, no vectors."""

    name = "bm25"

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus: list[tuple[str, list[str]]] = []
        self.doc_freqs: Counter = Counter()
        self.doc_lens: list[int] = []
        self.avg_dl: float = 0.0
        self.n_docs: int = 0

    def index(self, documents: list[tuple[str, str]]) -> None:
        """Index a list of (doc_id, text) tuples."""
        self.corpus = []
        self.doc_freqs = Counter()
        self.doc_lens = []

        for doc_id, text in documents:
            tokens = _tokenize(text)
            self.corpus.append((doc_id, tokens))
            self.doc_lens.append(len(tokens))
            seen = set(tokens)
            for t in seen:
                self.doc_freqs[t] += 1

        self.n_docs = len(self.corpus)
        self.avg_dl = sum(self.doc_lens) / self.n_docs if self.n_docs else 1.0

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Search the index. Returns list of (doc_id, score) sorted desc."""
        query_tokens = _tokenize(query)
        if not query_tokens or not self.corpus:
            return []

        scores = []
        for idx, (doc_id, doc_tokens) in enumerate(self.corpus):
            score = 0.0
            dl = self.doc_lens[idx]
            tf_map = Counter(doc_tokens)

            for qt in query_tokens:
                if qt not in tf_map:
                    continue
                tf = tf_map[qt]
                df = self.doc_freqs.get(qt, 0)
                idf = math.log((self.n_docs - df + 0.5) / (df + 0.5) + 1.0)
                tf_norm = (tf * (self.k1 + 1)) / (
                    tf + self.k1 * (1 - self.b + self.b * dl / self.avg_dl)
                )
                score += idf * tf_norm

            if score > 0:
                scores.append((doc_id, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Not applicable for BM25. Raises NotImplementedError."""
        raise NotImplementedError("BM25 does not produce embedding vectors")

    def embed_query(self, text: str) -> list[float]:
        """Not applicable for BM25. Raises NotImplementedError."""
        raise NotImplementedError("BM25 does not produce embedding vectors")


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer."""
    text = text.lower()
    return re.findall(r"\b\w+\b", text)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _check_ollama_available(base_url: str = "http://localhost:11434") -> tuple[bool, str | None, list[str]]:
    """Check if ollama server is running and which models are available.
    
    Returns: (server_running, version_or_none, list_of_models)
    """
    import json
    import urllib.request
    try:
        req = urllib.request.Request(f"{base_url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        models = [m.get("name", "").split(":")[0] for m in data.get("models", [])]
        return True, None, models
    except Exception:
        return False, None, []


def _check_openai_key() -> str | None:
    """Check for OpenAI API key in env or openclaw auth."""
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    # Check openclaw auth profiles
    auth_dir = os.path.expanduser("~/.openclaw")
    for candidate in ["auth.json", "config.json"]:
        path = os.path.join(auth_dir, candidate)
        if os.path.exists(path):
            try:
                import json
                with open(path) as f:
                    data = json.load(f)
                # Look for openai key in various formats
                if isinstance(data, dict):
                    if "openai_api_key" in data:
                        return data["openai_api_key"]
                    for profile in data.values():
                        if isinstance(profile, dict) and "openai_api_key" in profile:
                            return profile["openai_api_key"]
            except (OSError, ValueError):
                pass
    return None


def _check_voyage_key() -> str | None:
    """Check for Voyage API key in env."""
    return os.environ.get("VOYAGE_API_KEY")


def detect_providers() -> list[dict]:
    """Detect all available embedding providers.
    
    Returns list of dicts with keys: name, available, version, models, install_hint
    """
    providers = []

    # 1. ollama
    server_running, version, models = _check_ollama_available()
    has_nomic = "nomic-embed-text" in models if models else False
    providers.append({
        "name": "ollama",
        "available": server_running and has_nomic,
        "server_running": server_running,
        "models": models,
        "has_nomic": has_nomic,
        "version": version,
        "install_hint": None if server_running else "curl -fsSL https://ollama.com/install.sh | sh && ollama pull nomic-embed-text",
    })

    # 2. sentence-transformers
    st_spec = importlib.util.find_spec("sentence_transformers")
    st_version = None
    if st_spec:
        try:
            # already imported as _importlib_metadata
            st_version = _importlib_metadata.version("sentence-transformers")
        except Exception:
            st_version = "installed"
    providers.append({
        "name": "sentence-transformers",
        "available": st_spec is not None,
        "version": st_version,
        "install_hint": 'pip install "palaia[sentence-transformers]"' if not st_spec else None,
    })

    # 3. fastembed
    fe_spec = importlib.util.find_spec("fastembed")
    fe_version = None
    if fe_spec:
        try:
            # already imported as _importlib_metadata
            fe_version = _importlib_metadata.version("fastembed")
        except Exception:
            fe_version = "installed"
    providers.append({
        "name": "fastembed",
        "available": fe_spec is not None,
        "version": fe_version,
        "install_hint": 'pip install "palaia[fastembed]"' if not fe_spec else None,
    })

    # 4. OpenAI
    openai_key = _check_openai_key()
    providers.append({
        "name": "openai",
        "available": openai_key is not None,
        "version": None,
        "install_hint": None if openai_key else "Set OPENAI_API_KEY environment variable",
    })

    # 5. Voyage
    voyage_key = _check_voyage_key()
    providers.append({
        "name": "voyage",
        "available": voyage_key is not None,
        "version": None,
        "install_hint": None if voyage_key else "Set VOYAGE_API_KEY environment variable",
    })

    return providers


def auto_detect_provider(config: dict | None = None) -> EmbeddingProvider | BM25Provider:
    """Auto-detect the best available embedding provider.
    
    Order: ollama → sentence-transformers → fastembed → openai → bm25
    
    Args:
        config: Optional config dict with embedding_provider and embedding_model keys.
    
    Returns:
        An embedding provider instance.
    """
    config = config or {}
    provider_name = config.get("embedding_provider", "auto")
    model = config.get("embedding_model", "") or None

    if provider_name == "none":
        return BM25Provider()

    if provider_name != "auto":
        # Explicit provider requested
        return _create_provider(provider_name, model)

    # Auto-detect
    providers = detect_providers()
    for p in providers:
        if p["available"] and p["name"] != "voyage":  # voyage is not a provider we implement
            return _create_provider(p["name"], model)

    # Fallback
    return BM25Provider()


def _create_provider(name: str, model: str | None = None) -> EmbeddingProvider | BM25Provider:
    """Create a provider by name."""
    if name == "ollama":
        return OllamaProvider(model=model)
    elif name == "sentence-transformers":
        return SentenceTransformersProvider(model=model)
    elif name == "fastembed":
        return FastEmbedProvider(model=model)
    elif name == "openai":
        return OpenAIProvider(model=model)
    elif name == "bm25" or name == "none":
        return BM25Provider()
    else:
        raise ValueError(f"Unknown embedding provider: {name}")


def get_provider_display_info(provider: EmbeddingProvider | BM25Provider) -> str:
    """Get a human-readable display string for a provider."""
    if isinstance(provider, BM25Provider):
        return "BM25 (keyword search)"
    name = getattr(provider, 'name', 'unknown')
    model = getattr(provider, 'model_name', None) or getattr(provider, 'model', None) or 'default'
    return f"{name} ({model})"
