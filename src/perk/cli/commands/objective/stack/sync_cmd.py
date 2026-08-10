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

from collections.abc import Sequence
from pathlib import Path

import click

from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import ObjectiveStoreError
from perk.backends.resolve import resolve_objective_store
from perk.boundary import OutputModel
from perk.cli.commands.objective.stack.shared import resolve_objective_id
from perk.cli.commands.objective.stack.status_cmd import ObjectiveOut
from perk.cli.context import require_config, require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.delivery import sync, train
from perk.delivery.journal import JournalCorruptionError
from perk.delivery.persistence import TrainPersistenceError
from perk.github import GitHubError
from perk.run import discovery
from perk.substrate import git
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
    def from_domain(cls, layer: sync.SyncedLayer) -> "SyncedLayerOut":
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
    dry_run: bool
    adopted_node: str | None
    continued: bool
    aborted: bool

    @classmethod
    def from_domain(cls, result: sync.SyncResult) -> "ObjectiveStackSyncOut":
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
            dry_run=result.dry_run,
            adopted_node=result.adopted_node,
            continued=result.continued,
            aborted=result.aborted,
        )


# --- the production remote-writer probe (the fail-closed §8.49 preflight wiring) ---


class GhaRemoteWriterProbe:
    """The production :class:`~perk.delivery.sync.RemoteWriterProbe`: the server-side
    status-filtered GHA run listing, matched via the managed run-name convention. Any listing
    failure raises the probe's typed error — sync maps it to
    ``writer_observation_unavailable`` (fail closed, never "no active writer")."""

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def active_plan_ids(self, plan_ids: Sequence[str]) -> frozenset[str]:
        try:
            return discovery.active_writer_plan_ids(self._repo_root, list(plan_ids))
        except GitHubError as exc:
            raise sync.WriterObservationError(str(exc)) from exc


# --- confirmation + rendering (stderr only; interactive --json never contaminates stdout) ---


def _render_cascade(cascade: sync.SyncCascade) -> None:
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

    def approve(cascade: sync.SyncCascade) -> bool:
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

    def approve(preview: sync.AbortPreview) -> bool:
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


def _render_result(result: sync.SyncResult, *, mode: str) -> None:
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


def _resolve_run_id(repo_root: Path, objective_id: str, explicit: str | None) -> str:
    """``--run-id`` → the ACTIVE objective header's ``run_id`` (stamped at save); both absent
    is the typed ``invalid_input`` refusal (a defensive arm).

    The header fallback follows ``superseded_by`` forward (the same walk the operation's
    reconstruction performs) so syncing through a superseded objective journals the ACTIVE
    objective's run identity, never the predecessor's.
    """
    if explicit is not None and explicit.strip():
        return explicit.strip()
    store = resolve_objective_store(repo_root)
    state, _redirected_from = train.resolve_active_objective(store, objective_id)
    header_run_id = state.header.get("run_id")
    if isinstance(header_run_id, str) and header_run_id.strip():
        return header_run_id.strip()
    raise UserFacingCliError(
        f"Objective #{state.id} carries no run_id and none was passed — supply --run-id.",
        error_type="invalid_input",
    )


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
        config = require_config(ctx)
        objective_id = resolve_objective_id(repo_root, objective)
        if mode == "continue":
            # --run-id is deliberately not consulted: a continue journals under the
            # MANIFEST's captured run identity.
            result = sync.continue_train_sync(
                repo_root,
                objective_id=objective_id,
                approve=_make_approve(yes=yes),
                remote_writers=GhaRemoteWriterProbe(repo_root),
                worktree_root=config.worktree_root,
            )
        elif mode == "abort":
            result = sync.abort_train_sync(
                repo_root,
                objective_id=objective_id,
                approve=_make_abort_approve(yes=yes),
                worktree_root=config.worktree_root,
            )
        else:
            resolved_run_id = _resolve_run_id(repo_root, objective_id, run_id)
            result = sync.synchronize_train(
                repo_root,
                objective_id=objective_id,
                run_id=resolved_run_id,
                include_base=include_base,
                dry_run=dry_run,
                adopt_node=adopt,
                approve=_make_approve(yes=yes),
                remote_writers=GhaRemoteWriterProbe(repo_root),
                worktree_root=config.worktree_root,
            )
    except sync.SyncError as exc:
        fail(ctx, as_json=as_json, error_type=exc.error_type, message=str(exc))
        return
    except train.TrainReconstructionError as exc:
        # The reconstruction seam's bounded vocabulary passes through verbatim (the
        # stack-status convention): objective_not_found | invalid_delivery_policy |
        # invalid_train | git_error | github_error | supersession_corruption.
        fail(ctx, as_json=as_json, error_type=exc.error_type, message=str(exc))
        return
    except JournalCorruptionError as exc:
        fail(ctx, as_json=as_json, error_type="journal_corruption", message=str(exc))
        return
    except git.GitError as exc:
        fail(ctx, as_json=as_json, error_type="git_error", message=str(exc))
        return
    except (IssueBackendError, ObjectiveStoreError, TrainPersistenceError, GitHubError) as exc:
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
