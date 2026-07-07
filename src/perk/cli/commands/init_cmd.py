"""`perk init` — thin Click adapter over the convergent init operation (perk/convergence/init.py).

`init` is a **supervisor surface** (cli-vs-pi.md §3.2): `--json` to stdout + stable
exit codes (0 converged / 1 invalid input / 2 environment-not-ready), human text to stderr.
"""

import json
import sys

import click

from perk.cli.emit import emit
from perk.cli.ensure import UserFacingCliError
from perk.convergence.init import InitReport, report_to_dict, run_init
from perk.substrate.output import machine_output, user_output


def _render_human(report: InitReport) -> None:
    """Human-facing step output to stderr."""
    if not report.ok:
        user_output(click.style("✗ ", fg="red") + (report.message or "init failed"))
        for check in report.env:
            if not check.ok:
                user_output(f"  - {check.name}: {check.detail} — {check.remediation}")
        if report.changes:
            # e.g. skills_sync_failed: convergence already happened and stays recorded.
            user_output("Converged before failure:")
            for change in report.changes:
                user_output(f"  - {change}")
        for warning in report.warnings:
            user_output(click.style("⚠️ ", fg="yellow") + warning)
        return

    user_output(click.style("✓", fg="green") + f" perk init ({report.mode})")
    for check in report.env:
        if check.ok:
            mark = click.style("✓", fg="green")
        elif check.optional:
            mark = click.style("⚠️", fg="yellow")
        else:
            mark = click.style("✗", fg="red")
        user_output(f"  {mark} {check.name} {check.detail}")

    if report.changes:
        user_output("Converged:")
        for change in report.changes:
            user_output(f"  - {change}")
    else:
        user_output("Already converged (no changes).")

    for warning in report.warnings:
        user_output(click.style("⚠️ ", fg="yellow") + warning)

    if report.github is not None:
        auth = report.github.auth
        if auth.ok:
            user_output(click.style("✓", fg="green") + f" GitHub: {auth.user or 'authenticated'}")
        else:
            user_output(
                click.style("⚠️", fg="yellow") + f" GitHub not verified: {auth.error}\n"
                "  Run: gh auth login  (perk did not mutate GitHub)"
            )

    if report.linear is not None:
        readiness = report.linear.readiness
        if report.linear.ok and readiness is not None:
            line = f" Linear: {readiness.user or 'authenticated'}, team {report.linear.team}"
            if readiness.created_labels:
                line += f", created labels: {', '.join(readiness.created_labels)}"
            user_output(click.style("✓", fg="green") + line)
        else:
            error = report.linear.error or (readiness.error if readiness is not None else None)
            user_output(
                click.style("⚠️", fg="yellow") + f" Linear not verified: {error}\n"
                "  Export LINEAR_API_KEY and set [issues] team in .perk/config.toml"
                "  (perk did not mutate Linear)"
            )
        project = report.linear.project
        if project is not None:
            if not project.projects_ok:
                user_output(
                    click.style("⚠️", fg="yellow") + " Linear Projects: read-access not verified"
                )
            if project.states_error:
                user_output(click.style("⚠️", fg="yellow") + " Linear: workflow states not verified")
            elif project.missing_state_types:
                user_output(
                    click.style("⚠️", fg="yellow")
                    + " Linear: team missing workflow state type(s): "
                    + ", ".join(project.missing_state_types)
                )

    if report.handoff is not None:
        user_output("")
        user_output(click.style("📋 Next: ", fg="cyan") + f"read and execute {report.handoff}")


@click.command("init")
@click.option("--force", is_flag=True, help="Re-seed the user-editable config to defaults.")
@click.option("--no-interactive", is_flag=True, help="Never prompt (CI/supervisor).")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def init_perk(ctx: click.Context, *, force: bool, no_interactive: bool, as_json: bool) -> None:
    """Scaffold/converge this repo for perk (idempotent; safe to re-run).

    Verifies the environment, wires `.pi/settings.json` + the borrowed package set, creates
    the `.perk/workflow/` cache, scaffolds config, manages `.gitignore` + the `AGENTS.md` block,
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

    emit(as_json=as_json, payload=report_to_dict(report), render=lambda: _render_human(report))
    ctx.exit(report.exit_code)
