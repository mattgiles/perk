"""``perk run-worker`` — the runner-side positioning + headless drive (Node 2.2; contracts §8.14).

The CI entrypoint the managed ``perk-run.yml`` workflow invokes after it checks out the plan
branch. It is the runner's positioning job (Gap 7): reconstruct the ``cache.plan-ref`` from the
plan's GitHub state, materialize the handoff/plan-ref/plan-body into the checkout's
``.pi/workflow/``, then spawn the Node headless worker (``extension/workerMain.ts``, Node 1.2) for
the dispatched stage with ``PERK_RUN_ID`` in the env. The worker inherits the prepared worktree and
never re-mints.

Deterministic exterior command (no agentic reasoning): it positions and drives. Model/auth
resolution is the Node worker's job (env-var key resolution, Gap 5). The worker owns stdout (its
structured ``RunOutcome`` JSON) + the exit code; this command only reports positioning progress to
stderr and forwards the worker's exit code.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from perk import cache, github, launch, resume, run_report
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.init import GIT_PACKAGE
from perk.output import user_output
from perk.registry import Stage, load_registry

# The cold remote door: only stages that declare it are remotely drivable (implement/address).
DRIVABLE_DOOR = "cold_remote"

# A belt-and-suspenders Python-side bound above the workflow's own `timeout-minutes` (the worker's
# budget watchdog is the real bound; the workflow job timeout is the outer one).
WORKER_TIMEOUT_S = 90 * 60


@dataclass(frozen=True)
class WorkerEntry:
    """The resolved Node worker entrypoint + how it was found (for the progress line)."""

    path: Path
    source: str  # "env" | "self" | "consumer-git" | "consumer-npm"


def _drivable_stage(stage_id: str) -> Stage:
    """Resolve a remotely-drivable stage from the registry, or raise ``stage_not_drivable``."""
    stage = next((s for s in load_registry().stages if s.id == stage_id), None)
    if stage is None:
        raise UserFacingCliError(f"unknown stage {stage_id!r}", error_type="stage_not_drivable")
    if stage.doors.get(DRIVABLE_DOOR) is not True:
        raise UserFacingCliError(
            f"stage {stage_id!r} is not remotely drivable (it has no cold_remote door).",
            error_type="stage_not_drivable",
        )
    return stage


def _git_clone_worker_entry(repo_root: Path) -> Path:
    """The worker entrypoint inside pi's git-package clone, derived from ``GIT_PACKAGE``.

    pi clones a ``git:`` package to ``.pi/git/<host>/<path>`` (docs/packages.md). Deriving the path
    from ``GIT_PACKAGE`` (rather than hardcoding segments) keeps the resolver in lockstep with the
    package URL — a URL change cannot silently desync this candidate.
    """
    remainder = GIT_PACKAGE.removeprefix("git:")
    clone = repo_root / ".pi" / "git"
    for segment in remainder.split("/"):
        clone = clone / segment
    return clone / "extension" / "workerMain.ts"


def resolve_worker_entry(repo_root: Path, environ: dict[str, str]) -> WorkerEntry:
    """Locate ``workerMain.ts``: the ``PERK_WORKER_ENTRY`` override, else the self-repo path, else
    the consumer git-package clone under ``.pi/git/<host>/<path>``, else the consumer npm install
    under ``.pi/npm/node_modules/@perk/pi``. A miss is loud, never silent."""
    override = (environ.get("PERK_WORKER_ENTRY") or "").strip()
    if override:
        path = Path(override)
        if path.is_file():
            return WorkerEntry(path=path, source="env")
        raise UserFacingCliError(
            f"PERK_WORKER_ENTRY={override!r} does not point at a file.",
            error_type="worker_entry_missing",
        )
    candidates: list[tuple[Path, str]] = [
        (repo_root / "extension" / "workerMain.ts", "self"),
        (_git_clone_worker_entry(repo_root), "consumer-git"),
        (
            repo_root
            / ".pi"
            / "npm"
            / "node_modules"
            / "@perk"
            / "pi"
            / "extension"
            / "workerMain.ts",
            "consumer-npm",
        ),
    ]
    for path, source in candidates:
        if path.is_file():
            return WorkerEntry(path=path, source=source)
    checked = ", ".join(str(p) for p, _ in candidates)
    raise UserFacingCliError(
        f"could not locate the Node worker entrypoint (checked {checked}). "
        "Set PERK_WORKER_ENTRY to extension/workerMain.ts.",
        error_type="worker_entry_missing",
    )


def position_worktree(
    repo_root: Path, *, run_id: str, stage: Stage, plan_ref: dict[str, Any]
) -> None:
    """Materialize the worktree the Node worker consumes (handoff + plan-ref + plan-body).

    Mirrors the cold-local positioning in ``launch.launch_stage`` (the worktree *is* the checkout
    here, so cwd = ``repo_root``). The worker reads the plan-ref to seed its prompt and the handoff
    ``mode`` to set tool gating; it never re-writes them.
    """
    cache.ensure_layout(repo_root)
    cache.write_handoff(repo_root, run_id, {"stage": stage.id, "mode": stage.mode})
    cache.write_plan_ref(repo_root, plan_ref)
    launch.materialize_plan_body(repo_root, repo_root, plan_ref)


def _spawn_worker(
    entry: Path, *, stage_id: str, worktree: Path, run_id: str, environ: dict[str, str]
) -> int:
    """Spawn ``node <entry> <stage> --worktree <worktree>`` with ``PERK_RUN_ID`` in the env.

    Inherits stdio so the worker owns stdout (its ``RunOutcome`` JSON) + stderr; returns the exit
    code. Routed through one wrapper so tests can monkeypatch the spawn.
    """
    argv = ["node", str(entry), stage_id, "--worktree", str(worktree)]
    env = {**environ, "PERK_RUN_ID": run_id}
    try:
        proc = subprocess.run(argv, check=False, cwd=worktree, env=env, timeout=WORKER_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise UserFacingCliError(
            f"the Node worker exceeded {WORKER_TIMEOUT_S}s and was killed.",
            error_type="worker_timeout",
        ) from exc
    except FileNotFoundError as exc:
        raise UserFacingCliError(
            "node was not found on PATH — the composite setup action installs it.",
            error_type="node_missing",
        ) from exc
    return proc.returncode


def run_worker(
    *,
    repo_root: Path,
    run_id: str,
    stage_id: str,
    plan: int,
    base: str | None,
    environ: dict[str, str],
) -> int:
    """Position the checkout and drive the dispatched stage headlessly; return the worker exit code.

    ``base`` is accepted (it is part of the §8.13 input contract and recorded by the dispatcher) but
    not consumed here — the plan branch is already checked out by the workflow; it is carried for
    parity + future use (e.g. rebase-on-conflict, a later node).
    """
    stage = _drivable_stage(stage_id)
    try:
        state = github.get_plan(number=plan, repo_root=repo_root)
    except GitHubError as exc:
        raise UserFacingCliError(
            f"run-worker failed to resolve plan #{plan}\n{exc}", error_type="github_error"
        ) from exc
    if state is None:
        raise UserFacingCliError(f"Plan issue #{plan} not found", error_type="plan_not_found")
    plan_ref = resume.reconstruct_plan_ref(state)

    user_output(
        f"run-worker: positioning {stage.id} for plan #{plan} "
        f"(run_id={run_id}, base={base or '<unset>'})"
    )
    position_worktree(repo_root, run_id=run_id, stage=stage, plan_ref=plan_ref)
    entry = resolve_worker_entry(repo_root, environ)
    user_output(f"run-worker: worker entry={entry.path} ({entry.source})")
    run_report.report_started(repo_root, run_id=run_id, stage=stage.id, plan=plan, environ=environ)
    code = _spawn_worker(
        entry.path, stage_id=stage.id, worktree=repo_root, run_id=run_id, environ=environ
    )
    user_output(f"run-worker: worker exited {code}")
    run_report.report_terminal(
        repo_root, run_id=run_id, stage=stage.id, plan=plan, exit_code=code, environ=environ
    )
    return code
