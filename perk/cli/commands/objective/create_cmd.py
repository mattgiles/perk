"""`perk objective create` — mint a run_id and create the perk:objective issue."""

import json
import os
from pathlib import Path

import click

from perk import objective, plan
from perk.backends import issues
from perk.backends.issue_backend import IssueBackendError
from perk.cli.alias import alias
from perk.cli.commands.objective.shared import fail
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.state import run_id
from perk.substrate.output import machine_output, user_output


@alias("new")
@click.command("create")
@click.option(
    "--body",
    "body_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to the authored objective markdown (may embed a roadmap).",
)
@click.option("--title", help="Objective title (else derived from body).")
@click.option(
    "--roadmap",
    "roadmap_json",
    help="Structured roadmap as a JSON array of nodes (preferred over embedding YAML in --body).",
)
@click.option("--run-id", "run_id_arg", help="Correlation run id (defaults to $PERK_RUN_ID).")
@click.option("--dry-run", is_flag=True, help="Compose without creating an issue.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def create_objective(
    ctx: click.Context,
    *,
    body_path: Path,
    title: str | None,
    roadmap_json: str | None,
    run_id_arg: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Mint a run_id and create the perk:objective issue from authored markdown."""
    try:
        repo_root = require_repo(ctx)
        if not dry_run:
            require_github(ctx)
        body_text = body_path.read_text(encoding="utf-8").strip()
        if not body_text:
            raise UserFacingCliError("Objective body is empty", error_type="empty_body")
        # Resolve the roadmap: a structured --roadmap JSON wins (the agent path, never hand-written
        # YAML); otherwise validate any roadmap embedded in the body (the legacy cold-CLI path).
        roadmap_nodes: list[objective.ObjectiveNode] | None = None
        body_nodes: list[objective.ObjectiveNode] = []
        if roadmap_json is not None:
            try:
                raw = json.loads(roadmap_json)
            except json.JSONDecodeError as exc:
                raise UserFacingCliError(
                    f"Invalid --roadmap JSON: {exc}", error_type="invalid_roadmap"
                ) from exc
            roadmap_nodes, errors = objective.parse_structured_roadmap(raw)
        else:
            body_nodes, errors = objective.parse_roadmap_nodes(body_text)
        if errors:
            raise UserFacingCliError(
                "Invalid objective roadmap: " + "; ".join(errors), error_type="invalid_roadmap"
            )
        # Reject a roadmap-free objective before creating (also makes --dry-run reject early). The
        # parse/read layer stays lenient (existing node-less issues remain readable); creation does
        # not. `empty_roadmap` falls through EXIT_FOR_TYPE to exit 1.
        effective_nodes = roadmap_nodes if roadmap_nodes is not None else body_nodes
        if not effective_nodes:
            raise UserFacingCliError(
                "An objective needs at least one roadmap node — author a roadmap (the "
                "objective_save tool's `roadmap`, or a `--roadmap` JSON array) before creating.",
                error_type="empty_roadmap",
            )
        resolved_title = title or plan.derive_title(body_text, fallback="perk objective")
        resolved_run_id = run_id_arg or os.environ.get("PERK_RUN_ID") or run_id.mint()
        issue = issues.resolve_issue_backend(repo_root).create_objective_issue(
            title=resolved_title,
            body=body_text,
            run_id=resolved_run_id,
            roadmap_nodes=roadmap_nodes,
            dry_run=dry_run,
        )
    except IssueBackendError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="github_error",
            message=f"objective create failed\n{exc}",
        )
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    payload = {
        "success": True,
        "error_type": None,
        # Opaque string id at every machine boundary (contracts §8.21; Node 4.1).
        "objective": {"id": issue.id, "url": issue.url, "existed": issue.existed},
        "dry_run": dry_run,
    }
    if as_json:
        machine_output(json.dumps(payload))
    else:
        verb = "Found existing" if issue.existed else "Created"
        user_output(click.style("✓ ", fg="green") + f"{verb} objective #{issue.id} {issue.url}")
