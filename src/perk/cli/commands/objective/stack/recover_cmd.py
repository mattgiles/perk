"""``perk objective stack recover`` — the conclude-only recovery worker (contracts.md §8.51).

The cold surface over ``perk.delivery.recover.recover_operations``: classify every
unresolved stack operation, conclude the one selected target (automatic SYNC/ADOPT
all-after roll-forward; confirmed ``--abandon`` with proof), then sweep orphaned
machine-local sync residue. Retry is never recover's verb — the report's detail routes to
the owning command. ``--dry-run`` reports everything and mutates nothing. No ``--run-id``:
conclude-only recovery needs no run identity. Exit 0 = successful
classification/report/no-op/actions (including declined and ``selection_required``); 1 =
typed refusals + infra failures; 2 = not-a-repo.
"""

import click

from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import ObjectiveStoreError
from perk.boundary import OutputModel
from perk.cli.commands.objective.stack.shared import resolve_objective_id
from perk.cli.commands.objective.stack.status_cmd import ObjectiveOut
from perk.cli.context import require_config, require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.delivery import recover, sync, train, transfer
from perk.delivery.journal import JournalCorruptionError
from perk.delivery.persistence import TrainPersistenceError
from perk.github import GitHubError
from perk.substrate import git
from perk.substrate.output import user_output

# --- the ``--json`` envelope (OutputModel family; declaration order load-bearing) ---


class RecoverOperationOut(OutputModel):
    operation_id: str
    kind: str
    prepared_created: str
    classification: str  # all_before | all_after | mixed | unsupported
    action: str  # reported | rolled_forward | abandoned | declined
    detail: str

    @classmethod
    def from_domain(cls, row: recover.OperationRow) -> "RecoverOperationOut":
        return cls(
            operation_id=row.operation_id,
            kind=row.kind,
            prepared_created=row.prepared_created,
            classification=row.classification,
            action=row.action,
            detail=row.detail,
        )


class SweepFailureOut(OutputModel):
    target: str
    error: str


class ObjectiveStackRecoverOut(OutputModel):
    """The ``perk objective stack recover --json`` envelope (contracts.md §8.51). Under
    ``dry_run`` the swept lists carry the WOULD-BE sweep targets (nothing was deleted)."""

    success: bool
    objective: ObjectiveOut
    dry_run: bool
    selection_required: bool
    operations: tuple[RecoverOperationOut, ...]
    swept_worktrees: tuple[str, ...]
    swept_refs: tuple[str, ...]
    sweep_failures: tuple[SweepFailureOut, ...]
    sweep_skipped: str | None

    @classmethod
    def from_domain(cls, result: recover.RecoverResult) -> "ObjectiveStackRecoverOut":
        return cls(
            success=True,
            objective=ObjectiveOut(
                id=result.objective_id,
                url=result.objective_url,
                redirected_from=result.redirected_from,
            ),
            dry_run=result.dry_run,
            selection_required=result.selection_required,
            operations=tuple(RecoverOperationOut.from_domain(row) for row in result.operations),
            swept_worktrees=result.swept_worktrees,
            swept_refs=result.swept_refs,
            sweep_failures=tuple(
                SweepFailureOut(target=failure.target, error=failure.error)
                for failure in result.sweep_failures
            ),
            sweep_skipped=result.sweep_skipped,
        )


# --- confirmation + rendering (stderr only; --json never contaminates stdout) ---


def _make_approve(*, yes: bool):
    """The abandon confirmation (the sync command's discipline): render exactly what an
    affirmative answer abandons, ``--yes`` auto-approves, non-interactive without ``--yes``
    is the typed ``confirmation_required`` refusal — never a hang, never a silent journal
    write."""

    def approve(preview: recover.AbandonPreview) -> bool:
        user_output(
            f"Abandon operation {preview.operation_id} ({preview.kind}, prepared "
            f"{preview.prepared_created})?"
        )
        user_output(f"  {preview.detail}")
        if yes:
            return True
        stdin = click.get_text_stream("stdin")
        if not stdin.isatty():
            raise UserFacingCliError(
                "Abandoning an unresolved operation needs confirmation — rerun "
                "interactively or pass --yes.",
                error_type="confirmation_required",
            )
        return click.confirm("Abandon it?", err=True)

    return approve


def _render_result(result: recover.RecoverResult) -> None:
    if result.dry_run:
        user_output("dry run: nothing was concluded, journaled, or swept")
    if not result.operations:
        user_output("no unresolved operations")
    for row in result.operations:
        user_output(
            f"  {row.operation_id} ({row.kind}, prepared {row.prepared_created}): "
            f"{row.classification} → {row.action}"
        )
        user_output(f"    {row.detail}")
    if result.selection_required:
        user_output(
            "several operations are unresolved — rerun with `--operation ULID` to act on one"
        )
    if result.sweep_skipped is not None:
        user_output(f"sweep skipped: {result.sweep_skipped}")
    elif result.swept_worktrees or result.swept_refs:
        verb = "would sweep" if result.dry_run else "swept"
        user_output(
            f"{verb} {len(result.swept_worktrees)} orphaned worktree(s) and "
            f"{len(result.swept_refs)} orphaned ref(s)"
        )
    for failure in result.sweep_failures:
        user_output(f"  sweep failure: {failure.target} ({failure.error})")


@click.command("recover")
@click.argument("objective", required=False)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="Classify and report only — no roll-forward, no abandon, no sweep.",
)
@click.option(
    "--operation",
    "operation_id",
    default=None,
    metavar="ULID",
    help="The action target when several operations are unresolved.",
)
@click.option(
    "--abandon",
    "abandon",
    is_flag=True,
    help="Abandon the target operation with proof (requires an all-before classification).",
)
@click.option("--yes", "yes", is_flag=True, help="Approve the rendered abandon without asking.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def recover_stack(
    ctx: click.Context,
    *,
    objective: str | None,
    dry_run: bool,
    operation_id: str | None,
    abandon: bool,
    yes: bool,
    as_json: bool,
) -> None:
    """Conclude unresolved stack operations and sweep orphaned sync residue.

    Classifies every unresolved operation against fresh authority (SYNC/ADOPT through the
    sync-record core; PUBLISH through the publish proof; TRANSFER through the transfer
    manifest + run_id successor lookup; LAND report-only), rolls the target forward
    automatically when everything verified at the prepared after state, abandons a proven
    all-before target under --abandon (confirmed), then sweeps orphaned sync worktrees/refs.
    Retries route to the owning command (`stack sync`, `/submit`).
    """
    if dry_run and abandon:
        fail(
            ctx,
            as_json=as_json,
            error_type="invalid_input",
            message="--dry-run and --abandon are mutually exclusive — preview first, then abandon.",
        )
        return
    try:
        repo_root = require_repo(ctx)
        config = require_config(ctx)
        objective_id = resolve_objective_id(repo_root, objective)
        result = recover.recover_operations(
            repo_root,
            objective_id=objective_id,
            worktree_root=config.worktree_root,
            dry_run=dry_run,
            abandon=abandon,
            operation_id=operation_id,
            approve=_make_approve(yes=yes),
        )
    except (recover.RecoverError, sync.SyncError, transfer.TransferError) as exc:
        # RecoverError is §8.51's vocabulary; the roll-forward tail's SyncError arms
        # (sync_drift / pr_drift / postcondition_unverified / …) pass through under §8.49's,
        # and the TRANSFER arm's TransferError arms under §8.53's.
        fail(ctx, as_json=as_json, error_type=exc.error_type, message=str(exc))
        return
    except train.TrainReconstructionError as exc:
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
    payload = ObjectiveStackRecoverOut.from_domain(result).model_dump(mode="json")
    emit(as_json=as_json, payload=payload, render=lambda: _render_result(result))
