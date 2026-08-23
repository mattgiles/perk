"""`perk implement [PLAN]` — the cold door for the implement stage.

Replaces the generic registry launcher for `implement` with a dedicated command that:

- **accepts an optional PLAN issue number** — `perk implement 42` selects plan #42 (one
  canonical backend read via `perk.cli.plan_selection.select_plan`), updates the **main-root**
  selector on a real launch (a convenience for a later no-argument run — never a linked
  worktree's binding), and passes the resolved ref directly into the launch pipeline (the
  launch never re-reads that mutable cache write). Omit PLAN to implement the active saved
  plan; and
- **inherits the priming prompt** `launch.launch_stage` injects so the launched `pi`
  starts working on the plan instead of opening idle.

Grammar (`PlanLauncherCommand`): before the first bare `--`, only perk options plus the one
optional PLAN are accepted; everything after `--` is delivered to pi verbatim.
Supervisor surface (cli-vs-pi §3.2): `--dry-run` prints the launch plan; failures exit 1 (Click
renders `UserFacingCliError`), not-a-repo via `require_repo`.
"""

import click

from perk.backends.issue_backend import IssueBackendError
from perk.cli import completions
from perk.cli.alias import alias
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.cli.launcher_grammar import PI_PASSTHROUGH_EPILOG, PlanLauncherCommand
from perk.cli.plan_selection import load_main_config, main_repo_root, select_plan
from perk.run import launch
from perk.state import cache
from perk.substrate.registry import stage_by_id


@alias("impl")
@click.command("implement", cls=PlanLauncherCommand, epilog=PI_PASSTHROUGH_EPILOG)
@click.argument("plan", required=False, shell_complete=completions.complete_plan_id)
@click.option(
    "--worktree",
    help=(
        "Directory name for the checkout — never plan identity or the plan-<id> branch. "
        "Without PLAN, an EXISTING named checkout selects through its own binding (ahead of "
        "the invoking checkout's saved plan); a missing named directory requires PLAN."
    ),
)
@click.option("--dry-run", is_flag=True, help="Print the launch plan without exec'ing pi.")
@click.option(
    "--remote",
    type=str,
    default=None,
    is_flag=False,
    flag_value="",
    help="Local (default) or a remote runner (dispatch the stage to CI).",
)
@click.option(
    "--base",
    help="Branch off this ref instead of origin/<trunk> (e.g. for stacking on an unlanded branch).",
)
@click.pass_context
def implement(
    ctx: click.Context,
    *,
    plan: str | None,
    worktree: str | None,
    dry_run: bool,
    remote: str | None,
    base: str | None,
    pi_args: tuple[str, ...] = (),
) -> None:
    """Do the work on a branch (requires fresh context; cold-only).

    \b
    PLAN is an optional plan issue id (e.g. 42, #42, ENG-123, or the pasted issue URL) — or
    the plan's PR: its number or pasted .../pull/N URL, resolved to the plan it records. Omit
    it to implement the active saved plan: the no-argument form selects, in order, an explicit
    EXISTING --worktree's own binding, else the invoking checkout's cache.plan-ref (inside a
    plan worktree that is the worktree's binding); a missing --worktree directory without PLAN
    is refused (it cannot invent a binding). An explicit PLAN is
    canonical issue authority — it updates only the main-checkout selector and drives the
    launch directly. Typed failures (plan_not_found, issue_kind_mismatch,
    worktree_plan_mismatch, worktree_branch_mismatch, worktree_unbound, worktree_not_found,
    invalid_input) exit 1 before any launch.

    \b
    Examples:
      perk implement                  # implement the active saved plan
      perk implement 42               # select plan #42 and implement it
      perk implement 42 --dry-run     # resolve + print the launch, launch nothing
      perk implement 42 -- --model provider/model   # pi args go after the bare --
    """
    invocation_root = require_repo(ctx)
    main_root = main_repo_root(invocation_root)
    config = load_main_config(main_root)
    stage = stage_by_id("implement")

    if plan is None:
        # No plan id: launch the active saved plan. resolve_worktree reads the invoking
        # checkout's selector (or --worktree's own binding) and raises a clear "needs a saved
        # plan" error when there is none.
        launch.launch_stage(
            repo_root=main_root,
            config=config,
            stage=stage,
            worktree=worktree,
            dry_run=dry_run,
            remote=remote,
            pi_args=list(pi_args),
            base=base,
            invocation_root=invocation_root,
        )
        return

    # A plan id was given: one canonical backend read (selection happens BEFORE the
    # local-vs-remote split, so --remote dispatches exactly the selected plan).
    require_github(ctx)
    # Banner first: head a real local launch with the banner BEFORE narrating the lookup wait
    # (launch_stage's own call becomes the no-op fallback).
    launch.print_launch_banner_gated(main_root, dry_run=dry_run, remote=remote)
    try:
        selected = select_plan(main_root, plan)
    except IssueBackendError as exc:
        raise UserFacingCliError(f"implement failed\n{exc}", error_type="github_error") from exc

    if not dry_run:
        # Update the MAIN-root selector (future no-argument convenience only) — never a linked
        # worktree's binding, and never what the launch below consumes.
        cache.write_plan_ref(main_root, selected.ref)
    launch.launch_stage(
        repo_root=main_root,
        config=config,
        stage=stage,
        worktree=worktree,
        dry_run=dry_run,
        remote=remote,
        pi_args=list(pi_args),
        base=base,
        plan_ref=selected.ref,
        plan_state=selected.state,
        invocation_root=invocation_root,
    )
