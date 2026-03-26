"""Tests for project locking (ADR-011)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from palaia.project_lock import DEFAULT_TTL_SECONDS, ProjectLockError, ProjectLockManager


@pytest.fixture
def palaia_root(tmp_path):
    """Create a minimal .palaia directory."""
    root = tmp_path / ".palaia"
    root.mkdir()
    for sub in ("hot", "warm", "cold", "wal", "index"):
        (root / sub).mkdir()
    config = {"version": 1, "embedding_chain": ["bm25"], "agent": "TestAgent"}
    (root / "config.json").write_text(json.dumps(config))
    return root


@pytest.fixture
def lm(palaia_root):
    """Create a ProjectLockManager."""
    return ProjectLockManager(palaia_root)


class TestAcquireRelease:
    def test_acquire_creates_lock_file(self, lm, palaia_root):
        lock = lm.acquire("myproject", "elliot", "testing")
        assert lock["project"] == "myproject"
        assert lock["agent"] == "elliot"
        assert lock["reason"] == "testing"
        assert lock["ttl_seconds"] == DEFAULT_TTL_SECONDS
        assert (palaia_root / "locks" / "myproject.lock").exists()

    def test_release_removes_lock_file(self, lm, palaia_root):
        lm.acquire("myproject", "elliot")
        assert lm.release("myproject") is True
        assert not (palaia_root / "locks" / "myproject.lock").exists()

    def test_release_nonexistent(self, lm):
        assert lm.release("nope") is False

    def test_acquire_when_already_locked_by_other(self, lm):
        lm.acquire("proj", "elliot", "working")
        with pytest.raises(ProjectLockError, match="locked by elliot"):
            lm.acquire("proj", "cyberclaw", "also want to work")

    def test_acquire_same_agent_renews(self, lm):
        lm.acquire("proj", "elliot", "first")
        lock = lm.acquire("proj", "elliot", "second")
        # Should succeed (renew)
        assert lock["agent"] == "elliot"


class TestTTLExpiry:
    def test_expired_lock_is_unlocked(self, lm):
        lm.acquire("proj", "elliot", ttl=1)
        # Manually set expires to the past
        lock_path = lm._lock_path("proj")
        data = json.loads(lock_path.read_text())
        data["expires"] = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        lock_path.write_text(json.dumps(data))

        assert lm.is_locked("proj") is False
        assert lm.status("proj") is None

    def test_expired_lock_allows_new_acquire(self, lm):
        lm.acquire("proj", "elliot", ttl=1)
        # Expire it
        lock_path = lm._lock_path("proj")
        data = json.loads(lock_path.read_text())
        data["expires"] = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        lock_path.write_text(json.dumps(data))

        # Another agent can now acquire
        lock = lm.acquire("proj", "cyberclaw", "taking over")
        assert lock["agent"] == "cyberclaw"


class TestRenew:
    def test_renew_extends_ttl(self, lm):
        lm.acquire("proj", "elliot", ttl=600)
        old_lock = lm.status("proj")
        lock = lm.renew("proj", ttl=1800)
        assert lock["ttl_seconds"] == 1800
        # New expires should be later
        new_expires = datetime.fromisoformat(lock["expires"])
        old_expires = datetime.fromisoformat(old_lock["expires"])
        assert new_expires > old_expires

    def test_renew_no_lock(self, lm):
        with pytest.raises(ProjectLockError, match="No lock found"):
            lm.renew("nope")

    def test_renew_expired_lock(self, lm):
        lm.acquire("proj", "elliot", ttl=1)
        lock_path = lm._lock_path("proj")
        data = json.loads(lock_path.read_text())
        data["expires"] = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        lock_path.write_text(json.dumps(data))

        with pytest.raises(ProjectLockError, match="expired"):
            lm.renew("proj")


class TestBreakLock:
    def test_break_removes_lock(self, lm, palaia_root):
        lm.acquire("proj", "elliot")
        old = lm.break_lock("proj")
        assert old["agent"] == "elliot"
        assert not (palaia_root / "locks" / "proj.lock").exists()

    def test_break_nonexistent(self, lm):
        result = lm.break_lock("nope")
        assert result is None


class TestStatus:
    def test_status_active(self, lm):
        lm.acquire("proj", "elliot", "working")
        info = lm.status("proj")
        assert info is not None
        assert info["agent"] == "elliot"
        assert info["active"] is True
        assert "age_seconds" in info

    def test_status_expired(self, lm):
        lm.acquire("proj", "elliot", ttl=1)
        lock_path = lm._lock_path("proj")
        data = json.loads(lock_path.read_text())
        data["expires"] = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        lock_path.write_text(json.dumps(data))

        assert lm.status("proj") is None

    def test_status_not_found(self, lm):
        assert lm.status("nope") is None


class TestListLocks:
    def test_list_empty(self, lm):
        assert lm.list_locks() == []

    def test_list_active_only(self, lm):
        lm.acquire("proj1", "elliot")
        lm.acquire("proj2", "cyberclaw")
        # Expire proj2
        lock_path = lm._lock_path("proj2")
        data = json.loads(lock_path.read_text())
        data["expires"] = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        lock_path.write_text(json.dumps(data))

        locks = lm.list_locks()
        assert len(locks) == 1
        assert locks[0]["project"] == "proj1"


class TestGC:
    def test_gc_removes_expired(self, lm):
        lm.acquire("proj1", "elliot")
        lm.acquire("proj2", "cyberclaw")
        # Expire proj2
        lock_path = lm._lock_path("proj2")
        data = json.loads(lock_path.read_text())
        data["expires"] = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        lock_path.write_text(json.dumps(data))

        cleaned = lm.gc()
        assert "proj2" in cleaned
        assert not lock_path.exists()
        assert lm._lock_path("proj1").exists()


class TestIsLocked:
    def test_locked(self, lm):
        lm.acquire("proj", "elliot")
        assert lm.is_locked("proj") is True

    def test_not_locked(self, lm):
        assert lm.is_locked("proj") is False


class TestCLIIntegration:
    """Test CLI commands via subprocess."""

    def _run(self, tmp_path, *args, env_extra=None):
        """Run palaia CLI command."""
        import os

        env = os.environ.copy()
        if env_extra:
            env.update(env_extra)
        result = subprocess.run(
            [sys.executable, "-m", "palaia", *args],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
        )
        return result

    def test_lock_unlock_cycle(self, tmp_path):
        self._run(tmp_path, "init", "--agent", "TestAgent")
        r = self._run(tmp_path, "lock", "myproj", "--agent", "elliot", "--reason", "testing", "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["project"] == "myproj"
        assert data["agent"] == "elliot"

        # Status
        r = self._run(tmp_path, "lock", "status", "myproj", "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["agent"] == "elliot"
        assert data["active"] is True

        # Unlock
        r = self._run(tmp_path, "unlock", "myproj", "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["unlocked"] is True

        # Status after unlock
        r = self._run(tmp_path, "lock", "status", "myproj", "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["locked"] is False

    def test_lock_shorthand(self, tmp_path):
        """palaia lock <project> --agent should work as acquire shorthand."""
        self._run(tmp_path, "init", "--agent", "TestAgent")
        r = self._run(tmp_path, "lock", "myproj", "--agent", "elliot", "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["project"] == "myproj"

    def test_lock_conflict_json(self, tmp_path):
        self._run(tmp_path, "init", "--agent", "TestAgent")
        self._run(tmp_path, "lock", "myproj", "--agent", "elliot")
        r = self._run(tmp_path, "lock", "myproj", "--agent", "cyberclaw", "--json")
        assert r.returncode == 1
        data = json.loads(r.stdout)
        assert "error" in data
        assert "elliot" in data["error"]

    def test_lock_list_json(self, tmp_path):
        self._run(tmp_path, "init", "--agent", "TestAgent")
        self._run(tmp_path, "lock", "proj1", "--agent", "elliot")
        self._run(tmp_path, "lock", "proj2", "--agent", "cyberclaw")
        r = self._run(tmp_path, "lock", "list", "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["locks"]) == 2

    def test_lock_renew_json(self, tmp_path):
        self._run(tmp_path, "init", "--agent", "TestAgent")
        self._run(tmp_path, "lock", "myproj", "--agent", "elliot")
        r = self._run(tmp_path, "lock", "renew", "myproj", "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["ttl_seconds"] == DEFAULT_TTL_SECONDS

    def test_lock_break_json(self, tmp_path):
        self._run(tmp_path, "init", "--agent", "TestAgent")
        self._run(tmp_path, "lock", "myproj", "--agent", "elliot")
        r = self._run(tmp_path, "lock", "break", "myproj", "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["broken"] is True
        assert data["previous_lock"]["agent"] == "elliot"

    def test_env_agent(self, tmp_path):
        """PALAIA_AGENT env var should be used when --agent not given."""
        self._run(tmp_path, "init", "--agent", "TestAgent")
        r = self._run(tmp_path, "lock", "myproj", "--json", env_extra={"PALAIA_AGENT": "desmond"})
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["agent"] == "desmond"
