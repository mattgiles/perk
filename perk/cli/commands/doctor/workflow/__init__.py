"""`perk doctor workflow` — the workflow-focused diagnostic subgroup (contracts.md §8.19).

`init`'s diagnostic twin, narrowed to the remote-runner subsystem. `check` composes the **static**
prereq layer (`doctor.workflow_checks` — GitHub readiness ⊕ runner prereqs ⊕ the managed
`runner-workflow` present-check); `smoke-test [--wait]` adds the **live** proof a static check
cannot give — it dispatches a throwaway CI run with a `smoke=true` short-circuit (validate secrets +
confirm the runner started, then exit success; no plan checkout, no worker drive, no model spend),
optionally polls it to completion, and self-cancels its own run on a poll timeout. The smoke writes
**no** `DispatchRecord` and creates **no** GitHub artifacts, so it stays a pure doctor diagnostic
(`perk workflow run list` is unaffected) — there is no `cleanup` command (perk's smoke leaves
nothing durable).
"""

import click

from perk.cli.commands.doctor.workflow.check_cmd import check_workflow
from perk.cli.commands.doctor.workflow.smoke_test_cmd import smoke_test_workflow
from perk.substrate.output import user_output


@click.group("workflow", invoke_without_command=True)
@click.pass_context
def workflow_group(ctx: click.Context) -> None:
    """Diagnose the remote-runner subsystem (static prereqs + an optional live CI smoke)."""
    if ctx.invoked_subcommand is None:
        user_output(ctx.get_help())


workflow_group.add_command(check_workflow)
workflow_group.add_command(smoke_test_workflow)
