"""Tests for BM25 search."""

import pytest
from palaia.search import BM25, tokenize


def test_tokenize():
    tokens = tokenize("Hello World! This is a test.")
    assert tokens == ["hello", "world", "this", "is", "a", "test"]


def test_bm25_basic():
    bm25 = BM25()
    docs = [
        ("doc1", "the quick brown fox jumps over the lazy dog"),
        ("doc2", "a fast red car drives on the highway"),
        ("doc3", "the lazy cat sleeps on the couch all day"),
    ]
    bm25.index(docs)
    
    results = bm25.search("lazy dog")
    assert len(results) > 0
    assert results[0][0] == "doc1"  # Best match


def test_bm25_no_results():
    bm25 = BM25()
    bm25.index([("doc1", "hello world")])
    results = bm25.search("zyxwvut")
    assert results == []


def test_bm25_empty_corpus():
    bm25 = BM25()
    bm25.index([])
    results = bm25.search("anything")
    assert results == []


def test_bm25_ranking():
    bm25 = BM25()
    docs = [
        ("doc1", "python programming language"),
        ("doc2", "python snake reptile animal"),
        ("doc3", "python programming python scripting python code"),
    ]
    bm25.index(docs)
    
    results = bm25.search("python programming")
    # Both doc1 and doc3 match both terms, doc2 only matches "python"
    result_ids = [r[0] for r in results]
    assert "doc2" in result_ids
    assert result_ids[-1] == "doc2"  # doc2 should rank lowest (no "programming")
