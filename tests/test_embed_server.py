"""Tests for the embed_server module."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from palaia.embed_server import EmbedServer, _count_entries
from palaia.search import SearchEngine
from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    """Create a minimal palaia store for testing."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for d in ("hot", "warm", "cold", "wal", "index"):
        (root / d).mkdir()
    config = {
        "agent": "test-agent",
        "default_scope": "team",
        "embedding_provider": "none",
        "embedding_chain": ["bm25"],
        "decay_lambda": 0.1,
        "hot_threshold_days": 7,
        "warm_threshold_days": 30,
        "hot_min_score": 0.3,
        "warm_min_score": 0.1,
        "lock_timeout_seconds": 5,
        "wal_retention_days": 7,
    }
    (root / "config.json").write_text(json.dumps(config))
    return root


@pytest.fixture
def store_with_entries(palaia_root):
    """Create a store with some test entries."""
    store = Store(palaia_root)
    store.write("Python is a great programming language", agent="test-agent", title="Python", tags=["tech"])
    store.write("Machine learning uses neural networks", agent="test-agent", title="ML Basics", tags=["ai"])
    store.write("Docker containers simplify deployment", agent="test-agent", title="Docker", tags=["devops"])
    return store


class TestEmbedServerUnit:
    """Unit tests for EmbedServer (no subprocess)."""

    def test_ping(self, palaia_root):
        server = EmbedServer(palaia_root)
        response = server.handle_request({"method": "ping"})
        assert response == {"result": "pong"}

    def test_status(self, palaia_root):
        server = EmbedServer(palaia_root)
        response = server.handle_request({"method": "status"})
        assert "result" in response
        result = response["result"]
        assert "entries" in result
        assert "cached" in result
        assert "provider" in result
        assert "has_embeddings" in result

    def test_shutdown(self, palaia_root):
        server = EmbedServer(palaia_root)
        response = server.handle_request({"method": "shutdown"})
        assert response == {"result": "shutting_down"}
        assert not server._running

    def test_unknown_method(self, palaia_root):
        server = EmbedServer(palaia_root)
        response = server.handle_request({"method": "nonexistent"})
        assert "error" in response
        assert "Unknown method" in response["error"]

    def test_query_empty_text(self, palaia_root):
        server = EmbedServer(palaia_root)
        response = server.handle_request({"method": "query", "params": {"text": ""}})
        assert "error" in response

    def test_query_returns_results(self, store_with_entries):
        server = EmbedServer(store_with_entries.root)
        response = server.handle_request({"method": "query", "params": {"text": "Python programming"}})
        assert "result" in response
        results = response["result"]["results"]
        assert len(results) > 0
        # Python entry should be first (BM25 keyword match)
        assert any("Python" in r.get("title", "") for r in results)

    def test_query_result_parity_with_search_engine(self, store_with_entries):
        """Embed server MUST return the same results as SearchEngine.search()."""
        root = store_with_entries.root
        store = Store(root)

        # Direct SearchEngine query
        engine = SearchEngine(store)
        direct_results = engine.search("neural networks machine learning", top_k=5)

        # Embed server query
        server = EmbedServer(root)
        server_response = server.handle_request(
            {
                "method": "query",
                "params": {"text": "neural networks machine learning", "top_k": 5},
            }
        )
        server_results = server_response["result"]["results"]

        # Same number of results
        assert len(server_results) == len(direct_results)

        # Same IDs in the same order (top-5 parity)
        direct_ids = [r["id"] for r in direct_results]
        server_ids = [r["id"] for r in server_results]
        assert direct_ids == server_ids

        # Same scores
        for dr, sr in zip(direct_results, server_results):
            assert abs(dr["score"] - sr["score"]) < 0.001

    def test_warmup(self, store_with_entries):
        server = EmbedServer(store_with_entries.root)
        response = server.handle_request({"method": "warmup"})
        assert "result" in response
        result = response["result"]
        assert "indexed" in result
        assert "new" in result
        assert "cached" in result

    def test_malformed_request_returns_error(self, palaia_root):
        """Server should handle malformed requests gracefully."""
        server = EmbedServer(palaia_root)
        # Missing method
        response = server.handle_request({})
        assert "error" in response

    def test_count_entries(self, store_with_entries):
        count = _count_entries(store_with_entries)
        assert count == 3

    def test_status_with_entries(self, store_with_entries):
        server = EmbedServer(store_with_entries.root)
        response = server.handle_request({"method": "status"})
        assert response["result"]["entries"] == 3


class TestEmbedServerSubprocess:
    """Integration tests that start the server as a subprocess."""

    def _start_server(self, palaia_root):
        """Start embed-server as a subprocess."""
        env = {
            "PALAIA_HOME": str(palaia_root),
            "PATH": subprocess.check_output(["bash", "-c", "echo $PATH"]).decode().strip(),
            "HOME": str(Path.home()),
        }
        proc = subprocess.Popen(
            [sys.executable, "-m", "palaia", "embed-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=str(palaia_root.parent),
        )
        # Wait for ready signal
        ready_line = proc.stdout.readline().decode().strip()
        ready = json.loads(ready_line)
        assert ready.get("result") == "ready"
        return proc

    def _send(self, proc, request):
        """Send a request and read the response."""
        line = json.dumps(request) + "\n"
        proc.stdin.write(line.encode())
        proc.stdin.flush()
        resp_line = proc.stdout.readline().decode().strip()
        return json.loads(resp_line)

    def test_subprocess_ping(self, palaia_root):
        proc = self._start_server(palaia_root)
        try:
            resp = self._send(proc, {"method": "ping"})
            assert resp == {"result": "pong"}
        finally:
            self._send(proc, {"method": "shutdown"})
            proc.wait(timeout=5)

    def test_subprocess_shutdown(self, palaia_root):
        proc = self._start_server(palaia_root)
        resp = self._send(proc, {"method": "shutdown"})
        assert resp["result"] == "shutting_down"
        proc.wait(timeout=5)
        assert proc.returncode is not None

    def test_subprocess_query(self, store_with_entries):
        proc = self._start_server(store_with_entries.root)
        try:
            resp = self._send(
                proc,
                {
                    "method": "query",
                    "params": {"text": "Python programming", "top_k": 5},
                },
            )
            assert "result" in resp
            assert len(resp["result"]["results"]) > 0
        finally:
            self._send(proc, {"method": "shutdown"})
            proc.wait(timeout=5)

    def test_subprocess_error_recovery(self, palaia_root):
        """Server should survive bad requests and continue."""
        proc = self._start_server(palaia_root)
        try:
            # Send invalid JSON
            proc.stdin.write(b"not-json\n")
            proc.stdin.flush()
            resp_line = proc.stdout.readline().decode().strip()
            resp = json.loads(resp_line)
            assert "error" in resp

            # Server should still respond
            resp2 = self._send(proc, {"method": "ping"})
            assert resp2 == {"result": "pong"}
        finally:
            self._send(proc, {"method": "shutdown"})
            proc.wait(timeout=5)
