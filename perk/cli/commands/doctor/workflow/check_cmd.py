"""`perk doctor workflow check` — static remote-runner prereq checks."""

import json

import click

from perk import doctor, init
from perk.cli.commands.doctor.workflow.shared import checks_to_dict, fail, render_checks
from perk.cli.context import require_repo
from perk.cli.ensure import UserFacingCliError
from perk.output import machine_output


@click.command("check")
@click.option("-v", "--verbose", is_flag=True, help="Show every check, not just failures.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def check_workflow(ctx: click.Context, verbose: bool, as_json: bool) -> None:
    """Static remote-runner prereq checks (GitHub readiness + runner prereqs + managed workflow)."""
    try:
        root = require_repo(ctx)
    except UserFacingCliError:
        fail(ctx, as_json=as_json, error_type="not_a_repo", message="Not a git repository.")
        return

    self_repo = init.is_self_repo(root)
    checks = doctor.workflow_checks(root, self_repo)
    if as_json:
        machine_output(json.dumps(checks_to_dict(checks, self_repo=self_repo)))
    else:
        render_checks(checks, verbose=verbose)
    ctx.exit(1 if any(c.status == "fail" for c in checks) else 0)
