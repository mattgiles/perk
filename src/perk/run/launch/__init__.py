"""The cold-door launch primitive (cli-vs-pi §4.1): position the environment, then
``exec pi`` primed for a stage, and hand off (§2.3).

Positioning runs FIRST and is **selection-aware** (contracts.md §8.38): ``resolve_worktree``
settles the one launch-authority ref — an explicitly selected ``plan_ref`` > an explicit
existing ``--worktree``'s own binding > the ``invocation_root`` active selector — derives the
canonical ``plan-<pr_id>`` branch/worktree name (D1), validates or materializes the checkout,
and **owns the worktree's plan-ref binding** (a fresh/restored checkout is bound at creation;
an existing one is accepted only after the binding-equality check). ``launch_stage`` then
writes only the run **handoff** (never the binding) and every later phase — seed prompt,
plan-body snapshot, Linear emission, cwd, dry-run JSON — consumes ``ResolvedWorktree.plan_ref``
so the launched ``pi`` links ``active_plan_ref`` on ``session_start`` (D5). ``create`` is
**idempotent** (D4): an existing worktree is validated reuse, not re-created; a missing
``reuse`` checkout restores from ``origin/plan-<id>`` (learn excepted). Arbitrary plan-``#N``
resolution is ``perk resume``/the explicit ``PLAN`` selectors (D2).

A ``--remote`` launch of a drivable stage (``implement``/``address``) is a **real drive**
(contracts.md §8.13): :func:`_drive_remote_target` persists the ``run_id→plan``
linkage, verifies it, then triggers the runner via :mod:`perk.run.runner` (it positions nothing
locally — the workflow positions the worker in CI).

**Package layout.**
This ``__init__`` keeps the orchestrator (:func:`launch_stage`), the immutable
:class:`_LaunchContext` + the named phase functions it flows through (:func:`_build_argv` and the
self-gating post-dry-run pipeline :func:`_write_session_handoff` / :func:`_warm_extension_install`
/ :func:`_materialize_into_worktree` / :func:`_emit_linear_run_started` / :func:`_run_setup_hook`
/ :func:`_exec_pi`), the pure child-environment builder (:func:`_build_exec_env`), the
``--dry-run`` preview
(:func:`_emit_dry_run_preview`), the agent-lock helpers (:func:`_pi_agent_dir` /
:func:`_sweep_stale_pi_agent_locks`), and the module constants used here
(``_PI_AGENT_LOCK_FILES`` / ``_NPM_QUIET_ENV``). The module-level imports the string-path
monkeypatches resolve against (``os`` / ``subprocess`` / ``github`` / ``git`` / ``cache`` /
``linear_agent`` / ``init`` / ``runner``) are kept here so ``perk.run.launch.<mod>.attr`` rebinds
the shared singleton every submodule that imports the same module sees. The orchestrator and its
phase functions reference
the moved helpers (``resolve_target`` / ``resolve_worktree`` / ``_resolve_prompt`` /
``materialize_plan_body`` / ``materialize_skills`` / ``materialize_extensions`` /
``print_launch_banner`` / ``run_worktree_setup`` /
``_drive_remote_target``) as **bare facade globals**, so ``setattr(launch, "run_worktree_setup",
…)`` / ``setattr(launch, "launch_stage", …)`` keep rebinding the names the phases read
(zero test churn) — which is also why the phases live HERE, not in a ``phases`` submodule: a
submodule would freeze its own copies of those names and silently break the name-binding patches.
``_WORKTREE_SETUP_TIMEOUT_S`` travels with ``run_worktree_setup`` into
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
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from perk import __version__, plan
from perk import github as github
from perk.backends.issue_backend import PlanState
from perk.backends.linear import agent as linear_agent
from perk.cli.ensure import Ensure, UserFacingCliError
from perk.convergence import init
from perk.convergence.init.extension_install import consumer_perk_package_dir
from perk.run import runner as runner
from perk.run.launch.materialize import (
    _WORKTREE_SETUP_TIMEOUT_S,
    materialize_extensions,
    materialize_plan_body,
    materialize_skills,
    print_launch_banner,
    print_launch_banner_gated,
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
    WorktreeRequest,
    _fetch_best_effort,
    _sync_main_checkout,
    checked_name,
    resolve_base,
    resolve_plan_worktree_name,
    resolve_target,
    resolve_worktree,
)
from perk.state import cache, run_id
from perk.substrate import git as git
from perk.substrate.config import (
    Config,
    ConfigError,
    StageModel,
    effective_pi_agent_dir,
    load_local_linear_api_key,
)
from perk.substrate.output import io_step, log_warn, machine_output, user_output
from perk.substrate.proc import which_absolute
from perk.substrate.registry import Stage
from perk.substrate.skill_exposure import skill_exposure_argv

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

# perk-launched sessions run the borrowed pi-fff extension in override mode (FFF replaces
# the builtin find/grep). Injected-default tier: operator env wins by merge order, so
# PI_FFF_MODE=tools-and-ui in the environment restores pi-fff's additive default.
FFF_OVERRIDE_ENV = {"PI_FFF_MODE": "override"}


@dataclass(frozen=True)
class _LaunchContext:
    """The resolved cold-local launch, read by every post-resolution phase.

    Built once in ``launch_stage`` after worktree/prompt/argv resolution and passed through the
    phase pipeline unchanged. Holds only the shared core; an input consumed by a single phase
    (``handoff_extra``) is passed to that phase directly. ``argv`` is a tuple for real
    immutability — the two consumers convert at the edge (``list(ctx.argv)`` for the dry-run
    preview and for ``os.execvpe``).
    """

    repo_root: Path
    config: Config
    stage: Stage
    resolved: ResolvedWorktree
    rid: str
    argv: tuple[str, ...]
    pi_agent_dir: Path | None = None


def _pi_agent_dir() -> Path:
    """Resolve the cold-local child's agent dir for lock sweeping.

    Blank inherited values are removed by `_build_exec_env`, so treat them as absent here too.
    Non-blank values retain pi's native expansion semantics; otherwise use `~/.pi/agent`.
    """
    env = os.environ.get("PI_CODING_AGENT_DIR")
    if env and env.strip():
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
    prompt_suffix: str | None = None,
    plan_ref: plan.PlanRef | None = None,
    plan_state: PlanState | None = None,
    plan_id: str | None = None,
    invocation_root: Path | None = None,
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

    ``run_id_override``: when given, the launched session uses this ``run_id`` instead of one
    minted here — a deliberate, documented exception to the registry's "cold mints" default, with
    two callers. ``perk replan`` re-enters an *existing* run: it re-launches the ``plan`` stage
    with the target plan's original ``run_id`` so the warm ``plan_save`` upserts the SAME plan
    issue in place (preserving its ``plan-header`` and objective link). ``perk learn harvest``
    pre-mints a *fresh* id at gather time so its run-scoped manifest path and the launched
    session agree on one ``run_id``. Every other caller passes ``None`` and mints as before.

    ``preview``: the cold ``perk pr address --preview`` flag — shapes the ``address``
    seed prompt to classify-only (take no action). Local-launch only: the remote dispatch path
    builds no seed prompt, so ``preview`` is inert on ``--remote``. Every other caller defaults
    ``False`` and is unaffected.

    ``prompt_suffix``: an extra paragraph appended between the stage prompt and the skill-binding
    suffix. Augment-only (mirroring binding delivery's D2 rule): a suffix never synthesizes a
    prompt — an idle launch (no stage prompt) stays idle and the suffix is dropped. Inert on
    ``--remote`` (the remote arm returns in :func:`_drive_remote_target` before prompt assembly —
    the worker builds its own primer) and on ``--dry-run`` from resume (resume's dry-run path
    returns before ``launch_stage`` is called). Today's single caller is the ``perk plan resume``
    door, which supplies the reuse advisory (contracts.md §8.38).

    ``sync_main`` (default ``True``): a guarded fast-forward of the main checkout before launch,
    for read-only ``worktree: none`` stages only (the planning/authoring stages that run in the
    user's main checkout and otherwise do no remote sync). The ``--no-sync`` opt-out on the
    interactive launchers flips it. Self-guarding + loud-but-non-fatal (see
    :func:`_sync_main_checkout`); inert on every other stage and on ``--remote``/``--dry-run``.

    ``plan_ref``/``plan_state``: an already-selected canonical plan (an explicit positional
    plan id, resolved by the caller through ``perk.cli.plan_selection``). The resolved ref is
    launch authority for BOTH the local positioning path and the ``--remote`` dispatch — the
    launch never re-reads the mutable root selector after selection. ``plan_state`` is the
    selection's already-fetched canonical state (spares a stacked restore its re-read).

    ``plan_id``: the bare-id twin of ``plan_ref`` (the ``plan watch`` selection shape),
    forwarded verbatim to ``resolve_worktree(plan_id=…)``: an existing checkout is validated
    reuse with NO backend read; a missing checkout performs the one canonical read lazily on
    the restore arm. The ``objective plan`` stacked child-layer arm is the one caller (it
    positions the planning session in the predecessor's checkout); every other caller passes
    ``None`` and is unaffected.

    ``invocation_root`` (defaults to ``repo_root``): the checkout the command was invoked from
    — the root the **no-argument cache fallback** reads (a launch inside a plan worktree selects
    that worktree's own plan). ``repo_root`` itself is the caller's positioning anchor (the
    main root for the two-roots plan-selecting doors).
    """
    target = resolve_target(stage, remote)  # raises `remote_blocked` on a local-only stage
    if target.is_remote:
        if worktree is not None:
            raise UserFacingCliError(
                "--worktree cannot combine with --remote: a local-positioning gesture has no "
                "remote meaning — select the plan with the positional PLAN instead.",
                error_type="invalid_input",
            )
        _drive_remote_target(
            stage=stage,
            target=target,
            repo_root=repo_root,
            dry_run=dry_run,
            plan_ref=plan_ref,
            selector_root=invocation_root if invocation_root is not None else repo_root,
        )
        return  # the remote path never reaches the cold-local exec block below
    Ensure.invariant(
        stage.doors.get("cold_local") is True,
        f"Stage '{stage.id}' has no cold-local door.",
    )
    if not dry_run:
        # Head a real launch with the perk banner, before any worktree work (git-worktree-add,
        # skills mirror, extension staging, worktree-setup hook, any fallback npm install) streams
        # beneath it. Both counts come from repo_root and are accurate at first render. `--dry-run`
        # keeps its `_emit_dry_run_preview` (no banner); `--remote` returned earlier in
        # `_drive_remote_target`.
        print_launch_banner(repo_root)
        # Guarded fast-forward of the main checkout for read-only `worktree: none`
        # planning/authoring stages (which run in the user's main checkout and otherwise never
        # sync at launch). Before `resolve_worktree` (a no-op fetch for `worktree: none`), so
        # ordering is irrelevant beyond "before exec". Self-guarding + loud-but-non-fatal; never
        # reached on `--remote` (returned earlier) or `--dry-run` (previewed below instead).
        if sync_main and stage.worktree == "none" and stage.mode == "read-only":
            _sync_main_checkout(repo_root)

    resolved = resolve_worktree(
        repo_root=repo_root,
        config=config,
        request=WorktreeRequest.for_stage(stage),
        worktree=worktree,
        materialize=not dry_run,
        base=base,
        invocation_root=invocation_root,
        selected_ref=plan_ref,
        plan_state=plan_state,
        plan_id=plan_id,
    )
    # Resolve once for preview/exec parity. Inherited redirects count as operator choices,
    # including the value injected by a parent session into a nested cold launch.
    pi_agent_dir = None
    if not os.environ.get("PI_CODING_AGENT_DIR", "").strip():
        try:
            pi_agent_dir = effective_pi_agent_dir(repo_root)
        except (ConfigError, tomllib.TOMLDecodeError) as exc:
            log_warn(
                "could not read [pi] agent_dir from the main checkout config — "
                f"launching without the redirect ({exc})"
            )
        if pi_agent_dir is not None:
            if not pi_agent_dir.exists():
                log_warn(
                    f"pi agent dir {pi_agent_dir} is missing — pi creates an empty agent dir "
                    "on demand; sessions launch with no auth.json/models.json"
                )
            elif not pi_agent_dir.is_dir():
                raise UserFacingCliError(
                    f"pi agent dir {pi_agent_dir} is not a directory — pi cannot create its "
                    "sessions tree under a non-directory. Set [pi] agent_dir to a directory.",
                    error_type="pi_agent_dir_invalid",
                )
    ctx = _LaunchContext(
        repo_root=repo_root,
        config=config,
        stage=stage,
        resolved=resolved,
        rid=run_id_override or run_id.mint(),
        pi_agent_dir=pi_agent_dir,
        argv=_build_argv(
            stage=stage,
            config=config,
            repo_root=repo_root,
            binding_trigger=binding_trigger,
            pi_args=pi_args,
            prompt=_resolve_prompt(
                stage=stage,
                resolved=resolved,
                repo_root=repo_root,
                config=config,
                prompt_override=prompt_override,
                binding_trigger=binding_trigger,
                preview=preview,
                prompt_suffix=prompt_suffix,
            ),
        ),
    )

    if dry_run:  # side-effect-free: no worktree created, no handoff/plan-ref written
        _emit_dry_run_preview(
            stage=stage,
            resolved=resolved,
            rid=ctx.rid,
            argv=list(ctx.argv),
            setup=config.worktree_setup,
            sync_main=sync_main,
            pi_agent_dir=ctx.pi_agent_dir,
        )
        return

    _write_session_handoff(ctx, handoff_extra)
    _warm_extension_install(ctx)
    _materialize_into_worktree(ctx)  # self-gates: worktree stages only
    _emit_linear_run_started(ctx)  # self-gates: implement only
    _run_setup_hook(ctx)  # self-gates: marker-gated (set at create/restore materialization)
    _exec_pi(ctx)  # the CLI *becomes* pi — nothing after this runs


def _build_argv(
    *,
    stage: Stage,
    config: Config,
    repo_root: Path,
    binding_trigger: str | None,
    pi_args: list[str],
    prompt: str | None,
) -> tuple[str, ...]:
    """Assemble the one ``pi`` argv shared verbatim by the dry-run preview and the exec
    (build-argv-once: preview parity is structural, never re-derived)."""
    # Worktree stages run in a fresh `plan-<id>` checkout whose path pi has never seen, so pi's
    # project-trust prompt (keyed per canonical cwd) re-fires on every launch. perk always launches
    # its OWN managed checkout, so trust is implicit — pass pi's `--approve` to trust the project
    # for THIS run (no `~/.pi/agent/trust.json` write, so ephemeral worktrees leave no residue).
    # Inserted BEFORE pi_args so a user-passed `--no-approve` overrides it (pi parses last-wins).
    # `worktree: none` stages run in the repo root the user trusts manually, so they are left alone.
    trust_args = ["--approve"] if stage.worktree != "none" else []
    model_args = _stage_model_argv(config, stage.id)
    # Skill-exposure scoping (contracts.md §8.39) sits between the model args and `pi_args` so a
    # user-passed `--skill` stays additive and any user flag stays last (pi parses last-wins).
    skill_args = _skill_exposure_argv(repo_root, config, stage, binding_trigger)
    return (
        "pi",
        *trust_args,
        *model_args,
        *skill_args,
        *pi_args,
        *([prompt] if prompt is not None else []),
    )


def _skill_exposure_argv(
    repo_root: Path, config: Config, stage: Stage, binding_trigger: str | None
) -> list[str]:
    """The `[skills]`/`stages:` scoped-launch argv fragment (empty when the exposure model is
    not in use — the launch argv then stays byte-identical to unscoped discovery).

    Mirrors :func:`_stage_model_argv`; the trigger normalizes with the same expression
    ``_resolve_prompt`` uses so the bound-skill union fires on exactly the trigger whose bindings
    the seed prompt delivers. Wrapped in the blanket fail-open guard (contracts.md §8.39): any
    unexpected exception → one warn + no flags — the launch degrades to full discovery, never
    blocks.
    """
    trigger = binding_trigger or f"stage:{stage.id}"
    try:
        args, warnings = skill_exposure_argv(
            repo_root,
            stage_id=stage.id,
            trigger=trigger,
            policy=config.skills,
            user_bindings=config.user_bindings,
        )
    except Exception as exc:  # the deliberate whole-composition fail-open (§8.39 ladder)
        log_warn(
            f"skills: exposure composition failed ({exc}) — "
            "launching with pi's full skill discovery"
        )
        return []
    for warning in warnings:
        log_warn(warning)
    return args


def _write_session_handoff(ctx: _LaunchContext, handoff_extra: dict[str, object] | None) -> None:
    """Write the run handoff (+ any ``handoff_extra`` keys) into the worktree cache.

    The worktree's ``plan-ref`` binding is NOT written here: the positioner
    (:func:`resolve_worktree`) owns binding materialization — a fresh/restored checkout is bound
    at creation and an existing checkout is only accepted after the binding equality check, so
    a launch can never clobber a worktree's own binding with the mutable root selector."""
    wt = ctx.resolved.path
    cache.ensure_layout(wt)
    cache.write_handoff(
        wt, ctx.rid, {"stage": ctx.stage.id, "mode": ctx.stage.mode, **(handoff_extra or {})}
    )


def _warm_extension_install(ctx: _LaunchContext) -> None:
    """Warm perk's @mgiles/perk npm install into the repo-root .pi/npm/ BEFORE staging it into
    the worktree.

    pi installs a missing project-scope ``npm:`` package lazily and unlocked, so a missing-install
    window + parallel launches let a second process load from a half-installed package and drop
    the perk extension. ``ensure_extension_install_present`` installs-on-absent under a
    cross-process lock (a cheap ``is_dir()`` no-op once present); self-repo-exempt and best-effort
    + non-fatal internally. It is idempotent and depends on neither ``env`` nor ``chdir``, so it
    runs here — the repo-root install is fully warmed before ``materialize_extensions`` clones it
    into the worktree. ``worktree: none`` stages load from this repo-root install directly.
    """
    # Narrate the install ONLY when one is about to happen: the common path (package present) is an
    # instant locked no-op, so a cheap unlocked pre-check decides whether to emit the step line.
    # The extra `is_dir()` is purely cosmetic — the function re-checks authoritatively under its own
    # lock, so it can never cause a double install. When the step IS emitted, always RESOLVE it
    # (every step line becomes a done/warn line): the function returns a change line only when IT
    # installed, so a `None` return means either a concurrent process won the lock (now present ->
    # done) or the install failed (still absent -> warn); a re-check of the package dir
    # disambiguates the two.
    self_repo = init.is_self_repo(ctx.repo_root)
    narrate_install = not self_repo and not consumer_perk_package_dir(ctx.repo_root).is_dir()
    if narrate_install:
        with io_step("installing perk extension (@mgiles/perk)") as s:
            installed_line = init.ensure_extension_install_present(
                ctx.repo_root, self_repo=self_repo
            )
            if installed_line is not None or consumer_perk_package_dir(ctx.repo_root).is_dir():
                s.done("installed perk extension")
            else:
                s.warn("perk extension install failed (non-fatal); pi will install it in-session")
    else:
        init.ensure_extension_install_present(ctx.repo_root, self_repo=self_repo)


def _materialize_into_worktree(ctx: _LaunchContext) -> None:
    """Materialize the plan body, skills mirror, and warmed extensions into the worktree
    (self-gates: worktree stages only).

    The plan body is the per-worktree snapshot ``perk pr review-context`` reads first (offline,
    fetch-once — it reviews the plan as implemented, not whatever the issue says today).
    Best-effort + loud-but-non-fatal (a worktree without a snapshot falls back to a live fetch at
    review time). Consumes ``ResolvedWorktree.plan_ref`` — the one resolved ref that is launch
    authority (no fallback to the mutable root selector). ``materialize_extensions`` clones the
    warmed repo-root .pi/npm/ into the worktree so pi installs nothing at startup (a silent launch
    beneath the banner).
    """
    if ctx.stage.worktree == "none":
        return
    wt = ctx.resolved.path
    materialize_plan_body(ctx.repo_root, wt, ctx.resolved.plan_ref)
    materialize_skills(ctx.repo_root, wt)
    materialize_extensions(ctx.repo_root, wt)


def _emit_linear_run_started(ctx: _LaunchContext) -> None:
    """Mirror the implement-run start into Linear's Agents UI (self-gates: implement only).

    Gated inside the emitter (stamped provider == "linear" AND LINEAR_AGENT_TOKEN) and fully
    fail-soft — it can never block the ``_exec_pi`` that follows. Not reached on --dry-run or
    --remote (``launch_stage`` returns earlier).
    """
    if ctx.stage.id != "implement":
        return
    linear_agent.emit_run_started(
        ctx.resolved.path,
        plan_ref=ctx.resolved.plan_ref,
        run_id=ctx.rid,
        environ=os.environ,
    )


def run_pending_setup(worktree: Path, commands: list[str]) -> None:
    """The marker-gated `[worktree] setup` gesture: run the hook only while the positioner's
    ``setup-pending`` marker is present, and clear the marker **only on success** (immediately
    when no hook is configured) — so a failed setup can never be skipped forever.

    The positioner sets the marker at materialization (``create-fresh``/``restore-remote``); a
    ``reuse-local`` checkout still carrying it is setup-eligible and re-runs the hook here. A
    failure propagates ``run_worktree_setup``'s ``worktree_setup_failed`` with the marker left
    in place (the retry signal). Lives HERE (not ``materialize``) so it reads the facade
    ``run_worktree_setup`` global that ``setattr(launch, "run_worktree_setup", …)`` patches
    rebind (the module-docstring name-binding rule).
    """
    if not cache.has_marker(worktree, cache.SETUP_PENDING):
        return
    run_worktree_setup(worktree, commands)  # raises on failure, leaving the marker
    cache.clear_marker(worktree, cache.SETUP_PENDING)


def _run_setup_hook(ctx: _LaunchContext) -> None:
    """Run the marker-gated `[worktree] setup` before the exec (self-gates: worktree stages).

    Keyed off the positioner's disposition + the ``setup-pending`` marker (never re-derived from
    stage/path state): a fresh/restored materialization carries the marker, and a ``reuse-local``
    checkout still carrying it (a previously failed setup) is setup-eligible and re-runs the
    hook. ``run_pending_setup`` raises on failure with the marker left in place, so a failed
    setup aborts the launch here (before ``exec pi``) and the next run retries it. Never reached
    on a dry run (``launch_stage``'s ``if dry_run:`` branch returns first).
    """
    if ctx.resolved.disposition == "root":
        return
    run_pending_setup(ctx.resolved.path, ctx.config.worktree_setup)


def _build_exec_env(
    *,
    run_id: str,
    environ: Mapping[str, str],
    fallback_linear_api_key: str | None,
    pi_agent_dir: Path | None,
) -> dict[str, str]:
    """Build the environment passed to pi without mutating the operator environment.

    Operator npm/FFF choices override perk's defaults. The run identity and CLI version are
    authoritative launch metadata, so they override conflicting inherited values. A non-blank
    operator ``LINEAR_API_KEY`` wins over the gitignored local-config fallback. Agent-dir
    precedence is already settled by `launch_stage`; a supplied path is assigned verbatim.
    """
    env = {
        **_NPM_QUIET_ENV,
        **FFF_OVERRIDE_ENV,
        **environ,
        "PERK_RUN_ID": run_id,
        "PERK_CLI_VERSION": __version__,
    }
    if not env.get("LINEAR_API_KEY", "").strip() and fallback_linear_api_key is not None:
        env["LINEAR_API_KEY"] = fallback_linear_api_key
    if pi_agent_dir is not None:
        env["PI_CODING_AGENT_DIR"] = str(pi_agent_dir)
    elif not env.get("PI_CODING_AGENT_DIR", "").strip():
        # Pi treats whitespace as a path, but launch precedence treats it as unset.
        env.pop("PI_CODING_AGENT_DIR", None)
    return env


def _resolve_pi_executable() -> str:
    """Resolve the absolute path of the ``pi`` binary — typed refusal on a PATH miss.

    Module-level on purpose: ``_exec_pi`` reads it as a bare facade global, so
    ``monkeypatch.setattr(launch, "_resolve_pi_executable", …)`` rebinds the name it calls
    (the module-docstring name-binding rule). No bare-name fallback — a miss is a
    ``pi_cli_missing`` refusal, never a raw ``FileNotFoundError`` traceback from ``execvpe``'s
    exhausted PATH walk.
    """
    candidate = which_absolute("pi")
    if candidate is None:
        raise UserFacingCliError(
            "pi CLI not found on PATH — install it: "
            "npm install -g @earendil-works/pi-coding-agent (requires Node >= 22).",
            error_type="pi_cli_missing",
        )
    return candidate


def _exec_pi(ctx: _LaunchContext) -> None:
    """Build the child env, sweep stale pi agent locks, chdir into the worktree, and ``exec pi``
    — the CLI *becomes* pi, so nothing after this runs.

    The pi executable is resolved to an ABSOLUTE path pre-chdir via
    :func:`_resolve_pi_executable` (FIRST, before any exec-phase side effect): re-resolving the
    bare name after the chdir would let a relative ``PATH`` entry (e.g. ``.``) pick up a ``pi``
    inside the very worktree being launched into. Bounded protection: this closes pi-name
    substitution from the worktree, not the ``#!/usr/bin/env node`` shebang-interpreter lookup
    (pi's bin script's ``env`` still walks the unchanged ``PATH`` post-chdir — a recorded
    residual; sanitizing the operator's ``PATH`` is out of scope).

    Annotated ``-> None`` (not ``NoReturn``): tests stub ``os.execvpe`` and control returns.
    """
    pi_path = _resolve_pi_executable()  # pre-chdir: aborts the exec phase before any side effect
    # PERK_CLI_VERSION carries the running CLI's version into the launched session so the
    # extension's `session_start` handler can surface a soft drift warning when the live loaded
    # `@mgiles/perk` extension differs from the CLI that launched it (a stale lazy-installed npm:
    # package). Informational only (not run-control data, unlike PERK_RUN_ID); set at this single
    # local-launch seam — the remote worker early-returns before here.
    # Seed LINEAR_API_KEY from the gitignored `.perk/local.toml` `[linear] api_key` so the
    # borrowed in-session `linear_*` tools and any `perk <stage> --json` cold-door worker the
    # session spawns (they inherit this env) can authenticate. Env wins: only fill it when the
    # environment does not already provide the key. Best-effort (fail-soft reader) — reached only
    # on the local path (`--dry-run`/`--remote` returned earlier). Reads from the MAIN checkout
    # (`ctx.repo_root`) and runs before the `os.chdir` below.
    local_linear_key = None
    if not os.environ.get("LINEAR_API_KEY", "").strip():
        local_linear_key = load_local_linear_api_key(ctx.repo_root)
    env = _build_exec_env(
        run_id=ctx.rid,
        environ=os.environ,
        fallback_linear_api_key=local_linear_key,
        pi_agent_dir=ctx.pi_agent_dir,
    )
    _sweep_stale_pi_agent_locks(ctx.pi_agent_dir or _pi_agent_dir())
    # The presence probe does not eliminate the exec race — a failed chdir/exec is an ordinary
    # OSError arm, not a crash (the watch-seam shape).
    try:
        os.chdir(ctx.resolved.path)  # pi's ctx.cwd becomes the worktree; the extension claims there
        # absolute pi path: no bare-name PATH re-resolution after the chdir; argv[0] stays "pi"
        os.execvpe(pi_path, list(ctx.argv), env)  # the CLI *becomes* pi — nothing after this runs
    except OSError as exc:
        raise UserFacingCliError(
            f"could not launch pi in {ctx.resolved.path}: {exc}",
            error_type="launch_failed",
        ) from exc


def _stage_model_argv(config: Config, stage_id: str) -> list[str]:
    """Per-stage ``--model``/``--thinking`` launch flags from `[models.stages.<id>]` (empty
    when unset — pi's own model/thinking defaults are left untouched). Inserted before
    ``pi_args`` so an explicit ``perk <stage> --model X``/``--thinking Y`` overrides it (pi
    parses last-wins)."""
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
    pi_agent_dir: Path | None = None,
) -> None:
    """The side-effect-free ``--dry-run`` preview of a cold-local launch (user lines + the
    machine-readable JSON payload). The remote dispatch preview in :func:`_drive_remote_target`
    is a different payload and stays inline there.

    ``setup`` is the project's ``[worktree] setup`` commands; when the resolution would
    materialize the worktree (a ``create-fresh`` or ``restore-remote`` disposition) and the list
    is non-empty, the planned commands are previewed (but never run — and no marker is written).

    ``sync_main`` mirrors the real-run gate: when the stage WOULD fast-forward the main checkout
    (a read-only ``worktree: none`` stage with sync on), the preview emits a line + a
    ``payload["sync_main"]`` flag (build-once preview-parity discipline).
    """
    user_output(f"would launch stage '{stage.id}' in {resolved.path}")
    user_output(f"  run_id={rid}  PERK_RUN_ID={rid}  argv={' '.join(argv)}")
    if resolved.disposition == "restore-remote":
        user_output(f"  would restore the worktree from {resolved.base} (no fetch on a dry run)")
    payload: dict[str, object] = {
        "success": True,
        "stage": stage.id,
        "worktree": str(resolved.path),
        "run_id": rid,
        "argv": argv,
        "base": resolved.base,
        "disposition": resolved.disposition,
    }
    if pi_agent_dir is not None:
        user_output(f"  PI_CODING_AGENT_DIR={pi_agent_dir}")
        payload["pi_agent_dir"] = str(pi_agent_dir)
    if resolved.plan_ref is not None:
        payload["plan_ref"] = plan.PlanRefOut.from_domain(resolved.plan_ref).model_dump(mode="json")
    would_sync = stage.worktree == "none" and stage.mode == "read-only" and sync_main
    if would_sync:
        user_output("  would sync main checkout (fast-forward) before launch")
        payload["sync_main"] = would_sync
    # Preview the setup commands exactly when a real run would materialize the worktree and run
    # them (the disposition IS the real-run gate — no re-derivation from stage/path state).
    if resolved.disposition in ("create-fresh", "restore-remote") and setup:
        user_output(f"  would run setup: {'; '.join(setup)}")
        payload["setup"] = setup
    machine_output(json.dumps(payload))


__all__ = [
    "FFF_OVERRIDE_ENV",
    "_NPM_QUIET_ENV",
    "_PI_AGENT_LOCK_FILES",
    "_WORKTREE_SETUP_TIMEOUT_S",
    "ResolvedWorktree",
    "Target",
    "WorktreeRequest",
    "_LaunchContext",
    "_address_prompt",
    "_build_argv",
    "_build_exec_env",
    "_drive_remote_target",
    "_emit_dry_run_preview",
    "_emit_linear_run_started",
    "_exec_pi",
    "_fetch_best_effort",
    "_implement_prompt",
    "_initial_prompt",
    "_learn_prompt",
    "_materialize_into_worktree",
    "_pi_agent_dir",
    "_plan_read_instruction",
    "_resolve_pi_executable",
    "_resolve_prompt",
    "_run_setup_hook",
    "_skill_exposure_argv",
    "_stage_model_argv",
    "_sweep_stale_pi_agent_locks",
    "_sync_main_checkout",
    "_warm_extension_install",
    "_write_session_handoff",
    "checked_name",
    "launch_stage",
    "materialize_extensions",
    "materialize_plan_body",
    "materialize_skills",
    "print_launch_banner",
    "print_launch_banner_gated",
    "resolve_base",
    "resolve_plan_worktree_name",
    "resolve_target",
    "resolve_worktree",
    "run_pending_setup",
    "run_worktree_setup",
    "skill_exposure_argv",
]
