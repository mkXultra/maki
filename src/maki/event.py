from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventSource(Enum):
    WATCHER = "watcher"
    SCHEDULE = "schedule"
    USER = "user"


@dataclass
class Event:
    source: EventSource
    name: str
    data: dict[str, Any] = field(default_factory=dict)
