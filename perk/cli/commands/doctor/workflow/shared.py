"""Cross-verb helpers for the `perk doctor workflow` subgroup."""

import json

import click

from perk.cli.commands.doctor.render import render_group
from perk.doctor import Check
from perk.output import machine_output, user_output

# The focused render order for the workflow subgroup (a subset of doctor's `GROUP_ORDER`).
WORKFLOW_GROUP_ORDER = ("github", "runner", "repository")
EXIT_FOR_TYPE = {"not_a_repo": 2}


def render_checks(checks: list[Check], *, verbose: bool) -> None:
    """Human render to stderr, grouped + condensed (reuses doctor's group/check renderers)."""
    by_group: dict[str, list[Check]] = {}
    for check in checks:
        by_group.setdefault(check.group, []).append(check)
    for group in WORKFLOW_GROUP_ORDER:
        if group in by_group:
            render_group(group, by_group[group], verbose=verbose)


def checks_to_dict(checks: list[Check], *, self_repo: bool) -> dict[str, object]:
    """The `--json` report shape (a `report_to_dict`-style object over the focused check set)."""
    passed = sum(1 for c in checks if c.status == "ok")
    warnings = sum(1 for c in checks if c.status in ("warn", "info"))
    failed = sum(1 for c in checks if c.status == "fail")
    return {
        "success": True,
        "healthy": failed == 0,
        "self_repo": self_repo,
        "checks": [
            {
                "name": c.name,
                "group": c.group,
                "status": c.status,
                "message": c.message,
                "detail": c.detail,
                "remediation": c.remediation,
            }
            for c in checks
        ],
        "summary": {"passed": passed, "warnings": warnings, "failed": failed},
    }


def fail(ctx: click.Context, *, as_json: bool, error_type: str, message: str) -> None:
    if as_json:
        machine_output(json.dumps({"success": False, "error_type": error_type, "message": message}))
    else:
        user_output(click.style("Error: ", fg="red") + message)
    ctx.exit(EXIT_FOR_TYPE.get(error_type, 1))
