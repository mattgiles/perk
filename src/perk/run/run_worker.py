"""``perk run-worker`` — the runner-side positioning + headless drive (contracts §8.14).

The CI entrypoint the managed ``perk-run.yml`` workflow invokes after it checks out the plan
branch. It is the runner's positioning job: reconstruct the ``cache.plan-ref`` from the
plan's GitHub state, materialize the handoff/plan-ref/plan-body into the checkout's
``.perk/workflow/``, deliver ``.agents/skills/`` via the skills-CLI sync (fatal — no skills, no
drive), then spawn the Node headless worker (``extension/workerMain.ts``) for the dispatched stage
with ``PERK_RUN_ID`` in the env. The worker inherits the prepared worktree and never re-mints.

Deterministic exterior command (no agentic reasoning): it positions and drives. Model/auth
resolution is the Node worker's job (env-var key resolution). The worker owns stdout (its
structured ``RunOutcome`` JSON) + the exit code; this command only reports positioning progress to
stderr and forwards the worker's exit code.
"""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from perk import plan
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import agent as linear_agent
from perk.cli.ensure import UserFacingCliError
from perk.convergence import init
from perk.convergence.init.extension_install import (
    consumer_npm_install_root,
    consumer_perk_package_dir,
)
from perk.run import launch, resume, run_report
from perk.state import cache
from perk.substrate.output import user_output
from perk.substrate.registry import Stage, load_registry

# The cold remote door: only stages that declare it are remotely drivable (implement/address).
DRIVABLE_DOOR = "cold_remote"

# A belt-and-suspenders Python-side bound above the workflow's own `timeout-minutes` (the worker's
# budget watchdog is the real bound; the workflow job timeout is the outer one).
WORKER_TIMEOUT_S = 90 * 60


@dataclass(frozen=True)
class WorkerEntry:
    """The resolved Node worker entrypoint + how it was found (for the progress line)."""

    path: Path
    source: str  # "env" | "self" | "consumer-npm"


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


def _stage_consumer_entry(repo_root: Path, package_dir: Path) -> Path:
    """Re-home the npm-installed perk package outside ``node_modules``; return the staged entry.

    Node's built-in type stripping hard-refuses ``.ts`` files under any ``node_modules`` directory
    (``ERR_UNSUPPORTED_NODE_MODULES_TYPE_STRIPPING``), so the consumer entry cannot be spawned in
    place. The whole package is copied (fresh on every resolve, so a reinstalled package never
    leaves a stale copy) to keep its package-root-relative resources (``shared/``, ``prompts/``,
    ``package.json``) reachable; bare imports still resolve by walking up to
    ``.pi/npm/node_modules`` — where the composite's worker-deps step installs the pi SDK whose
    real deps close the worker's import set (contracts.md §8.14).
    """
    staged_root = consumer_npm_install_root(repo_root) / "perk-worker"
    if staged_root.exists():
        shutil.rmtree(staged_root)
    shutil.copytree(package_dir, staged_root, ignore=shutil.ignore_patterns("node_modules"))
    return staged_root / "extension" / "workerMain.ts"


def resolve_worker_entry(repo_root: Path, environ: dict[str, str]) -> WorkerEntry:
    """Locate ``workerMain.ts``: the ``PERK_WORKER_ENTRY`` override, else the self-repo path, else
    the consumer npm install under ``.pi/npm/node_modules/@mgiles/perk`` — staged outside
    ``node_modules`` via ``_stage_consumer_entry`` so plain ``node`` can type-strip it. A miss is
    loud, never silent."""
    override = (environ.get("PERK_WORKER_ENTRY") or "").strip()
    if override:
        path = Path(override)
        if path.is_file():
            return WorkerEntry(path=path, source="env")
        raise UserFacingCliError(
            f"PERK_WORKER_ENTRY={override!r} does not point at a file.",
            error_type="worker_entry_missing",
        )
    self_entry = repo_root / "extension" / "workerMain.ts"
    if self_entry.is_file():
        return WorkerEntry(path=self_entry, source="self")
    package_dir = consumer_perk_package_dir(repo_root)
    if (package_dir / "extension" / "workerMain.ts").is_file():
        return WorkerEntry(
            path=_stage_consumer_entry(repo_root, package_dir), source="consumer-npm"
        )
    checked = ", ".join(str(p) for p in (self_entry, package_dir / "extension" / "workerMain.ts"))
    raise UserFacingCliError(
        f"could not locate the Node worker entrypoint (checked {checked}). "
        "Set PERK_WORKER_ENTRY to extension/workerMain.ts.",
        error_type="worker_entry_missing",
    )


def _deliver_skills(repo_root: Path) -> None:
    """Populate ``.agents/skills/`` via the canonical skills-CLI sync; fatal on failure.

    The runner checkout carries the committed manifests (``.agents/manifest.yaml`` +
    ``.agents/manifest.d/*.yaml``) but no ``.agents/skills/`` (gitignored), so the stage
    skill-binding pointers would dangle without this. ``repo_skill_names=()`` on purpose:
    repo-authored skills still sync via their committed fragment — only the post-sync presence
    loop and the remediation hint skip them, which keeps positioning free of a GitHub read.

    Deliberately fatal (``skills_sync_failed``), diverging from the local worktree mirror's
    loud-but-non-fatal posture: locally a human sees the warning; remotely nobody does, and a
    silently-degraded drive is worse than a failed one.
    """
    error = init.sync_skills(repo_root, [])
    if error is not None:
        raise UserFacingCliError(error, error_type="skills_sync_failed")
    user_output("run-worker: skills delivered via skills update --sync")


def position_worktree(
    repo_root: Path, *, run_id: str, stage: Stage, plan_ref: plan.PlanRef
) -> None:
    """Materialize the worktree the Node worker consumes: handoff + plan-ref + plan-body +
    skills delivery (fatal).

    Mirrors the cold-local positioning in ``launch.launch_stage`` (the worktree *is* the checkout
    here, so cwd = ``repo_root``), including its materialize order (plan body → skills). The
    worker reads the plan-ref to seed its prompt and the handoff ``mode`` to set tool gating; it
    never re-writes them. Skills arrive via the skills-CLI sync rather than the local symlink
    mirror — the checkout has no ``.agents/skills/`` to mirror from — and a delivery failure
    raises here, before the worker spawns.
    """
    cache.ensure_layout(repo_root)
    cache.write_handoff(repo_root, run_id, {"stage": stage.id, "mode": stage.mode})
    cache.write_plan_ref(repo_root, plan_ref)
    launch.materialize_plan_body(repo_root, repo_root, plan_ref)
    _deliver_skills(repo_root)


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
    plan: str,
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
        backend = resolve.resolve_issue_backend(repo_root)
        state = backend.get_plan(issue_id=plan)
    except IssueBackendError as exc:
        raise UserFacingCliError(
            f"run-worker failed to resolve plan #{plan}\n{exc}", error_type="github_error"
        ) from exc
    if state is None:
        raise UserFacingCliError(f"Plan issue #{plan} not found", error_type="plan_not_found")
    plan_ref = resume.reconstruct_plan_ref(state, provider=backend.backend_id)

    user_output(
        f"run-worker: positioning {stage.id} for plan #{plan} "
        f"(run_id={run_id}, base={base or '<unset>'})"
    )
    position_worktree(repo_root, run_id=run_id, stage=stage, plan_ref=plan_ref)
    entry = resolve_worker_entry(repo_root, environ)
    user_output(f"run-worker: worker entry={entry.path} ({entry.source})")
    run_report.report_started(repo_root, run_id=run_id, stage=stage.id, plan=plan, environ=environ)
    # Mirror the remote run into Linear's Agents UI. Gated inside the
    # emitters (stamped provider == "linear" AND LINEAR_AGENT_TOKEN) and fully fail-soft —
    # emission can never change the forwarded worker exit code.
    run_url = run_report.run_url_from_env(environ)
    linear_agent.emit_run_started(
        repo_root,
        plan_ref=plan_ref,
        run_id=run_id,
        environ=environ,
        external_urls=[("GitHub Actions run", run_url)] if run_url else [],
    )
    code = _spawn_worker(
        entry.path, stage_id=stage.id, worktree=repo_root, run_id=run_id, environ=environ
    )
    user_output(f"run-worker: worker exited {code}")
    run_report.report_terminal(
        repo_root, run_id=run_id, stage=stage.id, plan=plan, exit_code=code, environ=environ
    )
    # A failed remote drive would otherwise leave the agent session dangling-active; a successful
    # remote implement already emitted its PR activity via the in-run `perk pr submit` delegation
    # (no success-arm terminal activity).
    if code != 0:
        linear_agent.emit_run_failed(repo_root, exit_code=code, run_url=run_url, environ=environ)
    return code
