"""The objective-refinement authoring boundary (contracts.md §8.67): exact context serialization,
strict transfer parsing, artifact containment and the draft → save-request binding.

The committed goldens under ``tests/fixtures/objective-refinement/`` are shared with the
node:test suite (``extension/authoring/refinement/*.test.ts``): ``context.json`` is Python's
canonical serialization of the fixture context below (Unicode, embedded newlines/escapes, a
final LF) and ``draft.json`` is the TypeScript plane's exact draft serialization. The two suites
pin the SAME bytes/digests from both sides — the byte-ownership contract.
"""

import json
from pathlib import Path
from typing import Any, cast

import pytest

from perk.backends.issue_backend import MarkedCommentExpectation
from perk.objective._models import NodeStatus
from perk.objective.refinement import authoring, codec
from perk.objective.refinement.authoring import (
    AuthoringErrorCode,
    PriorRefinement,
    RefinementAuthoringError,
    RefinementContext,
    RefinementDraft,
    RefinementObjective,
)
from perk.objective.refinement.models import (
    RefinementCodeBasis,
    RefinementIdentity,
    RefinementProvenance,
    RefinementSource,
    RefinementTarget,
)
from perk.state import cache

FIXTURES = Path(__file__).parent / "fixtures" / "objective-refinement"
GOLDEN_CONTEXT = (FIXTURES / "context.json").read_bytes()
GOLDEN_DIGEST = (FIXTURES / "context.sha256").read_text(encoding="utf-8").strip()
GOLDEN_DRAFT = (FIXTURES / "draft.json").read_bytes()
TS = "2026-09-07T12:00:00Z"


def fixture_context() -> RefinementContext:
    source = RefinementSource(
        description="Ünïcode déscription — with “quotes” and a tab\tand emoji 🚀",
        slug="future-node",
        comment="author note\nsecond line",
        depends_on=("1.1", "1.2"),
        effective_depends_on=("1.1", "1.2"),
        issue_description='Issue body line 1\n\nLine 3 with \\backslash\\ and "quotes"\n',
    )
    identity = RefinementIdentity(
        backend="linear",
        objective_id="proj-1",
        objective_run_id="01OBJRUN",
        node_id="2.3",
        carrier_id="issue-23",
    )
    target = RefinementTarget(
        identity=identity,
        source=source,
        source_digest=codec.source_digest(source),
        carrier_identifier="ENG-23",
        carrier_url="https://linear.app/x/issue/ENG-23",
        status=NodeStatus.BLOCKED,
        plan_ref=None,
        has_plan_metadata=False,
    )
    provenance = RefinementProvenance(
        authoring_run_id="01AUTHRUN",
        authored_at=TS,
        code_basis=RefinementCodeBasis(head_sha="b" * 40, dirty=True, captured_at=TS),
    )
    prior_provenance = RefinementProvenance(
        authoring_run_id="01PRIORRUN",
        authored_at="2026-08-01T09:30:00Z",
        code_basis=RefinementCodeBasis(
            head_sha="a" * 40, dirty=False, captured_at="2026-08-01T09:30:00Z"
        ),
    )
    return RefinementContext(
        run_id="01AUTHRUN",
        target=target,
        expected=MarkedCommentExpectation(comment_id="cmt-9", body_digest="c" * 64),
        provenance=provenance,
        objective=RefinementObjective(
            id="proj-1", title="Objective “Ship it” 🚢", url="https://linear.app/x/project/proj-1"
        ),
        prior=PriorRefinement(
            markdown="## Prior\n\n- ünïcode ✓\n- line\twith tab\n",
            source_digest="d" * 64,
            provenance=prior_provenance,
            saved_at="2026-08-01T10:00:00Z",
        ),
        engagement=(
            "<untrusted_node_engagement>\n[c-1 by Ada] scope it — s'il vous plaît\n"
            "</untrusted_node_engagement>"
        ),
        warnings=("node engagement unavailable (simulated) — continuing without it",),
    )


def _err(fn, code: AuthoringErrorCode) -> RefinementAuthoringError:
    with pytest.raises(RefinementAuthoringError) as info:
        fn()
    assert info.value.code is code, str(info.value)
    return info.value


# --------------------------------------------------------------------------- serialization


def test_golden_context_is_the_exact_canonical_serialization() -> None:
    prep = authoring.prepared(fixture_context())
    assert prep.context_json.encode("utf-8") == GOLDEN_CONTEXT
    assert prep.context_digest == GOLDEN_DIGEST
    # Canonical form: sorted keys, compact separators, ASCII-only escapes, exactly one final LF.
    text = prep.context_json
    assert text.endswith("}\n") and not text.endswith("\n\n")
    assert text.isascii()
    assert ": " not in text.split('"engagement"')[0] and ", " not in text.split('"')[0]
    assert json.loads(text) == authoring.context_mapping(fixture_context())


def test_serialize_is_idempotent_and_parse_roundtrips_the_full_context() -> None:
    context = fixture_context()
    first = authoring.serialize_context(context)
    parsed = authoring.parse_context(first)
    assert parsed == context
    assert authoring.serialize_context(parsed) == first


def test_artifact_digest_is_over_exact_utf8_bytes_including_the_final_lf() -> None:
    text = GOLDEN_CONTEXT.decode("utf-8")
    assert authoring.artifact_digest(text) == GOLDEN_DIGEST
    assert authoring.artifact_digest(text.rstrip("\n")) != GOLDEN_DIGEST
    assert authoring.is_artifact_digest(GOLDEN_DIGEST)
    assert not authoring.is_artifact_digest(GOLDEN_DIGEST.upper())
    assert not authoring.is_artifact_digest(GOLDEN_DIGEST[len("sha256:") :])  # bare hex is remote


def test_context_mapping_uses_lists_and_retains_required_nulls() -> None:
    context = fixture_context()
    mapping = authoring.context_mapping(context)
    target = cast(dict[str, Any], mapping["target"])
    assert target["source"]["depends_on"] == ["1.1", "1.2"]
    assert target["plan_ref"] is None
    absent = RefinementContext(
        run_id=context.run_id,
        target=context.target,
        expected=MarkedCommentExpectation(comment_id=None, body_digest=None),
        provenance=context.provenance,
        objective=context.objective,
        prior=None,
        engagement="",
        warnings=(),
    )
    absent_mapping = authoring.context_mapping(absent)
    assert absent_mapping["prior"] is None
    assert absent_mapping["expected"] == {"comment_id": None, "body_digest": None}
    assert authoring.parse_context(authoring.serialize_context(absent)) == absent


# --------------------------------------------------------------------------- strict parsing


def _mutated(**changes: object) -> str:
    mapping = json.loads(GOLDEN_CONTEXT)
    for dotted, value in changes.items():
        cursor = mapping
        *parents, leaf = dotted.split(".")
        for key in parents:
            cursor = cursor[key]
        if value is _DELETE:
            del cursor[leaf]
        else:
            cursor[leaf] = value
    return json.dumps(mapping) + "\n"


_DELETE = object()


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("{not json", "not valid JSON"),
        ("[]\n", "not a JSON object"),
        (_mutated(extra_key="x"), "fields invalid"),
        (_mutated(schema_version="1"), "fields invalid"),  # coercion refused
        (_mutated(schema_version=2), "unknown schema_version"),
        (_mutated(**{"target.status": "flying"}), "status 'flying' is unknown"),
        (_mutated(**{"target.source_digest": "z" * 64}), "not a canonical"),
        (_mutated(**{"target.source.description": "changed"}), "does not match the target source"),
        (_mutated(**{"target.identity.node_id": ""}), "context invalid"),
        (_mutated(**{"provenance.code_basis.head_sha": "short"}), "context invalid"),
        (_mutated(**{"expected.body_digest": None}), "expectation must carry both"),
        (_mutated(run_id=" "), "run_id is blank"),
        (_mutated(**{"prior.markdown": "  "}), "prior.markdown is blank"),
        (_mutated(**{"target.source.depends_on": "1.1"}), "fields invalid"),  # str not spread
        (_mutated(target=_DELETE), "fields invalid"),
        (_mutated(warnings=[1]), "fields invalid"),
    ],
)
def test_parse_context_refuses_every_defect_as_context_invalid(text: str, fragment: str) -> None:
    err = _err(lambda: authoring.parse_context(text), AuthoringErrorCode.CONTEXT_INVALID)
    assert fragment in str(err)


def test_golden_draft_parses_with_byte_exact_markdown() -> None:
    draft = authoring.parse_draft(GOLDEN_DRAFT.decode("utf-8"))
    assert draft == RefinementDraft(
        run_id="01AUTHRUN",
        context_digest=GOLDEN_DIGEST,
        markdown=(
            '## Refinement\n\nÜnïcode ✓ — tabs\tand "quotes" and \\backslashes\\.\n\n'
            "- trailing spaces   \n- final line without LF"
        ),
    )
    # Nothing is trimmed: the trailing-space line and the missing final newline survive.
    assert draft.markdown.endswith("without LF") and "spaces   \n" in draft.markdown


@pytest.mark.parametrize(
    "payload, fragment",
    [
        ("{oops", "not valid JSON"),
        ('"str"', "not a JSON object"),
        ({"schema_version": 1, "run_id": "r", "context_digest": GOLDEN_DIGEST}, "fields invalid"),
        (
            {"schema_version": 1, "run_id": "r", "context_digest": GOLDEN_DIGEST, "markdown": 3},
            "fields invalid",
        ),
        (
            {
                "schema_version": 1,
                "run_id": "r",
                "context_digest": GOLDEN_DIGEST,
                "markdown": "x",
                "title": "no",
            },
            "fields invalid",
        ),
        (
            {"schema_version": 9, "run_id": "r", "context_digest": GOLDEN_DIGEST, "markdown": "x"},
            "unknown schema_version",
        ),
        (
            {"schema_version": 1, "run_id": "r", "context_digest": "abc", "markdown": "x"},
            "context_digest is not",
        ),
        (
            {
                "schema_version": 1,
                "run_id": "r",
                "context_digest": GOLDEN_DIGEST,
                "markdown": " \n",
            },
            "markdown is blank",
        ),
        (
            {"schema_version": 1, "run_id": "", "context_digest": GOLDEN_DIGEST, "markdown": "x"},
            "run_id is blank",
        ),
    ],
)
def test_parse_draft_refuses_every_defect_as_draft_invalid(payload: object, fragment: str) -> None:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    err = _err(lambda: authoring.parse_draft(text), AuthoringErrorCode.DRAFT_INVALID)
    assert fragment in str(err)


# --------------------------------------------------------------------------- artifact I/O


def test_load_context_artifact_reads_the_fixed_session_data_file(tmp_path: Path) -> None:
    data_dir = cache.session_data_dir(tmp_path, "01AUTHRUN")
    data_dir.mkdir(parents=True)
    (data_dir / authoring.CONTEXT_ARTIFACT).write_bytes(GOLDEN_CONTEXT)
    context, digest = authoring.load_context_artifact(tmp_path, run_id="01AUTHRUN")
    assert context == fixture_context() and digest == GOLDEN_DIGEST


def test_load_context_artifact_missing_and_invalid_are_distinct(tmp_path: Path) -> None:
    _err(
        lambda: authoring.load_context_artifact(tmp_path, run_id="01AUTHRUN"),
        AuthoringErrorCode.CONTEXT_MISSING,
    )
    data_dir = cache.session_data_dir(tmp_path, "01AUTHRUN")
    data_dir.mkdir(parents=True)
    path = data_dir / authoring.CONTEXT_ARTIFACT
    path.write_bytes(b"\xff\xfe not utf8")
    err = _err(
        lambda: authoring.load_context_artifact(tmp_path, run_id="01AUTHRUN"),
        AuthoringErrorCode.CONTEXT_INVALID,
    )
    assert "not valid UTF-8" in str(err)
    # A valid artifact belonging to ANOTHER run is not this run's context.
    path.write_bytes(GOLDEN_CONTEXT)
    other_dir = cache.session_data_dir(tmp_path, "01OTHER")
    other_dir.mkdir(parents=True)
    (other_dir / authoring.CONTEXT_ARTIFACT).write_bytes(GOLDEN_CONTEXT)
    err = _err(
        lambda: authoring.load_context_artifact(tmp_path, run_id="01OTHER"),
        AuthoringErrorCode.CONTEXT_INVALID,
    )
    assert "does not match the current run" in str(err)


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "a\\b", "a\0b"])
def test_unsafe_run_ids_are_refused_before_any_path_derivation(tmp_path: Path, bad: str) -> None:
    assert not authoring.is_safe_run_id(bad)
    err = _err(
        lambda: authoring.context_artifact_path(tmp_path, bad), AuthoringErrorCode.CONTEXT_INVALID
    )
    assert "not a safe path component" in str(err)


def test_context_artifact_path_refuses_a_symlinked_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / authoring.CONTEXT_ARTIFACT).write_bytes(GOLDEN_CONTEXT)
    data_dir = cache.session_data_dir(tmp_path, "01AUTHRUN")
    data_dir.parent.mkdir(parents=True)
    data_dir.symlink_to(outside, target_is_directory=True)
    # The data dir itself resolving elsewhere is fine for the parent check only when the file
    # resolves inside the SAME resolved dir — a symlinked FILE pointing outside is refused.
    data_dir.unlink()
    data_dir.mkdir()
    (data_dir / authoring.CONTEXT_ARTIFACT).symlink_to(outside / authoring.CONTEXT_ARTIFACT)
    err = _err(
        lambda: authoring.context_artifact_path(tmp_path, "01AUTHRUN"),
        AuthoringErrorCode.CONTEXT_INVALID,
    )
    assert "escapes" in str(err)


def test_load_draft_file_missing_vs_invalid(tmp_path: Path) -> None:
    _err(
        lambda: authoring.load_draft_file(tmp_path / "none.json"),
        AuthoringErrorCode.DRAFT_MISSING,
    )
    bad = tmp_path / "draft.json"
    bad.write_bytes(b"\xff")
    _err(lambda: authoring.load_draft_file(bad), AuthoringErrorCode.DRAFT_INVALID)
    bad.write_bytes(GOLDEN_DRAFT)
    assert authoring.load_draft_file(bad).context_digest == GOLDEN_DIGEST


# --------------------------------------------------------------------------- save binding


def test_compose_save_request_binds_exact_run_and_context_digest() -> None:
    context = fixture_context()
    draft = authoring.parse_draft(GOLDEN_DRAFT.decode("utf-8"))
    request = authoring.compose_save_request(context, draft, context_digest=GOLDEN_DIGEST)
    assert request.document.markdown == draft.markdown  # byte-exact, tail preserved
    assert request.document.identity == context.target.identity
    assert request.document.source_digest == context.target.source_digest
    assert request.document.provenance == context.provenance  # retained, never regenerated
    assert request.expected == context.expected

    other_digest = "sha256:" + "0" * 64
    err = _err(
        lambda: authoring.compose_save_request(context, draft, context_digest=other_digest),
        AuthoringErrorCode.DRAFT_INVALID,
    )
    assert "context_digest does not match" in str(err)
    wrong_run = RefinementDraft(run_id="01ELSE", context_digest=GOLDEN_DIGEST, markdown="x")
    err = _err(
        lambda: authoring.compose_save_request(context, wrong_run, context_digest=GOLDEN_DIGEST),
        AuthoringErrorCode.DRAFT_INVALID,
    )
    assert "run id" in str(err)
