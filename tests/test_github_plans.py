"""Tests for the GitHub plan/issue substrate (``perk/backends/github/plans.py``).

The plan/issue-tier ops relocated out of the gateway (plan/learn
issues, labels, marked comments, in-place adoption, plan reads). Split out of ``test_github.py``
so each test file matches its module home (mirrors the backend/resolve split).
"""

import json
import subprocess

import pytest
from _github_fakes import ROOT, _GhDispatch, _GhRecorder, _has, _header, _Proc

from perk import github, plan
from perk.backends.github import plans


def test_create_label_created(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GhRecorder(post=_Proc(0)))
    label = plans.create_label("perk:plan", color="c", description="d", repo_root=ROOT)
    assert label.created is True


def test_create_label_already_exists_is_ok(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", _GhRecorder(post=_Proc(1, stderr="HTTP 422: already_exists"))
    )
    label = plans.create_label("perk:plan", color="c", description="d", repo_root=ROOT)
    assert label.created is False  # idempotent, not an error


def test_create_label_other_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GhRecorder(post=_Proc(1, stderr="HTTP 403: forbidden")))
    with pytest.raises(github.GitHubError):
        plans.create_label("perk:plan", color="c", description="d", repo_root=ROOT)


def test_create_label_dry_run_does_not_shell(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("dry run must not shell gh")

    monkeypatch.setattr(subprocess, "run", boom)
    assert plans.create_label("x", color="c", description="d", repo_root=ROOT, dry_run=True)


def test_create_plan_issue_success_uses_body_file(monkeypatch):
    rec = _GhRecorder(post=_Proc(0, stdout=json.dumps({"number": 123, "url": "u/123"})))
    monkeypatch.setattr(subprocess, "run", rec)
    issue = plans.create_plan_issue(title="t", body="BODY-CONTENT", repo_root=ROOT, run_id=None)
    assert issue.number == 123 and issue.url == "u/123" and issue.existed is False
    # body went through `-F body=@file`, never inline
    assert rec.body_files == ["BODY-CONTENT"]
    assert all("body=BODY-CONTENT" not in tok for c in rec.calls for tok in c)


def test_create_plan_issue_non_2xx_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GhRecorder(post=_Proc(1, stderr="HTTP 500")))
    with pytest.raises(github.GitHubError):
        plans.create_plan_issue(title="t", body="b", repo_root=ROOT, run_id=None)


def test_create_plan_issue_gh_missing_raises(monkeypatch):
    def boom(*_a, **_k):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(github.GitHubError):
        plans.create_plan_issue(title="t", body="b", repo_root=ROOT, run_id=None)


def test_create_plan_issue_dry_run_does_not_shell(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("dry run must not shell gh")

    monkeypatch.setattr(subprocess, "run", boom)
    issue = plans.create_plan_issue(
        title="t", body="b", repo_root=ROOT, run_id="01RID", dry_run=True
    )
    assert issue.number == 0 and issue.existed is False


def test_create_plan_issue_idempotent_returns_existing_no_post(monkeypatch):
    existing = [{"number": 7, "html_url": "u/7", "body": _header("01RID")}]
    rec = _GhRecorder(get=_Proc(0, stdout=json.dumps(existing)))
    monkeypatch.setattr(subprocess, "run", rec)
    issue = plans.create_plan_issue(title="t", body="b", repo_root=ROOT, run_id="01RID")
    assert issue.number == 7 and issue.existed is True
    assert not rec.posted()  # dedup short-circuits before any POST


def test_find_plan_issue_match_and_no_match(monkeypatch):
    issues = [
        {"number": 1, "html_url": "u/1", "body": _header("OTHER")},
        {"number": 2, "html_url": "u/2", "body": _header("01RID")},
    ]
    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(0, stdout=json.dumps(issues))))
    found = plans.find_plan_issue(run_id="01RID", repo_root=ROOT)
    assert found is not None and found.number == 2

    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(0, stdout="[]")))
    assert plans.find_plan_issue(run_id="01RID", repo_root=ROOT) is None


# --- learn issue -------------------------------------------------------------------


def _learn_header(run_id: str, plan_number: int = 7) -> str:
    return plan.render_metadata_block(
        plan.LEARN_HEADER_KEY, {"run_id": run_id, "created": "t", "plan": plan_number}
    )


def test_find_learn_issue_is_label_scoped_and_ignores_the_plan_issue(monkeypatch):
    # The D10 regression: a list carrying the PLAN issue (same run_id, but its run_id lives in the
    # plan-header block) must NOT match find_learn_issue (which reads the learn-header block). This
    # is exactly what stops /learn from treating the plan issue as the learn issue.
    plan_issue = [{"number": 7, "html_url": "u/7", "body": _header("01RID")}]
    rec = _GhRecorder(get=_Proc(0, stdout=json.dumps(plan_issue)))
    monkeypatch.setattr(subprocess, "run", rec)
    assert plans.find_learn_issue(run_id="01RID", repo_root=ROOT) is None
    # ...and the lookup is label-scoped to perk:learn.
    assert any("labels=perk:learn" in tok for c in rec.calls for tok in c)


def test_find_learn_issue_matches_a_learn_issue_with_the_run_id(monkeypatch):
    learn_issue = [{"number": 99, "html_url": "u/99", "body": _learn_header("01RID")}]
    monkeypatch.setattr(
        subprocess, "run", _GhRecorder(get=_Proc(0, stdout=json.dumps(learn_issue)))
    )
    found = plans.find_learn_issue(run_id="01RID", repo_root=ROOT)
    assert found is not None and found.number == 99


def test_create_learn_issue_idempotent_returns_existing_no_create(monkeypatch):
    existing = [{"number": 99, "html_url": "u/99", "body": _learn_header("01RID")}]
    rec = _GhRecorder(get=_Proc(0, stdout=json.dumps(existing)))
    monkeypatch.setattr(subprocess, "run", rec)
    issue = plans.create_learn_issue(
        title="Learnings: X", body="b", repo_root=ROOT, run_id="01RID", plan_number=7
    )
    assert issue.number == 99 and issue.existed is True
    assert not rec.posted()  # dedup short-circuits before the label create + issue POST


def test_create_learn_issue_creates_with_label_and_header(monkeypatch):
    # No existing learn issue -> lazy-create the perk:learn label, then POST the issue with the
    # learn-header rendered into the body so a later find_learn_issue can match.
    rec = _GhRecorder(
        get=_Proc(0, stdout="[]"),
        post=_Proc(0, stdout=json.dumps({"number": 100, "url": "u/100"})),
    )
    monkeypatch.setattr(subprocess, "run", rec)
    issue = plans.create_learn_issue(
        title="Learnings: X", body="captured body", repo_root=ROOT, run_id="01RID", plan_number=7
    )
    assert issue.number == 100 and issue.existed is False
    assert any("name=perk:learn" in tok for c in rec.calls for tok in c)  # lazy label create
    body = rec.body_files[-1]
    assert plan.extract_run_id(body, header_key=plan.LEARN_HEADER_KEY) == "01RID"
    assert "captured body" in body
    # A decision-less call omits the captured-classification fields (back-compat).
    header = plan.find_metadata_block(body, plan.LEARN_HEADER_KEY)
    assert header is not None and "decision" not in header and "target" not in header


def test_create_learn_issue_persists_decision_and_target(monkeypatch):
    # The captured classification rides the learn-header (html style) and reads back via
    # find_metadata_block (contracts.md §8.35).
    rec = _GhRecorder(
        get=_Proc(0, stdout="[]"),
        post=_Proc(0, stdout=json.dumps({"number": 101, "url": "u/101"})),
    )
    monkeypatch.setattr(subprocess, "run", rec)
    plans.create_learn_issue(
        title="Learnings: X",
        body="captured body",
        repo_root=ROOT,
        run_id="01RID",
        plan_number=7,
        decision="UPDATE_EXISTING_DOC",
        target="docs/learned/workflow/foo.md",
    )
    header = plan.find_metadata_block(rec.body_files[-1], plan.LEARN_HEADER_KEY)
    assert header is not None
    assert header["decision"] == "UPDATE_EXISTING_DOC"
    assert header["target"] == "docs/learned/workflow/foo.md"
    assert header["plan"] == 7  # GitHub stores the int issue number, unchanged


# --- learned-docs consumer (hop-2) ----------------------------------------------------------


def test_list_learn_issues_parses_open_issues(monkeypatch):
    issues = [
        {"number": 45, "title": "L45", "html_url": "u/45", "body": "body 45"},
        {"number": 50, "title": "L50", "html_url": "u/50", "body": "body 50"},
        "not-a-dict",  # skipped defensively
        {"number": 60, "title": "PR", "html_url": "u/60", "body": "b", "pull_request": {}},
    ]
    rec = _GhRecorder(get=_Proc(0, stdout=json.dumps(issues)))
    monkeypatch.setattr(subprocess, "run", rec)
    summaries = plans.list_learn_issues(repo_root=ROOT)
    assert [s.number for s in summaries] == [45, 50]  # the PR + the non-dict are skipped
    assert summaries[0].title == "L45" and summaries[0].body == "body 45"
    assert any("labels=perk:learn" in tok for c in rec.calls for tok in c)


def test_list_learn_issues_raises_on_infra_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(1, stderr="HTTP 500")))
    with pytest.raises(github.GitHubError):
        plans.list_learn_issues(repo_root=ROOT)


# --- pending-learn backlog (`perk learn pending`) --------------------------------------------


def _plan_header_body(learn_state: str | None) -> str:
    fields: dict[str, object] = {"run_id": "01RID", "created": "t"}
    if learn_state is not None:
        fields["learn_state"] = learn_state
    return plan.render_metadata_block(plan.PLAN_HEADER_KEY, fields)


def test_list_plans_pending_learn_filters_to_pending_headers(monkeypatch):
    issues = [
        {
            "number": 10,
            "title": "P10",
            "html_url": "u/10",
            "body": _plan_header_body("pending"),
            "closed_at": "2026-01-02T03:04:05Z",
        },
        {"number": 11, "title": "P11", "html_url": "u/11", "body": _plan_header_body("captured")},
        {"number": 12, "title": "P12", "html_url": "u/12", "body": "no header block"},
        "not-a-dict",  # skipped defensively
        {"number": 13, "title": "PR", "html_url": "u/13", "body": "b", "pull_request": {}},
        {"number": 14, "title": "P14", "html_url": "u/14", "body": _plan_header_body("pending")},
    ]
    rec = _GhRecorder(get=_Proc(0, stdout=json.dumps(issues)))
    monkeypatch.setattr(subprocess, "run", rec)
    rows = plans.list_plans_pending_learn(repo_root=ROOT, limit=50)
    assert [r.number for r in rows] == [10, 14]
    assert rows[0].title == "P10" and rows[0].url == "u/10"
    assert rows[0].closed_at == "2026-01-02T03:04:05Z"
    assert rows[1].closed_at is None  # absent closed_at maps to None


def test_list_plans_pending_learn_sorts_closed_desc_none_last(monkeypatch):
    # Rows arrive in REST updated-desc order with closed_at out of order; the read must return
    # them closed-desc (the protocol's most-recently-closed-first promise), None-closed rows last.
    issues = [
        {
            "number": 20,
            "title": "P20",
            "html_url": "u/20",
            "body": _plan_header_body("pending"),
            "closed_at": "2026-01-01T00:00:00Z",
        },
        {"number": 21, "title": "P21", "html_url": "u/21", "body": _plan_header_body("pending")},
        {
            "number": 22,
            "title": "P22",
            "html_url": "u/22",
            "body": _plan_header_body("pending"),
            "closed_at": "2026-03-01T00:00:00Z",
        },
        {
            "number": 23,
            "title": "P23",
            "html_url": "u/23",
            "body": _plan_header_body("pending"),
            "closed_at": "2026-02-01T00:00:00Z",
        },
    ]
    rec = _GhRecorder(get=_Proc(0, stdout=json.dumps(issues)))
    monkeypatch.setattr(subprocess, "run", rec)
    rows = plans.list_plans_pending_learn(repo_root=ROOT, limit=50)
    assert [r.number for r in rows] == [22, 23, 20, 21]


def test_list_plans_pending_learn_query_shape(monkeypatch):
    # A non-default limit: proves the caller's value (not a hardcoded default) reaches per_page.
    rec = _GhRecorder(get=_Proc(0, stdout="[]"))
    monkeypatch.setattr(subprocess, "run", rec)
    plans.list_plans_pending_learn(repo_root=ROOT, limit=9)
    [call] = rec.calls
    for field in (
        "labels=perk:plan",
        "state=closed",
        "sort=updated",
        "direction=desc",
        "per_page=9",
    ):
        assert any(field in tok for tok in call), field


def test_list_plans_pending_learn_raises_on_infra_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(1, stderr="HTTP 500")))
    with pytest.raises(github.GitHubError):
        plans.list_plans_pending_learn(repo_root=ROOT, limit=50)


# --- gist issue (§8.41) --------------------------------------------------------------


def _gist_header(run_id: str, scope: str = "plan") -> str:
    return plan.render_metadata_block(
        plan.GIST_HEADER_KEY, {"run_id": run_id, "created": "t", "scope": scope}
    )


def test_find_gist_issue_is_label_scoped_and_ignores_the_plan_issue(monkeypatch):
    # A list carrying the PLAN issue (same run_id, but its run_id lives in the plan-header
    # block) must NOT match find_gist_issue (which reads the gist-header block).
    plan_issue = [{"number": 7, "html_url": "u/7", "body": _header("01RID")}]
    rec = _GhRecorder(get=_Proc(0, stdout=json.dumps(plan_issue)))
    monkeypatch.setattr(subprocess, "run", rec)
    assert plans.find_gist_issue(run_id="01RID", repo_root=ROOT) is None
    # ...and the lookup is label-scoped to perk:gist.
    assert any("labels=perk:gist" in tok for c in rec.calls for tok in c)


def test_find_gist_issue_matches_a_gist_issue_with_the_run_id(monkeypatch):
    gist_issue = [{"number": 88, "html_url": "u/88", "body": _gist_header("01RID")}]
    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(0, stdout=json.dumps(gist_issue))))
    found = plans.find_gist_issue(run_id="01RID", repo_root=ROOT)
    assert found is not None and found.number == 88


def test_create_gist_issue_idempotent_returns_existing_no_create(monkeypatch):
    existing = [{"number": 88, "html_url": "u/88", "body": _gist_header("01RID")}]
    rec = _GhRecorder(get=_Proc(0, stdout=json.dumps(existing)))
    monkeypatch.setattr(subprocess, "run", rec)
    issue = plans.create_gist_issue(
        title="Gist: X", body="b", repo_root=ROOT, run_id="01RID", scope="plan"
    )
    assert issue.number == 88 and issue.existed is True
    assert not rec.posted()  # dedup short-circuits before the label create + issue POST


def test_create_gist_issue_creates_with_label_and_header(monkeypatch):
    # No existing gist issue -> lazy-create the perk:gist label, then POST the issue with the
    # gist-header (incl. the scope) rendered into the body so a later find_gist_issue can match.
    rec = _GhRecorder(
        get=_Proc(0, stdout="[]"),
        post=_Proc(0, stdout=json.dumps({"number": 90, "url": "u/90"})),
    )
    monkeypatch.setattr(subprocess, "run", rec)
    issue = plans.create_gist_issue(
        title="Gist: X", body="intent prose", repo_root=ROOT, run_id="01RID", scope="objective"
    )
    assert issue.number == 90 and issue.existed is False
    assert any("name=perk:gist" in tok for c in rec.calls for tok in c)  # lazy label create
    body = rec.body_files[-1]
    assert plan.extract_run_id(body, header_key=plan.GIST_HEADER_KEY) == "01RID"
    assert "intent prose" in body
    header = plan.find_metadata_block(body, plan.GIST_HEADER_KEY)
    assert header is not None and header["scope"] == "objective"


def test_create_gist_issue_dry_run_does_not_shell(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("dry run must not shell gh")

    monkeypatch.setattr(subprocess, "run", boom)
    issue = plans.create_gist_issue(
        title="t", body="b", repo_root=ROOT, run_id="01RID", scope="plan", dry_run=True
    )
    assert issue.number == 0 and issue.existed is False


def test_list_gist_issues_parses_open_issues(monkeypatch):
    issues = [
        {"number": 45, "title": "G45", "html_url": "u/45", "body": "body 45"},
        "not-a-dict",  # skipped defensively
        {"number": 60, "title": "PR", "html_url": "u/60", "body": "b", "pull_request": {}},
    ]
    rec = _GhRecorder(get=_Proc(0, stdout=json.dumps(issues)))
    monkeypatch.setattr(subprocess, "run", rec)
    summaries = plans.list_gist_issues(repo_root=ROOT)
    assert [s.number for s in summaries] == [45]  # the PR + the non-dict are skipped
    assert summaries[0].title == "G45" and summaries[0].body == "body 45"
    assert any("labels=perk:gist" in tok for c in rec.calls for tok in c)


def test_list_gist_issues_raises_on_infra_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(1, stderr="HTTP 500")))
    with pytest.raises(github.GitHubError):
        plans.list_gist_issues(repo_root=ROOT)


def test_close_and_label_consolidated_labels_and_closes(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(args, **_):
        gh_args = args[1:]
        calls.append(gh_args)
        return _Proc(0, stdout="{}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert plans.close_and_label_consolidated(issue=45, repo_root=ROOT) is True
    # lazy label create + a labels POST (add) + a state=closed PATCH.
    assert any("name=perk:consolidated" in tok for c in calls for tok in c)
    assert any("labels[]=perk:consolidated" in tok for c in calls for tok in c)
    assert any("state=closed" in tok for c in calls for tok in c)
    assert any("PATCH" in c for c in calls)


def test_close_and_label_consolidated_dry_run_does_not_shell(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("dry run must not shell gh")

    monkeypatch.setattr(subprocess, "run", boom)
    assert plans.close_and_label_consolidated(issue=45, repo_root=ROOT, dry_run=True) is True


def test_reopen_issue_reopens_a_closed_issue(monkeypatch):
    rec = _GhDispatch(
        [
            (_has("issues/45", "GET"), _Proc(0, '{"state": "closed"}')),
            (_has("issues/45", "PATCH"), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    assert plans.reopen_issue(number=45, repo_root=ROOT) is True
    assert any("state=open" in tok for c in rec.calls for tok in c)
    assert rec.method_calls("PATCH") == 1


def test_reopen_issue_already_open_converges_without_a_write(monkeypatch):
    rec = _GhDispatch([(_has("issues/45", "GET"), _Proc(0, '{"state": "open"}'))])
    monkeypatch.setattr(subprocess, "run", rec)
    assert plans.reopen_issue(number=45, repo_root=ROOT) is False
    assert rec.method_calls("PATCH") == 0


def test_reopen_issue_dry_run_does_not_shell(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("dry run must not shell gh")

    monkeypatch.setattr(subprocess, "run", boom)
    assert plans.reopen_issue(number=45, repo_root=ROOT, dry_run=True) is False


def test_reopen_issue_raises_on_uninterpretable_state(monkeypatch):
    # A GET payload without a readable state must raise, never fall through to the PATCH
    # (which could claim a reopen write on an already-open issue — a false True).
    rec = _GhDispatch([(_has("issues/45", "GET"), _Proc(0, '{"weird": true}'))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(github.GitHubError, match="no state field"):
        plans.reopen_issue(number=45, repo_root=ROOT)
    assert rec.method_calls("PATCH") == 0


def test_reopen_issue_raises_on_patch_failure(monkeypatch):
    rec = _GhDispatch(
        [
            (_has("issues/45", "GET"), _Proc(0, '{"state": "closed"}')),
            (_has("issues/45", "PATCH"), _Proc(1, stderr="HTTP 500")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(github.GitHubError):
        plans.reopen_issue(number=45, repo_root=ROOT)


def test_close_and_label_consolidated_raises_on_label_failure(monkeypatch):
    # label create succeeds (422 idempotent), but the labels POST fails -> raise.
    def fake_run(args, **_):
        gh_args = args[1:]
        if "name=perk:consolidated" in gh_args:  # create_label POST
            return _Proc(0)
        if "labels[]=perk:consolidated" in gh_args:  # the add-label POST
            return _Proc(1, stderr="HTTP 500")
        return _Proc(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(github.GitHubError):
        plans.close_and_label_consolidated(issue=45, repo_root=ROOT)


# --------------------------------------------------------------- PR lifecycle ops


def test_update_plan_header_merges_fields(monkeypatch):
    body = _header("01RID")
    rec = _GhDispatch(
        [
            (_has("issues/123", ".body"), _Proc(0, body)),
            (_has("issues/123", "PATCH"), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    upd = plans.update_plan_header(
        issue=123, fields={"branch": "plan-123", "pr": "55"}, repo_root=ROOT
    )
    assert set(upd.fields_updated) == {"branch", "pr"} and upd.dry_run is False
    # the PATCHed body carries the merged header
    patched = rec.body_files[-1]
    merged = plan.find_metadata_block(patched, plan.PLAN_HEADER_KEY)
    assert merged is not None and merged["branch"] == "plan-123" and merged["pr"] == "55"
    assert merged["run_id"] == "01RID"  # untouched fields preserved


def test_update_plan_header_dry_run_does_not_patch(monkeypatch):
    rec = _GhDispatch([(_has("issues/123", ".body"), _Proc(0, _header("01RID")))])
    monkeypatch.setattr(subprocess, "run", rec)
    upd = plans.update_plan_header(
        issue=123, fields={"branch": "plan-123"}, repo_root=ROOT, dry_run=True
    )
    assert upd.dry_run is True and rec.method_calls("PATCH") == 0


def test_update_plan_header_rejects_unknown_field(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(0, _header("01RID")))
    with pytest.raises(github.GitHubError, match="unknown plan-header field"):
        plans.update_plan_header(issue=123, fields={"bogus": "x"}, repo_root=ROOT)


# ---------------------------------------------------- plan upsert (re-save)


def _comment_list(*bodies: str) -> str:
    return json.dumps([{"id": 100 + i, "body": b} for i, b in enumerate(bodies)])


def test_find_plan_body_comment_id_returns_matching_id(monkeypatch):
    listing = _comment_list("just chatter", plan.render_plan_body("# P\n\nbody"))
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issues/123/comments"), _Proc(0, listing))])
    )
    assert plans._find_plan_body_comment_id(123, ROOT) == 101


def test_find_plan_body_comment_id_none_when_no_match(monkeypatch):
    listing = _comment_list("nothing here", "still nothing")
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issues/123/comments"), _Proc(0, listing))])
    )
    assert plans._find_plan_body_comment_id(123, ROOT) is None


def test_update_plan_issue_patches_comment_and_title(monkeypatch):
    listing = _comment_list(plan.render_plan_body("# Old\n\nold body"))
    rec = _GhDispatch(
        [
            (_has("issues/123/comments"), _Proc(0, listing)),
            (_has("issues/comments/100", "PATCH"), _Proc(0, "{}")),
            (_has("issues/123", "PATCH", "title="), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    upd = plans.update_plan_issue(
        number=123,
        title="New Title",
        body_comment=plan.render_plan_body("# New\n\nnew body"),
        repo_root=ROOT,
    )
    assert upd.body_updated is True and upd.title_updated is True and upd.dry_run is False
    assert "new body" in rec.body_files[-1]  # the comment PATCH carried the new body
    title_patch = next(c for c in rec.calls if "PATCH" in c and any("title=" in t for t in c))
    assert "title=New Title" in title_patch


def test_update_plan_issue_falls_back_to_fresh_comment(monkeypatch):
    listing = _comment_list("no plan-body block here")
    rec = _GhDispatch(
        [
            (_has("issues/123/comments", "POST"), _Proc(0, "{}")),
            (_has("issues/123/comments"), _Proc(0, listing)),
            (_has("issues/123", "PATCH"), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    upd = plans.update_plan_issue(number=123, title="T", body_comment="BODY", repo_root=ROOT)
    assert upd.body_updated is False  # no plan-body comment -> fresh POST fallback
    assert rec.method_calls("POST") == 1


def test_update_plan_issue_dry_run_does_not_shell(monkeypatch):
    rec = _GhDispatch([])
    monkeypatch.setattr(subprocess, "run", rec)
    upd = plans.update_plan_issue(
        number=123, title="T", body_comment="B", repo_root=ROOT, dry_run=True
    )
    assert upd.dry_run is True and upd.body_updated is False and upd.title_updated is False
    assert rec.calls == []


# ----------------------------------------------------- in-place issue adoption (§8.29)


def test_read_issue_maps_fields(monkeypatch):
    payload = json.dumps(
        {"number": 7, "title": "Human title", "body": "do the thing", "state": "OPEN", "url": "u7"}
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        _GhDispatch([(_has("view", "number,title,body,state,url"), _Proc(0, payload))]),
    )
    src = plans.read_issue(number=7, repo_root=ROOT)
    assert src == plans.IssueRead(
        number=7, url="u7", title="Human title", body="do the thing", state="OPEN"
    )


def test_read_issue_none_when_not_found(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _Proc(1, stderr="gh: Not Found (HTTP 404)")
    )
    assert plans.read_issue(number=7, repo_root=ROOT) is None


def test_read_issue_malformed_payload_raises_labelled(monkeypatch):
    # `number` present but non-coercible to int -> ValidationError -> labelled GitHubError.
    payload = json.dumps({"number": "not-an-int", "title": "t"})
    monkeypatch.setattr(
        subprocess,
        "run",
        _GhDispatch([(_has("view", "number,title,body,state,url"), _Proc(0, payload))]),
    )
    with pytest.raises(github.GitHubError, match="read issue #7"):
        plans.read_issue(number=7, repo_root=ROOT)


def test_add_issue_label_posts_additively(monkeypatch):
    rec = _GhDispatch([(_has("issues/7/labels", "POST"), _Proc(0, "{}"))])
    monkeypatch.setattr(subprocess, "run", rec)
    assert plans.add_issue_label(issue=7, label="perk:plan", repo_root=ROOT) is True
    assert rec.method_calls("POST") == 1


def test_add_issue_label_dry_run_does_not_shell(monkeypatch):
    rec = _GhDispatch([])
    monkeypatch.setattr(subprocess, "run", rec)
    assert plans.add_issue_label(issue=7, label="perk:plan", repo_root=ROOT, dry_run=True) is False
    assert rec.calls == []


def test_adopt_issue_as_plan_stamps_in_place(monkeypatch):
    # The human issue has a verbatim body and NO plan-header (the cold door refuses one that does).
    rec = _GhDispatch(
        [
            (
                _has("view", "number,title,body,state,url"),
                _Proc(
                    0,
                    json.dumps(
                        {
                            "number": 7,
                            "title": "Human title",
                            "body": "HUMAN BODY VERBATIM",
                            "state": "OPEN",
                            "url": "u7",
                        }
                    ),
                ),
            ),
            (_has("{repo}/labels", "POST"), _Proc(0, "{}")),  # create_label
            (_has("issues/7/labels", "POST"), _Proc(0, "{}")),  # additive label add
            (_has("issues/7/comments", "POST"), _Proc(0, "{}")),  # plan-body comment POST
            (_has("issues/7/comments"), _Proc(0, "[]")),  # comment list (no plan-body yet)
            (_has("issues/7", ".body"), _Proc(0, "HUMAN BODY VERBATIM")),  # _get_issue_body
            (_has("issues/7", "PATCH"), _Proc(0, "{}")),  # body PATCH (header + callout)
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    header_fields = plan.render_plan_header_fields(
        plan.PlanHeader(run_id="RID", created="t", adopted_from="7")
    )
    result = plans.adopt_issue_as_plan(
        number=7,
        header_fields=header_fields,
        plan_markdown="# Adopted Plan\n\nthe plan body\n",
        callout=plan.plan_callout("7"),
        command="perk impl 7",
        repo_root=ROOT,
    )
    assert result == plans.PlanAdoption(number=7, url="u7", dry_run=False)
    # The PATCHed issue body stamps the header additively, preserves the human body verbatim, and
    # carries the impl callout — the title is NEVER PATCHed.
    patched = rec.body_files[0]
    assert "HUMAN BODY VERBATIM" in patched
    assert "perk impl 7" in patched
    stamped = plan.find_metadata_block(patched, plan.PLAN_HEADER_KEY)
    assert stamped is not None and stamped["adopted_from"] == "7"
    # The plan-body comment carries the authored markdown.
    assert "the plan body" in rec.body_files[1]
    assert not any("title=" in tok for c in rec.calls for tok in c)


def test_adopt_issue_as_plan_rejects_unknown_header_field(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(0, "{}"))
    with pytest.raises(github.GitHubError, match="unknown plan-header field"):
        plans.adopt_issue_as_plan(
            number=7,
            header_fields={"bogus": "x"},
            plan_markdown="# p\n",
            callout="C",
            command="perk impl 7",
            repo_root=ROOT,
        )


# ---------------------------------------------- marker-keyed comment upsert

MARKER = "<!-- perk:run-report:RID -->"


def test_find_comment_id_by_marker_matches(monkeypatch):
    listing = _comment_list("chatter", f"{MARKER}\nstarted note")
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issues/42/comments"), _Proc(0, listing))])
    )
    assert plans.find_comment_id_by_marker(issue=42, marker=MARKER, repo_root=ROOT) == 101


def test_find_comment_id_by_marker_no_match(monkeypatch):
    listing = _comment_list("nothing", "still nothing")
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issues/42/comments"), _Proc(0, listing))])
    )
    assert plans.find_comment_id_by_marker(issue=42, marker=MARKER, repo_root=ROOT) is None


def test_upsert_marked_comment_patches_existing(monkeypatch):
    listing = _comment_list(f"{MARKER}\nstarted note")
    rec = _GhDispatch(
        [
            (_has("issues/42/comments"), _Proc(0, listing)),
            (_has("issues/comments/100", "PATCH"), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    result = plans.upsert_marked_comment(
        issue=42, marker=MARKER, body=f"{MARKER}\nterminal note", repo_root=ROOT
    )
    assert result.posted is True
    assert rec.method_calls("PATCH") == 1 and rec.method_calls("POST") == 0
    assert "terminal note" in rec.body_files[-1]


def test_upsert_marked_comment_posts_new(monkeypatch):
    listing = _comment_list("no marker here")
    rec = _GhDispatch(
        [
            (_has("issues/42/comments", "POST"), _Proc(0, "{}")),
            (_has("issues/42/comments"), _Proc(0, listing)),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    result = plans.upsert_marked_comment(
        issue=42, marker=MARKER, body=f"{MARKER}\nstarted note", repo_root=ROOT
    )
    assert result.posted is True
    assert rec.method_calls("POST") == 1


def test_upsert_marked_comment_dry_run_does_not_shell(monkeypatch):
    rec = _GhDispatch([])
    monkeypatch.setattr(subprocess, "run", rec)
    result = plans.upsert_marked_comment(
        issue=42, marker=MARKER, body=MARKER, repo_root=ROOT, dry_run=True
    )
    assert result.posted is False and rec.calls == []


def test_get_plan_planned_has_no_pr(monkeypatch):
    issue = {"number": 7, "title": "T", "body": _header("01RID"), "state": "OPEN", "url": "u/7"}
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issue", "view"), _Proc(0, json.dumps(issue)))])
    )
    state = plans.get_plan(number=7, repo_root=ROOT)
    assert state is not None and state.title == "T" and state.pr is None
    assert state.state == "OPEN"  # populated from the fetched issue JSON


def test_get_plan_carries_closed_state(monkeypatch):
    issue = {"number": 7, "title": "T", "body": _header("01RID"), "state": "CLOSED", "url": "u/7"}
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issue", "view"), _Proc(0, json.dumps(issue)))])
    )
    state = plans.get_plan(number=7, repo_root=ROOT)
    assert state is not None and state.state == "CLOSED"


def test_get_plan_impl_fetches_pr(monkeypatch):
    header = plan.PlanHeader(
        run_id="01RID",
        created="t",
        lifecycle_stage=plan.LifecycleStage.IMPL,
        branch="plan-7",
        pr="55",
    )
    body = plan.render_metadata_block(plan.PLAN_HEADER_KEY, plan.render_plan_header_fields(header))
    issue = {"number": 7, "title": "T", "body": body, "state": "OPEN", "url": "u/7"}
    pr = {"number": 55, "html_url": "u/pr/55", "draft": False, "state": "open"}
    monkeypatch.setattr(
        subprocess,
        "run",
        _GhDispatch(
            [
                (_has("issue", "view"), _Proc(0, json.dumps(issue))),
                (_has("pulls/55"), _Proc(0, json.dumps(pr))),
            ]
        ),
    )
    state = plans.get_plan(number=7, repo_root=ROOT)
    assert state is not None and state.pr is not None
    assert state.pr.number == 55 and state.pr.state == "OPEN"


@pytest.mark.parametrize("raw_pr", ["garbage", "0", "-3", 0, -3, ["55"]])
def test_get_plan_malformed_pr_stays_raw_with_no_lookup(monkeypatch, raw_pr):
    # The shared tolerant read-boundary parser (§8.54): malformed/non-positive `pr` metadata
    # resolves NO PR — no pulls lookup is attempted (the _GhDispatch would fail loud on an
    # unmatched pulls call) — while the raw header value stays readable for classification.
    body = plan.render_metadata_block(
        plan.PLAN_HEADER_KEY, {"run_id": "01RID", "created": "t", "pr": raw_pr}
    )
    issue = {"number": 7, "title": "T", "body": body, "state": "OPEN", "url": "u/7"}
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issue", "view"), _Proc(0, json.dumps(issue)))])
    )
    state = plans.get_plan(number=7, repo_root=ROOT)
    assert state is not None and state.pr is None
    assert state.header["pr"] == raw_pr  # the raw claim is preserved, never rewritten


@pytest.mark.parametrize("raw_pr", ["", "  ", "None", None])
def test_get_plan_blank_or_none_pr_is_no_claim(monkeypatch, raw_pr):
    body = plan.render_metadata_block(
        plan.PLAN_HEADER_KEY, {"run_id": "01RID", "created": "t", "pr": raw_pr}
    )
    issue = {"number": 7, "title": "T", "body": body, "state": "OPEN", "url": "u/7"}
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issue", "view"), _Proc(0, json.dumps(issue)))])
    )
    state = plans.get_plan(number=7, repo_root=ROOT)
    assert state is not None and state.pr is None


def test_get_plan_not_found(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        _GhDispatch([(_has("issue", "view"), _Proc(1, stderr="GraphQL: Could not resolve (404)"))]),
    )
    assert plans.get_plan(number=999, repo_root=ROOT) is None


# --------------------------------------------------------------- land ops


def test_get_plan_body_extracts_from_first_comment(monkeypatch):
    markdown = "# Add retry\n\n## Steps\n1. Add helper\n2. Wire it in\n"
    comment_body = plan.render_plan_body(markdown)
    payload = json.dumps(
        {"body": "<!-- perk:metadata-block:plan-header -->", "comments": [{"body": comment_body}]}
    )
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Proc(0, payload))
    assert plans.get_plan_body(number=42, repo_root=ROOT) == markdown.strip()


def test_get_plan_body_none_when_no_block(monkeypatch):
    payload = json.dumps({"body": "just a header", "comments": []})
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Proc(0, payload))
    assert plans.get_plan_body(number=42, repo_root=ROOT) is None


def test_get_plan_body_missing_issue_returns_none(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Proc(1, stderr="not found"))
    assert plans.get_plan_body(number=999, repo_root=ROOT) is None


def test_get_plan_body_infra_failure_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Proc(1, stderr="HTTP 500"))
    with pytest.raises(github.GitHubError):
        plans.get_plan_body(number=42, repo_root=ROOT)


# --- PR body craft -----------------------------------------------------------------


def test_gist_adoption_round_trip(monkeypatch):
    """The §8.41 consumption round trip on GitHub: the REAL created gist body is eligible for the
    unchanged plan adoption door, the REAL adoption stamp lands the plan-header additively beside
    the gist-header (distinct block keys — no collision), and that stamped body is exactly what
    flips `adopted` in the backend's gist listing."""
    from perk import objective
    from perk.backends.github.backend import GitHubIssueBackend

    # 1. Create: capture the body `create_gist_issue` actually composes.
    rec = _GhRecorder(
        get=_Proc(0, stdout="[]"),
        post=_Proc(0, stdout=json.dumps({"number": 90, "url": "u/90"})),
    )
    monkeypatch.setattr(subprocess, "run", rec)
    plans.create_gist_issue(
        title="Faster reviews", body="intent prose", repo_root=ROOT, run_id="01G", scope="plan"
    )
    gist_body = rec.body_files[-1]

    # 2. Eligibility for the UNCHANGED doors: OPEN is the issue's own state; the body carries no
    #    plan-header (`plan from` would not flag already_plan) and no objective-header.
    assert plan.find_metadata_block(gist_body, plan.PLAN_HEADER_KEY) is None
    assert not plan.has_metadata_block(gist_body, objective.OBJECTIVE_HEADER_KEY)

    # 3. Adopt in place through the REAL stamp (the writer `plan save --adopt-from` calls),
    #    reading the created gist body back as the issue body.
    rec2 = _GhDispatch(
        [
            (
                _has("view", "number,title,body,state,url"),
                _Proc(
                    0,
                    json.dumps(
                        {
                            "number": 90,
                            "title": "Faster reviews",
                            "body": gist_body,
                            "state": "OPEN",
                            "url": "u/90",
                        }
                    ),
                ),
            ),
            (_has("{repo}/labels", "POST"), _Proc(0, "{}")),
            (_has("issues/90/labels", "POST"), _Proc(0, "{}")),
            (_has("issues/90/comments", "POST"), _Proc(0, "{}")),
            (_has("issues/90/comments"), _Proc(0, "[]")),
            (_has("issues/90", ".body"), _Proc(0, gist_body)),
            (_has("issues/90", "PATCH"), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec2)
    header_fields = plan.render_plan_header_fields(
        plan.PlanHeader(run_id="01P", created="t", adopted_from="90")
    )
    plans.adopt_issue_as_plan(
        number=90,
        header_fields=header_fields,
        plan_markdown="# The plan\n",
        callout=plan.plan_callout("90"),
        command="perk impl 90",
        repo_root=ROOT,
    )
    adopted_body = rec2.body_files[0]

    # 4. The additive stamp: both blocks coexist — the gist-header still parses (run_id + scope
    #    intact), the plan-header joined it, the prose survived.
    gist_header = plan.parse_gist_header(adopted_body)
    assert gist_header is not None and gist_header.run_id == "01G"
    assert gist_header.scope is plan.GistScope.PLAN
    stamped = plan.find_metadata_block(adopted_body, plan.PLAN_HEADER_KEY)
    assert stamped is not None and stamped["adopted_from"] == "90"
    assert "intent prose" in adopted_body

    # 5. The stamped body is exactly what flips `adopted` in the gist listing (the default
    #    `perk gist list` view hides adopted rows; `--all` marks them).
    monkeypatch.setattr(
        plans,
        "list_gist_issues",
        lambda **_: (
            plans.GistIssueSummary(number=88, title="fresh", url="u/88", body=gist_body),
            plans.GistIssueSummary(
                number=90, title="Faster reviews", url="u/90", body=adopted_body
            ),
        ),
    )
    fresh, adopted = GitHubIssueBackend(ROOT).list_gist_issues()
    assert fresh.adopted is False and adopted.adopted is True
    assert adopted.scope == "plan"
