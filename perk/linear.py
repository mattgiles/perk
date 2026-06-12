"""The Linear GraphQL client substrate (Objective #252, Node 2.1).

One request wrapper (``LinearClient.request``) over ``https://api.linear.app/graphql`` —
personal-API-key auth (a **plain** ``Authorization: <API_KEY>`` header; ``Bearer`` is
OAuth2-only), explicit timeouts, and an error boundary that maps every failure mode into the
backend-neutral ``IssueBackendError`` (with the structured ``LinearGraphQLError`` subclass for
GraphQL-level errors). There is no legacy Linear substrate, so this client itself IS the
boundary: it raises ``IssueBackendError`` directly, never a private error type translated later.

Errors-array-first ordering (per the Linear docs audit in plan #340): the wrapper parses the
JSON body and raises ``LinearGraphQLError`` whenever an ``errors`` array is present,
**regardless of HTTP status** — that is how rate-limit failures actually arrive (HTTP 400 with
``errors[].extensions.code == "RATELIMITED"``, not HTTP 429) and how auth failures arrive.
Status-based handling is the fallback for non-2xx responses whose bodies carry no GraphQL
errors. Partial success (``errors`` alongside partial ``data``) fails loud — perk's narrow
queries never want partial results.

Deliberately dormant: the consumer now exists (``perk/linear_backend.py``'s
``LinearIssueBackend``, Node 2.2), but the resolver in ``perk/issues.py`` still raises on
``backend = "linear"`` until Nodes 2.3/2.4 wire it.

Explicit deferrals (flagged, not silently omitted):

- **Retry/backoff on RATELIMITED** — fail loud now (a typed ``LinearGraphQLError``); revisit
  once Node 2.2/2.3 call patterns exist.
- **``LINEAR_API_KEY`` validation in init/doctor + contracts.md documentation** — Node 2.4.
  This node is single-plane (Python) and dormant, so contracts.md is untouched.
"""

import os
from collections.abc import Mapping
from typing import cast

import httpx

from perk.issue_backend import IssueBackendError

LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"

RATELIMITED_CODE = "RATELIMITED"
"""The documented ``extensions.code`` for rate-limit failures (arrives as HTTP 400)."""

_AUTHENTICATION_ERROR_CODE = "AUTHENTICATION_ERROR"

_API_KEY_HINT = (
    "set LINEAR_API_KEY — create a personal API key at linear.app Settings → Security & access"
)

_TIMEOUT = 30  # seconds — matches github.py's _WRITE_TIMEOUT; one wrapper, one ceiling.

_BODY_SLICE = 500  # bounded body excerpt in diagnostics


class LinearGraphQLError(IssueBackendError):
    """A Linear response carried a GraphQL ``errors`` array.

    ``codes`` holds the de-duplicated ``extensions.code`` values (order-preserved; entries
    without a code omitted). Consumers (Node 2.2) branch on ``.codes``, never on substrings —
    ``str(exc)`` keeps Linear's verbatim error messages for humans.
    """

    def __init__(self, message: str, *, codes: tuple[str, ...]) -> None:
        super().__init__(message)
        self.codes = codes


class LinearClient:
    """The one Linear GraphQL request wrapper.

    Constructor-bound auth (the Linear analog of ``GitHubIssueBackend``'s constructor-bound
    ``repo_root``): an instance is constructed for exactly one API key. ``transport`` is
    injectable for offline tests (``httpx.MockTransport``).
    """

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = _TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise IssueBackendError(f"Linear API key is empty; {_API_KEY_HINT}")
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport

    def request(self, query: str, variables: dict[str, object] | None = None) -> dict[str, object]:
        """POST one GraphQL request; return the ``data`` dict or raise ``IssueBackendError``.

        Raises ``LinearGraphQLError`` whenever the body carries a GraphQL ``errors`` array
        (regardless of HTTP status); plain ``IssueBackendError`` for transport failures,
        non-2xx statuses without GraphQL errors, and malformed bodies. Lookup-miss ``None``
        *fields inside* ``data`` are the caller's domain — never interpreted here.
        """
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.post(
                    LINEAR_GRAPHQL_URL,
                    json={"query": query, "variables": variables or {}},
                    headers={
                        "Authorization": self._api_key,
                        "Content-Type": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            raise IssueBackendError(f"Linear API request failed: {exc}") from exc

        body: object | None
        try:
            body = response.json()
        except ValueError:
            body = None

        if isinstance(body, dict):
            errors = body.get("errors")
            if isinstance(errors, list) and errors:
                raise _graphql_error(errors, status=response.status_code)

        if response.status_code < 200 or response.status_code >= 300:
            message = f"Linear API request failed with HTTP {response.status_code}"
            if response.status_code == 401:
                message += f"; check LINEAR_API_KEY ({_API_KEY_HINT})"
            excerpt = response.text[:_BODY_SLICE]
            if excerpt:
                message += f": {excerpt}"
            raise IssueBackendError(message)

        if not isinstance(body, dict):
            raise IssueBackendError(
                f"unparseable Linear API response (expected a JSON object): "
                f"{response.text[:_BODY_SLICE]}"
            )

        data = body.get("data")
        if not isinstance(data, dict):
            raise IssueBackendError(
                f"Linear API response missing data: {response.text[:_BODY_SLICE]}"
            )
        return data


def client_from_env(env: Mapping[str, str] | None = None) -> LinearClient:
    """Build a ``LinearClient`` from ``LINEAR_API_KEY`` (default ``os.environ``)."""
    source = os.environ if env is None else env
    api_key = source.get("LINEAR_API_KEY", "").strip()
    if not api_key:
        raise IssueBackendError(f"LINEAR_API_KEY is not set; {_API_KEY_HINT}")
    return LinearClient(api_key=api_key)


def _graphql_error(errors: list[object], *, status: int) -> LinearGraphQLError:
    """Build a ``LinearGraphQLError`` from a GraphQL ``errors`` array, tolerating junk entries."""
    messages: list[str] = []
    codes: list[str] = []
    for entry in errors:
        if isinstance(entry, dict):
            entry_dict = cast("dict[str, object]", entry)
            raw_message = entry_dict.get("message")
            messages.append(
                raw_message if isinstance(raw_message, str) else "(malformed Linear error entry)"
            )
            extensions = entry_dict.get("extensions")
            if isinstance(extensions, dict):
                code = cast("dict[str, object]", extensions).get("code")
                if isinstance(code, str) and code not in codes:
                    codes.append(code)
        else:
            messages.append("(malformed Linear error entry)")
    message = "Linear GraphQL error: " + "; ".join(messages)
    if _AUTHENTICATION_ERROR_CODE in codes or status == 401:
        message += f" — check LINEAR_API_KEY ({_API_KEY_HINT})"
    return LinearGraphQLError(message, codes=tuple(codes))
