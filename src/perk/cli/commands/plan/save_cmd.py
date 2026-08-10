"""`perk plan save` — the Python/worker GitHub plan-write (the cold save door).

The first `require_github` consumer and the first GitHub *mutation* (contracts.md §8.4).
The warm in-session twin is the TS `/plan-save` tool. Supervisor surface:
`--json` to stdout + stable exit codes, human text to stderr.

Exit codes: 0 saved · 1 invalid input / unauthed / op failure · 2 not-a-repo.
"""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

import click

from perk import objective, plan
from perk.backends import issue_backend, objective_store, resolve
from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import ObjectiveStoreError
from perk.boundary import OutputModel
from perk.cli.context import require_github, require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.state import cache
from perk.substrate.config import ConfigError, load_config
from perk.substrate.output import user_output


@dataclass(frozen=True)
class ObjectiveNodeLink:
    """The objective-node commit outcome: `linked` true iff the node→plan backlink +
    in_progress advance succeeded; `node`/`status` describe it; `error` carries a non-fatal
    link failure. A precise frozen record (not a `dict`) so its serialization boundary is
    nameable (`ObjectiveNodeLinkOut`)."""

    linked: bool
    node: str
    status: str | None
    error: str | None


@dataclass(frozen=True)
class PlanSaveResult:
    issue: issue_backend.IssueRef
    plan_ref: plan.PlanRef
    issue_body: str
    body_comment: str
    dry_run: bool
    cached: bool  # the plan-ref was written to .perk/workflow/plan-ref.json (real save only)
    updated: bool  # an existing issue was updated in place (idempotent re-save upsert)
    # The objective-node commit; `None` when no objective node link was requested (no --node-id).
    objective_node: ObjectiveNodeLink | None = None


@click.command("save")
@click.option(
    "--plan-file",
    # Deliberately no exists=True: existence/emptiness are tier-2 (UserFacingCliError) so the
    # --json error envelope (error_type: invalid_input) survives a missing file.
    type=click.Path(path_type=Path),
    help="Path to the plan markdown to save.",
)
@click.option("--run-id", help="Correlation run id (defaults to $PERK_RUN_ID).")
@click.option("--title", help="Issue title (defaults to the plan's first heading).")
@click.option(
    "--objective-id",
    help="Link the plan to an objective (the plan→objective direction).",
)
@click.option(
    "--node-id",
    help="Objective node id to commit on save (with --objective-id; sets the node→plan backlink "
    "+ advances it to in_progress).",
)
@click.option(
    "--consumed-learn",
    help="Comma-separated perk:learn issue ids this docs plan consumes (e.g. '45,50' "
    "or 'ENG-45,ENG-50').",
)
@click.option(
    "--adopt-from",
    help="Adopt the named pre-existing issue IN PLACE as this plan (stamps the plan "
    "metadata additively into that issue, mutually exclusive with --objective-id/--node-id).",
)
@click.option("--dry-run", is_flag=True, help="Compose and print without touching GitHub.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def plan_save(
    ctx: click.Context,
    *,
    plan_file: Path | None,
    run_id: str | None,
    title: str | None,
    objective_id: str | None,
    node_id: str | None,
    consumed_learn: str | None,
    adopt_from: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Save a plan to GitHub as an issue (the queryable header + the full body comment).

    \b
    Examples:
      perk plan save --plan-file plan.md           # create the plan issue
      perk plan save --plan-file plan.md --dry-run # compose + print, no GitHub
      perk plan save --plan-file plan.md --json    # machine-readable (supervisor surface)
    """
    try:
        repo_root = require_repo(ctx)
        # A dry run composes + prints locally; it needs neither auth nor a network.
        if not dry_run:
            require_github(ctx)
        resolved_run_id = run_id if run_id is not None else os.environ.get("PERK_RUN_ID")
        # Recover the objective link from the handoff: the `/plan-save` command forwards only
        # {plan, title}, so an objective-plan factory session would otherwise drop the link the
        # `objective-plan` command stashed in the handoff. Explicit flags always win; a non-
        # objective run (handoff without `objective_id`) is unaffected.
        objective_id, node_id = _link_from_handoff(
            repo_root, resolved_run_id, objective_id, node_id
        )
        # Recover `consumed_learn` from the handoff: the learn factories are read-only, so the
        # save lands review-first via `plan_review` approval (or the `/plan-save` failsafe) —
        # neither forwards consumed_learn — rather than the gated-out `plan_save` *tool*. The
        # learn cold doors stash the gathered ids in the handoff; recover them here so the save
        # surface is irrelevant. An explicit --consumed-learn always wins; a non-factory run (no
        # handoff key) is unaffected.
        consumed_learn_ids = _consumed_learn_from_handoff(
            repo_root, resolved_run_id, _parse_consumed_learn(consumed_learn)
        )
        # Recover the adoption link from the handoff: the `plan from` cold door stashes the
        # source `adopt_from` issue id in the handoff so it survives the `/plan-save` *command*
        # path (which forwards only {plan, title}). An explicit --adopt-from always wins.
        adopt_from = _adopt_from_handoff(repo_root, resolved_run_id, adopt_from)
        result = _plan_save_impl(
            repo_root=repo_root,
            plan_file=plan_file,
            run_id=resolved_run_id,
            title=title,
            objective_id=objective_id,
            node_id=node_id,
            consumed_learn=consumed_learn_ids,
            adopt_from=adopt_from,
            dry_run=dry_run,
        )
    except IssueBackendError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="github_error",
            message=f"GitHub plan write failed\n{exc}",
            extra={"dry_run": False},
        )
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
            extra={"dry_run": False},
        )
        return

    emit(as_json=as_json, payload=_result_to_dict(result), render=lambda: _render_human(result))


def _link_from_handoff(
    repo_root: Path,
    run_id: str | None,
    objective_id: str | None,
    node_id: str | None,
) -> tuple[str | None, str | None]:
    """Default ``objective_id``/``node_id`` from the run's handoff when not passed explicitly.

    The ``objective-plan`` factory stashes ``objective_id``/``node_id`` in the handoff so the link
    survives the ``/plan-save`` *command* path (which forwards only ``{plan, title}``). Explicit
    flags win outright; only fill BOTH from the handoff when BOTH were absent (a half-specified
    link is the caller's, never silently mixed with the handoff's). A missing handoff, a non-
    objective handoff, or a missing key leaves the inputs untouched. Best-effort: a malformed
    handoff must never block a save.
    """
    if objective_id is not None or node_id is not None or not run_id:
        return objective_id, node_id
    try:
        handoff = cache.read_handoff(repo_root, run_id)
    except (OSError, ValueError):
        return objective_id, node_id
    if handoff is None:
        return objective_id, node_id
    ho_objective = handoff.objective_id
    ho_node = handoff.node_id
    if ho_objective and ho_node:
        return str(ho_objective), str(ho_node)
    return objective_id, node_id


def _consumed_learn_from_handoff(
    repo_root: Path,
    run_id: str | None,
    consumed_learn: tuple[str, ...],
) -> tuple[str, ...]:
    """Default ``consumed_learn`` from the run's handoff when not passed explicitly.

    The ``learn-docs`` factory stashes the gathered ``perk:learn`` ids in the handoff so they
    survive the ``/plan-save`` *command* path (which forwards only ``{plan, title}``, dropping the
    flag). An explicit ``--consumed-learn`` (parsed to a non-empty tuple) always wins; an empty
    tuple means the flag was absent, so fall back to the handoff. A missing handoff, a non-factory
    handoff (no ``consumed_learn`` key), or a malformed value leaves the input untouched.
    Best-effort: a malformed handoff must never block a save. Ids are opaque strings (§8.21).
    """
    if consumed_learn or not run_id:
        return consumed_learn
    try:
        handoff = cache.read_handoff(repo_root, run_id)
    except (OSError, ValueError):
        return consumed_learn
    if handoff is None:
        return consumed_learn
    raw = handoff.consumed_learn
    if not raw:
        return consumed_learn
    ids = {cleaned for n in raw if (cleaned := str(n).lstrip("#").strip())}
    if not ids:
        return consumed_learn
    return tuple(sorted(ids))


def _adopt_from_handoff(
    repo_root: Path,
    run_id: str | None,
    adopt_from: str | None,
) -> str | None:
    """Default ``adopt_from`` from the run's handoff when not passed explicitly.

    The ``plan from`` cold door stashes the source issue id in the handoff (key ``adopt_from``) so
    the in-place adoption link survives the ``/plan-save`` *command* path (which forwards only
    ``{plan, title}``). An explicit ``--adopt-from`` always wins; a missing handoff, a non-adoption
    handoff (no ``adopt_from`` key), or a malformed value leaves the input untouched. Best-effort:
    a malformed handoff must never block a save. The id is an opaque string (§8.21).
    """
    if adopt_from is not None or not run_id:
        return adopt_from
    try:
        handoff = cache.read_handoff(repo_root, run_id)
    except (OSError, ValueError):
        return adopt_from
    if handoff is None:
        return adopt_from
    ho_adopt = handoff.adopt_from
    if ho_adopt:
        return str(ho_adopt)
    return adopt_from


def _parse_consumed_learn(raw: str | None) -> tuple[str, ...]:
    """Parse a comma-separated issue-id list into a sorted unique tuple of opaque string ids
    (GitHub ``45`` or Linear ``ENG-45``).

    ``None``/empty → ``()``. Tokens are stripped of ``#``/whitespace; only empty tokens are
    skipped — ids are otherwise opaque (no int parse; contracts §8.21).
    """
    if not raw or not raw.strip():
        return ()
    ids: set[str] = set()
    for token in raw.split(","):
        token = token.strip().lstrip("#").strip()
        if token:
            ids.add(token)
    return tuple(sorted(ids))


def _fetch_linked_objective(
    store: objective_store.ObjectiveStore,
    objective_id: str | None,
    *,
    strict: bool,
) -> objective_store.ObjectiveState | None:
    """Fetch the linked objective's state ONCE (the base lookup + the §8.46 layer stamping
    both read from it).

    ``strict`` (a node-linked real save): a failed read fails the save AND a proven-missing
    objective is a typed refusal — a save that cannot determine the delivery policy must not
    guess or proceed unstamped. Non-strict (unlinked saves + dry runs): fail-soft with a
    report, mirroring the historic base lookup — an expected store failure never blocks the
    save.
    """
    if objective_id is None:
        return None
    bare = str(objective_id).lstrip("#")
    try:
        state = store.get_objective(objective_id=bare)
    except ObjectiveStoreError as exc:
        if strict:
            raise UserFacingCliError(
                f"objective #{bare} read failed — a node-linked save reads its objective "
                f"strictly (the delivery policy must not be guessed)\n{exc}",
                error_type="github_error",
            ) from exc
        # Report (never silent) — matches the repo's fail-open-with-report norm so a misconfig
        # objective store surfaces, while the save still proceeds (falls through to config).
        user_output(f"perk plan save: objective base lookup skipped (non-fatal): {exc}")
        return None
    if state is None and strict:
        raise UserFacingCliError(
            f"Objective #{bare} not found — a node-linked save reads its objective strictly "
            "(a save that cannot determine the delivery policy must not proceed unstamped).",
            error_type="objective_not_found",
        )
    return state


@dataclass(frozen=True)
class _LayerIdentity:
    """The §8.46 layer-identity trio a stacked node-linked save stamps into the plan header
    (checkpoint fields stay unwritten — the durable pair is publication-owned).
    ``delivery_lineage`` is always a verified non-empty string — a stacked objective without
    one refuses before composing."""

    objective_node_id: str
    delivery_lineage: str
    predecessor_plan_id: str | None


def _stacked_layer_identity(
    state: objective_store.ObjectiveState, node_id: str, *, strict: bool
) -> _LayerIdentity | None:
    """Derive the layer-identity trio for a node-linked save of a STACKED objective (§8.46).

    ``None`` for incremental objectives (headers stay byte-identical). The predecessor is the
    delivery-order predecessor node's linked plan id (``None`` on the bottom layer); a
    non-bottom layer whose predecessor has no linked plan is a typed
    ``stacked_predecessor_missing`` refusal BEFORE any write — without the trio every stacked
    plan would mint permanent ``wrong_owner``/``node_link_mismatch`` blockers. ``strict``
    (real save) fails closed on junk policy / a missing or invalid lineage (an unstamped
    routing field would silently send a child layer down the incremental path) / an
    underivable order; a dry run degrades to no trio (best-effort compose).
    """
    try:
        policy = objective.delivery_policy(state.header)
    except ValueError as exc:
        if strict:
            raise UserFacingCliError(str(exc), error_type="invalid_delivery_policy") from exc
        return None
    if policy is not objective.DeliveryPolicy.STACKED:
        return None
    raw_lineage = state.header.get("delivery_lineage")
    lineage = raw_lineage.strip() if isinstance(raw_lineage, str) else None
    if not lineage:
        if strict:
            raise UserFacingCliError(
                f"objective #{state.id} is stacked but carries no valid delivery_lineage — "
                "a stacked layer cannot be saved without its train identity (the plan would "
                "silently route down the incremental path).",
                error_type="missing_lineage",
            )
        return None
    try:
        order = objective.delivery_order(list(state.nodes))
    except ValueError as exc:
        if strict:
            raise UserFacingCliError(
                f"no canonical delivery order exists: {exc}", error_type="invalid_train"
            ) from exc
        return None
    index = next((i for i, node in enumerate(order) if node.id == node_id), None)
    if index is None:
        if strict:
            raise UserFacingCliError(
                f"node {node_id} is not a layer of objective #{state.id}'s delivery train "
                "(unknown or skipped) — a stacked node-linked save must name a layer.",
                error_type="invalid_input",
            )
        return None
    if index == 0:
        predecessor: str | None = None
    else:
        predecessor_node = order[index - 1]
        if predecessor_node.pr is None:
            raise UserFacingCliError(
                f"node {node_id} is not the bottom layer and its delivery-order predecessor "
                f"{predecessor_node.id} has no linked plan — plan the predecessor first "
                f"(`perk objective plan {state.id} --node {predecessor_node.id}`).",
                error_type="stacked_predecessor_missing",
            )
        predecessor = str(predecessor_node.pr).lstrip("#")
    return _LayerIdentity(
        objective_node_id=node_id,
        delivery_lineage=lineage,
        predecessor_plan_id=predecessor,
    )


def _refuse_cross_node_upsert(
    backend: issue_backend.IssueBackend, *, issue_id: str, requested_node: str
) -> None:
    """Refuse a node-linked same-run-id upsert whose stored header names a DIFFERENT node.

    ``create_plan_issue`` is idempotent on ``run_id`` (the documented upsert), so a scripted
    node-linked save reusing the ambient workflow run ID would silently rewrite the previous
    node's plan in place (self-predecessor header, two roadmap nodes pointing at one plan)
    while the command succeeds — ``issue.existed: true`` is the only tell. Read the stored
    ``objective_node_id`` BEFORE any mutation and fail closed on a cross-node mismatch
    (``error_type: node_conflict``). A null stored node stays allowed (legitimately links a
    standalone plan to a node); same-node re-saves proceed untouched.
    """
    state = backend.get_plan(issue_id=issue_id)
    if state is None:
        return
    stored = state.header.get("objective_node_id")
    existing = stored if isinstance(stored, str) else None
    if existing is not None and existing != requested_node:
        raise UserFacingCliError(
            f"plan #{issue_id} is already linked to objective node {existing}; refusing the "
            f"same-run-id upsert for node {requested_node} (it would silently rewrite the "
            f"other node's plan in place). Mint a fresh run ID per node — e.g. unset or "
            "override PERK_RUN_ID for this save.",
            error_type="node_conflict",
        )


def _resolve_plan_base(
    repo_root: Path,
    state: objective_store.ObjectiveState | None,
) -> str | None:
    """Resolve the plan's pinned base: the linked objective's own ``base`` wins (it is the
    source of truth for its node plans), else the repo's ``[workflow] base``, else ``None``.

    ``state`` is the once-fetched linked objective (:func:`_fetch_linked_objective`) —
    ``None``/missing, or a header without ``base``, falls through to the config step. When
    unset everywhere the submit + start-point paths fall back to the GitHub default branch
    (byte-identical to today).
    """
    if state is not None:
        obj_base = state.header.get("base")
        if isinstance(obj_base, str) and obj_base.strip():
            return obj_base.strip()
    # This path bypasses `require_config` (the lazy context cache), so guard the raw config
    # errors locally — a broken config must fail the save cleanly, not traceback.
    try:
        return load_config(repo_root).workflow_base
    except (tomllib.TOMLDecodeError, ConfigError) as exc:
        raise UserFacingCliError(f".perk config invalid: {exc}\nFix it, then re-run.") from exc


def _plan_save_impl(
    *,
    repo_root: Path,
    plan_file: Path | None,
    run_id: str | None,
    title: str | None,
    objective_id: str | None = None,
    node_id: str | None = None,
    consumed_learn: tuple[str, ...] = (),
    adopt_from: str | None = None,
    dry_run: bool,
) -> PlanSaveResult:
    """Pure-ish logic (no Click). Composes the header/body and performs the GitHub write."""
    # In-place adoption is NOT objective-linked: the node-unification path is the in-place
    # writer for objective nodes — refuse to mix two in-place semantics.
    if adopt_from is not None:
        adopt_from = adopt_from.strip().lstrip("#").strip() or None
    if adopt_from is not None and (objective_id is not None or node_id is not None):
        raise UserFacingCliError(
            "--adopt-from is mutually exclusive with --objective-id/--node-id (adoption is not "
            "objective-linked; objective nodes are unified in place via their node-issue).",
            error_type="invalid_input",
        )
    if plan_file is None:
        raise UserFacingCliError(
            "No plan file given\nPass --plan-file <path> to the plan markdown.",
            error_type="invalid_input",
        )
    if not plan_file.is_file():
        raise UserFacingCliError(f"Plan file not found: {plan_file}", error_type="invalid_input")
    plan_markdown = plan_file.read_text(encoding="utf-8")
    if not plan_markdown.strip():
        raise UserFacingCliError(f"Plan file is empty: {plan_file}", error_type="invalid_input")

    resolved_title = title or plan.derive_title(plan_markdown)
    backend = resolve.resolve_issue_backend(repo_root)
    store = resolve.resolve_objective_store(repo_root)

    # ONE objective read serves both the base lookup and the §8.46 layer stamping. A
    # node-linked real save reads strictly (a failed read fails the save); every other save
    # keeps the historic fail-soft posture.
    node_linked = bool(objective_id and node_id)
    objective_state = _fetch_linked_objective(
        store, objective_id, strict=node_linked and not dry_run
    )
    # Resolve + pin the plan's base: the objective's own base wins (it is the source of
    # truth for its node plans), else the repo's `[workflow] base`, else None (submit/start-point
    # fall back to the GitHub default branch). Pinned once here into BOTH the plan-header and the
    # cache.plan-ref so a later config change never retargets this plan.
    resolved_base = _resolve_plan_base(repo_root, objective_state)
    # The §8.46 layer-identity trio for a stacked node-linked save — derived BEFORE any write
    # (the stacked_predecessor_missing refusal must pre-empt every mutation). Incremental and
    # unlinked saves get None and stay byte-identical.
    layer_identity: _LayerIdentity | None = None
    if node_id is not None and node_linked and objective_state is not None:
        layer_identity = _stacked_layer_identity(objective_state, node_id, strict=not dry_run)
    header = plan.PlanHeader(
        run_id=run_id or "",
        created=plan.now_iso(),
        objective_id=objective_id,
        consumed_learn=consumed_learn,
        base=resolved_base,
        # Adoption provenance: self-referential by construction (the plan is stamped INTO
        # the source issue); its presence marks the issue body/title as verbatim human content.
        adopted_from=adopt_from,
        objective_node_id=layer_identity.objective_node_id if layer_identity else None,
        delivery_lineage=layer_identity.delivery_lineage if layer_identity else None,
        predecessor_plan_id=layer_identity.predecessor_plan_id if layer_identity else None,
    )
    header_out = plan.render_plan_header_fields(header)
    # The dry-run compose preview only — backends store the header themselves from `header_out`
    # (GitHub renders this same block; Linear upserts an attachment envelope).
    issue_body = plan.render_metadata_block(plan.PLAN_HEADER_KEY, header_out)
    body_comment = plan.render_plan_body(plan_markdown)

    # Unification: an objective-linked REAL save writes the plan INTO the existing
    # node-issue (project-backed stores) instead of minting a second perk:plan issue. The store's
    # `save_node_plan` returns the node-issue ref for a unifying store, and `None` otherwise (and
    # on a dry run — resolving the node-issue needs a network read). `None` means "take the
    # standalone path, UNCHANGED below".
    unified_ref = None
    if not dry_run and objective_id and node_id:
        unified_ref = store.save_node_plan(
            objective_id=str(objective_id).lstrip("#"),
            node_id=node_id,
            header_fields=header_out,
            plan_markdown=plan_markdown,
        )

    # In-place adoption: stamp the authored plan ADDITIVELY into the existing (non-perk)
    # issue — an in-place write into an existing object, so no second `perk:plan` issue is minted.
    # `dry_run` falls through to the standalone compose-preview (byte-stable existing behavior).
    adopt_ref = None
    if not dry_run and adopt_from:
        adopt_ref = backend.adopt_issue_as_plan(
            issue_id=adopt_from,
            header_fields=header_out,
            plan_markdown=plan_markdown,
            callout=plan.plan_callout(adopt_from),
            command=f"perk impl {adopt_from}",
        )

    if adopt_ref is not None:
        # The human issue IS the plan issue now (an in-place additive stamp, so `updated=True`); it
        # carries the `perk:plan` label, added (never replacing) alongside the human's own labels.
        issue = issue_backend.IssueRef(id=adopt_ref.id, url=adopt_ref.url, existed=True)
        updated = True
        labels: tuple[str, ...] = (plan.PLAN_LABEL,)
    elif unified_ref is not None:
        # Project-backed: the node-issue IS the plan issue (an in-place write into an existing
        # issue, so `updated=True`); it carries no perk:plan label (discovered by project
        # membership + the objective-node block).
        issue = issue_backend.IssueRef(id=unified_ref.id, url=unified_ref.url, existed=True)
        updated = True
        labels: tuple[str, ...] = ()
    else:
        backend.ensure_label(
            plan.PLAN_LABEL,
            color=plan.PLAN_LABEL_COLOR,
            description=plan.PLAN_LABEL_DESCRIPTION,
            dry_run=dry_run,
        )
        issue = backend.create_plan_issue(
            title=resolved_title,
            header_fields=header_out,
            run_id=run_id,
            dry_run=dry_run,
        )
        # `create_plan_issue` is idempotent on run_id: a fresh create returns existed=False, a
        # re-save returns the existing issue. On a fresh create we post the plan-body comment; on a
        # re-save we upsert the existing issue in place (PATCH the plan-body comment + the title). A
        # dry run shells nothing. The anti-duplicate guarantee is preserved — never a second issue
        # per run_id.
        updated = False
        if not dry_run:
            if issue.existed:
                # The same-run-id cross-node guard: BEFORE any mutation, a node-linked
                # re-save must not silently retarget another node's plan. Fail closed —
                # zero mutation on refusal.
                if node_linked and node_id is not None:
                    _refuse_cross_node_upsert(backend, issue_id=issue.id, requested_node=node_id)
                backend.update_plan_issue(
                    issue_id=issue.id,
                    title=resolved_title,
                    body_comment=body_comment,
                )
                # `update_plan_issue` rewrites only the plan-body comment + the issue title; it
                # never touches the `plan-header` block. So the planning-time header fields
                # (`objective_id`, `consumed_learn`) that are only written on a fresh create would
                # be silently dropped on any re-save — leaving the canonical header (which
                # `reconstruct_plan_ref` / on-land consume read from) stale. Merge them back via the
                # `update_plan_header` gateway, which is additive (omitted fields are left intact,
                # never clobbering an existing link or the submit-populated branch/pr/
                # lifecycle_stage). A failure surfaces (raises IssueBackendError → `github_error`)
                # — this is the canonical save, where a silent drop is the bug.
                header_fields: dict[str, object] = {}
                if objective_id is not None:
                    header_fields["objective_id"] = objective_id
                if consumed_learn:
                    header_fields["consumed_learn"] = list(consumed_learn)
                if resolved_base is not None:
                    header_fields["base"] = resolved_base
                # The §8.46 layer-identity trio merges back too (additive; a bottom layer's
                # absent predecessor stays unwritten — absent ≡ null at the read boundary).
                if layer_identity is not None:
                    header_fields["objective_node_id"] = layer_identity.objective_node_id
                    header_fields["delivery_lineage"] = layer_identity.delivery_lineage
                    if layer_identity.predecessor_plan_id is not None:
                        header_fields["predecessor_plan_id"] = layer_identity.predecessor_plan_id
                if header_fields:
                    backend.update_plan_header(issue_id=issue.id, fields=header_fields)
                updated = True
            else:
                backend.add_issue_comment(issue_id=issue.id, body=body_comment, dry_run=dry_run)
                # The plan issue body holds only the hidden `plan-header` block, so prepend a
                # visible, copyable `perk impl <id>` callout as the first thing a human sees. The
                # server-assigned id is only known here (post-create). Idempotent on the command
                # string and structurally above the header block, so the submit-time
                # `update_plan_header` rewrite preserves it.
                backend.prepend_plan_callout(
                    issue_id=issue.id,
                    callout=plan.plan_callout(issue.id),
                    command=f"perk impl {issue.id}",
                )
        labels = (plan.PLAN_LABEL,)

    plan_ref = plan.PlanRef(
        provider=backend.backend_id,
        pr_id=issue.id,
        url=issue.url,
        labels=labels,
        objective_id=objective_id,
        consumed_learn=consumed_learn,
        base=resolved_base,
        # The routing field (§8.46): stamped so a launch routes into the parent-aware stacked
        # path; every decision still reconstructs the train fresh.
        delivery_lineage=layer_identity.delivery_lineage if layer_identity else None,
    )
    # Persist the ref as the cache.plan-ref pointer: the next session's
    # reconciliation links it, and `implement` reads it. A dry run writes nothing.
    if not dry_run:
        cache.write_plan_ref(repo_root, plan_ref)

    # Commit the objective-node claim atomically: set the node→plan backlink AND advance
    # `planning → in_progress` in a single write. Fail-loud, non-fatal, idempotent on re-save
    # (the plan already exists — an expected store failure (ObjectiveStoreError) never raises
    # here, mirroring pr_land._reconcile_objective_on_land; a programming error propagates).
    objective_node_result: ObjectiveNodeLink | None = None
    if not dry_run and objective_id and node_id:
        try:
            store.update_objective_node(
                objective_id=str(objective_id).lstrip("#"),
                node_id=node_id,
                status=objective.NodeStatus.IN_PROGRESS,
                pr=f"#{issue.id}",
            )
            objective_node_result = ObjectiveNodeLink(
                linked=True, node=node_id, status="in_progress", error=None
            )
        except ObjectiveStoreError as exc:  # fail-loud, non-fatal: the plan already exists.
            user_output(f"perk plan save: objective node link skipped (non-fatal): {exc}")
            objective_node_result = ObjectiveNodeLink(
                linked=False, node=node_id, status=None, error=str(exc)
            )

    return PlanSaveResult(
        issue=issue,
        plan_ref=plan_ref,
        issue_body=issue_body,
        body_comment=body_comment,
        dry_run=dry_run,
        cached=not dry_run,
        updated=updated,
        objective_node=objective_node_result,
    )


class IssueOut(OutputModel):
    """The serialization boundary of the picked :class:`issue_backend.IssueRef` subset
    (field order load-bearing)."""

    id: str  # opaque string id at every machine boundary (contracts §8.21)
    url: str
    existed: bool  # warm /plan-save surfaces this in details

    @classmethod
    def from_domain(cls, issue: issue_backend.IssueRef) -> "IssueOut":
        return cls(id=issue.id, url=issue.url, existed=issue.existed)


class ObjectiveNodeLinkOut(OutputModel):
    """The serialization boundary of :class:`ObjectiveNodeLink` (field order load-bearing)."""

    linked: bool
    node: str
    status: str | None
    error: str | None

    @classmethod
    def from_domain(cls, link: ObjectiveNodeLink) -> "ObjectiveNodeLinkOut":
        return cls(linked=link.linked, node=link.node, status=link.status, error=link.error)


class PlanSaveOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`PlanSaveResult` (order load-bearing)."""

    success: bool
    error_type: str | None
    message: str | None
    issue: IssueOut
    plan_ref: plan.PlanRefOut
    cached: bool
    updated: bool
    objective_node: ObjectiveNodeLinkOut | None
    dry_run: bool

    @classmethod
    def from_domain(cls, result: PlanSaveResult) -> "PlanSaveOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            issue=IssueOut.from_domain(result.issue),
            plan_ref=plan.PlanRefOut.from_domain(result.plan_ref),
            cached=result.cached,
            updated=result.updated,
            objective_node=None
            if result.objective_node is None
            else ObjectiveNodeLinkOut.from_domain(result.objective_node),
            dry_run=result.dry_run,
        )


def _result_to_dict(result: PlanSaveResult) -> dict[str, object]:
    return PlanSaveOut.from_domain(result).model_dump(mode="json")


def _render_human(result: PlanSaveResult) -> None:
    if result.dry_run:
        user_output(click.style("plan-save --dry-run (no GitHub writes)", dim=True))
        user_output(click.style("── issue body ──", fg="bright_black"))
        user_output(result.issue_body)
        user_output(click.style("── plan-body comment ──", fg="bright_black"))
        user_output(result.body_comment)
        return
    verb = "Updated" if result.issue.existed else "Saved"
    user_output(
        click.style("✓ ", fg="green")
        + f"{verb} plan "
        + click.style(f"#{result.issue.id}", fg="cyan")
        + f" → {result.issue.url}"
    )
    node_link = result.objective_node
    if node_link and node_link.linked:
        user_output(
            click.style(
                f"  ↳ linked objective #{result.plan_ref.objective_id} node "
                f"{node_link.node} (in_progress)",
                dim=True,
            )
        )
