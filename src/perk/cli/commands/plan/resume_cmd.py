"""`perk resume <plan>` — the cross-stage resume verb.

Resolve any plan to its next action and act on it. Reads the plan from the issue backend
(`IssueBackend.get_plan`), reconstructs the `cache.plan-ref`, classifies via the shared
`resume.resolve_next_action` (contracts.md §8.37), then either launches the verdict's stage
(reusing `launch_stage` — idempotent worktree + materialize + exec pi) or names the human gate
without launching. Supervisor surface: `--json` to stdout, stable exit codes.

Exit codes: 0 resumed / nothing-to-resume · 1 invalid input / unauthed / plan-not-found /
kind-mismatch (``issue_kind_mismatch`` — an existing issue with no plan-header) / op failure ·
2 not-a-repo.
"""

import json

import click

from perk import github, plan
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.cli import completions
from perk.cli.context import require_github, require_repo
from perk.cli.emit import fail
from perk.cli.ensure import Ensure, UserFacingCliError
from perk.cli.plan_selection import (
    load_main_config,
    main_repo_root,
    parse_plan_id,
    require_plan_kind,
)
from perk.github import GitHubError
from perk.prompts import render
from perk.run import launch, resume
from perk.state import cache
from perk.substrate.output import io_step, machine_output, user_output
from perk.substrate.registry import stage_by_id


@click.command("resume", context_settings={"ignore_unknown_options": True})
@click.argument("plan", shell_complete=completions.complete_plan_id)
@click.option("--dry-run", is_flag=True, help="Resolve + print the stage without launching.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.option(
    "--remote",
    type=str,
    default=None,
    is_flag=False,
    flag_value="",
    help=(
        "Local (default) or a remote runner (dispatch the resolved stage to CI; only the "
        "remotely runnable stages — implement/address — dispatch)."
    ),
)
@click.argument("pi_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def resume_cmd(
    ctx: click.Context,
    *,
    plan: str,
    dry_run: bool,
    as_json: bool,
    remote: str | None,
    pi_args: tuple[str, ...],
) -> None:
    """Resume PLAN (a plan issue id) at its current stage.

    \b
    Examples:
      perk plan resume 42            # resolve #42's stage and launch it (fresh context)
      perk plan resume 42 --dry-run  # print the resolved stage + launch plan, launch nothing
      perk plan resume https://github.com/o/r/issues/42   # paste the plan's URL instead of the id
    """
    try:
        invocation_root = require_repo(ctx)
        require_github(ctx)  # resume always reads GitHub (the dry run resolves via a read)
        # Two-roots rule: config, canonical reads, selector writes, and positioning all anchor
        # to the MAIN checkout (a relative worktree root must never resolve beneath a linked
        # worktree); resume has no cache-fallback read — the plan id is always explicit.
        main_root = main_repo_root(invocation_root)
        config = load_main_config(main_root)
        plan_id = parse_plan_id(plan)
        backend = resolve.resolve_issue_backend(main_root)
        # Banner first: head a real local launch with the banner BEFORE narrating the lookup wait.
        launch.print_launch_banner_gated(main_root, dry_run=dry_run, remote=remote)
        # Narrate the backend lookup wait. The lookup runs on the dry-run path too (dry-run
        # resolves the stage via this same read), so the narration is NOT gated on `dry_run`; the
        # line goes to stderr, leaving the `--json` stdout payload byte-unchanged. The not-found
        # raise escapes the step (dangling + the error text below).
        with io_step(f"looking up plan #{plan_id}") as s:
            state = backend.get_plan(issue_id=plan_id)
            if state is None:
                raise UserFacingCliError(
                    f"Plan issue #{plan_id} not found", error_type="plan_not_found"
                )
            # Positive plan identification (contracts §8.1): a headerless issue must never bind
            # and launch as a plan — refuse before reconstruction/classification.
            require_plan_kind(state, plan_id, backend_id=backend.backend_id)
            ref = resume.reconstruct_plan_ref(state, provider=backend.backend_id)
            next_action = resume.resolve_next_action(
                state,
                has_pending_learn=cache.has_marker(main_root, cache.PENDING_LEARN),
                get_feedback=lambda n: github.get_pr_feedback(pr_number=n, repo_root=main_root),
            )
            s.done(f"found plan #{plan_id}")
    except (IssueBackendError, GitHubError) as exc:
        fail(ctx, as_json=as_json, error_type="github_error", message=f"resume failed\n{exc}")
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    stage_id = next_action.stage_id
    if stage_id is None:
        # Gate/terminal verdicts NEVER launch (real and dry-run alike): report the human gate
        # (or done) and exit 0 — a benign decision, matching the supervisor's exit posture.
        if next_action is resume.NextAction.DONE:
            _render_done(plan_id, as_json=as_json)
            return
        pr = Ensure.not_none(state.pr, "gate verdict with no PR — this is a bug")
        _render_gate(
            plan_id,
            next_action,
            pr.number,
            stacked=ref.delivery_lineage is not None,
            as_json=as_json,
        )
        return

    worktree_name = launch.resolve_plan_worktree_name(ref)
    if dry_run:
        _render_dry_run(plan_id, next_action, worktree_name, ref, as_json=as_json)
        return

    # Real run: update the MAIN-root selector (never a linked worktree's binding — the
    # two-roots rule), then launch the stage with the resolved ref passed directly (the
    # launch never re-reads that mutable cache write).
    cache.write_plan_ref(main_root, ref)
    stage = stage_by_id(stage_id)
    # Resume prior-work advisory (contracts.md §8.38): an implement resume into a worktree that
    # already exists locally (the D4 reuse arm — the same `worktree_root / name` join
    # `resolve_worktree` performs) may hold committed/uncommitted work from an interrupted
    # session; advise the launched session to inspect and reconcile before starting. Deliberately
    # scoped: implement verdict only, local reuse only, this resume door only.
    prompt_suffix: str | None = None
    if stage_id == "implement" and (config.worktree_root / worktree_name).exists():
        prompt_suffix = render("common/resume-advisory.md", {})
    launch.launch_stage(
        repo_root=main_root,
        config=config,
        stage=stage,
        worktree=None,
        dry_run=False,
        remote=remote,
        pi_args=list(pi_args),
        prompt_suffix=prompt_suffix,
        plan_ref=ref,  # the resolved ref is launch authority (never re-read from the cache)
        plan_state=state,
        invocation_root=invocation_root,
    )


def _gate_message(
    plan_id: str, next_action: resume.NextAction, pr_number: int, *, stacked: bool
) -> str:
    """The human gate line for a non-launchable verdict (contracts.md §8.37) —
    delivery-aware: a stacked layer reviews on the draft PR, records the post-review handoff
    with `perk ready`, and lands whole as a train (never `/land`)."""
    prefix = f"plan #{plan_id} (PR #{pr_number}): "
    if next_action is resume.NextAction.READY_FOR_REVIEW:
        if stacked:
            return prefix + (
                "draft layer PR — review proceeds on the draft; when review + address are "
                f"done, record the handoff with perk ready {plan_id}; the train lands whole "
                "via /objective-land"
            )
        return prefix + (
            "draft PR — mark it ready (perk pr ready from the plan worktree) "
            "and /land when satisfied"
        )
    if next_action is resume.NextAction.AWAITING_REVIEW:
        return prefix + "no actionable feedback — awaiting the human review/land gate"
    return prefix + "PR closed unmerged — needs human attention (reopen it or replan)"


def _render_gate(
    plan_id: str, next_action: resume.NextAction, pr_number: int, *, stacked: bool, as_json: bool
) -> None:
    message = _gate_message(plan_id, next_action, pr_number, stacked=stacked)
    if as_json:
        machine_output(
            json.dumps(
                {
                    "success": True,
                    "plan": plan_id,
                    "next_action": next_action.value,
                    "resumed_stage": None,
                    "pr": pr_number,
                    "message": message,
                }
            )
        )
    else:
        user_output(message)


def _render_done(plan_id: str, *, as_json: bool) -> None:
    message = f"plan #{plan_id} is merged and learned — nothing to resume"
    if as_json:
        machine_output(
            json.dumps(
                {
                    "success": True,
                    "plan": plan_id,
                    "next_action": resume.NextAction.DONE.value,
                    "resumed_stage": None,
                    "message": message,
                }
            )
        )
    else:
        user_output(message)


def _render_dry_run(
    plan_id: str,
    next_action: resume.NextAction,
    worktree: str,
    ref: plan.PlanRef,
    *,
    as_json: bool,
) -> None:
    stage_id = next_action.stage_id
    if as_json:
        machine_output(
            json.dumps(
                {
                    "success": True,
                    "plan": plan_id,
                    "next_action": next_action.value,
                    "resumed_stage": stage_id,
                    "worktree": worktree,
                    "plan_ref": plan.PlanRefOut.from_domain(ref).model_dump(mode="json"),
                    "dry_run": True,
                }
            )
        )
    else:
        user_output(click.style("resume --dry-run (resolve only, no launch)", dim=True))
        user_output(f"  plan=#{plan_id}  resumed_stage={stage_id}  worktree={worktree}")
