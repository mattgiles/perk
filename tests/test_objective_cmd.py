import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github, objective
from perk.backends.github import objectives
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
        return objectives.ObjectiveIssue(number=42, url="u/42", existed=False)

    monkeypatch.setattr(objectives, "create_objective_issue", _create)
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

    monkeypatch.setattr(objectives, "create_objective_issue", _must_not_create)
    result = _invoke(["objective", "create", "--json"], body="# Obj\n\nprose")
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False and payload["error_type"] == "empty_roadmap"


def test_create_structured_empty_roadmap_rejected(monkeypatch):
    # --roadmap "[]" is a structurally empty roadmap — rejected before any write.
    _authed(monkeypatch)

    def _must_not_create(**k):
        raise AssertionError("create_objective_issue must not be called for an empty roadmap")

    monkeypatch.setattr(objectives, "create_objective_issue", _must_not_create)
    result = _invoke(["objective", "create", "--json", "--roadmap", "[]"], body="# Obj\n\nprose")
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False and payload["error_type"] == "empty_roadmap"


def test_create_structured_roadmap_passes_nodes(monkeypatch):
    # --roadmap <json> is parsed into ObjectiveNodes and handed to create_objective_issue;
    # the agent never hand-writes roadmap YAML in the body.
    _authed(monkeypatch)
    captured = {}

    def _create(**k):
        captured.update(k)
        return objectives.ObjectiveIssue(number=7, url="u/7", existed=False)

    monkeypatch.setattr(objectives, "create_objective_issue", _create)
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


def _invoke_with_config(args, *, body, config):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        pi = Path(d) / ".pi"
        pi.mkdir(parents=True, exist_ok=True)
        (pi / "perk.toml").write_text(config, encoding="utf-8")
        bf = Path(d) / "obj.md"
        bf.write_text(body, encoding="utf-8")
        return runner.invoke(cli, [*args, "--body", str(bf)])


def test_create_base_flag_stored(monkeypatch):
    # --base develop pins the objective's base into create_objective(base=...).
    _authed(monkeypatch)
    captured = {}

    def _create(**k):
        captured.update(k)
        return objectives.ObjectiveIssue(number=7, url="u/7", existed=False)

    monkeypatch.setattr(objectives, "create_objective_issue", _create)
    roadmap = json.dumps([{"id": "1.1", "description": "x"}])
    result = _invoke(
        ["objective", "create", "--json", "--base", "develop", "--roadmap", roadmap],
        body="# Ship it\n\nprose",
    )
    assert result.exit_code == 0, result.output
    assert captured["base"] == "develop"


def test_create_base_from_config(monkeypatch):
    # With no --base, the repo's [workflow] base is pinned at create time.
    _authed(monkeypatch)
    captured = {}

    def _create(**k):
        captured.update(k)
        return objectives.ObjectiveIssue(number=7, url="u/7", existed=False)

    monkeypatch.setattr(objectives, "create_objective_issue", _create)
    roadmap = json.dumps([{"id": "1.1", "description": "x"}])
    result = _invoke_with_config(
        ["objective", "create", "--json", "--roadmap", roadmap],
        body="# Ship it\n\nprose",
        config='[workflow]\nbase = "release"\n',
    )
    assert result.exit_code == 0, result.output
    assert captured["base"] == "release"


def test_create_base_flag_wins_over_config(monkeypatch):
    # An explicit --base wins over the [workflow] base config.
    _authed(monkeypatch)
    captured = {}

    def _create(**k):
        captured.update(k)
        return objectives.ObjectiveIssue(number=7, url="u/7", existed=False)

    monkeypatch.setattr(objectives, "create_objective_issue", _create)
    roadmap = json.dumps([{"id": "1.1", "description": "x"}])
    result = _invoke_with_config(
        ["objective", "create", "--json", "--base", "develop", "--roadmap", roadmap],
        body="# Ship it\n\nprose",
        config='[workflow]\nbase = "release"\n',
    )
    assert result.exit_code == 0, result.output
    assert captured["base"] == "develop"


def test_create_base_none_when_unset(monkeypatch):
    # Neither --base nor [workflow] base → base=None (default-branch behavior).
    _authed(monkeypatch)
    captured = {}

    def _create(**k):
        captured.update(k)
        return objectives.ObjectiveIssue(number=7, url="u/7", existed=False)

    monkeypatch.setattr(objectives, "create_objective_issue", _create)
    roadmap = json.dumps([{"id": "1.1", "description": "x"}])
    result = _invoke(
        ["objective", "create", "--json", "--roadmap", roadmap], body="# Ship it\n\nprose"
    )
    assert result.exit_code == 0, result.output
    assert captured["base"] is None


def test_create_structured_roadmap_invalid(monkeypatch):
    # A structurally invalid --roadmap node is rejected as invalid_roadmap before any write.
    _authed(monkeypatch)
    monkeypatch.setattr(
        objectives,
        "create_objective_issue",
        lambda **k: objectives.ObjectiveIssue(number=1, url="u/1", existed=False),
    )
    bad = json.dumps([{"id": "1.1", "description": "x", "status": "bogus"}])
    result = _invoke(["objective", "create", "--json", "--roadmap", bad], body="# Obj\n\nprose")
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "invalid_roadmap"


def test_create_malformed_roadmap_json(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(
        objectives,
        "create_objective_issue",
        lambda **k: objectives.ObjectiveIssue(number=1, url="u/1", existed=False),
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


# --- objective create --adopt-from + handoff recovery --------------------------


class _AdoptStubStore:
    """A minimal ObjectiveStore stub that records the adoption call and returns a fresh ref."""

    backend_id = "github"

    def __init__(self, *, adopt_returns_none: bool = False) -> None:
        self.adopt_kwargs: dict | None = None
        self.created = False
        self._adopt_returns_none = adopt_returns_none
        from perk.backends import objective_store

        self._ref_cls = objective_store.ObjectiveRef

    def adopt_source_as_objective(self, **kwargs):
        self.adopt_kwargs = kwargs
        if self._adopt_returns_none:
            return None
        return self._ref_cls(id="proj-1", url="p/url", existed=False)

    def create_objective(self, **kwargs):
        self.created = True
        return self._ref_cls(id="99", url="u/99", existed=False)

    def post_status_update(self, **kwargs):
        return False


def _invoke_adopt(args, *, body, monkeypatch, store, write_handoff=None):
    from perk.backends import resolve
    from perk.state import cache

    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: store)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        bf = Path(d) / "obj.md"
        bf.write_text(body, encoding="utf-8")
        if write_handoff is not None:
            run_id, blob = write_handoff
            cache.write_handoff(Path(d), run_id, blob)
        return runner.invoke(cli, [*args, "--body", str(bf)])


def test_create_adopt_from_routes_to_writer(monkeypatch):
    _authed(monkeypatch)
    store = _AdoptStubStore()
    roadmap = json.dumps(
        [
            {"id": "1.1", "description": "first", "adopt_issue": "ENG-1"},
            {"id": "1.2", "description": "second"},
        ]
    )
    result = _invoke_adopt(
        ["objective", "create", "--json", "--adopt-from", "proj-1", "--roadmap", roadmap],
        body="# Ship it\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 0, result.output
    assert store.adopt_kwargs is not None and store.created is False
    assert store.adopt_kwargs["source_id"] == "proj-1"
    assert store.adopt_kwargs["adopt_map"] == {"1.1": "ENG-1"}
    assert [n.id for n in store.adopt_kwargs["roadmap_nodes"]] == ["1.1", "1.2"]


def test_create_adopt_from_handoff_recovery(monkeypatch):
    _authed(monkeypatch)
    store = _AdoptStubStore()
    roadmap = json.dumps([{"id": "1.1", "description": "x"}])
    result = _invoke_adopt(
        ["objective", "create", "--json", "--run-id", "RID9", "--roadmap", roadmap],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
        write_handoff=("RID9", {"adopt_from": "proj-7"}),
    )
    assert result.exit_code == 0, result.output
    assert store.adopt_kwargs is not None
    assert store.adopt_kwargs["source_id"] == "proj-7"  # recovered from the handoff


def test_create_explicit_adopt_from_wins_over_handoff(monkeypatch):
    _authed(monkeypatch)
    store = _AdoptStubStore()
    roadmap = json.dumps([{"id": "1.1", "description": "x"}])
    result = _invoke_adopt(
        [
            "objective",
            "create",
            "--json",
            "--run-id",
            "RID9",
            "--adopt-from",
            "explicit-1",
            "--roadmap",
            roadmap,
        ],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
        write_handoff=("RID9", {"adopt_from": "handoff-1"}),
    )
    assert result.exit_code == 0, result.output
    assert store.adopt_kwargs is not None
    assert store.adopt_kwargs["source_id"] == "explicit-1"


def test_create_adopt_unsupported(monkeypatch):
    _authed(monkeypatch)
    store = _AdoptStubStore(adopt_returns_none=True)
    roadmap = json.dumps([{"id": "1.1", "description": "x"}])
    result = _invoke_adopt(
        ["objective", "create", "--json", "--adopt-from", "proj-1", "--roadmap", roadmap],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False and payload["error_type"] == "adopt_unsupported"


def test_create_adopt_from_dry_run_composes_without_adopting(monkeypatch):
    _authed(monkeypatch)
    store = _AdoptStubStore()
    roadmap = json.dumps([{"id": "1.1", "description": "x"}])
    result = _invoke_adopt(
        [
            "objective",
            "create",
            "--json",
            "--dry-run",
            "--adopt-from",
            "proj-1",
            "--roadmap",
            roadmap,
        ],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 0, result.output
    # dry-run falls through to the offline create_objective(dry_run=True) compose-preview
    assert store.adopt_kwargs is None and store.created is True


def test_show_json(monkeypatch):
    monkeypatch.setattr(
        objectives,
        "get_objective",
        lambda **k: objectives.ObjectiveState(
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
        objectives,
        "get_objective",
        lambda **k: objectives.ObjectiveState(
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
    monkeypatch.setattr(objectives, "get_objective", lambda **k: None)
    result = _invoke(["objective", "show", "99", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "objective_not_found"


def test_node_json(monkeypatch):
    _authed(monkeypatch)
    captured = {}

    def _update(**k):
        captured.update(k)
        return objectives.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        )

    monkeypatch.setattr(objectives, "update_objective_node", _update)
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

    monkeypatch.setattr(objectives, "update_objective_node", _update)
    result = _invoke(["objective", "node", "42", "--node", "9.9", "--status", "done", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "node_not_found"


def test_node_add_json(monkeypatch):
    _authed(monkeypatch)
    captured = {}

    def _add(**k):
        captured.update(k)
        return objectives.ObjectiveNodeAdd(
            number=k["number"], node_id="2.3", comment_updated=True, dry_run=False
        )

    monkeypatch.setattr(objectives, "add_objective_node", _add)
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
        return objectives.ObjectiveNodeAdd(
            number=k["number"], node_id="1.3", comment_updated=False, dry_run=True
        )

    monkeypatch.setattr(objectives, "add_objective_node", _add)
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

    monkeypatch.setattr(objectives, "add_objective_node", _add)
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
        objectives,
        "get_objective",
        lambda **k: objectives.ObjectiveState(
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


# --- objective reconcile worker ---------------------------------------------------


def test_reconcile_dry_run_composes_without_writing(monkeypatch):
    captured = {}

    def _update(**k):
        captured.update(k)
        return objectives.ObjectiveBodyUpdate(
            number=k["number"], comment_id=99, updated=False, dry_run=True
        )

    monkeypatch.setattr(objectives, "update_objective_body", _update)
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

    monkeypatch.setattr(objectives, "update_objective_body", _update)
    result = _invoke(["objective", "reconcile", "5", "--json"], body="x")
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "reconcile_target_missing"


def test_reconcile_no_region_maps_to_reconcile_target_missing(monkeypatch):
    _authed(monkeypatch)

    def _update(**k):
        raise github.GitHubError("objective #5 body comment has no reconcilable region")

    monkeypatch.setattr(objectives, "update_objective_body", _update)
    result = _invoke(["objective", "reconcile", "5", "--json"], body="x")
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "reconcile_target_missing"


def test_reconcile_infra_error_maps_to_github_error(monkeypatch):
    _authed(monkeypatch)

    def _update(**k):
        raise github.GitHubError("gh timed out")

    monkeypatch.setattr(objectives, "update_objective_body", _update)
    result = _invoke(["objective", "reconcile", "5", "--json"], body="x")
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "github_error"


# --- fail-open Project Updates on the Linear project-backed path -------------------

from perk.backends import objective_store, resolve  # noqa: E402


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
    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: store)
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
    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: store)
    roadmap = json.dumps([{"id": "1.1", "description": "x"}])
    result = _invoke(
        ["objective", "create", "--json", "--roadmap", roadmap], body="# Ship it\n\nprose"
    )
    assert result.exit_code == 0
    assert store.posts == []  # idempotent found-existing path posts nothing


def test_create_status_update_failure_is_fail_open(monkeypatch):
    _authed(monkeypatch)
    store = _FakeStore(post_raises=True)
    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: store)
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
    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: store)
    result = _invoke(["objective", "reconcile", "proj-1", "--json"], body="New prose.")
    assert result.exit_code == 0
    assert len(store.posts) == 1
    assert store.posts[0]["body"] == (
        "**Roadmap reconciled** — the objective prose was updated against the merged diff."
    )


def test_reconcile_status_update_failure_is_fail_open(monkeypatch):
    _authed(monkeypatch)
    store = _FakeStore(updated=True, post_raises=True)
    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: store)
    result = _invoke(["objective", "reconcile", "proj-1", "--json"], body="New prose.")
    assert result.exit_code == 0
    assert json.loads(result.stdout)["success"] is True
    assert "project update skipped (non-fatal)" in result.stderr


def test_doctor_github_store_is_a_clean_noop(monkeypatch):
    # GitHub objectives have no divergence surface — the drift report is trivially empty and the
    # detect path makes no network call (the no-op store precedent).
    result = _invoke(["objective", "doctor", "42", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert payload["drift"] == [] and payload["fix"] is None


def test_doctor_fix_github_store_empty_repair(monkeypatch):
    _authed(monkeypatch)
    result = _invoke(["objective", "doctor", "42", "--fix", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    fix = payload["fix"]
    assert fix["applied"] == [] and fix["aborted"] is False and fix["remaining"] == []
