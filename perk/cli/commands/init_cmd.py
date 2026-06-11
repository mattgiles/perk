"""`perk init` — thin Click adapter over the convergent init operation (perk/init.py).

`init` is a **supervisor surface** (cli-vs-pi.md §3.2): `--json` to stdout + stable
exit codes (0 converged / 1 invalid input / 2 environment-not-ready), human text to stderr.
"""

import json
import sys

import click

from perk.cli.ensure import UserFacingCliError
from perk.init import InitReport, report_to_dict, run_init
from perk.output import machine_output, user_output


def _render_human(report: InitReport) -> None:
    """Human-facing step output to stderr."""
    if not report.ok:
        user_output(click.style("✗ ", fg="red") + (report.message or "init failed"))
        for check in report.env:
            if not check.ok:
                user_output(f"  - {check.name}: {check.detail} — {check.remediation}")
        return

    user_output(click.style("✓", fg="green") + f" perk init ({report.mode})")
    for check in report.env:
        mark = click.style("✓", fg="green") if check.ok else click.style("✗", fg="red")
        user_output(f"  {mark} {check.name} {check.detail}")

    if report.changes:
        user_output("Converged:")
        for change in report.changes:
            user_output(f"  - {change}")
    else:
        user_output("Already converged (no changes).")

    if report.github is not None:
        auth = report.github.auth
        if auth.ok:
            user_output(click.style("✓", fg="green") + f" GitHub: {auth.user or 'authenticated'}")
        else:
            user_output(
                click.style("⚠️", fg="yellow") + f" GitHub not verified: {auth.error}\n"
                "  Run: gh auth login  (perk did not mutate GitHub)"
            )

    if report.handoff is not None:
        user_output("")
        user_output(click.style("📋 Next: ", fg="cyan") + f"read and execute {report.handoff}")


@click.command("init")
@click.option("--force", is_flag=True, help="Re-seed the user-editable config to defaults.")
@click.option("--no-interactive", is_flag=True, help="Never prompt (CI/supervisor).")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def init_perk(ctx: click.Context, force: bool, no_interactive: bool, as_json: bool) -> None:
    """Scaffold/converge this repo for perk (idempotent; safe to re-run).

    Verifies the environment, wires `.pi/settings.json` + the borrowed package set, creates
    the `.pi/workflow/` cache, scaffolds config, manages `.gitignore` + the `AGENTS.md` block,
    verifies GitHub (never mutating), and writes the post-init handoff.

    \b
    Examples:
      perk init                 # converge the current repo
      perk init --json          # machine-readable report (supervisor surface)
      perk init --force         # also re-seed config to defaults
    """
    interactive = not no_interactive and sys.stdin.isatty()
    try:
        report = run_init(force=force, interactive=interactive)
    except UserFacingCliError as exc:
        if as_json:
            machine_output(
                json.dumps(
                    {
                        "success": False,
                        "error_type": exc.error_type or "invalid_input",
                        "message": exc.format_message(),
                    }
                )
            )
            ctx.exit(1)
        raise

    if as_json:
        machine_output(json.dumps(report_to_dict(report)))
    else:
        _render_human(report)
    ctx.exit(report.exit_code)
