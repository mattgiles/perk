"""Private capability-row formatters shared by Prepare and synchronization.

Authoring Prepare and the sync engine own authority invocation and ordering; this module owns
only the stable, pure capability-row prose. The successful native-stack and every atomic-push row
retain their honesty caveats: schema presence does not prove per-repository preview enrollment,
and an atomic dry-run proves transport capability/authentication rather than branch write
permission.
"""

from dataclasses import dataclass

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
