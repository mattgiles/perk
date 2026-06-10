"""`perk doctor workflow smoke-test` — dispatch a throwaway CI run to prove the runner is live."""

import json

import click

from perk import doctor, github, init, workflow_artifacts, workflow_smoke
from perk.cli.commands.doctor.workflow.shared import fail, render_checks
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.output import machine_output, user_output


@click.command("smoke-test")
@click.option("--wait", is_flag=True, help="Poll the dispatched run to completion.")
@click.option("-v", "--verbose", is_flag=True, help="Show every prereq check, not just failures.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def smoke_test_workflow(ctx: click.Context, wait: bool, verbose: bool, as_json: bool) -> None:
    """Dispatch a throwaway CI run (smoke short-circuit) to prove the runner is live."""
    try:
        root = require_repo(ctx)
    except UserFacingCliError:
        fail(ctx, as_json=as_json, error_type="not_a_repo", message="Not a git repository.")
        return
    try:
        require_github(ctx)
    except UserFacingCliError as exc:
        fail(ctx, as_json=as_json, error_type="github_unauthed", message=exc.format_message())
        return

    self_repo = init.is_self_repo(root)
    checks = doctor.workflow_checks(root, self_repo)
    if not as_json:
        render_checks(checks, verbose=verbose)

    # Gate: refuse if GitHub is not authenticated, or the runner is deliberately disabled.
    github_auth = next((c for c in checks if c.name == "github-auth"), None)
    if github_auth is None or github_auth.status != "ok":
        fail(
            ctx,
            as_json=as_json,
            error_type="github_unauthed",
            message="cannot smoke-test — GitHub not authenticated",
        )
        return
    enabled = github.get_repo_variable(name=workflow_artifacts.RUNNER_ENABLED_VAR, repo_root=root)
    if enabled == "false":
        fail(
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
        fail(
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
