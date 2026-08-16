"""Private capability-row formatters plus the retained sync atomic-push helper.

Authoring Prepare owns authority invocation and ordering in :mod:`perk.delivery.facade`; this
module owns only the stable, pure capability-row prose. The successful native-stack and every
atomic-push row retain their honesty caveats: schema presence does not prove per-repository
preview enrollment, and an atomic dry-run proves transport capability/authentication rather than
branch write permission.

``probe_atomic_push_urls`` remains public temporarily for the deferred sync-family migration. It
uses the same private atomic-push formatter as authoring Prepare and preserves its existing
real-transport behavior.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from perk.substrate import git as git_mod

_PUSH_CAVEAT = "(proves server capability and authentication, not branch write permission)"


@dataclass(frozen=True)
class _CapabilityCheck:
    """One internal capability observation with stable name, verdict, and detail."""

    name: str
    ok: bool
    detail: str


def _native_stack_check(available: bool) -> _CapabilityCheck:
    if available:
        detail = (
            "the GraphQL schema exposes PullRequest.stack on this GitHub host — the native-stack "
            "API surface exists (schema presence does not prove per-repository preview "
            "enrollment; the end-to-end dogfood does)"
        )
    else:
        detail = (
            "expected a PullRequest.stack field in the GraphQL schema; observed none (or "
            "introspection failed) — native stacks are unavailable on this GitHub host"
        )
    return _CapabilityCheck(name="native-stack", ok=available, detail=detail)


def _merge_rules_check(
    base: str,
    *,
    squash_allowed: bool | None = None,
    merge_queue_required: bool | None = None,
    error: str | None = None,
) -> _CapabilityCheck:
    if error is not None:
        return _CapabilityCheck(
            name="merge-rules",
            ok=False,
            detail=f"could not verify the merge rules for base {base!r} "
            f"(can't verify ⇒ don't promise): {error}",
        )
    if squash_allowed is None or merge_queue_required is None:
        raise ValueError("merge-rule facts are required when no error is present")
    squash = "allowed" if squash_allowed else "disallowed"
    queue = "required" if merge_queue_required else "not required"
    return _CapabilityCheck(
        name="merge-rules",
        ok=squash_allowed and not merge_queue_required,
        detail=f"base {base!r}: expected squash direct-merge allowed and no merge "
        f"queue; observed squash merge {squash}, merge queue {queue}",
    )


def _remote_base_check(
    base: str,
    *,
    sha: str | None = None,
    error: str | None = None,
) -> _CapabilityCheck:
    if error is not None:
        return _CapabilityCheck(
            name="remote-base",
            ok=False,
            detail=f"could not observe refs/heads/{base} on origin "
            f"(can't verify ⇒ don't promise): {error}",
        )
    if sha is None:
        return _CapabilityCheck(
            name="remote-base",
            ok=False,
            detail=f"expected refs/heads/{base} on origin; observed no such remote "
            "branch — a stacked train needs a real remote base to publish against",
        )
    return _CapabilityCheck(
        name="remote-base",
        ok=True,
        detail=f"observed refs/heads/{base} on origin at {sha}",
    )


def _push_urls_error_check(error: str) -> _CapabilityCheck:
    return _CapabilityCheck(
        name="atomic-push",
        ok=False,
        detail=f"could not resolve the push URLs for origin: {error}",
    )


def _empty_push_urls_check() -> _CapabilityCheck:
    return _CapabilityCheck(
        name="atomic-push",
        ok=False,
        detail="expected at least one configured push URL for origin; observed none",
    )


def _atomic_push_check(push_url: str, *, error: str | None = None) -> _CapabilityCheck:
    if error is not None:
        return _CapabilityCheck(
            name="atomic-push",
            ok=False,
            detail=f"the no-op --atomic --dry-run push to {push_url} failed "
            f"{_PUSH_CAVEAT}: {error}",
        )
    return _CapabilityCheck(
        name="atomic-push",
        ok=True,
        detail=f"the no-op --atomic --dry-run push to {push_url} succeeded {_PUSH_CAVEAT}",
    )


def _default_atomic_push(repo: Path, push_url: str, base_branch: str, base_sha: str) -> None:
    git_mod.probe_atomic_push(repo, push_url=push_url, base_branch=base_branch, base_sha=base_sha)


def probe_atomic_push_urls(
    repo_root: Path,
    *,
    ref_branch: str,
    ref_sha: str,
    push_urls_probe: Callable[[Path], list[str]] = git_mod.push_urls,
    atomic_push_probe: Callable[[Path, str, str, str], None] = _default_atomic_push,
    resolved_push_urls: list[str] | None = None,
) -> list[_CapabilityCheck]:
    """Run the retained sync-owned no-op probe against every configured push URL.

    ``ref_sha`` must be the observed remote head of ``ref_branch`` so each probe is a true
    no-op. Expected Git failures become private failed rows; unexpected errors propagate.
    """
    if resolved_push_urls is None:
        try:
            urls = push_urls_probe(repo_root)
        except git_mod.GitError as exc:
            return [_push_urls_error_check(str(exc))]
    else:
        urls = resolved_push_urls
    if not urls:
        return [_empty_push_urls_check()]

    checks: list[_CapabilityCheck] = []
    for url in urls:
        try:
            atomic_push_probe(repo_root, url, ref_branch, ref_sha)
        except git_mod.GitError as exc:
            checks.append(_atomic_push_check(url, error=str(exc)))
        else:
            checks.append(_atomic_push_check(url))
    return checks
