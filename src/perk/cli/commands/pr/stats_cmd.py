"""`perk pr stats` — the read-only change-stats worker.

Counts the current branch's change stats (Code / Tests / Comments / Learned docs / Other lines
added, removed and modified, via cloc) over ``merge-base(<base>, HEAD)..HEAD`` — the same facts
`perk pr submit` writes into the PR body. Base: ``--base``, else the local ``cache.plan-ref``
base, else the repository trunk. Offline by default (``origin/<base>`` when it resolves locally,
else the local ``<base>``); ``--fetch`` refreshes ``origin/<base>`` first, reproducing
publication's fresh-remote semantics. No ``gh`` call, no mutation.

Supervisor surface: `--json` to stdout, human text to stderr, stable exit codes.
Exit codes: 0 ok · 1 stats unavailable (cloc missing / failed, range unresolved, git failed) ·
2 not-a-repo.
"""

from dataclasses import dataclass
from pathlib import Path

import click

from perk.boundary import OutputModel
from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.delivery import change_stats
from perk.delivery.change_stats import ChangeStats, ChangeStatsOut
from perk.state import cache
from perk.substrate import git
from perk.substrate.output import user_output


@dataclass(frozen=True)
class PrStatsResult:
    base_ref: str
    stats: ChangeStats


class PrStatsOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`PrStatsResult` (order load-bearing)."""

    success: bool
    error_type: str | None
    message: str | None
    base_ref: str
    stats: ChangeStatsOut

    @classmethod
    def from_domain(cls, result: PrStatsResult) -> "PrStatsOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            base_ref=result.base_ref,
            stats=ChangeStatsOut.from_domain(result.stats),
        )


@click.command("stats")
@click.option(
    "--base",
    default=None,
    help="The branch to diff against (default: the plan-ref base, else the trunk).",
)
@click.option(
    "--fetch", is_flag=True, help="Fetch origin/<base> first (publication's fresh-remote view)."
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def stats_pr(ctx: click.Context, *, base: str | None, fetch: bool, as_json: bool) -> None:
    """Count this branch's change stats with cloc (read-only; what `pr submit` reports).

    \b
    Rows: Code, Tests, Comments, Learned docs, Other — lines added / removed / modified.
    """
    try:
        repo_root = require_repo(ctx)
        result = _impl(repo_root=repo_root, base=base, fetch=fetch)
    except change_stats.ChangeStatsUnavailable as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.kind,
            message=f"change stats unavailable\n{exc.message}",
        )
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    emit(as_json=as_json, payload=_result_to_dict(result), render=lambda: _render_human(result))


def _impl(*, repo_root: Path, base: str | None, fetch: bool) -> PrStatsResult:
    chosen = _resolve_base(repo_root, base)
    rng = change_stats.resolve_range(repo_root, base=chosen, fetch=fetch)
    stats = change_stats.summarize(repo_root, rng.base, rng.head)
    return PrStatsResult(base_ref=rng.base_ref, stats=stats)


def _resolve_base(repo_root: Path, base: str | None) -> str:
    """``--base`` > the local plan-ref base > the trunk (all local reads)."""
    if base is not None and base.strip():
        return base.strip()
    plan_ref = cache.read_plan_ref(repo_root)
    if plan_ref is not None and plan_ref.base and plan_ref.base.strip():
        return plan_ref.base.strip()
    return git.detect_trunk_branch(repo_root)


def _result_to_dict(result: PrStatsResult) -> dict[str, object]:
    return PrStatsOut.from_domain(result).model_dump(mode="json")


def _render_human(result: PrStatsResult) -> None:
    stats = result.stats
    user_output(
        click.style("change stats", fg="cyan")
        + f" vs {result.base_ref} ({stats.base[:7]}..{stats.head[:7]})"
    )
    for line in change_stats.render_lines(stats):
        user_output(f"  {line}")
