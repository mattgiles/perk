"""``perk objective refine-context <objective> [--node ID] --run-id RID --json`` — the warm
``/objective-refine`` door's deterministic context worker (contracts.md §8.67).

The SAME fresh preparation and serialization the cold door performs, minus sync, files and
launch: the extension calls it through ``runColdDoor`` and receives the exact ``context_json``
STRING (Python's canonical serialization, final LF included) plus its ``sha256:`` digest inside
the ``--json`` envelope — a string, never a parsed object to re-encode. The extension validates
the digest, decodes for use, and writes the unchanged raw string as the session artifact.

An internal worker, not a browse surface or a model tool: it requires an explicit, safe current
run id (the provenance is bound to it) and emits nothing but the envelope.
"""

import click

from perk.cli import completions
from perk.cli.commands.objective.refinement_common import REFINEMENT_FAILURES, translate_failure
from perk.cli.commands.objective.shared import parse_objective_id
from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.objective.refinement import authoring
from perk.substrate.output import user_output


@click.command("refine-context")
@click.argument("number", shell_complete=completions.complete_objective_id)
@click.option(
    "--node",
    "node_ids",
    multiple=True,
    help="Refine a specific node id (else the first refinable, unrefined future node).",
)
@click.option(
    "--run-id",
    "run_id_arg",
    required=True,
    help="The current session's run id (the context binds to it).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit the context envelope to stdout.")
@click.pass_context
def refine_context_objective(
    ctx: click.Context,
    *,
    number: str,
    node_ids: tuple[str, ...],
    run_id_arg: str,
    as_json: bool,
) -> None:
    """Prepare the refinement grounding context for the current run (internal warm worker)."""
    try:
        repo_root = require_repo(ctx)
        objective_id = parse_objective_id(number)
        if len(node_ids) > 1:
            raise UserFacingCliError(
                "--node may be given at most once.", error_type="invalid_input"
            )
        requested_node = node_ids[0].strip() if node_ids else None
        if requested_node == "":
            raise UserFacingCliError("--node must not be blank.", error_type="invalid_input")
        if not authoring.is_safe_run_id(run_id_arg):
            raise UserFacingCliError(
                f"--run-id {run_id_arg!r} is not a safe run id.", error_type="invalid_input"
            )
        context = authoring.prepare_refinement_context(
            repo_root, objective_id=objective_id, node_id=requested_node, run_id=run_id_arg
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

    prep = authoring.prepared(context)
    target = context.target

    def render_human() -> None:
        user_output(
            f"prepared refinement context: objective {context.objective.id} node "
            f"{target.identity.node_id} ({target.status.value}; "
            f"prior={'yes' if context.prior is not None else 'no'}) "
            f"digest={prep.context_digest}"
        )
        for warning in context.warnings:
            user_output(f"warning: {warning}")

    emit(
        as_json=as_json,
        payload={
            "success": True,
            "error_type": None,
            "context_json": prep.context_json,
            "context_digest": prep.context_digest,
        },
        render=render_human,
    )
