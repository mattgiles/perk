"""The release-notes feature: the lenient display parser/renderer + `perk release-notes`.

Parser tests exercise fixture literals plus the real repo changelog (a generic baseline guard —
no version literals that rot). CLI tests run against the registered root `cli` with the two
monkeypatch seams (`changelog_path`, `_cli_version`); notes land on stderr, failures are always
`UserFacingCliError` (exit 1, never a traceback).
"""

import re

from click.testing import CliRunner

from perk._resources import changelog_path
from perk.cli.cli import cli
from perk.cli.commands import release_notes_cmd as rn_cmd
from perk.release_notes import (
    Entry,
    find_release,
    parse_release_notes,
    render_release,
    render_releases,
)

SAMPLE = """\
# Changelog

Intro prose in the file preamble (before any release header — skipped).

## [Unreleased]

<!-- As of abc1234 -->

### Added

- pending thing

## [2.0.0] - 2026-05-01

Release preamble line.

### Added

- top-level bullet
  - nested level one
    - nested level two
- multi-line bullet start
  continues here and
  ends here

### Changed

### Weird Category

- weird entry

## [1.2.3] - 2026-01-15

### Fixed

- a fix

See docs for details.
"""

MALFORMED = """\
## [1.0] - x

- content under a malformed header is skipped

## just words

stray text under an unknown header

## [3.0.0] - 2026-02-02

   - odd indent bullet
"""


# --- parser ---------------------------------------------------------------


def test_release_headers_and_dates_in_file_order():
    releases = parse_release_notes(SAMPLE)
    assert [(r.version, r.date) for r in releases] == [
        ("2.0.0", "2026-05-01"),
        ("1.2.3", "2026-01-15"),
    ]


def test_unreleased_skipped_by_default():
    releases = parse_release_notes(SAMPLE)
    assert all(r.version != "Unreleased" for r in releases)


def test_unreleased_included_on_request_first_with_no_date():
    releases = parse_release_notes(SAMPLE, include_unreleased=True)
    assert releases[0].version == "Unreleased"
    assert releases[0].date is None
    assert [c.name for c in releases[0].categories] == ["Added"]


def test_marker_comment_never_becomes_an_entry():
    releases = parse_release_notes(SAMPLE, include_unreleased=True)
    entries = [e for r in releases for e in r.preamble] + [
        e for r in releases for c in r.categories for e in c.entries
    ]
    assert all("As of" not in e.text for e in entries)


def test_categories_in_order_empty_scaffolds_and_unknown_names():
    release = parse_release_notes(SAMPLE)[0]
    assert [c.name for c in release.categories] == ["Added", "Changed", "Weird Category"]
    by_name = {c.name: c for c in release.categories}
    assert by_name["Changed"].entries == ()
    assert [e.text for e in by_name["Weird Category"].entries] == ["weird entry"]


def test_release_preamble_captured_before_first_category():
    release = parse_release_notes(SAMPLE)[0]
    assert [e.text for e in release.preamble] == ["Release preamble line."]
    assert release.has_content()


def test_nested_bullets_levels_and_order():
    added = parse_release_notes(SAMPLE)[0].categories[0]
    bullets = [(e.text, e.level) for e in added.entries if e.kind == "bullet"]
    assert bullets[:3] == [
        ("top-level bullet", 0),
        ("nested level one", 1),
        ("nested level two", 2),
    ]


def test_multiline_bullet_continuation_joined():
    added = parse_release_notes(SAMPLE)[0].categories[0]
    assert (
        Entry(kind="bullet", text="multi-line bullet start continues here and ends here", level=0)
        in added.entries
    )


def test_prose_paragraph_inside_section_preserved():
    fixed = parse_release_notes(SAMPLE)[1].categories[0]
    assert Entry(kind="prose", text="See docs for details.", level=0) in fixed.entries


def test_lenient_on_malformed_headers_and_odd_indents():
    releases = parse_release_notes(MALFORMED)
    assert [r.version for r in releases] == ["3.0.0"]
    # Content under the malformed / unknown `## ` headers is skipped entirely.
    all_text = " ".join(
        e.text for r in releases for c in r.categories for e in c.entries
    ) + " ".join(e.text for r in releases for e in r.preamble)
    assert "malformed" not in all_text
    assert "stray text" not in all_text
    # Odd indent (3 spaces) tolerated: integer division maps it to level 1.
    assert [(e.text, e.level) for e in releases[0].preamble] == [("odd indent bullet", 1)]


def test_parser_total_on_junk_inputs():
    for junk in ("", "\n\n", "just words", "## ", "- dangling bullet", "### Orphan\n- x"):
        parse_release_notes(junk)  # must not raise (total by construction)


def test_find_release():
    releases = parse_release_notes(SAMPLE)
    hit = find_release(releases, "1.2.3")
    assert hit is not None and hit.version == "1.2.3"
    assert find_release(releases, "9.9.9") is None


def test_real_changelog_baseline():
    releases = parse_release_notes(changelog_path().read_text(encoding="utf-8"))
    assert len(releases) >= 1
    for release in releases:
        assert re.fullmatch(r"\d+\.\d+\.\d+", release.version)
        assert release.date is not None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", release.date)


# --- renderer -------------------------------------------------------------


def test_render_drops_empty_categories_and_indents_bullets():
    rendered = render_release(parse_release_notes(SAMPLE)[0])
    assert "2.0.0 (2026-05-01)" in rendered
    assert "Changed:" not in rendered
    assert "Added:" in rendered
    assert "  - top-level bullet" in rendered
    assert "    - nested level one" in rendered
    assert "      - nested level two" in rendered


def test_render_prose_as_bare_paragraph():
    rendered = render_release(parse_release_notes(SAMPLE)[1])
    assert "Fixed:" in rendered
    assert "\nSee docs for details." in rendered
    assert "- See docs" not in rendered


def test_render_unreleased_header_is_bare():
    unreleased = parse_release_notes(SAMPLE, include_unreleased=True)[0]
    rendered = render_release(unreleased)
    assert "Unreleased" in rendered
    assert "(None)" not in rendered


def test_render_releases_joins_all():
    rendered = render_releases(parse_release_notes(SAMPLE))
    assert rendered.index("2.0.0 (2026-05-01)") < rendered.index("1.2.3 (2026-01-15)")


# --- CLI ------------------------------------------------------------------


def _patch_changelog(tmp_path, monkeypatch, text=SAMPLE):
    path = tmp_path / "CHANGELOG.md"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(rn_cmd, "changelog_path", lambda: path)


def _assert_clean_failure(result):
    """Every expected failure exits 1 via UserFacingCliError — never a traceback."""
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "Traceback" not in result.stderr


def test_cli_default_shows_running_versions_notes(tmp_path, monkeypatch):
    _patch_changelog(tmp_path, monkeypatch)
    monkeypatch.setattr(rn_cmd, "_cli_version", lambda: "2.0.0")
    result = CliRunner().invoke(cli, ["release-notes"])
    assert result.exit_code == 0, result.stderr
    assert "2.0.0 (2026-05-01)" in result.stderr
    assert "top-level bullet" in result.stderr
    assert result.stdout == ""  # stdout stays machine-clean


def test_cli_default_miss_is_clean_error(tmp_path, monkeypatch):
    _patch_changelog(tmp_path, monkeypatch)
    monkeypatch.setattr(rn_cmd, "_cli_version", lambda: "9.9.9")
    result = CliRunner().invoke(cli, ["release-notes"])
    _assert_clean_failure(result)
    assert "No release notes for perk 9.9.9" in result.stderr
    assert "--all" in result.stderr


def test_cli_version_hit(tmp_path, monkeypatch):
    _patch_changelog(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["release-notes", "--version", "1.2.3"])
    assert result.exit_code == 0, result.stderr
    assert "1.2.3 (2026-01-15)" in result.stderr
    assert "2.0.0" not in result.stderr


def test_cli_version_miss_lists_available(tmp_path, monkeypatch):
    _patch_changelog(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["release-notes", "--version", "8.8.8"])
    _assert_clean_failure(result)
    assert "No release notes for perk 8.8.8" in result.stderr
    assert "2.0.0, 1.2.3" in result.stderr


def test_cli_version_bad_shape(tmp_path, monkeypatch):
    _patch_changelog(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["release-notes", "--version", "garbage"])
    _assert_clean_failure(result)
    assert "--version expects an X.Y.Z version" in result.stderr


def test_cli_all_renders_every_release_never_unreleased(tmp_path, monkeypatch):
    _patch_changelog(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["release-notes", "--all"])
    assert result.exit_code == 0, result.stderr
    assert "2.0.0 (2026-05-01)" in result.stderr
    assert "1.2.3 (2026-01-15)" in result.stderr
    assert "Unreleased" not in result.stderr
    assert "pending thing" not in result.stderr


def test_cli_all_and_version_mutually_exclusive(tmp_path, monkeypatch):
    _patch_changelog(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["release-notes", "--all", "--version", "1.2.3"])
    _assert_clean_failure(result)
    assert "not both" in result.stderr


def test_cli_missing_changelog_is_clean_error(monkeypatch):
    def _raise() -> object:
        raise FileNotFoundError("no bundled changelog")

    monkeypatch.setattr(rn_cmd, "changelog_path", _raise)
    result = CliRunner().invoke(cli, ["release-notes", "--all"])
    _assert_clean_failure(result)
    assert "Could not read perk's bundled changelog" in result.stderr


def test_cli_all_with_zero_releases_is_clean_error(tmp_path, monkeypatch):
    _patch_changelog(tmp_path, monkeypatch, text="# Changelog\n\nno releases here\n")
    result = CliRunner().invoke(cli, ["release-notes", "--all"])
    _assert_clean_failure(result)
    assert "No releases found" in result.stderr
