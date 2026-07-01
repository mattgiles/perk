"""Cross-verb helpers for the ``perk learn`` group."""

import json

import click

from perk.substrate.output import machine_output, user_output

_EXIT_FOR_TYPE = {"not_a_repo": 2}


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
    ctx.exit(_EXIT_FOR_TYPE.get(error_type, 1))
