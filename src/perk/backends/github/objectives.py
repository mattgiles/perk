from dataclasses import dataclass
from pathlib import Path

from perk import objective, plan
from perk.backends.github import plans
from perk.github import _exec
from perk.substrate.output import user_output

# ===========================================================================
# Objective ops (objective storage + mechanics; contracts.md §8.4).
#
# Mirrors the plan/learn idempotency + two-step create exactly: REST `gh api`, bodies via file,
# idempotency keyed on the header `run_id` via the LIST endpoint (label-scoped to
# `perk:objective`), the `perk:objective` label created lazily, mutations RAISE / lookups return
# `... | None`. The objective body holds two blocks (`objective-header` + `objective-roadmap`); the
# first comment holds the rendered table (`objective-body`). Status is explicit-only.
# ===========================================================================


@dataclass(frozen=True)
class ObjectiveIssue:
    """An objective issue. ``existed`` is True when returned by idempotent dedup."""

    number: int
    url: str
    existed: bool


@dataclass(frozen=True)
class ObjectiveState:
    """An objective's observable state: header + roadmap nodes (``perk objective show``).
    ``state`` is the issue's lifecycle read (``"open"``/``"closed"``, normalized from GitHub's
    uppercase vocabulary; defaulted open for direct construction)."""

    number: int
    url: str
    title: str
    header: dict[str, object]
    nodes: tuple[objective.ObjectiveNode, ...]
    state: str = "open"


@dataclass(frozen=True)
class ObjectiveHeaderUpdate:
    """The result of a staged ``objective-header`` field write."""

    fields_updated: tuple[str, ...]
    dry_run: bool


@dataclass(frozen=True)
class ObjectiveNodeUpdate:
    """The result of an ``update_objective_node`` write (body + comment both re-rendered)."""

    number: int
    node_id: str
    comment_updated: bool
    dry_run: bool


@dataclass(frozen=True)
class ObjectiveBodyUpdate:
    """The result of an ``update_objective_body`` write (the Reconcilable prose splice)."""

    number: int
    comment_id: int | None
    updated: bool
    dry_run: bool


@dataclass(frozen=True)
class ObjectiveNodeAdd:
    """The result of an ``add_objective_node`` write (a new roadmap node inserted)."""

    number: int
    node_id: str
    comment_updated: bool
    dry_run: bool


@dataclass(frozen=True)
class ObjectiveAdoption:
    """The result of an in-place :func:`adopt_issue_as_objective` stamp (§8.30)."""

    number: int
    url: str
    existed: bool
    dry_run: bool


def find_objective_issue(*, run_id: str, repo_root: Path) -> ObjectiveIssue | None:
    """Find an open ``perk:objective`` issue whose ``objective-header`` ``run_id`` matches.

    The label-scoped twin of ``find_plan_issue`` (delegates to the parameterized finder); returns
    None for no match, raises on an infra failure.
    """
    found = plans.find_plan_issue(
        run_id=run_id,
        repo_root=repo_root,
        label=objective.OBJECTIVE_LABEL,
        header_key=objective.OBJECTIVE_HEADER_KEY,
    )
    if found is None:
        return None
    return ObjectiveIssue(number=found.number, url=found.url, existed=True)


def create_objective_issue(
    *,
    title: str,
    body: str,
    repo_root: Path,
    run_id: str,
    status: str = "active",
    base: str | None = None,
    roadmap_nodes: list[objective.ObjectiveNode] | None = None,
    supersedes: str | None = None,
    delivery: str | None = None,
    delivery_lineage: str | None = None,
    dry_run: bool = False,
) -> ObjectiveIssue:
    """Create the ``perk:objective`` issue (the two-step create). ``body`` is the authored
    objective markdown (prose). The roadmap comes from ``roadmap_nodes`` when given (the
    structured path — the agent never hand-writes roadmap YAML); otherwise any roadmap embedded
    in ``body`` is parsed from it (the legacy cold-CLI path). Idempotent on ``run_id``; raises
    ``GitHubError`` on failure.

    Steps: (1) idempotency check; (2) lazily create the ``perk:objective`` label; (3) compose the
    issue body = ``objective-header`` (``objective_comment_id: null``) + ``objective-roadmap``
    blocks; (4) POST the issue; (5) post the ``objective-body`` comment (rendered table + prose),
    capturing its id; (6) backfill ``objective_comment_id`` into the header.

    ``delivery``/``delivery_lineage`` compose into the INITIAL header (atomic — never a
    create-then-merge, which could crash between writes and persist a stacked-reviewed
    objective as incremental); ``None`` renders byte-identically to before (§8.42).
    """
    if dry_run:
        return ObjectiveIssue(number=0, url="(dry-run)", existed=False)

    existing = find_objective_issue(run_id=run_id, repo_root=repo_root)
    if existing is not None:
        return existing

    if roadmap_nodes is None:
        nodes, errors = objective.parse_roadmap_nodes(body)
        if errors:
            raise _exec.GitHubError("invalid objective roadmap: " + "; ".join(errors))
    else:
        nodes = list(roadmap_nodes)

    # Storage backstop: no surface may store a node-less objective. Placed after the dedup
    # short-circuit (idempotent re-lookups unaffected) and the dry-run early-return (a no-op),
    # before any label/issue write.
    if not nodes:
        raise _exec.GitHubError("objective roadmap is empty: an objective needs at least one node")

    plans.create_label(
        objective.OBJECTIVE_LABEL,
        color=objective.OBJECTIVE_LABEL_COLOR,
        description=objective.OBJECTIVE_LABEL_DESCRIPTION,
        repo_root=repo_root,
    )

    header = objective.ObjectiveHeader(
        run_id=run_id,
        created=plan.now_iso(),
        objective_comment_id=None,
        status=status,
        base=base,
        supersedes=supersedes,
        delivery=delivery,
        delivery_lineage=delivery_lineage,
    )
    header_block = plan.render_metadata_block(
        objective.OBJECTIVE_HEADER_KEY, objective.render_header_block(header)
    )
    roadmap_block = plan.render_metadata_block(
        objective.OBJECTIVE_ROADMAP_KEY, objective.render_roadmap_block(nodes)
    )
    issue_body = f"{header_block}\n\n{roadmap_block}\n"

    created = plans.create_plan_issue(
        title=title,
        body=issue_body,
        repo_root=repo_root,
        run_id=None,  # idempotency already handled above
        labels=(objective.OBJECTIVE_LABEL,),
    )

    comment_body = objective.render_body_comment(nodes, prose=body.strip())
    # Prepend a visible, copyable `perk objective plan <number>` callout above the rendered table
    # (the issue number is server-assigned and known here). The reconcile / table-rerender helpers
    # splice between markers only, so the callout is durable.
    comment_body = plan.prepend_callout(
        comment_body,
        objective.objective_callout(str(created.number)),
        command=f"perk objective plan {created.number}",
    )
    comment_id = plans._post_comment_with_id(
        issue=created.number, body=comment_body, repo_root=repo_root
    )
    update_objective_header(
        number=created.number,
        fields={"objective_comment_id": comment_id},
        repo_root=repo_root,
    )
    return ObjectiveIssue(number=created.number, url=created.url, existed=False)


def adopt_issue_as_objective(
    *,
    number: int,
    title: str,
    prose: str,
    repo_root: Path,
    run_id: str,
    status: str = "active",
    base: str | None = None,
    roadmap_nodes: list[objective.ObjectiveNode],
    dry_run: bool = False,
) -> ObjectiveAdoption:
    """Additively stamp perk objective metadata INTO a pre-existing GitHub issue — adopting it in
    place as a perk objective (§8.30), never minting a second issue.

    Mirrors :func:`create_objective_issue` + :func:`perk.github.adopt_issue_as_plan`. The bounded
    single-issue path (GitHub objectives have no child issues, so the node → issue ``adopt_map`` is
    not applicable here; the roadmap is authored fresh). The additive stamp: (a) idempotency via
    ``find_objective_issue(run_id=)``; (b) ensure + ADD the ``perk:objective`` label (never
    replaces the issue's labels); (c) read the issue's CURRENT body verbatim (the human prose),
    compose ``<human body verbatim>`` + the ``objective-header`` block (``adopted_from="#<n>"``,
    ``objective_comment_id: null``) + the ``objective-roadmap`` block, PATCH the body (title
    untouched); (d) post the ``objective-body`` comment — ``render_body_comment(nodes, prose=<model
    prose>)`` + the ``render_adopted_overview_note(<original human body>)`` appended below the
    Reconcilable markers (Immutable) + the ``perk objective plan <number>`` callout prepended — and
    backfill ``objective_comment_id``. Raises ``GitHubError`` on an infra failure; ``dry_run`` reads
    nothing and returns early. An empty ``roadmap_nodes`` raises (the storage backstop).
    """
    if dry_run:
        return ObjectiveAdoption(number=number, url="(dry-run)", existed=False, dry_run=True)

    existing = find_objective_issue(run_id=run_id, repo_root=repo_root)
    if existing is not None:
        return ObjectiveAdoption(
            number=existing.number, url=existing.url, existed=True, dry_run=False
        )

    nodes = list(roadmap_nodes)
    if not nodes:
        raise _exec.GitHubError("objective roadmap is empty: an objective needs at least one node")

    src = plans.read_issue(number=number, repo_root=repo_root)
    if src is None:
        raise _exec.GitHubError(f"issue #{number} not found")
    # Wrong-kind writer guard (presence-only, before any mutation): a plan carrier is never
    # adoptable as an objective — a gist carries `gist-header`, so gist adoption is exempt.
    if plan.has_metadata_block(src.body, plan.PLAN_HEADER_KEY):
        raise _exec.GitHubError(
            f"issue #{number} carries a plan-header — wrong kind for objective adoption"
        )

    # (b) ensure + additively add the perk:objective label (never replaces the issue's labels).
    plans.create_label(
        objective.OBJECTIVE_LABEL,
        color=objective.OBJECTIVE_LABEL_COLOR,
        description=objective.OBJECTIVE_LABEL_DESCRIPTION,
        repo_root=repo_root,
    )
    plans.add_issue_label(issue=number, label=objective.OBJECTIVE_LABEL, repo_root=repo_root)

    # (c) stamp the header + roadmap blocks additively into the issue body (human body verbatim,
    # title untouched). The original human body is the verbatim archive source for the body comment.
    original_body = plans._get_issue_body(number, repo_root)
    header = objective.ObjectiveHeader(
        run_id=run_id,
        created=plan.now_iso(),
        objective_comment_id=None,
        status=status,
        base=base,
        adopted_from=objective.canonical_pr(number),
    )
    header_block = plan.render_metadata_block(
        objective.OBJECTIVE_HEADER_KEY, objective.render_header_block(header)
    )
    roadmap_block = plan.render_metadata_block(
        objective.OBJECTIVE_ROADMAP_KEY, objective.render_roadmap_block(nodes)
    )
    new_body = f"{original_body.rstrip()}\n\n{header_block}\n\n{roadmap_block}\n"
    with _exec._body_file(new_body) as body_path:
        proc = _exec._run(
            _exec._rest_args(
                f"repos/{{owner}}/{{repo}}/issues/{number}", method="PATCH", body_path=body_path
            ),
            cwd=repo_root,
            timeout=_exec._WRITE_TIMEOUT,
        )
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to stamp objective-header on #{number}")

    # (d) post the objective-body comment: rendered table + MODEL prose, then the verbatim
    # `Adopted-from` Immutable archive note appended below the Reconcilable markers, then the
    # copyable callout prepended. Backfill objective_comment_id into the header.
    comment_body = objective.render_body_comment(nodes, prose=prose.strip())
    archive_note = objective.render_adopted_overview_note(original_body)
    if archive_note:
        comment_body = f"{comment_body.rstrip()}\n\n{archive_note}\n"
    comment_body = plan.prepend_callout(
        comment_body,
        objective.objective_callout(str(number)),
        command=f"perk objective plan {number}",
    )
    comment_id = plans._post_comment_with_id(issue=number, body=comment_body, repo_root=repo_root)
    update_objective_header(
        number=number,
        fields={"objective_comment_id": comment_id},
        repo_root=repo_root,
    )
    return ObjectiveAdoption(number=number, url=src.url, existed=False, dry_run=False)


def supersede_objective_issue(
    *,
    old_number: int,
    title: str,
    prose: str,
    repo_root: Path,
    run_id: str,
    status: str = "active",
    base: str | None = None,
    roadmap_nodes: list[objective.ObjectiveNode],
    delivery: str | None = None,
    delivery_lineage: str | None = None,
    close_predecessor: bool = True,
    dry_run: bool = False,
) -> ObjectiveIssue:
    """Create a net-new ``perk:objective`` issue that supersedes ``old_number`` (the GitHub arm
    of the supersede model).

    Idempotent on ``run_id``. Under ``close_predecessor=True`` (the incremental §8.32 path) a
    find-by-``run_id`` hit is today's early return (no re-close); otherwise: (1) create the new
    objective issue exactly as :func:`create_objective_issue`, carrying ``supersedes=#<old>`` in
    its header; (2) close the old issue **fail-open** via :func:`finalize_supersession_issue`
    — a failure there is logged loud-but-non-fatal and never raised after the new issue exists.

    ``close_predecessor=False`` is the transfer protocol's deferred-close arm (§8.53): the
    create runs WITHOUT any old-side stamp/close (those move to
    :func:`finalize_supersession_issue`, called only after the successor projection verifies),
    and the found-by-``run_id`` arm is **convergent**: it verifies + completes the subordinate
    creation writes — a null header ``objective_comment_id`` (or a vanished objective-body
    comment) first discovers any already-posted marker-bearing comment, then reuses it or posts
    the comment from the supplied prose and backfills the header. (The issue POST itself carries
    the run-id header atomically, so the first GitHub effect is always run-id-discoverable.)

    ``carry_map`` is not applicable (GitHub objectives have no child issues — carried nodes are
    authored fresh rows). ``dry_run`` returns early; an empty ``roadmap_nodes`` raises (the
    storage backstop)."""
    if dry_run:
        return ObjectiveIssue(number=0, url="(dry-run)", existed=False)

    existing = find_objective_issue(run_id=run_id, repo_root=repo_root)
    if existing is not None:
        if not close_predecessor:
            _converge_objective_subordinates(
                number=existing.number,
                prose=prose,
                roadmap_nodes=roadmap_nodes,
                repo_root=repo_root,
            )
        return existing

    if not list(roadmap_nodes):
        raise _exec.GitHubError("objective roadmap is empty: an objective needs at least one node")

    created = create_objective_issue(
        title=title,
        body=prose,
        repo_root=repo_root,
        run_id=run_id,
        status=status,
        base=base,
        roadmap_nodes=roadmap_nodes,
        supersedes=objective.canonical_pr(old_number),
        delivery=delivery,
        delivery_lineage=delivery_lineage,
    )

    if close_predecessor:
        # Close the old objective LAST, fail-open: one implementation, two postures — the
        # raising finalize wrapped so a failure here never fails the create (the new objective
        # already exists; the bookkeeping posture).
        try:
            finalize_supersession_issue(
                old_number=old_number, new_number=created.number, repo_root=repo_root
            )
        except _exec.GitHubError as exc:
            user_output(
                f"perk objective replan: closing superseded objective #{old_number} skipped "
                f"(non-fatal): {exc}"
            )
    return created


def _converge_objective_subordinates(
    *,
    number: int,
    prose: str,
    roadmap_nodes: list[objective.ObjectiveNode],
    repo_root: Path,
) -> None:
    """The deferred-close found-arm's convergent materialization (§8.53): verify and complete
    the two-step create's subordinate writes on an already-found objective issue.

    The issue POST is atomic (header incl. ``run_id`` + roadmap), so the only healable window
    is the objective-body comment + the ``objective_comment_id`` backfill. A resolvable recorded
    comment converges as a no-op. Otherwise the found-arm lists comments for the objective-body
    marker before posting: this recovers the exact post-succeeded/backfill-failed window without
    creating a duplicate. Only when no marker-bearing comment exists does it compose and post a
    replacement, then backfill the discovered or fresh id.
    """
    body = plans._get_issue_body(number, repo_root)
    header = plan.find_metadata_block(body, objective.OBJECTIVE_HEADER_KEY) or {}
    comment_id = header.get("objective_comment_id")
    if isinstance(comment_id, int) and plans._get_comment_body(comment_id, repo_root) is not None:
        return

    recovered_comment_id = plans.find_comment_id_by_marker(
        issue=number,
        marker=objective.ROADMAP_TABLE_MARKER_START,
        repo_root=repo_root,
    )
    if recovered_comment_id is None:
        comment_body = objective.render_body_comment(list(roadmap_nodes), prose=prose.strip())
        comment_body = plan.prepend_callout(
            comment_body,
            objective.objective_callout(str(number)),
            command=f"perk objective plan {number}",
        )
        recovered_comment_id = plans._post_comment_with_id(
            issue=number, body=comment_body, repo_root=repo_root
        )
    update_objective_header(
        number=number,
        fields={"objective_comment_id": recovered_comment_id},
        repo_root=repo_root,
    )


def finalize_supersession_issue(*, old_number: int, new_number: int, repo_root: Path) -> None:
    """The extracted close side of the supersede model (§8.53's deferred close) — **raising**
    and **idempotent**: stamp ``superseded_by=#<new>`` into the old header (skipped when the
    stamp is already present — a conflicting existing stamp raises), then close the old issue
    (``plans.close_issue`` is idempotent on an already-closed issue). GitHub has no status-
    update surface, so the best-effort update is a structural no-op here."""
    body = plans._get_issue_body(old_number, repo_root)
    header = plan.find_metadata_block(body, objective.OBJECTIVE_HEADER_KEY) or {}
    stamped = header.get("superseded_by")
    expected = objective.canonical_pr(new_number)
    if stamped is None:
        update_objective_header(
            number=old_number,
            fields={"superseded_by": expected},
            repo_root=repo_root,
        )
    elif stamped != expected:
        raise _exec.GitHubError(
            f"objective #{old_number} is already superseded by {stamped!r} — refusing to "
            f"re-stamp it as {expected!r}"
        )
    plans.close_issue(number=old_number, repo_root=repo_root)


def get_objective(*, number: int, repo_root: Path) -> ObjectiveState | None:
    """Read an objective issue's state (header + roadmap nodes). ``None`` when absent; raises on
    an infra failure."""
    data = _exec._run_json(
        ["issue", "view", str(number), "--json", "number,title,body,url,state"],
        what=f"failed to read objective issue #{number}",
        source="`gh issue view`",
        cwd=repo_root,
        none_on_not_found=True,
    )
    if data is None:
        return None
    body = str(data.get("body", ""))
    header = plan.find_metadata_block(body, objective.OBJECTIVE_HEADER_KEY) or {}
    nodes, errors = objective.parse_roadmap_nodes(body)
    if errors:
        raise _exec.GitHubError(f"invalid objective roadmap on #{number}: " + "; ".join(errors))
    return ObjectiveState(
        number=int(data["number"]) if "number" in data else number,
        url=str(data.get("url", "")),
        title=str(data.get("title", "")),
        header=header,
        nodes=tuple(nodes),
        # gh reports uppercase OPEN/CLOSED; only a positive CLOSED reads closed (fail-open).
        state="closed" if str(data.get("state", "")).upper() == "CLOSED" else "open",
    )


def update_objective_header(
    *, number: int, fields: dict[str, object], repo_root: Path, dry_run: bool = False
) -> ObjectiveHeaderUpdate:
    """Merge ``fields`` into the issue body's ``objective-header`` block and PATCH it (REST).

    Rejects unknown header keys (LBYL). A dry run validates + composes only.
    """
    unknown = set(fields) - objective.OBJECTIVE_HEADER_FIELDS
    if unknown:
        raise _exec.GitHubError(f"unknown objective-header field(s): {sorted(unknown)}")
    body = plans._get_issue_body(number, repo_root)
    header = plan.find_metadata_block(body, objective.OBJECTIVE_HEADER_KEY) or {}
    new_body = plan.replace_metadata_block(
        body, objective.OBJECTIVE_HEADER_KEY, {**header, **fields}
    )
    if dry_run:
        return ObjectiveHeaderUpdate(fields_updated=tuple(fields), dry_run=True)
    with _exec._body_file(new_body) as body_path:
        proc = _exec._run(
            _exec._rest_args(
                f"repos/{{owner}}/{{repo}}/issues/{number}", method="PATCH", body_path=body_path
            ),
            cwd=repo_root,
            timeout=_exec._WRITE_TIMEOUT,
        )
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to update objective-header on #{number}")
    return ObjectiveHeaderUpdate(fields_updated=tuple(fields), dry_run=False)


def update_objective_node(
    *,
    number: int,
    node_id: str,
    status: objective.NodeStatus | None = None,
    pr: str | None = None,
    description: str | None = None,
    repo_root: Path,
    dry_run: bool = False,
) -> ObjectiveNodeUpdate:
    """Update one roadmap node (explicit-status-only): re-render the ``objective-roadmap`` block
    in the issue body (authoritative) AND the rendered table in the ``objective-body`` comment.

    Raises ``GitHubError`` if the node is not found or the roadmap is invalid; the comment
    re-render is best-effort (the frontmatter is the source of truth).
    """
    body = plans._get_issue_body(number, repo_root)
    nodes, errors = objective.parse_roadmap_nodes(body)
    if errors:
        raise _exec.GitHubError("invalid objective roadmap: " + "; ".join(errors))
    updated = objective.update_node(nodes, node_id, status=status, pr=pr, description=description)
    if updated is None:
        raise _exec.GitHubError(f"objective node {node_id!r} not found on #{number}")
    if dry_run:
        return ObjectiveNodeUpdate(
            number=number, node_id=node_id, comment_updated=False, dry_run=True
        )

    new_body = plan.replace_metadata_block(
        body, objective.OBJECTIVE_ROADMAP_KEY, objective.render_roadmap_block(updated)
    )
    with _exec._body_file(new_body) as body_path:
        proc = _exec._run(
            _exec._rest_args(
                f"repos/{{owner}}/{{repo}}/issues/{number}", method="PATCH", body_path=body_path
            ),
            cwd=repo_root,
            timeout=_exec._WRITE_TIMEOUT,
        )
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to update objective roadmap on #{number}")

    comment_updated = False
    header = plan.find_metadata_block(new_body, objective.OBJECTIVE_HEADER_KEY) or {}
    comment_id = header.get("objective_comment_id")
    if isinstance(comment_id, int):
        comment_body = plans._get_comment_body(comment_id, repo_root)
        if comment_body is not None:
            rerendered = objective.rerender_body_table(comment_body, updated)
            if rerendered is not None:
                plans._patch_comment_body(comment_id, rerendered, repo_root)
                comment_updated = True
    return ObjectiveNodeUpdate(
        number=number, node_id=node_id, comment_updated=comment_updated, dry_run=False
    )


def add_objective_node(
    *,
    number: int,
    phase: int,
    description: str,
    status: objective.NodeStatus = objective.NodeStatus.PENDING,
    slug: str | None = None,
    depends_on: tuple[str, ...] | None = None,
    comment: str | None = None,
    repo_root: Path,
    dry_run: bool = False,
) -> ObjectiveNodeAdd:
    """Insert a new node into ``phase`` (auto-assigned ``<phase>.<n>``, appended after that phase's
    last node): re-render the ``objective-roadmap`` block in the issue body (authoritative) AND the
    rendered table in the ``objective-body`` comment.

    Raises ``GitHubError`` if the roadmap is invalid or the auto-assigned id collides; the comment
    re-render is best-effort (the frontmatter is the source of truth).
    """
    body = plans._get_issue_body(number, repo_root)
    nodes, errors = objective.parse_roadmap_nodes(body)
    if errors:
        raise _exec.GitHubError("invalid objective roadmap: " + "; ".join(errors))
    result = objective.add_node(
        nodes,
        phase=phase,
        description=description,
        status=status,
        slug=slug,
        depends_on=depends_on,
        comment=comment,
    )
    if result is None:
        raise _exec.GitHubError(f"could not add node to phase {phase} on #{number} (id collision)")
    updated, new_id = result
    if dry_run:
        return ObjectiveNodeAdd(number=number, node_id=new_id, comment_updated=False, dry_run=True)

    new_body = plan.replace_metadata_block(
        body, objective.OBJECTIVE_ROADMAP_KEY, objective.render_roadmap_block(updated)
    )
    with _exec._body_file(new_body) as body_path:
        proc = _exec._run(
            _exec._rest_args(
                f"repos/{{owner}}/{{repo}}/issues/{number}", method="PATCH", body_path=body_path
            ),
            cwd=repo_root,
            timeout=_exec._WRITE_TIMEOUT,
        )
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to add objective roadmap node on #{number}")

    comment_updated = False
    header = plan.find_metadata_block(new_body, objective.OBJECTIVE_HEADER_KEY) or {}
    comment_id = header.get("objective_comment_id")
    if isinstance(comment_id, int):
        comment_body = plans._get_comment_body(comment_id, repo_root)
        if comment_body is not None:
            rerendered = objective.rerender_body_table(comment_body, updated)
            if rerendered is not None:
                plans._patch_comment_body(comment_id, rerendered, repo_root)
                comment_updated = True
    return ObjectiveNodeAdd(
        number=number, node_id=new_id, comment_updated=comment_updated, dry_run=False
    )


def update_objective_body(
    *, number: int, prose: str, repo_root: Path, dry_run: bool = False
) -> ObjectiveBodyUpdate:
    """Reconcile the objective-body comment's Reconcilable prose region.

    Reads the issue body's ``objective-header`` for ``objective_comment_id``, fetches the
    ``objective-body`` comment, splices ``prose`` between the Reconcilable markers (the Mechanical
    table block and any Immutable notes are untouched — structurally enforced by
    :func:`objective.replace_reconcilable_section`), and PATCHes the comment.

    Raises ``GitHubError`` when the objective has no body comment or the comment lacks the
    Reconcilable region (legacy objectives lacking it). A dry run composes only (no PATCH).
    """
    body = plans._get_issue_body(number, repo_root)
    header = plan.find_metadata_block(body, objective.OBJECTIVE_HEADER_KEY) or {}
    comment_id = header.get("objective_comment_id")
    if not isinstance(comment_id, int):
        raise _exec.GitHubError(f"objective #{number} has no body comment")
    comment_body = plans._get_comment_body(comment_id, repo_root)
    if comment_body is None:
        raise _exec.GitHubError(f"objective #{number} has no body comment")
    spliced = objective.replace_reconcilable_section(comment_body, prose)
    if spliced is None:
        raise _exec.GitHubError(f"objective #{number} body comment has no reconcilable region")
    if dry_run:
        return ObjectiveBodyUpdate(
            number=number, comment_id=comment_id, updated=False, dry_run=True
        )
    plans._patch_comment_body(comment_id, spliced, repo_root)
    return ObjectiveBodyUpdate(number=number, comment_id=comment_id, updated=True, dry_run=False)
