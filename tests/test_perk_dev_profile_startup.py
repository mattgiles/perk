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
