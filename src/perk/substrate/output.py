"""Human-vs-machine output split (python-cli-guidelines.md §7).

- ``user_output`` -> **stderr**: all human-facing text (status, progress, errors).
- ``machine_output`` -> **stdout**: structured/script data (JSON, paths, activation).

Keeping them on separate streams lets a supervisor parse stdout while progress flows
to stderr uncorrupted.
"""

import os
import shutil
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import click

# Module-level output revision, bumped by every ``user_output`` AND every ``machine_output`` call
# (stdout and stderr interleave on the same terminal interactively). ``io_step`` records it at
# step-emit time and rewrites the step line in place only when it is unchanged at resolution —
# any interleaved output falls back to plain append, so the rewrite can never erase a foreign line.
_OUTPUT_REVISION = 0


def user_output(message: str = "", *, nl: bool = True) -> None:
    """Write a human-facing message to stderr."""
    global _OUTPUT_REVISION
    _OUTPUT_REVISION += 1
    click.echo(message, err=True, nl=nl)


def machine_output(message: str = "", *, nl: bool = True) -> None:
    """Write script/machine-readable data to stdout."""
    global _OUTPUT_REVISION
    _OUTPUT_REVISION += 1
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


class StepHandle:
    """The resolution handle :func:`io_step` yields — resolve the step with :meth:`done` or
    :meth:`warn` exactly once.

    Rewrite eligibility and the output revision are recorded at construction (step-emit time);
    resolution rewrites the ``\u203a`` step line in place only when eligible AND no output landed
    in between, else appends a plain ``log_done``/``log_warn`` line (the append-only shape
    CliRunner/CI/piped stderr always sees). A second resolution call falls back to a plain append
    line (defensive; never raises).
    """

    def __init__(self, attempt: str) -> None:
        self.resolved = False
        self._rewrite = _rewrite_eligible(attempt)
        self._revision = _OUTPUT_REVISION

    def done(self, message: str) -> None:
        """Resolve the step as **completed** (``\u2713``)."""
        self._resolve("\u2713", message, log_done)

    def warn(self, message: str) -> None:
        """Resolve the step as **degraded / skipped** (``\u26a0``)."""
        self._resolve("\u26a0", message, log_warn)

    def _resolve(self, glyph: str, message: str, plain: Callable[[str], None]) -> None:
        if self.resolved:
            plain(message)  # defensive double-resolve: append, never raise
            return
        rewrite_now = self._rewrite and self._revision == _OUTPUT_REVISION
        self.resolved = True
        if rewrite_now:
            # Cursor up one line + erase it, then write the final glyph line in its place.
            user_output(f"\x1b[1A\x1b[2K  {glyph} {message}")
        else:
            plain(message)


def _rewrite_eligible(attempt: str) -> bool:
    """Whether the just-emitted step line may be rewritten in place at resolution.

    The exact gate ``print_launch_banner`` uses (interactive stderr, ``NO_COLOR`` unset) plus a
    width check: a step line wider than the terminal wraps onto two rows, and cursor-up-one would
    erase the wrong row — so a wrapped line always falls back to plain append.
    """
    if not sys.stderr.isatty() or os.environ.get("NO_COLOR"):
        return False
    return len("  \u203a ") + len(attempt) <= shutil.get_terminal_size().columns


@contextmanager
def io_step(attempt: str) -> Iterator[StepHandle]:
    """Narrate one perceptible wait: emit the ``\u203a {attempt}`` step line, yield a handle whose
    :meth:`~StepHandle.done` / :meth:`~StepHandle.warn` resolves it, and **auto-resolve** with
    ``done(attempt)`` on a clean exit — "every step resolves" is structural, not a convention.

    An exception escaping the block leaves the step line unresolved on purpose: the error text
    the ``fail(...)`` boundary prints immediately below IS the resolution, and for a hang the
    dangling ``\u203a`` pinpoints where (python-cli-guidelines.md §7.5).

    On an interactive terminal (``NO_COLOR`` unset, unwrapped line, no interleaved output) the
    resolution rewrites the step line in place; everywhere else (CliRunner, CI, piped stderr) the
    output is the deterministic ANSI-free two-line step->resolution shape.

    Not designed for nesting: an inner step bumps the output revision, so an outer step naturally
    falls back to append mode (no current site nests).
    """
    log_step(attempt)
    handle = StepHandle(attempt)
    yield handle
    if not handle.resolved:
        handle.done(attempt)


def user_confirm(prompt: str, *, default: bool = False) -> bool:
    """Confirm with the user, flushing stderr first to avoid a buffering hang.

    Prefer a context-bound console when one is available; use this for standalone
    code without context access.
    """
    sys.stderr.flush()
    return click.confirm(prompt, default=default, err=True)
