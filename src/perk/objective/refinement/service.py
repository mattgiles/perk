"""Objective-node refinement — the backend-facing read / select / save flow (contracts.md §8.67).

Three callables over the two tier CONTRACTS (``ObjectiveStore`` for the target snapshot,
``IssueBackend`` for the carrier comments) — never a concrete implementation:

- :func:`read_node_refinement` — the current target plus its valid saved record (all statuses
  readable; a changed source is advisory, never absence);
- :func:`select_refinement_target` — an explicit eligible node (re-refinement allowed) or the
  first eligible node with no valid record, in natural order and ignoring dependency readiness;
- :func:`save_node_refinement` — validate, re-read the target, check identity → eligibility →
  source, establish the record's validity, then ONE guarded upsert whose verified comment is the
  returned record (no second read).

Every refusal is a :class:`RefinementError` with a code from the fixed mapping table; original
causes are chained, comment ids and the attempted-write flag pass through. Only the refinement's
own comment is ever written — no claim, plan, description, attachment, status, relation,
milestone, objective-lifecycle, or delivery mutation, and never an automatic retry.
"""

from perk.backends.issue_backend import (
    IssueBackend,
    IssueBackendError,
    MarkedCommentError,
    MarkedCommentErrorCode,
)
from perk.backends.objective_store import (
    ObjectiveStore,
    ObjectiveStoreError,
    RefinementTargetReadCode,
    RefinementTargetReadError,
)
from perk.objective.graph import node_sort_key
from perk.objective.refinement import codec
from perk.objective.refinement.models import (
    REFINABLE_STATUSES,
    RefinementError,
    RefinementErrorCode,
    RefinementObjectiveSnapshot,
    RefinementRead,
    RefinementSaveRequest,
    RefinementTarget,
    SavedRefinement,
)

_TARGET_READ_CODES: dict[RefinementTargetReadCode, RefinementErrorCode] = {
    "unsupported_backend": RefinementErrorCode.UNSUPPORTED_BACKEND,
    "malformed_target": RefinementErrorCode.MALFORMED_TARGET,
    "ambiguous_target": RefinementErrorCode.AMBIGUOUS_TARGET,
}

_GUARDED_UPSERT_CODES: dict[MarkedCommentErrorCode, RefinementErrorCode] = {
    "unsupported_backend": RefinementErrorCode.UNSUPPORTED_BACKEND,
    "invalid_input": RefinementErrorCode.INVALID_INPUT,
    "malformed_comment": RefinementErrorCode.MALFORMED_REFINEMENT,
    "ambiguous_comment": RefinementErrorCode.AMBIGUOUS_REFINEMENT,
    "stale_comment": RefinementErrorCode.STALE_REFINEMENT,
    "backend_error": RefinementErrorCode.BACKEND_ERROR,
    "write_unverified": RefinementErrorCode.WRITE_UNVERIFIED,
}


def _snapshot(
    store: ObjectiveStore, issues: IssueBackend, *, objective_id: str
) -> RefinementObjectiveSnapshot:
    """The support decision + the fresh target read, with the store's typed refusals mapped."""
    if store.backend_id != issues.backend_id:
        raise RefinementError(
            RefinementErrorCode.INVALID_INPUT,
            f"objective store backend {store.backend_id!r} does not match issue backend "
            f"{issues.backend_id!r}",
        )
    try:
        snapshot = store.read_node_refinement_targets(objective_id=objective_id)
    except RefinementTargetReadError as exc:
        raise RefinementError(_TARGET_READ_CODES[exc.code], str(exc)) from exc
    except ObjectiveStoreError as exc:
        raise RefinementError(RefinementErrorCode.BACKEND_ERROR, str(exc)) from exc
    if snapshot is None:
        raise RefinementError(
            RefinementErrorCode.OBJECTIVE_NOT_FOUND, f"objective {objective_id!r} not found"
        )
    return snapshot


def _target(snapshot: RefinementObjectiveSnapshot, node_id: str) -> RefinementTarget:
    for target in snapshot.targets:
        if target.identity.node_id == node_id:
            return target
    raise RefinementError(
        RefinementErrorCode.NODE_NOT_FOUND,
        f"objective {snapshot.objective_id!r} has no node {node_id!r}",
    )


def _discover(issues: IssueBackend, target: RefinementTarget) -> RefinementRead:
    """The one comment-discovery implementation: all carrier comments, then the codec's exact
    target discovery (ambiguity from marker headers first, malformed next, foreign ignored)."""
    try:
        comments = issues.read_comments(issue_id=target.identity.carrier_id)
    except IssueBackendError as exc:
        raise RefinementError(
            RefinementErrorCode.BACKEND_ERROR,
            f"could not read comments on {target.carrier_identifier}: {exc}",
        ) from exc
    saved = codec.find_target_refinement(comments, target.identity)
    return RefinementRead(target=target, saved=saved)


def _ineligible(target: RefinementTarget) -> RefinementError:
    reasons: list[str] = []
    if target.status not in REFINABLE_STATUSES:
        reasons.append(f"status {target.status.value}")
    if target.plan_ref is not None:
        reasons.append(f"plan backlink {target.plan_ref}")
    if target.has_plan_metadata:
        reasons.append("plan metadata present")
    return RefinementError(
        RefinementErrorCode.NODE_INELIGIBLE,
        f"node {target.identity.node_id!r} is not refinable ({', '.join(reasons)})",
    )


def read_node_refinement(
    store: ObjectiveStore,
    issues: IssueBackend,
    *,
    objective_id: str,
    node_id: str,
) -> RefinementRead:
    """Read one node's refinement: the current target (any status) plus its valid saved record,
    or ``saved=None`` for genuine absence. A changed source reads as ``source_changed=True`` —
    advisory only, never absence or a requeue."""
    snapshot = _snapshot(store, issues, objective_id=objective_id)
    return _discover(issues, _target(snapshot, node_id))


def select_refinement_target(
    store: ObjectiveStore,
    issues: IssueBackend,
    *,
    objective_id: str,
    node_id: str | None = None,
) -> RefinementRead:
    """Select the refinement target. Explicit ``node_id``: the node must be eligible; its prior
    valid record (if any) is returned so it can be re-refined. Default: walk the snapshot in
    natural order ignoring dependency readiness, skip ineligible nodes and nodes with a valid
    record, return the first eligible absence; a malformed / ambiguous / unreadable record on an
    eligible node stops the walk. An empty or exhausted population is ``no_unrefined_node``. No
    claim, no delivery call."""
    snapshot = _snapshot(store, issues, objective_id=objective_id)
    if node_id is not None:
        target = _target(snapshot, node_id)
        if not target.eligible:
            raise _ineligible(target)
        return _discover(issues, target)
    for target in sorted(snapshot.targets, key=lambda t: node_sort_key(t.identity.node_id)):
        if not target.eligible:
            continue
        read = _discover(issues, target)
        if read.saved is None:
            return read
    raise RefinementError(
        RefinementErrorCode.NO_UNREFINED_NODE,
        f"objective {snapshot.objective_id!r} has no eligible unrefined node",
    )


def save_node_refinement(
    store: ObjectiveStore,
    issues: IssueBackend,
    *,
    request: RefinementSaveRequest,
) -> SavedRefinement:
    """Persist a refinement through ONE guarded comment upsert and return the record as verified
    by the backend's own read-back (no second read here).

    Precedence: request validation → fresh snapshot → node lookup → exact identity → current
    eligibility → source digest → current record validity/uniqueness → the guarded upsert
    (which owns backend-rendered convergence and the expected-content comparison, using the
    request's ORIGINAL expectation). The returned ``verified_comment`` is decoded through the
    same codec; a missing or undecodable verified result is ``write_unverified``. Nothing is
    refreshed, rebuilt, followed, or rebound implicitly, and a node that became ineligible
    refuses even an otherwise idempotent save."""
    codec.validate_save_request(request)
    document = request.document
    if document.identity.backend != store.backend_id:
        raise RefinementError(
            RefinementErrorCode.INVALID_INPUT,
            f"request identity backend {document.identity.backend!r} does not match the store "
            f"backend {store.backend_id!r}",
        )
    snapshot = _snapshot(store, issues, objective_id=document.identity.objective_id)
    target = _target(snapshot, document.identity.node_id)
    if target.identity != document.identity:
        raise RefinementError(
            RefinementErrorCode.STALE_SOURCE,
            f"node {document.identity.node_id!r} identity changed since the refinement was "
            "authored (objective run or carrier differs)",
        )
    if not target.eligible:
        raise _ineligible(target)
    if target.source_digest != document.source_digest:
        raise RefinementError(
            RefinementErrorCode.STALE_SOURCE,
            f"node {document.identity.node_id!r} source changed since the refinement was "
            "authored (re-read the target and re-refine)",
        )
    # Establish the current record's validity/uniqueness (malformed/ambiguous refuse here); the
    # request's expectation is retained verbatim — never refreshed from this read.
    _discover(issues, target)

    marker = codec.html_marker(codec.target_key(document.identity))
    rendered = codec.render_refinement(document)
    try:
        result = issues.upsert_marked_comment(
            issue_id=document.identity.carrier_id,
            marker=marker,
            body=rendered,
            expected=request.expected,
        )
    except MarkedCommentError as exc:
        raise RefinementError(
            _GUARDED_UPSERT_CODES[exc.code],
            str(exc),
            comment_ids=exc.comment_ids,
            write_attempted=exc.write_attempted,
        ) from exc
    except IssueBackendError as exc:
        raise RefinementError(RefinementErrorCode.BACKEND_ERROR, str(exc)) from exc

    verified = result.verified_comment

    def unverified(reason: str) -> RefinementError:
        # A verified-result failure conservatively reports the attempted write.
        return RefinementError(
            RefinementErrorCode.WRITE_UNVERIFIED,
            f"refinement save returned no verifiable record: {reason}",
            comment_ids=(verified.id,) if verified is not None else (),
            write_attempted=True,
        )

    if verified is None:
        raise unverified("the backend returned no verified comment")
    try:
        saved = codec.parse_refinement_comment(verified)
    except RefinementError as exc:
        raise unverified(str(exc)) from exc
    if saved is None:
        raise unverified("the verified comment carries no refinement marker")
    if saved.document.identity != document.identity:
        raise unverified("the verified comment belongs to a different identity")
    return saved
