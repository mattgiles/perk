"""Error vocabulary for the CLI: raise + check + report.

``UserFacingCliError`` is for *expected*, user-triggerable failures — Click intercepts
it at every level, prints ``Error: …`` in red, and exits 1. Use ``RuntimeError`` only
for impossible states / bugs.

``Ensure`` provides LBYL precondition checks that all raise ``UserFacingCliError`` with
an actionable message.

``fail`` is the report half: the canonical supervisor-surface failure path (a stable
failure JSON under ``--json``, styled stderr text otherwise, then a stable exit code via
``EXIT_FOR_TYPE``) shared by every ``--json``-capable command.
"""

import json
from pathlib import Path
from typing import IO, Any, TypeVar

import click

from perk.substrate.output import machine_output, user_output

T = TypeVar("T")

# error_type -> process exit code (default 1).
EXIT_FOR_TYPE = {"not_a_repo": 2}


def fail(
    ctx: click.Context,
    *,
    as_json: bool,
    error_type: str,
    message: str,
    extra: dict[str, object] | None = None,
) -> None:
    """The shared failure path: a stable failure JSON (or styled stderr text) + a stable exit code.

    ``extra`` is merged into the failure JSON **after** the three base keys — the dry-run-capable
    verbs pass ``{"dry_run": False}`` to preserve their exact historical key order.
    """
    if as_json:
        machine_output(
            json.dumps(
                {"success": False, "error_type": error_type, "message": message, **(extra or {})}
            )
        )
    else:
        user_output(click.style("Error: ", fg="red") + message)
    ctx.exit(EXIT_FOR_TYPE.get(error_type, 1))


class UserFacingCliError(click.ClickException):
    """An expected failure a user can trigger (bad input, missing file, precondition).

    Click intercepts it at every command level and exits 1; we override ``show`` only to
    style the ``Error:`` prefix in red. The optional ``error_type`` is a stable code for the
    supervisor ``--json`` surface; human output ignores it.
    """

    def __init__(self, message: str, *, error_type: str | None = None) -> None:
        super().__init__(message)
        self.error_type = error_type

    def show(self, file: IO[Any] | None = None) -> None:
        click.echo(click.style("Error: ", fg="red") + self.format_message(), err=True)


class Ensure:
    """LBYL precondition checks. Each raises ``UserFacingCliError`` with a clear message.

    A narrowing ``assert x is not None`` in CLI command code is a review-magnet: it vanishes
    under ``python -O`` and raises an unfriendly ``AssertionError`` at the user. ``Ensure.
    not_none(value, message)`` is the drop-in replacement — it raises the Click-intercepted
    ``UserFacingCliError`` (clean ``Error: …``, exit 1) AND narrows ``T | None`` to ``T`` for ty.
    """

    @staticmethod
    def invariant(condition: bool, message: str) -> None:
        if not condition:
            raise UserFacingCliError(message)

    @staticmethod
    def not_none(value: T | None, message: str) -> T:
        if value is None:
            raise UserFacingCliError(message)
        return value

    @staticmethod
    def truthy(value: T, message: str) -> T:
        if not value:
            raise UserFacingCliError(message)
        return value

    @staticmethod
    def not_empty(value: str, message: str) -> str:
        if not value:
            raise UserFacingCliError(message)
        return value

    @staticmethod
    def path_exists(path: Path, message: str) -> Path:
        if not path.exists():
            raise UserFacingCliError(message)
        return path
