"""File-based locking for concurrent access (ADR-007)."""

from __future__ import annotations

import fcntl
import json
import os
import sys
import time
import warnings
from pathlib import Path

STALE_LOCK_SECONDS = 60


class LockError(Exception):
    pass


class PalaiaLock:
    """Advisory file lock with stale detection."""

    def __init__(self, palaia_root: Path, timeout: float = 5.0):
        self.lock_path = palaia_root / ".lock"
        self.timeout = timeout
        self._fd = None

    def _check_stale(self) -> bool:
        """Check if existing lock is stale (>60s old). If stale, remove it and warn."""
        if not self.lock_path.exists():
            return False
        try:
            with open(self.lock_path, "r") as f:
                data = json.load(f)
            lock_ts = data.get("ts", 0)
            lock_pid = data.get("pid", 0)
            age = time.time() - lock_ts
            if age > STALE_LOCK_SECONDS:
                warnings.warn(
                    f"Stale lock detected (age: {age:.0f}s, pid: {lock_pid}). "
                    f"Overriding stale lock.",
                    stacklevel=3,
                )
                try:
                    self.lock_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return True
        except (json.JSONDecodeError, OSError, ValueError):
            # Corrupt lock file — treat as stale
            try:
                self.lock_path.unlink(missing_ok=True)
            except OSError:
                pass
            return True
        return False

    def acquire(self) -> None:
        deadline = time.monotonic() + self.timeout
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Check for stale lock before first attempt
        self._check_stale()
        
        self._fd = open(self.lock_path, "w")
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # Write our PID
                self._fd.write(json.dumps({"pid": os.getpid(), "ts": time.time()}))
                self._fd.flush()
                return
            except (IOError, OSError):
                if time.monotonic() >= deadline:
                    # One more stale check before giving up
                    if self._check_stale():
                        # Retry once after removing stale lock
                        try:
                            self._fd.close()
                            self._fd = open(self.lock_path, "w")
                            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            self._fd.write(json.dumps({"pid": os.getpid(), "ts": time.time()}))
                            self._fd.flush()
                            return
                        except (IOError, OSError):
                            pass
                    self._fd.close()
                    self._fd = None
                    raise LockError(
                        f"Could not acquire lock within {self.timeout}s"
                    )
                time.sleep(0.05)

    def release(self) -> None:
        if self._fd:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                self._fd.close()
            except (IOError, OSError):
                pass
            self._fd = None
            try:
                self.lock_path.unlink(missing_ok=True)
            except OSError:
                pass

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()
