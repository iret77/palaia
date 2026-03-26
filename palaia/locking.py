"""Backward-compatibility shim — canonical module is ``palaia.project_lock``.

All symbols are re-exported so existing ``from palaia.locking import ...``
statements continue to work.
"""

from palaia.project_lock import (  # noqa: F401
    DEFAULT_TTL_SECONDS,
    ProjectLockError,
    ProjectLockManager,
)
