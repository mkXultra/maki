"""Shared confirm queue used by Core and UserInput backends (web, cli)."""
from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from enum import Enum


class ConfirmChoice(Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    EDIT = "edit"


@dataclass
class ConfirmRequest:
    id: str
    job_name: str
    agent_output: str
    session_id: str | None = None
    response: ConfirmChoice | None = None
    edit_text: str | None = None
    event: threading.Event = field(default_factory=threading.Event)

    @staticmethod
    def new_id() -> str:
        return secrets.token_hex(8)


class ConfirmStore:
    """Thread-safe store for pending confirm requests."""

    def __init__(self) -> None:
        self._pending: dict[str, ConfirmRequest] = {}
        self._lock = threading.Lock()
        self.token = secrets.token_urlsafe(16)

    def add(self, request: ConfirmRequest) -> None:
        with self._lock:
            self._pending[request.id] = request

    def get(self, request_id: str) -> ConfirmRequest | None:
        with self._lock:
            return self._pending.get(request_id)

    def resolve(self, request_id: str, choice: ConfirmChoice, edit_text: str | None = None) -> bool:
        with self._lock:
            req = self._pending.get(request_id)
            if not req:
                return False
            req.response = choice
            req.edit_text = edit_text
            req.event.set()
            return True

    def remove(self, request_id: str) -> None:
        with self._lock:
            self._pending.pop(request_id, None)

    def list_pending(self) -> list[ConfirmRequest]:
        with self._lock:
            return [r for r in self._pending.values() if r.response is None]
