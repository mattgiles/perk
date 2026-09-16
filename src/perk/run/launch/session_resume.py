"""The session-resume engine: open Pi's native session picker (``pi --resume``) in a chosen
checkout (contracts.md §8.71).

Two doors consume it — the root ``perk resume [TARGET]`` command and ``perk plan resume``'s
non-launching gate arms. Both share ONE call shape: :func:`prepare_session_resume` composes the
launch (argv built once for preview/exec parity), :func:`emit_session_resume_preview` renders
the ``--dry-run`` report, :func:`exec_session_resume` hands the spec to the one shared Pi exec
pipeline (:func:`perk.run.launch.exec_pi`). :func:`resolve_resume_checkout` is the selector
table the root command routes through.

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
reopened ephemeral ``plan-<id>`` worktree therefore prompts for trust once — accepted.

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
===========  ============  ===================================================================

Import direction: this module imports the facade (``from perk.run import launch``) and reads
every shared helper as a facade ATTRIBUTE at call time, so facade monkeypatches (the exec
recorder included) rebind for it too; the facade never imports this module (consumers import
``perk.run.launch.session_resume`` directly). No ``os``, no ``git`` here — the exec pipeline
and the git probes live behind the facade.
"""

import json
import shlex
from dataclasses import dataclass
from pathlib import Path

import click

from perk import plan
from perk.cli.ensure import UserFacingCliError
from perk.run import launch
from perk.substrate.config import Config
from perk.substrate.output import machine_output, user_output

# The reserved `--worktree` word naming the main checkout; compared BEFORE `checked_name`, so a
# directory literally named `root` under the worktree root is unreachable by name (accepted).
MAIN_CHECKOUT_WORD = "root"

_NEVER_CREATES = "perk resume never creates, restores, or rebinds checkouts"


@dataclass(frozen=True)
class SessionResumeLaunch:
    """A composed session-picker launch: where pi runs, the argv shared verbatim by preview and
    exec, and the agent-dir half of the launch environment."""

    main_root: Path
    checkout: Path
    argv: tuple[str, ...]
    agent_dir: launch.LaunchAgentDir


def prepare_session_resume(*, main_root: Path, checkout: Path) -> SessionResumeLaunch:
    """Compose the picker launch for ``checkout``: the agent dir through the shared launch
    precedence (anchored to the MAIN checkout's config) and the one argv — ``pi --resume``,
    nothing else (no ``--approve``: see the module docstring; no stage flags: the exterior
    rule). Raises the resolver's ``pi_agent_dir_invalid`` before anything is announced."""
    agent_dir = launch.resolve_launch_agent_dir(main_root)
    return SessionResumeLaunch(
        main_root=main_root,
        checkout=checkout,
        argv=("pi", "--resume"),
        agent_dir=agent_dir,
    )


def exec_session_resume(launch_spec: SessionResumeLaunch) -> None:
    """Hand the spec to the one shared Pi exec pipeline with ``run_id=None`` (nothing minted;
    an inherited ``PERK_RUN_ID`` dropped): absolute ``pi`` pre-chdir, the ``LINEAR_API_KEY``
    seed from the main checkout, the stale-lock sweep, chdir + execvpe, ``OSError`` →
    ``launch_failed``. A named entry point so both doors (and later arms) share one call shape.

    Annotated ``-> None`` (not ``NoReturn``): tests stub ``os.execvpe`` and control returns.
    """
    launch.exec_pi(
        main_root=launch_spec.main_root,
        checkout=launch_spec.checkout,
        argv=launch_spec.argv,
        run_id=None,
        agent_dir=launch_spec.agent_dir,
    )


def emit_session_resume_preview(launch_spec: SessionResumeLaunch) -> None:
    """The side-effect-free ``--dry-run`` report: human lines to stderr, then ONE JSON payload
    to stdout with a fixed key order (``success`` · ``checkout`` · ``agent_dir`` ·
    ``agent_dir_source`` · ``argv`` · ``dry_run``). ``agent_dir_source == "config"`` is the
    injection signal (no separate injected-path key). Writes nothing."""
    resolution = launch_spec.agent_dir.resolution
    user_output(
        click.style("resume --dry-run (session picker — resolve only, no launch)", dim=True)
    )
    user_output(f"  checkout: {launch_spec.checkout}")
    if resolution is not None:
        user_output(f"  agent dir: {resolution.path} ({resolution.source})")
    else:
        user_output("  agent dir: unresolved")
    user_output(f"  command:  {shlex.join(launch_spec.argv)}")
    payload: dict[str, object] = {
        "success": True,
        "checkout": str(launch_spec.checkout),
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
