"""``perk objective node-engagement <NUMBER> --node ID [--json]`` — read a node-issue's
pre-planning human engagement.

The **warm path's fetch surface** + a human/CI affordance: a roadmap node-issue may carry human
comments / description edits made **before** perk ever plans it. This read worker surfaces that
engagement as the rendered ``<untrusted_node_engagement>`` DATA block (or a "no engagement" note).
Read-only — consistent with the model already shelling ``perk objective show`` from the seed (a
read worker, never a mutation affordance).

Linear-first: GitHub single-issue objectives + the dormant issue-backed Linear store return the
empty bundle (the block is ``None``, the human/JSON surface says "no pre-planning engagement").

Supervisor surface: ``--json`` → stdout machine payload, human text → stderr,
stable exits (``0`` ok · ``1`` invalid/op-failure · ``2`` not-a-repo).
"""

import dataclasses
import json

import click

from perk.backends import resolve
from perk.backends.engagement import render_node_engagement
from perk.backends.objective_store import ObjectiveStoreError
from perk.cli import completions
from perk.cli.commands.objective.shared import parse_objective_id
from perk.cli.context import require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.substrate.output import machine_output, user_output


@click.command("node-engagement")
@click.argument("number", shell_complete=completions.complete_objective_id)
@click.option("--node", "node_id", required=True, help="The roadmap node id (e.g. 2.3).")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def node_engagement_objective(
    ctx: click.Context, *, number: str, node_id: str, as_json: bool
) -> None:
    """Read a roadmap node-issue's pre-planning human engagement (comments + description edits).

    \b
    Examples:
      perk objective node-engagement 7 --node 2.1          # rendered untrusted-DATA block (stderr)
      perk objective node-engagement 7 --node 2.1 --json   # machine payload (stdout)
    """
    try:
        repo_root = require_repo(ctx)
        number = parse_objective_id(number)
        store = resolve.resolve_objective_store(repo_root)
        state = store.get_objective(objective_id=number)
        if state is None:
            raise UserFacingCliError(
                f"Objective #{number} not found", error_type="objective_not_found"
            )
        engagement = store.read_node_engagement(objective_id=number, node_id=node_id)
    except ObjectiveStoreError as exc:
        fail(ctx, as_json=as_json, error_type="github_error", message=str(exc))
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    block = render_node_engagement(engagement)
    if as_json:
        machine_output(
            json.dumps(
                {
                    "success": True,
                    "error_type": None,
                    "objective": number,
                    "node": node_id,
                    "comments": [dataclasses.asdict(c) for c in engagement.comments],
                    "description_edits": [
                        dataclasses.asdict(e) for e in engagement.description_edits
                    ],
                }
            )
        )
    elif block is not None:
        user_output(block)
    else:
        user_output(f"no pre-planning engagement on node {node_id}")
