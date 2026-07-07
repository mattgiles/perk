"""Offline tests for the Linear agent-session emission layer (``perk/backends/linear/agent.py``).

Request *composition* only (Bearer header, mutation substrings, variables) over a recording
``httpx.MockTransport`` — exact GraphQL field signatures are verified live at the smoke gate.
Plus: gating (no token / wrong provider → zero requests),
fail-softness (a raising transport propagates nothing, one stderr note), the
``agent-session.json`` round-trip, and the missing-session-file skip.
"""

import dataclasses
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from perk import plan
from perk.backends.linear import agent as linear_agent
from perk.state import cache

_TOKEN_ENV = {"LINEAR_AGENT_TOKEN": "lin_oauth_agent"}

_LINEAR_PLAN_REF = plan.PlanRef(
    provider="linear",
    pr_id="ENG-123",
    url="https://linear.app/acme/issue/ENG-123",
    labels=("perk:plan",),
)
_GITHUB_PLAN_REF = dataclasses.replace(_LINEAR_PLAN_REF, provider="github")

_CREATE_RESPONSE = {
    "data": {
        "agentSessionCreateOnIssue": {
            "success": True,
            "agentSession": {"id": "sess-1", "url": "https://linear.app/acme/agents/sess-1"},
        }
    }
}

_OK_RESPONSE = {"data": {"agentActivityCreate": {"success": True}}}


def _recording_environ(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Patch ``LinearClient`` construction so every emitter call records its requests."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        if "agentSessionCreateOnIssue" in body["query"]:
            return httpx.Response(200, json=_CREATE_RESPONSE)
        return httpx.Response(200, json=_OK_RESPONSE)

    transport = httpx.MockTransport(handler)
    original = linear_agent.LinearClient

    def factory(*, api_key: str, bearer: bool = False) -> Any:
        return original(api_key=api_key, bearer=bearer, transport=transport)

    monkeypatch.setattr(linear_agent, "LinearClient", factory)
    return seen


def _raising_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    transport = httpx.MockTransport(handler)
    original = linear_agent.LinearClient

    def factory(*, api_key: str, bearer: bool = False) -> Any:
        return original(api_key=api_key, bearer=bearer, transport=transport)

    monkeypatch.setattr(linear_agent, "LinearClient", factory)


def _seed_session(root: Path) -> None:
    cache.write_plan_ref(root, _LINEAR_PLAN_REF)
    cache.write_agent_session(
        root,
        cache.AgentSession(session_id="sess-1", issue="ENG-123", url="https://linear.app/s/1"),
    )


class TestGating:
    def test_no_token_means_zero_requests(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = _recording_environ(monkeypatch)
        linear_agent.emit_run_started(tmp_path, plan_ref=_LINEAR_PLAN_REF, run_id="r1", environ={})
        assert seen == []
        assert cache.read_agent_session(tmp_path) is None

    def test_github_provider_means_zero_requests(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = _recording_environ(monkeypatch)
        github_ref = _GITHUB_PLAN_REF
        linear_agent.emit_run_started(
            tmp_path, plan_ref=github_ref, run_id="r1", environ=_TOKEN_ENV
        )
        assert seen == []

    def test_none_plan_ref_means_zero_requests(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = _recording_environ(monkeypatch)
        linear_agent.emit_run_started(tmp_path, plan_ref=None, run_id="r1", environ=_TOKEN_ENV)
        assert seen == []

    def test_follow_up_emitters_gate_on_the_stamped_plan_ref(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = _recording_environ(monkeypatch)
        cache.write_plan_ref(tmp_path, _GITHUB_PLAN_REF)
        cache.write_agent_session(
            tmp_path, cache.AgentSession(session_id="sess-1", issue="X", url=None)
        )
        linear_agent.emit_pr_opened(
            tmp_path, pr_number=7, pr_url="u", branch="b", environ=_TOKEN_ENV
        )
        linear_agent.emit_landed(tmp_path, pr_number=7, summary="", environ=_TOKEN_ENV)
        linear_agent.emit_run_failed(tmp_path, exit_code=1, run_url=None, environ=_TOKEN_ENV)
        assert seen == []

    def test_emission_enabled_truth_table(self) -> None:
        assert linear_agent.emission_enabled(_LINEAR_PLAN_REF, _TOKEN_ENV)
        assert not linear_agent.emission_enabled(_LINEAR_PLAN_REF, {})
        assert not linear_agent.emission_enabled(_LINEAR_PLAN_REF, {"LINEAR_AGENT_TOKEN": "   "})
        assert not linear_agent.emission_enabled(_GITHUB_PLAN_REF, _TOKEN_ENV)
        assert not linear_agent.emission_enabled(None, _TOKEN_ENV)


class TestRunStarted:
    def test_creates_session_persists_pointer_and_emits_thought(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = _recording_environ(monkeypatch)
        linear_agent.emit_run_started(
            tmp_path,
            plan_ref=_LINEAR_PLAN_REF,
            run_id="run-9",
            environ=_TOKEN_ENV,
            external_urls=[("GitHub Actions run", "https://gh/run/1")],
        )
        assert len(seen) == 2
        create = json.loads(seen[0].content)
        assert "agentSessionCreateOnIssue" in create["query"]
        assert create["variables"]["input"]["issueId"] == "ENG-123"
        assert create["variables"]["input"]["externalUrls"] == [
            {"label": "GitHub Actions run", "url": "https://gh/run/1"}
        ]
        # OAuth Bearer form on every request.
        assert seen[0].headers["Authorization"] == "Bearer lin_oauth_agent"
        # The session pointer round-trips through agent-session.json.
        session = cache.read_agent_session(tmp_path)
        assert session == cache.AgentSession(
            session_id="sess-1",
            issue="ENG-123",
            url="https://linear.app/acme/agents/sess-1",
        )
        thought = json.loads(seen[1].content)
        assert "agentActivityCreate" in thought["query"]
        content = thought["variables"]["input"]["content"]
        assert content["type"] == "thought"
        assert "ENG-123" in content["body"]
        assert "run-9" in content["body"]
        assert thought["variables"]["input"]["agentSessionId"] == "sess-1"

    def test_no_external_urls_omits_the_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = _recording_environ(monkeypatch)
        linear_agent.emit_run_started(
            tmp_path, plan_ref=_LINEAR_PLAN_REF, run_id="r", environ=_TOKEN_ENV
        )
        create = json.loads(seen[0].content)
        assert "externalUrls" not in create["variables"]["input"]

    def test_fail_soft_emits_one_stderr_note(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _raising_environ(monkeypatch)
        linear_agent.emit_run_started(
            tmp_path, plan_ref=_LINEAR_PLAN_REF, run_id="r", environ=_TOKEN_ENV
        )  # must not raise
        err = capsys.readouterr().err
        assert "perk linear-agent: run-started emission skipped (non-fatal):" in err

    def test_programming_error_propagates_out_of_the_emitter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Fail-soft covers the typed expected failures (IssueBackendError, OSError) only —
        # a bug in the emission layer surfaces instead of becoming a non-fatal note.
        def _boom(_environ: Any) -> Any:
            raise RuntimeError("bug in the emission layer")

        monkeypatch.setattr(linear_agent, "agent_client_from_env", _boom)
        with pytest.raises(RuntimeError):
            linear_agent.emit_run_started(
                tmp_path, plan_ref=_LINEAR_PLAN_REF, run_id="r", environ=_TOKEN_ENV
            )


class TestPrOpened:
    def test_emits_action_activity_and_adds_external_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = _recording_environ(monkeypatch)
        _seed_session(tmp_path)
        linear_agent.emit_pr_opened(
            tmp_path,
            pr_number=42,
            pr_url="https://github.com/acme/x/pull/42",
            branch="plan-ENG-123",
            environ=_TOKEN_ENV,
        )
        assert len(seen) == 2
        activity = json.loads(seen[0].content)
        content = activity["variables"]["input"]["content"]
        assert content == {
            "type": "action",
            "action": "Opened pull request",
            "parameter": "plan-ENG-123",
            "result": "https://github.com/acme/x/pull/42",
        }
        update = json.loads(seen[1].content)
        assert "agentSessionUpdate" in update["query"]
        assert update["variables"]["id"] == "sess-1"
        assert update["variables"]["input"]["addedExternalUrls"] == [
            {"label": "PR #42", "url": "https://github.com/acme/x/pull/42"}
        ]

    def test_missing_session_file_skips_with_a_note(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        seen = _recording_environ(monkeypatch)
        cache.write_plan_ref(tmp_path, _LINEAR_PLAN_REF)  # gate open, but no session file
        linear_agent.emit_pr_opened(
            tmp_path, pr_number=42, pr_url="u", branch="b", environ=_TOKEN_ENV
        )
        assert seen == []
        assert "no agent-session.json" in capsys.readouterr().err

    def test_fail_soft(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _raising_environ(monkeypatch)
        _seed_session(tmp_path)
        linear_agent.emit_pr_opened(
            tmp_path, pr_number=42, pr_url="u", branch="b", environ=_TOKEN_ENV
        )  # must not raise
        assert "pr-opened emission skipped (non-fatal):" in capsys.readouterr().err


class TestLanded:
    def test_emits_response_activity_with_summary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = _recording_environ(monkeypatch)
        _seed_session(tmp_path)
        linear_agent.emit_landed(
            tmp_path, pr_number=42, summary="Objective nodes marked done: 5.1.", environ=_TOKEN_ENV
        )
        assert len(seen) == 1
        content = json.loads(seen[0].content)["variables"]["input"]["content"]
        assert content["type"] == "response"
        assert content["body"] == "PR #42 squash-merged. Objective nodes marked done: 5.1."

    def test_empty_summary_keeps_the_base_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = _recording_environ(monkeypatch)
        _seed_session(tmp_path)
        linear_agent.emit_landed(tmp_path, pr_number=42, summary="  ", environ=_TOKEN_ENV)
        content = json.loads(seen[0].content)["variables"]["input"]["content"]
        assert content["body"] == "PR #42 squash-merged."


class TestRunFailed:
    def test_emits_error_activity_with_run_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = _recording_environ(monkeypatch)
        _seed_session(tmp_path)
        linear_agent.emit_run_failed(
            tmp_path, exit_code=3, run_url="https://gh/run/1", environ=_TOKEN_ENV
        )
        content = json.loads(seen[0].content)["variables"]["input"]["content"]
        assert content["type"] == "error"
        assert "exit code 3" in content["body"]
        assert "https://gh/run/1" in content["body"]

    def test_fail_soft(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _raising_environ(monkeypatch)
        _seed_session(tmp_path)
        linear_agent.emit_run_failed(
            tmp_path, exit_code=1, run_url=None, environ=_TOKEN_ENV
        )  # must not raise
        assert "run-failed emission skipped (non-fatal):" in capsys.readouterr().err


class TestAgentSession:
    def test_round_trip(self, tmp_path: Path) -> None:
        session = cache.AgentSession(session_id="s", issue="ENG-1", url=None)
        path = cache.write_agent_session(tmp_path, session)
        assert path == tmp_path / ".perk" / "workflow" / "agent-session.json"
        assert cache.read_agent_session(tmp_path) == session

    def test_absent_reads_none(self, tmp_path: Path) -> None:
        assert cache.read_agent_session(tmp_path) is None
