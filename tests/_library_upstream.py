"""The offline upstream the librarian network-verb tests clone from.

A local bare repository (the ``remote_git_repo_factory`` world, built OUTSIDE the consumer repo)
reached through git's own ``url.<base>.insteadOf`` rewriting, set as env config
(``GIT_CONFIG_COUNT``/``KEY_0``/``VALUE_0``). Env config is independent of the global/system
files the library's config-pinned policy nulls, so every clone / fetch / ls-remote against the
recorded ``https://github.com/acme/widget.git`` reaches the bare repository — no production seam.
"""

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_REF = "acme/widget"
CLONE_URL = "https://github.com/acme/widget.git"
ENTRY_PATH = "source-code/github.com/acme/widget"


def run_git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=60
    ).stdout


@dataclass(frozen=True)
class Upstream:
    """``seed`` is a work tree whose ``origin`` is ``remote``; it holds one unpushed "advance"
    commit that ``advance_origin()`` pushes (returning its SHA)."""

    seed: Path
    remote: Path
    advance_origin: Callable[[], str]

    def tag(self, name: str, ref: str = "HEAD") -> str:
        """Tag ``ref`` in the seed, push the tag, and return the tagged commit."""
        run_git(self.seed, "tag", name, ref)
        run_git(self.seed, "push", "-q", "origin", f"refs/tags/{name}")
        return run_git(self.seed, "rev-parse", f"{name}^{{commit}}").strip()

    def sha(self, ref: str) -> str:
        return run_git(self.remote, "rev-parse", ref).strip()


@pytest.fixture
def upstream(tmp_path_factory, remote_git_repo_factory, monkeypatch) -> Upstream:
    _clone, remote, advance_origin = remote_git_repo_factory(tmp_path_factory.mktemp("upstream"))
    run_git(remote, "config", "uploadpack.allowFilter", "true")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.{remote.as_uri()}.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", CLONE_URL)
    return Upstream(seed=remote.parent / "seed", remote=remote, advance_origin=advance_origin)
