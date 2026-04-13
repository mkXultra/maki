from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


BUILTIN_ACTIONS = {"maki/confirm", "maki/report", "maki/auto"}


@dataclass
class StepDef:
    """A step is either a shell command (run:) or a builtin action (uses:)."""
    name: str = ""
    run: str | None = None
    uses: str | None = None
    cwd: str = "."
    with_options: dict = field(default_factory=dict)
    if_condition: str | None = None


@dataclass
class JobDef:
    name: str
    on: str
    steps: list[StepDef] = field(default_factory=list)


@dataclass
class WatcherDef:
    name: str
    enabled: bool = True
    steps: list[dict] = field(default_factory=list)
    schedule: str | None = None  # cron expression e.g. "*/10 * * * *"


@dataclass
class Config:
    default_interval: int = 300
    watchers: list[WatcherDef] = field(default_factory=list)
    jobs: list[JobDef] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        candidates = [
            path,
            Path("maki.yaml"),
            Path.home() / ".config" / "maki" / "config.yaml",
        ]
        for p in candidates:
            if p and p.exists():
                return cls._from_file(p)
        return cls()

    @classmethod
    def _from_file(cls, path: Path) -> Config:
        raw = yaml.safe_load(path.read_text()) or {}

        # YAML parses 'on:' as boolean True, normalize keys
        raw = {("on" if k is True else k): v for k, v in raw.items()}

        # Parse on: block
        on_block = raw.get("on", {})
        default_interval = 300
        watchers: list[WatcherDef] = []

        for key, value in on_block.items():
            if key == "schedule":
                default_interval = value.get("interval", 300) if isinstance(value, dict) else 300
            else:
                if isinstance(value, dict):
                    steps = value.get("steps", [])
                    enabled = value.get("enabled", True)
                    schedule = value.get("schedule")
                else:
                    steps = []
                    enabled = True
                    schedule = None
                watchers.append(WatcherDef(name=key, enabled=enabled, steps=steps, schedule=schedule))

        # Parse jobs: block
        jobs_block = raw.get("jobs", {})
        jobs: list[JobDef] = []

        for name, job_raw in jobs_block.items():
            job_raw = {("on" if k is True else k): v for k, v in job_raw.items()}

            steps: list[StepDef] = []
            for step_raw in job_raw.get("steps", []):
                steps.append(StepDef(
                    name=step_raw.get("name", ""),
                    run=step_raw.get("run"),
                    uses=step_raw.get("uses"),
                    cwd=step_raw.get("cwd", "."),
                    with_options=step_raw.get("with", {}),
                    if_condition=step_raw.get("if"),
                ))

            jobs.append(JobDef(
                name=name,
                on=job_raw.get("on", "manual"),
                steps=steps,
            ))

        config = cls(
            default_interval=default_interval,
            watchers=watchers,
            jobs=jobs,
        )
        config.validate()
        return config

    def validate(self) -> None:
        valid_triggers = {"manual", "schedule"}
        valid_triggers.update(w.name for w in self.watchers)
        for job in self.jobs:
            if job.on not in valid_triggers:
                raise ValueError(
                    f"Job '{job.name}' has on: '{job.on}' "
                    f"but no watcher with that name exists. "
                    f"Valid triggers: {sorted(valid_triggers)}"
                )
            for step in job.steps:
                if step.run and step.uses:
                    raise ValueError(
                        f"Job '{job.name}' has a step with both 'run' and 'uses'"
                    )
                if step.uses and step.uses not in BUILTIN_ACTIONS:
                    raise ValueError(
                        f"Job '{job.name}' step uses unknown action '{step.uses}'. "
                        f"Available: {sorted(BUILTIN_ACTIONS)}"
                    )
                if not step.run and not step.uses:
                    raise ValueError(
                        f"Job '{job.name}' has a step with neither 'run' nor 'uses'"
                    )
