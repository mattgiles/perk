"""The OFFLINE cross-backend regression gate for objective-node refinement (contracts.md §8.67 /
§8.68) — the gate that closes the GitHub refinement carrier by owner decision, with no live
GitHub run.

Every test drives the REAL resolvers, stores/adapters/service, CLI doors and workers over ONE
stateful ``FakeGitHubIssues`` (``tests/_github_fakes.py``; installed on ``subprocess.run`` — git
keeps working through its pass-through) and, for the parity arm, ``FakeLinearWorkspace``.
``launch.launch_stage`` / ``launch._sync_main_checkout`` / ``github.check_auth`` are the only
stubs (no ``exec pi``, no network, no ``gh auth`` probe anywhere in the refinement doors).

Scope: the DOOR-level behavior enabling GitHub authoring adds — the cold door binds a GitHub
context, the warm worker returns the same bytes, the save worker reaches the objective-issue
carrier with typed envelopes, planning consumes the record (warm worker + cold door) and the
claim leaves it untouched, GitHub error translation (never ``github_error`` /
``github_unauthed``), the ``node-engagement --json`` shape + seed-pointer parity across backends,
and the committed-route flip. The persistence matrix (long bodies, replace/retry, coexistence
filters, the service-level 65,536-character refusal, incremental/stacked) is owned by
``tests/test_github_refinement.py`` and deliberately NOT repeated here.

Live GitHub behavior — comment-body byte preservation, the real HTTP 422 shape, ``fullDatabaseId``
presence on every comment, ``--paginate --slurp`` on the comments endpoint — is unobserved and
recorded as such in ``docs/design/archive/objective-refinement-github-carrier.md``.
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from _github_fakes import FakeGitHubIssues, _Proc
from _linear_fakes import _TEAM_KEY, FakeLinearWorkspace
from click.testing import CliRunner

from perk import github, objective, plan
from perk.backends import resolve
from perk.backends.github.backend import GitHubIssueBackend
from perk.backends.github.objective_store import GitHubObjectiveStore
from perk.backends.linear import LinearIssueBackend, LinearProjectObjectiveStore
from perk.backends.linear import client as linear_client
from perk.cli.cli import cli
from perk.cli.commands.objective.node_context import refinement_boundary
from perk.cli.commands.objective.node_engagement_cmd import ObjectiveNodeEngagementOut
from perk.objective.refinement import authoring, codec, service
from perk.objective.refinement.models import (
    RefinementCodeBasis,
    RefinementProvenance,
    RefinementSaveRequest,
)
from perk.run import launch
from perk.state import cache
from perk.state import run_id as run_id_mod
from perk.substrate.config import Config

OBJ = 252
OBJ_ID = str(OBJ)
OBJ_RUN = "01OBJRUN"
URL = f"https://github.com/octo/repo/issues/{OBJ}"
FROZEN_NOW = "2026-09-10T12:00:00Z"
HUMAN_COMMENT = "please keep the scope tight"
# Short on purpose (one non-ASCII character, no final LF) — the long coexistence body is the
# persistence gate's.
MARKDOWN = "## Approach\n\n- carve the seam first ✓\n- no final LF"
GOLDEN_LINEAR_CONTEXT = (
    Path(__file__).resolve().parent / "fixtures" / "objective-refinement" / "context.json"
)
# The plan seed's pointer to a snapshotted refinement: a code span the path cannot close + the
# three measurements (`plan_cmd._node_context_reference`).
POINTER_RE = re.compile(r"`+(?P<path>[^`]+?)`+ \(bytes=(\d+), lines=(\d+), max_line_bytes=(\d+)\)")
NODE_CONTEXT_NOTICE = "Node-context notice"

# --------------------------------------------------------------------------- scaffolding


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, timeout=30, capture_output=True)


def _scaffold_repo(root: Path, *, config: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@x.io")
    _git(root, "config", "user.name", "T")
    (root / "README.md").write_text("# repo\n", encoding="utf-8")
    (root / ".gitignore").write_text(".perk/workflow/\n", encoding="utf-8")
    (root / ".perk").mkdir()
    (root / ".perk" / "config.toml").write_text(config, encoding="utf-8")
    _git(root, "add", "README.md", ".gitignore", ".perk/config.toml")
    _git(root, "commit", "-q", "-m", "init")


GITHUB_CONFIG = '[issues]\nbackend = "github"\n'


def _scaffold_github_repo(root: Path) -> None:
    _scaffold_repo(root, config=GITHUB_CONFIG)


def _scaffold_linear_repo(root: Path) -> None:
    _scaffold_repo(root, config=f'[issues]\nbackend = "linear"\nteam = "{_TEAM_KEY}"\n')


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


def _default_nodes() -> list[objective.ObjectiveNode]:
    # One explicit dependency keeps the graph explicit (no inferred sequential edge from the
    # claimed predecessor onto 1.2), so 1.2 is both refinable AND plannable.
    return [
        _node("1.1", "Predecessor work"),
        _node("1.2", "Refine me"),
        _node("2.1", "Future", depends_on=("1.2",)),
    ]


def _gh_harness(
    monkeypatch: pytest.MonkeyPatch, root: Path
) -> tuple[FakeGitHubIssues, GitHubObjectiveStore, GitHubIssueBackend]:
    """One stateful ``gh`` fake on ``subprocess.run`` seeded with the incremental objective: a
    claimed + planned predecessor (``1.1``), the refinable ``1.2``, a blocked ``2.1``, and one
    human comment on the carrier; the store + issue backend come through the real resolvers."""
    fake = FakeGitHubIssues(page_size=2)
    monkeypatch.setattr(subprocess, "run", fake)
    fake.seed_objective(
        OBJ, run_id=OBJ_RUN, nodes=_default_nodes(), prose="# Objective\n\nProse.\n"
    )
    fake.add_comment(OBJ, HUMAN_COMMENT)
    store = resolve.resolve_objective_store(root)
    issues = resolve.resolve_issue_backend(root)
    assert isinstance(store, GitHubObjectiveStore)
    assert isinstance(issues, GitHubIssueBackend)
    store.update_objective_node(
        objective_id=OBJ_ID, node_id="1.1", status=objective.NodeStatus.PLANNING
    )
    store.update_objective_node(objective_id=OBJ_ID, node_id="1.1", pr="#301")
    store.update_objective_node(
        objective_id=OBJ_ID, node_id="1.1", status=objective.NodeStatus.IN_PROGRESS
    )
    store.update_objective_node(
        objective_id=OBJ_ID, node_id="2.1", status=objective.NodeStatus.BLOCKED
    )
    return fake, store, issues


def _linear_harness(
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


def _body_comment(fake: FakeGitHubIssues) -> dict[str, object]:
    header = plan.find_metadata_block(str(fake.issues[OBJ]["body"]), objective.OBJECTIVE_HEADER_KEY)
    assert header is not None
    comment = fake.comment_by_id(int(str(header["objective_comment_id"])))
    assert comment is not None
    return comment


def _refinement_comments(fake: FakeGitHubIssues) -> list[dict[str, object]]:
    return [c for c in fake.comments[OBJ] if codec.is_refinement_comment(str(c["body"]))]


def _provenance() -> RefinementProvenance:
    return RefinementProvenance(
        authoring_run_id="01AUTHRUN",
        authored_at=FROZEN_NOW,
        code_basis=RefinementCodeBasis(head_sha="b" * 40, dirty=False, captured_at=FROZEN_NOW),
    )


# --------------------------------------------------------------------------- door plumbing


def _invoke(monkeypatch: pytest.MonkeyPatch, root: Path, args: list[str]):
    monkeypatch.chdir(root)
    return CliRunner().invoke(cli, args)


def _payload(result) -> dict[str, Any]:
    """The `--json` envelope; nested payload shapes are asserted, so values stay untyped."""
    assert result.stdout.strip(), result.output
    return json.loads(result.stdout)


def _write_draft(path: Path, *, run_id: str, digest: str, markdown: str) -> None:
    body = json.dumps(
        {"schema_version": 1, "run_id": run_id, "context_digest": digest, "markdown": markdown},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    path.write_text(body + "\n", encoding="utf-8")


def _materialize_context(root: Path, *, run_id: str, context_json: str) -> str:
    """Stand in for the interior importing the context as the run's session artifact."""
    data_dir = cache.session_data_dir(root, run_id)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / authoring.CONTEXT_ARTIFACT).write_text(context_json, encoding="utf-8")
    return authoring.artifact_digest(context_json)


def _stub_launch(monkeypatch: pytest.MonkeyPatch, sink: dict) -> None:
    monkeypatch.setattr(launch, "launch_stage", lambda **k: sink.update(k))


def _forbid_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launch, "launch_stage", lambda **k: pytest.fail("must not launch"))


def _forbid_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launch, "_sync_main_checkout", lambda root: pytest.fail("must not sync"))


def _noop_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launch, "_sync_main_checkout", lambda root: None)


def _freeze_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """One constant timestamp so the cold door's context bytes and the warm worker's are
    provably equal (the provenance carries ``authored_at`` / ``captured_at``)."""
    monkeypatch.setattr(plan, "now_iso", lambda: FROZEN_NOW)


def _authed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The plan door calls ``require_github`` on every real launch and the fake does not model
    ``gh auth status``; auth is not what this gate tests. The refine doors never reach here."""
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _refinement_file(root: Path, run_id: str, objective_id: str) -> Path:
    return (
        cache.run_scratch_dir(root, run_id)
        / "node-context"
        / objective_id
        / "1.2"
        / ("refinement.md")
    )


def _seed_pointer(seed: str) -> Path:
    """The exactly-one refinement pointer a plan seed carries."""
    [match] = POINTER_RE.finditer(seed)
    return Path(match.group("path"))


# --------------------------------------------------------------------------- the doors gate


def test_phase2_gate_github_refinement_doors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The named offline doors gate (contracts.md §8.67, the GitHub arm; incremental — the
    stacked arm is the persistence gate's): dry run → cold door → warm worker parity → save
    worker (+ envelopes) → non-effect proofs → the worker's 65,536-character envelope → warm and
    cold consumption over the objective issue → the post-claim refusal."""
    root = tmp_path / "repo"
    _scaffold_github_repo(root)
    fake, _store, _issues = _gh_harness(monkeypatch, root)

    # 1. Before: the `objective show` bytes, the raw issue body, the objective-body comment.
    show_before = _invoke(monkeypatch, root, ["objective", "show", OBJ_ID, "--json"])
    assert show_before.exit_code == 0, show_before.output
    show_bytes_before = show_before.stdout
    issue_body_before = str(fake.issues[OBJ]["body"])
    body_comment_before = dict(_body_comment(fake))

    # 2. Dry run: online read-only resolution on GitHub; nothing minted, synced or launched.
    _forbid_launch(monkeypatch)
    _forbid_sync(monkeypatch)
    dry_start = len(fake.calls)
    result = _invoke(
        monkeypatch, root, ["objective", "refine", OBJ_ID, "--node", "1.2", "--dry-run", "--json"]
    )
    assert result.exit_code == 0, result.output
    dry = _payload(result)
    assert dry["backend"] == "github"
    assert dry["carrier_identifier"] == f"#{OBJ}"
    assert dry["carrier_url"] == fake.issues[OBJ]["url"] == URL
    assert dry["node_status"] == "pending"
    assert dry["has_prior_refinement"] is False
    assert fake.mutations(dry_start) == []
    assert cache.list_run_ids(root) == []

    # 3. Cold door: the ONE sync (stubbed), then a GitHub-bound context + a real launch.
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    _noop_sync(monkeypatch)
    _freeze_clock(monkeypatch)
    cold_start = len(fake.calls)
    result = _invoke(monkeypatch, root, ["objective", "refine", OBJ_ID, "--node", "1.2", "--json"])
    assert result.exit_code == 0, result.output
    assert launched["stage"].id == "objective-refine"
    assert launched["sync_main"] is False
    handoff_extra = launched["handoff_extra"]
    assert set(handoff_extra) == {"objective_refinement"}
    handoff_digest = handoff_extra["objective_refinement"]["context_digest"]
    rid = launched["run_id_override"]
    assert isinstance(rid, str) and rid
    raw = (cache.run_scratch_dir(root, rid) / authoring.CONTEXT_ARTIFACT).read_text(
        encoding="utf-8"
    )
    assert authoring.artifact_digest(raw) == handoff_digest
    context = authoring.parse_context(raw)
    assert context.target.identity.backend == "github"
    assert context.target.identity.carrier_id == OBJ_ID
    assert context.target.source.issue_description == ""
    assert context.target.carrier_identifier == f"#{OBJ}"
    assert context.expected.comment_id is None
    assert context.engagement == ""
    prompt = launched["prompt_override"]
    assert str(cache.session_data_dir(root, rid) / authoring.CONTEXT_ARTIFACT) in prompt
    assert "objective_refinement_draft" in prompt and "/objective-refinement-save" in prompt
    assert "linear_get_issue" not in prompt  # the GitHub read clause is empty
    assert fake.mutations(cold_start) == []

    # 4. Warm worker parity: the same run id → byte-identical context, the same digest.
    result = _invoke(
        monkeypatch,
        root,
        ["objective", "refine-context", OBJ_ID, "--node", "1.2", "--run-id", rid, "--json"],
    )
    assert result.exit_code == 0, result.output
    warm = _payload(result)
    assert warm["context_json"] == raw
    assert warm["context_digest"] == handoff_digest

    # 5. Save worker: the draft bound to this run + digest lands ONE comment on the objective
    # issue; a different draft under the now-stale absence expectation refuses typed.
    _materialize_context(root, run_id=rid, context_json=raw)
    draft_path = tmp_path / "draft.json"
    _write_draft(draft_path, run_id=rid, digest=handoff_digest, markdown=MARKDOWN)
    save_args = ["objective", "refinement-save", "--draft-file", str(draft_path), "--json"]
    save_start = len(fake.calls)
    result = _invoke(monkeypatch, root, [*save_args, "--run-id", rid])
    assert result.exit_code == 0, result.output
    saved = _payload(result)
    [comment] = _refinement_comments(fake)
    comment_id = str(comment["id"])
    saved_body = str(comment["body"])
    assert saved["carrier_identifier"] == f"#{OBJ}"
    assert saved["carrier_url"] == URL
    assert saved["node_id"] == "1.2"
    assert saved["objective_run_id"] == OBJ_RUN
    assert saved["comment_id"] == comment_id
    assert fake.mutations(save_start) == [f"POST issues/{OBJ}/comments"]
    _write_draft(draft_path, run_id=rid, digest=handoff_digest, markdown="## Changed\n")
    stale_start = len(fake.calls)
    result = _invoke(monkeypatch, root, [*save_args, "--run-id", rid])
    stale = _payload(result)
    assert result.exit_code == 1 and stale["error_type"] == "stale_refinement", stale
    assert stale["comment_ids"] == [comment_id]
    assert stale["write_attempted"] is False
    assert fake.mutations(stale_start) == []
    assert len(_refinement_comments(fake)) == 1

    # 6. Non-effect proofs at the CLI surfaces: `objective show` bytes, the issue body and the
    # objective-body comment are unchanged; the rendered engagement omits the refinement while
    # the `--json` census carries it as a perk-authored row (unfiltered by design).
    show_after = _invoke(monkeypatch, root, ["objective", "show", OBJ_ID, "--json"])
    assert show_after.exit_code == 0, show_after.output
    assert show_after.stdout == show_bytes_before
    assert str(fake.issues[OBJ]["body"]) == issue_body_before
    assert _body_comment(fake) == body_comment_before
    human = _invoke(monkeypatch, root, ["objective", "engagement", OBJ_ID])
    assert human.exit_code == 0, human.output
    assert HUMAN_COMMENT in human.stderr
    assert codec.MARKER_FAMILY not in human.stderr
    assert "carve the seam" not in human.stderr and MARKDOWN not in human.stderr
    machine = _invoke(monkeypatch, root, ["objective", "engagement", OBJ_ID, "--json"])
    assert machine.exit_code == 0, machine.output
    rows = _payload(machine)["project_comments"]
    assert isinstance(rows, list)
    assert any(row["body"] == HUMAN_COMMENT for row in rows)
    [refinement_row] = [row for row in rows if row["id"] == comment_id]
    assert refinement_row["author"]["kind"] == "perk"
    assert cache.read_plan_ref(root) is None

    # 7. The 65,536-character refusal through the worker: a re-refinement pass carries the prior
    # + the exact expectation; the huge draft's PATCH is the one attempted mutation, the typed
    # envelope keeps gh's diagnostic, the stored record is unchanged.
    rid2 = run_id_mod.mint()
    result = _invoke(
        monkeypatch,
        root,
        ["objective", "refine-context", OBJ_ID, "--node", "1.2", "--run-id", rid2, "--json"],
    )
    assert result.exit_code == 0, result.output
    context2_json = _payload(result)["context_json"]
    assert isinstance(context2_json, str)
    context2 = authoring.parse_context(context2_json)
    assert context2.prior is not None and context2.prior.markdown == MARKDOWN
    assert context2.expected.comment_id == comment_id
    digest2 = _materialize_context(root, run_id=rid2, context_json=context2_json)
    _write_draft(draft_path, run_id=rid2, digest=digest2, markdown="x" * 66_000 + "\n")
    huge_start = len(fake.calls)
    result = _invoke(monkeypatch, root, [*save_args, "--run-id", rid2])
    huge = _payload(result)
    assert result.exit_code == 1 and huge["error_type"] == "backend_error", huge
    assert "Body is too long (maximum is 65536 characters)" in str(huge["message"])
    assert huge["write_attempted"] is True
    assert huge["comment_ids"] == [comment_id]
    assert fake.mutations(huge_start) == [f"PATCH issues/comments/{comment_id}"]
    stored = fake.comment_by_id(int(comment_id))
    assert stored is not None and stored["body"] == saved_body

    # 8. Consumption (warm): the node-engagement worker under the live run id snapshots the
    # dated block under run scratch; the engagement is `absent` (no per-node issues on GitHub).
    rid3 = run_id_mod.mint()
    monkeypatch.setenv("PERK_RUN_ID", rid3)
    result = _invoke(
        monkeypatch, root, ["objective", "node-engagement", OBJ_ID, "--node", "1.2", "--json"]
    )
    monkeypatch.delenv("PERK_RUN_ID")
    assert result.exit_code == 0, result.output
    engagement = _payload(result)
    ObjectiveNodeEngagementOut.model_validate(engagement)
    assert engagement["engagement_status"] == "absent"
    assert engagement["warnings"] == []
    refinement = engagement["refinement"]
    assert isinstance(refinement, dict) and refinement["status"] == "present"
    expected_file = _refinement_file(root, rid3, OBJ_ID)
    assert Path(str(refinement["file"]["path"])).resolve() == expected_file.resolve()
    text = expected_file.read_text(encoding="utf-8")
    assert f"<untrusted_node_refinement:{refinement_boundary(MARKDOWN)}>" in text
    assert MARKDOWN in text

    # 9. Consumption (cold plan door) + interleaving on the single-issue carrier: the claim
    # precedes the read, the seed points at the snapshot, the refinement comment is untouched.
    _authed(monkeypatch)
    planned: dict = {}
    _stub_launch(monkeypatch, planned)
    _forbid_sync(monkeypatch)
    refinement_before_plan = dict(stored)
    plan_start = len(fake.calls)
    result = _invoke(
        monkeypatch, root, ["objective", "plan", OBJ_ID, "--node", "1.2", "--no-sync", "--json"]
    )
    assert result.exit_code == 0, result.output
    narration = result.stderr
    assert narration.index("marking node 1.2 planning") < narration.index("reading node context")
    assert "read node context — refinement present" in narration
    plan_calls = fake.calls[plan_start:]
    first_claim = next(
        i
        for i, gh in enumerate(plan_calls)
        if "-X" in gh and gh[gh.index("-X") + 1] == "PATCH" and gh[1].endswith(f"issues/{OBJ}")
    )
    first_comment_read = next(
        i
        for i, gh in enumerate(plan_calls)
        if gh[:2] == ["api", "graphql"] and any("comments(first" in tok for tok in gh)
    )
    assert first_claim < first_comment_read  # claim before read
    plan_rid = planned["run_id_override"]
    assert isinstance(plan_rid, str) and plan_rid
    assert planned["handoff_extra"] == {"objective_id": OBJ_ID, "node_id": "1.2"}
    seed = planned["prompt_override"]
    assert _seed_pointer(seed).resolve() == _refinement_file(root, plan_rid, OBJ_ID).resolve()
    assert NODE_CONTEXT_NOTICE not in seed
    assert fake.comment_by_id(int(comment_id)) == refinement_before_plan
    assert f"PATCH issues/comments/{comment_id}" not in fake.mutations(plan_start)
    assert f"PATCH issues/{OBJ}" in fake.mutations(plan_start)

    # 10. Post-claim: a new grounding pass refuses typed; the historical read stays present.
    rid4 = run_id_mod.mint()
    result = _invoke(
        monkeypatch,
        root,
        ["objective", "refine-context", OBJ_ID, "--node", "1.2", "--run-id", rid4, "--json"],
    )
    assert result.exit_code == 1 and _payload(result)["error_type"] == "node_ineligible"
    monkeypatch.setenv("PERK_RUN_ID", rid4)
    result = _invoke(
        monkeypatch, root, ["objective", "node-engagement", OBJ_ID, "--node", "1.2", "--json"]
    )
    monkeypatch.delenv("PERK_RUN_ID")
    assert result.exit_code == 0, result.output
    assert _payload(result)["refinement"]["status"] == "present"


# --------------------------------------------------------------------------- error translation


def test_github_error_translation_at_the_refinement_doors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every GitHub-side failure reaches the refinement doors in the refinement vocabulary —
    never the seeded helper's ``github_error`` and never a ``gh auth`` probe's
    ``github_unauthed``."""
    root = tmp_path / "repo"
    _scaffold_github_repo(root)
    fake, _store, _issues = _gh_harness(monkeypatch, root)
    _forbid_launch(monkeypatch)
    _forbid_sync(monkeypatch)

    def refuse(args: list[str]) -> dict[str, Any]:
        result = _invoke(monkeypatch, root, args)
        assert result.exit_code == 1, result.output
        payload = _payload(result)
        assert payload["error_type"] not in ("github_error", "github_unauthed"), payload
        return payload

    # A non-numeric objective id: the adapter's honest refusal, before any gh call.
    start = len(fake.calls)
    payload = refuse(["objective", "refine", "ENG-1", "--dry-run", "--json"])
    assert payload["error_type"] == "backend_error" and "numeric" in str(payload["message"])
    assert fake.calls[start:] == []
    # A missing objective; an unknown node; the claimed predecessor.
    payload = refuse(["objective", "refine", "999", "--dry-run", "--json"])
    assert payload["error_type"] == "objective_not_found"
    payload = refuse(["objective", "refine", OBJ_ID, "--node", "9.9", "--dry-run", "--json"])
    assert payload["error_type"] == "node_not_found"
    payload = refuse(["objective", "refine", OBJ_ID, "--node", "1.1", "--dry-run", "--json"])
    assert payload["error_type"] == "node_ineligible"

    # A transport/auth failure at gh: `backend_error` carrying gh's diagnostic, nothing minted,
    # nothing launched — at the cold door (real launch, sync stubbed) and at the warm worker.
    fake.faults.append(
        (
            lambda gh: True,
            _Proc(1, stderr="gh: HTTP 401: Bad credentials (https://docs.github.com/rest)"),
        )
    )
    _noop_sync(monkeypatch)
    payload = refuse(["objective", "refine", OBJ_ID, "--json"])
    assert payload["error_type"] == "backend_error", payload
    assert "Bad credentials" in str(payload["message"])
    assert cache.list_run_ids(root) == []
    payload = refuse(
        ["objective", "refine-context", OBJ_ID, "--run-id", run_id_mod.mint(), "--json"]
    )
    assert payload["error_type"] == "backend_error", payload
    assert "Bad credentials" in str(payload["message"])
    fake.faults.clear()

    # A Linear-bound context retained in the GitHub checkout: the service refuses the backend
    # mismatch before any read or write — never a silent save elsewhere.
    golden = GOLDEN_LINEAR_CONTEXT.read_text(encoding="utf-8")
    golden_context = authoring.parse_context(golden)
    assert golden_context.target.identity.backend == "linear"
    golden_rid = golden_context.run_id
    digest = _materialize_context(root, run_id=golden_rid, context_json=golden)
    draft_path = tmp_path / "draft.json"
    _write_draft(draft_path, run_id=golden_rid, digest=digest, markdown="## Cross-backend\n")
    calls_before = list(fake.calls)
    payload = refuse(
        [
            "objective",
            "refinement-save",
            "--draft-file",
            str(draft_path),
            "--run-id",
            golden_rid,
            "--json",
        ]
    )
    assert payload["error_type"] == "invalid_input", payload
    assert "does not match the store backend" in str(payload["message"])
    assert fake.calls == calls_before


# --------------------------------------------------------------------------- shape parity


@pytest.mark.parametrize("backend", ["linear", "github"])
def test_node_engagement_json_and_seed_pointer_shape_parity_across_backends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str
) -> None:
    """The two consumption shapes are backend-neutral: the ``node-engagement --json`` payload
    (the same closed key sets, ``present``, no warnings) and the plan seed's refinement pointer
    (exactly one, under the launch's pre-minted run, no notice line)."""
    root = tmp_path / "repo"
    if backend == "github":
        _scaffold_github_repo(root)
        _fake, store, issues = _gh_harness(monkeypatch, root)
        objective_id = OBJ_ID
    else:
        _scaffold_linear_repo(root)
        _ws, store, issues = _linear_harness(monkeypatch, root)
        objective_id = store.create_objective(
            title="Obj",
            body="# Objective\n\nProse.\n\n### Phase 1: One\n\n### Phase 2: Two\n",
            run_id=OBJ_RUN,
            roadmap_nodes=[
                _node("1.1", "Predecessor work"),
                _node("1.2", "Refine me"),
                _node("2.1", "Future", status=objective.NodeStatus.BLOCKED, depends_on=("1.2",)),
            ],
        ).id

    # ONE refinement on node 1.2 through the service (not the doors).
    read = service.select_refinement_target(store, issues, objective_id=objective_id, node_id="1.2")
    document = codec.document_for_target(read.target, markdown=MARKDOWN, provenance=_provenance())
    service.save_node_refinement(
        store, issues, request=RefinementSaveRequest(document=document, expected=read.expected)
    )

    # The warm worker's payload shape.
    rid = run_id_mod.mint()
    monkeypatch.setenv("PERK_RUN_ID", rid)
    result = _invoke(
        monkeypatch,
        root,
        ["objective", "node-engagement", objective_id, "--node", "1.2", "--json"],
    )
    monkeypatch.delenv("PERK_RUN_ID")
    assert result.exit_code == 0, result.output
    payload = _payload(result)
    ObjectiveNodeEngagementOut.model_validate(payload)
    assert set(payload) == {
        "success",
        "error_type",
        "objective",
        "node",
        "comments",
        "description_edits",
        "engagement_status",
        "refinement",
        "warnings",
    }
    refinement = payload["refinement"]
    assert isinstance(refinement, dict)
    assert set(refinement) == {"status", "file"}
    assert set(refinement["file"]) == {"path", "bytes", "lines", "max_line_bytes"}
    assert refinement["status"] == "present"
    assert payload["warnings"] == []

    # The cold plan door's seed pointer.
    _authed(monkeypatch)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    _forbid_sync(monkeypatch)
    result = _invoke(
        monkeypatch,
        root,
        ["objective", "plan", objective_id, "--node", "1.2", "--no-sync", "--json"],
    )
    assert result.exit_code == 0, result.output
    plan_rid = launched["run_id_override"]
    assert isinstance(plan_rid, str) and plan_rid
    seed = launched["prompt_override"]
    pointer = _seed_pointer(seed)
    assert pointer.resolve() == _refinement_file(root, plan_rid, objective_id).resolve()
    assert pointer.is_file()
    assert NODE_CONTEXT_NOTICE not in seed


# --------------------------------------------------------------------------- the route flip


def test_sync_that_flips_the_route_to_github_selects_over_github_fresh_adapters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cold door's ONE sync lands a commit that flips the committed ``[issues]`` route from
    Linear to GitHub: the door reloads the Config, builds fresh GitHub adapters, selects over the
    objective issue and launches with the post-sync Config — nothing from the pre-sync Linear
    route survives (no Linear traffic, no Linear read clause)."""
    root = tmp_path / "repo"
    _scaffold_linear_repo(root)
    ws, _store, _issues = _linear_harness(monkeypatch, root)
    fake = FakeGitHubIssues(page_size=2)
    monkeypatch.setattr(subprocess, "run", fake)
    fake.seed_objective(
        OBJ, run_id=OBJ_RUN, nodes=_default_nodes(), prose="# Objective\n\nProse.\n"
    )

    def flip(repo_root: Path) -> None:
        assert repo_root == root
        (root / ".perk" / "config.toml").write_text(
            GITHUB_CONFIG + '[worktree]\nsetup = ["echo post-flip"]\n', encoding="utf-8"
        )
        _git(root, "add", ".perk/config.toml")
        _git(root, "commit", "-q", "-m", "flip the issue backend")

    monkeypatch.setattr(launch, "_sync_main_checkout", flip)
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    linear_start = len(ws.requests)
    result = _invoke(monkeypatch, root, ["objective", "refine", OBJ_ID, "--node", "1.2", "--json"])
    assert result.exit_code == 0, result.output
    assert ws.requests[linear_start:] == []  # no Linear traffic after the flip
    rid = launched["run_id_override"]
    raw = (cache.run_scratch_dir(root, rid) / authoring.CONTEXT_ARTIFACT).read_text(
        encoding="utf-8"
    )
    context = authoring.parse_context(raw)
    assert context.target.identity.backend == "github"
    assert context.target.identity.carrier_id == OBJ_ID
    config: Config = launched["config"]
    assert config.worktree_setup == ["echo post-flip"]  # the post-sync Config, not the cache
    assert "linear_get_issue" not in launched["prompt_override"]
    assert fake.mutations() == []
