"""`perk-dev audit judge` — the seeded judgment-wave cold door (door + seed + bundle).

`launch.launch_stage` is stubbed on its defining module (no `exec pi`), the
test_learn_harvest_cmd.py pattern; the synthetic corpus rides the test_perk_dev_bounding.py
scaffolding style (a fake repo + encoded session dir + a grill-exercising session). The door's
contract (contracts.md §8.50): one coherent census → full deterministic report → bundle pass,
the pinned bundle-root artifact sequence (manifest → deterministic.json → stale-verdicts
unlink) materialized in EVERY mode (only the launch is dry-run-gated), and the absolute
`audit_bundle_dir` handoff binding.
"""

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from perk_dev.audit.corpus import encode_session_dir
from perk_dev.cli import cli

from perk.run import launch

GRILL = "plan.grill-before-review"
JUDGMENT_IDS = {GRILL, "engagement.untrusted-as-data", "objective-plan.route-explorer-report"}

DRY_RUN_PAYLOAD_KEYS = {
    "success",
    "error_type",
    "bundle_dir",
    "deterministic_path",
    "manifest_path",
    "packetized",
    "expectations",
    "launched",
}

# ------------------------------------------------------------------------- fixtures


def _ws(**data: object) -> dict[str, object]:
    return {"type": "custom", "customType": "perk:workflow-state", "data": data}


def _user(text: str) -> dict[str, object]:
    return {
        "type": "message",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


def _assistant_call(name: str, args: dict[str, object]) -> dict[str, object]:
    return {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [{"type": "toolCall", "name": name, "arguments": args}],
        },
    }


def _tool_result(tool: str, text: str = "") -> dict[str, object]:
    return {
        "type": "message",
        "message": {
            "role": "toolResult",
            "toolName": tool,
            "content": [{"type": "text", "text": text}],
        },
    }


class Env:
    """A tmp corpus environment: a git-init'd fake repo + its encoded session dir."""

    def __init__(self, tmp_path: Path) -> None:
        self.main_root = (tmp_path / "repo").resolve()
        self.main_root.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.main_root, check=True, timeout=30)
        self.sessions_root = tmp_path / "sessions"
        self.main_dir = self.sessions_root / encode_session_dir(str(self.main_root))

    def write_grill_session(self, name: str = "g.jsonl") -> Path:
        """A stage:plan session exercising the committed grill judgment expectation."""
        self.main_dir.mkdir(parents=True, exist_ok=True)
        entries: list[dict[str, object]] = [
            {
                "type": "session",
                "version": 3,
                "id": name.removesuffix(".jsonl"),
                "cwd": str(self.main_root),
            },
            _ws(run_id="01G", stage="plan", perk_version="2.3.0"),
            _user("please plan this"),
            _assistant_call("plan_draft", {"title": "t"}),
            _tool_result("plan_draft", "ok"),
        ]
        path = self.main_dir / name
        path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
        return path


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    e = Env(tmp_path)
    e.write_grill_session()
    monkeypatch.chdir(e.main_root)
    return e


def _stub_launch(monkeypatch: pytest.MonkeyPatch, sink: dict[str, object]) -> None:
    monkeypatch.setattr(
        launch,
        "launch_stage",
        lambda **k: sink.update(
            stage=k["stage"].id,
            mode=k["stage"].mode,
            prompt=k.get("prompt_override"),
            handoff_extra=k.get("handoff_extra"),
            binding_trigger=k.get("binding_trigger"),
            run_id_override=k.get("run_id_override"),
        ),
    )


def _judge(env: Env, *args: str):
    """Invoke the judge verb; JSON payloads ride stdout (the door narrates on stderr)."""
    return CliRunner().invoke(
        cli, ["audit", "judge", "--sessions-root", str(env.sessions_root), *args]
    )


def _default_bundle_dir(env: Env) -> Path:
    return (env.main_root / ".perk" / "workflow" / "scratch" / "audit-evidence").resolve()


# ------------------------------------------------------------------ dry-run + payload


def test_dry_run_json_payload_keys_and_values(env: Env):
    result = _judge(env, "--dry-run", "--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert set(payload) == DRY_RUN_PAYLOAD_KEYS
    assert payload["success"] is True and payload["error_type"] is None
    assert payload["launched"] is False
    # Integers in the payload; decimal strings only in the seed vars.
    assert payload["packetized"] == 1
    assert payload["expectations"] == len(JUDGMENT_IDS)
    bundle_dir = _default_bundle_dir(env)
    assert payload["bundle_dir"] == str(bundle_dir)
    assert payload["deterministic_path"] == str(bundle_dir / "deterministic.json")
    assert payload["manifest_path"] == str(bundle_dir / "manifest.json")


def test_dry_run_materializes_the_full_bundle_and_shows_the_seed(env: Env):
    # Gather materializes the coherent bundle in EVERY mode — only the launch is skipped.
    result = _judge(env, "--dry-run")
    assert result.exit_code == 0, result.output
    bundle_dir = _default_bundle_dir(env)
    assert (bundle_dir / "manifest.json").is_file()
    assert (bundle_dir / "deterministic.json").is_file()
    assert "seed prompt" in result.output  # dry_run_shows_seed=True
    assert "audit judge --dry-run" in result.output


def test_dry_run_unlinks_stale_verdicts(env: Env):
    # A rebuilt bundle must never let `audit fold` consume a prior snapshot's verdicts.
    bundle_dir = _default_bundle_dir(env)
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "verdicts.json").write_text('{"stale": true}', encoding="utf-8")
    result = _judge(env, "--dry-run")
    assert result.exit_code == 0, result.output
    assert not (bundle_dir / "verdicts.json").exists()
    assert (bundle_dir / "manifest.json").is_file()
    assert (bundle_dir / "deterministic.json").is_file()


# ------------------------------------------------------------------- the happy path


def test_happy_path_fresh_out_dir_launches_the_audit_stage(
    env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    sink: dict[str, object] = {}
    _stub_launch(monkeypatch, sink)
    out_dir = tmp_path / "fresh-bundle"  # genuinely fresh: no preseeded fixture
    assert not out_dir.exists()
    result = _judge(env, "--out", str(out_dir))
    assert result.exit_code == 0, result.output

    # Both bundle-root artifacts written; deterministic.json is the audit-run envelope.
    resolved = out_dir.resolve()
    manifest = json.loads((resolved / "manifest.json").read_text(encoding="utf-8"))
    deterministic = json.loads((resolved / "deterministic.json").read_text(encoding="utf-8"))
    assert manifest["success"] is True
    assert deterministic["success"] is True and deterministic["error_type"] is None
    # The deterministic report is always FULL — never narrowed to the judgment tier.
    assert deterministic["deterministic_count"] > 0

    # The structural write binding: the handoff carries the ABSOLUTE bundle dir.
    assert sink["stage"] == "audit"
    assert sink["mode"] == "read-only"
    assert sink["binding_trigger"] is None
    assert sink["run_id_override"] is None
    handoff_extra = sink["handoff_extra"]
    assert isinstance(handoff_extra, dict)
    assert handoff_extra == {"audit_bundle_dir": str(resolved)}
    assert resolved.is_absolute()


def test_seed_contains_summary_bundle_dir_fold_callout_and_no_arg_drive(
    env: Env, monkeypatch: pytest.MonkeyPatch
):
    sink: dict[str, object] = {}
    _stub_launch(monkeypatch, sink)
    result = _judge(env)
    assert result.exit_code == 0, result.output
    seed = sink["prompt"]
    assert isinstance(seed, str)
    bundle_dir = _default_bundle_dir(env)
    assert str(bundle_dir) in seed
    # The injected deterministic summary rides the shared unstyled render-line builder.
    assert "confirmed sessions: 1" in seed
    assert "verdicts:" in seed
    # The no-argument tool drive + the copyable fold callout (unquoted — no specials).
    assert "`run_audit_wave`" in seed
    assert "with no arguments" in seed
    assert f"perk-dev audit fold --bundle {bundle_dir}" in seed


def test_fold_callout_is_shell_quoted_for_a_spacey_bundle_path(
    env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # The callout is explicitly advertised as copyable — a bundle path with spaces must
    # survive a paste as ONE shell token (shlex.join door-side).
    sink: dict[str, object] = {}
    _stub_launch(monkeypatch, sink)
    out_dir = tmp_path / "bundle with spaces"
    result = _judge(env, "--out", str(out_dir))
    assert result.exit_code == 0, result.output
    seed = sink["prompt"]
    assert isinstance(seed, str)
    assert f"perk-dev audit fold --bundle '{out_dir.resolve()}'" in seed


def test_relative_out_resolves_against_the_invocation_cwd(
    env: Env, monkeypatch: pytest.MonkeyPatch
):
    # `--out` resolves ONCE, absolute, at gather time — launch_stage changes cwd before pi
    # runs, so a relative spelling would otherwise dangle.
    nested = env.main_root / "sub" / "dir"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    result = _judge(env, "--dry-run", "--json", "--out", "rel-bundle")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    expected = (nested / "rel-bundle").resolve()
    assert payload["bundle_dir"] == str(expected)
    assert Path(payload["bundle_dir"]).is_absolute()
    assert (expected / "manifest.json").is_file()
    assert (expected / "deterministic.json").is_file()


def test_one_census_coherence_manifest_pairs_subset_of_deterministic_cells(env: Env):
    # The manifest and deterministic.json derive from the SAME census: every manifest pair
    # identity appears among that expectation's deterministic judgment cells.
    result = _judge(env, "--dry-run")
    assert result.exit_code == 0, result.output
    bundle_dir = _default_bundle_dir(env)
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    deterministic = json.loads((bundle_dir / "deterministic.json").read_text(encoding="utf-8"))
    det_cells = {
        (result["id"], cell["session_path"])
        for result in deterministic["results"]
        for cell in result["cells"]
    }
    manifest_pairs = {
        (pair["expectation_id"], pair["session_path"])
        for result in manifest["results"]
        for pair in result["pairs"]
    }
    assert manifest_pairs, "the grill session must produce at least one pair"
    assert manifest_pairs <= det_cells
    # And the exercised pair is a judgment-tier cell awaiting the fold.
    grill = next(r for r in deterministic["results"] if r["id"] == GRILL)
    assert grill["cells"][0]["status"] == "unchecked"
    assert grill["cells"][0]["reason"] == "judgment-tier"


# ------------------------------------------------------------------------- fail arms


def test_expectation_filter_narrows_the_bundle_not_the_deterministic_report(env: Env):
    result = _judge(env, "--dry-run", "--json", "--expectation", GRILL)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["expectations"] == 1
    bundle_dir = _default_bundle_dir(env)
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in manifest["results"]] == [GRILL]
    deterministic = json.loads((bundle_dir / "deterministic.json").read_text(encoding="utf-8"))
    assert {r["id"] for r in deterministic["results"]} > JUDGMENT_IDS


def test_unknown_expectation_is_bad_arguments(env: Env):
    result = _judge(env, "--json", "--expectation", "nope.missing")
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "bad_arguments"
    assert "unknown expectation id(s): nope.missing" in payload["message"]
    assert "known judgment ids:" in payload["message"]


def test_deterministic_expectation_is_bad_arguments_naming_tier(env: Env):
    result = _judge(env, "--json", "--expectation", "plan.draft-before-review")
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "bad_arguments"
    assert "not judgment-tier" in payload["message"]
    assert "plan.draft-before-review (tier: deterministic)" in payload["message"]


def test_max_sessions_zero_is_bad_arguments(env: Env):
    result = _judge(env, "--json", "--max-sessions", "0")
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "bad_arguments"
    assert "--max-sessions must be >= 1" in payload["message"]


def test_remote_is_rejected(env: Env):
    # The audit stage is cold_remote:false — `--remote` is refused before any side effect.
    result = _judge(env, "--json", "--remote")
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "remote_blocked"
    assert not _default_bundle_dir(env).exists()


def test_unwritable_out_is_io_error(env: Env, tmp_path: Path):
    blocked = tmp_path / "blocked"
    blocked.write_text("a file, not a dir", encoding="utf-8")
    result = _judge(env, "--json", "--out", str(blocked / "bundle"))
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "io_error"
    assert "unusable until a successful re-run" in payload["message"]


def test_not_a_repo_exits_two(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bare = tmp_path / "bare"
    bare.mkdir()
    monkeypatch.chdir(bare)
    result = CliRunner().invoke(cli, ["audit", "judge", "--json"])
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "not_a_repo"
