"""Shared BM25 ranking algorithm — pure Python, zero dependencies.

Used by both ``search.py`` (``BM25`` class) and ``embeddings.py``
(``BM25Provider`` fallback).
"""

from __future__ import annotations

import math
import re
from collections import Counter


def tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer."""
    text = text.lower()
    return re.findall(r"\b\w+\b", text)


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
                tf_norm = (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * dl / self.avg_dl))
                score += idf * tf_norm

            if score > 0:
                scores.append((doc_id, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]
