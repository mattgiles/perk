"""The prose-review launcher: build → catalog → bind → open → serve, with typed failures."""

import re
import socket
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from perk_dev.cli import cli
from perk_dev.prose_review import cli as review_cli
from perk_dev.prose_review.catalog import CatalogQueryError

from perk.substrate.proc import ProcFailure


class _Snapshot:
    """An opaque stand-in — the launcher hands it to create_app untouched."""


@dataclass
class _Calls:
    build: list[Path] = field(default_factory=list)
    opened: list[str] = field(default_factory=list)
    served: list[tuple[object, int]] = field(default_factory=list)


@pytest.fixture()
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    dist = tmp_path / "tools" / "prose-review" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(review_cli, "repo_root", lambda _cwd: tmp_path)
    return tmp_path


@pytest.fixture()
def happy(fake_repo: Path, monkeypatch: pytest.MonkeyPatch) -> _Calls:
    calls = _Calls()
    monkeypatch.setattr(review_cli, "build_frontend", lambda root: calls.build.append(root))
    monkeypatch.setattr(review_cli, "load_catalog", lambda _root: _Snapshot())

    def open_browser(url: str) -> bool:
        calls.opened.append(url)
        return True

    monkeypatch.setattr(review_cli, "_open_browser", open_browser)

    def serve(app: object, sock: socket.socket) -> None:
        # Recorded at call time: the launcher's finally arm closes the socket on return.
        calls.served.append((app, sock.getsockname()[1]))

    monkeypatch.setattr(review_cli, "_serve", serve)
    return calls


def _invoke(*args: str) -> Result:
    return CliRunner().invoke(cli, ["prose-review", *args])


def _served_url(result: Result) -> str:
    match = re.search(r"http://127\.0\.0\.1:\d+", result.stderr)
    assert match is not None, result.stderr
    return match.group()


def test_not_a_repo_fails_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(review_cli, "repo_root", lambda _cwd: None)
    result = _invoke()
    assert result.exit_code == 2, result.output
    assert "not inside a git repository" in result.stderr


def test_happy_path_builds_prints_opens_and_serves(fake_repo: Path, happy: _Calls) -> None:
    result = _invoke()
    assert result.exit_code == 0, result.output
    url = _served_url(result)
    assert happy.build == [fake_repo]
    assert happy.opened == [url]
    assert len(happy.served) == 1
    app, port = happy.served[0]
    assert isinstance(app, review_cli.SecurityGuardMiddleware)
    # The printed URL is the socket's real bound port.
    assert url.endswith(f":{port}")


def test_no_open_prints_the_url_without_opening(happy: _Calls) -> None:
    result = _invoke("--no-open")
    assert result.exit_code == 0, result.output
    _served_url(result)
    assert happy.opened == []
    assert len(happy.served) == 1


def test_opener_returning_false_warns_and_still_serves(
    happy: _Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(review_cli, "_open_browser", lambda _url: False)
    result = _invoke()
    assert result.exit_code == 0, result.output
    url = _served_url(result)
    assert f"could not open a browser — visit {url}" in result.stderr
    assert len(happy.served) == 1


@pytest.mark.parametrize("error", [OSError("no browser available"), RuntimeError("opener bug")])
def test_opener_raising_warns_and_still_serves(
    happy: _Calls, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def boom(_url: str) -> bool:
        raise error

    monkeypatch.setattr(review_cli, "_open_browser", boom)
    result = _invoke()
    assert result.exit_code == 0, result.output
    assert "could not open a browser" in result.stderr
    assert len(happy.served) == 1


def test_build_failure_is_typed_and_never_serves(
    happy: _Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_build(_root: Path) -> None:
        raise ProcFailure("exit", ("npm", "run", "build"), returncode=1, stderr="vite exploded")

    monkeypatch.setattr(review_cli, "build_frontend", failing_build)
    result = _invoke()
    assert result.exit_code == 1, result.output
    assert "vite exploded" in result.stderr
    assert happy.served == []


def test_missing_index_after_build_is_typed(fake_repo: Path, happy: _Calls) -> None:
    (fake_repo / "tools" / "prose-review" / "dist" / "index.html").unlink()
    result = _invoke()
    assert result.exit_code == 1, result.output
    assert "index.html is missing" in result.stderr
    assert happy.served == []


def test_invalid_catalog_is_typed_and_never_serves(
    happy: _Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_load(_root: Path) -> object:
        raise CatalogQueryError("prose catalog has validation findings: fixture")

    monkeypatch.setattr(review_cli, "load_catalog", failing_load)
    result = _invoke()
    assert result.exit_code == 1, result.output
    assert "validation findings" in result.stderr
    assert happy.served == []
