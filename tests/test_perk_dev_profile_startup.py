"""`perk-dev profile-startup` — the measurement pieces: Pi's timing grammar, the real PTY spawn,
subject specs/preflight/trust/stamps, the Node census analysis, the Python handoff arms.

The PTY cases spawn `sys.executable -c …` children on a real pseudo-terminal (fast tier: every
child prints its marker or is terminated within a sub-second budget). Subject probes are
hermetic: `run_captured` is monkeypatched to canned `--version` outputs and the agent dir is the
suite-wide isolated one.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from perk_dev.profile_startup import subjects as subjects_mod
from perk_dev.profile_startup.pty_session import PtySize, spawn_pty
from perk_dev.profile_startup.subjects import (
    Subject,
    check_trust,
    parse_subject_specs,
    stamp_subject,
)
from perk_dev.profile_startup.timings import TimingsScanner, parse_pi_timings

from perk.cli.ensure import UserFacingCliError
from perk.substrate import git

# --- timings -------------------------------------------------------------------------------------

_FIXTURE_STDERR = """opening a plain Pi session in /tmp/checkout: pi
npm warn deprecated something@1.0.0: use something-else

--- Startup Timings: extensions ---
  /tmp/checkout/.pi/npm/node_modules/@mgiles/perk/extension/index.ts module import: 41ms
  /tmp/checkout/.pi/npm/node_modules/@mgiles/perk/extension/index.ts factory: 3ms
  /tmp/checkout/.pi/extensions/local one.ts module import: 0ms
  TOTAL: 44ms
-----------------------------------


--- Startup Timings: main ---
  imports: 120ms
  createAgentSession: 310ms
  interactiveMode.init: 95ms
  TOTAL: 525ms
-----------------------------

"""


def test_parse_pi_timings_reads_every_group_verbatim():
    groups = parse_pi_timings(_FIXTURE_STDERR)
    assert list(groups) == ["extensions", "main"]
    ext = groups["extensions"]
    assert ext.total_ms == 44
    assert [(r.label, r.ms) for r in ext.rows] == [
        (
            "/tmp/checkout/.pi/npm/node_modules/@mgiles/perk/extension/index.ts module import",
            41,
        ),
        ("/tmp/checkout/.pi/npm/node_modules/@mgiles/perk/extension/index.ts factory", 3),
        ("/tmp/checkout/.pi/extensions/local one.ts module import", 0),
    ]
    # The first row is a real delta since Pi's resetTimings("extensions") — never assumed zero.
    assert ext.rows[0].ms == 41
    main = groups["main"]
    assert main.total_ms == 525
    assert [r.label for r in main.rows] == ["imports", "createAgentSession", "interactiveMode.init"]


def test_parse_pi_timings_drops_an_unterminated_group():
    text = "--- Startup Timings: main ---\n  imports: 12ms\n"
    assert parse_pi_timings(text) == {}


def test_timings_scanner_fires_exactly_once_on_the_main_total():
    scanner = TimingsScanner()
    fired = [line for line in _FIXTURE_STDERR.splitlines() if scanner.feed(line)]
    assert fired == ["  TOTAL: 525ms"]
    # A second report never re-fires; an `extensions` TOTAL never fires.
    assert not any(scanner.feed(line) for line in _FIXTURE_STDERR.splitlines())
    fresh = TimingsScanner()
    assert fresh.feed("--- Startup Timings: extensions ---") is False
    assert fresh.feed("  TOTAL: 44ms") is False
    assert fresh.feed("  TOTAL: 44ms") is False  # outside any group


# --- the real PTY --------------------------------------------------------------------------------

_MARKER_STDERR = (
    "--- Startup Timings: main ---\\n  a: 1ms\\n  TOTAL: 1ms\\n-----------------------------\\n"
)


def _spawn(script: str, *, timeout_s: float = 10.0, exit_grace_s: float = 5.0, size=None):
    return spawn_pty(
        (sys.executable, "-c", script),
        cwd=Path.cwd(),
        env=os.environ,
        size=size if size is not None else PtySize(cols=120, rows=40),
        timeout_s=timeout_s,
        exit_grace_s=exit_grace_s,
        startup_marker=TimingsScanner().feed,
    )


def test_spawn_pty_child_sees_a_sized_controlling_terminal_with_piped_stderr():
    script = (
        "import os, sys\n"
        "print('tty', os.isatty(0), os.isatty(1), os.isatty(2))\n"
        "print('size', tuple(os.get_terminal_size(1)))\n"
        f"sys.stderr.write('{_MARKER_STDERR}')\n"
        "sys.stderr.flush()\n"
        "sys.stdout.write('probe:' + repr((os.isatty(0), os.isatty(1), os.isatty(2), "
        "tuple(os.get_terminal_size(1)))) + chr(10))\n"
        "sys.stderr.write('probe:' + repr((os.isatty(0), os.isatty(1), os.isatty(2), "
        "tuple(os.get_terminal_size(1)))) + chr(10))\n"
    )
    run = _spawn(script, size=PtySize(cols=97, rows=23))
    assert run.exit_code == 0
    assert run.timed_out is False and run.lingered is False
    assert run.elapsed_ms is not None and run.exit_ms is not None
    assert run.exit_ms >= run.elapsed_ms
    assert run.stdout_bytes > 0
    # stderr is a plain pipe: the probe line arrives clean there.
    assert "probe:(True, True, False, (97, 23))" in run.stderr
    assert run.spawn_monotonic_ns > 0


def test_spawn_pty_flags_a_child_that_outlives_its_exit_grace():
    script = (
        "import sys, time\n"
        f"sys.stderr.write('{_MARKER_STDERR}')\n"
        "sys.stderr.flush()\n"
        "time.sleep(30)\n"
    )
    run = _spawn(script, exit_grace_s=0.2)
    assert run.lingered is True
    assert run.timed_out is False
    assert run.elapsed_ms is not None
    assert run.exit_ms is None
    assert run.exit_code is not None and run.exit_code != 0


def test_spawn_pty_kills_a_child_that_never_prints_the_marker():
    run = _spawn("import time\ntime.sleep(30)\n", timeout_s=0.5)
    assert run.timed_out is True
    assert run.lingered is False
    assert run.elapsed_ms is None and run.exit_ms is None


def test_spawn_pty_drains_a_stdout_flood_without_deadlocking():
    script = (
        "import sys\n"
        f"sys.stderr.write('{_MARKER_STDERR}')\n"
        "sys.stdout.write('x' * (3 * 1024 * 1024))\n"
        "sys.stdout.flush()\n"
    )
    run = _spawn(script)
    assert run.exit_code == 0
    assert run.stdout_bytes >= 3 * 1024 * 1024
    assert run.lingered is False and run.timed_out is False


# --- subjects: specs + preflight ----------------------------------------------------------------


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _prepare_checkout(root: Path, *, executable: bool = True, npm: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in ("perk", "python"):
        tool = bin_dir / name
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        if executable:
            tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    if npm:
        (root / ".pi" / "npm" / "node_modules").mkdir(parents=True, exist_ok=True)
        _write_json(root / ".pi" / "npm" / "package.json", {"dependencies": {"pi-subagents": "^1"}})
    return root


def _error_type(exc_info) -> str | None:
    return exc_info.value.error_type


def test_parse_subject_specs_happy_path_resolves_in_order(tmp_path):
    a = _prepare_checkout(tmp_path / "a")
    b = _prepare_checkout(tmp_path / "b")
    subjects = parse_subject_specs([f"main={a}", f"cand.1_x={b}"])
    assert [s.label for s in subjects] == ["main", "cand.1_x"]
    assert subjects[0].checkout == a.resolve()
    assert subjects[0].executable == a.resolve() / ".venv" / "bin" / "perk"
    assert subjects[0].python == a.resolve() / ".venv" / "bin" / "python"


@pytest.mark.parametrize(
    "spec",
    ["nolabel", "=path", "bad label=x", "-lead=x", "ünïcode=x"],
)
def test_parse_subject_specs_refuses_bad_labels(tmp_path, spec):
    with pytest.raises(UserFacingCliError) as exc:
        parse_subject_specs([spec.replace("x", str(tmp_path))])
    assert _error_type(exc) == "bad_arguments"


def test_parse_subject_specs_refuses_duplicate_labels(tmp_path):
    a = _prepare_checkout(tmp_path / "a")
    with pytest.raises(UserFacingCliError) as exc:
        parse_subject_specs([f"same={a}", f"same={a}"])
    assert _error_type(exc) == "bad_arguments"
    assert "twice" in str(exc.value)


def test_parse_subject_specs_missing_directory(tmp_path):
    with pytest.raises(UserFacingCliError) as exc:
        parse_subject_specs([f"x={tmp_path / 'nope'}"])
    assert _error_type(exc) == "subject_missing"


def test_parse_subject_specs_missing_console_script(tmp_path):
    root = tmp_path / "a"
    root.mkdir()
    with pytest.raises(UserFacingCliError) as exc:
        parse_subject_specs([f"x={root}"])
    assert _error_type(exc) == "subject_missing"
    assert "uv sync --all-packages --project" in str(exc.value)


def test_parse_subject_specs_non_executable_console_script(tmp_path):
    root = _prepare_checkout(tmp_path / "a", executable=False)
    with pytest.raises(UserFacingCliError) as exc:
        parse_subject_specs([f"x={root}"])
    assert _error_type(exc) == "subject_missing"


def test_parse_subject_specs_missing_npm_install(tmp_path):
    root = _prepare_checkout(tmp_path / "a", npm=False)
    with pytest.raises(UserFacingCliError) as exc:
        parse_subject_specs([f"x={root}"])
    assert _error_type(exc) == "subject_not_converged"
    assert "perk doctor --fix" in str(exc.value)


def test_parse_subject_specs_malformed_npm_manifest(tmp_path):
    root = _prepare_checkout(tmp_path / "a")
    (root / ".pi" / "npm" / "package.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(UserFacingCliError) as exc:
        parse_subject_specs([f"x={root}"])
    assert _error_type(exc) == "subject_not_converged"


# --- subjects: trust -----------------------------------------------------------------------------


def _agent_dir(tmp_path: Path, trust: object | None = None, settings: object | None = None) -> Path:
    agent = tmp_path / "agent"
    agent.mkdir(exist_ok=True)
    if trust is not None:
        (agent / "trust.json").write_text(
            trust if isinstance(trust, str) else json.dumps(trust), encoding="utf-8"
        )
    if settings is not None:
        (agent / "settings.json").write_text(
            settings if isinstance(settings, str) else json.dumps(settings), encoding="utf-8"
        )
    return agent


def test_check_trust_exact_key(tmp_path):
    checkout = tmp_path / "repo"
    checkout.mkdir()
    agent = _agent_dir(tmp_path, trust={str(checkout.resolve()): True})
    assert check_trust(checkout, agent) == f"trusted_by={checkout.resolve()}"


def test_check_trust_ancestor_true(tmp_path):
    checkout = tmp_path / "parent" / "repo"
    checkout.mkdir(parents=True)
    agent = _agent_dir(tmp_path, trust={str((tmp_path / "parent").resolve()): True})
    assert check_trust(checkout, agent) == f"trusted_by={(tmp_path / 'parent').resolve()}"


def test_check_trust_nearer_false_shadows_an_outer_true(tmp_path):
    checkout = tmp_path / "parent" / "repo"
    checkout.mkdir(parents=True)
    agent = _agent_dir(
        tmp_path,
        trust={str((tmp_path / "parent").resolve()): True, str(checkout.resolve()): False},
        settings={"defaultProjectTrust": "always"},  # a saved `false` beats the default too
    )
    with pytest.raises(UserFacingCliError) as exc:
        check_trust(checkout, agent)
    assert _error_type(exc) == "subject_untrusted"


def test_check_trust_missing_store_with_default_always(tmp_path):
    checkout = tmp_path / "repo"
    checkout.mkdir()
    agent = _agent_dir(tmp_path, settings={"defaultProjectTrust": "always"})
    assert check_trust(checkout, agent) == "trusted_by=defaultProjectTrust"


def test_check_trust_null_entry_falls_through_to_the_default(tmp_path):
    checkout = tmp_path / "repo"
    checkout.mkdir()
    agent = _agent_dir(
        tmp_path,
        trust={str(checkout.resolve()): None},
        settings={"defaultProjectTrust": "always"},
    )
    assert check_trust(checkout, agent) == "trusted_by=defaultProjectTrust"


def test_check_trust_missing_store_and_malformed_settings_refuses(tmp_path):
    checkout = tmp_path / "repo"
    checkout.mkdir()
    agent = _agent_dir(tmp_path, settings="{not json")
    with pytest.raises(UserFacingCliError) as exc:
        check_trust(checkout, agent)
    assert _error_type(exc) == "subject_untrusted"
    assert "choose Trust" in str(exc.value)


def test_check_trust_missing_store_and_no_setting_refuses(tmp_path):
    checkout = tmp_path / "repo"
    checkout.mkdir()
    agent = _agent_dir(tmp_path)
    with pytest.raises(UserFacingCliError) as exc:
        check_trust(checkout, agent)
    assert _error_type(exc) == "subject_untrusted"


@pytest.mark.parametrize("store", ["{not json", "[1]", '{"/x": "yes"}'])
def test_check_trust_malformed_store_refuses_like_pi(tmp_path, store):
    checkout = tmp_path / "repo"
    checkout.mkdir()
    agent = _agent_dir(tmp_path, trust=store, settings={"defaultProjectTrust": "always"})
    with pytest.raises(UserFacingCliError) as exc:
        check_trust(checkout, agent)
    assert _error_type(exc) == "subject_untrusted"


# --- subjects: the stamp -------------------------------------------------------------------------


def _canned_run_captured(outputs: dict[str, tuple[int, str]]):
    """A `run_captured` fake keyed by argv[0]'s basename → (returncode, stdout)."""

    def fake(argv, *, cwd=None, timeout, env_overlay=None, env_remove=None):
        assert timeout == 60
        code, out = outputs[Path(argv[0]).name]
        return subprocess.CompletedProcess(list(argv), code, stdout=out, stderr="")

    return fake


def _stamp_fixture(tmp_path: Path, git_repo: Path, monkeypatch) -> tuple[Subject, Path]:
    checkout = _prepare_checkout(git_repo)
    npm = checkout / ".pi" / "npm"
    _write_json(
        npm / "package.json",
        {"dependencies": {"pi-subagents": "^1", "absent-pkg": "^2", "broken-pkg": "^3"}},
    )
    _write_json(npm / "node_modules" / "pi-subagents" / "package.json", {"version": "0.70.1"})
    (npm / "node_modules" / "broken-pkg").mkdir(parents=True)
    (npm / "node_modules" / "broken-pkg" / "package.json").write_text("{oops", encoding="utf-8")
    # SDK copies: one under the checkout-root node_modules, one under .pi/npm/node_modules.
    _write_json(
        checkout / "node_modules" / "@earendil-works" / "pi-coding-agent" / "package.json",
        {"version": "0.87.0"},
    )
    _write_json(npm / "node_modules" / "typebox" / "package.json", {"version": "1.3.27"})
    agent = _agent_dir(tmp_path, trust={str(checkout.resolve()): True})
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent))
    monkeypatch.setattr(
        subjects_mod,
        "run_captured",
        _canned_run_captured(
            {"perk": (0, "perk 3.6.0\n"), "pi": (0, "0.87.0\n"), "node": (0, "v26.3.0\n")}
        ),
    )
    subject = parse_subject_specs([f"base={checkout}"])[0]
    return subject, agent


def test_stamp_subject_records_provenance(tmp_path, git_repo, monkeypatch):
    subject, agent = _stamp_fixture(tmp_path, git_repo, monkeypatch)
    pi_bin = tmp_path / "bin" / "pi"
    pi_bin.parent.mkdir()
    pi_bin.write_text("", encoding="utf-8")
    stamp = stamp_subject(subject, pi_path=str(pi_bin), node_path=str(tmp_path / "bin" / "node"))
    assert stamp.head == git.head_commit(subject.checkout)
    assert stamp.dirty is True  # the fixture wrote untracked files into the repo
    assert stamp.perk_version == "perk 3.6.0"
    assert stamp.pi_version == "0.87.0"
    assert stamp.node_version == "v26.3.0"
    assert stamp.pi_path == os.path.realpath(pi_bin)
    assert stamp.packages == {"pi-subagents": "0.70.1", "absent-pkg": None, "broken-pkg": None}
    assert [(c.name, c.version) for c in stamp.sdk_copies] == [
        ("@earendil-works/pi-coding-agent", "0.87.0"),
        ("typebox", "1.3.27"),
    ]
    assert stamp.sdk_copies[0].root == str(
        subject.checkout / "node_modules" / "@earendil-works" / "pi-coding-agent"
    )
    assert stamp.sdk_copies[1].root == str(
        subject.checkout / ".pi" / "npm" / "node_modules" / "typebox"
    )
    assert stamp.agent_dir == str(agent) and stamp.agent_dir_source == "env"
    assert stamp.trusted_by == f"trusted_by={subject.checkout}"


def test_stamp_subject_refuses_a_non_git_checkout(tmp_path, monkeypatch):
    checkout = _prepare_checkout(tmp_path / "plain")
    monkeypatch.setattr(
        subjects_mod,
        "run_captured",
        _canned_run_captured({"perk": (0, "x"), "pi": (0, "x"), "node": (0, "x")}),
    )
    subject = parse_subject_specs([f"p={checkout}"])[0]
    with pytest.raises(UserFacingCliError) as exc:
        stamp_subject(subject, pi_path="/bin/pi", node_path="/bin/node")
    assert _error_type(exc) == "subject_probe_failed"


def test_stamp_subject_refuses_a_failing_version_probe(tmp_path, git_repo, monkeypatch):
    subject, _agent = _stamp_fixture(tmp_path, git_repo, monkeypatch)
    monkeypatch.setattr(
        subjects_mod,
        "run_captured",
        _canned_run_captured({"perk": (0, "perk 3.6.0"), "pi": (2, ""), "node": (0, "v26")}),
    )
    with pytest.raises(UserFacingCliError) as exc:
        stamp_subject(subject, pi_path="/bin/pi", node_path="/bin/node")
    assert _error_type(exc) == "subject_probe_failed"
    assert "exited 2" in str(exc.value)


def test_stamp_subject_refuses_an_unreadable_trust_store(tmp_path, git_repo, monkeypatch):
    subject, agent = _stamp_fixture(tmp_path, git_repo, monkeypatch)
    (agent / "trust.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(UserFacingCliError) as exc:
        stamp_subject(subject, pi_path="/bin/pi", node_path="/bin/node")
    assert _error_type(exc) == "subject_untrusted"


# --- the Node census ----------------------------------------------------------------------------


def _census_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """A census dir with a main Pi process file and a child process file, plus a host root and
    two SDK package roots outside it (with versions)."""
    host_root = tmp_path / "opt" / "pi"
    _write_json(host_root / "package.json", {"name": "@earendil-works/pi-coding-agent"})
    pi_bin = host_root / "dist" / "bundle" / "cli.js"
    pi_bin.parent.mkdir(parents=True)
    pi_bin.write_text("", encoding="utf-8")
    sdk_root_a = tmp_path / "repo" / "node_modules" / "@earendil-works" / "pi-coding-agent"
    _write_json(sdk_root_a / "package.json", {"version": "0.87.0"})
    sdk_root_b = tmp_path / "repo" / ".pi" / "npm" / "node_modules" / "typebox"
    _write_json(sdk_root_b / "package.json", {"version": "1.3.27"})
    sdk_root_c = tmp_path / "other" / "node_modules" / "typebox"  # no package.json → version null
    sdk_root_c.mkdir(parents=True)
    census_dir = tmp_path / "census"
    census_dir.mkdir()

    def resolve(url: str) -> str:
        return json.dumps({"kind": "resolve", "url": url, "parent": None, "specifier": url})

    main_rows = [
        json.dumps(
            {
                "kind": "process",
                "pid": 4242,
                "ppid": 1,
                "argv": ["/usr/bin/node", str(tmp_path / "bin" / "pi")],
                "execPath": "/usr/bin/node",
                "node": "v26.3.0",
                "cwd": str(tmp_path / "repo"),
                "hooks": True,
            }
        ),
        resolve("node:fs"),
        resolve("node:path"),
        resolve("node:fs"),  # a duplicate resolution counts once
        resolve((host_root / "dist" / "main.js").as_uri()),
        resolve((host_root / "node_modules" / "chalk" / "index.js").as_uri()),
        resolve((sdk_root_a / "dist" / "index.js").as_uri()),
        resolve((sdk_root_a / "dist" / "core" / "agent.js").as_uri()),
        resolve((sdk_root_b / "build" / "index.mjs").as_uri()),
        resolve((sdk_root_c / "build" / "index.mjs").as_uri()),
        resolve((tmp_path / "repo" / "node_modules" / "pi-subagents" / "index.js").as_uri()),
        resolve((tmp_path / "repo" / ".pi" / "extensions" / "local.ts").as_uri()),
        resolve("data:text/javascript,export default 1"),
    ]
    (census_dir / "census-4242.jsonl").write_text("\n".join(main_rows) + "\n", encoding="utf-8")
    child_rows = [
        json.dumps(
            {
                "kind": "process",
                "pid": 4243,
                "ppid": 4242,
                "argv": ["/usr/bin/node", "/somewhere/else.js"],
                "execPath": "/usr/bin/node",
                "node": "v26.3.0",
                "cwd": "/",
                "hooks": True,
            }
        ),
        resolve("node:child_process"),
    ]
    (census_dir / "census-4243.jsonl").write_text("\n".join(child_rows) + "\n", encoding="utf-8")
    # A symlinked `pi` bin: the header names the symlink, the harness compares realpaths.
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "pi").symlink_to(pi_bin)
    return census_dir, host_root


def test_analyze_census_groups_the_main_process(tmp_path):
    from perk_dev.profile_startup import census

    census_dir, host_root = _census_fixture(tmp_path)
    summary = census.analyze_census(
        census_dir, pi_bin_realpath=os.path.realpath(tmp_path / "bin" / "pi"), host_root=host_root
    )
    assert summary.main_pid == 4242
    assert summary.distinct_modules == 11
    assert summary.builtin_modules == 2
    assert summary.host_modules == 2  # dist/main.js + the host's OWN node_modules/chalk
    assert summary.by_package == {
        "@earendil-works/pi-coding-agent": 2,
        "<unpackaged>": 2,  # the .pi/extensions file + the data: URL
        "typebox": 2,
        "pi-subagents": 1,
    }
    assert summary.sdk_outside_host == {"@earendil-works/pi-coding-agent": 2, "typebox": 2}
    assert summary.sdk_outside_host_total == 4
    roots = [(r.name, r.root, r.version, r.modules) for r in summary.sdk_outside_host_roots]
    assert roots == [
        (
            "@earendil-works/pi-coding-agent",
            str(tmp_path / "repo" / "node_modules" / "@earendil-works" / "pi-coding-agent"),
            "0.87.0",
            2,
        ),
        ("typebox", str(tmp_path / "other" / "node_modules" / "typebox"), None, 1),
        (
            "typebox",
            str(tmp_path / "repo" / ".pi" / "npm" / "node_modules" / "typebox"),
            "1.3.27",
            1,
        ),
    ]


def test_pi_package_root_walks_up_from_the_realpath(tmp_path):
    from perk_dev.profile_startup import census

    _census_dir, host_root = _census_fixture(tmp_path)
    assert census.pi_package_root(str(tmp_path / "bin" / "pi")) == host_root.resolve()
    assert census.pi_package_root(str(tmp_path / "nowhere" / "pi")) is None


def test_compose_node_options_and_tracer_path(tmp_path):
    from perk_dev.profile_startup import census

    assert census.TRACER_PATH.exists() and census.TRACER_PATH.name == "module_tracer.mjs"
    value = census.compose_node_options(
        census_dir=tmp_path / "node-census", cpu_prof_dir=tmp_path / "cpu prof"
    )
    assert value == (
        f"--import={census.TRACER_PATH.resolve().as_uri()} --cpu-prof "
        f'--cpu-prof-dir="{tmp_path / "cpu prof"}"'
    )
    assert value.startswith("--import=file://")


def _pty_run(*, exit_code=0, elapsed_ms=400.0, timed_out=False, lingered=False, stderr=""):
    from perk_dev.profile_startup.pty_session import PtyRun

    return PtyRun(
        exit_code=exit_code,
        elapsed_ms=elapsed_ms,
        exit_ms=None if (timed_out or lingered) else 900.0,
        timed_out=timed_out,
        lingered=lingered,
        stderr=stderr,
        stdout_bytes=10,
        spawn_monotonic_ns=1_000_000_000,
    )


def _classify(tmp_path, run, *, marker_seen, census_dir=None):
    from perk_dev.profile_startup import census

    host_root = tmp_path / "opt" / "pi"
    return census.classify_census_run(
        run,
        marker_seen=marker_seen,
        census_dir=census_dir if census_dir is not None else tmp_path / "empty-census",
        cpu_prof_dir=tmp_path / "cpu-prof",
        pi_bin_realpath=os.path.realpath(tmp_path / "bin" / "pi"),
        host_root=host_root,
    )


def test_census_status_ladder(tmp_path):
    from perk_dev.profile_startup import census

    census_dir, _host_root = _census_fixture(tmp_path)
    (tmp_path / "cpu-prof").mkdir()
    (tmp_path / "cpu-prof" / "CPU.1.cpuprofile").write_text("{}", encoding="utf-8")

    timed = _classify(
        tmp_path, _pty_run(exit_code=-9, elapsed_ms=None, timed_out=True), marker_seen=False
    )
    assert timed.status == "timed_out" and timed.summary is None and timed.hooks_supported is None

    failed = _classify(tmp_path, _pty_run(exit_code=3, elapsed_ms=None), marker_seen=False)
    assert failed.status == "failed_exit" and "exited 3" in (failed.failure or "")

    no_marker = _classify(tmp_path, _pty_run(exit_code=0, elapsed_ms=None), marker_seen=False)
    assert no_marker.status == "no_marker"

    no_file = _classify(tmp_path, _pty_run(), marker_seen=True)
    assert no_file.status == "no_census_file" and no_file.process_files == 0

    ok = _classify(
        tmp_path, _pty_run(exit_code=-15, lingered=True), marker_seen=True, census_dir=census_dir
    )
    assert ok.status == "ok" and ok.lingered is True  # lingered is a flag beside `ok`
    assert ok.main_pid == 4242 and ok.hooks_supported is True
    assert ok.process_files == 2 and ok.cpu_profiles == ("CPU.1.cpuprofile",)
    assert ok.summary is not None and ok.summary.sdk_outside_host_total == 4

    main_file = census_dir / "census-4242.jsonl"
    text = main_file.read_text(encoding="utf-8")
    main_file.write_text(text + "{not json\n", encoding="utf-8")
    malformed = _classify(tmp_path, _pty_run(), marker_seen=True, census_dir=census_dir)
    assert malformed.status == "malformed_census" and malformed.summary is None

    header, *rest = text.splitlines()
    header_obj = json.loads(header)
    header_obj["hooks"] = False
    main_file.write_text("\n".join([json.dumps(header_obj), *rest]) + "\n", encoding="utf-8")
    unsupported = _classify(tmp_path, _pty_run(), marker_seen=True, census_dir=census_dir)
    assert unsupported.status == "hooks_unsupported" and unsupported.hooks_supported is False

    # The host root is resolved BEFORE any spawn: `None` → not spawned.
    subject = Subject(
        label="s", checkout=tmp_path, executable=tmp_path / "perk", python=tmp_path / "python"
    )

    def never_spawn(*args, **kwargs):
        raise AssertionError("the census arm must not spawn without a host root")

    unresolved = census.run_census_arm(
        subject,
        env={},
        profiles_dir=tmp_path / "profiles",
        pi_path=str(tmp_path / "nowhere" / "pi"),
        spawn=never_spawn,
        size=PtySize(cols=80, rows=24),
        timeout_s=1.0,
        exit_grace_s=1.0,
        report=lambda _line: None,
    )
    assert unresolved.status == "host_root_unresolved"
    assert not (tmp_path / "profiles").exists()


# --- the Python handoff arms ---------------------------------------------------------------------

_IMPORTTIME_LOG = """opening a plain Pi session in /tmp/x: pi
import time: self [us] | cumulative | imported package
import time:       120 |        120 |   _io
import time:        50 |       3000 |     perk.substrate.git
import time:       900 |       9000 |   perk.cli.cli
import time:        10 |         10 | zipimport
PERK_PROFILE_HANDOFF set — recorded the Pi handoff to /tmp/h.json; exiting without launching pi
"""


def test_summarize_importtime_sorts_by_cumulative():
    from perk_dev.profile_startup import handoff

    rows = handoff.summarize_importtime(_IMPORTTIME_LOG, top=3)
    assert [(r.name, r.cumulative_us, r.self_us) for r in rows] == [
        ("perk.cli.cli", 9000, 900),
        ("perk.substrate.git", 3000, 50),
        ("_io", 120, 120),
    ]
    rendered = handoff.render_importtime_top(rows)
    assert "perk.cli.cli" in rendered and rendered.splitlines()[0].endswith("module")


def test_handoff_record_mirrors_the_seam(tmp_path, launch_exec_recorder):
    from perk_dev.profile_startup import handoff

    from perk.run import launch

    target = tmp_path / "h.json"
    launch._record_profile_handoff(
        target,
        pi_path="/stub/bin/pi",
        argv=("pi",),
        checkout=tmp_path,
        env={"B": "2", "A": "1"},
    )
    written = set(json.loads(target.read_text(encoding="utf-8")))
    assert written == handoff.record_keys()  # cross-plane agreement on the key set
    record = handoff.read_handoff_record(target)
    assert record is not None
    assert record.schema_version == 1 and record.argv == ("pi",) and record.env_keys == ("A", "B")
    assert handoff.read_handoff_record(tmp_path / "missing.json") is None
    (tmp_path / "bad.json").write_text('{"schema": 1}', encoding="utf-8")
    assert handoff.read_handoff_record(tmp_path / "bad.json") is None


def _fake_handoff_spawn(*, write_records: set[str], write_prof: bool = True, exit_codes=None):
    """A spawn fake for the handoff arms: writes the seam's record for the named arms (keyed by
    the PERK_PROFILE_HANDOFF target's stem suffix), a cProfile dump for the cProfile arm, and an
    importtime log on the importtime arm's stderr."""
    import cProfile

    from perk.run import launch

    calls: list[dict] = []

    def spawn(argv, *, cwd, env, size, timeout_s, exit_grace_s, startup_marker):
        target = Path(env[launch.PROFILE_HANDOFF_ENV])
        arm = target.stem.removeprefix("handoff-")
        calls.append({"argv": tuple(argv), "arm": arm, "target": target, "cwd": cwd})
        assert startup_marker("--- Startup Timings: main ---") is False  # never fires
        if arm in write_records:
            launch._record_profile_handoff(
                target, pi_path="/stub/bin/pi", argv=("pi",), checkout=cwd, env=env
            )
        stderr = ""
        if arm == "cprofile" and write_prof:
            prof = Path(argv[argv.index("-o") + 1])
            profiler = cProfile.Profile()
            profiler.runcall(sum, range(10))
            profiler.dump_stats(str(prof))
        if arm == "importtime":
            stderr = _IMPORTTIME_LOG
        code = (exit_codes or {}).get(arm, 0)
        return _pty_run(exit_code=code, elapsed_ms=None, stderr=stderr)

    return spawn, calls


def _subject(tmp_path: Path) -> Subject:
    return Subject(
        label="s",
        checkout=tmp_path / "checkout",
        executable=tmp_path / "checkout" / ".venv" / "bin" / "perk",
        python=tmp_path / "checkout" / ".venv" / "bin" / "python",
    )


def _run_arms(tmp_path, spawn):
    from perk_dev.profile_startup import handoff

    return handoff.run_handoff_arms(
        _subject(tmp_path),
        env={"PATH": "/usr/bin"},
        profiles_dir=tmp_path / "profiles",
        spawn=spawn,
        size=PtySize(cols=120, rows=40),
        timeout_s=5.0,
        exit_grace_s=1.0,
        report=lambda _line: None,
    )


def test_run_handoff_arms_happy_path_writes_every_artifact(tmp_path):
    spawn, calls = _fake_handoff_spawn(write_records={"direct", "cprofile", "importtime"})
    profile = _run_arms(tmp_path, spawn)
    assert [c["arm"] for c in calls] == ["direct", "cprofile", "importtime"]
    subject = _subject(tmp_path)
    assert calls[0]["argv"] == (str(subject.executable),)
    assert calls[1]["argv"][:4] == (str(subject.python), "-m", "cProfile", "-o")
    assert calls[1]["argv"][-2:] == ("-m", "perk")
    assert calls[2]["argv"] == (str(subject.python), "-X", "importtime", "-m", "perk")
    assert len({c["target"] for c in calls}) == 3  # each arm has its own record file
    assert all(c["cwd"] == subject.checkout for c in calls)
    profiles = tmp_path / "profiles"
    for name in (
        "handoff-direct.json",
        "handoff-cprofile.json",
        "handoff-importtime.json",
        "cprofile.prof",
        "cprofile-top.txt",
        "importtime.log",
        "importtime-top.txt",
    ):
        assert (profiles / name).is_file(), name
    assert "cumulative" in (profiles / "cprofile-top.txt").read_text(encoding="utf-8")
    assert (profiles / "importtime.log").read_text(encoding="utf-8") == _IMPORTTIME_LOG
    assert {name: arm.status for name, arm in profile.arms.items()} == {
        "direct": "ok",
        "cprofile": "ok",
        "importtime": "ok",
    }
    assert profile.handoff_ms is not None and profile.handoff_ms > 0


def test_run_handoff_arms_stale_record_is_unlinked_before_the_spawn(tmp_path):
    from perk.run import launch

    profiles = tmp_path / "profiles"
    profiles.mkdir()
    launch._record_profile_handoff(
        profiles / "handoff-direct.json", pi_path="/stale", argv=("pi",), checkout=tmp_path, env={}
    )
    spawn, _calls = _fake_handoff_spawn(write_records={"cprofile", "importtime"})
    profile = _run_arms(tmp_path, spawn)
    assert profile.arms["direct"].status == "no_record"
    assert profile.arms["direct"].record_present is False
    assert profile.handoff_ms is None
    assert not (profiles / "handoff-direct.json").exists()


def test_run_handoff_arms_failed_arm_is_recorded_not_raised(tmp_path):
    spawn, _calls = _fake_handoff_spawn(
        write_records={"direct", "importtime"}, write_prof=False, exit_codes={"importtime": 1}
    )
    profile = _run_arms(tmp_path, spawn)
    assert profile.arms["direct"].status == "ok"
    assert profile.arms["cprofile"].status == "no_record"  # exit 0, seam never reached
    assert profile.arms["cprofile"].output_present is False
    assert profile.arms["importtime"].status == "failed"  # non-zero exit
    assert profile.arms["importtime"].record_present is True
