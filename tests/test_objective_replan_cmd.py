"""`perk objective replan <N>`: the superseding re-author cold door.

The objective store, issue backend, and `launch.launch_stage` are stubbed (no GitHub, no
`exec pi`), mirroring test_from_cmd.py / test_replan_cmd.py. Asserts the dry-run materialization,
the fresh-run-id + `supersedes` handoff threading, and the refusals.
"""

import json
from pathlib import Path

from click.testing import CliRunner

from perk import github, objective
from perk.backends import resolve
from perk.backends.objective_store import ObjectiveState
from perk.cli.cli import cli
from perk.cli.commands.objective import replan_cmd
from perk.delivery import DeliveryError, PrepareRequest, PrepareResult
from perk.run import launch

_SCRATCH_REL = ".perk/workflow/scratch/objective-replan-42.md"


def _git_init(path, factory) -> None:
    factory(path)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _node(node_id: str, status: objective.NodeStatus, pr: str | None = None):
    return objective.ObjectiveNode(id=node_id, description=f"node {node_id}", status=status, pr=pr)


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


class _PrepareService:
    """Dumb Delivery spy returning the configured façade result or error."""

    def __init__(
        self,
        *,
        result: PrepareResult | None = None,
        error: DeliveryError | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.requests: list[PrepareRequest] = []

    def prepare(self, request: PrepareRequest) -> PrepareResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def _replan_result(state: ObjectiveState) -> PrepareResult:
    context = PrepareResult.ReplanContext(
        objective_id=state.id,
        objective_url=state.url,
        objective_title=state.title,
        nodes=state.nodes,
        delivery="incremental",
        base=None,
        delivery_lineage=None,
        claimed=(),
        open_pr_plans=(),
    )
    return PrepareResult(kind="replan", replan=context)


def _patch(
    monkeypatch,
    store: _FakeStore,
    *,
    result: PrepareResult | None = None,
    error: DeliveryError | None = None,
) -> _PrepareService:
    _authed(monkeypatch)
    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: store)
    if result is None and error is None:
        assert store._state is not None
        result = _replan_result(store._state)
    service = _PrepareService(result=result, error=error)
    monkeypatch.setattr(replan_cmd, "resolve_delivery", lambda _root: service)
    return service


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


def test_dry_run_json_materializes_and_does_not_launch(monkeypatch, unborn_git_repo_factory):
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    service = _patch(monkeypatch, store)

    def boom_launch(**k):
        raise AssertionError("--dry-run must not launch")

    monkeypatch.setattr(launch, "launch_stage", boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
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
        assert service.requests == [PrepareRequest(kind="replan", objective_id="42")]


def test_linear_backend_skips_the_github_auth_gate(monkeypatch, unborn_git_repo_factory):
    # The auth gate is backend-conditional: a Linear-configured repo reaches store resolution
    # without ever probing `gh` auth (Linear auth is enforced at store construction).
    def no_auth_probe():
        raise AssertionError("check_auth must not run on the Linear arm")

    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    store.backend_id = "linear"
    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: store)
    service = _PrepareService(result=_replan_result(store._state))
    monkeypatch.setattr(replan_cmd, "resolve_delivery", lambda _root: service)
    monkeypatch.setattr(github, "check_auth", no_auth_probe)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        perk_dir = Path(d) / ".perk"
        perk_dir.mkdir(exist_ok=True)
        (perk_dir / "config.toml").write_text('[issues]\nbackend = "linear"\n', encoding="utf-8")
        result = runner.invoke(cli, ["objective", "replan", "42", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["success"] is True


def test_github_backend_still_refuses_unauthed(monkeypatch, unborn_git_repo_factory):
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    _patch(monkeypatch, store)
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(False, None, (), "not logged in")
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42", "--dry-run", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["success"] is False and payload["error_type"] == "github_unauthed"


def test_real_launch_threads_supersedes_handoff_and_fresh_run_id(
    monkeypatch, unborn_git_repo_factory
):
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    _patch(monkeypatch, store)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42", "--json"])
        assert result.exit_code == 0, result.output
        assert "looking up objective #42" in result.stderr  # narrates the backend lookup wait
        # The gather step resolves with the materialized artifact name.
        assert "\u2713 materialized objective #42 \u2192 objective-replan-42.md" in result.stderr
    assert launched["stage"] == "objective-author"  # borrows the objective-author stage
    assert launched["handoff_extra"] == {"supersedes": "42"}
    assert launched["run_id_override"] is None  # FRESH run_id minted (net-new objective)
    assert launched["binding_trigger"] == "command:objective-replan"
    prompt = launched["prompt"] or ""
    assert _SCRATCH_REL in prompt
    # The skill pointer is binding-delivered (command:objective-replan), never hardcoded.
    assert "perk-objective-replan" not in prompt
    # Review-first seed: approval auto-saves the supersession — no direct-save ending.
    assert "objective_save" not in prompt  # `/objective-save` (hyphen) doesn't match
    assert "plan_review" in prompt
    assert "CLOSES #42" in prompt
    # The replan seed RE-ASKS the delivery policy pre-publication (§8.45).
    assert "Re-ask the delivery choice" in prompt
    assert "ask_user_question" in prompt
    assert "incremental as the first, recommended option" in prompt


def test_real_launch_banner_precedes_lookup(monkeypatch, unborn_git_repo_factory):
    """A real local launch heads stderr with the banner BEFORE the `looking up #X` narration."""
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    _patch(monkeypatch, store)
    _stub_launch(monkeypatch, {})
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42"])
        assert result.exit_code == 0, result.output
        err = result.stderr
        assert err.index("skills \u00b7") < err.index("looking up")


def test_dry_run_emits_no_banner(monkeypatch, unborn_git_repo_factory):
    """The banner is gated off on `--dry-run` (the preview path owns the output)."""
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    _patch(monkeypatch, store)
    monkeypatch.setattr(launch, "launch_stage", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        assert "skills \u00b7" not in result.stderr


def test_strips_hash_prefix(monkeypatch, unborn_git_repo_factory):
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    _patch(monkeypatch, store)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "#42", "--json"])
        assert result.exit_code == 0, result.output
    assert launched["handoff_extra"] == {"supersedes": "42"}


def test_refuses_not_found(monkeypatch, unborn_git_repo_factory):
    store = _FakeStore(state=None)
    _patch(
        monkeypatch,
        store,
        error=DeliveryError("Objective 42 not found", error_type="objective_not_found"),
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42", "--json"])
        assert result.exit_code == 1
        # Parse stdout: the real-path `looking up #42` line is on stderr (combined .output).
        assert json.loads(result.stdout)["error_type"] == "objective_not_found"


def test_refuses_already_superseded(monkeypatch, unborn_git_repo_factory):
    store = _FakeStore(
        state=_state(_UNFINISHED_NODES, header={"run_id": "01OLD", "superseded_by": "99"})
    )
    _patch(
        monkeypatch,
        store,
        error=DeliveryError(
            "Objective 42 is already superseded by 99; replan its successor instead.",
            error_type="objective_not_open",
        ),
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "objective_not_open"


def test_refuses_non_open_github_objective(monkeypatch, unborn_git_repo_factory):
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    _patch(
        monkeypatch,
        store,
        error=DeliveryError(
            "Objective 42 is not open (state=closed)",
            error_type="objective_not_open",
        ),
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "objective_not_open"


def test_rejects_remote(monkeypatch, unborn_git_repo_factory):
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    _patch(monkeypatch, store)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42", "--remote", "runner", "--json"])
        assert result.exit_code == 1


def test_engagement_read_failure_is_fail_soft(monkeypatch, unborn_git_repo_factory):
    store = _FakeStore(state=_state(_UNFINISHED_NODES), raise_engagement=True)
    _patch(monkeypatch, store)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42", "--json"])
        assert result.exit_code == 0, result.output
        text = (Path(d) / _SCRATCH_REL).read_text(encoding="utf-8")
    assert "<untrusted_objective_engagement>" not in text


# ----------------------------------------------------------------- stacked predecessors (§8.53)


def _stacked_state(nodes) -> ObjectiveState:
    return _state(
        nodes, header={"run_id": "01OLD", "delivery": "stacked", "delivery_lineage": "01L"}
    )


def _configure_stacked(
    service: _PrepareService,
    store: _FakeStore,
    *,
    unresolved=(),
    claimed=(),
    open_layers=(),
    blockers=(),
) -> None:
    """Configure the one replan Prepare result/error consumed by the command."""
    if unresolved:
        op = unresolved[0]
        if op.kind.value == "transfer":
            service.error = DeliveryError(
                f"An interrupted replan transfer (operation {op.operation_id}) is unresolved "
                "on objective 42 — conclude it with `perk objective stack recover 42` "
                "before replanning.",
                error_type="transfer_incomplete",
            )
        else:
            service.error = DeliveryError(
                f"Operation {op.operation_id} ({op.kind.value}) is unresolved on objective "
                "42 — conclude it via `perk objective stack recover 42` or the owning "
                "command before replanning.",
                error_type="unresolved_operation",
            )
        return
    if blockers:
        blocker = blockers[0]
        service.error = DeliveryError(
            f"[{blocker.code}] {blocker.message}",
            error_type="claimed_prefix_malformed",
        )
        return
    state = store._state
    assert state is not None
    context = PrepareResult.ReplanContext(
        objective_id=state.id,
        objective_url=state.url,
        objective_title=state.title,
        nodes=state.nodes,
        delivery="stacked",
        base="main",
        delivery_lineage="01L",
        claimed=tuple(
            PrepareResult.ReplanClaim(
                node_id=layer.node_id,
                plan_id=layer.plan_id,
                branch=layer.branch,
                pr_number=layer.pr_number,
            )
            for layer in claimed
        ),
        open_pr_plans=tuple((layer.plan_id, layer.pr_number) for layer in open_layers),
    )
    service.result = PrepareResult(kind="replan", replan=context)


def _claimed_layer(node_id: str, plan_id: str, pr_number: int):
    from perk.delivery import sync as sync_mod
    from perk.delivery.train import LayerWriter

    return sync_mod.ClaimedLayer(
        node_id=node_id,
        plan_id=plan_id,
        branch=f"plan-{plan_id}",
        pr_number=pr_number,
        parent_checkpoint_sha="a" * 40,
        published_head_sha="b" * 40,
        writer=LayerWriter.FREE,
    )


def _open_layer(plan_id: str, pr_number: int):
    from types import SimpleNamespace

    from perk.delivery.train import LayerPr

    return SimpleNamespace(plan_id=plan_id, pr_number=pr_number, pr=LayerPr.READY)


def test_stacked_published_scratch_carries_prefix_open_prs_and_immutability(
    monkeypatch, unborn_git_repo_factory
):
    nodes = [_node("1.1", objective.NodeStatus.IN_PROGRESS, pr="#12")]
    store = _FakeStore(state=_stacked_state(nodes))
    service = _patch(monkeypatch, store)
    _configure_stacked(
        service,
        store,
        claimed=(_claimed_layer("1.1", "12", 34),),
        open_layers=(_open_layer("12", 34), _open_layer("14", 36)),
    )
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42", "--json"])
        assert result.exit_code == 0, result.output
        text = (Path(d) / _SCRATCH_REL).read_text(encoding="utf-8")
    assert "<stacked_delivery_facts>" in text
    assert "published layers (checkpoint-claimed): 1" in text
    assert "train lineage: 01L" in text
    # The claimed prefix rides as a MUST-carry ordered listing.
    assert "MUST carry these plans in exactly this order" in text
    assert "1. node 1.1  plan #12  branch plan-12  PR #34" in text
    # The D5 mandatory-carry open-PR plans.
    assert "Mandatory-carry plans with OPEN PRs" in text
    assert "- plan #14 (PR #36)" in text
    # The immutability facts + the seed's published arm (no delivery re-ask).
    assert "IMMUTABLE after publication" in text and "delivery=stacked" in text
    prompt = launched["prompt"] or ""
    assert "the delivery policy is IMMUTABLE" in prompt
    assert "do NOT re-ask the delivery choice" in prompt
    assert "Re-ask the delivery choice:" not in prompt


def test_stacked_prepublication_keeps_the_delivery_reask(monkeypatch, unborn_git_repo_factory):
    nodes = [_node("1.1", objective.NodeStatus.PENDING, pr="#12")]
    store = _FakeStore(state=_stacked_state(nodes))
    service = _patch(monkeypatch, store)
    _configure_stacked(service, store, claimed=(), open_layers=(_open_layer("12", 34),))
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42", "--json"])
        assert result.exit_code == 0, result.output
        text = (Path(d) / _SCRATCH_REL).read_text(encoding="utf-8")
    assert "Nothing is published yet" in text
    assert "IMMUTABLE after publication" not in text
    assert "- plan #12 (PR #34)" in text  # open PRs stay mandatory-carry pre-publication
    prompt = launched["prompt"] or ""
    assert "Re-ask the delivery choice" in prompt
    assert "converting the policy refuses while any carried plan has an OPEN PR" in prompt


def test_stacked_door_refuses_structurally_blocked_train_without_launching(
    monkeypatch, unborn_git_repo_factory
):
    from types import SimpleNamespace

    store = _FakeStore(state=_stacked_state([_node("1.1", objective.NodeStatus.PENDING)]))
    service = _patch(monkeypatch, store)
    blocker = SimpleNamespace(
        code="wrong_owner",
        message="plan 12 belongs to objective 99, expected 42",
    )
    _configure_stacked(service, store, blockers=(blocker,))
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
    assert payload["error_type"] == "claimed_prefix_malformed"
    assert "wrong_owner" in payload["message"]
    assert launched == {}


def test_stacked_door_refuses_unresolved_transfer(monkeypatch, unborn_git_repo_factory):
    from types import SimpleNamespace

    from perk.delivery.journal import OperationKind

    store = _FakeStore(state=_stacked_state([_node("1.1", objective.NodeStatus.PENDING)]))
    service = _patch(monkeypatch, store)
    op = SimpleNamespace(kind=OperationKind.TRANSFER, operation_id="01OPTRANSFER")
    _configure_stacked(service, store, unresolved=(op,))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
    assert payload["error_type"] == "transfer_incomplete"
    assert "perk objective stack recover 42" in payload["message"]  # names the PREDECESSOR


def test_stacked_door_refuses_other_unresolved_operation(monkeypatch, unborn_git_repo_factory):
    from types import SimpleNamespace

    from perk.delivery.journal import OperationKind

    store = _FakeStore(state=_stacked_state([_node("1.1", objective.NodeStatus.PENDING)]))
    service = _patch(monkeypatch, store)
    op = SimpleNamespace(kind=OperationKind.PUBLISH, operation_id="01OPPUBLISH")
    _configure_stacked(service, store, unresolved=(op,))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
    assert payload["error_type"] == "unresolved_operation"
    assert "01OPPUBLISH" in payload["message"] and "publish" in payload["message"]


def test_junk_delivery_policy_refuses_fail_closed(monkeypatch, unborn_git_repo_factory):
    store = _FakeStore(
        state=_state([_node("1.1", objective.NodeStatus.PENDING)], header={"delivery": "bogus"})
    )
    _patch(
        monkeypatch,
        store,
        error=DeliveryError(
            "unknown objective delivery policy: 'bogus'",
            error_type="invalid_delivery_policy",
        ),
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "invalid_delivery_policy"
