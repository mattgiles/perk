"""The run: sample environment, schedule, run-directory writes, and the profiled arms.

``run_profile`` orchestrates one measurement: write ``meta.json`` → stamp every subject (the
probe/trust preflight — every refusal lands before any sample is spawned) → one discarded
warm-up per subject → ``runs`` rounds, every subject in order per round (alternation spreads
machine-load drift across subjects) → unless ``--no-profiles``, the profiled arms per subject
AFTER all timing samples (they never mix into the statistics) → ``summary.json`` + ``summary.md``.
Every sample spawns ``(subject.executable,)`` — bare ``perk``, argv literally the console script
— with ``cwd=checkout``.

The sample env is the inherited environment minus :data:`REMOVED_ENV` (an operator's Node
startup flags would change both the timings and the module graph, and a perk run id / profiling
variable inherited from a perk session must not leak into the measured launch — the removed
``NODE_OPTIONS`` value is RECORDED as ``operator_node_options``), plus a ``TERM`` default only
when absent, plus :data:`INJECTED_ENV`. ``PI_CODING_AGENT_DIR`` is inherited untouched — the
same posture as perk's own launches; the resolved agent dir is recorded per subject.

Run directory layout (under ``--output``)::

    meta.json                          schema, started_at, tool, host, options, env, pty_size,
                                       subjects (label + checkout, in order), schedule
    subjects/<label>/stamp.json        SubjectStamp
    samples/<label>/warmup.json        the discarded first run (+ warmup.stderr.txt)
    samples/<label>/<NNN>.json         Sample (+ <NNN>.stderr.txt)
    profiles/<label>/handoff-*.json    the seam's raw records, one per Python arm
    profiles/<label>/handoff-summary.json / cprofile.prof / cprofile-top.txt /
                     importtime.log / importtime-top.txt
    profiles/<label>/node-census/census-<pid>.jsonl, node-census-summary.json,
                     cpu-prof/*.cpuprofile
    summary.json / summary.md
"""

import json
import os
import platform
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import perk_dev
from perk import __version__ as perk_version
from perk.cli.ensure import UserFacingCliError
from perk.substrate import git
from perk_dev.profile_startup import census as census_mod
from perk_dev.profile_startup import handoff as handoff_mod
from perk_dev.profile_startup.census import CensusRunOut
from perk_dev.profile_startup.handoff import HandoffProfileOut
from perk_dev.profile_startup.pty_session import PtyRun, PtySize, SpawnFn, spawn_pty
from perk_dev.profile_startup.subjects import Subject, SubjectStamp, stamp_subject
from perk_dev.profile_startup.summary import (
    EnvInfo,
    HostInfo,
    RunOptions,
    Sample,
    SampleOut,
    SubjectStampOut,
    SubjectSummary,
    Summary,
    ToolInfo,
    build_summary,
    classify_sample,
    render_summary_md,
    summary_json_text,
)
from perk_dev.profile_startup.timings import TimingsScanner

INJECTED_ENV: dict[str, str] = {
    "PI_STARTUP_BENCHMARK": "1",
    "PI_TIMING": "1",  # Pi compares this to the literal "1"
    "PI_OFFLINE": "1",
}
REMOVED_ENV: tuple[str, ...] = (
    "PERK_RUN_ID",
    "PERK_PROFILE_HANDOFF",
    "PERK_MODULE_CENSUS_DIR",
    "NODE_OPTIONS",
)
DEFAULT_TERM = "xterm-256color"
META_SCHEMA = 1
WARMUP = "warmup"

type ScheduleEntry = tuple[str | int, str]


@dataclass(frozen=True)
class ProfileOptions:
    """Everything a run needs, already validated by the CLI."""

    subjects: tuple[Subject, ...]
    runs: int
    output: Path
    timeout_s: float
    exit_grace_s: float
    pty_size: PtySize
    profiles: bool
    pi_path: str
    node_path: str


@dataclass(frozen=True)
class SampleEnv:
    env: dict[str, str]
    operator_node_options: str | None


def build_sample_env(environ: Mapping[str, str]) -> SampleEnv:
    """The env every spawned process receives (see the module doc)."""
    env = {k: v for k, v in environ.items() if k not in REMOVED_ENV}
    env.setdefault("TERM", DEFAULT_TERM)
    env.update(INJECTED_ENV)
    return SampleEnv(env=env, operator_node_options=environ.get("NODE_OPTIONS"))


def schedule(subjects: Sequence[Subject], runs: int) -> tuple[ScheduleEntry, ...]:
    """``("warmup", label)`` per subject in order, then rounds ``1..runs`` over every subject."""
    entries: list[ScheduleEntry] = [(WARMUP, s.label) for s in subjects]
    for round_number in range(1, runs + 1):
        entries.extend((round_number, s.label) for s in subjects)
    return tuple(entries)


def perk_dev_head() -> str | None:
    """The running ``perk_dev`` package's checkout HEAD (``None`` outside a git checkout or when
    the probe cannot answer — provenance, never a refusal)."""
    root = git.repo_root(Path(perk_dev.__file__).resolve().parent)
    if root is None:
        return None
    try:
        return git.head_commit(root)
    except git.GitError:
        return None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _sample_name(entry: ScheduleEntry) -> str:
    kind, _label = entry
    return WARMUP if kind == WARMUP else f"{int(kind):03d}"


def _spawn_sample(
    subject: Subject, *, options: ProfileOptions, env: Mapping[str, str], spawn: SpawnFn
) -> tuple[PtyRun, bool]:
    scanner = TimingsScanner()
    try:
        run = spawn(
            (str(subject.executable),),
            cwd=subject.checkout,
            env=env,
            size=options.pty_size,
            timeout_s=options.timeout_s,
            exit_grace_s=options.exit_grace_s,
            startup_marker=scanner.feed,
        )
    except OSError as exc:
        raise UserFacingCliError(
            f"subject {subject.label}: could not spawn {subject.executable}: {exc}",
            error_type="subject_probe_failed",
        ) from exc
    return run, scanner.seen


def _describe(sample: Sample) -> str:
    if sample.failed:
        return f"FAILED ({sample.failure})"
    flags = " lingered" if sample.lingered else ""
    return (
        f"elapsed {sample.elapsed_ms:.1f} ms · pi main {sample.pi_main_total_ms} ms · "
        f"exit {'n/a' if sample.exit_ms is None else f'{sample.exit_ms:.1f} ms'}{flags}"
    )


def run_profile(
    options: ProfileOptions,
    *,
    spawn: SpawnFn = spawn_pty,
    environ: Mapping[str, str] = os.environ,
    report: Callable[[str], None],
) -> Summary:
    """Run one measurement into ``options.output`` (see the module doc) and return its summary.

    ``OSError`` from a run-directory write propagates (the CLI maps it to ``io_error`` and names
    the partial directory); a subject refusal (``subject_probe_failed`` / ``subject_untrusted``)
    propagates as ``UserFacingCliError`` before any sample is spawned.
    """
    out = options.output
    started_at = _now()
    sample_env = build_sample_env(environ)
    plan = schedule(options.subjects, options.runs)
    tool = ToolInfo(perk_version=perk_version, perk_dev_head=perk_dev_head())
    host = HostInfo(
        platform=platform.platform(), machine=platform.machine(), cpu_count=os.cpu_count()
    )
    run_options = RunOptions(
        runs=options.runs,
        timeout_s=options.timeout_s,
        exit_grace_s=options.exit_grace_s,
        pty_size=options.pty_size,
        profiles=options.profiles,
    )
    env_info = EnvInfo(
        injected=dict(INJECTED_ENV),
        removed=REMOVED_ENV,
        operator_node_options=sample_env.operator_node_options,
    )
    out.mkdir(parents=True, exist_ok=True)
    _write_json(
        out / "meta.json",
        {
            "schema": META_SCHEMA,
            "started_at": started_at,
            "tool": asdict(tool),
            "host": asdict(host),
            "options": {
                "runs": options.runs,
                "timeout_s": options.timeout_s,
                "exit_grace_s": options.exit_grace_s,
                "profiles": options.profiles,
            },
            "env": {
                "injected": dict(INJECTED_ENV),
                "removed": list(REMOVED_ENV),
                "operator_node_options": sample_env.operator_node_options,
            },
            "pty_size": {"cols": options.pty_size.cols, "rows": options.pty_size.rows},
            "subjects": [{"label": s.label, "checkout": str(s.checkout)} for s in options.subjects],
            "schedule": [list(entry) for entry in plan],
        },
    )

    # Stamps: the probe/trust preflight — every subject is decided before any sample spawns.
    stamps: dict[str, SubjectStamp] = {}
    for subject in options.subjects:
        report(f"stamping {subject.label} ({subject.checkout})")
        stamp = stamp_subject(subject, pi_path=options.pi_path, node_path=options.node_path)
        stamps[subject.label] = stamp
        _write_json(
            out / "subjects" / subject.label / "stamp.json",
            SubjectStampOut.from_domain(stamp).model_dump(mode="json"),
        )

    by_label = {s.label: s for s in options.subjects}
    first_runs: dict[str, Sample] = {}
    samples: dict[str, list[Sample]] = {s.label: [] for s in options.subjects}
    for entry in plan:
        kind, label = entry
        subject = by_label[label]
        name = _sample_name(entry)
        run, _seen = _spawn_sample(subject, options=options, env=sample_env.env, spawn=spawn)
        sample = classify_sample(run, index=0 if kind == WARMUP else int(kind))
        _write_json(
            out / "samples" / label / f"{name}.json",
            SampleOut.from_domain(sample).model_dump(mode="json"),
        )
        _write_text(out / "samples" / label / f"{name}.stderr.txt", run.stderr)
        if kind == WARMUP:
            first_runs[label] = sample
        else:
            samples[label].append(sample)
        report(f"  {label} {name}: {_describe(sample)}")

    handoffs: dict[str, handoff_mod.HandoffProfile] = {}
    censuses: dict[str, census_mod.CensusRun] = {}
    if options.profiles:
        for subject in options.subjects:
            profiles_dir = out / "profiles" / subject.label
            report(f"profiling {subject.label}")
            profile = handoff_mod.run_handoff_arms(
                subject,
                env=sample_env.env,
                profiles_dir=profiles_dir,
                spawn=spawn,
                size=options.pty_size,
                timeout_s=options.timeout_s,
                exit_grace_s=options.exit_grace_s,
                report=report,
            )
            handoffs[subject.label] = profile
            _write_json(
                profiles_dir / "handoff-summary.json",
                HandoffProfileOut.from_domain(profile).model_dump(mode="json"),
            )
            census = census_mod.run_census_arm(
                subject,
                env=sample_env.env,
                profiles_dir=profiles_dir,
                pi_path=options.pi_path,
                spawn=spawn,
                size=options.pty_size,
                timeout_s=options.timeout_s,
                exit_grace_s=options.exit_grace_s,
                report=report,
            )
            censuses[subject.label] = census
            _write_json(
                profiles_dir / "node-census-summary.json",
                CensusRunOut.from_domain(census).model_dump(mode="json"),
            )

    summary = build_summary(
        started_at=started_at,
        finished_at=_now(),
        tool=tool,
        host=host,
        options=run_options,
        env=env_info,
        subjects=[
            SubjectSummary(
                label=s.label,
                checkout=str(s.checkout),
                stamp=stamps[s.label],
                first_run=first_runs.get(s.label),
                samples=tuple(samples[s.label]),
                handoff=handoffs.get(s.label),
                census=censuses.get(s.label),
            )
            for s in options.subjects
        ],
    )
    _write_text(out / "summary.json", summary_json_text(summary))
    _write_text(out / "summary.md", render_summary_md(summary))
    return summary
