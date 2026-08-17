"""`perk objective create` — mint a run_id and create the perk:objective issue."""

import json
import os
import tomllib
from pathlib import Path
from typing import Any

import click

from perk import objective, plan
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import ObjectiveStoreError
from perk.cli.alias import alias
from perk.cli.context import require_github, require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.delivery import (
    Delivery,
    DeliveryError,
    PrepareRequest,
    TransferRequest,
    resolve_delivery,
)
from perk.github import GitHubError
from perk.state import cache, run_id
from perk.substrate import git
from perk.substrate.config import ConfigError, load_config
from perk.substrate.output import machine_output, user_output


def _adopt_from_handoff(
    repo_root: Path, run_id_value: str | None, adopt_from: str | None
) -> str | None:
    """Default ``adopt_from`` from the run's handoff when not passed explicitly (§8.30).

    The ``objective author --from`` cold door stashes the source id in the handoff (key
    ``adopt_from``) so the in-place adoption link survives the ``objective_save`` tool path (which
    forwards only ``{prose, roadmap, title, base, run-id}``). An explicit ``--adopt-from`` always
    wins; a missing handoff, a non-adoption handoff, or a malformed value leaves the input
    untouched. Best-effort: a malformed handoff must never block a save. Opaque string (§8.21).
    """
    if adopt_from is not None or not run_id_value:
        return adopt_from
    try:
        handoff = cache.read_handoff(repo_root, run_id_value)
    except (OSError, ValueError):
        return adopt_from
    if handoff is None:
        return adopt_from
    ho_adopt = handoff.adopt_from
    if ho_adopt:
        return str(ho_adopt)
    return adopt_from


def _supersedes_from_handoff(
    repo_root: Path, run_id_value: str | None, supersedes: str | None
) -> str | None:
    """Default ``supersedes`` from the run's handoff when not passed explicitly (the supersede
    model).

    The ``objective replan`` cold door stashes the old objective id in the handoff (key
    ``supersedes``) so the close-old/create-new link survives the ``objective_save`` tool path
    (which forwards only ``{prose, roadmap, title, base, run-id}``). An explicit ``--supersedes``
    always wins; a missing handoff, a non-supersede handoff, or a malformed value leaves the input
    untouched. Best-effort: a malformed handoff must never block a save. Opaque string (§8.21).
    """
    if supersedes is not None or not run_id_value:
        return supersedes
    try:
        handoff = cache.read_handoff(repo_root, run_id_value)
    except (OSError, ValueError):
        return supersedes
    if handoff is None:
        return supersedes
    ho_supersedes = handoff.supersedes
    if ho_supersedes:
        return str(ho_supersedes)
    return supersedes


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
    "--base",
    help="Target branch for this objective's plans (else `[workflow] base`, else the GitHub "
    "default).",
)
@click.option(
    "--roadmap",
    "roadmap_json",
    help="Structured roadmap as a JSON array of nodes (preferred over embedding YAML in --body).",
)
@click.option("--run-id", "run_id_arg", help="Correlation run id (defaults to $PERK_RUN_ID).")
@click.option(
    "--adopt-from",
    help="Adopt the named pre-existing source (a Linear project / GitHub issue) IN PLACE as this "
    "objective (stamps the objective metadata additively into the same source).",
)
@click.option(
    "--supersedes",
    help="Re-author as a net-new objective that supersedes and closes the named OLD objective "
    "(carries unfinished work forward). Mutually exclusive with --adopt-from.",
)
@click.option(
    "--delivery",
    type=click.Choice(["incremental", "stacked"]),
    default=None,
    help="The reviewed delivery choice: incremental (the default — each plan lands "
    "independently) or stacked (all non-skipped roadmap nodes land as ONE atomic PR train; "
    "validated + capability-checked at save).",
)
@click.option("--dry-run", is_flag=True, help="Compose without creating an issue.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def create_objective(
    ctx: click.Context,
    *,
    body_path: Path,
    title: str | None,
    base: str | None,
    roadmap_json: str | None,
    run_id_arg: str | None,
    adopt_from: str | None,
    supersedes: str | None,
    delivery: str | None,
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
        raw_roadmap: Any = None
        if roadmap_json is not None:
            try:
                raw = json.loads(roadmap_json)
            except json.JSONDecodeError as exc:
                raise UserFacingCliError(
                    f"Invalid --roadmap JSON: {exc}", error_type="invalid_roadmap"
                ) from exc
            raw_roadmap = raw
            roadmap_nodes, errors = objective.parse_structured_roadmap(raw)
        else:
            body_nodes, errors = objective.parse_roadmap_nodes(body_text)
        if errors:
            raise UserFacingCliError(
                "Invalid objective roadmap: " + "; ".join(errors), error_type="invalid_roadmap"
            )
        # Reject a roadmap-free objective before creating (also makes --dry-run reject early). The
        # parse/read layer stays lenient (existing node-less issues remain readable); creation does
        # not. `empty_roadmap` falls through `perk.cli.emit.EXIT_FOR_TYPE` to exit 1.
        effective_nodes = roadmap_nodes if roadmap_nodes is not None else body_nodes
        if not effective_nodes:
            raise UserFacingCliError(
                "An objective needs at least one roadmap node — author a roadmap (the "
                "objective_save tool's `roadmap`, or a `--roadmap` JSON array) before creating.",
                error_type="empty_roadmap",
            )
        resolved_title = title or plan.derive_title(body_text, fallback="perk objective")
        resolved_run_id = run_id_arg or os.environ.get("PERK_RUN_ID") or run_id.mint()
        # Pin the objective's base at create time: explicit --base wins, else the repo's
        # `[workflow] base` default, else None (node plans then fall through to the GitHub
        # default). Pinning keeps the objective self-describing for its node plans.
        # This path bypasses `require_config` (the lazy context cache), so guard the raw config
        # errors locally — a broken config must fail the create cleanly, not traceback.
        try:
            resolved_base = base or load_config(repo_root).workflow_base
        except (tomllib.TOMLDecodeError, ConfigError) as exc:
            raise UserFacingCliError(f".perk config invalid: {exc}\nFix it, then re-run.") from exc
        store = resolve.resolve_objective_store(repo_root)
        # Recover the adoption link from the handoff: the `objective author --from` cold
        # door stashes the source id in the handoff so it survives the `objective_save` tool path
        # (which forwards only {prose, roadmap, title, base, run-id}). An explicit --adopt-from
        # wins.
        adopt_from = _adopt_from_handoff(repo_root, resolved_run_id, adopt_from)
        # Recover the supersede link from the handoff too (the `objective replan` cold door stashes
        # the OLD objective id there). An explicit --supersedes wins.
        supersedes = _supersedes_from_handoff(repo_root, resolved_run_id, supersedes)
        # --supersedes and --adopt-from are mutually exclusive (close-old/create-new vs in-place
        # additive stamp — incompatible models).
        if adopt_from is not None and supersedes is not None:
            raise UserFacingCliError(
                "--supersedes and --adopt-from are mutually exclusive (re-author vs in-place "
                "adoption).",
                error_type="invalid_input",
            )
        # The reviewed delivery choice (§8.45). Only an explicit `stacked` changes anything —
        # absent (and an explicit `incremental`, forwarded verbatim from the reviewed draft)
        # keeps every existing path byte-identical (§8.42's absence rule: incremental is never
        # written). Order: strict train validation → the adopt refusal → Prepare (skipped on
        # --dry-run, which is offline) → the store mutation.
        resolved_delivery: objective.DeliveryPolicy | None = None
        delivery_lineage: str | None = None
        delivery_service: Delivery | None = None
        if delivery == "stacked":
            stacked_errors = objective.validate_stacked_roadmap(effective_nodes)
            if stacked_errors:
                raise UserFacingCliError(
                    "Invalid objective roadmap: " + "; ".join(stacked_errors),
                    error_type="invalid_roadmap",
                )
            if adopt_from is not None:
                raise UserFacingCliError(
                    "--adopt-from cannot be combined with --delivery stacked: in-place "
                    "adoption of a stacked objective is deferred — author a fresh stacked "
                    "objective instead.",
                    error_type="invalid_input",
                )
            if not dry_run:
                delivery_service = resolve_delivery(repo_root)
                # Prepare resolves the effective probe base lazily while stored base semantics
                # stay unchanged (`resolved_base` may remain None).
                if delivery_service is None:
                    raise RuntimeError("real stacked save lost its Delivery service")
                delivery_service.prepare(PrepareRequest(kind="authoring", base=resolved_base))
                resolved_delivery = objective.DeliveryPolicy.STACKED
                if supersedes is None:
                    # A fresh stacked create mints the train identity here (§8.45); a
                    # superseding save's copy-or-mint moved into the transfer protocol.
                    delivery_lineage = objective.mint_delivery_lineage()
        # Supersede model: on a real save, create a net-new objective that supersedes + closes the
        # OLD one (carrying unfinished work forward). The D1 routing matrix (§8.53) keys on ONE
        # fail-closed predecessor classification read: a stacked predecessor — or an
        # incremental→stacked conversion — routes through the transfer protocol; only
        # incremental→incremental keeps the plain store mutation (byte-identical apart from the
        # classification read). The writer returns None for a store that does not support
        # superseding (`supersede_unsupported`); a dry run falls through to the offline
        # `create_objective(dry_run=True)` compose-preview (transfer never engages).
        if supersedes is not None and not dry_run:
            old_objective_id = supersedes.strip().lstrip("#").strip()
            carry_map = objective.parse_adopt_mapping(raw_roadmap)
            if delivery_service is None:
                delivery_service = resolve_delivery(repo_root)
            result = delivery_service.transfer(
                TransferRequest(
                    predecessor_id=old_objective_id,
                    run_id=resolved_run_id,
                    title=resolved_title,
                    prose=body_text,
                    base=resolved_base,
                    roadmap_nodes=tuple(effective_nodes),
                    carry_map=tuple(carry_map.items()),
                    delivery=(
                        "stacked"
                        if resolved_delivery is objective.DeliveryPolicy.STACKED
                        else "incremental"
                    ),
                )
            )
            issue = result.successor
        # In-place objective adoption (§8.30): on a real save, stamp perk's metadata
        # ADDITIVELY into the existing source instead of minting a fresh objective. The writer
        # returns None on a dry run (resolving the source needs a network read) OR for a store that
        # does not support adoption (`adopt_unsupported`); a dry run falls through to the offline
        # `create_objective(dry_run=True)` compose-preview.
        elif adopt_from is not None and not dry_run:
            adopt_from = adopt_from.strip().lstrip("#").strip()
            adopt_map = objective.parse_adopt_mapping(raw_roadmap)
            issue = store.adopt_source_as_objective(
                source_id=adopt_from,
                title=resolved_title,
                prose=body_text,
                run_id=resolved_run_id,
                base=resolved_base,
                roadmap_nodes=effective_nodes,
                adopt_map=adopt_map,
            )
            if issue is None:
                raise UserFacingCliError(
                    f"The configured objective backend does not support in-place adoption of "
                    f"{adopt_from!r}; author a fresh objective instead.",
                    error_type="adopt_unsupported",
                )
        else:
            issue = store.create_objective(
                title=resolved_title,
                body=body_text,
                run_id=resolved_run_id,
                base=resolved_base,
                roadmap_nodes=roadmap_nodes,
                delivery=resolved_delivery,
                delivery_lineage=delivery_lineage,
                dry_run=dry_run,
            )
    except DeliveryError as exc:
        fail(ctx, as_json=as_json, error_type=exc.error_type, message=str(exc))
        return
    except git.GitError as exc:
        fail(ctx, as_json=as_json, error_type="git_error", message=str(exc))
        return
    except (IssueBackendError, GitHubError) as exc:
        fail(ctx, as_json=as_json, error_type="github_error", message=str(exc))
        return
    except ObjectiveStoreError as exc:
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

    # Fail-open Project Update: post a status update on a fresh create only (skip the
    # idempotent found-existing path and any dry run). Linear project store posts; GitHub + the
    # issue-backed Linear store no-op (return False). An expected store failure
    # (ObjectiveStoreError) is logged loud-but-non-fatal and NEVER changes the create result;
    # a programming error propagates.
    if not dry_run and not issue.existed:
        try:
            store.post_status_update(
                objective_id=issue.id,
                body=objective.objective_created_update_body(
                    resolved_title,
                    node_count=len(effective_nodes),
                    phase_count=len(objective.group_nodes_by_phase(effective_nodes)),
                ),
            )
        except ObjectiveStoreError as exc:  # fail-open: bookkeeping, never load-bearing
            user_output(f"perk objective create: project update skipped (non-fatal): {exc}")

    payload = {
        "success": True,
        "error_type": None,
        # Opaque string id at every machine boundary (contracts §8.21).
        "objective": {"id": issue.id, "url": issue.url, "existed": issue.existed},
        "dry_run": dry_run,
    }
    if as_json:
        machine_output(json.dumps(payload))
    else:
        verb = "Found existing" if issue.existed else "Created"
        user_output(click.style("✓ ", fg="green") + f"{verb} objective #{issue.id} {issue.url}")
