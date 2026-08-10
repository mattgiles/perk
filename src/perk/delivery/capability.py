"""The stacked-authoring capability preflight (contracts.md §8.45).

Composes the three §8.45 capability checks — native-stack availability, direct-merge/queue
rules, and the atomic-push dry-run — plus the remote-base-SHA observation the push probe
needs, into one honest :class:`CapabilityReport`. Every check's ``detail`` carries the
expected-vs-observed facts **and the probe's honesty caveats** (schema presence proves the API
surface, not per-repository enrollment; a passing push probe proves server capability and
authentication, not branch write permission).

The probe callables are keyword-injectable (production defaults over ``perk.github.stacks`` +
``perk.substrate.git``; tests pass fakes). Import direction stays §8.44's: this delivery-module
leaf imports the gateway/substrate one-directionally; nothing in ``perk/backends/`` or
``perk/github/`` imports it. Failures never escape: a probe's typed error (``GitHubError`` /
``GitError``) converts into a failed check, because the preflight's whole job is honest
capability feedback, not a crash.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from perk.github import GitHubError, stacks
from perk.substrate import git as git_mod

# The push probe proves the transport, never the permission — stated on success AND failure.
_PUSH_CAVEAT = "(proves server capability and authentication, not branch write permission)"


@dataclass(frozen=True)
class CapabilityCheck:
    """One capability observation: a stable ``name``, the verdict, and the honest
    expected-vs-observed ``detail``."""

    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class CapabilityReport:
    """The composed preflight outcome — ``ok`` iff every check passed."""

    checks: tuple[CapabilityCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def failures(self) -> tuple[CapabilityCheck, ...]:
        return tuple(check for check in self.checks if not check.ok)


def _default_atomic_push(repo: Path, push_url: str, base_branch: str, base_sha: str) -> None:
    git_mod.probe_atomic_push(repo, push_url=push_url, base_branch=base_branch, base_sha=base_sha)


def probe_atomic_push_urls(
    repo_root: Path,
    *,
    ref_branch: str,
    ref_sha: str,
    push_urls_probe: Callable[[Path], list[str]] = git_mod.push_urls,
    atomic_push_probe: Callable[[Path, str, str, str], None] = _default_atomic_push,
) -> list[CapabilityCheck]:
    """The per-push-URL atomic-push capability probe, shared by stacked authoring and sync.

    Enumerates origin's configured push URLs and runs the no-op ``--atomic --dry-run`` push
    probe per URL against the given refspec (``ref_sha`` must be the OBSERVED remote head of
    ``ref_branch`` so the probe is a true no-op). Returns one ``atomic-push``
    :class:`CapabilityCheck` per URL — all must pass — plus the two composition failures (an
    unresolvable push-URL config; zero configured URLs). Never raises: probe errors convert
    into failed checks (the preflight's whole job is honest capability feedback).
    """
    checks: list[CapabilityCheck] = []
    try:
        urls = push_urls_probe(repo_root)
    except git_mod.GitError as exc:
        return [
            CapabilityCheck(
                name="atomic-push",
                ok=False,
                detail=f"could not resolve the push URLs for origin: {exc}",
            )
        ]
    if not urls:
        return [
            CapabilityCheck(
                name="atomic-push",
                ok=False,
                detail="expected at least one configured push URL for origin; observed none",
            )
        ]
    for url in urls:
        try:
            atomic_push_probe(repo_root, url, ref_branch, ref_sha)
        except git_mod.GitError as exc:
            checks.append(
                CapabilityCheck(
                    name="atomic-push",
                    ok=False,
                    detail=f"the no-op --atomic --dry-run push to {url} failed "
                    f"{_PUSH_CAVEAT}: {exc}",
                )
            )
        else:
            checks.append(
                CapabilityCheck(
                    name="atomic-push",
                    ok=True,
                    detail=f"the no-op --atomic --dry-run push to {url} succeeded {_PUSH_CAVEAT}",
                )
            )
    return checks


def preflight_stacked_authoring(
    repo_root: Path,
    *,
    base: str,
    stack_probe: Callable[[Path], bool] = stacks.stack_capability,
    merge_rules_probe: Callable[[Path, str], stacks.MergeRules] = stacks.base_merge_rules,
    remote_head_probe: Callable[[Path, str], str | None] = git_mod.remote_branch_head,
    push_urls_probe: Callable[[Path], list[str]] = git_mod.push_urls,
    atomic_push_probe: Callable[[Path, str, str, str], None] = _default_atomic_push,
) -> CapabilityReport:
    """Run the §8.45 stacked-authoring capability preflight against ``base``.

    Check order (each independent — a failure never hides the later observations, except the
    push probes, which need the remote base SHA to run at all):

    1. ``native-stack`` — schema introspection (fail closed in the probe itself).
    2. ``merge-rules`` — squash direct-merge allowed AND no merge-queue rule on ``base``.
    3. ``remote-base`` — the observed ``refs/heads/<base>`` SHA on origin (an absent remote
       base branch is a capability failure, not a crash).
    4. ``atomic-push`` — one no-op ``--atomic --dry-run`` push per configured push URL; **all
       must pass** (skipped when the remote base SHA is unknowable).
    """
    checks: list[CapabilityCheck] = []

    available = stack_probe(repo_root)
    if available:
        stack_detail = (
            "the GraphQL schema exposes PullRequest.stack on this GitHub host — the native-stack "
            "API surface exists (schema presence does not prove per-repository preview "
            "enrollment; the end-to-end dogfood does)"
        )
    else:
        stack_detail = (
            "expected a PullRequest.stack field in the GraphQL schema; observed none (or "
            "introspection failed) — native stacks are unavailable on this GitHub host"
        )
    checks.append(CapabilityCheck(name="native-stack", ok=available, detail=stack_detail))

    try:
        rules = merge_rules_probe(repo_root, base)
    except GitHubError as exc:
        checks.append(
            CapabilityCheck(
                name="merge-rules",
                ok=False,
                detail=f"could not verify the merge rules for base {base!r} "
                f"(can't verify ⇒ don't promise): {exc}",
            )
        )
    else:
        squash = "allowed" if rules.squash_allowed else "disallowed"
        queue = "required" if rules.merge_queue_required else "not required"
        checks.append(
            CapabilityCheck(
                name="merge-rules",
                ok=rules.squash_allowed and not rules.merge_queue_required,
                detail=f"base {base!r}: expected squash direct-merge allowed and no merge "
                f"queue; observed squash merge {squash}, merge queue {queue}",
            )
        )

    base_sha: str | None
    try:
        base_sha = remote_head_probe(repo_root, base)
    except git_mod.GitError as exc:
        base_sha = None
        checks.append(
            CapabilityCheck(
                name="remote-base",
                ok=False,
                detail=f"could not observe refs/heads/{base} on origin "
                f"(can't verify ⇒ don't promise): {exc}",
            )
        )
    else:
        if base_sha is None:
            checks.append(
                CapabilityCheck(
                    name="remote-base",
                    ok=False,
                    detail=f"expected refs/heads/{base} on origin; observed no such remote "
                    "branch — a stacked train needs a real remote base to publish against",
                )
            )
        else:
            checks.append(
                CapabilityCheck(
                    name="remote-base",
                    ok=True,
                    detail=f"observed refs/heads/{base} on origin at {base_sha}",
                )
            )

    if base_sha is not None:
        checks.extend(
            probe_atomic_push_urls(
                repo_root,
                ref_branch=base,
                ref_sha=base_sha,
                push_urls_probe=push_urls_probe,
                atomic_push_probe=atomic_push_probe,
            )
        )

    return CapabilityReport(checks=tuple(checks))
