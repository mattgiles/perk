"""Tests for the backend-tier resolvers + the consumer-boundary scans (Objective #746).

The resolver (``perk/backends/resolve.py``) is the only door every backend consumer goes through:
``resolve_issue_backend`` / ``resolve_objective_store`` validate the committed ``[issues]``
selection and construct the matching backend; the local overlay is never read. The
``TestConsumerBoundary`` scans are the source-scan companions proving no production module reaches
the GitHub substrate modules (``perk/backends/github/{plans,objectives}.py``) directly — both
express "the resolver is the only door". (The objective-store tests folded in here from the
retired ``test_objective_stores.py``.)
"""

from pathlib import Path

import pytest

import perk
from perk.backends import resolve
from perk.backends.github.backend import GitHubIssueBackend
from perk.backends.github.objective_store import GitHubObjectiveStore
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import LinearIssueBackend, LinearProjectObjectiveStore
from perk.backends.resolve import (
    resolve_issue_backend,
    resolve_issue_backend_id,
    resolve_objective_store,
    resolve_objective_store_id,
)


def _write_config(repo_root: Path, name: str, text: str) -> None:
    pi = repo_root / ".pi"
    pi.mkdir(parents=True, exist_ok=True)
    (pi / name).write_text(text, encoding="utf-8")


class TestResolver:
    def test_returns_github_backend_bound_to_root(self, tmp_path: Path) -> None:
        backend = resolve_issue_backend(tmp_path)
        assert isinstance(backend, GitHubIssueBackend)
        assert backend._repo_root == tmp_path

    def test_explicit_github_selection_returns_github_backend(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "github"\n')
        assert isinstance(resolve_issue_backend(tmp_path), GitHubIssueBackend)

    def test_resolve_id_accepts_linear(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\n')
        assert resolve_issue_backend_id(tmp_path) == resolve.LINEAR_BACKEND_ID

    def test_linear_selection_missing_api_key_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\nteam = "ENG"\n')
        with pytest.raises(IssueBackendError, match="LINEAR_API_KEY"):
            resolve_issue_backend(tmp_path)

    def test_linear_selection_missing_team_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\n')
        with pytest.raises(IssueBackendError, match=r"\[issues\] team is required"):
            resolve_issue_backend(tmp_path)

    def test_linear_selection_returns_linear_backend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\nteam = "ENG"\n')
        backend = resolve_issue_backend(tmp_path)
        assert isinstance(backend, LinearIssueBackend)
        assert backend.backend_id == "linear"
        # Construction is lazy — the team key is bound, no network call issued.
        assert backend._team_key == "ENG"

    def test_unknown_selection_raises(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "jira"\n')
        with pytest.raises(IssueBackendError, match="unknown issue backend"):
            resolve_issue_backend(tmp_path)

    def test_local_overlay_selection_is_ignored(self, tmp_path: Path) -> None:
        # Committed-only read: a perk.local.toml [issues] selection never fragments the store.
        _write_config(tmp_path, "perk.local.toml", '[issues]\nbackend = "linear"\n')
        assert isinstance(resolve_issue_backend(tmp_path), GitHubIssueBackend)

    def test_malformed_committed_toml_raises_backend_error(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "perk.toml", "[issues\nbackend =")
        with pytest.raises(IssueBackendError, match="not valid TOML"):
            resolve_issue_backend(tmp_path)

    def test_resolve_id_defaults_to_github(self, tmp_path: Path) -> None:
        assert resolve_issue_backend_id(tmp_path) == resolve.GITHUB_BACKEND_ID


class TestObjectiveResolver:
    """The objective-store resolver pair (folded in from the retired test_objective_stores.py)."""

    def test_default_returns_github_store_bound_to_root(self, tmp_path: Path) -> None:
        store = resolve_objective_store(tmp_path)
        assert isinstance(store, GitHubObjectiveStore)
        assert store._repo_root == tmp_path

    def test_explicit_github_selection_returns_github_store(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "github"\n')
        assert isinstance(resolve_objective_store(tmp_path), GitHubObjectiveStore)

    def test_resolve_id_single_sources_off_issue_backend(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\n')
        assert resolve_objective_store_id(tmp_path) == resolve.LINEAR_BACKEND_ID

    def test_resolve_id_defaults_to_github(self, tmp_path: Path) -> None:
        assert resolve_objective_store_id(tmp_path) == resolve.GITHUB_BACKEND_ID

    def test_linear_selection_returns_project_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Node 3.4: the linear arm is project-backed (LinearProjectObjectiveStore), not the
        # dormant issue-backed LinearObjectiveStore.
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\nteam = "ENG"\n')
        store = resolve_objective_store(tmp_path)
        assert isinstance(store, LinearProjectObjectiveStore)
        assert store.backend_id == "linear"
        # Construction is lazy — the team key is bound on the shared ops, no network call issued.
        assert store._issue_ops._team_key == "ENG"
        assert store._projects._team_key == "ENG"

    def test_linear_selection_missing_team_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\n')
        with pytest.raises(IssueBackendError, match=r"\[issues\] team is required"):
            resolve_objective_store(tmp_path)

    def test_linear_selection_missing_api_key_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\nteam = "ENG"\n')
        with pytest.raises(IssueBackendError, match="LINEAR_API_KEY"):
            resolve_objective_store(tmp_path)

    def test_unknown_selection_raises(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "jira"\n')
        with pytest.raises(IssueBackendError, match="unknown issue backend"):
            resolve_objective_store(tmp_path)


# The GitHub plan/issue + objective substrate modules. Production code must reach them through the
# resolvers in perk.backends.resolve (resolve_issue_backend / resolve_objective_store), never by
# importing the substrate module directly. The only legitimate importers are the GitHub backend
# package's own modules (the adapters + the sibling substrate) under perk/backends/github/.
SUBSTRATE_MODULES: tuple[str, ...] = (
    "perk.backends.github.plans",
    "perk.backends.github.objectives",
)


class TestConsumerBoundary:
    def test_no_production_module_imports_the_substrate_directly(self) -> None:
        """Source scan: no module under perk/ OUTSIDE the GitHub backend package
        (perk/backends/github/) may import the substrate modules
        perk.backends.github.{plans,objectives} directly — production reaches plan/issue and
        objective ops through resolve.resolve_issue_backend(...) / resolve.resolve_objective_store(
        ...). The adapters (backend.py, objective_store.py) and the sibling substrate
        (objectives.py importing plans) legitimately import it, so the whole perk/backends/github/
        package is allowed."""
        perk_dir = Path(perk.__file__).parent
        github_backend_dir = perk_dir / "backends" / "github"
        offenders: list[str] = []
        for path in sorted(perk_dir.rglob("*.py")):
            if path.is_relative_to(github_backend_dir):
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if any(mod in line for mod in SUBSTRATE_MODULES):
                    offenders.append(
                        f"{path.relative_to(perk_dir.parent)}:{lineno}: {line.strip()}"
                    )
        assert not offenders, (
            "substrate imports must go through perk.backends.resolve:\n" + "\n".join(offenders)
        )
