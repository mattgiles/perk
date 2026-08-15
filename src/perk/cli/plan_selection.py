"""Canonical CLI-level plan selection — the one selector seam every plan-selecting cold door
uses (neutral: under ``perk/cli/``, not inside a command group).

Owns the backend-agnostic id/URL parser (:func:`parse_plan_id`), the canonical one-read
selection (:func:`select_plan` → :class:`SelectedPlan`), the positive plan-kind guard
(:func:`require_plan_kind` — typed errors: ``invalid_input`` / ``plan_not_found`` /
``issue_kind_mismatch``), and the **two-roots rule**
(:func:`main_repo_root` / :func:`load_main_config`):

- **invocation root** — ``require_repo(ctx)`` at the cwd. Used for worktree-local binding
  *reads* only: the no-argument cache fallback (``address``/``ready`` inside a plan worktree
  select that worktree's own plan).
- **main root** — ``git.main_worktree_root(invocation_root) or invocation_root``. Used for
  config loading, ``config.worktree_root`` resolution, backend/canonical reads, and **all
  selector writes**. An explicit-plan launch invoked from inside a linked worktree updates only
  the main-checkout selector; the linked worktree's durable binding is never written by
  selection (the plan-ref two-role clobber hazard).
"""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from perk import plan
from perk.backends import issue_backend, resolve
from perk.cli.ensure import UserFacingCliError
from perk.run import resume
from perk.substrate import git
from perk.substrate.config import Config, ConfigError, load_config
from perk.substrate.output import io_step

_LINEAR_IDENT = re.compile(r"^[A-Za-z0-9]+-\d+$")


def main_repo_root(invocation_root: Path) -> Path:
    """The **main checkout's** root, even when invoked from inside a linked worktree.

    The anchor for config loading, ``config.worktree_root`` resolution, backend/canonical
    reads, and selector writes — never for the no-argument cache fallback (which reads the
    invocation root's own binding).
    """
    return git.main_worktree_root(invocation_root) or invocation_root


def load_main_config(main_root: Path) -> Config:
    """Load config against the **main checkout's** root.

    A small local twin of ``PerkContext.config()``'s error translation — ``require_config`` is
    deliberately not used because it binds config to the *invocation* root, which would rebase
    a relative ``[worktree] root`` under a linked worktree.
    """
    try:
        return load_config(main_root)
    except tomllib.TOMLDecodeError as exc:
        raise UserFacingCliError(
            f".perk/config.toml is not valid TOML ({exc})\nFix it, then re-run."
        ) from exc
    except ConfigError as exc:
        raise UserFacingCliError(
            f".perk config invalid: {exc}\nFix it, then re-run (perk doctor pinpoints the field)."
        ) from exc


@dataclass(frozen=True)
class SelectedPlan:
    """One canonical plan selection: the parsed id, the single backend read it performed, and
    the reconstructed provider-agnostic ref every launch artifact consumes."""

    plan_id: str
    state: issue_backend.PlanState
    ref: plan.PlanRef


def require_plan_kind(state: issue_backend.PlanState, plan_id: str, *, backend_id: str) -> None:
    """Positive plan identification (contracts §8.1): refuse an existing issue with no
    plan-header. GitHub objective carriers name the right door.

    Presence-only kind evidence (``PlanState.has_plan_header``): an absent header means "not a
    plan" — refuse; a present-but-malformed header still identifies a plan (kind vs health are
    separate concerns). The right-door hint is GitHub-only: only there does the refused issue's
    id equal the objective id (a Linear metadata-sentinel issue refuses with the generic
    message; a Linear Project id never reaches this arm — ``get_plan`` returns ``None`` →
    ``plan_not_found``). A both-headers carrier still selects as a plan (doctor is the
    both-headers surface). Raises typed ``issue_kind_mismatch``.
    """
    if state.has_plan_header:
        return
    message = (
        f"Issue #{plan_id} is not a perk plan (it has no plan-header) — pass a saved plan's id."
    )
    if state.has_objective_header and backend_id == "github":
        message = (
            f"Issue #{plan_id} is a perk objective, not a plan — objectives are planned "
            f"node-by-node:\n  perk objective plan {plan_id}"
        )
    raise UserFacingCliError(message, error_type="issue_kind_mismatch")


def select_plan(main_root: Path, raw: str, *, what: str = "plan") -> SelectedPlan:
    """Resolve an explicit plan selector (id or pasted URL) against the issue backend — ONE
    canonical read yielding matching ``PlanState``/``PlanRef``.

    Backend reads anchor to the **main root** (canonical-store selection must not fork inside a
    linked worktree). Positive plan identification: an existing issue with no plan-header
    refuses via :func:`require_plan_kind`. Raises typed ``UserFacingCliError``s
    (``invalid_input`` / ``plan_not_found`` / ``issue_kind_mismatch``); backend transport
    failures (``IssueBackendError``) propagate for the caller's own fail boundary.
    """
    plan_id = parse_plan_id(raw, what=what)
    backend = resolve.resolve_issue_backend(main_root)
    # Narrate the backend lookup wait (stderr — the `--json` stdout payload stays clean). The
    # not-found and kind-mismatch raises escape the step (dangling + the error text below).
    with io_step(f"looking up plan #{plan_id}") as s:
        state = backend.get_plan(issue_id=plan_id)
        if state is None:
            raise UserFacingCliError(
                f"Plan issue #{plan_id} not found", error_type="plan_not_found"
            )
        require_plan_kind(state, plan_id, backend_id=backend.backend_id)
        s.done(f"found plan #{plan_id}")
    ref = resume.reconstruct_plan_ref(state, provider=backend.backend_id)
    return SelectedPlan(plan_id=plan_id, state=state, ref=ref)


def _id_from_url(raw: str) -> str | None:
    """Peel a recognized GitHub/Linear issue or objective URL down to its opaque id.

    Pure and offline — returns ``None`` when ``raw`` is not an http(s) URL we recognize, leaving
    the caller to treat it as a bare id (or reject it). The extracted token stays opaque: the
    backend remains the sole authority on whether it resolves.

    Recognized shapes:

    - Linear issue ``.../issue/IDENT/...`` → the ``IDENT`` segment (e.g. ``SAV-888``), verbatim.
    - Linear project ``.../project/SLUG/...`` → the ``SLUG`` segment (the project id), verbatim.
    - GitHub/GHES ``.../issues/N`` → the digits ``N``. A ``/pull/N`` URL is a different object
      than the plan-issue, so it is deliberately **not** matched (returns ``None``).
    """
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"}:
        return None
    segments = [s for s in parts.path.split("/") if s]
    host = parts.hostname or ""
    if host == "linear.app" or host.endswith(".linear.app"):
        for keyword, accept in (("issue", _LINEAR_IDENT.match), ("project", lambda _s: True)):
            for i, seg in enumerate(segments[:-1]):
                if seg == keyword and accept(segments[i + 1]):
                    return segments[i + 1]
        return None
    # GitHub / GHES (any other host): /issues/<digits>, keyed on the path shape (covers GHES too).
    for i, seg in enumerate(segments[:-1]):
        if seg == "issues" and segments[i + 1].isdigit():
            return segments[i + 1]
    return None


def parse_plan_id(plan: str, *, what: str = "plan") -> str:
    """Validate an opaque issue id — accept ``42``, ``#42``, a backend-native string id like
    Linear's ``ENG-123``, or the issue/objective **URL** it was pasted from.

    A pasted URL is peeled to its id first: GitHub ``.../issues/N``, Linear ``.../issue/IDENT``,
    or Linear ``.../project/SLUG`` (a ``/pull/N`` URL is rejected — it is a different object).

    Strips ``#``/whitespace; rejects empty ids and anything unusable as a ``plan-<id>`` worktree
    name (the ``launch.resolve_plan_worktree_name`` rule: no ``/``, never ``.``/``..``). The id
    is otherwise opaque — the issue backend is the authority on whether it resolves.
    """
    value = plan
    if urlsplit(plan.strip()).scheme.lower() in {"http", "https"}:
        extracted = _id_from_url(plan.strip())
        if extracted is None:
            raise UserFacingCliError(
                f"Could not extract a {what} id from URL {plan!r} — paste a GitHub issue URL "
                "(.../issues/N) or a Linear issue/project URL.",
                error_type="invalid_input",
            )
        value = extracted
    cleaned = value.strip().lstrip("#").strip()
    if not cleaned or "/" in cleaned or cleaned in (".", ".."):
        raise UserFacingCliError(
            f"Invalid {what} id {plan!r} — expected an issue id (e.g. 42 or ENG-123).",
            error_type="invalid_input",
        )
    return cleaned
