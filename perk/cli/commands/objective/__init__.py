"""``perk objective`` — the deterministic objective mechanics (cold-door workers, P2.T9).

A developer / CI / T10 surface (like ``perk state`` / ``perk registry``), **not** an agent
affordance: the model drives objectives through the extension's bounded transition tools (T10),
never by shelling ``perk objective``. Each subcommand is a supervisor surface (cli-vs-pi §3.2):
``--json`` → stdout, human text → stderr, stable exit codes (``0`` ok · ``1`` invalid/op-failure ·
``2`` not-a-repo), ``UserFacingCliError`` with a stable ``error_type``.

Subcommands: ``create`` (two-step issue create from authored markdown), ``show`` (header + roadmap
+ summary + next-node), ``node`` (explicit-status node update), ``next`` (dependency-graph
selection — what T10's ``/objective-plan`` consumes).
"""

import click

from perk.cli.alias import AliasGroup, alias, register_with_aliases
from perk.cli.commands.objective.create_cmd import create_objective
from perk.cli.commands.objective.next_cmd import next_objective
from perk.cli.commands.objective.node_cmd import node_objective
from perk.cli.commands.objective.reconcile_cmd import reconcile_objective
from perk.cli.commands.objective.run_cmd import run_objective
from perk.cli.commands.objective.show_cmd import show_objective


@alias("obj")
@click.group("objective", cls=AliasGroup)
def objective_group() -> None:
    """Deterministic objective storage + mechanics (dev/CI/T10 surface, not an agent affordance)."""


register_with_aliases(objective_group, create_objective)
register_with_aliases(objective_group, show_objective)
register_with_aliases(objective_group, node_objective)
register_with_aliases(objective_group, reconcile_objective)
register_with_aliases(objective_group, next_objective)
register_with_aliases(objective_group, run_objective)
