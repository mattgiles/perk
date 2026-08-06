"""``perk gist`` — the gist command group (launchers + deterministic workers).

A **gist** is a rough, problem-space-focused statement of intent tracked in the issue backend
(contracts.md §8.41) — upstream of both plans and objectives, consumed by the unchanged in-place
adoption doors (``perk plan from`` / ``perk objective author --from``). The group folds the two
**launchers** (``author``/``save`` — each opens a primed pi session) beside the deterministic
**workers** (``create``/``list``). The workers are a developer / CI surface, not an agent
affordance: the model persists gists through the ``gist_save`` tool, never by shelling them.

Each subcommand is a supervisor surface: ``--json`` → stdout, human text → stderr, stable exit
codes (``0`` ok · ``1`` invalid/op-failure · ``2`` not-a-repo), ``UserFacingCliError`` with a
stable ``error_type``.

Help renders **Launchers** + **Workers** sections via ``SectionedAliasGroup`` + ``mark_kind``.
Bare ``perk gist`` stays group help — no hybrid bare-launch.
"""

import click

from perk.cli.alias import SectionedAliasGroup, mark_kind, register_with_aliases
from perk.cli.commands.gist.author_cmd import author_gist
from perk.cli.commands.gist.create_cmd import create_gist
from perk.cli.commands.gist.list_cmd import list_gists
from perk.cli.commands.gist.save_cmd import save_gist


@click.group("gist", cls=SectionedAliasGroup)
def gist_group() -> None:
    """Gist launchers (primed pi sessions) + deterministic tracking workers."""


# Launchers (each opens a primed pi session).
register_with_aliases(gist_group, mark_kind(author_gist, "launcher"))
register_with_aliases(gist_group, mark_kind(save_gist, "launcher"))

# Workers (deterministic dev/CI surface).
register_with_aliases(gist_group, mark_kind(create_gist, "worker"))
register_with_aliases(gist_group, mark_kind(list_gists, "worker"))
