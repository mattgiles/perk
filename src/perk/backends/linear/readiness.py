from dataclasses import dataclass
from pathlib import Path

from perk import objective, plan
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear._helpers import (
    _NODE_STATUS_STATE_TYPE,
)
from perk.backends.linear.backend import LinearIssueBackend
from perk.backends.linear.client import (
    LinearClient,
    _opt_dict,
    _opt_list,
    _opt_str,
)

# ===========================================================================
# Shared readiness probe — used by both `perk init` and `perk doctor`.
# Report-shaped (never raises): every failure mode lands in a `LinearReadiness` field,
# mirroring `github.check_auth`'s degrade discipline. Offline-testable through a
# `LinearClient`-subclass fake.
# ===========================================================================

# The five perk labels (name, color, description), the readiness probe ensures/looks up.
_PERK_LABELS: tuple[tuple[str, str, str], ...] = (
    (plan.PLAN_LABEL, plan.PLAN_LABEL_COLOR, plan.PLAN_LABEL_DESCRIPTION),
    (plan.LEARN_LABEL, plan.LEARN_LABEL_COLOR, plan.LEARN_LABEL_DESCRIPTION),
    (plan.CONSOLIDATED_LABEL, plan.CONSOLIDATED_LABEL_COLOR, plan.CONSOLIDATED_LABEL_DESCRIPTION),
    (
        objective.OBJECTIVE_LABEL,
        objective.OBJECTIVE_LABEL_COLOR,
        objective.OBJECTIVE_LABEL_DESCRIPTION,
    ),
    (
        objective.OBJECTIVE_NODE_LABEL,
        objective.OBJECTIVE_NODE_LABEL_COLOR,
        objective.OBJECTIVE_NODE_LABEL_DESCRIPTION,
    ),
)


@dataclass(frozen=True)
class LinearReadiness:
    """The init/doctor Linear readiness snapshot (report-shaped; never raises)."""

    auth_ok: bool
    user: str | None
    team_ok: bool
    missing_labels: tuple[str, ...] = ()
    created_labels: tuple[str, ...] = ()
    error: str | None = None


def check_readiness(client: LinearClient, *, team_key: str, ensure_labels: bool) -> LinearReadiness:
    """Probe Linear readiness: viewer auth, team resolution, and the five perk labels.

    Report-shaped — every failure mode lands in a ``LinearReadiness`` field (never raises),
    mirroring ``github.check_auth``. Phases short-circuit: an auth failure skips team + labels; a
    team failure skips labels. With ``ensure_labels=False`` (doctor report path) labels are
    looked up only and missing names land in ``missing_labels``; with ``ensure_labels=True``
    (init + doctor ``--fix``) each of the five labels is ensured and names actually created land in
    ``created_labels`` (lookup-first idempotency → a converged workspace reports none).
    """
    # --- auth: one viewer query ---
    try:
        data = client.request("{ viewer { id name email } }")
    except IssueBackendError as exc:
        return LinearReadiness(auth_ok=False, user=None, team_ok=False, error=str(exc))
    viewer_dict = _opt_dict(data.get("viewer"))
    user: str | None = None
    if viewer_dict is not None:
        name = viewer_dict.get("name")
        email = viewer_dict.get("email")
        user = name if isinstance(name, str) and name.strip() else None
        if user is None and isinstance(email, str) and email.strip():
            user = email

    # --- team: resolve the team UUID (the client's shared resolver) ---
    backend = LinearIssueBackend(client, team_key=team_key, repo_root=Path())
    try:
        client.team_id(team_key)
    except IssueBackendError as exc:
        return LinearReadiness(auth_ok=True, user=user, team_ok=False, error=str(exc))

    # --- labels: the four perk labels ---
    missing: list[str] = []
    created: list[str] = []
    try:
        for name, color, description in _PERK_LABELS:
            if ensure_labels:
                _, was_created = backend._ops._ensure_label_id(
                    name, color=color, description=description
                )
                if was_created:
                    created.append(name)
            elif backend._ops._lookup_label_id(name) is None:
                missing.append(name)
    except IssueBackendError as exc:
        return LinearReadiness(
            auth_ok=True,
            user=user,
            team_ok=True,
            missing_labels=tuple(missing),
            created_labels=tuple(created),
            error=str(exc),
        )
    return LinearReadiness(
        auth_ok=True,
        user=user,
        team_ok=True,
        missing_labels=tuple(missing),
        created_labels=tuple(created),
    )


# The workflow-state `type`s the node-status mirror (`_NODE_STATUS_STATE_TYPE`) needs. Derived from
# the map (never hand-listed) so the two stay in lockstep (= {unstarted, started, completed,
# canceled}).
_REQUIRED_STATE_TYPES: frozenset[str] = frozenset(_NODE_STATUS_STATE_TYPE.values())


@dataclass(frozen=True)
class LinearProjectReadiness:
    """Project-backed objective readiness snapshot (report-shaped; never raises).

    Probed only after `check_readiness` reports auth_ok && team_ok. `projects_ok` reflects a
    non-mutating Project read probe (the find-scan's prerequisite); `missing_state_types` are
    the node-status-mirror state types the team lacks. Both are warn-level / non-fatal.
    """

    projects_ok: bool
    projects_error: str | None = None
    missing_state_types: tuple[str, ...] = ()
    states_error: str | None = None


def _present_state_types(data: dict[str, object]) -> frozenset[str]:
    """Lenient parse of the present workflow-state `type` strings from a team-states payload.

    Skips malformed nodes rather than raising (this probe never raises): a non-dict ``team`` /
    ``states`` / node, or a non-str ``type``, is simply dropped.
    """
    team = _opt_dict(data.get("team"))
    if team is None:
        return frozenset()
    states = _opt_dict(team.get("states"))
    if states is None:
        return frozenset()
    nodes = _opt_list(states.get("nodes"))
    if nodes is None:
        return frozenset()
    present: set[str] = set()
    for raw in nodes:
        node = _opt_dict(raw)
        if node is None:
            continue
        node_type = _opt_str(node.get("type"))
        if node_type is not None:
            present.add(node_type)
    return frozenset(present)


def check_project_readiness(client: LinearClient, *, team_key: str) -> LinearProjectReadiness:
    """Probe project-backed objective readiness: Project read-access + the workflow-state types
    the node-status mirror needs. Report-shaped (never raises). The CALLER gates on auth_ok &&
    team_ok — this reuses the client's cached ``team_id`` (a cache hit after ``check_readiness``),
    so no auth/team re-probe.
    """
    team_id = client.team_id(team_key)

    # --- projects: a non-mutating Project read (the find-scan's prerequisite). Independent of the
    # states phase — does NOT short-circuit it. ---
    projects_ok = False
    projects_error: str | None = None
    try:
        client.request(
            "query($teamId: String!) { team(id: $teamId) { projects(first: 1) { nodes { id } } } }",
            {"teamId": team_id},
        )
        projects_ok = True
    except IssueBackendError as exc:
        projects_error = str(exc)

    # --- states: the workflow-state types the node-status mirror needs. ---
    missing_state_types: tuple[str, ...] = ()
    states_error: str | None = None
    try:
        data = client.request(
            "query($teamId: String!) { team(id: $teamId) { states { nodes { type } } } }",
            {"teamId": team_id},
        )
        present = _present_state_types(data)
        missing_state_types = tuple(sorted(_REQUIRED_STATE_TYPES - present))
    except IssueBackendError as exc:
        states_error = str(exc)

    return LinearProjectReadiness(
        projects_ok=projects_ok,
        projects_error=projects_error,
        missing_state_types=missing_state_types,
        states_error=states_error,
    )
