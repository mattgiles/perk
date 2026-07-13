"""Isolated unit coverage for the shared learn-factory core (`factory_common`).

Exercises the pure gather-time routing + inbox-render helpers directly (no GitHub, no `exec pi`):
`partition_by_destination` (the default-route discipline), `_classification_line`, `render_inbox`.
"""

from perk import plan
from perk.backends.issue_backend import LearnIssueSummary
from perk.cli.commands.learn import factory_common
from perk.learn.docs_scan import DocFindings


def _issue(
    num: int, *, decision: str | None = None, target: str | None = None
) -> LearnIssueSummary:
    """A learn-issue summary whose body carries (or omits) a stamped learn-header. ``header`` is
    populated the way a real backend does (GitHub parses the body block at list time)."""
    body = f"learning {num}"
    if decision is not None or target is not None:
        header = plan.render_learn_header(
            run_id="01RID", created="t", plan=num, decision=decision, target=target
        )
        body = f"{body}\n\n{header}"
    return LearnIssueSummary(
        id=str(num),
        title=f"L{num}",
        url=f"u/{num}",
        body=body,
        header=plan.parse_learn_header(body),
    )


def _bare(num: int, body: str) -> LearnIssueSummary:
    return LearnIssueSummary(
        id=str(num),
        title=f"L{num}",
        url=f"u/{num}",
        body=body,
        header=plan.parse_learn_header(body),
    )


def test_partition_routes_should_be_code_to_code_bucket():
    doc_destined, code_destined = factory_common.partition_by_destination(
        (_issue(1, decision="SHOULD_BE_CODE"),)
    )
    assert doc_destined == ()
    assert tuple(i.id for i in code_destined) == ("1",)


def test_partition_defaults_absent_header_to_docs():
    # An issue with NO learn-header (a legacy/unclassified capture) is the default route: docs.
    doc_destined, code_destined = factory_common.partition_by_destination(
        (_bare(2, "a learning with no header at all"),)
    )
    assert tuple(i.id for i in doc_destined) == ("2",)
    assert code_destined == ()


def test_partition_defaults_malformed_header_to_docs():
    # A present-but-malformed header (plan is a list → parse_learn_header degrades to None) also
    # takes the default docs route, never the code bucket.
    malformed = plan.render_metadata_block(
        plan.LEARN_HEADER_KEY, {"run_id": "01RID", "plan": [1, 2, 3]}
    )
    doc_destined, code_destined = factory_common.partition_by_destination(
        (_bare(3, f"body\n\n{malformed}"),)
    )
    assert tuple(i.id for i in doc_destined) == ("3",)
    assert code_destined == ()


def test_partition_non_code_decisions_route_to_docs():
    # Every non-SHOULD_BE_CODE classification defaults to docs (the catch-all).
    doc_destined, code_destined = factory_common.partition_by_destination(
        (
            _issue(4, decision="NEW_DOC"),
            _issue(5, decision="UPDATE_EXISTING_DOC"),
            _issue(6, decision="CAPTURE_LEARN"),
        )
    )
    assert tuple(i.id for i in doc_destined) == ("4", "5", "6")
    assert code_destined == ()


def test_classification_line_renders_decision_with_target():
    line = factory_common._classification_line(
        _issue(7, decision="SHOULD_BE_CODE", target="perk/foo.py::bar")
    )
    assert line == "**classification:** SHOULD_BE_CODE → target: `perk/foo.py::bar`"


def test_classification_line_renders_decision_without_target():
    line = factory_common._classification_line(_issue(8, decision="NEW_DOC"))
    assert line == "**classification:** NEW_DOC"


def test_classification_line_renders_unclassified_for_absent_header():
    line = factory_common._classification_line(_bare(9, "no header here"))
    assert line == "**classification:** (unclassified)"


def test_render_inbox_carries_classification_lines_and_untrusted_blocks():
    issues = (
        _issue(10, decision="NEW_DOC", target="docs/learned/x.md"),
        _bare(11, "unclassified learning body"),
    )
    text = factory_common.render_inbox(
        issues,
        kind=factory_common.DOCS_FACTORY,
        inventory=(),
        findings=DocFindings(),
    )
    # Each issue's perk-derived classification line renders above its verbatim untrusted block.
    assert "**classification:** NEW_DOC → target: `docs/learned/x.md`" in text
    assert "**classification:** (unclassified)" in text
    assert text.count("</untrusted_learning>") == 2
    # The docs factory includes the existing-docs scan section; the code factory does not.
    assert "## Existing docs (scan)" in text
    code_text = factory_common.render_inbox(
        issues, kind=factory_common.CODE_FACTORY, inventory=(), findings=DocFindings()
    )
    assert "## Existing docs (scan)" not in code_text
