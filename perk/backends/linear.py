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

Live: the consumer exists (``perk/backends/linear_backend.py``'s ``LinearIssueBackend``) and the
resolver in ``perk/backends/issues.py`` constructs it on ``backend = "linear"`` (Node 2.4 wired
config, init/doctor readiness, and contracts §8.21).

Explicit deferrals (flagged, not silently omitted):

- **Retry/backoff on RATELIMITED** — *decided fail-loud* (Node 1.2). No RATELIMITED tripped at
  the live smoke gate (``docs/planning/linear-smoke-gate.md`` gate-9, "not tripped at low
  volume"), so there is no observed behavior to justify backoff. ``LinearClient.request`` keeps
  raising the typed ``LinearGraphQLError`` on ``RATELIMITED_CODE``; retry/backoff stays deferred
  until a live RATELIMITED is observed at the gate.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import httpx

from perk.backends.issue_backend import IssueBackendError
from perk.substrate import config


def _require_dict(value: object, what: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise IssueBackendError(f"unexpected Linear payload shape ({what}): {value!r}")
    return cast("dict[str, object]", value)


def _require_list(value: object, what: str) -> list[object]:
    if not isinstance(value, list):
        raise IssueBackendError(f"unexpected Linear payload shape ({what}): {value!r}")
    return cast("list[object]", value)


def _require_str(value: object, what: str) -> str:
    if not isinstance(value, str):
        raise IssueBackendError(f"unexpected Linear payload shape ({what}): {value!r}")
    return value


# --- optional-aware (tolerant, NEVER-raise) siblings of the _require_* family ---
# These internalize the `cast`-after-`isinstance` workaround for the ty quirk "isinstance does not
# narrow through a subsequent __getitem__" (docs/learned/toolchain/ty.md) for the LENIENT parse
# sites that must skip / default / return None on a malformed shape rather than fail loud.


def _opt_dict(value: object) -> dict[str, object] | None:
    return cast("dict[str, object]", value) if isinstance(value, dict) else None


def _opt_list(value: object) -> list[object] | None:
    return cast("list[object]", value) if isinstance(value, list) else None


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


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


_ENTITY_NOT_FOUND_CODE = "INPUT_ERROR"


def _is_entity_not_found(exc: LinearGraphQLError) -> bool:
    """A missing-entity error: Linear returns the generic ``INPUT_ERROR`` code with an
    ``"Entity not found: <Entity>"`` message (observed at the live smoke gate, 2026-06-15 —
    docs/planning/linear-smoke-gate.md gate-8 row). ``INPUT_ERROR`` alone is too broad (a generic
    input-error code), so pair it with the message prefix."""
    return _ENTITY_NOT_FOUND_CODE in exc.codes and "entity not found" in str(exc).lower()


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
        bearer: bool = False,
    ) -> None:
        if not api_key.strip():
            raise IssueBackendError(f"Linear API key is empty; {_API_KEY_HINT}")
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport
        # OAuth tokens (e.g. an actor=app agent token) use the `Bearer <token>` form;
        # personal API keys keep the plain `Authorization: <API_KEY>` header byte-identically.
        self._bearer = bearer
        # Resolved-id memoization, the natural home for the shared caches (correction §3d): a
        # store that owns one client and constructs both op classes over it gets a single shared
        # cache automatically — without the op classes composing each other. The client stays
        # team-agnostic at construction, so `_team_id_cache` is keyed by team key.
        self._team_id_cache: dict[str, str] = {}
        # The API-key user's viewer UUID (the project lead / issue assignee). Resolved once and
        # memoized, mirroring `_team_id_cache`; the viewer is constant for one API key.
        self._viewer_id_cache: str | None = None

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
                        "Authorization": (
                            f"Bearer {self._api_key}" if self._bearer else self._api_key
                        ),
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

    # ------------------------------------------------------------------ shared machinery
    # The single home for Linear GraphQL API-client logic (correction §3): team-UUID + uuid
    # resolution and the generic cursor loop live on the client, so both op classes reach them
    # through ``self._client`` instead of one composing the other.

    def team_id(self, team_key: str) -> str:
        """Resolve (and cache, by team key) the team UUID from a team key."""
        cached = self._team_id_cache.get(team_key)
        if cached is not None:
            return cached
        query = "query($key: String!) { teams(filter: { key: { eq: $key } }) { nodes { id } } }"
        data = self.request(query, {"key": team_key})
        teams = _require_dict(data.get("teams"), "teams")
        nodes = _require_list(teams.get("nodes"), "teams.nodes")
        if not nodes:
            raise IssueBackendError(f"Linear team {team_key!r} not found")
        node = _require_dict(nodes[0], "teams.nodes[0]")
        team_id = _require_str(node.get("id"), "team id")
        self._team_id_cache[team_key] = team_id
        return team_id

    def viewer_id(self) -> str:
        """Resolve (and cache) the API-key user's viewer UUID.

        One ``query { viewer { id } }`` request; the viewer is the human user behind the personal
        API key, so the id is constant for one client and cached after the first call (mirroring
        :meth:`team_id`'s memoization). Raises ``IssueBackendError`` on a malformed payload.
        """
        cached = self._viewer_id_cache
        if cached is not None:
            return cached
        data = self.request("query { viewer { id } }")
        viewer = _require_dict(data.get("viewer"), "viewer")
        viewer_id = _require_str(viewer.get("id"), "viewer id")
        self._viewer_id_cache = viewer_id
        return viewer_id

    def paginate(
        self, query: str, variables: dict[str, object], *path: str
    ) -> list[dict[str, object]]:
        """Generic cursor loop over a ``nodes`` + ``pageInfo`` connection at ``path``.

        ``query`` must accept a ``$cursor: String`` variable and select
        ``pageInfo { hasNextPage endCursor }``. Malformed payload shapes raise (never silently
        truncate).
        """
        nodes: list[dict[str, object]] = []
        cursor: str | None = None
        while True:
            data = self.request(query, {**variables, "cursor": cursor})
            connection: object = data
            for key in path:
                connection = _require_dict(connection, ".".join(path)).get(key)
            conn = _require_dict(connection, ".".join(path))
            for raw in _require_list(conn.get("nodes"), "nodes"):
                nodes.append(_require_dict(raw, "node"))
            page_info = _require_dict(conn.get("pageInfo"), "pageInfo")
            if not page_info.get("hasNextPage"):
                return nodes
            cursor = _require_str(page_info.get("endCursor"), "endCursor")


def client_from_env(
    env: Mapping[str, str] | None = None, *, repo_root: Path | None = None
) -> LinearClient:
    """Build a ``LinearClient`` from ``LINEAR_API_KEY`` (default ``os.environ``).

    The env value **wins**: it is resolved first (stripped). Only when it is empty/blank **and**
    ``repo_root`` is given does the local-only ``config.load_local_linear_api_key(repo_root)``
    fallback (the gitignored ``.pi/perk.local.toml`` ``[linear] api_key``) apply. ``repo_root=None``
    (the default) preserves the env-only behavior for every existing caller. Still empty ⇒ the
    unchanged hinted ``IssueBackendError``.
    """
    source = os.environ if env is None else env
    api_key = source.get("LINEAR_API_KEY", "").strip()
    if not api_key and repo_root is not None:
        api_key = config.load_local_linear_api_key(repo_root) or ""
    if not api_key:
        raise IssueBackendError(f"LINEAR_API_KEY is not set; {_API_KEY_HINT}")
    return LinearClient(api_key=api_key)


def _graphql_error(errors: list[object], *, status: int) -> LinearGraphQLError:
    """Build a ``LinearGraphQLError`` from a GraphQL ``errors`` array, tolerating junk entries."""
    messages: list[str] = []
    codes: list[str] = []
    for entry in errors:
        entry_dict = _opt_dict(entry)
        if entry_dict is not None:
            raw_message = entry_dict.get("message")
            messages.append(
                raw_message if isinstance(raw_message, str) else "(malformed Linear error entry)"
            )
            extensions = _opt_dict(entry_dict.get("extensions"))
            if extensions is not None:
                code = extensions.get("code")
                if isinstance(code, str) and code not in codes:
                    codes.append(code)
        else:
            messages.append("(malformed Linear error entry)")
    message = "Linear GraphQL error: " + "; ".join(messages)
    if _AUTHENTICATION_ERROR_CODE in codes or status == 401:
        message += f" — check LINEAR_API_KEY ({_API_KEY_HINT})"
    return LinearGraphQLError(message, codes=tuple(codes))
