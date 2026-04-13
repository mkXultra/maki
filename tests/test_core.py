from __future__ import annotations

from types import SimpleNamespace

import pytest

from maki import core
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
