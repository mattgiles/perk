"""`perk registry check` — validate the bundled registry."""

import json

import click

from perk.cli.alias import alias
from perk.cli.commands.registry.shared import load_or_die
from perk.cli.ensure import UserFacingCliError
from perk.substrate.output import machine_output, user_output
from perk.substrate.registry import FindingSeverity, validate


@alias("ch")
@click.command("check")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable result on stdout.")
def check_registry(*, as_json: bool) -> None:
    """Validate the bundled registry (shape, graph, state-key vocabulary).

    Exits 0 when valid, 1 when any error issue is found.

    \b
    Examples:
      perk registry check
      perk registry check --json
    """
    reg = load_or_die()
    issues = validate(reg)
    errors = [i for i in issues if i.severity is FindingSeverity.ERROR]

    if as_json:
        machine_output(
            json.dumps(
                {
                    "success": not errors,
                    "stages": len(reg.stages),
                    "state_keys": len(reg.state_keys),
                    "issues": [
                        {"severity": i.severity.value, "where": i.where, "message": i.message}
                        for i in issues
                    ],
                }
            )
        )

    if errors:
        if not as_json:
            for issue in issues:
                user_output(f"  {issue}")
        raise UserFacingCliError(
            f"registry invalid: {len(errors)} error(s) in {len(reg.stages)} stage(s)"
        )

    if not as_json:
        user_output(
            f"registry OK: {len(reg.stages)} stages, graph consistent, "
            f"{len(reg.state_keys)} state keys"
        )
