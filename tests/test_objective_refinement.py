"""Objective-node refinement — codec, model, service, and selection (contracts.md §8.67).

Offline, backend-free: the codec is exercised on exact bytes; the service runs over minimal
in-memory ``ObjectiveStore``/``IssueBackend`` doubles whose guarded upsert is scripted, so every
row of the public error-mapping table and every selection rule is pinned explicitly. The real
Linear store/adapter integration lives in ``test_linear_refinement.py``.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import pytest

from perk.backends import issue_backend, objective_store
from perk.backends.engagement import EngagementAuthor, EngagementComment
from perk.backends.issue_backend import (
    CommentResult,
    IssueBackend,
    MarkedCommentError,
    MarkedCommentExpectation,
    scan_marked_comments,
)
from perk.backends.objective_store import ObjectiveStore
from perk.objective import NodeStatus
from perk.objective.refinement import codec, service
from perk.objective.refinement.models import (
    RefinementCodeBasis,
    RefinementDocument,
    RefinementError,
    RefinementErrorCode,
    RefinementIdentity,
    RefinementObjectiveSnapshot,
    RefinementProvenance,
    RefinementRead,
    RefinementSaveRequest,
    RefinementSource,
    RefinementTarget,
    SavedRefinement,
)

# --------------------------------------------------------------------------- fixtures

HEAD = "a" * 40
TS = "2026-09-07T12:34:56Z"
# Golden pins (computed once from the exact canonical encodings; a drift here is a wire break).
GOLDEN_IDENTITY_JSON = (
    '{"backend":"linear","carrier_id":"iss-node12","node_id":"1.2",'
    '"objective_id":"proj-11","objective_run_id":"01RUNOBJ"}'
)
GOLDEN_TARGET_KEY = "d2dfbd7a5e1caa6c89bd424bada36565efaa8fc7257ac63eceb856dd3072ca14"
GOLDEN_SOURCE_DIGEST = "2d087859c16fef0b3aaa20bb10d0cadca109416152ccc54e252940946b707656"


def _identity(**overrides: str) -> RefinementIdentity:
    fields: dict[str, str] = {
        "backend": "linear",
        "objective_id": "proj-11",
        "objective_run_id": "01RUNOBJ",
        "node_id": "1.2",
        "carrier_id": "iss-node12",
    }
    fields.update(overrides)
    return RefinementIdentity(**fields)


def _source(**overrides: object) -> RefinementSource:
    fields: dict[str, object] = {
        "description": "Ship the thing",
        "slug": "ship-the-thing",
        "comment": None,
        "depends_on": None,
        "effective_depends_on": ("1.1",),
        "issue_description": "Ship the thing\n\nHuman notes.",
    }
    fields.update(overrides)
    return RefinementSource(**fields)


def _provenance(**overrides: object) -> RefinementProvenance:
    basis = RefinementCodeBasis(head_sha=HEAD, dirty=False, captured_at=TS)
    fields: dict[str, object] = {"authoring_run_id": "01AUTHRUN", "authored_at": TS}
    fields.update(overrides)
    return RefinementProvenance(code_basis=basis, **fields)


def _document(
    *,
    identity: RefinementIdentity | None = None,
    source: RefinementSource | None = None,
    provenance: RefinementProvenance | None = None,
    markdown: str = "## Approach\n\nDo it carefully.\n",
    source_digest: str | None = None,
) -> RefinementDocument:
    src = source if source is not None else _source()
    return RefinementDocument(
        identity=identity if identity is not None else _identity(),
        source=src,
        source_digest=source_digest if source_digest is not None else codec.source_digest(src),
        provenance=provenance if provenance is not None else _provenance(),
        markdown=markdown,
    )


def _comment(body: str, *, cid: str = "c-1", edited: str | None = None) -> EngagementComment:
    return EngagementComment(
        id=cid,
        body=body,
        created_at="2026-09-07T12:00:00.123Z",
        edited_at=edited,
        author=EngagementAuthor(kind="perk", display_name="perk", id=None),
    )


def _target(
    *,
    identity: RefinementIdentity | None = None,
    source: RefinementSource | None = None,
    status: NodeStatus = NodeStatus.PENDING,
    plan_ref: str | None = None,
    has_plan_metadata: bool = False,
) -> RefinementTarget:
    src = source if source is not None else _source()
    ident = identity if identity is not None else _identity()
    return RefinementTarget(
        identity=ident,
        source=src,
        source_digest=codec.source_digest(src),
        carrier_identifier="ENG-12",
        carrier_url="https://linear.app/test/issue/ENG-12",
        status=status,
        plan_ref=plan_ref,
        has_plan_metadata=has_plan_metadata,
    )


def _snapshot(*targets: RefinementTarget) -> RefinementObjectiveSnapshot:
    return RefinementObjectiveSnapshot(
        backend="linear",
        objective_id="proj-11",
        objective_run_id="01RUNOBJ",
        objective_url="https://linear.app/test/project/proj-11",
        targets=tuple(targets),
    )


def _inline(body: str) -> str:
    """The Linear transcoder's marker rewrite, applied locally (the parser accepts both)."""
    return body.replace("<!-- perk:objective-refinement", "`perk:objective-refinement").replace(
        " -->", "`", 1
    )


# --------------------------------------------------------------------------- codec: scalars


class TestCanonicalEncodings:
    def test_identity_json_and_target_key_golden(self) -> None:
        assert codec.canonical_json(codec._identity_mapping(_identity())) == GOLDEN_IDENTITY_JSON
        assert codec.target_key(_identity()) == GOLDEN_TARGET_KEY
        assert (
            codec.target_key(_identity())
            == hashlib.sha256(GOLDEN_IDENTITY_JSON.encode("utf-8")).hexdigest()
        )

    def test_source_digest_golden_and_null_vs_empty_distinct(self) -> None:
        assert codec.source_digest(_source()) == GOLDEN_SOURCE_DIGEST
        assert codec.source_digest(_source(depends_on=())) != GOLDEN_SOURCE_DIGEST

    def test_source_digest_excludes_everything_but_the_six_fields(self) -> None:
        # Two targets differing only in status / backlink / carrier addressing hash equal.
        a = _target(status=NodeStatus.PENDING)
        b = _target(status=NodeStatus.DONE, plan_ref="#ENG-12", has_plan_metadata=True)
        assert a.source_digest == b.source_digest

    def test_canonical_json_escapes_non_ascii_and_line_separators(self) -> None:
        text = codec.canonical_json({"z": "é\u2028", "a": 1})
        assert text == '{"a":1,"z":"\\u00e9\\u2028"}'
        assert "\u2028" not in text

    @pytest.mark.parametrize(
        "value",
        ["2026-09-07T12:34:56Z", "2024-02-29T00:00:00Z", "1999-12-31T23:59:59Z"],
    )
    def test_canonical_timestamps(self, value: str) -> None:
        assert codec.is_canonical_timestamp(value)

    @pytest.mark.parametrize(
        "value",
        [
            "2026-09-07T12:34:56.000Z",  # fractional seconds
            "2026-09-07T12:34:56+00:00",  # numeric offset
            "2026-09-07T12:34:56",  # no Z
            "2026-09-07 12:34:56Z",  # space separator
            "2026-9-7T12:34:56Z",  # lenient widths
            "2026-02-30T12:34:56Z",  # invalid calendar date
            "2026-09-07T24:00:00Z",  # invalid time
            "2026-09-07t12:34:56z",  # lowercase
            "",
        ],
    )
    def test_noncanonical_timestamps_refused(self, value: str) -> None:
        assert not codec.is_canonical_timestamp(value)

    def test_format_timestamp_converts_aware_and_drops_microseconds(self) -> None:
        moment = datetime(2026, 9, 7, 14, 34, 56, 789000, tzinfo=timezone(timedelta(hours=2)))
        assert codec.format_timestamp(moment) == "2026-09-07T12:34:56Z"
        assert codec.is_canonical_timestamp(codec.format_timestamp(datetime.now(UTC)))

    def test_format_timestamp_refuses_naive(self) -> None:
        with pytest.raises(ValueError, match="aware"):
            codec.format_timestamp(datetime(2026, 9, 7, 12, 0, 0))

    @pytest.mark.parametrize(
        "digest",
        [GOLDEN_TARGET_KEY.upper(), "sha256:" + GOLDEN_TARGET_KEY, GOLDEN_TARGET_KEY[:63], ""],
    )
    def test_source_digest_refusals(self, digest: str) -> None:
        findings = codec.document_findings(_document(source_digest=digest))
        assert any("source_digest" in f for f in findings)

    @pytest.mark.parametrize("sha", ["abc1234", HEAD.upper(), HEAD[:39], HEAD + "a"])
    def test_head_sha_refusals(self, sha: str) -> None:
        basis = RefinementCodeBasis(head_sha=sha, dirty=False, captured_at=TS)
        prov = RefinementProvenance(authoring_run_id="r", authored_at=TS, code_basis=basis)
        assert any("head_sha" in f for f in codec.document_findings(_document(provenance=prov)))

    def test_dependency_order_and_uniqueness_findings(self) -> None:
        assert codec.source_findings(_source(effective_depends_on=("1.10", "1.2")))
        assert codec.source_findings(_source(depends_on=("1.1", "1.1")))
        assert codec.source_findings(_source(depends_on=(" ",)))
        assert codec.source_findings(_source(depends_on=("1.2", "1.10"))) == []

    def test_blank_identity_and_provenance_fields(self) -> None:
        assert codec.identity_findings(_identity(node_id=" "))
        assert codec.identity_findings(_identity(carrier_id=""))
        assert codec.provenance_findings(_provenance(authoring_run_id=""))
        assert codec.provenance_findings(_provenance(authored_at="2026-09-07T12:34:56.5Z"))

    def test_blank_markdown_is_a_finding(self) -> None:
        assert "markdown is blank" in codec.document_findings(_document(markdown=" \n"))


# --------------------------------------------------------------------------- codec: envelope


class TestRenderAndParse:
    def test_exact_envelope_bytes(self) -> None:
        doc = _document(markdown="Body\n")
        rendered = codec.render_refinement(doc)
        marker = f"<!-- perk:objective-refinement:v1:{GOLDEN_TARGET_KEY} -->"
        preamble = marker + "\n\n# Objective node refinement (advisory)\n\n```json\n"
        assert rendered.startswith(preamble)
        header_line, tail = rendered[len(preamble) :].split("\n", 1)
        assert tail == "```\n\nBody\n"
        header = json.loads(header_line)
        assert header == {
            "schema_version": "1",
            "identity": json.loads(GOLDEN_IDENTITY_JSON),
            "source": {
                "description": "Ship the thing",
                "slug": "ship-the-thing",
                "comment": None,
                "depends_on": None,
                "effective_depends_on": ["1.1"],
                "issue_description": "Ship the thing\n\nHuman notes.",
            },
            "source_digest": GOLDEN_SOURCE_DIGEST,
            "provenance": {
                "authoring_run_id": "01AUTHRUN",
                "authored_at": TS,
                "code_basis": {"head_sha": HEAD, "dirty": False, "captured_at": TS},
            },
        }
        # Canonical: sorted keys, no whitespace, single line.
        assert header_line == codec.canonical_json(header)
        assert "\n" not in header_line

    def test_round_trip_html_and_inline_forms_with_full_field_conversion(self) -> None:
        markdown = (
            "## Long\n\n```md\n<!-- perk:metadata-block:plan-body -->\nnested fence\n```\n"
            "| a | b |\n|---|---|\n| ü | 東京 |\n\n\n"
        )
        doc = _document(markdown=markdown)
        for body in (codec.render_refinement(doc), _inline(codec.render_refinement(doc))):
            saved = codec.parse_refinement_comment(_comment(body, edited="2026-09-08T00:00:00Z"))
            assert saved is not None
            assert saved.document == doc
            assert saved.body_digest == hashlib.sha256(body.encode("utf-8")).hexdigest()
            assert saved.saved_at == "2026-09-08T00:00:00Z"
            assert saved.comment.created_at == "2026-09-07T12:00:00.123Z"

    def test_markdown_tail_preserved_verbatim_including_trailing_content(self) -> None:
        doc = _document(markdown="x\n\n```\nunclosed fence\n\n\n")
        saved = codec.parse_refinement_comment(_comment(codec.render_refinement(doc)))
        assert saved is not None and saved.document.markdown == "x\n\n```\nunclosed fence\n\n\n"

    def test_unrelated_comments_are_none(self) -> None:
        assert codec.parse_refinement_comment(_comment("just a note")) is None
        assert codec.parse_refinement_comment(_comment("")) is None
        # An ordinary mention of the family name is not a marker.
        assert (
            codec.parse_refinement_comment(
                _comment("see perk:objective-refinement:v1 markers for details")
            )
            is None
        )
        # A marker below the first line does not make the comment a family record.
        rendered = codec.render_refinement(_document())
        assert codec.parse_refinement_comment(_comment("# plan\n" + rendered)) is None

    def test_unknown_header_keys_ignored(self) -> None:
        rendered = codec.render_refinement(_document())
        head, rest = rendered.split("```json\n", 1)
        line, tail = rest.split("\n", 1)
        header = json.loads(line)
        header["future_field"] = {"x": 1}
        header["identity"]["extra"] = "ignored"
        patched = head + "```json\n" + json.dumps(header) + "\n" + tail
        saved = codec.parse_refinement_comment(_comment(patched))
        assert saved is not None and saved.document == _document()

    @staticmethod
    def _mutate_header(rendered: str, mutate) -> str:
        head, rest = rendered.split("```json\n", 1)
        line, tail = rest.split("\n", 1)
        header = json.loads(line)
        mutate(header)
        return head + "```json\n" + json.dumps(header) + "\n" + tail

    def _expect_malformed(self, body: str, match: str) -> RefinementError:
        with pytest.raises(RefinementError) as info:
            codec.parse_refinement_comment(_comment(body, cid="c-x"))
        assert info.value.code is RefinementErrorCode.MALFORMED_REFINEMENT
        assert info.value.write_attempted is False
        assert info.value.comment_ids == ("c-x",)
        assert match in str(info.value)
        return info.value

    def test_malformed_variants_fail_not_disappear(self) -> None:
        rendered = codec.render_refinement(_document())

        def drop_identity_field(h: dict) -> None:
            del h["identity"]["carrier_id"]

        def drop_provenance(h: dict) -> None:
            del h["provenance"]

        def bad_version(h: dict) -> None:
            h["schema_version"] = "2"

        def bad_digest(h: dict) -> None:
            h["source_digest"] = "0" * 64

        def bad_time(h: dict) -> None:
            h["provenance"]["authored_at"] = "2026-09-07T12:34:56.000Z"

        def bad_sha(h: dict) -> None:
            h["provenance"]["code_basis"]["head_sha"] = "abc123"

        def dirty_not_bool(h: dict) -> None:
            h["provenance"]["code_basis"]["dirty"] = 1

        def key_mismatch(h: dict) -> None:
            h["identity"]["node_id"] = "1.3"

        def omitted_nullable(h: dict) -> None:
            del h["source"]["slug"]

        self._expect_malformed(self._mutate_header(rendered, drop_identity_field), "header fields")
        self._expect_malformed(self._mutate_header(rendered, drop_provenance), "header fields")
        self._expect_malformed(self._mutate_header(rendered, bad_version), "schema_version")
        self._expect_malformed(self._mutate_header(rendered, bad_digest), "source_digest")
        self._expect_malformed(self._mutate_header(rendered, bad_time), "authored_at")
        self._expect_malformed(self._mutate_header(rendered, bad_sha), "head_sha")
        self._expect_malformed(self._mutate_header(rendered, dirty_not_bool), "header fields")
        self._expect_malformed(self._mutate_header(rendered, key_mismatch), "marker key")
        self._expect_malformed(self._mutate_header(rendered, omitted_nullable), "header fields")
        # Envelope damage.
        self._expect_malformed(rendered.replace("```json\n{", "```json\n{{", 1), "not valid JSON")
        self._expect_malformed(rendered.replace("```json\n{", "```json\n[{", 1), "not valid JSON")
        self._expect_malformed(rendered.replace("```json\n", "```json\n\n", 1), "not closed")
        self._expect_malformed(rendered.replace("(advisory)", "(edited)"), "title/header fence")
        self._expect_malformed(rendered.replace("\n```\n\n", "\n```\n", 1), "not closed")
        header_only = rendered.split("\n```\n\n", 1)[0] + "\n```\n\n"
        self._expect_malformed(header_only + "   \n", "markdown is blank")
        self._expect_malformed(header_only, "markdown is blank")
        # A bad marker key.
        first, rest = rendered.split("\n", 1)
        self._expect_malformed(
            f"<!-- perk:objective-refinement:v1:{GOLDEN_TARGET_KEY.upper()} -->\n" + rest,
            "marker key",
        )
        self._expect_malformed("<!-- perk:objective-refinement:v1:short -->\n" + rest, "marker key")
        # The exact ownership marker repeated in the document.
        self._expect_malformed(rendered + "\n" + first, "repeated")

    def test_is_refinement_comment_ownership_predicate(self) -> None:
        rendered = codec.render_refinement(_document())
        assert codec.is_refinement_comment(rendered)
        assert codec.is_refinement_comment(_inline(rendered))
        # Damaged owned record: still owned (must never become a plan).
        assert codec.is_refinement_comment(rendered.replace("```json\n{", "```json\n{{", 1))
        assert codec.is_refinement_comment("<!-- perk:objective-refinement:v1:junk -->\r\nx")
        # Mentions later in a real plan do not change its kind.
        plan_body = "<!-- perk:metadata-block:plan-body -->\n# Plan\n" + rendered
        assert not codec.is_refinement_comment(plan_body)
        assert not codec.is_refinement_comment("perk:objective-refinement:v1 is the family\nx")
        assert not codec.is_refinement_comment("")


# --------------------------------------------------------------------------- codec: discovery


class TestTargetDiscovery:
    def test_absent_and_foreign_records_ignored(self) -> None:
        identity = _identity()
        foreign = codec.render_refinement(_document(identity=_identity(objective_run_id="OLD")))
        historical = codec.render_refinement(_document(identity=_identity(carrier_id="moved")))
        comments = [_comment("hello", cid="h"), _comment(foreign, cid="f"), _comment(historical)]
        assert codec.find_target_refinement(comments, identity) is None
        # A foreign record with a broken payload is still ignored — never rebound, never parsed.
        broken_foreign = foreign.replace("```json\n{", "```json\n{{", 1)
        assert codec.find_target_refinement([_comment(broken_foreign, cid="bf")], identity) is None

    def test_neighboring_node_identities_are_distinct(self) -> None:
        keys = {codec.target_key(_identity(node_id=n)) for n in ("1.1", "1.2", "1.10", "2.1")}
        assert len(keys) == 4
        comments = [
            _comment(codec.render_refinement(_document(identity=_identity(node_id=n))), cid=n)
            for n in ("1.1", "1.2", "1.10")
        ]
        found = codec.find_target_refinement(comments, _identity(node_id="1.10"))
        assert found is not None and found.comment.id == "1.10"
        found_12 = codec.find_target_refinement(comments, _identity(node_id="1.2"))
        assert found_12 is not None and found_12.comment.id == "1.2"

    def test_finds_the_unique_record_on_a_later_position(self) -> None:
        rendered = codec.render_refinement(_document())
        comments = [_comment(f"noise {i}", cid=f"n{i}") for i in range(120)]
        comments.append(_comment(_inline(rendered), cid="late"))
        found = codec.find_target_refinement(comments, _identity())
        assert found is not None and found.comment.id == "late"

    def test_duplicates_are_ambiguous_even_when_equal_and_before_payload_parse(self) -> None:
        rendered = codec.render_refinement(_document())
        broken = rendered.replace("```json\n{", "```json\n{{", 1)
        with pytest.raises(RefinementError) as info:
            codec.find_target_refinement(
                [_comment(rendered, cid="a"), _comment(rendered, cid="b")], _identity()
            )
        assert info.value.code is RefinementErrorCode.AMBIGUOUS_REFINEMENT
        assert info.value.comment_ids == ("a", "b")
        # Two BROKEN copies: ambiguity is decided from the marker headers first.
        with pytest.raises(RefinementError) as info2:
            codec.find_target_refinement(
                [_comment(broken, cid="a"), _comment(broken, cid="b")], _identity()
            )
        assert info2.value.code is RefinementErrorCode.AMBIGUOUS_REFINEMENT

    def test_misplaced_and_repeated_markers_are_malformed(self) -> None:
        rendered = codec.render_refinement(_document())
        marker = rendered.split("\n", 1)[0]
        with pytest.raises(RefinementError) as info:
            codec.find_target_refinement([_comment("intro\n" + rendered, cid="m")], _identity())
        assert info.value.code is RefinementErrorCode.MALFORMED_REFINEMENT
        assert info.value.comment_ids == ("m",)
        with pytest.raises(RefinementError) as info2:
            codec.find_target_refinement([_comment(rendered + "\n" + marker, cid="r")], _identity())
        assert info2.value.code is RefinementErrorCode.MALFORMED_REFINEMENT
        # The exact target marker embedded in an unrelated comment is misplaced too.
        with pytest.raises(RefinementError):
            codec.find_target_refinement([_comment("see " + marker, cid="u")], _identity())

    def test_family_record_with_unreadable_key_is_malformed(self) -> None:
        rendered = codec.render_refinement(_document())
        rest = rendered.split("\n", 1)[1]
        bad = "<!-- perk:objective-refinement:v1:not-a-key -->\n" + rest
        with pytest.raises(RefinementError) as info:
            codec.find_target_refinement([_comment(bad, cid="bad")], _identity())
        assert info.value.code is RefinementErrorCode.MALFORMED_REFINEMENT

    def test_unique_record_with_mismatched_identity_is_malformed(self) -> None:
        # Marker key matches the target but the header names another identity.
        rendered = codec.render_refinement(_document())
        other = codec.render_refinement(_document(identity=_identity(node_id="1.3")))
        spliced = rendered.split("\n", 1)[0] + "\n" + other.split("\n", 1)[1]
        with pytest.raises(RefinementError) as info:
            codec.find_target_refinement([_comment(spliced, cid="s")], _identity())
        assert info.value.code is RefinementErrorCode.MALFORMED_REFINEMENT


class TestScanMarkedComments:
    def test_exact_first_line_only_in_either_form(self) -> None:
        forms = ("<!-- perk:x:KEY -->", "`perk:x:KEY`")
        owned_html = _comment("<!-- perk:x:KEY -->\nbody", cid="a")
        owned_inline = _comment("`perk:x:KEY`\nbody", cid="b")
        prefix = _comment("<!-- perk:x:KEY2 -->\nbody", cid="c")  # a longer key never matches
        misplaced = _comment("x\n<!-- perk:x:KEY -->", cid="d")
        repeated = _comment("<!-- perk:x:KEY -->\n<!-- perk:x:KEY -->", cid="e")
        indented = _comment("  <!-- perk:x:KEY -->\nbody", cid="f")
        scan = scan_marked_comments(
            [owned_html, owned_inline, prefix, misplaced, repeated, indented], forms=forms
        )
        assert [c.id for c in scan.owned] == ["a", "b"]
        assert [c.id for c in scan.malformed] == ["d", "e", "f"]


# --------------------------------------------------------------------------- models


class TestModelProperties:
    @pytest.mark.parametrize(
        ("status", "plan_ref", "has_meta", "eligible"),
        [
            (NodeStatus.PENDING, None, False, True),
            (NodeStatus.BLOCKED, None, False, True),
            (NodeStatus.PLANNING, None, False, False),
            (NodeStatus.IN_PROGRESS, None, False, False),
            (NodeStatus.DONE, None, False, False),
            (NodeStatus.SKIPPED, None, False, False),
            (NodeStatus.PENDING, "#ENG-12", False, False),
            (NodeStatus.BLOCKED, None, True, False),
            (NodeStatus.PENDING, "#ENG-12", True, False),
        ],
    )
    def test_eligibility_predicate(
        self, status: NodeStatus, plan_ref: str | None, has_meta: bool, eligible: bool
    ) -> None:
        target = _target(status=status, plan_ref=plan_ref, has_plan_metadata=has_meta)
        assert target.eligible is eligible

    def test_read_properties(self) -> None:
        target = _target()
        absent = RefinementRead(target=target, saved=None)
        assert absent.source_changed is False
        assert absent.expected == MarkedCommentExpectation(None, None)
        saved = codec.parse_refinement_comment(_comment(codec.render_refinement(_document())))
        assert saved is not None
        present = RefinementRead(target=target, saved=saved)
        assert present.source_changed is False
        assert present.expected == MarkedCommentExpectation("c-1", saved.body_digest)
        drifted = RefinementRead(target=_target(source=_source(description="Other")), saved=saved)
        assert drifted.source_changed is True  # advisory: still present
        assert drifted.saved is saved
        assert saved.saved_at == saved.comment.created_at

    @pytest.mark.parametrize(
        ("cid", "digest", "problem"),
        [
            (None, None, None),
            ("c", "0" * 64, None),
            ("c", None, "both"),
            (None, "0" * 64, "both"),
            (" ", "0" * 64, "blank"),
            ("c", "0" * 63, "canonical"),
            ("c", "A" * 64, "canonical"),
        ],
    )
    def test_expectation_validation(self, cid: str | None, digest: str | None, problem) -> None:
        got = MarkedCommentExpectation(cid, digest).validation_problem()
        if problem is None:
            assert got is None
        else:
            assert got is not None and problem in got


# --------------------------------------------------------------------------- service doubles


class _Store:
    """An ``ObjectiveStore`` double for the refinement read: a preset snapshot, ``None``, or an
    exception; every call is counted so "no dummy-node probe / no capability flag" is provable."""

    backend_id = "linear"

    def __init__(self, result: RefinementObjectiveSnapshot | None | Exception) -> None:
        self.result = result
        self.calls: list[str] = []

    def read_node_refinement_targets(
        self, *, objective_id: str
    ) -> RefinementObjectiveSnapshot | None:
        self.calls.append(objective_id)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _Issues:
    """An ``IssueBackend`` double: comments per carrier id, a scripted guarded upsert."""

    backend_id = "linear"

    def __init__(
        self,
        comments: dict[str, list[EngagementComment]] | None = None,
        *,
        upsert: CommentResult | Exception | None = None,
        read_error: Exception | None = None,
    ) -> None:
        self.comments = comments or {}
        self.upsert = upsert
        self.read_error = read_error
        self.reads: list[str] = []
        self.upserts: list[dict[str, object]] = []

    def read_comments(self, *, issue_id: str) -> tuple[EngagementComment, ...]:
        self.reads.append(issue_id)
        if self.read_error is not None:
            raise self.read_error
        return tuple(self.comments.get(issue_id, ()))

    def upsert_marked_comment(
        self,
        *,
        issue_id: str,
        marker: str,
        body: str,
        dry_run: bool = False,
        expected: MarkedCommentExpectation | None = None,
    ) -> CommentResult:
        self.upserts.append(
            {"issue_id": issue_id, "marker": marker, "body": body, "expected": expected}
        )
        if isinstance(self.upsert, Exception):
            raise self.upsert
        assert self.upsert is not None, "upsert not scripted"
        return self.upsert


def _read(store: _Store, issues: _Issues, *, objective_id: str, node_id: str) -> RefinementRead:
    return service.read_node_refinement(
        cast("ObjectiveStore", store),
        cast("IssueBackend", issues),
        objective_id=objective_id,
        node_id=node_id,
    )


def _select(
    store: _Store, issues: _Issues, *, objective_id: str, node_id: str | None = None
) -> RefinementRead:
    return service.select_refinement_target(
        cast("ObjectiveStore", store),
        cast("IssueBackend", issues),
        objective_id=objective_id,
        node_id=node_id,
    )


def _save(store: _Store, issues: _Issues, *, request: RefinementSaveRequest) -> SavedRefinement:
    return service.save_node_refinement(
        cast("ObjectiveStore", store), cast("IssueBackend", issues), request=request
    )


def _saved_comment(document: RefinementDocument, cid: str = "c-1") -> EngagementComment:
    return _comment(_inline(codec.render_refinement(document)), cid=cid)


def _err(fn, code: RefinementErrorCode, **kwargs) -> RefinementError:
    with pytest.raises(RefinementError) as info:
        fn()
    assert info.value.code is code, str(info.value)
    for key, value in kwargs.items():
        assert getattr(info.value, key) == value, (key, getattr(info.value, key))
    return info.value


# --------------------------------------------------------------------------- service: read


class TestReadNodeRefinement:
    def test_absent_and_present_and_stale_reads(self) -> None:
        target = _target()
        store = _Store(_snapshot(target))
        issues = _Issues({"iss-node12": []})
        read = _read(store, issues, objective_id="proj-11", node_id="1.2")
        assert read.saved is None and read.target == target
        assert issues.reads == ["iss-node12"]

        doc = _document()
        issues = _Issues({"iss-node12": [_saved_comment(doc)]})
        read = _read(store, issues, objective_id="proj-11", node_id="1.2")
        assert read.saved is not None and read.saved.document == doc
        assert read.source_changed is False

        # A changed source: still present, advisory flag set, no requeue.
        drifted = _Store(_snapshot(_target(source=_source(description="Changed"))))
        read = _read(drifted, issues, objective_id="proj-11", node_id="1.2")
        assert read.saved is not None and read.source_changed is True

    @pytest.mark.parametrize(
        "status", [NodeStatus.PLANNING, NodeStatus.IN_PROGRESS, NodeStatus.DONE, NodeStatus.SKIPPED]
    )
    def test_all_statuses_readable(self, status: NodeStatus) -> None:
        doc = _document()
        store = _Store(
            _snapshot(_target(status=status, plan_ref="#ENG-12", has_plan_metadata=True))
        )
        issues = _Issues({"iss-node12": [_saved_comment(doc)]})
        read = _read(store, issues, objective_id="proj-11", node_id="1.2")
        assert read.saved is not None and read.target.eligible is False

    def test_mapping_rows_on_read(self) -> None:
        issues = _Issues({"iss-node12": []})

        def read(store, iss=issues):
            return lambda: _read(store, iss, objective_id="proj-11", node_id="1.2")

        unsupported = _Store(
            objective_store.RefinementTargetReadError("unsupported_backend", "nope")
        )
        _err(read(unsupported), RefinementErrorCode.UNSUPPORTED_BACKEND, write_attempted=False)
        assert issues.reads == []  # refused before any comment read
        _err(read(_Store(None)), RefinementErrorCode.OBJECTIVE_NOT_FOUND)
        _err(read(_Store(_snapshot())), RefinementErrorCode.NODE_NOT_FOUND)
        _err(
            read(_Store(objective_store.RefinementTargetReadError("malformed_target", "m"))),
            RefinementErrorCode.MALFORMED_TARGET,
        )
        _err(
            read(_Store(objective_store.RefinementTargetReadError("ambiguous_target", "a"))),
            RefinementErrorCode.AMBIGUOUS_TARGET,
        )
        boom = _err(
            read(_Store(objective_store.ObjectiveStoreError("transport down"))),
            RefinementErrorCode.BACKEND_ERROR,
        )
        assert isinstance(boom.__cause__, objective_store.ObjectiveStoreError)
        store = _Store(_snapshot(_target()))
        failing = _Issues(read_error=issue_backend.IssueBackendError("comments down"))
        _err(read(store, failing), RefinementErrorCode.BACKEND_ERROR)
        broken = codec.render_refinement(_document()).replace("```json\n{", "```json\n{{", 1)
        _err(
            read(store, _Issues({"iss-node12": [_comment(broken, cid="b")]})),
            RefinementErrorCode.MALFORMED_REFINEMENT,
            comment_ids=("b",),
            write_attempted=False,
        )
        dup = _saved_comment(_document())
        _err(
            read(store, _Issues({"iss-node12": [dup, _comment(dup.body, cid="c-2")]})),
            RefinementErrorCode.AMBIGUOUS_REFINEMENT,
            comment_ids=("c-1", "c-2"),
        )

    def test_backend_mismatch_is_invalid_input(self) -> None:
        store = _Store(_snapshot(_target()))
        issues = _Issues()
        issues.backend_id = "github"
        _err(
            lambda: _read(
                store,
                issues,
                objective_id="proj-11",
                node_id="1.2",
            ),
            RefinementErrorCode.INVALID_INPUT,
        )
        assert store.calls == []


# --------------------------------------------------------------------------- service: select


def _targets_for_selection() -> list[RefinementTarget]:
    def t(node_id: str, **kw) -> RefinementTarget:
        return _target(identity=_identity(node_id=node_id, carrier_id=f"iss-{node_id}"), **kw)

    return [
        t("1.1", status=NodeStatus.DONE, plan_ref="#ENG-1", has_plan_metadata=True),
        t("1.10", status=NodeStatus.PENDING),  # deliberately listed before 1.2
        t("1.2", status=NodeStatus.IN_PROGRESS, plan_ref="#ENG-2", has_plan_metadata=True),
        t("1.3", status=NodeStatus.PENDING, has_plan_metadata=True),  # contradictory: plan metadata
        t("1.4", status=NodeStatus.BLOCKED),  # far-future, dependency-blocked
        t("1.5", status=NodeStatus.PLANNING),
        t("2.1", status=NodeStatus.PENDING),
    ]


class TestSelectRefinementTarget:
    def test_default_selection_walks_natural_order_ignoring_readiness(self) -> None:
        targets = _targets_for_selection()
        store = _Store(_snapshot(*targets))
        issues = _Issues()
        read = _select(store, issues, objective_id="proj-11")
        # 1.4 (blocked, no plan) is the first eligible absence in natural order — its
        # dependency readiness is irrelevant; 1.3's plan metadata disqualifies it.
        assert read.target.identity.node_id == "1.4" and read.saved is None
        # Only eligible nodes were read: never the done/in-progress/planning/plan-bearing ones.
        assert issues.reads == ["iss-1.4"]

    def test_default_selection_skips_valid_and_stale_records_and_orders_1_2_before_1_10(
        self,
    ) -> None:
        a = _target(identity=_identity(node_id="1.10", carrier_id="iss-1.10"))
        b = _target(identity=_identity(node_id="1.2", carrier_id="iss-1.2"))
        c = _target(identity=_identity(node_id="1.3", carrier_id="iss-1.3"))
        stale_doc = _document(identity=b.identity, source=_source(description="old"))
        issues = _Issues({"iss-1.2": [_saved_comment(stale_doc)]})
        store = _Store(_snapshot(a, b, c))
        read = _select(store, issues, objective_id="proj-11")
        # 1.2 has a (stale but valid) record → skipped, never re-selected; 1.3 is next.
        assert read.target.identity.node_id == "1.3"
        assert issues.reads == ["iss-1.2", "iss-1.3"]

    def test_default_selection_stops_on_malformed_or_ambiguous_eligible_record(self) -> None:
        a = _target(identity=_identity(node_id="1.1", carrier_id="iss-1.1"))
        b = _target(identity=_identity(node_id="1.2", carrier_id="iss-1.2"))
        broken = codec.render_refinement(_document(identity=a.identity)).replace("{", "{{", 1)
        issues = _Issues({"iss-1.1": [_comment(broken, cid="bad")]})
        store = _Store(_snapshot(a, b))
        _err(
            lambda: _select(store, issues, objective_id="proj-11"),
            RefinementErrorCode.MALFORMED_REFINEMENT,
            comment_ids=("bad",),
        )
        assert issues.reads == ["iss-1.1"]
        good = _saved_comment(_document(identity=a.identity), cid="g1")
        issues = _Issues({"iss-1.1": [good, _comment(good.body, cid="g2")]})
        _err(
            lambda: _select(store, issues, objective_id="proj-11"),
            RefinementErrorCode.AMBIGUOUS_REFINEMENT,
        )
        issues = _Issues(read_error=issue_backend.IssueBackendError("down"))
        _err(
            lambda: _select(store, issues, objective_id="proj-11"),
            RefinementErrorCode.BACKEND_ERROR,
        )

    def test_empty_and_exhausted_populations(self) -> None:
        issues = _Issues()
        _err(
            lambda: _select(
                _Store(_snapshot()),
                issues,
                objective_id="proj-11",
            ),
            RefinementErrorCode.NO_UNREFINED_NODE,
        )
        only = _target()
        refined = _Issues({"iss-node12": [_saved_comment(_document())]})
        _err(
            lambda: _select(
                _Store(_snapshot(only)),
                refined,
                objective_id="proj-11",
            ),
            RefinementErrorCode.NO_UNREFINED_NODE,
        )
        forbidden = [_target(status=s) for s in (NodeStatus.DONE, NodeStatus.SKIPPED)]
        _err(
            lambda: _select(
                _Store(_snapshot(*forbidden)),
                issues,
                objective_id="proj-11",
            ),
            RefinementErrorCode.NO_UNREFINED_NODE,
        )
        assert issues.reads == []

    def test_explicit_selection(self) -> None:
        targets = _targets_for_selection()
        store = _Store(_snapshot(*targets))
        doc = _document(identity=_identity(node_id="1.10", carrier_id="iss-1.10"))
        issues = _Issues({"iss-1.10": [_saved_comment(doc)]})
        # Explicit re-refinement: eligible + valid presence returns the record + its expectation.
        read = _select(store, issues, objective_id="proj-11", node_id="1.10")
        assert read.saved is not None and read.expected.comment_id == "c-1"
        for node_id in ("1.1", "1.2", "1.3", "1.5"):
            _err(
                lambda n=node_id: _select(
                    store,
                    issues,
                    objective_id="proj-11",
                    node_id=n,
                ),
                RefinementErrorCode.NODE_INELIGIBLE,
            )
        _err(
            lambda: _select(
                store,
                issues,
                objective_id="proj-11",
                node_id="9.9",
            ),
            RefinementErrorCode.NODE_NOT_FOUND,
        )
        # Ineligible explicit targets are refused before any comment read.
        assert issues.reads == ["iss-1.10"]

    def test_unsupported_store_refuses_before_network_without_capability_probe(self) -> None:
        store = _Store(objective_store.RefinementTargetReadError("unsupported_backend", "x"))
        issues = _Issues()
        _err(
            lambda: _select(store, issues, objective_id="proj-11"),
            RefinementErrorCode.UNSUPPORTED_BACKEND,
        )
        assert store.calls == ["proj-11"] and issues.reads == []


# --------------------------------------------------------------------------- service: save


def _request(
    document: RefinementDocument | None = None,
    expected: MarkedCommentExpectation | None = None,
) -> RefinementSaveRequest:
    return RefinementSaveRequest(
        document=document if document is not None else _document(),
        expected=expected if expected is not None else MarkedCommentExpectation(None, None),
    )


def _verified(document: RefinementDocument, cid: str = "c-new") -> CommentResult:
    return CommentResult(posted=True, verified_comment=_saved_comment(document, cid=cid))


class TestSaveNodeRefinement:
    def test_success_returns_the_verified_record_with_no_second_read(self) -> None:
        doc = _document()
        store = _Store(_snapshot(_target()))
        issues = _Issues({"iss-node12": []}, upsert=_verified(doc))
        saved = _save(store, issues, request=_request(doc))
        assert isinstance(saved, SavedRefinement)
        assert saved.comment.id == "c-new" and saved.document == doc
        assert issues.reads == ["iss-node12"]  # exactly the discovery read; none after the write
        [call] = issues.upserts
        assert call["issue_id"] == "iss-node12"
        assert call["marker"] == f"<!-- perk:objective-refinement:v1:{GOLDEN_TARGET_KEY} -->"
        assert call["body"] == codec.render_refinement(doc)
        assert call["expected"] == MarkedCommentExpectation(None, None)

    def test_expectation_is_retained_not_refreshed(self) -> None:
        doc = _document()
        prior = _saved_comment(doc, cid="c-old")
        store = _Store(_snapshot(_target()))
        issues = _Issues({"iss-node12": [prior]}, upsert=_verified(doc, cid="c-old"))
        request = _request(doc, MarkedCommentExpectation("c-old", "0" * 64))  # a stale digest
        _save(store, issues, request=request)
        assert issues.upserts[0]["expected"] == request.expected  # verbatim, never rebuilt

    def test_invalid_requests_refuse_before_any_backend_call(self) -> None:
        store = _Store(_snapshot(_target()))
        issues = _Issues()
        bad_requests = [
            _request(_document(markdown="  ")),
            _request(_document(source_digest="0" * 64)),
            _request(expected=MarkedCommentExpectation("c", None)),
            _request(expected=MarkedCommentExpectation("c", "xyz")),
            _request(_document(provenance=_provenance(authored_at="2026-09-07T12:34:56+00:00"))),
            _request(_document(identity=_identity(backend="github"))),
        ]
        for request in bad_requests:
            _err(
                lambda r=request: _save(store, issues, request=r),
                RefinementErrorCode.INVALID_INPUT,
                write_attempted=False,
            )
        assert store.calls == [] and issues.reads == [] and issues.upserts == []

    def test_precheck_precedence_identity_then_eligibility_then_source(self) -> None:
        issues = _Issues({"iss-node12": []})
        # Identity differs (a new objective run or a moved carrier) → stale_source.
        moved = _Store(_snapshot(_target(identity=_identity(carrier_id="iss-other"))))
        _err(
            lambda: _save(moved, issues, request=_request()),
            RefinementErrorCode.STALE_SOURCE,
        )
        # Ineligible wins over a changed source.
        claimed = _Store(
            _snapshot(
                _target(
                    status=NodeStatus.PLANNING,
                    source=_source(description="changed"),
                )
            )
        )
        _err(
            lambda: _save(claimed, issues, request=_request()),
            RefinementErrorCode.NODE_INELIGIBLE,
        )
        planned = _Store(_snapshot(_target(has_plan_metadata=True)))
        _err(
            lambda: _save(planned, issues, request=_request()),
            RefinementErrorCode.NODE_INELIGIBLE,
        )
        # Source digest changed → stale_source (sibling progress alone never changes it).
        drifted = _Store(_snapshot(_target(source=_source(issue_description="edited by human"))))
        _err(
            lambda: _save(drifted, issues, request=_request()),
            RefinementErrorCode.STALE_SOURCE,
        )
        missing = _Store(_snapshot())
        _err(
            lambda: _save(missing, issues, request=_request()),
            RefinementErrorCode.NODE_NOT_FOUND,
        )
        assert issues.reads == [] and issues.upserts == []

    def test_discovery_refusals_happen_before_the_upsert(self) -> None:
        store = _Store(_snapshot(_target()))
        broken = codec.render_refinement(_document()).replace("{", "{{", 1)
        issues = _Issues({"iss-node12": [_comment(broken, cid="b")]}, upsert=_verified(_document()))
        _err(
            lambda: _save(store, issues, request=_request()),
            RefinementErrorCode.MALFORMED_REFINEMENT,
            comment_ids=("b",),
            write_attempted=False,
        )
        dup = _saved_comment(_document())
        issues = _Issues(
            {"iss-node12": [dup, _comment(dup.body, cid="c-2")]}, upsert=_verified(_document())
        )
        _err(
            lambda: _save(store, issues, request=_request()),
            RefinementErrorCode.AMBIGUOUS_REFINEMENT,
        )
        assert issues.upserts == []

    @pytest.mark.parametrize(
        ("guarded_code", "expected_code"),
        [
            ("unsupported_backend", RefinementErrorCode.UNSUPPORTED_BACKEND),
            ("invalid_input", RefinementErrorCode.INVALID_INPUT),
            ("malformed_comment", RefinementErrorCode.MALFORMED_REFINEMENT),
            ("ambiguous_comment", RefinementErrorCode.AMBIGUOUS_REFINEMENT),
            ("stale_comment", RefinementErrorCode.STALE_REFINEMENT),
            ("backend_error", RefinementErrorCode.BACKEND_ERROR),
            ("write_unverified", RefinementErrorCode.WRITE_UNVERIFIED),
        ],
    )
    def test_guarded_upsert_codes_pass_through(self, guarded_code, expected_code) -> None:
        store = _Store(_snapshot(_target()))
        native = MarkedCommentError(
            guarded_code, "native detail", comment_ids=("x", "y"), write_attempted=True
        )
        issues = _Issues({"iss-node12": []}, upsert=native)
        err = _err(
            lambda: _save(store, issues, request=_request()),
            expected_code,
            comment_ids=("x", "y"),
            write_attempted=True,
        )
        assert err.__cause__ is native and "native detail" in str(err)

    def test_plain_backend_failure_maps_to_backend_error(self) -> None:
        store = _Store(_snapshot(_target()))
        issues = _Issues({"iss-node12": []}, upsert=issue_backend.IssueBackendError("boom"))
        _err(
            lambda: _save(store, issues, request=_request()),
            RefinementErrorCode.BACKEND_ERROR,
        )

    def test_missing_or_invalid_verified_result_is_write_unverified(self) -> None:
        store = _Store(_snapshot(_target()))
        cases = [
            CommentResult(posted=True, verified_comment=None),
            CommentResult(posted=True, verified_comment=_comment("not a refinement", cid="v")),
            CommentResult(
                posted=True,
                verified_comment=_comment(
                    codec.render_refinement(_document()).replace("{", "{{", 1), cid="v"
                ),
            ),
            _verified(_document(identity=_identity(node_id="1.3"))),
        ]
        for result in cases:
            issues = _Issues({"iss-node12": []}, upsert=result)
            _err(
                lambda i=issues: _save(store, i, request=_request()),
                RefinementErrorCode.WRITE_UNVERIFIED,
                write_attempted=True,
            )
            assert i_reads_once(issues)


def i_reads_once(issues: _Issues) -> bool:
    return issues.reads == ["iss-node12"]
