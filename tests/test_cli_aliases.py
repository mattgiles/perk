"""Aliases are pure CLI sugar: every declared alias resolves to its primary command.

Walks the live ``cli`` surface so a future collision/typo trips the table-driven guard, and
spot-checks behavioral equivalence + the dedup'd ``--help`` rendering.
"""

from pathlib import Path

import click
from click.testing import CliRunner

from perk.cli.alias import AliasGroup, SectionedGroup, get_aliases
from perk.cli.cli import cli
from perk.cli.context import PerkContext
from perk.substrate.config import Config


def _ctx(repo: Path) -> PerkContext:
    return PerkContext.for_test(
        cwd=repo, repo_root=repo, config=Config(worktree_root=repo / ".worktrees")
    )


# The full declared vocabulary (kept in lock-step with the @alias annotations).
EXPECTED_ROOT_ALIASES = {
    "worktree": "wt",
    "objective": "obj",
    "registry": "reg",
    "state": "st",
    "implement": "impl",
    "objective-plan": "oplan",
    "resume": "res",
    "replan": "rp",
    "plan-save": "psave",
}


def _walk(group: click.Group) -> list[tuple[click.Group, str, click.Command]]:
    """Yield (parent_group, primary_name, cmd) for every primary (non-alias) command."""
    out: list[tuple[click.Group, str, click.Command]] = []
    alias_names = {a for name in group.commands for a in get_aliases(group.commands[name])}
    seen: set[str] = set()
    for name, cmd in group.commands.items():
        if name in alias_names or cmd.name in seen:
            continue
        seen.add(cmd.name or name)
        out.append((group, cmd.name or name, cmd))
        if isinstance(cmd, click.Group):
            out.extend(_walk(cmd))
    return out


def test_every_alias_points_back_to_its_primary():
    """Each declared alias must register the same Command object as its primary name."""
    for parent, primary, cmd in _walk(cli):
        for alias_name in get_aliases(cmd):
            assert alias_name in parent.commands, f"{alias_name} not registered in {parent.name}"
            assert parent.commands[alias_name] is cmd, (
                f"alias {alias_name} does not resolve to primary {primary}"
            )


def test_root_alias_table_matches_expected():
    declared = {
        cmd.name: get_aliases(cmd)[0]
        for cmd in cli.commands.values()
        if get_aliases(cmd) and cmd.name in EXPECTED_ROOT_ALIASES
    }
    assert declared == EXPECTED_ROOT_ALIASES


def test_alias_resolves_same_behavior(git_repo):
    runner = CliRunner()
    obj = _ctx(git_repo)
    full = runner.invoke(cli, ["worktree", "list"], obj=obj)
    aliased = runner.invoke(cli, ["wt", "ls"], obj=obj)
    assert full.exit_code == aliased.exit_code == 0
    assert full.output == aliased.output


def test_top_level_alias_help_equivalent():
    # The alias surfaces the same command; only the prog name in the Usage line differs.
    runner = CliRunner()
    aliased = runner.invoke(cli, ["impl", "--help"]).output.replace("cli impl", "cli implement")
    assert aliased == runner.invoke(cli, ["implement", "--help"]).output


def test_registry_and_state_aliases_resolve():
    runner = CliRunner()
    assert runner.invoke(cli, ["reg", "ch"]).exit_code == 0
    assert runner.invoke(cli, ["st", "s"], obj=_ctx(Path.cwd())).exit_code == 0


def test_help_lists_alias_in_parenthetical_only():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "worktree (wt)" in result.output
    assert "implement (impl)" in result.output
    # The alias name must not appear as its own command row.
    for line in result.output.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("wt "), line
        assert not stripped.startswith("impl "), line


def test_subgroup_help_dedups_aliases():
    result = CliRunner().invoke(cli, ["worktree", "--help"])
    assert result.exit_code == 0
    assert "list (ls)" in result.output
    assert "remove (rm)" in result.output
    assert "create (new)" in result.output


def test_root_and_subgroups_use_alias_group():
    assert isinstance(cli, AliasGroup)
    assert isinstance(cli, SectionedGroup)
    for name in ("worktree", "objective", "registry", "state"):
        assert isinstance(cli.commands[name], AliasGroup)
        assert not isinstance(cli.commands[name], SectionedGroup)


def test_objective_run_and_alias_resolve():
    """`perk objective run` and `perk obj r` resolve to the supervisor command (Node 3.4)."""
    objective_group = cli.commands["objective"]
    assert isinstance(objective_group, click.Group)
    assert "run" in objective_group.commands
    assert objective_group.commands["r"] is objective_group.commands["run"]
    assert cli.commands["obj"] is objective_group
