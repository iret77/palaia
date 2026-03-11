"""BM25 search with tiered embedding support (ADR-001)."""

import math
import re
from collections import Counter
from pathlib import Path


def tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer."""
    text = text.lower()
    tokens = re.findall(r"\b\w+\b", text)
    return tokens


class BM25:
    """BM25 ranking algorithm — pure Python, zero dependencies."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus: list[tuple[str, list[str]]] = []  # (doc_id, tokens)
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
            tokens = tokenize(text)
            self.corpus.append((doc_id, tokens))
            self.doc_lens.append(len(tokens))
            seen = set(tokens)
            for t in seen:
                self.doc_freqs[t] += 1

        self.n_docs = len(self.corpus)
        self.avg_dl = sum(self.doc_lens) / self.n_docs if self.n_docs else 1.0

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Search the index. Returns list of (doc_id, score) sorted desc."""
        query_tokens = tokenize(query)
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


def detect_search_tier() -> int:
    """Detect best available search tier.
    
    Returns:
        1: BM25 only
        2: ollama available
        3: API key available
    """
    import shutil
    import subprocess
    import os

    # Check Tier 3: API key
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("VOYAGE_API_KEY"):
        return 3

    # Check Tier 2: ollama
    if shutil.which("ollama"):
        try:
            result = subprocess.run(
                ["ollama", "list"], capture_output=True, text=True, timeout=5
            )
            if "nomic-embed-text" in result.stdout:
                return 2
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return 1


class SearchEngine:
    """Unified search across tiers."""

    def __init__(self, store):
        self.store = store
        self.bm25 = BM25()
        self.tier = detect_search_tier()

    def build_index(self, include_cold: bool = False) -> None:
        """Build search index from store entries."""
        entries = self.store.all_entries(include_cold=include_cold)
        docs = []
        for meta, body, tier in entries:
            doc_id = meta.get("id", "unknown")
            # Index both title and body
            title = meta.get("title", "")
            tags = " ".join(meta.get("tags", []))
            full_text = f"{title} {tags} {body}"
            docs.append((doc_id, full_text))
        self.bm25.index(docs)

    def search(self, query: str, top_k: int = 10, include_cold: bool = False) -> list[dict]:
        """Search memories. Returns list of result dicts."""
        self.build_index(include_cold=include_cold)
        results = self.bm25.search(query, top_k=top_k)

        output = []
        for doc_id, score in results:
            entry = self.store.read(doc_id)
            if entry:
                meta, body = entry
                output.append({
                    "id": doc_id,
                    "score": round(score, 4),
                    "scope": meta.get("scope", "team"),
                    "title": meta.get("title", ""),
                    "tags": meta.get("tags", []),
                    "body": body[:200] + ("..." if len(body) > 200 else ""),
                    "tier": self._get_tier(doc_id),
                    "decay_score": meta.get("decay_score", 0),
                })
        return output

    def _get_tier(self, entry_id: str) -> str:
        """Determine which tier an entry is in."""
        for tier in ("hot", "warm", "cold"):
            if (self.store.root / tier / f"{entry_id}.md").exists():
                return tier
        return "unknown"
