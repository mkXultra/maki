from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


BUILTIN_ACTIONS = {"maki/confirm", "maki/report", "maki/auto", "maki/agent"}
LOCAL_ACTION_PREFIXES = ("./", "../")
WORKFLOW_ENV_ERROR = (
    "Top-level workflow env is not supported; "
    "use jobs.<job>.env or jobs.<job>.steps[].env"
)


def is_local_action_ref(action_ref: object) -> bool:
    return isinstance(action_ref, str) and action_ref.startswith(LOCAL_ACTION_PREFIXES)


def resolve_action_path(action_ref: str, base_dir: Path) -> Path:
    return (base_dir / action_ref).resolve()


def normalize_action_metadata(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        return None
    return {str(key): value for key, value in raw.items()}


def normalize_env(raw: Any, *, location: str) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{location} env must be a mapping, got {type(raw).__name__}")

    normalized: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise ValueError(f"{location} env keys must be strings, got {type(key).__name__}")
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise ValueError(
                f"{location} env['{key}'] must be a scalar, got {type(value).__name__}"
            )
        normalized[key] = "" if value is None else str(value)
    return normalized


@dataclass
class StepDef:
    """A step is either a shell command (run:) or a builtin action (uses:)."""
    name: str = ""
    run: str | None = None
    uses: str | None = None
    cwd: str = "."
    env: dict[str, str] = field(default_factory=dict)
    with_options: dict = field(default_factory=dict)
    if_condition: str | None = None


@dataclass
class JobDef:
    name: str
    on: str
    env: dict[str, str] = field(default_factory=dict)
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
    base_dir: Path = field(default_factory=lambda: Path.cwd())

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
        if "env" in raw:
            raise ValueError(WORKFLOW_ENV_ERROR)

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
            if not isinstance(job_raw, dict):
                raise ValueError(f"Job '{name}' definition must be a mapping, got {type(job_raw).__name__}")
            job_raw = {("on" if k is True else k): v for k, v in job_raw.items()}
            job_env = normalize_env(job_raw.get("env"), location=f"Job '{name}'")

            steps: list[StepDef] = []
            steps_raw = job_raw.get("steps", [])
            if not isinstance(steps_raw, list):
                raise ValueError(f"Job '{name}' steps must be a list, got {type(steps_raw).__name__}")
            for index, step_raw in enumerate(steps_raw, start=1):
                if not isinstance(step_raw, dict):
                    raise ValueError(
                        f"Job '{name}' step #{index} must be a mapping, got {type(step_raw).__name__}"
                    )
                step_name = step_raw.get("name")
                step_location = (
                    f"Job '{name}' step '{step_name}'"
                    if isinstance(step_name, str) and step_name
                    else f"Job '{name}' step #{index}"
                )
                step_env = normalize_env(step_raw.get("env"), location=step_location)
                steps.append(StepDef(
                    name=step_raw.get("name", ""),
                    run=step_raw.get("run"),
                    uses=step_raw.get("uses"),
                    cwd=step_raw.get("cwd", "."),
                    env=step_env,
                    with_options=step_raw.get("with", {}),
                    if_condition=step_raw.get("if"),
                ))

            jobs.append(JobDef(
                name=name,
                on=job_raw.get("on", "manual"),
                env=job_env,
                steps=steps,
            ))

        config = cls(
            default_interval=default_interval,
            watchers=watchers,
            jobs=jobs,
            base_dir=path.resolve().parent,
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
                if step.uses is not None and not isinstance(step.uses, str):
                    raise ValueError(
                        f"Job '{job.name}' step uses must be a string, got {type(step.uses).__name__}"
                    )
                if step.uses and step.uses not in BUILTIN_ACTIONS and not is_local_action_ref(step.uses):
                    raise ValueError(
                        f"Job '{job.name}' step uses unknown action '{step.uses}'. "
                        f"Available: {sorted(BUILTIN_ACTIONS)} or local refs starting with ./ or ../"
                    )
                if not step.run and not step.uses:
                    raise ValueError(
                        f"Job '{job.name}' has a step with neither 'run' nor 'uses'"
                    )
