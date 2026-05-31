"""Error vocabulary for the CLI (python-cli-guidelines.md §5).

``UserFacingCliError`` is for *expected*, user-triggerable failures — Click intercepts
it at every level, prints ``Error: …`` in red, and exits 1. Use ``RuntimeError`` only
for impossible states / bugs.

``Ensure`` provides LBYL precondition checks that all raise ``UserFacingCliError`` with
an actionable message. (Domain-specific checks that depend on git/GitHub state are added
as those gateways land in later turns.)
"""

from pathlib import Path
from typing import IO, Any, TypeVar

import click

T = TypeVar("T")


class UserFacingCliError(click.ClickException):
    """An expected failure a user can trigger (bad input, missing file, precondition).

    Click intercepts it at every command level and exits 1; we override ``show`` only to
    style the ``Error:`` prefix in red. The optional ``error_type`` is a stable code for the
    supervisor ``--json`` surface (cli-vs-pi.md §3.2); human output ignores it.
    """

    def __init__(self, message: str, *, error_type: str | None = None) -> None:
        super().__init__(message)
        self.error_type = error_type

    def show(self, file: IO[Any] | None = None) -> None:
        click.echo(click.style("Error: ", fg="red") + self.format_message(), err=True)


class Ensure:
    """LBYL precondition checks. Each raises ``UserFacingCliError`` with a clear message."""

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
