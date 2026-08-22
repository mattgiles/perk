import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from perk import github, objective
from perk.backends import resolve
from perk.backends.github import objectives, plans
from perk.cli.cli import cli
from perk.cli.commands.objective import create_cmd

_REAL_RESOLVE_DELIVERY = create_cmd.resolve_delivery
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
        cfg = Path(d) / ".perk"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "config.toml").write_text(config, encoding="utf-8")
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

    def __init__(
        self, *, adopt_returns_none: bool = False, supersede_returns_none: bool = False
    ) -> None:
        self.adopt_kwargs: dict | None = None
        self.supersede_kwargs: dict | None = None
        self.created = False
        self._adopt_returns_none = adopt_returns_none
        self._supersede_returns_none = supersede_returns_none
        from perk.backends import objective_store

        self._ref_cls = objective_store.ObjectiveRef

    def adopt_source_as_objective(self, **kwargs):
        self.adopt_kwargs = kwargs
        if self._adopt_returns_none:
            return None
        return self._ref_cls(id="proj-1", url="p/url", existed=False)

    def supersede_objective(self, **kwargs):
        self.supersede_kwargs = kwargs
        if self._supersede_returns_none:
            return None
        return self._ref_cls(id="proj-2", url="p/url2", existed=False)

    def get_objective(self, **kwargs):
        # The D1 classification read's default: an incremental predecessor (empty header).
        from perk.backends import objective_store

        return objective_store.ObjectiveState(
            id=kwargs["objective_id"], url="u/old", title="Old", header={}, nodes=()
        )

    def create_objective(self, **kwargs):
        self.created = True
        return self._ref_cls(id="99", url="u/99", existed=False)

    def post_status_update(self, **kwargs):
        return False


def _invoke_adopt(args, *, body, monkeypatch, store, write_handoff=None, config=None):
    from perk.backends import resolve
    from perk.state import cache

    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: store)
    if create_cmd.resolve_delivery is _REAL_RESOLVE_DELIVERY:
        service = _PrepareStub()
        monkeypatch.setattr(create_cmd, "resolve_delivery", lambda _root: service)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        bf = Path(d) / "obj.md"
        bf.write_text(body, encoding="utf-8")
        if config is not None:
            config_path = Path(d) / ".perk" / "config.toml"
            config_path.parent.mkdir()
            config_path.write_text(config, encoding="utf-8")
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


def test_create_supersedes_routes_to_writer(monkeypatch):
    _authed(monkeypatch)
    store = _AdoptStubStore()
    service = _stub_prepare(monkeypatch)
    roadmap = json.dumps(
        [
            {"id": "1.1", "description": "carried", "adopt_issue": "ENG-2"},
            {"id": "1.2", "description": "fresh"},
        ]
    )
    result = _invoke_adopt(
        ["objective", "create", "--json", "--supersedes", "#42", "--roadmap", roadmap],
        body="# Successor\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 0, result.output
    assert store.supersede_kwargs is None and store.created is False
    (request,) = service.transfer_requests
    assert request.predecessor_id == "42"  # `#` stripped
    assert request.carry_map == (("1.1", "ENG-2"),)
    assert [node.id for node in request.roadmap_nodes] == ["1.1", "1.2"]


def test_create_supersedes_handoff_recovery(monkeypatch):
    _authed(monkeypatch)
    store = _AdoptStubStore()
    service = _stub_prepare(monkeypatch)
    roadmap = json.dumps([{"id": "1.1", "description": "x"}])
    result = _invoke_adopt(
        ["objective", "create", "--json", "--run-id", "RID9", "--roadmap", roadmap],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
        write_handoff=("RID9", {"supersedes": "55"}),
    )
    assert result.exit_code == 0, result.output
    assert service.transfer_requests[0].predecessor_id == "55"  # recovered from the handoff


def test_create_explicit_supersedes_wins_over_handoff(monkeypatch):
    _authed(monkeypatch)
    store = _AdoptStubStore()
    service = _stub_prepare(monkeypatch)
    roadmap = json.dumps([{"id": "1.1", "description": "x"}])
    result = _invoke_adopt(
        [
            "objective",
            "create",
            "--json",
            "--run-id",
            "RID9",
            "--supersedes",
            "explicit-9",
            "--roadmap",
            roadmap,
        ],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
        write_handoff=("RID9", {"supersedes": "handoff-9"}),
    )
    assert result.exit_code == 0, result.output
    assert service.transfer_requests[0].predecessor_id == "explicit-9"


def test_create_supersede_unsupported(monkeypatch):
    from perk.delivery import DeliveryError

    _authed(monkeypatch)
    store = _AdoptStubStore()
    _stub_prepare(
        monkeypatch,
        transfer_error=DeliveryError(
            "The configured objective backend does not support replan",
            error_type="supersede_unsupported",
        ),
    )
    roadmap = json.dumps([{"id": "1.1", "description": "x"}])
    result = _invoke_adopt(
        ["objective", "create", "--json", "--supersedes", "42", "--roadmap", roadmap],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False and payload["error_type"] == "supersede_unsupported"


def test_create_supersedes_and_adopt_from_mutually_exclusive(monkeypatch):
    _authed(monkeypatch)
    store = _AdoptStubStore()
    roadmap = json.dumps([{"id": "1.1", "description": "x"}])
    result = _invoke_adopt(
        [
            "objective",
            "create",
            "--json",
            "--supersedes",
            "42",
            "--adopt-from",
            "proj-1",
            "--roadmap",
            roadmap,
        ],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False and payload["error_type"] == "invalid_input"
    assert store.supersede_kwargs is None and store.adopt_kwargs is None


def test_create_supersedes_dry_run_composes_without_superseding(monkeypatch):
    _authed(monkeypatch)
    store = _AdoptStubStore()
    roadmap = json.dumps([{"id": "1.1", "description": "x"}])
    result = _invoke_adopt(
        [
            "objective",
            "create",
            "--json",
            "--dry-run",
            "--supersedes",
            "42",
            "--roadmap",
            roadmap,
        ],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 0, result.output
    # dry-run falls through to the offline create_objective(dry_run=True) compose-preview
    assert store.supersede_kwargs is None and store.created is True


# --- the reviewed delivery choice (§8.45): validation → Prepare → gate → lineage -----------


class _DeliveryStubStore(_AdoptStubStore):
    """The adopt stub + captured create kwargs and a readable predecessor header."""

    def __init__(self, *, old_header: dict | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.create_kwargs: dict | None = None
        self.get_objective_ids: list[str] = []
        self._old_header = old_header if old_header is not None else {}

    def create_objective(self, **kwargs):
        self.created = True
        self.create_kwargs = kwargs
        return self._ref_cls(id="99", url="u/99", existed=False)

    def get_objective(self, **kwargs):
        from perk.backends import objective_store

        self.get_objective_ids.append(kwargs["objective_id"])
        return objective_store.ObjectiveState(
            id=kwargs["objective_id"], url="u/old", title="Old", header=self._old_header, nodes=()
        )


class _PrepareStub:
    """Configurable Delivery spy for command request→invoke→render tests."""

    def __init__(self, *, error=None, transfer_error=None, transfer_result=None) -> None:
        self.error = error
        self.transfer_error = transfer_error
        self.transfer_result = transfer_result
        self.requests = []
        self.transfer_requests = []

    def prepare(self, request):
        from perk.delivery import PrepareResult

        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return PrepareResult(kind="authoring", base=request.base or "main")

    def transfer(self, request):
        from perk.backends.objective_store import ObjectiveRef
        from perk.delivery import TransferResult

        self.transfer_requests.append(request)
        if self.transfer_error is not None:
            raise self.transfer_error
        if self.transfer_result is not None:
            return self.transfer_result
        return TransferResult(
            predecessor_id=request.predecessor_id,
            successor=ObjectiveRef(id="777", url="u/777", existed=False),
            operation_id=None,
            abandoned_operation_id=None,
            rolled_forward=False,
            journaled=False,
        )


def _stub_prepare(
    monkeypatch,
    *,
    error=None,
    transfer_error=None,
    transfer_result=None,
    resolver_calls: list | None = None,
):
    service = _PrepareStub(
        error=error,
        transfer_error=transfer_error,
        transfer_result=transfer_result,
    )

    def _resolve(repo_root):
        if resolver_calls is not None:
            resolver_calls.append(repo_root)
        return service

    monkeypatch.setattr(create_cmd, "resolve_delivery", _resolve)
    return service


def _two_nodes_roadmap() -> str:
    return json.dumps(
        [{"id": "1.1", "description": "first"}, {"id": "1.2", "description": "second"}]
    )


def test_create_stacked_one_node_rejected_with_standalone_plan_message(monkeypatch):
    _authed(monkeypatch)
    store = _DeliveryStubStore()
    resolver_calls: list[Path] = []
    _stub_prepare(monkeypatch, resolver_calls=resolver_calls)
    roadmap = json.dumps([{"id": "1.1", "description": "only"}])
    result = _invoke_adopt(
        ["objective", "create", "--json", "--delivery", "stacked", "--roadmap", roadmap],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False and payload["error_type"] == "invalid_roadmap"
    assert "save a one-node objective as a standalone plan instead" in payload["message"]
    assert store.created is False
    assert resolver_calls == []


def test_create_stacked_fan_out_fan_in_dag_accepted(monkeypatch):
    _authed(monkeypatch)
    store = _DeliveryStubStore()
    _stub_prepare(monkeypatch)
    roadmap = json.dumps(
        [
            {"id": "1.1", "description": "root", "depends_on": []},
            {"id": "2.1", "description": "left", "depends_on": ["1.1"]},
            {"id": "2.2", "description": "right", "depends_on": ["1.1"]},
            {"id": "3.1", "description": "join", "depends_on": ["2.1", "2.2"]},
        ]
    )
    result = _invoke_adopt(
        ["objective", "create", "--json", "--delivery", "stacked", "--roadmap", roadmap],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 0, result.output
    assert store.create_kwargs is not None
    assert store.create_kwargs["delivery"] == objective.DeliveryPolicy.STACKED


def test_create_stacked_over_100_nodes_rejected(monkeypatch):
    _authed(monkeypatch)
    store = _DeliveryStubStore()
    roadmap = json.dumps([{"id": f"1.{i}", "description": f"n{i}"} for i in range(1, 102)])
    result = _invoke_adopt(
        ["objective", "create", "--json", "--delivery", "stacked", "--roadmap", roadmap],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "invalid_roadmap" and "at most 100" in payload["message"]
    assert store.created is False


def test_create_stacked_adopt_from_rejected(monkeypatch):
    _authed(monkeypatch)
    store = _DeliveryStubStore()
    resolver_calls: list[Path] = []
    _stub_prepare(monkeypatch, resolver_calls=resolver_calls)
    result = _invoke_adopt(
        [
            "objective",
            "create",
            "--json",
            "--delivery",
            "stacked",
            "--adopt-from",
            "proj-1",
            "--roadmap",
            _two_nodes_roadmap(),
        ],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False and payload["error_type"] == "invalid_input"
    assert "in-place adoption of a stacked objective is deferred" in payload["message"]
    assert store.adopt_kwargs is None and store.created is False
    assert resolver_calls == []


def test_create_stacked_prepare_failure_maps_to_capability_unsupported(monkeypatch):
    from perk.delivery import DeliveryError

    _authed(monkeypatch)
    store = _DeliveryStubStore()
    _stub_prepare(
        monkeypatch,
        error=DeliveryError(
            "This repository cannot take a stacked delivery train against base 'main':\n"
            "- merge-rules: expected squash direct-merge allowed; observed disallowed",
            error_type="capability_unsupported",
        ),
    )
    result = _invoke_adopt(
        [
            "objective",
            "create",
            "--json",
            "--delivery",
            "stacked",
            "--roadmap",
            _two_nodes_roadmap(),
        ],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "capability_unsupported"
    # Every failed check's expected-vs-observed detail rides the message.
    assert "merge-rules" in payload["message"]
    assert "expected squash direct-merge allowed; observed disallowed" in payload["message"]
    assert store.created is False


def test_create_stacked_stores_delivery_and_a_valid_ulid_lineage(monkeypatch):
    from ulid import ULID

    _authed(monkeypatch)
    store = _DeliveryStubStore()
    prepare = _stub_prepare(monkeypatch)
    result = _invoke_adopt(
        [
            "objective",
            "create",
            "--json",
            "--delivery",
            "stacked",
            "--roadmap",
            _two_nodes_roadmap(),
        ],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 0, result.output
    assert store.create_kwargs is not None
    assert store.create_kwargs["delivery"] == objective.DeliveryPolicy.STACKED
    lineage = store.create_kwargs["delivery_lineage"]
    assert str(ULID.from_str(lineage)) == lineage  # a freshly-minted, parseable ULID
    # No explicit --base and no [workflow] base: Prepare receives stored-base intent as None;
    # the façade owns trunk fallback.
    from perk.delivery import PrepareRequest

    assert prepare.requests == [PrepareRequest(kind="authoring", base=None)]


@pytest.mark.parametrize(
    ("extra_args", "config", "expected_base"),
    [
        (["--base", "develop"], None, "develop"),
        ([], '[workflow]\nbase = "release"\n', "release"),
        ([], None, None),
    ],
)
def test_create_stacked_passes_stored_base_intent_to_prepare(
    monkeypatch, extra_args, config, expected_base
):
    from perk.delivery import PrepareRequest

    _authed(monkeypatch)
    store = _DeliveryStubStore()
    prepare = _stub_prepare(monkeypatch)
    result = _invoke_adopt(
        [
            "objective",
            "create",
            "--json",
            "--delivery",
            "stacked",
            "--roadmap",
            _two_nodes_roadmap(),
            *extra_args,
        ],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
        config=config,
    )

    assert result.exit_code == 0, result.output
    assert prepare.requests == [PrepareRequest(kind="authoring", base=expected_base)]
    assert store.create_kwargs is not None
    assert store.create_kwargs["base"] == expected_base


def test_create_stacked_supersede_routes_through_the_transfer_protocol(monkeypatch):
    from perk.delivery import PrepareRequest

    # A stacked successor submits one façade Transfer request after Prepare.
    _authed(monkeypatch)
    store = _DeliveryStubStore(old_header={"delivery": "stacked", "delivery_lineage": "01OLD"})
    prepare = _stub_prepare(monkeypatch)
    result = _invoke_adopt(
        [
            "objective",
            "create",
            "--json",
            "--delivery",
            "stacked",
            "--supersedes",
            "#42",
            "--roadmap",
            _two_nodes_roadmap(),
        ],
        body="# Successor\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 0, result.output
    assert prepare.requests == [PrepareRequest(kind="authoring", base=None)]
    assert store.get_objective_ids == []
    assert store.supersede_kwargs is None
    assert len(prepare.transfer_requests) == 1
    assert prepare.transfer_requests[0].predecessor_id == "42"
    assert prepare.transfer_requests[0].delivery == "stacked"
    payload = json.loads(result.output)
    assert payload["objective"]["id"] == "777"


def test_create_stacked_supersede_prepare_refusal_precedes_every_mutation(monkeypatch):
    from perk.delivery import DeliveryError, PrepareRequest

    _authed(monkeypatch)
    store = _DeliveryStubStore(old_header={"delivery": "stacked", "delivery_lineage": "01OLD"})
    prepare = _stub_prepare(
        monkeypatch,
        error=DeliveryError(
            "This repository cannot take a stacked delivery train against base 'main'",
            error_type="capability_unsupported",
        ),
    )
    result = _invoke_adopt(
        [
            "objective",
            "create",
            "--json",
            "--delivery",
            "stacked",
            "--supersedes",
            "#42",
            "--roadmap",
            _two_nodes_roadmap(),
        ],
        body="# Successor\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )

    assert result.exit_code == 1
    assert prepare.requests == [PrepareRequest(kind="authoring", base=None)]
    payload = json.loads(result.output)
    assert payload["error_type"] == "capability_unsupported"
    assert prepare.transfer_requests == []
    assert store.get_objective_ids == []
    assert store.create_kwargs is None
    assert store.supersede_kwargs is None
    assert store.created is False


@pytest.mark.parametrize("backend_id", ["github", "linear"])
def test_transfer_submits_raw_carry_identity_for_delivery_to_normalize(monkeypatch, backend_id):
    _authed(monkeypatch)
    store = _DeliveryStubStore(old_header={"delivery": "stacked", "delivery_lineage": "01OLD"})
    service = _stub_prepare(monkeypatch)
    monkeypatch.setattr(resolve, "resolve_objective_store_id", lambda _root: backend_id)
    roadmap = json.dumps(
        [
            {"id": "1.1", "description": "first", "pr": "#91", "adopt_issue": "ENG-1"},
            {"id": "1.2", "description": "second", "pr": "#92", "adopt_issue": "ENG-2"},
        ]
    )
    result = _invoke_adopt(
        [
            "objective",
            "create",
            "--json",
            "--delivery",
            "stacked",
            "--supersedes",
            "42",
            "--roadmap",
            roadmap,
        ],
        body="# Successor\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 0, result.output
    assert service.transfer_requests[0].carry_map == (
        ("1.1", "ENG-1"),
        ("1.2", "ENG-2"),
    )


def test_create_stacked_predecessor_routes_even_for_incremental_successor(monkeypatch):
    # D1: a STACKED predecessor routes through the transfer protocol regardless of the
    # successor's (incremental) choice.
    _authed(monkeypatch)
    store = _DeliveryStubStore(old_header={"delivery": "stacked", "delivery_lineage": "01OLD"})
    service = _stub_prepare(monkeypatch)
    result = _invoke_adopt(
        ["objective", "create", "--json", "--supersedes", "42", "--roadmap", _two_nodes_roadmap()],
        body="# Successor\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 0, result.output
    assert store.supersede_kwargs is None
    assert len(service.transfer_requests) == 1
    assert service.transfer_requests[0].delivery == "incremental"


def test_create_supersede_classification_not_found_fails_closed(monkeypatch):
    from perk.delivery import DeliveryError

    _authed(monkeypatch)
    store = _DeliveryStubStore()
    _stub_prepare(
        monkeypatch,
        transfer_error=DeliveryError("Objective 42 not found", error_type="objective_not_found"),
    )
    result = _invoke_adopt(
        ["objective", "create", "--json", "--supersedes", "42", "--roadmap", _two_nodes_roadmap()],
        body="# Successor\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "objective_not_found"
    assert store.supersede_kwargs is None and store.created is False


def test_create_hash_only_supersedes_reaches_authoritative_not_found(monkeypatch):
    from perk.delivery import DeliveryError

    _authed(monkeypatch)
    service = _stub_prepare(
        monkeypatch,
        transfer_error=DeliveryError("Objective  not found", error_type="objective_not_found"),
    )

    result = _invoke_adopt(
        [
            "objective",
            "create",
            "--json",
            "--supersedes",
            "#",
            "--roadmap",
            json.dumps([{"id": "1.1", "description": "work"}]),
        ],
        body="# Successor\n\nprose",
        monkeypatch=monkeypatch,
        store=_AdoptStubStore(),
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "objective_not_found"
    assert payload["message"] == "Objective  not found"
    assert service.transfer_requests[0].predecessor_id == ""


def test_create_supersede_whitespace_scalars_keep_existing_cli_resolution(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setenv("PERK_RUN_ID", "01ENV")
    store = _AdoptStubStore()
    service = _stub_prepare(monkeypatch)

    result = _invoke_adopt(
        [
            "objective",
            "create",
            "--json",
            "--supersedes",
            "42",
            "--title",
            " ",
            "--run-id",
            " ",
            "--base",
            " ",
            "--roadmap",
            json.dumps([{"id": "1.1", "description": "work"}]),
        ],
        body="# Derived title\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )

    assert result.exit_code == 0, result.output
    assert len(service.transfer_requests) == 1
    assert service.transfer_requests[0].title == " "
    assert service.transfer_requests[0].run_id == " "
    assert service.transfer_requests[0].base == " "


def test_create_supersede_classification_junk_policy_fails_closed(monkeypatch):
    from perk.delivery import DeliveryError

    _authed(monkeypatch)
    store = _DeliveryStubStore()
    _stub_prepare(
        monkeypatch,
        transfer_error=DeliveryError(
            "unknown objective delivery policy: 'bogus'",
            error_type="invalid_delivery_policy",
        ),
    )
    result = _invoke_adopt(
        ["objective", "create", "--json", "--supersedes", "42", "--roadmap", _two_nodes_roadmap()],
        body="# Successor\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "invalid_delivery_policy"
    assert store.supersede_kwargs is None and store.created is False


def test_create_supersede_classification_infra_failure_fails_the_save(monkeypatch):
    from perk.delivery import DeliveryError

    _authed(monkeypatch)
    store = _DeliveryStubStore()
    _stub_prepare(
        monkeypatch,
        transfer_error=DeliveryError(
            "objective create failed\nread timed out",
            error_type="github_error",
        ),
    )
    result = _invoke_adopt(
        ["objective", "create", "--json", "--supersedes", "42", "--roadmap", _two_nodes_roadmap()],
        body="# Successor\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "github_error"
    assert store.supersede_kwargs is None and store.created is False


def test_create_supersede_transfer_refusal_maps_the_typed_error(monkeypatch):
    from perk.delivery import DeliveryError

    _authed(monkeypatch)
    store = _DeliveryStubStore(old_header={"delivery": "stacked", "delivery_lineage": "01OLD"})
    _stub_prepare(
        monkeypatch,
        transfer_error=DeliveryError("prefix broken", error_type="prefix_mismatch"),
    )
    result = _invoke_adopt(
        ["objective", "create", "--json", "--supersedes", "42", "--roadmap", _two_nodes_roadmap()],
        body="# Successor\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "prefix_mismatch" and "prefix broken" in payload["message"]


@pytest.mark.parametrize("as_json", (True, False))
def test_transfer_repo_git_failure_reaches_stable_cli_envelopes(monkeypatch, as_json):
    from perk.backends.objective_store import ObjectiveState
    from perk.delivery import Delivery, PrepareResult
    from perk.delivery._fakes import FakeDeliveryGitHub, FakeDeliveryPersistence
    from perk.delivery.observe import RepoDeliveryGit
    from perk.substrate import git as git_mod

    _authed(monkeypatch)
    persistence = FakeDeliveryPersistence(
        objectives={
            "42": ObjectiveState(
                id="42",
                url="u/42",
                title="Old",
                header={},
                nodes=(),
            )
        }
    )

    def fail_worktree_read(*_args, **_kwargs):
        raise git_mod.GitError("adapter worktrees unavailable")

    monkeypatch.setattr(git_mod, "worktree_list", fail_worktree_read)

    def resolve_service(repo_root):
        bound = Delivery(
            persistence=persistence,
            git=RepoDeliveryGit(repo_root),
            github=FakeDeliveryGitHub(),
        )

        class _Service:
            def prepare(self, request):
                assert request.kind == "authoring"
                return PrepareResult(kind="authoring", base="main")

            def transfer(self, request):
                return bound.transfer(request)

        return _Service()

    monkeypatch.setattr(create_cmd, "resolve_delivery", resolve_service)
    args = [
        "objective",
        "create",
        "--supersedes",
        "42",
        "--delivery",
        "stacked",
        "--roadmap",
        _two_nodes_roadmap(),
    ]
    if as_json:
        args.append("--json")
    result = _invoke_adopt(
        args,
        body="# Successor\n\nprose",
        monkeypatch=monkeypatch,
        store=_AdoptStubStore(),
    )

    assert result.exit_code == 1
    if as_json:
        payload = json.loads(result.output)
        assert payload["error_type"] == "git_error"
        assert payload["message"] == "git worktree list failed: adapter worktrees unavailable"
    else:
        assert result.output == "Error: git worktree list failed: adapter worktrees unavailable\n"


def test_create_stacked_dry_run_skips_probes_and_gate_but_validates_bounds(monkeypatch):
    _authed(monkeypatch)
    store = _DeliveryStubStore()

    def _must_not_resolve(*_args, **_kwargs):
        raise AssertionError("--dry-run must not resolve Delivery")

    monkeypatch.setattr(create_cmd, "resolve_delivery", _must_not_resolve)
    # Bounds still validate on a dry run: one node → invalid_roadmap.
    one = json.dumps([{"id": "1.1", "description": "only"}])
    result = _invoke_adopt(
        ["objective", "create", "--json", "--dry-run", "--delivery", "stacked", "--roadmap", one],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "invalid_roadmap"
    # A valid stacked roadmap dry-runs clean without the probes, the gate, or a real write.
    result = _invoke_adopt(
        [
            "objective",
            "create",
            "--json",
            "--dry-run",
            "--delivery",
            "stacked",
            "--roadmap",
            _two_nodes_roadmap(),
        ],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 0, result.output
    assert store.create_kwargs is not None and store.create_kwargs["dry_run"] is True


def test_create_no_delivery_flag_stores_both_none(monkeypatch):
    _authed(monkeypatch)
    store = _DeliveryStubStore()
    result = _invoke_adopt(
        ["objective", "create", "--json", "--roadmap", _two_nodes_roadmap()],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 0, result.output
    assert store.create_kwargs is not None
    assert store.create_kwargs["delivery"] is None
    assert store.create_kwargs["delivery_lineage"] is None


def test_create_explicit_incremental_behaves_like_absent(monkeypatch):
    # An explicit `incremental` is forwarded verbatim to the door and never serialized —
    # byte-identical to no --delivery at all (§8.42's absence rule).
    _authed(monkeypatch)
    store = _DeliveryStubStore()

    def _must_not_resolve(*_args, **_kwargs):
        raise AssertionError("incremental must not resolve Delivery")

    monkeypatch.setattr(create_cmd, "resolve_delivery", _must_not_resolve)
    result = _invoke_adopt(
        [
            "objective",
            "create",
            "--json",
            "--delivery",
            "incremental",
            "--roadmap",
            _two_nodes_roadmap(),
        ],
        body="# Obj\n\nprose",
        monkeypatch=monkeypatch,
        store=store,
    )
    assert result.exit_code == 0, result.output
    assert store.create_kwargs is not None
    assert store.create_kwargs["delivery"] is None
    assert store.create_kwargs["delivery_lineage"] is None


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


def _stub_node_add(monkeypatch, *, node_id="2.3", captured=None):
    def _add(**k):
        if captured is not None:
            captured.update(k)
        return objectives.ObjectiveNodeAdd(
            number=k["number"], node_id=node_id, comment_updated=True, dry_run=False
        )

    monkeypatch.setattr(objectives, "add_objective_node", _add)


def _stub_objective_state(monkeypatch, *, header=None):
    monkeypatch.setattr(
        objectives,
        "get_objective",
        lambda **k: objectives.ObjectiveState(
            number=42, url="u/42", title="Obj", header=header or {"run_id": "01RID"}, nodes=()
        ),
    )


def test_node_add_json(monkeypatch):
    _authed(monkeypatch)
    captured = {}
    _stub_node_add(monkeypatch, captured=captured)
    _stub_objective_state(monkeypatch)
    reopen_calls = []

    def _reopen(**k):
        reopen_calls.append(k)
        return True

    monkeypatch.setattr(plans, "reopen_issue", _reopen)
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
    payload = json.loads(result.stdout)
    assert payload["success"] is True and payload["node"] == "2.3"
    assert payload["comment_updated"] is True and payload["dry_run"] is False
    # The reopen-on-incomplete invariant fired: a non-terminal add converges the objective open.
    assert payload["reopened"] is True and payload["reopen_error"] is None
    assert len(reopen_calls) == 1 and reopen_calls[0]["number"] == 42
    assert captured["phase"] == 2
    assert captured["depends_on"] == ("1.1", "2.1")
    assert captured["status"] is N.PENDING  # default


def test_node_add_human_output_names_the_reopen(monkeypatch):
    _authed(monkeypatch)
    _stub_node_add(monkeypatch)
    _stub_objective_state(monkeypatch)
    monkeypatch.setattr(plans, "reopen_issue", lambda **k: True)
    result = _invoke(["objective", "node-add", "42", "--phase", "1", "--description", "X"])
    assert result.exit_code == 0
    assert "Added node 2.3 on #42" in result.stderr
    assert "Reopened #42 (roadmap incomplete again)" in result.stderr


def test_node_add_superseded_objective_is_not_reopened(monkeypatch):
    # Superseded lineage is exempt: `objective replan` closed it deliberately; resurrecting it
    # would fork the live objective. The skip is policy, not an error (reopen_error stays None).
    _authed(monkeypatch)
    _stub_node_add(monkeypatch)
    _stub_objective_state(monkeypatch, header={"superseded_by": "#77"})
    monkeypatch.setattr(
        plans, "reopen_issue", lambda **k: pytest.fail("reopen must not run on superseded lineage")
    )
    result = _invoke(
        ["objective", "node-add", "42", "--phase", "1", "--description", "X", "--json"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["reopened"] is False and payload["reopen_error"] is None
    assert "superseded by #77; not reopening" in result.stderr


def test_node_add_terminal_status_skips_the_reopen_read(monkeypatch):
    # A --status done/skipped add never triggers a reopen — the guard chain short-circuits
    # before even the get_objective read.
    _authed(monkeypatch)
    _stub_node_add(monkeypatch)
    monkeypatch.setattr(
        objectives, "get_objective", lambda **k: pytest.fail("terminal add must not read")
    )
    result = _invoke(
        [
            "objective",
            "node-add",
            "42",
            "--phase",
            "1",
            "--description",
            "X",
            "--status",
            "done",
            "--json",
        ]
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["reopened"] is False and payload["reopen_error"] is None


def test_node_add_reopen_failure_is_fail_open(monkeypatch):
    # A reopen failure never discards the add result: success stays True, the error is carried
    # on reopen_error and noted on stderr (the exact posture of land's close-on-complete).
    _authed(monkeypatch)
    _stub_node_add(monkeypatch)
    _stub_objective_state(monkeypatch)

    def _boom(**k):
        raise github.GitHubError("reopen exploded")

    monkeypatch.setattr(plans, "reopen_issue", _boom)
    result = _invoke(
        ["objective", "node-add", "42", "--phase", "1", "--description", "X", "--json"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True and payload["node"] == "2.3"
    assert payload["reopened"] is False
    assert "reopen exploded" in payload["reopen_error"]
    assert "objective reopen skipped (non-fatal)" in result.stderr


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
    # The incremental payload stays byte-identical — no stacked build_ready block.
    assert set(payload) == {"success", "error_type", "next_node"}


def _stacked_next_state():
    return objectives.ObjectiveState(
        number=42,
        url="u/42",
        title="Obj",
        header={"delivery": "stacked", "delivery_lineage": "01JB0000000000000000000000"},
        nodes=_nodes(),
    )


def _stacked_next_selection(kind, node=None, *, ready=None, reason=None):
    from perk.cli.commands.objective.shared import StackedSelection

    return StackedSelection(
        kind=kind,
        node=node,
        ready=ready if ready is not None else kind in ("plannable", "in_flight"),
        reason=reason,
        train=None,
    )


def test_next_stacked_payload_carries_the_build_ready_block(monkeypatch):
    # Stacked selection is readiness-derived (contracts.md §8.46): next_node is the helper's
    # plannable candidate and the payload gains the additive build_ready block.
    from perk.cli.commands.objective import next_cmd

    monkeypatch.setattr(objectives, "get_objective", lambda **k: _stacked_next_state())
    monkeypatch.setattr(
        next_cmd,
        "stacked_selection",
        lambda *_a: _stacked_next_selection("plannable", _nodes()[1]),
    )
    result = _invoke(["objective", "next", "42", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["next_node"]["id"] == "1.2"
    assert payload["build_ready"] == {"ready": True, "reason": None, "blockers": []}


def test_next_stacked_build_blocked_constrains_next_node(monkeypatch):
    from perk.cli.commands.objective import next_cmd

    monkeypatch.setattr(objectives, "get_objective", lambda **k: _stacked_next_state())
    monkeypatch.setattr(
        next_cmd,
        "stacked_selection",
        lambda *_a: _stacked_next_selection("build_blocked", reason="[x] y"),
    )
    result = _invoke(["objective", "next", "42", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["next_node"] is None
    assert payload["build_ready"] == {"ready": False, "reason": "[x] y", "blockers": []}


def test_next_stacked_build_blocked_human_line(monkeypatch):
    from perk.cli.commands.objective import next_cmd

    monkeypatch.setattr(objectives, "get_objective", lambda **k: _stacked_next_state())
    monkeypatch.setattr(
        next_cmd,
        "stacked_selection",
        lambda *_a: _stacked_next_selection("build_blocked", reason="[x] y"),
    )
    result = _invoke(["objective", "next", "42"])
    assert result.exit_code == 0
    assert "build blocked: [x] y" in result.output


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

from perk.backends import objective_store  # noqa: E402


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


# The doctor command's coverage (two-part report: manifest drift + the DeliveryTrain
# diagnosis, the repair state machine, redirects, and the exit-code table) lives in
# tests/test_objective_doctor_cmd.py.
