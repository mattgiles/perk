"""Objective-node refinement over the REAL GitHub store + adapter (contracts.md §8.67, the GitHub
arm).

The stateful ``FakeGitHubIssues`` fakes the external ``gh`` transport only: every test drives the
real ``GitHubObjectiveStore`` (the refinement target read over the objective issue), the real
``GitHubIssueBackend`` (the guarded marked-comment seams + the coexistence filters), and the real
``perk.objective.refinement.service``. On GitHub every node's carrier IS the objective issue —
per-node records are told apart by the marker key — so the coexistence filters (the marker
finder, the plan-body scans, the dream-companion scan, the engagement renderers) are exercised by
the same fake.

Assertions are semantic (complete pagination, correct mutation identity, full replacement, typed
outcomes, zero forbidden effects, at-most-one mutation attempt) — never frozen argv or total call
counts. The **offline persistence gate** at the bottom is an ordinary pytest case over a temp repo
+ the actual resolvers. Live GitHub behavior (byte preservation, the 422 shape, ``fullDatabaseId``
presence, ``--paginate --slurp`` on the comments endpoint) is deliberately unobserved here.
"""

import copy
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from _github_fakes import ROOT, FakeGitHubIssues

from perk import objective, plan
from perk.backends import resolve
from perk.backends.engagement import EMPTY_NODE_ENGAGEMENT, render_objective_engagement
from perk.backends.github import objectives, plans
from perk.backends.github.backend import GitHubIssueBackend
from perk.backends.github.objective_store import GitHubObjectiveStore
from perk.backends.issue_backend import (
    MarkedCommentError,
    MarkedCommentExpectation,
    body_digest,
)
from perk.backends.objective_store import ObjectiveStoreError, RefinementTargetReadError
from perk.cli.commands.objective.node_context import (
    RefinementMissing,
    RefinementPresent,
    assemble_node_context,
)
from perk.learn import dream_companion
from perk.objective.refinement import codec, service
from perk.objective.refinement.models import (
    RefinementCodeBasis,
    RefinementDocument,
    RefinementError,
    RefinementErrorCode,
    RefinementIdentity,
    RefinementProvenance,
    RefinementSaveRequest,
    RefinementSource,
    RefinementTarget,
    SavedRefinement,
)
from perk.substrate import git

OBJ = 252
OBJ_ID = str(OBJ)
OBJ_RUN = "01OBJRUN"
HEAD = "b" * 40
TS = "2026-09-07T12:00:00Z"
URL = f"https://github.com/octo/repo/issues/{OBJ}"

# --------------------------------------------------------------------------- harness


def _node(
    node_id: str,
    description: str,
    *,
    status: objective.NodeStatus = objective.NodeStatus.PENDING,
    depends_on: tuple[str, ...] | None = None,
    slug: str | None = None,
    comment: str | None = None,
    pr: str | None = None,
) -> objective.ObjectiveNode:
    return objective.ObjectiveNode(
        id=node_id,
        description=description,
        status=status,
        pr=pr,
        depends_on=depends_on,
        slug=slug,
        comment=comment,
    )


def _default_nodes() -> list[objective.ObjectiveNode]:
    return [
        _node("1.1", "Predecessor work", slug="predecessor"),
        _node("1.2", "Refine me", slug="refine-me", comment="author note"),
        _node("1.10", "Tenth node"),
        _node("2.1", "Far future", depends_on=("1.10",)),
    ]


def _harness(
    monkeypatch: pytest.MonkeyPatch,
    *,
    nodes: list[objective.ObjectiveNode] | None = None,
    page_size: int = 2,
    seed: bool = True,
) -> tuple[FakeGitHubIssues, GitHubObjectiveStore, GitHubIssueBackend]:
    fake = FakeGitHubIssues(page_size=page_size)
    monkeypatch.setattr(subprocess, "run", fake)
    if seed:
        fake.seed_objective(
            OBJ,
            run_id=OBJ_RUN,
            nodes=nodes if nodes is not None else _default_nodes(),
            prose="# Objective\n\nProse.\n",
        )
    return fake, GitHubObjectiveStore(ROOT), GitHubIssueBackend(ROOT)


def _provenance(run_id: str = "01AUTHRUN") -> RefinementProvenance:
    return RefinementProvenance(
        authoring_run_id=run_id,
        authored_at=TS,
        code_basis=RefinementCodeBasis(head_sha=HEAD, dirty=False, captured_at=TS),
    )


def _target(store: GitHubObjectiveStore, node_id: str) -> RefinementTarget:
    snapshot = store.read_node_refinement_targets(objective_id=OBJ_ID)
    assert snapshot is not None
    return next(t for t in snapshot.targets if t.identity.node_id == node_id)


def _document(
    target: RefinementTarget, markdown: str = "## Approach\n\nCarefully.\n"
) -> RefinementDocument:
    return codec.document_for_target(target, markdown=markdown, provenance=_provenance())


def _err(fn: Callable[[], object], code: RefinementErrorCode, **attrs: object) -> RefinementError:
    with pytest.raises(RefinementError) as info:
        fn()
    assert info.value.code is code, str(info.value)
    for key, value in attrs.items():
        assert getattr(info.value, key) == value, (key, getattr(info.value, key))
    return info.value


def _guard_err(fn: Callable[[], object], code: str, **attrs: object) -> MarkedCommentError:
    with pytest.raises(MarkedCommentError) as info:
        fn()
    assert info.value.code == code, str(info.value)
    for key, value in attrs.items():
        assert getattr(info.value, key) == value, (key, getattr(info.value, key))
    return info.value


def _read_err(fn: Callable[[], object], code: str) -> RefinementTargetReadError:
    with pytest.raises(RefinementTargetReadError) as info:
        fn()
    assert info.value.code == code, str(info.value)
    return info.value


def _header_block(**overrides: object) -> str:
    """A rendered ``objective-header`` block; ``overrides`` replace rendered fields (so a junk
    ``run_id`` can be staged without going through the typed header)."""
    fields = objective.render_header_block(
        objective.ObjectiveHeader(run_id=OBJ_RUN, created=TS, objective_comment_id=None)
    )
    return plan.render_metadata_block(objective.OBJECTIVE_HEADER_KEY, {**fields, **overrides})


def _roadmap_block(nodes: list[objective.ObjectiveNode]) -> str:
    return plan.render_metadata_block(
        objective.OBJECTIVE_ROADMAP_KEY, objective.render_roadmap_block(nodes)
    )


def _classify(body: str):
    return objectives.refinement_targets_from_issue(
        number=OBJ, url=URL, body=body, backend_id="github"
    )


def _body_comment(fake: FakeGitHubIssues) -> dict[str, object]:
    header = plan.find_metadata_block(str(fake.issues[OBJ]["body"]), objective.OBJECTIVE_HEADER_KEY)
    assert header is not None
    comment = fake.comment_by_id(int(str(header["objective_comment_id"])))
    assert comment is not None
    return comment


def _refinement_comments(fake: FakeGitHubIssues) -> list[dict[str, object]]:
    return [c for c in fake.comments[OBJ] if codec.is_refinement_comment(str(c["body"]))]


def _non_comment_state(fake: FakeGitHubIssues) -> dict[int, dict[str, object]]:
    """Everything except comments — the surface refinement must never touch."""
    return copy.deepcopy(fake.issues)


# A long Markdown body (> 1,500 chars) that quotes every marker the coexistence filters guard: a
# fenced code block, a table, the roadmap-table marker, the dream-companion marker text, and a
# COMPLETE plan-body example — so the gate itself exercises the filters.
LONG_MARKDOWN = (
    "## Approach\n\n"
    + "\n".join(f"- step {i}: do the thing with care and detail — ünïcödé 東京" for i in range(80))
    + "\n\n```python\nx = {'a': 1}\n# <!-- not a perk marker -->\n```\n\n"
    "| col | val |\n|---|---|\n| a | b |\n\n"
    f"Never hand-edit the `{objective.ROADMAP_TABLE_MARKER_START}` region or the\n"
    "`perk:learn-dream-report` companion comments.\n\n"
    + plan.render_plan_body("# Example\n\nbody")
    + "\n\n\n"
)


# --------------------------------------------------------------------------- comment identity


class TestCommentIdentity:
    def test_read_comments_ids_are_the_stringified_database_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, store, issues = _harness(monkeypatch)
        human_id = fake.add_comment(OBJ, "a human remark")
        third_id = fake.add_comment(OBJ, "another")  # three comments → two GraphQL pages
        body_comment = _body_comment(fake)
        rows = issues.read_comments(issue_id=OBJ_ID)
        assert [c.id for c in rows] == [str(body_comment["id"]), str(human_id), str(third_id)]
        assert store.read_comments(objective_id=OBJ_ID) == rows
        # The objective-body comment's EngagementComment.id equals the header's
        # objective_comment_id (as str) and the REST marker finder's integer id.
        header = store.get_objective(objective_id=OBJ_ID)
        assert header is not None
        assert rows[0].id == str(header.header["objective_comment_id"])
        found = plans.find_comment_id_by_marker(
            issue=OBJ, marker=objective.ROADMAP_TABLE_MARKER_START, repo_root=ROOT
        )
        assert found == body_comment["id"] and str(found) == rows[0].id
        assert issues.find_comment_id_by_marker(
            issue_id=OBJ_ID, marker=objective.ROADMAP_TABLE_MARKER_START
        ) == str(found)
        assert rows[0].author.kind == "perk" and rows[1].author.kind == "human"
        assert len(fake.graphql_calls()) >= 2  # the scan paginated


# --------------------------------------------------------------------------- the target read


class TestRefinementTargetRead:
    def test_no_objective_header_is_none(self) -> None:
        assert _classify("just a human issue\n") is None
        assert _classify(_roadmap_block(_default_nodes())) is None  # roadmap without a header

    def test_two_header_blocks_are_ambiguous_before_any_parse(self) -> None:
        # The second block is malformed — still ambiguous_target, never malformed_target: the
        # cardinality refusal precedes every parse.
        broken = "<!-- perk:metadata-block:objective-header -->\n```yaml\nrun_id: x"
        body = f"{_header_block()}\n\n{_roadmap_block(_default_nodes())}\n\n{broken}\n"
        err = _read_err(lambda: _classify(body), "ambiguous_target")
        assert "2 objective-header blocks" in str(err) and f"#{OBJ}" in str(err)
        inline = plan.render_metadata_block(
            objective.OBJECTIVE_HEADER_KEY, {"run_id": OBJ_RUN}, style="inline-code"
        )
        _read_err(lambda: _classify(f"{_header_block()}\n\n{inline}\n"), "ambiguous_target")

    def test_malformed_header_and_unreadable_run_id_are_malformed(self) -> None:
        broken = "<!-- perk:metadata-block:objective-header -->\n```yaml\nrun_id: x"
        err = _read_err(lambda: _classify(broken), "malformed_target")
        assert "present but malformed" in str(err)
        for run_id in ("", "   ", None, 7):
            body = f"{_header_block(run_id=run_id)}\n\n{_roadmap_block(_default_nodes())}\n"
            err = _read_err(lambda body=body: _classify(body), "malformed_target")
            assert "no readable run_id" in str(err)

    def test_two_roadmap_blocks_are_ambiguous_even_when_each_is_valid(self) -> None:
        # The trap the cardinality check exists for: two individually valid roadmap blocks must
        # never key or digest a refinement against whichever happens to come first.
        first = _roadmap_block([_node("1.1", "First shape")])
        second = _roadmap_block([_node("1.1", "Second shape")])
        body = f"{_header_block()}\n\n{first}\n\nprose\n\n{second}\n"
        assert plan.find_metadata_block(body, objective.OBJECTIVE_ROADMAP_KEY) is not None
        err = _read_err(lambda: _classify(body), "ambiguous_target")
        assert "2 objective-roadmap blocks" in str(err)

    def test_malformed_roadmap_is_malformed(self) -> None:
        broken = "<!-- perk:metadata-block:objective-roadmap -->\n```yaml\nnodes: ["
        err = _read_err(lambda: _classify(f"{_header_block()}\n\n{broken}\n"), "malformed_target")
        assert "invalid objective roadmap" in str(err)
        # A parseable block whose node fails validation is the same refusal.
        bad_node = plan.render_metadata_block(
            objective.OBJECTIVE_ROADMAP_KEY,
            {"schema_version": "1", "nodes": [{"id": "1.1", "status": "pending"}]},
        )
        _read_err(lambda: _classify(f"{_header_block()}\n\n{bad_node}\n"), "malformed_target")

    def test_duplicate_node_id_is_ambiguous(self) -> None:
        dup = _roadmap_block([_node("1.1", "A"), _node("1.2", "B"), _node("1.1", "A again")])
        err = _read_err(lambda: _classify(f"{_header_block()}\n\n{dup}\n"), "ambiguous_target")
        assert "'1.1' appears more than once" in str(err)

    def test_roadmap_free_objective_has_zero_targets(self) -> None:
        snapshot = _classify(f"{_header_block()}\n")
        assert snapshot is not None
        assert snapshot.targets == () and snapshot.objective_run_id == OBJ_RUN
        assert snapshot.objective_id == OBJ_ID and snapshot.objective_url == URL

    def test_happy_path_identity_source_order_and_normalization(self) -> None:
        nodes = [
            _node("2.1", "Far future", depends_on=("1.2", "1.1", "1.1")),
            _node("1.10", "Tenth node", depends_on=()),
            _node("1.1", "Predecessor work", slug="predecessor", pr="#301"),
            _node(
                "1.2",
                "Refine me",
                slug="refine-me",
                comment="author note",
                status=objective.NodeStatus.BLOCKED,
            ),
        ]
        snapshot = _classify(f"{_header_block()}\n\n{_roadmap_block(nodes)}\n")
        assert snapshot is not None
        assert snapshot.backend == "github"
        assert snapshot.objective_id == OBJ_ID and snapshot.objective_url == URL
        assert [t.identity.node_id for t in snapshot.targets] == ["1.1", "1.2", "1.10", "2.1"]
        by_id = {t.identity.node_id: t for t in snapshot.targets}
        for target in snapshot.targets:
            assert target.identity.backend == "github"
            assert target.identity.objective_id == target.identity.carrier_id == OBJ_ID
            assert target.identity.objective_run_id == OBJ_RUN
            assert target.carrier_identifier == f"#{OBJ}" and target.carrier_url == URL
            assert target.source.issue_description == ""
            assert target.has_plan_metadata is False
            assert target.source_digest == codec.source_digest(target.source)
        assert by_id["1.1"].plan_ref == "#301" and by_id["1.1"].eligible is False
        assert by_id["1.2"].status is objective.NodeStatus.BLOCKED and by_id["1.2"].eligible
        assert by_id["1.2"].source.slug == "refine-me"
        assert by_id["1.2"].source.comment == "author note"
        # depends_on normalized (unique, naturally sorted). The roadmap block's storage shape
        # renders a None beside declared deps as `[]` (the existing reconstruction loss), so
        # 1.1 reads `()` here; None is preserved when the block carries no depends_on column
        # (the sequential case below).
        assert by_id["2.1"].source.depends_on == ("1.1", "1.2")
        assert by_id["1.1"].source.depends_on == ()
        assert by_id["1.10"].source.depends_on == ()
        # Effective dependencies via build_graph: explicit edges when any node declares them.
        assert by_id["2.1"].source.effective_depends_on == ("1.1", "1.2")
        assert by_id["1.1"].source.effective_depends_on == ()
        # Sequential inference when no node declares deps.
        plain = [_node("1.1", "a"), _node("1.2", "b"), _node("2.1", "c")]
        seq = _classify(f"{_header_block()}\n\n{_roadmap_block(plain)}\n")
        assert seq is not None
        effective = {t.identity.node_id: t.source.effective_depends_on for t in seq.targets}
        assert effective["1.1"] == () and effective["2.1"] != ()
        assert all(t.source.depends_on is None for t in seq.targets)

    def test_store_read_over_the_fake(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake, store, _issues = _harness(monkeypatch)
        fake.add_comment(OBJ, "a human remark")
        start = len(fake.calls)
        snapshot = store.read_node_refinement_targets(objective_id=OBJ_ID)
        assert snapshot is not None
        assert [t.identity.node_id for t in snapshot.targets] == ["1.1", "1.2", "1.10", "2.1"]
        assert snapshot.objective_url == URL
        assert snapshot == store.read_node_refinement_targets(objective_id=f"#{OBJ}")
        # A pure read: no mutation, no comment read.
        assert fake.mutations(start) == []
        assert fake.graphql_calls(start) == []
        assert not any("comments" in " ".join(gh) for gh in fake.calls[start:])
        assert store.read_node_refinement_targets(objective_id="999") is None
        with pytest.raises(ObjectiveStoreError, match="numeric"):
            store.read_node_refinement_targets(objective_id="ENG-1")
        # The substrate's typed refusals pass through the store's translate CM untouched.
        fake.issues[OBJ]["body"] = (
            f"{fake.issues[OBJ]['body']}\n{_roadmap_block(_default_nodes())}\n"
        )
        err = _read_err(
            lambda: store.read_node_refinement_targets(objective_id=OBJ_ID), "ambiguous_target"
        )
        assert isinstance(err, ObjectiveStoreError)


# --------------------------------------------------------------------------- guarded upsert


MARKER = "<!-- perk:test-guard:v1:abc -->"


def _body(text: str) -> str:
    return f"{MARKER}\n\n{text}"


class TestGuardedUpsertOverGitHub:
    def test_create_update_convergence_identity_transcode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, _store, issues = _harness(monkeypatch)
        absent = MarkedCommentExpectation(None, None)
        long_body = _body(
            "line one\n" * 50
            + "<details><summary>x</summary>\n\n<!-- perk:other:x -->\n</details>\n"
        )
        start = len(fake.calls)
        result = issues.upsert_marked_comment(
            issue_id=OBJ_ID, marker=MARKER, body=long_body, expected=absent
        )
        assert result.posted is True and result.verified_comment is not None
        verified = result.verified_comment
        assert fake.mutations(start) == [f"POST issues/{OBJ}/comments"]
        [comment] = [c for c in fake.comments[OBJ] if c["body"] == long_body]
        assert verified.id == str(comment["id"])  # the full-width database id, as str
        assert int(verified.id) > 2**31 - 1  # past what a 32-bit GraphQL Int could carry
        assert verified.body == long_body  # stored verbatim: HTML marker + <details> preserved
        assert issues.transcode(long_body) == long_body
        assert verified.created_at == comment["created_at"] and verified.edited_at is None
        assert verified.author.kind == "perk"

        # Update: expectation = observed id + digest → one PATCH on the database id.
        start = len(fake.calls)
        short_body = _body("short")
        expected = MarkedCommentExpectation(verified.id, body_digest(verified.body))
        updated = issues.upsert_marked_comment(
            issue_id=OBJ_ID, marker=MARKER, body=short_body, expected=expected
        )
        assert fake.mutations(start) == [f"PATCH issues/comments/{comment['id']}"]
        assert updated.verified_comment is not None
        assert updated.verified_comment.id == verified.id
        assert updated.verified_comment.body == short_body == comment["body"]
        assert updated.verified_comment.edited_at == comment["edited_at"] is not None

        # Convergence: the same body again → no mutation, the observed comment returned.
        start = len(fake.calls)
        again = issues.upsert_marked_comment(
            issue_id=OBJ_ID, marker=MARKER, body=short_body, expected=expected
        )
        assert fake.mutations(start) == []
        assert again.verified_comment == updated.verified_comment

    def test_duplicate_owners_across_pages_and_a_sole_owner_on_the_last_page(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, _store, issues = _harness(monkeypatch, page_size=2)
        fake.add_comment(OBJ, "chatter one")
        first = fake.add_comment(OBJ, _body("first owner"), login="perk-bot", bot=True)
        fake.add_comment(OBJ, "chatter two")
        second = fake.add_comment(OBJ, _body("second owner"), login="perk-bot", bot=True)
        start = len(fake.calls)
        err = _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=OBJ_ID,
                marker=MARKER,
                body=_body("x"),
                expected=MarkedCommentExpectation(None, None),
            ),
            "ambiguous_comment",
            write_attempted=False,
        )
        assert err.comment_ids == (str(first), str(second))
        assert fake.mutations(start) == []
        graphql = fake.graphql_calls(start)
        assert len(graphql) >= 2 and any(
            any(tok.startswith("cursor=") for tok in gh) for gh in graphql[1:]
        )
        # Remove the first owner: the sole owner sits on the LAST page and converges.
        fake.comments[OBJ] = [c for c in fake.comments[OBJ] if c["id"] != first]
        start = len(fake.calls)
        result = issues.upsert_marked_comment(
            issue_id=OBJ_ID,
            marker=MARKER,
            body=_body("second owner"),
            expected=MarkedCommentExpectation(None, None),
        )
        assert result.verified_comment is not None
        assert result.verified_comment.id == str(second)
        assert fake.mutations(start) == []

    def test_too_long_bodies_are_backend_error_with_the_diagnostic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, _store, issues = _harness(monkeypatch)
        too_long = _body("x" * 65_537)
        assert len(too_long) > 65_536
        comments_before = copy.deepcopy(fake.comments[OBJ])
        start = len(fake.calls)
        err = _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=OBJ_ID,
                marker=MARKER,
                body=too_long,
                expected=MarkedCommentExpectation(None, None),
            ),
            "backend_error",
            write_attempted=True,
        )
        assert "Body is too long (maximum is 65536 characters)" in str(err)
        assert fake.comments[OBJ] == comments_before  # no comment created
        assert fake.mutations(start) == [f"POST issues/{OBJ}/comments"]  # exactly one attempt
        # Update path: the stored body is unchanged.
        created = issues.upsert_marked_comment(
            issue_id=OBJ_ID,
            marker=MARKER,
            body=_body("fits"),
            expected=MarkedCommentExpectation(None, None),
        )
        assert created.verified_comment is not None
        observed = created.verified_comment
        start = len(fake.calls)
        err = _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id=OBJ_ID,
                marker=MARKER,
                body=too_long,
                expected=MarkedCommentExpectation(observed.id, body_digest(observed.body)),
            ),
            "backend_error",
            write_attempted=True,
        )
        assert "Body is too long" in str(err) and err.comment_ids == (observed.id,)
        stored = fake.comment_by_id(int(observed.id))
        assert stored is not None and stored["body"] == _body("fits")
        assert fake.mutations(start) == [f"PATCH issues/comments/{observed.id}"]

    def test_preflight_refusals_dry_run_and_the_ordinary_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, _store, issues = _harness(monkeypatch)
        start = len(fake.calls)
        # Non-numeric issue id: backend_error at preflight, no gh call.
        err = _guard_err(
            lambda: issues.upsert_marked_comment(
                issue_id="ENG-1",
                marker=MARKER,
                body=_body("x"),
                expected=MarkedCommentExpectation(None, None),
            ),
            "backend_error",
            write_attempted=False,
        )
        assert "numeric" in str(err) and fake.calls[start:] == []
        # Dry run: posted=False, no gh call.
        dry = issues.upsert_marked_comment(
            issue_id=OBJ_ID,
            marker=MARKER,
            body=_body("x"),
            dry_run=True,
            expected=MarkedCommentExpectation(None, None),
        )
        assert dry.posted is False and dry.verified_comment is None
        assert fake.calls[start:] == []
        # The seams refuse junk comment ids honestly (the driver normalizes this).
        with pytest.raises(Exception, match="GitHub comment ids are numeric"):
            issues.update("IC_abc", _body("x"))
        # The ordinary expected=None path is unchanged: finder (exhaustive REST) + POST/PATCH.
        start = len(fake.calls)
        ordinary = issues.upsert_marked_comment(issue_id=OBJ_ID, marker=MARKER, body=_body("v1"))
        assert ordinary.posted is True and ordinary.verified_comment is None
        assert fake.mutations(start) == [f"POST issues/{OBJ}/comments"]
        [created] = [c for c in fake.comments[OBJ] if c["body"] == _body("v1")]
        start = len(fake.calls)
        issues.upsert_marked_comment(issue_id=OBJ_ID, marker=MARKER, body=_body("v2"))
        assert fake.mutations(start) == [f"PATCH issues/comments/{created['id']}"]
        assert created["body"] == _body("v2")
        list_call = next(
            gh for gh in fake.calls[start:] if any(f"issues/{OBJ}/comments" in t for t in gh)
        )
        assert "--paginate" in list_call and "--slurp" in list_call


# --------------------------------------------------------------------------- coexistence


def _seed_refinement(
    fake: FakeGitHubIssues,
    store: GitHubObjectiveStore,
    issues: GitHubIssueBackend,
    node_id: str,
    markdown: str = LONG_MARKDOWN,
) -> SavedRefinement:
    read = service.select_refinement_target(store, issues, objective_id=OBJ_ID, node_id=node_id)
    return service.save_node_refinement(
        store,
        issues,
        request=RefinementSaveRequest(
            document=_document(read.target, markdown), expected=read.expected
        ),
    )


def _source() -> RefinementSource:
    return RefinementSource(
        description="Predecessor work",
        slug="predecessor",
        comment=None,
        depends_on=None,
        effective_depends_on=(),
        issue_description="",
    )


class TestCoexistenceFilters:
    def test_marker_finder_skips_a_refinement_quoting_the_marker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Seed the refinement FIRST (before the body comment) so a naive first-hit finder would
        # select it.
        fake = FakeGitHubIssues(page_size=2)
        monkeypatch.setattr(subprocess, "run", fake)
        fake.add_issue(OBJ, title="Obj", body="")
        target_identity = RefinementIdentity(
            backend="github",
            objective_id=OBJ_ID,
            objective_run_id=OBJ_RUN,
            node_id="1.1",
            carrier_id=OBJ_ID,
        )
        quoting = codec.render_refinement(
            RefinementDocument(
                identity=target_identity,
                source=_source(),
                source_digest=codec.source_digest(_source()),
                provenance=_provenance(),
                markdown=LONG_MARKDOWN,
            )
        )
        assert objective.ROADMAP_TABLE_MARKER_START in quoting
        refinement_id = fake.add_comment(OBJ, quoting, login="perk-bot", bot=True)
        fake.add_comment(OBJ, "chatter")
        body_comment = plan.prepend_callout(
            objective.render_body_comment(_default_nodes(), prose="Prose."),
            objective.objective_callout(OBJ_ID),
            command=f"perk objective plan {OBJ}",
        )
        body_id = fake.add_comment(OBJ, body_comment, login="perk-bot", bot=True)
        start = len(fake.calls)
        found = plans.find_comment_id_by_marker(
            issue=OBJ, marker=objective.ROADMAP_TABLE_MARKER_START, repo_root=ROOT
        )
        assert found == body_id and found != refinement_id
        # The body comment sits on the second REST page; the list call was exhaustive.
        [list_call] = [
            gh for gh in fake.calls[start:] if any(f"issues/{OBJ}/comments" in t for t in gh)
        ]
        assert "--paginate" in list_call and "--slurp" in list_call
        # Alone, a marker-quoting refinement reads as no match — even across three pages.
        fake.comments[OBJ] = [c for c in fake.comments[OBJ] if c["id"] != body_id]
        fake.add_comment(OBJ, "more chatter")
        fake.add_comment(OBJ, "yet more")
        assert (
            plans.find_comment_id_by_marker(
                issue=OBJ, marker=objective.ROADMAP_TABLE_MARKER_START, repo_root=ROOT
            )
            is None
        )
        # A marker only on the third page is found.
        late_id = fake.add_comment(OBJ, body_comment, login="perk-bot", bot=True)
        assert len(fake.comments[OBJ]) == 5
        assert (
            plans.find_comment_id_by_marker(
                issue=OBJ, marker=objective.ROADMAP_TABLE_MARKER_START, repo_root=ROOT
            )
            == late_id
        )

    def test_objective_body_recovery_backfills_the_real_comment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The §8.53 deferred-close found-arm over a header with `objective_comment_id: null` and a
        # marker-quoting refinement seeded FIRST: the recovery backfills the body comment's id
        # without posting a replacement.
        fake = FakeGitHubIssues(page_size=2)
        monkeypatch.setattr(subprocess, "run", fake)
        fake.seed_objective(
            OBJ, run_id=OBJ_RUN, nodes=_default_nodes(), prose="Prose.", objective_comment_id=False
        )
        [body_comment] = fake.comments[OBJ]
        quoting = f"<!-- perk:objective-refinement:v1:{'a' * 64} -->\n\n{LONG_MARKDOWN}"
        fake.comments[OBJ].insert(
            0,
            {
                "id": 1,
                "body": quoting,
                "created_at": "2026-02-01T00:00:00Z",
                "edited_at": None,
                "login": "perk-bot",
                "bot": True,
            },
        )
        header = plan.find_metadata_block(
            str(fake.issues[OBJ]["body"]), objective.OBJECTIVE_HEADER_KEY
        )
        assert header is not None and header["objective_comment_id"] is None
        start = len(fake.calls)
        objectives._converge_objective_subordinates(
            number=OBJ, prose="Prose.", roadmap_nodes=_default_nodes(), repo_root=ROOT
        )
        assert fake.mutations(start) == [f"PATCH issues/{OBJ}"]  # the header backfill only
        header = plan.find_metadata_block(
            str(fake.issues[OBJ]["body"]), objective.OBJECTIVE_HEADER_KEY
        )
        assert header is not None and header["objective_comment_id"] == body_comment["id"]
        assert len(fake.comments[OBJ]) == 2

    def test_plan_body_scans_skip_a_refinement_carrying_a_plan_example(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, store, issues = _harness(monkeypatch)
        saved = _seed_refinement(fake, store, issues, "1.2")
        assert plan.extract_plan_body(saved.comment.body) is not None  # the example IS complete
        # Only the refinement carries a plan-body block: no plan comment, no plan body.
        assert plans._find_plan_body_comment_id(OBJ, ROOT) is None
        assert plans.get_plan_body(number=OBJ, repo_root=ROOT) is None
        assert issues.get_plan_body(issue_id=OBJ_ID) is None
        # A real plan comment AFTER the refinement is the one found/read.
        real = fake.add_comment(
            OBJ, plan.render_plan_body("# Real plan\n\nreal body"), login="perk-bot", bot=True
        )
        assert plans._find_plan_body_comment_id(OBJ, ROOT) == real
        assert plans.get_plan_body(number=OBJ, repo_root=ROOT) == "# Real plan\n\nreal body"

    def test_dream_companion_scan_skips_a_refinement_quoting_its_marker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, store, issues = _harness(monkeypatch)
        saved = _seed_refinement(fake, store, issues, "1.2")
        assert "perk:learn-dream-report" in saved.comment.body
        run_id = "01DREAMRUNAAAAAAAAAAAAAAAA"
        start = len(fake.calls)
        dream_companion.persist_parts(
            issues, carrier_id=OBJ_ID, run_id=run_id, parts=["part one", "part two"]
        )
        assert fake.mutations(start) == [f"POST issues/{OBJ}/comments"] * 2
        bodies = [str(c["body"]) for c in fake.comments[OBJ]]
        assert f"<!-- perk:learn-dream-report:{run_id}:1 -->\n\npart one" in bodies
        assert f"<!-- perk:learn-dream-report:{run_id}:2 -->\n\npart two" in bodies
        start = len(fake.calls)
        dream_companion.persist_parts(
            issues, carrier_id=OBJ_ID, run_id=run_id, parts=["part one", "part two"]
        )
        assert fake.mutations(start) == []  # a re-run converges: no conflict, no POST
        # The refinement itself is untouched by the companion writes.
        stored = fake.comment_by_id(int(saved.comment.id))
        assert stored is not None and stored["body"] == saved.comment.body

    def test_engagement_renders_omit_the_refinement_and_node_engagement_stays_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, store, issues = _harness(monkeypatch)
        fake.add_comment(OBJ, "please keep the scope tight")
        saved = _seed_refinement(fake, store, issues, "1.2")
        rendered = render_objective_engagement(
            project_comments=store.read_comments(objective_id=OBJ_ID),
            project_description_edits=store.read_description_edits(objective_id=OBJ_ID),
            node_engagements=(),
        )
        assert rendered is not None
        assert "please keep the scope tight" in rendered
        assert "step 79" not in rendered and codec.MARKER_FAMILY not in rendered
        assert saved.comment.id not in rendered
        assert (
            store.read_node_engagement(objective_id=OBJ_ID, node_id="1.2") is EMPTY_NODE_ENGAGEMENT
        )


# --------------------------------------------------------------------------- service over GitHub


class TestServiceOverGitHub:
    def test_select_save_read_replace_and_retry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        nodes = [
            _node("1.1", "Predecessor work", pr="#301", status=objective.NodeStatus.IN_PROGRESS),
            _node("1.2", "Refine me", slug="refine-me", comment="author note"),
            _node("2.1", "Far future", status=objective.NodeStatus.BLOCKED),
        ]
        fake, store, issues = _harness(monkeypatch, nodes=nodes)
        state_before = _non_comment_state(fake)
        body_comment_before = dict(_body_comment(fake))

        read = service.select_refinement_target(store, issues, objective_id=OBJ_ID)
        assert read.target.identity.node_id == "1.2" and read.saved is None  # 1.1 has a backlink
        blocked = service.select_refinement_target(
            store, issues, objective_id=OBJ_ID, node_id="2.1"
        )
        assert blocked.target.status is objective.NodeStatus.BLOCKED and blocked.target.eligible

        start = len(fake.calls)
        document = _document(read.target, LONG_MARKDOWN)
        saved = service.save_node_refinement(
            store, issues, request=RefinementSaveRequest(document=document, expected=read.expected)
        )
        assert isinstance(saved, SavedRefinement)
        assert fake.mutations(start) == [f"POST issues/{OBJ}/comments"]
        [comment] = _refinement_comments(fake)
        assert saved.comment.id == str(comment["id"])
        assert comment["body"] == codec.render_refinement(document)  # stored verbatim
        assert saved.document.markdown == LONG_MARKDOWN
        assert saved.document.provenance == _provenance()
        assert saved.document.source == read.target.source
        assert saved.saved_at == comment["created_at"]
        assert _non_comment_state(fake) == state_before  # comment-only

        again = service.read_node_refinement(store, issues, objective_id=OBJ_ID, node_id="1.2")
        assert again.saved == saved and again.source_changed is False
        nxt = service.select_refinement_target(store, issues, objective_id=OBJ_ID)
        assert nxt.target.identity.node_id == "2.1"  # 1.2 now carries a valid record
        re_refine = service.select_refinement_target(
            store, issues, objective_id=OBJ_ID, node_id="1.2"
        )
        assert re_refine.saved == saved

        # Replacement: shorter Markdown, same comment id, old tail gone, provenance preserved.
        start = len(fake.calls)
        shorter = codec.document_for_target(
            re_refine.target, markdown="## Shorter\n", provenance=_provenance("01SECOND")
        )
        request = RefinementSaveRequest(document=shorter, expected=re_refine.expected)
        replaced = service.save_node_refinement(store, issues, request=request)
        assert replaced.comment.id == saved.comment.id
        assert fake.mutations(start) == [f"PATCH issues/comments/{saved.comment.id}"]
        assert "step 79" not in replaced.comment.body
        assert replaced.document.provenance.authoring_run_id == "01SECOND"
        assert replaced.comment.edited_at is not None
        assert replaced.saved_at == replaced.comment.edited_at

        # An explicit retry of the SAME request converges: same verified comment, no mutation.
        start = len(fake.calls)
        retried = service.save_node_refinement(store, issues, request=request)
        assert retried == replaced
        assert fake.mutations(start) == []
        assert _non_comment_state(fake) == state_before
        assert _body_comment(fake) == body_comment_before

        # A node description edit flips source_changed; the record stays readable.
        store.update_objective_node(objective_id=OBJ_ID, node_id="1.2", description="Edited")
        changed = service.read_node_refinement(store, issues, objective_id=OBJ_ID, node_id="1.2")
        assert changed.saved == retried and changed.source_changed is True
        _err(
            lambda: service.save_node_refinement(store, issues, request=request),
            RefinementErrorCode.STALE_SOURCE,
            write_attempted=False,
        )

    def test_node_context_assembly_present_absent_and_ambiguous(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, store, issues = _harness(monkeypatch)
        fake.add_comment(OBJ, "please keep the scope tight")
        # Absent: a live read over the objective issue with no record and no warning — the arm
        # that formerly reported `unsupported` on GitHub.
        absent = assemble_node_context(
            store, objective_id=OBJ_ID, node_id="1.2", issues=lambda: issues
        )
        assert absent.refinement == RefinementMissing("absent")
        assert absent.engagement_status == "absent" and absent.warnings == ()

        saved = _seed_refinement(fake, store, issues, "1.2")
        state_before = _non_comment_state(fake)
        start = len(fake.calls)
        context = assemble_node_context(
            store, objective_id=OBJ_ID, node_id="1.2", issues=lambda: issues
        )
        assert context.engagement_status == "absent"  # single-issue objective: no node issues
        present = context.refinement
        assert isinstance(present, RefinementPresent)
        assert present.comment_id == saved.comment.id
        assert LONG_MARKDOWN in present.block and "source_changed: no" in present.block
        assert context.warnings == ()
        assert fake.mutations(start) == [] and _non_comment_state(fake) == state_before

        # A duplicated roadmap block on the carrier: the service refuses `ambiguous_target`, the
        # assembly reports an `unavailable` warning coded ambiguous_target — never `absent`.
        fake.issues[OBJ]["body"] = (
            f"{fake.issues[OBJ]['body']}\n{_roadmap_block(_default_nodes())}\n"
        )
        _err(
            lambda: service.read_node_refinement(store, issues, objective_id=OBJ_ID, node_id="1.2"),
            RefinementErrorCode.AMBIGUOUS_TARGET,
        )
        damaged = assemble_node_context(
            store, objective_id=OBJ_ID, node_id="1.2", issues=lambda: issues
        )
        assert damaged.refinement == RefinementMissing("unavailable")
        [warning] = damaged.warnings
        assert warning.surface == "refinement" and warning.code == "ambiguous_target"
        assert "objective-roadmap blocks" in warning.message


# --------------------------------------------------------------------------- the persistence gate


def _scaffold_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, timeout=30)
    subprocess.run(["git", "config", "user.email", "t@x.io"], cwd=root, check=True, timeout=30)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True, timeout=30)
    (root / "README.md").write_text("# repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True, timeout=30)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True, timeout=30)
    cfg = root / ".perk"
    cfg.mkdir()
    (cfg / "config.toml").write_text('[issues]\nbackend = "github"\n', encoding="utf-8")


@pytest.mark.parametrize("delivery", [None, "stacked"], ids=["incremental", "stacked"])
def test_phase2_gate_github_refinement_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, delivery: str | None
) -> None:
    """The named offline persistence gate (contracts.md §8.67, the GitHub arm): real resolvers,
    real store + adapter + service over ONE stateful ``gh`` fake, a real temp checkout as the
    code basis. Installed on ``subprocess.run`` — git keeps working through the pass-through."""
    root = tmp_path / "repo"
    root.mkdir()
    _scaffold_repo(root)
    fake = FakeGitHubIssues(page_size=2)
    monkeypatch.setattr(subprocess, "run", fake)
    store = resolve.resolve_objective_store(root)
    issues = resolve.resolve_issue_backend(root)
    assert isinstance(store, GitHubObjectiveStore)
    assert isinstance(issues, GitHubIssueBackend)

    # An objective with an unfinished (claimed + planned) predecessor, a blocked future node, and
    # one human comment on the carrier.
    nodes = [_node("1.1", "Predecessor work"), _node("1.2", "Refine me"), _node("2.1", "Future")]
    fake.seed_objective(
        OBJ, run_id=OBJ_RUN, nodes=nodes, prose="# Objective\n\nProse.\n", delivery=delivery
    )
    fake.add_comment(OBJ, "please keep the scope tight")
    store.update_objective_node(
        objective_id=OBJ_ID, node_id="1.1", status=objective.NodeStatus.PLANNING
    )
    store.update_objective_node(objective_id=OBJ_ID, node_id="1.1", pr="#301")
    store.update_objective_node(
        objective_id=OBJ_ID, node_id="1.1", status=objective.NodeStatus.IN_PROGRESS
    )
    store.update_objective_node(
        objective_id=OBJ_ID, node_id="2.1", status=objective.NodeStatus.BLOCKED
    )
    roadmap_before = store.get_objective(objective_id=OBJ_ID)
    assert roadmap_before is not None
    body_before = store.read_objective_body(objective_id=OBJ_ID)
    assert body_before is not None
    issue_body_before = str(fake.issues[OBJ]["body"])
    body_comment_before = dict(_body_comment(fake))
    state_before = _non_comment_state(fake)

    # The actual temp-checkout code basis (the producers the authoring caller uses) — git runs
    # through the patched subprocess.run.
    head_sha = git.resolve_commit(root, "HEAD")
    assert head_sha is not None
    (root / "scratch.txt").write_text("wip\n", encoding="utf-8")  # a dirty tree is recorded
    captured_at = plan.now_iso()
    provenance = RefinementProvenance(
        authoring_run_id="01GATEAUTH",
        authored_at=plan.now_iso(),
        code_basis=RefinementCodeBasis(
            head_sha=head_sha, dirty=git.is_dirty(root), captured_at=captured_at
        ),
    )
    assert provenance.code_basis.dirty is True

    # Select (default): the predecessor is ineligible, 1.2 is the first eligible absence.
    read = service.select_refinement_target(store, issues, objective_id=OBJ_ID)
    assert read.target.identity.node_id == "1.2" and read.saved is None
    assert read.target.identity.carrier_id == OBJ_ID and read.target.carrier_identifier == f"#{OBJ}"
    blocked = service.select_refinement_target(store, issues, objective_id=OBJ_ID, node_id="2.1")
    assert blocked.target.status is objective.NodeStatus.BLOCKED and blocked.target.eligible

    # Save a long refinement.
    refine_start = len(fake.calls)
    document = codec.document_for_target(read.target, markdown=LONG_MARKDOWN, provenance=provenance)
    saved = service.save_node_refinement(
        store, issues, request=RefinementSaveRequest(document=document, expected=read.expected)
    )
    assert fake.mutations(refine_start) == [f"POST issues/{OBJ}/comments"]
    [comment] = _refinement_comments(fake)
    assert comment["body"] == codec.render_refinement(document)
    assert saved.comment.id == str(comment["id"])
    assert saved.document.markdown == LONG_MARKDOWN and len(LONG_MARKDOWN) > 1500
    assert saved.document.provenance == provenance

    # Read back, then replace (same comment id), then retry the replacement (no mutation).
    back = service.read_node_refinement(store, issues, objective_id=OBJ_ID, node_id="1.2")
    assert back.saved == saved and back.source_changed is False
    replacement = codec.document_for_target(
        back.target, markdown="## Replaced\n\nShorter.\n", provenance=provenance
    )
    request = RefinementSaveRequest(document=replacement, expected=back.expected)
    replaced = service.save_node_refinement(store, issues, request=request)
    assert replaced.comment.id == saved.comment.id
    assert replaced.document.provenance == provenance  # preserved, never regenerated
    assert "step 1:" not in replaced.comment.body
    retry_start = len(fake.calls)
    assert service.save_node_refinement(store, issues, request=request) == replaced
    assert fake.mutations(retry_start) == []
    # The refinement's mutation log: one POST + one PATCH on the comment — never an issue PATCH.
    assert fake.mutations(refine_start) == [
        f"POST issues/{OBJ}/comments",
        f"PATCH issues/comments/{saved.comment.id}",
    ]
    assert len(_refinement_comments(fake)) == 1
    # Every scan paginated (three comments over page_size=2): a cursor-carrying GraphQL call.
    graphql = fake.graphql_calls(refine_start)
    assert len(graphql) >= 2
    assert any(any(tok.startswith("cursor=") for tok in gh) for gh in graphql)

    # Unchanged roadmap block / header / objective-body comment / issue body bytes.
    assert store.get_objective(objective_id=OBJ_ID) == roadmap_before
    assert store.read_objective_body(objective_id=OBJ_ID) == body_before
    assert str(fake.issues[OBJ]["body"]) == issue_body_before
    assert _body_comment(fake) == body_comment_before
    assert _non_comment_state(fake) == state_before

    # The 65,536-character refusal: typed backend_error, the diagnostic kept, the stored record
    # unchanged and still readable.
    huge = codec.document_for_target(
        back.target, markdown="x" * 66_000 + "\n", provenance=provenance
    )
    huge_start = len(fake.calls)
    err = _err(
        lambda: service.save_node_refinement(
            store,
            issues,
            request=RefinementSaveRequest(document=huge, expected=replaced_expectation(replaced)),
        ),
        RefinementErrorCode.BACKEND_ERROR,
        write_attempted=True,
    )
    assert "Body is too long" in str(err)
    assert fake.mutations(huge_start) == [f"PATCH issues/comments/{saved.comment.id}"]
    stored = fake.comment_by_id(int(saved.comment.id))
    assert stored is not None and stored["body"] == replaced.comment.body
    still = service.read_node_refinement(store, issues, objective_id=OBJ_ID, node_id="1.2")
    assert still.saved == replaced

    # Then plan/refinement interleaving on the single-issue carrier: claim + backlink the refined
    # node — the roadmap block and body-comment table re-render, the refinement comment stays
    # byte-untouched.
    refinement_bytes = dict(stored)
    plan_start = len(fake.calls)
    store.update_objective_node(
        objective_id=OBJ_ID, node_id="1.2", status=objective.NodeStatus.PLANNING
    )
    store.update_objective_node(objective_id=OBJ_ID, node_id="1.2", pr="#302")
    plan_mutations = fake.mutations(plan_start)
    assert f"PATCH issues/{OBJ}" in plan_mutations
    assert f"PATCH issues/comments/{body_comment_before['id']}" in plan_mutations
    assert f"PATCH issues/comments/{saved.comment.id}" not in plan_mutations
    assert fake.comment_by_id(int(saved.comment.id)) == refinement_bytes
    assert str(fake.issues[OBJ]["body"]) != issue_body_before
    assert "#302" in str(_body_comment(fake)["body"])
    # Historical refinement reads remain available; new saves refuse; nothing else mutates.
    historical = service.read_node_refinement(store, issues, objective_id=OBJ_ID, node_id="1.2")
    assert historical.saved is not None
    assert historical.saved.document == replaced.document
    assert historical.saved.comment.id == replaced.comment.id
    assert historical.target.eligible is False and historical.target.plan_ref == "#302"
    refuse_start = len(fake.calls)
    _err(
        lambda: service.save_node_refinement(
            store,
            issues,
            request=RefinementSaveRequest(
                document=codec.document_for_target(
                    historical.target, markdown="## Too late\n", provenance=provenance
                ),
                expected=historical.expected,
            ),
        ),
        RefinementErrorCode.NODE_INELIGIBLE,
        write_attempted=False,
    )
    assert fake.mutations(refuse_start) == []
    # Engagement renders omit the refinement and keep the human comment.
    rendered = render_objective_engagement(
        project_comments=store.read_comments(objective_id=OBJ_ID),
        project_description_edits=(),
        node_engagements=(),
    )
    assert rendered is not None and "please keep the scope tight" in rendered
    assert codec.MARKER_FAMILY not in rendered and "Replaced" not in rendered
    after = store.get_objective(objective_id=OBJ_ID)
    assert after is not None
    statuses = {n.id: n.status for n in after.nodes}
    assert statuses["1.1"] is objective.NodeStatus.IN_PROGRESS
    assert statuses["1.2"] is objective.NodeStatus.PLANNING
    assert statuses["2.1"] is objective.NodeStatus.BLOCKED
    assert (after.header.get("delivery") == "stacked") is (delivery == "stacked")


def replaced_expectation(saved: SavedRefinement) -> MarkedCommentExpectation:
    return MarkedCommentExpectation(comment_id=saved.comment.id, body_digest=saved.body_digest)
