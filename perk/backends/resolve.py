"""The backend-tier resolvers: the issue-backend + objective-store resolvers.

This is the home for **both** issue-tier and objective-tier resolvers: the issue-tier resolvers
(``resolve_issue_backend_id`` / ``resolve_issue_backend``) and the backend-id constants are the only
door every issue-tier consumer goes through; the objective-tier resolvers
(``resolve_objective_store_id`` / ``resolve_objective_store``) are the door every objective-tier
consumer goes through.

The resolver reads the **committed** ``.perk/config.toml`` ``[issues]`` table and constructs the
matching backend (``GitHubIssueBackend`` from perk/backends/github/backend.py, or the Linear
backend). It deliberately reads the committed config only — the backend decides where canonical
durable state is written, so the local overlay is never consulted.
"""

import tomllib
from pathlib import Path

from perk.backends import issue_backend, linear, objective_store
from perk.backends.github.backend import GitHubIssueBackend
from perk.backends.github.objective_store import GitHubObjectiveStore
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

    Reads the **committed** `.perk/config.toml` only (``load_committed_issues_backend``; the local
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
            f".perk/config.toml is not valid TOML ({exc}); run `perk doctor`"
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
                "set the Linear team key in .perk/config.toml"
            )
        client = linear_client.client_from_env(repo_root=repo_root)
        return linear.LinearIssueBackend(client, team_key=team, repo_root=repo_root)
    raise IssueBackendError(f"no backend implementation for {backend_id!r}")


def resolve_objective_store_id(repo_root: Path) -> str:
    """Resolve the repo's objective-store selection — single-sourced off the ``[issues]`` table.

    An objective and its plan/learn issues share one backend selection (both populations live in the
    same tracker), so this re-exports ``resolve_issue_backend_id`` rather than reading a separate
    config key. Unknown/malformed config raises ``IssueBackendError`` (every caller's existing error
    boundary handles it).
    """
    return resolve_issue_backend_id(repo_root)


def resolve_objective_store(repo_root: Path) -> objective_store.ObjectiveStore:
    """Resolve the repo's objective store from the committed ``[issues]`` config table.

    Mirrors ``resolve_issue_backend``: ``resolve_objective_store_id`` validates the selection and
    this constructs the matching store. The Linear arm requires a committed ``[issues] team`` and
    the ``LINEAR_API_KEY`` env var (either missing raises the same hinted ``IssueBackendError``
    ``resolve_issue_backend`` raises). Construction is lazy (no network).
    """
    backend_id = resolve_objective_store_id(repo_root)
    if backend_id == GITHUB_BACKEND_ID:
        return GitHubObjectiveStore(repo_root)
    if backend_id == LINEAR_BACKEND_ID:
        team = config.load_committed_issues_team(repo_root)
        if team is None:
            raise IssueBackendError(
                '[issues] team is required when backend = "linear" — '
                "set the Linear team key in .perk/config.toml"
            )
        client = linear_client.client_from_env(repo_root=repo_root)
        return linear.LinearProjectObjectiveStore(client, team_key=team, repo_root=repo_root)
    raise IssueBackendError(f"no backend implementation for {backend_id!r}")
