"""Tests for the ``perk gist`` command group (contracts.md §8.41).

The worker pair (``create``/``list``) is exercised through CliRunner with stubbed backends
(the resolver seam); the launcher pair (``author``/``save``) through ``--dry-run`` + a stubbed
``launch_stage`` (the ``test_from_cmd.py`` sink pattern).
"""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github
from perk.backends import resolve
from perk.backends.issue_backend import GistSummary, IssueBackendError, IssueRef
from perk.backends.objective_store import ObjectiveRef
from perk.cli.cli import cli
from perk.run import launch
from perk.state import cache


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


class _StubIssueBackend:
    """Records create/list calls; canned returns."""

    backend_id = "stub"

    def __init__(self, *, gists: tuple[GistSummary, ...] = ()) -> None:
        self.create_kwargs: dict | None = None
        self._gists = gists

    def create_gist_issue(self, **kwargs) -> IssueRef:
        self.create_kwargs = kwargs
        if kwargs.get("dry_run"):
            return IssueRef(id="0", url="(dry-run)", existed=False)
        return IssueRef(id="7", url="u/7", existed=False)

    def list_gist_issues(self) -> tuple[GistSummary, ...]:
        return self._gists


class _StubStore:
    """Records create_gist_source calls; canned project-tier returns."""

    backend_id = "stub"

    def __init__(self, *, source_returns_none: bool = False, gists: tuple = ()) -> None:
        self.create_kwargs: dict | None = None
        self._source_returns_none = source_returns_none
        self._gists = gists

    def create_gist_source(self, **kwargs) -> ObjectiveRef | None:
        self.create_kwargs = kwargs
        if self._source_returns_none or kwargs.get("dry_run"):
            return None
        return ObjectiveRef(id="proj-1", url="p/url", existed=False)

    def list_gist_sources(self) -> tuple[GistSummary, ...]:
        return self._gists


def _invoke(args, *, monkeypatch, backend, store, body=None, write_handoff=None):
    monkeypatch.setattr(resolve, "resolve_issue_backend", lambda _root: backend)
    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: store)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        full = list(args)
        if body is not None:
            bf = Path(d) / "gist.md"
            bf.write_text(body, encoding="utf-8")
            full = [*full, "--body", str(bf)]
        if write_handoff is not None:
            run_id, blob = write_handoff
            cache.write_handoff(Path(d), run_id, blob)
        return runner.invoke(cli, full)


# ------------------------------------------------------------------ gist create


def test_create_json_defaults_to_plan_scope(monkeypatch):
    _authed(monkeypatch)
    backend, store = _StubIssueBackend(), _StubStore()
    result = _invoke(
        ["gist", "create", "--json"],
        monkeypatch=monkeypatch,
        backend=backend,
        store=store,
        body="# Do the thing\n\nintent prose",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "success": True,
        "error_type": None,
        "gist": {"id": "7", "url": "u/7", "existed": False},
        "scope": "plan",
        "dry_run": False,
    }
    assert backend.create_kwargs is not None
    assert backend.create_kwargs["title"] == "Do the thing"  # derived from the body heading
    assert backend.create_kwargs["scope"] == "plan"
    assert store.create_kwargs is None  # plan scope never touches the project tier


def test_create_human_prints_consumption_hint(monkeypatch):
    _authed(monkeypatch)
    result = _invoke(
        ["gist", "create"],
        monkeypatch=monkeypatch,
        backend=_StubIssueBackend(),
        store=_StubStore(),
        body="# G\n\nprose",
    )
    assert result.exit_code == 0, result.output
    assert "Created gist 7" in result.output
    assert "Consume with: perk plan from 7" in result.output


def test_create_objective_scope_routes_to_the_project_tier(monkeypatch):
    _authed(monkeypatch)
    backend, store = _StubIssueBackend(), _StubStore()
    result = _invoke(
        ["gist", "create", "--scope", "objective"],
        monkeypatch=monkeypatch,
        backend=backend,
        store=store,
        body="# G\n\nprose",
    )
    assert result.exit_code == 0, result.output
    assert store.create_kwargs is not None and store.create_kwargs["title"] == "G"
    assert backend.create_kwargs is None  # the project tier satisfied the save
    assert "Consume with: perk objective author --from proj-1" in result.output


def test_create_objective_scope_none_falls_back_to_the_issue_tier(monkeypatch):
    # A store with no project surface returns None — the save falls through to the issue tier
    # with scope=objective stamped in the gist-header.
    _authed(monkeypatch)
    backend, store = _StubIssueBackend(), _StubStore(source_returns_none=True)
    result = _invoke(
        ["gist", "create", "--json", "--scope", "objective"],
        monkeypatch=monkeypatch,
        backend=backend,
        store=store,
        body="# G\n\nprose",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["scope"] == "objective" and payload["gist"]["id"] == "7"
    assert store.create_kwargs is not None
    assert backend.create_kwargs is not None and backend.create_kwargs["scope"] == "objective"


def test_create_scope_recovered_from_handoff(monkeypatch):
    # `perk gist author --scope objective` stashes gist_scope in the handoff; the save recovers
    # it when --scope is not given.
    _authed(monkeypatch)
    backend, store = _StubIssueBackend(), _StubStore()
    result = _invoke(
        ["gist", "create", "--json", "--run-id", "RID9"],
        monkeypatch=monkeypatch,
        backend=backend,
        store=store,
        body="# G\n\nprose",
        write_handoff=("RID9", {"stage": "gist-author", "gist_scope": "objective"}),
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["scope"] == "objective"
    assert store.create_kwargs is not None  # objective scope routed to the project tier


def test_create_explicit_scope_wins_over_handoff(monkeypatch):
    _authed(monkeypatch)
    backend, store = _StubIssueBackend(), _StubStore()
    result = _invoke(
        ["gist", "create", "--json", "--run-id", "RID9", "--scope", "plan"],
        monkeypatch=monkeypatch,
        backend=backend,
        store=store,
        body="# G\n\nprose",
        write_handoff=("RID9", {"stage": "gist-author", "gist_scope": "objective"}),
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["scope"] == "plan"
    assert store.create_kwargs is None


def test_create_dry_run_is_offline(monkeypatch):
    # No auth stub: --dry-run skips require_github; the objective-scope project arm returns None
    # on dry_run and falls through to the issue tier's offline dry-run ref.
    backend, store = _StubIssueBackend(), _StubStore()
    result = _invoke(
        ["gist", "create", "--json", "--dry-run", "--scope", "objective"],
        monkeypatch=monkeypatch,
        backend=backend,
        store=store,
        body="# G\n\nprose",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True and payload["gist"]["id"] == "0"
    assert backend.create_kwargs is not None and backend.create_kwargs["dry_run"] is True


def test_create_empty_body_rejected(monkeypatch):
    _authed(monkeypatch)
    backend, store = _StubIssueBackend(), _StubStore()
    result = _invoke(
        ["gist", "create", "--json"],
        monkeypatch=monkeypatch,
        backend=backend,
        store=store,
        body="   \n",
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False and payload["error_type"] == "empty_body"
    assert backend.create_kwargs is None


def test_create_backend_error_maps_to_github_error(monkeypatch):
    _authed(monkeypatch)

    class _Failing(_StubIssueBackend):
        def create_gist_issue(self, **kwargs):
            raise IssueBackendError("boom")

    result = _invoke(
        ["gist", "create", "--json"],
        monkeypatch=monkeypatch,
        backend=_Failing(),
        store=_StubStore(),
        body="# G\n\nprose",
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "github_error"


# ------------------------------------------------------------------ gist list


def _summaries() -> tuple[GistSummary, ...]:
    return (
        GistSummary(id="1", title="Fresh", url="u/1", body="b", scope="plan", adopted=False),
        GistSummary(id="2", title="Taken", url="u/2", body="b", scope="plan", adopted=True),
    )


def test_list_default_hides_adopted(monkeypatch):
    _authed(monkeypatch)
    result = _invoke(
        ["gist", "list", "--json"],
        monkeypatch=monkeypatch,
        backend=_StubIssueBackend(gists=_summaries()),
        store=_StubStore(),
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["success"] is True and payload["error_type"] is None
    assert payload["gists"] == [
        {
            "id": "1",
            "url": "u/1",
            "title": "Fresh",
            "scope": "plan",
            "adopted": False,
            "kind": "issue",
        },
    ]


def test_list_all_includes_adopted_and_projects(monkeypatch):
    _authed(monkeypatch)
    project_gist = GistSummary(
        id="proj-9", title="Big idea", url="p/9", body="b", scope="objective", adopted=False
    )
    result = _invoke(
        ["gist", "list", "--all", "--json"],
        monkeypatch=monkeypatch,
        backend=_StubIssueBackend(gists=_summaries()),
        store=_StubStore(gists=(project_gist,)),
    )
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)["gists"]
    assert [(r["id"], r["kind"], r["adopted"]) for r in rows] == [
        ("1", "issue", False),
        ("2", "issue", True),
        ("proj-9", "project", False),
    ]


def test_list_human_marks_adopted_and_empty_exits_zero(monkeypatch):
    _authed(monkeypatch)
    result = _invoke(
        ["gist", "list", "--all"],
        monkeypatch=monkeypatch,
        backend=_StubIssueBackend(gists=_summaries()),
        store=_StubStore(),
    )
    assert result.exit_code == 0, result.output
    assert "[adopted]" in result.output

    empty = _invoke(
        ["gist", "list"],
        monkeypatch=monkeypatch,
        backend=_StubIssueBackend(),
        store=_StubStore(),
    )
    assert empty.exit_code == 0
    assert "No unconsumed gists." in empty.output


def test_list_backend_error_maps_to_github_error(monkeypatch):
    _authed(monkeypatch)

    class _Failing(_StubIssueBackend):
        def list_gist_issues(self):
            raise IssueBackendError("down")

    result = _invoke(
        ["gist", "list", "--json"],
        monkeypatch=monkeypatch,
        backend=_Failing(),
        store=_StubStore(),
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "github_error"


# ------------------------------------------------------------------ launchers


def _stub_launch(monkeypatch, sink: dict) -> None:
    monkeypatch.setattr(
        launch,
        "launch_stage",
        lambda **k: sink.update(
            stage=k["stage"].id,
            prompt=k.get("prompt_override"),
            handoff_extra=k.get("handoff_extra"),
            sync_main=k.get("sync_main"),
        ),
    )


def test_author_launches_gist_author_with_seed(monkeypatch):
    sink: dict = {}
    _stub_launch(monkeypatch, sink)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["gist", "author"])
    assert result.exit_code == 0, result.output
    assert sink["stage"] == "gist-author"
    assert "gist_draft" in sink["prompt"] and "plan_review" in sink["prompt"]
    assert sink["handoff_extra"] is None  # no --scope → nothing pre-seeded


def test_author_scope_rides_the_handoff(monkeypatch):
    sink: dict = {}
    _stub_launch(monkeypatch, sink)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["gist", "author", "--scope", "objective"])
    assert result.exit_code == 0, result.output
    assert sink["handoff_extra"] == {"gist_scope": "objective"}


def test_author_dry_run_prints_launch_plan(monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["gist", "author", "--dry-run", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.splitlines()[-1])
    assert payload["success"] is True and payload["stage"] == "gist-author"


def test_author_remote_rejected(monkeypatch):
    # gist-author is local-only (cold_remote: false) — --remote is rejected up front.
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["gist", "author", "--remote", "ci", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["success"] is False


def test_save_dry_run_prints_launch_plan(monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["gist", "save", "--dry-run", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.splitlines()[-1])
    assert payload["success"] is True and payload["stage"] == "gist-save"
