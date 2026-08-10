"""Judgment-fold tests (perk_dev.audit.fold, `perk-dev audit fold`).

The fold is pure over parsed bundle artifacts, so the fixtures here are synthetic
JSON artifacts written straight into a tmp bundle dir (no census/corpus scaffolding):
a deterministic.json in the `audit run` envelope shape, a manifest.json slice, and a
verdicts.json in the wave tool's contract shape. The CLI tests pin the emit() stream
split, the `bad_bundle`/`not_a_repo` arms, and the envelope's exact key set.
"""

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from perk_dev.audit import fold
from perk_dev.audit.runner import (
    UNCHECKED_REASONS,
    VERDICTS,
    AuditReport,
    AuditReportOut,
    Cell,
)
from perk_dev.cli import cli

# ------------------------------------------------------------------------- fixtures

SESSIONS = "/sessions/enc-main"


def _cell(
    basename: str,
    *,
    status: str = "unchecked",
    reason: str | None = "judgment-tier",
    vintage_version: str | None = "2.3.0",
    vintage_basis: str = "stamp",
    entries: tuple[int, ...] = (),
    detail: str = "judgment-tier expectation — outside the deterministic runner",
    path: str | None = None,
) -> dict[str, object]:
    return {
        "session_basename": basename,
        "session_path": path or f"{SESSIONS}/{basename}",
        "status": status,
        "reason": reason,
        "vintage_version": vintage_version,
        "vintage_basis": vintage_basis,
        "entries": list(entries),
        "detail": detail,
    }


def _result(
    entry_id: str,
    cells: list[dict[str, object]],
    *,
    tier: str = "judgment",
) -> dict[str, object]:
    counts = dict.fromkeys(VERDICTS, 0)
    for cell in cells:
        counts[str(cell["status"])] += 1
    return {
        "id": entry_id,
        "kind": "prompt-adherence",
        "tier": tier,
        "applies_to": ["stage:plan"],
        "exercising": len(cells),
        "not_exercised": not cells,
        "status_counts": counts,
        "cells": cells,
    }


def _deterministic(results: list[dict[str, object]], *, success: bool = True) -> dict[str, object]:
    totals = dict.fromkeys(VERDICTS, 0)
    for result in results:
        counts = result["status_counts"]
        assert isinstance(counts, dict)
        for status, count in counts.items():
            assert isinstance(status, str) and isinstance(count, int)
            totals[status] += count
    return {
        "success": success,
        "error_type": None,
        "sessions_root": "/sessions",
        "main_root": "/repo",
        "worktree_root": "/repo/.worktrees",
        "confirmed_sessions": 5,
        "deterministic_count": sum(1 for r in results if r["tier"] == "deterministic"),
        "judgment_count": sum(1 for r in results if r["tier"] == "judgment"),
        "totals": totals,
        "not_exercised": [],
        "results": results,
    }


def _pair(
    expectation_id: str,
    basename: str,
    *,
    status: str = "packetized",
    detail: str = "",
    path: str | None = None,
) -> dict[str, object]:
    return {
        "expectation_id": expectation_id,
        "session_basename": basename,
        "session_path": path or f"{SESSIONS}/{basename}",
        "status": status,
        "detail": detail,
    }


def _manifest(
    results: dict[str, list[dict[str, object]]], *, success: bool = True
) -> dict[str, object]:
    return {
        "success": success,
        "error_type": None,
        "results": [{"id": entry_id, "pairs": pairs} for entry_id, pairs in results.items()],
    }


def _lane(
    expectation_id: str,
    basename: str,
    *,
    status: str = "report",
    verdict: str | None = "satisfied",
    confidence: str | None = "high",
    citations: tuple[int, ...] = (),
    rationale: str | None = "the rationale",
    detail: str = "",
    path: str | None = None,
) -> dict[str, object]:
    return {
        "expectation_id": expectation_id,
        "session_basename": basename,
        "session_path": path or f"{SESSIONS}/{basename}",
        "status": status,
        "verdict": verdict if status == "report" else None,
        "confidence": confidence if status == "report" else None,
        "citations": list(citations),
        "rationale": rationale if status == "report" else None,
        "detail": detail,
    }


def _verdicts(
    bundle_dir: Path, lanes: list[dict[str, object]], *, flow: str = "audit"
) -> dict[str, object]:
    return {"bundle_dir": str(bundle_dir), "flow": flow, "lanes": lanes}


def _write_bundle(
    tmp_path: Path,
    *,
    deterministic: dict[str, object] | None,
    manifest: dict[str, object] | None,
    verdicts: dict[str, object] | None,
) -> Path:
    bundle = (tmp_path / "bundle").resolve()
    bundle.mkdir(parents=True, exist_ok=True)
    if deterministic is not None:
        (bundle / "deterministic.json").write_text(json.dumps(deterministic), encoding="utf-8")
    if manifest is not None:
        (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if verdicts is not None:
        (bundle / "verdicts.json").write_text(json.dumps(verdicts), encoding="utf-8")
    return bundle


def _load(bundle: Path) -> tuple[AuditReport, fold.BundleManifest, fold.BundleVerdicts]:
    return (
        fold.load_deterministic(bundle),
        fold.load_manifest(bundle),
        fold.load_verdicts(bundle),
    )


# ------------------------------------------------------------------ the mapping matrix

JUDGEY = "judgey.expectation"


def _matrix_bundle(tmp_path: Path) -> Path:
    """One judgment expectation exercising every mapping arm, plus a deterministic
    expectation (untouched), a vintage not-applicable cell (preserved), a filtered
    judgment expectation with no manifest entry (kept judgment-tier), and one orphan
    lane (warned)."""
    judgment_cells = [
        _cell(f"s{i}.jsonl")
        for i in range(1, 12)  # s1..s11 all start unchecked/judgment-tier
    ]
    judgment_cells.append(
        _cell(
            "s12.jsonl",
            status="not-applicable",
            reason=None,
            detail="session vintage below the 9.0.0 floor",
        )
    )
    judgment_cells.append(_cell("s13.jsonl"))  # no manifest pair — kept judgment-tier
    deterministic_cells = [
        _cell("d1.jsonl", status="violated", reason=None, entries=(7,), detail="hard proof"),
        _cell("d2.jsonl", status="satisfied", reason=None, detail=""),
    ]
    filtered_cells = [_cell("f1.jsonl")]
    det = _deterministic(
        [
            _result(JUDGEY, judgment_cells),
            _result("det.expectation", deterministic_cells, tier="deterministic"),
            _result("filtered.expectation", filtered_cells),
        ]
    )
    manifest = _manifest(
        {
            JUDGEY: [
                _pair(JUDGEY, "s1.jsonl"),
                _pair(JUDGEY, "s2.jsonl"),
                _pair(JUDGEY, "s3.jsonl"),
                _pair(JUDGEY, "s4.jsonl"),
                _pair(JUDGEY, "s5.jsonl"),
                _pair(JUDGEY, "s6.jsonl"),
                _pair(JUDGEY, "s7.jsonl"),
                _pair(JUDGEY, "s8.jsonl", status="unboundable", detail="estimate over budget"),
                _pair(JUDGEY, "s9.jsonl", status="not-sampled", detail="cap of 5 reached"),
                _pair(JUDGEY, "s10.jsonl", status="unparsed", detail="could not be re-parsed"),
                _pair(JUDGEY, "s11.jsonl", status="malformed", detail="2 malformed line(s)"),
            ]
        }
    )
    bundle = _write_bundle(tmp_path, deterministic=det, manifest=manifest, verdicts=None)
    verdicts = _verdicts(
        bundle,
        [
            _lane(JUDGEY, "s1.jsonl", verdict="satisfied", citations=(2, 4), rationale="clean"),
            _lane(
                JUDGEY,
                "s2.jsonl",
                verdict="violated",
                confidence="medium",
                citations=(3,),
                rationale="bad",
            ),
            _lane(JUDGEY, "s3.jsonl", verdict="violated", citations=(), rationale="claim"),
            _lane(JUDGEY, "s4.jsonl", verdict="unclear", confidence="low", rationale="hazy"),
            _lane(JUDGEY, "s5.jsonl", status="lane-failed", detail="analyst crashed"),
            _lane(JUDGEY, "s6.jsonl", status="malformed-report", detail="no boolean ok"),
            _lane(JUDGEY, "orphan.jsonl", verdict="satisfied", rationale="nobody asked"),
        ],
    )
    (bundle / "verdicts.json").write_text(json.dumps(verdicts), encoding="utf-8")
    return bundle


def _folded_cells(report: AuditReport, entry_id: str) -> dict[str, Cell]:
    result = next(r for r in report.results if r.id == entry_id)
    return {c.session_basename: c for c in result.cells}


def test_fold_mapping_matrix(tmp_path: Path):
    bundle = _matrix_bundle(tmp_path)
    report, warnings = fold.fold_report(*_load(bundle))
    cells = _folded_cells(report, JUDGEY)

    s1 = cells["s1.jsonl"]
    assert s1.status == "satisfied" and s1.reason is None
    assert s1.entries == (2, 4)
    assert s1.detail == "judgment lead (confidence high): clean"

    s2 = cells["s2.jsonl"]
    assert s2.status == "violated" and s2.entries == (3,)
    assert s2.detail == "judgment lead, not proof (confidence medium): bad"

    s3 = cells["s3.jsonl"]
    assert s3.status == "unchecked" and s3.reason == "auditor-unclear"
    assert "cite-less violation claim" in s3.detail and "claim" in s3.detail

    s4 = cells["s4.jsonl"]
    assert s4.status == "unchecked" and s4.reason == "auditor-unclear"
    assert "auditor unclear" in s4.detail
    assert "confidence low" in s4.detail and "hazy" in s4.detail

    s5 = cells["s5.jsonl"]
    assert s5.status == "unchecked" and s5.reason == "lane-failed"
    assert s5.detail == "analyst crashed"

    s6 = cells["s6.jsonl"]
    assert s6.status == "unchecked" and s6.reason == "lane-failed"
    assert s6.detail == "no boolean ok"

    s7 = cells["s7.jsonl"]
    assert s7.status == "unchecked" and s7.reason == "lane-failed"
    assert s7.detail == "no verdict recorded for this pair"

    s8 = cells["s8.jsonl"]
    assert s8.status == "unchecked" and s8.reason == "unboundable"
    assert s8.detail == "estimate over budget"

    s9 = cells["s9.jsonl"]
    assert s9.status == "unchecked" and s9.reason == "not-sampled"
    assert s9.detail == "cap of 5 reached"

    assert cells["s10.jsonl"].reason == "unparsed"
    assert cells["s11.jsonl"].reason == "malformed"

    # The vintage-gated not-applicable cell is preserved untouched (the runner's
    # vintage-before-tier precedence — never replaceable).
    s12 = cells["s12.jsonl"]
    assert s12.status == "not-applicable" and s12.reason is None
    assert "below the 9.0.0 floor" in s12.detail

    # A judgment-tier cell with no manifest pair stays honestly judgment-tier.
    s13 = cells["s13.jsonl"]
    assert s13.status == "unchecked" and s13.reason == "judgment-tier"

    # The orphan lane is ignored + warned (the warnings channel — the pure core did no I/O).
    assert len(warnings) == 1
    assert "orphan.jsonl" in warnings[0] and "matches no replaceable" in warnings[0]

    # Every fold reason is a member of the grown UNCHECKED_REASONS vocabulary.
    for cell in cells.values():
        if cell.status == "unchecked":
            assert cell.reason in UNCHECKED_REASONS


def test_fold_preserves_deterministic_results_and_filtered_expectations(tmp_path: Path):
    bundle = _matrix_bundle(tmp_path)
    deterministic, manifest, verdicts = _load(bundle)
    report, _warnings = fold.fold_report(deterministic, manifest, verdicts)

    det_cells = _folded_cells(report, "det.expectation")
    assert det_cells["d1.jsonl"].status == "violated"
    assert det_cells["d1.jsonl"].detail == "hard proof"
    assert det_cells["d2.jsonl"].status == "satisfied"

    # A filtered-at-judge-time expectation (no manifest entry) keeps every cell
    # judgment-tier — the fold never guesses.
    filtered = _folded_cells(report, "filtered.expectation")
    assert filtered["f1.jsonl"].status == "unchecked"
    assert filtered["f1.jsonl"].reason == "judgment-tier"

    # Roots/rollups pass through.
    assert report.sessions_root == "/sessions"
    assert report.not_exercised == ()


def test_fold_recomputes_counts_and_preserves_vintage(tmp_path: Path):
    bundle = _matrix_bundle(tmp_path)
    report, _warnings = fold.fold_report(*_load(bundle))
    assert tuple(report.totals) == VERDICTS
    judgey = next(r for r in report.results if r.id == JUDGEY)
    assert tuple(judgey.status_counts) == VERDICTS
    # s1 satisfied + s2 violated; s3..s11+s13 unchecked; s12 not-applicable.
    assert judgey.status_counts == {
        "satisfied": 1,
        "violated": 1,
        "not-exercised": 0,
        "not-applicable": 1,
        "unchecked": 10,
    }
    # Totals = judgey + det (1 violated, 1 satisfied) + filtered (1 unchecked).
    assert report.totals == {
        "satisfied": 2,
        "violated": 2,
        "not-exercised": 0,
        "not-applicable": 1,
        "unchecked": 11,
    }
    # Vintage fields ride the folded cell from the deterministic cell, untouched.
    cells = _folded_cells(report, JUDGEY)
    assert cells["s1.jsonl"].vintage_version == "2.3.0"
    assert cells["s1.jsonl"].vintage_basis == "stamp"


def test_fold_keys_by_session_path_under_duplicate_basenames(tmp_path: Path):
    # Two sessions share a basename across encoded session dirs — the census's real
    # collision case. The fold must key by session_path, never basename.
    path_a = "/sessions/enc-a/twin.jsonl"
    path_b = "/sessions/enc-b/twin.jsonl"
    det = _deterministic(
        [
            _result(
                JUDGEY,
                [_cell("twin.jsonl", path=path_a), _cell("twin.jsonl", path=path_b)],
            )
        ]
    )
    manifest = _manifest(
        {
            JUDGEY: [
                _pair(JUDGEY, "twin.jsonl", path=path_a),
                _pair(JUDGEY, "twin.jsonl", path=path_b),
            ]
        }
    )
    bundle = _write_bundle(tmp_path, deterministic=det, manifest=manifest, verdicts=None)
    verdicts = _verdicts(
        bundle,
        [
            _lane(JUDGEY, "twin.jsonl", path=path_a, verdict="satisfied", rationale="a ok"),
            _lane(
                JUDGEY,
                "twin.jsonl",
                path=path_b,
                verdict="violated",
                citations=(9,),
                rationale="b bad",
            ),
        ],
    )
    (bundle / "verdicts.json").write_text(json.dumps(verdicts), encoding="utf-8")
    report, warnings = fold.fold_report(*_load(bundle))
    assert warnings == ()
    result = next(r for r in report.results if r.id == JUDGEY)
    by_path = {c.session_path: c for c in result.cells}
    assert by_path[path_a].status == "satisfied"
    assert by_path[path_b].status == "violated" and by_path[path_b].entries == (9,)


# --------------------------------------------------------------- validate() invariants


def _minimal_bundle(tmp_path: Path) -> Path:
    det = _deterministic([_result(JUDGEY, [_cell("s1.jsonl")])])
    manifest = _manifest({JUDGEY: [_pair(JUDGEY, "s1.jsonl")]})
    bundle = _write_bundle(tmp_path, deterministic=det, manifest=manifest, verdicts=None)
    verdicts = _verdicts(bundle, [_lane(JUDGEY, "s1.jsonl", rationale="ok")])
    (bundle / "verdicts.json").write_text(json.dumps(verdicts), encoding="utf-8")
    return bundle


def _rewrite(bundle: Path, name: str, mutate) -> None:
    payload = json.loads((bundle / name).read_text(encoding="utf-8"))
    mutate(payload)
    (bundle / name).write_text(json.dumps(payload), encoding="utf-8")


def test_validate_false_success_headers(tmp_path: Path):
    bundle = _minimal_bundle(tmp_path)
    _rewrite(bundle, "deterministic.json", lambda p: p.update(success=False))
    with pytest.raises(fold.BundleError, match="success header"):
        fold.load_deterministic(bundle)
    bundle2 = _minimal_bundle(tmp_path / "b2")
    _rewrite(bundle2, "manifest.json", lambda p: p.update(success=False))
    with pytest.raises(fold.BundleError, match="success header"):
        fold.load_manifest(bundle2)


def test_validate_wrong_flow(tmp_path: Path):
    bundle = _minimal_bundle(tmp_path)
    _rewrite(bundle, "verdicts.json", lambda p: p.update(flow="learn"))
    with pytest.raises(fold.BundleError, match="flow is 'learn'"):
        fold.load_verdicts(bundle)


def test_validate_foreign_bundle_dir(tmp_path: Path):
    bundle = _minimal_bundle(tmp_path)
    _rewrite(bundle, "verdicts.json", lambda p: p.update(bundle_dir="/somewhere/else"))
    with pytest.raises(fold.BundleError, match="copied/foreign"):
        fold.load_verdicts(bundle)


def test_validate_unknown_vocabularies(tmp_path: Path):
    bundle = _minimal_bundle(tmp_path)
    _rewrite(
        bundle,
        "deterministic.json",
        lambda p: p["results"][0]["cells"][0].update(status="mystery"),
    )
    with pytest.raises(fold.BundleError, match="unknown cell status 'mystery'"):
        fold.load_deterministic(bundle)

    bundle2 = _minimal_bundle(tmp_path / "b2")
    _rewrite(
        bundle2,
        "deterministic.json",
        lambda p: p["results"][0]["cells"][0].update(reason="whimsy"),
    )
    with pytest.raises(fold.BundleError, match="unknown unchecked reason 'whimsy'"):
        fold.load_deterministic(bundle2)

    bundle3 = _minimal_bundle(tmp_path / "b3")
    _rewrite(
        bundle3,
        "manifest.json",
        lambda p: p["results"][0]["pairs"][0].update(status="vaporized"),
    )
    with pytest.raises(fold.BundleError, match="unknown pair status 'vaporized'"):
        fold.load_manifest(bundle3)

    bundle4 = _minimal_bundle(tmp_path / "b4")
    _rewrite(bundle4, "verdicts.json", lambda p: p["lanes"][0].update(status="exploded"))
    with pytest.raises(fold.BundleError, match="unknown lane status 'exploded'"):
        fold.load_verdicts(bundle4)

    bundle5 = _minimal_bundle(tmp_path / "b5")
    _rewrite(bundle5, "verdicts.json", lambda p: p["lanes"][0].update(verdict="guilty"))
    with pytest.raises(fold.BundleError, match="unknown verdict 'guilty'"):
        fold.load_verdicts(bundle5)

    bundle6 = _minimal_bundle(tmp_path / "b6")
    _rewrite(bundle6, "verdicts.json", lambda p: p["lanes"][0].update(confidence="total"))
    with pytest.raises(fold.BundleError, match="unknown confidence 'total'"):
        fold.load_verdicts(bundle6)

    bundle7 = _minimal_bundle(tmp_path / "b7")
    _rewrite(
        bundle7,
        "verdicts.json",
        lambda p: p["lanes"][0].update(verdict=None, confidence=None),
    )
    with pytest.raises(fold.BundleError, match="must carry a verdict and a confidence"):
        fold.load_verdicts(bundle7)


def test_validate_duplicate_identities(tmp_path: Path):
    bundle = _minimal_bundle(tmp_path)
    _rewrite(
        bundle,
        "deterministic.json",
        lambda p: p["results"][0]["cells"].append(p["results"][0]["cells"][0]),
    )
    with pytest.raises(fold.BundleError, match="duplicate cell identity"):
        fold.load_deterministic(bundle)

    bundle2 = _minimal_bundle(tmp_path / "b2")
    _rewrite(
        bundle2,
        "manifest.json",
        lambda p: p["results"][0]["pairs"].append(p["results"][0]["pairs"][0]),
    )
    with pytest.raises(fold.BundleError, match="duplicate pair identity"):
        fold.load_manifest(bundle2)

    bundle3 = _minimal_bundle(tmp_path / "b3")
    _rewrite(bundle3, "verdicts.json", lambda p: p["lanes"].append(p["lanes"][0]))
    with pytest.raises(fold.BundleError, match="duplicate lane identity"):
        fold.load_verdicts(bundle3)

    # Cell-identity uniqueness spans the WHOLE artifact: a second result row repeating the
    # same expectation id + session_path must also reach bad_bundle (the fold would
    # otherwise fold/count one lane twice).
    bundle4 = _minimal_bundle(tmp_path / "b4")
    _rewrite(
        bundle4,
        "deterministic.json",
        lambda p: p["results"].append(json.loads(json.dumps(p["results"][0]))),
    )
    with pytest.raises(fold.BundleError, match="duplicate cell identity"):
        fold.load_deterministic(bundle4)


def test_missing_artifacts_name_the_producing_command(tmp_path: Path):
    bundle = (tmp_path / "empty").resolve()
    bundle.mkdir()
    with pytest.raises(fold.BundleError, match=r"deterministic\.json missing.*audit judge"):
        fold.load_deterministic(bundle)
    with pytest.raises(fold.BundleError, match=r"manifest\.json missing.*audit judge"):
        fold.load_manifest(bundle)
    with pytest.raises(fold.BundleError, match=r"verdicts\.json missing.*run_audit_wave"):
        fold.load_verdicts(bundle)


def test_unparseable_artifact_is_bundle_error(tmp_path: Path):
    bundle = (tmp_path / "junk").resolve()
    bundle.mkdir()
    (bundle / "deterministic.json").write_text("not json", encoding="utf-8")
    with pytest.raises(fold.BundleError, match="unreadable/unparseable"):
        fold.load_deterministic(bundle)
    (bundle / "manifest.json").write_text('{"success": "not-a-usable-shape"', encoding="utf-8")
    with pytest.raises(fold.BundleError, match="unreadable/unparseable"):
        fold.load_manifest(bundle)
    (bundle / "verdicts.json").write_text('["wrong shape"]', encoding="utf-8")
    with pytest.raises(fold.BundleError, match="ill-shaped"):
        fold.load_verdicts(bundle)


def test_invalid_utf8_artifact_is_bundle_error(tmp_path: Path):
    # Invalid UTF-8 raises UnicodeDecodeError from read_text BEFORE json.loads runs — it must
    # land in the same typed bad_bundle arm, never an unhandled traceback.
    bundle = (tmp_path / "binary").resolve()
    bundle.mkdir()
    (bundle / "deterministic.json").write_bytes(b'{"success": \xff\xfe true}')
    with pytest.raises(fold.BundleError, match="unreadable/unparseable"):
        fold.load_deterministic(bundle)


# ------------------------------------------------------------------------------ CLI


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, timeout=60, capture_output=True)


@pytest.fixture
def cli_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    monkeypatch.chdir(repo)
    return repo


def test_cli_fold_json_envelope_matches_audit_run(cli_repo: Path, tmp_path: Path):
    bundle = _matrix_bundle(tmp_path)
    result = CliRunner().invoke(cli, ["audit", "fold", "--bundle", str(bundle), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    # The folded --json is the UNCHANGED AuditReportOut envelope — key set identical
    # to `audit run`'s.
    assert set(payload) == set(AuditReportOut.model_fields)
    assert payload["success"] is True and payload["error_type"] is None
    by_id = {r["id"]: r for r in payload["results"]}
    statuses = {c["session_basename"]: c["status"] for c in by_id[JUDGEY]["cells"]}
    assert statuses["s1.jsonl"] == "satisfied"
    assert statuses["s2.jsonl"] == "violated"
    # The orphan-lane warning rides stderr (user_output), never the stdout envelope.
    assert "orphan.jsonl" in result.stderr


def test_cli_fold_human_render(cli_repo: Path, tmp_path: Path):
    bundle = _matrix_bundle(tmp_path)
    result = CliRunner().invoke(cli, ["audit", "fold", "--bundle", str(bundle)])
    assert result.exit_code == 0, result.output
    out = " ".join(result.stderr.split())
    assert f"folded audit report — bundle: {bundle}" in out
    assert "lead, not proof" in out
    assert "judgment leads (leads, not proofs — human triage):" in out
    assert "unchecked breakdown:" in out
    assert "lane-failed 3" in out and "auditor-unclear 2" in out
    assert "unboundable 1" in out and "not-sampled 1" in out
    assert "warning:" in out and "orphan.jsonl" in out


def test_cli_fold_bad_bundle_arms(cli_repo: Path, tmp_path: Path):
    empty = tmp_path / "nothing"
    empty.mkdir()
    result = CliRunner().invoke(cli, ["audit", "fold", "--bundle", str(empty), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False and payload["error_type"] == "bad_bundle"
    assert "deterministic.json" in payload["message"]
    assert "audit judge" in payload["message"]

    # deterministic + manifest present, verdicts absent → the wave-naming arm.
    bundle = _minimal_bundle(tmp_path / "half")
    (bundle / "verdicts.json").unlink()
    result = CliRunner().invoke(cli, ["audit", "fold", "--bundle", str(bundle), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_type"] == "bad_bundle"
    assert "run_audit_wave" in payload["message"]


def test_cli_fold_not_a_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    outside = tmp_path / "no-repo"
    outside.mkdir()
    monkeypatch.chdir(outside)
    result = CliRunner().invoke(cli, ["audit", "fold", "--json"])
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error_type"] == "not_a_repo"
