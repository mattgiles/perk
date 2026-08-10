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

Import direction: this is gateway tier (PR-forge surface) — nothing here imports the backend
tier or the delivery module under ``perk/delivery/`` (its wiring leaf imports *this*).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field

from perk.boundary import LenientParseModel, translate_validation_errors
from perk.github import _exec
from perk.github._exec import GitHubError

# Schema introspection: does this GitHub host's `PullRequest` type expose the native-stack
# `stack` field? Presence proves the API SURFACE exists on the host — not per-repository
# preview enrollment (the real end-to-end proof is the dogfood gate).
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
