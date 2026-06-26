"""`perk skills` — manage this repo's skills (sugar over the `skills` CLI).

Every verb is a thin pass-through to the `skills` binary EXCEPT `remove` (edits
`.agents/manifest.yaml` directly) and the repo-authored-skill verbs `scaffold`/`delete` (manage the
repo's own `.pi/skills/*/SKILL.md` skills + the perk-managed `perk-repo-skills.yaml` fragment).
"""

import click

from perk.cli.alias import AliasGroup, alias, register_with_aliases
from perk.cli.commands.skills.add_cmd import add_skill
from perk.cli.commands.skills.create_cmd import create_skill
from perk.cli.commands.skills.delete_cmd import delete_skill
from perk.cli.commands.skills.list_cmd import list_skills
from perk.cli.commands.skills.rm_cmd import remove_skill
from perk.cli.commands.skills.scaffold_cmd import scaffold_skill
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
register_with_aliases(skills_group, scaffold_skill)
register_with_aliases(skills_group, create_skill)
register_with_aliases(skills_group, delete_skill)
register_with_aliases(skills_group, sync_skills_cmd)
