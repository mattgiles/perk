"""`perk-dev release-build` regression tests.

No real builds and no network: `tests/test_packaging.py` already builds the wheel and runs
`npm pack` in CI (and additionally runs `verify_tarball_files` against the real pack output,
pinning the expected/forbidden sets to reality). Here `build._run` is monkeypatched with a
recorder so the five-step orchestration, the artifact-count gate, and the per-step failure
translation are covered hermetically.
"""

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from perk_dev import build
from perk_dev.cli import cli

_PACK_PAYLOAD = json.dumps([{"files": [{"path": p} for p in sorted(build.NPM_TARBALL_EXPECTED)]}])


class _Recorder:
    """A canned `build._run`: records each call, seeds the fake `--out-dir` on `uv build`."""

    def __init__(self, *, fail_step: str | None = None, wheel_count: int = 1) -> None:
        self.calls: list[list[str]] = []
        self.fail_step = fail_step
        self.wheel_count = wheel_count

    def __call__(self, args: list[str], *, cwd: Path, timeout: int = 600) -> str:
        self.calls.append(list(args))
        step = self._step_of(args)
        if step == self.fail_step:
            raise build.BuildError(f"{args[0]}_failed", f"{' '.join(args)} exploded")
        if step == "uv-build":
            out_dir = Path(args[args.index("--out-dir") + 1])
            for i in range(self.wheel_count):
                (out_dir / f"perk-1.0.{i}-py3-none-any.whl").write_bytes(b"")
            (out_dir / "perk-1.0.0.tar.gz").write_bytes(b"")
        if step == "npm-pack":
            return _PACK_PAYLOAD
        return ""

    @staticmethod
    def _step_of(args: list[str]) -> str:
        if args[:2] == ["uv", "build"]:
            return "uv-build"
        if args[:3] == ["uvx", "twine", "check"]:
            return "twine"
        if args[:2] == ["uvx", "--from"]:
            return "smoke"
        if args[:2] == ["npm", "ci"]:
            return "npm-ci"
        if args[:3] == ["npm", "pack", "--dry-run"]:
            return "npm-pack"
        raise AssertionError(f"unexpected _run call: {args}")


# --- run_build orchestration --------------------------------------------------------


def test_five_step_sequence_and_args(tmp_path, monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(build, "_run", recorder)
    build.run_build(tmp_path)
    steps = [_Recorder._step_of(c) for c in recorder.calls]
    assert steps == ["uv-build", "twine", "smoke", "npm-ci", "npm-pack"]
    uv_build, twine, smoke, npm_ci, npm_pack = recorder.calls
    assert uv_build[:4] == ["uv", "build", "--package", "perk"] and "--out-dir" in uv_build
    assert twine[3].endswith(".whl") and twine[4].endswith(".tar.gz")  # explicit paths
    assert smoke == ["uvx", "--from", twine[3], "perk", "--help"]
    assert npm_ci == ["npm", "ci"]
    assert npm_pack == ["npm", "pack", "--dry-run", "--json"]


def test_wrong_artifact_count_is_uv_build_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "_run", _Recorder(wheel_count=2))
    with pytest.raises(build.BuildError) as exc:
        build.run_build(tmp_path)
    assert exc.value.error_type == "uv_build_failed"


@pytest.mark.parametrize(
    ("fail_step", "error_type"),
    [
        ("uv-build", "uv_build_failed"),
        ("twine", "twine_check_failed"),
        ("smoke", "wheel_smoke_failed"),
        ("npm-ci", "npm_ci_failed"),
        ("npm-pack", "npm_pack_failed"),
    ],
)
def test_per_step_failure_surfaces_via_cli(tmp_path, monkeypatch, fail_step, error_type):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=30)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(build, "_run", _Recorder(fail_step=fail_step))
    result = CliRunner().invoke(cli, ["release-build"])
    assert result.exit_code == 1, result.output
    assert "Error: " in result.stderr
    # The domain error_type is what the recorder's message carries through _fail.
    with pytest.raises(build.BuildError) as exc:
        build.run_build(tmp_path)
    assert exc.value.error_type == error_type


def test_unparseable_pack_output_is_npm_pack_failed(tmp_path, monkeypatch):
    recorder = _Recorder()

    def unparseable(args, *, cwd, timeout=600):
        out = recorder(args, cwd=cwd, timeout=timeout)
        return "not json" if _Recorder._step_of(args) == "npm-pack" else out

    monkeypatch.setattr(build, "_run", unparseable)
    with pytest.raises(build.BuildError) as exc:
        build.run_build(tmp_path)
    assert exc.value.error_type == "npm_pack_failed"


# --- verify_tarball_files (pure) ----------------------------------------------------


def test_verify_clean_set_passes():
    build.verify_tarball_files(set(build.NPM_TARBALL_EXPECTED) | {"README.md"})


def test_verify_missing_expected_names_offenders():
    paths = set(build.NPM_TARBALL_EXPECTED) - {"shared/registry.yaml"}
    with pytest.raises(build.BuildError) as exc:
        build.verify_tarball_files(paths)
    assert exc.value.error_type == "tarball_missing_files"
    assert "shared/registry.yaml" in exc.value.message


@pytest.mark.parametrize(
    "forbidden",
    ["extension/testing/helper.ts", "extension/doors/submit.test.ts", "agents/pr-reviewer.md"],
)
def test_verify_forbidden_present_names_offenders(forbidden):
    paths = set(build.NPM_TARBALL_EXPECTED) | {forbidden}
    with pytest.raises(build.BuildError) as exc:
        build.verify_tarball_files(paths)
    assert exc.value.error_type == "tarball_forbidden_files"
    assert forbidden in exc.value.message


# --- CLI ----------------------------------------------------------------------------


def test_cli_success_message(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=30)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(build, "_run", _Recorder())
    result = CliRunner().invoke(cli, ["release-build"])
    assert result.exit_code == 0, result.output
    assert "release-build OK" in result.stderr


def test_cli_not_a_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["release-build"])
    assert result.exit_code == 2, result.output


def test_release_build_is_registered():
    assert "release-build" in cli.commands
