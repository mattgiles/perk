"""Tests for ``perk learn pending`` — the closed-plans-awaiting-/learn backlog view.

Driven through the ``cli`` object with a fake backend monkeypatched onto
``resolve.resolve_issue_backend`` (the ``test_gist_cmd.py`` pattern). Pins the human render
(rows + the resume hint, the scan-window empty state), the ``--json`` envelope, the ``--limit``
forwarding + Click range rejection, and the error arms (backend failure → ``github_error`` exit 1;
not-a-repo → exit 2).
"""

import json
import subprocess

from click.testing import CliRunner

from perk import github
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError, PendingLearnPlan
from perk.cli.cli import cli


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


class _StubBackend:
    """Records the list call's kwargs; canned rows."""

    backend_id = "stub"

    def __init__(self, *, plans: tuple[PendingLearnPlan, ...] = ()) -> None:
        self.list_kwargs: dict | None = None
        self._plans = plans

    def list_plans_pending_learn(self, **kwargs) -> tuple[PendingLearnPlan, ...]:
        self.list_kwargs = kwargs
        return self._plans


def _invoke(args, *, monkeypatch, backend, git_init: bool = True):
    monkeypatch.setattr(resolve, "resolve_issue_backend", lambda _root: backend)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        if git_init:
            _git_init(d)
        return runner.invoke(cli, args)


def _rows() -> tuple[PendingLearnPlan, ...]:
    return (
        PendingLearnPlan(
            id="42", title="Add the thing", url="u/42", closed_at="2026-01-02T03:04:05Z"
        ),
        PendingLearnPlan(id="41", title="Fix the other", url="u/41", closed_at=None),
    )


def test_human_output_rows_and_resume_hint(monkeypatch):
    _authed(monkeypatch)
    result = _invoke(
        ["learn", "pending"], monkeypatch=monkeypatch, backend=_StubBackend(plans=_rows())
    )
    assert result.exit_code == 0, result.output
    assert "#42  2026-01-02T03:04:05Z  Add the thing  u/42" in result.output
    assert "#41  ?  Fix the other  u/41" in result.output  # None closed_at renders as ?
    assert "run: perk plan resume <id>  (launches the learn stage)" in result.output


def test_human_empty_state_names_the_scan_window(monkeypatch):
    _authed(monkeypatch)
    result = _invoke(
        ["learn", "pending", "--limit", "7"], monkeypatch=monkeypatch, backend=_StubBackend()
    )
    assert result.exit_code == 0, result.output
    assert "No plans pending learn (scanned the 7 most recently updated closed plans)." in (
        result.output
    )


def test_json_envelope_and_empty_exits_zero(monkeypatch):
    _authed(monkeypatch)
    result = _invoke(
        ["learn", "pending", "--json"],
        monkeypatch=monkeypatch,
        backend=_StubBackend(plans=_rows()),
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "success": True,
        "error_type": None,
        "plans": [
            {
                "id": "42",
                "title": "Add the thing",
                "url": "u/42",
                "closed_at": "2026-01-02T03:04:05Z",
            },
            {"id": "41", "title": "Fix the other", "url": "u/41", "closed_at": None},
        ],
    }

    empty = _invoke(["learn", "pending", "--json"], monkeypatch=monkeypatch, backend=_StubBackend())
    assert empty.exit_code == 0
    assert json.loads(empty.output) == {"success": True, "error_type": None, "plans": []}


def test_limit_is_forwarded_to_the_backend(monkeypatch):
    _authed(monkeypatch)
    backend = _StubBackend()
    result = _invoke(["learn", "pending", "--limit", "9"], monkeypatch=monkeypatch, backend=backend)
    assert result.exit_code == 0, result.output
    assert backend.list_kwargs == {"limit": 9}


def test_out_of_range_limit_rejected_by_click(monkeypatch):
    _authed(monkeypatch)
    for bad in ("0", "101"):
        result = _invoke(
            ["learn", "pending", "--limit", bad], monkeypatch=monkeypatch, backend=_StubBackend()
        )
        assert result.exit_code == 2
        assert "--limit" in result.output


def test_backend_error_maps_to_github_error(monkeypatch):
    _authed(monkeypatch)

    class _Failing(_StubBackend):
        def list_plans_pending_learn(self, **kwargs):
            raise IssueBackendError("boom")

    result = _invoke(["learn", "pending", "--json"], monkeypatch=monkeypatch, backend=_Failing())
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False and payload["error_type"] == "github_error"
    assert "boom" in payload["message"]


def test_not_a_repo_exits_two(monkeypatch):
    result = _invoke(
        ["learn", "pending", "--json"],
        monkeypatch=monkeypatch,
        backend=_StubBackend(),
        git_init=False,
    )
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"
