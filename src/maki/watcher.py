from __future__ import annotations

import os
import subprocess
from datetime import datetime

import click
from croniter import croniter

from maki.config import Config, WatcherDef
from maki.event import Event, EventSource

# Track last run time per watcher to evaluate cron
_last_run: dict[str, datetime] = {}


def run_watchers(config: Config) -> list[Event]:
    """Run all enabled watchers whose schedule matches."""
    events: list[Event] = []
    now = datetime.now()

    for watcher_def in config.watchers:
        if not watcher_def.enabled:
            continue

        if not should_run(watcher_def, now):
            click.echo(f"  Watcher [{watcher_def.name}]: skipped (not scheduled)")
            continue

        click.echo(f"  Watcher [{watcher_def.name}]: running...")
        result = run_watcher(watcher_def)
        _last_run[watcher_def.name] = now

        if result:
            events.append(result)
            click.echo(f"  Watcher [{watcher_def.name}]: event detected")
        else:
            click.echo(f"  Watcher [{watcher_def.name}]: no changes")

    return events


def should_run(watcher_def: WatcherDef, now: datetime) -> bool:
    """Check if a watcher should run based on its cron schedule."""
    if not watcher_def.schedule:
        return True  # No schedule = run every tick

    last = _last_run.get(watcher_def.name)
    if last is None:
        return True  # First run

    # Check if cron has ticked since last run
    cron = croniter(watcher_def.schedule, last)
    next_run = cron.get_next(datetime)
    return now >= next_run


def run_watcher(watcher_def: WatcherDef) -> Event | None:
    """Run a watcher by executing shell commands, piping output between steps."""
    if not watcher_def.steps:
        return None

    prev_output = ""
    outputs: list[str] = []

    for step in watcher_def.steps:
        cmd = step.get("run")
        cwd = step.get("cwd", ".")
        if not cmd:
            continue

        env = {**os.environ, "PREV": prev_output}

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )
            prev_output = result.stdout.strip()
            if prev_output:
                outputs.append(prev_output)
        except subprocess.TimeoutExpired:
            click.echo(f"    Step timed out: {cmd}")
            prev_output = ""
        except Exception as e:
            click.echo(f"    Step error: {e}")
            prev_output = ""

    if not outputs:
        return None

    return Event(
        source=EventSource.WATCHER,
        name=watcher_def.name,
        data={"output": outputs[-1], "all_outputs": outputs},
    )
