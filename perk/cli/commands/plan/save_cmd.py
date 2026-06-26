"""`perk plan save` — the Python/worker GitHub plan-write (the cold save door).

The first `require_github` consumer and the first GitHub *mutation* (contracts.md §8.4).
The warm in-session twin is the TS `/plan-save` tool. Supervisor surface:
`--json` to stdout + stable exit codes, human text to stderr.

Exit codes: 0 saved · 1 invalid input / unauthed / op failure · 2 not-a-repo.
"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import click

from perk import objective, plan
from perk.backends import issue_backend, objective_store, resolve
from perk.backends.issue_backend import IssueBackendError
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.state import cache
from perk.substrate.config import load_config
from perk.substrate.output import machine_output, user_output

# error_type -> process exit code (default 1).
_EXIT_FOR_TYPE = {"not_a_repo": 2}


@dataclass(frozen=True)
class PlanSaveResult:
    issue: issue_backend.IssueRef
    plan_ref: plan.PlanRef
    issue_body: str
    body_comment: str
    dry_run: bool
    cached: bool  # the plan-ref was written to .perk/workflow/plan-ref.json (real save only)
    updated: bool  # an existing issue was updated in place (idempotent re-save upsert)
    # The objective-node commit: `linked` true iff the node→plan backlink + in_progress
    # advance succeeded; `node`/`status` describe it; `error` carries a non-fatal link failure.
    # `None` when no objective node link was requested (no --node-id).
    objective_node: dict[str, object] | None = None


@click.command("save")
@click.option(
    "--plan-file",
    # Deliberately no exists=True: existence/emptiness are tier-2 (UserFacingCliError) so the
    # --json error envelope (error_type: invalid_input) survives a missing file.
    type=click.Path(path_type=Path),
    help="Path to the plan markdown to save.",
)
@click.option("--run-id", help="Correlation run id (defaults to $PERK_RUN_ID).")
@click.option("--title", help="Issue title (defaults to the plan's first heading).")
@click.option(
    "--objective-id",
    help="Link the plan to an objective (the plan→objective direction).",
)
@click.option(
    "--node-id",
    help="Objective node id to commit on save (with --objective-id; sets the node→plan backlink "
    "+ advances it to in_progress).",
)
@click.option(
    "--consumed-learn",
    help="Comma-separated perk:learn issue ids this docs plan consumes (e.g. '45,50' "
    "or 'ENG-45,ENG-50').",
)
@click.option(
    "--adopt-from",
    help="Adopt the named pre-existing issue IN PLACE as this plan (stamps the plan "
    "metadata additively into that issue, mutually exclusive with --objective-id/--node-id).",
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
    adopt_from: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Save a plan to GitHub as an issue (the queryable header + the full body comment).

    \b
    Examples:
      perk plan save --plan-file plan.md           # create the plan issue
      perk plan save --plan-file plan.md --dry-run # compose + print, no GitHub
      perk plan save --plan-file plan.md --json    # machine-readable (supervisor surface)
    """
    try:
        repo_root = require_repo(ctx)
        # A dry run composes + prints locally; it needs neither auth nor a network.
        if not dry_run:
            require_github(ctx)
        resolved_run_id = run_id if run_id is not None else os.environ.get("PERK_RUN_ID")
        # Recover the objective link from the handoff: the `/plan-save` command forwards only
        # {plan, title}, so an objective-plan factory session would otherwise drop the link the
        # `objective-plan` command stashed in the handoff. Explicit flags always win; a non-
        # objective run (handoff without `objective_id`) is unaffected.
        objective_id, node_id = _link_from_handoff(
            repo_root, resolved_run_id, objective_id, node_id
        )
        # Recover `consumed_learn` from the handoff: the learn-docs factory is read-only, so
        # the model saves via the `/plan-save` *command* (forwards only {plan, title}) rather than
        # the gated-out `plan_save` *tool*. The learn-docs cold door stashes the gathered ids in
        # the handoff; recover them here so the save surface is irrelevant. An explicit
        # --consumed-learn always wins; a non-factory run (no handoff key) is unaffected.
        consumed_learn_ids = _consumed_learn_from_handoff(
            repo_root, resolved_run_id, _parse_consumed_learn(consumed_learn)
        )
        # Recover the adoption link from the handoff: the `plan from` cold door stashes the
        # source `adopt_from` issue id in the handoff so it survives the `/plan-save` *command*
        # path (which forwards only {plan, title}). An explicit --adopt-from always wins.
        adopt_from = _adopt_from_handoff(repo_root, resolved_run_id, adopt_from)
        result = _plan_save_impl(
            repo_root=repo_root,
            plan_file=plan_file,
            run_id=resolved_run_id,
            title=title,
            objective_id=objective_id,
            node_id=node_id,
            consumed_learn=consumed_learn_ids,
            adopt_from=adopt_from,
            dry_run=dry_run,
        )
    except IssueBackendError as exc:
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
    """Default ``objective_id``/``node_id`` from the run's handoff when not passed explicitly.

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
    consumed_learn: tuple[str, ...],
) -> tuple[str, ...]:
    """Default ``consumed_learn`` from the run's handoff when not passed explicitly.

    The ``learn-docs`` factory stashes the gathered ``perk:learn`` ids in the handoff so they
    survive the ``/plan-save`` *command* path (which forwards only ``{plan, title}``, dropping the
    flag). An explicit ``--consumed-learn`` (parsed to a non-empty tuple) always wins; an empty
    tuple means the flag was absent, so fall back to the handoff. A missing handoff, a non-factory
    handoff (no ``consumed_learn`` key), or a malformed value leaves the input untouched.
    Best-effort: a malformed handoff must never block a save. Ids are opaque strings (§8.21).
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
    if not raw or not isinstance(raw, list):
        return consumed_learn
    ids = {cleaned for n in raw if (cleaned := str(n).lstrip("#").strip())}
    if not ids:
        return consumed_learn
    return tuple(sorted(ids))


def _adopt_from_handoff(
    repo_root: Path,
    run_id: str | None,
    adopt_from: str | None,
) -> str | None:
    """Default ``adopt_from`` from the run's handoff when not passed explicitly.

    The ``plan from`` cold door stashes the source issue id in the handoff (key ``adopt_from``) so
    the in-place adoption link survives the ``/plan-save`` *command* path (which forwards only
    ``{plan, title}``). An explicit ``--adopt-from`` always wins; a missing handoff, a non-adoption
    handoff (no ``adopt_from`` key), or a malformed value leaves the input untouched. Best-effort:
    a malformed handoff must never block a save. The id is an opaque string (§8.21).
    """
    if adopt_from is not None or not run_id:
        return adopt_from
    try:
        handoff = cache.read_handoff(repo_root, run_id)
    except (OSError, ValueError):
        return adopt_from
    if not handoff:
        return adopt_from
    ho_adopt = handoff.get("adopt_from")
    if ho_adopt:
        return str(ho_adopt)
    return adopt_from


def _parse_consumed_learn(raw: str | None) -> tuple[str, ...]:
    """Parse a comma-separated issue-id list into a sorted unique tuple of opaque string ids
    (GitHub ``45`` or Linear ``ENG-45``).

    ``None``/empty → ``()``. Tokens are stripped of ``#``/whitespace; only empty tokens are
    skipped — ids are otherwise opaque (no int parse; contracts §8.21).
    """
    if not raw or not raw.strip():
        return ()
    ids: set[str] = set()
    for token in raw.split(","):
        token = token.strip().lstrip("#").strip()
        if token:
            ids.add(token)
    return tuple(sorted(ids))


def _resolve_plan_base(
    repo_root: Path,
    store: objective_store.ObjectiveStore,
    objective_id: str | None,
) -> str | None:
    """Resolve the plan's pinned base: the linked objective's own ``base`` wins (it is the
    source of truth for its node plans), else the repo's ``[workflow] base``, else ``None``.

    Fail-soft on the objective read: a ``None``/missing objective, a header without ``base``, or any
    store error falls through to the config step (never blocks a save). When unset everywhere the
    submit + start-point paths fall back to the GitHub default branch (byte-identical to today).
    """
    if objective_id is not None:
        try:
            state = store.get_objective(objective_id=str(objective_id).lstrip("#"))
        except Exception as exc:  # fail-soft: a base lookup must never block a save.
            # Report (never silent) — matches the repo's fail-open-with-report norm so a misconfig
            # objective store surfaces, while the save still proceeds (falls through to config).
            print(
                f"perk plan save: objective base lookup skipped (non-fatal): {exc}",
                file=sys.stderr,
            )
            state = None
        if state is not None:
            obj_base = state.header.get("base")
            if isinstance(obj_base, str) and obj_base.strip():
                return obj_base.strip()
    return load_config(repo_root).workflow_base


def _plan_save_impl(
    *,
    repo_root: Path,
    plan_file: Path | None,
    run_id: str | None,
    title: str | None,
    objective_id: str | None = None,
    node_id: str | None = None,
    consumed_learn: tuple[str, ...] = (),
    adopt_from: str | None = None,
    dry_run: bool,
) -> PlanSaveResult:
    """Pure-ish logic (no Click). Composes the header/body and performs the GitHub write."""
    # In-place adoption is NOT objective-linked: the node-unification path is the in-place
    # writer for objective nodes — refuse to mix two in-place semantics.
    if adopt_from is not None:
        adopt_from = adopt_from.strip().lstrip("#").strip() or None
    if adopt_from is not None and (objective_id is not None or node_id is not None):
        raise UserFacingCliError(
            "--adopt-from is mutually exclusive with --objective-id/--node-id (adoption is not "
            "objective-linked; objective nodes are unified in place via their node-issue).",
            error_type="invalid_input",
        )
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
    backend = resolve.resolve_issue_backend(repo_root)
    store = resolve.resolve_objective_store(repo_root)

    # Resolve + pin the plan's base: the objective's own base wins (it is the source of
    # truth for its node plans), else the repo's `[workflow] base`, else None (submit/start-point
    # fall back to the GitHub default branch). Pinned once here into BOTH the plan-header and the
    # cache.plan-ref so a later config change never retargets this plan.
    resolved_base = _resolve_plan_base(repo_root, store, objective_id)
    header = plan.PlanHeader(
        run_id=run_id or "",
        created=plan.now_iso(),
        objective_id=objective_id,
        consumed_learn=consumed_learn,
        base=resolved_base,
        # Adoption provenance: self-referential by construction (the plan is stamped INTO
        # the source issue); its presence marks the issue body/title as verbatim human content.
        adopted_from=adopt_from,
    )
    issue_body = plan.render_metadata_block(plan.PLAN_HEADER_KEY, header.to_data())
    body_comment = plan.render_plan_body(plan_markdown)

    # Unification: an objective-linked REAL save writes the plan INTO the existing
    # node-issue (project-backed stores) instead of minting a second perk:plan issue. The store's
    # `save_node_plan` returns the node-issue ref for a unifying store, and `None` otherwise (and
    # on a dry run — resolving the node-issue needs a network read). `None` means "take the
    # standalone path, UNCHANGED below".
    unified_ref = None
    if not dry_run and objective_id and node_id:
        unified_ref = store.save_node_plan(
            objective_id=str(objective_id).lstrip("#"),
            node_id=node_id,
            header_fields=header.to_data(),
            plan_markdown=plan_markdown,
        )

    # In-place adoption: stamp the authored plan ADDITIVELY into the existing (non-perk)
    # issue — an in-place write into an existing object, so no second `perk:plan` issue is minted.
    # `dry_run` falls through to the standalone compose-preview (byte-stable existing behavior).
    adopt_ref = None
    if not dry_run and adopt_from:
        adopt_ref = backend.adopt_issue_as_plan(
            issue_id=adopt_from,
            header_fields=header.to_data(),
            plan_markdown=plan_markdown,
            callout=plan.plan_callout(adopt_from),
            command=f"perk impl {adopt_from}",
        )

    if adopt_ref is not None:
        # The human issue IS the plan issue now (an in-place additive stamp, so `updated=True`); it
        # carries the `perk:plan` label, added (never replacing) alongside the human's own labels.
        issue = issue_backend.IssueRef(id=adopt_ref.id, url=adopt_ref.url, existed=True)
        updated = True
        labels: tuple[str, ...] = (plan.PLAN_LABEL,)
    elif unified_ref is not None:
        # Project-backed: the node-issue IS the plan issue (an in-place write into an existing
        # issue, so `updated=True`); it carries no perk:plan label (discovered by project
        # membership + the objective-node block).
        issue = issue_backend.IssueRef(id=unified_ref.id, url=unified_ref.url, existed=True)
        updated = True
        labels: tuple[str, ...] = ()
    else:
        backend.ensure_label(
            plan.PLAN_LABEL,
            color=plan.PLAN_LABEL_COLOR,
            description=plan.PLAN_LABEL_DESCRIPTION,
            dry_run=dry_run,
        )
        issue = backend.create_plan_issue(
            title=resolved_title,
            body=issue_body,
            run_id=run_id,
            dry_run=dry_run,
        )
        # `create_plan_issue` is idempotent on run_id: a fresh create returns existed=False, a
        # re-save returns the existing issue. On a fresh create we post the plan-body comment; on a
        # re-save we upsert the existing issue in place (PATCH the plan-body comment + the title). A
        # dry run shells nothing. The anti-duplicate guarantee is preserved — never a second issue
        # per run_id.
        updated = False
        if not dry_run:
            if issue.existed:
                backend.update_plan_issue(
                    issue_id=issue.id,
                    title=resolved_title,
                    body_comment=body_comment,
                )
                # `update_plan_issue` rewrites only the plan-body comment + the issue title; it
                # never touches the `plan-header` block. So the planning-time header fields
                # (`objective_id`, `consumed_learn`) that are only written on a fresh create would
                # be silently dropped on any re-save — leaving the canonical header (which
                # `reconstruct_plan_ref` / on-land consume read from) stale. Merge them back via the
                # `update_plan_header` gateway, which is additive (omitted fields are left intact,
                # never clobbering an existing link or the submit-populated branch/pr/
                # lifecycle_stage). A failure surfaces (raises IssueBackendError → `github_error`)
                # — this is the canonical save, where a silent drop is the bug.
                header_fields: dict[str, object] = {}
                if objective_id is not None:
                    header_fields["objective_id"] = objective_id
                if consumed_learn:
                    header_fields["consumed_learn"] = list(consumed_learn)
                if resolved_base is not None:
                    header_fields["base"] = resolved_base
                if header_fields:
                    backend.update_plan_header(issue_id=issue.id, fields=header_fields)
                updated = True
            else:
                backend.add_issue_comment(issue_id=issue.id, body=body_comment, dry_run=dry_run)
                # The plan issue body holds only the hidden `plan-header` block, so prepend a
                # visible, copyable `perk impl <id>` callout as the first thing a human sees. The
                # server-assigned id is only known here (post-create). Idempotent on the command
                # string and structurally above the header block, so the submit-time
                # `update_plan_header` rewrite preserves it.
                backend.prepend_plan_callout(
                    issue_id=issue.id,
                    callout=plan.plan_callout(issue.id),
                    command=f"perk impl {issue.id}",
                )
        labels = (plan.PLAN_LABEL,)

    plan_ref = plan.PlanRef(
        provider=backend.backend_id,
        pr_id=issue.id,
        url=issue.url,
        labels=labels,
        objective_id=objective_id,
        consumed_learn=consumed_learn,
        base=resolved_base,
    )
    # Persist the ref as the cache.plan-ref pointer: the next session's
    # reconciliation links it, and `implement` reads it. A dry run writes nothing.
    if not dry_run:
        cache.write_plan_ref(repo_root, plan_ref.to_data())

    # Commit the objective-node claim atomically: set the node→plan backlink AND advance
    # `planning → in_progress` in a single write. Fail-loud, non-fatal, idempotent on re-save
    # (the plan already exists — never raise here; mirror pr_land._reconcile_objective_on_land).
    objective_node_result: dict[str, object] | None = None
    if not dry_run and objective_id and node_id:
        try:
            store.update_objective_node(
                objective_id=str(objective_id).lstrip("#"),
                node_id=node_id,
                status=objective.NodeStatus.IN_PROGRESS,
                pr=f"#{issue.id}",
            )
            objective_node_result = {
                "linked": True,
                "node": node_id,
                "status": "in_progress",
                "error": None,
            }
        except Exception as exc:  # fail-loud, non-fatal: the plan already exists.
            print(
                f"perk plan save: objective node link skipped (non-fatal): {exc}",
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
            # Opaque string id at every machine boundary (contracts §8.21).
            "id": result.issue.id,
            "url": result.issue.url,
            "existed": result.issue.existed,  # warm /plan-save surfaces this in details
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
        + click.style(f"#{result.issue.id}", fg="cyan")
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
