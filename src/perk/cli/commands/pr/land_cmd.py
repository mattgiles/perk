"""`perk pr land` — the Python/worker PR merge (the cold land door).

Finds the active plan's PR, marks it ready (if draft), squash-merges it (the `Closes #N` in the
PR body closes the plan issue), and sets the `pending-learn` semaphore — except for a learn-docs
consolidation plan (non-empty `consumed_learn`), which is exempt from the land→learn cycle: no
marker is set (`pending_learn: false` in the envelope) and `learn_state: skipped` is stamped
instead. Idempotent: an already
merged PR is success. Refuses a stacked-delivery plan (`delivery_lineage` on the cached ref OR
the plan header — header wins) before any mutation: stacked layers land only as one atomic
train, never individually. The durable post-merge bookkeeping delegates to
:func:`perk.delivery.finalize_landed_plan`; the Linear agent "landed" activity emission stays
here (worktree-session-scoped, a caller concern of the seam). The warm in-session twin is the TS
`/land` tool (delegates here via `pi.exec`, then mirrors the marker for the in-session path).

Exit codes: 0 landed · 1 invalid input / unauthed / no plan / no PR / op failure · 2 not-a-repo.
"""

import os
from dataclasses import dataclass
from pathlib import Path

import click

from perk import delivery, github
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import agent as linear_agent
from perk.boundary import OutputModel
from perk.cli.context import require_github, require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.run import launch
from perk.state import cache
from perk.substrate.output import user_output

# Learn-consume skip reasons that are ordinary, not failures: non-factory plans carry no
# `consumed_learn` (so `no_consumed_learn` is expected) and a dry run early-returns `dry_run`.
# Anything else is surfaced.
_BENIGN_LEARN_SKIPS = frozenset({"no_consumed_learn", "dry_run"})


@dataclass(frozen=True)
class PrLandResult:
    pr: github.PullRequest
    branch: str
    issue: str  # the opaque plan-issue id (GitHub: "42"; Linear: "ENG-123")
    pending_learn: bool
    dry_run: bool
    objective: delivery.ObjectiveLandUpdate
    learn: delivery.LearnConsumeUpdate
    # An explicit on-land plan-issue close. GitHub relies on the squash footer's `Closes #N`
    # autoclose for default-branch merges, so this only fires for github when the PR's base is
    # non-default (autoclose never runs there); non-github backends always close explicitly.
    # Fail-open: False when skipped (autoclose path) or the close failed.
    plan_issue_closed: bool = False
    # The canonical post-merge learn state stamped onto the plan-header (contracts.md §8.36):
    # the effective `learn_state` value after the stamp (the kept value on the never-downgrade
    # arm), or None on dry-run / a failed stamp (resolution falls back to the local marker).
    learn_state: str | None = None


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

    emit(as_json=as_json, payload=_result_to_dict(result), render=lambda: _render_human(result))


def _stacked_refusal(issue: str) -> UserFacingCliError:
    """The fail-closed stacked-lineage refusal: landing one stacked layer individually merges
    into its parent branch and tears the train, so `pr land` refuses before any mutation."""
    return UserFacingCliError(
        f"plan #{issue} carries stacked delivery lineage — stacked layers land only as one "
        "atomic train, never individually\n"
        "Landing one layer merges into its parent branch and tears the train. "
        "Inspect the train with: perk objective stack status",
        error_type="stacked_plan",
    )


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
    # The local half of the stacked routing discriminator runs BEFORE the dry-run early-return:
    # a "would: mark ready → squash-merge" preview would be a lie for a stacked plan, and the
    # cached-ref check keeps --dry-run fully offline.
    if plan_ref.delivery_lineage is not None:
        raise _stacked_refusal(plan_ref.pr_id)
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
            objective=delivery.ObjectiveLandUpdate(None, (), "dry_run"),
            learn=delivery.LearnConsumeUpdate((), "dry_run"),
        )

    backend = resolve.resolve_issue_backend(repo_root)
    # Load-bearing pre-merge plan read: the header half of the stacked discriminator must be
    # checked before any mutation, and the squash title rides the same read.
    state = backend.get_plan(issue_id=issue)
    if state is None:
        raise UserFacingCliError(f"Plan issue #{issue} not found", error_type="plan_not_found")
    # The stacked routing discriminator (mirrors submit/ready): a stale cached ref without the
    # lineage still refuses once the plan header shows the lineage (header wins — a stale cached
    # ref must not silently land a stacked layer).
    header_lineage = state.header.get("delivery_lineage")
    stacked = plan_ref.delivery_lineage is not None or (
        isinstance(header_lineage, str) and bool(header_lineage.strip())
    )
    if stacked:
        raise _stacked_refusal(issue)
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
                title=state.title,
            ),
        )
    # A learn-docs consolidation plan (non-empty `consumed_learn`) IS the learn pass — it is
    # exempt from the land→learn cycle: no pending-learn marker (which would strand the worktree
    # behind a pointless /learn short-circuit); `learn_state: skipped` is stamped instead.
    # The marker is worktree-cache state, so it stays here (the finalize seam is cache-free).
    if not plan_ref.consumed_learn:
        cache.set_marker(repo_root, cache.PENDING_LEARN)
    fin = delivery.finalize_landed_plan(
        repo_root,
        landed=delivery.LandedPlan(
            plan_id=issue,
            objective_id=plan_ref.objective_id,
            consumed_learn=plan_ref.consumed_learn,
        ),
        pr_base=pr_base,
    )
    # Mirror the land into the Linear agent session. Gated inside the emitter
    # (stamped provider == "linear" AND LINEAR_AGENT_TOKEN) and fully fail-soft — it never
    # changes the land result or exit code. Never reached on --dry-run (early return).
    # Deliberately OUTSIDE the finalize seam: the gate reads worktree-session state and the
    # emission is not idempotent — activity reporting is this caller's concern.
    linear_agent.emit_landed(
        repo_root,
        pr_number=pr.number,
        summary=_landed_summary(fin.objective),
        environ=os.environ,
    )
    return PrLandResult(
        pr=pr,
        branch=branch,
        issue=issue,
        pending_learn=not plan_ref.consumed_learn,
        dry_run=False,
        objective=fin.objective,
        learn=fin.learn,
        plan_issue_closed=fin.plan_issue_closed,
        learn_state=fin.learn_state,
    )


def _landed_summary(obj_update: delivery.ObjectiveLandUpdate) -> str:
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


def _squash_commit_message(*, issue: str, url: str, backend_id: str, title: str) -> str:
    """The deepened squash commit message: plain ``"<plan title>\\n\\n<footer>"``.

    The footer branches per backend: GitHub keeps ``Closes #N`` (the autoclose target —
    byte-identical to the pre-Linear shape); non-github backends get a plain
    ``Plan: <id> — <url>`` reference line — NO commit magic words (Linear's commit-linking needs
    a non-assumable extra webhook; perk closes the plan issue explicitly at land instead).

    This is the second of the two PR targets (the GitHub HTML body is the other) — plain text
    only, so no HTML leaks into ``git log``. ``title`` rides the load-bearing pre-merge plan
    read; an empty title falls back to the bare footer.
    """
    footer = f"Closes #{issue}" if backend_id == "github" else f"Plan: {issue} — {url}"
    cleaned = title.strip()
    return f"{cleaned}\n\n{footer}" if cleaned else footer


class LandPrOut(OutputModel):
    """The serialization boundary of the picked :class:`github.PullRequest` subset
    (field order load-bearing)."""

    number: int
    state: str

    @classmethod
    def from_domain(cls, pr: github.PullRequest) -> "LandPrOut":
        return cls(number=pr.number, state=pr.state)


class ObjectiveLandOut(OutputModel):
    """The serialization boundary of :class:`delivery.ObjectiveLandUpdate` (field order
    load-bearing).

    ``id`` maps from the domain ``objective`` field (the linked objective id)."""

    id: str | None
    nodes_marked: tuple[str, ...]
    skipped_reason: str | None
    closed: bool

    @classmethod
    def from_domain(cls, update: delivery.ObjectiveLandUpdate) -> "ObjectiveLandOut":
        return cls(
            id=update.objective,
            nodes_marked=update.nodes_marked,
            skipped_reason=update.skipped_reason,
            closed=update.closed,
        )


class LearnConsumeOut(OutputModel):
    """The serialization boundary of :class:`delivery.LearnConsumeUpdate` (field order
    load-bearing)."""

    closed: tuple[str, ...]
    skipped_reason: str | None

    @classmethod
    def from_domain(cls, update: delivery.LearnConsumeUpdate) -> "LearnConsumeOut":
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
    # Declared LAST so the existing field byte-order is preserved (contracts.md §8.36).
    learn_state: str | None = None

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
            learn_state=result.learn_state,
        )


def _result_to_dict(result: PrLandResult) -> dict[str, object]:
    return PrLandOut.from_domain(result).model_dump(mode="json")


def _render_human(result: PrLandResult) -> None:
    if result.dry_run:
        user_output(click.style("pr land --dry-run (no GitHub writes, no marker)", dim=True))
        user_output(f"  branch={result.branch}  plan=#{result.issue}")
        user_output("  would: mark ready (if draft) → squash-merge → set pending-learn")
        return
    learn_fragment = (
        "; pending-learn set" if result.pending_learn else "; learn pass exempt (learn-docs plan)"
    )
    landed = (
        click.style("✓ ", fg="green")
        + "Landed PR "
        + click.style(f"#{result.pr.number}", fg="cyan")
        + " (squash-merged)"
        + learn_fragment
    )
    if result.learn_state is not None:
        landed += f"; learn_state={result.learn_state}"
    user_output(landed)
    if result.learn_state is None:
        user_output(
            click.style(
                "  ⚠ learn-state stamp failed — resume falls back to the local marker",
                fg="yellow",
            )
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
