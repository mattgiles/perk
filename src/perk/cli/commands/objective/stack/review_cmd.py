"""``perk objective stack review`` — the stacked-PR browser-review cold launcher
(contracts.md §8.4).

Resolves an ordered PR stack (a perk objective's delivery train by default, or a non-perk
base-ref chain via ``--pr``), materializes the combined-diff review checkout through the SAME
``--stack`` checkout implementation the warm ``/stack-review-browser`` door drives, and launches
the dedicated ``stack-review`` stage with the pinned snapshot bound to the session
(``handoff_extra["stack_review"]`` — the ``audit_bundle_dir`` recovery shape). In-session, ONE
parameterless ``open_stack_review`` call recovers the snapshot and opens the plannotator browser.

Local-only by design (the flow is an interactive browser session; the stage is
``cold_remote: false``). ``--dry-run`` is **side-effect-free**: resolution is read-only wire
reads — no fetch, no worktree mutation, no handoff write, no launch — and the preview renders
the launch plan plus the resolved stack table with the not-yet-computable SHAs as nulls.
"""

import re
from pathlib import Path

import click

from perk.cli.commands.objective.stack.shared import resolve_objective_id
from perk.cli.commands.pr.review.checkout_cmd import StackMemberOut, stack_checkout
from perk.cli.commands.pr.review.shared import review_worktree_name
from perk.cli.commands.pr.review.stack_resolve import (
    ResolvedStack,
    resolve_stack_from_objective,
    resolve_stack_from_pr,
)
from perk.cli.commands.seeded_door import SeededLaunch, run_seeded_door, seeded_door_options
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.prompts import render
from perk.run import launch
from perk.substrate.config import Config
from perk.substrate.output import io_step, user_output
from perk.substrate.registry import Stage

# The binding trigger the launched session fires (the warm door's command binding — the
# `perk-pr-review-browser` skill's stack-mode section rides it on both entry paths).
_BINDING_TRIGGER = "command:stack-review-browser"

_PR_URL_RE = re.compile(r"/pull/(\d+)(?:$|[/?#])")


def _parse_pr_target(raw: str) -> int:
    """``--pr`` accepts a bare number or a PR URL; anything else is ``invalid_input``."""
    text = raw.strip()
    if text.isdigit():
        return int(text)
    match = _PR_URL_RE.search(text)
    if match is not None:
        return int(match.group(1))
    raise UserFacingCliError(
        f"--pr expects a PR number or PR URL, got {raw!r}", error_type="invalid_input"
    )


def _stack_phrase(stack: ResolvedStack) -> str:
    """The seed's one human clause naming what was resolved (door-derived, never wire prose)."""
    if stack.kind == "objective":
        return f"objective #{stack.objective_id}'s delivery train"
    return f"the base-ref chain around PR #{stack.top.pr_number}"


def _member_lines(stack: ResolvedStack) -> tuple[str, ...]:
    """The human dry-run stack table (bottom→top; wire facts only — no SHAs pre-fetch)."""
    return tuple(
        f"  {index}. PR #{member.pr_number} {member.head_ref} ← {member.base_ref}"
        for index, member in enumerate(stack.members, start=1)
    )


def _preview_rows(stack: ResolvedStack) -> list[dict[str, object]]:
    """The dry-run snapshot rows: the real envelope's row shape with ``head_sha: null``
    (not computable without the fetch — the checkout worker is the hydration boundary)."""
    return [
        {
            "pr": member.pr_number,
            "url": member.url,
            "branch": member.head_ref,
            "head_sha": None,
            "base_ref": member.base_ref,
            "node_id": member.node_id,
            "plan_id": member.plan_id,
        }
        for member in stack.members
    ]


@click.command("review", context_settings={"ignore_unknown_options": True})
@click.argument("objective", required=False, default=None)
@click.option(
    "--pr",
    "pr_target",
    default=None,
    help="Review a non-perk stack: the base-ref chain walked from this PR (number or URL); "
    "mutually exclusive with OBJECTIVE.",
)
@click.option(
    "--focus",
    default=None,
    help="Operator focus note threaded to the reviewers and the triage guidance (DATA).",
)
@seeded_door_options(
    worktree_help="Ignored positioning override (stack review runs at repo root).",
    dry_run_help="Resolve the stack and print the launch plan; no fetch, no checkout, "
    "no handoff, no launch.",
    remote_subject="stack review",
)
@click.pass_context
def review_stack(
    ctx: click.Context,
    *,
    objective: str | None,
    pr_target: str | None,
    focus: str | None,
    worktree: str | None,
    dry_run: bool,
    remote: str | None,
    as_json: bool,
    no_sync: bool,
    pi_args: tuple[str, ...],
) -> None:
    """Review a whole PR stack in the browser (combined diff + judgment-routed posting).

    \b
    Examples:
      perk objective stack review            # the plan-ref-linked objective's train
      perk objective stack review 77         # an explicit objective's train
      perk objective stack review --pr 148   # a non-perk stack, from any member PR
      perk objective stack review --dry-run  # resolve + preview only
    """

    def gather(repo_root: Path, config: Config, stage: Stage) -> SeededLaunch:
        if objective is not None and pr_target is not None:
            raise UserFacingCliError(
                "OBJECTIVE and --pr are mutually exclusive — the train arm and the chain "
                "arm resolve different stacks.",
                error_type="invalid_input",
            )
        # Reject `--remote` before any side effect (stack-review is cold_remote:false).
        launch.resolve_target(stage, remote)
        launch.print_launch_banner_gated(repo_root, dry_run=dry_run, remote=remote)

        if pr_target is not None:
            stack = resolve_stack_from_pr(repo_root, _parse_pr_target(pr_target))
        else:
            stack = resolve_stack_from_objective(
                repo_root, resolve_objective_id(repo_root, objective)
            )
        # Resolution notes (train blockers) render and proceed — warn-only by contract.
        for note in stack.notes:
            user_output(f"note: {note}")

        top = stack.top
        seed = render(
            "stages/stack-review/cold.md",
            {
                "stack_phrase": _stack_phrase(stack),
                "member_count": str(len(stack.members)),
                "top_pr": str(top.pr_number),
            },
        )

        if dry_run:
            # Side-effect-free by contract: the argv preview is built the build-once way
            # (launch's own prompt/argv builders over the trivial `worktree: none`
            # resolution), and the handoff blob preview carries the same nulls as the
            # snapshot rows plus `dry_run: true`.
            would_path = config.worktree_root / review_worktree_name(top.pr_number)
            resolved = launch.resolve_worktree(
                repo_root=repo_root,
                config=config,
                request=launch.WorktreeRequest.for_stage(stage),
                worktree=worktree,
                materialize=False,
            )
            argv = launch._build_argv(
                stage=stage,
                config=config,
                repo_root=repo_root,
                binding_trigger=_BINDING_TRIGGER,
                pi_args=list(pi_args),
                prompt=launch._resolve_prompt(
                    stage=stage,
                    resolved=resolved,
                    repo_root=repo_root,
                    config=config,
                    prompt_override=seed,
                    binding_trigger=_BINDING_TRIGGER,
                ),
            )
            handoff_preview: dict[str, object] = {
                "stack_review": {
                    "kind": stack.kind,
                    "objective_id": stack.objective_id,
                    "stack": _preview_rows(stack),
                    "base_ref": stack.base_ref,
                    "base_sha": None,
                    "top_pr": top.pr_number,
                    "checkout_path": str(would_path),
                    "notes": list(stack.notes),
                    "focus": focus or "",
                    "dry_run": True,
                }
            }
            return SeededLaunch(
                seed=seed,
                launch_note="",  # never printed on a dry run
                dry_run_label=(
                    "objective stack review --dry-run (stack resolved; no fetch, no "
                    "checkout, no handoff, no launch)"
                ),
                dry_run_fields=(
                    f"  stack ({len(stack.members)} member(s), base {stack.base_ref}, "
                    f"top #{top.pr_number}):",
                    *_member_lines(stack),
                    f"  would check out review-{top.pr_number} at {would_path}",
                    f"  would launch stage 'stack-review'  argv={' '.join(argv)}",
                ),
                dry_run_payload={
                    "success": True,
                    "error_type": None,
                    "kind": stack.kind,
                    "objective_id": stack.objective_id,
                    "stage": stage.id,
                    "top_pr": top.pr_number,
                    "checkout_path": str(would_path),
                    "base_ref": stack.base_ref,
                    "base_sha": None,
                    "stack": _preview_rows(stack),
                    "notes": list(stack.notes),
                    "argv": list(argv),
                    "handoff": handoff_preview,
                    "launched": False,
                },
                binding_trigger=_BINDING_TRIGGER,
            )

        # The hydration boundary — the SAME implementation the warm door's cold worker runs:
        # one fetch, fail-closed topology validation, top-head checkout, pinned snapshot.
        with io_step(f"materializing the stack checkout (top PR #{top.pr_number})") as s:
            result = stack_checkout(
                repo_root=repo_root, worktree_root=config.worktree_root, stack=stack
            )
            s.done(
                f"review-{result.pr_number} at {result.head_sha[:8]} "
                f"({len(result.stack)} member(s))"
            )
        # Checkout-time drift notes (the snapshot's tail beyond the resolution notes).
        for note in result.stack_notes[len(stack.notes) :]:
            user_output(f"note: {note}")

        snapshot_rows = [
            StackMemberOut.from_domain(member).model_dump(mode="json") for member in result.stack
        ]
        return SeededLaunch(
            seed=seed,
            launch_note=(
                f"checked out the {len(result.stack)}-member stack (top PR "
                f"#{result.pr_number}); launching the stack-review session"
            ),
            dry_run_label="",  # unreachable on the real-run branch
            dry_run_fields=(),
            dry_run_payload={},
            # The structural binding: `open_stack_review` recovers this pinned snapshot from
            # the launch handoff — its SOLE stack authority (contracts.md §8.3/§8.4).
            handoff_extra={
                "stack_review": {
                    "kind": stack.kind,
                    "objective_id": stack.objective_id,
                    "stack": snapshot_rows,
                    "base_ref": result.stack_base_ref or result.base_ref,
                    "base_sha": result.base_sha,
                    "top_pr": result.pr_number,
                    "checkout_path": str(result.path),
                    "notes": list(result.stack_notes),
                    "focus": focus or "",
                }
            },
            binding_trigger=_BINDING_TRIGGER,
        )

    run_seeded_door(
        ctx,
        stage_id="stack-review",
        worktree=worktree,
        dry_run=dry_run,
        remote=remote,
        as_json=as_json,
        no_sync=no_sync,
        pi_args=pi_args,
        backend_errors=(GitHubError,),
        gather=gather,
    )
