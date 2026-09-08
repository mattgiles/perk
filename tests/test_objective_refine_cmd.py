"""The objective-node refinement doors (contracts.md §8.67): `perk objective refine` (the seeded
cold door), `refine-context` (the warm context worker) and `refinement-save` (the one save
worker) — over the REAL Linear store + adapter + service on a `FakeLinearWorkspace`, a real temp
checkout, and the actual resolvers. `launch.launch_stage` / `launch._sync_main_checkout` are the
only stubs (no `exec pi`, no network).
"""

import copy
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import click
import pytest
from _linear_fakes import _TEAM_KEY, FakeLinearWorkspace
from click.testing import CliRunner

from perk import objective
from perk.backends import resolve
from perk.backends.linear import LinearIssueBackend, LinearProjectObjectiveStore
from perk.backends.linear import attachments as linear_attachments
from perk.backends.linear import client as linear_client
from perk.cli.cli import cli
from perk.cli.commands.seeded_door import SeededLaunch, run_seeded_door
from perk.objective.refinement import authoring
from perk.run import launch
from perk.state import cache
from perk.substrate import git
from perk.substrate.config import Config

TS = "2026-09-07T12:00:00Z"
OBJ_RUN = "01OBJRUN"

# --------------------------------------------------------------------------- scaffolding


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, timeout=30, capture_output=True)


def _write_config(
    root: Path, *, backend: str = "linear", team: str = _TEAM_KEY, extra: str = ""
) -> None:
    body = f'[issues]\nbackend = "{backend}"\n'
    if backend == "linear":
        body += f'team = "{team}"\n'
    (root / ".perk" / "config.toml").write_text(body + extra, encoding="utf-8")


def _scaffold(root: Path, *, backend: str = "linear") -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@x.io")
    _git(root, "config", "user.name", "T")
    (root / "README.md").write_text("# repo\n", encoding="utf-8")
    (root / ".gitignore").write_text(".perk/workflow/\n", encoding="utf-8")
    (root / ".perk").mkdir()
    _write_config(root, backend=backend)
    _git(root, "add", "README.md", ".gitignore", ".perk/config.toml")
    _git(root, "commit", "-q", "-m", "init")


def _commit(root: Path, name: str) -> str:
    (root / name).write_text(name + "\n", encoding="utf-8")
    _git(root, "add", name)
    _git(root, "commit", "-q", "-m", name)
    sha = git.resolve_commit(root, "HEAD")
    assert sha is not None
    return sha


def _linear(
    monkeypatch: pytest.MonkeyPatch, root: Path
) -> tuple[FakeLinearWorkspace, LinearProjectObjectiveStore, LinearIssueBackend]:
    ws = FakeLinearWorkspace()
    monkeypatch.setattr(linear_client, "client_from_env", lambda *a, **k: ws)
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
    store = resolve.resolve_objective_store(root)
    issues = resolve.resolve_issue_backend(root)
    assert isinstance(store, LinearProjectObjectiveStore)
    assert isinstance(issues, LinearIssueBackend)
    return ws, store, issues


def _node(
    node_id: str,
    description: str,
    *,
    status: objective.NodeStatus = objective.NodeStatus.PENDING,
    depends_on: tuple[str, ...] | None = None,
) -> objective.ObjectiveNode:
    return objective.ObjectiveNode(
        id=node_id, description=description, status=status, depends_on=depends_on
    )


def _seed(store: LinearProjectObjectiveStore) -> str:
    ref = store.create_objective(
        title="Objective “Ship it”",
        body="# Objective\n\nProse.\n\n### Phase 1: One\n\n### Phase 2: Two\n",
        run_id=OBJ_RUN,
        roadmap_nodes=[
            _node("1.1", "First future node"),
            _node("1.2", "Blocked future node", status=objective.NodeStatus.BLOCKED),
            _node("2.1", "Far future", depends_on=("1.2",)),
        ],
    )
    return ref.id


def _node_issue(ws: FakeLinearWorkspace, obj_id: str, node_id: str) -> dict[str, object]:
    for issue in ws.issues.values():
        if issue.get("project_id") != obj_id:
            continue
        att = linear_attachments.find_perk_attachment(
            ws.attachment_nodes_of(issue), kind=linear_attachments.OBJECTIVE_NODE_KIND
        )
        if att is not None and att.payload.get("id") == node_id:
            return issue
    raise AssertionError(f"no node issue {node_id}")


def _mutation_names(ws: FakeLinearWorkspace, start: int = 0) -> list[str]:
    names: list[str] = []
    for query, _v in ws.requests[start:]:
        if query.lstrip().startswith("mutation"):
            names.append(query.split("{", 1)[1].split("(", 1)[0].strip())
    return names


def _non_comment_state(ws: FakeLinearWorkspace) -> dict[str, object]:
    issues = {
        uuid: {k: copy.deepcopy(v) for k, v in issue.items() if k != "comments"}
        for uuid, issue in ws.issues.items()
    }
    return {
        "issues": issues,
        "attachments": copy.deepcopy(ws.attachments),
        "relations": list(ws.relations),
        "milestones": copy.deepcopy(ws.milestones),
        "projects": copy.deepcopy(ws.projects),
        "labels": dict(ws.labels),
    }


def _stub_launch(monkeypatch: pytest.MonkeyPatch, sink: dict) -> None:
    monkeypatch.setattr(launch, "launch_stage", lambda **k: sink.update(k))


def _forbid(monkeypatch: pytest.MonkeyPatch, *, sync: bool = True, launch_too: bool = True) -> None:
    if sync:
        monkeypatch.setattr(
            launch, "_sync_main_checkout", lambda root: pytest.fail("must not sync")
        )
    if launch_too:
        monkeypatch.setattr(launch, "launch_stage", lambda **k: pytest.fail("must not launch"))


def _invoke(monkeypatch: pytest.MonkeyPatch, root: Path, args: list[str]):
    monkeypatch.chdir(root)
    return CliRunner().invoke(cli, args)


def _payload(result) -> dict[str, object]:
    assert result.stdout.strip(), result.output
    return json.loads(result.stdout)


def _write_draft(path: Path, *, run_id: str, digest: str, markdown: str) -> None:
    body = json.dumps(
        {"schema_version": 1, "run_id": run_id, "context_digest": digest, "markdown": markdown},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    path.write_text(body + "\n", encoding="utf-8")


def _scratch_runs(root: Path) -> list[str]:
    return cache.list_run_ids(root)


# --------------------------------------------------------------------------- rollout refusal


def test_github_backend_refuses_before_any_auth_network_sync_or_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    _scaffold(root, backend="github")
    _forbid(monkeypatch)
    monkeypatch.setattr(linear_client, "client_from_env", lambda *a, **k: pytest.fail("no client"))
    monkeypatch.setattr(resolve, "GitHubObjectiveStore", lambda *a, **k: pytest.fail("no store"))
    for args in (
        ["objective", "refine", "7", "--json"],
        ["objective", "refine", "7", "--dry-run", "--json"],
        ["objective", "refine-context", "7", "--run-id", "01RID", "--json"],
        ["objective", "refinement-save", "--draft-file", "d.json", "--run-id", "01RID", "--json"],
    ):
        result = _invoke(monkeypatch, root, args)
        assert result.exit_code == 1, result.output
        payload = _payload(result)
        assert payload["error_type"] == "unsupported_backend", payload
        assert "Linear only" in str(payload["message"])
    assert _scratch_runs(root) == []


# --------------------------------------------------------------------------- input refusals


@pytest.mark.parametrize(
    "args, error_type, fragment",
    [
        (["objective", "refine", "--json"], "objective_required", "objective id is required"),
        (["objective", "refine", "7", "--node", " ", "--json"], "invalid_input", "not be blank"),
        (
            ["objective", "refine", "7", "--node", "1.1", "--node", "1.2", "--json"],
            "invalid_input",
            "at most once",
        ),
        (
            ["objective", "refine", "7", "--worktree", "elsewhere", "--json"],
            "invalid_input",
            "--worktree is not accepted",
        ),
        (["objective", "refine", "7", "--remote", "--json"], "remote_blocked", "local-only"),
    ],
)
def test_input_and_target_restrictions_refuse_before_any_backend_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
    error_type: str,
    fragment: str,
) -> None:
    root = tmp_path / "repo"
    _scaffold(root)
    _forbid(monkeypatch)
    monkeypatch.setattr(linear_client, "client_from_env", lambda *a, **k: pytest.fail("no client"))
    result = _invoke(monkeypatch, root, args)
    assert result.exit_code == 1, result.output
    payload = _payload(result)
    assert payload["error_type"] == error_type, payload
    assert fragment in str(payload["message"]).lower() or fragment in str(payload["message"])
    assert _scratch_runs(root) == []


# --------------------------------------------------------------------------- dry run


def test_dry_run_resolves_online_reports_and_touches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    _scaffold(root)
    ws, store, _issues = _linear(monkeypatch, root)
    obj_id = _seed(store)
    before = _non_comment_state(ws)
    (root / "wip.txt").write_text("dirty\n", encoding="utf-8")
    _forbid(monkeypatch)
    start = len(ws.requests)

    result = _invoke(monkeypatch, root, ["objective", "refine", obj_id, "--dry-run", "--json"])
    assert result.exit_code == 0, result.output
    payload = _payload(result)
    assert payload == {
        "success": True,
        "error_type": None,
        "objective_id": obj_id,
        "objective_run_id": OBJ_RUN,
        "node_id": "1.1",
        "node_status": "pending",
        "carrier_identifier": payload["carrier_identifier"],
        "carrier_url": payload["carrier_url"],
        "has_prior_refinement": False,
        "source_changed": False,
        "advisory": True,
        "checkout": {
            "path": str(root),
            "head_sha": git.resolve_commit(root, "HEAD"),
            "dirty": True,
        },
        "backend": "linear",
        "dry_run": True,
    }
    # Explicit blocked node: eligible, reported as blocked.
    result = _invoke(
        monkeypatch, root, ["objective", "refine", obj_id, "--node", "1.2", "--dry-run", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert _payload(result)["node_status"] == "blocked"
    # Human dry-run shows no seed section and narrates the resolution.
    result = _invoke(monkeypatch, root, ["objective", "refine", obj_id, "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "advisory=yes" in result.stderr and "seed prompt" not in result.output
    # Nothing minted, written, claimed or mutated.
    assert _scratch_runs(root) == []
    assert _mutation_names(ws, start) == []
    assert _non_comment_state(ws) == before


# --------------------------------------------------------------------------- real launch


def test_real_launch_prepares_after_the_one_sync_and_launches_with_the_post_sync_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    _scaffold(root)
    ws, store, _issues = _linear(monkeypatch, root)
    obj_id = _seed(store)
    before = _non_comment_state(ws)
    pre_sync_head = git.resolve_commit(root, "HEAD")
    events: list[str] = []
    post_sync_head: dict[str, str] = {}

    def fake_sync(repo_root: Path) -> None:
        # The fast-forward moves HEAD AND changes the committed config: a new Linear team route
        # + a new [worktree] setup hook (a Config-carried value the launch must observe).
        events.append("sync")
        assert repo_root == root
        _write_config(root, team="OPS", extra='[worktree]\nsetup = ["echo post-sync"]\n')
        _git(root, "add", ".perk/config.toml")
        post_sync_head["sha"] = _commit(root, "landed.txt")

    monkeypatch.setattr(launch, "_sync_main_checkout", fake_sync)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    # Record the team key every constructed store/backend adapter is routed to.
    routes: list[tuple[str, str]] = []
    real_store = resolve.linear.LinearProjectObjectiveStore
    real_backend = resolve.linear.LinearIssueBackend

    def recording(kind: str, real: Callable):
        def build(client, *, team_key: str, repo_root: Path):
            routes.append((kind, team_key))
            return real(client, team_key=team_key, repo_root=repo_root)

        return build

    monkeypatch.setattr(
        resolve.linear, "LinearProjectObjectiveStore", recording("store", real_store)
    )
    monkeypatch.setattr(resolve.linear, "LinearIssueBackend", recording("issues", real_backend))
    start = len(ws.requests)

    result = _invoke(monkeypatch, root, ["objective", "refine", obj_id, "--node", "1.2", "--json"])
    assert result.exit_code == 0, result.output
    assert events == ["sync"]
    assert "advisory refinement; nothing claimed" in result.stderr

    # The launch: the actual stage, no sync again, a pre-minted run, the namespaced handoff only,
    # and the POST-sync Config (never the invocation-time one).
    assert launched["stage"].id == "objective-refine"
    assert launched["sync_main"] is False
    assert launched["plan_id"] is None and launched["worktree"] is None
    rid = launched["run_id_override"]
    assert isinstance(rid, str) and rid
    handoff_extra = launched["handoff_extra"]
    assert set(handoff_extra) == {"objective_refinement"}
    assert set(handoff_extra["objective_refinement"]) == {"context_digest"}
    config: Config = launched["config"]
    assert config.worktree_setup == ["echo post-sync"]

    # Fresh adapters selected on the new route: every adapter the door built after the sync is
    # routed to the post-sync team; none was built before it.
    assert routes == [("store", "OPS"), ("issues", "OPS")]

    # The materialized context: exact bytes in run scratch, digest = handoff digest, the
    # post-sync observation, the blocked target, the retained absence expectation.
    scratch_path = cache.run_scratch_dir(root, rid) / authoring.CONTEXT_ARTIFACT
    raw = scratch_path.read_text(encoding="utf-8")
    assert raw.endswith("}\n")
    assert authoring.artifact_digest(raw) == handoff_extra["objective_refinement"]["context_digest"]
    context = authoring.parse_context(raw)
    assert context.run_id == rid
    assert context.target.identity.node_id == "1.2"
    assert context.target.status is objective.NodeStatus.BLOCKED
    assert context.target.identity.objective_run_id == OBJ_RUN
    assert context.expected.comment_id is None and context.prior is None
    assert context.provenance.authoring_run_id == rid
    assert context.provenance.code_basis.head_sha == post_sync_head["sha"] != pre_sync_head
    assert context.provenance.code_basis.dirty is False
    assert context.provenance.authored_at == context.provenance.code_basis.captured_at
    assert context.objective.id == obj_id and context.objective.title == "Objective “Ship it”"

    # The seed: identifiers + the session-data context path; never claims or plans.
    prompt = launched["prompt_override"]
    assert "node `1.2`" in prompt
    assert str(cache.session_data_dir(root, rid) / authoring.CONTEXT_ARTIFACT) in prompt
    assert "objective_refinement_draft" in prompt and "/objective-refinement-save" in prompt
    assert "objective_node" not in prompt and "plan_save" not in prompt
    assert "linear_get_issue" in prompt  # the Linear read clause
    assert "full-content replacement" in prompt and "re-refining" not in prompt

    # Zero claims, plan refs, or non-comment writes.
    assert _mutation_names(ws, start) == []
    assert _non_comment_state(ws) == before
    assert cache.read_plan_ref(root) is None
    assert _scratch_runs(root) == [rid]


def test_sync_to_github_refuses_before_target_read_files_or_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    _scaffold(root)
    ws, store, _issues = _linear(monkeypatch, root)
    obj_id = _seed(store)
    monkeypatch.setattr(
        launch, "_sync_main_checkout", lambda repo_root: _write_config(root, backend="github")
    )
    _forbid(monkeypatch, sync=False)
    start = len(ws.requests)
    result = _invoke(monkeypatch, root, ["objective", "refine", obj_id, "--json"])
    assert result.exit_code == 1, result.output
    assert _payload(result)["error_type"] == "unsupported_backend"
    assert ws.requests[start:] == []  # no target API read after the route flipped
    assert _scratch_runs(root) == []


def test_no_sync_never_syncs_and_still_launches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    _scaffold(root)
    _ws, store, _issues = _linear(monkeypatch, root)
    obj_id = _seed(store)
    monkeypatch.setattr(launch, "_sync_main_checkout", lambda root: pytest.fail("must not sync"))
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    result = _invoke(monkeypatch, root, ["objective", "refine", obj_id, "--no-sync", "--json"])
    assert result.exit_code == 0, result.output
    assert launched["sync_main"] is False and launched["stage"].id == "objective-refine"


def test_target_refusals_are_typed_and_write_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    _scaffold(root)
    _ws, store, _issues = _linear(monkeypatch, root)
    obj_id = _seed(store)
    monkeypatch.setattr(launch, "_sync_main_checkout", lambda root: None)
    _forbid(monkeypatch, sync=False)
    cases = [
        (["objective", "refine", obj_id, "--node", "9.9", "--json"], "node_not_found"),
        (["objective", "refine", "missing-proj", "--json"], "objective_not_found"),
    ]
    store.update_objective_node(
        objective_id=obj_id, node_id="2.1", status=objective.NodeStatus.DONE
    )
    cases.append((["objective", "refine", obj_id, "--node", "2.1", "--json"], "node_ineligible"))
    for args, error_type in cases:
        result = _invoke(monkeypatch, root, args)
        assert result.exit_code == 1, result.output
        assert _payload(result)["error_type"] == error_type, result.output
    assert _scratch_runs(root) == []


# --------------------------------------------------------------------------- workers


def test_refine_context_worker_returns_the_exact_string_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    _scaffold(root)
    ws, store, _issues = _linear(monkeypatch, root)
    obj_id = _seed(store)
    _forbid(monkeypatch)
    start = len(ws.requests)
    result = _invoke(
        monkeypatch,
        root,
        ["objective", "refine-context", obj_id, "--run-id", "01WARMRUN", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = _payload(result)
    assert set(payload) == {"success", "error_type", "context_json", "context_digest"}
    context_json = payload["context_json"]
    assert isinstance(context_json, str) and context_json.endswith("}\n")
    assert authoring.artifact_digest(context_json) == payload["context_digest"]
    context = authoring.parse_context(context_json)
    assert context.run_id == "01WARMRUN" and context.target.identity.node_id == "1.1"
    assert authoring.serialize_context(context) == context_json
    # The worker never syncs, writes or mutates.
    assert _scratch_runs(root) == [] and _mutation_names(ws, start) == []
    # Unsafe run ids refuse before any preparation.
    for bad in ("../x", "a/b", ""):
        result = _invoke(
            monkeypatch, root, ["objective", "refine-context", obj_id, "--run-id", bad, "--json"]
        )
        assert result.exit_code == 1 and _payload(result)["error_type"] == "invalid_input"


def _materialize_context(root: Path, *, run_id: str, context_json: str) -> str:
    data_dir = cache.session_data_dir(root, run_id)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / authoring.CONTEXT_ARTIFACT).write_text(context_json, encoding="utf-8")
    return authoring.artifact_digest(context_json)


def test_refinement_save_worker_saves_the_comment_and_only_the_comment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    _scaffold(root)
    ws, store, issues = _linear(monkeypatch, root)
    obj_id = _seed(store)
    roadmap_before = store.get_objective(objective_id=obj_id)
    before = _non_comment_state(ws)
    _forbid(monkeypatch)

    # Capture-time provenance on an already-dirty checkout, then drift the checkout further
    # (a new commit AND a different dirty file): the save neither refreshes nor refuses.
    (root / "wip.txt").write_text("dirty\n", encoding="utf-8")
    rid = "01SAVERUN"
    context = authoring.prepare_refinement_context(
        root, objective_id=obj_id, node_id=None, run_id=rid
    )
    assert context.provenance.code_basis.dirty is True
    captured_head = context.provenance.code_basis.head_sha
    prep = authoring.prepared(context)
    digest = _materialize_context(root, run_id=rid, context_json=prep.context_json)
    _commit(root, "drift.txt")
    (root / "wip.txt").write_text("different dirty\n", encoding="utf-8")

    markdown = "## Refinement\n\nÜnïcode ✓ — keep the tail   \n- no final LF"
    draft_path = tmp_path / "draft.json"
    _write_draft(draft_path, run_id=rid, digest=digest, markdown=markdown)
    start = len(ws.requests)
    result = _invoke(
        monkeypatch,
        root,
        [
            "objective",
            "refinement-save",
            "--draft-file",
            str(draft_path),
            "--run-id",
            rid,
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = _payload(result)
    node_issue = _node_issue(ws, obj_id, "1.1")
    comments = ws.comments_of(node_issue)
    assert len(comments) == 1
    assert payload["success"] is True and payload["error_type"] is None
    assert payload["comment_id"] == comments[0]["id"]
    assert payload["node_id"] == "1.1" and payload["objective_id"] == obj_id
    assert payload["objective_run_id"] == OBJ_RUN
    assert payload["carrier_identifier"] == node_issue["identifier"]
    assert payload["carrier_url"] == context.target.carrier_url
    assert payload["authored_at"] == context.provenance.authored_at
    assert "saved_at" in payload and "body_digest" in payload
    assert _mutation_names(ws, start) == ["commentCreate"]

    # Read back: byte-exact Markdown + the ORIGINAL provenance (not the drifted checkout).
    from perk.objective.refinement import service

    back = service.read_node_refinement(store, issues, objective_id=obj_id, node_id="1.1")
    assert back.saved is not None
    assert back.saved.document.markdown == markdown
    assert back.saved.document.provenance == context.provenance
    assert back.saved.document.provenance.code_basis.head_sha == captured_head
    assert captured_head != git.resolve_commit(root, "HEAD")

    # Nothing but the comment: roadmap, manifest, statuses, backlinks, plan cache/ref unchanged.
    assert store.get_objective(objective_id=obj_id) == roadmap_before
    assert _non_comment_state(ws) == before
    assert cache.read_plan_ref(root) is None
    assert _scratch_runs(root) == [rid]

    # A deliberate same-candidate re-save (same retained expectation + provenance, same bytes)
    # converges on the service's idempotence: the same verified comment, no mutation.
    retry_start = len(ws.requests)
    result = _invoke(
        monkeypatch,
        root,
        [
            "objective",
            "refinement-save",
            "--draft-file",
            str(draft_path),
            "--run-id",
            rid,
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert _payload(result)["comment_id"] == comments[0]["id"]
    assert _mutation_names(ws, retry_start) == []
    assert len(ws.comments_of(node_issue)) == 1
    # A DIFFERENT draft under the now-stale absence expectation refuses typed (never overwrites
    # a record this grounding pass did not observe).
    _write_draft(draft_path, run_id=rid, digest=digest, markdown="## Changed\n")
    result = _invoke(
        monkeypatch,
        root,
        [
            "objective",
            "refinement-save",
            "--draft-file",
            str(draft_path),
            "--run-id",
            rid,
            "--json",
        ],
    )
    payload = _payload(result)
    assert result.exit_code == 1 and payload["error_type"] == "stale_refinement", payload
    assert payload["comment_ids"] == [comments[0]["id"]] and payload["write_attempted"] is False
    assert _mutation_names(ws, retry_start) == []

    # Re-refinement: a fresh grounding pass carries the prior + the exact expectation; the save
    # REPLACES the comment in place (same id).
    rid2 = "01REFINE2"
    context2 = authoring.prepare_refinement_context(
        root, objective_id=obj_id, node_id="1.1", run_id=rid2
    )
    assert context2.prior is not None and context2.prior.markdown == markdown
    assert context2.expected.comment_id == comments[0]["id"]
    digest2 = _materialize_context(
        root, run_id=rid2, context_json=authoring.serialize_context(context2)
    )
    _write_draft(draft_path, run_id=rid2, digest=digest2, markdown="## Replaced\n")
    replace_start = len(ws.requests)
    result = _invoke(
        monkeypatch,
        root,
        [
            "objective",
            "refinement-save",
            "--draft-file",
            str(draft_path),
            "--run-id",
            rid2,
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert _payload(result)["comment_id"] == comments[0]["id"]
    assert _mutation_names(ws, replace_start) == ["commentUpdate"]
    assert len(ws.comments_of(node_issue)) == 1


def test_refinement_save_worker_refuses_missing_mismatched_and_ineligible_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    _scaffold(root)
    ws, store, _issues = _linear(monkeypatch, root)
    obj_id = _seed(store)
    _forbid(monkeypatch)
    rid = "01SAVERUN"
    draft_path = tmp_path / "draft.json"

    def save(run_id: str = rid) -> dict[str, object]:
        result = _invoke(
            monkeypatch,
            root,
            [
                "objective",
                "refinement-save",
                "--draft-file",
                str(draft_path),
                "--run-id",
                run_id,
                "--json",
            ],
        )
        assert result.exit_code == 1, result.output
        return _payload(result)

    # Draft missing → draft_missing (before any context read).
    assert save()["error_type"] == "refinement_draft_missing"
    _write_draft(draft_path, run_id=rid, digest="sha256:" + "0" * 64, markdown="x")
    # Context missing for this run → context_missing.
    assert save()["error_type"] == "refinement_context_missing"
    # Unsafe run id → invalid_input.
    assert save("../x")["error_type"] == "invalid_input"
    context = authoring.prepare_refinement_context(
        root, objective_id=obj_id, node_id=None, run_id=rid
    )
    digest = _materialize_context(
        root, run_id=rid, context_json=authoring.serialize_context(context)
    )
    # Digest mismatch → draft_invalid (the context was re-prepared after the draft).
    payload = save()
    assert payload["error_type"] == "refinement_draft_invalid"
    assert "context_digest does not match" in str(payload["message"])
    # Wrong run in the draft → draft_invalid.
    _write_draft(draft_path, run_id="01ELSE", digest=digest, markdown="x")
    assert "run id" in str(save()["message"])
    # Corrupt context bytes → context_invalid.
    path = cache.session_data_dir(root, rid) / authoring.CONTEXT_ARTIFACT
    good = path.read_bytes()
    path.write_bytes(good[:-3])
    _write_draft(draft_path, run_id=rid, digest=digest, markdown="x")
    assert save()["error_type"] == "refinement_context_invalid"
    path.write_bytes(good)
    # The target becomes ineligible (a plan lands on it) → the service's typed refusal with
    # comment_ids/write_attempted in the envelope; no comment written.
    store.update_objective_node(
        objective_id=obj_id, node_id="1.1", status=objective.NodeStatus.PLANNING
    )
    start = len(ws.requests)
    payload = save()
    assert payload["error_type"] == "node_ineligible"
    assert payload["write_attempted"] is False and payload["comment_ids"] == []
    assert _mutation_names(ws, start) == []
    assert ws.comments_of(_node_issue(ws, obj_id, "1.1")) == []


# --------------------------------------------------------------------------- seeded tail


def test_seeded_launch_config_override_reaches_launch_stage_only_when_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = Config(worktree_root=tmp_path / "override")
    seen: list[Config] = []
    monkeypatch.setattr(launch, "launch_stage", lambda **k: seen.append(k["config"]))

    def make(spec_override: Config | None) -> click.Command:
        @click.command("door")
        @click.pass_context
        def door(ctx: click.Context) -> None:
            def gather(repo_root: Path, config: Config, stage) -> SeededLaunch:
                return SeededLaunch(
                    seed="s",
                    launch_note="n",
                    dry_run_label="l",
                    dry_run_fields=(),
                    dry_run_payload={},
                    config_override=spec_override,
                )

            run_seeded_door(
                ctx,
                stage_id="objective-refine",
                worktree=None,
                dry_run=False,
                remote=None,
                as_json=False,
                no_sync=True,
                pi_args=(),
                backend_errors=(),
                gather=gather,
            )

        return door

    from perk.cli.cli import cli as root_cli

    root = tmp_path / "repo"
    _scaffold(root)
    monkeypatch.chdir(root)
    for spec_override in (None, override):
        root_cli.add_command(make(spec_override), name="door-under-test")
        try:
            result = CliRunner().invoke(root_cli, ["door-under-test"])
        finally:
            root_cli.commands.pop("door-under-test", None)
        assert result.exit_code == 0, result.output
    assert len(seen) == 2
    assert seen[0].worktree_root != override.worktree_root  # default: the invocation Config
    assert seen[1] is override  # set: the override, identically
