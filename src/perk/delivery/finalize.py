"""The delivery **finalize** operation — idempotent post-merge land finalization.

The durable post-merge bookkeeping every land path performs per merged plan. **Package-internal**
(no root export): consumers bind it by module path — :meth:`perk.delivery.facade.Delivery.land`'s
private runtime (the incremental plan variant), stacked landing's per-layer finalize
(:mod:`perk.delivery.landing`), and recovery's roll-forward (:mod:`perk.delivery.recover`). The
operation owns exactly **four durable effects**, in order: stamp the canonical `learn_state`
plan-header field (contracts.md §8.36, never-downgrade) → close the plan issue where autoclose
cannot (non-default github base / non-github backends) → reconcile the linked objective
(mark backlinked nodes done, compute completeness, optionally close-on-complete, post the
"plan landed" project update) → consume the plan's `consumed_learn` issues.

The seam contract:

- **Reconstructed inputs only.** Callers pass a narrow :class:`LandedPlan` (plan id +
  objective/learn links) plus the merge-evidence ``pr_base`` — never the worktree
  ``cache.plan-ref``. Nothing here reads worktree state, and ``perk.state`` is never imported
  (the pending-learn marker is worktree-cache state and stays a caller concern).
- **Convergent-final-state idempotency.** Repeated invocations converge and never duplicate or
  regress a durable effect: the `learn_state` stamp never downgrades ``captured``/``skipped``,
  already-terminal nodes are skipped on re-mark, and the close/consume backend calls are
  backend-idempotent (a re-call is success, not a second effect). Individual sub-steps MAY
  re-issue idempotent backend calls — the contract is convergence, not zero repeat calls.
- **Fail-open on expected backend/store failures** (the merge already succeeded; bookkeeping is
  secondary and retryable): failures warn loud-but-non-fatal on stderr and surface in the
  result; a programming error propagates.
- **Activity reporting is a caller concern.** The Linear agent "landed" activity emission is
  worktree-session-scoped (its gate reads `cache.plan-ref` + `agent-session.json`) and not
  idempotent, so it deliberately stays OUT of this seam — each caller owns its own reporting.
- **The aggregate objective close is guardable.** ``close_objective_on_complete=False`` (the
  stacked per-layer callers) still marks nodes, still computes completeness, and still posts the
  honest project update — but never calls ``close_objective``; closing the objective after every
  layer verified is that caller's obligation.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from perk import github, objective, plan
from perk.backends import issue_backend, objective_store, resolve
from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import ObjectiveStoreError
from perk.github import GitHubError
from perk.substrate.output import user_output


@dataclass(frozen=True)
class LandedPlan:
    """The reconstructed just-merged-plan facts finalization consumes — deliberately narrower
    than ``plan.PlanRef`` (no provider/url/labels — nothing here reads them, and stacked
    callers reconstruct from durable authorities, not the worktree cache)."""

    plan_id: str  # opaque plan-issue id (GitHub: "42"; Linear: "ENG-123")
    objective_id: str | None = None
    consumed_learn: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObjectiveLandUpdate:
    """The mechanical auto-on-merge node-done outcome.

    ``objective`` is the linked objective id (``None`` when no link / unparseable).
    ``nodes_marked`` is the ids the merge marked ``done``. ``skipped_reason`` records why nothing
    was marked (or an error string) — the land result is **never** affected by this step.
    ``closed`` is ``True`` when this land completed the roadmap (every node terminal) and the
    objective issue was closed.
    """

    objective: str | None
    nodes_marked: tuple[str, ...]
    skipped_reason: str | None
    closed: bool = False


@dataclass(frozen=True)
class LearnConsumeUpdate:
    """The on-land consume outcome: the ``perk:learn`` issues this docs plan consumed are
    closed + labelled ``perk:consolidated``.

    ``closed`` is the issue ids successfully consolidated. ``skipped_reason`` records why
    nothing was consumed (or an error string) — the land result is **never** affected by this step.
    """

    closed: tuple[str, ...]
    skipped_reason: str | None


@dataclass(frozen=True)
class LandFinalization:
    """The composed outcome of the four durable finalization effects."""

    learn_state: str | None
    plan_issue_closed: bool
    objective: ObjectiveLandUpdate
    learn: LearnConsumeUpdate


def finalize_landed_plan(
    repo_root: Path,
    *,
    landed: LandedPlan,
    pr_base: str,
    close_objective_on_complete: bool = True,
) -> LandFinalization:
    """Run the four durable post-merge bookkeeping effects for one just-merged plan.

    ``pr_base`` is the merged PR's actual base branch (the autoclose-decision evidence) — callers
    capture it before ``merge_pr`` returns a synthetic ``PullRequest``. See the module docstring
    for the full seam contract (reconstructed inputs, convergence, fail-open, the
    ``close_objective_on_complete`` caller obligation).
    """
    backend = resolve.resolve_issue_backend(repo_root)
    learn_state = _stamp_learn_state(backend, landed=landed)
    plan_issue_closed = _close_plan_issue_on_land(
        backend, issue=landed.plan_id, repo_root=repo_root, pr_base=pr_base
    )
    obj_update = _reconcile_objective_on_land(
        landed=landed,
        repo_root=repo_root,
        close_objective_on_complete=close_objective_on_complete,
    )
    learn_update = _consume_learn_on_land(backend, landed=landed)
    return LandFinalization(
        learn_state=learn_state,
        plan_issue_closed=plan_issue_closed,
        objective=obj_update,
        learn=learn_update,
    )


def _stamp_learn_state(backend: issue_backend.IssueBackend, *, landed: LandedPlan) -> str | None:
    """Stamp the canonical post-merge learn state onto the plan-header (contracts.md §8.36).

    A learn-docs consolidation plan (non-empty ``consumed_learn``) skips its learn pass by
    design, so it is stamped ``skipped`` up front (it must never read forever-pending); every
    other plan gets ``pending``. **Never-downgrade guard**: an existing ``captured``/``skipped``
    header value is kept — an idempotent re-land after ``/learn`` must not resurrect a done
    plan — and returned so callers report the *effective* state. **Fail-open loud**
    (the on-land secondary-bookkeeping shape): never raises on expected backend failures
    (``IssueBackendError``) — a failure warns on stderr and returns ``None`` (resume then falls
    back to the local marker — no worse than legacy); a programming error propagates —
    fail-open covers expected infra/query/mutation failures, not bugs.
    """
    target = plan.LearnState.SKIPPED if landed.consumed_learn else plan.LearnState.PENDING
    try:
        state = backend.get_plan(issue_id=landed.plan_id)
        current = state.header.get("learn_state") if state is not None else None
        if current in (plan.LearnState.CAPTURED, plan.LearnState.SKIPPED):
            return str(current)
        backend.update_plan_header(issue_id=landed.plan_id, fields={"learn_state": target.value})
        return target.value
    except IssueBackendError as exc:  # fail-open: the learn-state stamp never blocks landing
        user_output(f"perk pr land: learn-state stamp skipped (non-fatal): {exc}")
        return None


def _github_base_is_non_default(repo_root: Path, pr_base: str) -> bool:
    """True when the merged PR's base is a confirmed **non-default** GitHub branch.

    GitHub only autocloses a ``Closes #N`` footer when the PR merges into the repo's *default*
    branch, so only a confirmed non-default base warrants an explicit close. Fail-open both ways:
    an unknown base (``""``) short-circuits **without** calling ``default_branch`` (rely on
    autoclose), and a ``default_branch`` lookup failure also defers to autoclose.
    """
    if not pr_base:
        return False
    try:
        return pr_base != github.default_branch(repo_root)
    except GitHubError:
        return False


def _close_plan_issue_on_land(
    backend: issue_backend.IssueBackend, *, issue: str, repo_root: Path, pr_base: str
) -> bool:
    """Explicitly close the plan issue after the merge — fail-open + idempotent.

    GitHub's ``Closes #N`` squash-footer autoclose fires **only on a default-branch merge**; a
    merge into a non-default base never autocloses, so perk closes the plan issue explicitly there
    (beside autoclose). Non-github backends have no commit-footer autoclose perk can assume
    (Linear's Done-on-merge automation is integration/team-config dependent), so they always get
    the explicit close. An expected backend failure (``IssueBackendError``) is logged
    loud-but-non-fatal and NEVER changes the land result (mirrors
    :func:`_reconcile_objective_on_land`); a programming error propagates — fail-open covers
    expected infra/query/mutation failures, not bugs. The outcome is surfaced as the result's
    ``plan_issue_closed``.
    """
    if backend.backend_id == "github" and not _github_base_is_non_default(repo_root, pr_base):
        return False
    try:
        return bool(backend.close_issue(issue_id=issue))
    except IssueBackendError as exc:  # fail-open: closing the plan issue never blocks landing
        user_output(f"perk pr land: plan issue close skipped (non-fatal): {exc}")
        return False


def _reconcile_objective_on_land(
    *, landed: LandedPlan, repo_root: Path, close_objective_on_complete: bool = True
) -> ObjectiveLandUpdate:
    """Mechanical auto-on-merge node-done: mark the objective node(s) backlinked to the
    just-merged plan ``done``.

    **Fail-open + non-audited by design.** The merge already succeeded; objective tracking is
    secondary and retryable, so this never raises on expected store failures
    (``ObjectiveStoreError``) and NEVER changes the land result — such a failure is logged
    loud-but-non-fatal to stderr and captured as a ``skipped_reason``; a programming error
    propagates — fail-open covers expected infra/query/mutation failures, not bugs. The auto
    node-done is deliberately set without an audit (the audit gate protects the model-facing
    tool path only).

    ``close_objective_on_complete=False`` (the stacked per-layer callers) never calls
    ``close_objective`` — nodes are still marked, completeness is still computed, and the
    "plan landed" update still posts the honest ``complete`` value, but ``closed`` stays
    ``False``: the aggregate close is the caller's obligation after every layer verified.
    """
    raw = landed.objective_id
    if not raw:
        return ObjectiveLandUpdate(None, (), "no_objective_link")
    objective_id = str(raw).lstrip("#").strip()
    if not objective_id:
        return ObjectiveLandUpdate(None, (), "bad_objective_id")
    store = resolve.resolve_objective_store(repo_root)
    try:
        state = store.get_objective(objective_id=objective_id)
        if state is None:
            return ObjectiveLandUpdate(objective_id, (), "objective_not_found")
        targets = objective.nodes_for_pr(list(state.nodes), landed.plan_id)
        if not targets:
            return ObjectiveLandUpdate(objective_id, (), "no_linked_node")
        marked: list[str] = []
        for node in targets:
            if node.status in objective.TERMINAL:
                continue
            store.update_objective_node(
                objective_id=objective_id,
                node_id=node.id,
                status=objective.NodeStatus.DONE,
            )
            marked.append(node.id)
        pr_id = landed.plan_id
        # Completeness is computed LOCALLY over the post-mark node list (no re-fetch — this path
        # just wrote those statuses itself): every target is terminal after the loop (already-
        # terminal targets were skipped but are terminal either way), other nodes as fetched. The
        # predicate matches `DependencyGraph.is_complete` (completeness is dependency-agnostic).
        # Running this even when `marked` is empty makes a re-land idempotent: re-landing the
        # final PR still converges the objective to closed.
        target_ids = {node.id for node in targets}
        complete = all(
            node.id in target_ids or node.status in objective.TERMINAL for node in state.nodes
        )
        if not complete or not close_objective_on_complete:
            if marked:
                _post_landed_update(
                    store, objective_id=objective_id, node_ids=marked, pr=pr_id, complete=complete
                )
            return ObjectiveLandUpdate(objective_id, tuple(marked), None)
        try:
            # Isolated fail-open: a close failure must NOT fall into the outer handler (which
            # would discard the already-marked node ids). Close through the OBJECTIVE STORE (each
            # backend retires its own entity: GitHub closes the issue, Linear marks the Project
            # complete) — not the issue tier (a Project is not an issue). No closing comment —
            # symmetric with the supervisor's completion close (§8.20).
            store.close_objective(objective_id=objective_id)
        except ObjectiveStoreError as exc:
            user_output(f"perk pr land: objective close skipped (non-fatal): {exc}")
            return ObjectiveLandUpdate(objective_id, tuple(marked), f"close_failed: {exc}")
        if marked:
            _post_landed_update(
                store, objective_id=objective_id, node_ids=marked, pr=pr_id, complete=True
            )
        return ObjectiveLandUpdate(objective_id, tuple(marked), None, closed=True)
    except ObjectiveStoreError as exc:  # fail-open: objective tracking never blocks landing
        user_output(f"perk pr land: objective reconciliation skipped (non-fatal): {exc}")
        return ObjectiveLandUpdate(objective_id, (), f"error: {exc}")


def _post_landed_update(
    store: objective_store.ObjectiveStore,
    *,
    objective_id: str,
    node_ids: list[str],
    pr: object,
    complete: bool,
) -> None:
    """Post the fail-open "plan landed" Project Update.

    Isolated like the close fail-open: an expected store failure (``ObjectiveStoreError``) is
    logged loud-but-non-fatal and NEVER discards the already-marked node result; a programming
    error propagates. Linear project store posts; GitHub + the issue-backed Linear store no-op
    (return ``False``).
    """
    try:
        store.post_status_update(
            objective_id=objective_id,
            body=objective.plan_landed_update_body(
                node_ids, pr=cast("str | int", pr), complete=complete
            ),
        )
    except ObjectiveStoreError as exc:  # fail-open: the update is bookkeeping, never load-bearing
        user_output(f"perk pr land: project update skipped (non-fatal): {exc}")


def _consume_learn_on_land(
    backend: issue_backend.IssueBackend, *, landed: LandedPlan
) -> LearnConsumeUpdate:
    """Consume the ``perk:learn`` issues a learned-docs plan consolidated: close each +
    label it ``perk:consolidated``.

    **Fail-open + non-fatal by design** (mirrors :func:`_reconcile_objective_on_land`). The merge
    already succeeded; consuming the learn issues is secondary and retryable, so this never raises
    on expected backend failures (``IssueBackendError``) and NEVER changes the land result — such
    a failure is logged loud-but-non-fatal to stderr and captured as a ``skipped_reason``; a
    programming error propagates — fail-open covers expected infra/query/mutation failures,
    not bugs.
    """
    raw = landed.consumed_learn
    if not raw:
        return LearnConsumeUpdate((), "no_consumed_learn")
    ids = [cleaned for n in raw if (cleaned := str(n).lstrip("#").strip())]
    if not ids:
        return LearnConsumeUpdate((), "bad_consumed_learn")
    # Per-issue isolation: close each issue independently so one bad issue (already-deleted,
    # transient infra error) does NOT strand the rest — the residual that made the accumulated
    # backlog cleanup unreliable. Expected backend failures are logged loud-but-non-fatal and
    # rolled into a `failed: #a, #b` skipped_reason; the closes that succeeded still land.
    closed: list[str] = []
    failed: list[str] = []
    for learn_id in ids:
        try:
            backend.close_and_label_consolidated(issue_id=learn_id)
            closed.append(learn_id)
        except IssueBackendError as exc:  # fail-open: consuming learn issues never blocks landing
            user_output(f"perk pr land: learn consume skipped issue #{learn_id} (non-fatal): {exc}")
            failed.append(learn_id)
    skipped_reason = f"failed: {', '.join(f'#{n}' for n in failed)}" if failed else None
    return LearnConsumeUpdate(tuple(closed), skipped_reason)
