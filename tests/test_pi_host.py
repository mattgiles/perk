"""The PATH `pi` admission: the pure decision, the bounded probe, the refusal texts (§8.76)."""

import ast
import json
import re
import subprocess
from pathlib import Path

import pytest
from _pi_layout import CODEMODE, INCIDENT_DETAIL, MCP, install_fake_pi

from perk.run import workflow_artifacts
from perk.substrate import pi_host
from perk.substrate.host_floor import load_host_floor, required_pi_version
from perk.substrate.pi_host import (
    PI_ADOPTED_VERSION,
    PI_COMPANION_PACKAGES,
    PI_INSTALL_COMMAND,
    PI_INSTALL_SPECS,
    PI_NPM_SPEC,
    PI_VERSION_PROBE_TIMEOUT,
    PiHost,
    admit_pi_companions,
    admit_pi_version,
    format_pi_refusal,
    locate_pi_package,
    pi_refusal_error_type,
    probe_pi_host,
    resolve_companions,
)
from perk.substrate.proc import ProcFailure
from perk.substrate.semver import Semver, parse_semver, satisfies_floor

REPO_ROOT = Path(__file__).resolve().parents[1]
FLOOR = Semver(1, 0, 0)
PI = "/opt/bin/pi"


PINNED_INSTALL_COMMAND = "npm install -g @earendil-works/pi-coding-agent@1.4.0"


def test_install_command_is_the_pinned_set() -> None:
    assert PI_INSTALL_COMMAND == PINNED_INSTALL_COMMAND
    assert PI_VERSION_PROBE_TIMEOUT == 20
    assert (f"{PI_NPM_SPEC}@{PI_ADOPTED_VERSION}",) == PI_INSTALL_SPECS
    assert PI_COMPANION_PACKAGES == (
        "@earendil-works/pi-agent-core",
        "@earendil-works/pi-ai",
        "@earendil-works/pi-codemode",
        "@earendil-works/pi-mcp",
        "@earendil-works/pi-telemetry",
        "@earendil-works/pi-tui",
    )
    assert list(PI_COMPANION_PACKAGES) == sorted(PI_COMPANION_PACKAGES)
    adopted = parse_semver(PI_ADOPTED_VERSION)
    assert adopted is not None
    assert str(adopted) == PI_ADOPTED_VERSION  # a plain release: no `v`, prerelease or build
    assert adopted.prerelease == ()
    assert satisfies_floor(adopted, required_pi_version(load_host_floor()))


def _family_keys(deps: dict[str, str]) -> set[str]:
    return {dep for dep in deps if dep.startswith("@earendil-works/")}


def test_pinned_install_family_is_closed_against_the_characterized_lockfile() -> None:
    # The committed lockfile is the characterized graph: its top-level `@earendil-works/*` entries
    # are exactly the pinned set (names), and every family range those entries declare names a
    # member (closure) — a companion added or dropped upstream fails here before it can float.
    lock = json.loads((REPO_ROOT / "package-lock.json").read_text(encoding="utf-8"))
    packages: dict[str, dict] = lock["packages"]
    top = {
        key.removeprefix("node_modules/"): entry
        for key, entry in packages.items()
        if re.fullmatch(r"node_modules/@earendil-works/[^/]+", key)
    }
    family = {PI_NPM_SPEC, *PI_COMPANION_PACKAGES}
    assert set(top) == family
    for name, entry in top.items():
        declared = _family_keys(entry.get("dependencies", {}))
        assert declared <= family, (name, declared - family)
        peers = _family_keys(entry.get("peerDependencies", {}))
        assert not peers, (name, peers)


def test_the_family_declares_itself_exactly_in_the_characterized_lockfile() -> None:
    # The single-spec install's premise, kept apart from the closed-names test on purpose: every
    # family member sits at the adopted version and declares each `@earendil-works/*` dependency at
    # exactly that version (no `^`/`~`). A Pi that returns to ranged declarations fails here — the
    # one exact spec would then float its companions and the install must name the family again.
    lock = json.loads((REPO_ROOT / "package-lock.json").read_text(encoding="utf-8"))
    packages: dict[str, dict] = lock["packages"]
    top = {
        key.removeprefix("node_modules/"): entry
        for key, entry in packages.items()
        if re.fullmatch(r"node_modules/@earendil-works/[^/]+", key)
    }
    assert set(top) == {PI_NPM_SPEC, *PI_COMPANION_PACKAGES}
    for name, entry in top.items():
        assert entry["version"] == PI_ADOPTED_VERSION, (name, entry["version"])
        deps: dict[str, str] = entry.get("dependencies", {})
        ranged = {dep: deps[dep] for dep in _family_keys(deps) if deps[dep] != PI_ADOPTED_VERSION}
        assert not ranged, (name, ranged)


def test_remote_install_pin_is_the_adopted_pin() -> None:
    assert workflow_artifacts.REMOTE_PI_VERSION == PI_ADOPTED_VERSION
    assert workflow_artifacts._PI_GLOBAL_INSTALL == PI_INSTALL_COMMAND


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
    assert admit_pi_version(PI, "1.1.0\n", floor).outcome == "unsupported"
    assert admit_pi_version(PI, "1.3.0\n", floor).outcome == "unsupported"
    assert admit_pi_version(PI, "1.4.0-rc.1\n", floor).outcome == "unsupported"
    at_floor = admit_pi_version(PI, "1.4.0\n", floor)
    assert at_floor.outcome == "admitted"
    assert at_floor.observed == "1.4.0"
    later = admit_pi_version(PI, "1.5.0\n", floor)
    assert later.outcome == "admitted"
    assert later.observed == "1.5.0"
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


def test_admission_never_reads_the_repos_dev_sdk_install() -> None:
    # The launch preflight delegates every read to the probe; the probe's companion read is
    # anchored at the resolved executable — it never consults the working directory (where the
    # repo's dev SDK install lives).
    strings = _code_strings(REPO_ROOT / "src/perk/run/pi_exec.py")
    assert strings
    assert not [s for s in strings if "package.json" in s or "node_modules" in s]
    source = (REPO_ROOT / "src/perk/substrate/pi_host.py").read_text(encoding="utf-8")
    assert "cwd" not in source
    assert "getcwd" not in source


# --- the companion family ------------------------------------------------------------------


@pytest.fixture
def broken_pi_layout(tmp_path: Path) -> str:
    return str(install_fake_pi(tmp_path / "broken", broken=True))


@pytest.fixture
def repaired_pi_layout(tmp_path: Path) -> str:
    return str(install_fake_pi(tmp_path / "repaired"))


def test_admit_companions_all_adopted_is_coherent() -> None:
    assert admit_pi_companions(dict.fromkeys(PI_COMPANION_PACKAGES, PI_ADOPTED_VERSION)) == ""


def test_admit_companions_lists_every_offender_in_family_order() -> None:
    resolved: dict[str, str | None] = dict.fromkeys(PI_COMPANION_PACKAGES, PI_ADOPTED_VERSION)
    resolved[MCP] = "1.5.0"
    resolved[CODEMODE] = None
    assert admit_pi_companions(resolved) == INCIDENT_DETAIL


def test_admit_companions_counts_an_unlisted_name_as_unresolved() -> None:
    assert admit_pi_companions({}) == ", ".join(
        f"{name} does not resolve" for name in PI_COMPANION_PACKAGES
    )


def test_locate_follows_the_bin_symlink_to_the_package(broken_pi_layout: str) -> None:
    package = locate_pi_package(broken_pi_layout)
    assert package is not None
    assert (
        package
        == (Path(broken_pi_layout).parent.parent / "lib/node_modules" / PI_NPM_SPEC).resolve()
    )


def test_locate_is_none_for_a_bare_script(tmp_path: Path) -> None:
    assert locate_pi_package(_script(tmp_path, "echo 1.4.0")) is None
    assert locate_pi_package(str(tmp_path / "absent-pi")) is None


def test_resolve_prefers_the_nested_copy_and_reports_the_dangling_link(
    broken_pi_layout: str,
) -> None:
    package = locate_pi_package(broken_pi_layout)
    assert package is not None
    # A global-root sibling at the adopted version does not shadow the nested copy.
    sibling = package.parent.parent / MCP
    sibling.mkdir(parents=True)
    (sibling / "package.json").write_text(
        json.dumps({"name": MCP, "version": PI_ADOPTED_VERSION}), encoding="utf-8"
    )
    resolved = resolve_companions(Path(broken_pi_layout).resolve().parent)
    assert list(resolved) == list(PI_COMPANION_PACKAGES)
    assert resolved[CODEMODE] is None
    assert resolved[MCP] == "1.5.0"
    others = {name: v for name, v in resolved.items() if name not in {CODEMODE, MCP}}
    assert set(others.values()) == {PI_ADOPTED_VERSION}


def test_resolve_reads_a_versionless_manifest_as_unresolved(repaired_pi_layout: str) -> None:
    package = locate_pi_package(repaired_pi_layout)
    assert package is not None
    (package.parent.parent / "@earendil-works/pi-tui/package.json").write_text(
        "[]", encoding="utf-8"
    )
    resolved = resolve_companions(Path(repaired_pi_layout).resolve().parent)
    assert resolved["@earendil-works/pi-tui"] is None


def test_a_nested_directory_without_a_manifest_shadows_the_outer_copy(
    repaired_pi_layout: str,
) -> None:
    # Node's ESM lookup stops at the first existing package directory; it never falls through to
    # the healthy global-root sibling, so neither may the probe.
    package = locate_pi_package(repaired_pi_layout)
    assert package is not None
    (package / "node_modules" / CODEMODE).mkdir(parents=True)
    resolved = resolve_companions(Path(repaired_pi_layout).resolve().parent)
    assert resolved[CODEMODE] is None
    host = probe_pi_host(repaired_pi_layout)
    assert (host.outcome, host.detail) == ("incoherent", f"{CODEMODE} does not resolve")


def test_real_probe_of_the_broken_layout_is_incoherent(
    broken_pi_layout: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The repo root holds a dev SDK install; the probe still reads only the executable's graph.
    monkeypatch.chdir(REPO_ROOT)
    host = probe_pi_host(broken_pi_layout)
    assert host == PiHost(broken_pi_layout, "incoherent", "1.4.0", "1.4.0", INCIDENT_DETAIL)
    assert pi_refusal_error_type(host) == "pi_companions_incoherent"


def test_real_probe_of_the_repaired_layout_is_admitted(repaired_pi_layout: str) -> None:
    host = probe_pi_host(repaired_pi_layout)
    assert host == PiHost(repaired_pi_layout, "admitted", "1.4.0", "1.4.0", "")


def test_an_admitted_non_adopted_version_is_not_family_checked(
    broken_pi_layout: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable(executable: str) -> Path | None:
        raise AssertionError("the family is read only for the adopted version")

    monkeypatch.setattr(pi_host, "locate_pi_package", unreachable)
    monkeypatch.setattr(pi_host, "run_captured", lambda argv, *, timeout: _completed(0, "1.5.0"))
    host = probe_pi_host(broken_pi_layout)
    assert (host.outcome, host.observed, host.detail) == ("admitted", "1.5.0", "")


def test_an_adopted_pi_outside_any_package_is_unverifiable(tmp_path: Path) -> None:
    executable = _script(tmp_path, f"echo {PI_ADOPTED_VERSION}")
    host = probe_pi_host(executable)
    realpath = Path(executable).resolve()
    assert (host.outcome, host.observed) == ("unverifiable", None)
    assert host.detail == (
        f"pi at {executable} resolves to {realpath}, which is not inside an installed "
        f"{PI_NPM_SPEC} package"
    )
    assert pi_refusal_error_type(host) == "pi_version_unverifiable"


def test_incoherent_refusal_text_and_error_type() -> None:
    host = PiHost(PI, "incoherent", "1.4.0", "1.4.0", INCIDENT_DETAIL)
    assert format_pi_refusal(host) == (
        "pi at /opt/bin/pi is Pi 1.4.0, but its companion packages are not the 1.4.0 family: "
        f"{INCIDENT_DETAIL}. perk requires the matching family — run: perk doctor --fix "
        f"(it runs: {PINNED_INSTALL_COMMAND})."
    )
    assert pi_refusal_error_type(host) == "pi_companions_incoherent"


# --- the bounded probe -----------------------------------------------------------------------


def _completed(rc: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["pi", "--version"], rc, stdout, stderr)


def test_probe_runs_version_once_with_the_bounded_timeout(
    monkeypatch: pytest.MonkeyPatch, repaired_pi_layout: str
) -> None:
    calls: list[tuple[list[str], int]] = []

    def fake_run(argv: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append((list(argv), timeout))
        return _completed(0, "1.4.0\n")

    monkeypatch.setattr(pi_host, "run_captured", fake_run)
    host = probe_pi_host(repaired_pi_layout)  # no floor argument: the bundled floor
    assert calls == [([repaired_pi_layout, "--version"], 20)]
    assert host == PiHost(repaired_pi_layout, "admitted", "1.4.0", "1.4.0", "")


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
        f"{PINNED_INSTALL_COMMAND} — perk init and perk doctor report the same requirement."
    )
    assert pi_refusal_error_type(host) == "pi_version_unsupported"


def test_unverifiable_refusal_text_and_error_type() -> None:
    host = admit_pi_version(PI, "latest\n", FLOOR)
    assert format_pi_refusal(host) == (
        "could not verify the Pi version of /opt/bin/pi (pi --version printed 'latest' instead "
        f"of a version); perk requires Pi >= 1.0.0. Reinstall it: {PINNED_INSTALL_COMMAND}."
    )
    assert pi_refusal_error_type(host) == "pi_version_unverifiable"
