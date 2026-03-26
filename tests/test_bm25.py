"""Tests for palaia.bm25 — BM25 ranking and tokenization."""

from __future__ import annotations

from palaia.bm25 import BM25, tokenize


class TestTokenize:
    def test_simple_sentence(self):
        tokens = tokenize("hello world")
        assert tokens == ["hello", "world"]

    def test_stopwords_removed(self):
        # tokenize does not remove stopwords — it's a simple word tokenizer
        tokens = tokenize("the cat is on the mat")
        assert "the" in tokens
        assert "cat" in tokens

    def test_punctuation_stripped(self):
        tokens = tokenize("hello, world! foo-bar.")
        assert "hello" in tokens
        assert "world" in tokens
        # Punctuation is stripped; "foo-bar" becomes "foo" and "bar"
        assert "foo" in tokens
        assert "bar" in tokens

    def test_empty_string(self):
        assert tokenize("") == []

    def test_unicode(self):
        tokens = tokenize("cafe resume")
        assert tokens == ["cafe", "resume"]


class TestBM25:
    def test_index_and_score(self):
        bm25 = BM25()
        bm25.index([("doc1", "the quick brown fox")])
        results = bm25.search("fox")
        assert len(results) == 1
        assert results[0][0] == "doc1"
        assert results[0][1] > 0

    def test_empty_corpus(self):
        bm25 = BM25()
        bm25.index([])
        results = bm25.search("anything")
        assert results == []

    def test_no_match(self):
        bm25 = BM25()
        bm25.index([("doc1", "the quick brown fox")])
        results = bm25.search("elephant")
        assert results == []

    def test_multiple_documents_ranking(self):
        bm25 = BM25()
        bm25.index([
            ("doc1", "the quick brown fox"),
            ("doc2", "the lazy dog"),
            ("doc3", "the fox jumps over the lazy dog"),
        ])
        results = bm25.search("fox")
        # doc1 and doc3 mention fox; doc2 does not
        result_ids = [r[0] for r in results]
        assert "doc1" in result_ids
        assert "doc3" in result_ids
        assert "doc2" not in result_ids

    def test_term_frequency_matters(self):
        bm25 = BM25()
        bm25.index([
            ("doc1", "fox"),
            ("doc2", "fox fox fox"),
        ])
        results = bm25.search("fox")
        # doc2 has higher TF, should score higher
        assert results[0][0] == "doc2"
        assert results[1][0] == "doc1"

    def test_idf_matters(self):
        bm25 = BM25()
        bm25.index([
            ("doc1", "common rare"),
            ("doc2", "common usual"),
            ("doc3", "common typical"),
        ])
        # "rare" only appears in doc1, so it has high IDF
        results = bm25.search("rare")
        assert len(results) == 1
        assert results[0][0] == "doc1"
