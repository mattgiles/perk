"""`perk pr submit` — the Python/worker PR open (the cold submit door).

Pushes the active plan's branch and opens a **draft** PR linking the plan (`Closes #N`), then
populates the staged `branch`/`pr`/`lifecycle_stage` plan-header fields. The warm in-session
twin is the TS `/submit` tool (delegates here via `pi.exec`).
Supervisor surface: `--json` to stdout + stable exit codes, human text to stderr.

Exit codes: 0 submitted · 1 invalid input / unauthed / no saved plan / op failure · 2 not-a-repo.
"""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

import click

from perk import delivery, github, plan
from perk.backends import issue_backend, resolve
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import agent as linear_agent
from perk.boundary import OutputModel
from perk.cli.context import require_github, require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError

# Root-path alias: inside `PrSubmitResult` the `delivery` *field* shadows the module, so the
# `operation` annotation cannot spell `delivery.SyncResult` there.
from perk.delivery import SyncResult as DeliverySyncResult
from perk.github import GitHubError
from perk.run import launch
from perk.state import cache
from perk.substrate import config as config_mod
from perk.substrate import git
from perk.substrate.output import user_output


@dataclass(frozen=True)
class PrSubmitResult:
    pr: github.PullRequest
    branch: str
    issue: str  # the opaque plan-issue id (GitHub: "42"; Linear: "ENG-123")
    header_update: issue_backend.PlanHeaderUpdate
    plan_embedded: bool
    pr_checked: bool
    dry_run: bool
    base: str
    # Tri-state mergeability from the local `git merge-tree` probe: True (clean), False
    # (conflicts present), None (probe undetermined / skipped — fail-open).
    mergeable: bool | None
    conflicts: tuple[str, ...]
    # The stacked-delivery additions (contracts.md §8.47) — all None on the incremental path.
    delivery: str | None = None
    stack_number: int | None = None
    stack_size: int | None = None
    stack_position: int | None = None
    operation_id: str | None = None
    operation: DeliverySyncResult | None = None


@click.command("submit")
@click.option("--dry-run", is_flag=True, help="Compose the plan without pushing or hitting GitHub.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.option(
    "--run-id",
    "run_id",
    default=None,
    help="This implement run's id; union-merged into the plan-header impl_run_ids (§8.35).",
)
@click.pass_context
def submit_pr(ctx: click.Context, *, dry_run: bool, as_json: bool, run_id: str | None) -> None:
    """Open a draft PR for the active plan's branch (the implement → submit boundary).

    \b
    Run from inside the plan's worktree (it reads the local cache.plan-ref).
    """
    try:
        repo_root = require_repo(ctx)
        if not dry_run:
            require_github(ctx)
        result = _pr_submit_impl(repo_root=repo_root, dry_run=dry_run, run_id=run_id)
    except (GitHubError, IssueBackendError) as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="github_error",
            message=f"PR submit failed\n{exc}",
            extra={"dry_run": False},
        )
        return
    except git.PushRejectedError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="push_rejected",
            message=(
                "Push rejected — the remote branch moved unexpectedly.\n"
                "Fetch/rebase onto the latest origin and re-submit.\n" + str(exc)
            ),
            extra={"dry_run": False},
        )
        return
    except git.GitError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="git_error",
            message=f"git push failed\n{exc}",
            extra={"dry_run": False},
        )
        return
    except delivery.DeliveryError as exc:
        if exc.phase == "cascade" and exc.origin == "delivery":
            message = f"stacked propagation failed\n{exc}"
        elif exc.phase == "layer" and exc.origin in {"domain", "delivery"}:
            message = f"stacked publication failed\n{exc}"
        elif exc.phase == "layer" and exc.origin == "git":
            if exc.error_type == "push_rejected":
                message = (
                    "Push rejected — the remote branch moved unexpectedly.\n"
                    "Fetch/rebase onto the latest origin and re-submit.\n" + str(exc)
                )
            else:
                message = f"git push failed\n{exc}"
        else:
            message = f"PR submit failed\n{exc}"
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type,
            message=message,
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


def _pr_submit_impl(*, repo_root: Path, dry_run: bool, run_id: str | None = None) -> PrSubmitResult:
    """Resolves the plan, pushes, opens the PR, updates the header.

    A dry run is fully **offline** (no push, no `gh` read or write): it composes the launch
    preview from the local `cache.plan-ref` only (mirroring `plan-save --dry-run`).
    A stacked plan (delivery-lineage discriminator) routes to `_stacked_submit_impl`
    (contracts.md §8.47); the incremental path below is untouched.
    """
    if run_id is not None and not run_id.strip():
        run_id = None
    plan_ref = cache.read_plan_ref(repo_root)
    if plan_ref is None:
        raise UserFacingCliError(
            "No saved plan in this worktree\nRun /plan-save then perk implement first.",
            error_type="no_plan_ref",
        )
    branch = launch.resolve_plan_worktree_name(plan_ref)
    issue = plan_ref.pr_id

    if dry_run:
        published = delivery.resolve_delivery(repo_root).publish(
            delivery.PublishRequest(kind="layer", plan_id=issue, dry_run=True)
        )
        layer = published.layer
        if layer is None:
            raise ValueError("layer dry-run publish returned no layer detail")
        return PrSubmitResult(
            pr=layer.pr,
            branch=layer.branch,
            issue=published.plan_id,
            header_update=layer.header_update,
            plan_embedded=layer.plan_embedded,
            pr_checked=layer.pr_checked,
            dry_run=True,
            base=layer.parent_branch,
            mergeable=None,
            conflicts=(),
        )

    # The stacked routing discriminator: a stale cached ref without the lineage still routes
    # stacked once the plan header shows the lineage (header wins — a stale cached ref must
    # not silently route incremental).
    backend = resolve.resolve_issue_backend(repo_root)
    state = backend.get_plan(issue_id=issue)
    if state is None:
        raise UserFacingCliError(f"Plan issue #{issue} not found", error_type="plan_not_found")
    header_lineage = state.header.get("delivery_lineage")
    stacked = plan_ref.delivery_lineage is not None or (
        isinstance(header_lineage, str) and bool(header_lineage.strip())
    )
    if git.is_dirty(repo_root):
        raise UserFacingCliError(
            "Uncommitted changes in this worktree\n"
            "Commit your changes before submitting — uncommitted work isn't pushed.",
            error_type="dirty_tree",
        )
    if stacked:
        return _stacked_submit_impl(
            repo_root=repo_root,
            state=state,
            issue=issue,
            run_id=run_id,
        )
    # Resolve the PR merge target / conflict-probe base: the plan's pinned base wins
    # (cache.plan-ref → plan-header), else the GitHub default branch (byte-identical to before).
    # Mirror the `isinstance(...).strip()` guard the start-point resolver uses (launch.py) so all
    # three base readers treat a malformed/non-string cached value identically (ignore it), rather
    # than stringifying it into a bogus branch name.
    pinned = plan_ref.base or state.header.get("base")
    base = (
        pinned.strip()
        if isinstance(pinned, str) and pinned.strip()
        else github.default_branch(repo_root)
    )
    # Auto-force (--force-with-lease): perk plan branches are single-author and expected to
    # diverge after amend/squash/rebase; a no-op on the first push.
    git.push(repo_root, branch, force=True)

    # Best-effort plan embed: fetch the verbatim plan markdown; None (no block / fetch
    # failure) -> no embed, no raise. The PR number is unknown until create_pr returns, so the
    # checkout footer is appended in a second update_pr_body pass (create-then-update).
    plan_body = _safe_plan_body(issue=issue, repo_root=repo_root)
    pr = github.create_pr(
        head=branch,
        base=base,
        title=state.title,
        body=_compose_pr_body(issue=issue, plan_body=plan_body),
        repo_root=repo_root,
        draft=True,
    )
    # A replan reuses branch plan-<N>, so find_pr_for_branch can return a prior attempt's PR in a
    # non-OPEN state. Never silently decorate a non-OPEN reused PR: a CLOSED reuse is the expected
    # replan-after-closed-attempt shape (reopen it and proceed — re-embedding the plan into a
    # CLOSED PR would let /land fail baffling-ly); a MERGED reuse has nothing to reuse (refuse).
    # A freshly created PR is always OPEN, so these arms fire only on `existed`.
    if pr.existed and pr.state == "MERGED":
        raise UserFacingCliError(
            f"PR #{pr.number} for branch {branch} has already merged\n"
            "The branch's PR is merged — there is nothing to submit. Start a fresh plan/branch "
            "for new work.",
            error_type="pr_already_merged",
        )
    if pr.existed and pr.state == "CLOSED":
        github.reopen_pr(number=pr.number, repo_root=repo_root)
        user_output(click.style(f"↺ reopened closed PR #{pr.number} for this branch", fg="yellow"))
    full_body = _compose_pr_body(issue=issue, plan_body=plan_body, pr_number=pr.number)
    github.update_pr_body(number=pr.number, body=full_body, repo_root=repo_root)
    # Post-write self-check: exactly what catches the issue-numbered-footer bug.
    errors = github.validate_pr_body(full_body, pr_number=pr.number)
    if errors:
        raise UserFacingCliError(
            "PR body check failed:\n  " + "\n  ".join(errors), error_type="pr_check_failed"
        )
    fields: dict[str, object] = {
        "branch": branch,
        "pr": str(pr.number),
        "lifecycle_stage": plan.LifecycleStage.IMPL.value,
    }
    # Stamp the implement run id into the staged `impl_run_ids` linkage (contracts.md §8.35):
    # union-merge against the header already in hand (dedup, order-preserving). Bare CLI
    # invocations (no `--run-id`) leave the field untouched. `update_plan_header` MERGES, so a
    # later resave/restamp accumulates new run ids rather than clobbering.
    if run_id:
        merged = plan.merge_untrusted_str_list(state.header.get("impl_run_ids"), run_id)
        fields["impl_run_ids"] = list(merged)
    header_update = backend.update_plan_header(issue_id=issue, fields=fields)
    # Mirror the opened PR into the Linear agent session. Gated inside the
    # emitter (stamped provider == "linear" AND LINEAR_AGENT_TOKEN) and fully fail-soft — it
    # never changes the submit result or exit code. Never reached on --dry-run (early return).
    linear_agent.emit_pr_opened(
        repo_root, pr_number=pr.number, pr_url=pr.url, branch=branch, environ=os.environ
    )
    # Mergeability gate: a deterministic local probe AFTER the PR exists. Fail-open —
    # `detect_merge_conflicts` swallows git failures and the call site is guarded so a probe
    # failure NEVER changes submit's exit code; only a definitive verdict sets mergeable.
    mergeable, conflicts = _probe_mergeability(repo_root, base=base, branch=branch)
    return PrSubmitResult(
        pr=pr,
        branch=branch,
        issue=issue,
        header_update=header_update,
        plan_embedded=plan_body is not None,
        pr_checked=True,
        dry_run=False,
        base=base,
        mergeable=mergeable,
        conflicts=conflicts,
    )


def _stacked_submit_impl(
    *,
    repo_root: Path,
    state: issue_backend.PlanState,
    issue: str,
    run_id: str | None,
) -> PrSubmitResult:
    """Submit stacked intent through the repository-scoped Delivery façade."""
    header_run_id = state.header.get("run_id")
    resolved_run_id = run_id or (
        header_run_id.strip() if isinstance(header_run_id, str) and header_run_id.strip() else ""
    )
    if not resolved_run_id:
        raise UserFacingCliError(
            "A stacked submit needs a resolvable run id for the operation journal\n"
            "Pass --run-id (neither the flag nor the plan header carries one).",
            error_type="invalid_input",
        )
    try:
        config_mod.load_config(repo_root)
    except (config_mod.ConfigError, tomllib.TOMLDecodeError, OSError) as exc:
        raise UserFacingCliError(
            f".perk config invalid: {exc}\nFix it, then re-run (perk doctor pinpoints the field).",
            error_type="invalid_config",
        ) from exc
    published = delivery.resolve_delivery(repo_root).publish(
        delivery.PublishRequest(
            kind="layer",
            plan_id=issue,
            run_id=resolved_run_id,
            trigger_run_id=run_id,
        )
    )
    result = published.layer
    if result is None:
        raise ValueError("layer publish returned no layer detail")
    if result.cascade is None:
        linear_agent.emit_pr_opened(
            repo_root,
            pr_number=result.pr.number,
            pr_url=result.pr.url,
            branch=result.branch,
            environ=os.environ,
        )
    published_head = result.published_head_sha
    if published_head is None:
        raise ValueError("real layer publish returned no published head")
    mergeable, conflicts = _probe_mergeability(
        repo_root, base=result.parent_branch, branch=published_head
    )
    return PrSubmitResult(
        pr=result.pr,
        branch=result.branch,
        issue=published.plan_id,
        header_update=result.header_update,
        plan_embedded=result.plan_embedded,
        pr_checked=result.pr_checked,
        dry_run=False,
        base=result.parent_branch,
        mergeable=mergeable,
        conflicts=conflicts,
        delivery="stacked",
        stack_number=result.stack_number,
        stack_size=result.stack_size,
        stack_position=result.stack_position,
        operation_id=result.operation_id,
        operation=result.cascade,
    )


def _probe_mergeability(
    repo_root: Path, *, base: str, branch: str
) -> tuple[bool | None, tuple[str, ...]]:
    """Map the local merge-conflict probe to submit's tri-state mergeability (fail-open).

    ``determined=False`` → ``(None, ())`` (probe skipped/undetermined); ``determined=True`` →
    ``(probe.mergeable, probe.conflicts)``. The verdict is taken from the probe's authoritative
    ``mergeable`` field (the exit code), NOT derived from ``conflicts`` being empty — a determined
    conflict exit whose paths failed to parse still carries ``mergeable=False`` (conflicts present,
    paths unparsed) and must not be mistaken for clean. The helper already swallows git failures,
    but the call is guarded too so nothing here can sink the submit.
    """
    try:
        probe = git.detect_merge_conflicts(repo_root, base=base, branch_ref=branch)
    except git.GitError:
        return None, ()
    if not probe.determined:
        return None, ()
    return probe.mergeable, probe.conflicts


def _safe_plan_body(*, issue: str, repo_root: Path) -> str | None:
    """Fetch the verbatim plan markdown for the `<details>` embed. Best-effort: any GitHub
    failure degrades to `None` (no embed) rather than sinking the submit."""
    try:
        backend = resolve.resolve_issue_backend(repo_root)
        return backend.get_plan_body(issue_id=issue)
    except IssueBackendError:
        return None


def _compose_pr_body(
    *, issue: str, plan_body: str | None = None, pr_number: int | None = None
) -> str:
    """Compose the GitHub PR body: closing keyword + plan link + a best-effort
    `<details>` embed of the verbatim plan + the checkout footer.

    The two-target split: this HTML-enhanced body goes ONLY into the GitHub PR body (the
    `<details>` embed is fine here). The **footer** (not the embed) must stay a plain-backtick line
    carrying the **PR** number `gh pr checkout <pr_number>` — the issue number fails
    `validate_pr_body` (the create-then-update fix for the latent issue-numbered-footer bug). The
    squash commit message is the OTHER target (plain text), set at land.

    Closing-keyword invariant: this incremental composition is fixed (exactly one
    `Closes #<plan>` + plan link + embed + footer), while stacked composition is owned by the
    Publish engine. Both create-then-update passes **overwrite** any pre-created PR body; the
    land-side squash footer is equally fixed — there is no seam for extra closing keywords. A PR
    that must close an additional issue needs a **post-submit** edit on the first turn after
    `/submit` (the door terminates its own turn): read the body via `gh pr view`, insert the
    extra `Closes #N` beside the existing one, write back via `gh pr edit --body-file` — and
    track it as an explicit todo before calling `/submit` so it survives the turn boundary.
    """
    parts = [f"Closes #{issue}", f"Plan: #{issue}"]
    if plan_body:
        parts.append(f"<details><summary>Plan #{issue}</summary>\n\n{plan_body}\n\n</details>")
    if pr_number is not None:
        parts.append(f"`gh pr checkout {pr_number}`")
    return "\n\n".join(parts) + "\n"


class SubmitPrOut(OutputModel):
    """The serialization boundary of the picked :class:`github.PullRequest` subset
    (field order load-bearing)."""

    number: int
    url: str
    is_draft: bool
    existed: bool

    @classmethod
    def from_domain(cls, pr: github.PullRequest) -> "SubmitPrOut":
        return cls(number=pr.number, url=pr.url, is_draft=pr.is_draft, existed=pr.existed)


class StackRefOut(OutputModel):
    """The native-stack facts of a stacked submit (field order load-bearing): the stack
    number, its total size, and this PR's 1-based bottom→top position."""

    number: int
    size: int
    position: int


class SyncedLayerOut(OutputModel):
    """One affected suffix layer in the delivery-operation block."""

    node_id: str
    plan_id: str
    branch: str
    pr_number: int
    before_sha: str
    after_sha: str

    @classmethod
    def from_domain(cls, layer: delivery.SyncResult.Layer) -> "SyncedLayerOut":
        return cls(
            node_id=layer.node_id,
            plan_id=layer.plan_id,
            branch=layer.branch,
            pr_number=layer.pr_number,
            before_sha=layer.before_sha,
            after_sha=layer.after_sha,
        )


class DeliveryOperationOut(OutputModel):
    """The typed delivery operation nested in a stacked cascade result."""

    kind: str
    operation_id: str | None
    abandoned_operation_id: str | None
    resumed: bool
    no_op: bool
    affected: tuple[SyncedLayerOut, ...]
    notes: tuple[str, ...]

    @classmethod
    def from_domain(cls, facts: delivery.SyncResult) -> "DeliveryOperationOut":
        return cls(
            kind="sync",
            operation_id=facts.operation_id,
            abandoned_operation_id=facts.abandoned_operation_id,
            resumed=facts.resumed,
            no_op=facts.no_op,
            affected=tuple(SyncedLayerOut.from_domain(layer) for layer in facts.affected),
            notes=facts.notes,
        )


class PlanHeaderUpdateOut(OutputModel):
    """The serialization boundary of the picked :class:`issue_backend.PlanHeaderUpdate` subset
    (field order load-bearing)."""

    fields_updated: tuple[str, ...]

    @classmethod
    def from_domain(cls, update: issue_backend.PlanHeaderUpdate) -> "PlanHeaderUpdateOut":
        return cls(fields_updated=update.fields_updated)


class PrSubmitOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`PrSubmitResult` (order load-bearing)."""

    success: bool
    error_type: str | None
    message: str | None
    pr: SubmitPrOut
    branch: str
    issue: str  # opaque string id at every machine boundary (contracts §8.21)
    plan_header: PlanHeaderUpdateOut
    plan_embedded: bool
    pr_checked: bool
    dry_run: bool
    base: str
    # Tri-state: bool when the probe is definitive, null when undetermined.
    mergeable: bool | None
    conflicts: tuple[str, ...]
    # Additive stacked-delivery fields (contracts.md §8.47) — all null on incremental.
    delivery: str | None
    stack: StackRefOut | None
    operation_id: str | None
    operation: DeliveryOperationOut | None

    @classmethod
    def from_domain(cls, result: PrSubmitResult) -> "PrSubmitOut":
        stack = (
            StackRefOut(
                number=result.stack_number,
                size=result.stack_size,
                position=result.stack_position,
            )
            if result.stack_number is not None
            and result.stack_size is not None
            and result.stack_position is not None
            else None
        )
        return cls(
            success=True,
            error_type=None,
            message=None,
            pr=SubmitPrOut.from_domain(result.pr),
            branch=result.branch,
            issue=result.issue,
            plan_header=PlanHeaderUpdateOut.from_domain(result.header_update),
            plan_embedded=result.plan_embedded,
            pr_checked=result.pr_checked,
            dry_run=result.dry_run,
            base=result.base,
            mergeable=result.mergeable,
            conflicts=result.conflicts,
            delivery=result.delivery,
            stack=stack,
            operation_id=result.operation_id,
            operation=(
                DeliveryOperationOut.from_domain(result.operation)
                if result.operation is not None
                else None
            ),
        )


def _result_to_dict(result: PrSubmitResult) -> dict[str, object]:
    return PrSubmitOut.from_domain(result).model_dump(mode="json")


def _render_human(result: PrSubmitResult) -> None:
    if result.dry_run:
        user_output(click.style("pr submit --dry-run (no push, no GitHub writes)", dim=True))
        user_output(f"  branch={result.branch}  base-plan=#{result.issue}")
        user_output(f"  would set plan-header: {', '.join(result.header_update.fields_updated)}")
        return
    verb = "Found existing" if result.pr.existed else "Opened draft"
    embed = "plan embedded" if result.plan_embedded else "no plan embed"
    user_output(
        click.style("✓ ", fg="green")
        + f"{verb} PR "
        + click.style(f"#{result.pr.number}", fg="cyan")
        + f" → {result.pr.url} ({embed}; footer checked)"
    )
    if result.delivery == "stacked":
        if result.stack_number is not None:
            user_output(
                click.style(
                    f"  stacked: layer {result.stack_position}/{result.stack_size} "
                    f"in stack #{result.stack_number} → targets {result.base}",
                    dim=True,
                )
            )
        else:
            user_output(click.style(f"  stacked layer → targets {result.base}", dim=True))
        if result.operation is not None:
            if result.operation.no_op:
                user_output("  suffix already in sync")
            else:
                for layer in result.operation.affected:
                    user_output(
                        f"  {layer.node_id} {layer.branch} (pr #{layer.pr_number}): "
                        f"{layer.before_sha} → {layer.after_sha}"
                    )
            for note in result.operation.notes:
                user_output(click.style(f"  note: {note}", dim=True))
    if result.mergeable is False:
        listing = ", ".join(result.conflicts) if result.conflicts else "(paths unavailable)"
        user_output(
            click.style(
                f"⚠ merge conflicts against {result.base}: {listing}\n"
                "  run /submit again after the conflict-resolver rebases onto the target branch",
                fg="yellow",
            )
        )
    elif result.mergeable is None:
        user_output(click.style("  mergeability not determined (probe skipped)", dim=True))
