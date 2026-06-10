"""``perk workflow run`` — the supervisor read surface over dispatched runs (Node 3.1).

A dev/CI/supervisor surface (like ``perk objective`` / ``perk state``), **not** an agent
affordance: the model never shells ``perk workflow``. ``workflow run list`` enumerates the durable
dispatch records (the verified ``run_id → plan`` linkage from Node 2.1) and correlates each
``run_id ↔ plan ↔ PR``, overlaying live GitHub run state. Read-only: it mutates nothing.

``--json`` → a stable machine report on stdout; the human table → stderr. The live overlay is
**best-effort, fail-soft** — a GitHub read failure degrades that field to record-only state with a
one-line stderr note; it never raises and never changes the exit code.

``cancel``/``retry`` are the shipped control siblings of ``list`` (Node 3.2, contracts.md §8.18):
deterministic, mutating supervisor commands that resolve a perk ``run_id`` to its dispatch record
and act on the runner-native handle (cancel an in-flight run; re-run a completed/failed run, with
``--failed`` to re-run only the failed jobs). They require GitHub auth and surface gh's own error
verbatim; they mutate no ``.pi/workflow/`` state.
"""

import click

from perk.cli.alias import AliasGroup, alias, register_with_aliases
from perk.cli.commands.workflow.run import run_group


@alias("wf")
@click.group("workflow", cls=AliasGroup)
def workflow_group() -> None:
    """Supervisor surface over dispatched runs (dev/CI/supervisor surface, not an agent
    affordance)."""


register_with_aliases(workflow_group, run_group)
