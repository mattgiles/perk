"""`perk learn evidence` CLI surface (contracts.md §8.35, node 3.1)."""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github, plan
from perk.backends import resolve
from perk.backends.issue_backend import PlanState
from perk.cli.cli import cli
from perk.cli.commands.learn import evidence_cmd
from perk.learn.evidence import EvidenceBundle, EvidenceSource
from perk.state import cache

_REF = plan.PlanRef(
    provider="github",
    pr_id="7",
    url="https://gh/o/r/issues/7",
    labels=("perk:plan",),
    objective_id=None,
)


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


class _FakeBackend:
    def __init__(self, header: dict[str, object]) -> None:
        self._header = header

    def get_plan(self, *, issue_id: str) -> PlanState:
        return PlanState(
            id=issue_id, url="u", title="Feat", header=self._header, pr=None, state="OPEN"
        )

    def get_plan_body(self, *, issue_id: str) -> str | None:
        return "PLAN BODY"


def _run(
    monkeypatch,
    *,
    header: dict[str, object],
    write_ref: bool = True,
    as_json: bool = True,
    do_render: bool = False,
):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        if write_ref:
            cache.write_plan_ref(Path(d), _REF)
        monkeypatch.setattr(resolve, "resolve_issue_backend", lambda root: _FakeBackend(header))
        monkeypatch.setattr(github, "list_prs_for_branch", lambda **k: ())
        args = ["learn", "evidence"]
        if as_json:
            args.append("--json")
        if do_render:
            args.append("--render")
        result = runner.invoke(cli, args)
    return result


def test_evidence_json_envelope(monkeypatch):
    result = _run(monkeypatch, header={"run_id": "01RUN_P", "impl_run_ids": []})
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert set(data) == {
        "success",
        "error_type",
        "message",
        "skipped",
        "skip_reason",
        "plan_id",
        "bundle_dir",
        "sources",
        "existing_docs",
        "render",
    }
    assert data["render"] is None
    assert data["success"] is True and data["skipped"] is False
    assert data["plan_id"] == "7"
    categories = {s["category"] for s in data["sources"]}
    assert {
        "plan",
        "pr",
        "planning-session",
        "implementation-session",
        "existing-docs",
    } <= categories
    source = data["sources"][0]
    assert set(source) == {"category", "label", "status", "artifact", "detail"}


def test_evidence_human_render_default_path(monkeypatch):
    # The default (non-`--json`) path renders a compact human summary to stderr without crashing —
    # exercises `_render_human` label splitting (`s.label.split("/")[0]`) + status lookups.
    result = _run(
        monkeypatch, header={"run_id": "01RUN_P", "impl_run_ids": ["01RUN_I"]}, as_json=False
    )
    assert result.exit_code == 0
    assert "plan " in result.output and "impl run(s)" in result.output


def test_evidence_human_render_skip(monkeypatch):
    result = _run(monkeypatch, header={"consumed_learn": ["12"]}, as_json=False)
    assert result.exit_code == 0
    assert "skipped" in result.output


def test_evidence_skip_arm(monkeypatch):
    result = _run(monkeypatch, header={"consumed_learn": ["12"]})
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["skipped"] is True
    assert data["sources"] == [] and data["existing_docs"] == []


def test_evidence_no_plan_ref_exits_1(monkeypatch):
    result = _run(monkeypatch, header={"run_id": "x"}, write_ref=False)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_plan_ref"


def test_evidence_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["learn", "evidence", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"


_SESSION_LINES = "\n".join(
    [
        json.dumps({"type": "session", "id": "S"}),
        json.dumps(
            {
                "type": "message",
                "id": "u",
                "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            }
        ),
    ]
)


def _bundle_with_session(repo_root: Path) -> EvidenceBundle:
    """A gathered bundle with one found planning-session source materialized on disk."""
    bundle_dir = repo_root / ".perk" / "workflow" / "scratch" / "learn-evidence"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    jsonl = bundle_dir / "planning-main.jsonl"
    jsonl.write_text(_SESSION_LINES, encoding="utf-8")
    artifact = jsonl.relative_to(repo_root).as_posix()
    return EvidenceBundle(
        skipped=False,
        skip_reason=None,
        plan_id="7",
        bundle_dir=bundle_dir.relative_to(repo_root).as_posix(),
        sources=(
            EvidenceSource(
                category="planning-session", label="main", status="found", artifact=artifact
            ),
            EvidenceSource(category="existing-docs", label="inventory", status="missing"),
        ),
        existing_docs=(),
    )


def _run_render(monkeypatch, *, bundle_factory, as_json: bool = True):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        monkeypatch.setattr(
            evidence_cmd, "gather_evidence", lambda root, ref: bundle_factory(Path(d))
        )
        args = ["learn", "evidence", "--render"]
        if as_json:
            args.append("--json")
        result = runner.invoke(cli, args)
        chunk = Path(d) / ".perk/workflow/scratch/learn-evidence/chunks/planning-main.md"
        chunk_exists = chunk.is_file()
    return result, chunk_exists


def test_render_json_arm(monkeypatch):
    result, chunk_exists = _run_render(monkeypatch, bundle_factory=_bundle_with_session)
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["render"] is not None
    sessions = data["render"]["sessions"]
    assert len(sessions) == 1
    report = sessions[0]
    assert set(report) == {
        "role",
        "source",
        "entries_read",
        "entries_kept",
        "entries_pruned",
        "malformed_lines",
        "duplicate_groups",
        "truncations",
        "boilerplate",
        "chunk_paths",
    }
    assert report["role"] == "planning-session/main"
    assert report["chunk_paths"] == [
        ".perk/workflow/scratch/learn-evidence/chunks/planning-main.md"
    ]
    assert chunk_exists


def test_render_human_arm(monkeypatch):
    result, _ = _run_render(monkeypatch, bundle_factory=_bundle_with_session, as_json=False)
    assert result.exit_code == 0
    assert "render: planning-session/main" in result.output


def test_evidence_writes_manifest_matching_json_stdout(monkeypatch):
    # A materialized (non-skip) bundle also writes <bundle_dir>/manifest.json with the same payload
    # as the --json stdout, so the analyst children can read it (contracts.md §8.35).
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        monkeypatch.setattr(
            evidence_cmd, "gather_evidence", lambda root, ref: _bundle_with_session(Path(d))
        )
        result = runner.invoke(cli, ["learn", "evidence", "--render", "--json"])
        assert result.exit_code == 0
        manifest = Path(d) / ".perk/workflow/scratch/learn-evidence/manifest.json"
        assert manifest.is_file()
        assert json.loads(manifest.read_text(encoding="utf-8")) == json.loads(result.output)


def test_evidence_skip_writes_no_manifest(monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        monkeypatch.setattr(
            resolve, "resolve_issue_backend", lambda root: _FakeBackend({"consumed_learn": ["12"]})
        )
        monkeypatch.setattr(github, "list_prs_for_branch", lambda **k: ())
        result = runner.invoke(cli, ["learn", "evidence", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output)["skipped"] is True
        assert not (Path(d) / ".perk/workflow/scratch/learn-evidence/manifest.json").exists()


def test_render_skip_plan_yields_null(monkeypatch):
    result = _run(monkeypatch, header={"consumed_learn": ["12"]}, do_render=True)
    assert result.exit_code == 0
    assert json.loads(result.output)["render"] is None


def test_no_render_keeps_render_null(monkeypatch):
    result = _run(monkeypatch, header={"run_id": "01RUN_P", "impl_run_ids": []})
    assert result.exit_code == 0
    assert json.loads(result.output)["render"] is None
