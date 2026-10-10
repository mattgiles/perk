"""The PATH `pi` admission: the pure decision, the bounded probe, the refusal texts (§8.76)."""

import ast
import json
import subprocess
from pathlib import Path

import pytest

from perk.substrate import pi_host
from perk.substrate.host_floor import load_host_floor, required_pi_version
from perk.substrate.pi_host import (
    PI_INSTALL_COMMAND,
    PI_VERSION_PROBE_TIMEOUT,
    PiHost,
    admit_pi_version,
    format_pi_refusal,
    pi_refusal_error_type,
    probe_pi_host,
)
from perk.substrate.proc import ProcFailure
from perk.substrate.semver import Semver, parse_semver, satisfies_floor

REPO_ROOT = Path(__file__).resolve().parents[1]
FLOOR = Semver(1, 0, 0)
PI = "/opt/bin/pi"


def test_install_command_is_the_global_npm_install() -> None:
    assert PI_INSTALL_COMMAND == "npm install -g @earendil-works/pi-coding-agent"
    assert PI_VERSION_PROBE_TIMEOUT == 20


# --- the pure decision -----------------------------------------------------------------------


@pytest.mark.parametrize("stdout", ["0.99.2\n", "1.0.0-rc.1\n", "0.0.0\n"])
def test_below_the_floor_is_unsupported(stdout: str) -> None:
    host = admit_pi_version(PI, stdout, FLOOR)
    assert host.outcome == "unsupported"
    assert host.observed == stdout.strip()
    assert host.required == "1.0.0"
    assert host.detail == ""


@pytest.mark.parametrize("stdout", ["1.0.0\n", "1.0.3\n", "1.10.0\n", "v2.0.0\n"])
def test_at_or_above_the_floor_is_admitted(stdout: str) -> None:
    host = admit_pi_version(PI, stdout, FLOOR)
    assert host.outcome == "admitted"
    assert host.observed == stdout.strip().lstrip("v")
    assert host.executable == PI


@pytest.mark.parametrize("stdout", ["", "\n", "latest\n", "pi 1.0.0\n"])
def test_malformed_output_is_unverifiable(stdout: str) -> None:
    host = admit_pi_version(PI, stdout, FLOOR)
    assert host.outcome == "unverifiable"
    assert host.observed is None
    assert host.detail == f"pi --version printed {stdout.strip()!r} instead of a version"


def test_a_long_malformed_output_is_truncated_in_the_detail() -> None:
    host = admit_pi_version(PI, "x" * 500, FLOOR)
    assert host.detail == f"pi --version printed {'x' * 80!r} instead of a version"


def test_the_dev_pin_satisfies_the_floor_and_the_cli_is_admitted_independently() -> None:
    # Independent observations against the SHIPPED floor: the committed SDK devDependency
    # satisfies it, yet the launch admission reads only the PATH CLI's own answer — the previous
    # floor and a prerelease of the current one are refused beside the pin, while the floor and an
    # unequal later release are each admitted on their own reading.
    package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    sdk_pin = package["devDependencies"]["@earendil-works/pi-coding-agent"]
    floor = required_pi_version(load_host_floor())
    pinned = parse_semver(sdk_pin)
    assert pinned is not None, sdk_pin
    assert satisfies_floor(pinned, floor), sdk_pin
    assert admit_pi_version(PI, "0.99.2\n", floor).outcome == "unsupported"
    assert admit_pi_version(PI, "1.0.0\n", floor).outcome == "unsupported"
    assert admit_pi_version(PI, "1.1.0-rc.1\n", floor).outcome == "unsupported"
    at_floor = admit_pi_version(PI, "1.1.0\n", floor)
    assert at_floor.outcome == "admitted"
    assert at_floor.observed == "1.1.0"
    later = admit_pi_version(PI, "1.2.0\n", floor)
    assert later.outcome == "admitted"
    assert later.observed == "1.2.0"
    assert later.observed != sdk_pin


def _code_strings(path: Path) -> list[str]:
    """Every string literal in ``path`` except docstrings (prose may name what is NOT read)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_admission_never_reads_the_sdk_install() -> None:
    for relative in ("src/perk/substrate/pi_host.py", "src/perk/run/pi_exec.py"):
        strings = _code_strings(REPO_ROOT / relative)
        assert strings, relative
        assert not [s for s in strings if "package.json" in s or "node_modules" in s], relative


# --- the bounded probe -----------------------------------------------------------------------


def _completed(rc: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["pi", "--version"], rc, stdout, stderr)


def test_probe_runs_version_once_with_the_bounded_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], int]] = []

    def fake_run(argv: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append((list(argv), timeout))
        return _completed(0, "1.1.0\n")

    monkeypatch.setattr(pi_host, "run_captured", fake_run)
    host = probe_pi_host(PI)  # no floor argument: the bundled floor
    assert calls == [([PI, "--version"], 20)]
    assert host == PiHost(PI, "admitted", "1.1.0", "1.1.0", "")


def test_probe_defaults_to_the_bundled_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pi_host, "run_captured", lambda argv, *, timeout: _completed(0, "0.99.2"))
    host = probe_pi_host(PI)
    assert host.outcome == "unsupported"
    assert host.required == load_host_floor().pi_min_version


@pytest.mark.parametrize(
    ("result", "detail"),
    [
        (_completed(3, "", "boom\nfatal: bad\n\n"), "pi --version exited 3: fatal: bad"),
        (_completed(1), "pi --version exited 1: (no output)"),
    ],
)
def test_a_non_zero_exit_is_unverifiable(
    monkeypatch: pytest.MonkeyPatch, result: subprocess.CompletedProcess[str], detail: str
) -> None:
    monkeypatch.setattr(pi_host, "run_captured", lambda argv, *, timeout: result)
    host = probe_pi_host(PI, FLOOR)
    assert (host.outcome, host.observed, host.detail) == ("unverifiable", None, detail)


@pytest.mark.parametrize(
    ("failure", "detail"),
    [
        (ProcFailure("timeout", (PI, "--version")), "pi --version timed out after 20 s"),
        (
            ProcFailure("spawn", (PI, "--version"), cause_text="[Errno 2] No such file"),
            "pi --version could not run: [Errno 2] No such file",
        ),
    ],
)
def test_a_timeout_or_spawn_failure_is_unverifiable(
    monkeypatch: pytest.MonkeyPatch, failure: ProcFailure, detail: str
) -> None:
    def raising(argv: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        raise failure

    monkeypatch.setattr(pi_host, "run_captured", raising)
    host = probe_pi_host(PI, FLOOR)
    assert (host.outcome, host.detail) == ("unverifiable", detail)


def _script(tmp_path: Path, body: str) -> str:
    script = tmp_path / "pi"
    script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    script.chmod(0o755)
    return str(script)


@pytest.mark.parametrize(
    "body",
    [
        r'printf "\377\n"',  # an undecodable byte on stdout, exit 0
        r'printf "\377\n" >&2; exit 1',  # an undecodable byte on stderr, non-zero exit
    ],
)
def test_real_probe_with_undecodable_output_is_unverifiable(tmp_path: Path, body: str) -> None:
    executable = _script(tmp_path, body)
    host = probe_pi_host(executable, FLOOR)
    assert (host.outcome, host.observed) == ("unverifiable", None)
    assert host.detail == "pi --version printed output that is not UTF-8"
    assert pi_refusal_error_type(host) == "pi_version_unverifiable"
    assert executable in format_pi_refusal(host)


def test_probe_against_a_missing_executable_is_unverifiable(tmp_path: Path) -> None:
    host = probe_pi_host(str(tmp_path / "absent-pi"), FLOOR)
    assert host.outcome == "unverifiable"
    assert host.detail.startswith("pi --version could not run: ")


# --- refusal texts + error types -------------------------------------------------------------


def test_unsupported_refusal_text_and_error_type() -> None:
    host = admit_pi_version(PI, "0.99.2\n", FLOOR)
    assert format_pi_refusal(host) == (
        "pi at /opt/bin/pi is version 0.99.2; perk requires Pi >= 1.0.0. Upgrade it: "
        "npm install -g @earendil-works/pi-coding-agent — perk init and perk doctor report the "
        "same requirement."
    )
    assert pi_refusal_error_type(host) == "pi_version_unsupported"


def test_unverifiable_refusal_text_and_error_type() -> None:
    host = admit_pi_version(PI, "latest\n", FLOOR)
    assert format_pi_refusal(host) == (
        "could not verify the Pi version of /opt/bin/pi (pi --version printed 'latest' instead "
        "of a version); perk requires Pi >= 1.0.0. Reinstall it: "
        "npm install -g @earendil-works/pi-coding-agent."
    )
    assert pi_refusal_error_type(host) == "pi_version_unverifiable"
