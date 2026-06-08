import json
import subprocess
from pathlib import Path

import click
import pytest

from perk import github, objective, plan
from perk.cli.context import PerkContext, require_github
from perk.cli.ensure import UserFacingCliError


class _Proc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


ROOT = Path("/repo")


def test_check_auth_authed(monkeypatch):
    def fake_run(args, **_):
        if args[1] == "auth":
            return _Proc(0, "✓ Logged in\n  - Token scopes: 'repo', 'read:org'\n")
        if args[1] == "api":
            return _Proc(0, "octocat\n")
        return _Proc(1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    auth = github.check_auth()
    assert auth.ok and auth.user == "octocat"
    assert "repo" in auth.scopes and "read:org" in auth.scopes


def test_check_auth_unauthed(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda args, **_: _Proc(1, "", "not logged in"))
    auth = github.check_auth()
    assert not auth.ok and auth.error and "not logged in" in auth.error


def test_check_repo_access_pushable(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **_: _Proc(0, '{"nameWithOwner":"me/repo","viewerPermission":"WRITE"}'),
    )
    ra = github.check_repo_access(Path("/x"))
    assert ra.ok and ra.repo == "me/repo" and ra.can_push


def test_check_repo_access_readonly(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **_: _Proc(0, '{"nameWithOwner":"me/repo","viewerPermission":"READ"}'),
    )
    ra = github.check_repo_access(Path("/x"))
    assert ra.ok and not ra.can_push


def test_gh_missing_raises_githuberror(monkeypatch):
    def boom(*_a, **_k):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(github.GitHubError):
        github.check_auth()


def test_check_repo_access_timeout_raises_githuberror(monkeypatch):
    # check_repo_access routes through _run, so a timeout becomes GitHubError (the
    # non-fatal guard in run_init catches it) rather than a raw TimeoutExpired.
    def timeout(args, **_):
        raise subprocess.TimeoutExpired(args, 15)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(github.GitHubError):
        github.check_repo_access(Path("/x"))


def test_require_github_raises_when_unauthed(monkeypatch):
    monkeypatch.setattr(github, "check_auth", lambda: github.AuthStatus(False, None, (), "no"))
    ctx = click.Context(
        click.Command("x"), obj=PerkContext.for_test(cwd=Path("/r"), repo_root=Path("/r"))
    )
    with pytest.raises(UserFacingCliError, match="not authenticated"):
        require_github(ctx)


def test_require_github_returns_status_when_authed(monkeypatch):
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )
    ctx = click.Context(
        click.Command("x"), obj=PerkContext.for_test(cwd=Path("/r"), repo_root=Path("/r"))
    )
    assert require_github(ctx).user == "octocat"


# --------------------------------------------------------- runner-prerequisite reads (Node 2.4)


def test_secret_exists_present(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda args, **_: _Proc(0, "{}"))
    assert github.secret_exists(name="PERK_GH_PAT", repo_root=ROOT) is True


def test_secret_exists_absent_404(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda args, **_: _Proc(1, "", "gh: Not Found (HTTP 404)")
    )
    assert github.secret_exists(name="PERK_GH_PAT", repo_root=ROOT) is False


def test_secret_exists_unknown_403(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda args, **_: _Proc(1, "", "gh: Forbidden (HTTP 403)")
    )
    assert github.secret_exists(name="PERK_GH_PAT", repo_root=ROOT) is None


def test_secret_exists_gh_missing_raises(monkeypatch):
    def boom(*_a, **_k):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(github.GitHubError):
        github.secret_exists(name="PERK_GH_PAT", repo_root=ROOT)


def test_get_workflow_permissions_parses(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **_: _Proc(
            0,
            '{"default_workflow_permissions":"write","can_approve_pull_request_reviews":true}',
        ),
    )
    perms = github.get_workflow_permissions(repo_root=ROOT)
    assert perms is not None
    assert perms.default_workflow_permissions == "write"
    assert perms.can_approve_pull_request_reviews is True


def test_get_workflow_permissions_none_on_nonzero(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda args, **_: _Proc(1, "", "boom"))
    assert github.get_workflow_permissions(repo_root=ROOT) is None


def test_get_workflow_permissions_unparseable_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda args, **_: _Proc(0, "not json"))
    with pytest.raises(github.GitHubError):
        github.get_workflow_permissions(repo_root=ROOT)


def test_get_repo_variable_value(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda args, **_: _Proc(0, "false\n"))
    assert github.get_repo_variable(name="PERK_ENABLED", repo_root=ROOT) == "false"


def test_get_repo_variable_absent_404(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda args, **_: _Proc(1, "", "gh: Not Found (HTTP 404)")
    )
    assert github.get_repo_variable(name="PERK_ENABLED", repo_root=ROOT) is None


# --------------------------------------------------------------- mutation ops (T2a)


class _GhRecorder:
    """Records `gh` argv and returns a configured `_Proc` per HTTP method."""

    def __init__(self, *, get: _Proc | None = None, post: _Proc | None = None) -> None:
        self._get = get or _Proc(0, "[]")
        self._post = post or _Proc(0, "{}")
        self.calls: list[list[str]] = []
        self.body_files: list[str] = []  # body content read from `-F body=@<path>` at call time

    def __call__(self, args, **_):
        gh_args = args[1:]  # drop "gh"
        self.calls.append(gh_args)
        for tok in gh_args:
            if tok.startswith("body=@"):
                self.body_files.append(Path(tok[len("body=@") :]).read_text(encoding="utf-8"))
        is_post = "POST" in gh_args
        return self._post if is_post else self._get

    def posted(self) -> bool:
        return any("POST" in c for c in self.calls)


def test_create_label_created(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GhRecorder(post=_Proc(0)))
    label = github.create_label("perk:plan", color="c", description="d", repo_root=ROOT)
    assert label.created is True


def test_create_label_already_exists_is_ok(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", _GhRecorder(post=_Proc(1, stderr="HTTP 422: already_exists"))
    )
    label = github.create_label("perk:plan", color="c", description="d", repo_root=ROOT)
    assert label.created is False  # idempotent, not an error


def test_create_label_other_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GhRecorder(post=_Proc(1, stderr="HTTP 403: forbidden")))
    with pytest.raises(github.GitHubError):
        github.create_label("perk:plan", color="c", description="d", repo_root=ROOT)


def test_create_label_dry_run_does_not_shell(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("dry run must not shell gh")

    monkeypatch.setattr(subprocess, "run", boom)
    assert github.create_label("x", color="c", description="d", repo_root=ROOT, dry_run=True)


def test_create_plan_issue_success_uses_body_file(monkeypatch):
    rec = _GhRecorder(post=_Proc(0, stdout=json.dumps({"number": 123, "url": "u/123"})))
    monkeypatch.setattr(subprocess, "run", rec)
    issue = github.create_plan_issue(title="t", body="BODY-CONTENT", repo_root=ROOT, run_id=None)
    assert issue.number == 123 and issue.url == "u/123" and issue.existed is False
    # body went through `-F body=@file`, never inline
    assert rec.body_files == ["BODY-CONTENT"]
    assert all("body=BODY-CONTENT" not in tok for c in rec.calls for tok in c)


def test_create_plan_issue_non_2xx_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GhRecorder(post=_Proc(1, stderr="HTTP 500")))
    with pytest.raises(github.GitHubError):
        github.create_plan_issue(title="t", body="b", repo_root=ROOT, run_id=None)


def test_create_plan_issue_gh_missing_raises(monkeypatch):
    def boom(*_a, **_k):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(github.GitHubError):
        github.create_plan_issue(title="t", body="b", repo_root=ROOT, run_id=None)


def test_create_plan_issue_dry_run_does_not_shell(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("dry run must not shell gh")

    monkeypatch.setattr(subprocess, "run", boom)
    issue = github.create_plan_issue(
        title="t", body="b", repo_root=ROOT, run_id="01RID", dry_run=True
    )
    assert issue.number == 0 and issue.existed is False


def test_create_plan_issue_idempotent_returns_existing_no_post(monkeypatch):
    existing = [{"number": 7, "html_url": "u/7", "body": _header("01RID")}]
    rec = _GhRecorder(get=_Proc(0, stdout=json.dumps(existing)))
    monkeypatch.setattr(subprocess, "run", rec)
    issue = github.create_plan_issue(title="t", body="b", repo_root=ROOT, run_id="01RID")
    assert issue.number == 7 and issue.existed is True
    assert not rec.posted()  # dedup short-circuits before any POST


def test_find_plan_issue_match_and_no_match(monkeypatch):
    issues = [
        {"number": 1, "html_url": "u/1", "body": _header("OTHER")},
        {"number": 2, "html_url": "u/2", "body": _header("01RID")},
    ]
    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(0, stdout=json.dumps(issues))))
    found = github.find_plan_issue(run_id="01RID", repo_root=ROOT)
    assert found is not None and found.number == 2

    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(0, stdout="[]")))
    assert github.find_plan_issue(run_id="01RID", repo_root=ROOT) is None


# --- learn issue (P2.T8b) -------------------------------------------------------------------


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
    assert github.find_learn_issue(run_id="01RID", repo_root=ROOT) is None
    # ...and the lookup is label-scoped to perk:learn.
    assert any("labels=perk:learn" in tok for c in rec.calls for tok in c)


def test_find_learn_issue_matches_a_learn_issue_with_the_run_id(monkeypatch):
    learn_issue = [{"number": 99, "html_url": "u/99", "body": _learn_header("01RID")}]
    monkeypatch.setattr(
        subprocess, "run", _GhRecorder(get=_Proc(0, stdout=json.dumps(learn_issue)))
    )
    found = github.find_learn_issue(run_id="01RID", repo_root=ROOT)
    assert found is not None and found.number == 99


def test_create_learn_issue_idempotent_returns_existing_no_create(monkeypatch):
    existing = [{"number": 99, "html_url": "u/99", "body": _learn_header("01RID")}]
    rec = _GhRecorder(get=_Proc(0, stdout=json.dumps(existing)))
    monkeypatch.setattr(subprocess, "run", rec)
    issue = github.create_learn_issue(
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
    issue = github.create_learn_issue(
        title="Learnings: X", body="captured body", repo_root=ROOT, run_id="01RID", plan_number=7
    )
    assert issue.number == 100 and issue.existed is False
    assert any("name=perk:learn" in tok for c in rec.calls for tok in c)  # lazy label create
    body = rec.body_files[-1]
    assert plan.extract_run_id(body, header_key=plan.LEARN_HEADER_KEY) == "01RID"
    assert "captured body" in body


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
    summaries = github.list_learn_issues(repo_root=ROOT)
    assert [s.number for s in summaries] == [45, 50]  # the PR + the non-dict are skipped
    assert summaries[0].title == "L45" and summaries[0].body == "body 45"
    assert any("labels=perk:learn" in tok for c in rec.calls for tok in c)


def test_list_learn_issues_raises_on_infra_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _GhRecorder(get=_Proc(1, stderr="HTTP 500")))
    with pytest.raises(github.GitHubError):
        github.list_learn_issues(repo_root=ROOT)


def test_close_and_label_consolidated_labels_and_closes(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(args, **_):
        gh_args = args[1:]
        calls.append(gh_args)
        return _Proc(0, stdout="{}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert github.close_and_label_consolidated(issue=45, repo_root=ROOT) is True
    # lazy label create + a labels POST (add) + a state=closed PATCH.
    assert any("name=perk:consolidated" in tok for c in calls for tok in c)
    assert any("labels[]=perk:consolidated" in tok for c in calls for tok in c)
    assert any("state=closed" in tok for c in calls for tok in c)
    assert any("PATCH" in c for c in calls)


def test_close_and_label_consolidated_dry_run_does_not_shell(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("dry run must not shell gh")

    monkeypatch.setattr(subprocess, "run", boom)
    assert github.close_and_label_consolidated(issue=45, repo_root=ROOT, dry_run=True) is True


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
        github.close_and_label_consolidated(issue=45, repo_root=ROOT)


def _header(run_id: str) -> str:
    return plan.render_metadata_block(
        plan.PLAN_HEADER_KEY, plan.PlanHeader(run_id=run_id, created="t").to_data()
    )


# --------------------------------------------------------------- PR lifecycle ops (T5a)


class _GhDispatch:
    """Route `gh` argv to a `_Proc` via (predicate, proc) handlers; record calls + body files."""

    def __init__(self, handlers) -> None:
        self.handlers = handlers
        self.calls: list[list[str]] = []
        self.body_files: list[str] = []

    def __call__(self, args, **_):
        gh = args[1:]
        self.calls.append(gh)
        for tok in gh:
            if tok.startswith("body=@"):
                self.body_files.append(Path(tok[len("body=@") :]).read_text(encoding="utf-8"))
        for pred, proc in self.handlers:
            if pred(gh):
                return proc
        return _Proc(1, stderr="unhandled: " + " ".join(gh))

    def method_calls(self, method: str) -> int:
        return sum(1 for c in self.calls if method in c)


def _has(*tokens):
    # substring match per token (gh endpoints are like "repos/{owner}/{repo}/pulls").
    return lambda gh: all(any(t in tok for tok in gh) for t in tokens)


def test_default_branch(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        _GhDispatch([(_has("repo", "view", "defaultBranchRef"), _Proc(0, "main\n"))]),
    )
    assert github.default_branch(ROOT) == "main"


def test_find_pr_for_branch_prefers_open(monkeypatch):
    pulls = [
        {"number": 1, "html_url": "u/1", "state": "closed", "draft": False},
        {"number": 2, "html_url": "u/2", "state": "open", "draft": True},
    ]
    monkeypatch.setattr(
        subprocess,
        "run",
        _GhDispatch(
            [
                (_has("repo", "view", "owner"), _Proc(0, "me\n")),
                (_has("pulls", "GET"), _Proc(0, json.dumps(pulls))),
            ]
        ),
    )
    pr = github.find_pr_for_branch(branch="plan-7", repo_root=ROOT)
    assert pr is not None and pr.number == 2 and pr.is_draft and pr.state == "OPEN"


def test_find_pr_for_branch_none(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        _GhDispatch(
            [
                (_has("repo", "view", "owner"), _Proc(0, "me\n")),
                (_has("pulls", "GET"), _Proc(0, "[]")),
            ]
        ),
    )
    assert github.find_pr_for_branch(branch="plan-7", repo_root=ROOT) is None


def test_create_pr_idempotent_returns_existing_no_post(monkeypatch):
    existing = [{"number": 9, "html_url": "u/9", "state": "open", "draft": True}]
    rec = _GhDispatch(
        [
            (_has("repo", "view", "owner"), _Proc(0, "me\n")),
            (_has("pulls", "GET"), _Proc(0, json.dumps(existing))),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    pr = github.create_pr(head="plan-7", base="main", title="t", body="b", repo_root=ROOT)
    assert pr.number == 9 and pr.existed is True
    assert rec.method_calls("POST") == 0  # dedup short-circuits the create


def test_create_pr_creates_when_none_uses_body_file(monkeypatch):
    created = {"number": 10, "html_url": "u/10", "draft": True, "state": "open"}
    rec = _GhDispatch(
        [
            (_has("repo", "view", "owner"), _Proc(0, "me\n")),
            (_has("pulls", "GET"), _Proc(0, "[]")),
            (_has("pulls", "POST"), _Proc(0, json.dumps(created))),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    pr = github.create_pr(head="plan-7", base="main", title="t", body="PR-BODY", repo_root=ROOT)
    assert pr.number == 10 and pr.existed is False and pr.is_draft
    assert rec.body_files == ["PR-BODY"]  # body via file, never inline
    assert all("body=PR-BODY" not in tok for c in rec.calls for tok in c)


def test_update_plan_header_merges_fields(monkeypatch):
    body = _header("01RID")
    rec = _GhDispatch(
        [
            (_has("issues/123", ".body"), _Proc(0, body)),
            (_has("issues/123", "PATCH"), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    upd = github.update_plan_header(
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
    upd = github.update_plan_header(
        issue=123, fields={"branch": "plan-123"}, repo_root=ROOT, dry_run=True
    )
    assert upd.dry_run is True and rec.method_calls("PATCH") == 0


def test_update_plan_header_rejects_unknown_field(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(0, _header("01RID")))
    with pytest.raises(github.GitHubError, match="unknown plan-header field"):
        github.update_plan_header(issue=123, fields={"bogus": "x"}, repo_root=ROOT)


# ---------------------------------------------------- plan upsert (re-save, P2.T13)


def _comment_list(*bodies: str) -> str:
    return json.dumps([{"id": 100 + i, "body": b} for i, b in enumerate(bodies)])


def test_find_plan_body_comment_id_returns_matching_id(monkeypatch):
    listing = _comment_list("just chatter", plan.render_plan_body("# P\n\nbody"))
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issues/123/comments"), _Proc(0, listing))])
    )
    assert github._find_plan_body_comment_id(123, ROOT) == 101


def test_find_plan_body_comment_id_none_when_no_match(monkeypatch):
    listing = _comment_list("nothing here", "still nothing")
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issues/123/comments"), _Proc(0, listing))])
    )
    assert github._find_plan_body_comment_id(123, ROOT) is None


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
    upd = github.update_plan_issue(
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
    upd = github.update_plan_issue(number=123, title="T", body_comment="BODY", repo_root=ROOT)
    assert upd.body_updated is False  # no plan-body comment -> fresh POST fallback
    assert rec.method_calls("POST") == 1


def test_update_plan_issue_dry_run_does_not_shell(monkeypatch):
    rec = _GhDispatch([])
    monkeypatch.setattr(subprocess, "run", rec)
    upd = github.update_plan_issue(
        number=123, title="T", body_comment="B", repo_root=ROOT, dry_run=True
    )
    assert upd.dry_run is True and upd.body_updated is False and upd.title_updated is False
    assert rec.calls == []


# ---------------------------------------------- marker-keyed comment upsert (Node 2.3)

MARKER = "<!-- perk:run-report:RID -->"


def test_find_comment_id_by_marker_matches(monkeypatch):
    listing = _comment_list("chatter", f"{MARKER}\nstarted note")
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issues/42/comments"), _Proc(0, listing))])
    )
    assert github.find_comment_id_by_marker(issue=42, marker=MARKER, repo_root=ROOT) == 101


def test_find_comment_id_by_marker_no_match(monkeypatch):
    listing = _comment_list("nothing", "still nothing")
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issues/42/comments"), _Proc(0, listing))])
    )
    assert github.find_comment_id_by_marker(issue=42, marker=MARKER, repo_root=ROOT) is None


def test_upsert_marked_comment_patches_existing(monkeypatch):
    listing = _comment_list(f"{MARKER}\nstarted note")
    rec = _GhDispatch(
        [
            (_has("issues/42/comments"), _Proc(0, listing)),
            (_has("issues/comments/100", "PATCH"), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    result = github.upsert_marked_comment(
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
    result = github.upsert_marked_comment(
        issue=42, marker=MARKER, body=f"{MARKER}\nstarted note", repo_root=ROOT
    )
    assert result.posted is True
    assert rec.method_calls("POST") == 1


def test_upsert_marked_comment_dry_run_does_not_shell(monkeypatch):
    rec = _GhDispatch([])
    monkeypatch.setattr(subprocess, "run", rec)
    result = github.upsert_marked_comment(
        issue=42, marker=MARKER, body=MARKER, repo_root=ROOT, dry_run=True
    )
    assert result.posted is False and rec.calls == []


def test_get_plan_planned_has_no_pr(monkeypatch):
    issue = {"number": 7, "title": "T", "body": _header("01RID"), "state": "OPEN", "url": "u/7"}
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issue", "view"), _Proc(0, json.dumps(issue)))])
    )
    state = github.get_plan(number=7, repo_root=ROOT)
    assert state is not None and state.title == "T" and state.pr is None
    assert state.state == "OPEN"  # populated from the fetched issue JSON


def test_get_plan_carries_closed_state(monkeypatch):
    issue = {"number": 7, "title": "T", "body": _header("01RID"), "state": "CLOSED", "url": "u/7"}
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issue", "view"), _Proc(0, json.dumps(issue)))])
    )
    state = github.get_plan(number=7, repo_root=ROOT)
    assert state is not None and state.state == "CLOSED"


def test_get_plan_impl_fetches_pr(monkeypatch):
    header = plan.PlanHeader(
        run_id="01RID",
        created="t",
        lifecycle_stage=plan.LifecycleStage.IMPL,
        branch="plan-7",
        pr="55",
    )
    body = plan.render_metadata_block(plan.PLAN_HEADER_KEY, header.to_data())
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
    state = github.get_plan(number=7, repo_root=ROOT)
    assert state is not None and state.pr is not None
    assert state.pr.number == 55 and state.pr.state == "OPEN"


def test_get_plan_not_found(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        _GhDispatch([(_has("issue", "view"), _Proc(1, stderr="GraphQL: Could not resolve (404)"))]),
    )
    assert github.get_plan(number=999, repo_root=ROOT) is None


# --------------------------------------------------------------- land ops (T5b)


def test_mark_pr_ready_succeeds(monkeypatch):
    rec = _GhDispatch([(_has("pr", "ready"), _Proc(0))])
    monkeypatch.setattr(subprocess, "run", rec)
    github.mark_pr_ready(number=42, repo_root=ROOT)  # no raise
    assert any("ready" in c for c in rec.calls)


def test_mark_pr_ready_dry_run_does_not_shell(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("dry run must not shell gh")

    monkeypatch.setattr(subprocess, "run", boom)
    github.mark_pr_ready(number=42, repo_root=ROOT, dry_run=True)


def test_merge_pr_squash_success(monkeypatch):
    rec = _GhDispatch([(_has("merge", "PUT"), _Proc(0, "{}"))])
    monkeypatch.setattr(subprocess, "run", rec)
    pr = github.merge_pr(number=42, repo_root=ROOT, commit_message="Closes #7")
    assert pr.state == "MERGED" and pr.number == 42
    # squash method + the closing commit message went through
    assert any("merge_method=squash" in tok for c in rec.calls for tok in c)
    assert any("commit_message=Closes #7" in tok for c in rec.calls for tok in c)


def test_merge_pr_already_merged_is_success(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        _GhDispatch([(_has("merge", "PUT"), _Proc(1, stderr="HTTP 405: already merged"))]),
    )
    pr = github.merge_pr(number=42, repo_root=ROOT)
    assert pr.state == "MERGED"  # idempotent


def test_merge_pr_other_failure_raises(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        _GhDispatch([(_has("merge", "PUT"), _Proc(1, stderr="HTTP 409: conflict"))]),
    )
    with pytest.raises(github.GitHubError):
        github.merge_pr(number=42, repo_root=ROOT)


def test_merge_pr_dry_run_does_not_shell(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("dry run must not shell gh")

    monkeypatch.setattr(subprocess, "run", boom)
    pr = github.merge_pr(number=42, repo_root=ROOT, dry_run=True)
    assert pr.state == "MERGED"


def test_get_plan_body_extracts_from_first_comment(monkeypatch):
    markdown = "# Add retry\n\n## Steps\n1. Add helper\n2. Wire it in\n"
    comment_body = plan.render_plan_body(markdown)
    payload = json.dumps(
        {"body": "<!-- perk:metadata-block:plan-header -->", "comments": [{"body": comment_body}]}
    )
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Proc(0, payload))
    assert github.get_plan_body(number=42, repo_root=ROOT) == markdown.strip()


def test_get_plan_body_none_when_no_block(monkeypatch):
    payload = json.dumps({"body": "just a header", "comments": []})
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Proc(0, payload))
    assert github.get_plan_body(number=42, repo_root=ROOT) is None


def test_get_plan_body_missing_issue_returns_none(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Proc(1, stderr="not found"))
    assert github.get_plan_body(number=999, repo_root=ROOT) is None


def test_get_plan_body_infra_failure_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Proc(1, stderr="HTTP 500"))
    with pytest.raises(github.GitHubError):
        github.get_plan_body(number=42, repo_root=ROOT)


# --- PR body craft (P2.T8a) -----------------------------------------------------------------


def test_update_pr_body_patches_via_file(monkeypatch):
    rec = _GhDispatch([(_has("pulls/42", "PATCH"), _Proc(0, "{}"))])
    monkeypatch.setattr(subprocess, "run", rec)
    upd = github.update_pr_body(number=42, body="NEW-BODY", repo_root=ROOT)
    assert upd.number == 42 and upd.dry_run is False
    assert rec.body_files == ["NEW-BODY"]  # body via file, never inline
    assert all("body=NEW-BODY" not in tok for c in rec.calls for tok in c)


def test_update_pr_body_dry_run_does_not_shell(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("dry run must not shell gh")

    monkeypatch.setattr(subprocess, "run", boom)
    assert github.update_pr_body(number=42, body="x", repo_root=ROOT, dry_run=True).dry_run


def test_update_pr_body_failure_raises(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("pulls/42", "PATCH"), _Proc(1, stderr="HTTP 422"))])
    )
    with pytest.raises(github.GitHubError):
        github.update_pr_body(number=42, body="x", repo_root=ROOT)


def test_get_pr_body_returns_body(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Proc(0, "PR BODY TEXT"))
    assert github.get_pr_body(number=42, repo_root=ROOT) == "PR BODY TEXT"


def test_get_pr_body_missing_returns_none(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Proc(1, stderr="HTTP 404"))
    assert github.get_pr_body(number=999, repo_root=ROOT) is None


def test_validate_pr_body_valid_footer_passes():
    body = "Closes #7\n\nPlan: #7\n\n`gh pr checkout 42`\n"
    assert github.validate_pr_body(body, pr_number=42) == ()


def test_validate_pr_body_issue_number_footer_fails():
    # The regression test: the latent issue-numbered-footer bug (footer carries #7, not the PR #42).
    body = "Closes #7\n\n`gh pr checkout 7`\n"
    errors = github.validate_pr_body(body, pr_number=42)
    assert errors and any("wrong number" in e for e in errors)


def test_validate_pr_body_word_boundary():
    # `42` must not match `checkout 123` (word-boundary, not substring).
    body = "`gh pr checkout 123`\n"
    errors = github.validate_pr_body(body, pr_number=12)
    assert errors and any("wrong number" in e for e in errors)


def test_validate_pr_body_html_wrapped_fails():
    body = "Closes #7\n\n<code>gh pr checkout 42</code>\n"
    errors = github.validate_pr_body(body, pr_number=42)
    assert errors and any("plain-backtick" in e for e in errors)


def test_validate_pr_body_missing_footer_fails():
    errors = github.validate_pr_body("Closes #7\n\nPlan: #7\n", pr_number=42)
    assert errors and any("missing" in e for e in errors)


def test_validate_pr_body_html_details_embed_is_fine():
    # The <details> plan embed is explicitly fine; only the footer is validated.
    body = (
        "Closes #7\n\n<details><summary>Plan #7</summary>\n\n# Plan\n\n</details>\n\n"
        "`gh pr checkout 42`\n"
    )
    assert github.validate_pr_body(body, pr_number=42) == ()


# --- review feedback (P2.T7) ----------------------------------------------------------------

_THREADS_PAYLOAD = json.dumps(
    {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [
                            {
                                "id": "PRRT_1",
                                "isResolved": False,
                                "isOutdated": False,
                                "path": "perk/github.py",
                                "line": 12,
                                "comments": {
                                    "nodes": [
                                        {
                                            "databaseId": 99,
                                            "body": "please rename this",
                                            "author": {"login": "rev"},
                                            "path": "perk/github.py",
                                            "line": 12,
                                            "createdAt": "2026-01-01T00:00:00Z",
                                        }
                                    ]
                                },
                            },
                            {
                                "id": "PRRT_2",
                                "isResolved": True,
                                "isOutdated": False,
                                "path": None,
                                "line": None,
                                "comments": {"nodes": []},
                            },
                        ]
                    }
                }
            }
        }
    }
)

_REVIEWS_PAYLOAD = json.dumps(
    {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviews": {
                        "nodes": [
                            {
                                "id": "PRR_1",
                                "author": {"login": "rev"},
                                "body": "looks good",
                                "state": "APPROVED",
                                "submittedAt": "2026-01-02T00:00:00Z",
                            }
                        ]
                    }
                }
            }
        }
    }
)

_COMMENTS_PAYLOAD = json.dumps(
    [{"id": 7, "body": "nice work", "user": {"login": "rev"}, "created_at": "2026-01-03T00:00:00Z"}]
)


def test_get_pr_feedback_parses_all_sources(monkeypatch):
    rec = _GhDispatch(
        [
            (_has("repo", "view", "nameWithOwner"), _Proc(0, "octo/repo\n")),
            (_has("graphql", "reviewThreads"), _Proc(0, _THREADS_PAYLOAD)),
            (_has("graphql", "reviews"), _Proc(0, _REVIEWS_PAYLOAD)),
            (_has("issues/42/comments"), _Proc(0, _COMMENTS_PAYLOAD)),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    fb = github.get_pr_feedback(pr_number=42, repo_root=ROOT)
    assert fb.pr_number == 42
    assert len(fb.review_threads) == 2
    assert fb.review_threads[0].thread_id == "PRRT_1"
    assert fb.review_threads[0].is_resolved is False
    assert fb.review_threads[0].comments[0].comment_id == 99
    assert fb.review_threads[1].is_resolved is True
    assert len(fb.discussion_comments) == 1 and fb.discussion_comments[0].comment_id == 7
    assert len(fb.reviews) == 1 and fb.reviews[0].state == "APPROVED"


def test_get_pr_feedback_infra_failure_raises(monkeypatch):
    rec = _GhDispatch(
        [
            (_has("repo", "view", "nameWithOwner"), _Proc(0, "octo/repo\n")),
            (_has("graphql", "reviewThreads"), _Proc(1, stderr="HTTP 500")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(github.GitHubError):
        github.get_pr_feedback(pr_number=42, repo_root=ROOT)


def test_resolve_review_threads_reply_then_resolve(monkeypatch):
    rec = _GhDispatch(
        [
            (_has("graphql", "addPullRequestReviewThreadReply"), _Proc(0, "{}")),
            (_has("graphql", "resolveReviewThread"), _Proc(0, "{}")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    result = github.resolve_review_threads(
        batch=[{"thread_id": "PRRT_1", "comment": "Fixed"}], repo_root=ROOT
    )
    assert result.success is True
    assert result.results[0].comment_added is True and result.results[0].success is True
    # reply mutation ran before the resolve mutation
    assert rec.method_calls("graphql") == 2


def test_resolve_review_threads_no_comment_skips_reply(monkeypatch):
    rec = _GhDispatch([(_has("graphql", "resolveReviewThread"), _Proc(0, "{}"))])
    monkeypatch.setattr(subprocess, "run", rec)
    result = github.resolve_review_threads(batch=[{"thread_id": "PRRT_1"}], repo_root=ROOT)
    assert result.success is True and result.results[0].comment_added is False


def test_resolve_review_threads_per_item_error_captured(monkeypatch):
    rec = _GhDispatch([(_has("graphql", "resolveReviewThread"), _Proc(1, stderr="bad thread"))])
    monkeypatch.setattr(subprocess, "run", rec)
    result = github.resolve_review_threads(
        batch=[{"thread_id": "BAD", "comment": None}], repo_root=ROOT
    )
    assert result.success is False
    assert result.results[0].success is False and "bad thread" in (result.results[0].error or "")


def test_resolve_review_threads_batch_success_is_all(monkeypatch):
    def fake_run(args, **_):
        gh = args[1:]
        if any("resolveReviewThread" in t for t in gh):
            # second thread id fails
            if any("PRRT_2" in t for t in gh):
                return _Proc(1, stderr="nope")
            return _Proc(0, "{}")
        return _Proc(1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = github.resolve_review_threads(
        batch=[{"thread_id": "PRRT_1"}, {"thread_id": "PRRT_2"}], repo_root=ROOT
    )
    assert result.success is False
    assert result.results[0].success is True and result.results[1].success is False


def test_resolve_review_threads_dry_run_does_not_shell(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("dry run must not shell gh")

    monkeypatch.setattr(subprocess, "run", boom)
    result = github.resolve_review_threads(
        batch=[{"thread_id": "PRRT_1", "comment": "x"}], repo_root=ROOT, dry_run=True
    )
    assert result.success is True and result.results[0].comment_added is True


# --------------------------------------------------------------- objective ops (P2.T9)


def _obj_header(run_id: str, comment_id=None) -> str:
    return plan.render_metadata_block(
        objective.OBJECTIVE_HEADER_KEY,
        objective.ObjectiveHeader(
            run_id=run_id, created="t", objective_comment_id=comment_id
        ).to_data(),
    )


def _obj_roadmap(nodes) -> str:
    return plan.render_metadata_block(
        objective.OBJECTIVE_ROADMAP_KEY, objective.render_roadmap_block(nodes)
    )


def _obj_body(run_id, nodes, comment_id=None) -> str:
    return f"{_obj_header(run_id, comment_id)}\n\n{_obj_roadmap(nodes)}\n"


def test_find_objective_issue_label_scoped(monkeypatch):
    issues = [{"number": 5, "html_url": "u/5", "body": _obj_header("01RID")}]
    rec = _GhRecorder(get=_Proc(0, stdout=json.dumps(issues)))
    monkeypatch.setattr(subprocess, "run", rec)
    found = github.find_objective_issue(run_id="01RID", repo_root=ROOT)
    assert found is not None and found.number == 5 and found.existed is True
    assert any("labels=perk:objective" in tok for c in rec.calls for tok in c)


def test_create_objective_issue_idempotent(monkeypatch):
    existing = [{"number": 5, "html_url": "u/5", "body": _obj_header("01RID")}]
    rec = _GhRecorder(get=_Proc(0, stdout=json.dumps(existing)))
    monkeypatch.setattr(subprocess, "run", rec)
    issue = github.create_objective_issue(
        title="Obj", body="# Obj\n\nprose", repo_root=ROOT, run_id="01RID"
    )
    assert issue.number == 5 and issue.existed is True
    assert not rec.posted()  # dedup short-circuits before any write


def test_create_objective_issue_rejects_empty_roadmap(monkeypatch):
    # Storage backstop: a node-less objective (no embedded roadmap, no roadmap_nodes) raises
    # GitHubError after the idempotency lookup (returns []) and before any issue POST.
    rec = _GhRecorder(get=_Proc(0, stdout="[]"))
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(github.GitHubError):
        github.create_objective_issue(
            title="Obj", body="# Obj\n\nprose", repo_root=ROOT, run_id="01EMPTY"
        )
    assert not rec.posted()  # no issue created


def test_create_objective_issue_two_step(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    roadmap = _obj_roadmap(nodes)
    body = f"# My objective\n\n{roadmap}\n"
    rec = _GhDispatch(
        [
            (_has("repos/{owner}/{repo}/labels", "POST"), _Proc(0)),  # lazy label create
            (_has("comments", "POST"), _Proc(0, json.dumps({"id": 555}))),  # body comment
            (
                _has("repos/{owner}/{repo}/issues", "POST"),
                _Proc(0, json.dumps({"number": 200, "url": "u/200"})),
            ),
            (
                _has("issues/200", ".body"),
                _Proc(0, _obj_body("01RID", nodes)),
            ),  # header backfill read
            (_has("issues/200", "PATCH"), _Proc(0, "{}")),
            (_has("issues", "GET"), _Proc(0, "[]")),  # idempotency find -> none
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    issue = github.create_objective_issue(
        title="My objective", body=body, repo_root=ROOT, run_id="01RID"
    )
    assert issue.number == 200 and issue.existed is False
    # the perk:objective label was lazily created
    assert any("name=perk:objective" in tok for c in rec.calls for tok in c)
    # the comment-id backfill PATCHed the header with objective_comment_id=555
    patched = rec.body_files[-1]
    header = plan.find_metadata_block(patched, objective.OBJECTIVE_HEADER_KEY)
    assert header is not None and header["objective_comment_id"] == 555


def test_create_objective_issue_dry_run_does_not_shell(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("dry run must not shell gh")

    monkeypatch.setattr(subprocess, "run", boom)
    issue = github.create_objective_issue(
        title="t", body="# t", repo_root=ROOT, run_id="01RID", dry_run=True
    )
    assert issue.number == 0 and issue.existed is False


def test_get_objective_parses_header_and_nodes(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.DONE),
        objective.ObjectiveNode(id="1.2", description="B", status=objective.NodeStatus.PENDING),
    ]
    issue = {
        "number": 5,
        "title": "Obj",
        "body": _obj_body("01RID", nodes, comment_id=9),
        "url": "u/5",
    }
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issue", "view"), _Proc(0, json.dumps(issue)))])
    )
    state = github.get_objective(number=5, repo_root=ROOT)
    assert state is not None and state.title == "Obj"
    assert [n.id for n in state.nodes] == ["1.1", "1.2"]
    assert state.header["objective_comment_id"] == 9


def test_get_objective_not_found(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issue", "view"), _Proc(1, stderr="not found"))])
    )
    assert github.get_objective(number=404, repo_root=ROOT) is None


def test_update_objective_node_updates_body_and_comment(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING),
        objective.ObjectiveNode(id="1.2", description="B", status=objective.NodeStatus.PENDING),
    ]
    issue_body = _obj_body("01RID", nodes, comment_id=555)
    comment_body = objective.render_body_comment(nodes, prose="prose here")
    rec = _GhDispatch(
        [
            (_has("issues/comments/555", ".body"), _Proc(0, comment_body)),
            (_has("issues/comments/555", "PATCH"), _Proc(0, "{}")),
            (_has("issues/123", "PATCH"), _Proc(0, "{}")),
            (_has("issues/123", ".body"), _Proc(0, issue_body)),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    result = github.update_objective_node(
        number=123, node_id="1.2", status=objective.NodeStatus.IN_PROGRESS, pr="#9", repo_root=ROOT
    )
    assert result.comment_updated is True and result.dry_run is False
    # the PATCHed roadmap shows 1.2 in_progress with pr #9 (explicit status, not inferred)
    body_patch = rec.body_files[0]
    parsed, _ = objective.parse_roadmap_nodes(body_patch)
    n = next(x for x in parsed if x.id == "1.2")
    assert n.status is objective.NodeStatus.IN_PROGRESS and n.pr == "#9"


def test_update_objective_node_not_found_raises(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    issue_body = _obj_body("01RID", nodes, comment_id=555)
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issues/123", ".body"), _Proc(0, issue_body))])
    )
    with pytest.raises(github.GitHubError, match="not found"):
        github.update_objective_node(
            number=123, node_id="9.9", status=objective.NodeStatus.DONE, repo_root=ROOT
        )


def test_update_objective_node_dry_run_does_not_patch(monkeypatch):
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.PENDING)
    ]
    issue_body = _obj_body("01RID", nodes, comment_id=555)
    rec = _GhDispatch([(_has("issues/123", ".body"), _Proc(0, issue_body))])
    monkeypatch.setattr(subprocess, "run", rec)
    result = github.update_objective_node(
        number=123, node_id="1.1", status=objective.NodeStatus.DONE, repo_root=ROOT, dry_run=True
    )
    assert result.dry_run is True and rec.method_calls("PATCH") == 0


def test_update_objective_body_splices_reconcilable_region(monkeypatch):
    nodes = [objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.DONE)]
    issue_body = _obj_body("01RID", nodes, comment_id=777)
    comment_body = objective.render_body_comment(nodes, prose="Old prose.")
    rec = _GhDispatch(
        [
            (_has("issues/comments/777", "PATCH"), _Proc(0, "{}")),
            (_has("issues/comments/777", ".body"), _Proc(0, comment_body)),
            (_has("issues/123", ".body"), _Proc(0, issue_body)),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    result = github.update_objective_body(number=123, prose="New prose.", repo_root=ROOT)
    assert result.updated is True and result.comment_id == 777 and result.dry_run is False
    patched = rec.body_files[-1]
    assert "New prose." in patched and "Old prose." not in patched
    # the Mechanical table block is preserved
    assert objective.ROADMAP_TABLE_MARKER_START in patched


def test_update_objective_body_dry_run_does_not_patch(monkeypatch):
    nodes = [objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.DONE)]
    issue_body = _obj_body("01RID", nodes, comment_id=777)
    comment_body = objective.render_body_comment(nodes, prose="Old prose.")
    rec = _GhDispatch(
        [
            (_has("issues/comments/777", ".body"), _Proc(0, comment_body)),
            (_has("issues/123", ".body"), _Proc(0, issue_body)),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    result = github.update_objective_body(
        number=123, prose="New prose.", repo_root=ROOT, dry_run=True
    )
    assert result.updated is False and result.dry_run is True
    assert rec.method_calls("PATCH") == 0


def test_update_objective_body_no_comment_raises(monkeypatch):
    nodes = [objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.DONE)]
    issue_body = _obj_body("01RID", nodes, comment_id=None)  # no objective_comment_id
    monkeypatch.setattr(
        subprocess, "run", _GhDispatch([(_has("issues/123", ".body"), _Proc(0, issue_body))])
    )
    with pytest.raises(github.GitHubError, match="no body comment"):
        github.update_objective_body(number=123, prose="x", repo_root=ROOT)


def test_update_objective_body_no_region_raises(monkeypatch):
    nodes = [objective.ObjectiveNode(id="1.1", description="A", status=objective.NodeStatus.DONE)]
    issue_body = _obj_body("01RID", nodes, comment_id=777)
    # a pre-T11 comment with no reconcilable markers
    legacy_comment = "<!-- perk:roadmap-table -->\ntable\n<!-- /perk:roadmap-table -->\n\nprose"
    monkeypatch.setattr(
        subprocess,
        "run",
        _GhDispatch(
            [
                (_has("issues/comments/777", ".body"), _Proc(0, legacy_comment)),
                (_has("issues/123", ".body"), _Proc(0, issue_body)),
            ]
        ),
    )
    with pytest.raises(github.GitHubError, match="no reconcilable region"):
        github.update_objective_body(number=123, prose="x", repo_root=ROOT)


def test_update_objective_header_rejects_unknown_field(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(0, _obj_header("01RID")))
    with pytest.raises(github.GitHubError, match="unknown objective-header field"):
        github.update_objective_header(number=5, fields={"bogus": "x"}, repo_root=ROOT)


# --- workflow dispatch (Node 2.1 — contracts.md §8.13) --------------------------------


def test_trigger_workflow_matches_on_a_later_attempt(monkeypatch):
    # The discovery poll uses an injected no-op sleep; the matching run only appears on attempt 3.
    attempts = {"n": 0}
    slept: list[float] = []

    def fake_run(args, **_):
        if args[1] == "workflow":
            return _Proc(0)
        if args[1] == "api":
            attempts["n"] += 1
            if attempts["n"] < 3:
                return _Proc(0, "[]")
            return _Proc(
                0,
                json.dumps(
                    [
                        {
                            "id": 7,
                            "html_url": "u",
                            "status": "queued",
                            "display_title": "plan (01TOK)",
                        }
                    ]
                ),
            )
        return _Proc(1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    wr = github.trigger_workflow(
        repo_root=ROOT,
        workflow="perk-run.yml",
        inputs={"run_id": "01TOK", "stage": "implement"},
        ref="main",
        match_token="01TOK",
        sleep=slept.append,
        max_attempts=5,
    )
    assert wr.id == "7" and wr.status == "queued"
    assert len(slept) == 2  # slept after attempts 1 and 2, matched on 3


def test_trigger_workflow_raises_when_dispatch_nonzero(monkeypatch):
    def fake_run(args, **_):
        if args[1] == "workflow":
            return _Proc(1, "", "could not find any workflows named perk-run.yml")
        return _Proc(1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(github.GitHubError):
        github.trigger_workflow(
            repo_root=ROOT,
            workflow="perk-run.yml",
            inputs={"run_id": "01TOK"},
            ref="main",
            match_token="01TOK",
            sleep=lambda _s: None,
            max_attempts=2,
        )


def test_trigger_workflow_raises_on_exhaustion(monkeypatch):
    def fake_run(args, **_):
        if args[1] == "workflow":
            return _Proc(0)
        if args[1] == "api":
            return _Proc(0, json.dumps([{"id": 1, "display_title": "unrelated"}]))
        return _Proc(1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(github.GitHubError):
        github.trigger_workflow(
            repo_root=ROOT,
            workflow="perk-run.yml",
            inputs={"run_id": "01TOK"},
            ref="main",
            match_token="01TOK",
            sleep=lambda _s: None,
            max_attempts=2,
        )
