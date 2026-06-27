"""`perk state new-run` — mint a run_id and write its handoff blob."""

import json
from pathlib import Path
from typing import Any

import click
from pydantic import ConfigDict, RootModel

from perk.boundary import ValidationError, format_validation_error
from perk.cli.alias import alias
from perk.cli.ensure import UserFacingCliError
from perk.state import cache, run_id
from perk.substrate.output import machine_output, user_output


class HandoffArgInput(RootModel[dict[str, object]]):
    """Minimal strict parse: the ``--handoff`` payload must be a JSON object.

    The handoff is open-ended (cache ``HandoffModel`` is ``extra="allow"``), so this only
    enforces the object shape (a list/scalar fails loudly with a field path).
    """

    model_config = ConfigDict(strict=True)


def _read_handoff_arg(value: str) -> dict[str, Any]:
    """Parse a ``--handoff`` argument: a JSON object literal or ``@path`` to one."""
    if value.startswith("@"):
        path = Path(value[1:])
        if not path.is_file():
            raise UserFacingCliError(f"--handoff file not found: {path}")
        raw = path.read_text(encoding="utf-8")
    else:
        raw = value
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UserFacingCliError(f"--handoff is not valid JSON: {exc}") from exc
    try:
        model = HandoffArgInput.model_validate(parsed)
    except ValidationError as exc:
        raise UserFacingCliError(format_validation_error(exc, source="--handoff")) from exc
    return model.root


@alias("nr")
@click.command("new-run")
@click.option(
    "--handoff",
    "handoff_arg",
    help="Handoff JSON object (or @file) to write for the extension to claim.",
)
def new_run(*, handoff_arg: str | None) -> None:
    """Mint a run_id, write its handoff blob, and print the id on stdout.

    \b
    Examples:
      RID=$(perk state new-run)
      RID=$(perk state new-run --handoff '{"mode": "read-only"}')
    """
    data = _read_handoff_arg(handoff_arg) if handoff_arg is not None else {}
    root = Path.cwd()
    rid = run_id.mint()
    cache.ensure_layout(root)
    cache.write_handoff(root, rid, data)
    user_output(f"minted run_id {rid}; wrote handoff {cache.handoff_path(root, rid)}")
    machine_output(rid)
