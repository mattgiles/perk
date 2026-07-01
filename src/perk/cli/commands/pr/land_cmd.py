"""`perk pr land` — the Python/worker PR merge (the cold land door).

Finds the active plan's PR, marks it ready (if draft), squash-merges it (the `Closes #N` in the
PR body closes the plan issue), and sets the `pending-learn` semaphore. Idempotent: an already
merged PR is success. The warm in-session twin is the TS `/land`
tool (delegates here via `pi.exec`, then mirrors the marker for the in-session path).

Exit codes: 0 landed · 1 invalid input / unauthed / no plan / no PR / op failure · 2 not-a-repo.
"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import click

from perk import github, objective, plan
from perk.backends import issue_backend, objective_store, resolve
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import agent as linear_agent
from perk.boundary import OutputModel
from perk.cli.commands.pr.shared import fail
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.run import launch
from perk.state import cache
from perk.substrate.output import machine_output, user_output

# Learn-consume skip reasons that are ordinary, not failures: non-factory plans carry no
# `consumed_learn` (so `no_consumed_learn` is expected) and a dry run early-returns `dry_run`.
# Anything else is surfaced.
_BENIGN_LEARN_SKIPS = frozenset({"no_consumed_learn", "dry_run"})


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
class PrLandResult:
    pr: github.PullRequest
    branch: str
    issue: str  # the opaque plan-issue id (GitHub: "42"; Linear: "ENG-123")
    pending_learn: bool
    dry_run: bool
    objective: ObjectiveLandUpdate
    learn: LearnConsumeUpdate
    # An explicit on-land plan-issue close. GitHub relies on the squash footer's `Closes #N`
    # autoclose for default-branch merges, so this only fires for github when the PR's base is
    # non-default (autoclose never runs there); non-github backends always close explicitly.
    # Fail-open: False when skipped (autoclose path) or the close failed.
    plan_issue_closed: bool = False


@click.command("land")
@click.option("--dry-run", is_flag=True, help="Compose the plan without touching GitHub.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def land_pr(ctx: click.Context, *, dry_run: bool, as_json: bool) -> None:
    """Merge the active plan's PR and set the pending-learn semaphore (submit → land).

    \b
    Run from inside the plan's worktree (it reads the local cache.plan-ref).
    """
    try:
        repo_root = require_repo(ctx)
        if not dry_run:
            require_github(ctx)
        result = _pr_land_impl(repo_root=repo_root, dry_run=dry_run)
    except (GitHubError, IssueBackendError) as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="github_error",
            message=f"PR land failed\n{exc}",
            extra={"dry_run": False},
        )
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
            extra={"dry_run": False},
        )
        return

    if as_json:
        machine_output(json.dumps(_result_to_dict(result)))
    else:
        _render_human(result)


def _pr_land_impl(*, repo_root: Path, dry_run: bool) -> PrLandResult:
    """Resolves the plan's PR, marks ready + squash-merges, sets pending-learn.

    A dry run is fully **offline** (no `gh`, no marker write): it composes the preview from the
    local `cache.plan-ref` only (mirroring `pr submit --dry-run`).
    """
    plan_ref = cache.read_plan_ref(repo_root)
    if plan_ref is None:
        raise UserFacingCliError(
            "No saved plan in this worktree\nRun /plan-save then perk implement first.",
            error_type="no_plan_ref",
        )
    branch = launch.resolve_plan_worktree_name(plan_ref)
    issue = plan_ref.pr_id

    if dry_run:
        return PrLandResult(
            pr=github.PullRequest(
                number=0, url="(dry-run)", is_draft=False, state="OPEN", existed=True
            ),
            branch=branch,
            issue=issue,
            pending_learn=False,  # a dry run sets no marker
            dry_run=True,
            objective=ObjectiveLandUpdate(None, (), "dry_run"),
            learn=LearnConsumeUpdate((), "dry_run"),
        )

    backend = resolve.resolve_issue_backend(repo_root)
    pr = github.find_pr_for_branch(branch=branch, repo_root=repo_root)
    if pr is None:
        raise UserFacingCliError(
            f"No PR found for branch {branch!r}\nRun /submit first.", error_type="no_pr"
        )
    # Capture the PR's actual base before the merge reassigns `pr` to a synthetic PullRequest
    # (which carries no base_ref). An idempotent re-land still sees the real base here.
    pr_base = pr.base_ref
    if pr.state != "MERGED":
        if pr.is_draft:
            github.mark_pr_ready(number=pr.number, repo_root=repo_root)
        pr = github.merge_pr(
            number=pr.number,
            repo_root=repo_root,
            commit_message=_squash_commit_message(
                issue=issue,
                url=plan_ref.url,
                backend_id=backend.backend_id,
                repo_root=repo_root,
            ),
        )
    cache.set_marker(repo_root, cache.PENDING_LEARN)
    plan_issue_closed = _close_plan_issue_on_land(
        backend, issue=issue, repo_root=repo_root, pr_base=pr_base
    )
    obj_update = _reconcile_objective_on_land(plan_ref=plan_ref, repo_root=repo_root)
    learn_update = _consume_learn_on_land(plan_ref=plan_ref, repo_root=repo_root)
    # Mirror the land into the Linear agent session. Gated inside the emitter
    # (stamped provider == "linear" AND LINEAR_AGENT_TOKEN) and fully fail-soft — it never
    # changes the land result or exit code. Never reached on --dry-run (early return).
    linear_agent.emit_landed(
        repo_root,
        pr_number=pr.number,
        summary=_landed_summary(obj_update),
        environ=os.environ,
    )
    return PrLandResult(
        pr=pr,
        branch=branch,
        issue=issue,
        pending_learn=True,
        dry_run=False,
        objective=obj_update,
        learn=learn_update,
        plan_issue_closed=plan_issue_closed,
    )


def _landed_summary(obj_update: ObjectiveLandUpdate) -> str:
    """The one-line land summary for the agent-session ``response`` activity:
    the objective nodes the merge marked done, when any; empty otherwise (the emitter
    supplies the "PR #n squash-merged." base line itself)."""
    if not obj_update.nodes_marked:
        return ""
    nodes = ", ".join(obj_update.nodes_marked)
    line = f"Objective #{obj_update.objective}: marked node(s) {nodes} done."
    if obj_update.closed:
        line += " Objective complete — closed."
    return line


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
    the explicit close. A failure is logged loud-but-non-fatal and NEVER changes the land result
    (mirrors :func:`_reconcile_objective_on_land`); the outcome is surfaced as the envelope's
    ``plan_issue_closed``.
    """
    if backend.backend_id == "github" and not _github_base_is_non_default(repo_root, pr_base):
        return False
    try:
        return bool(backend.close_issue(issue_id=issue))
    except Exception as exc:  # fail-open: closing the plan issue never blocks landing
        print(
            f"perk pr land: plan issue close skipped (non-fatal): {exc}",
            file=sys.stderr,
        )
        return False


def _reconcile_objective_on_land(*, plan_ref: plan.PlanRef, repo_root: Path) -> ObjectiveLandUpdate:
    """Mechanical auto-on-merge node-done: mark the objective node(s) backlinked to the
    just-merged plan ``done``.

    **Fail-open + non-audited by design.** The merge already succeeded; objective tracking is
    secondary and retryable, so this NEVER raises and NEVER changes the land result — any failure is
    logged loud-but-non-fatal to stderr and captured as a ``skipped_reason``. The auto node-done is
    deliberately set without an audit (the audit gate protects the model-facing tool path only).
    """
    raw = plan_ref.objective_id
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
        targets = objective.nodes_for_pr(list(state.nodes), plan_ref.pr_id)
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
        pr_id = plan_ref.pr_id
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
        if not complete:
            if marked:
                _post_landed_update(
                    store, objective_id=objective_id, node_ids=marked, pr=pr_id, complete=False
                )
            return ObjectiveLandUpdate(objective_id, tuple(marked), None)
        try:
            # Isolated fail-open: a close failure must NOT fall into the outer handler (which
            # would discard the already-marked node ids). Close through the OBJECTIVE STORE (each
            # backend retires its own entity: GitHub closes the issue, Linear marks the Project
            # complete) — not the issue tier (a Project is not an issue). No closing comment —
            # symmetric with the supervisor's completion close (§8.20).
            store.close_objective(objective_id=objective_id)
        except Exception as exc:
            print(
                f"perk pr land: objective close skipped (non-fatal): {exc}",
                file=sys.stderr,
            )
            return ObjectiveLandUpdate(objective_id, tuple(marked), f"close_failed: {exc}")
        if marked:
            _post_landed_update(
                store, objective_id=objective_id, node_ids=marked, pr=pr_id, complete=True
            )
        return ObjectiveLandUpdate(objective_id, tuple(marked), None, closed=True)
    except Exception as exc:  # fail-open: objective tracking never blocks landing
        print(
            f"perk pr land: objective reconciliation skipped (non-fatal): {exc}",
            file=sys.stderr,
        )
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

    Isolated like the close fail-open: a failure is logged loud-but-non-fatal and NEVER discards
    the already-marked node result. Linear project store posts; GitHub + the issue-backed Linear
    store no-op (return ``False``).
    """
    try:
        store.post_status_update(
            objective_id=objective_id,
            body=objective.plan_landed_update_body(
                node_ids, pr=cast("str | int", pr), complete=complete
            ),
        )
    except Exception as exc:  # fail-open: the status update is bookkeeping, never load-bearing
        print(
            f"perk pr land: project update skipped (non-fatal): {exc}",
            file=sys.stderr,
        )


def _consume_learn_on_land(*, plan_ref: plan.PlanRef, repo_root: Path) -> LearnConsumeUpdate:
    """Consume the ``perk:learn`` issues a learned-docs plan consolidated: close each +
    label it ``perk:consolidated``.

    **Fail-open + non-fatal by design** (mirrors :func:`_reconcile_objective_on_land`). The merge
    already succeeded; consuming the learn issues is secondary and retryable, so this NEVER raises
    and NEVER changes the land result — any failure is logged loud-but-non-fatal to stderr and
    captured as a ``skipped_reason``.
    """
    raw = plan_ref.consumed_learn
    if not raw:
        return LearnConsumeUpdate((), "no_consumed_learn")
    ids = [cleaned for n in raw if (cleaned := str(n).lstrip("#").strip())]
    if not ids:
        return LearnConsumeUpdate((), "bad_consumed_learn")
    # Per-issue isolation: close each issue independently so one bad issue (already-deleted,
    # transient infra error) does NOT strand the rest — the residual that made the accumulated
    # backlog cleanup unreliable. Failures are logged loud-but-non-fatal and rolled into a
    # `failed: #a, #b` skipped_reason; the closes that succeeded still land. Never raises.
    backend = resolve.resolve_issue_backend(repo_root)
    closed: list[str] = []
    failed: list[str] = []
    for learn_id in ids:
        try:
            backend.close_and_label_consolidated(issue_id=learn_id)
            closed.append(learn_id)
        except Exception as exc:  # fail-open: consuming learn issues never blocks landing
            print(
                f"perk pr land: learn consume skipped issue #{learn_id} (non-fatal): {exc}",
                file=sys.stderr,
            )
            failed.append(learn_id)
    skipped_reason = f"failed: {', '.join(f'#{n}' for n in failed)}" if failed else None
    return LearnConsumeUpdate(tuple(closed), skipped_reason)


def _squash_commit_message(*, issue: str, url: str, backend_id: str, repo_root: Path) -> str:
    """The deepened squash commit message: plain ``"<plan title>\\n\\n<footer>"``.

    The footer branches per backend: GitHub keeps ``Closes #N`` (the autoclose target —
    byte-identical to the pre-Linear shape); non-github backends get a plain
    ``Plan: <id> — <url>`` reference line — NO commit magic words (Linear's commit-linking needs
    a non-assumable extra webhook; perk closes the plan issue explicitly at land instead).

    This is the second of the two PR targets (the GitHub HTML body is the other) — plain text
    only, so no HTML leaks into ``git log``. Best-effort title fetch: a missing/empty title (or any
    backend read failure) falls back to the bare footer.
    """
    footer = f"Closes #{issue}" if backend_id == "github" else f"Plan: {issue} — {url}"
    try:
        state = resolve.resolve_issue_backend(repo_root).get_plan(issue_id=issue)
    except (GitHubError, IssueBackendError):
        return footer
    title = state.title.strip() if state is not None else ""
    return f"{title}\n\n{footer}" if title else footer


class LandPrOut(OutputModel):
    """The serialization boundary of the picked :class:`github.PullRequest` subset
    (field order load-bearing)."""

    number: int
    state: str

    @classmethod
    def from_domain(cls, pr: github.PullRequest) -> "LandPrOut":
        return cls(number=pr.number, state=pr.state)


class ObjectiveLandOut(OutputModel):
    """The serialization boundary of :class:`ObjectiveLandUpdate` (field order load-bearing).

    ``id`` maps from the domain ``objective`` field (the linked objective id)."""

    id: str | None
    nodes_marked: tuple[str, ...]
    skipped_reason: str | None
    closed: bool

    @classmethod
    def from_domain(cls, update: ObjectiveLandUpdate) -> "ObjectiveLandOut":
        return cls(
            id=update.objective,
            nodes_marked=update.nodes_marked,
            skipped_reason=update.skipped_reason,
            closed=update.closed,
        )


class LearnConsumeOut(OutputModel):
    """The serialization boundary of :class:`LearnConsumeUpdate` (field order load-bearing)."""

    closed: tuple[str, ...]
    skipped_reason: str | None

    @classmethod
    def from_domain(cls, update: LearnConsumeUpdate) -> "LearnConsumeOut":
        return cls(closed=update.closed, skipped_reason=update.skipped_reason)


class PrLandOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`PrLandResult` (field order load-bearing)."""

    success: bool
    error_type: str | None
    message: str | None
    pr: LandPrOut
    branch: str
    issue: str  # opaque string id at every machine boundary (contracts §8.21)
    pending_learn: bool
    plan_issue_closed: bool
    dry_run: bool
    objective: ObjectiveLandOut
    learn: LearnConsumeOut

    @classmethod
    def from_domain(cls, result: PrLandResult) -> "PrLandOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            pr=LandPrOut.from_domain(result.pr),
            branch=result.branch,
            issue=result.issue,
            pending_learn=result.pending_learn,
            plan_issue_closed=result.plan_issue_closed,
            dry_run=result.dry_run,
            objective=ObjectiveLandOut.from_domain(result.objective),
            learn=LearnConsumeOut.from_domain(result.learn),
        )


def _result_to_dict(result: PrLandResult) -> dict[str, object]:
    return PrLandOut.from_domain(result).model_dump(mode="json")


def _render_human(result: PrLandResult) -> None:
    if result.dry_run:
        user_output(click.style("pr land --dry-run (no GitHub writes, no marker)", dim=True))
        user_output(f"  branch={result.branch}  plan=#{result.issue}")
        user_output("  would: mark ready (if draft) → squash-merge → set pending-learn")
        return
    user_output(
        click.style("✓ ", fg="green")
        + "Landed PR "
        + click.style(f"#{result.pr.number}", fg="cyan")
        + " (squash-merged); pending-learn set"
    )
    if result.plan_issue_closed:
        user_output(
            click.style("  plan issue closed explicitly (non-default base branch)", dim=True)
        )
    if result.objective.nodes_marked:
        nodes = ", ".join(result.objective.nodes_marked)
        user_output(f"  objective #{result.objective.objective}: marked node(s) {nodes} done")
    if result.objective.closed:
        user_output(f"  objective #{result.objective.objective} complete — closed")
    if result.learn.closed:
        closed = ", ".join(f"#{n}" for n in result.learn.closed)
        user_output(f"  consolidated learn issue(s) {closed} into docs/learned")
    # Surface a non-benign learn-consume skip: `no_consumed_learn` is the ordinary
    # non-factory case (and dry-run early-returns), so stay quiet on those; a real failure
    # (`failed: …`, `bad_consumed_learn`, `error: …`) must be visible, not silent.
    if result.learn.skipped_reason and result.learn.skipped_reason not in _BENIGN_LEARN_SKIPS:
        user_output(
            click.style(f"  ⚠ learn consume incomplete: {result.learn.skipped_reason}", fg="yellow")
        )
