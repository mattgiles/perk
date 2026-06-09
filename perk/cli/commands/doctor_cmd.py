"""`perk doctor` — `init`'s diagnostic twin (thin Click adapter over perk/doctor.py).

The *second* canonical supervisor surface (cli-vs-pi.md §3.2): `--json` to stdout + stable exit
codes (0 healthy / 1 unhealthy / 2 not-a-repo), grouped human text to stderr.

Shipped as a Click **group** with ``invoke_without_command=True`` so bare ``perk doctor`` runs the
health checks today and the Phase-3 ``perk doctor workflow`` subgroup slots in without a breaking
command-type change (erk's `cli/doctor-workflow.md` tripwire).
"""

import json

import click

from perk.cli.context import require_repo
from perk.cli.ensure import UserFacingCliError
from perk.doctor import Check, DoctorReport, report_to_dict, run_doctor
from perk.output import machine_output, user_output

_GROUP_ORDER = ("environment", "github", "runner", "package", "repository", "registry", "state")
_ICON: dict[str, tuple[str, str]] = {
    "ok": ("✓", "green"),
    "warn": ("⚠", "yellow"),
    "info": ("•", "cyan"),
    "fail": ("✗", "red"),
}


def _render_check(check: Check) -> None:
    glyph, color = _ICON[check.status]
    line = f"   {click.style(glyph, fg=color)} {check.name}: {check.message}"
    if check.detail:
        line += click.style(f" — {check.detail}", dim=True)
    user_output(line)


def _render_group(group: str, checks: list[Check], *, verbose: bool) -> None:
    """erk's three-way condensed rule: collapse a clean group, else expand fails/warnings."""
    total = len(checks)
    fails = [c for c in checks if c.status == "fail"]
    warns = [c for c in checks if c.status in ("warn", "info")]
    if verbose:
        user_output(click.style(group, bold=True) + f" ({total} checks)")
        for check in checks:
            _render_check(check)
    elif fails:
        user_output(click.style("✗", fg="red") + f" {group} ({total - len(fails)}/{total} checks)")
        for check in fails:
            _render_check(check)
    elif warns:
        user_output(click.style("⚠", fg="yellow") + f" {group} ({total} checks)")
        for check in warns:
            _render_check(check)
    else:
        user_output(click.style("✓", fg="green") + f" {group} ({total} checks)")


def _render(report: DoctorReport, *, verbose: bool) -> None:
    if report.error_type is not None:
        user_output(click.style("✗ ", fg="red") + (report.message or "doctor failed"))
        return

    mode = "self" if report.self_repo else "consumer"
    user_output(click.style("perk doctor", bold=True) + f" ({mode})")
    by_group: dict[str, list[Check]] = {}
    for check in report.checks:
        by_group.setdefault(check.group, []).append(check)
    for group in _GROUP_ORDER:
        if group in by_group:
            _render_group(group, by_group[group], verbose=verbose)

    remediations = sorted(
        {c.remediation for c in report.checks if c.remediation and c.status in ("fail", "warn")}
    )
    if remediations:
        user_output("")
        user_output(click.style("Remediation", bold=True))
        for remediation in remediations:
            user_output(f"  {remediation}")

    if report.fixed:
        user_output("")
        user_output(click.style("Fixed", bold=True))
        for change in report.fixed:
            user_output(f"  - {change}")

    passed = sum(1 for c in report.checks if c.status == "ok")
    failed = sum(1 for c in report.checks if c.status == "fail")
    user_output("")
    if report.healthy:
        user_output(click.style("✓ healthy", fg="green", bold=True) + f" ({passed} ok)")
    else:
        user_output(click.style(f"✗ {failed} check(s) failed", fg="red", bold=True))


@click.group("doctor", invoke_without_command=True)
@click.option("--fix", is_flag=True, help="Apply known repairs (re-converge drift).")
@click.option("-v", "--verbose", is_flag=True, help="Show every check, not just failures.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def doctor(ctx: click.Context, fix: bool, verbose: bool, as_json: bool) -> None:
    """Diagnose (and with --fix, repair) this perk-managed repo.

    `doctor` reports a grouped health view; `--fix` re-converges drifted managed pieces (and
    seeds missing config) — it never mutates GitHub and never overwrites your config edits.

    \b
    Examples:
      perk doctor               # condensed health report
      perk doctor --verbose     # every check
      perk doctor --fix         # repair known drift
      perk doctor --json        # machine-readable report (supervisor surface)
    """
    if ctx.invoked_subcommand is not None:
        return  # a future subgroup (e.g. `perk doctor workflow`, Phase 3) handles it

    try:
        root = require_repo(ctx)
    except UserFacingCliError:
        report = DoctorReport.not_repo()
        if as_json:
            machine_output(json.dumps(report_to_dict(report)))
        else:
            _render(report, verbose=verbose)
        ctx.exit(report.exit_code)

    report = run_doctor(root, fix=fix)
    if as_json:
        machine_output(json.dumps(report_to_dict(report)))
    else:
        _render(report, verbose=verbose)
    ctx.exit(report.exit_code)


# Register the Phase-3 workflow subgroup onto the `doctor` group (the reserved
# `invoked_subcommand` hook). Imported at the bottom of the file so the `doctor` group object
# already exists; `doctor_workflow_cmd` imports this module's render helpers (no cycle).
from perk.cli.commands.doctor_workflow_cmd import (  # noqa: E402
    workflow_group as _doctor_workflow_group,
)

doctor.add_command(_doctor_workflow_group)
