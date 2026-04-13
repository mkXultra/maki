from __future__ import annotations

from types import SimpleNamespace

import pytest

from maki import agent, core
from maki.config import Config, JobDef, StepDef
from maki.confirm import ConfirmChoice, ConfirmStore
from maki.context import LoopContext
from maki.event import Event, EventSource


def test_resolves_step_outputs_and_comparison_expressions() -> None:
    context = {
        "steps": {
            "generate": {
                "outputs": {
                    "result": "ready",
                    "choice": "accept",
                },
            },
        },
    }

    assert (
        core.resolve_expressions(
            "result=${{ steps.generate.outputs.result }}",
            context,
        )
        == "result=ready"
    )
    assert (
        core.resolve_expressions(
            "${{ steps.generate.outputs.choice == 'accept' }}",
            context,
        )
        == "true"
    )
    assert (
        core.resolve_expressions(
            "${{ steps.generate.outputs.choice != 'reject' }}",
            context,
        )
        == "true"
    )
    assert core.eval_condition("${{ steps.generate.outputs.choice == 'accept' }}", context)
    assert not core.eval_condition("${{ steps.generate.outputs.choice != 'accept' }}", context)


def test_process_event_expands_outputs_and_honors_conditions(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str]] = []

    def fake_shell_step(
        step: StepDef,
        resolved_cmd: str,
        prev_output: str,
        steps_context: dict[str, dict],
    ) -> str:
        calls.append((step.name, resolved_cmd, prev_output))
        return "ready" if step.name == "generate" else "consumed"

    monkeypatch.setattr(core, "run_shell_step", fake_shell_step)

    config = Config(
        jobs=[
            JobDef(
                name="manual-job",
                on="manual",
                steps=[
                    StepDef(name="generate", run="generate"),
                    StepDef(
                        name="consume",
                        if_condition="${{ steps.generate.outputs.result == 'ready' }}",
                        run="echo ${{ steps.generate.outputs.result }}",
                    ),
                    StepDef(
                        name="skip",
                        if_condition="${{ steps.generate.outputs.result != 'ready' }}",
                        run="should-not-run",
                    ),
                ],
            )
        ],
    )
    loop_ctx = LoopContext()

    core.process_event(
        Event(source=EventSource.USER, name="manual", data={"input": "seed"}),
        config,
        loop_ctx,
        ConfirmStore(),
    )

    assert calls == [
        ("generate", "generate", "seed"),
        ("consume", "echo ready", "ready"),
    ]
    assert loop_ctx.last_results["manual"] == "consumed"


def test_run_shell_step_exports_prev_and_step_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=" next output \n", stderr="")

    monkeypatch.setattr(core.subprocess, "run", fake_run)

    output = core.run_shell_step(
        StepDef(name="current", cwd="/tmp"),
        "echo env",
        "previous output",
        {
            "first-step": {
                "outputs": {
                    "result": "alpha",
                    "other-key": "beta",
                },
            },
        },
    )

    assert output == "next output"
    assert captured["args"] == ("echo env",)
    assert captured["kwargs"]["shell"] is True
    assert captured["kwargs"]["cwd"] == "/tmp"
    assert captured["kwargs"]["env"]["PREV"] == "previous output"
    assert captured["kwargs"]["env"]["STEPS_FIRST_STEP_RESULT"] == "alpha"
    assert captured["kwargs"]["env"]["STEPS_FIRST_STEP_OTHER_KEY"] == "beta"


def test_run_local_action_executes_python_and_reads_outputs(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    action_dir = tmp_path / "echo"
    action_dir.mkdir()
    (action_dir / "maki-action.yaml").write_text(
        """
name: echo
description: Example local Python action
inputs:
  message:
    required: true
  prefix:
    default: ""
runs:
  using: python
  main: action.py
""".strip()
    )
    (action_dir / "action.py").write_text(
        """
import json
import os
from pathlib import Path

inputs = json.loads(os.environ["MAKI_INPUTS"])
payload = {
    "outputs": {
        "result": f"{inputs['prefix']}{inputs['message']}|{os.environ['MAKI_PREV']}",
        "prefix": inputs["prefix"],
    }
}
Path(os.environ["MAKI_OUTPUT"]).write_text(json.dumps(payload))
""".strip()
    )

    result = core.run_local_action(
        "./echo",
        "previous",
        {"message": "hello", "prefix": "hi: "},
        base_dir=tmp_path,
    )

    assert result == {"result": "hi: hello|previous", "prefix": "hi: "}
    assert capsys.readouterr().out == ""


def test_run_local_action_resolves_inputs_defaults_expressions_and_prev(tmp_path) -> None:
    action_dir = tmp_path / "echo"
    action_dir.mkdir()
    (action_dir / "action.yaml").write_text(
        """
name: echo
inputs:
  message:
    required: true
  prefix:
    default: ">> "
  extra:
    default: fallback
runs:
  using: python
  main: action.py
""".strip()
    )
    (action_dir / "action.py").write_text(
        """
import json
import os
from pathlib import Path

inputs = json.loads(os.environ["MAKI_INPUTS"])
Path(os.environ["MAKI_OUTPUT"]).write_text(
    json.dumps(
        {
            "result": f"{inputs['prefix']}{inputs['message']}",
            "prev": os.environ["MAKI_PREV"],
            "extra": inputs["extra"],
        }
    )
)
""".strip()
    )

    result = core.run_local_action(
        "./echo",
        "prev text",
        {
            "message": "${{ steps.seed.outputs.result }}:$PREV",
            "prefix": "${{ steps.seed.outputs.prefix }}",
        },
        expr_context={"steps": {"seed": {"outputs": {"result": "ready", "prefix": "::"}}}},
        base_dir=tmp_path,
    )

    assert result == {
        "result": "::ready:prev text",
        "prev": "prev text",
        "extra": "fallback",
    }


def test_run_local_action_returns_empty_outputs_when_file_missing(tmp_path) -> None:
    action_dir = tmp_path / "echo"
    action_dir.mkdir()
    (action_dir / "maki-action.yaml").write_text(
        """
name: echo
runs:
  using: python
  main: action.py
""".strip()
    )
    (action_dir / "action.py").write_text("print('no outputs')")

    result = core.run_local_action("./echo", "prev", {}, base_dir=tmp_path)

    assert result == {}


def test_run_local_action_required_input_missing_fails(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    action_dir = tmp_path / "echo"
    action_dir.mkdir()
    (action_dir / "maki-action.yaml").write_text(
        """
name: echo
inputs:
  message:
    required: true
runs:
  using: python
  main: action.py
""".strip()
    )
    (action_dir / "action.py").write_text("raise SystemExit(0)")

    result = core.run_local_action("./echo", "prev", {}, base_dir=tmp_path)

    assert result is None
    assert "requires input 'message'" in capsys.readouterr().out


def test_run_local_action_unsupported_runs_using_fails(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    action_dir = tmp_path / "echo"
    action_dir.mkdir()
    (action_dir / "maki-action.yaml").write_text(
        """
name: echo
runs:
  using: node
  main: action.js
""".strip()
    )

    result = core.run_local_action("./echo", "prev", {}, base_dir=tmp_path)

    assert result is None
    assert "only supports runs.using: python" in capsys.readouterr().out


def test_run_local_action_malformed_output_json_fails(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    action_dir = tmp_path / "echo"
    action_dir.mkdir()
    (action_dir / "maki-action.yaml").write_text(
        """
name: echo
runs:
  using: python
  main: action.py
""".strip()
    )
    (action_dir / "action.py").write_text(
        """
import os
from pathlib import Path

Path(os.environ["MAKI_OUTPUT"]).write_text("{not json")
""".strip()
    )

    result = core.run_local_action("./echo", "prev", {}, base_dir=tmp_path)

    assert result is None
    assert "output JSON is malformed" in capsys.readouterr().out


def test_run_local_action_nonzero_exit_fails(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    action_dir = tmp_path / "echo"
    action_dir.mkdir()
    (action_dir / "maki-action.yaml").write_text(
        """
name: echo
runs:
  using: python
  main: action.py
""".strip()
    )
    (action_dir / "action.py").write_text(
        """
import sys

print("boom")
sys.exit(2)
""".strip()
    )

    result = core.run_local_action("./echo", "prev", {}, base_dir=tmp_path)

    assert result is None
    assert "local action failed: boom" in capsys.readouterr().out


@pytest.mark.parametrize("action", ["maki/auto", "maki/report"])
def test_builtin_passthrough_actions(action: str, capsys: pytest.CaptureFixture[str]) -> None:
    result = core.run_builtin_action(
        action,
        "agent output",
        JobDef(name="demo", on="manual"),
        ConfirmStore(),
    )

    assert result == {"result": "agent output"}
    assert "agent output" in capsys.readouterr().out


def test_builtin_agent_calls_run_and_wait_with_defaults_and_outputs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def fake_run_and_wait(**kwargs):
        captured.update(kwargs)
        return agent.AgentResult(
            status=agent.Status.COMPLETED,
            output="draft ready",
            session_id="session-123",
        )

    monkeypatch.setattr(agent, "run_and_wait", fake_run_and_wait)

    result = core.run_builtin_action(
        "maki/agent",
        "previous context",
        JobDef(name="demo", on="manual"),
        ConfirmStore(),
        {"prompt": "Reply draft. $PREV"},
    )

    assert captured == {
        "prompt": "Reply draft. previous context",
        "cwd": ".",
        "model": "haiku",
        "timeout": 180,
        "session_id": None,
    }
    assert result == {
        "result": "draft ready",
        "status": "completed",
        "session_id": "session-123",
    }
    output = capsys.readouterr().out
    assert "completed" in output
    assert "draft ready" in output


def test_builtin_agent_resolves_expressions_and_reuses_session_id_in_later_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_calls: list[dict[str, object]] = []
    shell_calls: list[str] = []

    def fake_run_and_wait(**kwargs):
        agent_calls.append(kwargs)
        if len(agent_calls) == 1:
            return agent.AgentResult(
                status=agent.Status.COMPLETED,
                output="draft 1",
                session_id="session-1",
            )
        return agent.AgentResult(
            status=agent.Status.CONFIRM,
            output="continue?",
            session_id="session-1",
        )

    def fake_shell_step(
        step: StepDef,
        resolved_cmd: str,
        prev_output: str,
        steps_context: dict[str, dict],
    ) -> str:
        shell_calls.append(step.name)
        if step.name == "seed-model":
            return "sonnet"
        if step.name == "seed-timeout":
            return "240"
        raise AssertionError(f"unexpected shell step: {step.name}")

    monkeypatch.setattr(agent, "run_and_wait", fake_run_and_wait)
    monkeypatch.setattr(core, "run_shell_step", fake_shell_step)

    config = Config(
        jobs=[
            JobDef(
                name="manual-job",
                on="manual",
                steps=[
                    StepDef(name="seed-model", run="model"),
                    StepDef(name="seed-timeout", run="timeout"),
                    StepDef(
                        name="draft",
                        uses="maki/agent",
                        with_options={
                            "prompt": "Reply draft. $PREV",
                            "cwd": "/tmp/${{ steps.seed-model.outputs.result }}",
                            "model": "${{ steps.seed-model.outputs.result }}",
                            "timeout": "${{ steps.seed-timeout.outputs.result }}",
                            "session_id": "",
                        },
                    ),
                    StepDef(
                        name="followup",
                        uses="maki/agent",
                        with_options={
                            "prompt": "Continue ${{ steps.draft.outputs.result }}",
                            "cwd": "/repo/${{ steps.draft.outputs.session_id }}",
                            "model": "${{ steps.seed-model.outputs.result }}",
                            "timeout": "${{ steps.seed-timeout.outputs.result }}",
                            "session_id": "${{ steps.draft.outputs.session_id }}",
                        },
                    ),
                ],
            )
        ],
    )
    loop_ctx = LoopContext()

    core.process_event(
        Event(source=EventSource.USER, name="manual", data={"input": "initial"}),
        config,
        loop_ctx,
        ConfirmStore(),
    )

    assert shell_calls == ["seed-model", "seed-timeout"]
    assert agent_calls == [
        {
            "prompt": "Reply draft. 240",
            "cwd": "/tmp/sonnet",
            "model": "sonnet",
            "timeout": 240,
            "session_id": None,
        },
        {
            "prompt": "Continue draft 1",
            "cwd": "/repo/session-1",
            "model": "sonnet",
            "timeout": 240,
            "session_id": "session-1",
        },
    ]
    assert loop_ctx.last_results["manual"] == "continue?"


def test_builtin_agent_missing_prompt_fails_clearly(capsys: pytest.CaptureFixture[str]) -> None:
    result = core.run_builtin_action(
        "maki/agent",
        "previous context",
        JobDef(name="demo", on="manual"),
        ConfirmStore(),
        {},
    )

    assert result is None
    assert "requires non-empty with.prompt" in capsys.readouterr().out


def test_builtin_agent_invalid_timeout_fails_clearly(capsys: pytest.CaptureFixture[str]) -> None:
    result = core.run_builtin_action(
        "maki/agent",
        "previous context",
        JobDef(name="demo", on="manual"),
        ConfirmStore(),
        {"prompt": "draft", "timeout": "soon"},
    )

    assert result is None
    assert "timeout must be an integer" in capsys.readouterr().out


def test_builtin_agent_run_and_wait_exception_fails_cleanly(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_run_and_wait(**kwargs):
        raise RuntimeError("ai-cli exploded")

    monkeypatch.setattr(agent, "run_and_wait", fake_run_and_wait)

    result = core.run_builtin_action(
        "maki/agent",
        "previous context",
        JobDef(name="demo", on="manual"),
        ConfirmStore(),
        {"prompt": "draft"},
    )

    assert result is None
    assert "maki/agent failed: ai-cli exploded" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("choice", "edit_text", "expected"),
    [
        (
            ConfirmChoice.ACCEPT,
            None,
            {
                "result": "draft",
                "choice": "accept",
                "edit_text": "",
                "original": "draft",
            },
        ),
        (
            ConfirmChoice.EDIT,
            "revise this",
            {
                "result": "revise this",
                "choice": "edit",
                "edit_text": "revise this",
                "original": "draft",
            },
        ),
        (
            ConfirmChoice.REJECT,
            None,
            {
                "result": "",
                "choice": "reject",
                "edit_text": "",
                "original": "draft",
            },
        ),
    ],
)
def test_builtin_confirm_maps_choices_without_blocking(
    monkeypatch: pytest.MonkeyPatch,
    choice: ConfirmChoice,
    edit_text: str | None,
    expected: dict[str, str],
) -> None:
    captured: dict = {}

    def fake_wait_for_confirm(**kwargs):
        captured.update(kwargs)
        return choice, edit_text

    monkeypatch.setattr(core, "wait_for_confirm", fake_wait_for_confirm)
    store = ConfirmStore()
    job = JobDef(name="demo", on="manual")

    result = core.run_builtin_action(
        "maki/confirm",
        "draft",
        job,
        store,
        {"open_browser": True},
    )

    assert result == expected
    assert captured == {
        "store": store,
        "job_name": "demo",
        "agent_output": "draft",
        "open_browser": True,
    }
