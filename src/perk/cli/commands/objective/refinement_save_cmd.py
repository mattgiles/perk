"""``perk objective refinement-save --draft-file FILE --run-id RID [--json]`` — the refinement
save worker (contracts.md §8.67).

The ONE persistence path behind both in-session save gestures (the approval-driven save seam and
the human ``/objective-refinement-save`` command): strictly read the transferred draft file,
strictly read the current run's fixed context artifact from the invocation checkout's session
data (containment-checked; no caller-supplied context path, no other-run fallback), require the
matching run id and the EXACT context digest, compose the document from the context's target +
retained provenance and the draft's byte-exact Markdown, and hand the service ONE guarded upsert
under the context's retained expectation. Nothing is reselected, refreshed or recovered from
plan handoff fields.

Direct CLI invocation is a human/extension persistence gesture; metadata is not an approval
credential. Every service refusal keeps its code, ``comment_ids`` and ``write_attempted`` (read
back rather than blindly retry). The worker is backend-neutral: the context's bound backend must
equal the resolved store's — a retained draft whose context names another backend refuses
``invalid_input`` at the service before any read, never a silent save elsewhere.
"""

from pathlib import Path

import click

from perk.cli.commands.objective.refinement_common import (
    REFINEMENT_FAILURES,
    saved_payload,
    translate_failure,
)
from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.objective.refinement import authoring
from perk.substrate.output import user_output


@click.command("refinement-save")
@click.option(
    "--draft-file",
    "draft_file",
    required=True,
    type=click.Path(path_type=Path),
    help="The transferred objective-refinement-draft.json (exact bytes; never a bare Markdown "
    "file).",
)
@click.option(
    "--run-id",
    "run_id_arg",
    required=True,
    help="The current session's run id (the context is read from its session data).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def refinement_save_objective(
    ctx: click.Context, *, draft_file: Path, run_id_arg: str, as_json: bool
) -> None:
    """Save the current run's validated refinement draft as the node's marked comment."""
    try:
        repo_root = require_repo(ctx)
        if not authoring.is_safe_run_id(run_id_arg):
            raise UserFacingCliError(
                f"--run-id {run_id_arg!r} is not a safe run id.", error_type="invalid_input"
            )
        outcome = authoring.save_refinement_draft(
            repo_root, run_id=run_id_arg, draft_file=draft_file
        )
    except REFINEMENT_FAILURES as exc:
        failure = translate_failure(exc)
        fail(
            ctx,
            as_json=as_json,
            error_type=failure.error_type,
            message=failure.message,
            extra=failure.extra,
        )
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    payload = saved_payload(outcome)

    def render_human() -> None:
        user_output(
            f"saved refinement: objective {payload['objective_id']} node {payload['node_id']} "
            f"→ comment {payload['comment_id']} on {payload['carrier_identifier']} "
            f"({payload['carrier_url']}); saved_at={payload['saved_at']}"
        )

    emit(as_json=as_json, payload=payload, render=render_human)
