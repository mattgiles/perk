"""The post-upgrade notice (`perk/cli/version_check.py`, the user-level max-seen store).

Mirrors the sibling `tests/test_version_check.py` layers, plus the store-specific ones:
- **pure decision matrix**: `_decide_last_seen` directly — the "no write on same/downgrade"
  proof lives here, without mtime games;
- **core I/O**: `upgrade_notice` against a tmp store with the gates open;
- **suppression matrix**: each suppressed shape performs **no store I/O**;
- **never-crash**: unwritable/unreadable stores degrade silently;
- **CliRunner integration**: the root-callback hook via a monkeypatched `HOME` (POSIX
  `Path.home()` honors it).
"""

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from perk import __version__
from perk.cli import version_check
from perk.cli.cli import cli
from perk.cli.version_check import _decide_last_seen, upgrade_notice
from perk.substrate import paths

_OLD = "0.0.0"
_NEWER = "9999.0.0"


def _call(store: Path, *, argv=(), subcommand=None, env=None, interactive=True):
    return upgrade_notice(
        argv=list(argv),
        subcommand=subcommand,
        env=env or {},
        interactive=interactive,
        store=store,
    )


# --- pure core: the decision matrix -----------------------------------------------------------


@pytest.mark.parametrize(
    ("stored", "current", "expected"),
    [
        # First unsuppressed run: record silently.
        (None, "1.2.3", ("1.2.3", False)),
        # Garbage stored content: self-heal silently (can't know it was an upgrade).
        ("not-a-version", "1.2.3", ("1.2.3", False)),
        ("1.2", "1.2.3", ("1.2.3", False)),
        ("1.2.3rc1", "1.2.3", ("1.2.3", False)),
        # Same version: no-op, no write.
        ("1.2.3", "1.2.3", (None, False)),
        # Upgrade: record + notice.
        ("1.2.3", "1.2.4", ("1.2.4", True)),
        ("1.9.0", "1.10.0", ("1.10.0", True)),
        ("0.9.9", "1.0.0", ("1.0.0", True)),
        # Downgrade: the max seen is never lowered.
        ("1.2.4", "1.2.3", (None, False)),
        # Unparseable current: do nothing (defensive).
        ("1.2.3", "garbage", (None, False)),
        (None, "garbage", (None, False)),
    ],
)
def test_decision_matrix(stored, current, expected):
    assert _decide_last_seen(stored, current) == expected


# --- core I/O (gates open, tmp store) ---------------------------------------------------------


def test_first_run_records_silently_and_creates_parents(tmp_path):
    store = tmp_path / ".perk" / "last-seen-version"
    assert _call(store) is None
    assert store.read_text(encoding="utf-8") == f"{__version__}\n"


def test_upgrade_notices_and_records(tmp_path):
    store = tmp_path / "last-seen-version"
    store.write_text(f"{_OLD}\n", encoding="utf-8")
    message = _call(store)
    assert message is not None
    assert __version__ in message and "perk release-notes" in message
    assert store.read_text(encoding="utf-8") == f"{__version__}\n"


def test_downgrade_is_silent_and_store_untouched(tmp_path):
    store = tmp_path / "last-seen-version"
    store.write_text(f"{_NEWER}\n", encoding="utf-8")
    assert _call(store) is None
    assert store.read_text(encoding="utf-8") == f"{_NEWER}\n"


def test_garbage_store_self_heals_silently(tmp_path):
    store = tmp_path / "last-seen-version"
    store.write_text("garbage\n", encoding="utf-8")
    assert _call(store) is None
    assert store.read_text(encoding="utf-8") == f"{__version__}\n"


# --- suppression matrix: no store I/O when suppressed -----------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"env": {"PERK_SKIP_VERSION_CHECK": "1"}},
        {"env": {"PERK_SKIP_VERSION_CHECK": "yes-please"}},
        {"env": {"CI": "true"}},
        {"interactive": False},
        {"argv": ["doctor", "--version"]},
        {"argv": ["doctor", "--help"]},
        {"argv": ["doctor", "--json"]},
        {"subcommand": "run-worker"},
    ],
)
def test_suppressed_invocations_do_no_store_io(tmp_path, kwargs):
    # Upgrade-primed: were the gates open, this WOULD notice and rewrite the store.
    store = tmp_path / "last-seen-version"
    store.write_text(f"{_OLD}\n", encoding="utf-8")
    assert _call(store, **kwargs) is None
    assert store.read_text(encoding="utf-8") == f"{_OLD}\n"


def test_suppressed_first_run_does_not_create_the_store(tmp_path):
    store = tmp_path / ".perk" / "last-seen-version"
    assert _call(store, env={"CI": "true"}) is None
    assert not store.exists()


# --- never-crash: silent degrade on store failures --------------------------------------------


def test_unwritable_store_suppresses_the_notice(tmp_path):
    # Upgrade-primed but unwritable: record-then-notice means the notice is withheld (it would
    # otherwise repeat on every run).
    parent = tmp_path / "readonly"
    parent.mkdir()
    store = parent / "last-seen-version"
    store.write_text(f"{_OLD}\n", encoding="utf-8")
    store.chmod(0o444)
    parent.chmod(0o555)
    try:
        assert _call(store) is None
        assert store.read_text(encoding="utf-8") == f"{_OLD}\n"
    finally:
        parent.chmod(0o755)
        store.chmod(0o644)


def test_read_failure_treated_as_first_run(tmp_path, monkeypatch):
    store = tmp_path / "last-seen-version"
    store.write_text(f"{_OLD}\n", encoding="utf-8")
    real_read_text = Path.read_text

    def boom(self, *args, **kwargs):
        if self == store:
            raise OSError("io error")
        return real_read_text(self, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(Path, "read_text", boom)
        assert _call(store) is None  # no raise; treated as first-run
    # Self-healed: the current version was recorded despite the unreadable prior content.
    assert store.read_text(encoding="utf-8") == f"{__version__}\n"


# --- CliRunner integration (the root-callback hook) -------------------------------------------


def _force_gates_open(monkeypatch, repo):
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HOME", str(repo))
    monkeypatch.setattr(version_check, "_interactive", lambda: True)
    monkeypatch.setattr(sys, "argv", ["perk", "registry", "show"])
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PERK_SKIP_VERSION_CHECK", raising=False)


def _write_store(home: Path, version: str) -> Path:
    store = home / ".perk" / "last-seen-version"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(f"{version}\n", encoding="utf-8")
    return store


def test_cli_emits_notice_on_stale_store(git_repo, monkeypatch):
    store = _write_store(git_repo, _OLD)
    _force_gates_open(monkeypatch, git_repo)
    result = CliRunner().invoke(cli, ["registry", "show"])
    assert result.exit_code == 0
    assert "perk release-notes" in result.stderr and __version__ in result.stderr
    assert store.read_text(encoding="utf-8") == f"{__version__}\n"


def test_cli_stays_silent_on_current_store(git_repo, monkeypatch):
    # Same forced-open gates: proves the emission is upgrade-gated, not gate-gated.
    _write_store(git_repo, __version__)
    _force_gates_open(monkeypatch, git_repo)
    result = CliRunner().invoke(cli, ["registry", "show"])
    assert result.exit_code == 0
    assert "perk release-notes" not in result.stderr


def test_cli_shows_both_surfaces_together(git_repo, monkeypatch):
    # A stale repo pin AND an old store: the ⚠ warning first, the notice second.
    pin = paths.required_version_file(git_repo)
    pin.parent.mkdir(parents=True, exist_ok=True)
    pin.write_text("0.0.1\n", encoding="utf-8")
    _write_store(git_repo, _OLD)
    _force_gates_open(monkeypatch, git_repo)
    result = CliRunner().invoke(cli, ["registry", "show"])
    assert result.exit_code == 0
    assert "\u26a0" in result.stderr and "0.0.1" in result.stderr
    assert "perk release-notes" in result.stderr
