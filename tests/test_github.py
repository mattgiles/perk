"""Tests for the pure GitHub forge gateway (``perk/github/``): auth + workflows + the
PR-tier ``prs`` ops. The plan/issue substrate tests live in ``tests/test_github_plans.py``;
the objective substrate in ``tests/test_github_objectives.py``.
"""

import json
import subprocess
from pathlib import Path

import click
import pytest
from _github_fakes import ROOT, _GhDispatch, _has, _Proc

from perk import github
from perk.cli.context import PerkContext, require_github
from perk.cli.ensure import UserFacingCliError


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


# --------------------------------------------------------- runner-prerequisite reads


def test_secret_exists_present(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda args, **_: _Proc(0, "{}"))
    assert github.secret_exists(name="PERK_GH_PAT", repo_root=ROOT) is True


def test_secret_exists_absent_404(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda args, **_: _Proc(1, "", "gh: Not Found (HTTP 404)")
    )
    assert github.secret_exists(name="PERK_GH_PAT", repo_root=ROOT) is False


def test_secret_exists_not_found_without_404(monkeypatch):
    """A "Not Found" stderr with no literal 404 is a lookup miss (the sanctioned
    ``_is_not_found`` lowercase fold)."""
    monkeypatch.setattr(subprocess, "run", lambda args, **_: _Proc(1, "", "gh: Not Found"))
    assert github.secret_exists(name="PERK_GH_PAT", repo_root=ROOT) is False


def test_get_pr_not_found_without_404(monkeypatch):
    """Same fold via ``_run_json(none_on_not_found=True)``: ``get_pr`` -> ``None``."""
    monkeypatch.setattr(subprocess, "run", lambda args, **_: _Proc(1, "", "gh: Not Found"))
    assert github.get_pr(number=99, repo_root=ROOT) is None


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


def test_find_pr_for_branch_carries_base_ref(monkeypatch):
    # The PR's actual base.ref is surfaced on the dataclass (the land-time autoclose
    # determinant); a payload without `base` defaults to "".
    pulls = [
        {
            "number": 2,
            "html_url": "u/2",
            "state": "open",
            "draft": False,
            "base": {"ref": "release"},
        },
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
    assert pr is not None and pr.base_ref == "release"
    # A construction from a base-less payload defaults base_ref to "".
    assert (
        github.PullRequest(number=1, url="u", is_draft=False, state="OPEN", existed=True).base_ref
        == ""
    )


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


# --- workflow dispatch (contracts.md §8.13) --------------------------------


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
