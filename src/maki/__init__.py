from pathlib import Path

import click

from maki.config import Config
from maki.core import run_loop
from maki.event import Event, EventSource


@click.group()
@click.version_option()
def main() -> None:
    """maki - A lightweight passive AI CLI."""
    pass


@main.command()
@click.option("--once", is_flag=True, help="Run a single tick and exit")
@click.option("--config", "config_path", type=click.Path(exists=True), help="Config file path")
def run(once: bool, config_path: str | None) -> None:
    """Start the main loop."""
    cfg = Config.load(Path(config_path) if config_path else None)
    run_loop(cfg, once=once)


@main.command()
@click.argument("instruction")
@click.option("--config", "config_path", type=click.Path(exists=True), help="Config file path")
@click.option("--job", "job_name", help="Run a specific job by name instead of trigger matching")
def do(instruction: str, config_path: str | None, job_name: str | None) -> None:
    """Run a manual task."""
    cfg = Config.load(Path(config_path) if config_path else None)
    if job_name:
        matched = [j for j in cfg.jobs if j.name == job_name]
        if not matched:
            click.echo(f"Job '{job_name}' not found. Available: {[j.name for j in cfg.jobs]}")
            return
        # Use __job__:<name> as event name for direct job matching
        event = Event(source=EventSource.USER, name=f"__job__:{job_name}", data={"input": instruction})
    else:
        event = Event(source=EventSource.USER, name="manual", data={"input": instruction})
    from maki.confirm import ConfirmStore
    from maki.context import LoopContext
    from maki.core import process_event
    from maki.web import start_server
    store = ConfirmStore()
    url = start_server(store)
    click.echo(f"Dashboard: {url}")
    process_event(event, cfg, LoopContext(), store)


@main.command()
@click.option("--config", "config_path", type=click.Path(exists=True), help="Config file path")
def status(config_path: str | None) -> None:
    """Show current status."""
    cfg = Config.load(Path(config_path) if config_path else None)
    click.echo(f"Default interval: {cfg.default_interval}s")
    click.echo(f"Watchers ({len(cfg.watchers)}):")
    for w in cfg.watchers:
        sched = f", schedule: {w.schedule}" if w.schedule else ", every tick"
        click.echo(f"  - {w.name} ({'enabled' if w.enabled else 'disabled'}{sched})")
    click.echo(f"Jobs ({len(cfg.jobs)}):")
    for j in cfg.jobs:
        step_summary = ", ".join(s.uses or "shell" for s in j.steps)
        click.echo(f"  - {j.name} (on: {j.on}, steps: [{step_summary}])")


@main.command("agent")
@click.option("--model", default="haiku", help="Model to use")
@click.option("--cwd", default=".", help="Working directory")
@click.option("--timeout", default=180, help="Timeout in seconds")
@click.argument("prompt")
def agent_cmd(model: str, cwd: str, timeout: int, prompt: str) -> None:
    """Run an AI agent and print its output. Helper for use in job steps."""
    from maki.agent import run_and_wait
    result = run_and_wait(prompt=prompt, cwd=cwd, model=model, timeout=timeout)
    if result.output:
        click.echo(result.output)


@main.group()
def watch() -> None:
    """Watch for events (run in a separate terminal)."""
    pass


@watch.command("confirm")
@click.option("--port", default=7831, help="Port of running maki instance")
@click.option("--token", required=True, help="Auth token from maki dashboard URL")
def watch_confirm(port: int, token: str) -> None:
    """Watch and respond to confirm requests from CLI."""
    import json
    import time
    import urllib.request

    base = f"http://127.0.0.1:{port}"
    click.echo(f"Watching for confirms on {base}...")

    while True:
        try:
            req = urllib.request.Request(f"{base}/api/pending?token={token}")
            with urllib.request.urlopen(req) as resp:
                pending = json.loads(resp.read())
        except Exception:
            time.sleep(2)
            continue

        for item in pending:
            click.echo("\n" + "=" * 60)
            click.echo(f"Job: {item['job_name']}")
            click.echo("-" * 60)
            click.echo(item["agent_output"])
            click.echo("=" * 60)

            while True:
                choice = click.prompt(
                    "[a]ccept / [r]eject / [e]dit",
                    type=str,
                    default="a",
                ).lower().strip()
                if choice in ("a", "accept", "r", "reject", "e", "edit"):
                    break

            edit_text = ""
            if choice in ("e", "edit"):
                click.echo("Enter feedback (empty line to finish):")
                lines = []
                while True:
                    line = input()
                    if line == "":
                        break
                    lines.append(line)
                edit_text = "\n".join(lines)

            choice_map = {"a": "accept", "accept": "accept", "r": "reject", "reject": "reject", "e": "edit", "edit": "edit"}
            body = json.dumps({"id": item["id"], "choice": choice_map[choice], "edit_text": edit_text}).encode()
            req = urllib.request.Request(
                f"{base}/api/respond?token={token}",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req)
            click.echo("  Sent.")

        time.sleep(2)
