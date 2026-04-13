from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Any

AI_CLI = "ai-cli"


def resolve_ai_cli_executable() -> str:
    resolved = shutil.which(AI_CLI, path=os.environ.get("PATH"))
    return resolved or AI_CLI


class Status(Enum):
    COMPLETED = "completed"
    CONFIRM = "confirm"
    ERROR = "error"


@dataclass
class AgentResult:
    status: Status
    output: str
    session_id: str | None = None
    raw: dict[str, Any] | None = None


def spawn(
    *,
    prompt: str,
    cwd: str,
    model: str = "claude-ultra",
    session_id: str | None = None,
    env: dict[str, str] | None = None,
) -> int:
    """Spawn an agent via ai-cli and return the PID."""
    cmd = [resolve_ai_cli_executable(), "run", "--cwd", cwd, "--prompt", prompt, "--model", model]
    if session_id:
        cmd.extend(["--session-id", session_id])
    run_kwargs = {"capture_output": True, "text": True, "check": True}
    if env is not None:
        run_kwargs["env"] = env
    result = subprocess.run(cmd, **run_kwargs)
    data = json.loads(result.stdout)
    return data["pid"]


def wait(pid: int, timeout: int = 180) -> None:
    """Wait for an agent process to complete."""
    cmd = [AI_CLI, "wait", str(pid), "--timeout", str(timeout)]
    subprocess.run(cmd, capture_output=True, text=True, check=True)


def get_result(pid: int) -> AgentResult:
    """Get the result of a completed agent process."""
    cmd = [AI_CLI, "result", str(pid)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)

    status_str = data.get("status", "")
    session_id = data.get("session_id")

    # Extract agent output message
    agent_output = data.get("agentOutput", {})
    if isinstance(agent_output, dict):
        output = agent_output.get("message") or agent_output.get("response", "")
        session_id = session_id or agent_output.get("session_id")
    else:
        output = str(agent_output)

    if status_str == "completed":
        # Output contains a question → treat as confirmation request
        if "?" in output or "？" in output:
            status = Status.CONFIRM
        else:
            status = Status.COMPLETED
    elif status_str == "failed":
        status = Status.ERROR
    else:
        status = Status.ERROR

    return AgentResult(
        status=status,
        output=output,
        session_id=session_id,
        raw=data,
    )


def run_and_wait(
    *,
    prompt: str,
    cwd: str,
    model: str = "claude-ultra",
    session_id: str | None = None,
    timeout: int = 180,
    env: dict[str, str] | None = None,
) -> AgentResult:
    """Spawn an agent, wait for it, and return the result."""
    pid = spawn(prompt=prompt, cwd=cwd, model=model, session_id=session_id, env=env)
    wait(pid, timeout=timeout)
    return get_result(pid)
