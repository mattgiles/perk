"""The repo-ref grammar (``perk/library/repo_ref.py``, contracts.md §8.75(i))."""

import pytest

from perk.library.errors import LibraryError
from perk.library.repo_ref import parse_repo_ref


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "pallets/click",
            ("github.com", "pallets", "click", "https://github.com/pallets/click.git"),
        ),
        (
            "github.com/pallets/click",
            ("github.com", "pallets", "click", "https://github.com/pallets/click.git"),
        ),
        (
            "https://github.com/pallets/click",
            ("github.com", "pallets", "click", "https://github.com/pallets/click.git"),
        ),
        (
            "https://github.com/pallets/click.git/",
            ("github.com", "pallets", "click", "https://github.com/pallets/click.git"),
        ),
        (
            "  http://gitea.local/org/repo  ",
            ("gitea.local", "org", "repo", "http://gitea.local/org/repo.git"),
        ),
        (
            "ssh://git@github.com/pallets/click.git",
            ("github.com", "pallets", "click", "ssh://git@github.com/pallets/click.git"),
        ),
        (
            "git@github.com:pallets/click.git",
            ("github.com", "pallets", "click", "git@github.com:pallets/click.git"),
        ),
        (
            "GitHub.com/Pallets/Click",
            ("github.com", "Pallets", "Click", "https://github.com/Pallets/Click.git"),
        ),
    ],
)
def test_accepted_shapes(text, expected):
    ref = parse_repo_ref(text)
    host, org, repo, _clone_url = expected
    assert (ref.host, ref.org, ref.repo, ref.clone_url) == expected
    assert ref.path == f"source-code/{host}/{org}/{repo}"
    assert ref.default_slug == repo.lower()


@pytest.mark.parametrize(
    "text",
    [
        "click",
        "https://github.com/pallets/click/tree/main",
        "https://github.com/pallets",
        "https://gitlab.com/g/sub/repo",
        "https://github.com/pallets/click?x=1",
        "https://github.com/pallets/click#readme",
        "https://user:token@github.com/pallets/click",
        "https://github.com:8443/pallets/click",
        "pallets/../click",
        "pallets/.click",
        "ftp://x/y/z",
        "https://[::1/org/repo",
        "org/repo@main",
        "a/b/c",
        "",
    ],
)
def test_refusals(text):
    with pytest.raises(LibraryError) as excinfo:
        parse_repo_ref(text)
    assert excinfo.value.error_type == "invalid_repo_ref"
    assert "git@<host>:<org>/<repo>" in str(excinfo.value)


def test_default_slug_lowercases_the_repo_name():
    assert parse_repo_ref("acme/My_Repo").default_slug == "my_repo"


def test_default_slug_outside_the_grammar_asks_for_slug():
    ref = parse_repo_ref(f"acme/{'r' * 65}")
    with pytest.raises(LibraryError) as excinfo:
        _ = ref.default_slug
    assert excinfo.value.error_type == "invalid_slug"
    assert "--slug" in str(excinfo.value)
