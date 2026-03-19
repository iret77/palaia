"""Tests for cross-platform file locking (lock.py)."""

from __future__ import annotations

import sys

import pytest

from palaia.lock import LockError, PalaiaLock, _lock_impl


class TestLockImplDetection:
    """Test that the correct lock implementation is selected."""

    def test_lock_impl_is_set(self):
        """Lock implementation should be detected on import."""
        assert _lock_impl in ("fcntl", "msvcrt", "mkdir")

    def test_unix_uses_fcntl(self):
        """On Unix systems, fcntl should be the default."""
        if sys.platform == "win32":
            pytest.skip("Unix-only test")
        assert _lock_impl == "fcntl"


class TestLockBasicOperations:
    """Test lock acquire/release regardless of platform."""

    def test_acquire_release(self, tmp_path):
        lock = PalaiaLock(tmp_path, timeout=2.0)
        lock.acquire()
        assert lock.lock_path.exists() or lock._mkdir_lock is not None
        lock.release()

    def test_context_manager(self, tmp_path):
        lock = PalaiaLock(tmp_path, timeout=2.0)
        with lock:
            pass  # Should not raise

    def test_double_release_safe(self, tmp_path):
        lock = PalaiaLock(tmp_path, timeout=2.0)
        lock.acquire()
        lock.release()
        lock.release()  # Should not raise


class TestMkdirFallback:
    """Test the mkdir-based fallback lock implementation."""

    def test_mkdir_acquire_release(self, tmp_path):
        """Test mkdir fallback directly."""
        lock = PalaiaLock(tmp_path, timeout=2.0)
        # Force mkdir path
        lock._acquire_mkdir()
        assert lock._mkdir_lock is not None
        lock._release_mkdir()
        assert lock._mkdir_lock is None

    def test_mkdir_contention_timeout(self, tmp_path):
        """mkdir lock should timeout when directory exists."""
        lock = PalaiaLock(tmp_path, timeout=0.2)
        lock_dir = tmp_path / ".lock.lk"
        lock_dir.mkdir(parents=True)
        # Write a non-stale lock file so stale detection doesn't help
        import json
        import time

        lock_file = tmp_path / ".lock"
        lock_file.write_text(json.dumps({"pid": 99999, "ts": time.time()}))
        with pytest.raises(LockError):
            lock._acquire_mkdir()


class TestStaleDetection:
    """Test stale lock detection and cleanup."""

    def test_stale_lock_override(self, tmp_path):
        """Stale locks (>60s old) should be overridden."""
        import json

        lock_path = tmp_path / ".lock"
        # Write a stale lock (timestamp 120s ago)
        import time

        stale_data = {"pid": 99999, "ts": time.time() - 120}
        lock_path.write_text(json.dumps(stale_data))

        lock = PalaiaLock(tmp_path, timeout=2.0)
        with lock:
            pass  # Should succeed by overriding stale lock

    def test_corrupt_lock_treated_as_stale(self, tmp_path):
        """Corrupt lock files should be treated as stale."""
        lock_path = tmp_path / ".lock"
        lock_path.write_text("not json at all")

        lock = PalaiaLock(tmp_path, timeout=2.0)
        with lock:
            pass  # Should succeed
