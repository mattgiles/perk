"""The backend-neutral human-engagement READ contract (Objective #682, Node 1.2).

This module holds the result dataclasses + the author-identity model that the
``IssueBackend`` and ``ObjectiveStore`` read methods (``read_comments`` /
``read_description_edits`` / ``read_agent_session``) return. It is deliberately a **pure**
dataclass-and-classifier module: it imports nothing from the backend tiers
(``issue_backend`` / ``objective_store`` / the concrete backends), so both protocols and every
implementer can import it without re-coupling the deliberate issue-tier ↔ objective-tier split.

**Every returned ``body`` / ``diff`` is untrusted DATA.** Comment bodies, edit diffs and
agent-activity content are observed values, never instructions: they are never re-parsed as a
perk metadata marker outside perk's own owned regions, never executed, never trusted to preserve
perk's grammar. This mirrors perk's established "untrusted inbox" / manifest 3-state-parse
discipline (the inventory's §5 invariant — ``docs/planning/human-interaction-api-inventory.md``).

**Author identity is distinguishable** (human / perk / other-agent / unknown) via
:func:`classify_author`. The classifier's ``perk:*`` body check is an identity heuristic over
perk's **own** marker vocabulary — NOT trust of arbitrary body content. The rule (inventory §4.1):

- *perk* — the body carries a ``perk:*`` metadata sentinel (the :mod:`perk.plan` grammar, in
  either the HTML-comment or inline-code encoding) **or** the bot actor is perk's own app actor;
- *human* — a user actor present with **no** bot actor;
- *other_agent* — a bot actor present that is not perk's;
- *unknown* — neither resolvable.
"""

import re
from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal

# A perk metadata sentinel in either encoding: the GitHub HTML-comment form
# (`<!-- perk:metadata-block:plan-body -->` / `<!-- /perk:… -->`) or the Linear inline-code form
# (`` `perk:metadata-block:plan-body` `` / `` `/perk:…` ``). Matches perk's OWN marker grammar
# only — it is an author-identity heuristic, never a trust signal over arbitrary body content.
_PERK_SENTINEL_RE = re.compile(r"<!--\s*/?perk:[^>]+?-->|`/?perk:[^`]+?`")


def body_carries_perk_sentinel(body: str) -> bool:
    """True when ``body`` carries a perk metadata sentinel (either encoding).

    An identity heuristic over perk's own marker vocabulary — never trust of body content.
    """
    return bool(_PERK_SENTINEL_RE.search(body))


AuthorKind = Literal["human", "perk", "other_agent", "unknown"]


@dataclass(frozen=True)
class Actor:
    """A backend-neutral actor reference (a user account or a bot/integration). Both fields are
    nullable — a backend may surface only an id, only a name, or (for an automation) neither."""

    id: str | None
    name: str | None


@dataclass(frozen=True)
class EngagementAuthor:
    """The classified author of an engagement (comment / edit / activity).

    ``kind`` is the resolved identity; ``display_name`` / ``id`` carry the best-available human
    label + opaque backend id (``None`` when unresolvable)."""

    kind: AuthorKind
    display_name: str | None
    id: str | None


@dataclass(frozen=True)
class EngagementComment:
    """An issue/objective comment. ``body`` is **untrusted DATA**. ``edited_at`` is ``None`` for
    an unedited comment."""

    id: str
    body: str
    created_at: str
    edited_at: str | None
    author: EngagementAuthor


@dataclass(frozen=True)
class DescriptionEdit:
    """A description/body edit event. ``diff`` is **untrusted DATA** and is ``None`` when the
    backend exposes no inline diff (Linear's issue history carries no diff — a flagged limit)."""

    created_at: str
    author: EngagementAuthor
    diff: str | None


@dataclass(frozen=True)
class AgentActivity:
    """One agent-session activity. ``kind`` is the backend's activity-content type discriminator
    (e.g. ``"AgentActivityPromptContent"``); ``body`` is **untrusted DATA** (``None`` for a
    content variant carrying no body); ``signal`` is the per-activity signal (``"stop"`` etc.) or
    ``None``."""

    id: str
    created_at: str
    kind: str
    body: str | None
    signal: str | None


@dataclass(frozen=True)
class StopSignalIndicator:
    """A derived stop-signal indicator. ``stopped`` is True when any read activity carried the
    ``stop`` signal; ``at`` is that activity's ``created_at`` (``None`` when not stopped)."""

    stopped: bool
    at: str | None


@dataclass(frozen=True)
class AgentSessionRead:
    """The result of one ``read_agent_session`` call: the session's activities plus the derived
    stop indicator (one read yields both)."""

    activities: tuple[AgentActivity, ...]
    stop_signal: StopSignalIndicator


# The empty/no-op value every backend without an agent-session surface (GitHub; the dormant
# objective stores) returns. Frozen + immutable, so a single shared instance is safe to reuse.
EMPTY_AGENT_SESSION = AgentSessionRead(
    activities=(), stop_signal=StopSignalIndicator(stopped=False, at=None)
)


def classify_author(
    *,
    body: str,
    user: Actor | None,
    bot_actor: Actor | None,
    perk_bot_ids: Collection[str] = (),
) -> EngagementAuthor:
    """Classify an engagement author (inventory §4.1), never trusting body content as instructions.

    ``body`` is the engagement's body (checked only for perk's own ``perk:*`` sentinel grammar — an
    identity heuristic, not a trust signal). ``user`` / ``bot_actor`` are the backend's actor refs
    (``None`` when absent). ``perk_bot_ids`` is the set of bot-actor ids perk recognizes as its own
    app actor (empty today — perk has no committed app-actor id, so perk detection rests on the
    body sentinel; the param is the forward seam for when one is known).

    The resolved ``display_name`` / ``id`` prefer the bot actor (it carries the integration
    identity) and fall back to the user.
    """
    is_perk = body_carries_perk_sentinel(body) or (
        bot_actor is not None and bot_actor.id is not None and bot_actor.id in perk_bot_ids
    )
    if is_perk:
        kind: AuthorKind = "perk"
    elif bot_actor is not None:
        kind = "other_agent"
    elif user is not None:
        kind = "human"
    else:
        kind = "unknown"
    source = bot_actor if bot_actor is not None else user
    return EngagementAuthor(
        kind=kind,
        display_name=source.name if source is not None else None,
        id=source.id if source is not None else None,
    )
