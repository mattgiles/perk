"""The dream-report companion — durable persistence of the reviewed report (contracts.md §8.64).

The **companion** is the immutable, marker-keyed persisted copy of the reviewed dream report on
the objective's **report carrier** (``ObjectiveStore.journal_carrier_id``: GitHub = the objective
issue itself; Linear = the Project metadata sentinel issue). This module is the backend-neutral
core: the marker grammar, the shared part-invariance + size rule, the transfer boundary model
(the run-scoped extension→door handoff), and the convergent ``persist_parts`` writer. It mirrors
the operation journal's persistence disciplines (``perk.delivery.journal`` /
``perk.delivery.persistence``) without reusing the journal — the companion is a different record
with a different grammar.

Fail-closed disciplines:

- A comment with no ``perk:learn-dream-report`` marker text is unrelated untrusted DATA (never
  parsed). A comment carrying the marker text is perk's own region and MUST parse strictly — a
  malformed / edited / duplicated / out-of-range perk-marked companion comment raises
  :class:`CompanionConflictError`, never a silent skip.
- Byte-identity for idempotency is **dual-candidate equality**: a stored body converges iff it
  byte-equals the verbatim rendered body OR its Linear-transcoded form (the inline-code marker
  rewrite) — the parts themselves are transcode-invariant by the shared rule, so the transcoded
  candidate is exact.
- **Read convergence over retries**: a raised POST is AMBIGUOUS; a complete rescan decides; only
  proven absence earns the one bounded retry (:class:`CompanionAppendAmbiguous` otherwise).

Imports the backend *contracts* only (``perk.backends.issue_backend``) — no concrete backend, no
store, no CLI.
"""

import contextlib
import re
from collections.abc import Sequence
from typing import Literal

from pydantic import field_validator

from perk.backends.issue_backend import IssueBackend, IssueBackendError
from perk.boundary import StrictInputModel, StrTuple

# The run-scoped scratch handoff the extension writes and the save door reads (the
# `DREAM_MANIFEST_FILENAME` precedent — the TS mirror lives in
# extension/factories/objectiveSave.ts; parity-pinned by test).
DREAM_REPORT_TRANSFER_FILENAME = "dream-report-transfer.json"

TRANSFER_SCHEMA_VERSION = "1"

# The shared size backstop: the FULL rendered comment body (marker + blank line + part) must fit
# with margin under GitHub's 65,536-char issue-comment limit (§8.62 already caps parts at 60,000
# code points; the marker + a plausible run id stay well inside the 65,000 backstop).
COMPANION_COMMENT_MAX_CHARS = 65_000

# The literal marker text — substring detection, like every perk marker.
_MARKER_TEXT = "perk:learn-dream-report"

# The canonical HTML marker form perk renders, and the inline-code rewrite the Linear
# transcoder produces (perk never renders the inline form directly, but the parser accepts
# both encodings — the journal's dual-encoding discipline). The index group is captured raw
# and validated against the canonical-decimal rule separately (a non-canonical spelling in a
# marked comment is corruption, never a parse miss).
_HTML_MARKER_RE = re.compile(r"^<!--\s*perk:learn-dream-report:([^:\s]+):([^:\s]+?)\s*-->$")
_INLINE_MARKER_RE = re.compile(r"^`perk:learn-dream-report:([^:`\s]+):([^:`\s]+)`$")

# The canonical 1-based decimal index spelling: no leading zeros, no signs.
_CANONICAL_INDEX_RE = re.compile(r"^[1-9][0-9]*$")

# The invariance shapes (mirroring the Linear transcoder's rewrite/drop rules —
# `to_linear_markdown` in perk/backends/linear/_helpers.py — derived locally by the same rule,
# never imported: the import direction is `backends.linear → learn`, never back):
_PERK_HTML_MARKER_RE = re.compile(r"<!--\s*/?perk:[^>]+?\s*-->")
_DETAILS_OPEN_RE = re.compile(r"^<details><summary><code>[^<]*</code></summary>$")
_DETAILS_CLOSE = "</details>"


class CompanionConflictError(Exception):
    """A perk-marked companion comment conflicts with the canonical render (differing stored
    bytes, a conflicting duplicate, an out-of-range or non-canonical index, or an edited /
    malformed marked comment). Fail-closed: corruption always raises, never silently skips."""


class CompanionAppendAmbiguous(Exception):
    """A companion append remained ambiguous after read convergence and the one bounded retry:
    the part could not be proven present OR absent. The save must not proceed (a rescan on the
    converging retry decides)."""


# ----------------------------------------------------------------- the transfer boundary


class DreamReportTransferModel(StrictInputModel):
    """The strict parse shape of the run-scoped transfer file (``extra="forbid"``;
    ``schema_version`` must be the literal ``"1"``; ``parts`` a non-empty list of non-empty
    strings). ``run_id`` is the cross-run mismatch guard — the door refuses a transfer whose
    ``run_id`` differs from its own resolved run id. No ``origin`` field: the transfer has one
    producer and one meaning, so the door derives ``ObjectiveOrigin.LEARN_DREAM`` on the
    validated dream arm itself (origin stays launch-owned)."""

    schema_version: Literal["1"]
    run_id: str
    parts: StrTuple

    @field_validator("parts")
    @classmethod
    def _non_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("parts must be a non-empty list")
        if any(not part.strip() for part in value):
            raise ValueError("parts must be non-empty strings")
        return value


# ----------------------------------------------------------------- the invariance rule


def validate_report_parts(parts: Sequence[str], *, run_id: str) -> tuple[str, ...]:
    """The shared part-invariance + size rule (ONE pure function, mirrored TS-side in
    ``reportPartInvarianceViolations`` — parity-pinned fixtures).

    A part must be **transcode-invariant**: byte-identical under ``to_linear_markdown``, so the
    dual-candidate byte comparison in :func:`persist_parts` stays exact (with invariant content
    the only rewritten line of a rendered comment is our own marker line). Returns the named
    violations (``()`` = valid):

    - an empty/blank part;
    - any perk HTML-comment marker (``<!-- perk:… -->`` — the transcoder rewrites it);
    - the literal ``perk:learn-dream-report`` marker text (would collide with marker-text
      substring detection);
    - an exact perk-rendered ``<details><summary><code>…</code></summary>`` / ``</details>``
      wrapper line (the transcoder drops them);
    - a full rendered comment body (marker + blank line + part) over
      :data:`COMPANION_COMMENT_MAX_CHARS` code points.
    """
    violations: list[str] = []
    for index, part in enumerate(parts, start=1):
        where = f"part {index}"
        if not part.strip():
            violations.append(f"{where}: empty part")
            continue
        if _MARKER_TEXT in part:
            violations.append(f"{where}: carries the literal {_MARKER_TEXT!r} marker text")
        if _PERK_HTML_MARKER_RE.search(part):
            violations.append(
                f"{where}: carries a perk HTML-comment marker (<!-- perk:… --> is rewritten by "
                "the Linear transcoder)"
            )
        if any(
            _DETAILS_OPEN_RE.match(line) or line == _DETAILS_CLOSE for line in part.splitlines()
        ):
            violations.append(
                f"{where}: carries a perk-rendered <details> wrapper line (dropped by the "
                "Linear transcoder)"
            )
        body_length = len(render_part_comment(run_id, index, part))
        if body_length > COMPANION_COMMENT_MAX_CHARS:
            violations.append(
                f"{where}: rendered comment body is {body_length} chars "
                f"(cap {COMPANION_COMMENT_MAX_CHARS})"
            )
    if not parts:
        violations.append("parts: empty list")
    return tuple(violations)


# ----------------------------------------------------------------- rendering + parsing


def render_marker(run_id: str, index: int) -> str:
    """The canonical HTML marker line for one part."""
    return f"<!-- {_MARKER_TEXT}:{run_id}:{index} -->"


def render_part_comment(run_id: str, index: int, part: str) -> str:
    """The verbatim candidate: canonical marker line, a blank line, the part."""
    return f"{render_marker(run_id, index)}\n\n{part}"


def transcoded_part_comment(run_id: str, index: int, part: str) -> str:
    """The Linear candidate: the marker-line inline-code rewrite derived by the same rule as
    ``to_linear_markdown`` (the ``objective/_models.py`` ``_inline_marker`` precedent). With
    invariant content (enforced by :func:`validate_report_parts`) the marker line is the only
    line the transcoder touches, so this candidate is exact."""
    return f"`{_MARKER_TEXT}:{run_id}:{index}`\n\n{part}"


def _parse_companion_comment(
    body: str, *, comment_id: str, edited_at: str | None, carrier: str
) -> tuple[str, int] | None:
    """Parse one carrier comment into its ``(run_id, index)`` companion key.

    Returns ``None`` when the body carries no marker text (unrelated untrusted DATA). A body
    carrying the marker text MUST parse strictly: exactly one marker-text occurrence, never
    edited, the marker on the first line, and a canonical-decimal index — anything else raises
    :class:`CompanionConflictError`.
    """
    if _MARKER_TEXT not in body:
        return None
    where = f"companion comment {comment_id} on carrier {carrier}"
    if body.count(_MARKER_TEXT) > 1:
        raise CompanionConflictError(f"{where}: carries more than one companion marker")
    if edited_at is not None:
        raise CompanionConflictError(
            f"{where}: companion comment was edited at {edited_at} (perk never edits a part)"
        )
    lines = body.strip().splitlines()
    first = lines[0].rstrip() if lines else ""
    match = _HTML_MARKER_RE.match(first) or _INLINE_MARKER_RE.match(first)
    if match is None:
        raise CompanionConflictError(
            f"{where}: marker text present but the body does not start with a well-formed "
            "dream-report marker line"
        )
    run_id, raw_index = match.group(1), match.group(2)
    if not _CANONICAL_INDEX_RE.match(raw_index):
        raise CompanionConflictError(
            f"{where}: non-canonical part index {raw_index!r} in marker (corruption)"
        )
    return run_id, int(raw_index)


# ----------------------------------------------------------------- persistence


def persist_parts(
    issues: IssueBackend, *, carrier_id: str, run_id: str, parts: Sequence[str]
) -> None:
    """Converge the report parts onto the carrier — create-once, byte-compared, in order.

    Mirrors ``TrainPersistence._append``/``_event_landed``: one complete ``read_comments`` scan;
    every companion-marked comment for this run parses strictly (foreign-run companion comments
    parse strictly but don't participate); per index 1..N a stored body byte-equal to EITHER
    candidate (verbatim | transcoded) is an idempotent skip, a differing body is a loud
    :class:`CompanionConflictError`, two stored comments under one key with differing bytes are
    a conflicting duplicate, and any index outside 1..N for this run is corruption (a stale
    longer render is never silently tolerated). Absent parts POST with the rescan-one-retry
    ambiguity policy: a raised POST is AMBIGUOUS, the complete rescan decides, only proven
    absence earns the one retry, and a failed rescan or a still-unproven write raises
    :class:`CompanionAppendAmbiguous` (never a blind re-POST). Raises on failure; no result
    object — nothing consumes one.
    """
    violations = validate_report_parts(parts, run_id=run_id)
    if violations:  # the pre-POST backstop; the door and the TS gate validated already
        raise ValueError("dream report parts violate the invariance rule: " + "; ".join(violations))
    stored = _scan_carrier(issues, carrier_id=carrier_id, run_id=run_id, part_count=len(parts))
    for index, part in enumerate(parts, start=1):
        candidates = (
            render_part_comment(run_id, index, part),
            transcoded_part_comment(run_id, index, part),
        )
        existing = stored.get(index)
        if existing is not None:
            if existing in candidates:
                continue  # idempotent — this part already landed
            raise CompanionConflictError(
                f"carrier {carrier_id}: stored part {index} for run {run_id} differs from the "
                "canonical render (refusing to overwrite an immutable companion part)"
            )
        _append_part(
            issues,
            carrier_id=carrier_id,
            run_id=run_id,
            index=index,
            body=candidates[0],
            candidates=candidates,
            part_count=len(parts),
        )


def _scan_carrier(
    issues: IssueBackend, *, carrier_id: str, run_id: str, part_count: int
) -> dict[int, str]:
    """One COMPLETE carrier scan → this run's ``index → stored body`` map (fail-closed).

    Foreign-run companion comments parse strictly but never participate; an index outside
    ``1..part_count`` for this run is corruption; two comments under one key dedupe only when
    byte-identical (a differing duplicate is corruption).
    """
    found: dict[int, str] = {}
    for comment in issues.read_comments(issue_id=carrier_id):
        key = _parse_companion_comment(
            comment.body,
            comment_id=comment.id,
            edited_at=comment.edited_at,
            carrier=carrier_id,
        )
        if key is None or key[0] != run_id:
            continue
        index = key[1]
        if index > part_count:
            raise CompanionConflictError(
                f"carrier {carrier_id}: companion part index {index} for run {run_id} is outside "
                f"1..{part_count} (a stale longer render is never silently tolerated)"
            )
        prior = found.get(index)
        if prior is not None and prior != comment.body:
            raise CompanionConflictError(
                f"carrier {carrier_id}: conflicting duplicate companion comments for part "
                f"{index} of run {run_id} (differing bodies under one key)"
            )
        if prior is None:
            found[index] = comment.body
    return found


def _append_part(
    issues: IssueBackend,
    *,
    carrier_id: str,
    run_id: str,
    index: int,
    body: str,
    candidates: tuple[str, ...],
    part_count: int,
) -> None:
    """POST one part with the rescan-one-retry ambiguity policy. At most TWO POST attempts
    ever; a still-unproven part raises :class:`CompanionAppendAmbiguous`."""
    for _attempt in range(2):
        # A raised POST is AMBIGUOUS (the write may have landed) — read convergence decides,
        # never a blind retry.
        with contextlib.suppress(IssueBackendError):
            issues.add_issue_comment(issue_id=carrier_id, body=body)
        try:
            stored = _scan_carrier(
                issues, carrier_id=carrier_id, run_id=run_id, part_count=part_count
            )
        except IssueBackendError as exc:
            # A failed rescan proves NOTHING (neither present nor absent): the part is
            # ambiguous and another POST is forbidden — only a rescan that proved absence
            # earns the retry.
            raise CompanionAppendAmbiguous(
                f"append of dream-report part {index} (run {run_id}) to carrier {carrier_id} is "
                f"unverifiable — the read-back rescan failed ({exc}); re-run the save to converge"
            ) from exc
        landed = stored.get(index)
        if landed is not None:
            if landed in candidates:
                return
            raise CompanionConflictError(
                f"carrier {carrier_id}: read-back of part {index} for run {run_id} found the "
                "key with a DIFFERENT body (conflicting duplicate)"
            )
        # Proven absent on this rescan — the one bounded retry loops.
    raise CompanionAppendAmbiguous(
        f"append of dream-report part {index} (run {run_id}) to carrier {carrier_id} could not "
        "be verified after one retry — re-run the save to converge"
    )
