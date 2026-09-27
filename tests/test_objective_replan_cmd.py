"""`perk objective replan <N>`: the superseding re-author cold door.

The objective store, issue backend, and `launch.launch_stage` are stubbed (no GitHub, no
`exec pi`), mirroring test_from_cmd.py / test_replan_cmd.py. Asserts the dry-run materialization,
the fresh-run-id + `supersedes` handoff threading, and the refusals.
"""

import contextlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from perk import github, objective
from perk.backends import engagement, resolve
from perk.backends.objective_store import AdoptableObjectiveSource, ObjectiveState
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

    def __init__(
        self,
        *,
        state: ObjectiveState | None,
        raise_engagement: bool = False,
        sources: dict[str, AdoptableObjectiveSource] | None = None,
        comments: tuple[engagement.EngagementComment, ...] = (),
    ) -> None:
        self._state = state
        self._raise_engagement = raise_engagement
        self._sources = sources
        self._comments = comments
        self.source_calls: list[str] = []

    def get_objective(self, *, objective_id: str):
        return self._state

    def read_comments(self, *, objective_id: str):
        if self._raise_engagement:
            from perk.backends.objective_store import ObjectiveStoreError

            raise ObjectiveStoreError("boom")
        return self._comments

    def read_description_edits(self, *, objective_id: str):
        return ()

    def read_node_engagement(self, *, objective_id: str, node_id: str):
        return engagement.EMPTY_NODE_ENGAGEMENT

    def read_objective_source(self, *, source_id: str):
        self.source_calls.append(source_id)
        # With a `sources` map the fake answers ONLY from it (a miss is `None` — the subject's
        # prose read then falls back to the title); without one it returns the default
        # old-objective prose every existing test relies on. Keys resolve the way the GitHub
        # store resolves ids (`int(id.removeprefix("#"))`), so `042` / `+42` reach source 42.
        if self._sources is not None:
            key = source_id.removeprefix("#")
            with contextlib.suppress(ValueError):
                key = str(int(key))
            return self._sources.get(key)
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

    state = _state(_UNFINISHED_NODES)
    store = _FakeStore(state=state)
    store.backend_id = "linear"
    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: store)
    service = _PrepareService(result=_replan_result(state))
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


# ----------------------------------------------------------------- `--from` guidance (§8.32)

_STEER = "Drop phase 3 and pivot the remaining work toward the gizmo rewrite."


def _write_steer(d: str, body: str = _STEER) -> Path:
    path = Path(d) / "steer.md"
    path.write_text(body, encoding="utf-8")
    return path


def _boom_launch(**_k) -> None:
    raise AssertionError("a refused --from must never launch")


def test_from_file_appends_guidance_block_and_seed_arm(monkeypatch, unborn_git_repo_factory):
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    _patch(monkeypatch, store)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        steer = _write_steer(d)
        result = runner.invoke(cli, ["objective", "replan", "42", "--from", "steer.md", "--json"])
        assert result.exit_code == 0, result.output
        text = (Path(d) / _SCRATCH_REL).read_text(encoding="utf-8")
    assert "<untrusted_replan_guidance>" in text
    assert f"from: file {steer.resolve()}" in text
    assert _STEER in text
    assert text.index("</untrusted_objective_unfinished_nodes>") < text.index(
        "<untrusted_replan_guidance>"
    )
    assert "<untrusted_replan_guidance>" in (launched["prompt"] or "")
    # Guidance only: the supersede handoff is unchanged, a fresh run_id is minted, and the file
    # arm does no network read.
    assert launched["handoff_extra"] == {"supersedes": "42"}
    assert launched["run_id_override"] is None
    assert "reading guidance source" not in result.stderr


def test_from_source_reads_store_and_narrates(monkeypatch, unborn_git_repo_factory):
    source = AdoptableObjectiveSource(
        id="99", url="u/99", title="Steer it", prose="Pivot the remaining work to X."
    )
    store = _FakeStore(state=_state(_UNFINISHED_NODES), sources={"99": source})
    _patch(monkeypatch, store)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42", "--from", "99", "--json"])
        assert result.exit_code == 0, result.output
        text = (Path(d) / _SCRATCH_REL).read_text(encoding="utf-8")
        dry = runner.invoke(
            cli, ["objective", "replan", "42", "--from", "99", "--dry-run", "--json"]
        )
        assert dry.exit_code == 0, dry.output
    assert "from: source 99 — Steer it (u/99)" in text
    assert "Pivot the remaining work to X." in text
    assert "reading guidance source 99" in result.stderr
    assert "read guidance source 99" in result.stderr
    assert launched["handoff_extra"] == {"supersedes": "42"}
    payload = json.loads(dry.stdout)
    assert payload["from"] == "99" and payload["from_kind"] == "source"


def test_from_source_strips_hash_prefix(monkeypatch, unborn_git_repo_factory):
    source = AdoptableObjectiveSource(id="99", url="u/99", title="Steer it", prose="Steer text.")
    store = _FakeStore(state=_state(_UNFINISHED_NODES), sources={"99": source})
    _patch(monkeypatch, store)
    monkeypatch.setattr(launch, "launch_stage", _boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(
            cli, ["objective", "replan", "42", "--from", "#99", "--dry-run", "--json"]
        )
        assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["from"] == "99"
    assert "99" in store.source_calls


def test_from_file_dry_run_json_kind(monkeypatch, unborn_git_repo_factory):
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    _patch(monkeypatch, store)
    monkeypatch.setattr(launch, "launch_stage", _boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        _write_steer(d)
        result = runner.invoke(
            cli, ["objective", "replan", "42", "--from", "steer.md", "--dry-run", "--json"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["from_kind"] == "file"
        assert Path(payload["from"]).resolve() == (Path(d) / "steer.md").resolve()
    # The guidance keys are appended before `dry_run`, which stays the last key.
    assert list(payload)[-3:] == ["from", "from_kind", "dry_run"]


def test_from_missing_source_refuses_guidance_not_found(monkeypatch, unborn_git_repo_factory):
    store = _FakeStore(state=_state(_UNFINISHED_NODES), sources={})
    service = _patch(monkeypatch, store)
    monkeypatch.setattr(launch, "launch_stage", _boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42", "--from", "77", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert not (Path(d) / _SCRATCH_REL).exists()
    assert payload["error_type"] == "guidance_not_found"
    assert "77" in payload["message"]
    # The source read precedes the objective lookup.
    assert service.requests == []


def test_from_bodiless_source_refuses_guidance_empty(monkeypatch, unborn_git_repo_factory):
    source = AdoptableObjectiveSource(id="99", url="u/99", title="Blank", prose="   ")
    store = _FakeStore(state=_state(_UNFINISHED_NODES), sources={"99": source})
    _patch(monkeypatch, store)
    monkeypatch.setattr(launch, "launch_stage", _boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42", "--from", "99", "--json"])
        assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "guidance_empty"


def test_from_empty_file_refuses_seed_file_error(monkeypatch, unborn_git_repo_factory):
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    _patch(monkeypatch, store)
    monkeypatch.setattr(launch, "launch_stage", _boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        _write_steer(d, body="")
        result = runner.invoke(cli, ["objective", "replan", "42", "--from", "steer.md", "--json"])
        assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "seed_file_error"


def test_from_blank_refuses_invalid_input(monkeypatch, unborn_git_repo_factory):
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    _patch(monkeypatch, store)
    monkeypatch.setattr(launch, "launch_stage", _boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42", "--from", "  ", "--json"])
        assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "invalid_input"


@pytest.mark.parametrize("alias", ["42", "#42"])
def test_from_aliasing_the_objective_refuses_invalid_input(
    monkeypatch, unborn_git_repo_factory, alias
):
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    service = _patch(monkeypatch, store)
    monkeypatch.setattr(launch, "launch_stage", _boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        # A real (non-dry-run) launch: the refusal must precede even the banner.
        result = runner.invoke(cli, ["objective", "replan", "42", "--from", alias, "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert not (Path(d) / _SCRATCH_REL).exists()
    assert payload["error_type"] == "invalid_input"
    assert "#42" in payload["message"]
    assert store.source_calls == []  # never read as guidance (nor as the subject's prose)
    assert service.requests == []
    assert "skills \u00b7" not in result.stderr


@pytest.mark.parametrize(
    ("subject", "alias"),
    [("42", "042"), ("42", "+42"), ("042", "42"), ("#042", "#42")],
)
def test_from_backend_equivalent_objective_spelling_refuses_invalid_input(
    monkeypatch, unborn_git_repo_factory, subject, alias
):
    # The instant local check compares cleaned spellings only; the store resolves `042` / `+42`
    # to the SAME issue the save would close. The backend-canonical check (the guidance source's
    # id vs Prepare's objective id) refuses before the scratch write and launch.
    subject_src = AdoptableObjectiveSource(id="42", url="u/42", title="Old objective", prose="Old.")
    store = _FakeStore(state=_state(_UNFINISHED_NODES), sources={"42": subject_src})
    service = _patch(monkeypatch, store)
    monkeypatch.setattr(launch, "launch_stage", _boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", subject, "--from", alias, "--json"])
        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert not any((Path(d) / ".perk/workflow/scratch").glob("objective-replan-*"))
    assert payload["error_type"] == "invalid_input"
    assert "#42" in payload["message"]
    # Only the read-only Prepare snapshot ran — it is where the subject's canonical id comes from.
    assert len(service.requests) == 1


def test_from_aliasing_the_replan_scratch_refuses_invalid_input(
    monkeypatch, unborn_git_repo_factory
):
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    service = _patch(monkeypatch, store)
    monkeypatch.setattr(launch, "launch_stage", _boom_launch)
    sentinel = "SENTINEL: a prior replan's scratch, which must survive the refusal.\n"
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        scratch = Path(d) / _SCRATCH_REL
        scratch.parent.mkdir(parents=True, exist_ok=True)
        scratch.write_text(sentinel, encoding="utf-8")
        result = runner.invoke(
            cli, ["objective", "replan", "42", "--from", _SCRATCH_REL, "--dry-run", "--json"]
        )
        assert result.exit_code == 1
        assert scratch.read_text(encoding="utf-8") == sentinel  # refusal precedes the write
    assert json.loads(result.stdout)["error_type"] == "invalid_input"
    assert service.requests == []


def test_from_another_objective_is_accepted_as_data(monkeypatch, unborn_git_repo_factory):
    sibling = AdoptableObjectiveSource(
        id="43", url="u/43", title="Sibling", prose="Sibling prose.", has_objective_header=True
    )
    store = _FakeStore(state=_state(_UNFINISHED_NODES), sources={"43": sibling})
    _patch(monkeypatch, store)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "replan", "42", "--from", "43", "--json"])
        assert result.exit_code == 0, result.output
        text = (Path(d) / _SCRATCH_REL).read_text(encoding="utf-8")
    assert "from: source 43 — Sibling (u/43)" in text
    assert "Sibling prose." in text
    assert launched["handoff_extra"] == {"supersedes": "42"}


def test_from_guidance_precedes_stacked_facts(monkeypatch, unborn_git_repo_factory):
    nodes = [_node("1.1", objective.NodeStatus.IN_PROGRESS, pr="#12")]
    comment = engagement.EngagementComment(
        id="c1",
        body="Please reconsider the gizmo milestone.",
        created_at="2024-01-01T00:00:00Z",
        edited_at=None,
        author=engagement.EngagementAuthor(kind="human", display_name="alice", id="u1"),
    )
    store = _FakeStore(state=_stacked_state(nodes), comments=(comment,))
    service = _patch(monkeypatch, store)
    _configure_stacked(service, store, claimed=(_claimed_layer("1.1", "12", 34),))
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        _write_steer(d)
        result = runner.invoke(cli, ["objective", "replan", "42", "--from", "steer.md", "--json"])
        assert result.exit_code == 0, result.output
        text = (Path(d) / _SCRATCH_REL).read_text(encoding="utf-8")
    # Steer first, enforced constraints next, engagement last.
    assert text.index("</untrusted_replan_guidance>") < text.index("<stacked_delivery_facts>")
    assert text.index("</stacked_delivery_facts>") < text.index("<untrusted_objective_engagement>")
    assert text.rstrip().endswith("</untrusted_objective_engagement>")


def test_without_from_is_byte_identical(monkeypatch, unborn_git_repo_factory):
    store = _FakeStore(state=_state(_UNFINISHED_NODES))
    _patch(monkeypatch, store)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        dry = runner.invoke(cli, ["objective", "replan", "42", "--dry-run", "--json"])
        assert dry.exit_code == 0, dry.output
        result = runner.invoke(cli, ["objective", "replan", "42", "--json"])
        assert result.exit_code == 0, result.output
        text = (Path(d) / _SCRATCH_REL).read_text(encoding="utf-8")
    payload = json.loads(dry.stdout)
    assert list(payload) == [
        "success",
        "error_type",
        "objective",
        "supersedes",
        "scratch_path",
        "unfinished_nodes",
        "dry_run",
    ]
    assert "<untrusted_replan_guidance>" not in text
    assert "untrusted_replan_guidance" not in (launched["prompt"] or "")
    assert "reading guidance source" not in dry.stderr + result.stderr
    assert launched["handoff_extra"] == {"supersedes": "42"}
