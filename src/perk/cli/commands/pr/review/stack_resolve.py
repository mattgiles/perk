"""Stack resolution for the stacked-PR review flow (contracts.md §8.4).

Resolves an ordered PR stack from either entry arm — a perk objective's delivery train
(`resolve_stack_from_objective`) or a base-ref chain walk from any member PR
(`resolve_stack_from_pr`) — into **wire facts only**: PR numbers, refs, and repository
identities, never resolved commit SHAs. The checkout worker is the single hydration boundary
(its one fetch resolves every member head SHA and the combined base SHA), so nothing here
re-resolves moving refs and nothing downstream re-resolves them either.

Consumer tier by construction: this module composes the GitHub gateway AND the delivery
façade, so it lives beside the review commands, not in ``perk/github/``.

Both arms share the cardinality gates and the fork gate, so the doors and the reviewer
children refuse consistently:

- fewer than 2 members → ``not_a_stack`` (a single PR is `/pr-review-browser` territory);
- more than :data:`STACK_REVIEW_MAX_MEMBERS` → ``stack_too_deep`` (chunked review of deeper
  trains is deliberately deferred);
- a cross-repository head → ``fork_unsupported`` (branch names alone cannot distinguish a
  same-repo child from a fork child — the ``head_repo`` identity closes that hole, and an
  empty/unavailable identity fails closed).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from perk import github
from perk.cli.ensure import UserFacingCliError
from perk.delivery import DeliveryError, StatusRequest, resolve_delivery
from perk.github import PullRequest

# The shared member ceiling (both arms). A module constant, exported and pinned: deeper trains
# refuse with `stack_too_deep` rather than degrading into an unreviewably large combined diff.
STACK_REVIEW_MAX_MEMBERS = 20


@dataclass(frozen=True)
class StackMember:
    """One stack member's wire facts (no resolved commit SHAs — see the module header).

    ``recorded_head_sha`` is the objective arm's journal-recorded ``published_head_sha`` — a
    recorded publication fact carried for the checkout worker's drift corroboration note,
    NOT a resolved ref (``None`` in chain mode and for unpublished layers)."""

    pr_number: int
    url: str
    head_ref: str
    base_ref: str
    head_repo: str
    node_id: str | None
    plan_id: str | None
    recorded_head_sha: str | None = None


@dataclass(frozen=True)
class ResolvedStack:
    """An ordered, all-OPEN, same-repo-headed PR stack (bottom→top wire facts).

    ``base_ref`` is the bottom member's base branch (the combined-diff base);
    ``notes`` are report-only warnings (train blockers, drift observations) — warn and
    proceed, never a refusal."""

    members: tuple[StackMember, ...]
    base_ref: str
    kind: Literal["objective", "chain"]
    objective_id: str | None
    notes: tuple[str, ...]

    @property
    def top(self) -> StackMember:
        return self.members[-1]


def _home_repo_full_name(repo_root: Path) -> str:
    """The repository's own ``owner/name`` (the fork gate's comparison key).

    Derived from the canonical ``gh repo view`` identity URL
    (``https://github.com/<owner>/<name>``) — the one public gateway read that carries the
    owner segment. Raises ``GitHubError`` on an infra failure.
    """
    identity = github.repo_identity(repo_root)
    parts = [p for p in identity.url.split("/") if p]
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return identity.name


def _gate_cardinality(members: list[StackMember]) -> None:
    """The shared cardinality gates (both arms) — see the module header."""
    if len(members) < 2:
        raise UserFacingCliError(
            f"Not a stack: {len(members)} open member PR(s) resolved — a single PR is "
            "reviewed with /pr-review-browser.",
            error_type="not_a_stack",
        )
    if len(members) > STACK_REVIEW_MAX_MEMBERS:
        raise UserFacingCliError(
            f"Stack too deep: {len(members)} members exceed the "
            f"{STACK_REVIEW_MAX_MEMBERS}-member review ceiling.",
            error_type="stack_too_deep",
        )


def _gate_fork(pr: PullRequest, home: str) -> None:
    """Refuse a cross-repository (or identity-less) head — `fork_unsupported`, fail closed."""
    if pr.head_repo != home:
        described = pr.head_repo or "an unavailable head repository"
        raise UserFacingCliError(
            f"PR #{pr.number}'s head lives in {described}, not {home} — fork stacks are "
            "unsupported.",
            error_type="fork_unsupported",
        )


def _member_from_pr(pr: PullRequest) -> StackMember:
    return StackMember(
        pr_number=pr.number,
        url=pr.url,
        head_ref=pr.head_ref,
        base_ref=pr.base_ref,
        head_repo=pr.head_repo,
        node_id=None,
        plan_id=None,
    )


def resolve_stack_from_pr(repo_root: Path, pr_number: int) -> ResolvedStack:
    """Resolve the base-ref **chain** containing PR ``pr_number`` (the non-perk arm).

    Downward: repeatedly find the OPEN same-repo PR whose head is the current member's base
    branch — a merged/closed/missing/foreign lower PR ends the walk (that member's base is
    the stack base). Upward: repeatedly list the OPEN PRs based on the current head, filtered
    to same-repo heads — 0 is the top, 1 extends, more than 1 is the typed
    ``ambiguous_stack`` refusal naming the candidates. A candidate that is ALREADY in the
    walked chain means the base-ref graph loops — the typed ``stack_cycle`` refusal, never a
    "successful" end of the walk (a cycle can pass the checkout ancestry gate while the
    chosen base renders an empty combined diff). Wire facts only; typed refusals
    (`pr_not_found`, `pr_not_open`, `fork_unsupported`, `ambiguous_stack`, `stack_cycle`,
    `not_a_stack`, `stack_too_deep`) exit before any launch.
    """
    start = github.get_pr(number=pr_number, repo_root=repo_root)
    if start is None:
        raise UserFacingCliError(
            f"PR #{pr_number} not found\nCheck the number (gh pr list shows open PRs).",
            error_type="pr_not_found",
        )
    if start.state != "OPEN":
        raise UserFacingCliError(
            f"PR #{pr_number} is {start.state} — a stack review needs an open member PR.",
            error_type="pr_not_open",
        )
    home = _home_repo_full_name(repo_root)
    _gate_fork(start, home)

    seen = {start.number}
    down: list[PullRequest] = []
    current = start
    # Both walks are bounded by the member ceiling; a revisited PR is the typed cycle refusal
    # below (never a "successful" end of the walk — the PR base graph is functional, so any
    # base-ref loop is reachable by following bases down).
    while len(down) <= STACK_REVIEW_MAX_MEMBERS:
        lower = github.find_pr_for_branch(branch=current.base_ref, repo_root=repo_root)
        if lower is None or lower.state != "OPEN" or lower.head_repo != home:
            break
        if lower.number in seen:
            raise UserFacingCliError(
                f"Stack cycle: PR #{current.number}'s base branch {current.base_ref!r} is "
                f"already-walked PR #{lower.number}'s head — the base-ref graph loops. Fix "
                "the PR base branches, then re-run.",
                error_type="stack_cycle",
            )
        seen.add(lower.number)
        down.append(lower)
        current = lower

    up: list[PullRequest] = []
    current = start
    while len(up) <= STACK_REVIEW_MAX_MEMBERS:
        candidates = [
            p
            for p in github.list_open_prs_for_base(base=current.head_ref, repo_root=repo_root)
            if p.head_repo == home
        ]
        looped = [p for p in candidates if p.number in seen]
        if looped:
            # Defense in depth: a seen upward candidate is the same loop pathology (a PR has
            # exactly one base, so it cannot legitimately reappear above the chain).
            raise UserFacingCliError(
                f"Stack cycle: PR #{looped[0].number} is based on already-walked branch "
                f"{current.head_ref!r} — the base-ref graph loops. Fix the PR base branches, "
                "then re-run.",
                error_type="stack_cycle",
            )
        if not candidates:
            break
        if len(candidates) > 1:
            names = ", ".join(f"#{p.number} ({p.head_ref})" for p in candidates)
            raise UserFacingCliError(
                f"Ambiguous stack: {len(candidates)} open PRs stack on "
                f"{current.head_ref!r} — {names}. Start from the intended top PR instead.",
                error_type="ambiguous_stack",
            )
        chosen = candidates[0]
        seen.add(chosen.number)
        up.append(chosen)
        current = chosen

    ordered = [*reversed(down), start, *up]
    members = [_member_from_pr(p) for p in ordered]
    _gate_cardinality(members)
    return ResolvedStack(
        members=tuple(members),
        base_ref=members[0].base_ref,
        kind="chain",
        objective_id=None,
        notes=(),
    )


def resolve_stack_from_objective(repo_root: Path, objective_id: str) -> ResolvedStack:
    """Resolve the stack from a perk objective's delivery train (the first-class arm).

    One ``Delivery.status`` read selects the OPEN, PR-carrying layers in delivery order; one
    ``get_pr`` read per member supplies the URL / head-repository identity / observed refs
    (the train layer carries no URL). Ref-level linkage is checked here (each member's
    observed base == its predecessor's head branch; the first member's base == the train's
    effective base; a gap → ``stack_discontiguous``); commit-topology validation happens at
    checkout, where the objects exist. Train blockers become report-only ``notes`` — warn
    and proceed.
    """
    try:
        status = resolve_delivery(repo_root).status(StatusRequest(objective_id=objective_id))
    except DeliveryError as exc:
        raise UserFacingCliError(str(exc), error_type=exc.error_type) from exc
    delivery_train = status.train
    if delivery_train is None:
        raise UserFacingCliError(
            f"Objective #{status.objective_id} has no stacked delivery train "
            f"({status.no_train_reason}) — stack review needs a stacked objective.",
            error_type="not_stacked",
        )
    notes = [f"[{f.code}] {f.message}" for f in delivery_train.blockers]
    home = _home_repo_full_name(repo_root)
    members: list[StackMember] = []
    for layer in delivery_train.layers:
        if layer.pr_number is None:
            continue
        pr = github.get_pr(number=layer.pr_number, repo_root=repo_root)
        if pr is None or pr.state != "OPEN":
            continue
        _gate_fork(pr, home)
        members.append(
            StackMember(
                pr_number=pr.number,
                url=pr.url,
                head_ref=pr.head_ref or (layer.branch or ""),
                base_ref=pr.base_ref,
                head_repo=pr.head_repo,
                node_id=layer.node_id,
                plan_id=layer.plan_id,
                recorded_head_sha=layer.published_head_sha,
            )
        )
    _gate_cardinality(members)
    expected_base = delivery_train.base
    for member in members:
        if member.base_ref != expected_base:
            raise UserFacingCliError(
                f"Stack discontiguous: PR #{member.pr_number}'s observed base is "
                f"{member.base_ref!r}, expected {expected_base!r} — the train's open layers "
                "do not form one base-linked chain (sync the stack first).",
                error_type="stack_discontiguous",
            )
        expected_base = member.head_ref
    return ResolvedStack(
        members=tuple(members),
        base_ref=delivery_train.base,
        kind="objective",
        objective_id=status.objective_id,
        notes=tuple(notes),
    )
