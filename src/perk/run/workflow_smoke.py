"""The `perk doctor workflow smoke-test` core logic (contracts.md §8.19).

A Click-free, testable module that dispatches a throwaway CI run to prove the genuinely CI-only
prerequisites a static check cannot: that the managed workflow is dispatchable, the runner actually
starts a job, and the secrets are readable **in the Actions context**. It triggers the managed
``perk-run.yml`` **directly** with a ``smoke=true`` short-circuit (the workflow validates secrets,
echoes a smoke-ok line, then exits success — no plan checkout, no composite setup, no worker drive,
no model spend), persisting **no** dispatch record and creating **no** GitHub artifacts (no
branch/PR/issue). So `perk workflow run list` is unaffected (no record is written, and run
discovery filters ``stage == runner.SMOKE_STAGE`` out of the canonical GHA enumeration), and
there is no ``cleanup``
command to write (perk's smoke leaves nothing durable) — the only real leftover is an in-flight run
on a poll timeout, which ``smoke-test --wait`` self-cancels.
"""

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from perk import github
from perk.github import GitHubError
from perk.run import runner
from perk.state import run_id
from perk.substrate.output import user_output

# The sentinel `plan` input — the smoke short-circuit never checks out a plan branch. The stage
# sentinel is `runner.SMOKE_STAGE` (its canonical home: discovery filters on it too).
SMOKE_PLAN = "smoke"

# Poll cadence: give the throwaway run up to 10 minutes, polling every 15s.
POLL_TIMEOUT_S = 600
POLL_INTERVAL_S = 15


@dataclass(frozen=True)
class SmokeDispatch:
    """A successful dispatch — the verified run handle (no dispatch record is written)."""

    run_id: str
    run_ref: str
    url: str


@dataclass(frozen=True)
class SmokePollResult:
    """The terminal (or timed-out) state of a polled smoke run."""

    status: str
    conclusion: str | None
    url: str
    timed_out: bool


@dataclass(frozen=True)
class SmokeError:
    """A dispatch failure (the gh/gateway error surfaced verbatim)."""

    step: str
    message: str


def dispatch_smoke(
    repo_root: Path, *, sleep: Callable[[float], None] = time.sleep
) -> SmokeDispatch | SmokeError:
    """Trigger the managed workflow with ``smoke=true`` and return the verified run handle.

    Mints a fresh ``run_id``, resolves the default branch (fallback ``"main"`` on a ``GitHubError``,
    with a stderr note — mirrors ``launch._drive_remote_target``), then dispatches + verifies by
    discovery. Writes **no** dispatch record. A ``GitHubError`` (including the
    ``PERK_ENABLED=false`` job-skipped case, which ``smoke-test`` pre-checks before reaching here)
    is returned as a ``SmokeError``.
    """
    rid = run_id.mint()
    try:
        base = github.default_branch(repo_root)
    except GitHubError as exc:
        base = "main"
        user_output(
            f"⚠ could not resolve the default branch ({exc}); basing the smoke dispatch on "
            f"{base!r}."
        )
    inputs = {
        "run_id": rid,
        "stage": runner.SMOKE_STAGE,
        "plan": SMOKE_PLAN,
        "base": base,
        "smoke": "true",
    }
    try:
        wr = github.trigger_workflow(
            repo_root=repo_root,
            workflow=runner.GITHUB_ACTIONS_WORKFLOW,
            inputs=inputs,
            ref=base,
            match_token=rid,
            sleep=sleep,
        )
    except GitHubError as exc:
        return SmokeError("dispatch", str(exc))
    return SmokeDispatch(run_id=rid, run_ref=wr.id, url=wr.url)


def poll_smoke(
    repo_root: Path,
    run_ref: str,
    url: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> SmokePollResult:
    """Poll the run until it completes or ``POLL_TIMEOUT_S`` elapses.

    Returns the conclusion on completion; on timeout returns ``timed_out=True`` with the last
    observed status. ``sleep``/``now`` are injectable so the poll loop is unit-testable with no
    real delay.
    """
    start = now()
    last_status = ""
    while True:
        wr = github.get_workflow_run(run_id=run_ref, repo_root=repo_root)
        if wr is not None:
            last_status = wr.status
            if wr.status == "completed":
                return SmokePollResult(
                    status=wr.status, conclusion=wr.conclusion, url=wr.url or url, timed_out=False
                )
        if now() - start >= POLL_TIMEOUT_S:
            return SmokePollResult(status=last_status, conclusion=None, url=url, timed_out=True)
        sleep(POLL_INTERVAL_S)


def cancel_smoke(repo_root: Path, run_ref: str) -> None:
    """Best-effort cancel of a timed-out smoke run; swallows ``GitHubError`` (never raises)."""
    with contextlib.suppress(GitHubError):
        github.cancel_workflow_run(run_id=run_ref, repo_root=repo_root)
