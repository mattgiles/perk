"""`perk doctor workflow` — the workflow-focused diagnostic subgroup (Node 3.3; contracts.md §8.19).

`init`'s diagnostic twin, narrowed to the remote-runner subsystem. `check` composes the **static**
prereq layer (`doctor.workflow_checks` — GitHub readiness ⊕ runner prereqs ⊕ the managed
`runner-workflow` present-check); `smoke-test [--wait]` adds the **live** proof a static check
cannot give — it dispatches a throwaway CI run with a `smoke=true` short-circuit (validate secrets +
confirm the runner started, then exit success; no plan checkout, no worker drive, no model spend),
optionally polls it to completion, and self-cancels its own run on a poll timeout. The smoke writes
**no** `DispatchRecord` and creates **no** GitHub artifacts, so it stays a pure doctor diagnostic
(`perk workflow run list` is unaffected) — there is no `cleanup` command (perk's smoke leaves
nothing durable, unlike erk's one-shot PR).
"""

import json

import click

from perk import doctor, github, init, workflow_artifacts, workflow_smoke
from perk.cli.commands import doctor_cmd
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.doctor import Check
from perk.output import machine_output, user_output

# The focused render order for the workflow subgroup (a subset of doctor's `_GROUP_ORDER`).
_WORKFLOW_GROUP_ORDER = ("github", "runner", "repository")
_EXIT_FOR_TYPE = {"not_a_repo": 2}


def _render_checks(checks: list[Check], *, verbose: bool) -> None:
    """Human render to stderr, grouped + condensed (reuses doctor_cmd's group/check renderers)."""
    by_group: dict[str, list[Check]] = {}
    for check in checks:
        by_group.setdefault(check.group, []).append(check)
    for group in _WORKFLOW_GROUP_ORDER:
        if group in by_group:
            doctor_cmd._render_group(group, by_group[group], verbose=verbose)


def _checks_to_dict(checks: list[Check], *, self_repo: bool) -> dict[str, object]:
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


def _fail(ctx: click.Context, *, as_json: bool, error_type: str, message: str) -> None:
    if as_json:
        machine_output(json.dumps({"success": False, "error_type": error_type, "message": message}))
    else:
        user_output(click.style("Error: ", fg="red") + message)
    ctx.exit(_EXIT_FOR_TYPE.get(error_type, 1))


@click.group("workflow", invoke_without_command=True)
@click.pass_context
def workflow_group(ctx: click.Context) -> None:
    """Diagnose the remote-runner subsystem (static prereqs + an optional live CI smoke)."""
    if ctx.invoked_subcommand is None:
        user_output(ctx.get_help())


@workflow_group.command("check")
@click.option("-v", "--verbose", is_flag=True, help="Show every check, not just failures.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def check_cmd(ctx: click.Context, verbose: bool, as_json: bool) -> None:
    """Static remote-runner prereq checks (GitHub readiness + runner prereqs + managed workflow)."""
    try:
        root = require_repo(ctx)
    except UserFacingCliError:
        _fail(ctx, as_json=as_json, error_type="not_a_repo", message="Not a git repository.")
        return

    self_repo = init.is_self_repo(root)
    checks = doctor.workflow_checks(root, self_repo)
    if as_json:
        machine_output(json.dumps(_checks_to_dict(checks, self_repo=self_repo)))
    else:
        _render_checks(checks, verbose=verbose)
    ctx.exit(1 if any(c.status == "fail" for c in checks) else 0)


@workflow_group.command("smoke-test")
@click.option("--wait", is_flag=True, help="Poll the dispatched run to completion.")
@click.option("-v", "--verbose", is_flag=True, help="Show every prereq check, not just failures.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def smoke_test_cmd(ctx: click.Context, wait: bool, verbose: bool, as_json: bool) -> None:
    """Dispatch a throwaway CI run (smoke short-circuit) to prove the runner is live."""
    try:
        root = require_repo(ctx)
    except UserFacingCliError:
        _fail(ctx, as_json=as_json, error_type="not_a_repo", message="Not a git repository.")
        return
    try:
        require_github(ctx)
    except UserFacingCliError as exc:
        _fail(ctx, as_json=as_json, error_type="github_unauthed", message=exc.format_message())
        return

    self_repo = init.is_self_repo(root)
    checks = doctor.workflow_checks(root, self_repo)
    if not as_json:
        _render_checks(checks, verbose=verbose)

    # Gate: refuse if GitHub is not authenticated, or the runner is deliberately disabled.
    github_auth = next((c for c in checks if c.name == "github-auth"), None)
    if github_auth is None or github_auth.status != "ok":
        _fail(
            ctx,
            as_json=as_json,
            error_type="github_unauthed",
            message="cannot smoke-test — GitHub not authenticated",
        )
        return
    enabled = github.get_repo_variable(name=workflow_artifacts.RUNNER_ENABLED_VAR, repo_root=root)
    if enabled == "false":
        _fail(
            ctx,
            as_json=as_json,
            error_type="runner_disabled",
            message=(
                f"{workflow_artifacts.RUNNER_ENABLED_VAR}=false — the runner job is disabled; "
                "enable it before smoke-testing"
            ),
        )
        return

    result = workflow_smoke.dispatch_smoke(root)
    if isinstance(result, workflow_smoke.SmokeError):
        _fail(
            ctx,
            as_json=as_json,
            error_type="smoke_dispatch_failed",
            message=f"{result.step}: {result.message}",
        )
        return

    user_output(f"dispatched smoke run {result.run_id} → {result.url}")

    if not wait:
        if as_json:
            machine_output(
                json.dumps(
                    {
                        "success": True,
                        "action": "smoke-test",
                        "run_id": result.run_id,
                        "run_ref": result.run_ref,
                        "url": result.url,
                        "waited": False,
                        "conclusion": None,
                        "timed_out": False,
                    }
                )
            )
        ctx.exit(0)

    poll = workflow_smoke.poll_smoke(root, result.run_ref, result.url)
    if poll.timed_out:
        workflow_smoke.cancel_smoke(root, result.run_ref)
        user_output(f"⚠ smoke run did not complete in time (cancelled) → {poll.url}")
        exit_code = 0  # inconclusive, not unhealthy
    elif poll.conclusion == "success":
        user_output(f"✓ smoke run succeeded → {poll.url}")
        exit_code = 0
    else:
        user_output(f"✗ smoke run concluded {poll.conclusion!r} → {poll.url}")
        exit_code = 1

    if as_json:
        machine_output(
            json.dumps(
                {
                    "success": True,
                    "action": "smoke-test",
                    "run_id": result.run_id,
                    "run_ref": result.run_ref,
                    "url": poll.url,
                    "waited": True,
                    "conclusion": poll.conclusion,
                    "timed_out": poll.timed_out,
                }
            )
        )
    ctx.exit(exit_code)
