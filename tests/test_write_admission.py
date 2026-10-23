"""The write admission for `perk init` / `perk doctor --fix` (contracts.md §8.5 / §8.6 / §8.6a)."""

from pathlib import Path

import pytest

import perk
from perk.convergence import write_admission
from perk.convergence.write_admission import WriteRefusal, running_checkout, write_refusal

REPO_ROOT = Path(__file__).resolve().parents[1]


# --- perk's own repo: checkout equality ------------------------------------------------------


def test_the_running_checkout_is_this_checkout() -> None:
    assert running_checkout() == REPO_ROOT.resolve()
    assert write_refusal(REPO_ROOT, self_repo=True) is None


def test_a_self_repo_that_is_not_the_running_checkout_is_foreign(tmp_path: Path) -> None:
    refusal = write_refusal(tmp_path, self_repo=True)
    assert refusal == WriteRefusal(
        "foreign_perk",
        f"perk {perk.__version__} is running from {REPO_ROOT.resolve()}, not from this checkout "
        f"({tmp_path.resolve()}). In perk's own repo, perk init and perk doctor --fix converge "
        "only from the checkout's own install: run them as `uv run perk …` here.",
    )


def _fake_nested_worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    main = tmp_path / "main"
    worktree = main / ".worktrees" / "plan-1"
    init_file = worktree / "src" / "perk" / "__init__.py"
    init_file.parent.mkdir(parents=True)
    init_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(perk, "__file__", str(init_file))
    return main, worktree


def test_a_nested_worktrees_perk_never_converges_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Containment would admit this: the worktree's src/perk lives INSIDE main's tree.
    main, worktree = _fake_nested_worktree(tmp_path, monkeypatch)
    refusal = write_refusal(main, self_repo=True)
    assert refusal is not None and refusal.error_type == "foreign_perk"
    assert str(worktree.resolve()) in refusal.message


def test_a_nested_worktrees_perk_converges_its_own_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _main, worktree = _fake_nested_worktree(tmp_path, monkeypatch)
    assert write_refusal(worktree, self_repo=True) is None


def test_mains_perk_never_converges_a_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main = tmp_path / "main"
    init_file = main / "src" / "perk" / "__init__.py"
    init_file.parent.mkdir(parents=True)
    init_file.write_text("", encoding="utf-8")
    worktree = main / ".worktrees" / "plan-1"
    worktree.mkdir(parents=True)
    monkeypatch.setattr(perk, "__file__", str(init_file))
    refusal = write_refusal(worktree, self_repo=True)
    assert refusal is not None and refusal.error_type == "foreign_perk"


# --- a consumer repo: the required-perk-version pin ------------------------------------------


def _pin(root: Path, text: str) -> None:
    pin = root / ".perk" / "required-perk-version"
    pin.parent.mkdir(parents=True, exist_ok=True)
    pin.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("pin", ["4.0.0\n", "3.9.9\n", "4.0.0-rc.1\n", "0.0.1"])
def test_an_equal_or_newer_perk_converges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pin: str
) -> None:
    monkeypatch.setattr(perk, "__version__", "4.0.0")
    _pin(tmp_path, pin)
    assert write_refusal(tmp_path, self_repo=False) is None


@pytest.mark.parametrize("pin", ["4.0.1", "5.0.0", "99.0.0\n"])
def test_an_older_perk_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pin: str
) -> None:
    monkeypatch.setattr(perk, "__version__", "4.0.0")
    _pin(tmp_path, pin)
    assert write_refusal(tmp_path, self_repo=False) == WriteRefusal(
        "perk_outdated",
        f"perk 4.0.0 is older than this repo's required perk version {pin.strip()} "
        "(.perk/required-perk-version) — upgrade perk before running init or doctor --fix; a "
        "newer perk converges the pin forward.",
    )


def test_a_prerelease_of_the_pin_is_older(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(perk, "__version__", "4.1.0-rc.1")
    _pin(tmp_path, "4.1.0")
    refusal = write_refusal(tmp_path, self_repo=False)
    assert refusal is not None and refusal.error_type == "perk_outdated"


@pytest.mark.parametrize("pin", ["garbage", "", "4.0"])
def test_an_unparseable_pin_never_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pin: str
) -> None:
    monkeypatch.setattr(perk, "__version__", "4.0.0")
    _pin(tmp_path, pin)
    assert write_refusal(tmp_path, self_repo=False) is None


def test_an_unparseable_running_version_never_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(perk, "__version__", "4.0.0.dev3")
    _pin(tmp_path, "99.0.0")
    assert write_refusal(tmp_path, self_repo=False) is None


def test_a_missing_pin_never_refuses(tmp_path: Path) -> None:
    assert write_refusal(tmp_path, self_repo=False) is None


def test_an_unreadable_pin_never_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _pin(tmp_path, "99.0.0")

    def unreadable(root: Path) -> str | None:
        raise OSError("permission denied")

    monkeypatch.setattr(write_admission, "read_version_pin", unreadable)
    assert write_refusal(tmp_path, self_repo=False) is None


def test_an_undecodable_pin_never_refuses(tmp_path: Path) -> None:
    pin = tmp_path / ".perk" / "required-perk-version"
    pin.parent.mkdir(parents=True)
    pin.write_bytes(b"\xff\xfe9")
    assert write_refusal(tmp_path, self_repo=False) is None
