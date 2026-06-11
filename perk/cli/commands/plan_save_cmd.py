"""`perk plan-save` — the Python/worker GitHub plan-write (the cold save door).

The first `require_github` consumer and the first GitHub *mutation* (contracts.md §8.4;
T2a). The warm in-session twin is the TS `/plan-save` tool (T3). Supervisor surface
(cli-vs-pi §3.2): `--json` to stdout + stable exit codes, human text to stderr.

Exit codes: 0 saved · 1 invalid input / unauthed / op failure · 2 not-a-repo.
"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import click

from perk import cache, github, objective, plan
from perk.cli.alias import alias
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.output import machine_output, user_output

# error_type -> process exit code (default 1).
_EXIT_FOR_TYPE = {"not_a_repo": 2}


@dataclass(frozen=True)
class PlanSaveResult:
    issue: github.PlanIssue
    plan_ref: plan.PlanRef
    issue_body: str
    body_comment: str
    dry_run: bool
    cached: bool  # the plan-ref was written to .pi/workflow/plan-ref.json (real save only)
    updated: bool  # an existing issue was updated in place (idempotent re-save upsert)
    # The objective-node commit (P2.T10): `linked` true iff the node→plan backlink + in_progress
    # advance succeeded; `node`/`status` describe it; `error` carries a non-fatal link failure.
    # `None` when no objective node link was requested (no --node-id).
    objective_node: dict[str, object] | None = None


@alias("psave")
@click.command("plan-save")
@click.option(
    "--plan-file",
    type=click.Path(path_type=Path),
    help="Path to the plan markdown to save.",
)
@click.option("--run-id", help="Correlation run id (defaults to $PERK_RUN_ID).")
@click.option("--title", help="Issue title (defaults to the plan's first heading).")
@click.option(
    "--objective-id",
    help="Link the plan to an objective (the plan→objective direction; P2.T10).",
)
@click.option(
    "--node-id",
    help="Objective node id to commit on save (with --objective-id; sets the node→plan backlink "
    "+ advances it to in_progress).",
)
@click.option(
    "--consumed-learn",
    help="Comma-separated perk:learn issue numbers this docs plan consumes (hop-2; e.g. '45,50').",
)
@click.option("--dry-run", is_flag=True, help="Compose and print without touching GitHub.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def plan_save(
    ctx: click.Context,
    *,
    plan_file: Path | None,
    run_id: str | None,
    title: str | None,
    objective_id: str | None,
    node_id: str | None,
    consumed_learn: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Save a plan to GitHub as an issue (the queryable header + the full body comment).

    \b
    Examples:
      perk plan-save --plan-file plan.md           # create the plan issue
      perk plan-save --plan-file plan.md --dry-run # compose + print, no GitHub
      perk plan-save --plan-file plan.md --json    # machine-readable (supervisor surface)
    """
    try:
        repo_root = require_repo(ctx)
        # A dry run composes + prints locally; it needs neither auth nor a network.
        if not dry_run:
            require_github(ctx)
        resolved_run_id = run_id if run_id is not None else os.environ.get("PERK_RUN_ID")
        # Recover the objective link from the handoff (#78): the `/plan-save` command forwards only
        # {plan, title}, so an objective-plan factory session would otherwise drop the link the
        # `objective-plan` command stashed in the handoff. Explicit flags always win; a non-
        # objective run (handoff without `objective_id`) is unaffected.
        objective_id, node_id = _link_from_handoff(
            repo_root, resolved_run_id, objective_id, node_id
        )
        # Recover `consumed_learn` from the handoff (#102): the learn-docs factory is read-only, so
        # the model saves via the `/plan-save` *command* (forwards only {plan, title}) rather than
        # the gated-out `plan_save` *tool*. The learn-docs cold door stashes the gathered numbers in
        # the handoff; recover them here so the save surface is irrelevant. An explicit
        # --consumed-learn always wins; a non-factory run (no handoff key) is unaffected.
        consumed_learn_numbers = _consumed_learn_from_handoff(
            repo_root, resolved_run_id, _parse_consumed_learn(consumed_learn)
        )
        result = _plan_save_impl(
            repo_root=repo_root,
            plan_file=plan_file,
            run_id=resolved_run_id,
            title=title,
            objective_id=objective_id,
            node_id=node_id,
            consumed_learn=consumed_learn_numbers,
            dry_run=dry_run,
        )
    except GitHubError as exc:
        _fail(
            ctx,
            as_json=as_json,
            error_type="github_error",
            message=f"GitHub plan write failed\n{exc}",
        )
        return
    except UserFacingCliError as exc:
        _fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    if as_json:
        machine_output(json.dumps(_result_to_dict(result)))
    else:
        _render_human(result)


def _link_from_handoff(
    repo_root: Path,
    run_id: str | None,
    objective_id: str | None,
    node_id: str | None,
) -> tuple[str | None, str | None]:
    """Default ``objective_id``/``node_id`` from the run's handoff when not passed explicitly (#78).

    The ``objective-plan`` factory stashes ``objective_id``/``node_id`` in the handoff so the link
    survives the ``/plan-save`` *command* path (which forwards only ``{plan, title}``). Explicit
    flags win outright; only fill BOTH from the handoff when BOTH were absent (a half-specified
    link is the caller's, never silently mixed with the handoff's). A missing handoff, a non-
    objective handoff, or a missing key leaves the inputs untouched. Best-effort: a malformed
    handoff must never block a save.
    """
    if objective_id is not None or node_id is not None or not run_id:
        return objective_id, node_id
    try:
        handoff = cache.read_handoff(repo_root, run_id)
    except (OSError, ValueError):
        return objective_id, node_id
    if not handoff:
        return objective_id, node_id
    ho_objective = handoff.get("objective_id")
    ho_node = handoff.get("node_id")
    if ho_objective and ho_node:
        return str(ho_objective), str(ho_node)
    return objective_id, node_id


def _consumed_learn_from_handoff(
    repo_root: Path,
    run_id: str | None,
    consumed_learn: tuple[int, ...],
) -> tuple[int, ...]:
    """Default ``consumed_learn`` from the run's handoff when not passed explicitly (#102).

    The ``learn-docs`` factory stashes the gathered ``perk:learn`` numbers in the handoff so they
    survive the ``/plan-save`` *command* path (which forwards only ``{plan, title}``, dropping the
    flag). An explicit ``--consumed-learn`` (parsed to a non-empty tuple) always wins; an empty
    tuple means the flag was absent, so fall back to the handoff. A missing handoff, a non-factory
    handoff (no ``consumed_learn`` key), or a malformed value leaves the input untouched.
    Best-effort: a malformed handoff must never block a save.
    """
    if consumed_learn or not run_id:
        return consumed_learn
    try:
        handoff = cache.read_handoff(repo_root, run_id)
    except (OSError, ValueError):
        return consumed_learn
    if not handoff:
        return consumed_learn
    raw = handoff.get("consumed_learn")
    if not raw:
        return consumed_learn
    try:
        numbers = {int(str(n).lstrip("#")) for n in raw}
    except (TypeError, ValueError):
        return consumed_learn
    return tuple(sorted(numbers))


def _parse_consumed_learn(raw: str | None) -> tuple[int, ...]:
    """Parse a comma-separated issue-number list into a sorted unique tuple (hop-2).

    ``None``/empty → ``()``. A non-integer token raises ``UserFacingCliError`` (``invalid_input``).
    """
    if not raw or not raw.strip():
        return ()
    numbers: set[int] = set()
    for token in raw.split(","):
        token = token.strip().lstrip("#")
        if not token:
            continue
        try:
            numbers.add(int(token))
        except ValueError as exc:
            raise UserFacingCliError(
                f"Invalid --consumed-learn value {token!r} (expected issue numbers).",
                error_type="invalid_input",
            ) from exc
    return tuple(sorted(numbers))


def _plan_save_impl(
    *,
    repo_root: Path,
    plan_file: Path | None,
    run_id: str | None,
    title: str | None,
    objective_id: str | None = None,
    node_id: str | None = None,
    consumed_learn: tuple[int, ...] = (),
    dry_run: bool,
) -> PlanSaveResult:
    """Pure-ish logic (no Click). Composes the header/body and performs the GitHub write."""
    if plan_file is None:
        raise UserFacingCliError(
            "No plan file given\nPass --plan-file <path> to the plan markdown.",
            error_type="invalid_input",
        )
    if not plan_file.is_file():
        raise UserFacingCliError(f"Plan file not found: {plan_file}", error_type="invalid_input")
    plan_markdown = plan_file.read_text(encoding="utf-8")
    if not plan_markdown.strip():
        raise UserFacingCliError(f"Plan file is empty: {plan_file}", error_type="invalid_input")

    resolved_title = title or plan.derive_title(plan_markdown)
    header = plan.PlanHeader(
        run_id=run_id or "",
        created=plan.now_iso(),
        objective_id=objective_id,
        consumed_learn=consumed_learn,
    )
    issue_body = plan.render_metadata_block(plan.PLAN_HEADER_KEY, header.to_data())
    body_comment = plan.render_plan_body(plan_markdown)

    github.create_label(
        plan.PLAN_LABEL,
        color=plan.PLAN_LABEL_COLOR,
        description=plan.PLAN_LABEL_DESCRIPTION,
        repo_root=repo_root,
        dry_run=dry_run,
    )
    issue = github.create_plan_issue(
        title=resolved_title,
        body=issue_body,
        repo_root=repo_root,
        run_id=run_id,
        dry_run=dry_run,
    )
    # `create_plan_issue` is idempotent on run_id: a fresh create returns existed=False, a re-save
    # returns the existing issue. On a fresh create we post the plan-body comment; on a re-save we
    # upsert the existing issue in place (PATCH the plan-body comment + the title). A dry run shells
    # nothing. The anti-duplicate guarantee is preserved — never a second issue per run_id.
    updated = False
    if not dry_run:
        if issue.existed:
            github.update_plan_issue(
                number=issue.number,
                title=resolved_title,
                body_comment=body_comment,
                repo_root=repo_root,
            )
            # `update_plan_issue` rewrites only the plan-body comment + the issue title; it never
            # touches the `plan-header` block. So the planning-time header fields (`objective_id`,
            # `consumed_learn`) that are only written on a fresh create would be silently dropped on
            # any re-save — leaving the canonical header (which `reconstruct_plan_ref` / on-land
            # consume read from) stale. Merge them back via the `update_plan_header` gateway, which
            # is additive (omitted fields are left intact, never clobbering an existing link or the
            # submit-populated branch/pr/lifecycle_stage). A failure surfaces (raises GitHubError →
            # `github_error`) — this is the canonical save, where a silent drop is the bug.
            header_fields: dict[str, object] = {}
            if objective_id is not None:
                header_fields["objective_id"] = objective_id
            if consumed_learn:
                header_fields["consumed_learn"] = list(consumed_learn)
            if header_fields:
                github.update_plan_header(
                    issue=issue.number, fields=header_fields, repo_root=repo_root
                )
            updated = True
        else:
            github.add_issue_comment(
                issue=issue.number, body=body_comment, repo_root=repo_root, dry_run=dry_run
            )

    plan_ref = plan.PlanRef(
        provider="github",
        pr_id=str(issue.number),
        url=issue.url,
        labels=(plan.PLAN_LABEL,),
        objective_id=objective_id,
        consumed_learn=consumed_learn,
    )
    # Persist the ref as the cache.plan-ref pointer (turn-2b §7): the next session's
    # reconciliation links it, and `implement` reads it. A dry run writes nothing.
    if not dry_run:
        cache.write_plan_ref(repo_root, plan_ref.to_data())

    # Commit the objective-node claim atomically (P2.T10): set the node→plan backlink AND advance
    # `planning → in_progress` in a single write. Fail-loud, non-fatal, idempotent on re-save
    # (the plan already exists — never raise here; mirror pr_land._reconcile_objective_on_land).
    objective_node_result: dict[str, object] | None = None
    if not dry_run and objective_id and node_id:
        try:
            github.update_objective_node(
                number=int(str(objective_id).lstrip("#")),
                node_id=node_id,
                status=objective.NodeStatus.IN_PROGRESS,
                pr=f"#{issue.number}",
                repo_root=repo_root,
            )
            objective_node_result = {
                "linked": True,
                "node": node_id,
                "status": "in_progress",
                "error": None,
            }
        except Exception as exc:  # fail-loud, non-fatal: the plan already exists.
            print(
                f"perk plan-save: objective node link skipped (non-fatal): {exc}",
                file=sys.stderr,
            )
            objective_node_result = {
                "linked": False,
                "node": node_id,
                "status": None,
                "error": str(exc),
            }

    return PlanSaveResult(
        issue=issue,
        plan_ref=plan_ref,
        issue_body=issue_body,
        body_comment=body_comment,
        dry_run=dry_run,
        cached=not dry_run,
        updated=updated,
        objective_node=objective_node_result,
    )


def _result_to_dict(result: PlanSaveResult) -> dict[str, object]:
    return {
        "success": True,
        "error_type": None,
        "message": None,
        "issue": {
            "number": result.issue.number,
            "url": result.issue.url,
            "existed": result.issue.existed,  # warm /plan-save surfaces this in details (T3)
        },
        "plan_ref": result.plan_ref.to_data(),
        "cached": result.cached,
        "updated": result.updated,
        "objective_node": result.objective_node,
        "dry_run": result.dry_run,
    }


def _render_human(result: PlanSaveResult) -> None:
    if result.dry_run:
        user_output(click.style("plan-save --dry-run (no GitHub writes)", dim=True))
        user_output(click.style("── issue body ──", fg="bright_black"))
        user_output(result.issue_body)
        user_output(click.style("── plan-body comment ──", fg="bright_black"))
        user_output(result.body_comment)
        return
    verb = "Updated" if result.issue.existed else "Saved"
    user_output(
        click.style("✓ ", fg="green")
        + f"{verb} plan "
        + click.style(f"#{result.issue.number}", fg="cyan")
        + f" → {result.issue.url}"
    )
    node_link = result.objective_node
    if node_link and node_link.get("linked"):
        user_output(
            click.style(
                f"  ↳ linked objective #{result.plan_ref.objective_id} node "
                f"{node_link.get('node')} (in_progress)",
                dim=True,
            )
        )


def _fail(ctx: click.Context, *, as_json: bool, error_type: str, message: str) -> None:
    """Route a failure to the supervisor surface (stable exit code; --json or styled stderr)."""
    if as_json:
        machine_output(
            json.dumps(
                {"success": False, "error_type": error_type, "message": message, "dry_run": False}
            )
        )
    else:
        user_output(click.style("Error: ", fg="red") + message)
    ctx.exit(_EXIT_FOR_TYPE.get(error_type, 1))
