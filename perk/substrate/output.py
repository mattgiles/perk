"""Human-vs-machine output split (python-cli-guidelines.md §7).

- ``user_output`` -> **stderr**: all human-facing text (status, progress, errors).
- ``machine_output`` -> **stdout**: structured/script data (JSON, paths, activation).

Keeping them on separate streams lets a supervisor parse stdout while progress flows
to stderr uncorrupted.
"""

import sys

import click


def user_output(message: str = "", *, nl: bool = True) -> None:
    """Write a human-facing message to stderr."""
    click.echo(message, err=True, nl=nl)


def machine_output(message: str = "", *, nl: bool = True) -> None:
    """Write script/machine-readable data to stdout."""
    click.echo(message, err=False, nl=nl)


# The leveled progress-log vocabulary for the cold-door launch path (python-cli-guidelines.md §7).
# Glyph-only, no ANSI color — the glyph carries the semantics — indented two spaces so the lines
# sit in a tidy column beneath the launch banner. All three route through ``user_output`` (stderr),
# so ``--json`` consumers (stdout) are unaffected. The convention is "narrate the waits on the
# critical path": a step earns a line only when it performs perceptible blocking I/O AND its
# outcome gates the launched session.


def log_step(message: str) -> None:
    """An action **starting** — a wait the user is about to sit through (``\u203a``)."""
    user_output(f"  \u203a {message}")


def log_done(message: str) -> None:
    """A milestone **completed** — confirmation a narrated wait finished (``\u2713``)."""
    user_output(f"  \u2713 {message}")


def log_warn(message: str) -> None:
    """A degraded / skipped step — a loud-but-non-fatal note (``\u26a0``)."""
    user_output(f"  \u26a0 {message}")


def user_confirm(prompt: str, *, default: bool = False) -> bool:
    """Confirm with the user, flushing stderr first to avoid a buffering hang.

    Prefer a context-bound console when one is available; use this for standalone
    code without context access.
    """
    sys.stderr.flush()
    return click.confirm(prompt, default=default, err=True)
