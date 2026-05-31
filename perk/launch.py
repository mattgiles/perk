"""The cold-door launch primitive (cli-vs-pi §4.1): position the environment, then
``exec pi`` primed for a stage, and hand off (§2.3).

T4 builds the *mechanism*; plan-ref positioning is Phase 1, so a ``create``/``reuse`` stage
is positioned by an explicit worktree name (no branch-name metadata, PRIOR_ART §11). The
launched ``pi`` claims the ``run_id`` via the T3 extension; the in-session *handler* (acting
on ``handoff.stage``) is Phase 1.
"""

import json
import os
from pathlib import Path

from perk import cache, git, run_id
from perk.cli.ensure import Ensure, UserFacingCliError
from perk.config import Config
from perk.output import machine_output, user_output
from perk.registry import Stage


def resolve_worktree(
    *, repo_root: Path, config: Config, stage: Stage, worktree: str | None, materialize: bool
) -> Path:
    """Resolve the worktree this stage runs in (validating); create it only when
    ``materialize`` (i.e. not a dry run)."""
    if stage.worktree == "none":
        return repo_root

    name = Ensure.not_none(
        worktree,
        f"Stage '{stage.id}' needs a worktree — pass --worktree NAME\n"
        "(plan-ref resolution lands in Phase 1).",
    )
    Ensure.invariant(
        "/" not in name and name not in ("", ".", ".."),
        f"Invalid worktree name '{name}' — no path separators.",
    )
    path = config.worktree_root / name
    if stage.worktree == "create":
        Ensure.invariant(not path.exists(), f"Worktree already exists: {path}")
        if materialize:
            git.worktree_add(repo_root, path, branch=name, create_branch=True)
    else:  # reuse
        Ensure.path_exists(
            path,
            f"Worktree not found: {path}\nCreate it with 'perk worktree create {name}'.",
        )
    return path


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
    """Mint a run_id, write the handoff, position the worktree, and ``exec pi``."""
    if remote is not None:
        raise UserFacingCliError(
            f"remote target is Phase 3 — '{stage.id}' is cold_remote-blocked\n"
            "Run without --remote for a local session."
        )
    Ensure.invariant(
        stage.doors.get("cold_local") is True,
        f"Stage '{stage.id}' has no cold-local door.",
    )

    wt = resolve_worktree(
        repo_root=repo_root, config=config, stage=stage, worktree=worktree, materialize=not dry_run
    )
    rid = run_id.mint()
    argv = ["pi", *pi_args]

    if dry_run:  # side-effect-free: no worktree created, no handoff written
        user_output(f"would launch stage '{stage.id}' in {wt}")
        user_output(f"  run_id={rid}  PERK_RUN_ID={rid}  argv={' '.join(argv)}")
        machine_output(
            json.dumps(
                {
                    "success": True,
                    "stage": stage.id,
                    "worktree": str(wt),
                    "run_id": rid,
                    "argv": argv,
                }
            )
        )
        return

    cache.ensure_layout(wt)
    cache.write_handoff(wt, rid, {"stage": stage.id, "mode": stage.mode})
    env = {**os.environ, "PERK_RUN_ID": rid}
    os.chdir(wt)  # pi's ctx.cwd becomes the worktree; the extension claims from there
    os.execvpe("pi", argv, env)  # the CLI *becomes* pi — nothing after this runs
