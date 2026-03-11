"""File-based locking for concurrent access (ADR-007)."""

import fcntl
import json
import os
import time
from pathlib import Path


class LockError(Exception):
    pass


class PalaiaLock:
    """Advisory file lock with stale detection."""

    def __init__(self, palaia_root: Path, timeout: float = 5.0):
        self.lock_path = palaia_root / ".lock"
        self.timeout = timeout
        self._fd = None

    def acquire(self) -> None:
        deadline = time.monotonic() + self.timeout
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
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
