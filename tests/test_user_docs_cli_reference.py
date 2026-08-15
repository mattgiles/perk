"""Bi-directional guard for the split CLI reference (the `reference/cli.md` hub + its six
family children under `docs/user-docs/reference/cli/`).

The reference quadrant's rule is that the CLI pages are written against real ``--help`` output
and guarded by a pytest check, so a documented-but-missing command (or a newly-added,
undocumented one) fails CI. This guard enforces both directions over the whole page family:

- **documented → exists**: every command a page documents resolves in the live CLI.
- **exists → documented**: every non-hidden CLI command (minus a small, justified allowlist)
  is documented on exactly one page, and on the page its family map assigns.

It also censuses the hub's marked command map (one row per visible root command, minus the
allowlist). Wording is NOT string-pinned — the guard checks existence/completeness/placement
only; summary accuracy is human-reviewed (avoids brittleness to ``--help`` rewordings).
"""

import re
from pathlib import Path

import click

from perk.cli.alias import get_aliases
from perk.cli.cli import cli

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = REPO_ROOT / "docs/user-docs/reference"

# The seven pages of the CLI reference family (paths relative to `docs/user-docs/reference/`),
# each mapped to the root commands whose entries it owns. The hub owns the stage-launcher spine;
# every other root command's detail lives on its family child. A new root command must be
# assigned to exactly one page here (the partition test enforces it).
FAMILY_MAP: dict[str, frozenset[str]] = {
    "cli.md": frozenset({"implement", "submit", "address", "land", "ready"}),
    "cli/setup-and-health.md": frozenset({"init", "doctor"}),
    "cli/plan.md": frozenset({"plan"}),
    "cli/objective.md": frozenset({"objective"}),
    "cli/pr.md": frozenset({"pr"}),
    "cli/learn-and-gist.md": frozenset({"learn", "gist"}),
    "cli/remote-and-utility.md": frozenset(
        {"worktree", "state", "registry", "skills", "workflow", "release-notes"}
    ),
}

# The only non-hidden, intentionally-undocumented CLI path. ``run-worker`` is the internal CI
# worker entrypoint (positions the checkout + drives a stage headlessly), not an operator-facing
# command, so the reference family deliberately omits it. The hidden ``learn launch`` verb needs
# no allowlist entry — it is already excluded as a hidden command.
ALLOWLIST: set[tuple[str, ...]] = {("run-worker",)}

# The hub's marked command-map region (one row per visible root command minus the allowlist).
MAP_BEGIN = "<!-- BEGIN perk cli command map -->"
MAP_END = "<!-- END perk cli command map -->"

# A documented entry is a heading — or a bold-bullet lead-in (the `perk skills` verb shape) —
# whose first `` `perk …` `` code span's leading run of command tokens is the path.
_PERK_SPAN = re.compile(r"`perk ([^`]+)`")
_COMMAND_TOKEN = re.compile(r"^[a-z][a-z0-9-]*$")
_HEADING = re.compile(r"^#{1,6}\s")
_BOLD_BULLET = re.compile(r"^- \*\*`perk ")


def _page_text(page: str) -> str:
    return (REFERENCE_DIR / page).read_text(encoding="utf-8")


def _path_from_line(line: str) -> tuple[str, ...] | None:
    """The command path of one entry line: the first `` `perk …` `` span's leading run of
    command tokens (``^[a-z][a-z0-9-]*$``), stopping at the first non-command token (an option
    ``-…``, a ``<…>``/``[…]`` metavar, or an alias parenthetical)."""
    match = _PERK_SPAN.search(line)
    if match is None:
        return None
    path: list[str] = []
    for token in match.group(1).split():
        if _COMMAND_TOKEN.match(token):
            path.append(token)
        else:
            break
    return tuple(path) if path else None


def _documented_paths(md: str) -> set[tuple[str, ...]]:
    """Extract the documented command paths from one page's headings and bold-bullet lead-ins."""
    paths: set[tuple[str, ...]] = set()
    for line in md.splitlines():
        if not (_HEADING.match(line) or _BOLD_BULLET.match(line)):
            continue
        path = _path_from_line(line)
        if path is not None:
            paths.add(path)
    return paths


def _documented_by_page() -> dict[str, set[tuple[str, ...]]]:
    return {page: _documented_paths(_page_text(page)) for page in FAMILY_MAP}


def _documented_union() -> set[tuple[str, ...]]:
    return set().union(*_documented_by_page().values())


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


def _visible_root_commands() -> set[str]:
    return {path[0] for path in _cli_command_paths() if len(path) == 1}


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


def _map_rows() -> list[str]:
    """The data rows of the hub's marked command-map table (everything after the separator)."""
    hub = _page_text("cli.md")
    assert MAP_BEGIN in hub and MAP_END in hub, "cli.md lost the marked command-map region"
    region = hub.split(MAP_BEGIN, 1)[1].split(MAP_END, 1)[0]
    table = [line for line in region.splitlines() if line.startswith("|")]
    separators = [i for i, line in enumerate(table) if re.fullmatch(r"[|\s:-]+", line)]
    assert separators, "command-map table has no header separator row"
    return table[separators[0] + 1 :]


def test_documented_cli_commands_all_resolve():
    """documented → exists: every documented path resolves in the live CLI."""
    unresolved = sorted(path for path in _documented_union() if _resolve(path) is None)
    assert not unresolved, "documented commands that no longer resolve: " + ", ".join(
        "perk " + " ".join(path) for path in unresolved
    )


def test_every_cli_command_is_documented():
    """exists → documented: every non-hidden CLI command (minus allowlist) is documented."""
    missing = sorted(_cli_command_paths() - ALLOWLIST - _documented_union())
    assert not missing, "CLI commands missing from the reference family: " + ", ".join(
        "perk " + " ".join(path) for path in missing
    )


def test_entries_sit_on_their_family_page():
    """placement: every path a page documents has its root token in that page's family set."""
    offenders = [
        f"{page}: perk {' '.join(path)}"
        for page, paths in _documented_by_page().items()
        for path in sorted(paths)
        if path[0] not in FAMILY_MAP[page]
    ]
    assert not offenders, "entries documented outside their family page: " + ", ".join(offenders)


def test_family_map_partitions_the_visible_root_commands():
    """partition: family sets are pairwise disjoint; their union plus the allowlist roots equals
    the visible root command set (a new root command must be assigned a page)."""
    pages = list(FAMILY_MAP)
    overlaps = [
        f"{a} & {b}: {sorted(FAMILY_MAP[a] & FAMILY_MAP[b])}"
        for i, a in enumerate(pages)
        for b in pages[i + 1 :]
        if FAMILY_MAP[a] & FAMILY_MAP[b]
    ]
    assert not overlaps, "family sets overlap: " + "; ".join(overlaps)
    assigned = set().union(*FAMILY_MAP.values()) | {path[0] for path in ALLOWLIST}
    live = _visible_root_commands()
    assert assigned == live, (
        f"family map + allowlist != visible root commands — unassigned: {sorted(live - assigned)}, "
        f"stale assignments: {sorted(assigned - live)}"
    )


def test_no_entry_is_documented_on_two_pages():
    """uniqueness: no command path is documented as an entry on two pages."""
    owners: dict[tuple[str, ...], list[str]] = {}
    for page, paths in _documented_by_page().items():
        for path in paths:
            owners.setdefault(path, []).append(page)
    duplicated = {path: pages for path, pages in owners.items() if len(pages) > 1}
    assert not duplicated, "entries documented on multiple pages: " + ", ".join(
        f"perk {' '.join(path)} ({', '.join(sorted(pages))})"
        for path, pages in sorted(duplicated.items())
    )


def test_allowlist_entries_are_real_and_excluded():
    """No stale allowlist entry: each path resolves and is genuinely absent from the docs."""
    documented = _documented_union()
    for path in ALLOWLIST:
        assert _resolve(path) is not None, f"stale allowlist entry (does not resolve): {path}"
        assert path not in documented, (
            f"allowlisted path is documented (drop from allowlist): {path}"
        )


def test_documentation_is_non_vacuous():
    """Vacuous-scan self-check: a rename / regex break can't silently empty the scan."""
    thin = {page: len(paths) for page, paths in _documented_by_page().items() if len(paths) < 4}
    assert not thin, f"pages with implausibly few documented entries: {thin}"
    assert len(_documented_union()) >= 80, (
        f"only {len(_documented_union())} documented entries across the family — "
        "the extraction looks broken"
    )


def test_hub_command_map_census():
    """The hub's marked command map is a complete census: exactly one `perk <name>` code span
    per data row, no duplicate names, set-equal to the visible root set minus the allowlist."""
    rows = _map_rows()
    names: list[str] = []
    offenders: list[str] = []
    for row in rows:
        spans = _PERK_SPAN.findall(row)
        if len(spans) != 1:
            offenders.append(f"{len(spans)} `perk …` spans in row: {row.strip()}")
            continue
        name = spans[0].strip()
        if not _COMMAND_TOKEN.match(name):
            offenders.append(f"not a bare root command name: `perk {name}`")
            continue
        names.append(name)
    assert not offenders, "malformed command-map rows: " + "; ".join(offenders)
    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert not duplicates, f"duplicate command-map rows: {duplicates}"
    expected = _visible_root_commands() - {path[0] for path in ALLOWLIST}
    assert set(names) == expected, (
        f"command-map census drift — missing: {sorted(expected - set(names))}, "
        f"unexpected: {sorted(set(names) - expected)}"
    )
    # Known-anchor spot checks: the owning-page links stay live.
    by_name = {spans[0].strip(): row for row in rows if (spans := _PERK_SPAN.findall(row))}
    assert "#perk-implement-plan-alias-impl" in by_name["implement"], (
        "implement row must link the hub spine entry"
    )
    assert "./cli/objective.md" in by_name["objective"], "objective row must link cli/objective.md"
    assert "./cli/remote-and-utility.md" in by_name["release-notes"], (
        "release-notes row must link cli/remote-and-utility.md"
    )
