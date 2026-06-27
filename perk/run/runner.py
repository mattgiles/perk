"""The runner-agnostic dispatch contract (contracts.md §8.13).

A `--remote` launch of a drivable stage (`implement`/`address`) is a **real drive**: mint a
perk ``run_id``, persist the dispatch intent as a durable ``run_id → plan`` linkage record
(``cache.write_dispatch``), read it back to verify it established (the §8.2 establish-before-
consume discipline), then **trigger** a runner. This module is the runner library — the
runner-agnostic ``Runner`` `Protocol` plus its first (and currently only) implementation,
``GitHubActionsRunner``. No CLI, no Click here; the drive lives in ``perk/run/launch/remote.py``.

The perk ``run_id`` (a ULID, ``perk/state/run_id.py``) is the canonical, runner-agnostic correlation
key and is *itself* the run-discovery token: it is a workflow input and is embedded in the
runner-side ``run-name`` so a dispatch can verify-by-discovery. The runner-native run id (GitHub
Actions' numeric id) is a *separate* handle stored inside the ``RunHandle`` — never conflate them.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from perk import github
from perk.boundary import StrictBoundaryModel

# The workflow filename the artifact MUST be named (locked here, built there). The
# GitHub Actions runner triggers this workflow; its `run-name` must embed `${{ inputs.run_id }}`
# so the dispatcher can verify the run by discovery (contracts.md §8.13).
GITHUB_ACTIONS_WORKFLOW = "perk-run.yml"


def utc_now_iso() -> str:
    """The current time as ISO-8601 UTC, for the dispatch record's ``dispatched_at``."""
    return datetime.now(UTC).isoformat()


class RunnerError(Exception):
    """A runner could not dispatch/verify (or observe/cancel) a run."""


class RunHandle(StrictBoundaryModel):
    """The opaque, runner-side handle a successful (verified) ``dispatch`` returns.

    ``run_ref`` is the runner-native run id (the GitHub Actions numeric id, as a string) — the
    handle stored *inside* the dispatch record; it is **not** the perk ``run_id``. JSON-stable via
    ``model_dump(mode="json")`` / ``model_validate``.
    """

    runner: str  # the runner ref the dispatch was routed to ("" => default)
    kind: str  # the runner kind discriminator ("github-actions")
    run_ref: str  # the runner-native run id
    url: str  # the human run URL


@dataclass(frozen=True)
class RunObservation:
    """The result of ``observe``: a runner-agnostic snapshot of a dispatched run's state."""

    status: str  # "queued" | "in_progress" | "completed" | "unknown"
    conclusion: str | None  # "success" | "failure" | "cancelled" | … | None
    url: str


class Runner(Protocol):
    """The runner-agnostic dispatch contract (contracts.md §8.13).

    ``dispatch`` triggers a run and returns a **verified** handle (the runner-side run was
    discovered and matched to ``run_id``); it raises ``RunnerError`` on a trigger/discovery
    failure. ``observe``/``cancel``/``retry`` operate on a previously-returned ``RunHandle`` — they
    are implemented (not stubbed) so the contract is validated end-to-end and Nodes 3.1/3.2 consume
    settled shapes (the supervisor *command surfaces* are those later nodes' work, not this one).
    """

    kind: str

    def dispatch(
        self,
        *,
        stage: str,
        plan_ref: dict[str, Any],
        run_id: str,
        base: str,
        repo_root: Path,
    ) -> RunHandle: ...

    def observe(self, handle: RunHandle, *, repo_root: Path) -> RunObservation: ...

    def cancel(self, handle: RunHandle, *, repo_root: Path) -> None: ...

    def retry(self, handle: RunHandle, *, failed_only: bool, repo_root: Path) -> None: ...


class GitHubActionsRunner:
    """The first ``Runner`` implementation: dispatch a stage to GitHub Actions (``kind =
    "github-actions"``)."""

    kind = "github-actions"

    def __init__(self, ref: str = "") -> None:
        # The runner ref the dispatch is routed to ("" => the default runner). Carried into the
        # dispatch record + the handle; future routing (a model/profile registry) is a later
        # concern — do not wire it to model here.
        self.ref = ref

    def dispatch(
        self,
        *,
        stage: str,
        plan_ref: dict[str, Any],
        run_id: str,
        base: str,
        repo_root: Path,
    ) -> RunHandle:
        pr_id = str(plan_ref.get("pr_id", "")).strip()
        inputs = {"run_id": run_id, "stage": stage, "plan": pr_id, "base": base}
        try:
            wr = github.trigger_workflow(
                repo_root=repo_root,
                workflow=GITHUB_ACTIONS_WORKFLOW,
                inputs=inputs,
                ref=github.default_branch(repo_root),
                match_token=run_id,
            )
        except github.GitHubError as exc:
            raise RunnerError(str(exc)) from exc
        return RunHandle(runner=self.ref, kind=self.kind, run_ref=wr.id, url=wr.url)

    def observe(self, handle: RunHandle, *, repo_root: Path) -> RunObservation:
        try:
            wr = github.get_workflow_run(run_id=handle.run_ref, repo_root=repo_root)
        except github.GitHubError as exc:
            raise RunnerError(str(exc)) from exc
        if wr is None:
            return RunObservation(status="unknown", conclusion=None, url=handle.url)
        return RunObservation(status=wr.status, conclusion=wr.conclusion, url=wr.url or handle.url)

    def cancel(self, handle: RunHandle, *, repo_root: Path) -> None:
        try:
            github.cancel_workflow_run(run_id=handle.run_ref, repo_root=repo_root)
        except github.GitHubError as exc:
            raise RunnerError(str(exc)) from exc

    def retry(self, handle: RunHandle, *, failed_only: bool, repo_root: Path) -> None:
        try:
            github.rerun_workflow_run(
                run_id=handle.run_ref, repo_root=repo_root, failed_only=failed_only
            )
        except github.GitHubError as exc:
            raise RunnerError(str(exc)) from exc


def select_runner(ref: str) -> Runner:
    """Select the runner for a dispatch ref. There is exactly one runner today, so any ref yields
    a ``GitHubActionsRunner`` carrying the ref — the "keep future runners open" seam (the ref is
    recorded in the dispatch record; routing it to a runner *kind* is a later concern)."""
    return GitHubActionsRunner(ref)
