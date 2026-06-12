"""Linear agent-session emission for implement runs (Objective #252, Node 5.1 — stretch).

An **opt-in, fail-soft** one-way mirror of a perk implement run into Linear's Agents UI:
create an ``AgentSession`` on the plan issue when an implement run starts, emit
``AgentActivity`` records at the run's stage transitions (PR opened at submit; summary at
land; an ``error`` activity on a failed remote drive), and attach the PR URL to the session.

**The gate** (checked inside every emitter): emission fires only when the worktree's stamped
``cache.plan-ref.provider == "linear"`` (the Node 3.1 rule — branch on the stamped provider,
never config) **and** ``LINEAR_AGENT_TOKEN`` is set. Without the token, behavior is
byte-identical to a non-emitting run ("additive only").

**Auth**: Linear's AgentSession/AgentActivity API requires an OAuth ``actor=app`` token from a
Linear agent application — a personal ``LINEAR_API_KEY`` is rejected. The token is sent in the
OAuth ``Authorization: Bearer <token>`` form (``LinearClient(bearer=True)``).

**Fail-soft posture**: every emitter is fully wrapped (mirrors ``land_cmd``'s
``_reconcile_objective_on_land`` fail-open discipline) — it never raises and never changes the
host command's result/exit code; a failure prints one loud-but-non-fatal stderr note
(``perk linear-agent: <what> skipped (non-fatal): <exc>``).

**Session-id persistence**: ``.pi/workflow/agent-session.json`` (cache tier, §8.1/§8.22).
A hook that needs the session but finds the file absent fail-soft skips with a stderr note.

**Offline-test limitation (flagged)**: the GraphQL operations here (``agentSessionCreateOnIssue``,
``agentActivityCreate``, ``agentSessionUpdate``) are substring-pinned in offline fakes only —
exact field signatures are verified live at the smoke gate (``docs/linear-smoke-gate.md``), the
same known limitation class as the Linear backend's "GraphQL type strings unverified live"
deferral.

**Known caveats + explicit deferrals** (flagged, not silently omitted):

- **Staleness (accepted, not mitigated)**: Linear marks sessions ``stale`` ~30 min after the
  last activity, so long implement runs show stale until the submit/land activity refreshes
  them. Setting ``externalUrls`` at create prevents the "unresponsive" marking.
- **Remote-created session invisible to a local land**: ``agent-session.json`` lives in the
  remote runner's checkout, so a later local land (fresh checkout) skips its emission.
- **``perk address`` emission** — deferred.
- **The agent *plan* checklist** (``agentSessionUpdate.plan``; the Agent Plan API is a
  technology preview) — deferred.
- **Elicitation activities and retry/backoff** — deferred.
- **No webhook receiver**: emission is one-way; perk never *responds* to Linear prompts, so the
  ``prompted`` webhook / 10-second-response expectation does not apply to these proactively
  created sessions.
"""

import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from perk.linear import LinearClient
from perk.state import cache

AGENT_TOKEN_ENV = "LINEAR_AGENT_TOKEN"
"""The env var carrying the OAuth ``actor=app`` agent token (the emission gate's second half)."""

# Mutation documents (substring-pinned offline; field signatures verified live at the smoke gate).
_CREATE_SESSION_MUTATION = """\
mutation AgentSessionCreateOnIssue($input: AgentSessionCreateOnIssue!) {
  agentSessionCreateOnIssue(input: $input) {
    success
    agentSession { id url }
  }
}
"""

_CREATE_ACTIVITY_MUTATION = """\
mutation AgentActivityCreate($input: AgentActivityCreateInput!) {
  agentActivityCreate(input: $input) {
    success
  }
}
"""

_UPDATE_SESSION_MUTATION = """\
mutation AgentSessionUpdate($id: String!, $input: AgentSessionUpdateInput!) {
  agentSessionUpdate(id: $id, input: $input) {
    success
  }
}
"""


def emission_enabled(plan_ref: dict[str, Any] | None, environ: Mapping[str, str]) -> bool:
    """The gate: stamped ``provider == "linear"`` AND a non-empty ``LINEAR_AGENT_TOKEN``."""
    if plan_ref is None:
        return False
    if str(plan_ref.get("provider", "")) != "linear":
        return False
    return bool(environ.get(AGENT_TOKEN_ENV, "").strip())


def agent_client_from_env(environ: Mapping[str, str]) -> LinearClient:
    """A bearer-auth ``LinearClient`` over ``LINEAR_AGENT_TOKEN`` (the OAuth agent token)."""
    token = environ.get(AGENT_TOKEN_ENV, "").strip()
    # Callers check `emission_enabled` first; an empty token here raises (caught fail-soft).
    return LinearClient(api_key=token, bearer=True)


def emit_run_started(
    worktree: Path,
    *,
    plan_ref: dict[str, Any] | None,
    run_id: str,
    environ: Mapping[str, str] | None = None,
    external_urls: Sequence[tuple[str, str]] = (),
) -> None:
    """Create the Linear ``AgentSession`` on the plan issue + one ``thought`` activity.

    Persists the session pointer to ``agent-session.json`` in ``worktree``. Fully fail-soft.
    """
    env = os.environ if environ is None else environ
    if plan_ref is None or not emission_enabled(plan_ref, env):
        return
    try:
        client = agent_client_from_env(env)
        issue = str(plan_ref.get("pr_id", ""))
        create_input: dict[str, object] = {"issueId": issue}
        if external_urls:
            create_input["externalUrls"] = [
                {"label": label, "url": url} for label, url in external_urls
            ]
        data = client.request(_CREATE_SESSION_MUTATION, {"input": create_input})
        session_id, session_url = _parse_created_session(data)
        cache.write_agent_session(
            worktree, {"session_id": session_id, "issue": issue, "url": session_url}
        )
        _create_activity(
            client,
            session_id,
            {
                "type": "thought",
                "body": f"Starting implement run for plan `{issue}` (run `{run_id}`)",
            },
        )
    except Exception as exc:  # fail-soft: emission never changes the host command's outcome
        _note(f"run-started emission skipped (non-fatal): {exc}")


def emit_pr_opened(
    worktree: Path,
    *,
    pr_number: int,
    pr_url: str,
    branch: str,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Emit an ``action`` activity for the opened PR + attach its URL to the session."""
    env = os.environ if environ is None else environ
    session = _enabled_session(worktree, env, what="pr-opened emission")
    if session is None:
        return
    try:
        client = agent_client_from_env(env)
        _create_activity(
            client,
            session,
            {
                "type": "action",
                "action": "Opened pull request",
                "parameter": branch,
                "result": pr_url,
            },
        )
        client.request(
            _UPDATE_SESSION_MUTATION,
            {
                "id": session,
                "input": {"addedExternalUrls": [{"label": f"PR #{pr_number}", "url": pr_url}]},
            },
        )
    except Exception as exc:  # fail-soft
        _note(f"pr-opened emission skipped (non-fatal): {exc}")


def emit_landed(
    worktree: Path,
    *,
    pr_number: int,
    summary: str,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Emit the terminal ``response`` activity after the PR is squash-merged."""
    env = os.environ if environ is None else environ
    session = _enabled_session(worktree, env, what="landed emission")
    if session is None:
        return
    try:
        client = agent_client_from_env(env)
        body = f"PR #{pr_number} squash-merged."
        if summary.strip():
            body += f" {summary.strip()}"
        _create_activity(client, session, {"type": "response", "body": body})
    except Exception as exc:  # fail-soft
        _note(f"landed emission skipped (non-fatal): {exc}")


def emit_run_failed(
    worktree: Path,
    *,
    exit_code: int,
    run_url: str | None,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Emit an ``error`` activity for a failed remote drive (the dangling-active guard)."""
    env = os.environ if environ is None else environ
    session = _enabled_session(worktree, env, what="run-failed emission")
    if session is None:
        return
    try:
        client = agent_client_from_env(env)
        body = f"Implement run failed (exit code {exit_code})."
        if run_url:
            body += f" Run: {run_url}"
        _create_activity(client, session, {"type": "error", "body": body})
    except Exception as exc:  # fail-soft
        _note(f"run-failed emission skipped (non-fatal): {exc}")


def _enabled_session(worktree: Path, env: Mapping[str, str], *, what: str) -> str | None:
    """The session id for a follow-up emitter, or ``None`` (gate closed / no session file).

    An absent ``agent-session.json`` at a hook is a fail-soft skip with a stderr note (e.g. a
    remote-run-created session invisible to a later local land — a known, accepted consequence).
    """
    if not emission_enabled(cache.read_plan_ref(worktree), env):
        return None
    session = cache.read_agent_session(worktree)
    session_id = str(session.get("session_id", "")) if isinstance(session, dict) else ""
    if not session_id:
        _note(f"{what} skipped (non-fatal): no agent-session.json in this worktree")
        return None
    return session_id


def _create_activity(client: LinearClient, session_id: str, content: dict[str, object]) -> None:
    """POST one ``agentActivityCreate`` (session status is derived automatically by Linear)."""
    client.request(
        _CREATE_ACTIVITY_MUTATION,
        {"input": {"agentSessionId": session_id, "content": content}},
    )


def _parse_created_session(data: dict[str, object]) -> tuple[str, str | None]:
    """Pull ``agentSession { id url }`` out of the create payload (tiny, local narrowing)."""
    payload = data.get("agentSessionCreateOnIssue")
    if not isinstance(payload, dict):
        raise ValueError(f"unexpected agentSessionCreateOnIssue payload: {json.dumps(data)[:200]}")
    session = cast("dict[str, object]", payload).get("agentSession")
    if not isinstance(session, dict):
        raise ValueError(f"agentSessionCreateOnIssue returned no agentSession: {payload!r}")
    session_dict = cast("dict[str, object]", session)
    session_id = session_dict.get("id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError(f"agentSession missing id: {session!r}")
    url = session_dict.get("url")
    return session_id, url if isinstance(url, str) else None


def _note(message: str) -> None:
    """One loud-but-non-fatal stderr note (the fail-soft reporting boundary)."""
    print(f"perk linear-agent: {message}", file=sys.stderr)
