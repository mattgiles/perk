"""Tests for the issue-backend resolver + the consumer-boundary scan (Objective #746, Node 2.1).

The resolver (``perk/backends/resolve.py``) is the only door every issue-tier consumer goes
through: ``resolve_issue_backend`` validates the committed ``[issues]`` selection and constructs the
matching backend (``GitHubIssueBackend`` / ``LinearIssueBackend``); the local overlay is never read.
``TestConsumerBoundary`` is the source-scan companion proving no production module reaches the
``perk/github/`` issue-tier functions directly — both express "the resolver is the only door".
"""

import re
from pathlib import Path

import pytest

import perk
from perk.backends import resolve
from perk.backends.github.backend import GitHubIssueBackend
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import LinearIssueBackend
from perk.backends.resolve import resolve_issue_backend, resolve_issue_backend_id


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


# The 15 issue-tier functions on the perk/github/ package (the GitHubIssueBackend substrate).
# Production code must reach them through perk.backends.resolve.resolve_issue_backend, never
# directly. The objective-tier functions have their own scan in tests/test_objective_stores.py.
ISSUE_TIER_FUNCTIONS: tuple[str, ...] = (
    "create_label",
    "find_plan_issue",
    "create_plan_issue",
    "update_plan_issue",
    "update_plan_header",
    "get_plan",
    "get_plan_body",
    "find_learn_issue",
    "create_learn_issue",
    "list_learn_issues",
    "close_and_label_consolidated",
    "close_issue",
    "add_issue_comment",
    "find_comment_id_by_marker",
    "upsert_marked_comment",
)


class TestConsumerBoundary:
    def test_no_production_module_calls_issue_tier_directly(self) -> None:
        """Source scan: outside perk/backends/github/backend.py (the adapter) and the perk/github/
        package itself, no module under perk/ may contain a `github.<issue-tier-fn>(` call.

        `objective_stores.py` is also allowed: `GitHubObjectiveStore.close_objective` (Node 3.4)
        deliberately reaches the issue-tier close primitive (`github.close_issue`) to retire a
        GitHub objective issue — a GitHub objective IS an issue, so its close is byte-identical to
        the issue close, and routing it through the objective adapter (not the issue backend) is the
        point of moving the close onto the `ObjectiveStore`."""
        perk_dir = Path(perk.__file__).parent
        allowed = {
            perk_dir / "backends" / "github" / "backend.py",
            perk_dir / "backends" / "objective_stores.py",
        }
        github_pkg_dir = perk_dir / "github"
        pattern = re.compile(
            r"github\.(" + "|".join(re.escape(fn) for fn in ISSUE_TIER_FUNCTIONS) + r")\("
        )
        offenders: list[str] = []
        for path in sorted(perk_dir.rglob("*.py")):
            if path in allowed or path.is_relative_to(github_pkg_dir):
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if pattern.search(line):
                    offenders.append(
                        f"{path.relative_to(perk_dir.parent)}:{lineno}: {line.strip()}"
                    )
        assert not offenders, (
            "issue-tier calls must go through perk.backends.resolve:\n" + "\n".join(offenders)
        )
