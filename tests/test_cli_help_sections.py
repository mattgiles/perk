"""Sectioned root-group help (``SectionedGroup``).

The root ``perk --help`` renders curated sections (Top-Level Commands / Command Groups /
Initialization / Other / Hidden) while preserving the parenthetical alias display; subgroups
stay flat. A drift guard walks the live root surface so the curated lists partition it cleanly.
"""

import click
from click.testing import CliRunner

from perk.cli.alias import (
    COMMAND_GROUPS,
    INITIALIZATION,
    TOP_LEVEL_COMMANDS,
    SectionedGroup,
    get_aliases,
)
from perk.cli.cli import cli


def _between(output: str, start_header: str, end_header: str | None) -> str:
    """Return the slice of ``output`` between two section headers (exclusive of the headers)."""
    start = output.index(start_header) + len(start_header)
    end = output.index(end_header) if end_header else len(output)
    return output[start:end]


def test_root_help_renders_section_headers():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Top-Level Commands:" in result.output
    assert "Command Groups:" in result.output
    assert "Initialization:" in result.output


def test_command_groups_section_lists_groups():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    groups_slice = _between(result.output, "Command Groups:", "Initialization:")
    for entry in (
        "worktree (wt)",
        "objective (obj)",
        "pr",
        "registry (reg)",
        "state (st)",
        "workflow",
    ):
        assert entry in groups_slice, entry
    top_slice = _between(result.output, "Top-Level Commands:", "Command Groups:")
    # The group rows (with their parenthetical aliases) must not appear under Top-Level Commands.
    for entry in ("worktree (wt)", "objective (obj)", "registry (reg)", "state (st)"):
        assert entry not in top_slice, entry


def test_init_under_initialization():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    init_slice = _between(result.output, "Initialization:", "Other:")
    assert "init" in init_slice


def test_workers_render_under_other():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    other_slice = _between(result.output, "Other:", None)
    assert "run-worker" in other_slice


def test_pr_group_lists_all_verbs():
    result = CliRunner().invoke(cli, ["pr", "--help"])
    assert result.exit_code == 0
    for verb in (
        "submit",
        "check",
        "ready",
        "land",
        "feedback",
        "resolve-threads",
        "review-context",
        "review-post",
    ):
        assert verb in result.output, verb


def test_flat_pr_spellings_are_gone():
    # No backwards-compat alias survives the pr-* → `pr <verb>` fold.
    result = CliRunner().invoke(cli, ["pr-submit"])
    assert result.exit_code != 0


def test_aliases_still_parenthetical():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "worktree (wt)" in result.output
    assert "implement (impl)" in result.output
    for line in result.output.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("wt "), line
        assert not stripped.startswith("impl "), line


def _synthetic_group() -> SectionedGroup:
    grp = SectionedGroup("syn")

    @grp.command("visible")
    def _visible() -> None:
        """A visible command."""

    @grp.command("secret", hidden=True)
    def _secret() -> None:
        """A hidden command."""

    return grp


def test_hidden_section_default_omits(monkeypatch):
    monkeypatch.delenv("PERK_SHOW_HIDDEN", raising=False)
    result = CliRunner().invoke(_synthetic_group(), ["--help"])
    assert result.exit_code == 0
    assert "Hidden:" not in result.output
    assert "secret" not in result.output


def test_hidden_section_shown_with_env(monkeypatch):
    monkeypatch.setenv("PERK_SHOW_HIDDEN", "1")
    result = CliRunner().invoke(_synthetic_group(), ["--help"])
    assert result.exit_code == 0
    assert "Hidden:" in result.output
    hidden_slice = result.output[result.output.index("Hidden:") :]
    assert "secret" in hidden_slice


def test_section_lists_drift_guard():
    ctx = click.Context(cli)
    alias_names = {a for name in cli.commands for a in get_aliases(cli.commands[name])}
    visible: set[str] = set()
    for name in cli.list_commands(ctx):
        cmd = cli.get_command(ctx, name)
        if cmd is None or cmd.hidden or name in alias_names:
            continue
        visible.add(name)

    curated = [set(TOP_LEVEL_COMMANDS), set(COMMAND_GROUPS), set(INITIALIZATION)]

    # (a) No stale entries: every curated name resolves to a live root command.
    for bucket in curated:
        for name in bucket:
            assert name in cli.commands, f"stale curated entry: {name}"

    # (b) The three curated lists are pairwise disjoint.
    assert curated[0] & curated[1] == set()
    assert curated[0] & curated[2] == set()
    assert curated[1] & curated[2] == set()

    # (c) Union of (curated ∩ visible) + Other catch-all == full visible set.
    categorized = (curated[0] | curated[1] | curated[2]) & visible
    other = visible - categorized
    assert categorized | other == visible
