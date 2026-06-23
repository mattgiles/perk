"""The backend-tier resolvers (Objective #746, Node 2.1): the issue-backend resolver + constants.

This is the home for **both** issue-tier and objective-tier resolvers; this node carries the
issue-tier resolvers (``resolve_issue_backend_id`` / ``resolve_issue_backend``) and the backend-id
constants, the only door every issue-tier consumer goes through. The objective resolvers join it in
node 2.2 (the module is named generically so 2.2 only adds to it).

The resolver reads the **committed** ``.pi/perk.toml`` ``[issues]`` table and constructs the
matching backend (``GitHubIssueBackend`` from perk/backends/github/backend.py, or the Linear
backend). It deliberately reads the committed config only — the backend decides where canonical
durable state is written, so the local overlay is never consulted.
"""

import tomllib
from pathlib import Path

from perk.backends import issue_backend, linear
from perk.backends.github.backend import GitHubIssueBackend
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import client as linear_client
from perk.substrate import config

# The `[issues] backend` vocabulary (contracts.md §8.21). Both "github" (default) and "linear"
# are live selections; "linear" additionally requires a committed `[issues] team` and the
# `LINEAR_API_KEY` env var (resolved in `resolve_issue_backend`).
GITHUB_BACKEND_ID = "github"
LINEAR_BACKEND_ID = "linear"
KNOWN_ISSUE_BACKENDS = (GITHUB_BACKEND_ID, LINEAR_BACKEND_ID)


def resolve_issue_backend_id(repo_root: Path) -> str:
    """Resolve the repo's `[issues] backend` selection to a known backend id — or raise.

    Reads the **committed** `.pi/perk.toml` only (``load_committed_issues_backend``; the local
    overlay is deliberately never read — the backend decides where canonical durable state is
    written). Absent or ``"github"`` → ``GITHUB_BACKEND_ID``; ``"linear"`` → ``LINEAR_BACKEND_ID``.
    Unknown values **raise** ``IssueBackendError`` (falling back silently would write canonical
    issues to the wrong tracker); a malformed committed TOML is mapped into ``IssueBackendError``
    too.
    """
    try:
        selected = config.load_committed_issues_backend(repo_root)
    except tomllib.TOMLDecodeError as exc:
        raise IssueBackendError(
            f".pi/perk.toml is not valid TOML ({exc}); run `perk doctor`"
        ) from exc
    if selected is None or selected == GITHUB_BACKEND_ID:
        return GITHUB_BACKEND_ID
    if selected == LINEAR_BACKEND_ID:
        return LINEAR_BACKEND_ID
    known = ", ".join(KNOWN_ISSUE_BACKENDS)
    raise IssueBackendError(f"unknown issue backend {selected!r} (known: {known})")


def resolve_issue_backend(repo_root: Path) -> issue_backend.IssueBackend:
    """Resolve the repo's issue backend from the committed `[issues]` config table.

    Config-driven selection is live: ``resolve_issue_backend_id`` validates the selection (raising
    ``IssueBackendError`` on unknown/malformed config — every caller's existing error boundary
    handles it) and this constructs the matching backend. The Linear arm additionally requires a
    committed ``[issues] team`` (the Linear team key) and the ``LINEAR_API_KEY`` env var; either
    missing raises a hinted ``IssueBackendError``. Construction is lazy (no network): the team
    UUID is resolved on first use.
    """
    backend_id = resolve_issue_backend_id(repo_root)
    if backend_id == GITHUB_BACKEND_ID:
        return GitHubIssueBackend(repo_root)
    if backend_id == LINEAR_BACKEND_ID:
        team = config.load_committed_issues_team(repo_root)
        if team is None:
            raise IssueBackendError(
                '[issues] team is required when backend = "linear" — '
                "set the Linear team key in .pi/perk.toml"
            )
        client = linear_client.client_from_env(repo_root=repo_root)
        return linear.LinearIssueBackend(client, team_key=team, repo_root=repo_root)
    raise IssueBackendError(f"no backend implementation for {backend_id!r}")
