import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import cache, github
from perk.cli.cli import cli

_REF = {
    "provider": "github",
    "pr_id": "7",
    "url": "https://gh/o/r/issues/7",
    "labels": ["perk:plan"],
    "objective_id": None,
}


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _open_pr():
    return github.PullRequest(number=42, url="u", is_draft=False, state="OPEN", existed=True)


def _write_batch(d: str, batch) -> str:
    path = Path(d) / "batch.json"
    path.write_text(json.dumps(batch), encoding="utf-8")
    return str(path)


class _Proc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# --- CLI command: validation + resolution + dry-run -----------------------------------------


def test_post_success_json(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: _open_pr())
    monkeypatch.setattr(
        github,
        "post_pr_review",
        lambda **k: github.ReviewPostResult(ok=True, mode="review", pr_number=42, comment_count=1),
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        batch = _write_batch(
            d, {"summary": "looks good", "comments": [{"path": "x.py", "line": 3, "body": "nit"}]}
        )
        result = runner.invoke(cli, ["pr", "review-post", "--json", "--batch", batch])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["pr"] == 42
    assert data["mode"] == "review" and data["comment_count"] == 1


def test_post_dry_run_offline():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        batch = _write_batch(d, {"summary": "ok"})
        result = runner.invoke(cli, ["pr", "review-post", "--dry-run", "--json", "--batch", batch])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["dry_run"] is True


def test_post_bad_batch_not_object(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        batch = _write_batch(d, ["not", "an", "object"])
        result = runner.invoke(cli, ["pr", "review-post", "--json", "--batch", batch])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "bad_batch"


def test_post_bad_batch_missing_summary(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        batch = _write_batch(d, {"comments": []})
        result = runner.invoke(cli, ["pr", "review-post", "--json", "--batch", batch])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "bad_batch"


def test_post_bad_batch_malformed_comment(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        bad = {"summary": "ok", "comments": [{"path": "x.py", "body": "no line"}]}
        batch = _write_batch(d, bad)
        result = runner.invoke(cli, ["pr", "review-post", "--json", "--batch", batch])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "bad_batch"


def test_post_no_plan_ref_exits_1(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        batch = _write_batch(d, {"summary": "ok"})
        result = runner.invoke(cli, ["pr", "review-post", "--json", "--batch", batch])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_plan_ref"


def test_post_no_pr_exits_1(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        batch = _write_batch(d, {"summary": "ok"})
        result = runner.invoke(cli, ["pr", "review-post", "--json", "--batch", batch])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_pr"


def test_post_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        batch = _write_batch(d, {"summary": "ok"})
        result = runner.invoke(cli, ["pr", "review-post", "--json", "--batch", batch])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"


# --- gateway: the one-review submission + the COMMENT-event + the comment fallback -----------


def test_gateway_review_path_sends_event_comment(monkeypatch):
    seen: dict[str, str] = {}

    def fake_run(args, **_):
        # the review endpoint POST: assert the COMMENT event rode in the JSON input file.
        if "reviews" in " ".join(args):
            idx = args.index("--input")
            payload = json.loads(Path(args[idx + 1]).read_text(encoding="utf-8"))
            seen["event"] = payload["event"]
            return _Proc(0, "{}")
        return _Proc(0, "{}")

    monkeypatch.setattr(github, "_run", fake_run)
    result = github.post_pr_review(
        pr_number=42,
        summary="ok",
        comments=[github.InlineReviewComment(path="x.py", line=3, body="nit")],
        repo_root=Path(),
    )
    assert result.ok is True and result.mode == "review"
    assert seen["event"] == "COMMENT"


def test_gateway_falls_back_to_comment_on_review_failure(monkeypatch):
    calls: list[str] = []

    def fake_run(args, **_):
        joined = " ".join(args)
        if "reviews" in joined:
            calls.append("review")
            return _Proc(1, "", "422 Unprocessable: line not part of the diff")
        if "comments" in joined:
            calls.append("comment")
            return _Proc(0, "{}")
        return _Proc(0, "{}")

    monkeypatch.setattr(github, "_run", fake_run)
    result = github.post_pr_review(
        pr_number=42,
        summary="ok",
        comments=[github.InlineReviewComment(path="x.py", line=999, body="bad anchor")],
        repo_root=Path(),
    )
    assert result.ok is True and result.mode == "comment_fallback"
    assert calls == ["review", "comment"]


def test_gateway_raises_when_even_fallback_fails(monkeypatch):
    def fake_run(args, **_):
        return _Proc(1, "", "boom")

    monkeypatch.setattr(github, "_run", fake_run)
    try:
        github.post_pr_review(pr_number=42, summary="ok", comments=[], repo_root=Path())
    except github.GitHubError:
        return
    raise AssertionError("expected GitHubError when both review and fallback fail")


def test_gateway_dry_run_does_not_shell(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("dry-run must not shell gh")

    monkeypatch.setattr(github, "_run", boom)
    result = github.post_pr_review(
        pr_number=42, summary="ok", comments=[], repo_root=Path(), dry_run=True
    )
    assert result.ok is True and result.mode == "review"
