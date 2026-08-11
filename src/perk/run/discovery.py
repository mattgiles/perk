"""Canonical remote-run discovery (contracts.md §8.13/§8.17).

The GHA run listing — via the managed run-name (``perk {stage} · plan #{plan} · {run_id}``) — is
the **existence source** for remote runs; the local ``scratch/runs/<run_id>/dispatch.json`` record
is a cache/correlation accelerator. This module is the thin orchestration seam the supervisor
surfaces (``perk workflow run list``/``cancel``/``retry``, the ``perk objective run`` gate) call
to reach that source. It sits **above** both ``perk.state.cache`` and ``perk.run.runner``
(``cache`` imports ``runner``, so the layer that needs both must be a sibling, not live in
``runner``). Reconstruction is in-memory per command — discovery never writes back into
``.perk/workflow/`` (a read never mutates the cache; the control surfaces keep §8.18's
no-local-mutation rule).
"""

from pathlib import Path

from perk import github
from perk.run import runner


def discover_runs(repo_root: Path, *, limit: int = 100) -> list[runner.DiscoveredRun]:
    """Enumerate the remote perk runs, newest-first (a single page — at most ``limit``/100 runs).

    Exactly one runner exists today, so discovery asks the default runner; widening to multiple
    registered runners means enumerating each and merging here. Propagates ``RunnerError`` —
    each caller picks its fail-soft/hard posture.
    """
    return runner.select_runner("").discover(repo_root=repo_root, limit=limit)


def active_writer_plan_ids(
    repo_root: Path,
    plan_ids: list[str],
    *,
    exclude_run_id: str | None = None,
    exclude_plan_id: str | None = None,
) -> frozenset[str]:
    """The plan ids (of ``plan_ids``) currently held by an ACTIVE remote writer — a queued or
    in-progress perk run whose managed run-name names that plan (contracts.md §8.49).

    ``exclude_run_id`` + ``exclude_plan_id`` omit exactly the submit-triggering remote run
    on its corroborated plan: its committed work is already the cascade trigger, while every
    other active writer must still block. Neither field excludes anything alone. The dirty tree
    gate upstream refuses uncommitted invoking state.

    Uses the SERVER-side status filter (one call per status) so active runs can never be
    displaced off a newest-first page by completed runs; the single-page 100-cap then bounds
    *simultaneously active* runs — an honest bound. Propagates ``GitHubError`` — the sync
    caller maps any failure to its fail-closed ``writer_observation_unavailable`` refusal
    (an unreadable observation is never "no active writer").
    """
    wanted = {p.removeprefix("#") for p in plan_ids}
    active: set[str] = set()
    for status in ("queued", "in_progress"):
        listings = github.list_workflow_runs(
            workflow=runner.GITHUB_ACTIONS_WORKFLOW, repo_root=repo_root, status=status
        )
        for listing in listings:
            parsed = runner.parse_run_name(listing.title)
            if parsed is None:
                continue
            plan = parsed.plan_id.removeprefix("#")
            if (
                exclude_run_id is not None
                and exclude_plan_id is not None
                and parsed.run_id == exclude_run_id
                and plan == exclude_plan_id.removeprefix("#")
            ):
                continue
            if plan in wanted:
                active.add(plan)
    return frozenset(active)


def find_discovered_run(
    repo_root: Path, run_id: str, *, limit: int = 100
) -> runner.DiscoveredRun | None:
    """The discovered run whose parsed ``run_id`` token matches exactly, or ``None``."""
    for run in discover_runs(repo_root, limit=limit):
        if run.run_id == run_id:
            return run
    return None
