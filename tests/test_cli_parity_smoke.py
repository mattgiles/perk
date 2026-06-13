"""Structural parity-smoke harness (Objective #495 Node 2.1, D5).

Node 2.1 ships *dormant* CLI substrate (the merge factory, the flat-alias mechanism, sectioned
group help) with a **byte-identical live command/help surface**. This module fingerprints that
surface structurally — the verb set of the root + every subgroup, plus each visible root command's
section bucket — and asserts it equals a literal expected dict. A 3.x fold *edits* this dict; the
diff is the review surface. Structural (not raw ``--help`` text), so it is terminal-width-stable.
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


# The literal pre-node surface (today's verbs, aliases, and section classification). A 3.x fold
# (merging a real submit/land, registering a flat alias, sectioning a group) edits THIS dict — the
# diff is the review surface. Empty/dormant in 2.1 ⇒ this is unchanged from the pre-node surface.
EXPECTED_SURFACE: dict[str, object] = {
    "root": [
        ("address", ()),
        ("doctor", ()),
        ("implement", ("impl",)),
        ("init", ()),
        ("land", ()),
        ("learn", ()),
        ("objective", ("obj",)),
        ("objective-author", ("oauthor",)),
        ("objective-plan", ("oplan",)),
        ("objective-save", ()),
        ("plan", ()),
        ("plan-save", ("psave",)),
        ("pr", ()),
        ("registry", ("reg",)),
        ("replan", ("rp",)),
        ("resume", ("res",)),
        ("run-worker", ()),
        ("save", ()),
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
        "objective-author": "launchers",
        "objective-plan": "launchers",
        "objective-save": "launchers",
        "plan": "launchers",
        "plan-save": "other",
        "pr": "groups",
        "registry": "groups",
        "replan": "launchers",
        "resume": "launchers",
        "run-worker": "other",
        "save": "launchers",
        "state": "groups",
        "submit": "launchers",
        "workflow": "groups",
        "worktree": "groups",
    },
    "groups": {
        "doctor": [("workflow", ())],
        "learn": [("capture", ()), ("docs", ())],
        "objective": [
            ("create", ("new",)),
            ("next", ("n",)),
            ("node", ()),
            ("reconcile", ("rec",)),
            ("run", ("r",)),
            ("show", ("s",)),
        ],
        "pr": [
            ("check", ()),
            ("feedback", ()),
            ("land", ()),
            ("ready", ()),
            ("resolve-threads", ()),
            ("review-context", ()),
            ("review-post", ()),
            ("submit", ()),
        ],
        "registry": [("check", ("ch",)), ("show", ("s",))],
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


def test_live_surface_is_byte_identical_to_pre_node():
    """The dormancy proof: the live surface equals the literal pre-node fingerprint."""
    assert _surface_fingerprint(cli) == EXPECTED_SURFACE


def test_root_visible_command_set_unchanged():
    fp = _surface_fingerprint(cli)
    live = cast(list[tuple[str, tuple[str, ...]]], fp["root"])
    expected = cast(list[tuple[str, tuple[str, ...]]], EXPECTED_SURFACE["root"])
    assert {name for name, _aliases in live} == {name for name, _aliases in expected}


def test_each_group_verb_set_unchanged():
    fp = _surface_fingerprint(cli)
    assert fp["groups"] == EXPECTED_SURFACE["groups"]
