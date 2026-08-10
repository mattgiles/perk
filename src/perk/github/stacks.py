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

Import direction: this is gateway tier (PR-forge surface) — nothing here imports the backend
tier or the delivery module under ``perk/delivery/`` (its wiring leaf imports *this*).
"""

import json
from collections.abc import Sequence
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
