"""`perk implement [PLAN]` — the cold door for the implement stage (P1.T4c).

Replaces the generic registry launcher for `implement` with a dedicated command that:

- **accepts an optional PLAN issue number** — `perk implement 42` selects plan #42 as the active
  `cache.plan-ref` and launches it, restoring [phase-1-plan.md] §P1.T4's `perk implement <plan>`
  (T4a's D2 read only the *active* ref; the dogfood run surfaced that `implement <plan>` is the
  natural verb). Omit PLAN to implement the active saved plan (the T4a behavior); and
- **inherits the priming prompt** `launch.launch_stage` now injects (Bug 1) so the launched `pi`
  starts working on the plan instead of opening idle.

Reuses `perk resume`'s plan resolution (`github.get_plan` + `resume.reconstruct_plan_ref`).
Supervisor surface (cli-vs-pi §3.2): `--dry-run` prints the launch plan; failures exit 1 (Click
renders `UserFacingCliError`), not-a-repo via `require_repo`.
"""

import json
from pathlib import Path

import click

from perk import cache, github, launch, resume
from perk.cli.alias import alias
from perk.cli.commands.resume_cmd import parse_plan_id
from perk.cli.context import require_config, require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.output import machine_output, user_output
from perk.registry import Stage, load_registry


def _implement_stage() -> Stage:
    return next(s for s in load_registry().stages if s.id == "implement")


@alias("impl")
@click.command("implement", context_settings={"ignore_unknown_options": True})
@click.argument("plan", required=False)
@click.option("--worktree", help="Worktree to position (overrides the plan name).")
@click.option(
    "--dry-run", "dry_run", is_flag=True, help="Print the launch plan without exec'ing pi."
)
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
@click.argument("pi_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def implement(
    ctx: click.Context,
    *,
    plan: str | None,
    worktree: str | None,
    dry_run: bool,
    remote: str | None,
    base: str | None,
    pi_args: tuple[str, ...],
) -> None:
    """Do the work on a branch (requires fresh context; cold-only).

    \b
    PLAN is an optional plan issue number (e.g. 42 or #42). Omit it to implement the active
    saved plan in this repo.

    \b
    Examples:
      perk implement              # implement the active saved plan
      perk implement 42           # select plan #42 and implement it
      perk implement 42 --dry-run # resolve + print the launch, launch nothing
    """
    repo_root = require_repo(ctx)
    config = require_config(ctx)
    stage = _implement_stage()

    if plan is None:
        # No plan id: launch the active saved plan (T4a). launch_stage reads the active ref
        # (or --worktree) and raises a clear "needs a saved plan" error when there is none.
        launch.launch_stage(
            repo_root=repo_root,
            config=config,
            stage=stage,
            worktree=worktree,
            dry_run=dry_run,
            remote=remote,
            pi_args=list(pi_args),
            base=base,
        )
        return

    # A plan id was given: resolve it from GitHub and make it the active plan-ref.
    require_github(ctx)
    number = parse_plan_id(plan)
    try:
        state = github.get_plan(number=number, repo_root=repo_root)
    except GitHubError as exc:
        raise UserFacingCliError(f"implement failed\n{exc}", error_type="github_error") from exc
    if state is None:
        raise UserFacingCliError(f"Plan issue #{number} not found", error_type="plan_not_found")
    ref = resume.reconstruct_plan_ref(state)
    worktree_name = launch.resolve_plan_worktree_name(ref)

    if dry_run:
        _render_dry_run(repo_root, number, worktree_name, ref, base)
        return

    # Select #N as the active plan (mirrors `perk resume`), then launch (worktree derived + the
    # ref materialized into it by launch_stage; the session is primed by Bug 1).
    cache.write_plan_ref(repo_root, ref)
    launch.launch_stage(
        repo_root=repo_root,
        config=config,
        stage=stage,
        worktree=None,
        dry_run=False,
        remote=remote,
        pi_args=list(pi_args),
        base=base,
    )


def _render_dry_run(
    repo_root: Path, number: int, worktree: str, ref: dict[str, object], base: str | None
) -> None:
    # No worktree exists yet on a fresh plan, so resolve the base the same way the active-ref
    # dry-run create does (local refs only, no fetch) to keep the two dry-run JSONs consistent.
    resolved_base = launch.resolve_base(repo_root, worktree, base)
    machine_output(
        json.dumps(
            {
                "success": True,
                "stage": "implement",
                "plan": number,
                "worktree": worktree,
                "plan_ref": ref,
                "base": resolved_base,
                "dry_run": True,
            }
        )
    )
    user_output(click.style("implement --dry-run (resolve only, no launch)", dim=True))
    user_output(f"  plan=#{number}  worktree={worktree}")
