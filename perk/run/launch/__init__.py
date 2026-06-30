"""The cold-door launch primitive (cli-vs-pi §4.1): position the environment, then
``exec pi`` primed for a stage, and hand off (§2.3).

Positioning is **plan-ref-aware**: for ``create``/``reuse`` stages, when no
explicit ``--worktree`` is given, the worktree/branch name is **derived** from the active
``cache.plan-ref`` (``plan-<pr_id>``, D1) and the plan-ref + handoff are **materialized into
the worktree** (D5) so the launched ``pi`` links ``active_plan_ref`` on ``session_start``.
``create`` is **idempotent** (D4): an existing worktree is reused (resume), not re-created.
Arbitrary plan-``#N`` resolution is ``perk resume``; here the *active* ref is used (D2).

A ``--remote`` launch of a drivable stage (``implement``/``address``) is a **real drive**
(contracts.md §8.13): :func:`_drive_remote_target` persists the ``run_id→plan``
linkage, verifies it, then triggers the runner via :mod:`perk.run.runner` (it positions nothing
locally — the workflow positions the worker in CI).

**Package layout.**
This ``__init__`` keeps the orchestrator (:func:`launch_stage`), the ``--dry-run`` preview
(:func:`_emit_dry_run_preview`), the agent-lock helpers (:func:`_pi_agent_dir` /
:func:`_sweep_stale_pi_agent_locks`), and the module constants used here
(``_PI_AGENT_LOCK_FILES`` / ``_NPM_QUIET_ENV``). The module-level imports the string-path
monkeypatches resolve against (``os`` / ``subprocess`` / ``github`` / ``git`` / ``cache`` /
``linear_agent`` / ``init`` / ``runner``) are kept here so ``perk.run.launch.<mod>.attr`` rebinds
the shared singleton every submodule that imports the same module sees. The orchestrator references
the moved helpers (``resolve_target`` / ``resolve_worktree`` / ``_resolve_prompt`` /
``materialize_plan_body`` / ``materialize_skills`` / ``materialize_extensions`` /
``print_launch_banner`` / ``run_worktree_setup`` /
``_drive_remote_target``) as **bare facade globals**, so ``setattr(launch, "run_worktree_setup",
…)`` / ``setattr(launch, "launch_stage", …)`` keep rebinding the names the orchestrator reads
(zero test churn). ``_WORKTREE_SETUP_TIMEOUT_S`` travels with ``run_worktree_setup`` into
``materialize`` and is re-exported here so ``launch._WORKTREE_SETUP_TIMEOUT_S`` resolves verbatim.
Submodules: ``worktree`` (resolution), ``prompts`` (seed prompts), ``materialize`` (worktree
materialization), ``remote`` (the ``--remote`` dispatch).
"""

import json
import os

# `subprocess` / `github` / `git` / `runner` are imported here purely so the string-path
# monkeypatches (`perk.run.launch.<mod>.attr`) and the facade reads (`launch.<mod>`) resolve to the
# shared singleton every submodule that imports the same module sees — the explicit-re-export alias
# form (`import x as x`) marks that intent for the linter (they are not referenced in this file).
import subprocess as subprocess
from pathlib import Path

from perk import __version__, plan
from perk import github as github
from perk.backends.linear import agent as linear_agent
from perk.cli.ensure import Ensure
from perk.convergence import init
from perk.convergence.init.extension_install import consumer_perk_package_dir
from perk.run import runner as runner
from perk.run.launch.materialize import (
    _WORKTREE_SETUP_TIMEOUT_S,
    materialize_extensions,
    materialize_plan_body,
    materialize_skills,
    print_launch_banner,
    run_worktree_setup,
)
from perk.run.launch.prompts import (
    _address_prompt,
    _implement_prompt,
    _initial_prompt,
    _learn_prompt,
    _plan_read_instruction,
    _resolve_prompt,
)
from perk.run.launch.remote import _drive_remote_target
from perk.run.launch.worktree import (
    ResolvedWorktree,
    Target,
    _fetch_best_effort,
    _sync_main_checkout,
    resolve_base,
    resolve_plan_worktree_name,
    resolve_target,
    resolve_worktree,
)
from perk.state import cache, run_id
from perk.substrate import git as git
from perk.substrate.config import Config, StageModel, load_local_linear_api_key
from perk.substrate.output import log_done, log_step, machine_output, user_output
from perk.substrate.registry import Stage

# pi locks its agent-dir JSON via proper-lockfile, which holds a lock as a *directory*
# (atomic mkdir). A stale regular *file* at one of these paths makes pi's startup rmdir fail
# with ENOTDIR and print a "(startup session lookup, global settings)" warning on every launch.
_PI_AGENT_LOCK_FILES = ("settings.json.lock", "auth.json.lock")

# Quiet the npm installs pi runs at startup when a fresh worktree's gitignored
# .pi/npm/ is empty (funding nags, audit advisories, allow-scripts warnings).
# loglevel=error keeps real install failures visible on pi's inherited stdio.
# Setdefault semantics: a user's own npm_config_* env vars win (see launch_stage).
_NPM_QUIET_ENV = {
    "npm_config_loglevel": "error",
    "npm_config_fund": "false",
    "npm_config_audit": "false",
}


def _pi_agent_dir() -> Path:
    """Mirror pi's ``config.js getAgentDir()``: ``PI_CODING_AGENT_DIR`` env var if set/non-empty,
    else ``~/.pi/agent``."""
    env = os.environ.get("PI_CODING_AGENT_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".pi" / "agent"


def _sweep_stale_pi_agent_locks(agent_dir: Path) -> None:
    """Remove stale pi agent-dir lockfiles before exec'ing pi.

    Only removes a lock path when it is **not a directory**: a directory is a *live*
    ``proper-lockfile`` lock (held via atomic ``mkdir``), so a non-directory at that path can
    only be a stale artifact and can never clobber a held lock. Best-effort and non-fatal — a
    sweep failure must never block a launch; if a stale lock survives, pi surfaces its own
    startup diagnostic (the status-quo warning), so this is a report-not-swallow boundary.

    Project-scope locks (``<worktree>/.pi/settings.json.lock``) are out of scope: launched
    worktrees get a fresh ``.pi/`` and the observed bug is on pi's global agent dir.
    """
    for name in _PI_AGENT_LOCK_FILES:
        lock = agent_dir / name
        try:
            if not lock.is_dir():
                lock.unlink(missing_ok=True)
        except OSError:
            pass  # best-effort; a stale lock is surfaced by pi's own startup diagnostic


def launch_stage(
    *,
    repo_root: Path,
    config: Config,
    stage: Stage,
    worktree: str | None,
    dry_run: bool,
    remote: str | None,
    pi_args: list[str],
    prompt_override: str | None = None,
    base: str | None = None,
    handoff_extra: dict[str, object] | None = None,
    binding_trigger: str | None = None,
    run_id_override: str | None = None,
    preview: bool = False,
    sync_main: bool = True,
) -> None:
    """Mint a run_id, write the handoff (+ plan-ref), position the worktree, and ``exec pi``.

    ``prompt_override``: when given, it is the seeded initial prompt instead of the
    stage-derived ``_initial_prompt`` — the dedicated ``perk objective plan`` command supplies a
    node-seeded prompt (objective-plan has no plan-ref, so ``_initial_prompt`` returns ``None``).
    All existing callers pass ``None`` and are unaffected.

    ``handoff_extra``: extra keys merged into the handoff blob so a stage can carry context
    that must survive *which save surface the model uses*. ``objective-plan`` passes the
    ``objective_id``/``node_id`` it just marked ``planning`` so a later ``perk plan-save`` recovers
    the link from the handoff even when the model saved via the ``/plan-save`` *command* (which
    forwards only ``{plan, title}``) rather than the ``plan_save`` *tool*. The ``Handoff`` TS
    interface already carries arbitrary keys (``[key: string]: unknown``), so no TS change is
    needed to ferry it.

    ``binding_trigger``: the trigger whose resolved skill bindings (defaults ⊕ the user
    overlay) are appended to the initial prompt **only when there is one to augment** (an idle
    launch stays idle); it defaults to ``f"stage:{stage.id}"``. The ``learn-docs`` cold door (which
    borrows the ``plan`` stage) overrides it to its ``command:learn-docs`` trigger so it does not
    fire ``stage:plan``.

    ``run_id_override`` (the ``replan`` cold door): when given, the session re-enters this
    *existing* ``run_id`` instead of minting a fresh one — a deliberate, documented exception to the
    registry's "cold mints" default. ``perk replan`` re-launches the ``plan`` stage with the target
    plan's original ``run_id`` so the warm ``plan_save`` upserts the SAME plan issue in place
    (preserving its ``plan-header`` and objective link). Every other caller passes ``None`` and
    mints as before.

    ``preview``: the cold ``perk pr address --preview`` flag — shapes the ``address``
    seed prompt to classify-only (take no action). Local-launch only: the remote dispatch path
    builds no seed prompt, so ``preview`` is inert on ``--remote``. Every other caller defaults
    ``False`` and is unaffected.

    ``sync_main`` (default ``True``): a guarded fast-forward of the main checkout before launch,
    for read-only ``worktree: none`` stages only (the planning/authoring stages that run in the
    user's main checkout and otherwise do no remote sync). The ``--no-sync`` opt-out on the
    interactive launchers flips it. Self-guarding + loud-but-non-fatal (see
    :func:`_sync_main_checkout`); inert on every other stage and on ``--remote``/``--dry-run``.
    """
    target = resolve_target(stage, remote)  # raises `remote_blocked` on a local-only stage
    if target.is_remote:
        _drive_remote_target(stage=stage, target=target, repo_root=repo_root, dry_run=dry_run)
        return  # the remote path never reaches the cold-local exec block below
    Ensure.invariant(
        stage.doors.get("cold_local") is True,
        f"Stage '{stage.id}' has no cold-local door.",
    )
    # Head a real launch with the perk banner, before any worktree work (git-worktree-add, skills
    # mirror, extension staging, worktree-setup hook, any fallback npm install) streams beneath it.
    # Both counts come from repo_root and are accurate at first render. `--dry-run` keeps its
    # `_emit_dry_run_preview` (no banner); `--remote` returned earlier in `_drive_remote_target`.
    if not dry_run:
        print_launch_banner(repo_root)

    # Guarded fast-forward of the main checkout for read-only `worktree: none` planning/authoring
    # stages (which run in the user's main checkout and otherwise never sync at launch). Before
    # `resolve_worktree` (a no-op fetch for `worktree: none`), so ordering is irrelevant beyond
    # "before exec". Self-guarding + loud-but-non-fatal; never reached on `--remote` (returned
    # earlier) or `--dry-run` (previewed below instead).
    if not dry_run and sync_main and stage.worktree == "none" and stage.mode == "read-only":
        _sync_main_checkout(repo_root)

    resolved = resolve_worktree(
        repo_root=repo_root,
        config=config,
        stage=stage,
        worktree=worktree,
        materialize=not dry_run,
        base=base,
    )
    wt = resolved.path
    rid = run_id_override or run_id.mint()
    prompt = _resolve_prompt(
        stage=stage,
        resolved=resolved,
        repo_root=repo_root,
        config=config,
        prompt_override=prompt_override,
        binding_trigger=binding_trigger,
        preview=preview,
    )
    # Worktree stages run in a fresh `plan-<id>` checkout whose path pi has never seen, so pi's
    # project-trust prompt (keyed per canonical cwd) re-fires on every launch. perk always launches
    # its OWN managed checkout, so trust is implicit — pass pi's `--approve` to trust the project
    # for THIS run (no `~/.pi/agent/trust.json` write, so ephemeral worktrees leave no residue).
    # Inserted BEFORE pi_args so a user-passed `--no-approve` overrides it (pi parses last-wins).
    # `worktree: none` stages run in the repo root the user trusts manually, so they are left alone.
    trust_args = ["--approve"] if stage.worktree != "none" else []
    model_args = _stage_model_argv(config, stage.id)
    argv = ["pi", *trust_args, *model_args, *pi_args, *([prompt] if prompt is not None else [])]

    if dry_run:  # side-effect-free: no worktree created, no handoff/plan-ref written
        _emit_dry_run_preview(
            stage=stage,
            resolved=resolved,
            rid=rid,
            argv=argv,
            setup=config.worktree_setup,
            sync_main=sync_main,
        )
        return

    cache.ensure_layout(wt)
    cache.write_handoff(wt, rid, {"stage": stage.id, "mode": stage.mode, **(handoff_extra or {})})
    if resolved.plan_ref is not None:  # D5: materialize the ref into the worktree
        cache.write_plan_ref(wt, resolved.plan_ref)
    # Warm perk's @mgiles/perk npm install into the repo-root .pi/npm/ BEFORE staging it into the
    # worktree. pi installs a missing project-scope `npm:` package lazily and unlocked, so a
    # missing-install window + parallel launches let a second process load from a half-installed
    # package and drop the perk extension. `ensure_extension_install_present` installs-on-absent
    # under a cross-process lock (a cheap `is_dir()` no-op once present); self-repo-exempt and
    # best-effort + non-fatal internally. It is idempotent and depends on neither `env` nor `chdir`,
    # so it runs here — the repo-root install is fully warmed before `materialize_extensions` clones
    # it into the worktree. `worktree: none` stages load from this repo-root install directly.
    # Narrate the install ONLY when one actually happens: the common path (package present) is an
    # instant locked no-op that returns `None`, so a cheap unlocked pre-check decides whether to
    # emit the step line. The extra `is_dir()` is purely cosmetic — the function re-checks
    # authoritatively under its own lock, so it can never cause a double install.
    self_repo = init.is_self_repo(repo_root)
    if not self_repo and not consumer_perk_package_dir(repo_root).is_dir():
        log_step("installing perk extension (@mgiles/perk)")
    if init.ensure_extension_install_present(repo_root, self_repo=self_repo) is not None:
        log_done("installed perk extension")
    # Materialize the plan body into the worktree so in-session checkpoints can seed from
    # its `## Steps` list. Best-effort + loud-but-non-fatal (a worktree without a body just yields
    # inert checkpoints). Uses the derived ref, falling back to the repo-root active ref.
    # `materialize_extensions` clones the warmed repo-root .pi/npm/ into the worktree so pi installs
    # nothing at startup (a silent launch beneath the banner).
    if stage.worktree != "none":
        materialize_plan_body(repo_root, wt, resolved.plan_ref or cache.read_plan_ref(repo_root))
        materialize_skills(repo_root, wt)
        materialize_extensions(repo_root, wt)
    # Mirror the implement-run start into Linear's Agents UI. Gated inside
    # the emitter (stamped provider == "linear" AND LINEAR_AGENT_TOKEN) and fully fail-soft —
    # it can never block the exec below. Not reached on --dry-run or --remote (early returns).
    if stage.id == "implement":
        linear_agent.emit_run_started(
            wt,
            plan_ref=resolved.plan_ref or cache.read_plan_ref(repo_root),
            run_id=rid,
            environ=os.environ,
        )
    # Run the project's `[worktree] setup` commands inside a freshly created worktree before the
    # exec. `run_worktree_setup` raises a `UserFacingCliError` on failure, so a failed setup aborts
    # the launch here (before `exec pi`); the worktree is left in place so a fixed re-run reuses it.
    # Never reached on a dry run (the `if dry_run:` block returns above) or on reuse.
    if resolved.created and config.worktree_setup:
        run_worktree_setup(wt, config.worktree_setup)
    # PERK_CLI_VERSION carries the running CLI's version into the launched session so the
    # extension's `session_start` handler can surface a soft drift warning when the live loaded
    # `@mgiles/perk` extension differs from the CLI that launched it (a stale lazy-installed npm:
    # package). Informational only (not run-control data, unlike PERK_RUN_ID); set at this single
    # local-launch seam — the remote worker early-returns before here.
    env = {
        **_NPM_QUIET_ENV,
        **os.environ,
        "PERK_RUN_ID": rid,
        "PERK_CLI_VERSION": __version__,
    }
    # Seed LINEAR_API_KEY from the gitignored `.perk/local.toml` `[linear] api_key` so the
    # borrowed in-session `linear_*` tools and any `perk <stage> --json` cold-door worker the
    # session spawns (they inherit this env) can authenticate. Env wins: only fill it when the
    # environment does not already provide the key. Best-effort (fail-soft reader) — reached only
    # on the local path (`--dry-run`/`--remote` returned earlier).
    if not os.environ.get("LINEAR_API_KEY", "").strip():
        local_linear_key = load_local_linear_api_key(repo_root)
        if local_linear_key is not None:
            env["LINEAR_API_KEY"] = local_linear_key
    _sweep_stale_pi_agent_locks(_pi_agent_dir())  # silence pi's stale-lock startup warning
    os.chdir(wt)  # pi's ctx.cwd becomes the worktree; the extension claims from there
    os.execvpe("pi", argv, env)  # the CLI *becomes* pi — nothing after this runs


def _stage_model_argv(config: Config, stage_id: str) -> list[str]:
    """Per-stage ``--model``/``--thinking`` launch flags from `[stages.<id>]` (empty when unset —
    pi's own model/thinking defaults are left untouched). Inserted before ``pi_args`` so an
    explicit ``perk <stage> --model X``/``--thinking Y`` overrides it (pi parses last-wins)."""
    sm: StageModel | None = config.stage_models.get(stage_id)
    if sm is None:
        return []
    args: list[str] = []
    if sm.model:
        args += ["--model", sm.model]
    if sm.thinking:
        args += ["--thinking", sm.thinking]
    return args


def _emit_dry_run_preview(
    *,
    stage: Stage,
    resolved: ResolvedWorktree,
    rid: str,
    argv: list[str],
    setup: list[str] | None = None,
    sync_main: bool = True,
) -> None:
    """The side-effect-free ``--dry-run`` preview of a cold-local launch (user lines + the
    machine-readable JSON payload). The remote dispatch preview in :func:`_drive_remote_target`
    is a different payload and stays inline there.

    ``setup`` is the project's ``[worktree] setup`` commands; when the worktree would be freshly
    created and the list is non-empty, the planned commands are previewed (but never run).

    ``sync_main`` mirrors the real-run gate: when the stage WOULD fast-forward the main checkout
    (a read-only ``worktree: none`` stage with sync on), the preview emits a line + a
    ``payload["sync_main"]`` flag (build-once preview-parity discipline).
    """
    user_output(f"would launch stage '{stage.id}' in {resolved.path}")
    user_output(f"  run_id={rid}  PERK_RUN_ID={rid}  argv={' '.join(argv)}")
    payload: dict[str, object] = {
        "success": True,
        "stage": stage.id,
        "worktree": str(resolved.path),
        "run_id": rid,
        "argv": argv,
        "base": resolved.base,
    }
    if resolved.plan_ref is not None:
        payload["plan_ref"] = plan.PlanRefOut.from_domain(resolved.plan_ref).model_dump(mode="json")
    would_sync = stage.worktree == "none" and stage.mode == "read-only" and sync_main
    if would_sync:
        user_output("  would sync main checkout (fast-forward) before launch")
        payload["sync_main"] = would_sync
    # On a dry run the worktree is never created, so `resolved.created` is always False; preview
    # the setup commands when the stage WOULD freshly create the worktree (a `create` stage whose
    # path does not yet exist — the same condition that gates `run_worktree_setup` on a real run).
    would_create = stage.worktree == "create" and not resolved.path.exists()
    if would_create and setup:
        user_output(f"  would run setup: {'; '.join(setup)}")
        payload["setup"] = setup
    machine_output(json.dumps(payload))


__all__ = [
    "_NPM_QUIET_ENV",
    "_PI_AGENT_LOCK_FILES",
    "_WORKTREE_SETUP_TIMEOUT_S",
    "ResolvedWorktree",
    "Target",
    "_address_prompt",
    "_drive_remote_target",
    "_emit_dry_run_preview",
    "_fetch_best_effort",
    "_implement_prompt",
    "_initial_prompt",
    "_learn_prompt",
    "_pi_agent_dir",
    "_plan_read_instruction",
    "_resolve_prompt",
    "_stage_model_argv",
    "_sweep_stale_pi_agent_locks",
    "_sync_main_checkout",
    "launch_stage",
    "materialize_extensions",
    "materialize_plan_body",
    "materialize_skills",
    "print_launch_banner",
    "resolve_base",
    "resolve_plan_worktree_name",
    "resolve_target",
    "resolve_worktree",
    "run_worktree_setup",
]
