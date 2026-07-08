import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github
from perk.cli.cli import cli

# A fixture diff whose anchors are known: RIGHT 2/3 (added), LEFT 2 (deleted), 1/RIGHT+LEFT
# and the trailing context line (old 3 / new 4) on both sides.
_FIXTURE_DIFF = (
    "diff --git a/x.py b/x.py\n"
    "index 1111111..2222222 100644\n"
    "--- a/x.py\n"
    "+++ b/x.py\n"
    "@@ -1,3 +1,4 @@\n"
    " one\n"
    "-two\n"
    "+two!\n"
    "+two-and-a-half\n"
    " three\n"
)


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _fixture_diff(monkeypatch) -> None:
    monkeypatch.setattr(github, "get_pr_diff", lambda **k: _FIXTURE_DIFF)


def _write_batch(d: str, batch) -> str:
    path = Path(d) / "batch.json"
    path.write_text(json.dumps(batch), encoding="utf-8")
    return str(path)


def _post_spy(monkeypatch, *, mode: str = "review"):
    """A gateway spy returning a canned result; records the kwargs of the one expected call."""
    seen: dict[str, object] = {}

    def fake_post(**kwargs):
        seen.update(kwargs)
        return github.ReviewPostResult(
            ok=True, mode=mode, pr_number=kwargs["pr_number"], comment_count=len(kwargs["comments"])
        )

    monkeypatch.setattr(github, "post_pr_review", fake_post)
    return seen


def _boom_post(monkeypatch) -> None:
    def boom(**_k):
        raise AssertionError("the mutation must be structurally unreachable")

    monkeypatch.setattr(github, "post_pr_review", boom)


# --- success arms ---------------------------------------------------------------------------


def test_submit_success_json_approve(monkeypatch):
    _authed(monkeypatch)
    _fixture_diff(monkeypatch)
    seen = _post_spy(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        batch = _write_batch(
            d,
            {
                "body": "ship it",
                "comments": [
                    {"path": "x.py", "line": 2, "body": "nice"},
                    {"path": "x.py", "line": 2, "side": "LEFT", "body": "goodbye"},
                ],
            },
        )
        result = runner.invoke(
            cli,
            ["pr", "review-submit", "--pr", "42", "--event", "approve", "--json", "--batch", batch],
        )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["pr"] == 42
    assert data["event"] == "approve" and data["mode"] == "review"
    assert data["comment_count"] == 2 and data["dry_run"] is False
    # the gateway spy saw the wire event + the side passthrough
    assert seen["event"] == "APPROVE"
    comments = seen["comments"]
    assert [c.side for c in comments] == ["RIGHT", "LEFT"]
    assert seen["summary"] == "ship it"


def test_submit_omitted_event_defaults_to_comment(monkeypatch):
    _authed(monkeypatch)
    _fixture_diff(monkeypatch)
    seen = _post_spy(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        batch = _write_batch(d, {"body": "some thoughts"})
        result = runner.invoke(
            cli, ["pr", "review-submit", "--pr", "42", "--json", "--batch", batch]
        )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["event"] == "comment"  # the flag spelling in the envelope
    assert seen["event"] == "COMMENT"  # the wire spelling at the gateway


def test_submit_dry_run_validates_but_never_posts(monkeypatch):
    _authed(monkeypatch)
    _fixture_diff(monkeypatch)
    _boom_post(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        batch = _write_batch(
            d, {"body": "ok", "comments": [{"path": "x.py", "line": 3, "body": "nit"}]}
        )
        result = runner.invoke(
            cli, ["pr", "review-submit", "--pr", "42", "--dry-run", "--json", "--batch", batch]
        )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["dry_run"] is True and data["mode"] == "validated"
    assert data["comment_count"] == 1


def test_submit_body_less_approve_with_valid_comments_succeeds(monkeypatch):
    _authed(monkeypatch)
    _fixture_diff(monkeypatch)
    _post_spy(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        batch = _write_batch(d, {"comments": [{"path": "x.py", "line": 2, "body": "nice"}]})
        result = runner.invoke(
            cli,
            ["pr", "review-submit", "--pr", "42", "--event", "approve", "--json", "--batch", batch],
        )
    assert result.exit_code == 0
    assert json.loads(result.output)["success"] is True


def test_submit_degraded_modes_serialize(monkeypatch):
    _authed(monkeypatch)
    _fixture_diff(monkeypatch)
    for mode in ("review_folded", "comment_fallback"):
        _post_spy(monkeypatch, mode=mode)
        runner = CliRunner()
        with runner.isolated_filesystem() as d:
            _git_init(d)
            batch = _write_batch(
                d, {"body": "b", "comments": [{"path": "x.py", "line": 2, "body": "n"}]}
            )
            result = runner.invoke(
                cli, ["pr", "review-submit", "--pr", "42", "--json", "--batch", batch]
            )
        assert result.exit_code == 0
        assert json.loads(result.output)["mode"] == mode


def test_submit_degraded_modes_render_human(monkeypatch):
    _authed(monkeypatch)
    _fixture_diff(monkeypatch)
    _post_spy(monkeypatch, mode="review_folded")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        batch = _write_batch(
            d, {"body": "b", "comments": [{"path": "x.py", "line": 2, "body": "n"}]}
        )
        result = runner.invoke(cli, ["pr", "review-submit", "--pr", "42", "--batch", batch])
    assert result.exit_code == 0
    assert "comments folded into the review body" in result.output


# --- bad_batch arms -------------------------------------------------------------------------


def _assert_bad_batch(monkeypatch, batch_data, *, argv_extra: list[str] | None = None):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        batch = _write_batch(d, batch_data)
        result = runner.invoke(
            cli,
            ["pr", "review-submit", "--pr", "42", "--json", "--batch", batch] + (argv_extra or []),
        )
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["error_type"] == "bad_batch"
    return data


def test_submit_bad_batch_unknown_key(monkeypatch):
    data = _assert_bad_batch(monkeypatch, {"body": "b", "bogus": 1})
    assert "bogus" in data["message"]


def test_submit_bad_batch_stray_fyi_rejected(monkeypatch):
    # in-session triage color is structurally unpostable through this door
    data = _assert_bad_batch(monkeypatch, {"body": "b", "fyi": ["note"]})
    assert "fyi" in data["message"]


def test_submit_bad_batch_null_line(monkeypatch):
    # line: null findings are folded into the review body UPSTREAM — never submitted inline
    data = _assert_bad_batch(
        monkeypatch, {"body": "b", "comments": [{"path": "x.py", "line": None, "body": "n"}]}
    )
    assert "line" in data["message"]


def test_submit_bad_batch_string_line(monkeypatch):
    data = _assert_bad_batch(
        monkeypatch, {"body": "b", "comments": [{"path": "x.py", "line": "3", "body": "n"}]}
    )
    assert "line" in data["message"]


def test_submit_bad_batch_bad_side(monkeypatch):
    data = _assert_bad_batch(
        monkeypatch,
        {"body": "b", "comments": [{"path": "x.py", "line": 3, "side": "BOTH", "body": "n"}]},
    )
    assert "side" in data["message"]


def test_submit_bad_batch_missing_body_for_request_changes(monkeypatch):
    _assert_bad_batch(
        monkeypatch,
        {"comments": [{"path": "x.py", "line": 2, "body": "n"}]},
        argv_extra=["--event", "request-changes"],
    )


def test_submit_bad_batch_missing_body_for_comment(monkeypatch):
    _assert_bad_batch(monkeypatch, {"comments": [{"path": "x.py", "line": 2, "body": "n"}]})


def test_submit_bad_batch_empty_batch_for_comment(monkeypatch):
    _assert_bad_batch(monkeypatch, {})


# --- bad_anchors ----------------------------------------------------------------------------


def test_submit_bad_anchors_reports_invalid_and_never_posts(monkeypatch):
    _authed(monkeypatch)
    _fixture_diff(monkeypatch)
    _boom_post(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        batch = _write_batch(
            d,
            {
                "body": "b",
                "comments": [
                    {"path": "x.py", "line": 2, "body": "good anchor"},
                    {"path": "nope.py", "line": 1, "body": "bad path"},
                ],
            },
        )
        result = runner.invoke(
            cli, ["pr", "review-submit", "--pr", "42", "--json", "--batch", batch]
        )
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["error_type"] == "bad_anchors"
    assert data["pr"] == 42 and data["event"] == "comment" and data["dry_run"] is False
    assert data["invalid"] == [
        {
            "index": 1,
            "path": "nope.py",
            "line": 1,
            "side": "RIGHT",
            "reason": "path not in the PR diff",
        }
    ]
    assert "1 of 2" in data["message"]


def test_submit_bad_anchors_same_shape_under_dry_run(monkeypatch):
    _authed(monkeypatch)
    _fixture_diff(monkeypatch)
    _boom_post(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        batch = _write_batch(
            d, {"body": "b", "comments": [{"path": "x.py", "line": 999, "body": "n"}]}
        )
        result = runner.invoke(
            cli, ["pr", "review-submit", "--pr", "42", "--dry-run", "--json", "--batch", batch]
        )
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["error_type"] == "bad_anchors" and data["dry_run"] is True
    assert data["invalid"][0]["reason"] == "line 999 (RIGHT) is not part of the diff for x.py"


# --- error arms -----------------------------------------------------------------------------


def test_submit_pr_not_found(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(github, "get_pr_diff", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        batch = _write_batch(d, {"body": "b"})
        result = runner.invoke(
            cli, ["pr", "review-submit", "--pr", "42", "--json", "--batch", batch]
        )
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "pr_not_found"


def test_submit_own_pr_rejection(monkeypatch):
    _authed(monkeypatch)
    _fixture_diff(monkeypatch)

    def raise_own_pr(**_k):
        raise github.OwnPrReviewError("Can not approve your own pull request")

    monkeypatch.setattr(github, "post_pr_review", raise_own_pr)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        batch = _write_batch(d, {"body": "b"})
        result = runner.invoke(
            cli,
            ["pr", "review-submit", "--pr", "42", "--event", "approve", "--json", "--batch", batch],
        )
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["error_type"] == "own_pr"
    assert "your own PR" in data["message"]


def test_submit_github_error(monkeypatch):
    _authed(monkeypatch)
    _fixture_diff(monkeypatch)

    def raise_github(**_k):
        raise github.GitHubError("boom")

    monkeypatch.setattr(github, "post_pr_review", raise_github)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        batch = _write_batch(d, {"body": "b"})
        result = runner.invoke(
            cli, ["pr", "review-submit", "--pr", "42", "--json", "--batch", batch]
        )
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "github_error"


def test_submit_unauthed_even_dry_run(monkeypatch):
    # the always-online divergence from review-post: anchor validation shells gh
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(False, None, (), "not logged in")
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        batch = _write_batch(d, {"body": "b"})
        result = runner.invoke(
            cli, ["pr", "review-submit", "--pr", "42", "--dry-run", "--json", "--batch", batch]
        )
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "github_unauthed"


def test_submit_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        batch = _write_batch(d, {"body": "b"})
        result = runner.invoke(
            cli, ["pr", "review-submit", "--pr", "42", "--json", "--batch", batch]
        )
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"
