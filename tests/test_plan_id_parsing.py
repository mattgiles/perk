"""`parse_plan_id` / `parse_objective_id`: the single shared, pure, offline id parser.

Exercises bare-id passthrough (unchanged) and the additive URL-peeling: GitHub `.../issues/N`,
Linear `.../issue/IDENT`, Linear `.../project/SLUG`. The peeled id stays opaque — these tests do
no network and assert only the extracted string (or the `invalid_input` refusal).
"""

import pytest

from perk.cli.commands.objective.shared import parse_objective_id
from perk.cli.ensure import UserFacingCliError
from perk.cli.plan_selection import parse_plan_id


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
    # A /pull/N URL is a different object than the plan-issue — deliberately not matched.
    with pytest.raises(UserFacingCliError) as exc:
        parse_plan_id("https://github.com/owner/repo/pull/888")
    assert exc.value.error_type == "invalid_input"


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
