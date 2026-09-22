"""The run summary: per-sample classification, statistics, the ``--json`` snapshot, and the
Markdown render.

``elapsed_ms`` is stamped in the HARNESS: from its ``Popen`` call to the moment it observes Pi's
``main`` ``TOTAL`` line on the stderr pipe — so it includes process creation/exec and the
harness's own read latency, not only work inside the console script. ``pre_pi_remainder_ms =
elapsed_ms - pi_main_total_ms`` is therefore a DERIVED ESTIMATE of everything OUTSIDE Pi's own
``main`` timing (Pi's ``resetTimings()`` runs at its ``main()`` entry, so Pi's totals exclude all
of it): process spawn/exec, Python (perk) up to the exec handoff, Node boot to Pi's ``main()``,
Pi's fixed 150 ms benchmark settle, and the marker-observation latency. Every surface that prints
it says so. Statistics exclude failed samples and the discarded warm-up
(``first_run`` is reported apart). A two-subject run carries a delta block — reported, never
judged: there is no verdict vocabulary here.
"""

import json
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import Field

from perk.boundary import OutputModel
from perk_dev.profile_startup.census import CensusRun, CensusRunOut
from perk_dev.profile_startup.handoff import HandoffProfile, HandoffProfileOut
from perk_dev.profile_startup.pty_session import PtyRun, PtySize
from perk_dev.profile_startup.subjects import SubjectStamp
from perk_dev.profile_startup.timings import MAIN_NAMESPACE, TimingGroup, parse_pi_timings

EXTENSIONS_NAMESPACE = "extensions"
REMAINDER_CAVEAT = (
    "derived estimate: elapsed_ms - Pi's `main` TOTAL = everything outside Pi's own timing: "
    "process spawn/exec, Python (perk) up to the exec handoff, Node boot to Pi's `main()`, Pi's "
    "fixed 150 ms benchmark settle, and the harness's marker-observation latency"
)
_TOP_EXTENSION_ROWS = 10


# --- domain ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Sample:
    """One classified spawn (a timing sample or the warm-up)."""

    index: int
    elapsed_ms: float | None
    exit_ms: float | None
    exit_code: int | None
    timed_out: bool
    lingered: bool
    failed: bool
    failure: str | None
    pi_main_total_ms: int | None
    pre_pi_remainder_ms: float | None
    extension_rows: tuple[tuple[str, int], ...]
    groups: dict[str, TimingGroup]


@dataclass(frozen=True)
class Stats:
    median: float
    min: float
    max: float
    count: int


@dataclass(frozen=True)
class ExtensionRowStats:
    label: str
    stats: Stats


@dataclass(frozen=True)
class Delta:
    """``second - first`` over medians; ``delta_pct`` relative to the first."""

    delta_ms: float
    delta_pct: float | None


@dataclass(frozen=True)
class SubjectSummary:
    label: str
    checkout: str
    stamp: SubjectStamp
    first_run: Sample | None
    samples: tuple[Sample, ...]
    handoff: HandoffProfile | None
    census: CensusRun | None


@dataclass(frozen=True)
class ToolInfo:
    perk_version: str
    perk_dev_head: str | None


@dataclass(frozen=True)
class HostInfo:
    platform: str
    machine: str
    cpu_count: int | None


@dataclass(frozen=True)
class RunOptions:
    runs: int
    timeout_s: float
    exit_grace_s: float
    pty_size: PtySize
    profiles: bool


@dataclass(frozen=True)
class EnvInfo:
    injected: dict[str, str]
    removed: tuple[str, ...]
    operator_node_options: str | None


@dataclass(frozen=True)
class Summary:
    started_at: str
    finished_at: str
    tool: ToolInfo
    host: HostInfo
    options: RunOptions
    env: EnvInfo
    subjects: tuple[SubjectSummary, ...]


# --- classification + statistics ------------------------------------------------------------------


def classify_sample(run: PtyRun, *, index: int) -> Sample:
    """Turn one PTY run into a :class:`Sample` (``failed`` when timed out, exited non-zero
    without a ``main`` group, or the ``main`` group never appeared)."""
    groups = parse_pi_timings(run.stderr)
    main = groups.get(MAIN_NAMESPACE)
    failure: str | None = None
    if run.timed_out:
        failure = "timed_out: the `main` TOTAL line never appeared before --timeout"
    elif main is None and run.exit_code != 0:
        failure = f"exit {run.exit_code} without a `main` timing group"
    elif main is None:
        failure = "no `main` timing group in stderr"
    extensions = groups.get(EXTENSIONS_NAMESPACE)
    remainder = (
        run.elapsed_ms - main.total_ms
        if main is not None and run.elapsed_ms is not None and failure is None
        else None
    )
    return Sample(
        index=index,
        elapsed_ms=run.elapsed_ms if failure is None else None,
        exit_ms=run.exit_ms,
        exit_code=run.exit_code,
        timed_out=run.timed_out,
        lingered=run.lingered,
        failed=failure is not None,
        failure=failure,
        pi_main_total_ms=main.total_ms if main is not None and failure is None else None,
        pre_pi_remainder_ms=remainder,
        extension_rows=tuple((r.label, r.ms) for r in extensions.rows) if extensions else (),
        groups=groups,
    )


def stats_of(values: Sequence[float]) -> Stats | None:
    if not values:
        return None
    return Stats(
        median=float(statistics.median(values)),
        min=float(min(values)),
        max=float(max(values)),
        count=len(values),
    )


def successful(samples: Sequence[Sample]) -> tuple[Sample, ...]:
    return tuple(s for s in samples if not s.failed)


def metric_stats(samples: Sequence[Sample], metric: str) -> Stats | None:
    values = [getattr(s, metric) for s in successful(samples)]
    return stats_of([float(v) for v in values if v is not None])


def extension_row_stats(samples: Sequence[Sample]) -> tuple[ExtensionRowStats, ...]:
    """Per-label statistics over the successful samples, median descending (ties by label)."""
    by_label: dict[str, list[float]] = {}
    for sample in successful(samples):
        for label, ms in sample.extension_rows:
            by_label.setdefault(label, []).append(float(ms))
    rows = [
        ExtensionRowStats(label=label, stats=stats)
        for label, values in by_label.items()
        if (stats := stats_of(values)) is not None
    ]
    return tuple(sorted(rows, key=lambda r: (-r.stats.median, r.label)))


def _delta(first: float | None, second: float | None) -> Delta | None:
    if first is None or second is None:
        return None
    delta_ms = second - first
    return Delta(delta_ms=delta_ms, delta_pct=(delta_ms / first * 100.0) if first else None)


def _median_or_none(stats: Stats | None) -> float | None:
    return stats.median if stats is not None else None


def compute_deltas(subjects: Sequence[SubjectSummary]) -> dict[str, Delta | None] | None:
    """The four metric deltas for exactly two subjects (``None`` otherwise)."""
    if len(subjects) != 2:
        return None
    first, second = subjects
    handoff = (
        first.handoff.handoff_ms if first.handoff else None,
        second.handoff.handoff_ms if second.handoff else None,
    )
    return {
        "elapsed_ms": _delta(
            _median_or_none(metric_stats(first.samples, "elapsed_ms")),
            _median_or_none(metric_stats(second.samples, "elapsed_ms")),
        ),
        "pi_main_total_ms": _delta(
            _median_or_none(metric_stats(first.samples, "pi_main_total_ms")),
            _median_or_none(metric_stats(second.samples, "pi_main_total_ms")),
        ),
        "pre_pi_remainder_ms": _delta(
            _median_or_none(metric_stats(first.samples, "pre_pi_remainder_ms")),
            _median_or_none(metric_stats(second.samples, "pre_pi_remainder_ms")),
        ),
        "handoff_ms": _delta(*handoff),
    }


def build_summary(
    *,
    started_at: str,
    finished_at: str,
    tool: ToolInfo,
    host: HostInfo,
    options: RunOptions,
    env: EnvInfo,
    subjects: Sequence[SubjectSummary],
) -> Summary:
    return Summary(
        started_at=started_at,
        finished_at=finished_at,
        tool=tool,
        host=host,
        options=options,
        env=env,
        subjects=tuple(subjects),
    )


# --- the --json snapshot (field order as written; `schema` first) ---------------------------------


class StatsOut(OutputModel):
    median: float
    min: float
    max: float
    count: int

    @classmethod
    def from_domain(cls, s: Stats | None) -> "StatsOut | None":
        if s is None:
            return None
        return cls(median=s.median, min=s.min, max=s.max, count=s.count)


class TimingRowOut(OutputModel):
    label: str
    ms: int


class TimingGroupOut(OutputModel):
    rows: tuple[TimingRowOut, ...]
    total_ms: int


class SampleOut(OutputModel):
    index: int
    elapsed_ms: float | None
    exit_ms: float | None
    exit_code: int | None
    timed_out: bool
    lingered: bool
    failed: bool
    failure: str | None
    pi_main_total_ms: int | None
    pre_pi_remainder_ms: float | None
    extension_rows: tuple[TimingRowOut, ...]
    groups: dict[str, TimingGroupOut]

    @classmethod
    def from_domain(cls, s: Sample) -> "SampleOut":
        return cls(
            index=s.index,
            elapsed_ms=s.elapsed_ms,
            exit_ms=s.exit_ms,
            exit_code=s.exit_code,
            timed_out=s.timed_out,
            lingered=s.lingered,
            failed=s.failed,
            failure=s.failure,
            pi_main_total_ms=s.pi_main_total_ms,
            pre_pi_remainder_ms=s.pre_pi_remainder_ms,
            extension_rows=tuple(
                TimingRowOut(label=label, ms=ms) for label, ms in s.extension_rows
            ),
            groups={
                namespace: TimingGroupOut(
                    rows=tuple(TimingRowOut(label=r.label, ms=r.ms) for r in group.rows),
                    total_ms=group.total_ms,
                )
                for namespace, group in s.groups.items()
            },
        )


class SdkCopyOut(OutputModel):
    name: str
    root: str
    version: str | None


class SubjectStampOut(OutputModel):
    head: str
    dirty: bool
    perk_version: str
    pi_version: str
    pi_path: str
    node_version: str
    packages: dict[str, str | None]
    sdk_copies: tuple[SdkCopyOut, ...]
    agent_dir: str | None
    agent_dir_source: str | None
    trusted_by: str

    @classmethod
    def from_domain(cls, s: SubjectStamp) -> "SubjectStampOut":
        return cls(
            head=s.head,
            dirty=s.dirty,
            perk_version=s.perk_version,
            pi_version=s.pi_version,
            pi_path=s.pi_path,
            node_version=s.node_version,
            packages=dict(s.packages),
            sdk_copies=tuple(
                SdkCopyOut(name=c.name, root=c.root, version=c.version) for c in s.sdk_copies
            ),
            agent_dir=s.agent_dir,
            agent_dir_source=s.agent_dir_source,
            trusted_by=s.trusted_by,
        )


class SampleStatsOut(OutputModel):
    count: int
    failed: int
    elapsed_ms: StatsOut | None
    pi_main_total_ms: StatsOut | None
    pre_pi_remainder_ms: StatsOut | None


class ExtensionRowStatsOut(OutputModel):
    label: str
    stats: StatsOut


class SubjectSummaryOut(OutputModel):
    label: str
    checkout: str
    stamp: SubjectStampOut
    first_run: SampleOut | None
    samples: SampleStatsOut
    extension_rows: tuple[ExtensionRowStatsOut, ...]
    handoff: HandoffProfileOut | None
    census: CensusRunOut | None

    @classmethod
    def from_domain(cls, s: SubjectSummary) -> "SubjectSummaryOut":
        return cls(
            label=s.label,
            checkout=s.checkout,
            stamp=SubjectStampOut.from_domain(s.stamp),
            first_run=SampleOut.from_domain(s.first_run) if s.first_run is not None else None,
            samples=SampleStatsOut(
                count=len(s.samples),
                failed=sum(1 for x in s.samples if x.failed),
                elapsed_ms=StatsOut.from_domain(metric_stats(s.samples, "elapsed_ms")),
                pi_main_total_ms=StatsOut.from_domain(metric_stats(s.samples, "pi_main_total_ms")),
                pre_pi_remainder_ms=StatsOut.from_domain(
                    metric_stats(s.samples, "pre_pi_remainder_ms")
                ),
            ),
            extension_rows=tuple(
                ExtensionRowStatsOut(
                    label=r.label,
                    stats=StatsOut(
                        median=r.stats.median,
                        min=r.stats.min,
                        max=r.stats.max,
                        count=r.stats.count,
                    ),
                )
                for r in extension_row_stats(s.samples)
            ),
            handoff=HandoffProfileOut.from_domain(s.handoff) if s.handoff is not None else None,
            census=CensusRunOut.from_domain(s.census) if s.census is not None else None,
        )


class DeltaOut(OutputModel):
    delta_ms: float
    delta_pct: float | None


class DeltaMetricsOut(OutputModel):
    elapsed_ms: DeltaOut | None
    pi_main_total_ms: DeltaOut | None
    pre_pi_remainder_ms: DeltaOut | None
    handoff_ms: DeltaOut | None


class DeltasOut(OutputModel):
    first: str
    second: str
    metrics: DeltaMetricsOut


class ToolOut(OutputModel):
    perk_version: str
    perk_dev_head: str | None


class HostOut(OutputModel):
    platform: str
    machine: str
    cpu_count: int | None


class PtySizeOut(OutputModel):
    cols: int
    rows: int


class OptionsOut(OutputModel):
    runs: int
    timeout_s: float
    exit_grace_s: float
    pty_size: PtySizeOut
    profiles: bool


class EnvOut(OutputModel):
    injected: dict[str, str]
    removed: tuple[str, ...]
    operator_node_options: str | None


class SummaryOut(OutputModel):
    """The machine snapshot — the SAME bytes go to ``summary.json`` and to ``--json`` stdout.

    ``schema_version`` serializes as ``schema`` (a field literally named ``schema`` would shadow
    ``BaseModel.schema``); dump with ``by_alias=True`` — :func:`summary_json_text` does.
    """

    schema_version: int = Field(serialization_alias="schema")
    started_at: str
    finished_at: str
    tool: ToolOut
    host: HostOut
    options: OptionsOut
    env: EnvOut
    subjects: tuple[SubjectSummaryOut, ...]
    deltas: DeltasOut | None

    @classmethod
    def from_domain(cls, s: Summary) -> "SummaryOut":
        deltas = compute_deltas(s.subjects)
        return cls(
            schema_version=1,
            started_at=s.started_at,
            finished_at=s.finished_at,
            tool=ToolOut(perk_version=s.tool.perk_version, perk_dev_head=s.tool.perk_dev_head),
            host=HostOut(
                platform=s.host.platform, machine=s.host.machine, cpu_count=s.host.cpu_count
            ),
            options=OptionsOut(
                runs=s.options.runs,
                timeout_s=s.options.timeout_s,
                exit_grace_s=s.options.exit_grace_s,
                pty_size=PtySizeOut(cols=s.options.pty_size.cols, rows=s.options.pty_size.rows),
                profiles=s.options.profiles,
            ),
            env=EnvOut(
                injected=dict(s.env.injected),
                removed=s.env.removed,
                operator_node_options=s.env.operator_node_options,
            ),
            subjects=tuple(SubjectSummaryOut.from_domain(x) for x in s.subjects),
            deltas=(
                DeltasOut(
                    first=s.subjects[0].label,
                    second=s.subjects[1].label,
                    metrics=DeltaMetricsOut(
                        **{
                            name: (
                                DeltaOut(delta_ms=d.delta_ms, delta_pct=d.delta_pct)
                                if d is not None
                                else None
                            )
                            for name, d in deltas.items()
                        }
                    ),
                )
                if deltas is not None
                else None
            ),
        )


def summary_json_text(summary: Summary) -> str:
    """The exact ``summary.json`` bytes (``schema`` is the first key)."""
    dumped = SummaryOut.from_domain(summary).model_dump(mode="json", by_alias=True)
    return json.dumps(dumped, indent=2) + "\n"


# --- the Markdown render --------------------------------------------------------------------------


def _fmt(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _stats_cell(stats: Stats | None, *, ok: int, failed: int) -> str:
    if stats is None:
        return f"n/a ({ok} ok / {failed} failed)"
    return f"{_fmt(stats.median)} [{_fmt(stats.min)}-{_fmt(stats.max)}] ({ok} ok / {failed} failed)"


def _metric_table(
    subjects: Sequence[SubjectSummary], metric: str, title: str, caveat: str | None = None
) -> list[str]:
    lines = [f"## {title}", ""]
    if caveat:
        lines += [f"_{caveat}_", ""]
    lines += ["| subject | median [min-max] (n ok / n failed) |", "|---|---|"]
    for s in subjects:
        ok = len(successful(s.samples))
        failed = len(s.samples) - ok
        lines.append(
            f"| {s.label} | {_stats_cell(metric_stats(s.samples, metric), ok=ok, failed=failed)} |"
        )
    lines.append("")
    return lines


def _census_line(census: CensusRun) -> str:
    if census.status != "ok" or census.summary is None:
        detail = f" — {census.failure}" if census.failure else ""
        return f"{census.status}{detail}"
    s = census.summary
    parts = [
        "ok" + (" (lingered)" if census.lingered else ""),
        f"{s.distinct_modules} distinct modules",
        f"{s.builtin_modules} builtin",
        f"{s.host_modules} under the host root",
        f"SDK modules outside the host root: {s.sdk_outside_host_total}",
    ]
    for root in s.sdk_outside_host_roots:
        parts.append(f"{root.name} {root.modules} @ {root.root} ({root.version or 'version n/a'})")
    return " · ".join(parts)


def render_summary_md(summary: Summary) -> str:
    """The human rendering of a run (also printed to stderr)."""
    o = summary.options
    lines: list[str] = ["# perk startup profile", ""]
    lines += [
        f"- started {summary.started_at} · finished {summary.finished_at}",
        f"- perk-dev {summary.tool.perk_version} (perk-dev head "
        f"{summary.tool.perk_dev_head or 'n/a'}) · host {summary.host.platform} "
        f"{summary.host.machine} · {summary.host.cpu_count} CPUs",
        f"- runs {o.runs} per subject (+1 discarded warm-up) · PTY {o.pty_size.cols}x"
        f"{o.pty_size.rows} · timeout {o.timeout_s:g} s · exit grace {o.exit_grace_s:g} s · "
        f"profiles {'on' if o.profiles else 'off'}",
        "- injected env: "
        + " ".join(f"{k}={v}" for k, v in summary.env.injected.items())
        + " · removed: "
        + ", ".join(summary.env.removed),
    ]
    if summary.env.operator_node_options is not None:
        lines.append(
            f"- operator NODE_OPTIONS removed from every spawn: "
            f"`{summary.env.operator_node_options}`"
        )
    lines += ["", "## subjects", ""]
    lines += [
        "| subject | checkout | revision | dirty | perk | pi | node | agent dir | trust |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summary.subjects:
        st = s.stamp
        lines.append(
            f"| {s.label} | {s.checkout} | {st.head[:12]} | {'yes' if st.dirty else 'no'} | "
            f"{st.perk_version} | {st.pi_version} | {st.node_version} | "
            f"{st.agent_dir or 'n/a'} ({st.agent_dir_source or 'n/a'}) | {st.trusted_by} |"
        )
    lines.append("")
    for s in summary.subjects:
        copies = ", ".join(f"{c.name} {c.version or 'n/a'} @ {c.root}" for c in s.stamp.sdk_copies)
        lines.append(f"- {s.label} SDK copies installed: {copies or 'none'}")
        packages = ", ".join(f"{n} {v or 'n/a'}" for n, v in s.stamp.packages.items())
        lines.append(f"- {s.label} consumer packages: {packages or 'none'}")
    lines.append("")
    lines += _metric_table(
        summary.subjects,
        "elapsed_ms",
        "elapsed_ms (the harness's spawn call → Pi's `main` TOTAL line observed on stderr)",
    )
    lines += _metric_table(
        summary.subjects, "pi_main_total_ms", "pi_main_total_ms (Pi's own `main` TOTAL)"
    )
    lines += _metric_table(
        summary.subjects,
        "pre_pi_remainder_ms",
        "pre_pi_remainder_ms",
        caveat=REMAINDER_CAVEAT,
    )
    lines += ["## first run (the warm-up — reported apart, never in the statistics)", ""]
    lines += [
        "| subject | elapsed_ms | pi_main_total_ms | pre_pi_remainder_ms | failed |",
        "|---|---|---|---|---|",
    ]
    for s in summary.subjects:
        f = s.first_run
        if f is None:
            lines.append(f"| {s.label} | n/a | n/a | n/a | n/a |")
        else:
            total = f.pi_main_total_ms if f.pi_main_total_ms is not None else "n/a"
            lines.append(
                f"| {s.label} | {_fmt(f.elapsed_ms)} | {total} | "
                f"{_fmt(f.pre_pi_remainder_ms)} | {f.failure or 'no'} |"
            )
    lines.append("")
    lines += [
        f"## top {_TOP_EXTENSION_ROWS} extension rows (median ms, successful samples only)",
        "",
    ]
    for s in summary.subjects:
        rows = extension_row_stats(s.samples)[:_TOP_EXTENSION_ROWS]
        lines.append(f"### {s.label}")
        lines.append("")
        if not rows:
            lines.append("_no extension rows_")
        else:
            lines += ["| row | median [min-max] (n) |", "|---|---|"]
            for r in rows:
                lines.append(
                    f"| {r.label} | {_fmt(r.stats.median)} [{_fmt(r.stats.min)}-"
                    f"{_fmt(r.stats.max)}] ({r.stats.count}) |"
                )
        lines.append("")
    lines += ["## handoff (Python → Pi, the stop-before-exec seam)", ""]
    for s in summary.subjects:
        if s.handoff is None:
            lines.append(f"- {s.label}: not profiled (--no-profiles)")
            continue
        arms = " · ".join(f"{name} {arm.status}" for name, arm in s.handoff.arms.items())
        lines.append(f"- {s.label}: handoff_ms {_fmt(s.handoff.handoff_ms)} · {arms}")
    lines.append("")
    lines += ["## Node module census", ""]
    for s in summary.subjects:
        if s.census is None:
            lines.append(f"- {s.label}: not profiled (--no-profiles)")
            continue
        lines.append(f"- {s.label}: {_census_line(s.census)}")
    lines.append("")
    deltas = compute_deltas(summary.subjects)
    if deltas is not None:
        first, second = summary.subjects
        lines += [
            f"## delta ({second.label} - {first.label}, over medians; reported, not judged)",
            "",
            "| metric | Δ ms | Δ % |",
            "|---|---|---|",
        ]
        for name, d in deltas.items():
            if d is None:
                lines.append(f"| {name} | n/a | n/a |")
            else:
                lines.append(f"| {name} | {d.delta_ms:+.1f} | {_fmt(d.delta_pct)} |")
        lines.append("")
    return "\n".join(lines)
