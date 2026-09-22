"""The Node module census: one more PTY spawn of a subject's ``perk`` with the perk-dev-owned
``--import`` tracer (``module_tracer.mjs``) and ``--cpu-prof`` in ``NODE_OPTIONS``.

The tracer writes one ``census-<pid>.jsonl`` per Node process (children inherit
``NODE_OPTIONS``); the MAIN process is the file whose header ``argv[1]`` realpath equals the
``pi`` bin realpath. :func:`analyze_census` groups that process's distinct resolved URLs:
``node:`` → builtins; ``file:`` under the Pi host root → host modules; everything else by the
package name after the last ``node_modules/`` segment (``@scope/name`` takes two segments;
no ``node_modules`` → ``"<unpackaged>"``). ``sdk_outside_host_roots`` — the distinct package
roots of the SDK packages that loaded from OUTSIDE the host root, with their versions — is the
authoritative provenance of which duplicate SDK copies a launch actually loaded; the subject
stamp's ``sdk_copies`` only says which copies are installed.

``NODE_OPTIONS`` is composed from an EMPTY base: the harness scrubs the operator's value from
every spawned process (it would change both the timings and the module graph). All three flags
are in Node's ``NODE_OPTIONS`` allowlist; the ``file:`` URI needs no quoting, the profile dir is
double-quoted (the CLI refuses an ``--output`` containing ``"``).
"""

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import unquote, urlparse

from perk.boundary import OutputModel
from perk_dev.profile_startup.pty_session import PtyRun, PtySize, SpawnFn
from perk_dev.profile_startup.timings import TimingsScanner

if (
    TYPE_CHECKING
):  # `subjects` imports SDK_PACKAGE_NAMES from here — a type-only edge breaks the cycle
    from perk_dev.profile_startup.subjects import Subject

# The SDK packages whose duplicate copies outside the Pi host root the census reports on. A
# reporting filter only — the specifier census later work pins is its own, not this constant.
SDK_PACKAGE_NAMES: tuple[str, ...] = (
    "@earendil-works/pi-coding-agent",
    "@earendil-works/pi-tui",
    "@earendil-works/pi-ai",
    "@earendil-works/pi-agent-core",
    "typebox",
)
PI_HOST_PACKAGE_NAME = "@earendil-works/pi-coding-agent"
TRACER_PATH = Path(__file__).with_name("module_tracer.mjs")
CENSUS_DIR_ENV = "PERK_MODULE_CENSUS_DIR"
UNPACKAGED = "<unpackaged>"

type CensusStatus = Literal[
    "ok",
    "host_root_unresolved",
    "timed_out",
    "failed_exit",
    "no_marker",
    "no_census_file",
    "malformed_census",
    "hooks_unsupported",
]


class CensusError(Exception):
    """A census that cannot be analyzed — carries the :data:`CensusStatus` it maps to."""

    def __init__(self, status: CensusStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class SdkRoot:
    """One SDK package root that loaded from outside the host root."""

    name: str
    root: str
    version: str | None
    modules: int


@dataclass(frozen=True)
class CensusSummary:
    """The main Pi process's module census (distinct resolved URLs)."""

    main_pid: int
    distinct_modules: int
    builtin_modules: int
    host_modules: int
    by_package: dict[str, int]
    sdk_outside_host: dict[str, int]
    sdk_outside_host_total: int
    sdk_outside_host_roots: tuple[SdkRoot, ...]


@dataclass(frozen=True)
class CensusRun:
    """The census arm's outcome. ``summary`` is populated ONLY for ``status == "ok"``;
    ``lingered`` is a flag beside an ``ok`` status, never a status of its own."""

    status: CensusStatus
    exit_code: int | None
    timed_out: bool
    lingered: bool
    marker_seen: bool
    hooks_supported: bool | None
    main_pid: int | None
    process_files: int
    cpu_profiles: tuple[str, ...]
    summary: CensusSummary | None
    failure: str | None


@dataclass(frozen=True)
class ProcessCensus:
    """One parsed ``census-<pid>.jsonl``: its header and the resolved URLs in order."""

    path: Path
    header: dict[str, object]
    urls: tuple[str, ...]


def compose_node_options(*, cpu_prof_dir: Path) -> str:
    """The ``NODE_OPTIONS`` value for the census arm, from an empty base (see the module doc).
    The tracer learns its census directory from ``PERK_MODULE_CENSUS_DIR``, not from a flag."""
    return f'--import={TRACER_PATH.resolve().as_uri()} --cpu-prof --cpu-prof-dir="{cpu_prof_dir}"'


def _read_json_object(path: Path) -> dict[str, object] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _package_version(root: Path) -> str | None:
    manifest = _read_json_object(root / "package.json")
    if manifest is None:
        return None
    version = manifest.get("version")
    return version if isinstance(version, str) else None


def pi_package_root(pi_path: str) -> Path | None:
    """The ``@earendil-works/pi-coding-agent`` package root above the ``pi`` bin (realpath
    walk-up to the nearest ``package.json`` with that ``name``); ``None`` when not found."""
    real = Path(os.path.realpath(pi_path))
    for candidate in real.parents:
        manifest = _read_json_object(candidate / "package.json")
        if manifest is not None and manifest.get("name") == PI_HOST_PACKAGE_NAME:
            return candidate
    return None


def _parse_header(path: Path) -> dict[str, object] | None:
    """The first line of a census file as a process header (``None`` when it is not one)."""
    try:
        with path.open(encoding="utf-8") as handle:
            first = handle.readline()
    except (OSError, UnicodeDecodeError):
        return None
    try:
        raw = json.loads(first)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict) or raw.get("kind") != "process":
        return None
    return raw


def _header_main_script(header: Mapping[str, object]) -> str | None:
    argv = header.get("argv")
    if isinstance(argv, list) and len(argv) > 1 and isinstance(argv[1], str):
        return argv[1]
    return None


def load_main_census(census_dir: Path, *, pi_bin_realpath: str) -> ProcessCensus:
    """The main Pi process's census (the file whose header ``argv[1]`` realpath is the ``pi``
    bin). ``no_census_file`` when none matches; ``malformed_census`` when that file holds an
    unparsable line."""
    for path in sorted(census_dir.glob("census-*.jsonl")) if census_dir.is_dir() else []:
        header = _parse_header(path)
        if header is None:
            continue
        script = _header_main_script(header)
        if script is None or os.path.realpath(script) != pi_bin_realpath:
            continue
        urls: list[str] = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines()[1:], 2):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CensusError(
                    "malformed_census", f"{path}:{number}: unparsable census line ({exc})"
                ) from exc
            if not isinstance(row, dict):
                raise CensusError("malformed_census", f"{path}:{number}: not a JSON object")
            if row.get("kind") == "resolve" and isinstance(row.get("url"), str):
                urls.append(row["url"])
        return ProcessCensus(path=path, header=header, urls=tuple(urls))
    raise CensusError(
        "no_census_file",
        f"no census file under {census_dir} names the pi bin {pi_bin_realpath} as its main script",
    )


def _package_of(path: str) -> tuple[str, str] | None:
    """``(name, root)`` for a path under a ``node_modules/`` segment; ``None`` otherwise."""
    marker = "/node_modules/"
    index = path.rfind(marker)
    if index < 0:
        return None
    prefix = path[: index + len(marker)]
    rest = path[index + len(marker) :].split("/")
    take = 2 if rest and rest[0].startswith("@") else 1
    if len(rest) < take or not all(rest[:take]):
        return None
    name = "/".join(rest[:take])
    return name, prefix + name


def analyze_census(census_dir: Path, *, pi_bin_realpath: str, host_root: Path) -> CensusSummary:
    """Group the main process's distinct resolved URLs (see the module doc). Raises
    :class:`CensusError` for ``no_census_file`` / ``malformed_census`` / ``hooks_unsupported``."""
    census = load_main_census(census_dir, pi_bin_realpath=pi_bin_realpath)
    if census.header.get("hooks") is not True:
        raise CensusError(
            "hooks_unsupported",
            f"{census.path}: node:module registerHooks is unavailable in this Node "
            f"({census.header.get('node')}) — the census recorded no resolutions",
        )
    pid = census.header.get("pid")
    host = str(host_root.resolve()).rstrip("/") + "/"
    builtin = 0
    host_modules = 0
    by_package: dict[str, int] = {}
    roots: dict[tuple[str, str], int] = {}
    for url in dict.fromkeys(census.urls):
        if url.startswith("node:"):
            builtin += 1
            continue
        parsed = urlparse(url)
        if parsed.scheme != "file":
            by_package[UNPACKAGED] = by_package.get(UNPACKAGED, 0) + 1
            continue
        path = unquote(parsed.path)
        if path.startswith(host):
            host_modules += 1
            continue
        package = _package_of(path)
        if package is None:
            by_package[UNPACKAGED] = by_package.get(UNPACKAGED, 0) + 1
            continue
        name, root = package
        by_package[name] = by_package.get(name, 0) + 1
        roots[(name, root)] = roots.get((name, root), 0) + 1
    by_package = dict(sorted(by_package.items(), key=lambda item: (-item[1], item[0])))
    sdk_outside_host = {name: by_package[name] for name in SDK_PACKAGE_NAMES if name in by_package}
    sdk_roots = tuple(
        SdkRoot(name=name, root=root, version=_package_version(Path(root)), modules=count)
        for (name, root), count in sorted(roots.items())
        if name in SDK_PACKAGE_NAMES
    )
    return CensusSummary(
        main_pid=pid if isinstance(pid, int) else -1,
        distinct_modules=len(set(census.urls)),
        builtin_modules=builtin,
        host_modules=host_modules,
        by_package=by_package,
        sdk_outside_host=sdk_outside_host,
        sdk_outside_host_total=sum(sdk_outside_host.values()),
        sdk_outside_host_roots=sdk_roots,
    )


def classify_census_run(
    run: PtyRun,
    *,
    marker_seen: bool,
    census_dir: Path,
    cpu_prof_dir: Path,
    pi_bin_realpath: str,
    host_root: Path,
) -> CensusRun:
    """Decide the status ladder for a spawned census arm: ``timed_out`` → ``failed_exit``
    (non-zero exit with no marker) → ``no_marker`` → the census checks → ``ok``."""
    process_files = len(list(census_dir.glob("census-*.jsonl"))) if census_dir.is_dir() else 0
    cpu_profiles = (
        tuple(sorted(p.name for p in cpu_prof_dir.glob("*.cpuprofile")))
        if cpu_prof_dir.is_dir()
        else ()
    )
    common = {
        "exit_code": run.exit_code,
        "timed_out": run.timed_out,
        "lingered": run.lingered,
        "marker_seen": marker_seen,
        "process_files": process_files,
        "cpu_profiles": cpu_profiles,
    }
    if run.timed_out:
        return CensusRun(
            status="timed_out",
            hooks_supported=None,
            main_pid=None,
            summary=None,
            failure="the startup marker never appeared before the timeout",
            **common,
        )
    if run.exit_code != 0 and not marker_seen:
        return CensusRun(
            status="failed_exit",
            hooks_supported=None,
            main_pid=None,
            summary=None,
            failure=f"exited {run.exit_code} without the startup marker",
            **common,
        )
    if not marker_seen:
        return CensusRun(
            status="no_marker",
            hooks_supported=None,
            main_pid=None,
            summary=None,
            failure="exited 0 without the `main` TOTAL line",
            **common,
        )
    try:
        summary = analyze_census(census_dir, pi_bin_realpath=pi_bin_realpath, host_root=host_root)
    except CensusError as exc:
        hooks: bool | None = False if exc.status == "hooks_unsupported" else None
        return CensusRun(
            status=exc.status,
            hooks_supported=hooks,
            main_pid=None,
            summary=None,
            failure=str(exc),
            **common,
        )
    return CensusRun(
        status="ok",
        hooks_supported=True,
        main_pid=summary.main_pid,
        summary=summary,
        failure=None,
        **common,
    )


def run_census_arm(
    subject: "Subject",
    *,
    env: Mapping[str, str],
    profiles_dir: Path,
    pi_path: str,
    spawn: SpawnFn,
    size: PtySize,
    timeout_s: float,
    exit_grace_s: float,
    report: Callable[[str], None],
) -> CensusRun:
    """The census arm for one subject: resolve the host root (not spawned when unresolvable),
    spawn bare ``perk`` with the tracer + ``--cpu-prof`` in ``NODE_OPTIONS``, classify."""
    census_dir = profiles_dir / "node-census"
    cpu_prof_dir = profiles_dir / "cpu-prof"
    host_root = pi_package_root(pi_path)
    if host_root is None:
        return CensusRun(
            status="host_root_unresolved",
            exit_code=None,
            timed_out=False,
            lingered=False,
            marker_seen=False,
            hooks_supported=None,
            main_pid=None,
            process_files=0,
            cpu_profiles=(),
            summary=None,
            failure=(
                f"no {PI_HOST_PACKAGE_NAME} package.json above {os.path.realpath(pi_path)} — "
                "the census arm was not spawned"
            ),
        )
    census_dir.mkdir(parents=True, exist_ok=True)
    cpu_prof_dir.mkdir(parents=True, exist_ok=True)
    arm_env = {
        **env,
        "NODE_OPTIONS": compose_node_options(cpu_prof_dir=cpu_prof_dir),
        CENSUS_DIR_ENV: str(census_dir),
    }
    report(f"  {subject.label}: census arm (module tracer + --cpu-prof)")
    scanner = TimingsScanner()
    run = spawn(
        (str(subject.executable),),
        cwd=subject.checkout,
        env=arm_env,
        size=size,
        timeout_s=timeout_s,
        exit_grace_s=exit_grace_s,
        startup_marker=scanner.feed,
    )
    return classify_census_run(
        run,
        marker_seen=scanner.seen,
        census_dir=census_dir,
        cpu_prof_dir=cpu_prof_dir,
        pi_bin_realpath=os.path.realpath(pi_path),
        host_root=host_root,
    )


# --- the --json snapshot --------------------------------------------------------------------------


class SdkRootOut(OutputModel):
    name: str
    root: str
    version: str | None
    modules: int


class CensusSummaryOut(OutputModel):
    main_pid: int
    distinct_modules: int
    builtin_modules: int
    host_modules: int
    by_package: dict[str, int]
    sdk_outside_host: dict[str, int]
    sdk_outside_host_total: int
    sdk_outside_host_roots: tuple[SdkRootOut, ...]

    @classmethod
    def from_domain(cls, s: CensusSummary) -> "CensusSummaryOut":
        return cls(
            main_pid=s.main_pid,
            distinct_modules=s.distinct_modules,
            builtin_modules=s.builtin_modules,
            host_modules=s.host_modules,
            by_package=dict(s.by_package),
            sdk_outside_host=dict(s.sdk_outside_host),
            sdk_outside_host_total=s.sdk_outside_host_total,
            sdk_outside_host_roots=tuple(
                SdkRootOut(name=r.name, root=r.root, version=r.version, modules=r.modules)
                for r in s.sdk_outside_host_roots
            ),
        )


class CensusRunOut(OutputModel):
    status: str
    exit_code: int | None
    timed_out: bool
    lingered: bool
    marker_seen: bool
    hooks_supported: bool | None
    main_pid: int | None
    process_files: int
    cpu_profiles: tuple[str, ...]
    summary: CensusSummaryOut | None
    failure: str | None

    @classmethod
    def from_domain(cls, r: CensusRun) -> "CensusRunOut":
        return cls(
            status=r.status,
            exit_code=r.exit_code,
            timed_out=r.timed_out,
            lingered=r.lingered,
            marker_seen=r.marker_seen,
            hooks_supported=r.hooks_supported,
            main_pid=r.main_pid,
            process_files=r.process_files,
            cpu_profiles=r.cpu_profiles,
            summary=CensusSummaryOut.from_domain(r.summary) if r.summary is not None else None,
            failure=r.failure,
        )
