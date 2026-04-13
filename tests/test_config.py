from __future__ import annotations

from pathlib import Path
import re

import pytest

from maki.config import Config, WORKFLOW_ENV_ERROR


def test_parses_job_and_step_env(tmp_path: Path) -> None:
    config = load_config(
        tmp_path,
        """
jobs:
  demo:
    on: manual
    env:
      JOB_FLAG: enabled
      RETRIES: 3
    steps:
      - name: shell
        run: echo hi
        env:
          STEP_FLAG: true
          EMPTY_VALUE:
""",
    )

    job = config.jobs[0]
    assert job.env == {"JOB_FLAG": "enabled", "RETRIES": "3"}
    assert job.steps[0].env == {"STEP_FLAG": "True", "EMPTY_VALUE": ""}


def load_config(tmp_path: Path, text: str) -> Config:
    path = tmp_path / "maki.yaml"
    path.write_text(text)
    return Config._from_file(path)


def test_parses_on_blocks_watchers_jobs_and_with_options(tmp_path: Path) -> None:
    config = load_config(
        tmp_path,
        """
on:
  schedule:
    interval: 42
  inbox:
    enabled: false
    schedule: "*/5 * * * *"
    steps:
      - name: poll
        run: echo issue
        cwd: /tmp
jobs:
  triage:
    on: inbox
    steps:
      - name: summarize
        run: echo "$PREV"
        cwd: /work
      - name: report
        uses: maki/report
        with:
          format: plain
          nested:
            answer: 42
      - name: draft
        uses: maki/agent
        with:
          prompt: "Reply draft. $PREV"
          timeout: 180
""",
    )

    assert config.default_interval == 42
    assert len(config.watchers) == 1
    watcher = config.watchers[0]
    assert watcher.name == "inbox"
    assert watcher.enabled is False
    assert watcher.schedule == "*/5 * * * *"
    assert watcher.steps == [{"name": "poll", "run": "echo issue", "cwd": "/tmp"}]

    assert len(config.jobs) == 1
    job = config.jobs[0]
    assert job.name == "triage"
    assert job.on == "inbox"
    assert job.steps[0].name == "summarize"
    assert job.steps[0].run == 'echo "$PREV"'
    assert job.steps[0].cwd == "/work"
    assert job.steps[1].uses == "maki/report"
    assert job.steps[1].with_options == {
        "format": "plain",
        "nested": {"answer": 42},
    }
    assert job.steps[2].uses == "maki/agent"
    assert job.steps[2].with_options == {
        "prompt": "Reply draft. $PREV",
        "timeout": 180,
    }


def test_rejects_unsupported_top_level_workflow_env(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=re.escape(WORKFLOW_ENV_ERROR)):
        load_config(
            tmp_path,
            """
env:
  GLOBAL_FLAG: nope
jobs:
  demo:
    on: manual
    steps:
      - run: echo hi
""",
        )



def test_accepts_local_action_refs(tmp_path: Path) -> None:
    config = load_config(
        tmp_path,
        """
jobs:
  demo:
    on: manual
    steps:
      - uses: ./examples/local-python-action/echo
      - uses: ../shared/action
""",
    )

    assert config.jobs[0].steps[0].uses == "./examples/local-python-action/echo"
    assert config.jobs[0].steps[1].uses == "../shared/action"
    assert config.base_dir == tmp_path.resolve()


@pytest.mark.parametrize(
    ("yaml_text", "message"),
    [
        (
            """
jobs:
  demo:
    on: manual
    steps:
      - name: empty
""",
            "neither 'run' nor 'uses'",
        ),
        (
            """
jobs:
  demo:
    on: manual
    steps:
      - run: echo hi
        uses: maki/report
""",
            "both 'run' and 'uses'",
        ),
        (
            """
jobs:
  demo:
    on: manual
    steps:
      - uses: vendor/echo
""",
            "unknown action 'vendor/echo'",
        ),
        (
            """
jobs:
  demo:
    on: manual
    steps:
      - uses: 123
""",
            "step uses must be a string",
        ),
        (
            """
jobs:
  demo:
    on: manual
    env:
      - nope
    steps:
      - run: echo hi
""",
            "Job 'demo' env must be a mapping",
        ),
        (
            """
jobs:
  demo:
    on: manual
    env:
      nested:
        nope: true
    steps:
      - run: echo hi
""",
            r"Job 'demo' env\['nested'\] must be a scalar",
        ),
        (
            """
jobs:
  demo:
    on: manual
    steps:
      - run: echo hi
        env:
          123: nope
""",
            "env keys must be strings",
        ),
        (
            """
jobs:
  demo:
    on: manual
    steps:
      - name: shell
        run: echo hi
        env:
          - nope
""",
            "step 'shell' env must be a mapping",
        ),
    ],
)
def test_rejects_invalid_step_shapes(tmp_path: Path, yaml_text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_config(tmp_path, yaml_text)


def test_rejects_job_trigger_without_matching_watcher(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no watcher with that name exists"):
        load_config(
            tmp_path,
            """
on:
  known:
    steps: []
jobs:
  demo:
    on: missing
    steps:
      - run: echo hi
""",
        )
