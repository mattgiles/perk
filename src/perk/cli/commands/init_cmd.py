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

# Change-line prefixes that are host/local-only — never repo wiring, so they must not trigger
# the "commit the wiring" next-step (a run whose only deltas are a host install or the stored
# Linear key has nothing to commit).
_HOST_LOCAL_CHANGE_PREFIXES = (
    "tool ",
    "hunk CLI:",
    "git identity:",
    ".perk/local.toml:",
    ".perk/workflow/",
)


def _repo_wiring_changes(changes: list[str]) -> list[str]:
    """The change lines that touched committed repo wiring (the commit-hint classification)."""
    return [c for c in changes if not c.startswith(_HOST_LOCAL_CHANGE_PREFIXES)]


def _render_human(report: InitReport) -> None:
    """Human-facing step output to stderr."""
    if not report.ok:
        user_output(click.style("✗ ", fg="red") + (report.message or "init failed"))
        failing = [c for c in report.env if not c.ok and not c.optional]
        if failing:
            user_output("To finish setup:")
            for i, check in enumerate(failing, start=1):
                user_output(f"  {i}. {check.name}: {check.remediation}")
        if report.changes:
            # e.g. a guided host install / skills_sync_failed: what completed stays recorded
            # (host installs are not convergence, hence "Completed", not "Converged").
            user_output("Completed before failure:")
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
            # The `gh auth login` remediation lives in the Next steps block (single source).
            user_output(click.style("⚠️", fg="yellow") + f" GitHub not verified: {auth.error}")

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
        user_output(
            click.style("📋 ", fg="cyan")
            + f"Agent on-ramp (optional): {report.handoff} — point an agent at this file to "
            "continue setup."
        )

    steps: list[str] = []
    if report.github is not None and not report.github.auth.ok:
        steps.append("- Authenticate GitHub: gh auth login")
    if report.linear is not None and not report.linear.ok:
        readiness = report.linear.readiness
        error = report.linear.error or (readiness.error if readiness is not None else None)
        steps.append(f"- Linear: {error}")
    if _repo_wiring_changes(report.changes):
        steps.append("- Review and commit the wiring perk added (see: git status)")
    steps.append("- Start with: perk plan")
    user_output("")
    user_output("Next steps:")
    for step in steps:
        user_output(f"  {step}")


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
    # `--json` is a machine surface: an inherited-stdio `gh auth login` (or any prompt) must
    # never interleave with the one stdout JSON object, so it disables interactivity outright.
    interactive = not no_interactive and not as_json and sys.stdin.isatty()
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
