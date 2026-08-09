"""`perk worktree checkout` — print or activate a worktree by name.

A subprocess can never ``cd`` its parent shell, so bare invocation prints the target's
absolute path on stdout (composes with ``cd "$(perk wt co NAME)"``) and ``--script`` emits a
minimal ``cd`` script for ``source <(perk wt co NAME --script)`` — the gesture that actually
moves the current shell.
"""

import re
import shlex
from pathlib import Path

import click

from perk.cli.alias import alias
from perk.cli.context import require_config, require_repo
from perk.cli.ensure import Ensure, UserFacingCliError
from perk.substrate import git
from perk.substrate.git import GitError
from perk.substrate.output import machine_output, user_output

# The plan-number sugar: a bare number (`3`) or `#`-prefixed number (`#3`) resolves to `plan-3`.
_PLAN_NUMBER_RE = re.compile(r"^#?(\d+)$")


@alias("co")
@click.command("checkout")
@click.argument("name")
@click.option(
    "--script",
    is_flag=True,
    help="Emit a cd script on stdout for `source <(perk wt co NAME --script)`.",
)
@click.pass_context
def checkout_worktree(ctx: click.Context, *, name: str, script: bool) -> None:
    """Print or activate the worktree NAME.

    Bare invocation prints the worktree's absolute path on stdout (composes with
    `cd "$(perk wt co NAME)"`); `source <(perk wt co NAME --script)` changes directory in the
    current shell. NAME `root` navigates back to the main checkout, and a bare plan number
    (`3` or `#3`) resolves to `plan-3`.
    """
    _checkout_impl(
        repo_root=require_repo(ctx),
        worktree_root=require_config(ctx).worktree_root,
        name=name,
        script=script,
    )


def _checkout_impl(*, repo_root: Path, worktree_root: Path, name: str, script: bool) -> None:
    try:
        target = _resolve_target(repo_root, worktree_root, name)
    except UserFacingCliError:
        if script:
            # `source <(cmd)` cannot see cmd's exit code, so the sourced content itself must
            # return non-zero for a failure to break `&&` chains. Emit a valid error stub on
            # stdout, then re-raise so Click still prints `Error: …` on stderr and exits 1.
            machine_output("# perk error\nreturn 1\n", nl=False)
        raise
    if script:
        machine_output(_render_cd_script(target, _label(repo_root, target, name)), nl=False)
        return
    machine_output(str(target))
    # `shlex.quote` quotes only when needed, so the common hint stays clean while a name with
    # shell metacharacters (`#7`, spaces) survives pasting as one argument.
    user_output(f"to switch: source <(perk wt co {shlex.quote(name)} --script)")


def _resolve_target(repo_root: Path, worktree_root: Path, name: str) -> Path:
    """Resolve NAME to an absolute directory: `root` keyword → literal match → plan-number
    sugar. A literal match always beats the sugar; a miss raises ``UserFacingCliError``.

    NAME is confined under the worktree root (no separators, no `.`/`..` — the same validation
    as `worktree create`), so traversal (`../sibling`) and absolute inputs (`/tmp`, which a
    ``Path`` join would silently adopt wholesale) cannot name an arbitrary filesystem entry.
    Only directories resolve — a regular file would just make the emitted ``cd`` fail.
    """
    if name == "root":
        return git.main_worktree_root(repo_root) or repo_root
    Ensure.invariant(
        "/" not in name and name not in (".", ".."),
        f"Invalid worktree name '{name}' — no path separators.",
    )
    literal = worktree_root / name
    if literal.is_dir():
        return literal
    match = _PLAN_NUMBER_RE.match(name)
    if match:
        sugar = worktree_root / f"plan-{match.group(1)}"
        if sugar.is_dir():
            return sugar
        raise UserFacingCliError(f"Worktree not found: {literal} (also tried {sugar})")
    raise UserFacingCliError(f"Worktree not found: {literal}")


def _label(repo_root: Path, target: Path, name: str) -> str:
    """The display label for the script's echo: ``name [branch]``, best-effort.

    ``.resolve()`` on both sides of the path comparison is mandatory (macOS ``/var`` →
    ``/private/var``; see docs/learned/workflow/worktree-lifecycle.md). When the dir exists but
    is not a registered worktree the bracket suffix is omitted — a plain ``cd`` is still valid,
    so uncertainty in the branch lookup never blocks navigation.
    """
    try:
        worktrees = git.worktree_list(repo_root)
    except GitError:
        return name
    resolved = target.resolve()
    for wt in worktrees:
        if wt.path.resolve() == resolved:
            return f"{name} [{wt.branch or '(detached)'}]"
    return name


def _sq(text: str) -> str:
    """Single-quote ``text`` for POSIX shells (`'` becomes `'\\''`)."""
    return "'" + text.replace("'", "'\\''") + "'"


def _render_cd_script(target: Path, label: str) -> str:
    """A minimal POSIX ``cd`` script (bash/zsh) — no temp files, no logging helpers.

    The ``|| return 1`` guard keeps a failed ``cd`` (e.g. the directory vanished between
    resolution and sourcing) from being masked by the success echo — the sourced script
    returns non-zero and `&&` chains break, mirroring the resolution-failure stub.
    """
    lines = [
        "# perk worktree checkout",
        f"cd {_sq(str(target))} || return 1",
        f"echo {_sq(f'✓ checked out {label}')}",
    ]
    return "\n".join(lines) + "\n"
