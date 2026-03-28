"""Tests for embed-server socket transport, PID lifecycle, and client."""

from __future__ import annotations

import json
import os
import socket
import threading
import time

import pytest

from palaia.config import DEFAULT_CONFIG, save_config
from palaia.embed_server import (
    PID_FILENAME,
    SOCKET_FILENAME,
    EmbedServer,
    _cleanup_stale_socket,
    _is_pid_alive,
    _read_pid_file,
    _write_pid_file,
    get_pid_path,
    get_socket_path,
    is_server_running,
)
from palaia.store import Store


@pytest.fixture
def palaia_root(tmp_path):
    """Create a minimal .palaia directory with BM25-only config."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()

    config = dict(DEFAULT_CONFIG)
    config["agent"] = "test"
    config["embedding_chain"] = ["bm25"]
    save_config(root, config)
    return root


@pytest.fixture
def palaia_root_with_entries(palaia_root):
    """Create a .palaia directory with some entries."""
    store = Store(palaia_root)
    store.write(body="First test entry about Python", tags=["test"])
    store.write(body="Second entry about JavaScript", tags=["test"])
    store.write(body="Third entry about memory systems", tags=["memory"])
    return palaia_root


# ── PID file helpers ─────────────────────────────────────────────

class TestPidHelpers:
    def test_write_and_read_pid(self, tmp_path):
        pid_path = tmp_path / "test.pid"
        _write_pid_file(pid_path)
        assert _read_pid_file(pid_path) == os.getpid()

    def test_read_missing_pid(self, tmp_path):
        assert _read_pid_file(tmp_path / "nonexistent.pid") is None

    def test_read_invalid_pid(self, tmp_path):
        pid_path = tmp_path / "bad.pid"
        pid_path.write_text("not-a-number")
        assert _read_pid_file(pid_path) is None

    def test_current_pid_is_alive(self):
        assert _is_pid_alive(os.getpid()) is True

    def test_dead_pid_is_not_alive(self):
        # PID 99999999 should not exist
        assert _is_pid_alive(99999999) is False

    def test_get_socket_path(self, palaia_root):
        assert get_socket_path(palaia_root) == palaia_root / SOCKET_FILENAME

    def test_get_pid_path(self, palaia_root):
        assert get_pid_path(palaia_root) == palaia_root / PID_FILENAME


# ── Stale socket cleanup ────────────────────────────────────────

class TestStaleCleanup:
    def test_no_socket_no_error(self, palaia_root):
        """No socket file — cleanup does nothing."""
        sock_path = get_socket_path(palaia_root)
        pid_path = get_pid_path(palaia_root)
        _cleanup_stale_socket(sock_path, pid_path)  # should not raise

    def test_stale_socket_removed(self, palaia_root):
        """Socket with dead PID gets cleaned up."""
        sock_path = get_socket_path(palaia_root)
        pid_path = get_pid_path(palaia_root)
        sock_path.touch()
        pid_path.write_text("99999999")  # dead PID
        _cleanup_stale_socket(sock_path, pid_path)
        assert not sock_path.exists()
        assert not pid_path.exists()

    def test_live_socket_raises(self, palaia_root):
        """Socket with live PID raises error."""
        sock_path = get_socket_path(palaia_root)
        pid_path = get_pid_path(palaia_root)
        sock_path.touch()
        pid_path.write_text(str(os.getpid()))  # our own PID = alive
        with pytest.raises(RuntimeError, match="already running"):
            _cleanup_stale_socket(sock_path, pid_path)


# ── is_server_running ───────────────────────────────────────────

class TestIsServerRunning:
    def test_no_socket_not_running(self, palaia_root):
        assert is_server_running(palaia_root) is False

    def test_stale_pid_not_running(self, palaia_root):
        get_socket_path(palaia_root).touch()
        get_pid_path(palaia_root).write_text("99999999")
        assert is_server_running(palaia_root) is False


# ── EmbedServer handle_request ───────────────────────────────────

class TestHandleRequest:
    def test_ping(self, palaia_root):
        server = EmbedServer(palaia_root)
        resp = server.handle_request({"method": "ping"})
        assert resp == {"result": "pong"}

    def test_shutdown(self, palaia_root):
        server = EmbedServer(palaia_root)
        resp = server.handle_request({"method": "shutdown"})
        assert resp["result"] == "shutting_down"
        assert server._running is False

    def test_status(self, palaia_root_with_entries):
        server = EmbedServer(palaia_root_with_entries)
        resp = server.handle_request({"method": "status"})
        assert "result" in resp
        assert resp["result"]["entries"] == 3

    def test_unknown_method(self, palaia_root):
        server = EmbedServer(palaia_root)
        resp = server.handle_request({"method": "nonexistent"})
        assert "error" in resp

    def test_query(self, palaia_root_with_entries):
        server = EmbedServer(palaia_root_with_entries)
        resp = server.handle_request({
            "method": "query",
            "params": {"text": "Python", "top_k": 5},
        })
        assert "result" in resp
        assert "results" in resp["result"]

    def test_query_missing_text(self, palaia_root):
        server = EmbedServer(palaia_root)
        resp = server.handle_request({"method": "query", "params": {}})
        assert "error" in resp

    def test_embed_bm25_only(self, palaia_root):
        """embed method returns error when only BM25 is available."""
        server = EmbedServer(palaia_root)
        resp = server.handle_request({
            "method": "embed",
            "params": {"texts": ["hello"]},
        })
        assert "error" in resp
        assert "BM25" in resp["error"]

    def test_embed_missing_texts(self, palaia_root):
        server = EmbedServer(palaia_root)
        resp = server.handle_request({"method": "embed", "params": {}})
        assert "error" in resp

    def test_embed_invalid_texts(self, palaia_root):
        server = EmbedServer(palaia_root)
        resp = server.handle_request({
            "method": "embed",
            "params": {"texts": "not a list"},
        })
        assert "error" in resp


# ── Socket transport integration ─────────────────────────────────

class TestSocketTransport:
    def _start_server_thread(self, server, palaia_root):
        """Start embed-server in a background thread."""
        t = threading.Thread(
            target=server.run_socket,
            kwargs={"socket_path": get_socket_path(palaia_root)},
            daemon=True,
        )
        t.start()
        # Wait for socket to appear
        sock_path = get_socket_path(palaia_root)
        for _ in range(50):
            if sock_path.exists():
                time.sleep(0.05)  # extra settle time
                return t
            time.sleep(0.05)
        raise RuntimeError("Server did not start in time")

    def _send_recv(self, sock_path, request, timeout=2.0):
        """Send a request to the socket server and return response."""
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(str(sock_path))
        msg = json.dumps(request) + "\n"
        sock.sendall(msg.encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            buf += sock.recv(65536)
        sock.close()
        line = buf.split(b"\n")[0]
        return json.loads(line)

    def test_socket_ping(self, palaia_root):
        server = EmbedServer(palaia_root)
        self._start_server_thread(server, palaia_root)
        try:
            resp = self._send_recv(get_socket_path(palaia_root), {"method": "ping"})
            assert resp == {"result": "pong"}
        finally:
            server._running = False

    def test_socket_status(self, palaia_root_with_entries):
        server = EmbedServer(palaia_root_with_entries)
        self._start_server_thread(server, palaia_root_with_entries)
        try:
            resp = self._send_recv(
                get_socket_path(palaia_root_with_entries),
                {"method": "status"},
            )
            assert resp["result"]["entries"] == 3
        finally:
            server._running = False

    def test_socket_query(self, palaia_root_with_entries):
        server = EmbedServer(palaia_root_with_entries)
        self._start_server_thread(server, palaia_root_with_entries)
        try:
            resp = self._send_recv(
                get_socket_path(palaia_root_with_entries),
                {"method": "query", "params": {"text": "Python", "top_k": 3}},
            )
            assert "result" in resp
            assert isinstance(resp["result"]["results"], list)
        finally:
            server._running = False

    def test_socket_shutdown(self, palaia_root):
        server = EmbedServer(palaia_root)
        t = self._start_server_thread(server, palaia_root)
        resp = self._send_recv(
            get_socket_path(palaia_root),
            {"method": "shutdown"},
        )
        assert resp["result"] == "shutting_down"
        t.join(timeout=3)

    def test_socket_pid_file(self, palaia_root):
        """PID file is created when server starts and removed on stop."""
        server = EmbedServer(palaia_root)
        pid_path = get_pid_path(palaia_root)
        self._start_server_thread(server, palaia_root)
        try:
            assert pid_path.exists()
            pid = int(pid_path.read_text().strip())
            assert pid == os.getpid()
        finally:
            server._running = False
            time.sleep(0.2)  # let cleanup run

    def test_socket_multiple_clients(self, palaia_root_with_entries):
        """Multiple clients can query the same server."""
        server = EmbedServer(palaia_root_with_entries)
        self._start_server_thread(server, palaia_root_with_entries)
        sock_path = get_socket_path(palaia_root_with_entries)

        results = []
        errors = []

        def client_query(idx):
            try:
                resp = self._send_recv(
                    sock_path,
                    {"method": "query", "params": {"text": f"test {idx}", "top_k": 2}},
                )
                results.append((idx, resp))
            except Exception as e:
                errors.append((idx, e))

        threads = [threading.Thread(target=client_query, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        try:
            assert not errors, f"Client errors: {errors}"
            assert len(results) == 5
            for idx, resp in results:
                assert "result" in resp, f"Client {idx} got error: {resp}"
        finally:
            server._running = False


# ── EmbedServerClient ────────────────────────────────────────────

class TestEmbedServerClient:
    def test_client_ping(self, palaia_root):
        from palaia.embed_client import EmbedServerClient

        server = EmbedServer(palaia_root)
        sock_path = get_socket_path(palaia_root)
        # Start server in thread
        t = threading.Thread(
            target=server.run_socket,
            kwargs={"socket_path": sock_path},
            daemon=True,
        )
        t.start()
        for _ in range(50):
            if sock_path.exists():
                break
            time.sleep(0.05)

        try:
            client = EmbedServerClient(sock_path)
            assert client.ping() is True
            client.close()
        finally:
            server._running = False

    def test_client_query(self, palaia_root_with_entries):
        from palaia.embed_client import EmbedServerClient

        server = EmbedServer(palaia_root_with_entries)
        sock_path = get_socket_path(palaia_root_with_entries)
        t = threading.Thread(
            target=server.run_socket,
            kwargs={"socket_path": sock_path},
            daemon=True,
        )
        t.start()
        for _ in range(50):
            if sock_path.exists():
                break
            time.sleep(0.05)

        try:
            with EmbedServerClient(sock_path) as client:
                result = client.query({"text": "Python", "top_k": 3})
                assert "results" in result
                assert isinstance(result["results"], list)
        finally:
            server._running = False

    def test_client_status(self, palaia_root_with_entries):
        from palaia.embed_client import EmbedServerClient

        server = EmbedServer(palaia_root_with_entries)
        sock_path = get_socket_path(palaia_root_with_entries)
        t = threading.Thread(
            target=server.run_socket,
            kwargs={"socket_path": sock_path},
            daemon=True,
        )
        t.start()
        for _ in range(50):
            if sock_path.exists():
                break
            time.sleep(0.05)

        try:
            with EmbedServerClient(sock_path) as client:
                status = client.status()
                assert status["entries"] == 3
        finally:
            server._running = False

    def test_client_context_manager(self, palaia_root):
        from palaia.embed_client import EmbedServerClient

        server = EmbedServer(palaia_root)
        sock_path = get_socket_path(palaia_root)
        t = threading.Thread(
            target=server.run_socket,
            kwargs={"socket_path": sock_path},
            daemon=True,
        )
        t.start()
        for _ in range(50):
            if sock_path.exists():
                break
            time.sleep(0.05)

        try:
            with EmbedServerClient(sock_path) as client:
                assert client.ping() is True
            # After context exit, socket should be closed
            assert client._sock is None
        finally:
            server._running = False

    def test_client_connection_refused(self, tmp_path):
        from palaia.embed_client import EmbedServerClient

        client = EmbedServerClient(tmp_path / "nonexistent.sock")
        assert client.ping() is False


# ── should_auto_start ────────────────────────────────────────────

class TestShouldAutoStart:
    def test_fastembed_in_chain(self):
        from palaia.embed_client import should_auto_start

        config = {**DEFAULT_CONFIG, "embedding_chain": ["fastembed", "bm25"]}
        assert should_auto_start(config) is True

    def test_sentence_transformers_in_chain(self):
        from palaia.embed_client import should_auto_start

        config = {**DEFAULT_CONFIG, "embedding_chain": ["sentence-transformers", "bm25"]}
        assert should_auto_start(config) is True

    def test_openai_only_no_auto_start(self):
        from palaia.embed_client import should_auto_start

        config = {**DEFAULT_CONFIG, "embedding_chain": ["openai", "bm25"]}
        assert should_auto_start(config) is False

    def test_bm25_only_no_auto_start(self):
        from palaia.embed_client import should_auto_start

        config = {**DEFAULT_CONFIG, "embedding_chain": ["bm25"]}
        assert should_auto_start(config) is False

    def test_disabled_by_config(self):
        from palaia.embed_client import should_auto_start

        config = {
            **DEFAULT_CONFIG,
            "embedding_chain": ["fastembed", "bm25"],
            "embed_server_auto_start": False,
        }
        assert should_auto_start(config) is False

    def test_legacy_provider_fastembed(self):
        from palaia.embed_client import should_auto_start

        config = {**DEFAULT_CONFIG, "embedding_provider": "fastembed"}
        assert should_auto_start(config) is True

    def test_legacy_provider_openai(self):
        from palaia.embed_client import should_auto_start

        config = {**DEFAULT_CONFIG, "embedding_provider": "openai"}
        assert should_auto_start(config) is False


# ── Idle timeout ─────────────────────────────────────────────────

class TestIdleTimeout:
    def test_idle_timeout_triggers_shutdown(self, palaia_root):
        """Server shuts down after idle timeout."""
        server = EmbedServer(palaia_root, idle_timeout=1)  # 1 second
        sock_path = get_socket_path(palaia_root)
        t = threading.Thread(
            target=server.run_socket,
            kwargs={"socket_path": sock_path},
            daemon=True,
        )
        t.start()
        for _ in range(50):
            if sock_path.exists():
                break
            time.sleep(0.05)

        # Wait for idle timeout
        t.join(timeout=5)
        assert not server._running

    def test_activity_resets_idle(self, palaia_root):
        """Activity resets the idle timer."""
        server = EmbedServer(palaia_root, idle_timeout=2)
        sock_path = get_socket_path(palaia_root)
        t = threading.Thread(
            target=server.run_socket,
            kwargs={"socket_path": sock_path},
            daemon=True,
        )
        t.start()
        for _ in range(50):
            if sock_path.exists():
                break
            time.sleep(0.05)

        try:
            # Send pings to keep alive
            for _ in range(3):
                time.sleep(0.5)
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(1)
                sock.connect(str(sock_path))
                sock.sendall(b'{"method":"ping"}\n')
                sock.recv(1024)
                sock.close()

            # Server should still be running after 1.5s of activity
            assert server._running is True
        finally:
            server._running = False
