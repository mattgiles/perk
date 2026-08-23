"""`parse_plan_id` / `parse_objective_id` / `pr_number_from_url`: the shared, pure, offline
selector parsers.

Exercises bare-id passthrough (unchanged) and the additive URL-peeling: GitHub `.../issues/N`,
Linear `.../issue/IDENT`, Linear `.../project/SLUG` — plus the PR-URL peeler
(`pr_number_from_url`, GitHub/GHES `.../pull/N` only). The peeled id stays opaque — these tests
do no network and assert only the extracted value (or the `invalid_input` refusal).
"""

import pytest

from perk.cli.commands.objective.shared import parse_objective_id
from perk.cli.ensure import UserFacingCliError
from perk.cli.plan_selection import parse_plan_id, pr_number_from_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # GitHub issue URLs (+ trailing slash, query, fragment all peeled to the bare number).
        ("https://github.com/owner/repo/issues/888", "888"),
        ("https://github.com/owner/repo/issues/888/", "888"),
        ("https://github.com/owner/repo/issues/888?x=1", "888"),
        ("https://github.com/owner/repo/issues/888#frag", "888"),
        # GHES-style host — keyed on the /issues/<N> path shape, not the host string.
        ("https://github.acme.com/o/r/issues/12", "12"),
        # Linear issue + project URLs.
        ("https://linear.app/acme/issue/SAV-888/some-title", "SAV-888"),
        ("https://linear.app/acme/project/my-objective-3f8a2b1c/overview", "my-objective-3f8a2b1c"),
        # Bare ids are byte-for-byte unchanged (no http(s) scheme → never enters the URL branch).
        ("888", "888"),
        ("#888", "888"),
        ("SAV-888", "SAV-888"),
    ],
)
def test_parse_plan_id_accepts(raw: str, expected: str) -> None:
    assert parse_plan_id(raw) == expected


def test_github_pull_url_rejected() -> None:
    # The pure parser stays PR-unaware: a /pull/N URL is a different object than the
    # plan-issue. The PR-aware layer is `select_plan` (pr_number_from_url + the digits
    # fallback), never the parser — direct parse_plan_id callers keep rejecting it.
    with pytest.raises(UserFacingCliError) as exc:
        parse_plan_id("https://github.com/owner/repo/pull/888")
    assert exc.value.error_type == "invalid_input"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # GitHub PR URLs (+ trailing slash, query, fragment all peeled to the number).
        ("https://github.com/owner/repo/pull/888", 888),
        ("https://github.com/owner/repo/pull/888/", 888),
        ("https://github.com/owner/repo/pull/888?x=1", 888),
        ("https://github.com/owner/repo/pull/888#frag", 888),
        # GHES-style host — keyed on the /pull/<N> path shape, not the host string.
        ("https://github.acme.com/o/r/pull/12", 12),
        # The match anchors to the TERMINAL /pull/<N> route: a stray `pull` segment earlier
        # in the path can never resolve a different number than the one the user sees…
        ("https://github.com/pull/123/pull/888", 888),
        # …and subpage URLs / non-terminal shapes are not PR selectors.
        ("https://github.com/o/r/pull/888/files", None),
        ("https://github.com/pull/123/issues/5", None),
        # PR numbers are ASCII digits only: `²`.isdigit() is True but int("²") raises — the
        # peeler must refuse, never crash.
        ("https://github.com/o/r/pull/²", None),
        # Issue URLs, bare digits, and non-URLs are not PR selectors.
        ("https://github.com/owner/repo/issues/888", None),
        ("888", None),
        ("#888", None),
        ("not a url", None),
        # Linear hosts never carry PR objects (the PR always lives on GitHub).
        ("https://linear.app/acme/pull/9", None),
        ("https://acme.linear.app/pull/9", None),
    ],
)
def test_pr_number_from_url(raw: str, expected: int | None) -> None:
    assert pr_number_from_url(raw) == expected


def test_bad_id_rejected() -> None:
    # Regression guard: a path-unsafe bare id still raises (unchanged behavior).
    with pytest.raises(UserFacingCliError) as exc:
        parse_plan_id("bad/id")
    assert exc.value.error_type == "invalid_input"


def test_unrecognized_url_rejected_with_url_message() -> None:
    with pytest.raises(UserFacingCliError) as exc:
        parse_plan_id("https://example.com/foo")
    assert exc.value.error_type == "invalid_input"
    assert "Could not extract a plan id from URL" in exc.value.format_message()


def test_parse_objective_id_delegates_with_objective_wording() -> None:
    # The thin alias peels a URL identically and carries `what="objective"` into the error wording.
    assert parse_objective_id("https://github.com/o/r/issues/7") == "7"
    with pytest.raises(UserFacingCliError) as exc:
        parse_objective_id("https://example.com/foo")
    assert "Could not extract a objective id from URL" in exc.value.format_message()
