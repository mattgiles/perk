"""Stream remote run status back into GitHub from the runner (Node 2.3; contracts.md §8.15).

The **runner-side** consumer of the §8.12 structured run-event stream + the §8.11 ``RunOutcome``.
When ``perk run-worker`` drives a stage remotely it posts a **started** note before the worker
spawns and an **outcome** note after it returns — a single marker-keyed comment on the plan issue
(issue-canonical model), plus a terminal summary appended to the GitHub Actions **job summary**
(``$GITHUB_STEP_SUMMARY`` — the run-page "check" surface).

Deterministic exterior task (no agentic reasoning): pure formatters + thin **fail-soft** wiring. The
worker itself never mutates GitHub (§8.12 is explicit); reporting is best-effort — any exception is
caught, logged to stderr, and swallowed so observability can never change the worker's exit code or
crash the runner. The only free text surfaced is the worker's own already-capped (2 KiB)
``error.summary`` — no GitHub-sourced prose is ever quoted (route-don't-relay preserved end-to-end).
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from perk import issues
from perk.state import cache
from perk.substrate.output import user_output

# One marker-keyed comment per `run_id` (started -> terminal upsert; reruns are distinct run_ids).
RUN_REPORT_MARKER = "<!-- perk:run-report:{run_id} -->"


def run_url_from_env(environ: Mapping[str, str]) -> str | None:
    """Build the GitHub Actions run URL from the standard runner env; ``None`` when incomplete.

    ``{GITHUB_SERVER_URL}/{GITHUB_REPOSITORY}/actions/runs/{GITHUB_RUN_ID}`` when all three are
    present (a real runner); ``None`` for a local/test invocation (notes still post, just without
    the link).
    """
    server = (environ.get("GITHUB_SERVER_URL") or "").strip()
    repo = (environ.get("GITHUB_REPOSITORY") or "").strip()
    run_id = (environ.get("GITHUB_RUN_ID") or "").strip()
    if server and repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return None


def read_outcome(repo_root: Path, run_id: str) -> dict[str, Any] | None:
    """Return the ``outcome`` of the last ``run_finished`` event in the run's ``events.ndjson``.

    Reads the durable §8.12 stream out-of-process (the worker inherits stdio, so its stdout
    ``RunOutcome`` is not captured — the contract-sanctioned path is the events file). Fail-soft:
    ``None`` when the file is missing, empty, or carries no ``run_finished``; a malformed line is
    skipped, never raised.
    """
    text = cache.read_scratch(repo_root, run_id, "events.ndjson")
    if not text:
        return None
    outcome: dict[str, Any] | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("kind") == "run_finished":
            candidate = event.get("outcome")
            if isinstance(candidate, dict):
                outcome = candidate
    return outcome


def _run_line(run_url: str | None) -> str:
    return f"\nRun: {run_url}" if run_url else ""


def _budget_line(outcome: dict[str, Any]) -> str:
    budget = outcome.get("budget")
    if not isinstance(budget, dict):
        return ""
    turns = budget.get("turns")
    tokens = budget.get("tokens")
    elapsed = budget.get("elapsed_ms")
    return f"\nBudget: turns={turns}, tokens={tokens}, elapsed_ms={elapsed}"


def _pr_line(outcome: dict[str, Any]) -> str:
    pr = outcome.get("pr")
    if isinstance(pr, dict) and pr.get("number") is not None:
        return f"\nOpened PR #{pr.get('number')} ({pr.get('url')})"
    return ""


def _failure_section(outcome: dict[str, Any]) -> str:
    """The verbatim worker failure summary (already capped at 2 KiB; never re-expanded)."""
    error = outcome.get("error")
    if not isinstance(error, dict):
        return ""
    summary = error.get("summary")
    if not summary:
        return ""
    return f"\n\n**Failure summary:**\n\n{summary}"


def _outcome_body(*, outcome: dict[str, Any] | None, exit_code: int, run_url: str | None) -> str:
    """The shared post-head fragment (everything from ``Status:`` onward) for
    :func:`format_outcome` and :func:`format_step_summary`.

    Without an ``outcome`` (events file unreadable): a clearly-labelled degraded note derived
    from ``exit_code`` only. With one: status, ``terminal_signal``, the budget line, the PR link
    when present, the run URL, and on any non-``completed`` status the verbatim worker failure
    summary.
    """
    if outcome is None:
        degraded = (
            "completed (no structured outcome on disk)"
            if exit_code == 0
            else "failed (no structured outcome on disk)"
        )
        return f"Status: {degraded}{_run_line(run_url)}"
    status = outcome.get("status")
    body = (
        f"Status: {status}"
        f"\nterminal_signal: {outcome.get('terminal_signal')}"
        f"{_budget_line(outcome)}"
        f"{_pr_line(outcome)}"
        f"{_run_line(run_url)}"
    )
    if status != "completed":
        body += _failure_section(outcome)
    return body


def format_started(*, run_id: str, stage: str, plan: str, run_url: str | None) -> str:
    """The started body (marker first). No GitHub-sourced prose."""
    marker = RUN_REPORT_MARKER.format(run_id=run_id)
    return (
        f"{marker}\n"
        f"🤖 perk remote **{stage}** started\n"
        f"\nplan #{plan}"
        f"\nrun_id: `{run_id}`"
        f"{_run_line(run_url)}"
    )


def format_outcome(
    *,
    run_id: str,
    stage: str,
    plan: str,
    run_url: str | None,
    outcome: dict[str, Any] | None,
    exit_code: int,
) -> str:
    """The terminal body (marker first).

    With an ``outcome``: status, ``terminal_signal``, the budget line, the PR link when present,
    the run URL, and on any non-``completed`` status the verbatim worker failure summary.
    Without one (events file unreadable): a clearly-labelled degraded note derived from
    ``exit_code`` only, guaranteeing a terminal note even when the structured channel is lost.
    """
    marker = RUN_REPORT_MARKER.format(run_id=run_id)
    head = f"{marker}\n🤖 perk remote **{stage}** finished\n\nplan #{plan}\nrun_id: `{run_id}`"
    return f"{head}\n{_outcome_body(outcome=outcome, exit_code=exit_code, run_url=run_url)}"


def format_step_summary(
    *,
    stage: str,
    plan: str,
    run_url: str | None,
    outcome: dict[str, Any] | None,
    exit_code: int,
) -> str:
    """The markdown appended to the GitHub Actions job summary (the run-page "check" surface).

    Self-contained (re-derives from ``outcome``/``exit_code``), not coupled to the comment body.
    """
    head = f"## perk remote {stage}\n\nplan #{plan}"
    return f"{head}\n\n{_outcome_body(outcome=outcome, exit_code=exit_code, run_url=run_url)}\n"


def report_started(
    repo_root: Path, *, run_id: str, stage: str, plan: str, environ: Mapping[str, str]
) -> None:
    """Post the started note as a marker-keyed plan-issue comment. Fully fail-soft."""
    try:
        run_url = run_url_from_env(environ)
        body = format_started(run_id=run_id, stage=stage, plan=plan, run_url=run_url)
        backend = issues.resolve_issue_backend(repo_root)
        backend.upsert_marked_comment(
            issue_id=str(plan),
            marker=RUN_REPORT_MARKER.format(run_id=run_id),
            body=body,
        )
        user_output(f"run-report: posted started note on plan #{plan} (run_id={run_id})")
    except Exception as exc:  # observability is best-effort; never sink the run.
        user_output(f"run-report: started note failed (swallowed): {exc}")


def report_terminal(
    repo_root: Path,
    *,
    run_id: str,
    stage: str,
    plan: str,
    exit_code: int,
    environ: Mapping[str, str],
) -> None:
    """Update the marker comment with the terminal note + append the job summary. Fail-soft."""
    try:
        run_url = run_url_from_env(environ)
        outcome = read_outcome(repo_root, run_id)
        body = format_outcome(
            run_id=run_id,
            stage=stage,
            plan=plan,
            run_url=run_url,
            outcome=outcome,
            exit_code=exit_code,
        )
        backend = issues.resolve_issue_backend(repo_root)
        backend.upsert_marked_comment(
            issue_id=str(plan),
            marker=RUN_REPORT_MARKER.format(run_id=run_id),
            body=body,
        )
        summary_path = (environ.get("GITHUB_STEP_SUMMARY") or "").strip()
        if summary_path:
            summary = format_step_summary(
                stage=stage, plan=plan, run_url=run_url, outcome=outcome, exit_code=exit_code
            )
            with Path(summary_path).open("a", encoding="utf-8") as handle:
                handle.write(summary)
        user_output(f"run-report: posted terminal note on plan #{plan} (run_id={run_id})")
    except Exception as exc:  # observability is best-effort; never sink the run.
        user_output(f"run-report: terminal note failed (swallowed): {exc}")
