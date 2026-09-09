"""``perk objective node-engagement <NUMBER> --node ID [--json]`` — read one roadmap node's
advisory DATA: its pre-planning human engagement plus its saved refinement (§8.26).

The **warm path's fetch surface** + a human/CI affordance over the shared selected-node
assembly (:mod:`perk.cli.commands.objective.node_context`). The two advisory reads are
independent and each typed on its own outcome: the bounded engagement block (``present`` /
``absent`` / ``unavailable``) and the full dated ``<untrusted_node_refinement>`` block
(``present`` / ``absent`` / ``unsupported`` / ``unavailable``). A present refinement is written
under the run's scratch dir (``$PERK_RUN_ID`` or a minted run id — the ``pr review-context``
rule; a launched session's bash inherits the live run id) and the payload carries a pointer
``{path, bytes, lines, max_line_bytes}`` — never the inline text, whose full body can exceed
what a model's ``read`` tool accepts. Nothing is written for the other arms.

Authoritative failures stay hard (not a repo, invalid input, store resolution/lookup, an unknown
node → ``node_not_found``); advisory failures are **partial success** — exit 0 with typed
``warnings``. Read-only against the backend (a read worker, never a mutation affordance); its
only write is the gitignored scratch file.

Linear-first: GitHub single-issue objectives + the dormant issue-backed Linear store report the
refinement as ``unsupported`` quietly and the engagement as ``absent`` (their engagement read
returns the empty bundle).

Supervisor surface: ``--json`` → stdout machine payload, human text → stderr,
stable exits (``0`` ok · ``1`` invalid/op-failure · ``2`` not-a-repo).
"""

import functools
import os
from typing import Annotated, Literal

import click
from pydantic import Field

from perk.backends import resolve
from perk.backends.engagement import (
    AuthorKind,
    DescriptionEdit,
    EngagementAuthor,
    EngagementComment,
)
from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import ObjectiveStoreError
from perk.boundary import OutputModel
from perk.cli import completions
from perk.cli.commands.objective.node_context import (
    EngagementStatus,
    NodeContext,
    NodeContextWarning,
    RefinementMissing,
    RefinementSnapshotted,
    SnapshotRefinement,
    WarningSurface,
    assemble_node_context,
    snapshot_refinement,
)
from perk.cli.commands.objective.shared import parse_objective_id
from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.cli.paged_files import TextFileRefOut
from perk.state import run_id as run_id_mod
from perk.substrate.output import user_output


@click.command("node-engagement")
@click.argument("number", shell_complete=completions.complete_objective_id)
@click.option("--node", "node_id", required=True, help="The roadmap node id (e.g. 2.3).")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def node_engagement_objective(
    ctx: click.Context, *, number: str, node_id: str, as_json: bool
) -> None:
    """Read a roadmap node's advisory DATA: pre-planning human engagement + saved refinement.

    \b
    Examples:
      perk objective node-engagement 7 --node 2.1          # rendered untrusted-DATA blocks (stderr)
      perk objective node-engagement 7 --node 2.1 --json   # machine payload (stdout)
    """
    try:
        repo_root = require_repo(ctx)
        number = parse_objective_id(number)
        node_id = node_id.strip()
        if not node_id:
            raise UserFacingCliError("--node must not be blank.", error_type="invalid_input")
        try:
            store = resolve.resolve_objective_store(repo_root)
            state = store.get_objective(objective_id=number)
        except (ObjectiveStoreError, IssueBackendError) as exc:
            # The worker's store-failure vocabulary; the IssueBackendError arm covers a bad
            # ``[issues]`` selection surfacing from the resolver.
            fail(ctx, as_json=as_json, error_type="github_error", message=str(exc))
            return
        if state is None:
            raise UserFacingCliError(
                f"Objective #{number} not found", error_type="objective_not_found"
            )
        if node_id not in {node.id for node in state.nodes}:
            raise UserFacingCliError(
                f"Node {node_id!r} not found on objective #{number}.",
                error_type="node_not_found",
            )
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    # Advisory from here on: failures become warnings, never a non-zero exit. The snapshot is
    # a no-op (no I/O) unless a refinement is present.
    context = snapshot_refinement(
        assemble_node_context(
            store,
            objective_id=number,
            node_id=node_id,
            issues=functools.partial(resolve.resolve_issue_backend, repo_root),
        ),
        repo_root=repo_root,
        run_id=os.environ.get("PERK_RUN_ID") or run_id_mod.mint(),
    )

    emit(
        as_json=as_json,
        payload=ObjectiveNodeEngagementOut.from_domain(context).model_dump(mode="json"),
        render=lambda: _render_human(context),
    )


def _render_human(context: NodeContext[SnapshotRefinement]) -> None:
    if context.engagement_block is not None:
        user_output(context.engagement_block)
    else:
        user_output(f"no pre-planning engagement on node {context.node_id}")
    match context.refinement:
        case RefinementSnapshotted(block=block, file=file):
            user_output(block)
            user_output(f"refinement: {file.path}")
        case RefinementMissing(status=status):
            user_output(f"refinement: {status}")
    for warning in context.warnings:
        user_output(f"warning: [{warning.surface}/{warning.code}] {warning.message}")


# --------------------------------------------------------------------------- --json boundary
# Field order is load-bearing. The engagement models mirror the ``engagement.py`` dataclasses
# field-for-field so the ``comments`` / ``description_edits`` arrays serialize exactly as the
# earlier ``dataclasses.asdict`` payload did.


class EngagementAuthorOut(OutputModel):
    """The classified author of one engagement item (``kind`` + best-available label/id)."""

    kind: AuthorKind
    display_name: str | None
    id: str | None

    @classmethod
    def from_domain(cls, author: EngagementAuthor) -> "EngagementAuthorOut":
        return cls(kind=author.kind, display_name=author.display_name, id=author.id)


class EngagementCommentOut(OutputModel):
    """One node-issue comment; ``body`` is untrusted DATA."""

    id: str
    body: str
    created_at: str
    edited_at: str | None
    author: EngagementAuthorOut

    @classmethod
    def from_domain(cls, comment: EngagementComment) -> "EngagementCommentOut":
        return cls(
            id=comment.id,
            body=comment.body,
            created_at=comment.created_at,
            edited_at=comment.edited_at,
            author=EngagementAuthorOut.from_domain(comment.author),
        )


class DescriptionEditOut(OutputModel):
    """One node-issue description edit; ``diff`` is untrusted DATA (null when the backend
    exposes no inline diff)."""

    created_at: str
    author: EngagementAuthorOut
    diff: str | None

    @classmethod
    def from_domain(cls, edit: DescriptionEdit) -> "DescriptionEditOut":
        return cls(
            created_at=edit.created_at,
            author=EngagementAuthorOut.from_domain(edit.author),
            diff=edit.diff,
        )


class NodeContextWarningOut(OutputModel):
    """One advisory failure: the ``surface`` that failed, a stable ``code``, a human
    ``message``, and the carrier comment ids the outcome rests on."""

    surface: WarningSurface
    code: str
    message: str
    comment_ids: tuple[str, ...]

    @classmethod
    def from_domain(cls, warning: NodeContextWarning) -> "NodeContextWarningOut":
        return cls(
            surface=warning.surface,
            code=warning.code,
            message=warning.message,
            comment_ids=warning.comment_ids,
        )


class NodeRefinementPresentOut(OutputModel):
    """A saved refinement was read, rendered and written: ``file`` points at the full dated
    ``<untrusted_node_refinement>`` block under the run scratch dir."""

    status: Literal["present"]
    file: TextFileRefOut


class NodeRefinementStatusOut(OutputModel):
    """No refinement pointer: none is saved (``absent``), the backend has no refinement read
    (``unsupported``), or the read/snapshot failed (``unavailable`` — see ``warnings``)."""

    status: Literal["absent", "unsupported", "unavailable"]


class ObjectiveNodeEngagementOut(OutputModel):
    """The ``--json`` serialization boundary of a snapshotted :class:`NodeContext` (field order
    load-bearing; the pre-existing keys come first). ``refinement`` is discriminated on
    ``status``: ``present`` always carries a ``file`` pointer — the file is on disk."""

    success: bool
    error_type: str | None
    objective: str
    node: str
    comments: tuple[EngagementCommentOut, ...]
    description_edits: tuple[DescriptionEditOut, ...]
    engagement_status: EngagementStatus
    refinement: Annotated[
        NodeRefinementPresentOut | NodeRefinementStatusOut, Field(discriminator="status")
    ]
    warnings: tuple[NodeContextWarningOut, ...]

    @classmethod
    def from_domain(cls, context: NodeContext[SnapshotRefinement]) -> "ObjectiveNodeEngagementOut":
        """Only a snapshotted context is a wire state (the phase type forbids an assembled-only
        present refinement statically; the ``TypeError`` backstops untyped callers)."""
        refinement: NodeRefinementPresentOut | NodeRefinementStatusOut
        match context.refinement:
            case RefinementSnapshotted(file=file):
                refinement = NodeRefinementPresentOut(
                    status="present", file=TextFileRefOut.from_domain(file)
                )
            case RefinementMissing(status=status):
                refinement = NodeRefinementStatusOut(status=status)
            case other:
                raise TypeError(
                    f"a present refinement must be snapshotted before serialization, got {other!r}"
                )
        return cls(
            success=True,
            error_type=None,
            objective=context.objective_id,
            node=context.node_id,
            comments=tuple(
                EngagementCommentOut.from_domain(c) for c in context.engagement.comments
            ),
            description_edits=tuple(
                DescriptionEditOut.from_domain(e) for e in context.engagement.description_edits
            ),
            engagement_status=context.engagement_status,
            refinement=refinement,
            warnings=tuple(NodeContextWarningOut.from_domain(w) for w in context.warnings),
        )
