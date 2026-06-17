from dataclasses import dataclass
from pathlib import Path

from perk import objective, plan
from perk.github import _exec, plans

# ===========================================================================
# Objective ops (P2.T9 — objective storage + mechanics; contracts.md §8.4).
#
# Mirrors the plan/learn idempotency + two-step create exactly: REST `gh api`, bodies via file,
# idempotency keyed on the header `run_id` via the LIST endpoint (label-scoped to
# `perk:objective`), the `perk:objective` label created lazily, mutations RAISE / lookups return
# `... | None`. The objective body holds two blocks (`objective-header` + `objective-roadmap`); the
# first comment holds the rendered table (`objective-body`). Status is explicit-only (open #3).
# ===========================================================================


@dataclass(frozen=True)
class ObjectiveIssue:
    """An objective issue. ``existed`` is True when returned by idempotent dedup."""

    number: int
    url: str
    existed: bool


@dataclass(frozen=True)
class ObjectiveState:
    """An objective's observable state: header + roadmap nodes (``perk objective show``)."""

    number: int
    url: str
    title: str
    header: dict[str, object]
    nodes: tuple[objective.ObjectiveNode, ...]


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
    """The result of an ``update_objective_body`` write (the Reconcilable prose splice, P2.T11)."""

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
    )
    header_block = plan.render_metadata_block(objective.OBJECTIVE_HEADER_KEY, header.to_data())
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
    comment_id = plans._post_comment_with_id(
        issue=created.number, body=comment_body, repo_root=repo_root
    )
    update_objective_header(
        number=created.number,
        fields={"objective_comment_id": comment_id},
        repo_root=repo_root,
    )
    return ObjectiveIssue(number=created.number, url=created.url, existed=False)


def get_objective(*, number: int, repo_root: Path) -> ObjectiveState | None:
    """Read an objective issue's state (header + roadmap nodes). ``None`` when absent; raises on
    an infra failure."""
    data = _exec._run_json(
        ["issue", "view", str(number), "--json", "number,title,body,url"],
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
    """Reconcile the objective-body comment's Reconcilable prose region (P2.T11).

    Reads the issue body's ``objective-header`` for ``objective_comment_id``, fetches the
    ``objective-body`` comment, splices ``prose`` between the Reconcilable markers (the Mechanical
    table block and any Immutable notes are untouched — structurally enforced by
    :func:`objective.replace_reconcilable_section`), and PATCHes the comment.

    Raises ``GitHubError`` when the objective has no body comment or the comment lacks the
    Reconcilable region (objectives created before P2.T11). A dry run composes only (no PATCH).
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
