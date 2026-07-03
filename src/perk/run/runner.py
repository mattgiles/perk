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

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from perk import github
from perk.boundary import LenientParseModel
from perk.state import run_id as run_id_mod

# The workflow filename the artifact MUST be named (locked here, built there). The
# GitHub Actions runner triggers this workflow; its `run-name` must embed `${{ inputs.run_id }}`
# so the dispatcher can verify the run by discovery (contracts.md §8.13).
GITHUB_ACTIONS_WORKFLOW = "perk-run.yml"

# The smoke-test sentinel stage (contracts.md §8.19). Dispatched by `perk doctor workflow
# smoke-test` with no dispatch record; discovery filters it out so smoke runs never surface
# through the supervisor read surfaces.
SMOKE_STAGE = "smoke"

# The managed workflow's rendered run-name (workflow_artifacts.PERK_RUN_WORKFLOW pins
# `run-name: "perk ${{ inputs.stage }} · plan #${{ inputs.plan }} · ${{ inputs.run_id }}"`).
# This regex and that template are pinned to each other — the run-name IS the canonical
# remote-run existence record (contracts.md §8.13), so a template change must ripple here.
_RUN_NAME_RE = re.compile(r"^perk (?P<stage>\S+) · plan #(?P<plan>\S+) · (?P<run_id>\S+)$")


def utc_now_iso() -> str:
    """The current time as ISO-8601 UTC, for the dispatch record's ``dispatched_at``."""
    return datetime.now(UTC).isoformat()


class RunnerError(Exception):
    """A runner could not dispatch/verify (or observe/cancel) a run."""


@dataclass(frozen=True)
class RunHandle:
    """The opaque, runner-side handle a successful (verified) ``dispatch`` returns.

    ``run_ref`` is the runner-native run id (the GitHub Actions numeric id, as a string) — the
    handle stored *inside* the dispatch record; it is **not** the perk ``run_id``. The JSON
    boundary is :class:`RunHandleModel` (the dispatch cache's nested ``run_handle``).
    """

    runner: str  # the runner ref the dispatch was routed to ("" => default)
    kind: str  # the runner kind discriminator ("github-actions")
    run_ref: str  # the runner-native run id
    url: str  # the human run URL


class RunHandleModel(LenientParseModel):
    """The JSON parse/serialize boundary for :class:`RunHandle` (the dispatch cache's nested
    ``run_handle``). Field order matches :class:`RunHandle` for byte-stable serialization."""

    runner: str
    kind: str
    run_ref: str
    url: str

    def to_domain(self) -> RunHandle:
        """Convert the validated model into the frozen domain object."""
        return RunHandle(runner=self.runner, kind=self.kind, run_ref=self.run_ref, url=self.url)

    @classmethod
    def from_domain(cls, handle: RunHandle) -> "RunHandleModel":
        """Project the frozen :class:`RunHandle` onto the serialization boundary."""
        return cls(runner=handle.runner, kind=handle.kind, run_ref=handle.run_ref, url=handle.url)


@dataclass(frozen=True)
class ParsedRunName:
    """The three fields the managed run-name template embeds (stage / plan id / perk run_id)."""

    stage: str
    plan_id: str
    run_id: str


def parse_run_name(title: str) -> ParsedRunName | None:
    """Parse a rendered run-name back into its embedded fields; ``None`` when the title does not
    match the managed template or the token is not a valid perk ``run_id`` (ULID)."""
    match = _RUN_NAME_RE.match(title)
    if match is None:
        return None
    token = match.group("run_id")
    if not run_id_mod.is_run_id(token):
        return None
    return ParsedRunName(stage=match.group("stage"), plan_id=match.group("plan"), run_id=token)


@dataclass(frozen=True)
class DiscoveredRun:
    """A remote run reconstructed from the runner's canonical enumeration (contracts.md §8.13):
    the run-name's parsed fields + the runner-side state and handle."""

    run_id: str
    stage: str
    plan_id: str
    dispatched_at: str  # the run's created_at (ISO-8601) — the discovery-side dispatch time
    status: str
    conclusion: str | None
    handle: RunHandle


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
    failure. ``observe``/``cancel``/``retry`` operate on a previously-returned ``RunHandle``.
    ``discover`` enumerates the runner's perk runs from the canonical remote source (each runner
    owns its run-name/token convention), newest-first — the existence read the supervisor
    surfaces rest on (contracts.md §8.13/§8.17).
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

    def discover(self, *, repo_root: Path, limit: int) -> list[DiscoveredRun]: ...


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

    def discover(self, *, repo_root: Path, limit: int) -> list[DiscoveredRun]:
        try:
            listings = github.list_workflow_runs(
                workflow=GITHUB_ACTIONS_WORKFLOW, repo_root=repo_root, limit=limit
            )
        except github.GitHubError as exc:
            raise RunnerError(str(exc)) from exc
        discovered: list[DiscoveredRun] = []
        for listing in listings:  # newest-first, order preserved
            parsed = parse_run_name(listing.title)
            if parsed is None or parsed.stage == SMOKE_STAGE:
                continue  # foreign/renamed runs and smoke-test sentinels are not perk runs
            discovered.append(
                DiscoveredRun(
                    run_id=parsed.run_id,
                    stage=parsed.stage,
                    plan_id=parsed.plan_id,
                    dispatched_at=listing.created_at,
                    status=listing.run.status,
                    conclusion=listing.run.conclusion,
                    handle=RunHandle(
                        runner=self.ref,
                        kind=self.kind,
                        run_ref=listing.run.id,
                        url=listing.run.url,
                    ),
                )
            )
        return discovered


def select_runner(ref: str) -> Runner:
    """Select the runner for a dispatch ref. There is exactly one runner today, so any ref yields
    a ``GitHubActionsRunner`` carrying the ref — the "keep future runners open" seam (the ref is
    recorded in the dispatch record; routing it to a runner *kind* is a later concern)."""
    return GitHubActionsRunner(ref)
