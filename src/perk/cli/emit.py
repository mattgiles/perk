"""The CLI-wide result-envelope helpers: one failure path, one success dispatch.

A leaf module at the neutral ``perk/cli/`` level (beside ``context.py``/``ensure.py``) so every
command group — and ``perk_dev`` — shares one implementation without any group importing another
group's ``shared.py``.
"""

import json
from collections.abc import Callable

import click

from perk.substrate.output import machine_output, user_output

# The shared error-type → exit-code map; anything unlisted exits 1.
EXIT_FOR_TYPE: dict[str, int] = {"not_a_repo": 2}


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


def emit(*, as_json: bool, payload: dict[str, object], render: Callable[[], None]) -> None:
    """The shared success dispatch: structured payload → stdout, human render → stderr.

    This is the single place that contract lives: under ``--json`` the ``payload`` is written to
    stdout via ``machine_output``; otherwise ``render()`` is called (and writes human text to
    stderr). Per-command ``_result_to_dict``/``_render_human`` functions are the rendering hooks.
    """
    if as_json:
        machine_output(json.dumps(payload))
    else:
        render()
