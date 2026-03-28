"""Client for communicating with the palaia embed-server over Unix socket.

Provides:
- EmbedServerClient: low-level JSON-RPC client
- is_server_running(): check if a server is running
- auto_start_server(): start a daemon if not running
- should_auto_start(): check if auto-start makes sense for current config
"""

from __future__ import annotations

import json
import logging
import socket
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class EmbedServerClient:
    """JSON-RPC client for the embed-server Unix socket."""

    def __init__(self, socket_path: Path):
        self.socket_path = socket_path
        self._sock: socket.socket | None = None

    def _connect(self) -> socket.socket:
        """Connect to the Unix socket, reusing existing connection."""
        if self._sock is not None:
            return self._sock
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(self.socket_path))
        self._sock = sock
        return sock

    def _send(self, request: dict, timeout: float = 3.0) -> dict:
        """Send a JSON-RPC request and return the response."""
        sock = self._connect()
        sock.settimeout(timeout)
        msg = json.dumps(request, ensure_ascii=False) + "\n"
        sock.sendall(msg.encode("utf-8"))

        # Read response (newline-delimited JSON)
        buf = bytearray()
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                raise ConnectionError("Server closed connection")
            buf.extend(chunk)
            if b"\n" in buf:
                line, _, _ = buf.partition(b"\n")
                return json.loads(line.decode("utf-8"))

    def close(self) -> None:
        """Close the connection."""
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def ping(self, timeout: float = 1.0) -> bool:
        """Check if the server is responsive."""
        try:
            resp = self._send({"method": "ping"}, timeout=timeout)
            return resp.get("result") == "pong"
        except (ConnectionError, OSError, TimeoutError, json.JSONDecodeError):
            return False

    def query(self, params: dict, timeout: float = 3.0) -> dict:
        """Execute a search query. Returns the result dict."""
        resp = self._send({"method": "query", "params": params}, timeout=timeout)
        if "error" in resp:
            raise RuntimeError(f"Server error: {resp['error']}")
        return resp.get("result", {})

    def embed(self, texts: list[str], timeout: float = 10.0) -> list[list[float]]:
        """Compute embeddings for a list of texts. Returns vectors."""
        resp = self._send({"method": "embed", "params": {"texts": texts}}, timeout=timeout)
        if "error" in resp:
            raise RuntimeError(f"Server error: {resp['error']}")
        return resp.get("result", {}).get("vectors", [])

    def status(self, timeout: float = 2.0) -> dict:
        """Get server status."""
        resp = self._send({"method": "status"}, timeout=timeout)
        if "error" in resp:
            raise RuntimeError(f"Server error: {resp['error']}")
        return resp.get("result", {})

    def warmup(self, timeout: float = 60.0) -> dict:
        """Trigger server warmup. Returns indexing stats."""
        resp = self._send({"method": "warmup"}, timeout=timeout)
        if "error" in resp:
            raise RuntimeError(f"Server error: {resp['error']}")
        return resp.get("result", {})

    def shutdown(self) -> None:
        """Ask the server to shut down."""
        try:
            self._send({"method": "shutdown"}, timeout=2.0)
        except (ConnectionError, OSError, TimeoutError):
            pass
        self.close()


# ── Convenience functions ───────────────────────────────────────

def is_server_running(palaia_root: Path) -> bool:
    """Check if an embed-server is running and responsive for the given root."""
    from palaia.embed_server import get_socket_path

    sock_path = get_socket_path(palaia_root)
    if not sock_path.exists():
        return False

    client = EmbedServerClient(sock_path)
    try:
        return client.ping(timeout=1.0)
    except Exception:
        return False
    finally:
        client.close()


def auto_start_server(palaia_root: Path, timeout: float = 10.0) -> bool:
    """Start an embed-server daemon if not running. Returns True if server is available."""
    if is_server_running(palaia_root):
        return True

    from palaia.embed_server import start_daemon

    try:
        start_daemon(palaia_root)
    except Exception as e:
        logger.info("Failed to auto-start embed server: %s", e)
        return False

    # Wait for server to be responsive
    from palaia.embed_server import get_socket_path

    sock_path = get_socket_path(palaia_root)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sock_path.exists():
            client = EmbedServerClient(sock_path)
            try:
                if client.ping(timeout=1.0):
                    return True
            except Exception:
                pass
            finally:
                client.close()
        time.sleep(0.2)

    return False


# ── EmbeddingProvider wrapper ───────────────────────────────────

class EmbedServerProvider:
    """EmbeddingProvider that delegates to a running embed-server via Unix socket.

    Implements the EmbeddingProvider protocol (embed, embed_query).
    Raises ConnectionError on failure, which EmbeddingChain catches
    and falls through to the next provider.
    """

    name = "embed-server"

    def __init__(self, socket_path: Path):
        self.socket_path = socket_path

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts via the embed-server."""
        with EmbedServerClient(self.socket_path) as client:
            return client.embed(texts, timeout=10.0)

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query text via the embed-server."""
        result = self.embed([text])
        if not result:
            raise ConnectionError("Empty response from embed-server")
        return result[0]


# Provider names that benefit from embed-server (local model loading)
_LOCAL_PROVIDERS = {"fastembed", "sentence-transformers"}


def should_auto_start(config: dict) -> bool:
    """Check if auto-starting the embed-server makes sense for the current config.

    Returns True only if a local embedding provider (fastembed, sentence-transformers)
    is configured. API-based providers (OpenAI, Gemini, Ollama) don't benefit.
    """
    if not config.get("embed_server_auto_start", True):
        return False

    # Check embedding_chain first
    chain = config.get("embedding_chain")
    if chain and isinstance(chain, list):
        return bool(set(chain) & _LOCAL_PROVIDERS)

    # Legacy: check embedding_provider
    provider = config.get("embedding_provider", "auto")
    if provider in _LOCAL_PROVIDERS:
        return True

    # "auto" could resolve to a local provider — check what's available
    if provider == "auto":
        try:
            from palaia.embeddings import detect_providers

            for p in detect_providers():
                if p.get("available") and p.get("name") in _LOCAL_PROVIDERS:
                    return True
        except Exception:
            pass

    return False
