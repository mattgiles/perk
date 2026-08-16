import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from perk import github, plan
from perk.backends.github import plans
from perk.backends.issue_backend import IssueBackendError, PlanHeaderUpdate
from perk.backends.linear import agent as linear_agent
from perk.cli.cli import cli
from perk.cli.commands.pr import submit_cmd
from perk.delivery import observe as delivery_observe
from perk.state import cache
from perk.substrate import git

_REF = {
    "provider": "github",
    "pr_id": "7",
    "url": "https://gh/o/r/issues/7",
    "labels": ["perk:plan"],
    "objective_id": None,
}


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


_CLEAN_PROBE = git.MergeProbe(determined=True, mergeable=True, conflicts=())


def _stub_gh(
    monkeypatch,
    *,
    existed: bool = False,
    plan_body: str | None = None,
    probe: git.MergeProbe | None = _CLEAN_PROBE,
    state: str = "OPEN",
    reopen_fails: bool = False,
) -> dict[str, object]:
    """Stub the whole submit gateway path; record what the worker did.

    ``probe`` stubs the local merge-conflict probe: a ``MergeProbe`` is returned verbatim;
    ``None`` makes the probe raise ``GitError`` (the fail-open path). The probe call is recorded.
    ``state`` sets the reused PR's normalized state (OPEN | CLOSED | MERGED — the non-OPEN reuse
    guard); ``reopen_fails`` makes the ``reopen_pr`` stub raise ``GitHubError`` (the loud-fail arm).
    """
    calls: dict[str, object] = {
        "pushed": False,
        "push_kwargs": None,
        "header": None,
        "pr_body": None,
        "probed": False,
        "reopened": None,
    }
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **k: plans.PlanState(number=7, url="u/7", title="My Feature", header={}, pr=None),
    )
    monkeypatch.setattr(plans, "get_plan_body", lambda **k: plan_body)
    monkeypatch.setattr(github, "default_branch", lambda root: "main")
    monkeypatch.setattr(
        github,
        "create_pr",
        lambda **k: github.PullRequest(
            number=42, url="u/pr/42", is_draft=True, state=state, existed=existed
        ),
    )

    def _reopen(**k):
        calls["reopened"] = k["number"]
        if reopen_fails:
            raise github.GitHubError("reopen boom")

    monkeypatch.setattr(github, "reopen_pr", _reopen)

    def _update(**k):
        calls["header"] = k["fields"]
        return plans.PlanHeaderUpdate(fields_updated=tuple(k["fields"]), dry_run=False)

    def _update_body(**k):
        calls["pr_body"] = k["body"]
        return github.PrBodyUpdate(number=k["number"], dry_run=False)

    def _push(*a, **k):
        calls["pushed"] = True
        calls["push_kwargs"] = k

    def _probe(*_a, **_k):
        calls["probed"] = True
        if probe is None:
            raise git.GitError("probe boom")
        return probe

    monkeypatch.setattr(plans, "update_plan_header", _update)
    monkeypatch.setattr(github, "update_pr_body", _update_body)
    monkeypatch.setattr(git, "push", _push)
    monkeypatch.setattr(git, "is_dirty", lambda root: False)
    monkeypatch.setattr(git, "detect_merge_conflicts", _probe)
    return calls


def _run(monkeypatch, args, *, write_ref=True):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        if write_ref:
            cache.write_plan_ref(Path(d), plan.PlanRefModel.model_validate(_REF).to_domain())
        return runner.invoke(cli, args)


def test_dry_run_is_offline_and_well_formed(monkeypatch):
    # No gh stubs at all — a dry run must not shell anything.
    result = _run(monkeypatch, ["pr", "submit", "--dry-run", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["dry_run"] is True
    assert data["branch"] == "plan-7" and data["issue"] == "7"
    assert data["pr"]["number"] == 0  # stub (no PR opened on a dry run)
    assert data["plan_header"]["fields_updated"] == ["branch", "pr", "lifecycle_stage"]
    # Dry run stays fully offline: no probe, mergeability unknown.
    assert data["base"] == "" and data["mergeable"] is None and data["conflicts"] == []


def test_no_plan_ref_exits_1(monkeypatch):
    result = _run(monkeypatch, ["pr", "submit", "--dry-run", "--json"], write_ref=False)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_plan_ref"


def test_not_a_repo_exits_2(monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        result = runner.invoke(cli, ["pr", "submit", "--dry-run", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"


def test_real_submit_opens_pr_and_updates_header(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch)
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["pr"]["number"] == 42 and data["pr"]["existed"] is False
    assert calls["pushed"] is True
    assert calls["header"] == {"branch": "plan-7", "pr": "42", "lifecycle_stage": "impl"}
    # The footer carries the PR number (42), not the issue number (7) — the create-then-update fix.
    assert "`gh pr checkout 42`" in str(calls["pr_body"])
    assert "`gh pr checkout 7`" not in str(calls["pr_body"])
    assert data["pr_checked"] is True and data["plan_embedded"] is False
    # Mergeability surfaced: clean probe -> base/mergeable/conflicts present.
    assert data["base"] == "main"
    assert data["mergeable"] is True and data["conflicts"] == []
    assert calls["probed"] is True


def test_submit_targets_pinned_base_from_plan_ref(monkeypatch):
    # A plan-ref carrying `base` retargets create_pr + the mergeability probe (over the
    # GitHub default branch).
    _authed(monkeypatch)
    captured: dict[str, object] = {}
    _stub_gh(monkeypatch)
    monkeypatch.setattr(
        github,
        "create_pr",
        lambda **k: (
            captured.update(create_base=k["base"])
            or github.PullRequest(
                number=42, url="u/pr/42", is_draft=True, state="OPEN", existed=False
            )
        ),
    )

    def _probe(_root, *, base, branch_ref):
        captured["probe_base"] = base
        return _CLEAN_PROBE

    monkeypatch.setattr(git, "detect_merge_conflicts", _probe)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(
            Path(d), plan.PlanRefModel.model_validate({**_REF, "base": "develop"}).to_domain()
        )
        result = runner.invoke(cli, ["pr", "submit", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["base"] == "develop"
    assert captured["create_base"] == "develop"
    assert captured["probe_base"] == "develop"


def test_submit_falls_back_to_header_then_default_base(monkeypatch):
    # With no plan-ref base, submit resolves base from the plan-header, else default_branch.
    _authed(monkeypatch)
    captured: dict[str, object] = {}
    _stub_gh(monkeypatch)
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **k: plans.PlanState(
            number=7, url="u/7", title="My Feature", header={"base": "release"}, pr=None
        ),
    )
    monkeypatch.setattr(
        github,
        "create_pr",
        lambda **k: (
            captured.update(create_base=k["base"])
            or github.PullRequest(
                number=42, url="u/pr/42", is_draft=True, state="OPEN", existed=False
            )
        ),
    )
    result = _run(monkeypatch, ["pr", "submit", "--json"])  # _REF has no base
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["base"] == "release"
    assert captured["create_base"] == "release"


def test_submit_surfaces_conflicts_but_succeeds(monkeypatch):
    _authed(monkeypatch)
    _stub_gh(
        monkeypatch,
        probe=git.MergeProbe(determined=True, mergeable=False, conflicts=("a.py", "b.py")),
    )
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    # The submit succeeded MECHANICALLY (exit 0); mergeability is reported separately.
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True
    assert data["mergeable"] is False and data["conflicts"] == ["a.py", "b.py"]
    assert data["base"] == "main"


def test_submit_probe_failure_is_fail_open(monkeypatch):
    _authed(monkeypatch)
    _stub_gh(monkeypatch, probe=None)  # probe raises -> fail-open
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["mergeable"] is None and data["conflicts"] == []


def test_submit_undetermined_probe_is_null(monkeypatch):
    _authed(monkeypatch)
    _stub_gh(monkeypatch, probe=git.MergeProbe(determined=False, mergeable=False, conflicts=()))
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["mergeable"] is None


def test_real_submit_embeds_plan_when_available(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch, plan_body="# My Plan\n\nbody text")
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["plan_embedded"] is True
    body = str(calls["pr_body"])
    assert "<details><summary>Plan #7</summary>" in body and "# My Plan" in body
    assert "`gh pr checkout 42`" in body  # footer stays plain even with the HTML embed


def test_real_submit_idempotent_existing_pr(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch, existed=True)
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["pr"]["existed"] is True
    # OPEN reuse is byte-identical to today: never reopens.
    assert calls["reopened"] is None


def test_submit_reopens_closed_reused_pr(monkeypatch):
    # A replan reuses the branch; find_pr_for_branch returns the prior attempt's CLOSED PR.
    # Submit reopens it and proceeds (pushes, updates the header) rather than decorating a
    # closed PR that /land would then refuse.
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch, existed=True, state="CLOSED")
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0, result.output
    # The reopen note rides stderr; parse the JSON off stdout (result.output combines both).
    data = json.loads(result.stdout)
    assert data["success"] is True and data["pr"]["number"] == 42
    assert calls["reopened"] == 42
    assert calls["pushed"] is True
    assert calls["header"] == {"branch": "plan-7", "pr": "42", "lifecycle_stage": "impl"}
    assert "reopened closed PR #42" in result.stderr


def test_submit_reopen_failure_surfaces_loudly(monkeypatch):
    # A failed reopen propagates as GitHubError (today's infra-failure posture) — never a silent
    # fallback that decorates a still-closed PR.
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch, existed=True, state="CLOSED", reopen_fails=True)
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "github_error"
    assert calls["reopened"] == 42  # the reopen was attempted
    assert calls["header"] is None  # never advanced past the failed reopen


def test_submit_refuses_merged_reused_pr(monkeypatch):
    # A MERGED reused PR has nothing sane to reuse — refuse loudly with the new error_type
    # (never reopen; /land would fail on a merged PR anyway).
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch, existed=True, state="MERGED")
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "pr_already_merged"
    assert calls["reopened"] is None
    assert calls["header"] is None


def test_real_submit_plan_not_found_exits_1(monkeypatch):
    _authed(monkeypatch)
    _stub_gh(monkeypatch)
    monkeypatch.setattr(plans, "get_plan", lambda **k: None)
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "plan_not_found"


def test_real_submit_calls_linear_agent_pr_opened(monkeypatch):
    """The submit hook fires after the header update with the PR fields (the emitter
    itself gates on the stamped provider + LINEAR_AGENT_TOKEN)."""
    _authed(monkeypatch)
    _stub_gh(monkeypatch)
    emitted: list[dict] = []
    monkeypatch.setattr(
        submit_cmd.linear_agent, "emit_pr_opened", lambda _root, **kw: emitted.append(kw)
    )
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0
    assert len(emitted) == 1
    kw = emitted[0]
    assert kw["pr_number"] == 42
    assert kw["pr_url"] == "u/pr/42"
    assert kw["branch"] == "plan-7"


def test_dry_run_submit_never_calls_linear_agent(monkeypatch):
    emitted: list[dict] = []
    monkeypatch.setattr(
        submit_cmd.linear_agent, "emit_pr_opened", lambda _root, **kw: emitted.append(kw)
    )
    result = _run(monkeypatch, ["pr", "submit", "--dry-run", "--json"])
    assert result.exit_code == 0
    assert emitted == []


def test_linear_agent_failure_leaves_submit_payload_byte_identical(monkeypatch):
    """Fail-soft: a broken emitter substrate (gate forced open) never changes the --json payload
    or exit code."""
    _authed(monkeypatch)
    _stub_gh(monkeypatch)
    baseline = _run(monkeypatch, ["pr", "submit", "--json"])
    assert baseline.exit_code == 0

    monkeypatch.setattr(linear_agent, "emission_enabled", lambda *_a, **_k: True)
    monkeypatch.setattr(
        cache,
        "read_agent_session",
        lambda _r: cache.AgentSession(session_id="sess-1", issue="7"),
    )

    def boom(_environ):
        raise IssueBackendError("agent substrate down")

    monkeypatch.setattr(linear_agent, "agent_client_from_env", boom)
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0
    assert result.stdout == baseline.stdout  # the --json payload is byte-identical
    assert "pr-opened emission skipped (non-fatal)" in result.stderr


def test_real_submit_force_pushes(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch)
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0
    assert calls["pushed"] is True
    assert calls["push_kwargs"] == {"force": True}


def test_dirty_tree_refuses_before_push(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch)
    monkeypatch.setattr(git, "is_dirty", lambda root: True)
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "dirty_tree"
    assert calls["pushed"] is False


def test_push_rejected_maps_to_stable_error(monkeypatch):
    _authed(monkeypatch)
    _stub_gh(monkeypatch)

    def _reject(*a, **k):
        raise git.PushRejectedError("! [rejected] plan-7 -> plan-7 (non-fast-forward)")

    monkeypatch.setattr(git, "push", _reject)
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "push_rejected"


def _stub_get_plan_header(monkeypatch, header: dict[str, object]) -> None:
    """Re-stub the gateway `get_plan` so the in-hand plan-header carries `header` (for the
    `impl_run_ids` union-merge path)."""
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **k: plans.PlanState(
            number=7, url="u/7", title="My Feature", header=header, pr=None
        ),
    )


def test_run_id_stamps_impl_run_ids(monkeypatch):
    # `--run-id` on a fresh plan (empty header) stamps a single-element impl_run_ids linkage.
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch)
    result = _run(monkeypatch, ["pr", "submit", "--json", "--run-id", "01RUN_I"])
    assert result.exit_code == 0
    assert calls["header"] == {
        "branch": "plan-7",
        "pr": "42",
        "lifecycle_stage": "impl",
        "impl_run_ids": ["01RUN_I"],
    }
    assert json.loads(result.output)["plan_header"]["fields_updated"] == [
        "branch",
        "pr",
        "lifecycle_stage",
        "impl_run_ids",
    ]


def test_run_id_union_merges_existing_impl_run_ids(monkeypatch):
    # An existing impl_run_ids list is preserved + de-duplicated, the new id appended at the tail.
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch)
    _stub_get_plan_header(monkeypatch, {"impl_run_ids": ["01RUN_A", "01RUN_B"]})
    result = _run(monkeypatch, ["pr", "submit", "--json", "--run-id", "01RUN_C"])
    assert result.exit_code == 0
    assert calls["header"] == {
        "branch": "plan-7",
        "pr": "42",
        "lifecycle_stage": "impl",
        "impl_run_ids": ["01RUN_A", "01RUN_B", "01RUN_C"],
    }


def test_run_id_dedups_when_already_present(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch)
    _stub_get_plan_header(monkeypatch, {"impl_run_ids": ["01RUN_A"]})
    result = _run(monkeypatch, ["pr", "submit", "--json", "--run-id", "01RUN_A"])
    assert result.exit_code == 0
    assert calls["header"] == {
        "branch": "plan-7",
        "pr": "42",
        "lifecycle_stage": "impl",
        "impl_run_ids": ["01RUN_A"],
    }


def test_no_run_id_leaves_impl_run_ids_untouched(monkeypatch):
    # A bare CLI submit (no --run-id) never writes the impl_run_ids field.
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch)
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0
    assert calls["header"] == {"branch": "plan-7", "pr": "42", "lifecycle_stage": "impl"}


def test_merge_impl_run_ids_ignores_non_string_and_non_list():
    # The stored value is untrusted (read off the issue header): keep only string entries, and
    # degrade a non-list base to empty.
    assert submit_cmd._merge_impl_run_ids(["a", 3, "b"], "c") == ("a", "b", "c")
    assert submit_cmd._merge_impl_run_ids(None, "c") == ("c",)
    assert submit_cmd._merge_impl_run_ids("not-a-list", "c") == ("c",)


@pytest.mark.parametrize("stage", ["implement", "address"])
def test_writer_self_exclusion_requires_env_handoff_and_plan_corroboration(
    tmp_path: Path, stage: str
):
    run_id = "01RUN"
    cache.ensure_layout(tmp_path)
    cache.write_plan_ref(tmp_path, plan.PlanRefModel.model_validate(_STACKED_REF).to_domain())
    cache.write_handoff(tmp_path, run_id, {"stage": stage, "mode": "read-write"})
    cache.mark_handoff_consumed(tmp_path, run_id)

    assert (
        delivery_observe._corroborated_remote_run_id(
            tmp_path, "7", run_id, environ={"PERK_RUN_ID": run_id}
        )
        == run_id
    )
    assert delivery_observe._corroborated_remote_run_id(tmp_path, "7", run_id, environ={}) is None
    assert (
        delivery_observe._corroborated_remote_run_id(
            tmp_path, "8", run_id, environ={"PERK_RUN_ID": run_id}
        )
        is None
    )


def test_writer_self_exclusion_rejects_unconsumed_and_unsupported_handoffs(tmp_path: Path):
    cache.ensure_layout(tmp_path)
    cache.write_plan_ref(tmp_path, plan.PlanRefModel.model_validate(_STACKED_REF).to_domain())

    unconsumed_run_id = "01UNCONSUMED"
    cache.write_handoff(tmp_path, unconsumed_run_id, {"stage": "address", "mode": "read-write"})
    assert (
        delivery_observe._corroborated_remote_run_id(
            tmp_path,
            "7",
            unconsumed_run_id,
            environ={"PERK_RUN_ID": unconsumed_run_id},
        )
        is None
    )

    unsupported_run_id = "01UNSUPPORTED"
    cache.write_handoff(tmp_path, unsupported_run_id, {"stage": "submit", "mode": "read-write"})
    cache.mark_handoff_consumed(tmp_path, unsupported_run_id)
    assert (
        delivery_observe._corroborated_remote_run_id(
            tmp_path,
            "7",
            unsupported_run_id,
            environ={"PERK_RUN_ID": unsupported_run_id},
        )
        is None
    )


# --- stacked routing (contracts.md §8.47) ----------------------------------------------

_STACKED_REF = {**_REF, "delivery_lineage": "01LINEAGE"}


def _publication_result(*, operation=None, converged_noop: bool = False):
    from perk import delivery

    cascade = operation is not None
    return delivery.PublicationResult(
        pr=github.PullRequest(number=42, url="u/pr/42", is_draft=True, state="OPEN", existed=False),
        branch="plan-7",
        parent_branch="plan-6",
        operation_id=operation.operation_id if cascade else "01OP",
        stack_number=None if cascade else 9,
        stack_size=None if cascade else 2,
        stack_position=None if cascade else 2,
        parent_checkpoint_sha="p" * 40,
        published_head_sha="h" * 40,
        resumed=False,
        converged_noop=converged_noop,
        operation=operation,
    )


def _delivery_operation(*, no_op: bool = False):
    from perk import delivery

    return delivery.DeliveryOperationFacts(
        kind="sync",
        operation_id=None if no_op else "01SYNC",
        abandoned_operation_id=None,
        resumed=False,
        no_op=no_op,
        affected=()
        if no_op
        else (
            delivery.SyncResult.Layer(
                node_id="1.1",
                plan_id="7",
                branch="plan-7",
                pr_number=42,
                before_sha="a" * 40,
                after_sha="b" * 40,
            ),
        ),
        notes=("concluded old operation",),
    )


def _header_builder(captured: dict[str, Any]):
    """The captured `header_fields` builder, typed for the type checker."""
    from collections.abc import Callable
    from typing import cast

    return cast("Callable[[int], dict[str, object]]", captured["header_fields"])


def _run_stacked(monkeypatch, args, *, ref=None):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(
            Path(d), plan.PlanRefModel.model_validate(ref or _STACKED_REF).to_domain()
        )
        return runner.invoke(cli, args)


def test_header_lineage_routes_stacked_even_with_a_stale_ref(monkeypatch):
    from perk import delivery

    # The ref carries no lineage (stale), but the plan header does — header wins: the submit
    # routes to the stacked publish delegation, never silently incremental.
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch)
    _stub_get_plan_header(monkeypatch, {"delivery_lineage": "01LINEAGE", "run_id": "01HDR"})
    published: dict[str, object] = {}

    def _fake_publish(repo_root, **kwargs):
        published.update(kwargs)
        return _publication_result()

    monkeypatch.setattr(delivery, "publish_layer", _fake_publish)
    result = _run(monkeypatch, ["pr", "submit", "--json"])  # the plain, lineage-less _REF
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["delivery"] == "stacked"  # the stacked route was taken
    assert published["run_id"] == "01HDR"  # the publish delegation was reached
    assert published["trigger_run_id"] is None  # fallback journal ids are never trigger proof
    assert calls["pushed"] is False  # never reached the incremental push


def test_stacked_submit_delegates_to_publish_layer(monkeypatch):
    from perk import delivery

    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch)
    _stub_get_plan_header(monkeypatch, {"delivery_lineage": "01LINEAGE", "run_id": "01HDR"})
    captured: dict[str, Any] = {}

    def _fake_publish(repo_root, **kwargs):
        captured.update(kwargs)
        return _publication_result()

    monkeypatch.setattr(delivery, "publish_layer", _fake_publish)
    probes: dict[str, object] = {}

    def _probe(_root, *, base, branch_ref):
        probes["base"] = base
        probes["branch_ref"] = branch_ref
        return _CLEAN_PROBE

    monkeypatch.setattr(git, "detect_merge_conflicts", _probe)
    result = _run_stacked(monkeypatch, ["pr", "submit", "--json", "--run-id", "01RUN_X"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["success"] is True
    # The additive stacked envelope fields.
    assert data["delivery"] == "stacked"
    assert data["stack"] == {"number": 9, "size": 2, "position": 2}
    assert data["operation_id"] == "01OP"
    # `base` carries the PR's REAL merge target — the parent branch — and the mergeability
    # probe targets it (the conflict-resolver rebases onto the parent).
    assert data["base"] == "plan-6"
    assert probes["base"] == "plan-6" and probes["branch_ref"] == "h" * 40
    # publish_layer received the explicit --run-id (it wins over the header run_id).
    assert captured["plan_id"] == "7" and captured["run_id"] == "01RUN_X"
    assert captured["title"] == "My Feature"
    assert captured["trigger_run_id"] == "01RUN_X"
    assert "worktree_root" not in captured and "remote_writers" not in captured
    # The identity fields are composed by submit (the builder), written by publish.
    header_fields = _header_builder(captured)
    assert header_fields(42) == {
        "branch": "plan-7",
        "pr": "42",
        "lifecycle_stage": "impl",
        "impl_run_ids": ["01RUN_X"],
    }
    # The stacked route never runs the incremental push/header path.
    assert calls["pushed"] is False and calls["header"] is None


def test_stacked_cascade_envelope_bookkeeping_and_human_render(monkeypatch):
    from perk import delivery

    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch)
    _stub_get_plan_header(
        monkeypatch,
        {
            "delivery_lineage": "01LINEAGE",
            "run_id": "01HDR",
            "impl_run_ids": ["01OLD"],
        },
    )
    operation = _delivery_operation()
    monkeypatch.setattr(
        delivery,
        "publish_layer",
        lambda repo_root, **kwargs: _publication_result(operation=operation),
    )
    emitted: list[dict] = []
    monkeypatch.setattr(
        submit_cmd.linear_agent, "emit_pr_opened", lambda _root, **kw: emitted.append(kw)
    )

    result = _run_stacked(monkeypatch, ["pr", "submit", "--json", "--run-id", "01RUN_X"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["operation_id"] == "01SYNC"
    assert data["stack"] is None
    assert data["operation"] == {
        "kind": "sync",
        "operation_id": "01SYNC",
        "abandoned_operation_id": None,
        "resumed": False,
        "no_op": False,
        "affected": [
            {
                "node_id": "1.1",
                "plan_id": "7",
                "branch": "plan-7",
                "pr_number": 42,
                "before_sha": "a" * 40,
                "after_sha": "b" * 40,
            }
        ],
        "notes": ["concluded old operation"],
    }
    assert calls["header"] == {"impl_run_ids": ["01OLD", "01RUN_X"]}
    assert data["plan_header"]["fields_updated"] == ["impl_run_ids"]
    assert emitted == []


def test_stacked_cascade_without_explicit_run_id_skips_header_stamp(monkeypatch):
    from perk import delivery

    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch)
    _stub_get_plan_header(monkeypatch, {"delivery_lineage": "01LINEAGE", "run_id": "01HDR"})
    operation = _delivery_operation(no_op=True)
    monkeypatch.setattr(
        delivery,
        "publish_layer",
        lambda repo_root, **kwargs: _publication_result(operation=operation, converged_noop=True),
    )
    probed: dict[str, str] = {}

    def _probe(_root, *, base, branch):
        probed.update(base=base, branch=branch)
        return _CLEAN_PROBE.mergeable, _CLEAN_PROBE.conflicts

    monkeypatch.setattr(submit_cmd, "_probe_mergeability", _probe)
    result = _run_stacked(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["operation"]["no_op"] is True and data["operation_id"] is None
    assert data["plan_header"]["fields_updated"] == []
    assert calls["header"] is None
    assert probed == {"base": "plan-6", "branch": "h" * 40}


def test_stacked_cascade_human_render(capsys):
    operation = _delivery_operation()
    result = submit_cmd.PrSubmitResult(
        pr=github.PullRequest(number=42, url="u/pr/42", is_draft=True, state="OPEN", existed=True),
        branch="plan-7",
        issue="7",
        header_update=PlanHeaderUpdate(fields_updated=(), dry_run=False),
        plan_embedded=True,
        pr_checked=True,
        dry_run=False,
        base="plan-6",
        mergeable=True,
        conflicts=(),
        delivery="stacked",
        operation_id=operation.operation_id,
        operation=operation,
    )
    submit_cmd._render_human(result)
    rendered = capsys.readouterr().err
    assert f"{'a' * 40} → {'b' * 40}" in rendered
    assert "note: concluded old operation" in rendered

    submit_cmd._render_human(
        replace(result, operation_id=None, operation=_delivery_operation(no_op=True))
    )
    assert "suffix already in sync" in capsys.readouterr().err


def test_stacked_sync_error_maps_verbatim(monkeypatch):
    from perk import delivery

    _authed(monkeypatch)
    _stub_gh(monkeypatch)
    _stub_get_plan_header(monkeypatch, {"delivery_lineage": "01LINEAGE", "run_id": "01HDR"})

    def fail(repo_root, **kwargs):
        raise delivery.DeliveryError("remote moved", error_type="remote_drift")

    monkeypatch.setattr(delivery, "publish_layer", fail)
    result = _run_stacked(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["error_type"] == "remote_drift"
    assert "stacked propagation failed" in data["message"]


def test_stacked_config_failure_is_invalid_config(monkeypatch):
    _authed(monkeypatch)
    _stub_gh(monkeypatch)
    _stub_get_plan_header(monkeypatch, {"delivery_lineage": "01LINEAGE", "run_id": "01HDR"})
    monkeypatch.setattr(
        submit_cmd.config_mod,
        "load_config",
        lambda root: (_ for _ in ()).throw(submit_cmd.config_mod.ConfigError("bad worktrees")),
    )
    result = _run_stacked(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "invalid_config"


def test_incremental_submit_does_not_load_config(monkeypatch):
    _authed(monkeypatch)
    _stub_gh(monkeypatch)
    monkeypatch.setattr(
        submit_cmd.config_mod,
        "load_config",
        lambda root: (_ for _ in ()).throw(AssertionError("incremental loaded config")),
    )
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["operation"] is None


def test_stacked_run_id_falls_back_to_the_header(monkeypatch):
    from perk import delivery

    _authed(monkeypatch)
    _stub_gh(monkeypatch)
    _stub_get_plan_header(monkeypatch, {"delivery_lineage": "01LINEAGE", "run_id": "01HDR"})
    captured: dict[str, object] = {}

    def _fake_publish(repo_root, **kwargs):
        captured.update(kwargs)
        return _publication_result()

    monkeypatch.setattr(delivery, "publish_layer", _fake_publish)
    result = _run_stacked(monkeypatch, ["pr", "submit", "--json"])  # no --run-id
    assert result.exit_code == 0, result.output
    assert captured["run_id"] == "01HDR"
    # Without an explicit --run-id the impl_run_ids linkage stays untouched (§8.35): the
    # header run id serves the journal only.
    header_fields = _header_builder(captured)
    assert header_fields(42) == {"branch": "plan-7", "pr": "42", "lifecycle_stage": "impl"}


def test_stacked_blank_run_id_uses_header_only_for_the_journal(monkeypatch):
    from perk import delivery

    _authed(monkeypatch)
    _stub_gh(monkeypatch)
    _stub_get_plan_header(monkeypatch, {"delivery_lineage": "01LINEAGE", "run_id": "01HDR"})
    captured: dict[str, object] = {}

    def _fake_publish(repo_root, **kwargs):
        captured.update(kwargs)
        return _publication_result()

    monkeypatch.setattr(delivery, "publish_layer", _fake_publish)
    result = _run_stacked(monkeypatch, ["pr", "submit", "--json", "--run-id", ""])

    assert result.exit_code == 0, result.output
    assert captured["run_id"] == "01HDR"
    assert captured["trigger_run_id"] is None
    assert _header_builder(captured)(42) == {
        "branch": "plan-7",
        "pr": "42",
        "lifecycle_stage": "impl",
    }


def test_stacked_run_id_unresolvable_is_invalid_input(monkeypatch):
    _authed(monkeypatch)
    _stub_gh(monkeypatch)
    _stub_get_plan_header(monkeypatch, {"delivery_lineage": "01LINEAGE"})  # no run_id
    result = _run_stacked(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "invalid_input"


def test_stacked_publication_error_maps_to_its_error_type(monkeypatch):
    from perk import delivery

    _authed(monkeypatch)
    _stub_gh(monkeypatch)
    _stub_get_plan_header(monkeypatch, {"delivery_lineage": "01LINEAGE", "run_id": "01HDR"})

    def _fail(repo_root, **kwargs):
        raise delivery.PublicationError("rebase onto plan-6", error_type="stale_parent")

    monkeypatch.setattr(delivery, "publish_layer", _fail)
    result = _run_stacked(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["error_type"] == "stale_parent"
    assert "rebase onto plan-6" in data["message"]


def test_stacked_infra_reconstruction_error_is_delivery_error(monkeypatch):
    from perk import delivery
    from perk.delivery.train import TrainReconstructionError

    _authed(monkeypatch)
    _stub_gh(monkeypatch)
    _stub_get_plan_header(monkeypatch, {"delivery_lineage": "01LINEAGE", "run_id": "01HDR"})

    def _fail(repo_root, **kwargs):
        raise TrainReconstructionError("no order", error_type="invalid_train")

    monkeypatch.setattr(delivery, "publish_layer", _fail)
    result = _run_stacked(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "delivery_error"


def test_stacked_dry_run_stays_offline_and_byte_identical(monkeypatch):
    # The dry run returns before any routing: no backend, no publish.
    result = _run_stacked(monkeypatch, ["pr", "submit", "--dry-run", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["dry_run"] is True and data["success"] is True
    assert data["delivery"] is None and data["stack"] is None and data["operation_id"] is None


def test_incremental_envelope_serializes_stacked_fields_as_null(monkeypatch):
    _authed(monkeypatch)
    _stub_gh(monkeypatch)
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["delivery"] is None
    assert data["stack"] is None
    assert data["operation_id"] is None


def test_compose_stacked_pr_body_sections_and_footer(monkeypatch):
    from perk import delivery

    facts = delivery.LayerBodyFacts(
        node_id="2.2",
        position=2,
        total=3,
        parent_branch="plan-6",
        objective_base="main",
        objective_id="500",
        rows=(
            delivery.TrainRowFacts(node_id="2.1", plan_id="6", pr_number=41, current=False),
            delivery.TrainRowFacts(node_id="2.2", plan_id="7", pr_number=None, current=True),
            delivery.TrainRowFacts(node_id="2.3", plan_id=None, pr_number=None, current=False),
        ),
    )
    body = submit_cmd._compose_stacked_pr_body(
        issue="7", plan_body="# My Plan", facts=facts, pr_number=42
    )
    # The disclaimer + position line.
    assert (
        "> Informational — the delivery train on objective #500 is authoritative; "
        "refreshed only at publication." in body
    )
    assert "Layer 2 of 3 (node 2.2) — targets `plan-6`" in body
    assert "the train lands atomically into `main`" in body
    # The train-context table rows.
    assert "| 1 | 2.1 | #6 | #41 |" in body
    assert "| 2 | 2.2 | #7 | #42 (this PR) |" in body
    assert "| 3 | 2.3 | — | — |" in body
    # The plan embed + footer survive, and the standard body check passes.
    assert "<details><summary>Plan #7</summary>" in body
    assert "`gh pr checkout 42`" in body
    assert github.validate_pr_body(body, pr_number=42) == ()
    # The first (pre-create) pass has no footer yet but still marks the current row.
    first_pass = submit_cmd._compose_stacked_pr_body(
        issue="7", plan_body=None, facts=facts, pr_number=None
    )
    assert "| 2 | 2.2 | #7 | (this PR) |" in first_pass
    assert "gh pr checkout" not in first_pass
