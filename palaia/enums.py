"""Type-safe enums for palaia domain values.

Using ``str, Enum`` pattern for backward compatibility — enum members
compare equal to their string values (e.g., ``Tier.HOT == "hot"``).
"""

from enum import Enum


class Tier(str, Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class EntryType(str, Enum):
    MEMORY = "memory"
    PROCESS = "process"
    TASK = "task"


class EntryStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in-progress"
    DONE = "done"
    WONTFIX = "wontfix"


class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class WalOp(str, Enum):
    WRITE = "write"
    DELETE = "delete"


class Scope(str, Enum):
    TEAM = "team"
    PRIVATE = "private"
    PUBLIC = "public"
