"""Offline tests for the Linear GraphQL client substrate (``perk/backends/linear.py``).

Everything runs over an injected ``httpx.MockTransport`` — no network. ``client_from_env`` is
tested with explicit ``env={...}`` mappings, never the real environ.
"""

import json
from pathlib import Path

import httpx
import pytest

from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear.client import (
    LINEAR_GRAPHQL_URL,
    RATELIMITED_CODE,
    LinearClient,
    LinearGraphQLError,
    client_from_env,
)


def _client_with_response(
    *, status: int = 200, body: object | None = None, text: str | None = None
) -> tuple[LinearClient, list[httpx.Request]]:
    """A ``LinearClient`` over a MockTransport; the handler records received requests."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=body)

    client = LinearClient(api_key="lin_api_test", transport=httpx.MockTransport(handler))
    return client, seen


def _client_raising(exc: Exception) -> LinearClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return LinearClient(api_key="lin_api_test", transport=httpx.MockTransport(handler))


class TestRequestComposition:
    def test_success_round_trip_composes_the_documented_request(self) -> None:
        client, seen = _client_with_response(body={"data": {"issue": {"id": "abc"}}})
        data = client.request("query Q { issue { id } }", {"id": "abc"})
        assert data == {"issue": {"id": "abc"}}
        assert len(seen) == 1
        request = seen[0]
        assert request.method == "POST"
        assert str(request.url) == LINEAR_GRAPHQL_URL
        # Personal API keys use the plain form — NOT `Bearer <key>` (that's OAuth2-only).
        assert request.headers["Authorization"] == "lin_api_test"
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {
            "query": "query Q { issue { id } }",
            "variables": {"id": "abc"},
        }

    def test_bearer_mode_sends_the_oauth_header_form(self) -> None:
        # `bearer=True` is the OAuth (actor=app agent token) form used by
        # perk/backends/linear/agent.py.
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"data": {}})

        client = LinearClient(
            api_key="lin_oauth_test", transport=httpx.MockTransport(handler), bearer=True
        )
        client.request("query Q { viewer { id } }")
        assert seen[0].headers["Authorization"] == "Bearer lin_oauth_test"

    def test_omitted_variables_default_to_empty_object(self) -> None:
        client, seen = _client_with_response(body={"data": {}})
        client.request("query Q { viewer { id } }")
        assert json.loads(seen[0].content)["variables"] == {}


class TestViewerId:
    def test_resolves_and_caches_the_viewer_uuid(self) -> None:
        client, seen = _client_with_response(body={"data": {"viewer": {"id": "usr-1"}}})
        assert client.viewer_id() == "usr-1"
        # cached: a second call issues no further request
        assert client.viewer_id() == "usr-1"
        assert len(seen) == 1
        assert "viewer" in json.loads(seen[0].content)["query"]

    def test_malformed_payload_raises(self) -> None:
        client, _ = _client_with_response(body={"data": {"viewer": {"id": 7}}})
        with pytest.raises(IssueBackendError, match="viewer id"):
            client.viewer_id()

    def test_missing_viewer_raises(self) -> None:
        client, _ = _client_with_response(body={"data": {"viewer": None}})
        with pytest.raises(IssueBackendError, match="viewer"):
            client.viewer_id()


class TestGraphQLErrors:
    def test_ratelimited_arrives_as_http_400_with_a_code(self) -> None:
        # The documented rate-limit shape: HTTP 400, extensions.code == "RATELIMITED".
        client, _ = _client_with_response(
            status=400,
            body={
                "errors": [
                    {
                        "message": "Rate limit exceeded",
                        "extensions": {"code": RATELIMITED_CODE},
                    }
                ]
            },
        )
        with pytest.raises(LinearGraphQLError) as excinfo:
            client.request("query Q { viewer { id } }")
        assert excinfo.value.codes == (RATELIMITED_CODE,)
        assert "Rate limit exceeded" in str(excinfo.value)

    def test_partial_success_raises_and_discards_data(self) -> None:
        client, _ = _client_with_response(
            body={
                "data": {"issue": {"id": "abc"}},
                "errors": [{"message": "field failed"}],
            }
        )
        with pytest.raises(LinearGraphQLError, match="field failed"):
            client.request("query Q { issue { id } }")

    def test_multiple_errors_join_messages_and_dedupe_codes_order_preserved(self) -> None:
        client, _ = _client_with_response(
            status=400,
            body={
                "errors": [
                    {"message": "first", "extensions": {"code": "B"}},
                    {"message": "second", "extensions": {"code": "A"}},
                    {"message": "third", "extensions": {"code": "B"}},
                ]
            },
        )
        with pytest.raises(LinearGraphQLError) as excinfo:
            client.request("q")
        assert excinfo.value.codes == ("B", "A")
        assert "first; second; third" in str(excinfo.value)

    def test_error_entry_without_extensions_degrades_gracefully(self) -> None:
        client, _ = _client_with_response(
            status=400, body={"errors": [{"message": "no extensions here"}]}
        )
        with pytest.raises(LinearGraphQLError) as excinfo:
            client.request("q")
        assert excinfo.value.codes == ()
        assert "no extensions here" in str(excinfo.value)

    def test_malformed_error_entry_degrades_to_a_generic_message(self) -> None:
        client, _ = _client_with_response(status=400, body={"errors": ["junk", {}]})
        with pytest.raises(LinearGraphQLError) as excinfo:
            client.request("q")
        assert "malformed Linear error entry" in str(excinfo.value)

    def test_authentication_error_code_appends_the_api_key_hint(self) -> None:
        client, _ = _client_with_response(
            status=400,
            body={
                "errors": [
                    {
                        "message": "Authentication required",
                        "extensions": {"code": "AUTHENTICATION_ERROR"},
                    }
                ]
            },
        )
        with pytest.raises(LinearGraphQLError, match="LINEAR_API_KEY"):
            client.request("q")

    def test_graphql_error_is_an_issue_backend_error(self) -> None:
        # The backend-neutral guarantee Node 2.2 relies on.
        client, _ = _client_with_response(status=400, body={"errors": [{"message": "x"}]})
        with pytest.raises(IssueBackendError) as excinfo:
            client.request("q")
        assert isinstance(excinfo.value, LinearGraphQLError)


class TestHTTPFailures:
    def test_401_without_graphql_body_mentions_the_api_key(self) -> None:
        client, _ = _client_with_response(status=401, text="Unauthorized")
        with pytest.raises(IssueBackendError, match="LINEAR_API_KEY") as excinfo:
            client.request("q")
        assert not isinstance(excinfo.value, LinearGraphQLError)
        assert "401" in str(excinfo.value)

    def test_500_names_the_status(self) -> None:
        client, _ = _client_with_response(status=500, text="boom")
        with pytest.raises(IssueBackendError, match="500") as excinfo:
            client.request("q")
        assert not isinstance(excinfo.value, LinearGraphQLError)


class TestTransportFailures:
    def test_connect_error_maps_with_cause_chained(self) -> None:
        cause = httpx.ConnectError("no route to host")
        client = _client_raising(cause)
        with pytest.raises(IssueBackendError, match="Linear API request failed") as excinfo:
            client.request("q")
        assert excinfo.value.__cause__ is cause

    def test_timeout_maps_with_cause_chained(self) -> None:
        cause = httpx.TimeoutException("timed out")
        client = _client_raising(cause)
        with pytest.raises(IssueBackendError, match="Linear API request failed") as excinfo:
            client.request("q")
        assert excinfo.value.__cause__ is cause


class TestMalformedResponses:
    def test_200_non_json_body(self) -> None:
        client, _ = _client_with_response(text="<html>not json</html>")
        with pytest.raises(IssueBackendError, match="unparseable Linear API response"):
            client.request("q")

    def test_200_json_list_body(self) -> None:
        client, _ = _client_with_response(body=[1, 2, 3])
        with pytest.raises(IssueBackendError, match="unparseable Linear API response"):
            client.request("q")

    def test_200_data_null(self) -> None:
        client, _ = _client_with_response(body={"data": None})
        with pytest.raises(IssueBackendError, match="missing data"):
            client.request("q")

    def test_200_empty_object(self) -> None:
        client, _ = _client_with_response(body={})
        with pytest.raises(IssueBackendError, match="missing data"):
            client.request("q")


class TestConstructorAndEnv:
    def test_empty_api_key_raises(self) -> None:
        with pytest.raises(IssueBackendError, match="empty"):
            LinearClient(api_key="   ")

    def test_client_from_env_missing_key_raises_with_remediation(self) -> None:
        with pytest.raises(IssueBackendError, match="Security & access"):
            client_from_env(env={})

    def test_client_from_env_whitespace_key_raises(self) -> None:
        with pytest.raises(IssueBackendError, match="LINEAR_API_KEY is not set"):
            client_from_env(env={"LINEAR_API_KEY": "  "})

    def test_client_from_env_returns_a_working_client(self) -> None:
        client = client_from_env(env={"LINEAR_API_KEY": "lin_api_x"})
        assert isinstance(client, LinearClient)

    @staticmethod
    def _write_local_key(repo: Path, key: str) -> None:
        pi = repo / ".pi"
        pi.mkdir(parents=True, exist_ok=True)
        (pi / "perk.local.toml").write_text(f'[linear]\napi_key = "{key}"\n', encoding="utf-8")

    def test_client_from_env_falls_back_to_local_config(self, tmp_path: Path) -> None:
        self._write_local_key(tmp_path, "lin_api_local")
        client = client_from_env(env={}, repo_root=tmp_path)
        assert isinstance(client, LinearClient)

    def test_client_from_env_falls_back_to_main_checkout_from_worktree(
        self, git_repo: Path
    ) -> None:
        # The gitignored secret lives ONLY in the main checkout; a linked worktree must still
        # authenticate by reading the main checkout's `.pi/perk.local.toml` (passes after the fix).
        self._write_local_key(git_repo, "lin_api_main")
        from perk.substrate import git as gitmod

        wt = git_repo / ".worktrees" / "wt-linear"
        gitmod.worktree_add(git_repo, wt, branch="plan-linear", create_branch=True)
        client = client_from_env(env={}, repo_root=wt)
        assert isinstance(client, LinearClient)
        assert client._api_key == "lin_api_main"

    def test_client_from_env_env_wins_over_local_config(self, tmp_path: Path) -> None:
        self._write_local_key(tmp_path, "lin_api_local")
        client = client_from_env(env={"LINEAR_API_KEY": "lin_api_env"}, repo_root=tmp_path)
        assert client._api_key == "lin_api_env"

    def test_client_from_env_repo_root_none_empty_env_raises(self) -> None:
        with pytest.raises(IssueBackendError, match="Security & access"):
            client_from_env(env={}, repo_root=None)

    def test_client_from_env_repo_root_without_key_raises(self, tmp_path: Path) -> None:
        with pytest.raises(IssueBackendError, match="LINEAR_API_KEY is not set"):
            client_from_env(env={}, repo_root=tmp_path)
