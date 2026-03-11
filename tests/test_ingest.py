"""Tests for document ingestion (RAG) — ADR-009."""

from __future__ import annotations

import http.server
import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from palaia.config import save_config, DEFAULT_CONFIG
from palaia.entry import parse_entry
from palaia.ingest import DocumentIngestor, IngestResult, format_rag_output, _HTMLTextExtractor
from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    """Create a minimal Palaia root."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    save_config(root, dict(DEFAULT_CONFIG))
    return root


@pytest.fixture
def store(palaia_root):
    return Store(palaia_root)


@pytest.fixture
def ingestor(store):
    return DocumentIngestor(store)


@pytest.fixture
def sample_txt(tmp_path):
    """Create a sample .txt file with enough content."""
    content = "This is a test document. " * 100  # ~600 words
    f = tmp_path / "sample.txt"
    f.write_text(content)
    return f


@pytest.fixture
def sample_md(tmp_path):
    """Create a sample .md file."""
    content = "# Test Markdown\n\nThis is a markdown document with some content. " * 80
    f = tmp_path / "sample.md"
    f.write_text(content)
    return f


@pytest.fixture
def sample_html(tmp_path):
    """Create a sample .html file."""
    f = tmp_path / "sample.html"
    f.write_text(
        "<html><head><title>Test Page</title></head>"
        "<body><h1>Hello</h1><p>This is a test HTML document with content. " * 60
        + "</p></body></html>"
    )
    return f


@pytest.fixture
def sample_dir(tmp_path):
    """Create a directory with multiple files."""
    d = tmp_path / "docs"
    d.mkdir()
    (d / "one.txt").write_text("First document content for testing purposes. " * 50)
    (d / "two.md").write_text("Second document in markdown format. " * 50)
    (d / "ignored.xyz").write_text("This should be ignored.")
    return d


class TestIngestTxtFile:
    def test_ingest_txt_creates_entries(self, ingestor, sample_txt, store):
        result = ingestor.ingest(str(sample_txt), project="test-proj", scope="team")
        assert result.total_chunks > 0
        assert result.stored_chunks > 0
        assert result.source == str(sample_txt)
        assert result.project == "test-proj"
        assert len(result.entry_ids) == result.stored_chunks

    def test_ingest_txt_entries_are_readable(self, ingestor, sample_txt, store):
        result = ingestor.ingest(str(sample_txt), project="test-proj", scope="team")
        for eid in result.entry_ids:
            entry = store.read(eid)
            assert entry is not None
            meta, body = entry
            assert meta["source"] == "sample.txt"
            assert "rag" in meta.get("tags", [])
            assert "ingested" in meta.get("tags", [])


class TestIngestMdFile:
    def test_ingest_md_creates_entries(self, ingestor, sample_md, store):
        result = ingestor.ingest(str(sample_md), scope="team")
        assert result.total_chunks > 0
        assert result.stored_chunks > 0

    def test_ingest_md_preserves_content(self, ingestor, sample_md, store):
        result = ingestor.ingest(str(sample_md), scope="team")
        entry = store.read(result.entry_ids[0])
        assert entry is not None
        _, body = entry
        assert len(body) > 0


class TestIngestHtml:
    def test_ingest_html_file(self, ingestor, sample_html, store):
        result = ingestor.ingest(str(sample_html), scope="team")
        assert result.total_chunks > 0
        assert result.stored_chunks > 0

    def test_html_strips_tags(self, ingestor, sample_html, store):
        result = ingestor.ingest(str(sample_html), scope="team")
        entry = store.read(result.entry_ids[0])
        assert entry is not None
        _, body = entry
        assert "<script" not in body
        assert "<html" not in body


class TestIngestUrl:
    def test_ingest_url(self, ingestor, store, tmp_path):
        """Test URL ingestion with a local HTTP server."""
        content = "<html><head><title>API Docs</title></head><body>"
        content += "<p>This is API documentation with detailed content. " * 80 + "</p>"
        content += "</body></html>"

        # Write HTML to serve
        serve_dir = tmp_path / "serve"
        serve_dir.mkdir()
        (serve_dir / "api.html").write_text(content)

        handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, directory=str(serve_dir), **kw)
        server = http.server.HTTPServer(("127.0.0.1", 0), handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            result = ingestor.ingest(f"http://127.0.0.1:{port}/api.html", project="api-docs", scope="team")
            assert result.total_chunks > 0
            assert result.stored_chunks > 0
        finally:
            server.shutdown()


class TestIngestDirectory:
    def test_ingest_directory(self, ingestor, sample_dir, store):
        result = ingestor.ingest(str(sample_dir), project="multi", scope="team")
        assert result.total_chunks > 0
        assert result.stored_chunks > 0
        # Should have processed .txt and .md but not .xyz
        assert result.source == str(sample_dir)

    def test_directory_skips_unsupported(self, ingestor, sample_dir, store):
        result = ingestor.ingest(str(sample_dir), scope="team")
        # The .xyz file should be skipped
        for eid in result.entry_ids:
            entry = store.read(eid)
            assert entry is not None
            meta, _ = entry
            assert "ignored" not in meta.get("source", "")


class TestChunking:
    def test_chunk_size(self, ingestor):
        text = "Hello world. " * 1000  # 2000 words
        chunks = ingestor._chunk_text(text, size=200, overlap=0)
        assert len(chunks) > 1
        for chunk in chunks:
            word_count = len(chunk.split())
            # Allow some variance due to sentence boundaries
            assert word_count <= 250, f"Chunk too large: {word_count} words"

    def test_chunk_overlap(self, ingestor):
        sentences = [f"Sentence number {i} has some content." for i in range(100)]
        text = " ".join(sentences)
        chunks_no_overlap = ingestor._chunk_text(text, size=50, overlap=0)
        chunks_with_overlap = ingestor._chunk_text(text, size=50, overlap=20)
        # With overlap, there should be more chunks
        assert len(chunks_with_overlap) >= len(chunks_no_overlap)

    def test_chunk_empty_text(self, ingestor):
        assert ingestor._chunk_text("", 500, 50) == []
        assert ingestor._chunk_text("   ", 500, 50) == []

    def test_chunk_single_sentence(self, ingestor):
        text = "This is a single sentence."
        chunks = ingestor._chunk_text(text, 500, 50)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_small_chunk_size(self, ingestor, sample_txt, store):
        result = ingestor.ingest(str(sample_txt), chunk_size=50, chunk_overlap=10)
        assert result.total_chunks > 5  # Should create many small chunks

    def test_large_chunk_size(self, ingestor, sample_txt, store):
        result_small = ingestor.ingest(str(sample_txt), chunk_size=50, chunk_overlap=0)
        # Create new file to avoid dedup
        p = sample_txt.parent / "sample2.txt"
        p.write_text("Different content here for the second test. " * 100)
        result_large = ingestor.ingest(str(p), chunk_size=5000, chunk_overlap=0)
        assert result_small.total_chunks > result_large.total_chunks


class TestDryRun:
    def test_dry_run_no_entries(self, ingestor, sample_txt, store):
        result = ingestor.ingest(str(sample_txt), dry_run=True)
        assert result.total_chunks > 0
        assert result.stored_chunks > 0  # counted but not stored
        assert len(result.entry_ids) == 0  # no actual IDs
        # Verify nothing was actually written
        entries = store.list_entries("hot")
        assert len(entries) == 0

    def test_dry_run_reports_chunks(self, ingestor, sample_txt):
        result = ingestor.ingest(str(sample_txt), dry_run=True)
        assert result.total_chunks > 0


class TestSourceAttribution:
    def test_source_in_frontmatter(self, ingestor, sample_txt, store):
        result = ingestor.ingest(str(sample_txt), project="test", scope="team")
        entry = store.read(result.entry_ids[0])
        assert entry is not None
        meta, _ = entry
        assert meta["source"] == "sample.txt"
        assert "chunk_index" in meta
        assert "chunk_total" in meta
        assert "ingested_at" in meta

    def test_project_in_frontmatter(self, ingestor, sample_txt, store):
        result = ingestor.ingest(str(sample_txt), project="my-project", scope="team")
        entry = store.read(result.entry_ids[0])
        assert entry is not None
        meta, _ = entry
        assert meta["project"] == "my-project"

    def test_scope_in_frontmatter(self, ingestor, sample_txt, store):
        result = ingestor.ingest(str(sample_txt), scope="team")
        entry = store.read(result.entry_ids[0])
        assert entry is not None
        meta, _ = entry
        assert meta["scope"] == "team"

    def test_custom_tags(self, ingestor, sample_txt, store):
        result = ingestor.ingest(str(sample_txt), tags=["docs", "api"], scope="team")
        entry = store.read(result.entry_ids[0])
        assert entry is not None
        meta, _ = entry
        tags = meta.get("tags", [])
        assert "rag" in tags
        assert "ingested" in tags
        assert "docs" in tags
        assert "api" in tags


class TestRagOutput:
    def test_format_rag_output(self):
        results = [
            {
                "id": "abc123",
                "score": 0.87,
                "source": "docs/api.html",
                "chunk_index": 2,
                "chunk_total": 8,
                "full_body": "Authentication uses JWT tokens.",
                "title": "API Docs",
            },
        ]
        output = format_rag_output("How does auth work?", results)
        assert '[RAG Context for: "How does auth work?"]' in output
        assert "Source: docs/api.html (chunk 3/8)" in output
        assert "Score: 0.87" in output
        assert "Authentication uses JWT tokens." in output

    def test_format_rag_empty(self):
        output = format_rag_output("test", [])
        assert "[RAG Context" in output


class TestPdfWithoutPdfplumber:
    def test_pdf_without_pdfplumber_gives_hint(self, ingestor, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_text("%PDF-1.4 fake pdf")

        with patch("palaia.ingest.PDF_SUPPORT", False):
            with pytest.raises(ImportError, match="pdfplumber"):
                ingestor.ingest(str(pdf_file))


class TestDeduplication:
    def test_dedup_on_reingest(self, ingestor, sample_txt, store):
        result1 = ingestor.ingest(str(sample_txt))
        result2 = ingestor.ingest(str(sample_txt))
        # Second ingest should reuse existing entries
        assert result2.stored_chunks == result1.stored_chunks


class TestHtmlExtractor:
    def test_extracts_text(self):
        ext = _HTMLTextExtractor()
        ext.feed("<html><body><p>Hello world</p></body></html>")
        assert "Hello world" in ext.get_text()

    def test_extracts_title(self):
        ext = _HTMLTextExtractor()
        ext.feed("<html><head><title>My Title</title></head><body>Content</body></html>")
        assert ext.get_title() == "My Title"

    def test_skips_script_and_style(self):
        ext = _HTMLTextExtractor()
        ext.feed("<html><head><style>body{color:red}</style></head><body><script>alert(1)</script><p>visible</p></body></html>")
        text = ext.get_text()
        assert "visible" in text
        assert "alert" not in text
        assert "color" not in text


class TestIngestResult:
    def test_dataclass_fields(self):
        r = IngestResult(
            source="test.txt",
            total_chunks=10,
            stored_chunks=8,
            skipped_chunks=2,
            project="proj",
            entry_ids=["a", "b"],
            duration_seconds=1.5,
        )
        assert r.source == "test.txt"
        assert r.total_chunks == 10
        assert r.stored_chunks == 8
        assert r.skipped_chunks == 2
        assert r.project == "proj"
        assert len(r.entry_ids) == 2
        assert r.duration_seconds == 1.5

    def test_defaults(self):
        r = IngestResult(source="x", total_chunks=0, stored_chunks=0, skipped_chunks=0, project=None)
        assert r.entry_ids == []
        assert r.duration_seconds == 0.0


class TestIsUrl:
    def test_http(self):
        assert DocumentIngestor._is_url("http://example.com")

    def test_https(self):
        assert DocumentIngestor._is_url("https://example.com/path")

    def test_file_path(self):
        assert not DocumentIngestor._is_url("/tmp/file.txt")
        assert not DocumentIngestor._is_url("relative/path.md")


class TestSplitSentences:
    def test_basic_split(self, ingestor):
        sents = ingestor._split_sentences("Hello world. How are you? Fine thanks!")
        assert len(sents) == 3

    def test_preserves_content(self, ingestor):
        text = "First sentence. Second sentence."
        sents = ingestor._split_sentences(text)
        rejoined = " ".join(sents)
        assert "First sentence." in rejoined
        assert "Second sentence." in rejoined
