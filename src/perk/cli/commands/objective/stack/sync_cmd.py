"""``perk objective stack sync`` — the published-suffix synchronization worker
(contracts.md §8.49).

The minimal cold surface over ``perk.delivery.sync.synchronize_train``: resolve the
objective + run id, wire the fail-closed remote-writer probe, render the cascade for
confirmation on stderr (``--yes`` auto-approves; non-interactive without ``--yes`` is a typed
refusal — never a hang, never a silent push), and report the result-arm envelope.
Deliberately absent (the recovery node's surface): ``--adopt``, ``--dry-run``,
``--continue``/``--abort``.
"""

from collections.abc import Sequence
from pathlib import Path

import click

from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import ObjectiveStoreError
from perk.backends.resolve import resolve_objective_store
from perk.boundary import OutputModel
from perk.cli.commands.objective.stack.status_cmd import ObjectiveOut, _resolve_objective_id
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
    """The ``perk objective stack sync --json`` envelope (the §8.49 result-arm table)."""

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


def _render_result(result: sync.SyncResult) -> None:
    if result.declined:
        user_output("cascade declined; nothing pushed")
        return
    if result.no_op:
        user_output("nothing to synchronize")
        if result.base_advanced:
            user_output(
                "note: the objective base has advanced — cascade with "
                "`perk objective stack sync --base`"
            )
        return
    verb = "resumed" if result.resumed else "synchronized"
    user_output(f"{verb} {len(result.affected)} layer(s) (operation {result.operation_id})")
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


@click.command("sync")
@click.argument("objective", required=False)
@click.option(
    "--base",
    "include_base",
    is_flag=True,
    help="Re-anchor the whole published train onto the advanced objective base.",
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
    run_id: str | None,
    yes: bool,
    as_json: bool,
) -> None:
    """Synchronize an objective's published suffix (the transactional cascade).

    Rewrites the published stacked branches from the lowest changed layer (or the base, with
    --base) upward: candidates are computed by rebase in an isolated worktree, confirmed as
    one rendered cascade, journaled, pushed as ONE atomic leased multi-ref push, verified,
    and checkpointed. Exit 0 = success (incl. no-op and declined), 1 = typed failures,
    2 = not-a-repo.
    """
    try:
        repo_root = require_repo(ctx)
        config = require_config(ctx)
        objective_id = _resolve_objective_id(repo_root, objective)
        resolved_run_id = _resolve_run_id(repo_root, objective_id, run_id)
        result = sync.synchronize_train(
            repo_root,
            objective_id=objective_id,
            run_id=resolved_run_id,
            include_base=include_base,
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
    emit(as_json=as_json, payload=payload, render=lambda: _render_result(result))
