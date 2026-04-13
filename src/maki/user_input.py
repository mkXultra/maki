"""UserInput: terminal-based fallback and idle prompt."""
from __future__ import annotations

import click


def ask_idle() -> str | None:
    """Ask user if they have anything to do during idle."""
    click.echo("\nNo events detected.")
    response = click.prompt(
        "Anything you'd like me to do? (enter to skip)",
        type=str,
        default="",
        show_default=False,
    )
    return response.strip() or None
