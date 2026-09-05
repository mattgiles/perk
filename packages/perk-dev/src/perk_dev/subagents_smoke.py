"""The opt-in dev-only pi-subagents live smoke (`perk-dev subagents-smoke`).

Drives the existing non-streaming report-wave lifecycle live on the installed engine: a
headless `pi --mode json -p` session in the repo root makes exactly ONE
`explore_objective_node` call (a registered, parameter-only, read-only single-lane report
wave — tool gating never engages in a bare session), and the captured JSON event stream is
the evidence. The spawn rides `proc.run_captured` with the documented env-leak guard
(`env_remove=("PERK_RUN_ID", "PI_SESSION_FILE")` — a probe launched from inside a perk
session must not adopt the parent's run).

Everything except the one live spawn is pure and offline-testable: the event-stream
evaluator, the version gathering, and the report envelope. The smoke requires live model
credentials (the parent session's default model and the `[models.subagents]
objective-explorer` child model) — an accepted property of the opt-in smoke; it never runs
in CI or tests.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from perk import __version__ as _perk_version
from perk.boundary import OutputModel
from perk.cli.ensure import UserFacingCliError
from perk.substrate import git, proc

# The env-leak guard for probes launched from inside a perk session (see
# docs/learned/pi/headless-session-drive.md): an inherited PERK_RUN_ID/PI_SESSION_FILE makes
# the probe's bound perk extension claim the parent's run. Removal, not an overlay — an
# empty-string value is still a set variable.
SMOKE_ENV_REMOVE = ("PERK_RUN_ID", "PI_SESSION_FILE")

# Generous headroom above the wave module's 15-minute default timeout — the smoke spawns a
# live parent session that itself waits on a live child lane.
SMOKE_TIMEOUT_SECONDS = 1200

# The one tool execution the smoke expects to observe.
SMOKE_TOOL = "explore_objective_node"

# The fixed headless prompt: exactly one explore_objective_node call with fixed args, no
# other tool calls, then a fixed completion reply. The node id/description are inert probe
# inputs (the explorer maps real code either way); SMOKE-OK is a human tail marker only —
# the evaluator trusts the tool event stream, never the prose.
SMOKE_PROMPT = (
    "You are a smoke probe. Call the explore_objective_node tool EXACTLY ONCE with "
    'arguments {"node": "1.1", "description": "Map the report-wave flow entrypoints under '
    "extension/waves/: name each per-flow wave module and the tool that drives it, with one "
    'anchor file per flow."}. Make no other tool calls. After the tool returns, reply with '
    "exactly SMOKE-OK and stop."
)


@dataclass(frozen=True)
class SmokeEvaluation:
    """The pure verdict over one captured JSON event stream."""

    passed: bool
    # None on pass; on failure, names what was missing (the failure arm).
    reason: str | None
    # How many SMOKE_TOOL executions ended (whatever the verdict).
    tool_executions: int


def _is_successful_result(result: Any) -> bool:  # a raw json.loads value
    """True when a tool_execution_end `result` carries perk's ok details + a report.

    The explore tool never throws — a failure is a soft result with `details.ok: false` —
    so `isError` alone is not evidence; the details discriminant is.
    """
    if not isinstance(result, dict):
        return False
    details = result.get("details")
    return isinstance(details, dict) and details.get("ok") is True and "report" in details


def evaluate_event_stream(stdout: str) -> SmokeEvaluation:
    """Evaluate the captured `pi --mode json` event lines (pure; offline-testable).

    Pass ⟺ exactly one SMOKE_TOOL `tool_execution_end` event whose result is a successful
    perk tool result (non-error `details.ok` with a `report`). Non-JSON lines are tolerated
    (pi may interleave non-event output); an entirely unparseable stream is its own named
    failure arm.
    """
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    if not events:
        return SmokeEvaluation(
            passed=False, reason="stream unparseable (no JSON event lines)", tool_executions=0
        )
    ends = [
        e
        for e in events
        if e.get("type") == "tool_execution_end" and e.get("toolName") == SMOKE_TOOL
    ]
    if not ends:
        return SmokeEvaluation(
            passed=False,
            reason=f"no {SMOKE_TOOL} tool call observed in the event stream",
            tool_executions=0,
        )
    if len(ends) != 1:
        return SmokeEvaluation(
            passed=False,
            reason=f"expected exactly one {SMOKE_TOOL} execution, observed {len(ends)}",
            tool_executions=len(ends),
        )
    end = ends[0]
    if end.get("isError") is True or not _is_successful_result(end.get("result")):
        return SmokeEvaluation(
            passed=False,
            reason=f"the {SMOKE_TOOL} execution did not return a successful report "
            "(tool error or non-ok details)",
            tool_executions=1,
        )
    return SmokeEvaluation(passed=True, reason=None, tool_executions=1)


# ------------------------------------------------------------------------ version gathering


@dataclass(frozen=True)
class SmokeBaseline:
    """The supported-baseline identity the smoke report records."""

    perk_version: str
    repo_commit: str | None
    dirty: bool
    pi_version: str | None
    subagents_version: str | None


def _package_version(package_json: Path) -> str | None:
    """Best-effort `version` read of a package.json; None when absent/unreadable."""
    try:
        version = json.loads(package_json.read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return version if isinstance(version, str) else None


def gather_baseline(root: Path) -> SmokeBaseline:
    """Gather the baseline identity from the repo (pure reads; every field best-effort)."""
    return SmokeBaseline(
        perk_version=_perk_version,
        repo_commit=git.head_commit(root),
        dirty=git.is_dirty(root),
        pi_version=_package_version(
            root / "node_modules" / "@earendil-works" / "pi-coding-agent" / "package.json"
        ),
        subagents_version=_package_version(
            root / ".pi" / "npm" / "node_modules" / "pi-subagents" / "package.json"
        ),
    )


# ----------------------------------------------------------------------------- the live run


@dataclass(frozen=True)
class SmokeResult:
    """One live smoke run: the baseline, the verdict, and the spawn's exit code."""

    baseline: SmokeBaseline
    evaluation: SmokeEvaluation
    exit_code: int


def preflight(root: Path) -> Path:
    """LBYL preflight: the pinned pi binary + the installed engine. Returns the pi path."""
    pi_binary = root / "node_modules" / ".bin" / "pi"
    if not pi_binary.exists():
        raise UserFacingCliError(
            f"{pi_binary} not found — run `just install` to install the pinned dev Pi",
            error_type="pi_missing",
        )
    subagents = root / ".pi" / "npm" / "node_modules" / "pi-subagents" / "package.json"
    if not subagents.exists():
        raise UserFacingCliError(
            "pi-subagents is not installed (.pi/npm/node_modules/pi-subagents) — launch `pi` "
            "once in this repo so it lazy-installs the borrowed package",
            error_type="subagents_missing",
        )
    return pi_binary


def run_smoke(root: Path) -> SmokeResult:
    """Preflight, spawn the headless probe session, evaluate the captured stream."""
    pi_binary = preflight(root)
    try:
        completed = proc.run_captured(
            [str(pi_binary), "--mode", "json", "-p", SMOKE_PROMPT],
            cwd=root,
            timeout=SMOKE_TIMEOUT_SECONDS,
            env_remove=SMOKE_ENV_REMOVE,
        )
    except proc.ProcFailure as exc:
        raise UserFacingCliError(
            f"the smoke session could not run: {exc}", error_type="spawn_failed"
        ) from exc
    evaluation = evaluate_event_stream(completed.stdout)
    if completed.returncode != 0 and evaluation.passed:
        # A nonzero pi exit contradicts a passing stream — surface it as the verdict.
        evaluation = SmokeEvaluation(
            passed=False,
            reason=f"pi exited {completed.returncode} despite a passing event stream",
            tool_executions=evaluation.tool_executions,
        )
    return SmokeResult(
        baseline=gather_baseline(root), evaluation=evaluation, exit_code=completed.returncode
    )


# --------------------------------------------------------------------------- the --json envelope


class SubagentsSmokeOut(OutputModel):
    """The `--json` envelope for a completed smoke run (PASS or FAIL — both ran)."""

    success: bool
    error_type: str | None
    passed: bool
    reason: str | None
    tool_executions: int
    exit_code: int
    perk_version: str
    repo_commit: str | None
    dirty: bool
    pi_version: str | None
    subagents_version: str | None

    @classmethod
    def from_domain(cls, result: SmokeResult) -> "SubagentsSmokeOut":
        return cls(
            success=True,
            error_type=None,
            passed=result.evaluation.passed,
            reason=result.evaluation.reason,
            tool_executions=result.evaluation.tool_executions,
            exit_code=result.exit_code,
            perk_version=result.baseline.perk_version,
            repo_commit=result.baseline.repo_commit,
            dirty=result.baseline.dirty,
            pi_version=result.baseline.pi_version,
            subagents_version=result.baseline.subagents_version,
        )


def summary_lines(result: SmokeResult) -> list[str]:
    """The pinned human summary (tests assert substrings; wording tweaks stay cheap)."""
    verdict = "PASS" if result.evaluation.passed else "FAIL"
    commit = result.baseline.repo_commit or "unknown"
    dirty = " (dirty tree)" if result.baseline.dirty else ""
    lines = [
        f"subagents-smoke: {verdict}",
        f"perk {result.baseline.perk_version} @ {commit}{dirty}",
        f"pi {result.baseline.pi_version or 'unknown'} (pinned dev toolchain) · "
        f"pi-subagents {result.baseline.subagents_version or 'unknown'} (installed, unpinned)",
        f"observed {result.evaluation.tool_executions} {SMOKE_TOOL} execution(s) · "
        f"pi exit {result.exit_code}",
    ]
    if result.evaluation.reason is not None:
        lines.append(f"failure: {result.evaluation.reason}")
    return lines
