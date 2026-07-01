"""`perk-dev changelog-apply` regression tests.

Covers the strict proposal parse (`parse_proposal`/`load_proposal` rejection surfaces), the pure
append transform (`apply_to_text` placement/creation/marker rules on inline changelog strings),
the committed text goldens under `tests/golden/changelog/`, and the CLI envelope — including the
integration invariant that a happy-path apply is `changelog-check`-clean.
"""

import json
import subprocess
from pathlib import Path

import pytest
from _golden import TEXT_GOLDEN_DIR, assert_text_golden
from click.testing import CliRunner
from perk_dev import changelog
from perk_dev.cli import cli

_CHANGELOG_DIR = TEXT_GOLDEN_DIR / "changelog"


def _fixture(name: str) -> str:
    return (_CHANGELOG_DIR / name).read_text(encoding="utf-8")


# A well-formed [Unreleased] scaffold mirroring the shipped CHANGELOG.md shape.
_SCAFFOLD = """\
# Changelog

## [Unreleased]

<!-- As of fa6b115 -->

### Added

### Changed

### Fixed

## [1.0.1] - 2026-06-24

### Added

- a released entry with no token
"""

_HEAD = "9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1e0d"


def _proposal(entries: list[dict]) -> changelog.Proposal:
    return changelog.parse_proposal(
        {"since_commit": "fa6b115", "head_commit": _HEAD, "entries": entries}
    )


def _entry(**overrides) -> dict:
    base = {"category": "Added", "text": "a new thing", "commits": ["1234567"]}
    return {**base, **overrides}


# --- proposal parse -----------------------------------------------------------------


def test_parse_valid_proposal():
    proposal = _proposal(
        [_entry(confidence="high", backend="github"), _entry(category="Fixed", text="a fix")]
    )
    assert proposal.head_commit == _HEAD
    assert proposal.since_commit == "fa6b115"
    assert proposal.entries[0].commits == ("1234567",)
    assert proposal.entries[0].primary == "1234567"
    assert proposal.entries[1].category == "Fixed"


def test_parse_optional_confidence_backend_omitted():
    proposal = _proposal([_entry()])
    assert proposal.entries[0].text == "a new thing"


def _assert_bad_proposal(data: object) -> str:
    with pytest.raises(changelog.ChangelogError) as excinfo:
        changelog.parse_proposal(data)
    assert excinfo.value.error_type == "bad_proposal"
    return excinfo.value.message


def test_parse_unknown_key_rejected():
    message = _assert_bad_proposal(
        {"since_commit": "fa6b115", "head_commit": _HEAD, "entries": [], "surprise": 1}
    )
    assert "surprise" in message


def test_parse_missing_required_fields_rejected():
    complete = {"since_commit": "fa6b115", "head_commit": _HEAD, "entries": []}
    for field in complete:
        data = {k: v for k, v in complete.items() if k != field}
        message = _assert_bad_proposal(data)
        assert field in message
    entry = _entry()
    for field in ("category", "text", "commits"):
        data = {
            "since_commit": "fa6b115",
            "head_commit": _HEAD,
            "entries": [{k: v for k, v in entry.items() if k != field}],
        }
        message = _assert_bad_proposal(data)
        assert field in message


def test_parse_unknown_category_rejected():
    message = _assert_bad_proposal(
        {"since_commit": "fa6b115", "head_commit": _HEAD, "entries": [_entry(category="Frob")]}
    )
    assert "Frob" in message


def test_parse_malformed_shas_rejected():
    for data in (
        {"since_commit": "not-a-sha", "head_commit": _HEAD, "entries": []},
        {"since_commit": "fa6b115", "head_commit": "short1", "entries": []},
        {"since_commit": "fa6b115", "head_commit": _HEAD, "entries": [_entry(commits=["ZZZ"])]},
    ):
        _assert_bad_proposal(data)


def test_parse_empty_commits_rejected():
    message = _assert_bad_proposal(
        {"since_commit": "fa6b115", "head_commit": _HEAD, "entries": [_entry(commits=[])]}
    )
    assert "commits" in message


def test_parse_prestamped_hash_token_rejected():
    message = _assert_bad_proposal(
        {
            "since_commit": "fa6b115",
            "head_commit": _HEAD,
            "entries": [_entry(text="already stamped (abc1234)")],
        }
    )
    assert "(hash)" in message


def test_load_proposal_missing_file(tmp_path):
    with pytest.raises(changelog.ChangelogError) as excinfo:
        changelog.load_proposal(tmp_path / "nope.json")
    assert excinfo.value.error_type == "proposal_not_found"


def test_load_proposal_non_json(tmp_path):
    path = tmp_path / "proposal.json"
    path.write_text("not json at all", encoding="utf-8")
    with pytest.raises(changelog.ChangelogError) as excinfo:
        changelog.load_proposal(path)
    assert excinfo.value.error_type == "bad_proposal"


def test_load_proposal_happy(tmp_path):
    path = tmp_path / "proposal.json"
    path.write_text(
        json.dumps({"since_commit": "fa6b115", "head_commit": _HEAD, "entries": [_entry()]}),
        encoding="utf-8",
    )
    proposal = changelog.load_proposal(path)
    assert proposal.entries[0].category == "Added"


# --- apply_to_text ------------------------------------------------------------------


def test_append_into_existing_empty_category():
    out = changelog.apply_to_text(_SCAFFOLD, _proposal([_entry()]))
    assert "### Added\n\n- a new thing (1234567)\n\n### Changed" in out
    assert f"<!-- As of {_HEAD[:7]} -->" in out
    assert "<!-- As of fa6b115 -->" not in out
    # The released section is untouched.
    assert "- a released entry with no token" in out


def test_append_after_existing_bullet():
    seeded = _SCAFFOLD.replace(
        "### Added\n\n### Changed", "### Added\n\n- an old entry (0a1b2c3)\n\n### Changed"
    )
    out = changelog.apply_to_text(seeded, _proposal([_entry()]))
    assert "### Added\n\n- an old entry (0a1b2c3)\n- a new thing (1234567)\n\n### Changed" in out


def test_multiple_entries_same_category_keep_proposal_order():
    out = changelog.apply_to_text(
        _SCAFFOLD, _proposal([_entry(text="first"), _entry(text="second", commits=["fedcba9"])])
    )
    assert "### Added\n\n- first (1234567)\n- second (fedcba9)\n\n### Changed" in out


def test_create_absent_category_canonical_middle():
    out = changelog.apply_to_text(
        _SCAFFOLD, _proposal([_entry(category="Removed", text="a retired knob")])
    )
    assert "### Changed\n\n### Removed\n\n- a retired knob (1234567)\n\n### Fixed" in out


def test_create_major_changes_inserted_first():
    out = changelog.apply_to_text(
        _SCAFFOLD, _proposal([_entry(category="Major Changes", text="a headline shift")])
    )
    assert "### Major Changes\n\n- a headline shift (1234567)\n\n### Added" in out


def test_create_security_inserted_last():
    out = changelog.apply_to_text(
        _SCAFFOLD, _proposal([_entry(category="Security", text="a hardening fix")])
    )
    assert "### Fixed\n\n### Security\n\n- a hardening fix (1234567)\n\n## [1.0.1]" in out


def test_empty_entries_only_advances_marker():
    out = changelog.apply_to_text(_SCAFFOLD, _proposal([]))
    assert out == _SCAFFOLD.replace("<!-- As of fa6b115 -->", f"<!-- As of {_HEAD[:7]} -->")


def test_no_unreleased_raises():
    with pytest.raises(changelog.ChangelogError) as excinfo:
        changelog.apply_to_text("# Changelog\n\n## [1.0.0] - 2026-01-01\n", _proposal([]))
    assert excinfo.value.error_type == "no_unreleased"


def test_marker_missing_raises():
    with pytest.raises(changelog.ChangelogError) as excinfo:
        changelog.apply_to_text("# Changelog\n\n## [Unreleased]\n\n### Added\n", _proposal([]))
    assert excinfo.value.error_type == "marker_missing"


# --- goldens ------------------------------------------------------------------------


def _golden_apply() -> tuple[str, str]:
    """(input text, applied text) for the committed multi-category golden fixture."""
    input_text = _fixture("apply-multi.input.md")
    proposal = changelog.parse_proposal(json.loads(_fixture("apply-multi.proposal.json")))
    return input_text, changelog.apply_to_text(input_text, proposal)


def test_golden_apply_multi():
    _, applied = _golden_apply()
    assert_text_golden("changelog/apply-multi.expected", applied, suffix=".md")


def test_golden_extract_unreleased():
    _, applied = _golden_apply()
    expected = _fixture("apply-multi.expected.md")
    assert_text_golden(
        "changelog/apply-multi.unreleased", changelog.extract_unreleased(expected), suffix=".md"
    )
    assert changelog.extract_unreleased(applied) == changelog.extract_unreleased(expected)


# --- CLI ----------------------------------------------------------------------------


def _cli_repo(tmp_path, monkeypatch, *, changelog_text: str | None, proposal: dict | None) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=30)
    if changelog_text is not None:
        (tmp_path / "CHANGELOG.md").write_text(changelog_text, encoding="utf-8")
    proposal_path = tmp_path / "proposal.json"
    if proposal is not None:
        proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return proposal_path


def _good_proposal() -> dict:
    return {"since_commit": "fa6b115", "head_commit": _HEAD, "entries": [_entry()]}


def test_cli_registered():
    assert "changelog-apply" in cli.commands


def test_cli_not_a_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["changelog-apply", "--proposal", "proposal.json"])
    assert result.exit_code == 2, result.output


def test_cli_proposal_not_found(tmp_path, monkeypatch):
    _cli_repo(tmp_path, monkeypatch, changelog_text=_SCAFFOLD, proposal=None)
    result = CliRunner().invoke(cli, ["changelog-apply", "--proposal", "proposal.json"])
    assert result.exit_code == 1, result.output
    assert "not found" in result.stderr


def test_cli_changelog_not_found(tmp_path, monkeypatch):
    _cli_repo(tmp_path, monkeypatch, changelog_text=None, proposal=_good_proposal())
    result = CliRunner().invoke(cli, ["changelog-apply", "--proposal", "proposal.json"])
    assert result.exit_code == 1, result.output
    assert "CHANGELOG.md not found" in result.stderr


def test_cli_no_unreleased(tmp_path, monkeypatch):
    _cli_repo(
        tmp_path,
        monkeypatch,
        changelog_text="# Changelog\n\n## [1.0.0] - 2026-01-01\n",
        proposal=_good_proposal(),
    )
    result = CliRunner().invoke(cli, ["changelog-apply", "--proposal", "proposal.json"])
    assert result.exit_code == 1, result.output
    assert "[Unreleased]" in result.stderr


def test_cli_marker_missing(tmp_path, monkeypatch):
    _cli_repo(
        tmp_path,
        monkeypatch,
        changelog_text="# Changelog\n\n## [Unreleased]\n\n### Added\n",
        proposal=_good_proposal(),
    )
    result = CliRunner().invoke(cli, ["changelog-apply", "--proposal", "proposal.json"])
    assert result.exit_code == 1, result.output
    assert "marker" in result.stderr


def test_cli_happy_path_writes_golden_bytes(tmp_path, monkeypatch):
    input_text = _fixture("apply-multi.input.md")
    expected = _fixture("apply-multi.expected.md")
    proposal = json.loads(_fixture("apply-multi.proposal.json"))
    _cli_repo(tmp_path, monkeypatch, changelog_text=input_text, proposal=proposal)
    result = CliRunner().invoke(cli, ["changelog-apply", "--proposal", "proposal.json"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8") == expected
    assert f"marker now {_HEAD[:7]}" in result.stderr
    # Integration invariant: the applied changelog is changelog-check-clean.
    assert not changelog.check(tmp_path).has_errors()


def test_cli_dry_run_prints_section_and_writes_nothing(tmp_path, monkeypatch):
    input_text = _fixture("apply-multi.input.md")
    expected = _fixture("apply-multi.expected.md")
    proposal = json.loads(_fixture("apply-multi.proposal.json"))
    _cli_repo(tmp_path, monkeypatch, changelog_text=input_text, proposal=proposal)
    args = ["changelog-apply", "--proposal", "proposal.json", "--dry-run"]
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 0, result.output
    assert result.stdout == changelog.extract_unreleased(expected)
    assert "dry run" in result.stderr
    assert (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8") == input_text
