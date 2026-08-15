"""``perk pr address [PLAN]`` — the launcher-only address door.

``address`` has **both** a launcher half (opens a primed pi session that runs the classify→fix→
resolve loop) and the warm ``/address`` review flow, but **no deterministic worker** — so it is
**launcher-only (L)**, not a :class:`~perk.cli.stages.MergedCommand`. This dedicated launcher
carries the optional positional ``PLAN`` selector (one canonical backend read via
``perk.cli.plan_selection.select_plan``; a real launch updates only the **main-root** selector
and passes the resolved ref directly into the launch pipeline), the ``--worktree`` /
``--dry-run`` / ``--remote`` options, and the cold ``--preview`` flag (previously warm-only).

Grammar (`PlanLauncherCommand`): before the first bare ``--``, only perk options plus the one
optional ``PLAN`` are accepted (``perk address 1699`` is a selector, never a first user
message); everything after ``--`` is delivered to pi verbatim.

``--preview`` is a **local-launch concept**: it shapes the cold seed prompt only (the warm
``/address --preview`` gesture). On ``--remote`` (address is ``cold_remote: true``) the dispatch
path builds no seed prompt, so ``--preview`` is inert there (mirrors how the seed prompt is
local-only). ``--worktree`` combined with ``--remote`` is rejected (``invalid_input``): a
local-positioning gesture has no remote meaning — use the positional ``PLAN``.
"""

import click

from perk.backends.issue_backend import IssueBackendError
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.cli.launcher_grammar import PI_PASSTHROUGH_EPILOG, PlanLauncherCommand
from perk.cli.plan_selection import load_main_config, main_repo_root, select_plan
from perk.run import launch
from perk.run.launch import launch_stage
from perk.state import cache
from perk.substrate.registry import stage_by_id

# Click takes the first paragraph as short help, so the root-listing row renders the bare registry
# summary; the second paragraph disambiguates the launcher (per the cli-command-groups playbook).
_ADDRESS_HELP = (
    "Classify PR review feedback (isolated child) and resolve the threads.\n\n"
    "Opens a primed pi session for the 'address' stage (use --dry-run to print the launch plan "
    "without exec'ing pi). PLAN is an optional plan issue id (e.g. 42, #42, ENG-123, or the "
    "pasted issue URL): omit it to address the active saved plan — selected, in order, from an "
    "explicit EXISTING --worktree's own binding, else the invoking checkout's cache.plan-ref "
    "(inside a plan worktree, that worktree's own binding); a missing --worktree directory "
    "without PLAN is refused. Pass PLAN to select the plan canonically — the launch consumes "
    "the resolved ref directly, and a real launch updates only the main-checkout selector. "
    "Typed failures (plan_not_found, issue_kind_mismatch, worktree_plan_mismatch, "
    "worktree_branch_mismatch, worktree_unbound, worktree_not_found, invalid_input) exit 1 "
    "before any launch. Pass "
    "--preview to classify the feedback only and take no action (the warm /address --preview "
    "gesture); --preview is local-only (inert on --remote)."
)


@click.command(
    "address",
    cls=PlanLauncherCommand,
    help=_ADDRESS_HELP,
    epilog=PI_PASSTHROUGH_EPILOG,
)
@click.argument("plan", required=False)
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
    "--preview",
    is_flag=True,
    help="Classify the PR feedback only — take no action (the warm /address --preview gesture).",
)
@click.pass_context
def address_launcher(
    ctx: click.Context,
    *,
    plan: str | None,
    worktree: str | None,
    dry_run: bool,
    remote: str | None,
    preview: bool,
    pi_args: tuple[str, ...] = (),
) -> None:
    invocation_root = require_repo(ctx)
    main_root = main_repo_root(invocation_root)
    config = load_main_config(main_root)
    stage = stage_by_id("address")

    if plan is None:
        launch_stage(
            repo_root=main_root,
            config=config,
            stage=stage,
            worktree=worktree,
            dry_run=dry_run,
            remote=remote,
            pi_args=list(pi_args),
            preview=preview,
            invocation_root=invocation_root,
        )
        return

    # A plan id was given: one canonical backend read (selection happens BEFORE the
    # local-vs-remote split, so `perk address <id> --remote` dispatches exactly the selected
    # plan without re-reading the root cache).
    require_github(ctx)
    launch.print_launch_banner_gated(main_root, dry_run=dry_run, remote=remote)
    try:
        selected = select_plan(main_root, plan)
    except IssueBackendError as exc:
        raise UserFacingCliError(f"address failed\n{exc}", error_type="github_error") from exc

    if not dry_run:
        # Update the MAIN-root selector (future no-argument convenience only) — never a linked
        # worktree's binding, and never what the launch below consumes.
        cache.write_plan_ref(main_root, selected.ref)
    launch_stage(
        repo_root=main_root,
        config=config,
        stage=stage,
        worktree=worktree,
        dry_run=dry_run,
        remote=remote,
        pi_args=list(pi_args),
        preview=preview,
        plan_ref=selected.ref,
        plan_state=selected.state,
        invocation_root=invocation_root,
    )
