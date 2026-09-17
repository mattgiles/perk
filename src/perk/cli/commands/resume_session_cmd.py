"""``perk resume [TARGET]`` — browse and reopen Pi conversations for a checkout (``pi --resume``),
or reopen one run's recorded conversation directly (``pi --session <file>``).

The root session-resume door (contracts.md §8.71): resolve WHICH existing checkout to open the
picker in (the invocation root by default; ``--worktree NAME`` / ``--worktree root``; or a
plan's bound worktree via the positional ``TARGET``), compose the launch environment through
the shared engine (:mod:`perk.run.launch.session_resume`), and exec ``pi --resume`` there. The
picker itself is Pi's own (Current Folder / All scopes, search, empty lists, cancellation);
project trust for the reopened session follows Pi's own trust flow — perk composes no
``--approve``.

**The run arm.** ``TARGET`` routes by grammar first: a canonical perk run id (the strict
``is_canonical_run_id`` — a 26-character ULID with optional ``.<n>`` fork suffixes) reopens
that run's newest recorded conversation in its recorded checkout via the engine's
``resolve_run_session`` — offline: no ``[worktree]``/selector config, no issue backend, no
``gh``, no ``select_plan`` (the launch ENVIRONMENT is still composed through the shared seams,
the ``[pi] agent_dir`` precedence included). ``--worktree`` is refused with a run id (it already
pins its checkout). Anything else is a plan selector as before.

The exterior rule: perk mints no run id, writes no handoff or plan selector, adds no stage
prompt or `[models.stages]` flags, materializes nothing, runs no setup hook. An inherited
``PERK_RUN_ID`` is dropped so the reopened session keeps its own recorded identity.

Terminal-only: Pi 0.85.1's ``--resume`` constructs its TUI selector even on a pipe, so a
non-interactive invocation without ``--dry-run`` refuses ``not_a_tty`` — decided right after
``not_a_repo`` and BEFORE any config load, backend auth, or selection, so a scripted call fails
fast with no config or backend read. Not a registry stage: no ``MergedCommand``, no launcher
grammar, no ``--json``, no ``--remote``, no pi pass-through args, no launch banner.

Exit codes: 0 dry-run · 1 typed refusals (``not_a_tty``, ``worktree_*``, ``invalid_input``,
``run_not_found``, ``session_missing``, ``checkout_missing``, ``pi_cli_missing``,
``launch_failed``, selection errors) · 2 not-a-repo · a successful exec never returns (the
terminal receives pi's own exit status).
"""

import shlex
import sys

import click

from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.cli import completions
from perk.cli.context import require_github, require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.cli.plan_selection import load_main_config, main_repo_root, select_plan
from perk.github import GitHubError
from perk.run.launch import session_resume
from perk.state import run_id as run_id_mod
from perk.substrate.output import user_output


def _require_terminal() -> None:
    """The terminal-only rule: both stdin and stdout must be TTYs for the picker (typed
    ``not_a_tty``; the human failure path renders only the message). Reads this module's
    ``sys`` so tests can swap it (``CliRunner`` replaces ``sys.stdin`` itself)."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise UserFacingCliError(
            "perk resume opens Pi's interactive session picker, which needs a terminal on stdin "
            "and stdout — run it from a terminal, or pass --dry-run to preview the target",
            error_type="not_a_tty",
        )


@click.command("resume")
@click.argument("target", required=False, shell_complete=completions.complete_plan_id)
@click.option(
    "--worktree",
    type=str,
    default=None,
    metavar="NAME",
    help=(
        "An existing checkout by directory name under the configured worktree root; root "
        "selects the main checkout. With TARGET, the named checkout must be bound to that plan."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Resolve + print the checkout, agent dir and pi command without launching.",
)
@click.pass_context
def resume_session(
    ctx: click.Context, *, target: str | None, worktree: str | None, dry_run: bool
) -> None:
    """Browse and reopen Pi conversations for a checkout (pi --resume), or reopen one run's
    recorded conversation directly (pi --session).

    \b
    Where the picker opens:
      perk resume                       this checkout (a plan worktree resolves to itself)
      perk resume --worktree NAME       an existing checkout under the worktree root
      perk resume --worktree root       the main checkout
      perk resume PLAN                  the plan's bound worktree (plan-<id>)
      perk resume PLAN --worktree NAME  a named checkout that must be bound to PLAN
      perk resume PLAN --worktree root  refused: the main checkout is never a plan's
                                        worktree — drop PLAN or name a plan worktree
      perk resume RUN_ID                the run's newest recorded conversation, in its
                                        recorded checkout
      perk resume RUN_ID --worktree NAME  refused: a run id pins its checkout

    \b
    TARGET is a plan issue id (e.g. 42, #42, ENG-123, or the pasted issue URL) — or the
    plan's PR: its number or pasted .../pull/N URL. TARGET may also be a perk run id (a
    26-character ULID, optionally with .<n> fork suffixes — from the plan header's run_id /
    impl_run_ids or perk state show): it reopens that run's newest recorded conversation
    directly (pi --session <file>) in its recorded checkout, listing any others; --worktree
    is refused with a run id. Checkouts are never created, restored, or rebound (perk
    implement does that); a missing or mismatched checkout is a typed refusal.

    \b
    The picker is Pi's own: Current Folder / All scopes, search, empty lists and cancellation
    are Pi's. Project trust for the reopened session follows Pi's own trust flow (perk passes
    no --approve). perk mints no run id, writes no handoff or plan selector, and adds no
    stage prompt — an inherited PERK_RUN_ID is dropped so the reopened session keeps its own
    identity. The agent directory follows PI_CODING_AGENT_DIR, then the main checkout's
    [pi] agent_dir, then Pi's default. Terminal-only: stdin and stdout must be a TTY unless
    --dry-run is passed.

    \b
    Examples:
      perk resume                        # pick a session for this checkout
      perk resume --worktree plan-42     # pick a session for the plan-42 checkout
      perk resume --worktree root        # pick a session for the main checkout
      perk resume 42                     # pick a session for plan #42's worktree
      perk resume 42 --worktree plan-42-b
      perk resume 42 --dry-run           # print the resolved checkout + command, launch nothing
      perk resume 01ARZ3NDEKTSV4RRFFQ69G5FAV  # reopen that run's conversation
    """
    try:
        invocation_root = require_repo(ctx)  # `not_a_repo` is decided first, as everywhere
        if not dry_run:
            _require_terminal()  # fail fast: before any config load, backend auth, or selection
        # Two-roots rule: config, backend reads, and `--worktree` names anchor to the MAIN
        # checkout; the bare form positions at the INVOCATION root (never the root selector).
        main_root = main_repo_root(invocation_root)
        if target is not None and run_id_mod.is_canonical_run_id(target):
            # The run arm — routed by grammar BEFORE any config load: no `[worktree]` selector
            # config, no backend resolution, no `gh`, no `select_plan`. The record pins the
            # checkout, so `--worktree` has nothing to select.
            if worktree is not None:
                raise UserFacingCliError(
                    "TARGET is a run id, which already pins its recorded checkout — drop "
                    "--worktree, or name a plan or checkout instead",
                    error_type="invalid_input",
                )
            run = session_resume.resolve_run_session(main_root, target)
            spec = session_resume.prepare_session_resume(
                main_root=main_root, checkout=run.checkout, session_file=run.session_file
            )
            announce = (
                f"reopening run {target}'s recorded conversation {run.pi_session_id} in "
                f"{run.checkout}: {shlex.join(spec.argv)}"
            )
        else:
            config = load_main_config(main_root)
            ref = None
            if target is not None:
                # Backend-conditional auth (the `plan from` precedent): only the GitHub backend
                # needs a working `gh`; a Linear-backed repo authenticates through its own
                # errors.
                if resolve.resolve_issue_backend_id(main_root) == resolve.GITHUB_BACKEND_ID:
                    require_github(ctx)
                ref = select_plan(main_root, target).ref
            checkout = session_resume.resolve_resume_checkout(
                invocation_root=invocation_root,
                main_root=main_root,
                config=config,
                ref=ref,
                worktree=worktree,
            )
            spec = session_resume.prepare_session_resume(main_root=main_root, checkout=checkout)
            announce = f"opening Pi's session picker in {checkout}: {shlex.join(spec.argv)}"
        if dry_run:  # side-effect-free: no selector, no handoff, no run id
            session_resume.emit_session_resume_preview(spec)
            return
        user_output(announce)
        session_resume.exec_session_resume(spec)  # the CLI *becomes* pi — nothing after this runs
    except (IssueBackendError, GitHubError) as exc:
        fail(ctx, as_json=False, error_type="github_error", message=f"resume failed\n{exc}")
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=False,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
