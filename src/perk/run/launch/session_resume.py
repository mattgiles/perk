"""The session-resume engine: open Pi's native session picker (``pi --resume``) in a chosen
checkout, or reopen one RECORDED conversation of a run (``pi --session <file>``) in its recorded
cwd (contracts.md §8.71).

Two doors consume it — the root ``perk resume [TARGET]`` command and ``perk plan resume``'s
non-launching gate arms. Both share ONE call shape: :func:`prepare_session_resume` composes the
launch (argv built once for preview/exec parity), :func:`emit_session_resume_preview` renders
the ``--dry-run`` report, :func:`exec_session_resume` hands the spec to the one shared Pi exec
pipeline (:func:`perk.run.pi_exec.exec_pi`). :func:`resolve_resume_checkout` is the selector
table the root command routes through for the picker arms; :func:`resolve_run_session` is the
run arm's selector.

**The exterior rule.** This engine positions the cwd, composes the launch *environment*, and
execs pi — nothing else. It mints no run_id, writes no handoff, no ``plan-ref`` selector, no
stage prompt, no `[models.stages]` flags, no skills/extension materialization, no setup hook.
The shared pipeline removes an inherited ``PERK_RUN_ID`` (``run_id=None``) so a session that
already carries its identity keeps it (the extension's ``keep`` arm); a session with NO
persisted identity receives the extension's ordinary warm-session mint on load (contracts.md
§8.2 — an in-session branch entry, exactly as a hand-run ``pi`` in the repo; unchanged here).

**No ``--approve``.** Pi resolves project trust for the SELECTED session's cwd AFTER the
picker — whose All scope can open another project's session — so a perk-composed trust override
would auto-trust a project perk never inspected. The engine composes none; Pi's native trust
flow (saved decision / default / interactive prompt) governs the actually-resumed cwd. A
reopened ephemeral ``plan-<id>`` worktree therefore prompts for trust once — accepted. The run
arm keeps the uniform rule (re-evaluated, not inherited): its recorded ``cwd`` is data perk
reads back — any identified session's cwd, a hand-run ``pi`` in a subdirectory included, with
no registered-worktree probe — and Pi resolves trust from the session FILE's header cwd after
opening: the same two-step shape that made the picker's override unsafe.

**The run arm** (:func:`resolve_run_session`). The record is the §8.35 ``session-pointers.json``
under the MAIN checkout's run scratch dir; its ``sessions`` list is the run's
resumable-conversation index (one-to-many — a replan reuses the run id), written by the
extension at every identified ``session_start``. The run id reaches a filesystem path in exactly
ONE place here, :func:`_run_record_path`, which requires the STRICT grammar
(:func:`perk.state.run_id.is_canonical_run_id`) BEFORE any path is derived and then asserts the
derived record path stays under ``scratch/runs/`` (defense in depth — unreachable through the
grammar, proven live by a test that bypasses it); the permissive ``is_run_id`` (gc/runner) and
the class/site capture's write path are untouched. The refusal ladder: ``invalid_input``
(grammar/containment), ``run_not_found`` (no record, an empty ``sessions``, or a CORRUPT record
of any class — bad JSON, invalid UTF-8, a malformed ``at`` — which the reader already warned
about and degraded to ``None``), ``session_missing`` (the recorded file is gone, or Pi has not
flushed a just-started session's file yet), ``checkout_missing`` (the recorded cwd is gone —
never restored here). Collision policy: the entry with the NEWEST first-captured ``at`` wins —
``at`` is Pi's ``toISOString()`` form, validated at the read edge as a real instant (shape +
calendar-valid parse), so lexical order is chronological; ties go to the later list entry; the
others are listed on one stderr line.
"Offline" means no ``[worktree]``/selector config, no issue backend, no ``gh``, no
``select_plan`` — the launch ENVIRONMENT is composed exactly as for every arm
(``resolve_launch_agent_dir(main_root)`` still reads the main checkout's ``[pi] agent_dir`` on
its non-env arm).

**The Linear-key seed crosses projects (accepted residual, contracts.md §8.71(b)).** The shared
pipeline seeds ``LINEAR_API_KEY`` from the MAIN checkout's ``local.toml`` exactly as a stage launch
does — a reopened Linear-backed plan session needs it for the ``linear_*`` tools and the cold-door
workers it spawns. It is process environment, not per-project: a session the human opens from the
All scope in ANOTHER project inherits it, and a project trusted BEFORE loads its extensions with
no new prompt. The same exposure as an operator-exported key in a hand-run ``pi``; the engine
does not narrow the seed for the picker.

**The target table** (:func:`resolve_resume_checkout`; checkouts are never created, restored,
or rebound — the fail-closed validators' typed refusals propagate in their probe order):

===========  ============  ===================================================================
``ref``      ``worktree``  result
===========  ============  ===================================================================
``None``     ``None``      the invocation root (a linked worktree resolves to itself; the
                           main-root ``plan-ref`` selector is NEVER read)
``None``     ``"root"``    the main checkout
``None``     NAME          ``worktree_root / NAME`` — must exist (``worktree_not_found``) and be
                           a registered live worktree (``worktree_unregistered``); no binding
                           is required
ref          ``"root"``    ``invalid_input`` — the main checkout is never a plan's worktree
ref          ``None``      ``worktree_root / plan-<id>`` — must exist and validate against the
                           ref (``worktree_unregistered`` / ``worktree_unbound`` /
                           ``worktree_branch_mismatch`` / ``worktree_plan_mismatch``)
ref          NAME          ``worktree_root / NAME`` — must exist and validate against the ref
RUN_ID       ``None``      the recorded cwd + ``pi --session <file>`` (:func:`resolve_run_session`)
RUN_ID       NAME          ``invalid_input`` — a run id already pins its checkout
===========  ============  ===================================================================

Import direction: this module imports the exec seam (``from perk.run import pi_exec``) and the
facade (``from perk.run import launch``) and reads every shared helper as a module ATTRIBUTE at
call time — ``pi_exec.resolve_launch_agent_dir`` / ``pi_exec.exec_pi`` for the launch
environment, ``launch.<validator>`` for the worktree probes — so the ``pi_exec`` monkeypatches
(the exec recorder included) and the facade patches rebind for it too; the facade never imports
this module (consumers import ``perk.run.launch.session_resume`` directly). No ``os``, no
``git`` here — the exec pipeline lives in ``pi_exec`` and the git probes behind the facade.
"""

import json
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import click

from perk import plan
from perk.cli.ensure import UserFacingCliError
from perk.run import launch, pi_exec
from perk.state import cache, session_pointers
from perk.state import run_id as run_id_mod
from perk.substrate.config import Config
from perk.substrate.output import machine_output, user_output

# The reserved `--worktree` word naming the main checkout; compared BEFORE `checked_name`, so a
# directory literally named `root` under the worktree root is unreachable by name (accepted).
MAIN_CHECKOUT_WORD = "root"

_NEVER_CREATES = "perk resume never creates, restores, or rebinds checkouts"

# Pi's native session picker — the whole argv of the picker arms. It rides the spec (not the exec
# call) so preview and exec read ONE tuple; the run arm varies the argv per spec without changing
# either consumer's call shape.
_PICKER_ARGV: tuple[str, ...] = ("pi", "--resume")

# The run arm: `pi --session <absolute file>`. Pi treats a `/`-bearing argument as a PATH and
# opens it directly — no picker, no "found in a different project → fork?" prompt (that prompt is
# for id matches only).
_RUN_SESSION_ARGV_PREFIX: tuple[str, ...] = ("pi", "--session")


@dataclass(frozen=True)
class SessionResumeLaunch:
    """A composed session-resume launch: where pi runs, the argv shared verbatim by preview and
    exec, the agent-dir half of the launch environment, and — on the run arm — the pinned
    recorded session file (``None`` = the picker)."""

    main_root: Path
    checkout: Path
    argv: tuple[str, ...]
    agent_dir: pi_exec.LaunchAgentDir
    session_file: Path | None = None


@dataclass(frozen=True)
class RunSessionTarget:
    """The run arm's resolved target: the recorded checkout to chdir into, the recorded session
    file to pin, and its ``pi_session_id`` (the file basename) for the announce line."""

    checkout: Path
    session_file: Path
    pi_session_id: str


def prepare_session_resume(
    *, main_root: Path, checkout: Path, session_file: Path | None = None
) -> SessionResumeLaunch:
    """Compose the launch for ``checkout``: the agent dir through the shared launch precedence
    (anchored to the MAIN checkout's config — the run arm is not config-free: it resolves the
    ``[pi] agent_dir`` exactly as the picker does) and the one argv — ``pi --resume`` for the
    picker, or ``pi --session <file>`` when ``session_file`` pins a recorded conversation (an
    ABSOLUTE path: Pi opens a ``/``-bearing argument as a path, with no picker and no fork
    prompt). Nothing else on either arm — no ``--approve`` (see the module docstring), no stage
    flags (the exterior rule). Raises the resolver's ``pi_agent_dir_invalid`` before anything is
    announced."""
    agent_dir = pi_exec.resolve_launch_agent_dir(main_root)
    argv = _PICKER_ARGV if session_file is None else (*_RUN_SESSION_ARGV_PREFIX, str(session_file))
    return SessionResumeLaunch(
        main_root=main_root,
        checkout=checkout,
        argv=argv,
        agent_dir=agent_dir,
        session_file=session_file,
    )


def _run_record_path(main_root: Path, run_id: str) -> Path:
    """The ONE place a run id from the CLI selector becomes a path: the strict grammar gate
    fires BEFORE any derivation, then the derived record path must stay under the run-scratch
    root (both sides ``resolve()``d so macOS ``/private`` aliasing cannot false-trip). Both
    refusals are ``invalid_input``."""
    if not run_id_mod.is_canonical_run_id(run_id):
        raise UserFacingCliError(
            f"{run_id!r} is not a canonical perk run id (a 26-character ULID with optional "
            ".<n> fork suffixes)",
            error_type="invalid_input",
        )
    path = session_pointers.session_pointers_path(main_root, run_id)
    if not path.resolve().is_relative_to(cache.runs_dir(main_root).resolve()):
        raise UserFacingCliError(
            f"refusing run id {run_id!r}: its record path {path} escapes the run-scratch root",
            error_type="invalid_input",
        )
    return path


def _recorded_path_exists(probe: Callable[[], bool]) -> bool:
    """LBYL over a PERSISTED path string (``sessions[].session_file`` / ``.cwd``): an OS refusal
    to even stat it — ``EACCES`` on a parent, ``ENAMETOOLONG``, an embedded NUL (``ValueError``)
    — is the same answer as absence for the selector (the recorded path is unusable either way),
    so the ladder's typed ``session_missing`` / ``checkout_missing`` fire instead of a traceback
    escaping the door's ``UserFacingCliError`` boundary. Python 3.13's ``Path.is_file`` /
    ``is_dir`` swallow only ``ENOENT``-class errors themselves."""
    try:
        return probe()
    except (OSError, ValueError):
        return False


def resolve_run_session(main_root: Path, run_id: str) -> RunSessionTarget:
    """The run arm's selector: the run's newest recorded conversation, or a typed refusal.

    The refusal ladder, in probe order (every message is human-first; the code is the
    ``error_type``):

    1. ``invalid_input`` — the run id fails the strict grammar, or (unreachable through it) its
       record path escapes ``scratch/runs/``. No filesystem probe happens for a refused id.
    2. ``run_not_found`` — no record, an empty ``sessions`` list, or a CORRUPT record of any
       class (the reader warned, naming the path, and degraded to ``None``): the run predates
       session recording or ``perk state prune`` removed its run state.
    3. (collision) several entries — the newest first-captured ``at`` wins; ties go to the later
       list entry; one stderr line lists the others.
    4. ``session_missing`` — the chosen entry's file is not there (Pi writes a new session's
       file only after its first assistant reply, or it was removed) — or cannot be probed
       (:func:`_recorded_path_exists`).
    5. ``checkout_missing`` — the recorded cwd is gone (never restored here) — or cannot be
       probed.
    """
    path = _run_record_path(main_root, run_id)
    record = session_pointers.read_session_pointers(main_root, run_id)
    if record is None or not record.sessions:
        raise UserFacingCliError(
            f"no recorded Pi conversation for run {run_id} (searched {path}) — the run predates "
            "session recording, or its run state was pruned by `perk state prune`; browse the "
            "picker instead: perk resume",
            error_type="run_not_found",
        )
    newest = max(enumerate(record.sessions), key=lambda pair: (pair[1].at, pair[0]))[1]
    if len(record.sessions) > 1:
        others = ", ".join(e.pi_session_id for e in record.sessions if e is not newest)
        user_output(
            f"run {run_id} has {len(record.sessions)} recorded conversations — opening the "
            f"newest ({newest.pi_session_id}); others: {others}"
        )
    session_file = Path(newest.session_file)
    if not _recorded_path_exists(session_file.is_file):
        raise UserFacingCliError(
            f"run {run_id}'s recorded conversation {newest.pi_session_id} has no session file "
            f"at {session_file} — Pi writes a new session's file only after its first assistant "
            "reply (a just-started session has none yet), or the file was removed; browse the "
            "picker instead: perk resume",
            error_type="session_missing",
        )
    checkout = Path(newest.cwd)
    if not _recorded_path_exists(checkout.is_dir):
        raise UserFacingCliError(
            f"run {run_id}'s recorded checkout {checkout} no longer exists — {_NEVER_CREATES}; "
            "perk implement <PLAN> recreates a plan worktree, after which the picker "
            "(perk resume --worktree NAME) lists its conversations",
            error_type="checkout_missing",
        )
    return RunSessionTarget(
        checkout=checkout, session_file=session_file, pi_session_id=newest.pi_session_id
    )


def exec_session_resume(launch_spec: SessionResumeLaunch) -> None:
    """Hand the spec to the one shared Pi exec pipeline with ``run_id=None`` (nothing minted;
    an inherited ``PERK_RUN_ID`` dropped): absolute ``pi`` pre-chdir, the ``LINEAR_API_KEY``
    seed from the main checkout, the stale-lock sweep, chdir + execvpe, ``OSError`` →
    ``launch_failed``. A named entry point so both doors (and later arms) share one call shape.

    Annotated ``-> None`` (not ``NoReturn``): tests stub ``os.execvpe`` and control returns.
    """
    pi_exec.exec_pi(
        main_root=launch_spec.main_root,
        checkout=launch_spec.checkout,
        argv=launch_spec.argv,
        run_id=None,
        agent_dir=launch_spec.agent_dir,
    )


def emit_session_resume_preview(launch_spec: SessionResumeLaunch) -> None:
    """The side-effect-free ``--dry-run`` report: human lines to stderr (four on the picker
    arms; five on the run arm, which adds ``session:``), then ONE JSON payload to stdout with a
    fixed key order for EVERY arm (``success`` · ``checkout`` · ``session_file`` · ``agent_dir``
    · ``agent_dir_source`` · ``argv`` · ``dry_run``) — ``session_file`` is ``null`` on the picker
    arms. ``agent_dir_source == "config"`` is the injection signal (no separate injected-path
    key). Writes nothing."""
    resolution = launch_spec.agent_dir.resolution
    kind = "recorded session" if launch_spec.session_file is not None else "session picker"
    user_output(click.style(f"resume --dry-run ({kind} — resolve only, no launch)", dim=True))
    user_output(f"  checkout: {launch_spec.checkout}")
    if launch_spec.session_file is not None:
        user_output(f"  session:  {launch_spec.session_file}")
    if resolution is not None:
        user_output(f"  agent dir: {resolution.path} ({resolution.source})")
    else:
        user_output("  agent dir: unresolved")
    user_output(f"  command:  {shlex.join(launch_spec.argv)}")
    payload: dict[str, object] = {
        "success": True,
        "checkout": str(launch_spec.checkout),
        "session_file": (
            str(launch_spec.session_file) if launch_spec.session_file is not None else None
        ),
        "agent_dir": str(resolution.path) if resolution is not None else None,
        "agent_dir_source": resolution.source if resolution is not None else None,
        "argv": list(launch_spec.argv),
        "dry_run": True,
    }
    machine_output(json.dumps(payload))


def resolve_resume_checkout(
    *,
    invocation_root: Path,
    main_root: Path,
    config: Config,
    ref: plan.PlanRef | None,
    worktree: str | None,
) -> Path:
    """The selector table (module docstring): which existing checkout the picker opens in.

    Precedence reuse (contracts.md §8.38's selection order): an explicit plan ``ref`` > an
    explicit ``--worktree`` > the invocation root. ``--worktree`` names resolve under the MAIN
    checkout's effective ``worktree_root``. The bare form never reads the main-root ``plan-ref``
    selector — it opens the picker where the command was run. Nothing is created, restored, or
    rebound; the validators' typed refusals propagate in their existing probe order.
    """
    if ref is None:
        if worktree is None:
            return invocation_root
        if worktree == MAIN_CHECKOUT_WORD:
            return main_root
        path = config.worktree_root / launch.checked_name(worktree)
        if not path.exists():
            raise UserFacingCliError(
                f"no checkout named {worktree} at {path} — {_NEVER_CREATES}; "
                f"perk implement <PLAN> --worktree {worktree} creates one",
                error_type="worktree_not_found",
            )
        launch.require_registered_checkout(main_root, path)
        return path
    if worktree == MAIN_CHECKOUT_WORD:
        raise UserFacingCliError(
            "--worktree root names the main checkout, which is never a plan's implementation "
            "worktree — drop TARGET or name a plan worktree",
            error_type="invalid_input",
        )
    if worktree is None:
        path = config.worktree_root / launch.resolve_plan_worktree_name(ref)
        create_hint = f"perk implement {ref.pr_id} creates or restores it"
    else:
        path = config.worktree_root / launch.checked_name(worktree)
        create_hint = f"perk implement {ref.pr_id} --worktree {worktree} creates one"
    if not path.exists():
        raise UserFacingCliError(
            f"no checkout for plan #{ref.pr_id} at {path} — {create_hint}; {_NEVER_CREATES}",
            error_type="worktree_not_found",
        )
    launch.validate_existing_checkout(
        repo_root=main_root, path=path, ref=ref, source="the explicit plan selector"
    )
    return path
