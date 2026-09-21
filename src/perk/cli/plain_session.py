"""The bare-``perk`` plain-session door: exec a plain ``pi`` in the current checkout with perk's
configured launch environment (contracts.md §8.72, sharing §8.71(b)'s exterior rule)."""

import shlex
import sys

import click

from perk.cli.context import require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.cli.plan_selection import main_repo_root
from perk.run import launch
from perk.substrate.output import user_output

# The whole argv — literally `pi`, never `--approve`: Pi's own trust flow governs the invocation
# root, exactly as for a hand-run `pi` and for `perk resume`.
PLAIN_SESSION_ARGV: tuple[str, ...] = ("pi",)

_NOT_A_REPO_HINT = (
    "Bare `perk` opens a Pi session in a repo checkout — run `pi` directly here, or "
    "`perk --help` for the commands."
)


def _require_terminal() -> None:
    """The terminal-only rule: both stdin and stdout must be TTYs — the plain session is an
    interactive Pi TUI (typed ``not_a_tty``; the human failure path renders only the message).
    Reads this module's ``sys`` so tests can swap it (``CliRunner`` replaces ``sys.stdin``)."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise UserFacingCliError(
            "bare `perk` opens an interactive Pi session, which needs a terminal on stdin and "
            "stdout — run it from a terminal, or `perk --help` for the command list",
            error_type="not_a_tty",
        )


def run_plain_session(ctx: click.Context) -> None:
    """The bare-``perk`` arm of the root callback: a session launch that is not a stage launch.

    The ordered pipeline mirrors ``perk resume``'s bare arm — ``not_a_repo`` first, then the
    terminal check BEFORE any perk config read or agent-dir resolution (a scripted call fails
    fast), then the two-roots rule (config anchors to the MAIN checkout; the session opens at the
    invocation root, so a linked worktree resolves to itself), the shared agent-dir precedence
    (its missing-dir warning and ``pi_agent_dir_invalid`` refusal ride along), ONE announce line
    (emitted only after the agent dir resolved, so a refusal never follows an "opening" line —
    the exec-phase ``pi_cli_missing`` / ``launch_failed`` arms land after it), and the one shared
    Pi exec pipeline with ``run_id=None`` (an inherited ``PERK_RUN_ID`` is dropped; the extension
    mints its ordinary warm-session id on load, as for a hand-run ``pi``).

    ``launch.resolve_launch_agent_dir`` / ``launch.exec_pi`` are read as facade attributes at
    call time so facade monkeypatches (the exec recorder included) rebind for this arm too. Only
    ``UserFacingCliError`` is caught: an ``OSError`` / ``UnicodeDecodeError`` inside the shared
    config or ``local.toml`` readers is untyped and propagates through Click's ordinary
    exception boundary, as on every other cold launch.
    """
    try:
        invocation_root = require_repo(ctx)  # `not_a_repo` is decided first, as everywhere
        _require_terminal()  # fail fast: before any config load or agent-dir resolution
        main_root = main_repo_root(invocation_root)
        agent_dir = launch.resolve_launch_agent_dir(main_root)
        user_output(
            f"opening a plain Pi session in {invocation_root}: {shlex.join(PLAIN_SESSION_ARGV)}"
        )
        launch.exec_pi(
            main_root=main_root,
            checkout=invocation_root,
            argv=PLAIN_SESSION_ARGV,
            run_id=None,
            agent_dir=agent_dir,
        )  # the CLI *becomes* pi — nothing after this runs
    except UserFacingCliError as exc:
        message = exc.format_message()
        if exc.error_type == "not_a_repo":
            message = f"{message}\n{_NOT_A_REPO_HINT}"
        fail(
            ctx,
            as_json=False,
            error_type=exc.error_type or "invalid_input",
            message=message,
        )
