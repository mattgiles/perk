"""``perk objective stack sync`` — the published-suffix synchronization worker
(contracts.md §8.49).

The cold surface over ``perk.delivery.sync``: resolve the objective + run id, wire the
fail-closed remote-writer probe, render the cascade (or abort preview) for confirmation on
stderr (``--yes`` auto-approves; non-interactive without ``--yes`` is a typed refusal —
never a hang, never a silent push), and report the result-arm envelope. The control flags:
``--dry-run`` (side-effect-free preview; no confirmation needed), ``--adopt NODE`` (accept
an out-of-band remote edit as a cascade source), ``--continue``/``--abort`` (resume or
discard a retained conflict stop).
"""

import click

from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import ObjectiveStoreError
from perk.boundary import OutputModel
from perk.cli.commands.objective.stack.shared import resolve_objective_id, resolve_run_id
from perk.cli.commands.objective.stack.status_cmd import ObjectiveOut
from perk.cli.context import require_config, require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.delivery import DeliveryError, SyncRequest, SyncResult, resolve_delivery
from perk.substrate.output import user_output

# --- the ``--json`` envelope (OutputModel family; declaration order load-bearing) ---


class SyncedLayerOut(OutputModel):
    node_id: str
    plan_id: str
    branch: str
    pr_number: int
    before_sha: str
    after_sha: str

    @classmethod
    def from_domain(cls, layer: SyncResult.Layer) -> "SyncedLayerOut":
        return cls(
            node_id=layer.node_id,
            plan_id=layer.plan_id,
            branch=layer.branch,
            pr_number=layer.pr_number,
            before_sha=layer.before_sha,
            after_sha=layer.after_sha,
        )


class ObjectiveStackSyncOut(OutputModel):
    """The ``perk objective stack sync --json`` envelope (the §8.49 result-arm table).
    ``dry_run`` / ``adopted_node`` / ``continued`` / ``aborted`` are the additive
    control-surface arms (declared last, order load-bearing)."""

    success: bool
    objective: ObjectiveOut
    operation_id: str | None
    abandoned_operation_id: str | None
    no_op: bool
    declined: bool
    resumed: bool
    base_cascaded: bool
    base_advanced: bool
    affected: tuple[SyncedLayerOut, ...]
    notes: tuple[str, ...]
    dry_run: bool
    adopted_node: str | None
    continued: bool
    aborted: bool

    @classmethod
    def from_domain(cls, result: SyncResult) -> "ObjectiveStackSyncOut":
        return cls(
            success=True,
            objective=ObjectiveOut(
                id=result.objective_id,
                url=result.objective_url,
                redirected_from=result.redirected_from,
            ),
            operation_id=result.operation_id,
            abandoned_operation_id=result.abandoned_operation_id,
            no_op=result.no_op,
            declined=result.declined,
            resumed=result.resumed,
            base_cascaded=result.base_cascaded,
            base_advanced=result.base_advanced,
            affected=tuple(SyncedLayerOut.from_domain(layer) for layer in result.affected),
            notes=result.notes,
            dry_run=result.dry_run,
            adopted_node=result.adopted_node,
            continued=result.continued,
            aborted=result.aborted,
        )


# --- confirmation + rendering (stderr only; interactive --json never contaminates stdout) ---


def _render_cascade(cascade: SyncResult.Cascade) -> None:
    user_output(
        f"Objective #{cascade.objective_id}: synchronize {len(cascade.layers)} published layer(s)"
    )
    if cascade.include_base:
        user_output(f"  base {cascade.base_branch}: {cascade.base_before} → {cascade.base_after}")
    for layer in cascade.layers:
        user_output(
            f"  {layer.node_id} {layer.branch} (pr #{layer.pr_number}): "
            f"{layer.before_sha} → {layer.after_sha}"
        )


def _make_approve(*, yes: bool):
    """The approval callback: render the cascade to stderr, then confirm (also on stderr).

    ``--yes`` auto-approves (still rendering what it approved); a non-interactive session
    without ``--yes`` raises the typed ``confirmation_required`` refusal BEFORE any prompt —
    never a hang, never a silent push.
    """

    def approve(cascade: SyncResult.Cascade) -> bool:
        _render_cascade(cascade)
        if yes:
            return True
        stdin = click.get_text_stream("stdin")
        if not stdin.isatty():
            raise UserFacingCliError(
                "This cascade rewrites published branches and needs confirmation — rerun "
                "interactively or pass --yes.",
                error_type="confirmation_required",
            )
        return click.confirm("Push this cascade?", err=True)

    return approve


def _make_abort_approve(*, yes: bool):
    """The abort confirmation: render exactly what an affirmative answer discards, then
    confirm on stderr (the ``_make_approve`` discipline: ``--yes`` auto-approves,
    non-interactive without ``--yes`` is the typed ``confirmation_required`` refusal)."""

    def approve(preview: SyncResult.AbortPreview) -> bool:
        if not preview.parseable:
            user_output(f"Discard the UNPARSEABLE continuation manifest {preview.manifest_path}")
            user_output("  (any retained residue is left for `perk objective stack recover`)")
        elif not preview.contained:
            user_output(
                f"Discard the continuation manifest {preview.manifest_path} — its named "
                "targets failed containment validation, so ONLY the manifest file is deleted"
            )
        else:
            user_output(
                f"Discard operation {preview.operation_id}'s retained conflict state "
                f"(stopped on node {preview.conflict_node_id}):"
            )
            user_output(f"  worktree {preview.worktree_path}")
            user_output(f"  manifest {preview.manifest_path}")
        if yes:
            return True
        stdin = click.get_text_stream("stdin")
        if not stdin.isatty():
            raise UserFacingCliError(
                "Discarding retained conflict state needs confirmation — rerun "
                "interactively or pass --yes.",
                error_type="confirmation_required",
            )
        return click.confirm("Discard it?", err=True)

    return approve


def _render_result(result: SyncResult, *, mode: str) -> None:
    for note in result.notes:
        user_output(click.style(f"note: {note}", dim=True))
    if result.aborted:
        user_output("retained continuation discarded")
        return
    if result.declined:
        if mode == "abort":
            user_output("abort declined; everything stays retained")
        elif mode == "continue":
            user_output(
                "continuation declined; everything stays retained (re-enter with "
                "`perk objective stack sync --continue`)"
            )
        else:
            user_output("cascade declined; nothing pushed")
        return
    if result.dry_run:
        if result.no_op:
            user_output("dry run: nothing to synchronize")
            return
        verb = "adopt + cascade" if result.adopted_node is not None else "cascade"
        user_output(f"dry run: a real sync would {verb} {len(result.affected)} layer(s)")
        for layer in result.affected:
            user_output(
                f"  {layer.node_id} {layer.branch} (pr #{layer.pr_number}): "
                f"{layer.before_sha} → {layer.after_sha}"
            )
        user_output("nothing was journaled, pushed, or retained")
        return
    if result.no_op:
        user_output("nothing to synchronize")
        if result.base_advanced:
            user_output(
                "note: the objective base has advanced — cascade with "
                "`perk objective stack sync --base`"
            )
        return
    verb = "resumed" if result.resumed else ("continued" if result.continued else "synchronized")
    user_output(f"{verb} {len(result.affected)} layer(s) (operation {result.operation_id})")
    if result.adopted_node is not None:
        user_output(f"  adopted the out-of-band remote head of layer {result.adopted_node}")
    if result.abandoned_operation_id is not None:
        user_output(
            f"  (abandoned the unresolved operation {result.abandoned_operation_id} "
            "with proof first)"
        )
    for layer in result.affected:
        user_output(
            f"  {layer.node_id} {layer.branch} (pr #{layer.pr_number}): "
            f"{layer.before_sha} → {layer.after_sha}"
        )
    user_output("checkpoints updated; local branches are left untouched (deliberately stale)")


def _validate_flag_matrix(
    *, include_base: bool, dry_run: bool, adopt: str | None, continue_: bool, abort: bool
) -> str:
    """The §8.49 control-flag matrix, validated FIRST as typed ``invalid_input``:
    ``--continue``/``--abort`` are mutually exclusive with each other and with every
    cascade flag; ``--adopt`` + ``--base`` is refused; ``--adopt`` + ``--dry-run`` and
    ``--base`` + ``--dry-run`` compose. Returns the routing mode."""
    if continue_ and abort:
        raise UserFacingCliError(
            "--continue and --abort are mutually exclusive.", error_type="invalid_input"
        )
    for flag_name, active in (("--continue", continue_), ("--abort", abort)):
        if active and (include_base or dry_run or adopt is not None):
            raise UserFacingCliError(
                f"{flag_name} takes no cascade flags — drop --base/--adopt/--dry-run.",
                error_type="invalid_input",
            )
    if adopt is not None and include_base:
        raise UserFacingCliError(
            "--adopt and --base are mutually exclusive — adopt the layer first, then rerun "
            "with --base.",
            error_type="invalid_input",
        )
    if continue_:
        return "continue"
    if abort:
        return "abort"
    return "sync"


@click.command("sync")
@click.argument("objective", required=False)
@click.option(
    "--base",
    "include_base",
    is_flag=True,
    help="Re-anchor the whole published train onto the advanced objective base.",
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="Preview the cascade without journaling, pushing, or retaining anything.",
)
@click.option(
    "--adopt",
    "adopt",
    default=None,
    metavar="NODE",
    help="Adopt NODE's out-of-band remote edit as the cascade source.",
)
@click.option(
    "--continue",
    "continue_",
    is_flag=True,
    help="Resume the retained conflict stop (after `git rebase --continue` in its worktree).",
)
@click.option(
    "--abort",
    "abort",
    is_flag=True,
    help="Discard the retained conflict stop (confirmed; deletes the retained residue).",
)
@click.option("--run-id", "run_id", default=None, help="This operation's perk run id.")
@click.option("--yes", "yes", is_flag=True, help="Approve the rendered cascade without asking.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def sync_stack(
    ctx: click.Context,
    *,
    objective: str | None,
    include_base: bool,
    dry_run: bool,
    adopt: str | None,
    continue_: bool,
    abort: bool,
    run_id: str | None,
    yes: bool,
    as_json: bool,
) -> None:
    """Synchronize an objective's published suffix (the transactional cascade).

    Rewrites the published stacked branches from the lowest changed layer (or the base, with
    --base) upward: candidates are computed by rebase in an isolated worktree, confirmed as
    one rendered cascade, journaled, pushed as ONE atomic leased multi-ref push, verified,
    and checkpointed. --dry-run previews (side-effect-free); --adopt NODE accepts an
    out-of-band remote edit; --continue/--abort resume or discard a retained conflict stop.
    Exit 0 = success (incl. no-op and declined), 1 = typed failures, 2 = not-a-repo.
    """
    mode = "sync"
    try:
        mode = _validate_flag_matrix(
            include_base=include_base,
            dry_run=dry_run,
            adopt=adopt,
            continue_=continue_,
            abort=abort,
        )
        repo_root = require_repo(ctx)
        require_config(ctx)
        objective_id = resolve_objective_id(repo_root, objective)
        delivery = resolve_delivery(repo_root)
        if mode == "continue":
            # --run-id is deliberately not consulted: a continue journals under the
            # MANIFEST's captured run identity.
            request = SyncRequest(mode="continue", objective_id=objective_id)
            consent = _make_approve(yes=yes)
        elif mode == "abort":
            request = SyncRequest(mode="abort", objective_id=objective_id)
            consent = _make_abort_approve(yes=yes)
        else:
            resolved_run_id = resolve_run_id(repo_root, objective_id, run_id)
            request = SyncRequest(
                mode="cascade",
                objective_id=objective_id,
                run_id=resolved_run_id,
                include_base=include_base,
                dry_run=dry_run,
                adopt_node=adopt,
            )
            consent = None if dry_run else _make_approve(yes=yes)
        result = delivery.sync(request, consent=consent)
    except DeliveryError as exc:
        fail(ctx, as_json=as_json, error_type=exc.error_type, message=str(exc))
        return
    except (IssueBackendError, ObjectiveStoreError) as exc:
        fail(ctx, as_json=as_json, error_type="github_error", message=str(exc))
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return
    payload = ObjectiveStackSyncOut.from_domain(result).model_dump(mode="json")
    emit(as_json=as_json, payload=payload, render=lambda: _render_result(result, mode=mode))
