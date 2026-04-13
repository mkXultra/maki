from __future__ import annotations

import os
import platform
import re
import subprocess
import time

import click

from maki.config import Config, JobDef, StepDef
from maki.confirm import ConfirmChoice, ConfirmRequest, ConfirmStore
from maki.context import LoopContext
from maki.event import Event, EventSource
from maki.user_input import ask_idle
from maki.watcher import run_watchers
from maki.web import start_server


# --- Expression engine for ${{ }} syntax ---

def resolve_expressions(text: str, context: dict) -> str:
    """Replace ${{ expr }} with evaluated values from context.

    Context is a nested dict like:
      {"steps": {"generate": {"outputs": {"result": "..."}}}}

    Supports:
      ${{ steps.name.outputs.key }}
      ${{ steps.name.outputs.key == 'value' }}
      ${{ steps.name.outputs.key != 'value' }}
    """
    def replacer(match: re.Match) -> str:
        expr = match.group(1).strip()
        # Comparison: steps.x.outputs.y == 'value'
        cmp_match = re.match(r"(.+?)\s*(==|!=)\s*'([^']*)'", expr)
        if cmp_match:
            ref, op, value = cmp_match.group(1).strip(), cmp_match.group(2), cmp_match.group(3)
            resolved = _resolve_ref(ref, context)
            if op == "==":
                return "true" if resolved == value else "false"
            else:
                return "true" if resolved != value else "false"
        # Simple reference
        return _resolve_ref(expr, context)

    return re.sub(r"\$\{\{\s*(.+?)\s*\}\}", replacer, text)


def _resolve_ref(ref: str, context: dict) -> str:
    """Resolve a dotted reference like steps.generate.outputs.result."""
    parts = ref.split(".")
    current = context
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return ""
    return str(current) if current is not None else ""


def eval_condition(condition: str, context: dict) -> bool:
    """Evaluate an if condition. Returns True if step should run."""
    resolved = resolve_expressions(condition, context)
    return resolved.lower() not in ("false", "", "0")


def resolve_step_value(value: object, context: dict, prev_output: str) -> object:
    """Resolve expressions in step option values and expand $PREV in strings."""
    if isinstance(value, str):
        return resolve_expressions(value, context).replace("$PREV", prev_output)
    if isinstance(value, dict):
        return {k: resolve_step_value(v, context, prev_output) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_step_value(item, context, prev_output) for item in value]
    return value


# --- Main loop ---

def run_loop(config: Config, once: bool = False) -> None:
    loop_ctx = LoopContext()
    store = ConfirmStore()

    url = start_server(store)
    click.echo(f"maki started (interval: {config.default_interval}s)")
    click.echo(f"Dashboard: {url}")

    while True:
        loop_ctx.next_tick()
        click.echo(f"\n--- tick {loop_ctx.tick} ---")

        events = collect_events(config)

        if not events:
            user_task = ask_idle()
            if user_task:
                events.append(Event(
                    source=EventSource.USER,
                    name="manual",
                    data={"input": user_task},
                ))

        for event in events:
            process_event(event, config, loop_ctx, store)

        if once:
            click.echo("--once mode: exiting after 1 tick")
            break

        click.echo(f"Sleeping {config.default_interval}s...")
        time.sleep(config.default_interval)


def collect_events(config: Config) -> list[Event]:
    return run_watchers(config)


def process_event(event: Event, config: Config, loop_ctx: LoopContext, store: ConfirmStore) -> None:
    click.echo(f"Processing event: {event.source.value}/{event.name}")

    job = find_job(event, config)
    if not job:
        click.echo(f"  No job defined for event '{event.name}'")
        return

    click.echo(f"  Job: {job.name} ({len(job.steps)} steps)")

    # GA-style context: steps.<name>.outputs.<key>
    steps_context: dict[str, dict] = {}
    expr_context = {"steps": steps_context}

    # Seed initial input from event
    prev_output = event.data.get("output") or event.data.get("input") or ""

    for i, step in enumerate(job.steps):
        step_id = step.name or f"step_{i + 1}"

        # Check if condition
        if step.if_condition:
            if not eval_condition(step.if_condition, expr_context):
                click.echo(f"  [{step_id}] skipped (if: false)")
                steps_context[step_id] = {"outputs": {"result": ""}, "outcome": "skipped"}
                continue

        if step.run:
            resolved_cmd = resolve_expressions(step.run, expr_context)
            click.echo(f"  [{step_id}] run: {resolved_cmd[:80]}")
            output = run_shell_step(step, resolved_cmd, prev_output, steps_context)
            if output is None:
                click.echo(f"  [{step_id}] failed, stopping job")
                steps_context[step_id] = {"outputs": {"result": ""}, "outcome": "failure"}
                return
            steps_context[step_id] = {"outputs": {"result": output}, "outcome": "success"}
            prev_output = output

        elif step.uses:
            click.echo(f"  [{step_id}] uses: {step.uses}")
            outputs = run_builtin_action(step.uses, prev_output, job, store, step.with_options, expr_context)
            if outputs is None:
                steps_context[step_id] = {"outputs": {"result": ""}, "outcome": "failure"}
                return
            steps_context[step_id] = {"outputs": outputs, "outcome": "success"}
            prev_output = outputs.get("result", "")

    loop_ctx.last_results[event.name] = prev_output
    click.echo(f"  Job {job.name} completed")


def run_shell_step(
    step: StepDef,
    resolved_cmd: str,
    prev_output: str,
    steps_context: dict[str, dict],
) -> str | None:
    """Run a shell command with step outputs available as env vars."""
    env = {**os.environ, "PREV": prev_output}
    # Also export flattened step outputs for shell convenience
    for step_name, step_data in steps_context.items():
        for key, value in step_data.get("outputs", {}).items():
            env_key = f"STEPS_{step_name}_{key}".upper().replace("-", "_")
            env[env_key] = str(value)
    try:
        result = subprocess.run(
            resolved_cmd,
            shell=True,
            cwd=step.cwd,
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            stderr = result.stderr.strip()
            click.echo(f"    exit code {result.returncode}: {stderr[:200]}")
            return None
        return output
    except subprocess.TimeoutExpired:
        click.echo("    timed out")
        return None
    except Exception as e:
        click.echo(f"    error: {e}")
        return None


def run_builtin_action(
    action: str,
    prev: str,
    job: JobDef,
    store: ConfirmStore,
    options: dict | None = None,
    expr_context: dict | None = None,
) -> dict[str, str] | None:
    """Run a builtin action. Returns outputs dict or None on rejection/failure."""
    options = options or {}
    expr_context = expr_context or {}

    if action == "maki/auto":
        click.echo(f"    {prev[:200]}")
        return {"result": prev}

    elif action == "maki/report":
        click.echo("\n" + "=" * 60)
        click.echo(prev)
        click.echo("=" * 60)
        return {"result": prev}

    elif action == "maki/confirm":
        auto_open = options.get("open_browser", False)
        choice, edit_text = wait_for_confirm(
            store=store,
            job_name=job.name,
            agent_output=prev,
            open_browser=auto_open,
        )
        if choice == ConfirmChoice.ACCEPT:
            click.echo("    Accepted")
            return {"result": prev, "choice": "accept", "edit_text": "", "original": prev}
        elif choice == ConfirmChoice.EDIT:
            click.echo("    Edited")
            return {"result": edit_text or prev, "choice": "edit", "edit_text": edit_text or "", "original": prev}
        else:
            click.echo("    Rejected")
            return {"result": "", "choice": "reject", "edit_text": "", "original": prev}

    elif action == "maki/agent":
        resolved_options = resolve_step_value(options, expr_context, prev)
        prompt = str(resolved_options.get("prompt", "")) if isinstance(resolved_options, dict) else ""
        if not prompt.strip():
            click.echo("    error: maki/agent requires non-empty with.prompt")
            return None

        model = str(resolved_options.get("model", "haiku"))
        cwd = str(resolved_options.get("cwd", "."))
        timeout_raw = resolved_options.get("timeout", 180)
        try:
            timeout = int(timeout_raw)
        except (TypeError, ValueError):
            click.echo(f"    error: maki/agent timeout must be an integer, got {timeout_raw!r}")
            return None

        session_id_value = resolved_options.get("session_id")
        session_id = None if session_id_value in (None, "") else str(session_id_value)

        from maki import agent as maki_agent

        try:
            result = maki_agent.run_and_wait(
                prompt=prompt,
                cwd=cwd,
                model=model,
                timeout=timeout,
                session_id=session_id,
            )
        except Exception as e:
            detail = str(e).strip() or e.__class__.__name__
            click.echo(f"    error: maki/agent failed: {detail}")
            return None
        click.echo(f"    {result.status.value}")
        if result.output:
            click.echo(result.output)
        return {
            "result": result.output,
            "status": result.status.value,
            "session_id": result.session_id or "",
        }

    return {"result": prev}


def wait_for_confirm(
    store: ConfirmStore,
    job_name: str,
    agent_output: str,
    open_browser: bool = False,
) -> tuple[ConfirmChoice, str | None]:
    req = ConfirmRequest(
        id=ConfirmRequest.new_id(),
        job_name=job_name,
        agent_output=agent_output,
    )
    store.add(req)

    confirm_url = f"http://127.0.0.1:7831/?token={store.token}"
    click.echo(f"    Confirm required: {confirm_url}")
    notify_desktop(f"maki: {job_name} needs confirmation", confirm_url)

    if open_browser:
        import webbrowser
        webbrowser.open(confirm_url)

    req.event.wait()
    store.remove(req.id)

    click.echo(f"    User chose: {req.response.value if req.response else 'none'}")
    return req.response or ConfirmChoice.REJECT, req.edit_text


def notify_desktop(title: str, url: str) -> None:
    system = platform.system()
    try:
        if system == "Linux":
            subprocess.Popen(
                ["notify-send", title, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif system == "Darwin":
            subprocess.Popen(
                ["osascript", "-e", f'display notification "{url}" with title "{title}"'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except FileNotFoundError:
        pass


def find_job(event: Event, config: Config) -> JobDef | None:
    # Direct job match via --job flag
    if event.name.startswith("__job__:"):
        job_name = event.name.split(":", 1)[1]
        for job in config.jobs:
            if job.name == job_name:
                return job
        return None
    # Normal trigger match
    for job in config.jobs:
        if job.on == event.name:
            return job
    return None
