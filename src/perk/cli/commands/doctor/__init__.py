"""`perk doctor` — `init`'s diagnostic twin (thin Click adapter over perk/convergence/doctor.py).

The *second* canonical supervisor surface (cli-vs-pi.md §3.2): `--json` to stdout + stable exit
codes (0 healthy / 1 unhealthy / 2 not-a-repo), grouped human text to stderr.

Shipped as a Click **group** with ``invoke_without_command=True`` so bare ``perk doctor`` runs the
health checks and the ``perk doctor workflow`` subgroup slots in without a breaking
command-type change.
"""

import json

import click

from perk.cli.commands.doctor.render import render_report
from perk.cli.commands.doctor.workflow import workflow_group
from perk.cli.context import require_repo
from perk.cli.ensure import UserFacingCliError
from perk.convergence.doctor import DoctorReport, report_to_dict, run_doctor
from perk.substrate.output import machine_output


@click.group("doctor", invoke_without_command=True)
@click.option("--fix", is_flag=True, help="Apply known repairs (re-converge drift).")
@click.option("-v", "--verbose", is_flag=True, help="Show every check, not just failures.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def doctor_group(ctx: click.Context, *, fix: bool, verbose: bool, as_json: bool) -> None:
    """Diagnose (and with --fix, repair) this perk-managed repo.

    `doctor` reports a grouped health view; `--fix` re-converges drifted managed pieces (and
    seeds missing config) — it never mutates GitHub and never overwrites your config edits.

    Note: a plan adopted in place from a pre-existing issue (`perk plan from <issue>`) is
    identified by a populated `adopted_from` plan-header field; its issue body/title are verbatim
    human content. `doctor` never rewrites or validates that human prose — adoption provenance is
    awareness-only here, not a validating check.

    \b
    Examples:
      perk doctor               # condensed health report
      perk doctor --verbose     # every check
      perk doctor --fix         # repair known drift
      perk doctor --json        # machine-readable report (supervisor surface)
    """
    if ctx.invoked_subcommand is not None:
        return  # a registered subcommand (e.g. `perk doctor workflow`) handles it

    try:
        root = require_repo(ctx)
    except UserFacingCliError:
        report = DoctorReport.not_repo()
        if as_json:
            machine_output(json.dumps(report_to_dict(report)))
        else:
            render_report(report, verbose=verbose)
        ctx.exit(report.exit_code)

    report = run_doctor(root, fix=fix)
    if as_json:
        machine_output(json.dumps(report_to_dict(report)))
    else:
        render_report(report, verbose=verbose)
    ctx.exit(report.exit_code)


doctor_group.add_command(workflow_group)
