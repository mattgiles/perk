"""The Linear readiness group builder + its per-phase sub-builders.

Cohesive per-phase sub-builders; every emitted ``Check``
(name/group/status/message/detail/remediation) and the phase short-circuit ordering is
load-bearing.
"""

import tomllib
from pathlib import Path

from perk.backends import linear, resolve
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import client as linear_client
from perk.convergence.doctor.data import Check
from perk.substrate.config import (
    ConfigError,
    load_committed_issues_backend,
    load_committed_issues_team,
)


def _linear_selected(root: Path) -> bool:
    """The verify-gate read for the `linear` group (a malformed/ill-typed config defers to the
    config check). The downstream `[issues] team` reads run only when this returned ``True``,
    so they need no guard of their own (the whole table validated as one model)."""
    try:
        return load_committed_issues_backend(root) == resolve.LINEAR_BACKEND_ID
    except (tomllib.TOMLDecodeError, ConfigError):
        return False


_LINEAR_KEY_REMEDIATION = (
    "export LINEAR_API_KEY (create a personal API key at linear.app Settings → Security & access), "
    "or set [linear] api_key in .perk/local.toml — or re-run 'perk init' interactively to be "
    "prompted"
)


def _linear_auth_check(readiness: linear.LinearReadiness) -> Check:
    """The ``linear-auth`` Check from a completed probe: ``ok`` when authed, else ``warn``."""
    if not readiness.auth_ok:
        return Check(
            "linear-auth",
            "linear",
            "warn",
            "Linear not authenticated",
            readiness.error or "",
            _LINEAR_KEY_REMEDIATION,
        )
    return Check("linear-auth", "linear", "ok", f"authenticated as {readiness.user or '?'}")


def _linear_team_check(readiness: linear.LinearReadiness, team: str) -> Check:
    """The ``linear-team`` Check: ``ok`` when the team resolved, else ``warn``."""
    if not readiness.team_ok:
        return Check(
            "linear-team",
            "linear",
            "warn",
            f"team {team} not verified",
            readiness.error or "",
            'Set [issues] team to your Linear team key (e.g. "ENG") in .perk/config.toml.',
        )
    return Check("linear-team", "linear", "ok", f"team {team} found")


def _linear_label_check(readiness: linear.LinearReadiness) -> Check:
    """The ``linear-labels`` Check: unverified ``warn`` / missing ``warn`` / present ``ok``."""
    if readiness.error:
        return Check("linear-labels", "linear", "warn", "labels not verified", readiness.error)
    if readiness.missing_labels:
        return Check(
            "linear-labels",
            "linear",
            "warn",
            f"missing label(s): {', '.join(readiness.missing_labels)}",
            "",
            "Run `perk init` or `perk doctor --fix`.",
        )
    return Check("linear-labels", "linear", "ok", "perk labels present")


def _linear_project_checks(client: linear_client.LinearClient, team: str) -> list[Check]:
    """The ``linear-project-scopes`` + ``linear-workflow-states`` Checks (Projects readiness).

    Project-backed objective readiness (verify-gated, non-fatal). Called only on the ``team_ok``
    path — auth/team failures short-circuit before this probe. Reuses the client's cached team id
    (a cache hit after ``check_readiness``).
    """
    project = linear.check_project_readiness(client, team_key=team)
    checks: list[Check] = []
    if project.projects_ok:
        checks.append(Check("linear-project-scopes", "linear", "ok", "Linear Projects accessible"))
    else:
        checks.append(
            Check(
                "linear-project-scopes",
                "linear",
                "warn",
                "Linear Projects not accessible",
                project.projects_error or "",
                "Grant the Linear API token access to Projects (a personal API key at "
                "linear.app Settings → Security & access has full access).",
            )
        )
    if project.states_error:
        checks.append(
            Check(
                "linear-workflow-states",
                "linear",
                "warn",
                "workflow states not verified",
                project.states_error,
            )
        )
    elif project.missing_state_types:
        checks.append(
            Check(
                "linear-workflow-states",
                "linear",
                "warn",
                f"missing workflow state type(s): {', '.join(project.missing_state_types)}",
                "",
                f"Add Linear workflow state(s) of type "
                f"{', '.join(project.missing_state_types)} to team {team} "
                "(the node-status board mirror needs them).",
            )
        )
    else:
        checks.append(
            Check(
                "linear-workflow-states",
                "linear",
                "ok",
                "workflow states cover the node-status mirror",
            )
        )
    return checks


def _linear_checks(root: Path) -> list[Check]:
    """Linear readiness — verify-gated; always non-fatal (`warn`, the github-group D3 mirror).

    Built from one ``check_readiness(..., ensure_labels=False)`` call (lookup-only — the repair
    is `perk init` / `perk doctor --fix`), composed from per-phase sub-builders. Phases
    short-circuit like the probe: no auth → no team/labels checks (no silent pass — the failure
    carries its reason).
    """
    team = load_committed_issues_team(root)
    try:
        client = linear_client.client_from_env(repo_root=root)
    except IssueBackendError as exc:
        return [
            Check(
                "linear-auth",
                "linear",
                "warn",
                "Linear auth not verified",
                str(exc),
                _LINEAR_KEY_REMEDIATION,
            )
        ]
    if team is None:
        # The offline `issues-backend` check already fails on this; the network probe needs a
        # team to run, so report the gap here too (no silent pass) and stop.
        return [
            Check(
                "linear-team",
                "linear",
                "warn",
                "[issues] team not set — readiness not checked",
                "",
                "Set [issues] team in .perk/config.toml.",
            )
        ]
    readiness = linear.check_readiness(client, team_key=team, ensure_labels=False)
    auth = _linear_auth_check(readiness)
    if not readiness.auth_ok:
        return [auth]
    checks = [auth, _linear_team_check(readiness, team)]
    if not readiness.team_ok:
        return checks
    checks.append(_linear_label_check(readiness))
    checks.extend(_linear_project_checks(client, team))
    return checks
