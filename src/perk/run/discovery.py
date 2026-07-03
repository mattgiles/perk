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

from perk.run import runner


def discover_runs(repo_root: Path, *, limit: int = 100) -> list[runner.DiscoveredRun]:
    """Enumerate the remote perk runs, newest-first (a single page — at most ``limit``/100 runs).

    Exactly one runner exists today, so discovery asks the default runner; widening to multiple
    registered runners means enumerating each and merging here. Propagates ``RunnerError`` —
    each caller picks its fail-soft/hard posture.
    """
    return runner.select_runner("").discover(repo_root=repo_root, limit=limit)


def find_discovered_run(
    repo_root: Path, run_id: str, *, limit: int = 100
) -> runner.DiscoveredRun | None:
    """The discovered run whose parsed ``run_id`` token matches exactly, or ``None``."""
    for run in discover_runs(repo_root, limit=limit):
        if run.run_id == run_id:
            return run
    return None
