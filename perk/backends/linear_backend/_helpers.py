import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

from perk.backends import engagement, issue_backend, objective_store
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import (
    LinearClient,
    LinearGraphQLError,
    _is_entity_not_found,
    _require_str,
)
from perk.backends.objective_store import ObjectiveStoreError

_PAGE_SIZE = 50

# Every perk HTML-comment marker — metadata-block delimiters AND the run-report marker —
# rewritten generically to its inline-code sentinel.
_PERK_MARKER_RE = re.compile(r"<!--\s*(/?perk:[^>]+?)\s*-->")

# The exact perk-rendered `<details>` wrapper shapes (perk.plan's html-style renderers).
_DETAILS_OPEN_RE = re.compile(r"^<details><summary><code>[^<]*</code></summary>$")
_DETAILS_CLOSE = "</details>"

# The best-effort node-status → Linear workflow-state `type` mirror (Node 3.3). The status block
# is the source of truth; this mirror only nudges the node-issue's workflow state to match (so the
# project board reflects the roadmap). `blocked` has no Linear equivalent — mapped to `started`
# (it is in-flight work, just stuck).
_NODE_STATUS_STATE_TYPE: dict[str, str] = {
    "pending": "unstarted",
    "planning": "started",
    "in_progress": "started",
    "done": "completed",
    "blocked": "started",
    "skipped": "canceled",
}


def to_linear_markdown(text: str) -> str:
    """Transcode perk's GitHub-encoded markers into the Linear-safe inline-code encoding.

    Rewrites every perk HTML-comment marker (``<!-- perk:… -->`` / ``<!-- /perk:… -->``) to its
    inline-code sentinel (`` `perk:…` `` / `` `/perk:…` ``) and drops the perk-rendered
    ``<details>`` wrapper lines. Identity for any other text (non-perk markers pass through
    untouched). Pure; applied to every outgoing body/description/comment and every incoming
    ``marker`` argument.
    """
    rewritten = _PERK_MARKER_RE.sub(lambda m: f"`{m.group(1)}`", text)
    lines = [
        line
        for line in rewritten.splitlines()
        if not (_DETAILS_OPEN_RE.match(line) or line == _DETAILS_CLOSE)
    ]
    result = "\n".join(lines)
    if rewritten.endswith("\n"):
        result += "\n"
    return result


def _hex_color(color: str) -> str:
    """Map the GitHub bare-hex label colors into Linear's ``#``-prefixed form."""
    return color if color.startswith("#") else f"#{color}"


# ------------------------------------------------------------------ engagement-read mapping
# Pure mappers from Linear payload nodes into the backend-neutral engagement dataclasses
# (Objective #682, Node 1.2). perk has no committed app-actor id, so perk detection rests on the
# body sentinel; `perk_bot_ids=()` is the honest empty seam.


def _is_present(value: object) -> bool:
    """True when a nullable Linear field is populated — a non-empty dict (single actor) or a
    non-empty list (an actor list, e.g. ``descriptionUpdatedBy``). The shape of
    ``IssueHistory.descriptionUpdatedBy`` is live-unproven (inventory §6.1), so tolerate both."""
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, list):
        return bool(value)
    return False


def _actor_or_none(raw: object, *, prefer_display: bool = False) -> engagement.Actor | None:
    """Map a Linear ``user``/``botActor``/``actor`` selection into a neutral :class:`Actor`, or
    ``None`` when absent. ``prefer_display`` uses ``displayName`` over ``name`` (the ``user``
    field carries both)."""
    if not isinstance(raw, dict):
        return None
    node = cast("dict[str, object]", raw)
    raw_id = node.get("id")
    raw_name = node.get("name")
    name = raw_name if isinstance(raw_name, str) and raw_name else None
    if prefer_display:
        display = node.get("displayName")
        if isinstance(display, str) and display:
            name = display
    return engagement.Actor(id=raw_id if isinstance(raw_id, str) else None, name=name)


def _engagement_comment(node: dict[str, object]) -> engagement.EngagementComment:
    """Map a ``_comments_with_authors`` node into an :class:`EngagementComment` (untrusted body)."""
    body = node.get("body")
    body_text = body if isinstance(body, str) else ""
    edited = node.get("editedAt")
    author = engagement.classify_author(
        body=body_text,
        user=_actor_or_none(node.get("user"), prefer_display=True),
        bot_actor=_actor_or_none(node.get("botActor")),
    )
    return engagement.EngagementComment(
        id=_require_str(node.get("id"), "comment id"),
        body=body_text,
        created_at=_require_str(node.get("createdAt"), "comment createdAt"),
        edited_at=edited if isinstance(edited, str) else None,
        author=author,
    )


def _description_edit(node: dict[str, object]) -> engagement.DescriptionEdit:
    """Map a description-history node into a :class:`DescriptionEdit`. ``diff=None`` (Linear's
    history exposes no inline diff — a flagged deferral); author keyed on the editing ``actor``."""
    author = engagement.classify_author(
        body="", user=_actor_or_none(node.get("actor")), bot_actor=None
    )
    return engagement.DescriptionEdit(
        created_at=_require_str(node.get("createdAt"), "history createdAt"),
        author=author,
        diff=None,
    )


def _agent_activity(node: dict[str, object]) -> engagement.AgentActivity:
    """Map an agent-session activity node into an :class:`AgentActivity`. ``kind`` is the content
    union ``__typename``; ``body`` (untrusted DATA) is the content's body when the variant has
    one."""
    content = node.get("content")
    kind = ""
    body: str | None = None
    if isinstance(content, dict):
        content_dict = cast("dict[str, object]", content)
        typename = content_dict.get("__typename")
        kind = typename if isinstance(typename, str) else ""
        raw_body = content_dict.get("body")
        body = raw_body if isinstance(raw_body, str) else None
    signal = node.get("signal")
    return engagement.AgentActivity(
        id=_require_str(node.get("id"), "activity id"),
        created_at=_require_str(node.get("createdAt"), "activity createdAt"),
        kind=kind,
        body=body,
        signal=signal if isinstance(signal, str) else None,
    )


def _agent_session_read(
    activities: list[engagement.AgentActivity],
) -> engagement.AgentSessionRead:
    """Assemble the :class:`AgentSessionRead`, deriving the stop indicator from the activities:
    ``stopped`` when any activity carried the ``stop`` signal; ``at`` is the first such activity's
    ``created_at`` (activities are oldest-first)."""
    stop = next((a for a in activities if a.signal == "stop"), None)
    return engagement.AgentSessionRead(
        activities=tuple(activities),
        stop_signal=engagement.StopSignalIndicator(
            stopped=stop is not None, at=stop.created_at if stop is not None else None
        ),
    )


def _request_issue_mutation(
    client: LinearClient,
    mutation: str,
    variables: dict[str, object],
    *,
    issue_id: str,
) -> dict[str, object]:
    """Run an issue-targeted mutation, preserving the not-found error mapping.

    The verified issue mutations (``issueUpdate``/``commentCreate``) take the boundary
    **identifier** directly (live-verified at the Mode 2 smoke gate). A missing entity surfaces
    as a ``LinearGraphQLError`` matching :func:`_is_entity_not_found`; re-raise it as the
    byte-identical ``IssueBackendError("Linear issue <id> not found")`` the old ``uuid_for``
    resolution emitted. Every other error propagates unchanged.
    """
    try:
        return client.request(mutation, variables)
    except LinearGraphQLError as exc:
        if _is_entity_not_found(exc):
            raise IssueBackendError(f"Linear issue {issue_id!r} not found") from exc
        raise


@contextmanager
def _translate_objective() -> Iterator[None]:
    """Map the issue substrate's native error into the objective-tier neutral one (verbatim)."""
    try:
        yield
    except IssueBackendError as exc:
        raise ObjectiveStoreError(str(exc)) from exc


def _objective_ref(ref: issue_backend.IssueRef) -> objective_store.ObjectiveRef:
    """Convert a substrate `IssueRef` into the objective-tier `ObjectiveRef` (same fields)."""
    return objective_store.ObjectiveRef(id=ref.id, url=ref.url, existed=ref.existed)
