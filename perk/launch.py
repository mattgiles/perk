"""The cold-door launch primitive (cli-vs-pi §4.1): position the environment, then
``exec pi`` primed for a stage, and hand off (§2.3).

T4 (P1) makes positioning **plan-ref-aware**: for ``create``/``reuse`` stages, when no
explicit ``--worktree`` is given, the worktree/branch name is **derived** from the active
``cache.plan-ref`` (``plan-<pr_id>``, D1) and the plan-ref + handoff are **materialized into
the worktree** (D5) so the launched ``pi`` links ``active_plan_ref`` on ``session_start``.
``create`` is **idempotent** (D4): an existing worktree is reused (resume), not re-created.
Arbitrary plan-``#N`` resolution is ``perk resume`` (T5c); here the *active* ref is used (D2).
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from perk import cache, git, github, run_id
from perk.cli.ensure import Ensure, UserFacingCliError
from perk.config import Config
from perk.git import GitError
from perk.github import GitHubError
from perk.output import machine_output, user_output
from perk.registry import Stage


@dataclass(frozen=True)
class ResolvedWorktree:
    """The worktree a stage runs in, plus the plan-ref to materialize into it (if derived)."""

    path: Path
    plan_ref: dict[str, Any] | None


def resolve_plan_worktree_name(plan_ref: dict[str, Any]) -> str:
    """Deterministic, re-derivable worktree/branch name for a plan (D1).

    ``pr_id`` stays a string (provider-agnostic): ``42 -> plan-42``, ``PROJ-123 ->
    plan-PROJ-123``. Rejects ids that cannot be a single path segment.
    """
    pr_id = str(plan_ref.get("pr_id", "")).strip()
    Ensure.invariant(
        bool(pr_id) and "/" not in pr_id and pr_id not in (".", ".."),
        f"plan-ref pr_id unusable as a worktree name: {pr_id!r}",
    )
    return f"plan-{pr_id}"


def resolve_worktree(
    *, repo_root: Path, config: Config, stage: Stage, worktree: str | None, materialize: bool
) -> ResolvedWorktree:
    """Resolve the worktree this stage runs in (validating); create it only when
    ``materialize`` (i.e. not a dry run). ``create`` reuses an existing worktree (D4)."""
    if stage.worktree == "none":
        return ResolvedWorktree(path=repo_root, plan_ref=None)

    plan_ref: dict[str, Any] | None = None
    name = worktree
    if name is None:  # D2/D3: derive the name from the active plan-ref
        plan_ref = cache.read_plan_ref(repo_root)
        if plan_ref is None:
            raise UserFacingCliError(
                f"Stage '{stage.id}' needs a saved plan — run /plan-save first "
                "(or pass --worktree NAME).",
                error_type="no_plan_ref",
            )
        name = resolve_plan_worktree_name(plan_ref)

    Ensure.invariant(
        "/" not in name and name not in ("", ".", ".."),
        f"Invalid worktree name '{name}' — no path separators.",
    )
    path = config.worktree_root / name
    if stage.worktree == "create":
        if path.exists():
            pass  # D4: idempotent reuse (resume) — do not re-create or error
        elif materialize:
            try:
                git.worktree_add(repo_root, path, branch=name, create_branch=True)
            except GitError as exc:
                raise UserFacingCliError(f"git worktree add failed: {exc}") from exc
    else:  # reuse
        Ensure.path_exists(
            path,
            f"Worktree not found: {path}\nRun 'perk implement' first.",
        )
    return ResolvedWorktree(path=path, plan_ref=plan_ref)


def _initial_prompt(stage: Stage, plan_ref: dict[str, Any] | None) -> str | None:
    """The first message ``pi`` is launched with, so the session *starts working* rather than
    opening idle (P1.T4c, Bug 1). Only the ``implement`` stage is primed in Phase 1: read the plan,
    then implement on this branch and ``/submit`` when done. ``None`` (no prompt) for other stages
    — e.g. ``plan`` is user-driven exploration."""
    if stage.id != "implement" or plan_ref is None:
        return None
    provider = str(plan_ref.get("provider", ""))
    pr_id = str(plan_ref.get("pr_id", ""))
    url = str(plan_ref.get("url", ""))
    read_cmd = f"gh issue view {pr_id} --comments" if provider == "github" else f"open {url}"
    return (
        f"You are implementing perk plan {provider} #{pr_id} ({url}) on this branch.\n\n"
        f"First, read the full plan:\n    {read_cmd}\n\n"
        "Then implement it here. Work in focused steps and keep the tree committable. When the "
        "implementation is complete and committed, open the pull request with the /submit command."
    )


def launch_stage(
    *,
    repo_root: Path,
    config: Config,
    stage: Stage,
    worktree: str | None,
    dry_run: bool,
    remote: str | None,
    pi_args: list[str],
) -> None:
    """Mint a run_id, write the handoff (+ plan-ref), position the worktree, and ``exec pi``."""
    if remote is not None:
        raise UserFacingCliError(
            f"remote target is Phase 3 — '{stage.id}' is cold_remote-blocked\n"
            "Run without --remote for a local session."
        )
    Ensure.invariant(
        stage.doors.get("cold_local") is True,
        f"Stage '{stage.id}' has no cold-local door.",
    )

    resolved = resolve_worktree(
        repo_root=repo_root, config=config, stage=stage, worktree=worktree, materialize=not dry_run
    )
    wt = resolved.path
    rid = run_id.mint()
    # Prime the session (Bug 1): when --worktree is given the derived ref is absent, so fall back
    # to the repo-root active ref for the prompt.
    prompt = _initial_prompt(stage, resolved.plan_ref or cache.read_plan_ref(repo_root))
    argv = ["pi", *pi_args, *([prompt] if prompt is not None else [])]

    if dry_run:  # side-effect-free: no worktree created, no handoff/plan-ref written
        user_output(f"would launch stage '{stage.id}' in {wt}")
        user_output(f"  run_id={rid}  PERK_RUN_ID={rid}  argv={' '.join(argv)}")
        payload: dict[str, object] = {
            "success": True,
            "stage": stage.id,
            "worktree": str(wt),
            "run_id": rid,
            "argv": argv,
        }
        if resolved.plan_ref is not None:
            payload["plan_ref"] = resolved.plan_ref
        machine_output(json.dumps(payload))
        return

    cache.ensure_layout(wt)
    cache.write_handoff(wt, rid, {"stage": stage.id, "mode": stage.mode})
    if resolved.plan_ref is not None:  # D5: materialize the ref into the worktree
        cache.write_plan_ref(wt, resolved.plan_ref)
    # P2.T2c: materialize the plan body into the worktree so in-session checkpoints can seed from
    # its `## Steps` list. Best-effort + loud-but-non-fatal (a worktree without a body just yields
    # inert checkpoints). Uses the derived ref, falling back to the repo-root active ref.
    if stage.worktree != "none":
        _materialize_plan_body(repo_root, wt, resolved.plan_ref or cache.read_plan_ref(repo_root))
    env = {**os.environ, "PERK_RUN_ID": rid}
    os.chdir(wt)  # pi's ctx.cwd becomes the worktree; the extension claims from there
    os.execvpe("pi", argv, env)  # the CLI *becomes* pi — nothing after this runs


def _materialize_plan_body(
    repo_root: Path, worktree: Path, plan_ref: dict[str, Any] | None
) -> None:
    """Fetch the plan body from its canonical source and cache it into the worktree (P2.T2c).

    Best-effort: a non-github provider, a non-numeric id, or any GitHub failure is reported but
    never blocks the launch (checkpoints simply stay inert). Honest, not silent.
    """
    if plan_ref is None or str(plan_ref.get("provider")) != "github":
        return
    pr_id = str(plan_ref.get("pr_id", "")).strip()
    if not pr_id.isdigit():
        return
    try:
        body = github.get_plan_body(number=int(pr_id), repo_root=repo_root)
    except GitHubError as exc:
        user_output(f"  (checkpoints: could not fetch plan #{pr_id} body — {exc})")
        return
    if body:
        cache.write_plan_body(worktree, body)
