"""``perk objective engagement <NUMBER> [--json]`` — read the objective + node-issue human
engagement.

The **reconcile path's fetch surface** + a human/CI affordance: an objective (and its roadmap
node-issues) may carry human comments / description edits made after planning landed. This read
worker surfaces that engagement as ONE rendered ``<untrusted_objective_engagement>`` DATA block (or
a "no engagement" note). Read-only — consistent with the model already shelling
``perk objective show`` from the reconcile guidance (a read worker, never a mutation affordance).

It composes the EXISTING read methods (no new ``ObjectiveStore`` Protocol method): the
project-level ``read_comments`` / ``read_description_edits`` plus the per-node
``read_node_engagement`` looped over every roadmap node. Linear-first: GitHub surfaces the
objective issue's own comments + edits and no per-node sections; the dormant issue-backed Linear
store returns the empty surfaces.

Supervisor surface: ``--json`` → stdout machine payload, human text → stderr,
stable exits (``0`` ok · ``1`` invalid/op-failure · ``2`` not-a-repo).
"""

import dataclasses
import json

import click

from perk.backends import resolve
from perk.backends.engagement import render_objective_engagement
from perk.backends.objective_store import ObjectiveStoreError
from perk.cli.commands.objective.shared import parse_objective_id
from perk.cli.context import require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.substrate.output import machine_output, user_output


@click.command("engagement")
@click.argument("number")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def engagement_objective(ctx: click.Context, *, number: str, as_json: bool) -> None:
    """Read an objective + its node-issues' human engagement (comments + description edits).

    \b
    Examples:
      perk objective engagement 7          # rendered untrusted-DATA block (stderr)
      perk objective engagement 7 --json   # machine payload (stdout)
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
        project_comments = store.read_comments(objective_id=number)
        project_description_edits = store.read_description_edits(objective_id=number)
        node_engagements = tuple(
            (n.id, store.read_node_engagement(objective_id=number, node_id=n.id))
            for n in state.nodes
        )
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

    block = render_objective_engagement(
        project_comments=project_comments,
        project_description_edits=project_description_edits,
        node_engagements=node_engagements,
    )
    if as_json:
        machine_output(
            json.dumps(
                {
                    "success": True,
                    "error_type": None,
                    "objective": number,
                    "project_comments": [dataclasses.asdict(c) for c in project_comments],
                    "project_description_edits": [
                        dataclasses.asdict(e) for e in project_description_edits
                    ],
                    "nodes": [
                        {
                            "node": node_id,
                            "comments": [dataclasses.asdict(c) for c in ne.comments],
                            "description_edits": [
                                dataclasses.asdict(e) for e in ne.description_edits
                            ],
                        }
                        for node_id, ne in node_engagements
                    ],
                }
            )
        )
    elif block is not None:
        user_output(block)
    else:
        user_output(f"no human engagement on objective {number}")
