"""`perk registry` — inspect and validate the shared stage registry.

A developer / `doctor` / CI surface, **not** an agent affordance (cli-vs-pi §3.2/§6.6):
the agent reads registry data via an extension tool, never by shelling `perk`. `--json` here
is for machines that *launch* perk (CI, the future supervisor), per python-cli-guidelines §7.
"""

import json

import click

from perk.cli.alias import AliasGroup, alias, register_with_aliases
from perk.cli.ensure import UserFacingCliError
from perk.output import machine_output, user_output
from perk.registry import Registry, RegistryError, Severity, load_registry, validate


def _load_or_die() -> Registry:
    try:
        return load_registry()
    except RegistryError as exc:
        raise UserFacingCliError(str(exc)) from exc


@alias("reg")
@click.group("registry", cls=AliasGroup)
def registry() -> None:
    """Inspect and validate the shared stage registry (`shared/registry.yaml`)."""


@alias("ch")
@click.command("check")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable result on stdout.")
def check(as_json: bool) -> None:
    """Validate the bundled registry (shape, graph, state-key vocabulary).

    Exits 0 when valid, 1 when any error issue is found.

    \b
    Examples:
      perk registry check
      perk registry check --json
    """
    reg = _load_or_die()
    issues = validate(reg)
    errors = [i for i in issues if i.severity is Severity.ERROR]

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


@alias("s")
@click.command("show")
def show() -> None:
    """Print the stages and their transitions (a dev/doctor convenience)."""
    reg = _load_or_die()
    user_output(f"schema_version: {reg.schema_version}   ({len(reg.stages)} stages)")
    user_output("")
    for stage in reg.stages:
        doors = ",".join(d for d in ("warm", "cold_local", "cold_remote") if stage.doors.get(d))
        succ = ", ".join(stage.successors) or "—"
        user_output(
            f"  {stage.id:<10} mode={stage.mode:<10} worktree={stage.worktree:<7} "
            f"doors=[{doors}]  -> {succ}"
        )


register_with_aliases(registry, check)
register_with_aliases(registry, show)
