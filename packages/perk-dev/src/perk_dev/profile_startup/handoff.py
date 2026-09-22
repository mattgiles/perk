"""The Python profiling arms over ``exec_pi``'s stop-before-exec seam (contracts.md §8.72(i)).

Three PTY spawns per subject (the terminal-only rule holds even though perk exits before pi),
each with the sample env plus ``PERK_PROFILE_HANDOFF=<its own target>`` and a never-firing
startup marker (the run ends at exit):

1. the **direct** arm — bare ``perk`` → ``handoff-direct.json``; ``handoff_ms`` is
   ``record.handoff_monotonic_ns - run.spawn_monotonic_ns`` (both ``CLOCK_MONOTONIC`` /
   ``mach_absolute_time``: system-wide, so the cross-process subtraction is valid) — the ONLY
   source of ``handoff_ms``;
2. the **cProfile** arm — ``python -m cProfile -o cprofile.prof -m perk`` →
   ``handoff-cprofile.json`` (cProfile's runner swallows the seam's ``SystemExit`` and still dumps
   its stats) + ``cprofile-top.txt`` (pstats, top 40 by cumulative);
3. the **importtime** arm — ``python -X importtime -m perk`` → ``handoff-importtime.json``,
   stderr saved as ``importtime.log`` + ``importtime-top.txt`` (top 30 by cumulative microseconds).

Each arm has a DISTINCT record target and the harness unlinks it before spawning, so a stale
record can never stand in for an arm that failed before the seam. A failed arm is recorded
(``ArmStatus``), never raised — including a spawn that fails outright (``OSError`` from the PTY
spawn: a raced executable or cwd), which becomes a ``failed`` arm with ``exit_code=None`` while
the remaining arms still run. Only the harness's own artifact writes may raise (an ``io_error``
for the CLI).
"""

import io
import pstats
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field

from perk.boundary import LenientParseModel, OutputModel, ValidationError
from perk.run.launch import PROFILE_HANDOFF_ENV
from perk_dev.profile_startup.pty_session import PtyRun, PtySize, SpawnFn
from perk_dev.profile_startup.subjects import Subject

ARM_NAMES: tuple[str, ...] = ("direct", "cprofile", "importtime")
CPROFILE_TOP = 40
IMPORTTIME_TOP = 30

type ArmStatusKind = Literal["ok", "no_record", "failed"]

_IMPORTTIME_ROW_RE = re.compile(
    r"^import time:\s+(?P<self_us>\d+)\s+\|\s+(?P<cumulative_us>\d+)\s+\|(?P<name>.*)$"
)


class HandoffRecord(LenientParseModel):
    """The seam's record (mirrors ``_record_profile_handoff``'s key set exactly)."""

    schema_version: int = Field(alias="schema")
    handoff_monotonic_ns: int
    pid: int
    pi_path: str
    argv: tuple[str, ...]
    cwd: str
    env_keys: tuple[str, ...]


def record_keys() -> frozenset[str]:
    """The JSON key set the record parser expects (aliases, not attribute names)."""
    return frozenset(field.alias or name for name, field in HandoffRecord.model_fields.items())


def read_handoff_record(path: Path) -> HandoffRecord | None:
    """The record at ``path``, or ``None`` when absent / unreadable / not the seam's shape."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        return HandoffRecord.model_validate_json(text)
    except ValidationError:
        return None


@dataclass(frozen=True)
class ArmStatus:
    """One arm's outcome.

    ``record_present`` — the seam's record was written and parses. ``output_present`` — the arm's
    profiling artifact exists AND is usable: a ``cprofile.prof`` pstats can load (the cProfile
    arm), an ``importtime.log`` holding at least one ``import time:`` row (the importtime arm;
    the raw stderr is saved as the log regardless), always ``True`` for the direct arm (it has no
    artifact of its own). ``ok`` = exit 0 AND ``record_present`` AND ``output_present``;
    ``no_record`` = exit 0 but the seam was never reached; ``failed`` otherwise (a non-zero exit,
    a timeout, a spawn failure — ``exit_code`` is ``None`` when nothing was spawned).
    """

    status: ArmStatusKind
    exit_code: int | None
    timed_out: bool
    record_present: bool
    output_present: bool


@dataclass(frozen=True)
class HandoffProfile:
    """The three arms' statuses and the direct arm's ``handoff_ms`` (``None`` unless ``ok``)."""

    handoff_ms: float | None
    arms: dict[str, ArmStatus]


@dataclass(frozen=True)
class ImportRow:
    """One ``-X importtime`` row: self / cumulative microseconds and the (indented) module."""

    self_us: int
    cumulative_us: int
    name: str


def parse_importtime(log_text: str) -> tuple[ImportRow, ...]:
    """Every ``import time:`` row of a ``-X importtime`` stderr log, in log order."""
    rows: list[ImportRow] = []
    for line in log_text.splitlines():
        match = _IMPORTTIME_ROW_RE.match(line.rstrip("\r"))
        if match is None:
            continue
        rows.append(
            ImportRow(
                self_us=int(match["self_us"]),
                cumulative_us=int(match["cumulative_us"]),
                name=match["name"].strip(),
            )
        )
    return tuple(rows)


def summarize_importtime(log_text: str, *, top: int = IMPORTTIME_TOP) -> tuple[ImportRow, ...]:
    """The ``top`` rows by cumulative microseconds (descending; ties by name)."""
    rows = sorted(parse_importtime(log_text), key=lambda r: (-r.cumulative_us, r.name))
    return tuple(rows[:top])


def render_importtime_top(rows: tuple[ImportRow, ...]) -> str:
    lines = [f"{'cumulative_us':>13}  {'self_us':>9}  module"]
    lines.extend(f"{r.cumulative_us:>13}  {r.self_us:>9}  {r.name}" for r in rows)
    return "\n".join(lines) + "\n"


def render_cprofile_top(prof_path: Path, *, top: int = CPROFILE_TOP) -> str | None:
    """pstats' ``sort_stats("cumulative")`` top ``top`` rows of a cProfile dump; ``None`` when
    the dump is absent or not loadable (a truncated/corrupt file — the arm's output is unusable)."""
    stream = io.StringIO()
    try:
        stats = pstats.Stats(str(prof_path), stream=stream)
    except (OSError, EOFError, TypeError, ValueError):
        return None
    stats.sort_stats("cumulative").print_stats(top)
    return stream.getvalue()


def _arm_status(run: PtyRun, *, record_present: bool, output_present: bool) -> ArmStatusKind:
    if run.exit_code == 0 and record_present and output_present and not run.timed_out:
        return "ok"
    if run.exit_code == 0 and not record_present and not run.timed_out:
        return "no_record"
    return "failed"


def handoff_targets(profiles_dir: Path) -> dict[str, Path]:
    """Each arm's distinct record file under the subject's profiles dir."""
    return {name: profiles_dir / f"handoff-{name}.json" for name in ARM_NAMES}


def run_handoff_arms(
    subject: Subject,
    *,
    env: Mapping[str, str],
    profiles_dir: Path,
    spawn: SpawnFn,
    size: PtySize,
    timeout_s: float,
    exit_grace_s: float,
    report: Callable[[str], None],
) -> HandoffProfile:
    """Run the three arms for one subject and write their artifacts (see the module doc)."""
    profiles_dir.mkdir(parents=True, exist_ok=True)
    targets = handoff_targets(profiles_dir)
    prof_path = profiles_dir / "cprofile.prof"
    log_path = profiles_dir / "importtime.log"
    argvs: dict[str, tuple[str, ...]] = {
        "direct": (str(subject.executable),),
        "cprofile": (str(subject.python), "-m", "cProfile", "-o", str(prof_path), "-m", "perk"),
        "importtime": (str(subject.python), "-X", "importtime", "-m", "perk"),
    }
    arms: dict[str, ArmStatus] = {}
    handoff_ms: float | None = None
    for name in ARM_NAMES:
        target = targets[name]
        target.unlink(missing_ok=True)  # never let a stale record stand in for this arm
        if name == "cprofile":
            prof_path.unlink(missing_ok=True)
        report(f"  {subject.label}: {name} arm")
        try:
            run = spawn(
                argvs[name],
                cwd=subject.checkout,
                env={**env, PROFILE_HANDOFF_ENV: str(target)},
                size=size,
                timeout_s=timeout_s,
                exit_grace_s=exit_grace_s,
                startup_marker=lambda _line: False,
            )
        except OSError as exc:
            # Nothing was spawned: a failed arm, recorded like any other; the remaining arms run.
            report(f"  {subject.label}: {name} arm could not spawn ({exc})")
            arms[name] = ArmStatus(
                status="failed",
                exit_code=None,
                timed_out=False,
                record_present=False,
                output_present=False,
            )
            continue
        record = read_handoff_record(target)
        output_present = True
        if name == "cprofile":
            rendered = render_cprofile_top(prof_path)
            output_present = rendered is not None
            if rendered is not None:
                (profiles_dir / "cprofile-top.txt").write_text(rendered, encoding="utf-8")
        elif name == "importtime":
            log_path.write_text(run.stderr, encoding="utf-8")  # the raw log, rows or not
            rows = summarize_importtime(run.stderr)
            output_present = bool(rows)  # usable = at least one `import time:` row
            (profiles_dir / "importtime-top.txt").write_text(
                render_importtime_top(rows), encoding="utf-8"
            )
        status = _arm_status(run, record_present=record is not None, output_present=output_present)
        arms[name] = ArmStatus(
            status=status,
            exit_code=run.exit_code,
            timed_out=run.timed_out,
            record_present=record is not None,
            output_present=output_present,
        )
        if name == "direct" and status == "ok" and record is not None:
            handoff_ms = (record.handoff_monotonic_ns - run.spawn_monotonic_ns) / 1e6
    return HandoffProfile(handoff_ms=handoff_ms, arms=arms)


# --- the --json snapshot --------------------------------------------------------------------------


class ArmStatusOut(OutputModel):
    status: str
    exit_code: int | None
    timed_out: bool
    record_present: bool
    output_present: bool


class HandoffProfileOut(OutputModel):
    handoff_ms: float | None
    arms: dict[str, ArmStatusOut]

    @classmethod
    def from_domain(cls, p: HandoffProfile) -> "HandoffProfileOut":
        return cls(
            handoff_ms=p.handoff_ms,
            arms={
                name: ArmStatusOut(
                    status=arm.status,
                    exit_code=arm.exit_code,
                    timed_out=arm.timed_out,
                    record_present=arm.record_present,
                    output_present=arm.output_present,
                )
                for name, arm in p.arms.items()
            },
        )
