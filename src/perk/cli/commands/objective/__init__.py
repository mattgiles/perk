"""``perk objective`` — the objective command group (launchers + deterministic workers).

Folds the three objective **launchers** (`author`/`save`/`plan` — each opens a primed pi session)
beside the deterministic **workers** (`create`/`show`/`node`/`next`/`reconcile`/`run`). The workers
are a developer / CI surface (like ``perk state`` / ``perk registry``), **not** an agent
affordance: the model drives objectives through the extension's bounded transition tools,
never by shelling them. Each subcommand is a supervisor surface: ``--json`` →
stdout, human text → stderr, stable exit codes (``0`` ok · ``1`` invalid/op-failure · ``2``
not-a-repo), ``UserFacingCliError`` with a stable ``error_type``.

Help renders **Launchers** + **Workers** sections via ``SectionedAliasGroup`` + ``mark_kind``.
Bare ``perk objective`` stays group help — no hybrid bare-launch.
"""

import click

from perk.cli.alias import SectionedAliasGroup, alias, mark_kind, register_with_aliases
from perk.cli.commands.objective.author_cmd import author_objective
from perk.cli.commands.objective.create_cmd import create_objective
from perk.cli.commands.objective.doctor_cmd import doctor_objective
from perk.cli.commands.objective.engagement_cmd import engagement_objective
from perk.cli.commands.objective.next_cmd import next_objective
from perk.cli.commands.objective.node_add_cmd import node_add_objective
from perk.cli.commands.objective.node_cmd import node_objective
from perk.cli.commands.objective.node_engagement_cmd import node_engagement_objective
from perk.cli.commands.objective.plan_cmd import plan_objective
from perk.cli.commands.objective.reconcile_cmd import reconcile_objective
from perk.cli.commands.objective.replan_cmd import replan_objective
from perk.cli.commands.objective.run_cmd import run_objective
from perk.cli.commands.objective.save_cmd import save_objective
from perk.cli.commands.objective.show_cmd import show_objective
from perk.cli.commands.objective.stack import stack_group


@alias("obj")
@click.group("objective", cls=SectionedAliasGroup)
def objective_group() -> None:
    """Objective launchers (primed pi sessions) + deterministic storage/mechanics workers."""


# Launchers (each opens a primed pi session).
register_with_aliases(objective_group, mark_kind(author_objective, "launcher"))
register_with_aliases(objective_group, mark_kind(save_objective, "launcher"))
register_with_aliases(objective_group, mark_kind(plan_objective, "launcher"))
register_with_aliases(objective_group, mark_kind(replan_objective, "launcher"))

# Workers (deterministic dev/CI surface).
register_with_aliases(objective_group, mark_kind(create_objective, "worker"))
register_with_aliases(objective_group, mark_kind(show_objective, "worker"))
register_with_aliases(objective_group, mark_kind(node_objective, "worker"))
register_with_aliases(objective_group, mark_kind(node_add_objective, "worker"))
register_with_aliases(objective_group, mark_kind(node_engagement_objective, "worker"))
register_with_aliases(objective_group, mark_kind(engagement_objective, "worker"))
register_with_aliases(objective_group, mark_kind(reconcile_objective, "worker"))
register_with_aliases(objective_group, mark_kind(next_objective, "worker"))
register_with_aliases(objective_group, mark_kind(run_objective, "worker"))
register_with_aliases(objective_group, mark_kind(doctor_objective, "worker"))
register_with_aliases(objective_group, mark_kind(stack_group, "worker"))
