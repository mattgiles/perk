"""Human-vs-machine output split (python-cli-guidelines.md §7).

- ``user_output`` -> **stderr**: all human-facing text (status, progress, errors).
- ``machine_output`` -> **stdout**: structured/script data (JSON, paths, activation).

Keeping them on separate streams lets a supervisor parse stdout while progress flows
to stderr uncorrupted.
"""

from __future__ import annotations

import sys

import click


def user_output(message: str = "", *, nl: bool = True) -> None:
    """Write a human-facing message to stderr."""
    click.echo(message, err=True, nl=nl)


def machine_output(message: str = "", *, nl: bool = True) -> None:
    """Write script/machine-readable data to stdout."""
    click.echo(message, err=False, nl=nl)


def user_confirm(prompt: str, *, default: bool = False) -> bool:
    """Confirm with the user, flushing stderr first to avoid a buffering hang.

    Prefer a context-bound console when one is available; use this for standalone
    code without context access.
    """
    sys.stderr.flush()
    return click.confirm(prompt, default=default, err=True)
