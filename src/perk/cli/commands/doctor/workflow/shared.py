"""Cross-verb helpers for the `perk doctor workflow` subgroup."""

from perk.cli.commands.doctor.render import render_group
from perk.convergence.doctor import Check

# The focused render order for the workflow subgroup (a subset of doctor's `GROUP_ORDER`).
WORKFLOW_GROUP_ORDER = ("github", "runner", "repository")


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
