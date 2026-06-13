"""Bi-directional guard for the CLI reference page (``docs/user-docs/reference/cli.md``).

The reference quadrant's rule is that the CLI page is written against real ``--help`` output
and guarded by a pytest check, so a documented-but-missing command (or a newly-added,
undocumented one) fails CI. This guard enforces both directions:

- **documented → exists**: every command the page documents resolves in the live CLI.
- **exists → documented**: every non-hidden CLI command (minus a small, justified allowlist)
  is documented.

Wording is NOT string-pinned — the guard checks existence/completeness only; summary accuracy
is human-reviewed (avoids brittleness to ``--help`` rewordings).
"""

import re
from pathlib import Path

import click

from perk.cli.alias import get_aliases
from perk.cli.cli import cli

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_MD = REPO_ROOT / "docs/user-docs/reference/cli.md"

# The only non-hidden, intentionally-undocumented CLI path. ``run-worker`` is the internal CI
# worker entrypoint (positions the checkout + drives a stage headlessly), not an operator-facing
# command, so the reference page deliberately omits it. The hidden ``learn launch`` verb needs no
# allowlist entry — it is already excluded as a hidden command.
ALLOWLIST: set[tuple[str, ...]] = {("run-worker",)}

# A documented heading is `` `perk <path> …` ``; the leading run of command tokens is the path.
_PERK_HEADING = re.compile(r"`perk ([^`]+)`")
_COMMAND_TOKEN = re.compile(r"^[a-z][a-z0-9-]*$")


def _documented_paths(md: str) -> set[tuple[str, ...]]:
    """Extract documented command paths from ``perk …`` markdown headings.

    For each heading line whose text contains `` `perk <…>` ``, split the capture on whitespace,
    drop the leading ``perk``, and keep the leading run of command tokens (``^[a-z][a-z0-9-]*$``),
    stopping at the first non-command token (an option ``-…`` or a ``<…>``/``[…]`` placeholder).
    """
    paths: set[tuple[str, ...]] = set()
    for line in md.splitlines():
        if not re.match(r"^#+\s", line):
            continue
        match = _PERK_HEADING.search(line)
        if match is None:
            continue
        tokens = match.group(1).split()
        path: list[str] = []
        for token in tokens:
            if _COMMAND_TOKEN.match(token):
                path.append(token)
            else:
                break
        if path:
            paths.add(tuple(path))
    return paths


def _cli_command_paths() -> set[tuple[str, ...]]:
    """Walk the live CLI, yielding every group AND leaf path (skipping aliases + hidden)."""
    paths: set[tuple[str, ...]] = set()

    def walk(group: click.Group, prefix: tuple[str, ...]) -> None:
        ctx = click.Context(group)
        alias_names = {a for name in group.commands for a in get_aliases(group.commands[name])}
        for name in group.list_commands(ctx):
            cmd = group.get_command(ctx, name)
            if cmd is None or cmd.hidden or name in alias_names:
                continue
            path = (*prefix, name)
            paths.add(path)
            if isinstance(cmd, click.Group):
                walk(cmd, path)

    walk(cli, ())
    return paths


def _resolve(tokens: tuple[str, ...]) -> click.Command | None:
    """Resolve a command path from the root ``cli``, requiring each intermediate to be a group."""
    ctx = click.Context(cli)
    current: click.Command = cli
    for token in tokens:
        if not isinstance(current, click.Group):
            return None
        nxt = current.get_command(ctx, token)
        if nxt is None:
            return None
        current = nxt
    return current


def test_documented_cli_commands_all_resolve():
    """documented → exists: every documented path resolves in the live CLI."""
    documented = _documented_paths(CLI_MD.read_text())
    unresolved = sorted(path for path in documented if _resolve(path) is None)
    assert not unresolved, "documented commands that no longer resolve: " + ", ".join(
        "perk " + " ".join(path) for path in unresolved
    )


def test_every_cli_command_is_documented():
    """exists → documented: every non-hidden CLI command (minus allowlist) is documented."""
    documented = _documented_paths(CLI_MD.read_text())
    live = _cli_command_paths() - ALLOWLIST
    missing = sorted(live - documented)
    assert not missing, "CLI commands missing from the reference page: " + ", ".join(
        "perk " + " ".join(path) for path in missing
    )


def test_allowlist_entries_are_real_and_excluded():
    """No stale allowlist entry: each path resolves and is genuinely absent from the docs."""
    documented = _documented_paths(CLI_MD.read_text())
    for path in ALLOWLIST:
        assert _resolve(path) is not None, f"stale allowlist entry (does not resolve): {path}"
        assert path not in documented, (
            f"allowlisted path is documented (drop from allowlist): {path}"
        )


def test_documentation_is_non_vacuous():
    """Vacuous-scan self-check: a doc rename / regex break can't silently empty the scan."""
    assert len(_documented_paths(CLI_MD.read_text())) >= 20
