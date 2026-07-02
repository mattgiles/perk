"""The `.perk/required-perk-version` managed pin (`convergence/init/version_pin.py`)."""

from perk import __version__
from perk.convergence.init.version_pin import (
    converge_version_pin,
    read_version_pin,
    render_version_pin,
)
from perk.substrate import paths


def test_render_is_the_version_plus_newline():
    assert render_version_pin() == f"{__version__}\n"


def test_read_missing_file_returns_none(tmp_path):
    assert read_version_pin(tmp_path) is None


def test_read_returns_stripped_version(tmp_path):
    pin = paths.required_version_file(tmp_path)
    pin.parent.mkdir(parents=True, exist_ok=True)
    pin.write_text(f"{__version__}\n", encoding="utf-8")
    assert read_version_pin(tmp_path) == __version__


def test_converge_dry_run_reports_without_writing(tmp_path):
    changes = converge_version_pin(tmp_path, apply=False)
    assert changes == [".perk/required-perk-version: created"]
    assert not paths.required_version_file(tmp_path).exists()


def test_converge_creates_then_is_idempotent(tmp_path):
    assert converge_version_pin(tmp_path) == [".perk/required-perk-version: created"]
    pin = paths.required_version_file(tmp_path)
    assert pin.read_text(encoding="utf-8") == f"{__version__}\n"
    assert converge_version_pin(tmp_path) == []


def test_converge_updates_stale_content(tmp_path):
    pin = paths.required_version_file(tmp_path)
    pin.parent.mkdir(parents=True, exist_ok=True)
    pin.write_text("0.0.1\n", encoding="utf-8")
    assert converge_version_pin(tmp_path) == [".perk/required-perk-version: updated"]
    assert pin.read_text(encoding="utf-8") == f"{__version__}\n"
