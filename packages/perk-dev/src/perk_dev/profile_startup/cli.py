"""The ``perk-dev profile-startup`` verb: option domains, the refusal ladder, and the
supervisor contract (``--json`` payload → stdout, byte-identical to ``summary.json``; human text →
stderr; refusals through ``perk.cli.emit.fail``).

Refusals, in order and all BEFORE any sample is spawned: option-domain violations
(``bad_arguments``, naming the option) → subject specs (``bad_arguments`` / ``subject_missing`` /
``subject_not_converged``) → the output directory (``bad_arguments`` / ``output_not_empty``) →
``pi`` / ``node`` on PATH (``tool_missing``, once) → inside the run, per subject,
``subject_probe_failed`` / ``subject_untrusted`` (the stamps). Any ``OSError`` writing under
``--output`` is ``io_error`` (exit 1; the partial run directory is left in place and named). A
COMPLETED run exits 0 even when samples failed — the summary reports them (the detect-worker
posture) and a ``warning:`` line names every subject with zero successful samples.
"""

import math
import re
from pathlib import Path

import click

from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.substrate.output import machine_output, user_output
from perk.substrate.proc import which_absolute
from perk_dev.profile_startup.harness import ProfileOptions, run_profile
from perk_dev.profile_startup.pty_session import PtySize
from perk_dev.profile_startup.subjects import parse_subject_specs
from perk_dev.profile_startup.summary import (
    Summary,
    render_summary_md,
    successful,
    summary_json_text,
)

DEFAULT_RUNS = 5
DEFAULT_TIMEOUT_S = 180.0
DEFAULT_EXIT_GRACE_S = 10.0
DEFAULT_PTY_SIZE = "120x40"
PTY_COLS_RANGE = (40, 400)
PTY_ROWS_RANGE = (10, 200)
_PTY_SIZE_RE = re.compile(r"^(?P<cols>\d+)x(?P<rows>\d+)$")


def _bad(message: str) -> UserFacingCliError:
    return UserFacingCliError(message, error_type="bad_arguments")


def parse_pty_size(value: str) -> PtySize:
    """``COLSxROWS`` within the accepted domain, else ``bad_arguments``."""
    match = _PTY_SIZE_RE.match(value.strip())
    if match is None:
        raise _bad(f"--pty-size expects COLSxROWS (e.g. {DEFAULT_PTY_SIZE}), got {value!r}")
    cols, rows = int(match["cols"]), int(match["rows"])
    if not PTY_COLS_RANGE[0] <= cols <= PTY_COLS_RANGE[1]:
        raise _bad(
            f"--pty-size columns must be within {PTY_COLS_RANGE[0]}..{PTY_COLS_RANGE[1]}, "
            f"got {cols}"
        )
    if not PTY_ROWS_RANGE[0] <= rows <= PTY_ROWS_RANGE[1]:
        raise _bad(
            f"--pty-size rows must be within {PTY_ROWS_RANGE[0]}..{PTY_ROWS_RANGE[1]}, got {rows}"
        )
    return PtySize(cols=cols, rows=rows)


def _validate_scalars(*, runs: int, timeout_s: float, exit_grace_s: float) -> None:
    if runs < 1:
        raise _bad(f"--runs must be >= 1, got {runs}")
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise _bad(f"--timeout must be a finite number of seconds > 0, got {timeout_s}")
    if not math.isfinite(exit_grace_s) or exit_grace_s < 0:
        raise _bad(f"--exit-grace must be a finite number of seconds >= 0, got {exit_grace_s}")


def prepare_output_dir(raw: str) -> Path:
    """Resolve ``--output`` absolute and make it an empty directory (created, parents included).

    A ``"`` in the path is ``bad_arguments`` (the path is embedded in ``NODE_OPTIONS``); an
    existing non-directory is ``bad_arguments``; an existing non-empty directory is
    ``output_not_empty``.
    """
    output = Path(raw).expanduser().resolve()
    if '"' in str(output):
        raise _bad(
            f'--output must not contain a `"` character (it is embedded in NODE_OPTIONS): {output}'
        )
    if output.exists() and not output.is_dir():
        raise _bad(f"--output {output} exists and is not a directory")
    if output.is_dir() and any(output.iterdir()):
        raise UserFacingCliError(
            f"--output {output} is not empty — point it at a new or empty directory",
            error_type="output_not_empty",
        )
    output.mkdir(parents=True, exist_ok=True)
    return output


def resolve_tools() -> tuple[str, str]:
    """Absolute ``pi`` and ``node`` paths, else ``tool_missing`` (decided once, before subjects
    are probed)."""
    resolved: list[str] = []
    for name in ("pi", "node"):
        path = which_absolute(name)
        if path is None:
            raise UserFacingCliError(
                f"`{name}` is not on PATH — the profiler drives the real `pi` under `node`",
                error_type="tool_missing",
            )
        resolved.append(path)
    return resolved[0], resolved[1]


def _warn_empty_subjects(summary: Summary) -> None:
    for subject in summary.subjects:
        if not successful(subject.samples):
            user_output(
                click.style("warning: ", fg="yellow")
                + f"subject {subject.label} produced no successful sample "
                f"({len(subject.samples)} failed) — see samples/{subject.label}/*.stderr.txt"
            )


@click.command("profile-startup")
@click.option(
    "--runs",
    type=int,
    default=DEFAULT_RUNS,
    show_default=True,
    metavar="<n>",
    help="Timing samples per subject (>= 1), after one discarded warm-up each.",
)
@click.option(
    "--output",
    "output_opt",
    default=None,
    metavar="<dir>",
    help="Run directory (required; created, must be empty).",
)
@click.option(
    "--subject",
    "subject_specs",
    multiple=True,
    metavar="LABEL=CHECKOUT",
    help="A prepared perk checkout to measure through its own .venv/bin/perk (repeatable).",
)
@click.option(
    "--timeout",
    "timeout_s",
    type=float,
    default=DEFAULT_TIMEOUT_S,
    show_default=True,
    metavar="<seconds>",
    help="Spawn → startup-marker budget per sample (> 0).",
)
@click.option(
    "--exit-grace",
    "exit_grace_s",
    type=float,
    default=DEFAULT_EXIT_GRACE_S,
    show_default=True,
    metavar="<seconds>",
    help="How long a process may outlive its startup marker before it is terminated (>= 0).",
)
@click.option(
    "--pty-size",
    "pty_size_opt",
    default=DEFAULT_PTY_SIZE,
    show_default=True,
    metavar="COLSxROWS",
    help=f"Terminal geometry ({PTY_COLS_RANGE[0]}-{PTY_COLS_RANGE[1]} cols, "
    f"{PTY_ROWS_RANGE[0]}-{PTY_ROWS_RANGE[1]} rows).",
)
@click.option(
    "--no-profiles",
    "no_profiles",
    is_flag=True,
    help="Skip the profiled arms (Python handoff + cProfile + importtime, Node module census).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit summary.json's bytes to stdout.")
@click.pass_context
def profile_startup(
    ctx: click.Context,
    *,
    runs: int,
    output_opt: str | None,
    subject_specs: tuple[str, ...],
    timeout_s: float,
    exit_grace_s: float,
    pty_size_opt: str,
    no_profiles: bool,
    as_json: bool,
) -> None:
    """Measure perk's cold startup repeatably across one or more checkouts.

    Each subject's real `perk` runs on a pseudo-terminal under Pi's offline startup-benchmark
    mode; subjects alternate sample by sample after one discarded warm-up each; the run
    directory holds raw samples, per-subject provenance, the profiled arms, and a JSON +
    Markdown summary (medians, ranges, failed samples, a two-subject delta block — reported,
    never judged). See docs/developers/profiling-startup.md.

    \b
    Examples:
      perk-dev profile-startup --runs 5 --output /tmp/startup --subject main=.
      perk-dev profile-startup --output /tmp/ab --subject base=../perk-base --subject cand=. --json
    """
    try:
        _validate_scalars(runs=runs, timeout_s=timeout_s, exit_grace_s=exit_grace_s)
        pty_size = parse_pty_size(pty_size_opt)
        if output_opt is None or not output_opt.strip():
            raise _bad("--output is required (the run directory)")
        if not subject_specs:
            raise _bad("at least one --subject LABEL=CHECKOUT is required")
        subjects = parse_subject_specs(subject_specs)
        output = prepare_output_dir(output_opt)
        pi_path, node_path = resolve_tools()
    except UserFacingCliError as exc:
        fail(ctx, as_json=as_json, error_type=exc.error_type or "bad_arguments", message=str(exc))
        return
    options = ProfileOptions(
        subjects=subjects,
        runs=runs,
        output=output,
        timeout_s=timeout_s,
        exit_grace_s=exit_grace_s,
        pty_size=pty_size,
        profiles=not no_profiles,
        pi_path=pi_path,
        node_path=node_path,
    )
    try:
        summary = run_profile(options, report=user_output)
    except UserFacingCliError as exc:
        fail(ctx, as_json=as_json, error_type=exc.error_type or "bad_arguments", message=str(exc))
        return
    except OSError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type="io_error",
            message=f"could not write under {output}: {exc} — a partial run directory is left "
            f"in place at {output}",
        )
        return
    if as_json:
        machine_output(summary_json_text(summary), nl=False)
    else:
        for line in render_summary_md(summary).splitlines():
            user_output(line)
    _warn_empty_subjects(summary)
