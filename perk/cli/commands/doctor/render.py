"""Shared render helpers for `perk doctor` and its subgroups."""

import click

from perk.doctor import Check, DoctorReport
from perk.output import user_output

GROUP_ORDER = (
    "environment",
    "github",
    "runner",
    "package",
    "repository",
    "registry",
    "skills",
    "bindings",
    "providers",
    "issues",
    "state",
)
ICON: dict[str, tuple[str, str]] = {
    "ok": ("✓", "green"),
    "warn": ("⚠", "yellow"),
    "info": ("•", "cyan"),
    "fail": ("✗", "red"),
}


def render_check(check: Check) -> None:
    glyph, color = ICON[check.status]
    line = f"   {click.style(glyph, fg=color)} {check.name}: {check.message}"
    if check.detail:
        line += click.style(f" — {check.detail}", dim=True)
    user_output(line)


def render_group(group: str, checks: list[Check], *, verbose: bool) -> None:
    """erk's three-way condensed rule: collapse a clean group, else expand fails/warnings."""
    total = len(checks)
    fails = [c for c in checks if c.status == "fail"]
    warns = [c for c in checks if c.status in ("warn", "info")]
    if verbose:
        user_output(click.style(group, bold=True) + f" ({total} checks)")
        for check in checks:
            render_check(check)
    elif fails:
        user_output(click.style("✗", fg="red") + f" {group} ({total - len(fails)}/{total} checks)")
        for check in fails:
            render_check(check)
    elif warns:
        user_output(click.style("⚠", fg="yellow") + f" {group} ({total} checks)")
        for check in warns:
            render_check(check)
    else:
        user_output(click.style("✓", fg="green") + f" {group} ({total} checks)")


def render_report(report: DoctorReport, *, verbose: bool) -> None:
    if report.error_type is not None:
        user_output(click.style("✗ ", fg="red") + (report.message or "doctor failed"))
        return

    mode = "self" if report.self_repo else "consumer"
    user_output(click.style("perk doctor", bold=True) + f" ({mode})")
    by_group: dict[str, list[Check]] = {}
    for check in report.checks:
        by_group.setdefault(check.group, []).append(check)
    for group in GROUP_ORDER:
        if group in by_group:
            render_group(group, by_group[group], verbose=verbose)

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

    if report.fix_errors:
        user_output("")
        user_output(click.style("Fix failures", bold=True))
        for error in report.fix_errors:
            user_output(f"  {click.style('✗', fg='red')} {error}")

    passed = sum(1 for c in report.checks if c.status == "ok")
    failed = sum(1 for c in report.checks if c.status == "fail")
    user_output("")
    if report.healthy:
        user_output(click.style("✓ healthy", fg="green", bold=True) + f" ({passed} ok)")
    else:
        user_output(click.style(f"✗ {failed} check(s) failed", fg="red", bold=True))
