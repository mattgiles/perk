"""`perk objective node-engagement <NUMBER> --node ID [--json]` — the node advisory read worker
(engagement + refinement over the shared assembly). Stubs the resolved store and, where the
refinement arm matters, the resolved issue backend (no network)."""

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from perk import objective
from perk.backends import engagement, resolve
from perk.backends.github import objectives
from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import ObjectiveStoreError, RefinementTargetReadError
from perk.cli.cli import cli
from perk.cli.commands.objective.node_context import (
    NodeContext,
    render_node_refinement,
)
from perk.cli.commands.objective.node_engagement_cmd import ObjectiveNodeEngagementOut
from perk.cli.paged_files import TextFileRef
from perk.objective import NodeStatus
from perk.objective.refinement import codec
from perk.objective.refinement.models import (
    RefinementCodeBasis,
    RefinementDocument,
    RefinementIdentity,
    RefinementObjectiveSnapshot,
    RefinementProvenance,
    RefinementRead,
    RefinementSource,
    RefinementTarget,
)
from perk.state import cache
from perk.state import run_id as run_id_mod

N = objective.NodeStatus
HEAD = "b" * 40
TS = "2026-09-07T12:34:56Z"
RUN = "01RUNNODECTX"


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _nodes():
    return (
        objective.ObjectiveNode(id="1.1", description="A", status=N.DONE),
        objective.ObjectiveNode(id="2.1", description="B", status=N.PENDING),
    )


def _state():
    return objectives.ObjectiveState(
        number=7, url="u/7", title="Obj", header={"run_id": "01RID"}, nodes=_nodes()
    )


# --------------------------------------------------------------------------- refinement fixtures


def _identity() -> RefinementIdentity:
    return RefinementIdentity(
        backend="linear",
        objective_id="7",
        objective_run_id="01RID",
        node_id="2.1",
        carrier_id="iss-node21",
    )


def _source() -> RefinementSource:
    return RefinementSource(
        description="B",
        slug=None,
        comment=None,
        depends_on=None,
        effective_depends_on=(),
        issue_description="B",
    )


def _document(markdown: str = "## Approach\n\nDo it carefully.\n") -> RefinementDocument:
    source = _source()
    return RefinementDocument(
        identity=_identity(),
        source=source,
        source_digest=codec.source_digest(source),
        provenance=RefinementProvenance(
            authoring_run_id="01AUTHRUN",
            authored_at=TS,
            code_basis=RefinementCodeBasis(head_sha=HEAD, dirty=False, captured_at=TS),
        ),
        markdown=markdown,
    )


def _target() -> RefinementTarget:
    source = _source()
    return RefinementTarget(
        identity=_identity(),
        source=source,
        source_digest=codec.source_digest(source),
        carrier_identifier="ENG-21",
        carrier_url="https://linear.app/test/issue/ENG-21",
        status=NodeStatus.PENDING,
        plan_ref=None,
        has_plan_metadata=False,
    )


def _snapshot() -> RefinementObjectiveSnapshot:
    return RefinementObjectiveSnapshot(
        backend="linear",
        objective_id="7",
        objective_run_id="01RID",
        objective_url="https://linear.app/test/project/7",
        targets=(_target(),),
    )


def _perk_comment(body: str, cid: str = "c-ref") -> engagement.EngagementComment:
    return engagement.EngagementComment(
        id=cid,
        body=body,
        created_at="2026-09-07T12:00:00.123Z",
        edited_at=None,
        author=engagement.EngagementAuthor(kind="perk", display_name="perk", id=None),
    )


def _refinement_comment(markdown: str = "## Approach\n\nDo it carefully.\n"):
    return _perk_comment(codec.render_refinement(_document(markdown)))


def _expected_block(markdown: str = "## Approach\n\nDo it carefully.\n") -> str:
    saved = codec.parse_refinement_comment(_refinement_comment(markdown))
    assert saved is not None
    return render_node_refinement(RefinementRead(target=_target(), saved=saved))


# --------------------------------------------------------------------------- store / issues fakes


def _install_store(
    monkeypatch,
    *,
    engagement_result=None,
    raises=None,
    backend_id="github",
    targets=None,
    get_objective_raises=None,
):
    """The resolved store. GitHub-shaped by default (its refinement read is ``unsupported``);
    pass ``backend_id="linear"`` + ``targets`` for a refinement-bearing store."""

    class _Store:
        def __init__(self):
            self.backend_id = backend_id
            self.engagement_calls = 0

        def get_objective(self, *, objective_id):
            if get_objective_raises is not None:
                raise get_objective_raises
            return _state()

        def read_node_engagement(self, *, objective_id, node_id):
            self.engagement_calls += 1
            if raises is not None:
                raise ObjectiveStoreError(raises)
            return (
                engagement_result
                if engagement_result is not None
                else (engagement.EMPTY_NODE_ENGAGEMENT)
            )

        def read_node_refinement_targets(self, *, objective_id):
            if targets is None:
                raise RefinementTargetReadError("unsupported_backend", "no refinement read")
            if isinstance(targets, Exception):
                raise targets
            return targets

    store = _Store()
    monkeypatch.setattr(resolve, "resolve_objective_store", lambda root: store)
    return store


def _install_issues(monkeypatch, comments=(), *, backend_id="linear"):
    class _Issues:
        def __init__(self):
            self.backend_id = backend_id
            self.reads = []

        def read_comments(self, *, issue_id):
            self.reads.append(issue_id)
            return tuple(comments)

    issues = _Issues()
    monkeypatch.setattr(resolve, "resolve_issue_backend", lambda root: issues)
    return issues


def _install_present(monkeypatch, *, engagement_result=None, markdown=None):
    comment = _refinement_comment() if markdown is None else _refinement_comment(markdown)
    store = _install_store(
        monkeypatch, engagement_result=engagement_result, backend_id="linear", targets=_snapshot()
    )
    issues = _install_issues(monkeypatch, [comment])
    return store, issues


def _invoke(args, *, env=None, probe=None):
    """Run the worker in a fresh git repo. ``probe(repo_root)`` runs INSIDE the isolated
    filesystem (torn down on exit) — the place to inspect written scratch files."""
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, args, env=env)
        probed = probe(Path(d)) if probe is not None else None
        return result, probed


def _sample_engagement():
    return engagement.NodeEngagement(
        comments=(
            engagement.EngagementComment(
                id="c-1",
                body="please scope this down",
                created_at="2026-03-01",
                edited_at=None,
                author=engagement.EngagementAuthor(kind="human", display_name="Ada", id="u-1"),
            ),
        ),
        description_edits=(
            engagement.DescriptionEdit(
                created_at="2026-03-02",
                author=engagement.EngagementAuthor(kind="human", display_name="Ada", id="u-1"),
                diff=None,
            ),
        ),
    )


def _node_context_dir(repo_root: Path) -> Path:
    return cache.scratch_dir(repo_root) / "runs"


def _no_node_context_written(repo_root: Path) -> bool:
    runs = _node_context_dir(repo_root)
    if not runs.exists():
        return True
    return not any(p.name == "node-context" for p in runs.rglob("node-context"))


def _read_refinement_file(repo_root: Path) -> dict[str, object]:
    """The present-arm probe: the deterministic path's existence + bytes, plus the run root."""
    path = cache.run_scratch_dir(repo_root, RUN) / "node-context" / "7" / "2.1" / "refinement.md"
    return {
        "expected_path": path.resolve(),
        "bytes": path.read_bytes() if path.exists() else None,
        "runs_root": (cache.scratch_dir(repo_root) / "runs").resolve(),
    }


# --------------------------------------------------------------------------- existing surface


def test_json_payload_shape(monkeypatch):
    _install_store(monkeypatch, engagement_result=_sample_engagement())
    result, _ = _invoke(["objective", "node-engagement", "7", "--node", "2.1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["error_type"] is None
    assert payload["objective"] == "7"
    assert payload["node"] == "2.1"
    assert [c["id"] for c in payload["comments"]] == ["c-1"]
    assert payload["comments"][0] == {
        "id": "c-1",
        "body": "please scope this down",
        "created_at": "2026-03-01",
        "edited_at": None,
        "author": {"kind": "human", "display_name": "Ada", "id": "u-1"},
    }
    assert payload["description_edits"] == [
        {
            "created_at": "2026-03-02",
            "author": {"kind": "human", "display_name": "Ada", "id": "u-1"},
            "diff": None,
        }
    ]
    assert payload["engagement_status"] == "present"
    assert payload["refinement"] == {"status": "unsupported"}
    assert payload["warnings"] == []


def test_human_renders_block(monkeypatch):
    _install_store(monkeypatch, engagement_result=_sample_engagement())
    result, _ = _invoke(["objective", "node-engagement", "7", "--node", "2.1"])
    assert result.exit_code == 0, result.output
    assert "<untrusted_node_engagement>" in result.stderr
    assert "please scope this down" in result.stderr
    assert "refinement: unsupported" in result.stderr


def test_human_no_engagement_note(monkeypatch):
    _install_store(monkeypatch, engagement_result=engagement.EMPTY_NODE_ENGAGEMENT)
    result, _ = _invoke(["objective", "node-engagement", "7", "--node", "2.1"])
    assert result.exit_code == 0, result.output
    assert "no pre-planning engagement on node 2.1" in result.stderr


def test_json_empty_engagement(monkeypatch):
    _install_store(monkeypatch, engagement_result=engagement.EMPTY_NODE_ENGAGEMENT)
    result, _ = _invoke(["objective", "node-engagement", "7", "--node", "2.1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["comments"] == []
    assert payload["description_edits"] == []
    assert payload["engagement_status"] == "absent"


def test_objective_not_found(monkeypatch):
    class _Store:
        backend_id = "github"

        def get_objective(self, *, objective_id):
            return None

        def read_node_engagement(self, *, objective_id, node_id):
            raise AssertionError("never read")

    monkeypatch.setattr(resolve, "resolve_objective_store", lambda root: _Store())
    result, _ = _invoke(["objective", "node-engagement", "99", "--node", "2.1", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "objective_not_found"


def test_not_a_repo_exit_2():
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init -> not a repo
        result = runner.invoke(
            cli, ["objective", "node-engagement", "7", "--node", "2.1", "--json"]
        )
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error_type"] == "not_a_repo"


def test_node_option_required():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "node-engagement", "7"])
    assert result.exit_code != 0  # Click usage error: --node is required


# --------------------------------------------------------------------------- advisory split


def test_engagement_store_error_is_partial_success(monkeypatch):
    _install_store(monkeypatch, raises="linear boom")
    result, _ = _invoke(["objective", "node-engagement", "7", "--node", "2.1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["engagement_status"] == "unavailable"
    assert payload["comments"] == []
    assert payload["description_edits"] == []
    assert payload["refinement"] == {"status": "unsupported"}
    assert payload["warnings"] == [
        {
            "surface": "engagement",
            "code": "engagement_read_failed",
            "message": "node engagement unavailable: linear boom",
            "comment_ids": [],
        }
    ]


def test_human_warning_lines(monkeypatch):
    _install_store(monkeypatch, raises="linear boom")
    result, _ = _invoke(["objective", "node-engagement", "7", "--node", "2.1"])
    assert result.exit_code == 0, result.output
    assert (
        "warning: [engagement/engagement_read_failed] node engagement unavailable: linear boom"
        in (result.stderr)
    )


def test_detail_contract_present(monkeypatch):
    _install_present(monkeypatch, engagement_result=_sample_engagement())
    result, _ = _invoke(
        ["objective", "node-engagement", "7", "--node", "2.1", "--json"],
        env={"PERK_RUN_ID": RUN},
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert list(payload) == [
        "success",
        "error_type",
        "objective",
        "node",
        "comments",
        "description_edits",
        "engagement_status",
        "refinement",
        "warnings",
    ]
    assert list(payload["refinement"]) == ["status", "file"]
    assert list(payload["refinement"]["file"]) == ["path", "bytes", "lines", "max_line_bytes"]
    for forbidden in ("context_dir", "source_digest", "carrier", "saved_at", "message"):
        assert forbidden not in payload
    text = result.stdout
    for forbidden in ("context_dir", "source_digest", "carrier", "saved_at"):
        assert forbidden not in text


@pytest.mark.parametrize("status", ["absent", "unsupported", "unavailable"])
def test_detail_contract_non_present_arms(monkeypatch, status):
    if status == "unsupported":
        _install_store(monkeypatch)
    elif status == "absent":
        _install_store(monkeypatch, backend_id="linear", targets=_snapshot())
        _install_issues(monkeypatch, [])
    else:
        _install_store(
            monkeypatch, backend_id="linear", targets=ObjectiveStoreError("targets down")
        )
        _install_issues(monkeypatch, [])
    result, nothing_written = _invoke(
        ["objective", "node-engagement", "7", "--node", "2.1", "--json"],
        env={"PERK_RUN_ID": RUN},
        probe=_no_node_context_written,
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["refinement"] == {"status": status}
    assert list(payload["refinement"]) == ["status"]
    assert nothing_written is True
    if status == "unavailable":
        assert [w["code"] for w in payload["warnings"]] == ["backend_error"]
    else:
        assert payload["warnings"] == []


def test_present_arm_writes_the_file_under_the_live_run(monkeypatch):
    _, issues = _install_present(monkeypatch, engagement_result=_sample_engagement())
    result, probed = _invoke(
        ["objective", "node-engagement", "7", "--node", "2.1", "--json"],
        env={"PERK_RUN_ID": RUN},
        probe=_read_refinement_file,
    )
    assert result.exit_code == 0, result.output
    assert probed is not None
    payload = json.loads(result.stdout)
    assert payload["engagement_status"] == "present"
    assert payload["warnings"] == []
    refinement = payload["refinement"]
    assert refinement["status"] == "present"
    file = refinement["file"]
    assert Path(file["path"]).resolve() == probed["expected_path"]
    expected_text = _expected_block() + "\n"
    assert probed["bytes"] == expected_text.encode("utf-8")
    assert file["bytes"] == len(expected_text.encode("utf-8"))
    assert file["lines"] == len(expected_text.splitlines())
    assert file["max_line_bytes"] == max(len(line.encode()) for line in expected_text.splitlines())
    assert issues.reads == ["iss-node21"]


def test_present_arm_mints_a_run_id_when_unset(monkeypatch):
    monkeypatch.delenv("PERK_RUN_ID", raising=False)
    _install_present(monkeypatch)
    result, probed = _invoke(
        ["objective", "node-engagement", "7", "--node", "2.1", "--json"],
        probe=_read_refinement_file,
    )
    assert result.exit_code == 0, result.output
    assert probed is not None
    path = Path(json.loads(result.stdout)["refinement"]["file"]["path"])
    assert path.name == "refinement.md"
    assert path.parent.name == "2.1" and path.parent.parent.name == "7"
    assert path.parent.parent.parent.name == "node-context"
    run_segment = path.parent.parent.parent.parent.name
    assert run_id_mod.is_run_id(run_segment)
    assert run_segment != RUN
    assert path.parent.parent.parent.parent.parent.resolve() == probed["runs_root"]


def test_present_arm_human_output_order(monkeypatch):
    _install_present(monkeypatch, engagement_result=_sample_engagement())
    result, _ = _invoke(
        ["objective", "node-engagement", "7", "--node", "2.1"], env={"PERK_RUN_ID": RUN}
    )
    assert result.exit_code == 0, result.output
    text = result.stderr
    engagement_at = text.index("<untrusted_node_engagement>")
    refinement_at = text.index("<untrusted_node_refinement>")
    pointer_at = text.index("refinement: /")
    assert engagement_at < refinement_at < pointer_at
    assert _expected_block() in text
    assert "warning:" not in text


def test_snapshot_failure_through_the_cli_is_partial_success(monkeypatch):
    _install_present(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        run_dir = cache.run_scratch_dir(Path(d), RUN)
        run_dir.parent.mkdir(parents=True)
        run_dir.write_text("a file where the run dir should be", encoding="utf-8")
        result = runner.invoke(
            cli,
            ["objective", "node-engagement", "7", "--node", "2.1", "--json"],
            env={"PERK_RUN_ID": RUN},
        )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["refinement"] == {"status": "unavailable"}
    assert [w["code"] for w in payload["warnings"]] == ["node_context_snapshot_failed"]
    assert payload["warnings"][0]["surface"] == "refinement"
    assert payload["warnings"][0]["comment_ids"] == ["c-ref"]
    assert "could not write the refinement to" in payload["warnings"][0]["message"]


# --------------------------------------------------------------------------- hard boundary


def test_unknown_node_is_node_not_found_before_any_advisory_read(monkeypatch):
    store = _install_store(monkeypatch, engagement_result=_sample_engagement())
    result, nothing_written = _invoke(
        ["objective", "node-engagement", "7", "--node", "9.9", "--json"],
        probe=_no_node_context_written,
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "node_not_found"
    assert "9.9" in payload["message"]
    assert store.engagement_calls == 0
    assert nothing_written is True


def test_blank_node_is_invalid_input(monkeypatch):
    store = _install_store(monkeypatch)
    result, _ = _invoke(["objective", "node-engagement", "7", "--node", " ", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "invalid_input"
    assert store.engagement_calls == 0


def test_node_id_is_stripped(monkeypatch):
    _install_store(monkeypatch)
    result, _ = _invoke(["objective", "node-engagement", "7", "--node", " 2.1 ", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["node"] == "2.1"


def test_store_resolution_issue_backend_error_is_github_error(monkeypatch):
    def boom(root):
        raise IssueBackendError("bad [issues] backend selection")

    monkeypatch.setattr(resolve, "resolve_objective_store", boom)
    result, _ = _invoke(["objective", "node-engagement", "7", "--node", "2.1", "--json"])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "github_error"
    assert "bad [issues] backend selection" in payload["message"]


def test_get_objective_store_error_is_github_error(monkeypatch):
    _install_store(monkeypatch, get_objective_raises=ObjectiveStoreError("lookup failed"))
    result, _ = _invoke(["objective", "node-engagement", "7", "--node", "2.1", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "github_error"


def test_serializer_refuses_an_assembled_only_present_context():
    context = NodeContext(
        objective_id="7",
        node_id="2.1",
        engagement=engagement.EMPTY_NODE_ENGAGEMENT,
        engagement_status="absent",
        engagement_block=None,
        refinement_status="present",
        refinement_block="<untrusted_node_refinement>\n…\n</untrusted_node_refinement>",
        refinement_comment_id="c-ref",
        refinement_file=None,
        warnings=(),
    )
    with pytest.raises(ValueError, match="snapshotted"):
        ObjectiveNodeEngagementOut.from_domain(context)


def test_serializer_present_carries_the_pointer():
    ref = TextFileRef(path=Path("/repo/x/refinement.md"), bytes=10, lines=2, max_line_bytes=6)
    context = NodeContext(
        objective_id="7",
        node_id="2.1",
        engagement=engagement.EMPTY_NODE_ENGAGEMENT,
        engagement_status="absent",
        engagement_block=None,
        refinement_status="present",
        refinement_block="block",
        refinement_comment_id="c-ref",
        refinement_file=ref,
        warnings=(),
    )
    payload = ObjectiveNodeEngagementOut.from_domain(context).model_dump(mode="json")
    assert payload["refinement"] == {
        "status": "present",
        "file": {"path": "/repo/x/refinement.md", "bytes": 10, "lines": 2, "max_line_bytes": 6},
    }
