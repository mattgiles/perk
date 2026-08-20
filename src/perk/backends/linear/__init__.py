"""The Linear issue backend — plans, learn issues, labels, and the generic comment ops.

``LinearIssueBackend`` implements the issue-tier contract
(``perk.backends.issue_backend.IssueBackend``) over the GraphQL client substrate
(``perk.backends.linear.client.LinearClient``), with team-scoped + label-scoped queries and
body-marker idempotency matching the ``find_plan_issue`` semantics of the GitHub backend. The
objective tier mirrors ``perk.github``'s behavior shapes
(the two-step create with comment-id backfill, header LBYL, authoritative roadmap writes +
best-effort comment re-renders, the Reconcilable splice).

Live: the resolver in the issues module constructs this backend on ``backend = "linear"`` (config
``[issues] team`` parsing, init/doctor readiness, and the contracts §8.21 amendment).
:func:`check_readiness` is the shared init/doctor readiness probe (auth + team + the four
perk labels), report-shaped (never raises), mirroring ``github.check_auth``'s degrade discipline.

**Linear-safe encoding.** Caller-composed bodies arrive in the GitHub encoding — HTML-comment
metadata-block delimiters + ``<details>`` wrappers (rendered by ``perk.plan``). Linear stores
descriptions/comments as ProseMirror documents and round-trips markdown on write/read; HTML
comments and ``<details>`` are not in its supported markdown set and must be assumed lossy
(inline code and code fences ARE supported). So every outgoing body is transcoded by
:func:`to_linear_markdown` into the inline-code sentinel encoding (``perk.plan``'s dual-encoding
engine parses both forms), and every incoming ``marker`` argument is transcoded the same way so
marker-keyed comment upserts stay idempotent end-to-end. The round-trip fidelity is verified
live at the smoke gate.

**Identifier boundary ids.** Boundary issue ids are the human Linear identifier
(``ENG-123``), not the UUID: plan worktrees become ``plan-ENG-123`` (exploiting Linear's
branch-name auto-link when the GitHub integration is installed), and every envelope/prompt
renders readably. Reads pass identifiers natively (``issue(id:)`` accepts the identifier
interchangeably with the UUID); the verified **mutations** (``issueUpdate``/``commentCreate``)
also take the boundary identifier directly (live-verified at the Mode 2 smoke gate, 2026-06-15 —
no identifier→UUID resolution layer remains). ``issueRelationCreate`` (objective blocking
relations) is UUID-only — it receives the issue UUID captured from the ``issueCreate`` response at
issue-create time. Comment ids remain UUIDs (comments have no identifier). Envelope issue ids are
always-string at every ``--json`` boundary (contracts §8.21).

Explicit deferrals (flagged, not silently omitted):

- **Live round-trip fidelity** — recorded at the live smoke gate.
- **Not-found discrimination** — *implemented* (2026-06-15 observation): the three
  not-found sites pair ``INPUT_ERROR in exc.codes`` with the ``"Entity not found"`` message
  prefix (``_is_entity_not_found``). The gate-8 row recorded ``INPUT_ERROR`` as a *generic*
  input-error code, so a ``.codes``-only tightening would have been too broad — hence the
  pairing.
- **Rate-limit retry/backoff** — *decided fail-loud*: no RATELIMITED tripped at the
  smoke gate (gate-9, "not tripped at low volume"), so there is no observed behavior to justify
  backoff. The client keeps raising the typed ``LinearGraphQLError``; retry/backoff stays
  deferred until a live RATELIMITED is observed.

**Package layout.** The module is decomposed into a package along its natural seams, following the
``perk/github`` precedent. This ``__init__`` re-exports every public symbol plus the
test-reached privates behind a sorted ``__all__``, preserving the ``linear_backend.X``
attribute-access import path verbatim (zero consumer/test import churn). Submodules:

- ``_helpers`` — shared leaf: the payload/markdown helpers + module constants.
- ``issue_ops`` / ``project_ops`` — the ``_LinearIssueOps`` / ``_LinearProjectOps`` substrates.
- ``backend`` — ``LinearIssueBackend`` (the issue tier).
- ``dream_report`` — ``publish_dream_artifact`` (the dream-artifact upload + Resources link).
- ``objectives`` — ``LinearObjectiveStore`` (issue-backed, dormant).
- ``project_store`` — ``LinearProjectObjectiveStore`` (project-backed).
- ``readiness`` — the init/doctor readiness probes.
"""

from perk.backends.linear._helpers import (
    _NODE_STATUS_STATE_TYPE,
    _note,
    to_linear_markdown,
)
from perk.backends.linear.backend import LinearIssueBackend
from perk.backends.linear.dream_report import publish_dream_artifact
from perk.backends.linear.issue_ops import _LinearIssueOps
from perk.backends.linear.objectives import LinearObjectiveStore
from perk.backends.linear.project_ops import _LinearProjectOps
from perk.backends.linear.project_store import LinearProjectObjectiveStore
from perk.backends.linear.readiness import (
    _REQUIRED_STATE_TYPES,
    LinearProjectReadiness,
    LinearReadiness,
    check_project_readiness,
    check_readiness,
)

__all__ = [
    "_NODE_STATUS_STATE_TYPE",
    "_REQUIRED_STATE_TYPES",
    "LinearIssueBackend",
    "LinearObjectiveStore",
    "LinearProjectObjectiveStore",
    "LinearProjectReadiness",
    "LinearReadiness",
    "_LinearIssueOps",
    "_LinearProjectOps",
    "_note",
    "check_project_readiness",
    "check_readiness",
    "publish_dream_artifact",
    "to_linear_markdown",
]
