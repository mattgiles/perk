"""Remote-runner dispatch for the cold-door launch.

:func:`_drive_remote_target` — the ``--remote`` drive of a drivable stage (contracts.md
§8.13). It positions
nothing locally; it persists + verifies the ``run_id→plan`` linkage (establish-before-consume,
§8.2) and triggers the runner via :mod:`perk.run.runner`.
"""

import dataclasses
import json
from pathlib import Path

from perk import github, plan
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.run import runner
from perk.run.launch.worktree import Target
from perk.state import cache, run_id
from perk.substrate.output import log_warn, machine_output, user_output
from perk.substrate.registry import Stage


def _drive_remote_target(
    *,
    stage: Stage,
    target: Target,
    repo_root: Path,
    dry_run: bool,
    plan_ref: plan.PlanRef | None = None,
    selector_root: Path | None = None,
) -> None:
    """Drive a ``--remote`` launch of a drivable stage (contracts.md §8.13).

    Unlike the cold-local door, a remote dispatch positions **nothing** on the dispatcher's
    machine (no worktree, no handoff) — the workflow checks out the branch and positions
    the worker in CI. Here we only: resolve the plan, mint the ``run_id``, **persist the
    ``run_id→plan`` linkage and read it back to verify** (the establish-before-consume gate,
    §8.2), then **trigger** the runner and record the verified handle. A ``--dry-run`` is a
    side-effect-free dispatch preview (no persist, no trigger).

    ``plan_ref``: the already-selected canonical ref (an explicit positional plan id) —
    dispatched exactly as passed, never re-read from the mutable selector. Without it the
    no-argument gesture keeps the ``selector_root`` cache read (the invoking checkout).
    """
    if plan_ref is None:
        plan_ref = cache.read_plan_ref(selector_root if selector_root is not None else repo_root)
    if plan_ref is None:
        raise UserFacingCliError(
            "a remote drive needs a saved plan — run /plan-save first.",
            error_type="no_plan_ref",
        )
    rid = run_id.mint()  # a cold dispatch is a cold launch => mints (registry policy)
    runner_ref = target.runner or ""
    selected = runner.select_runner(runner_ref)
    # Prefer the plan's pinned base so the runner input carries the real target; fall back
    # to the GitHub default branch. (run_worker still treats `base` as informational — this keeps
    # the §8.13 input honest.)
    plan_base = plan_ref.base
    if plan_base and plan_base.strip():
        base = plan_base.strip()
    else:
        try:
            base = github.default_branch(repo_root)
        except GitHubError as exc:
            base = "main"
            log_warn(
                f"could not resolve the default branch ({exc}); basing the dispatch on "
                f"{base!r} — pass an explicit base if that is wrong."
            )
    pr_id = plan_ref.pr_id
    plan_ref_data = plan.PlanRefOut.from_domain(plan_ref).model_dump(mode="json")
    inputs = {
        "run_id": rid,
        "stage": stage.id,
        "plan": pr_id,
        "base": base,
        "workflow": runner.GITHUB_ACTIONS_WORKFLOW,
    }
    runner_label = runner_ref or "(default)"

    if dry_run:  # side-effect-free dispatch preview: no persist, no trigger
        user_output(
            f"would dispatch stage '{stage.id}' to {runner_label} (run_id={rid}, plan #{pr_id})"
        )
        machine_output(
            json.dumps(
                {
                    "success": True,
                    "dry_run": True,
                    "stage": stage.id,
                    "runner": runner_ref,
                    "run_id": rid,
                    "plan_ref": plan_ref_data,
                    "inputs": inputs,
                }
            )
        )
        return

    # Persist the intent (the verified linkage), then read it back and assert the round-trip
    # established before consuming — the establish-before-consume gate (§8.2).
    record = cache.Dispatch(
        run_id=rid,
        stage=stage.id,
        plan_ref=plan_ref,
        runner=runner_ref,
        kind=selected.kind,
        status="dispatching",
        dispatched_at=runner.utc_now_iso(),
        run_handle=None,
        error=None,
    )
    cache.write_dispatch(repo_root, rid, record)
    back = cache.read_dispatch(repo_root, rid)
    if back is None or back.run_id != rid or back.plan_ref.pr_id != pr_id:
        raise UserFacingCliError(
            f"dispatch state for run {rid} did not verify after write — refusing to trigger.",
            error_type="dispatch_state_unverified",
        )

    # Trigger the runner. On failure, the failed record stays for supervisor visibility.
    try:
        handle = selected.dispatch(
            stage=stage.id, plan_ref=plan_ref_data, run_id=rid, base=base, repo_root=repo_root
        )
    except (runner.RunnerError, GitHubError) as exc:
        failed = dataclasses.replace(record, status="failed", error=str(exc))
        cache.write_dispatch(repo_root, rid, failed)
        raise UserFacingCliError(
            f"failed to dispatch stage '{stage.id}' to {runner_label}: {exc}",
            error_type="dispatch_failed",
        ) from exc

    # Finalize: record the verified handle. The critical verified linkage is the step-above one;
    # a finalize-write mismatch is loud-but-non-fatal.
    final = dataclasses.replace(record, status="dispatched", run_handle=handle)
    cache.write_dispatch(repo_root, rid, final)
    confirm = cache.read_dispatch(repo_root, rid)
    if confirm is None or confirm.status != "dispatched":
        log_warn(f"dispatch record for run {rid} did not confirm 'dispatched' after finalize.")

    user_output(
        f"dispatched stage '{stage.id}' to {runner_label} — run {handle.url or handle.run_ref}"
    )
    machine_output(
        json.dumps(
            {
                "success": True,
                "stage": stage.id,
                "run_id": rid,
                "runner": runner_ref,
                "run_handle": runner.RunHandleModel.from_domain(handle).model_dump(mode="json"),
            }
        )
    )
