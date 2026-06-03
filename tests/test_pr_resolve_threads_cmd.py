import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github
from perk.cli.cli import cli


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _write_batch(d: str, batch) -> str:
    path = Path(d) / "batch.json"
    path.write_text(json.dumps(batch), encoding="utf-8")
    return str(path)


def test_resolve_success_json(monkeypatch):
    _authed(monkeypatch)

    def _resolve(**k):
        return github.BatchResolveResult(
            success=True,
            results=(
                github.ThreadResolveResult(
                    thread_id="PRRT_1", success=True, comment_added=True, error=None
                ),
            ),
        )

    monkeypatch.setattr(github, "resolve_review_threads", _resolve)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        batch = _write_batch(d, [{"thread_id": "PRRT_1", "comment": "Fixed"}])
        result = runner.invoke(cli, ["pr-resolve-threads", "--json", "--batch", batch])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["results"][0]["thread_id"] == "PRRT_1"


def test_resolve_partial_failure_still_exit_0(monkeypatch):
    _authed(monkeypatch)

    def _resolve(**k):
        return github.BatchResolveResult(
            success=False,
            results=(
                github.ThreadResolveResult(
                    thread_id="PRRT_1", success=False, comment_added=False, error="nope"
                ),
            ),
        )

    monkeypatch.setattr(github, "resolve_review_threads", _resolve)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        batch = _write_batch(d, [{"thread_id": "PRRT_1"}])
        result = runner.invoke(cli, ["pr-resolve-threads", "--json", "--batch", batch])
    # the batch ran; per-item failure rides inside the result (exit 0)
    assert result.exit_code == 0
    assert json.loads(result.output)["success"] is False


def test_resolve_dry_run_offline(monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        batch = _write_batch(d, [{"thread_id": "PRRT_1", "comment": "x"}])
        result = runner.invoke(cli, ["pr-resolve-threads", "--dry-run", "--json", "--batch", batch])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["dry_run"] is True


def test_resolve_bad_batch_exits_1(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        batch = _write_batch(d, {"not": "a list"})
        result = runner.invoke(cli, ["pr-resolve-threads", "--json", "--batch", batch])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "bad_batch"


def test_resolve_missing_thread_id_exits_1(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        batch = _write_batch(d, [{"comment": "no id"}])
        result = runner.invoke(cli, ["pr-resolve-threads", "--json", "--batch", batch])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "bad_batch"


def test_resolve_missing_batch_file_exits_2_or_usage():
    # a nonexistent --batch path is rejected by click (exists=True) before repo resolution
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["pr-resolve-threads", "--json", "--batch", "nope.json"])
    assert result.exit_code != 0


def test_resolve_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        batch = _write_batch(d, [{"thread_id": "PRRT_1"}])
        result = runner.invoke(cli, ["pr-resolve-threads", "--json", "--batch", batch])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"
