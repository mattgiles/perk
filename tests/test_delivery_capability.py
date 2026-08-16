"""Focused coverage for the private Prepare/sync capability row formatters."""

from perk.delivery import capability


def test_private_success_rows_retain_both_honesty_caveats() -> None:
    native = capability._native_stack_check(True)
    atomic = capability._atomic_push_check("https://gh/octo/repo.git")

    assert native.ok is True
    assert native.detail == (
        "the GraphQL schema exposes PullRequest.stack on this GitHub host — the native-stack "
        "API surface exists (schema presence does not prove per-repository preview enrollment; "
        "the end-to-end dogfood does)"
    )
    assert atomic.ok is True
    assert atomic.detail == (
        "the no-op --atomic --dry-run push to https://gh/octo/repo.git succeeded "
        "(proves server capability and authentication, not branch write permission)"
    )


def test_private_atomic_failure_row_retains_the_permission_caveat() -> None:
    failed = capability._atomic_push_check("https://gh/mirror.git", error="atomic unsupported")

    assert failed.ok is False
    assert failed.detail == (
        "the no-op --atomic --dry-run push to https://gh/mirror.git failed "
        "(proves server capability and authentication, not branch write permission): "
        "atomic unsupported"
    )


def test_private_push_url_error_row_preserves_the_observation_failure() -> None:
    failed = capability._push_urls_error_check("no remote")

    assert failed.ok is False
    assert failed.detail == "could not resolve the push URLs for origin: no remote"


def test_private_empty_push_url_row_is_a_failure() -> None:
    failed = capability._empty_push_urls_check()

    assert failed.ok is False
    assert failed.detail == "expected at least one configured push URL for origin; observed none"
