"""Tests for the dream-report companion core (``perk/learn/dream_companion.py``).

The ``tests/test_delivery_persistence.py`` fake pattern: an in-memory issue backend with
programmable POST/read plans, so the rescan-one-retry ambiguity policy and the dual-candidate
byte-compare convergence are pinned end to end. The invariance-rule fixtures are the shared
cross-plane set (``tests/parity/dream_report_invariance.json``), asserted rejected by BOTH this
suite and the TS gate mirror (``extension/authoring/objective/dreamReportGate.test.ts``).
"""

import itertools
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

from perk.backends import engagement
from perk.backends.issue_backend import CommentResult, IssueBackend, IssueBackendError
from perk.learn import dream_companion as dc

_RUN = "01RUNAAAAAAAAAAAAAAAAAAAAA"
_OTHER_RUN = "01RUNBBBBBBBBBBBBBBBBBBBBB"
_CARRIER = "252"

_PERK_AUTHOR = engagement.EngagementAuthor(kind="perk", display_name=None, id=None)

_PARITY_FIXTURE = Path(__file__).parent / "parity" / "dream_report_invariance.json"


@dataclass
class _FakeIssues:
    """A minimal in-memory issue backend: per-carrier comment lists + programmable POST/read
    plans (the ``test_delivery_persistence.py`` recipe).

    ``post_plan`` entries consumed per ``add_issue_comment`` call (default ``"ok"``): ``"ok"``
    succeed; ``"raise_after"`` record then raise (ambiguous-landed); ``"raise_lost"`` raise
    without recording (ambiguous-lost). ``read_plan`` entries consumed per ``read_comments``
    call (default ``"ok"``): ``"ok"`` honest read; ``"raise"`` an infra failure.
    """

    backend_id = "fake"

    comments: dict[str, list[engagement.EngagementComment]] = field(default_factory=dict)
    post_plan: list[str] = field(default_factory=list)
    read_plan: list[str] = field(default_factory=list)
    post_calls: list[tuple[str, str]] = field(default_factory=list)
    _seq: "itertools.count[int]" = field(default_factory=lambda: itertools.count(1))

    def seed(self, issue_id: str, body: str, *, edited_at: str | None = None) -> None:
        self._record(issue_id, body, edited_at=edited_at)

    def _record(self, issue_id: str, body: str, *, edited_at: str | None = None) -> None:
        n = next(self._seq)
        self.comments.setdefault(issue_id, []).append(
            engagement.EngagementComment(
                id=f"c{n}",
                body=body,
                created_at=f"2026-01-01T00:{n // 60:02d}:{n % 60:02d}Z",
                edited_at=edited_at,
                author=_PERK_AUTHOR,
            )
        )

    def add_issue_comment(
        self, *, issue_id: str, body: str, dry_run: bool = False
    ) -> CommentResult:
        self.post_calls.append((issue_id, body))
        behavior = self.post_plan.pop(0) if self.post_plan else "ok"
        if behavior == "raise_lost":
            raise IssueBackendError("boom (write lost)")
        self._record(issue_id, body)
        if behavior == "raise_after":
            raise IssueBackendError("boom (write landed)")
        return CommentResult(posted=True)

    def read_comments(self, *, issue_id: str) -> tuple[engagement.EngagementComment, ...]:
        behavior = self.read_plan.pop(0) if self.read_plan else "ok"
        if behavior == "raise":
            raise IssueBackendError("boom (read failed)")
        return tuple(self.comments.get(issue_id, ()))


def _issues() -> tuple[IssueBackend, _FakeIssues]:
    fake = _FakeIssues()
    return cast("IssueBackend", fake), fake


def _persist(issues: IssueBackend, parts: list[str]) -> None:
    dc.persist_parts(issues, carrier_id=_CARRIER, run_id=_RUN, parts=parts)


# --- the happy path + idempotent convergence ------------------------------------------------


def test_multi_part_happy_path_stores_exact_bodies():
    issues, fake = _issues()
    _persist(issues, ["part one", "part two", "part three"])
    bodies = [c.body for c in fake.comments[_CARRIER]]
    assert bodies == [
        f"<!-- perk:learn-dream-report:{_RUN}:1 -->\n\npart one",
        f"<!-- perk:learn-dream-report:{_RUN}:2 -->\n\npart two",
        f"<!-- perk:learn-dream-report:{_RUN}:3 -->\n\npart three",
    ]


def test_idempotent_retry_against_verbatim_stored_form():
    issues, fake = _issues()
    _persist(issues, ["part one", "part two"])
    posted = len(fake.post_calls)
    _persist(issues, ["part one", "part two"])  # the converging retry
    assert len(fake.post_calls) == posted  # nothing re-posted
    assert len(fake.comments[_CARRIER]) == 2


def test_idempotent_retry_against_transcoded_stored_form():
    # The Linear shape: the stored body carries the inline-code marker rewrite (the backend
    # transcoded the outgoing body); the dual-candidate compare converges without a POST.
    issues, fake = _issues()
    fake.seed(_CARRIER, f"`perk:learn-dream-report:{_RUN}:1`\n\npart one")
    _persist(issues, ["part one"])
    assert fake.post_calls == []


def test_partial_persist_converges_only_the_missing_parts():
    issues, fake = _issues()
    fake.seed(_CARRIER, f"<!-- perk:learn-dream-report:{_RUN}:1 -->\n\npart one")
    _persist(issues, ["part one", "part two"])
    assert [body for _, body in fake.post_calls] == [
        f"<!-- perk:learn-dream-report:{_RUN}:2 -->\n\npart two"
    ]


# --- conflicts + corruption ------------------------------------------------------------------


def test_differing_stored_bytes_refuse_loudly():
    issues, fake = _issues()
    fake.seed(_CARRIER, f"<!-- perk:learn-dream-report:{_RUN}:1 -->\n\nDIFFERENT")
    with pytest.raises(dc.CompanionConflictError, match="differs from the canonical render"):
        _persist(issues, ["part one"])
    assert fake.post_calls == []  # refused before any write


def test_conflicting_duplicate_is_corruption():
    issues, fake = _issues()
    fake.seed(_CARRIER, f"<!-- perk:learn-dream-report:{_RUN}:1 -->\n\npart one")
    fake.seed(_CARRIER, f"<!-- perk:learn-dream-report:{_RUN}:1 -->\n\nother bytes")
    with pytest.raises(dc.CompanionConflictError, match="conflicting duplicate"):
        _persist(issues, ["part one"])


def test_byte_identical_duplicate_dedupes():
    issues, fake = _issues()
    body = f"<!-- perk:learn-dream-report:{_RUN}:1 -->\n\npart one"
    fake.seed(_CARRIER, body)
    fake.seed(_CARRIER, body)
    _persist(issues, ["part one"])
    assert fake.post_calls == []


def test_out_of_range_index_is_corruption():
    # A stale longer render (an index beyond this run's part count) is never silently tolerated.
    issues, fake = _issues()
    fake.seed(_CARRIER, f"<!-- perk:learn-dream-report:{_RUN}:1 -->\n\npart one")
    fake.seed(_CARRIER, f"<!-- perk:learn-dream-report:{_RUN}:2 -->\n\nstale tail")
    with pytest.raises(dc.CompanionConflictError, match=r"outside 1\.\.1"):
        _persist(issues, ["part one"])


@pytest.mark.parametrize("index", ["01", "0", "+1", "-1"])
def test_non_canonical_index_is_corruption(index: str):
    issues, fake = _issues()
    fake.seed(_CARRIER, f"<!-- perk:learn-dream-report:{_RUN}:{index} -->\n\npart one")
    with pytest.raises(dc.CompanionConflictError, match="non-canonical part index"):
        _persist(issues, ["part one"])


def test_edited_marked_comment_is_corruption():
    issues, fake = _issues()
    fake.seed(
        _CARRIER,
        f"<!-- perk:learn-dream-report:{_RUN}:1 -->\n\npart one",
        edited_at="2026-06-13T00:00:00Z",
    )
    with pytest.raises(dc.CompanionConflictError, match="edited"):
        _persist(issues, ["part one"])


def test_malformed_marked_comment_is_corruption():
    # Marker text present but not a well-formed first-line marker → corruption, never a skip.
    issues, fake = _issues()
    fake.seed(_CARRIER, "some prose quoting perk:learn-dream-report mid-body")
    with pytest.raises(dc.CompanionConflictError, match="well-formed"):
        _persist(issues, ["part one"])


def test_leading_blank_line_before_marker_is_corruption():
    # The marker must sit on the PHYSICAL first line — a leading blank line is never
    # normalized away into acceptance.
    issues, fake = _issues()
    fake.seed(_CARRIER, f"\n<!-- perk:learn-dream-report:{_RUN}:1 -->\n\npart one")
    with pytest.raises(dc.CompanionConflictError, match="well-formed"):
        _persist(issues, ["part one"])


def test_leading_whitespace_on_the_marker_line_is_corruption():
    issues, fake = _issues()
    fake.seed(_CARRIER, f"  <!-- perk:learn-dream-report:{_RUN}:1 -->\n\npart one")
    with pytest.raises(dc.CompanionConflictError, match="well-formed"):
        _persist(issues, ["part one"])


def test_foreign_run_leading_blank_line_is_corruption_not_silent_skip():
    # Strict parsing applies to FOREIGN-run marked comments identically: a leading blank line
    # is corruption, never "parses after normalization, then non-participates".
    issues, fake = _issues()
    fake.seed(_CARRIER, f"\n<!-- perk:learn-dream-report:{_OTHER_RUN}:1 -->\n\nforeign part")
    with pytest.raises(dc.CompanionConflictError, match="well-formed"):
        _persist(issues, ["part one"])


def test_double_marker_text_is_corruption():
    issues, fake = _issues()
    fake.seed(
        _CARRIER,
        f"<!-- perk:learn-dream-report:{_RUN}:1 -->\n\nquoting perk:learn-dream-report again",
    )
    with pytest.raises(dc.CompanionConflictError, match="more than one companion marker"):
        _persist(issues, ["part one"])


def test_foreign_run_comments_parse_strictly_but_do_not_participate():
    issues, fake = _issues()
    # A well-formed foreign-run part (out of this run's range) is fine — non-participating.
    fake.seed(_CARRIER, f"<!-- perk:learn-dream-report:{_OTHER_RUN}:7 -->\n\nforeign part")
    # An unmarked comment is unrelated untrusted DATA.
    fake.seed(_CARRIER, "a human comment")
    _persist(issues, ["part one"])
    assert [body for _, body in fake.post_calls] == [
        f"<!-- perk:learn-dream-report:{_RUN}:1 -->\n\npart one"
    ]


def test_malformed_foreign_run_comment_still_raises():
    # Strict parse applies to EVERY marked comment — a malformed foreign-run marker is
    # corruption too (the marker text is perk's own region regardless of run).
    issues, fake = _issues()
    fake.seed(_CARRIER, f"<!-- perk:learn-dream-report:{_OTHER_RUN}:01 -->\n\nforeign part")
    with pytest.raises(dc.CompanionConflictError, match="non-canonical part index"):
        _persist(issues, ["part one"])


# --- the rescan-one-retry ambiguity policy ---------------------------------------------------


def test_ambiguous_landed_post_converges_via_rescan_without_retry():
    # "raise_after": the POST raises but the write landed — the rescan proves presence; no
    # second POST.
    issues, fake = _issues()
    fake.post_plan = ["raise_after"]
    _persist(issues, ["part one"])
    assert len(fake.post_calls) == 1
    assert len(fake.comments[_CARRIER]) == 1


def test_ambiguous_lost_post_earns_the_one_retry_then_lands():
    # "raise_lost": the POST raises and the write was lost — the rescan proves absence, which
    # earns exactly one retry; the retry lands.
    issues, fake = _issues()
    fake.post_plan = ["raise_lost", "ok"]
    _persist(issues, ["part one"])
    assert len(fake.post_calls) == 2
    assert [c.body for c in fake.comments[_CARRIER]] == [
        f"<!-- perk:learn-dream-report:{_RUN}:1 -->\n\npart one"
    ]


def test_failed_rescan_is_ambiguous_with_no_second_post():
    # A failed rescan proves nothing → CompanionAppendAmbiguous, and the second POST is
    # forbidden (only proven absence earns the retry).
    issues, fake = _issues()
    fake.post_plan = ["raise_lost"]
    fake.read_plan = ["ok", "raise"]  # the pre-persist scan, then the failing read-back
    with pytest.raises(dc.CompanionAppendAmbiguous, match="rescan failed"):
        _persist(issues, ["part one"])
    assert len(fake.post_calls) == 1


def test_still_absent_after_retry_is_ambiguous():
    issues, fake = _issues()
    fake.post_plan = ["raise_lost", "raise_lost"]
    with pytest.raises(dc.CompanionAppendAmbiguous, match="after one retry"):
        _persist(issues, ["part one"])
    assert len(fake.post_calls) == 2  # at most TWO POST attempts ever


# --- the shared invariance rule (the cross-plane parity fixture) -----------------------------


def _parity_fixture() -> dict:
    return json.loads(_PARITY_FIXTURE.read_text(encoding="utf-8"))


def _expand(entry: dict) -> str:
    if "part" in entry:
        return entry["part"]
    return entry["repeat"] * entry["count"]


def test_parity_fixture_valid_parts_pass():
    fixture = _parity_fixture()
    assert dc.validate_report_parts(fixture["valid"], run_id=fixture["run_id"]) == ()


def test_parity_fixture_invalid_parts_refuse():
    fixture = _parity_fixture()
    for entry in fixture["invalid"]:
        part = _expand(entry)
        violations = dc.validate_report_parts([part], run_id=fixture["run_id"])
        assert violations, f"expected a violation for: {entry['reason']}"


def test_validate_report_parts_empty_list_refuses():
    assert dc.validate_report_parts([], run_id=_RUN) != ()


def test_persist_parts_backstop_refuses_invariance_violations():
    issues, fake = _issues()
    with pytest.raises(ValueError, match="invariance rule"):
        _persist(issues, ["has <!-- perk:metadata-block:x --> inside"])
    assert fake.post_calls == []


# --- the transfer boundary model --------------------------------------------------------------


def test_transfer_model_round_trips():
    transfer = dc.DreamReportTransferModel.model_validate(
        {"schema_version": "1", "run_id": _RUN, "parts": ["one", "two"]}
    )
    assert transfer.run_id == _RUN
    assert transfer.parts == ("one", "two")


@pytest.mark.parametrize(
    "raw",
    [
        {"schema_version": "2", "run_id": _RUN, "parts": ["one"]},  # wrong version
        {"schema_version": "1", "run_id": _RUN, "parts": []},  # empty parts
        {"schema_version": "1", "run_id": _RUN, "parts": ["  "]},  # blank part
        {"schema_version": "1", "run_id": _RUN, "parts": ["ok"], "origin": "x"},  # unknown key
        {"schema_version": "1", "parts": ["ok"]},  # missing run_id
    ],
)
def test_transfer_model_rejects_malformed(raw: dict):
    with pytest.raises(Exception, match="validation error"):
        dc.DreamReportTransferModel.model_validate(raw)


def test_transfer_filename_parity():
    # The TS mirror (extension/pi/v1/objectiveAuthoring.ts DREAM_REPORT_TRANSFER_FILENAME) pins
    # the same literal.
    assert dc.DREAM_REPORT_TRANSFER_FILENAME == "dream-report-transfer.json"
