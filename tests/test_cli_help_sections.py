"""Sectioned root-group help (``SectionedGroup``).

The root ``perk --help`` renders curated sections (Stage Launchers / Command Groups /
Setup & Health / Other / Hidden) while preserving the parenthetical alias display; subgroups
stay flat. A drift guard walks the live root surface so the curated lists partition it cleanly.
"""

import click
from click.testing import CliRunner

from perk.cli.alias import (
    COMMAND_GROUPS,
    SETUP_HEALTH,
    STAGE_LAUNCHERS,
    SectionedAliasGroup,
    SectionedGroup,
    get_aliases,
    mark_kind,
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
    assert "Stage Launchers" in result.output
    assert "each opens a primed pi session" in result.output
    assert "Command Groups:" in result.output
    assert "Setup & Health:" in result.output


def test_command_groups_section_lists_groups():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    groups_slice = _between(result.output, "Command Groups:", "Setup & Health:")
    for entry in (
        "worktree (wt)",
        "objective (obj)",
        "pr",
        "registry (reg)",
        "state (st)",
        "workflow",
    ):
        assert entry in groups_slice, entry
    launchers_slice = _between(result.output, "Stage Launchers", "Command Groups:")
    # The group rows (with their parenthetical aliases) must not appear under Stage Launchers.
    for entry in ("worktree (wt)", "objective (obj)", "registry (reg)", "state (st)"):
        assert entry not in launchers_slice, entry


def test_init_and_doctor_under_setup_health():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    setup_slice = _between(result.output, "Setup & Health:", "Other:")
    rows = [line.strip().split()[0] for line in setup_slice.splitlines() if line.strip()]
    assert "init" in rows
    assert "doctor" in rows


def test_launchers_section_contents():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    launchers_slice = _between(result.output, "Stage Launchers", "Command Groups:")
    rows = [line.strip().split()[0] for line in launchers_slice.splitlines() if line.strip()]
    for name in ("submit", "land", "learn", "plan", "implement"):
        assert name in rows, name
    assert "implement (impl)" in launchers_slice
    assert "doctor" not in rows
    for group_name in COMMAND_GROUPS:
        assert group_name not in rows, group_name


def test_workers_render_under_other():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    other_slice = _between(result.output, "Other:", None)
    assert "run-worker" in other_slice
    # `plan-save` is gone (folded into the `plan` group as `perk plan save`, Node 3.2).
    assert "plan-save" not in other_slice


def test_stage_launcher_long_help_mentions_pi_session():
    result = CliRunner().invoke(cli, ["submit", "--help"])
    assert result.exit_code == 0
    assert "Opens a primed pi session for the 'submit' stage" in result.output
    assert "Push the branch and open a draft PR" in result.output
    # The root listing row stays the bare registry summary (no launcher sentence).
    root = CliRunner().invoke(cli, ["--help"])
    submit_rows = [line for line in root.output.splitlines() if line.strip().startswith("submit")]
    assert submit_rows
    for line in submit_rows:
        assert "primed pi session" not in line


def test_pr_group_lists_all_verbs():
    result = CliRunner().invoke(cli, ["pr", "--help"])
    assert result.exit_code == 0
    for verb in (
        "submit",
        "address",
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


def _kinded_group() -> SectionedAliasGroup:
    """A synthetic SectionedAliasGroup with a launcher, a worker, and an unmarked command."""
    grp = SectionedAliasGroup("syn")

    @grp.command("open")
    def _open() -> None:
        """A launcher command."""

    @grp.command("run-it")
    def _run_it() -> None:
        """A worker command."""

    @grp.command("plain")
    def _plain() -> None:
        """An unmarked command."""

    mark_kind(grp.commands["open"], "launcher")
    mark_kind(grp.commands["run-it"], "worker")
    return grp


def test_sectioned_alias_group_renders_launchers_and_workers():
    # Node 2.1 (SSOT §11.7-Q5): marked commands render under "Launchers" / "Workers".
    result = CliRunner().invoke(_kinded_group(), ["--help"])
    assert result.exit_code == 0
    assert "Launchers:" in result.output
    assert "Workers:" in result.output
    launchers_slice = _between(result.output, "Launchers:", "Workers:")
    assert "open" in launchers_slice
    workers_slice = _between(result.output, "Workers:", "Commands:")
    assert "run-it" in workers_slice


def test_sectioned_alias_group_unmarked_under_commands():
    result = CliRunner().invoke(_kinded_group(), ["--help"])
    assert result.exit_code == 0
    commands_slice = _between(result.output, "Commands:", None)
    assert "plain" in commands_slice
    # The marked commands do not leak into the catch-all Commands section.
    assert "open" not in commands_slice
    assert "run-it" not in commands_slice


def test_sectioned_alias_group_omits_empty_sections():
    # An all-unmarked group renders only the catch-all Commands section (== AliasGroup behavior).
    grp = SectionedAliasGroup("syn")

    @grp.command("only")
    def _only() -> None:
        """The only command."""

    result = CliRunner().invoke(grp, ["--help"])
    assert result.exit_code == 0
    assert "Launchers:" not in result.output
    assert "Workers:" not in result.output
    assert "Commands:" in result.output


def test_objective_group_renders_launchers_and_workers():
    # Node 3.1 (SSOT §11.7-Q5): the live `objective` group sections its folded launchers/workers.
    result = CliRunner().invoke(cli, ["objective", "--help"])
    assert result.exit_code == 0
    assert "Launchers:" in result.output
    assert "Workers:" in result.output
    launchers_slice = _between(result.output, "Launchers:", "Workers:")
    for name in ("author", "save", "plan"):
        assert name in launchers_slice, name
    workers_slice = _between(result.output, "Workers:", None)
    for name in ("create", "show", "node", "next", "reconcile", "run"):
        assert name in workers_slice, name


def test_section_lists_drift_guard():
    ctx = click.Context(cli)
    alias_names = {a for name in cli.commands for a in get_aliases(cli.commands[name])}
    visible: set[str] = set()
    for name in cli.list_commands(ctx):
        cmd = cli.get_command(ctx, name)
        if cmd is None or cmd.hidden or name in alias_names:
            continue
        visible.add(name)

    curated = [set(STAGE_LAUNCHERS), set(COMMAND_GROUPS), set(SETUP_HEALTH)]

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
