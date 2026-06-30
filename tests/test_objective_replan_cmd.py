"""`perk objective replan <N>`: the superseding re-author cold door.

The objective store, issue backend, and `launch.launch_stage` are stubbed (no GitHub, no
`exec pi`), mirroring test_from_cmd.py / test_replan_cmd.py. Asserts the dry-run materialization,
the fresh-run-id + `supersedes` handoff threading, and the refusals.
"""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github, objective
from perk.backends import resolve
from perk.backends.objective_store import ObjectiveState
from perk.cli.cli import cli
from perk.run import launch

_SCRATCH_REL = ".perk/workflow/scratch/objective-replan-42.md"


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _node(node_id: str, status: objective.NodeStatus, pr: str | None = None):
    return objective.ObjectiveNode(id=node_id, description=f"node {node_id}", status=status, pr=pr)


class _IssueRead:
    def __init__(self, state: str = "OPEN") -> None:
        self.state = state


class _FakeIssueBackend:
    def __init__(self, state: str = "OPEN") -> None:
        self._state = state

    def read_issue(self, *, issue_id: str):
        return _IssueRead(self._state)


class _FakeStore:
    backend_id = "github"

    def __init__(self, *, state: ObjectiveState | None, raise_engagement: bool = False) -> None:
        self._state = state
        self._raise_engagement = raise_engagement

    def get_objective(self, *, objective_id: str):
        return self._state

    def read_comments(self, *, objective_id: str):
        if self._raise_engagement:
            from perk.backends.objective_store import ObjectiveStoreError

            raise ObjectiveStoreError("boom")
        return ()

    def read_description_edits(self, *, objective_id: str):
        return ()

    def read_node_engagement(self, *, objective_id: str, node_id: str):
        from perk.backends import engagement

        return engagement.EMPTY_NODE_ENGAGEMENT

    def read_objective_source(self, *, source_id: str):
        from perk.backends.objective_store import AdoptableObjectiveSource

        return AdoptableObjectiveSource(
            id=source_id, url="u/42", title="Old objective", prose="The old objective rationale."
        )


def _state(nodes, *, header=None) -> ObjectiveState:
    return ObjectiveState(
        id="42",
        url="u/42",
        title="Old objective",
        header=header or {"run_id": "01OLD", "status": "active"},
        nodes=tuple(nodes),
    )


def _patch(monkeypatch, store, *, issue_state: str = "OPEN") -> None:
    _authed(monkeypatch)
    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: store)
    monkeypatch.setattr(
        resolve, "resolve_issue_backend", lambda _root: _FakeIssueBackend(issue_state)
    )


def _stub_launch(monkeypatch, sink: dict) -> None:
    monkeypatch.setattr(
        launch,
        "launch_stage",
        lambda **k: sink.update(
            stage=k["stage"].id,
            prompt=k.get("prompt_override"),
            handoff_extra=k.get("handoff_extra"),
            run_id_override=k.get("run_id_override"),
            binding_trigger=k.get("binding_trigger"),
        ),
    )


_UNFINISHED_NODES = [
    _node("1.1", objective.NodeStatus.DONE),
    _node("1.2", objective.NodeStatus.PENDING),
    _node("2.1", objective.NodeStatus.IN_PROGRESS),
    _node("2.2", objective.NodeStatus.SKIPPED),
]


def test_dry_run_json_materializes_and_does_not_launch(monkeypatch):
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    _patch(monkeypatch, store)

    def boom_launch(**k):
        raise AssertionError("--dry-run must not launch")

    monkeypatch.setattr(launch, "launch_stage", boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "replan", "42", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)  # stdout only: the lookup line is on stderr
        assert payload["success"] is True
        assert payload["objective"] == "42" and payload["supersedes"] == "42"
        # only the UNFINISHED nodes carry forward (done/skipped excluded)
        assert payload["unfinished_nodes"] == ["1.2", "2.1"]
        scratch = (Path(d) / _SCRATCH_REL).resolve()
        assert Path(payload["scratch_path"]).resolve() == scratch
        text = scratch.read_text(encoding="utf-8")
        assert "<untrusted_objective>" in text and "rationale" in text
        assert "<untrusted_objective_unfinished_nodes>" in text
        assert "node 1.2" in text and "node 2.1" in text
        assert "node 1.1" not in text  # done node excluded
        # The lookup runs on the dry-run path too, so the wait IS narrated (to stderr).
        assert "looking up objective #42" in result.stderr


def test_real_launch_threads_supersedes_handoff_and_fresh_run_id(monkeypatch):
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    _patch(monkeypatch, store)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "replan", "42", "--json"])
        assert result.exit_code == 0, result.output
        assert "looking up objective #42" in result.stderr  # narrates the backend lookup wait
    assert launched["stage"] == "objective-author"  # borrows the objective-author stage
    assert launched["handoff_extra"] == {"supersedes": "42"}
    assert launched["run_id_override"] is None  # FRESH run_id minted (net-new objective)
    assert launched["binding_trigger"] == "command:objective-replan"
    prompt = launched["prompt"] or ""
    assert _SCRATCH_REL in prompt
    assert "perk-objective-replan" in prompt
    assert "objective_save" in prompt


def test_real_launch_banner_precedes_lookup(monkeypatch):
    """A real local launch heads stderr with the banner BEFORE the `looking up #X` narration."""
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    _patch(monkeypatch, store)
    _stub_launch(monkeypatch, {})
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "replan", "42"])
        assert result.exit_code == 0, result.output
        err = result.stderr
        assert err.index("skills \u00b7") < err.index("looking up")


def test_dry_run_emits_no_banner(monkeypatch):
    """The banner is gated off on `--dry-run` (the preview path owns the output)."""
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    _patch(monkeypatch, store)
    monkeypatch.setattr(launch, "launch_stage", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "replan", "42", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        assert "skills \u00b7" not in result.stderr


def test_strips_hash_prefix(monkeypatch):
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    _patch(monkeypatch, store)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "replan", "#42", "--json"])
        assert result.exit_code == 0, result.output
    assert launched["handoff_extra"] == {"supersedes": "42"}


def test_refuses_not_found(monkeypatch):
    store = _FakeStore(state=None)
    _patch(monkeypatch, store)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "replan", "42", "--json"])
        assert result.exit_code == 1
        # Parse stdout: the real-path `looking up #42` line is on stderr (combined .output).
        assert json.loads(result.stdout)["error_type"] == "objective_not_found"


def test_refuses_already_superseded(monkeypatch):
    store = _FakeStore(
        state=_state(_UNFINISHED_NODES, header={"run_id": "01OLD", "superseded_by": "99"})
    )
    _patch(monkeypatch, store)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "replan", "42", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "objective_not_open"


def test_refuses_non_open_github_objective(monkeypatch):
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    _patch(monkeypatch, store, issue_state="CLOSED")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "replan", "42", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "objective_not_open"


def test_rejects_remote(monkeypatch):
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    _patch(monkeypatch, store)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "replan", "42", "--remote", "runner", "--json"])
        assert result.exit_code == 1


def test_engagement_read_failure_is_fail_soft(monkeypatch):
    store = _FakeStore(state=_state(_UNFINISHED_NODES), raise_engagement=True)
    _patch(monkeypatch, store)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "replan", "42", "--json"])
        assert result.exit_code == 0, result.output
        text = (Path(d) / _SCRATCH_REL).read_text(encoding="utf-8")
    assert "<untrusted_objective_engagement>" not in text
