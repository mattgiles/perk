"""Structural surface fingerprint of the canonical CLI taxonomy.

This module fingerprints the live ``perk`` command surface structurally — the verb set of the root
+ every subgroup, plus each visible root command's section bucket — and asserts it equals a literal
expected dict. The dict is the canonical post-taxonomy fingerprint; the equality assertion is the
drift guard against accidental surface regressions (any change to the verb/alias/section surface
shows up as a diff against this dict, which is the review surface). Structural (not raw ``--help``
text), so it is terminal-width-stable.
"""

from typing import cast

import click

from perk.cli.alias import (
    COMMAND_GROUPS,
    SETUP_HEALTH,
    STAGE_LAUNCHERS,
    get_aliases,
    get_flat_aliases,
)
from perk.cli.cli import cli


def _root_section(name: str) -> str:
    """Classify a visible root command into its ``SectionedGroup`` bucket."""
    if name in get_flat_aliases(cli):
        return "launchers"
    if name in COMMAND_GROUPS:
        return "groups"
    if name in SETUP_HEALTH:
        return "setup"
    if name in STAGE_LAUNCHERS:
        return "launchers"
    return "other"


def _group_verbs(group: click.Group, ctx: click.Context) -> list[tuple[str, tuple[str, ...]]]:
    """Sorted ``(primary_name, sorted_aliases)`` for a group's visible non-alias commands."""
    alias_names = {a for n in group.commands for a in get_aliases(group.commands[n])}
    seen: set[str] = set()
    rows: list[tuple[str, tuple[str, ...]]] = []
    for name in group.list_commands(ctx):
        cmd = group.get_command(ctx, name)
        if cmd is None or cmd.hidden or name in alias_names:
            continue
        primary = cmd.name or name
        if primary in seen:
            continue
        seen.add(primary)
        rows.append((primary, tuple(sorted(get_aliases(cmd)))))
    return sorted(rows)


def _surface_fingerprint(group: click.Group) -> dict[str, object]:
    """Deterministic structural fingerprint of the live CLI surface.

    Returns ``{"root": [...], "sections": {name: bucket}, "groups": {gname: [...]}}`` — verb sets
    for the root and each subgroup, plus the root section classification of every visible command.
    """
    ctx = click.Context(group)
    root = _group_verbs(group, ctx)
    sections = {name: _root_section(name) for name, _aliases in root}
    groups: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    for name, _aliases in root:
        cmd = group.get_command(ctx, name)
        if isinstance(cmd, click.Group):
            groups[name] = _group_verbs(cmd, click.Context(cmd))
    return {"root": root, "sections": sections, "groups": groups}


# The canonical CLI surface (the taxonomy's verbs, aliases, and section classification). Any change
# to the surface (merging a launcher+worker, registering a flat alias, sectioning a group) edits
# THIS dict — the diff is the review surface that catches accidental regressions.
EXPECTED_SURFACE: dict[str, object] = {
    "root": [
        ("address", ()),
        ("doctor", ()),
        ("implement", ("impl",)),
        ("init", ()),
        ("land", ()),
        ("learn", ()),
        ("objective", ("obj",)),
        ("plan", ()),
        ("pr", ()),
        ("ready", ()),
        ("registry", ("reg",)),
        ("run-worker", ()),
        ("skills", ("sk",)),
        ("state", ("st",)),
        ("submit", ()),
        ("workflow", ("wf",)),
        ("worktree", ("wt",)),
    ],
    "sections": {
        "address": "launchers",
        "doctor": "setup",
        "implement": "launchers",
        "init": "setup",
        "land": "launchers",
        "learn": "launchers",
        "objective": "groups",
        "plan": "launchers",
        "pr": "groups",
        "ready": "launchers",
        "registry": "groups",
        "run-worker": "other",
        "skills": "groups",
        "state": "groups",
        "submit": "launchers",
        "workflow": "groups",
        "worktree": "groups",
    },
    "groups": {
        "doctor": [("workflow", ())],
        "learn": [
            ("capture", ()),
            ("code", ()),
            ("docs", ()),
            ("docs-check", ()),
            ("docs-sync", ()),
            ("evidence", ()),
            ("skip", ()),
        ],
        "plan": [("from", ()), ("replan", ()), ("resume", ()), ("save", ())],
        "objective": [
            ("author", ()),
            ("create", ("new",)),
            ("doctor", ("doc",)),
            ("engagement", ()),
            ("next", ("n",)),
            ("node", ()),
            ("node-add", ()),
            ("node-engagement", ()),
            ("plan", ()),
            ("reconcile", ("rec",)),
            ("replan", ()),
            ("run", ("r",)),
            ("save", ()),
            ("show", ("s",)),
        ],
        "pr": [
            ("address", ()),
            ("check", ()),
            ("feedback", ()),
            ("land", ()),
            ("ready", ()),
            ("resolve-threads", ()),
            ("review-context", ()),
            ("review-post", ()),
            ("submit", ()),
            ("url", ()),
        ],
        "registry": [("check", ("ch",)), ("show", ("s",))],
        "skills": [
            ("add", ()),
            ("create", ()),
            ("delete", ()),
            ("list", ("ls",)),
            ("refine", ()),
            ("remove", ("rm",)),
            ("scaffold", ()),
            ("status", ()),
            ("sync", ()),
        ],
        "state": [("new-run", ("nr",)), ("prune", ("gc",)), ("show", ("s",))],
        "workflow": [("run", ())],
        "worktree": [
            ("create", ("new",)),
            ("list", ("ls",)),
            ("remove", ("rm",)),
            ("wipe", ()),
        ],
    },
}


def test_live_surface_matches_canonical_fingerprint():
    """The drift guard: the live surface equals the literal canonical fingerprint."""
    assert _surface_fingerprint(cli) == EXPECTED_SURFACE


def test_root_visible_command_set_unchanged():
    fp = _surface_fingerprint(cli)
    live = cast(list[tuple[str, tuple[str, ...]]], fp["root"])
    expected = cast(list[tuple[str, tuple[str, ...]]], EXPECTED_SURFACE["root"])
    assert {name for name, _aliases in live} == {name for name, _aliases in expected}


def test_each_group_verb_set_unchanged():
    fp = _surface_fingerprint(cli)
    assert fp["groups"] == EXPECTED_SURFACE["groups"]
