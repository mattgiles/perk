"""Canonical CLI-level plan selection — the one selector seam every plan-selecting cold door
uses (neutral: under ``perk/cli/``, not inside a command group).

Owns the backend-agnostic id/URL parser (:func:`parse_plan_id`), the canonical one-read
selection (:func:`select_plan` → :class:`SelectedPlan`), the positive plan-kind guard
(:func:`require_plan_kind` — typed errors: ``invalid_input`` / ``plan_not_found`` /
``issue_kind_mismatch``), and the **two-roots rule**
(:func:`main_repo_root` / :func:`load_main_config`).

:func:`select_plan` also accepts the plan's **PR** — a pasted ``.../pull/N`` URL (the explicit
arm) or a bare number that only resolves as a PR (the digits fallback, tried once after a
typed ``plan_not_found``/``issue_kind_mismatch`` miss). The PR resolution is two-tiered:
the **probe tier** reads the PR (``github.get_pr``) and peels its ``plan-<id>`` head branch
as the *candidate* plan pointer (a probe-tier miss refuses typed on the explicit arm and
re-raises the original error verbatim on the fallback arm); the **selection tier** then runs
the normal canonical selection on the peeled id and requires the selected plan's own recorded
``plan-header.pr`` to **corroborate** the supplied PR number — the head branch is a naming
convention, never provenance, so a stray/fork ``plan-*`` branch can never route to the wrong
plan. The pure parser (:func:`parse_plan_id`) stays PR-unaware and offline.

Two roots:

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

from perk import github, plan
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


# The two typed misses the bare-number PR fallback may recover from — everything else
# (invalid_input, infra errors) is never re-probed.
_FALLBACK_RECOVERABLE = frozenset({"plan_not_found", "issue_kind_mismatch"})


def select_plan(main_root: Path, raw: str, *, what: str = "plan") -> SelectedPlan:
    """Resolve an explicit plan selector (id, pasted URL, or the plan's PR) against the issue
    backend — the canonical selection yielding matching ``PlanState``/``PlanRef``.

    Backend reads anchor to the **main root** (canonical-store selection must not fork inside a
    linked worktree). Positive plan identification: an existing issue with no plan-header
    refuses via :func:`require_plan_kind`. Raises typed ``UserFacingCliError``s
    (``invalid_input`` / ``plan_not_found`` / ``issue_kind_mismatch``); backend transport
    failures (``IssueBackendError``) propagate for the caller's own fail boundary.

    The selector ladder (see the module docstring): a ``/pull/N`` URL takes the explicit PR
    arm; a non-digit id selects directly; a digit id selects directly first and falls back to
    the PR arm exactly once on a fallback-recoverable typed miss (GitHub's shared
    issue/PR number space makes the plan-first ladder unambiguous).
    """
    explicit_pr = pr_number_from_url(raw)
    if explicit_pr is not None:
        return _select_plan_via_pr(main_root, explicit_pr, what=what)
    plan_id = parse_plan_id(raw, what=what)
    if not plan_id.isdigit():
        # Backend-native ids (e.g. Linear's ENG-123) are never PR numbers — no probe.
        return _select_plan_by_id(main_root, plan_id)
    try:
        return _select_plan_by_id(main_root, plan_id, narrate_miss=True)
    except UserFacingCliError as exc:
        if exc.error_type not in _FALLBACK_RECOVERABLE:
            raise
        return _select_plan_via_pr(main_root, int(plan_id), what=what, fallback_from=exc)


def _select_plan_by_id(
    main_root: Path, plan_id: str, *, narrate_miss: bool = False
) -> SelectedPlan:
    """The fallback-free canonical selection core: ONE backend read for an already-parsed id.

    ``narrate_miss`` is set only by :func:`select_plan`'s digit-fallback arm: the two
    fallback-recoverable typed misses then resolve the lookup step via ``warn`` **before**
    raising, so a caught-and-continued miss never leaves a dangling ``\u203a`` line. Default
    ``False`` keeps :func:`io_step`'s escaping-exception contract (the caller's fail boundary
    is the resolution). Infra errors (``IssueBackendError``) are untouched by the flag.
    """
    backend = resolve.resolve_issue_backend(main_root)
    # Narrate the backend lookup wait (stderr — the `--json` stdout payload stays clean).
    with io_step(f"looking up plan #{plan_id}") as s:
        state = backend.get_plan(issue_id=plan_id)
        try:
            if state is None:
                raise UserFacingCliError(
                    f"Plan issue #{plan_id} not found", error_type="plan_not_found"
                )
            # PR-carrier guard: GitHub's `gh issue view <PR#>` resolves a PR number to the PR
            # itself, so a bare PR number surfaces here as an issue-shaped record whose url
            # names a pull request. The url is the reliable discriminator — never
            # `has_plan_header` (a raw delimiter scan; a PR body embedding plan markdown could
            # scan header-positive) — making the bare-PR-number path deterministic.
            if pr_number_from_url(state.url) is not None:
                raise UserFacingCliError(
                    f"#{plan_id} is a pull request, not a plan issue",
                    error_type="issue_kind_mismatch",
                )
            require_plan_kind(state, plan_id, backend_id=backend.backend_id)
        except UserFacingCliError as exc:
            if narrate_miss and exc.error_type in _FALLBACK_RECOVERABLE:
                s.warn(exc.format_message().splitlines()[0])
            raise
        s.done(f"found plan #{plan_id}")
    ref = resume.reconstruct_plan_ref(state, provider=backend.backend_id)
    return SelectedPlan(plan_id=plan_id, state=state, ref=ref)


def _plan_id_from_head(head: str) -> str | None:
    """Peel a conforming ``plan-<id>`` PR head branch to its plan id.

    One rule covers every non-conforming shape (``None``): a missing ``plan-`` prefix, an
    empty peel, a peel the parser rejects (``plan-a/b``, ``plan-.`` — the parser's
    ``invalid_input`` never leaks), and any *normalizing* peel (``plan-#42`` would parse to
    ``42``) via the canonical round-trip ``plan-<parsed> == head``.
    """
    if not head.startswith("plan-"):
        return None
    peeled = head.removeprefix("plan-")
    try:
        parsed = parse_plan_id(peeled)
    except UserFacingCliError:
        return None
    if f"plan-{parsed}" != head:
        return None
    return parsed


def _select_plan_via_pr(
    main_root: Path,
    pr_number: int,
    *,
    what: str = "plan",
    fallback_from: UserFacingCliError | None = None,
) -> SelectedPlan:
    """Resolve a PR selector to its plan: probe the PR, peel the ``plan-<id>`` head, run the
    canonical selection on the peeled id, then corroborate against the plan's recorded PR.

    The explicit arm (``fallback_from=None``, a pasted ``/pull/N`` URL) and the bare-number
    fallback arm differ **only** in how probe-tier misses resolve: typed refusal vs re-raising
    the original error verbatim (the probe is best-effort — the original message, objective
    right-door hint included, survives untouched). Past the probe both arms behave
    identically: a selection-tier failure names the peeled plan (strictly more informative),
    and the corroboration gate is the positive PR→plan evidence — the plan-header ``pr``
    field, stamped on submit, must record the supplied PR number.
    """
    with io_step(f"resolving PR #{pr_number}") as s:
        # Probe tier — every miss resolves the step with `warn` first (a fallback re-raise is
        # caught-and-reported by the caller's fail boundary, never left dangling).
        try:
            # Module-attribute call (the adapter discipline): monkeypatched fakes stay bound.
            pr = github.get_pr(number=pr_number, repo_root=main_root)
        except github.GitHubError as exc:
            s.warn(f"could not read PR #{pr_number}")
            if fallback_from is not None:
                raise fallback_from from exc
            # Translate so the callers' existing `except IssueBackendError` boundaries keep
            # catching the probe's transport failures.
            raise issue_backend.IssueBackendError(str(exc)) from exc
        if pr is None:
            s.warn(f"PR #{pr_number} not found")
            if fallback_from is not None:
                raise fallback_from
            raise UserFacingCliError(f"PR #{pr_number} not found", error_type="plan_not_found")
        peeled_id = _plan_id_from_head(pr.head_ref)
        if peeled_id is None:
            s.warn(f"PR #{pr_number} head branch {pr.head_ref!r} is not a plan branch")
            if fallback_from is not None:
                raise fallback_from
            raise UserFacingCliError(
                f"PR #{pr_number} (head branch {pr.head_ref!r}) was not created from a perk "
                f"{what} — pass the {what} issue id.",
                error_type="issue_kind_mismatch",
            )
        s.done(f"PR #{pr_number} → plan #{peeled_id}")
    # Selection tier — both arms identical from here: the peeled plan's own failure propagates
    # as-is (it names the peeled plan), and the corroboration refusal is typed in both arms.
    selected = _select_plan_by_id(main_root, peeled_id)
    recorded = issue_backend.parse_plan_pr(selected.state.header.get("pr"))
    if recorded != pr_number:
        recorded_text = f"PR #{recorded}" if recorded is not None else "no PR"
        raise UserFacingCliError(
            f"PR #{pr_number}'s head branch names plan #{peeled_id}, but that plan records "
            f"{recorded_text} — pass the plan issue id.",
            error_type="issue_kind_mismatch",
        )
    return selected


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


def pr_number_from_url(raw: str) -> int | None:
    """Peel a GitHub/GHES ``.../pull/<digits>`` URL to its PR number — ``None`` otherwise.

    Pure and offline, keyed on the path shape exactly like :func:`_id_from_url`'s
    ``/issues/N`` arm (any non-Linear host; trailing slash/query/fragment tolerated).
    ``None`` for non-URLs, bare digits, issue URLs, and every ``linear.app`` host (Linear has
    no PR objects — the PR always lives on GitHub). Doubles as the **PR-carrier
    discriminator** for backend-returned state urls (see :func:`_select_plan_by_id`).
    """
    parts = urlsplit(raw.strip())
    if parts.scheme.lower() not in {"http", "https"}:
        return None
    host = parts.hostname or ""
    if host == "linear.app" or host.endswith(".linear.app"):
        return None
    segments = [s for s in parts.path.split("/") if s]
    for i, seg in enumerate(segments[:-1]):
        if seg == "pull" and segments[i + 1].isdigit():
            return int(segments[i + 1])
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
