"""``perk objective refine <objective> [--node ID]`` — the objective-node refinement cold door.

Select a refinable FUTURE node (pending/blocked with no plan — an explicit ``--node`` or the
first unrefined eligible node in roadmap order, ignoring dependency readiness), prepare one
grounding context, and launch a **read-only** ``objective-refine`` session that authors a dated
advisory refinement and saves ONLY the node's marked comment (contracts.md §8.67). It never
creates a plan, claims a node, writes a backlink, changes node/objective state, or provisions a
predecessor checkout — the session explores the invoking checkout as-is, dirty changes included.

**Both issue backends**: the door acts on whatever objective store the committed ``[issues]``
selection resolves after the sync — the Linear Project store (carrier: the node-issue) or the
GitHub issue store (carrier: the objective issue itself). It never probes ``gh auth``: a GitHub
transport or authentication failure surfaces from the adapter as ``backend_error`` carrying
``gh``'s own diagnostic.

**Cold ordering — sync first, then everything fresh** (the door owns the run's ONE sync):
input + local-only + invoking-checkout restrictions → the guarded fast-forward (real launch
only, unless ``--no-sync``) → a FULL Config reload from disk → fresh store/issue adapters,
target selection, identity binding, engagement and the capture-time provenance → run mint,
context materialization, launch with that same post-sync Config
(``SeededLaunch.config_override``) and ``sync_main=False``. Nothing selected, resolved or
configured before the sync survives into the launch.

The handoff carries only the namespaced ``objective_refinement: {context_digest}`` — never a
top-level ``objective_id``/``node_id`` (the cold claim path reads those as a planning claim).
``--dry-run`` is online read-only resolution: it reports the selection and writes, mints, syncs
and launches nothing.
"""

from collections.abc import Callable
from pathlib import Path

import click

from perk.cli import completions
from perk.cli.commands.objective.refinement_common import REFINEMENT_FAILURES, as_cli_error
from perk.cli.commands.objective.shared import objective_read_instruction, parse_objective_id
from perk.cli.commands.seeded_door import SeededLaunch, run_seeded_door, seeded_door_options
from perk.cli.ensure import UserFacingCliError
from perk.objective.refinement import authoring
from perk.prompts import render
from perk.run import launch
from perk.state import cache, run_id
from perk.substrate import git
from perk.substrate.config import Config, ConfigError, load_config
from perk.substrate.output import io_step, log_warn
from perk.substrate.registry import Stage

_PRIOR_NOTE = (
    "A valid prior refinement already exists on this node — the context carries its FULL "
    "Markdown; you are re-refining, and a save replaces it whole (full-content replacement)."
)


def seed_prompt(
    *,
    objective_id: str,
    title: str,
    node_id: str,
    node_description: str,
    backend: str,
    url: str,
    context_path: str,
    has_prior: bool,
) -> str:
    """The shared cold/warm refinement flow prompt (``stages/objective-refine/seed.md``). The
    objective title + node description ride inside ``<untrusted_objective>`` as DATA; the only
    door-derived interpolations are identifiers, the read clause and the context artifact path."""
    return render(
        "stages/objective-refine/seed.md",
        {
            "number": objective_id,
            "title": title,
            "node_id": node_id,
            "node_description": node_description,
            "read_clause": objective_read_instruction(backend, objective_id, url),
            "context_path": context_path,
            "prior_note": _PRIOR_NOTE if has_prior else "",
        },
    )


def _checkout_observation(repo_root: Path) -> dict[str, object]:
    """The dry-run's honest checkout line: HEAD + dirty flag as observed NOW (never persisted)."""
    return {
        "path": str(repo_root),
        "head_sha": git.resolve_commit(repo_root, "HEAD"),
        "dirty": git.is_dirty(repo_root),
    }


@click.command("refine", context_settings={"ignore_unknown_options": True})
@click.argument("number", required=False, shell_complete=completions.complete_objective_id)
@click.option(
    "--node",
    "node_ids",
    multiple=True,
    help="Refine a specific node id (else the first refinable, unrefined future node).",
)
@seeded_door_options(
    worktree_help="Not accepted: objective refine always explores the checkout it is invoked "
    "from (dirty changes included) and never positions another worktree.",
    dry_run_help="Resolve the target + print; sync nothing, mint nothing, launch nothing.",
    remote_subject="objective refine",
    no_sync_help="Skip the ONE pre-selection fast-forward of the invoking checkout (target "
    "selection, provenance capture and the session then read the checkout as-is).",
)
@click.pass_context
def refine_objective(
    ctx: click.Context,
    *,
    number: str | None,
    node_ids: tuple[str, ...],
    worktree: str | None,
    dry_run: bool,
    remote: str | None,
    as_json: bool,
    no_sync: bool,
    pi_args: tuple[str, ...],
) -> None:
    """Author an advisory refinement of a future objective node (read-only).

    \b
    NUMBER is the objective id (required — a cold session has no active objective).
    \b
    Examples:
      perk objective refine 7                 # refine the first unrefined future node
      perk objective refine 7 --node 2.3      # refine (or re-refine) a specific node
      perk objective refine 7 --dry-run       # resolve + print, launch nothing
    """

    def gather(repo_root: Path, config: Config, stage: Stage) -> SeededLaunch:
        # 1. Input, local-only target and invoking-checkout restrictions — before any effect.
        if number is None:
            raise UserFacingCliError(
                "An objective id is required (e.g. `perk objective refine 7`).",
                error_type="objective_required",
            )
        objective_id = parse_objective_id(number)
        if len(node_ids) > 1:
            raise UserFacingCliError(
                "--node may be given at most once.", error_type="invalid_input"
            )
        requested_node = node_ids[0].strip() if node_ids else None
        if requested_node == "":
            raise UserFacingCliError("--node must not be blank.", error_type="invalid_input")
        if worktree is not None:
            raise UserFacingCliError(
                "--worktree is not accepted: objective refine explores the checkout it is "
                "invoked from and never positions another worktree.",
                error_type="invalid_input",
            )
        launch.resolve_target(stage, remote)  # `remote_blocked` on this local-only stage

        if dry_run:
            # Online read-only resolution: select against the configured route as-is and report.
            # No sync, no mint, no file, no claim, no launch.
            with io_step(f"resolving refinement target on objective {objective_id}") as s:
                selected = _guard(
                    lambda: authoring.select_bound_target(
                        repo_root, objective_id=objective_id, node_id=requested_node
                    )
                )
                s.done(f"selected node {selected.target.identity.node_id}")
            target = selected.target
            observation = _guard(lambda: _checkout_observation(repo_root))
            has_prior = selected.read.saved is not None
            payload: dict[str, object] = {
                "success": True,
                "error_type": None,
                "objective_id": target.identity.objective_id,
                "objective_run_id": target.identity.objective_run_id,
                "node_id": target.identity.node_id,
                "node_status": target.status.value,
                "carrier_identifier": target.carrier_identifier,
                "carrier_url": target.carrier_url,
                "has_prior_refinement": has_prior,
                "source_changed": selected.read.source_changed,
                "advisory": True,
                "checkout": observation,
                "backend": target.identity.backend,
                "dry_run": True,
            }
            return SeededLaunch(
                seed="",
                launch_note="",
                dry_run_label="objective refine --dry-run (resolve only; no sync, no launch)",
                dry_run_fields=(
                    f"  objective={target.identity.objective_id}  node={target.identity.node_id}"
                    f"  status={target.status.value}  prior={'yes' if has_prior else 'no'}",
                    f"  carrier={target.carrier_identifier}  advisory=yes",
                    f"  checkout={observation['path']}  head={observation['head_sha']}"
                    f"  dirty={observation['dirty']}",
                ),
                dry_run_payload=payload,
                dry_run_shows_seed=False,
            )

        # 2. Banner, then the run's ONE guarded fast-forward (the seeded tail gets no_sync=True).
        launch.print_launch_banner_gated(repo_root, dry_run=False, remote=remote)
        if not no_sync:
            launch._sync_main_checkout(repo_root)

        # 3. Reload the COMPLETE Config from disk (never the pre-sync cache), and only now build
        # fresh adapters + select + capture provenance.
        try:
            fresh_config = load_config(repo_root)
        except ConfigError as exc:
            raise UserFacingCliError(str(exc), error_type="config_error") from exc

        # 4. Mint the run (provenance is bound to it), prepare, materialize, launch.
        rid = run_id.mint()
        with io_step(f"preparing refinement context for objective {objective_id}") as s:
            context = _guard(
                lambda: authoring.prepare_refinement_context(
                    repo_root, objective_id=objective_id, node_id=requested_node, run_id=rid
                )
            )
            prep = authoring.prepared(context)
            try:
                cache.write_scratch(repo_root, rid, authoring.CONTEXT_ARTIFACT, prep.context_json)
            except OSError as exc:
                raise UserFacingCliError(
                    f"could not write the refinement context: {exc}", error_type="write_failed"
                ) from exc
            s.done(
                f"prepared node {context.target.identity.node_id} → {authoring.CONTEXT_ARTIFACT}"
            )
        # Visible fail-soft warnings (e.g. an unreadable node engagement) — also carried in the
        # context artifact's `warnings` for the session.
        for warning in context.warnings:
            log_warn(warning)

        target = context.target
        seed = seed_prompt(
            objective_id=context.objective.id,
            title=context.objective.title,
            node_id=target.identity.node_id,
            node_description=target.source.description,
            backend=target.identity.backend,
            url=context.objective.url,
            context_path=str(cache.session_data_dir(repo_root, rid) / authoring.CONTEXT_ARTIFACT),
            has_prior=context.prior is not None,
        )
        return SeededLaunch(
            seed=seed,
            launch_note=(
                f"selected objective {context.objective.id} node {target.identity.node_id} "
                "(advisory refinement; nothing claimed)"
            ),
            dry_run_label="",
            dry_run_fields=(),
            dry_run_payload={},
            # Namespaced ONLY: a top-level objective_id/node_id would read as a planning claim.
            handoff_extra={"objective_refinement": {"context_digest": prep.context_digest}},
            run_id_override=rid,
            config_override=fresh_config,
        )

    run_seeded_door(
        ctx,
        stage_id=authoring.REFINE_STAGE_ID,
        worktree=worktree,
        dry_run=dry_run,
        remote=remote,
        as_json=as_json,
        # The gather closure owns the run's one sync (gated on --no-sync above); the tail never
        # syncs again.
        no_sync=True,
        pi_args=pi_args,
        # Every expected failure is translated inside `gather` (typed refinement / backend / git
        # / write codes) — nothing is left for the helper's github_error arm.
        backend_errors=(),
        gather=gather,
    )


def _guard[T](fn: Callable[[], T]) -> T:
    """Run one step, translating the refinement exception family (refinement/authoring codes,
    resolver/store, git probes, filesystem) into the typed CLI error the seeded-door boundary
    understands."""
    try:
        return fn()
    except REFINEMENT_FAILURES as exc:
        raise as_cli_error(exc) from exc
