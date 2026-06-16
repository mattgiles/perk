import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github, objective
from perk.cli.cli import cli

N = objective.NodeStatus


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _nodes():
    return (
        objective.ObjectiveNode(id="1.1", description="A", status=N.DONE),
        objective.ObjectiveNode(id="1.2", description="B", status=N.PENDING),
    )


def _invoke(args, *, body=None):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        full = list(args)
        if body is not None:
            bf = Path(d) / "obj.md"
            bf.write_text(body, encoding="utf-8")
            full = [*full, "--body", str(bf)]
        return runner.invoke(cli, full)


def test_create_json(monkeypatch):
    _authed(monkeypatch)
    captured = {}

    def _create(**k):
        captured.update(k)
        return github.ObjectiveIssue(number=42, url="u/42", existed=False)

    monkeypatch.setattr(github, "create_objective_issue", _create)
    roadmap = json.dumps([{"id": "1.1", "description": "x"}])
    result = _invoke(
        ["objective", "create", "--json", "--roadmap", roadmap], body="# Ship it\n\nprose"
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["success"] is True and payload["objective"]["id"] == "42"
    assert captured["title"] == "Ship it"  # derived from the body heading


def test_create_empty_roadmap_rejected(monkeypatch):
    # A prose body with no --roadmap (and no embedded roadmap) is rejected before any write.
    _authed(monkeypatch)

    def _must_not_create(**k):
        raise AssertionError("create_objective_issue must not be called for an empty roadmap")

    monkeypatch.setattr(github, "create_objective_issue", _must_not_create)
    result = _invoke(["objective", "create", "--json"], body="# Obj\n\nprose")
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False and payload["error_type"] == "empty_roadmap"


def test_create_structured_empty_roadmap_rejected(monkeypatch):
    # --roadmap "[]" is a structurally empty roadmap — rejected before any write.
    _authed(monkeypatch)

    def _must_not_create(**k):
        raise AssertionError("create_objective_issue must not be called for an empty roadmap")

    monkeypatch.setattr(github, "create_objective_issue", _must_not_create)
    result = _invoke(["objective", "create", "--json", "--roadmap", "[]"], body="# Obj\n\nprose")
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False and payload["error_type"] == "empty_roadmap"


def test_create_structured_roadmap_passes_nodes(monkeypatch):
    # P3.T2: --roadmap <json> is parsed into ObjectiveNodes and handed to create_objective_issue;
    # the agent never hand-writes roadmap YAML in the body.
    _authed(monkeypatch)
    captured = {}

    def _create(**k):
        captured.update(k)
        return github.ObjectiveIssue(number=7, url="u/7", existed=False)

    monkeypatch.setattr(github, "create_objective_issue", _create)
    roadmap = json.dumps(
        [
            {"id": "1.1", "description": "first"},
            {"id": "1.2", "description": "second", "depends_on": ["1.1"]},
        ]
    )
    result = _invoke(
        ["objective", "create", "--json", "--roadmap", roadmap], body="# Ship it\n\nprose"
    )
    assert result.exit_code == 0, result.output
    nodes = captured["roadmap_nodes"]
    assert [n.id for n in nodes] == ["1.1", "1.2"]
    assert nodes[1].depends_on == ("1.1",)


def test_create_structured_roadmap_invalid(monkeypatch):
    # A structurally invalid --roadmap node is rejected as invalid_roadmap before any write.
    _authed(monkeypatch)
    monkeypatch.setattr(
        github,
        "create_objective_issue",
        lambda **k: github.ObjectiveIssue(number=1, url="u/1", existed=False),
    )
    bad = json.dumps([{"id": "1.1", "description": "x", "status": "bogus"}])
    result = _invoke(["objective", "create", "--json", "--roadmap", bad], body="# Obj\n\nprose")
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "invalid_roadmap"


def test_create_malformed_roadmap_json(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(
        github,
        "create_objective_issue",
        lambda **k: github.ObjectiveIssue(number=1, url="u/1", existed=False),
    )
    result = _invoke(
        ["objective", "create", "--json", "--roadmap", "{not json"], body="# Obj\n\nprose"
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "invalid_roadmap"


def test_create_empty_body_invalid(monkeypatch):
    _authed(monkeypatch)
    result = _invoke(["objective", "create", "--json"], body="   ")
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False and payload["error_type"] == "empty_body"


def test_create_invalid_roadmap(monkeypatch):
    _authed(monkeypatch)
    from perk.plan import render_metadata_block

    bad = render_metadata_block(
        objective.OBJECTIVE_ROADMAP_KEY,
        {"schema_version": "1", "nodes": [{"id": "1.1", "description": "x", "status": "bogus"}]},
    )
    result = _invoke(["objective", "create", "--json"], body=f"# Obj\n\n{bad}")
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "invalid_roadmap"


def test_show_json(monkeypatch):
    monkeypatch.setattr(
        github,
        "get_objective",
        lambda **k: github.ObjectiveState(
            number=42, url="u/42", title="Obj", header={"run_id": "01RID"}, nodes=_nodes()
        ),
    )
    result = _invoke(["objective", "show", "42", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["summary"]["total"] == 2
    assert payload["next_node"]["id"] == "1.2"
    assert payload["resumable_claims"] == []  # always present, empty when no claims exist
    assert payload["all_complete"] is False


def test_show_json_reports_resumable_claims(monkeypatch):
    # An unblocked planning-no-pr claim is surfaced for multi-terminal coordination.
    monkeypatch.setattr(
        github,
        "get_objective",
        lambda **k: github.ObjectiveState(
            number=42,
            url="u/42",
            title="Obj",
            header={},
            nodes=(
                objective.ObjectiveNode(
                    id="1.1", description="A", status=N.PLANNING, pr=None, depends_on=()
                ),
                objective.ObjectiveNode(id="1.2", description="B", status=N.PENDING, depends_on=()),
            ),
        ),
    )
    result = _invoke(["objective", "show", "42", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [n["id"] for n in payload["resumable_claims"]] == ["1.1"]
    assert payload["next_node"]["id"] == "1.2"  # pending-first selection
    # Human render notes the unresumed claim after the next: line.
    human = _invoke(["objective", "show", "42"])
    assert human.exit_code == 0
    assert "next: 1.2" in human.stderr
    assert "claims: 1.1 (planning, unresumed — resume with --node)" in human.stderr


def test_show_not_found(monkeypatch):
    monkeypatch.setattr(github, "get_objective", lambda **k: None)
    result = _invoke(["objective", "show", "99", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "objective_not_found"


def test_node_json(monkeypatch):
    _authed(monkeypatch)
    captured = {}

    def _update(**k):
        captured.update(k)
        return github.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        )

    monkeypatch.setattr(github, "update_objective_node", _update)
    result = _invoke(
        [
            "objective",
            "node",
            "42",
            "--node",
            "1.2",
            "--status",
            "in_progress",
            "--pr",
            "#9",
            "--json",
        ]
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["success"] is True and payload["node"] == "1.2"
    assert captured["status"] is N.IN_PROGRESS and captured["pr"] == "#9"


def test_node_not_found_maps_error(monkeypatch):
    _authed(monkeypatch)

    def _update(**k):
        raise github.GitHubError("objective node '9.9' not found on #42")

    monkeypatch.setattr(github, "update_objective_node", _update)
    result = _invoke(["objective", "node", "42", "--node", "9.9", "--status", "done", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "node_not_found"


def test_node_add_json(monkeypatch):
    _authed(monkeypatch)
    captured = {}

    def _add(**k):
        captured.update(k)
        return github.ObjectiveNodeAdd(
            number=k["number"], node_id="2.3", comment_updated=True, dry_run=False
        )

    monkeypatch.setattr(github, "add_objective_node", _add)
    result = _invoke(
        [
            "objective",
            "node-add",
            "42",
            "--phase",
            "2",
            "--description",
            "Newly emerged work",
            "--depends-on",
            "1.1",
            "--depends-on",
            "2.1",
            "--json",
        ]
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["success"] is True and payload["node"] == "2.3"
    assert payload["comment_updated"] is True and payload["dry_run"] is False
    assert captured["phase"] == 2
    assert captured["depends_on"] == ("1.1", "2.1")
    assert captured["status"] is N.PENDING  # default


def test_node_add_dry_run_does_not_require_github(monkeypatch):
    # No _authed(): a dry run must not call require_github.
    captured = {}

    def _add(**k):
        captured.update(k)
        return github.ObjectiveNodeAdd(
            number=k["number"], node_id="1.3", comment_updated=False, dry_run=True
        )

    monkeypatch.setattr(github, "add_objective_node", _add)
    result = _invoke(
        ["objective", "node-add", "42", "--phase", "1", "--description", "X", "--dry-run", "--json"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["dry_run"] is True and payload["node"] == "1.3"
    assert captured["dry_run"] is True


def test_node_add_collision_maps_to_invalid_input(monkeypatch):
    _authed(monkeypatch)

    def _add(**k):
        raise github.GitHubError("could not add node to phase 1 on #42 (id collision)")

    monkeypatch.setattr(github, "add_objective_node", _add)
    result = _invoke(
        ["objective", "node-add", "42", "--phase", "1", "--description", "X", "--json"]
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "invalid_input"


def test_node_add_not_a_repo_exit_2():
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init -> not a repo
        result = runner.invoke(
            cli, ["objective", "node-add", "1", "--phase", "1", "--description", "X", "--json"]
        )
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error_type"] == "not_a_repo"


def test_next_json(monkeypatch):
    monkeypatch.setattr(
        github,
        "get_objective",
        lambda **k: github.ObjectiveState(
            number=42, url="u/42", title="Obj", header={}, nodes=_nodes()
        ),
    )
    result = _invoke(["objective", "next", "42", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["next_node"]["id"] == "1.2"


def test_not_a_repo_exit_2(monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init -> not a repo
        result = runner.invoke(cli, ["objective", "show", "1", "--json"])
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error_type"] == "not_a_repo"


# --- P2.T11b: objective reconcile worker ---------------------------------------------------


def test_reconcile_dry_run_composes_without_writing(monkeypatch):
    captured = {}

    def _update(**k):
        captured.update(k)
        return github.ObjectiveBodyUpdate(
            number=k["number"], comment_id=99, updated=False, dry_run=True
        )

    monkeypatch.setattr(github, "update_objective_body", _update)
    result = _invoke(["objective", "reconcile", "5", "--dry-run", "--json"], body="New prose.")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["success"] is True and payload["updated"] is False
    assert payload["dry_run"] is True and captured["dry_run"] is True
    assert captured["prose"] == "New prose."


def test_reconcile_missing_target_maps_to_reconcile_target_missing(monkeypatch):
    _authed(monkeypatch)

    def _update(**k):
        raise github.GitHubError("objective #5 has no body comment")

    monkeypatch.setattr(github, "update_objective_body", _update)
    result = _invoke(["objective", "reconcile", "5", "--json"], body="x")
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "reconcile_target_missing"


def test_reconcile_no_region_maps_to_reconcile_target_missing(monkeypatch):
    _authed(monkeypatch)

    def _update(**k):
        raise github.GitHubError("objective #5 body comment has no reconcilable region")

    monkeypatch.setattr(github, "update_objective_body", _update)
    result = _invoke(["objective", "reconcile", "5", "--json"], body="x")
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "reconcile_target_missing"


def test_reconcile_infra_error_maps_to_github_error(monkeypatch):
    _authed(monkeypatch)

    def _update(**k):
        raise github.GitHubError("gh timed out")

    monkeypatch.setattr(github, "update_objective_body", _update)
    result = _invoke(["objective", "reconcile", "5", "--json"], body="x")
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "github_error"


# --- Node 4.3: fail-open Project Updates on the Linear project-backed path -------------------

from perk.backends import objective_store, objective_stores  # noqa: E402


class _FakeStore:
    """A minimal objective store stand-in for the create/reconcile transition sites: records the
    posted status-update body, or raises when `post_raises` is set (the fail-open probe)."""

    backend_id = "linear"

    def __init__(self, *, existed=False, updated=True, post_raises=False):
        self._existed = existed
        self._updated = updated
        self._post_raises = post_raises
        self.posts: list[dict] = []

    def create_objective(self, **k):
        return objective_store.ObjectiveRef(id="proj-1", url="p/url", existed=self._existed)

    def update_objective_body(self, **k):
        return objective_store.ObjectiveBodyUpdate(
            objective_id=str(k["objective_id"]),
            comment_id=None,
            updated=self._updated and not k.get("dry_run"),
            dry_run=bool(k.get("dry_run")),
        )

    def post_status_update(self, *, objective_id, body, dry_run=False):
        if self._post_raises:
            raise objective_store.ObjectiveStoreError("linear update boom")
        self.posts.append({"objective_id": objective_id, "body": body})
        return True


def test_create_posts_status_update_on_linear_path(monkeypatch):
    _authed(monkeypatch)
    store = _FakeStore()
    monkeypatch.setattr(objective_stores, "resolve_objective_store", lambda _root: store)
    roadmap = json.dumps([{"id": "1.1", "description": "x"}, {"id": "2.1", "description": "y"}])
    result = _invoke(
        ["objective", "create", "--json", "--roadmap", roadmap], body="# Ship it\n\nprose"
    )
    assert result.exit_code == 0
    assert len(store.posts) == 1
    assert store.posts[0]["objective_id"] == "proj-1"
    assert store.posts[0]["body"] == ("**Objective created** — Ship it\n\n2 nodes across 2 phases.")


def test_create_does_not_post_on_found_existing(monkeypatch):
    _authed(monkeypatch)
    store = _FakeStore(existed=True)
    monkeypatch.setattr(objective_stores, "resolve_objective_store", lambda _root: store)
    roadmap = json.dumps([{"id": "1.1", "description": "x"}])
    result = _invoke(
        ["objective", "create", "--json", "--roadmap", roadmap], body="# Ship it\n\nprose"
    )
    assert result.exit_code == 0
    assert store.posts == []  # idempotent found-existing path posts nothing


def test_create_status_update_failure_is_fail_open(monkeypatch):
    _authed(monkeypatch)
    store = _FakeStore(post_raises=True)
    monkeypatch.setattr(objective_stores, "resolve_objective_store", lambda _root: store)
    roadmap = json.dumps([{"id": "1.1", "description": "x"}])
    result = _invoke(
        ["objective", "create", "--json", "--roadmap", roadmap], body="# Ship it\n\nprose"
    )
    # The create still succeeds; the failure is logged loud-but-non-fatal to stderr.
    assert result.exit_code == 0
    assert json.loads(result.stdout)["success"] is True
    assert "project update skipped (non-fatal)" in result.stderr


def test_reconcile_posts_status_update_on_linear_path(monkeypatch):
    _authed(monkeypatch)
    store = _FakeStore(updated=True)
    monkeypatch.setattr(objective_stores, "resolve_objective_store", lambda _root: store)
    result = _invoke(["objective", "reconcile", "proj-1", "--json"], body="New prose.")
    assert result.exit_code == 0
    assert len(store.posts) == 1
    assert store.posts[0]["body"] == (
        "**Roadmap reconciled** — the objective prose was updated against the merged diff."
    )


def test_reconcile_status_update_failure_is_fail_open(monkeypatch):
    _authed(monkeypatch)
    store = _FakeStore(updated=True, post_raises=True)
    monkeypatch.setattr(objective_stores, "resolve_objective_store", lambda _root: store)
    result = _invoke(["objective", "reconcile", "proj-1", "--json"], body="New prose.")
    assert result.exit_code == 0
    assert json.loads(result.stdout)["success"] is True
    assert "project update skipped (non-fatal)" in result.stderr
