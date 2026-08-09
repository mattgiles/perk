"""`perk worktree checkout` — print or activate a worktree by name.

A subprocess can never ``cd`` its parent shell, so bare invocation prints the target's
absolute path on stdout (composes with ``cd "$(perk wt co NAME)"``) and ``--script`` emits a
minimal ``cd`` script for ``source <(perk wt co NAME --script)`` — the gesture that actually
moves the current shell.
"""

import re
from pathlib import Path

import click

from perk.cli.alias import alias
from perk.cli.context import require_config, require_repo
from perk.cli.ensure import UserFacingCliError
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
    user_output(f"to switch: source <(perk wt co {name} --script)")


def _resolve_target(repo_root: Path, worktree_root: Path, name: str) -> Path:
    """Resolve NAME to an absolute directory: `root` keyword → literal match → plan-number
    sugar. A literal match always beats the sugar; a miss raises ``UserFacingCliError``."""
    if name == "root":
        return git.main_worktree_root(repo_root) or repo_root
    literal = worktree_root / name
    if literal.exists():
        return literal
    match = _PLAN_NUMBER_RE.match(name)
    if match:
        sugar = worktree_root / f"plan-{match.group(1)}"
        if sugar.exists():
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
    """A minimal POSIX ``cd`` script (bash/zsh) — no temp files, no logging helpers."""
    lines = [
        "# perk worktree checkout",
        f"cd {_sq(str(target))}",
        f"echo {_sq(f'✓ checked out {label}')}",
    ]
    return "\n".join(lines) + "\n"
