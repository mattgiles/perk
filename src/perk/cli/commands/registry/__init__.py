"""`perk registry` — inspect and validate the shared stage registry.

A developer / `doctor` / CI surface, **not** an agent affordance (cli-vs-pi §3.2/§6.6):
the agent reads registry data via an extension tool, never by shelling `perk`. `--json` here
is for machines that *launch* perk (CI, the future supervisor), per python-cli-guidelines §7.
"""

import click

from perk.cli.alias import AliasGroup, alias, register_with_aliases
from perk.cli.commands.registry.check_cmd import check_registry
from perk.cli.commands.registry.show_cmd import show_registry


@alias("reg")
@click.group("registry", cls=AliasGroup)
def registry_group() -> None:
    """Inspect and validate the shared stage registry (`shared/registry.yaml`)."""


register_with_aliases(registry_group, check_registry)
register_with_aliases(registry_group, show_registry)
