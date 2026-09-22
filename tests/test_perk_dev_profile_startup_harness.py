"""`perk-dev profile-startup` — the run: schedule, sample env, the summary statistics + golden
`summary.json` snapshot, and `run_profile` driven through a fake `spawn` (canned `PtyRun`s; the
fake also writes the handoff/census files the profiled arms read)."""

import cProfile
import json
import os
import stat
from pathlib import Path

import pytest
from _golden import assert_text_golden
from perk_dev.profile_startup import harness
from perk_dev.profile_startup import subjects as subjects_mod
from perk_dev.profile_startup import summary as summary_mod
from perk_dev.profile_startup.pty_session import PtyRun, PtySize
from perk_dev.profile_startup.subjects import SdkCopy, Subject, SubjectStamp
from perk_dev.profile_startup.timings import parse_pi_timings

from perk import __version__
from perk.run import pi_exec
from perk.substrate import git

# --- schedule + env ----------------------------------------------------------------------------


def _subject(label: str, root: Path) -> Subject:
    return Subject(
        label=label,
        checkout=root,
        executable=root / ".venv" / "bin" / "perk",
        python=root / ".venv" / "bin" / "python",
    )


def test_schedule_alternates_subjects_after_one_warmup_each(tmp_path):
    a, b = _subject("a", tmp_path / "a"), _subject("b", tmp_path / "b")
    assert harness.schedule([a, b], 3) == (
        ("warmup", "a"),
        ("warmup", "b"),
        (1, "a"),
        (1, "b"),
        (2, "a"),
        (2, "b"),
        (3, "a"),
        (3, "b"),
    )


def test_build_sample_env_scrubs_injects_and_defaults_term():
    environ = {
        "PATH": "/usr/bin",
        "PERK_RUN_ID": "01X",
        "PERK_PROFILE_HANDOFF": "/tmp/h.json",
        "PERK_MODULE_CENSUS_DIR": "/tmp/c",
        "NODE_OPTIONS": "--max-old-space-size=8192",
        "PI_CODING_AGENT_DIR": "/agent",
    }
    sample = harness.build_sample_env(environ)
    assert not any(name in sample.env for name in harness.REMOVED_ENV)
    assert sample.operator_node_options == "--max-old-space-size=8192"
    assert sample.env["PI_STARTUP_BENCHMARK"] == "1"
    assert sample.env["PI_TIMING"] == "1"
    assert sample.env["PI_OFFLINE"] == "1"
    assert sample.env["TERM"] == "xterm-256color"
    assert sample.env["PI_CODING_AGENT_DIR"] == "/agent"  # inherited untouched
    assert sample.env["PATH"] == "/usr/bin"
    kept = harness.build_sample_env({"TERM": "screen", "PI_TIMING": "0"})
    assert kept.env["TERM"] == "screen"  # only defaulted when absent
    assert kept.env["PI_TIMING"] == "1"  # injected values win
    assert kept.operator_node_options is None


# --- summary statistics + the golden snapshot --------------------------------------------------

_MAIN_GROUP = (
    "--- Startup Timings: main ---\n"
    "  imports: {a}ms\n"
    "  createAgentSession: {b}ms\n"
    "  TOTAL: {t}ms\n"
    "-----------------------------\n"
)
_EXT_GROUP = (
    "--- Startup Timings: extensions ---\n"
    "  /repo/.pi/npm/node_modules/@mgiles/perk/extension/index.ts module import: {x}ms\n"
    "  /repo/.pi/npm/node_modules/@mgiles/perk/extension/index.ts factory: {y}ms\n"
    "  TOTAL: {t}ms\n"
    "-----------------------------------\n"
)


def _stderr(*, main_total: int, ext: tuple[int, int] = (40, 4)) -> str:
    a = main_total // 3
    return _EXT_GROUP.format(x=ext[0], y=ext[1], t=sum(ext)) + _MAIN_GROUP.format(
        a=a, b=main_total - a, t=main_total
    )


def _run(*, elapsed_ms, stderr, exit_code=0, timed_out=False, lingered=False, exit_ms=None):
    return PtyRun(
        exit_code=exit_code,
        elapsed_ms=elapsed_ms,
        exit_ms=exit_ms,
        timed_out=timed_out,
        lingered=lingered,
        stderr=stderr,
        stdout_bytes=1234,
        spawn_monotonic_ns=5_000_000_000,
    )


def _sample(index: int, *, elapsed_ms, main_total, ext=(40, 4), **kwargs):
    return summary_mod.classify_sample(
        _run(elapsed_ms=elapsed_ms, stderr=_stderr(main_total=main_total, ext=ext), **kwargs),
        index=index,
    )


def _stamp(label: str) -> SubjectStamp:
    return SubjectStamp(
        head=f"{label * 10}"[:40].ljust(40, "0"),
        dirty=False,
        perk_version="perk 3.6.0",
        pi_version="0.87.0",
        pi_path="/opt/node/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js",
        node_version="v26.3.0",
        packages={"pi-subagents": "0.70.1", "pi-web-access": None},
        sdk_copies=(
            SdkCopy(
                name="@earendil-works/pi-coding-agent",
                root=f"/checkouts/{label}/node_modules/@earendil-works/pi-coding-agent",
                version="0.87.0",
            ),
        ),
        agent_dir="/checkouts/main/.pi/agent",
        agent_dir_source="config",
        trusted_by="trusted_by=/checkouts",
    )


def _synthetic_summary(*, two_subjects: bool) -> summary_mod.Summary:
    from perk_dev.profile_startup.census import CensusRun, CensusSummary, SdkRoot
    from perk_dev.profile_startup.handoff import ArmStatus, HandoffProfile

    warm = _sample(0, elapsed_ms=2000.0, main_total=1500, exit_ms=2400.0)
    ok1 = _sample(1, elapsed_ms=1000.0, main_total=700, exit_ms=1300.0)
    ok2 = _sample(2, elapsed_ms=1100.0, main_total=750, ext=(44, 4), exit_ms=1400.0)
    lingered = _sample(3, elapsed_ms=1300.0, main_total=800, ext=(60, 6), lingered=True)
    failed = summary_mod.classify_sample(
        _run(elapsed_ms=None, stderr="npm ERR! boom\n", exit_code=1), index=4
    )
    handoff = HandoffProfile(
        handoff_ms=123.456,
        arms={
            "direct": ArmStatus("ok", 0, False, True, True),
            "cprofile": ArmStatus("ok", 0, False, True, True),
            "importtime": ArmStatus("no_record", 0, False, False, True),
        },
    )
    census = CensusRun(
        status="ok",
        exit_code=-15,
        timed_out=False,
        lingered=True,
        marker_seen=True,
        hooks_supported=True,
        main_pid=4242,
        process_files=2,
        cpu_profiles=("CPU.20260101.000000.4242.0.001.cpuprofile",),
        summary=CensusSummary(
            main_pid=4242,
            distinct_modules=1500,
            builtin_modules=60,
            host_modules=900,
            by_package={"@earendil-works/pi-coding-agent": 300, "pi-subagents": 240},
            sdk_outside_host={"@earendil-works/pi-coding-agent": 300},
            sdk_outside_host_total=300,
            sdk_outside_host_roots=(
                SdkRoot(
                    name="@earendil-works/pi-coding-agent",
                    root="/checkouts/a/node_modules/@earendil-works/pi-coding-agent",
                    version="0.87.0",
                    modules=300,
                ),
            ),
        ),
        failure=None,
    )
    subjects = [
        summary_mod.SubjectSummary(
            label="a",
            checkout="/checkouts/a",
            stamp=_stamp("a"),
            first_run=warm,
            samples=(ok1, ok2, lingered, failed),
            handoff=handoff,
            census=census,
        )
    ]
    if two_subjects:
        subjects.append(
            summary_mod.SubjectSummary(
                label="b",
                checkout="/checkouts/b",
                stamp=_stamp("b"),
                first_run=None,
                samples=(
                    _sample(1, elapsed_ms=900.0, main_total=600, exit_ms=1200.0),
                    _sample(2, elapsed_ms=950.0, main_total=650, exit_ms=1250.0),
                ),
                handoff=None,
                census=None,
            )
        )
    return summary_mod.build_summary(
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:05:00+00:00",
        tool=summary_mod.ToolInfo(perk_version="3.6.0", perk_dev_head="f" * 40),
        host=summary_mod.HostInfo(platform="macOS-15.0-arm64", machine="arm64", cpu_count=12),
        options=summary_mod.RunOptions(
            runs=4, timeout_s=180.0, exit_grace_s=10.0, pty_size=PtySize(120, 40), profiles=True
        ),
        env=summary_mod.EnvInfo(
            injected=dict(harness.INJECTED_ENV),
            removed=harness.REMOVED_ENV,
            operator_node_options="--max-old-space-size=8192",
        ),
        subjects=subjects,
    )


def test_classify_sample_derives_the_remainder_and_failures():
    ok = _sample(1, elapsed_ms=1000.0, main_total=700)
    assert ok.failed is False and ok.pi_main_total_ms == 700
    assert ok.pre_pi_remainder_ms == pytest.approx(300.0)
    assert ok.extension_rows[0][1] == 40
    assert set(ok.groups) == {"extensions", "main"}
    timed = summary_mod.classify_sample(
        _run(elapsed_ms=None, stderr="", exit_code=-9, timed_out=True), index=1
    )
    assert timed.failed and timed.failure is not None and timed.failure.startswith("timed_out")
    exit_no_main = summary_mod.classify_sample(
        _run(elapsed_ms=None, stderr="x", exit_code=2), index=1
    )
    assert exit_no_main.failure == "exit 2 without a `main` timing group"
    no_main = summary_mod.classify_sample(_run(elapsed_ms=None, stderr="x", exit_code=0), index=1)
    assert no_main.failure == "no `main` timing group in stderr"
    lingered = _sample(3, elapsed_ms=1300.0, main_total=800, lingered=True)
    assert lingered.failed is False and lingered.lingered is True


def test_summary_statistics_exclude_failed_samples_and_the_warmup():
    summary = _synthetic_summary(two_subjects=True)
    a = summary.subjects[0]
    elapsed = summary_mod.metric_stats(a.samples, "elapsed_ms")
    assert elapsed is not None
    assert (elapsed.median, elapsed.min, elapsed.max, elapsed.count) == (1100.0, 1000.0, 1300.0, 3)
    remainder = summary_mod.metric_stats(a.samples, "pre_pi_remainder_ms")
    assert remainder is not None and remainder.median == pytest.approx(350.0)
    rows = summary_mod.extension_row_stats(a.samples)
    assert rows[0].label.endswith("module import") and rows[0].stats.median == 44.0
    assert rows[0].stats.count == 3  # the failed sample contributed nothing
    deltas = summary_mod.compute_deltas(summary.subjects)
    assert deltas is not None
    assert deltas["elapsed_ms"] is not None
    assert deltas["elapsed_ms"].delta_ms == pytest.approx(925.0 - 1100.0)
    assert deltas["handoff_ms"] is None  # subject b has no handoff profile
    assert summary_mod.compute_deltas(_synthetic_summary(two_subjects=False).subjects) is None
    out = json.loads(summary_mod.summary_json_text(summary))
    assert out["subjects"][0]["first_run"]["elapsed_ms"] == 2000.0
    assert out["subjects"][0]["samples"] == {
        "count": 4,
        "failed": 1,
        "elapsed_ms": {"median": 1100.0, "min": 1000.0, "max": 1300.0, "count": 3},
        "pi_main_total_ms": {"median": 750.0, "min": 700.0, "max": 800.0, "count": 3},
        "pre_pi_remainder_ms": {"median": 350.0, "min": 300.0, "max": 500.0, "count": 3},
    }
    assert out["subjects"][1]["handoff"] is None and out["subjects"][1]["census"] is None


def test_summary_json_golden_snapshot():
    text = summary_mod.summary_json_text(_synthetic_summary(two_subjects=True))
    assert_text_golden("json/profile_startup_summary", text, suffix=".json")
    out = json.loads(text)
    assert list(out) == [
        "schema",
        "started_at",
        "finished_at",
        "tool",
        "host",
        "options",
        "env",
        "subjects",
        "deltas",
    ]
    assert list(out["subjects"][0]) == [
        "label",
        "checkout",
        "stamp",
        "first_run",
        "samples",
        "extension_rows",
        "handoff",
        "census",
    ]
    assert out["schema"] == 1
    assert list(out["subjects"][0]["stamp"]) == [
        "head",
        "dirty",
        "perk_version",
        "pi_version",
        "pi_path",
        "node_version",
        "packages",
        "sdk_copies",
        "agent_dir",
        "agent_dir_source",
        "trusted_by",
    ]


def test_render_summary_md_names_subjects_and_the_derived_estimate_caveat():
    text = summary_mod.render_summary_md(_synthetic_summary(two_subjects=True))
    assert "| a |" in text and "| b |" in text
    assert "derived estimate" in text and "150 ms benchmark settle" in text
    assert "operator NODE_OPTIONS removed" in text and "--max-old-space-size=8192" in text
    assert "handoff_ms 123.5" in text and "importtime no_record" in text
    assert "SDK modules outside the host root: 300" in text
    assert "## delta (b - a" in text
    assert "reported, not judged" in text
    assert "verdict" not in text.lower()


# --- run_profile with a fake spawn -------------------------------------------------------------


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _prepare_subject(root: Path) -> Path:
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in ("perk", "python"):
        tool = bin_dir / name
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    (root / ".pi" / "npm" / "node_modules").mkdir(parents=True, exist_ok=True)
    _write_json(root / ".pi" / "npm" / "package.json", {"dependencies": {"pi-subagents": "^1"}})
    return root


def _fake_host(tmp_path: Path) -> Path:
    """A fake Pi install: `bin/pi` → `<host root>/dist/bundle/cli.js`."""
    host_root = tmp_path / "opt" / "pi-coding-agent"
    _write_json(host_root / "package.json", {"name": "@earendil-works/pi-coding-agent"})
    cli = host_root / "dist" / "bundle" / "cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("", encoding="utf-8")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "pi").symlink_to(cli)
    return tmp_path / "bin" / "pi"


class _FakeSpawn:
    """Canned PTY runs keyed by the spawn's role, recording every call in order."""

    def __init__(self, *, pi_bin: Path, write_direct_record: bool = True) -> None:
        self.calls: list[dict] = []
        self.pi_bin = pi_bin
        self.write_direct_record = write_direct_record
        self._counter = 0

    def __call__(self, argv, *, cwd, env, size, timeout_s, exit_grace_s, startup_marker):
        self._counter += 1
        role = "sample"
        if pi_exec.PROFILE_HANDOFF_ENV in env:
            role = "handoff:" + Path(env[pi_exec.PROFILE_HANDOFF_ENV]).stem.removeprefix("handoff-")
        elif "NODE_OPTIONS" in env:
            role = "census"
        self.calls.append(
            {
                "role": role,
                "argv": tuple(argv),
                "cwd": cwd,
                "env": dict(env),
                "size": size,
                "timeout_s": timeout_s,
                "exit_grace_s": exit_grace_s,
            }
        )
        if role == "sample" or role == "census":
            main_total = 700 + self._counter
            stderr = _stderr(main_total=main_total)
            for line in stderr.splitlines():
                startup_marker(line)
            if role == "census":
                census_dir = Path(env["PERK_MODULE_CENSUS_DIR"])
                header = {
                    "kind": "process",
                    "pid": 777,
                    "ppid": 1,
                    "argv": ["/usr/bin/node", str(self.pi_bin)],
                    "execPath": "/usr/bin/node",
                    "node": "v26.3.0",
                    "cwd": str(cwd),
                    "hooks": True,
                }
                rows = [
                    json.dumps(header),
                    json.dumps(
                        {
                            "kind": "resolve",
                            "url": "node:fs",
                            "parent": None,
                            "specifier": "node:fs",
                        }
                    ),
                    json.dumps(
                        {
                            "kind": "resolve",
                            "url": (
                                cwd / "node_modules" / "@earendil-works" / "pi-tui" / "x.js"
                            ).as_uri(),
                            "parent": None,
                            "specifier": "@earendil-works/pi-tui",
                        }
                    ),
                ]
                (census_dir / "census-777.jsonl").write_text(
                    "\n".join(rows) + "\n", encoding="utf-8"
                )
                return _run(
                    elapsed_ms=1000.0 + self._counter, stderr=stderr, exit_code=-15, lingered=True
                )
            return _run(
                elapsed_ms=1000.0 + self._counter, stderr=stderr, exit_ms=1300.0 + self._counter
            )
        assert startup_marker("--- Startup Timings: main ---") is False
        target = Path(env[pi_exec.PROFILE_HANDOFF_ENV])
        arm = role.removeprefix("handoff:")
        if arm != "direct" or self.write_direct_record:
            pi_exec._record_profile_handoff(
                target, pi_path=str(self.pi_bin), argv=("pi",), checkout=cwd, env=env
            )
        stderr = ""
        if arm == "cprofile":
            profiler = cProfile.Profile()
            profiler.runcall(sum, range(10))
            profiler.dump_stats(argv[argv.index("-o") + 1])
        if arm == "importtime":
            stderr = (
                "import time:       120 |        120 |   _io\n"
                "import time:       900 |       9000 |   perk.cli.cli\n"
            )
        return _run(elapsed_ms=None, stderr=stderr, exit_ms=400.0)


def _options(tmp_path, subjects, *, runs=2, profiles=True) -> harness.ProfileOptions:
    pi_bin = (
        _fake_host(tmp_path) if not (tmp_path / "bin" / "pi").exists() else tmp_path / "bin" / "pi"
    )
    return harness.ProfileOptions(
        subjects=tuple(subjects),
        runs=runs,
        output=tmp_path / "out",
        timeout_s=30.0,
        exit_grace_s=2.0,
        pty_size=PtySize(cols=100, rows=30),
        profiles=profiles,
        pi_path=str(pi_bin),
        node_path="/usr/bin/node",
    )


@pytest.fixture
def two_subjects(tmp_path, git_repo_factory, monkeypatch, isolated_pi_agent_dir):
    a = _prepare_subject(git_repo_factory(tmp_path / "a"))
    b = _prepare_subject(git_repo_factory(tmp_path / "b"))
    isolated_pi_agent_dir.mkdir(exist_ok=True)
    (isolated_pi_agent_dir / "settings.json").write_text(
        json.dumps({"defaultProjectTrust": "always"}), encoding="utf-8"
    )

    def fake_run_captured(argv, *, cwd=None, timeout, env_overlay=None, env_remove=None):
        import subprocess

        out = {"perk": "perk 3.6.0\n", "pi": "0.87.0\n", "node": "v26.3.0\n"}[Path(argv[0]).name]
        return subprocess.CompletedProcess(list(argv), 0, stdout=out, stderr="")

    monkeypatch.setattr(subjects_mod, "run_captured", fake_run_captured)
    return _subject("a", a), _subject("b", b)


def test_run_profile_writes_the_run_directory_in_schedule_order(
    tmp_path, two_subjects, monkeypatch
):
    a, b = two_subjects
    monkeypatch.setenv("NODE_OPTIONS", "--operator-flag")
    monkeypatch.setenv("PERK_RUN_ID", "01LEAK")
    options = _options(tmp_path, [a, b], runs=2)
    fake = _FakeSpawn(pi_bin=Path(options.pi_path))
    reported: list[str] = []
    summary = harness.run_profile(options, spawn=fake, environ=os.environ, report=reported.append)
    out = options.output

    roles = [c["role"] for c in fake.calls]
    assert roles[:6] == ["sample"] * 6
    assert [c["cwd"] for c in fake.calls[:6]] == [
        a.checkout,
        b.checkout,
        a.checkout,
        b.checkout,
        a.checkout,
        b.checkout,
    ]
    assert roles[6:] == [
        "handoff:direct",
        "handoff:cprofile",
        "handoff:importtime",
        "census",
        "handoff:direct",
        "handoff:cprofile",
        "handoff:importtime",
        "census",
    ]
    for call in fake.calls:
        assert call["argv"][0].startswith(str(tmp_path))
        assert call["size"] == PtySize(cols=100, rows=30)
        assert call["timeout_s"] == 30.0 and call["exit_grace_s"] == 2.0
        assert call["env"]["PI_STARTUP_BENCHMARK"] == "1"
        assert "PERK_RUN_ID" not in call["env"]
    for call in fake.calls[:6]:
        assert call["argv"] == (str(call["cwd"] / ".venv" / "bin" / "perk"),)
        assert "NODE_OPTIONS" not in call["env"]
    targets = {
        c["env"][pi_exec.PROFILE_HANDOFF_ENV] for c in fake.calls if c["role"].startswith("handoff")
    }
    assert len(targets) == 6  # every arm of every subject has its own record file
    census_calls = [c for c in fake.calls if c["role"] == "census"]
    assert census_calls[0]["env"]["NODE_OPTIONS"].startswith("--import=file://")
    assert census_calls[0]["env"]["PERK_MODULE_CENSUS_DIR"] == str(
        out / "profiles" / "a" / "node-census"
    )

    expected_paths = [
        "meta.json",
        "subjects/a/stamp.json",
        "subjects/b/stamp.json",
        "samples/a/warmup.json",
        "samples/a/warmup.stderr.txt",
        "samples/a/001.json",
        "samples/a/001.stderr.txt",
        "samples/a/002.json",
        "samples/b/warmup.json",
        "samples/b/002.stderr.txt",
        "profiles/a/handoff-direct.json",
        "profiles/a/handoff-cprofile.json",
        "profiles/a/handoff-importtime.json",
        "profiles/a/handoff-summary.json",
        "profiles/a/cprofile.prof",
        "profiles/a/cprofile-top.txt",
        "profiles/a/importtime.log",
        "profiles/a/importtime-top.txt",
        "profiles/a/node-census/census-777.jsonl",
        "profiles/a/node-census-summary.json",
        "profiles/b/handoff-summary.json",
        "profiles/b/node-census-summary.json",
        "summary.json",
        "summary.md",
    ]
    for rel in expected_paths:
        assert (out / rel).is_file(), rel
    assert (out / "profiles" / "a" / "cpu-prof").is_dir()

    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["schema"] == 1
    assert meta["env"]["operator_node_options"] == "--operator-flag"
    assert meta["env"]["removed"] == list(harness.REMOVED_ENV)
    assert meta["schedule"] == [
        ["warmup", "a"],
        ["warmup", "b"],
        [1, "a"],
        [1, "b"],
        [2, "a"],
        [2, "b"],
    ]
    assert meta["subjects"] == [
        {"label": "a", "checkout": str(a.checkout)},
        {"label": "b", "checkout": str(b.checkout)},
    ]
    assert meta["tool"]["perk_version"] == __version__

    written = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert (out / "summary.json").read_text(encoding="utf-8") == summary_mod.summary_json_text(
        summary
    )
    assert written["subjects"][0]["samples"]["count"] == 2
    assert written["subjects"][0]["samples"]["failed"] == 0
    assert written["subjects"][0]["first_run"]["index"] == 0
    assert written["subjects"][0]["handoff"]["handoff_ms"] is not None
    assert written["subjects"][0]["handoff"]["arms"]["direct"]["status"] == "ok"
    assert written["subjects"][0]["census"]["status"] == "ok"
    assert written["subjects"][0]["census"]["lingered"] is True
    assert written["subjects"][0]["census"]["summary"]["sdk_outside_host"] == {
        "@earendil-works/pi-tui": 1
    }
    assert written["deltas"]["first"] == "a" and written["deltas"]["second"] == "b"
    assert written["env"]["operator_node_options"] == "--operator-flag"
    sample = json.loads((out / "samples" / "a" / "001.json").read_text(encoding="utf-8"))
    assert sample["index"] == 1 and sample["failed"] is False
    assert parse_pi_timings((out / "samples" / "a" / "001.stderr.txt").read_text(encoding="utf-8"))
    assert any("stamping a" in line for line in reported)
    assert any(line.startswith("  a 001:") for line in reported)


def test_run_profile_stale_direct_record_is_not_trusted(tmp_path, two_subjects):
    a, _b = two_subjects
    options = _options(tmp_path, [a], runs=1)
    stale = options.output / "profiles" / "a" / "handoff-direct.json"
    pi_exec._record_profile_handoff(
        stale, pi_path="/stale", argv=("pi",), checkout=a.checkout, env={}
    )
    fake = _FakeSpawn(pi_bin=Path(options.pi_path), write_direct_record=False)
    summary = harness.run_profile(options, spawn=fake, environ={}, report=lambda _line: None)
    handoff = summary.subjects[0].handoff
    assert handoff is not None
    assert handoff.arms["direct"].status == "no_record"
    assert handoff.handoff_ms is None
    assert not stale.exists()
    written = json.loads((options.output / "summary.json").read_text(encoding="utf-8"))
    assert written["deltas"] is None  # one subject
    assert written["subjects"][0]["handoff"]["handoff_ms"] is None


def test_run_profile_no_profiles_skips_the_profiles_tree(tmp_path, two_subjects):
    a, b = two_subjects
    options = _options(tmp_path, [a, b], runs=1, profiles=False)
    fake = _FakeSpawn(pi_bin=Path(options.pi_path))
    harness.run_profile(options, spawn=fake, environ={}, report=lambda _line: None)
    assert [c["role"] for c in fake.calls] == ["sample"] * 4
    assert not (options.output / "profiles").exists()
    written = json.loads((options.output / "summary.json").read_text(encoding="utf-8"))
    assert written["options"]["profiles"] is False
    assert all(s["handoff"] is None and s["census"] is None for s in written["subjects"])
    assert written["deltas"]["metrics"]["handoff_ms"] is None


def test_perk_dev_head_resolves_this_checkout_and_degrades_to_none(monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    assert harness.perk_dev_head() == git.head_commit(repo)
    monkeypatch.setattr(harness.git, "repo_root", lambda cwd: None)
    assert harness.perk_dev_head() is None
