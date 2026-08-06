"""``perk gist create`` — mint a run_id and persist the gist (contracts.md §8.41)."""

import json
import os
from pathlib import Path

import click

from perk import plan
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError, IssueRef
from perk.backends.objective_store import ObjectiveStoreError
from perk.cli.alias import alias
from perk.cli.context import require_github, require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.state import cache, run_id
from perk.substrate.output import machine_output, user_output


def _scope_from_handoff(repo_root: Path, run_id_value: str | None, scope: str | None) -> str | None:
    """Default ``scope`` from the run's handoff when not passed explicitly (§8.41).

    The ``perk gist author --scope`` cold door stashes the pre-seeded scope in the handoff (the
    declared ``gist_scope`` key) so it survives every save surface (the ``gist_save`` tool and
    the ``/gist-save`` command forward only ``{prose, title, scope?}``). An explicit ``--scope``
    always wins; a missing handoff or a scope-less one leaves the input untouched. Best-effort:
    a malformed handoff must never block a save.
    """
    if scope is not None or not run_id_value:
        return scope
    try:
        handoff = cache.read_handoff(repo_root, run_id_value)
    except (OSError, ValueError):
        return scope
    if handoff is None:
        return scope
    ho_scope = handoff.gist_scope
    if ho_scope in ("plan", "objective"):
        return ho_scope
    return scope


def _consumption_hint(gist_id: str, scope: str) -> str:
    """The human-facing consumption pointer: the adoption door matching the gist's scope."""
    if scope == "objective":
        return f"Consume with: perk objective author --from {gist_id}"
    return f"Consume with: perk plan from {gist_id}"


@alias("new")
@click.command("create")
@click.option(
    "--body",
    "body_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to the authored gist markdown (prose only — no roadmap, no steps).",
)
@click.option("--title", help="Gist title (else derived from body).")
@click.option(
    "--scope",
    type=click.Choice(["plan", "objective"]),
    default=None,
    help="The gist's consumption tier (else the launch handoff's pre-seeded scope, else plan).",
)
@click.option("--run-id", "run_id_arg", help="Correlation run id (defaults to $PERK_RUN_ID).")
@click.option("--dry-run", is_flag=True, help="Compose without creating anything.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def create_gist(
    ctx: click.Context,
    *,
    body_path: Path,
    title: str | None,
    scope: str | None,
    run_id_arg: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Mint a run_id and persist the gist from authored markdown."""
    try:
        repo_root = require_repo(ctx)
        if not dry_run:
            require_github(ctx)
        body_text = body_path.read_text(encoding="utf-8").strip()
        if not body_text:
            raise UserFacingCliError("Gist body is empty", error_type="empty_body")
        resolved_title = title or plan.derive_title(body_text, fallback="perk gist")
        resolved_run_id = run_id_arg or os.environ.get("PERK_RUN_ID") or run_id.mint()
        # Scope resolution: explicit --scope > the launch handoff's pre-seeded `gist_scope`
        # (best-effort recovery — never blocks a save) > "plan".
        resolved_scope = _scope_from_handoff(repo_root, resolved_run_id, scope) or "plan"

        ref: IssueRef | None = None
        if resolved_scope == "objective":
            # Objective scope routes to the project tier first (on Linear a gist project); a
            # None return (no project surface, or the offline dry-run) falls through to the
            # issue tier with the scope stamped in the gist-header.
            store = resolve.resolve_objective_store(repo_root)
            source = store.create_gist_source(
                title=resolved_title, prose=body_text, run_id=resolved_run_id, dry_run=dry_run
            )
            if source is not None:
                ref = IssueRef(id=source.id, url=source.url, existed=source.existed)
        if ref is None:
            backend = resolve.resolve_issue_backend(repo_root)
            ref = backend.create_gist_issue(
                title=resolved_title,
                body=body_text,
                run_id=resolved_run_id,
                scope=resolved_scope,
                dry_run=dry_run,
            )
    except (IssueBackendError, ObjectiveStoreError) as exc:
        fail(ctx, as_json=as_json, error_type="github_error", message=f"gist create failed\n{exc}")
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
        # Opaque string id at every machine boundary (contracts §8.21).
        "gist": {"id": ref.id, "url": ref.url, "existed": ref.existed},
        "scope": resolved_scope,
        "dry_run": dry_run,
    }
    if as_json:
        machine_output(json.dumps(payload))
    else:
        verb = "Found existing" if ref.existed else "Created"
        user_output(click.style("✓ ", fg="green") + f"{verb} gist {ref.id} {ref.url}")
        if not dry_run:
            user_output(_consumption_hint(ref.id, resolved_scope))
