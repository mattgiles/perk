"""The GitHub-native stacked-PR read adapter (contracts.md §8.44).

The explicitly GitHub-native seam of the deep delivery module's read path: the two GraphQL reads
the ``DeliveryTrain`` projection needs, split by schema stability —

- :func:`pr_delivery_facts` reads the **stable** public schema (state / draft / base / head /
  head OID) and keeps the honest lookup convention (``None`` on a missing PR, ``GitHubError``
  on infra failure).
- :func:`pr_stack` reads the **public-preview** native-stack fields (``PullRequest.stack`` /
  ``stackEntry``) with the tolerant-read posture: any failure that is not a PR lookup miss
  degrades to ``StackObservation(available=False)`` — preview instability is localized here and
  surfaces as *information*, never as a command failure. A null ``stack`` with ``available=True``
  means the PR is genuinely not stacked.

The capability probes (contracts.md §8.45) live here too: :func:`stack_capability` (a GraphQL
schema-introspection read — fail closed) and :func:`base_merge_rules` (squash direct-merge +
merge-queue branch rules — strict reads, ``GitHubError`` on infra failure). The atomic-push
dry-run is Git-plane and lives in ``perk.substrate.git.probe_atomic_push``; the
recheck-at-mutation composition is the ``/submit`` publication node's concern, not this
module's.

The **write surface** (contracts.md §8.47) is REST: :func:`stack_for_pr` is the strict
mutation-adjacent authority read (deliberately unlike the tolerant GraphQL preview read
``pr_stack`` the status projection keeps — a mutation classifies real state from it, so junk
never degrades silently), and :func:`create_stack` / :func:`append_to_stack` are **total**
mutation attempts through :func:`_stack_mutation`: they capture the HTTP status line +
``Retry-After`` header via ``gh api --include`` and return a typed
:class:`StackMutationOutcome` instead of raising on non-2xx/network outcomes —
classification (exact-after / unchanged-before / drift) belongs to the publish operation.

The **landing write surface** (contracts.md §8.56) follows the same split:
:func:`submit_merge_async` and :func:`merge_pr_direct` are **total** mutation attempts (the
``--include`` status/Retry-After capture; even a spawn failure folds into the ambiguous
``status=None`` arm — the landing operation classifies), while :func:`merge_async_result`
and :func:`pr_merged_evidence` are **strict** reads (they decide whether a journal outcome
may be appended, so junk raises, never degrades).

Import direction: this is gateway tier (PR-forge surface) — nothing here imports the backend
tier or the delivery module under ``perk/delivery/`` (its wiring leaf imports *this*).
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from pydantic import AliasChoices, Field

from perk.boundary import LenientParseModel, translate_validation_errors
from perk.github import _exec
from perk.github._exec import GitHubError

# Schema introspection: does this GitHub host's `PullRequest` type expose the native-stack
# `stack` field? Presence proves the API SURFACE exists on the host — not per-repository
# preview enrollment (the end-to-end proof was the dogfood gate:
# docs/design/archive/stacked-publication-dogfood.md).
STACK_CAPABILITY_QUERY = """query {
  __type(name: "PullRequest") {
    fields {
      name
    }
  }
}"""

MERGE_RULES_QUERY = """query($owner: String!, $repo: String!) {
  repository(owner: $owner, name: $repo) {
    squashMergeAllowed
  }
}"""

PR_DELIVERY_FACTS_QUERY = """query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      number
      state
      isDraft
      baseRefName
      headRefName
      headRefOid
    }
  }
}"""

# The preview read is a SEPARATE query from the stable one, so a preview-schema rejection can
# never poison the stable facts. `entries(first: 100)` is exact for every legal perk train
# (2-100 layers); `hasNextPage` means the observed stack is bigger than any perk train can be,
# so it is reported truncated (never exact).
PR_STACK_QUERY = """query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      stackEntry {
        position
      }
      stack {
        number
        size
        entries(first: 100) {
          nodes {
            position
            pullRequest {
              number
            }
          }
          pageInfo {
            hasNextPage
          }
        }
      }
    }
  }
}"""


@dataclass(frozen=True)
class MergeRules:
    """The base branch's direct-merge posture (the §8.45 merge-rules capability read).

    ``squash_allowed`` is the repository's ``squashMergeAllowed`` setting; ``merge_queue_required``
    is True when any effective branch rule of type ``merge_queue`` applies to the base (a
    queue-required base cannot take the direct squash merges a stacked train needs).
    """

    squash_allowed: bool
    merge_queue_required: bool


@dataclass(frozen=True)
class PrDeliveryFacts:
    """One PR's stable delivery-relevant facts (GraphQL ``PullRequest``).

    ``state`` is GraphQL's ``OPEN | CLOSED | MERGED`` vocabulary; ``head_sha`` is ``headRefOid``
    (the observed head commit the checkpoint corroboration compares against).
    """

    number: int
    state: str
    is_draft: bool
    base_ref: str
    head_ref: str
    head_sha: str


@dataclass(frozen=True)
class StackEntryFacts:
    """One native-stack entry: its 1-based ``position`` and member PR number."""

    position: int
    pr_number: int


@dataclass(frozen=True)
class StackFacts:
    """An observed native stack: identity, declared size, and its entries sorted by position.

    ``truncated`` is True when the entries page reported more beyond the first 100 — a stack a
    perk train can never exactly equal.
    """

    number: int
    size: int
    entries: tuple[StackEntryFacts, ...]
    truncated: bool


@dataclass(frozen=True)
class StackObservation:
    """The tolerant preview-read result. ``available=False`` means the preview read failed
    (schema rejection / infra) — membership is unknowable, not absent. ``available=True`` with
    ``stack=None`` means the PR is genuinely not in a native stack."""

    available: bool
    stack: StackFacts | None = None


class _PrDeliveryFactsModel(LenientParseModel):
    """Parse of the stable PR node (camelCase keys) — every field REQUIRED, ``state``
    constrained to GraphQL's ``PullRequestState``. The stable schema is an authority the
    projection classifies real state from: a partial/malformed payload must raise a labelled
    ``GitHubError`` at the call site, never read as empty/false observations (deliberately
    stricter than ``prs.PullRequestModel``'s tolerant defaults)."""

    number: int
    state: Literal["OPEN", "CLOSED", "MERGED"]
    is_draft: bool = Field(validation_alias=AliasChoices("isDraft"))
    base_ref: str = Field(validation_alias=AliasChoices("baseRefName"))
    head_ref: str = Field(validation_alias=AliasChoices("headRefName"))
    head_sha: str = Field(validation_alias=AliasChoices("headRefOid"))

    def to_domain(self) -> PrDeliveryFacts:
        return PrDeliveryFacts(
            number=self.number,
            state=self.state,
            is_draft=self.is_draft,
            base_ref=self.base_ref,
            head_ref=self.head_ref,
            head_sha=self.head_sha,
        )


class _StackMemberModel(LenientParseModel):
    """A stack entry's ``pullRequest { number }`` selection."""

    number: int


class _StackEntryModel(LenientParseModel):
    """One ``PullRequestStackEntry`` node — position + member PR are both required (an entry
    missing either cannot be compared exactly, so it fails the strict-enough parse and the
    caller degrades)."""

    position: int
    pull_request: _StackMemberModel = Field(validation_alias=AliasChoices("pullRequest"))

    def to_domain(self) -> StackEntryFacts:
        return StackEntryFacts(position=self.position, pr_number=self.pull_request.number)


class _PageInfoModel(LenientParseModel):
    """``hasNextPage`` is REQUIRED: exactness relies on OBSERVED non-truncation — absent
    pagination evidence must degrade the read (``available=False``), never silently parse as
    "not truncated" and let a bigger-than-observed stack classify ``EXACT``."""

    has_next_page: bool = Field(validation_alias=AliasChoices("hasNextPage"))


class _StackEntriesModel(LenientParseModel):
    """Every selected field is required — the query asks for all of them, so absence is a
    malformed reply, and a malformed preview shape degrades (never partially parses)."""

    nodes: tuple[_StackEntryModel, ...]
    page_info: _PageInfoModel = Field(validation_alias=AliasChoices("pageInfo"))


class _StackModel(LenientParseModel):
    """The ``PullRequestStack`` selection (all selected fields required — see
    :class:`_StackEntriesModel`)."""

    number: int
    size: int
    entries: _StackEntriesModel

    def to_domain(self) -> StackFacts:
        return StackFacts(
            number=self.number,
            size=self.size,
            # Sorted by position in the converter: consumers compare bottom→top sequences.
            entries=tuple(
                sorted((e.to_domain() for e in self.entries.nodes), key=lambda e: e.position)
            ),
            truncated=self.entries.page_info.has_next_page,
        )


def _pr_node(payload: dict[str, object], *, what: str) -> dict[str, object]:
    """Walk ``payload.data.repository.pullRequest`` to the PR node; a missing/null node is a
    labelled ``GitHubError`` (a zero-exit GraphQL reply must carry the PR it was asked for)."""
    cur: dict[str, object] | None = payload
    for key in ("data", "repository", "pullRequest"):
        cur = _exec._opt_dict(cur.get(key)) if cur is not None else None
    if cur is None:
        raise GitHubError(f"unexpected graphql payload ({what}): no pullRequest node")
    return cur


def pr_delivery_facts(*, number: int, repo_root: Path) -> PrDeliveryFacts | None:
    """Read one PR's stable delivery facts. ``None`` when the PR does not exist; raises
    ``GitHubError`` on an infra failure or a malformed payload (the stable schema is an
    authority — junk never degrades silently)."""
    what = f"failed to read delivery facts for PR #{number}"
    owner, repo = _exec._owner_repo(repo_root)
    proc = _exec._graphql_proc(
        PR_DELIVERY_FACTS_QUERY,
        repo_root=repo_root,
        str_vars={"owner": owner, "repo": repo},
        int_vars={"number": number},
    )
    if proc.returncode != 0:
        if _exec._is_not_found(proc):
            return None
        raise _exec._failed(proc, what)
    payload = _exec._parse_json(proc, source=f"pr delivery facts (#{number})")
    if not isinstance(payload, dict):
        raise GitHubError(f"unexpected graphql payload ({what}): {payload!r}")
    node = _pr_node(payload, what=what)
    with translate_validation_errors(GitHubError, source=what):
        return _PrDeliveryFactsModel.model_validate(node).to_domain()


def pr_stack(*, number: int, repo_root: Path) -> StackObservation:
    """Read one PR's native-stack membership (the public-preview fields) — tolerant.

    Any failure that is not a PR lookup miss — a preview-schema rejection, an infra failure, a
    malformed payload — returns ``StackObservation(available=False)``: the projection reports
    membership *unknown* rather than failing status on preview instability. A PR lookup miss
    still raises ``GitHubError`` (the caller asked about a PR that does not exist — a stable
    fact, not preview noise).
    """
    try:
        owner, repo = _exec._owner_repo(repo_root)
        proc = _exec._graphql_proc(
            PR_STACK_QUERY,
            repo_root=repo_root,
            str_vars={"owner": owner, "repo": repo},
            int_vars={"number": number},
        )
    except GitHubError:
        return StackObservation(available=False)
    if proc.returncode != 0:
        if _exec._is_not_found(proc):
            raise _exec._failed(proc, f"failed to read native stack for PR #{number}")
        return StackObservation(available=False)
    try:
        payload = _exec._parse_json(proc, source=f"pr stack (#{number})")
        if not isinstance(payload, dict):
            raise GitHubError(f"unexpected pr stack payload: {payload!r}")
        node = _pr_node(payload, what=f"failed to read native stack for PR #{number}")
        raw_stack = _exec._opt_dict(node.get("stack"))
        if node.get("stack") is not None and raw_stack is None:
            raise GitHubError(f"unexpected pr stack payload: stack is {node.get('stack')!r}")
        if raw_stack is None:
            return StackObservation(available=True, stack=None)
        with translate_validation_errors(GitHubError, source=f"pr stack (#{number})"):
            stack = _StackModel.model_validate(raw_stack).to_domain()
        return StackObservation(available=True, stack=stack)
    except GitHubError:
        return StackObservation(available=False)


def stack_capability(repo_root: Path) -> bool:
    """Whether this GitHub host's GraphQL schema exposes the native-stack API surface
    (a ``stack`` field on ``PullRequest``) — the §8.45 native-stack capability probe.

    **Fail closed**: an introspection failure, a malformed payload, or a missing field all
    return ``False`` (can't verify ⇒ don't promise). Schema presence proves the API surface
    exists on this host, **not** per-repository preview enrollment.
    """
    try:
        proc = _exec._graphql_proc(STACK_CAPABILITY_QUERY, repo_root=repo_root)
        if proc.returncode != 0:
            return False
        payload = _exec._parse_json(proc, source="stack capability introspection")
    except GitHubError:
        return False
    if not isinstance(payload, dict):
        return False
    data = _exec._opt_dict(payload.get("data"))
    type_node = _exec._opt_dict(data.get("__type")) if data is not None else None
    if type_node is None:
        return False
    return any(field.get("name") == "stack" for field in _exec._dicts(type_node.get("fields")))


def base_merge_rules(repo_root: Path, base: str) -> MergeRules:
    """Read the base branch's direct-merge posture (the §8.45 merge-rules capability read).

    Two strict reads: (a) GraphQL ``repository { squashMergeAllowed }``; (b) REST
    ``GET repos/{owner}/{repo}/rules/branches/{base}`` — the **effective** branch rules,
    scanned for any rule of type ``merge_queue``. **Fail closed on read failure**: any infra
    failure or malformed payload raises ``GitHubError`` (the capability layer converts it into
    a failed check — can't verify ⇒ don't promise).
    """
    what = f"failed to read merge rules for base {base!r}"
    owner, repo = _exec._owner_repo(repo_root)
    proc = _exec._graphql_proc(
        MERGE_RULES_QUERY, repo_root=repo_root, str_vars={"owner": owner, "repo": repo}
    )
    if proc.returncode != 0:
        raise _exec._failed(proc, what)
    payload = _exec._parse_json(proc, source=f"merge rules ({base})")
    data = _exec._opt_dict(payload.get("data")) if isinstance(payload, dict) else None
    repository = _exec._opt_dict(data.get("repository")) if data is not None else None
    squash = repository.get("squashMergeAllowed") if repository is not None else None
    if not isinstance(squash, bool):
        raise GitHubError(f"unexpected graphql payload ({what}): squashMergeAllowed missing")
    rules = _exec._run_json(
        _exec._rest_args(f"repos/{{owner}}/{{repo}}/rules/branches/{base}", method="GET"),
        what=what,
        source=f"branch rules ({base})",
        cwd=repo_root,
    )
    # Strict shape validation (never `_exec._dicts`, whose tolerant normalization would read a
    # malformed payload as "no rules" and let the preflight promise what it could not verify):
    # the effective-rules payload must be a list of rule objects each carrying a string `type`.
    if not isinstance(rules, list):
        raise GitHubError(f"unexpected branch rules payload ({what}): {rules!r}")
    rule_types: list[str] = []
    for rule in rules:
        rule_type = rule.get("type") if isinstance(rule, dict) else None
        if not isinstance(rule_type, str):
            raise GitHubError(f"unexpected branch rules payload ({what}): rule {rule!r}")
        rule_types.append(rule_type)
    merge_queue = "merge_queue" in rule_types
    return MergeRules(squash_allowed=squash, merge_queue_required=merge_queue)


# ------------------------------------------------------- the landing-readiness read (§8.55)

# One strict per-PR readiness document (the recorded transport shape: per-PR strict paginated
# reads, not one batched aliased query — GitHub gives no cross-PR snapshot consistency and
# per-alias pagination is inexpressible). The scalars are repeated on every page ON PURPOSE:
# the scalar-coherence guard re-reads them each request so checks/threads from different
# commits are never combined into one PrLandFacts. A branch-protection-required check that
# never reported at all is invisible to the rollup read; GitHub's own aggregate
# (`mergeStateStatus: BLOCKED`) is the covering authority for that case.
PR_LAND_READINESS_QUERY = """query($owner: String!, $repo: String!, $number: Int!,
       $checksCursor: String, $threadsCursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      number
      state
      isDraft
      baseRefName
      headRefName
      headRefOid
      mergeable
      mergeStateStatus
      reviewDecision
      commits(last: 1) {
        nodes {
          commit {
            statusCheckRollup {
              state
              contexts(first: 100, after: $checksCursor) {
                nodes {
                  __typename
                  ... on CheckRun {
                    name
                    status
                    conclusion
                    isRequired(pullRequestNumber: $number)
                  }
                  ... on StatusContext {
                    context
                    state
                    isRequired(pullRequestNumber: $number)
                  }
                }
                pageInfo {
                  hasNextPage
                  endCursor
                }
              }
            }
          }
        }
      }
      reviewThreads(first: 100, after: $threadsCursor) {
        nodes {
          isResolved
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}"""

# At most 20 requests per PR (≥2,000 contexts/threads — beyond any legal train's plausible
# shape); exceeding the cap raises rather than looping on a pathological/cyclic connection.
_LAND_READ_REQUEST_CAP = 20

type CheckOutcome = Literal["passed", "failed", "pending"]

# CheckRun conclusion → outcome (COMPLETED runs only). A COMPLETED run with a NULL conclusion
# is a contradictory wire state and normalizes to pending — fail-closed, never passed.
_CHECK_RUN_PASSED = frozenset({"SUCCESS", "NEUTRAL", "SKIPPED"})


@dataclass(frozen=True)
class CheckFacts:
    """One check context, normalized: ``name`` (CheckRun ``name`` / StatusContext
    ``context``), whether the base's rules require it, and the tri-state ``outcome``."""

    name: str
    is_required: bool
    outcome: CheckOutcome


@dataclass(frozen=True)
class PrLandFacts:
    """One PR's fresh landing-readiness facts (contracts.md §8.55).

    ``review_decision`` is nullable — null positively means the base requires no review.
    ``rollup_state`` is ``None`` when the head commit carries no ``statusCheckRollup``
    (no checks at all — ``checks`` is empty then).
    """

    number: int
    state: str
    is_draft: bool
    base_ref: str
    head_ref: str
    head_sha: str
    mergeable: str
    merge_state_status: str
    review_decision: str | None
    rollup_state: str | None
    checks: tuple[CheckFacts, ...]
    unresolved_thread_count: int


class _PrLandScalarsModel(LenientParseModel):
    """The repeated per-page scalar parse (every field REQUIRED; ``reviewDecision`` is
    required-but-nullable). Exhaustive ``Literal`` vocabularies: an unknown wire value is a
    labelled ``GitHubError``, never a silently-classified observation."""

    number: int
    state: Literal["OPEN", "CLOSED", "MERGED"]
    is_draft: bool = Field(validation_alias=AliasChoices("isDraft"))
    base_ref: str = Field(validation_alias=AliasChoices("baseRefName"))
    head_ref: str = Field(validation_alias=AliasChoices("headRefName"))
    head_sha: str = Field(validation_alias=AliasChoices("headRefOid"))
    mergeable: Literal["MERGEABLE", "CONFLICTING", "UNKNOWN"]
    merge_state_status: Literal[
        "BEHIND", "BLOCKED", "CLEAN", "DIRTY", "DRAFT", "HAS_HOOKS", "UNKNOWN", "UNSTABLE"
    ] = Field(validation_alias=AliasChoices("mergeStateStatus"))
    review_decision: Literal["APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED"] | None = Field(
        validation_alias=AliasChoices("reviewDecision")
    )


class _CheckRunModel(LenientParseModel):
    """One ``CheckRun`` context. ``conclusion`` is required-but-nullable (only COMPLETED
    runs carry one)."""

    name: str
    status: Literal["REQUESTED", "QUEUED", "IN_PROGRESS", "COMPLETED", "WAITING", "PENDING"]
    conclusion: (
        Literal[
            "SUCCESS",
            "NEUTRAL",
            "SKIPPED",
            "FAILURE",
            "TIMED_OUT",
            "CANCELLED",
            "ACTION_REQUIRED",
            "STALE",
            "STARTUP_FAILURE",
        ]
        | None
    )
    is_required: bool = Field(validation_alias=AliasChoices("isRequired"))

    def to_domain(self) -> CheckFacts:
        outcome: CheckOutcome
        if self.status != "COMPLETED" or self.conclusion is None:
            # Not finished — or the contradictory COMPLETED-with-null-conclusion state,
            # which is fail-closed: never passed.
            outcome = "pending"
        elif self.conclusion in _CHECK_RUN_PASSED:
            outcome = "passed"
        else:
            outcome = "failed"
        return CheckFacts(name=self.name, is_required=self.is_required, outcome=outcome)


class _StatusContextModel(LenientParseModel):
    """One commit-status context (the legacy Status API surface)."""

    context: str
    state: Literal["SUCCESS", "ERROR", "FAILURE", "EXPECTED", "PENDING"]
    is_required: bool = Field(validation_alias=AliasChoices("isRequired"))

    def to_domain(self) -> CheckFacts:
        outcome: CheckOutcome
        if self.state == "SUCCESS":
            outcome = "passed"
        elif self.state in ("ERROR", "FAILURE"):
            outcome = "failed"
        else:  # EXPECTED | PENDING
            outcome = "pending"
        return CheckFacts(name=self.context, is_required=self.is_required, outcome=outcome)


class _CursorPageInfoModel(LenientParseModel):
    """Cursor pagination evidence — both fields REQUIRED (``endCursor`` nullable only for an
    empty/terminal page): absent evidence is a malformed reply, never "no more pages"."""

    has_next_page: bool = Field(validation_alias=AliasChoices("hasNextPage"))
    end_cursor: str | None = Field(validation_alias=AliasChoices("endCursor"))


class _ThreadNodeModel(LenientParseModel):
    is_resolved: bool = Field(validation_alias=AliasChoices("isResolved"))


@dataclass(frozen=True)
class _ConnectionPage:
    """One parsed connection page: its accumulated-value contribution + pagination facts."""

    checks: tuple[CheckFacts, ...]
    unresolved: int
    has_next_page: bool
    end_cursor: str | None


def _parse_check_node(node: dict[str, object], *, what: str) -> CheckFacts:
    """Dispatch one ``contexts`` node on ``__typename`` (an unknown typename is a labelled
    error — the strict read never guesses a shape)."""
    typename = node.get("__typename")
    with translate_validation_errors(GitHubError, source=what):
        if typename == "CheckRun":
            return _CheckRunModel.model_validate(node).to_domain()
        if typename == "StatusContext":
            return _StatusContextModel.model_validate(node).to_domain()
    raise GitHubError(f"unexpected graphql payload ({what}): check context {typename!r}")


def _parse_checks_page(
    pr_node: dict[str, object], *, what: str
) -> tuple[str | None, _ConnectionPage | None]:
    """The ``(rollup_state, checks page)`` of one reply. A null ``statusCheckRollup`` is the
    honest no-checks arm ``(None, None)``; an empty ``commits.nodes`` is malformed authority
    (a PR always has ≥1 commit) and raises. ``commits.nodes`` must be EXACTLY one dict —
    ``last: 1`` fixes the cardinality, and this read feeds mutation-adjacent classification,
    so a junk member or an extra element never tolerantly filters down to a usable node."""
    commits = _exec._opt_dict(pr_node.get("commits"))
    raw_commit_nodes = commits.get("nodes") if commits is not None else None
    if not isinstance(raw_commit_nodes, list):
        raise GitHubError(f"unexpected graphql payload ({what}): malformed commits.nodes")
    if not raw_commit_nodes:
        raise GitHubError(f"unexpected graphql payload ({what}): empty commits.nodes")
    if len(raw_commit_nodes) != 1:
        raise GitHubError(
            f"unexpected graphql payload ({what}): {len(raw_commit_nodes)} commits.nodes "
            "(expected exactly 1 from last: 1)"
        )
    commit_node = _exec._opt_dict(raw_commit_nodes[0])
    if commit_node is None:
        raise GitHubError(f"unexpected graphql payload ({what}): malformed commits.nodes")
    commit = _exec._opt_dict(commit_node.get("commit"))
    if commit is None or "statusCheckRollup" not in commit:
        raise GitHubError(f"unexpected graphql payload ({what}): malformed commit node")
    rollup = _exec._opt_dict(commit["statusCheckRollup"])
    if rollup is None:
        if commit["statusCheckRollup"] is None:
            return None, None  # explicitly null: the head commit carries no checks at all
        raise GitHubError(f"unexpected graphql payload ({what}): malformed commit node")
    raw_state = rollup.get("state")
    if not isinstance(raw_state, str) or raw_state not in (
        "SUCCESS",
        "ERROR",
        "FAILURE",
        "EXPECTED",
        "PENDING",
    ):
        raise GitHubError(f"unexpected graphql payload ({what}): rollup state {raw_state!r}")
    rollup_state = raw_state
    contexts = _exec._opt_dict(rollup.get("contexts"))
    if contexts is None:
        raise GitHubError(f"unexpected graphql payload ({what}): missing contexts connection")
    raw_nodes = contexts.get("nodes")
    if not isinstance(raw_nodes, list):
        raise GitHubError(f"unexpected graphql payload ({what}): malformed contexts nodes")
    nodes: list[CheckFacts] = []
    for raw in raw_nodes:
        node = _exec._opt_dict(raw)
        if node is None:
            raise GitHubError(f"unexpected graphql payload ({what}): malformed check context")
        nodes.append(_parse_check_node(node, what=what))
    with translate_validation_errors(GitHubError, source=what):
        page_info = _CursorPageInfoModel.model_validate(contexts.get("pageInfo"))
    return rollup_state, _ConnectionPage(
        checks=tuple(nodes),
        unresolved=0,
        has_next_page=page_info.has_next_page,
        end_cursor=page_info.end_cursor,
    )


def _parse_threads_page(pr_node: dict[str, object], *, what: str) -> _ConnectionPage:
    threads = _exec._opt_dict(pr_node.get("reviewThreads"))
    if threads is None:
        raise GitHubError(f"unexpected graphql payload ({what}): missing reviewThreads")
    raw_nodes = threads.get("nodes")
    if not isinstance(raw_nodes, list):
        raise GitHubError(f"unexpected graphql payload ({what}): malformed reviewThreads nodes")
    unresolved = 0
    with translate_validation_errors(GitHubError, source=what):
        for raw in raw_nodes:
            if not _ThreadNodeModel.model_validate(raw).is_resolved:
                unresolved += 1
        page_info = _CursorPageInfoModel.model_validate(threads.get("pageInfo"))
    return _ConnectionPage(
        checks=(),
        unresolved=unresolved,
        has_next_page=page_info.has_next_page,
        end_cursor=page_info.end_cursor,
    )


@dataclass
class _ConnectionState:
    """One connection's pagination state. Nodes accumulate only while unexhausted; an
    exhausted connection keeps its final cursor and its re-returned nodes are ignored."""

    name: str
    cursor: str | None = None
    exhausted: bool = False

    def advance(self, page: _ConnectionPage, *, what: str) -> None:
        if page.has_next_page:
            # Cursor-progress rule: a continuing connection must present a fresh cursor —
            # a null or repeated one would loop forever (cyclic/non-advancing pagination).
            if page.end_cursor is None or page.end_cursor == self.cursor:
                raise GitHubError(
                    f"{what}: non-advancing {self.name} pagination (cursor {page.end_cursor!r})"
                )
            self.cursor = page.end_cursor
        else:
            self.exhausted = True
            # Keep the final endCursor: further requests (for the other connection) re-ask
            # past the exhausted tail, minimizing re-returned (ignored) nodes.
            if page.end_cursor is not None:
                self.cursor = page.end_cursor


def pr_land_facts(*, number: int, repo_root: Path) -> PrLandFacts | None:
    """Read one PR's fresh landing-readiness facts (the §8.55 strict per-PR read).

    ``None`` when the PR does not exist; raises ``GitHubError`` on infra failure, a
    malformed/partial payload, an unknown wire value, non-advancing pagination, a breached
    request cap, or a scalar changing between pages (the coherence guard: checks/threads
    observed across different commits are never combined into one result).
    """
    what = f"failed to read landing readiness for PR #{number}"
    owner, repo = _exec._owner_repo(repo_root)
    checks: list[CheckFacts] = []
    unresolved = 0
    first_scalars: _PrLandScalarsModel | None = None
    first_rollup_state: str | None = None
    checks_state = _ConnectionState("check contexts")
    threads_state = _ConnectionState("review threads")
    for _request in range(_LAND_READ_REQUEST_CAP):
        str_vars = {"owner": owner, "repo": repo}
        if checks_state.cursor is not None:
            str_vars["checksCursor"] = checks_state.cursor
        if threads_state.cursor is not None:
            str_vars["threadsCursor"] = threads_state.cursor
        proc = _exec._graphql_proc(
            PR_LAND_READINESS_QUERY,
            repo_root=repo_root,
            str_vars=str_vars,
            int_vars={"number": number},
        )
        if proc.returncode != 0:
            if first_scalars is None and _exec._is_not_found(proc):
                return None
            raise _exec._failed(proc, what)
        payload = _exec._parse_json(proc, source=f"pr land facts (#{number})")
        if not isinstance(payload, dict):
            raise GitHubError(f"unexpected graphql payload ({what}): {payload!r}")
        pr_node = _pr_node(payload, what=what)
        with translate_validation_errors(GitHubError, source=what):
            scalars = _PrLandScalarsModel.model_validate(pr_node)
        if scalars.number != number:
            # Identity check: a zero-exit payload carrying a DIFFERENT PR node must never
            # become this PR's readiness evidence.
            raise GitHubError(f"{what}: payload carries PR #{scalars.number}, expected #{number}")
        rollup_state, checks_page = _parse_checks_page(pr_node, what=what)
        threads_page = _parse_threads_page(pr_node, what=what)
        if first_scalars is None:
            first_scalars = scalars
            first_rollup_state = rollup_state
            if checks_page is None:
                checks_state.exhausted = True  # null rollup: no checks at all
        elif scalars != first_scalars or rollup_state != first_rollup_state:
            raise GitHubError(f"{what}: PR changed during the readiness read")
        if not checks_state.exhausted and checks_page is not None:
            checks.extend(checks_page.checks)
            checks_state.advance(checks_page, what=what)
        if not threads_state.exhausted:
            unresolved += threads_page.unresolved
            threads_state.advance(threads_page, what=what)
        if checks_state.exhausted and threads_state.exhausted:
            return PrLandFacts(
                number=first_scalars.number,
                state=first_scalars.state,
                is_draft=first_scalars.is_draft,
                base_ref=first_scalars.base_ref,
                head_ref=first_scalars.head_ref,
                head_sha=first_scalars.head_sha,
                mergeable=first_scalars.mergeable,
                merge_state_status=first_scalars.merge_state_status,
                review_decision=first_scalars.review_decision,
                rollup_state=first_rollup_state,
                checks=tuple(checks),
                unresolved_thread_count=unresolved,
            )
    raise GitHubError(f"{what}: pagination exceeded {_LAND_READ_REQUEST_CAP} requests")


# ---------------------------------------------------------------- the REST write surface (§8.47)


@dataclass(frozen=True)
class StackRestEntry:
    """One member PR of a REST stack resource, bottom→top order preserved."""

    pr_number: int
    state: str
    draft: bool
    merged: bool
    head_ref: str
    head_sha: str


@dataclass(frozen=True)
class StackRestFacts:
    """An observed REST stack resource: identity plus its member PRs bottom→top.

    ``size`` is derived from ``entries`` (the REST resource carries no separate size field the
    publish classification would trust over the members it compares).
    """

    number: int
    size: int
    entries: tuple[StackRestEntry, ...]

    @property
    def member_numbers(self) -> tuple[int, ...]:
        """The member PR numbers bottom→top (the exact-membership comparison key)."""
        return tuple(entry.pr_number for entry in self.entries)


@dataclass(frozen=True)
class StackMutationOutcome:
    """The typed, **total** result of one stack mutation attempt.

    ``applied`` is True only for a 2xx reply whose body parsed as a stack resource (carried on
    ``stack``); a 2xx with an unparseable body returns ``applied=False`` with the 2xx
    ``status`` — the caller's refetch decides. ``status`` is ``None`` when no HTTP status was
    observable (the ambiguous network arm). ``retry_after_seconds`` is parsed from a
    ``Retry-After`` header on any status; ``rate_limited`` is a 429, or a 403 whose body/stderr
    mentions rate limiting. ``raw_detail`` is a bounded stderr/body excerpt for messages.
    """

    applied: bool
    status: int | None
    retry_after_seconds: int | None
    rate_limited: bool
    raw_detail: str
    stack: StackRestFacts | None = None


class _StackRestHeadModel(LenientParseModel):
    """A stack member's ``head {ref, sha}`` — both required (the exact-head selector)."""

    ref: str
    sha: str


class _StackRestPrModel(LenientParseModel):
    """One ``pull_requests[]`` member of a REST stack resource — strict-enough: identity,
    state, draft, ``merged_at`` (required but nullable — an OMITTED field is wire-shape
    drift, never silently "not merged"), and the head selector are all required (a member
    missing any cannot be classified exactly)."""

    number: int
    state: str
    draft: bool
    merged_at: str | None
    head: _StackRestHeadModel

    def to_domain(self) -> StackRestEntry:
        return StackRestEntry(
            pr_number=self.number,
            state=self.state,
            draft=self.draft,
            merged=self.merged_at is not None,
            head_ref=self.head.ref,
            head_sha=self.head.sha,
        )


class _StackRestModel(LenientParseModel):
    """The REST stack resource — ``pull_requests`` order is bottom→top and is preserved."""

    number: int
    pull_requests: tuple[_StackRestPrModel, ...]

    def to_domain(self) -> StackRestFacts:
        entries = tuple(pr.to_domain() for pr in self.pull_requests)
        return StackRestFacts(number=self.number, size=len(entries), entries=entries)


def stack_for_pr(*, number: int, repo_root: Path) -> StackRestFacts | None:
    """The **strict** REST authority read: the stack containing PR ``number``, or ``None``
    when the PR belongs to no stack (an empty array is an ordinary observation).

    A 404 (stacked PRs unavailable for the repo), an infra failure, or a malformed payload
    raises ``GitHubError`` — this read feeds mutation classification, so junk never degrades
    silently (deliberately unlike the tolerant preview read :func:`pr_stack`).
    """
    what = f"failed to read the native stack for PR #{number}"
    # No empty-stdout default: only a literal `[]` payload means "in no stack" — a
    # successful process with empty output is a malformed authority reply and must raise
    # (this read feeds mutation classification; fail closed).
    payload = _exec._run_json(
        _exec._rest_args(
            "repos/{owner}/{repo}/stacks",
            method="GET",
            fields={"pull_request": str(number)},
        ),
        what=what,
        source=f"stacks?pull_request={number}",
        cwd=repo_root,
    )
    if not isinstance(payload, list):
        raise GitHubError(f"unexpected stacks payload ({what}): {payload!r}")
    if not payload:
        return None
    if len(payload) > 1:
        raise GitHubError(f"unexpected stacks payload ({what}): PR #{number} is in >1 stack")
    with translate_validation_errors(GitHubError, source=what):
        return _StackRestModel.model_validate(payload[0]).to_domain()


def create_stack(*, pull_requests: Sequence[int], repo_root: Path) -> StackMutationOutcome:
    """Create a native stack from ``pull_requests`` (bottom→top; each PR's base must match the
    previous PR's head ref). Total — see :func:`_stack_mutation`."""
    return _stack_mutation(
        "repos/{owner}/{repo}/stacks",
        pull_requests=pull_requests,
        what="create native stack",
        repo_root=repo_root,
    )


def append_to_stack(
    *, stack_number: int, pull_requests: Sequence[int], repo_root: Path
) -> StackMutationOutcome:
    """Append ``pull_requests`` (the exact missing suffix, bottom→top) to stack
    ``stack_number``. Total — see :func:`_stack_mutation`."""
    return _stack_mutation(
        f"repos/{{owner}}/{{repo}}/stacks/{stack_number}/add",
        pull_requests=pull_requests,
        what=f"append to native stack #{stack_number}",
        repo_root=repo_root,
    )


# Bound the stderr/body excerpt carried on the outcome (message material, never a payload).
_DETAIL_CAP = 500


def _stack_mutation(
    endpoint: str, *, pull_requests: Sequence[int], what: str, repo_root: Path
) -> StackMutationOutcome:
    """One stack mutation POST through ``gh api --include`` (header capture is the point —
    NOT ``_run_json``): split the HTTP response head from the body, parse the status line and
    ``Retry-After``, and classify into a **total** :class:`StackMutationOutcome`.

    Never raises for non-2xx/network outcomes (classification belongs to the publish
    operation); even a spawn/timeout ``GitHubError`` from ``_run`` folds into the ambiguous
    ``status=None`` arm — the caller's refetch-and-classify decides.
    """
    body = json.dumps({"pull_requests": [int(n) for n in pull_requests]})
    with _exec._body_file(body) as body_path:
        args = ["api", endpoint, "-X", "POST", "--include", "--input", body_path]
        try:
            proc = _exec._run(args, cwd=repo_root, timeout=_exec._WRITE_TIMEOUT)
        except GitHubError as exc:
            return StackMutationOutcome(
                applied=False,
                status=None,
                retry_after_seconds=None,
                rate_limited=False,
                raw_detail=f"{what}: {exc}"[:_DETAIL_CAP],
            )
    status, headers, response_body = _split_http_response(proc.stdout)
    retry_after = _parse_retry_after(headers.get("retry-after"))
    haystack = (response_body + proc.stderr).lower()
    rate_limited = status == 429 or (status == 403 and "rate limit" in haystack)
    detail = (proc.stderr.strip() or response_body.strip())[:_DETAIL_CAP]
    if status is None or not (200 <= status < 300):
        return StackMutationOutcome(
            applied=False,
            status=status,
            retry_after_seconds=retry_after,
            rate_limited=rate_limited,
            raw_detail=detail,
        )
    stack = _parse_stack_body(response_body)
    return StackMutationOutcome(
        applied=stack is not None,
        status=status,
        retry_after_seconds=retry_after,
        rate_limited=rate_limited,
        raw_detail=detail,
        stack=stack,
    )


def _split_http_response(stdout: str) -> tuple[int | None, dict[str, str], str]:
    """Split ``gh api --include`` stdout into (status, lower-cased headers, body).

    ``--include`` prints the response head (status line + headers) then the body; a redirect
    chain prints several head blocks, so the LAST ``HTTP/…`` status line wins. No status line
    at all → ``(None, {}, stdout)`` (the ambiguous arm — the process died before an HTTP
    status was observable).
    """
    lines = stdout.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("HTTP/")]
    if not starts:
        return None, {}, stdout
    start = starts[-1]
    parts = lines[start].split()
    status: int | None
    try:
        status = int(parts[1]) if len(parts) > 1 else None
    except ValueError:
        status = None
    headers: dict[str, str] = {}
    i = start + 1
    while i < len(lines) and lines[i].strip():
        key, _, value = lines[i].partition(":")
        headers[key.strip().lower()] = value.strip()
        i += 1
    return status, headers, "\n".join(lines[i + 1 :])


def _parse_retry_after(value: str | None) -> int | None:
    """The ``Retry-After`` seconds when the header carried a non-negative integer (the
    HTTP-date form is not honored — the caller's cap makes precision moot)."""
    if value is None:
        return None
    try:
        seconds = int(value.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def _parse_stack_body(body: str) -> StackRestFacts | None:
    """Parse a 2xx mutation reply's body as a stack resource; ``None`` when it does not parse
    (the caller returns ``applied=False`` with the 2xx status and lets the refetch decide —
    the helper stays total)."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        with translate_validation_errors(GitHubError, source="stack mutation reply"):
            return _StackRestModel.model_validate(payload).to_domain()
    except GitHubError:
        return None


# ---------------------------------------------------------------- the landing write surface (§8.56)

# The async stacked-PR merge body (public preview). perk sends EXACTLY these three fields — no
# `commit_title`/`commit_message` (GitHub's automatic per-PR squash messages stand; plan-issue
# closes are finalize's explicit job); `sha` is the documented head-pin (a non-matching PR head
# rejects the merge).
_MERGE_ASYNC_ACTION = "direct_merge"
_MERGE_ASYNC_METHOD = "squash"


@dataclass(frozen=True)
class MergeAsyncSubmitOutcome:
    """The typed, **total** result of one async-merge submission attempt.

    ``status`` is ``None`` when no HTTP status was observable (the ambiguous network arm).
    ``state`` is the parsed body ``status`` (``pending | merged | enqueued | failed``);
    ``None`` when the body did not parse — a 2xx/409 with an unparseable body classifies
    ambiguous (fail closed, never a guessed success). The ``details`` fields
    (``uuid``/``merge_method``/``merge_action``/``expected_head_sha``) are present on a
    ``pending`` reply and are the options the landing operation verifies against its request
    before recording the ``accepted`` handle.
    """

    status: int | None
    state: str | None
    uuid: str | None
    merge_method: str | None
    merge_action: str | None
    expected_head_sha: str | None
    retry_after_seconds: int | None
    rate_limited: bool
    raw_detail: str


def submit_merge_async(*, number: int, sha: str, repo_root: Path) -> MergeAsyncSubmitOutcome:
    """Submit the atomic async stack merge for the top PR (``PUT …/pulls/{n}/merge-async``).

    **Total**: never raises for non-2xx/network outcomes — even a spawn/timeout
    ``GitHubError`` folds into the ambiguous ``status=None`` arm; classification (the
    202/200/409/400/404/422 protocol) belongs to the landing operation.
    """
    what = f"submit async merge for PR #{number}"
    body = json.dumps(
        {"merge_action": _MERGE_ASYNC_ACTION, "merge_method": _MERGE_ASYNC_METHOD, "sha": sha}
    )
    with _exec._body_file(body) as body_path:
        args = [
            "api",
            f"repos/{{owner}}/{{repo}}/pulls/{number}/merge-async",
            "-X",
            "PUT",
            "--include",
            "--input",
            body_path,
        ]
        try:
            proc = _exec._run(args, cwd=repo_root, timeout=_exec._WRITE_TIMEOUT)
        except GitHubError as exc:
            return MergeAsyncSubmitOutcome(
                status=None,
                state=None,
                uuid=None,
                merge_method=None,
                merge_action=None,
                expected_head_sha=None,
                retry_after_seconds=None,
                rate_limited=False,
                raw_detail=f"{what}: {exc}"[:_DETAIL_CAP],
            )
    status, headers, response_body = _split_http_response(proc.stdout)
    retry_after = _parse_retry_after(headers.get("retry-after"))
    haystack = (response_body + proc.stderr).lower()
    rate_limited = status == 429 or (status == 403 and "rate limit" in haystack)
    detail = (proc.stderr.strip() or response_body.strip())[:_DETAIL_CAP]
    state, details = _parse_merge_async_body(response_body)
    return MergeAsyncSubmitOutcome(
        status=status,
        state=state,
        uuid=details.get("uuid"),
        merge_method=details.get("merge_method"),
        merge_action=details.get("merge_action"),
        expected_head_sha=details.get("expected_head_sha"),
        retry_after_seconds=retry_after,
        rate_limited=rate_limited,
        raw_detail=detail,
    )


def _parse_merge_async_body(body: str) -> tuple[str | None, dict[str, str]]:
    """Parse a merge-async reply body into ``(state, details)`` — total: anything that is not
    a JSON object carrying a string ``status`` yields ``(None, {})`` (the ambiguous arm)."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None, {}
    if not isinstance(payload, dict):
        return None, {}
    state = _exec._opt_str(payload.get("status"))
    if state is None:
        return None, {}
    raw_details = _exec._opt_dict(payload.get("details")) or {}
    details: dict[str, str] = {}
    for key in ("uuid", "merge_method", "merge_action", "expected_head_sha"):
        value = _exec._opt_str(raw_details.get(key))
        if value is not None:
            details[key] = value
    return state, details


# The poll's exhaustive state vocabulary: an unknown wire value raises, never classifies.
_MERGE_ASYNC_STATES = ("pending", "merged", "enqueued", "failed")


@dataclass(frozen=True)
class MergeAsyncResult:
    """One poll observation of a live async-merge handle. ``sha`` is the resulting merge
    commit (required on ``merged`` — enforced by the strict read); ``message`` is the
    reply's human detail (may be empty)."""

    state: Literal["pending", "merged", "enqueued", "failed"]
    sha: str | None
    message: str


def merge_async_result(*, number: int, uuid: str, repo_root: Path) -> MergeAsyncResult:
    """Poll the async-merge handle (``GET …/pulls/{n}/merge-async/{uuid}``) — **strict**.

    Raises ``GitHubError`` on infra failure, a malformed payload, an unknown ``status``
    value, a ``merged`` status missing ``details.sha``, or a 404 (an expired/unknown
    handle) — the landing operation's poll loop tolerates per-tick failures.
    """
    what = f"poll async merge {uuid} for PR #{number}"
    payload = _exec._run_json(
        _exec._rest_args(
            f"repos/{{owner}}/{{repo}}/pulls/{number}/merge-async/{uuid}", method="GET"
        ),
        what=what,
        source=f"merge-async result (#{number})",
        cwd=repo_root,
    )
    if not isinstance(payload, dict):
        raise GitHubError(f"unexpected merge-async payload ({what}): {payload!r}")
    state = payload.get("status")
    if not isinstance(state, str) or state not in _MERGE_ASYNC_STATES:
        raise GitHubError(f"unexpected merge-async payload ({what}): status {state!r}")
    details = _exec._opt_dict(payload.get("details")) or {}
    sha = _exec._opt_str(details.get("sha"))
    if state == "merged" and sha is None:
        raise GitHubError(f"unexpected merge-async payload ({what}): merged without details.sha")
    message = _exec._opt_str(details.get("message")) or ""
    return MergeAsyncResult(
        state=cast('Literal["pending", "merged", "enqueued", "failed"]', state),
        sha=sha,
        message=message,
    )


# The probe's total classification vocabulary: the four live wire states pass through;
# `expired` is the exact-404 arm (the handle is gone — the 24h merge-request lifetime);
# `unreadable` is every other failure (total: never raises, never guesses).
type MergeAsyncProbeState = Literal[
    "pending", "merged", "enqueued", "failed", "expired", "unreadable"
]


@dataclass(frozen=True)
class MergeAsyncProbe:
    """One **total** recovery observation of an async-merge handle (the recovery sibling of
    the strict :func:`merge_async_result` — recovery needs the 404-vs-transient distinction a
    raising read cannot express). ``sha`` is the merge commit on a well-formed ``merged``
    reply; ``message`` carries the reply's human detail / the failure text."""

    state: MergeAsyncProbeState
    sha: str | None
    message: str


def merge_async_probe(*, number: int, uuid: str, repo_root: Path) -> MergeAsyncProbe:
    """Probe the async-merge handle (``GET …/pulls/{n}/merge-async/{uuid}``) — **total**.

    Classification: the four live states pass through (``merged`` requires ``details.sha``);
    an exact HTTP 404 is ``expired`` (the handle is gone); any infra failure, malformed
    payload, unknown status, non-404 error reply, or merged-without-sha is ``unreadable``.
    Never raises — the recovery classification consumes every arm fail-closed.
    """
    what = f"probe async merge {uuid} for PR #{number}"
    args = [
        "api",
        f"repos/{{owner}}/{{repo}}/pulls/{number}/merge-async/{uuid}",
        "-X",
        "GET",
        "--include",
    ]
    try:
        proc = _exec._run(args, cwd=repo_root)
    except GitHubError as exc:
        return MergeAsyncProbe(state="unreadable", sha=None, message=f"{what}: {exc}"[:_DETAIL_CAP])
    status, _headers, response_body = _split_http_response(proc.stdout)
    detail = (proc.stderr.strip() or response_body.strip())[:_DETAIL_CAP]
    if status == 404:
        return MergeAsyncProbe(state="expired", sha=None, message=detail)
    if status is None or not (200 <= status < 300):
        return MergeAsyncProbe(
            state="unreadable", sha=None, message=f"{what}: HTTP {status}: {detail}"[:_DETAIL_CAP]
        )
    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict):
        return MergeAsyncProbe(
            state="unreadable",
            sha=None,
            message=f"{what}: unparseable reply body"[:_DETAIL_CAP],
        )
    state = payload.get("status")
    if not isinstance(state, str) or state not in _MERGE_ASYNC_STATES:
        return MergeAsyncProbe(
            state="unreadable",
            sha=None,
            message=f"{what}: unknown status {state!r}"[:_DETAIL_CAP],
        )
    details = _exec._opt_dict(payload.get("details")) or {}
    sha = _exec._opt_str(details.get("sha"))
    if state == "merged" and sha is None:
        return MergeAsyncProbe(
            state="unreadable",
            sha=None,
            message=f"{what}: merged without details.sha"[:_DETAIL_CAP],
        )
    message = _exec._opt_str(details.get("message")) or ""
    return MergeAsyncProbe(state=cast("MergeAsyncProbeState", state), sha=sha, message=message)


@dataclass(frozen=True)
class DirectMergeOutcome:
    """The typed, **total** result of one SHA-pinned legacy squash-merge attempt (the dynamic
    singleton's landing arm). ``merged`` is True for a 2xx reply whose body carried the merge
    ``sha``, or an "already merged" body/stderr (the idempotent race arm ``prs.merge_pr`` also
    honors); ``sha`` is the merge commit from the 200 body (``None`` on the already-merged
    arm — verification re-reads it)."""

    status: int | None
    merged: bool
    sha: str | None
    retry_after_seconds: int | None
    rate_limited: bool
    raw_detail: str


def merge_pr_direct(
    *, number: int, sha: str, commit_message: str | None, repo_root: Path
) -> DirectMergeOutcome:
    """The SHA-pinned legacy synchronous squash merge (``PUT …/pulls/{n}/merge``) — **total**
    (the same ``--include`` classification as :func:`submit_merge_async`). ``prs.merge_pr``
    is untouched — the incremental land keeps its own unpinned path."""
    what = f"direct squash merge for PR #{number}"
    payload: dict[str, object] = {"merge_method": "squash", "sha": sha}
    if commit_message is not None:
        payload["commit_message"] = commit_message
    with _exec._body_file(json.dumps(payload)) as body_path:
        args = [
            "api",
            f"repos/{{owner}}/{{repo}}/pulls/{number}/merge",
            "-X",
            "PUT",
            "--include",
            "--input",
            body_path,
        ]
        try:
            proc = _exec._run(args, cwd=repo_root, timeout=_exec._WRITE_TIMEOUT)
        except GitHubError as exc:
            return DirectMergeOutcome(
                status=None,
                merged=False,
                sha=None,
                retry_after_seconds=None,
                rate_limited=False,
                raw_detail=f"{what}: {exc}"[:_DETAIL_CAP],
            )
    status, headers, response_body = _split_http_response(proc.stdout)
    retry_after = _parse_retry_after(headers.get("retry-after"))
    haystack = (response_body + proc.stderr).lower()
    rate_limited = status == 429 or (status == 403 and "rate limit" in haystack)
    detail = (proc.stderr.strip() or response_body.strip())[:_DETAIL_CAP]
    merge_sha: str | None = None
    if status is not None and 200 <= status < 300:
        try:
            parsed = json.loads(response_body)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            merge_sha = _exec._opt_str(parsed.get("sha"))
    merged = merge_sha is not None or "already merged" in haystack
    return DirectMergeOutcome(
        status=status,
        merged=merged,
        sha=merge_sha,
        retry_after_seconds=retry_after,
        rate_limited=rate_limited,
        raw_detail=detail,
    )


PR_MERGED_EVIDENCE_QUERY = """query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      number
      state
      baseRefName
      headRefName
      headRefOid
      mergeCommit {
        oid
      }
    }
  }
}"""


@dataclass(frozen=True)
class PrMergedEvidence:
    """One PR's post-merge verification facts — identity included: ``base_ref`` /
    ``head_ref`` / ``head_sha`` let the landing operation corroborate that WHAT merged is
    the exact approved layer (head commit + branch + merge target), not merely that the PR
    number reads MERGED. ``merge_commit_sha`` is required-but-nullable — the landing
    operation fail-closes on a MERGED PR carrying a null merge commit."""

    number: int
    state: str
    base_ref: str
    head_ref: str
    head_sha: str
    merge_commit_sha: str | None


class _MergeCommitModel(LenientParseModel):
    oid: str


class _PrMergedEvidenceModel(LenientParseModel):
    """Strict parse of the merged-evidence node — every field REQUIRED; ``merge_commit`` is
    required-but-nullable (an OMITTED key is wire-shape drift, never silently "not
    merged")."""

    number: int
    state: Literal["OPEN", "CLOSED", "MERGED"]
    base_ref: str = Field(validation_alias=AliasChoices("baseRefName"))
    head_ref: str = Field(validation_alias=AliasChoices("headRefName"))
    head_sha: str = Field(validation_alias=AliasChoices("headRefOid"))
    merge_commit: _MergeCommitModel | None = Field(validation_alias=AliasChoices("mergeCommit"))

    def to_domain(self) -> PrMergedEvidence:
        return PrMergedEvidence(
            number=self.number,
            state=self.state,
            base_ref=self.base_ref,
            head_ref=self.head_ref,
            head_sha=self.head_sha,
            merge_commit_sha=None if self.merge_commit is None else self.merge_commit.oid,
        )


def pr_merged_evidence(*, number: int, repo_root: Path) -> PrMergedEvidence | None:
    """Read one PR's post-merge verification evidence (state + merge commit) — strict.

    ``None`` on a missing PR; raises ``GitHubError`` on infra failure or a malformed
    payload (this read decides whether a ``completed`` journal event may be appended —
    junk never degrades silently)."""
    what = f"failed to read merged evidence for PR #{number}"
    owner, repo = _exec._owner_repo(repo_root)
    proc = _exec._graphql_proc(
        PR_MERGED_EVIDENCE_QUERY,
        repo_root=repo_root,
        str_vars={"owner": owner, "repo": repo},
        int_vars={"number": number},
    )
    if proc.returncode != 0:
        if _exec._is_not_found(proc):
            return None
        raise _exec._failed(proc, what)
    payload = _exec._parse_json(proc, source=f"pr merged evidence (#{number})")
    if not isinstance(payload, dict):
        raise GitHubError(f"unexpected graphql payload ({what}): {payload!r}")
    # A zero-exit reply can also report the miss as an explicitly-null node (beside the
    # non-zero not-found arm) — honor the lookup convention for that wire shape too.
    data = _exec._opt_dict(payload.get("data"))
    repository = _exec._opt_dict(data.get("repository")) if data is not None else None
    if repository is not None and "pullRequest" in repository and repository["pullRequest"] is None:
        return None
    node = _pr_node(payload, what=what)
    with translate_validation_errors(GitHubError, source=what):
        return _PrMergedEvidenceModel.model_validate(node).to_domain()
