"""`perk learn skip` — record a deliberate learn skip canonically (the cold skip door).

Stamps `learn_state: skipped` onto the plan-header via the issue backend (contracts.md §8.36) —
unless the plan is already `captured`, in which case the stamp is a no-op and the envelope reports
the kept state — then clears the local `pending-learn` marker. The warm no-summary `/learn` arm
delegates here, so a deliberate skip is never a TS-only marker-clear: a merged-but-skipped plan
reads as done from any machine.

Exit codes: 0 skipped/no-op · 1 invalid input / unauthed / no plan / plan-not-found / op failure ·
2 not-a-repo.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import click

from perk import plan
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.boundary import OutputModel
from perk.cli.commands.learn.shared import fail
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.state import cache
from perk.substrate.output import machine_output, user_output


@dataclass(frozen=True)
class LearnSkipResult:
    plan_issue: str  # the opaque plan-issue id (GitHub: "42"; Linear: "ENG-123")
    # The effective header value after the skip: "skipped", or "captured" on the
    # never-downgrade no-op arm (a capture already recorded — never resurrected).
    learn_state: str
    pending_cleared: bool
    dry_run: bool


@click.command("skip")
@click.option("--dry-run", is_flag=True, help="Compose without stamping or clearing the marker.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def skip_learn(ctx: click.Context, *, dry_run: bool, as_json: bool) -> None:
    """Record a deliberate learn skip on the plan and clear pending-learn (land → learn).

    \b
    Run from inside the plan's worktree (it reads the local cache.plan-ref).
    """
    try:
        repo_root = require_repo(ctx)
        if not dry_run:
            require_github(ctx)
        result = _learn_skip_impl(repo_root=repo_root, dry_run=dry_run)
    except IssueBackendError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="github_error",
            message=f"learn skip failed\n{exc}",
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


def _learn_skip_impl(*, repo_root: Path, dry_run: bool) -> LearnSkipResult:
    plan_ref = cache.read_plan_ref(repo_root)
    if plan_ref is None:
        raise UserFacingCliError(
            "No saved plan in this worktree\nRun /plan-save then perk implement first.",
            error_type="no_plan_ref",
        )
    issue = plan_ref.pr_id

    if dry_run:
        return LearnSkipResult(
            plan_issue=issue,
            learn_state=plan.LearnState.SKIPPED.value,
            pending_cleared=False,
            dry_run=True,
        )

    backend = resolve.resolve_issue_backend(repo_root)
    state = backend.get_plan(issue_id=issue)
    if state is None:
        raise UserFacingCliError(f"Plan issue #{issue} not found", error_type="plan_not_found")
    # Never-downgrade (contracts.md §8.36): a recorded capture stays `captured` — the skip is a
    # no-op stamp and the envelope reports the kept state. The marker is still cleared: canonical
    # state is terminal either way.
    current = state.header.get("learn_state")
    if current == plan.LearnState.CAPTURED:
        cache.clear_marker(repo_root, cache.PENDING_LEARN)
        return LearnSkipResult(
            plan_issue=issue,
            learn_state=plan.LearnState.CAPTURED.value,
            pending_cleared=True,
            dry_run=False,
        )
    # Strict stamp BEFORE the marker clear: a failed stamp propagates (exit 1) and leaves the
    # marker set — the retry signal (mirrors `learn capture`'s canonical-first invariant).
    backend.update_plan_header(
        issue_id=issue, fields={"learn_state": plan.LearnState.SKIPPED.value}
    )
    cache.clear_marker(repo_root, cache.PENDING_LEARN)
    return LearnSkipResult(
        plan_issue=issue,
        learn_state=plan.LearnState.SKIPPED.value,
        pending_cleared=True,
        dry_run=False,
    )


class LearnSkipOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`LearnSkipResult` (order load-bearing)."""

    success: bool
    error_type: str | None
    message: str | None
    plan_issue: str
    learn_state: str
    pending_cleared: bool
    dry_run: bool

    @classmethod
    def from_domain(cls, result: LearnSkipResult) -> "LearnSkipOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            plan_issue=result.plan_issue,
            learn_state=result.learn_state,
            pending_cleared=result.pending_cleared,
            dry_run=result.dry_run,
        )


def _result_to_dict(result: LearnSkipResult) -> dict[str, object]:
    return LearnSkipOut.from_domain(result).model_dump(mode="json")


def _render_human(result: LearnSkipResult) -> None:
    if result.dry_run:
        user_output(click.style("learn skip --dry-run (no stamp, no marker clear)", dim=True))
        user_output(f"  plan=#{result.plan_issue}  would stamp learn_state=skipped")
        return
    if result.learn_state == plan.LearnState.CAPTURED:
        user_output(
            click.style("✓ ", fg="green")
            + f"Plan #{result.plan_issue} already captured — kept; pending-learn cleared"
        )
        return
    user_output(
        click.style("✓ ", fg="green")
        + f"Recorded learn skip on plan #{result.plan_issue}; pending-learn cleared"
    )
