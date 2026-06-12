"""Plan storage: the two-part header/body metadata-block engine + the provider-agnostic
plan ref (`contracts.md` §8.4; PRIOR_ART §2).

Pure and deterministic — **no Click, no subprocess, no network**. The GitHub *write* lives
in :mod:`perk.github`; the *in-session* twin is the TS extension (T3). Inference-hoisting
(PRIOR_ART §12 / erk-subagent §8): this layer stores what it is given (the plan body
**verbatim**) and computes nothing agentic — which is what keeps it deterministically
testable.

Storage shape (PRIOR_ART §2, erk's metadata-blocks, perk-namespaced):

- **Issue body** holds the ``plan-header`` block — compact YAML, queryable without fetching
  comments.
- **First comment** holds the ``plan-body`` block — the full plan markdown in a collapsible
  ``<details>``.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

import yaml

PLAN_LABEL = "perk:plan"
PLAN_LABEL_COLOR = "1f883d"  # GitHub green
PLAN_LABEL_DESCRIPTION = "perk plan issue"

# The learn issue (P2.T8b): a `perk:learn`-labelled knowledge-capture issue, created by `/learn`
# from agent-captured learnings. Distinct label + header key so its idempotency finder cannot
# collide with the plan issue (which shares the same `run_id` under the `warm: keep` learn stage).
LEARN_LABEL = "perk:learn"
LEARN_LABEL_COLOR = "8250df"  # GitHub purple
LEARN_LABEL_DESCRIPTION = "perk learn issue"

# The consolidated label (hop-2): a `perk:learn` issue gets this label + is closed when its
# learnings have been consumed into a `docs/learned/` documentation plan (the learn-docs factory).
# Closing already excludes it from the next `state=open` gather; the label is the durable record.
CONSOLIDATED_LABEL = "perk:consolidated"
CONSOLIDATED_LABEL_COLOR = "6e7781"  # GitHub gray
CONSOLIDATED_LABEL_DESCRIPTION = "perk learn issue consolidated into docs/learned"

PLAN_HEADER_KEY = "plan-header"
PLAN_BODY_KEY = "plan-body"
LEARN_HEADER_KEY = "learn-header"  # carries { run_id, created, plan } in the learn issue body

# The valid `plan-header` field names (the staged-population schema; lifecycle.md). Used by
# the submit-time `update_plan_header` write to reject unknown keys (LBYL on the schema).
PLAN_HEADER_FIELDS = frozenset(
    {"run_id", "lifecycle_stage", "branch", "pr", "created", "objective_id", "consumed_learn"}
)

_OPEN = "<!-- perk:metadata-block:{key} -->"
_CLOSE = "<!-- /perk:metadata-block:{key} -->"
_FENCE = "```"

# The Linear-safe delimiter encoding (objective #252 Node 2.2): inline-code sentinels on their
# own lines, with NO `<details>` wrapper. Linear stores bodies as ProseMirror documents and
# round-trips markdown on write/read — HTML comments and `<details>` are not in its supported
# markdown set and must be assumed lossy; inline code and fenced code blocks ARE supported.
_INLINE_OPEN = "`perk:metadata-block:{key}`"
_INLINE_CLOSE = "`/perk:metadata-block:{key}`"

BlockStyle = Literal["html", "inline-code"]


class LifecycleStage(StrEnum):
    """The stored, queryable plan stage (Q8 consolidation: ``planned → impl``; terminal
    ``merged``/``closed`` are derived from PR state, never stored)."""

    PLANNED = "planned"
    IMPL = "impl"


@dataclass(frozen=True)
class PlanHeader:
    """Compact, queryable metadata stored in the issue *body* (contracts.md §8.4).

    ``branch``/``pr`` are **staged** — null during planning, populated at submit
    (PRIOR_ART §2: "commands must handle missing fields gracefully").
    """

    run_id: str
    created: str  # ISO-8601 UTC (see :func:`now_iso`)
    lifecycle_stage: LifecycleStage = LifecycleStage.PLANNED
    branch: str | None = None
    pr: str | None = None
    objective_id: str | None = None  # Phase 2
    consumed_learn: tuple[int, ...] = ()  # hop-2: the perk:learn issues this docs plan consumes

    def to_data(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "lifecycle_stage": self.lifecycle_stage.value,
            "branch": self.branch,
            "pr": self.pr,
            "created": self.created,
            "objective_id": self.objective_id,
            "consumed_learn": list(self.consumed_learn),
        }


@dataclass(frozen=True)
class PlanRef:
    """The provider-agnostic plan→branch ref (contracts.md §8.4).

    ``pr_id`` is a **string** (allows non-numeric ids like Jira ``PROJ-123``); during
    planning it carries the *issue* id, with ``branch``/``pr`` staged null in the header.
    T2a **emits** this; T2b materializes it into ``cache.plan-ref``.
    """

    provider: str
    pr_id: str
    url: str
    labels: tuple[str, ...]
    objective_id: str | None = None
    consumed_learn: tuple[int, ...] = ()  # hop-2: consumed perk:learn issues (closed on land)

    def to_data(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "pr_id": self.pr_id,
            "url": self.url,
            "labels": list(self.labels),
            "objective_id": self.objective_id,
            "consumed_learn": list(self.consumed_learn),
        }


# --------------------------------------------------------------------- block engine


def render_metadata_block(key: str, data: dict[str, object], *, style: BlockStyle = "html") -> str:
    """Render a structured (YAML) perk metadata block. Inverse of :func:`find_metadata_block`.

    ``style="html"`` (the default — every GitHub call site, unchanged) uses HTML-comment
    delimiters + a collapsible ``<details>`` wrapper; ``style="inline-code"`` is the Linear-safe
    encoding (inline-code sentinels, no wrapper — see the ``_INLINE_OPEN`` note).
    """
    body = yaml.safe_dump(data, sort_keys=False, default_flow_style=False).strip()
    if style == "inline-code":
        return (
            f"{_INLINE_OPEN.format(key=key)}\n\n"
            f"{_FENCE}yaml\n{body}\n{_FENCE}\n\n"
            f"{_INLINE_CLOSE.format(key=key)}"
        )
    return (
        f"{_OPEN.format(key=key)}\n"
        f"<details><summary><code>{key}</code></summary>\n\n"
        f"{_FENCE}yaml\n{body}\n{_FENCE}\n\n"
        f"</details>\n"
        f"{_CLOSE.format(key=key)}"
    )


def replace_metadata_block(text: str, key: str, data: dict[str, object]) -> str:
    """Replace an existing perk metadata block (by key) with a re-rendered one (inverse of
    :func:`find_metadata_block`). Appends if the block is absent; a no-op if the open marker
    exists but its close marker is missing (malformed — caller validates via
    :func:`find_metadata_block`)."""
    start = text.find(_OPEN.format(key=key))
    if start != -1:
        rendered = render_metadata_block(key, data)
        close = _CLOSE.format(key=key)
        end = text.find(close, start)
        if end == -1:
            return text
        return text[:start] + rendered + text[end + len(close) :]
    # Form preservation: an existing inline-code (Linear-safe) block re-renders inline-code.
    start = text.find(_INLINE_OPEN.format(key=key))
    if start != -1:
        rendered = render_metadata_block(key, data, style="inline-code")
        close = _INLINE_CLOSE.format(key=key)
        end = text.find(close, start)
        if end == -1:
            return text
        return text[:start] + rendered + text[end + len(close) :]
    # Append-when-absent keeps the html form (only GitHub callers append today; the Linear
    # backend always finds an existing block before replacing).
    rendered = render_metadata_block(key, data)
    return f"{text.rstrip()}\n\n{rendered}\n" if text.strip() else f"{rendered}\n"


def has_metadata_block(text: str, key: str) -> bool:
    """Presence-only check for a perk metadata block's **open** delimiter, in either encoding
    (HTML or the Linear-safe inline-code sentinel).

    The absent-vs-malformed discriminator: :func:`find_metadata_block` returns ``None`` for both
    cases; this answers only "is a block (possibly malformed) present at all?".
    """
    return _OPEN.format(key=key) in text or _INLINE_OPEN.format(key=key) in text


def find_metadata_block(text: str, key: str) -> dict[str, object] | None:
    """Parse a single structured perk metadata block by key. None if absent or malformed.

    No custom regex beyond the delimiter scan (metadata-blocks best-practice 1). Dual-encoding
    scan: the HTML delimiters are tried first (the unchanged GitHub path), then the Linear-safe
    inline-code sentinels; the fence scan inside the segment is shared.
    """
    segment = _delimited_segment(text, _OPEN.format(key=key), _CLOSE.format(key=key))
    if segment is None:
        segment = _delimited_segment(
            text, _INLINE_OPEN.format(key=key), _INLINE_CLOSE.format(key=key)
        )
    if segment is None:
        return None

    fence = segment.find(f"{_FENCE}yaml")
    if fence == -1:
        return None
    body_start = fence + len(f"{_FENCE}yaml")
    body_end = segment.find(_FENCE, body_start)
    if body_end == -1:
        return None

    try:
        data = yaml.safe_load(segment[body_start:body_end])
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _delimited_segment(text: str, open_marker: str, close_marker: str) -> str | None:
    """The text between ``open_marker`` and ``close_marker`` (exclusive). None when absent."""
    start = text.find(open_marker)
    if start == -1:
        return None
    end = text.find(close_marker, start + len(open_marker))
    if end == -1:
        return None
    return text[start + len(open_marker) : end]


def render_plan_body(plan_markdown: str, *, style: BlockStyle = "html") -> str:
    """Render the ``plan-body`` comment — the full plan markdown in a collapsible block.

    The body is **prose markdown** (not YAML), so this is a write-only wrapper: T2a never
    parses it back (idempotency reads only the header). Stored **verbatim**.

    ``style="inline-code"`` (the Linear-safe encoding) wraps the verbatim plan markdown between
    the ``plan-body`` sentinels with no ``<details>`` wrapper — the plan markdown is NOT fenced
    (it is full markdown); the sentinels alone delimit it, mirroring the HTML encoding.
    """
    if style == "inline-code":
        return (
            f"{_INLINE_OPEN.format(key=PLAN_BODY_KEY)}\n\n"
            f"{plan_markdown.strip()}\n\n"
            f"{_INLINE_CLOSE.format(key=PLAN_BODY_KEY)}"
        )
    return (
        f"{_OPEN.format(key=PLAN_BODY_KEY)}\n"
        f"<details><summary><code>{PLAN_BODY_KEY}</code></summary>\n\n"
        f"{plan_markdown.strip()}\n\n"
        f"</details>\n"
        f"{_CLOSE.format(key=PLAN_BODY_KEY)}"
    )


def extract_plan_body(text: str) -> str | None:
    """Extract the verbatim plan markdown from a ``plan-body`` block (inverse of
    :func:`render_plan_body`). ``text`` is an issue body or a comment body. ``None`` when the block
    is absent or malformed. Used to materialize the plan body for in-session checkpoints (P2.T2c).

    Dual-encoding scan (mirrors :func:`find_metadata_block`): HTML first, then the Linear-safe
    inline-code sentinels — on that branch the body is the text strictly between the sentinels.
    """
    segment = _delimited_segment(
        text, _OPEN.format(key=PLAN_BODY_KEY), _CLOSE.format(key=PLAN_BODY_KEY)
    )
    if segment is not None:
        summary = f"<details><summary><code>{PLAN_BODY_KEY}</code></summary>"
        inner_start = segment.find(summary)
        if inner_start == -1:
            return None
        inner_start += len(summary)
        inner_end = segment.rfind("</details>")
        if inner_end == -1 or inner_end < inner_start:
            return None
        body = segment[inner_start:inner_end].strip()
        return body or None
    segment = _delimited_segment(
        text, _INLINE_OPEN.format(key=PLAN_BODY_KEY), _INLINE_CLOSE.format(key=PLAN_BODY_KEY)
    )
    if segment is None:
        return None
    body = segment.strip()
    return body or None


# ----------------------------------------------------------------------- helpers


def extract_run_id(issue_body: str, *, header_key: str = PLAN_HEADER_KEY) -> str | None:
    """The ``run_id`` in an issue body's metadata block (for idempotency). None if absent.

    ``header_key`` defaults to ``plan-header`` (the plan issue); the learn issue passes
    ``learn-header`` so its run_id is read from its OWN block (P2.T8b — the label-scoped finder).
    """
    block = find_metadata_block(issue_body, header_key)
    if block is None:
        return None
    run_id = block.get("run_id")
    return run_id if isinstance(run_id, str) and run_id else None


def derive_title(plan_markdown: str, *, fallback: str = "perk plan") -> str:
    """The plan title — the first real ATX ``# `` heading **outside any fenced code block**,
    else ``fallback``.

    Fenced ```` ``` ````/``~~~`` blocks are skipped so a ``#`` inside a code sample cannot be
    mistaken for the title (a real dogfood failure: a TOML ``# comment`` became the plan title).
    A heading is recognized only with 0-3 spaces of indent (CommonMark); 4+ is a code line.
    """
    fence: str | None = None
    for line in plan_markdown.splitlines():
        stripped = line.lstrip(" ")
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            fence = marker if fence is None else (None if marker == fence else fence)
            continue
        if fence is not None:
            continue  # inside a code fence — a leading `#` here is not a heading
        if len(line) - len(stripped) <= 3 and stripped.startswith("# "):
            title = stripped[2:].strip()
            if title:
                return title
    return fallback


def now_iso() -> str:
    """The current time as ISO-8601 UTC (``…Z``), for the header ``created`` field."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
