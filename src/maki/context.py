from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LoopContext:
    tick: int = 0
    last_results: dict[str, Any] = field(default_factory=dict)

    def next_tick(self) -> None:
        self.tick += 1


@dataclass
class TaskContext:
    name: str
    definition: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
