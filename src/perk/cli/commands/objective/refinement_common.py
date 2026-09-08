"""Shared boundary helpers for the three objective-refinement commands (contracts.md §8.67).

One deliberate error translation for the family (the launcher's ``gather`` and both workers):
refinement/authoring codes pass through unchanged, resolver/store failures are ``backend_error``
(the service's own vocabulary — never the seeded helper's ``github_error``), git probes are
``git_error``, filesystem writes are ``write_failed``. Diagnostic fields (``comment_ids``,
``write_attempted``) ride the ``--json`` envelope's ``extra`` so a caller can read back rather
than blindly retry.
"""

from dataclasses import dataclass

from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import ObjectiveStoreError
from perk.cli.ensure import UserFacingCliError
from perk.objective.refinement.authoring import RefinementAuthoringError, RefinementSaveOutcome
from perk.objective.refinement.models import RefinementError
from perk.substrate.git import GitError


@dataclass(frozen=True)
class RefinementFailure:
    """A typed failure ready for :func:`perk.cli.emit.fail`."""

    error_type: str
    message: str
    extra: dict[str, object]


# The exception family every refinement command boundary catches (one tuple, one translation).
REFINEMENT_FAILURES: tuple[type[Exception], ...] = (
    RefinementError,
    RefinementAuthoringError,
    IssueBackendError,
    ObjectiveStoreError,
    GitError,
    OSError,
)


def translate_failure(exc: Exception) -> RefinementFailure:
    """Map one expected refinement-family exception onto its stable ``error_type`` + extras."""
    if isinstance(exc, RefinementError):
        return RefinementFailure(
            error_type=exc.code.value,
            message=str(exc),
            extra={"comment_ids": list(exc.comment_ids), "write_attempted": exc.write_attempted},
        )
    if isinstance(exc, RefinementAuthoringError):
        return RefinementFailure(error_type=exc.code.value, message=str(exc), extra={})
    if isinstance(exc, (IssueBackendError, ObjectiveStoreError)):
        return RefinementFailure(error_type="backend_error", message=str(exc), extra={})
    if isinstance(exc, GitError):
        return RefinementFailure(error_type="git_error", message=str(exc), extra={})
    return RefinementFailure(error_type="write_failed", message=str(exc), extra={})


def as_cli_error(exc: Exception) -> UserFacingCliError:
    """The launcher-side twin: the seeded-door boundary types only ``UserFacingCliError``, so the
    gather closure re-raises through this (comment ids folded into the message — the launcher's
    envelope has no extras slot)."""
    failure = translate_failure(exc)
    message = failure.message
    ids = failure.extra.get("comment_ids")
    if isinstance(ids, list) and ids:
        message = f"{message} (comment ids: {', '.join(str(i) for i in ids)})"
    return UserFacingCliError(message, error_type=failure.error_type)


def saved_payload(outcome: RefinementSaveOutcome) -> dict[str, object]:
    """The verified save facts every save surface reports (``--json``): the comment id + carrier
    URL that make the receipt, the objective/node identity, the stored body digest, and the
    backend's native saved time."""
    saved = outcome.saved
    identity = saved.document.identity
    return {
        "success": True,
        "error_type": None,
        "comment_id": saved.comment.id,
        "carrier_url": outcome.context.target.carrier_url,
        "carrier_identifier": outcome.context.target.carrier_identifier,
        "objective_id": identity.objective_id,
        "objective_run_id": identity.objective_run_id,
        "node_id": identity.node_id,
        "body_digest": saved.body_digest,
        "source_digest": saved.document.source_digest,
        "saved_at": saved.saved_at,
        "authored_at": saved.document.provenance.authored_at,
    }
