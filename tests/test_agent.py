from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from maki import agent


def test_spawn_constructs_ai_cli_run_command_with_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        assert kwargs == {"capture_output": True, "text": True, "check": True}
        return SimpleNamespace(stdout=json.dumps({"pid": 1234}))

    monkeypatch.setattr(agent.subprocess, "run", fake_run)

    pid = agent.spawn(
        prompt="do work",
        cwd="/repo",
        model="haiku",
        session_id="session-1",
    )

    assert pid == 1234
    assert calls == [
        [
            "ai-cli",
            "run",
            "--cwd",
            "/repo",
            "--prompt",
            "do work",
            "--model",
            "haiku",
            "--session-id",
            "session-1",
        ],
    ]


def test_wait_constructs_ai_cli_wait_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        assert kwargs == {"capture_output": True, "text": True, "check": True}
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(agent.subprocess, "run", fake_run)

    agent.wait(1234, timeout=9)

    assert calls == [["ai-cli", "wait", "1234", "--timeout", "9"]]


@pytest.mark.parametrize(
    ("payload", "expected_status", "expected_output", "expected_session_id"),
    [
        (
            {
                "status": "completed",
                "agentOutput": {
                    "message": "finished",
                    "session_id": "nested-session",
                },
            },
            agent.Status.COMPLETED,
            "finished",
            "nested-session",
        ),
        (
            {
                "status": "completed",
                "session_id": "top-session",
                "agentOutput": {"response": "continue?"},
            },
            agent.Status.CONFIRM,
            "continue?",
            "top-session",
        ),
        (
            {
                "status": "failed",
                "agentOutput": "boom",
            },
            agent.Status.ERROR,
            "boom",
            None,
        ),
    ],
)
def test_get_result_parses_output_session_id_and_status(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict,
    expected_status: agent.Status,
    expected_output: str,
    expected_session_id: str | None,
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        assert kwargs == {"capture_output": True, "text": True, "check": True}
        return SimpleNamespace(stdout=json.dumps(payload))

    monkeypatch.setattr(agent.subprocess, "run", fake_run)

    result = agent.get_result(55)

    assert calls == [["ai-cli", "result", "55"]]
    assert result.status is expected_status
    assert result.output == expected_output
    assert result.session_id == expected_session_id
    assert result.raw == payload
