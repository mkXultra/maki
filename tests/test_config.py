from __future__ import annotations

from pathlib import Path

import pytest

from maki.config import Config


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
