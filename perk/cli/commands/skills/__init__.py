"""`perk skills` — manage this repo's skills (sugar over the `skills` CLI).

Every verb is a thin pass-through to the `skills` binary EXCEPT `remove`, which the upstream CLI
does not support and which perk implements by editing `.agents/manifest.yaml` directly.
"""

import click

from perk.cli.alias import AliasGroup, alias, register_with_aliases
from perk.cli.commands.skills.add_cmd import add_skill
from perk.cli.commands.skills.list_cmd import list_skills
from perk.cli.commands.skills.rm_cmd import remove_skill
from perk.cli.commands.skills.status_cmd import status_skills
from perk.cli.commands.skills.sync_cmd import sync_skills_cmd


@alias("sk")
@click.group("skills", cls=AliasGroup)
def skills_group() -> None:
    """Manage this repo's skills (sugar over the `skills` CLI)."""


register_with_aliases(skills_group, list_skills)
register_with_aliases(skills_group, status_skills)
register_with_aliases(skills_group, add_skill)
register_with_aliases(skills_group, remove_skill)
register_with_aliases(skills_group, sync_skills_cmd)
