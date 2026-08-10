"""Audit-runner tests (perk_dev.audit.runner, `perk-dev audit run`).

Matrix assembly drives the injectable seams over synthetic session corpora (the
test_perk_dev_corpus.py scaffolding style); the CLI tests pin the emit() stream split
(human render on stderr, --json envelope on stdout) and the report-never-gates exit code.
"""

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from perk_dev.audit.corpus import Census, build_census, encode_session_dir
from perk_dev.audit.expectations import Expectation, ExpectationCatalog
from perk_dev.audit.runner import (
    UNCHECKED_REASONS,
    VERDICTS,
    AuditReport,
    AuditReportOut,
    run_audit,
)
from perk_dev.audit.vintage import ReleaseHistory
from perk_dev.cli import cli

# ------------------------------------------------------------------------- fixtures


def _catalog(*entries: Expectation) -> ExpectationCatalog:
    return ExpectationCatalog(schema_version=1, expectations=entries)


def _expectation(
    entry_id: str,
    applies_to: tuple[str, ...],
    vintage_floor: str = "1.0.0",
    tier: str = "deterministic",
) -> Expectation:
    return Expectation(
        id=entry_id,
        kind="workflow-shape",
        surface="s",
        source="p.md",
        applies_to=applies_to,
        vintage_floor=vintage_floor,
        evidence="e",
        violation="v",
        tier=tier,
        enforcement="prose-only",
    )


def _ws(**data: object) -> dict[str, object]:
    return {"type": "custom", "customType": "perk:workflow-state", "data": data}


def _exec(tool: str, args: dict[str, object], *, is_error: bool = False) -> list[dict[str, object]]:
    """A call+result pair without ids: file-order bridging chains it linearly and the
    FIFO fallback pairs it."""
    return [
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "toolCall", "name": tool, "arguments": args}],
            },
        },
        {
            "type": "message",
            "message": {"role": "toolResult", "toolName": tool, "isError": is_error},
        },
    ]


def _write_session(
    directory: Path,
    name: str,
    *,
    cwd: str,
    entries: list[dict[str, object]],
    raw_lines: list[str] | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    session_id = name.removesuffix(".jsonl")
    lines = [json.dumps({"type": "session", "version": 3, "id": session_id, "cwd": cwd})]
    lines.extend(json.dumps(e) for e in entries)
    lines.extend(raw_lines or [])
    path = directory / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class Env:
    """A tmp corpus environment: a fake repo + encoded session dir."""

    def __init__(self, tmp_path: Path) -> None:
        self.main_root = tmp_path / "repo"
        self.main_root.mkdir()
        self.worktree_root = self.main_root / ".worktrees"
        self.worktree_root.mkdir()
        self.sessions_root = tmp_path / "sessions"
        self.sessions_root.mkdir()
        self.main_dir = self.sessions_root / encode_session_dir(str(self.main_root))

    def write(
        self,
        name: str,
        entries: list[dict[str, object]],
        raw_lines: list[str] | None = None,
    ) -> Path:
        return _write_session(
            self.main_dir, name, cwd=str(self.main_root), entries=entries, raw_lines=raw_lines
        )

    def census(self, catalog: ExpectationCatalog) -> Census:
        return build_census(
            sessions_root=self.sessions_root,
            main_root=self.main_root,
            worktree_root=self.worktree_root,
            catalog=catalog,
            bindings=[],
            history=ReleaseHistory(releases=()),
        )


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


# The unit-test catalog reuses a real checker id (the registry is keyed by expectation id)
# beside a judgment entry and a never-exercised entry.
GATED = "read-only.no-worktree-mutation"
CATALOG = _catalog(
    _expectation(GATED, ("stage:plan",), vintage_floor="2.0.0"),
    _expectation("judgey", ("stage:plan",), vintage_floor="1.0.0", tier="judgment"),
    _expectation("miss", ("command:learn-docs",)),
)


def _matrix_env(env: Env) -> Env:
    gate = [_ws(run_id="01R", stage="plan", mode="read-only", perk_version="2.0.0")]
    env.write("violated.jsonl", gate + _exec("write", {"path": "f", "content": "x"}))
    env.write("satisfied.jsonl", gate + _exec("bash", {"command": "cat README.md"}))
    env.write(
        "old.jsonl",
        [
            _ws(run_id="01O", stage="plan", mode="read-only", perk_version="1.0.0"),
            *_exec("bash", {"command": "cat README.md"}),
        ],
    )
    env.write(
        "mystery.jsonl",  # no stamp, no timestamp: vintage-unknown — checked anyway
        [
            _ws(run_id="01M", stage="plan", mode="read-only"),
            *_exec("bash", {"command": "cat README.md"}),
        ],
    )
    env.write(
        "mangled.jsonl",
        gate + _exec("bash", {"command": "cat README.md"}),
        raw_lines=["not json at all"],
    )
    return env


def _result(report: AuditReport, expectation_id: str):
    matches = [r for r in report.results if r.id == expectation_id]
    assert len(matches) == 1
    return matches[0]


def _cell(report: AuditReport, expectation_id: str, basename: str):
    cells = [c for c in _result(report, expectation_id).cells if c.session_basename == basename]
    assert len(cells) == 1, f"{basename}: {len(cells)} cells"
    return cells[0]


# ---------------------------------------------------------------- matrix assembly


def test_matrix_assembly(env: Env):
    census = _matrix_env(env).census(CATALOG)
    report = run_audit(census=census, catalog=CATALOG, expectation_ids=())

    violated = _cell(report, GATED, "violated.jsonl")
    assert violated.status == "violated"
    assert violated.entries != () and violated.reason is None
    assert violated.vintage_version == "2.0.0" and violated.vintage_basis == "stamp"

    assert _cell(report, GATED, "satisfied.jsonl").status == "satisfied"

    gated_old = _cell(report, GATED, "old.jsonl")
    assert gated_old.status == "not-applicable"
    assert "below the 2.0.0 floor" in gated_old.detail

    # Vintage-unknown is checked anyway: the verdict is computed and the unknown basis
    # rides the cell for calibration-time discounting.
    mystery = _cell(report, GATED, "mystery.jsonl")
    assert mystery.status == "satisfied"
    assert mystery.vintage_version is None and mystery.vintage_basis == "unknown"

    mangled = _cell(report, GATED, "mangled.jsonl")
    assert mangled.status == "unchecked" and mangled.reason == "malformed"

    judgey = _result(report, "judgey")
    assert judgey.exercising == 5
    assert all(c.status == "unchecked" and c.reason == "judgment-tier" for c in judgey.cells)

    miss = _result(report, "miss")
    assert miss.not_exercised is True and miss.cells == ()
    assert report.not_exercised == ("miss",)

    assert report.confirmed_sessions == 5
    assert report.deterministic_count == 2 and report.judgment_count == 1


def test_status_counts_and_totals_are_zero_filled_in_verdict_order(env: Env):
    census = _matrix_env(env).census(CATALOG)
    report = run_audit(census=census, catalog=CATALOG, expectation_ids=())
    assert tuple(report.totals) == VERDICTS
    assert report.totals == {
        "satisfied": 2,
        "violated": 1,
        "not-exercised": 0,
        "not-applicable": 1,
        "unchecked": 6,
    }
    for result in report.results:
        assert tuple(result.status_counts) == VERDICTS
    assert _result(report, "miss").status_counts == dict.fromkeys(VERDICTS, 0)


def test_every_violated_cell_cites_entries(env: Env):
    census = _matrix_env(env).census(CATALOG)
    report = run_audit(census=census, catalog=CATALOG, expectation_ids=())
    seen = 0
    for result in report.results:
        for cell in result.cells:
            if cell.status == "violated":
                seen += 1
                assert cell.entries != (), (result.id, cell.session_basename)
    assert seen == 1


def test_unchecked_reasons_vocabulary():
    assert UNCHECKED_REASONS == ("judgment-tier", "no-checker", "unparsed", "malformed")


def test_session_vanishing_between_census_and_reparse_is_unparsed(env: Env):
    path = env.write(
        "gone.jsonl",
        [
            _ws(run_id="01G", stage="plan", mode="read-only", perk_version="2.0.0"),
            *_exec("bash", {"command": "cat README.md"}),
        ],
    )
    census = env.census(CATALOG)
    path.unlink()  # confirmed at walk time; the re-parse now fails whole-file
    report = run_audit(census=census, catalog=CATALOG, expectation_ids=())
    cell = _cell(report, GATED, "gone.jsonl")
    assert cell.status == "unchecked" and cell.reason == "unparsed"


def test_deterministic_expectation_without_checker_is_unchecked(env: Env):
    catalog = _catalog(_expectation("no-such-checker", ("stage:plan",)))
    env.write("s.jsonl", [_ws(run_id="01R", stage="plan")])
    report = run_audit(census=env.census(catalog), catalog=catalog, expectation_ids=())
    cell = _cell(report, "no-such-checker", "s.jsonl")
    assert cell.status == "unchecked" and cell.reason == "no-checker"


def test_empty_session_falls_through_to_the_precondition_arm(env: Env):
    # A present header with zero entries is a legitimately empty session — never
    # unchecked/unparsed; the checker's precondition arm reports not-exercised.
    env.write("empty.jsonl", [_ws(run_id="01E", stage="plan", perk_version="2.0.0")])
    census = env.census(CATALOG)
    report = run_audit(census=census, catalog=CATALOG, expectation_ids=())
    cell = _cell(report, GATED, "empty.jsonl")
    assert cell.status == "not-exercised" and cell.reason is None
    assert cell.detail == "gate never engaged"


def test_filter_selects_in_catalog_order_and_dedupes(env: Env):
    census = _matrix_env(env).census(CATALOG)
    report = run_audit(
        census=census,
        catalog=CATALOG,
        expectation_ids=("judgey", GATED, "judgey"),
    )
    assert [r.id for r in report.results] == [GATED, "judgey"]
    assert report.deterministic_count == 1 and report.judgment_count == 1
    assert report.not_exercised == ()


def test_default_invocation_reports_all_expectations(env: Env):
    census = _matrix_env(env).census(CATALOG)
    report = run_audit(census=census, catalog=CATALOG, expectation_ids=())
    assert [r.id for r in report.results] == [e.id for e in CATALOG.expectations]


# ------------------------------------------------------------------------------ CLI


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, timeout=60, capture_output=True)


@pytest.fixture
def cli_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    env = Env(tmp_path)
    _git(env.main_root, "init", "-q")
    monkeypatch.chdir(env.main_root)
    return env


def _write_gated_violation(env: Env) -> None:
    """A stage:plan session violating the committed read-only expectation."""
    env.write(
        "v.jsonl",
        [
            _ws(run_id="01V", stage="plan", mode="read-only", perk_version="2.3.0"),
            *_exec("write", {"path": "f", "content": "x"}),
        ],
    )


def test_cli_run_json_envelope_and_exit_zero_with_violations(cli_repo: Env):
    _write_gated_violation(cli_repo)
    result = CliRunner().invoke(
        cli, ["audit", "run", "--sessions-root", str(cli_repo.sessions_root), "--json"]
    )
    assert result.exit_code == 0, result.output  # the report is leads, never a CI gate
    payload = json.loads(result.output)
    assert set(payload) == set(AuditReportOut.model_fields)
    assert payload["success"] is True and payload["error_type"] is None
    assert payload["confirmed_sessions"] == 1
    assert payload["totals"]["violated"] == 1
    by_id = {r["id"]: r for r in payload["results"]}
    gated = by_id["read-only.no-worktree-mutation"]
    assert gated["tier"] == "deterministic"
    cells = gated["cells"]
    assert len(cells) == 1 and cells[0]["status"] == "violated"
    assert cells[0]["entries"] != [] and cells[0]["reason"] is None
    assert cells[0]["vintage_version"] == "2.3.0" and cells[0]["vintage_basis"] == "stamp"
    # The judgment tier stays unchecked with its named reason.
    grill = by_id["plan.grill-before-review"]
    assert all(
        c["status"] == "unchecked" and c["reason"] == "judgment-tier" for c in grill["cells"]
    )


def test_cli_run_human_render_on_stderr(cli_repo: Env):
    _write_gated_violation(cli_repo)
    result = CliRunner().invoke(
        cli, ["audit", "run", "--sessions-root", str(cli_repo.sessions_root)]
    )
    assert result.exit_code == 0, result.output
    out = " ".join(result.stderr.split())  # the human render goes to stderr
    assert "confirmed sessions: 1" in out
    assert "verdicts: satisfied" in out and "· violated 1 ·" in out
    assert "read-only.no-worktree-mutation [deterministic]: 1 exercising" in out
    assert "violations:" in out
    assert "read-only.no-worktree-mutation · v.jsonl · entries" in out
    assert "vintage 2.3.0/stamp" in out


def test_cli_run_no_violations_renders_none(cli_repo: Env):
    cli_repo.write(
        "s.jsonl",
        [
            _ws(run_id="01S", stage="plan", mode="read-only", perk_version="2.3.0"),
            *_exec("bash", {"command": "cat README.md"}),
        ],
    )
    result = CliRunner().invoke(
        cli, ["audit", "run", "--sessions-root", str(cli_repo.sessions_root)]
    )
    assert result.exit_code == 0, result.output
    assert "violations: none" in result.stderr


def test_cli_run_expectation_filter(cli_repo: Env):
    _write_gated_violation(cli_repo)
    result = CliRunner().invoke(
        cli,
        [
            "audit",
            "run",
            "--sessions-root",
            str(cli_repo.sessions_root),
            "--expectation",
            "read-only.no-worktree-mutation",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [r["id"] for r in payload["results"]] == ["read-only.no-worktree-mutation"]
    assert payload["deterministic_count"] == 1 and payload["judgment_count"] == 0


def test_cli_run_unknown_expectation_is_bad_arguments(cli_repo: Env):
    result = CliRunner().invoke(
        cli,
        [
            "audit",
            "run",
            "--sessions-root",
            str(cli_repo.sessions_root),
            "--expectation",
            "no.such.expectation",
            "--json",
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False and payload["error_type"] == "bad_arguments"
    assert "no.such.expectation" in payload["message"]
    # The failure message lists the known ids.
    assert "read-only.no-worktree-mutation" in payload["message"]


def test_cli_run_not_a_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    outside = tmp_path / "no-repo"
    outside.mkdir()
    monkeypatch.chdir(outside)
    result = CliRunner().invoke(cli, ["audit", "run", "--json"])
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error_type"] == "not_a_repo"
