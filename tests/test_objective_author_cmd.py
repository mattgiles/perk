"""`perk objective author --from <source>`: the in-place objective-adoption cold door (#709, §8.30).

`objective_stores.resolve_objective_store`, `resolve.resolve_issue_backend`, and
`launch.launch_stage` are stubbed (no Linear/GitHub, no `exec pi`), mirroring test_from_cmd.py.
"""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github, objective, plan
from perk.backends import objective_store, objective_stores, resolve
from perk.backends.github import engagement as gh_engagement
from perk.cli.cli import cli
from perk.run import launch

_SCRATCH_REL = ".pi/workflow/scratch/objective-adopt-proj-1.md"


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _source(
    *, prose: str = "the human overview", issues_=()
) -> objective_store.AdoptableObjectiveSource:
    return objective_store.AdoptableObjectiveSource(
        id="proj-1", url="p/url", title="Human Project", prose=prose, issues=tuple(issues_)
    )


def _src_issue(identifier: str = "ENG-1") -> objective_store.AdoptableSourceIssue:
    return objective_store.AdoptableSourceIssue(
        id=f"i-{identifier}",
        identifier=identifier,
        url=f"u/{identifier}",
        title="An issue",
        body="issue body",
    )


class _FakeStore:
    def __init__(self, *, backend_id="linear", source=None, comments=(), raise_comments=False):
        self.backend_id = backend_id
        self._source = source
        self._comments = comments
        self._raise_comments = raise_comments

    def read_objective_source(self, *, source_id):
        return self._source

    def read_comments(self, *, objective_id):
        if self._raise_comments:
            raise objective_store.ObjectiveStoreError("linear exploded")
        return tuple(self._comments)


def _stub(monkeypatch, *, store, sink: dict | None = None, issue_state="OPEN"):
    monkeypatch.setattr(objective_stores, "resolve_objective_store", lambda _root: store)

    class _Backend:
        def read_issue(self, *, issue_id):
            return github.IssueRead(number=1, url="u", title="t", body="b", state=issue_state)

    monkeypatch.setattr(resolve, "resolve_issue_backend", lambda _root: _Backend())
    if sink is not None:
        monkeypatch.setattr(
            launch,
            "launch_stage",
            lambda **k: sink.update(
                stage=k["stage"].id,
                prompt=k.get("prompt_override"),
                handoff_extra=k.get("handoff_extra"),
                dry_run=k.get("dry_run"),
            ),
        )


def test_dry_run_materializes_scratch_and_does_not_launch(monkeypatch):
    _authed(monkeypatch)
    store = _FakeStore(source=_source(issues_=[_src_issue("ENG-1")]))

    def boom(**k):
        raise AssertionError("--dry-run must not launch")

    _stub(monkeypatch, store=store)
    monkeypatch.setattr(launch, "launch_stage", boom)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(
            cli, ["objective", "author", "--from", "proj-1", "--dry-run", "--json"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["success"] is True and payload["source"] == "proj-1"
        scratch = (Path(d) / _SCRATCH_REL).resolve()
        assert Path(payload["scratch_path"]).resolve() == scratch
        text = scratch.read_text(encoding="utf-8")
        assert "<untrusted_adopted_objective>" in text and "the human overview" in text
        assert "<untrusted_adopted_project_issues>" in text and "ENG-1" in text


def test_real_launch_threads_adopt_from_handoff_and_seed(monkeypatch):
    _authed(monkeypatch)
    launched: dict = {}
    _stub(monkeypatch, store=_FakeStore(source=_source(issues_=[_src_issue()])), sink=launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "author", "--from", "proj-1", "--json"])
        assert result.exit_code == 0, result.output
    assert launched["stage"] == "objective-author"
    assert launched["handoff_extra"] == {"adopt_from": "proj-1"}
    prompt = launched["prompt"] or ""
    assert _SCRATCH_REL in prompt
    assert "perk-objective-author" in prompt
    assert "objective_save" in prompt
    assert "adopt_issue" in prompt  # the mapping clause fires (source has issues)


def test_strips_hash_prefix(monkeypatch):
    _authed(monkeypatch)
    launched: dict = {}
    _stub(monkeypatch, store=_FakeStore(source=_source()), sink=launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "author", "--from", "#proj-1", "--json"])
        assert result.exit_code == 0, result.output
    assert launched["handoff_extra"] == {"adopt_from": "proj-1"}


def test_refuses_not_found(monkeypatch):
    _authed(monkeypatch)
    _stub(monkeypatch, store=_FakeStore(source=None))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "author", "--from", "proj-1", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "adopt_not_found"


def test_refuses_already_an_objective(monkeypatch):
    _authed(monkeypatch)
    header = plan.render_metadata_block(
        objective.OBJECTIVE_HEADER_KEY,
        objective.ObjectiveHeader(run_id="R", created="t").to_data(),
    )
    _stub(monkeypatch, store=_FakeStore(source=_source(prose=f"prose\n\n{header}\n")))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "author", "--from", "proj-1", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["error_type"] == "already_an_objective"
        assert "reconcile" in payload["message"]


def test_github_backend_refuses_closed_issue(monkeypatch):
    _authed(monkeypatch)
    _stub(
        monkeypatch,
        store=_FakeStore(backend_id="github", source=_source()),
        issue_state="CLOSED",
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "author", "--from", "7", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "adopt_not_open"


def test_linear_backend_skips_open_check(monkeypatch):
    # A Linear project has no OPEN/CLOSED — the OPEN check is skipped even if the issue backend
    # would report closed.
    _authed(monkeypatch)
    launched: dict = {}
    _stub(
        monkeypatch,
        store=_FakeStore(backend_id="linear", source=_source()),
        sink=launched,
        issue_state="CLOSED",
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "author", "--from", "proj-1", "--json"])
        assert result.exit_code == 0, result.output
    assert launched["handoff_extra"] == {"adopt_from": "proj-1"}


def test_engagement_appended_and_points_seed(monkeypatch):
    _authed(monkeypatch)
    launched: dict = {}
    comment = gh_engagement.IssueCommentRow(
        id="c1",
        body="please scope tightly",
        created_at="2026-03-01T10:00:00Z",
        edited_at=None,
        author_login="ada",
        author_id="u-1",
        author_is_bot=False,
    )
    from perk.backends.github import backend as _gh_backend

    eng = _gh_backend._engagement_comment(comment)
    _stub(monkeypatch, store=_FakeStore(source=_source(), comments=[eng]), sink=launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "author", "--from", "proj-1", "--json"])
        assert result.exit_code == 0, result.output
        text = (Path(d) / _SCRATCH_REL).read_text(encoding="utf-8")
    assert "<untrusted_adopted_issue_engagement>" in text
    assert "please scope tightly" in text


def test_engagement_read_failure_is_fail_soft(monkeypatch):
    _authed(monkeypatch)
    launched: dict = {}
    _stub(
        monkeypatch,
        store=_FakeStore(source=_source(), raise_comments=True),
        sink=launched,
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "author", "--from", "proj-1", "--json"])
        assert result.exit_code == 0, result.output
        text = (Path(d) / _SCRATCH_REL).read_text(encoding="utf-8")
    assert "<untrusted_adopted_issue_engagement>" not in text


def test_from_absent_uses_normal_authoring_seed(monkeypatch):
    _authed(monkeypatch)
    launched: dict = {}
    # No --from: the door must be byte-unchanged (the existing authoring seed, no handoff).
    monkeypatch.setattr(
        launch,
        "launch_stage",
        lambda **k: launched.update(
            stage=k["stage"].id,
            prompt=k.get("prompt_override"),
            handoff_extra=k.get("handoff_extra"),
        ),
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "author", "--json"])
        assert result.exit_code == 0, result.output
    assert launched["stage"] == "objective-author"
    assert launched["handoff_extra"] is None  # no adoption handoff
    assert "objective author flow" in (launched["prompt"] or "")
    assert "--from" not in (launched["prompt"] or "")


def test_remote_rejected(monkeypatch):
    _authed(monkeypatch)
    _stub(monkeypatch, store=_FakeStore(source=_source()))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(
            cli, ["objective", "author", "--from", "proj-1", "--remote", "ci", "--json"]
        )
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "remote_blocked"
