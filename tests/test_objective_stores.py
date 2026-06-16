"""Tests for the objective stores + resolver (Objective #548, Node 2.2).

Covers: static ``ObjectiveStore`` conformance (ty-checked, both stores), ``GitHubObjectiveStore``
per-method delegation onto ``perk.github``'s objective-tier functions (constructor-bound
``repo_root``, ``dry_run`` passthrough, str-id results), ``GitHubError`` → ``ObjectiveStoreError``
translation + the non-numeric-id guard, the resolver dispatch, and the objective-tier
consumer-boundary source scan (no production module outside ``perk/backends/objective_stores.py``
calls a ``github.<objective-tier-fn>`` directly).
"""

import re
from pathlib import Path
from typing import Any

import pytest

import perk
from perk import github, objective
from perk.backends import issues, objective_store
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear_backend import LinearObjectiveStore, LinearProjectObjectiveStore
from perk.backends.objective_store import ObjectiveStoreError
from perk.backends.objective_stores import (
    GitHubObjectiveStore,
    resolve_objective_store,
    resolve_objective_store_id,
)


def _make_store(repo_root: Path) -> objective_store.ObjectiveStore:
    """The static conformance check: ty verifies ``GitHubObjectiveStore`` satisfies the protocol."""
    store: objective_store.ObjectiveStore = GitHubObjectiveStore(repo_root)
    return store


class TestConformance:
    def test_github_store_satisfies_protocol(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert isinstance(store, GitHubObjectiveStore)

    def test_github_store_backend_id(self) -> None:
        assert GitHubObjectiveStore.backend_id == "github"

    def test_linear_store_backend_id(self) -> None:
        assert LinearObjectiveStore.backend_id == "linear"


def _write_config(repo_root: Path, name: str, text: str) -> None:
    pi = repo_root / ".pi"
    pi.mkdir(parents=True, exist_ok=True)
    (pi / name).write_text(text, encoding="utf-8")


class TestResolver:
    def test_default_returns_github_store_bound_to_root(self, tmp_path: Path) -> None:
        store = resolve_objective_store(tmp_path)
        assert isinstance(store, GitHubObjectiveStore)
        assert store._repo_root == tmp_path

    def test_explicit_github_selection_returns_github_store(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "github"\n')
        assert isinstance(resolve_objective_store(tmp_path), GitHubObjectiveStore)

    def test_resolve_id_single_sources_off_issue_backend(self, tmp_path: Path) -> None:
        _write_config(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\n')
        assert resolve_objective_store_id(tmp_path) == issues.LINEAR_BACKEND_ID

    def test_resolve_id_defaults_to_github(self, tmp_path: Path) -> None:
        assert resolve_objective_store_id(tmp_path) == issues.GITHUB_BACKEND_ID

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


class _Recorder:
    """Record a delegate call's kwargs and return a canned value."""

    def __init__(self, result: object) -> None:
        self.result = result
        self.kwargs: dict[str, Any] = {}

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self.result


class TestGitHubDelegation:
    def test_find_objective(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(github.ObjectiveIssue(number=252, url="u252", existed=True))
        monkeypatch.setattr(github, "find_objective_issue", rec)
        result = GitHubObjectiveStore(tmp_path).find_objective(run_id="RUN1")
        assert rec.kwargs == {"run_id": "RUN1", "repo_root": tmp_path}
        assert result == objective_store.ObjectiveRef(id="252", url="u252", existed=True)

    def test_find_objective_none_passthrough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(github, "find_objective_issue", _Recorder(None))
        assert GitHubObjectiveStore(tmp_path).find_objective(run_id="RUN1") is None

    def test_create_objective(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(github.ObjectiveIssue(number=252, url="u252", existed=False))
        monkeypatch.setattr(github, "create_objective_issue", rec)
        result = GitHubObjectiveStore(tmp_path).create_objective(
            title="t", body="b", run_id="RUN1", status="active", roadmap_nodes=None
        )
        assert rec.kwargs == {
            "title": "t",
            "body": "b",
            "repo_root": tmp_path,
            "run_id": "RUN1",
            "status": "active",
            "roadmap_nodes": None,
            "dry_run": False,
        }
        assert result == objective_store.ObjectiveRef(id="252", url="u252", existed=False)

    def test_get_objective(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(
            github.ObjectiveState(number=252, url="u252", title="t", header={}, nodes=())
        )
        monkeypatch.setattr(github, "get_objective", rec)
        result = GitHubObjectiveStore(tmp_path).get_objective(objective_id="252")
        assert rec.kwargs == {"number": 252, "repo_root": tmp_path}
        assert result == objective_store.ObjectiveState(
            id="252", url="u252", title="t", header={}, nodes=()
        )

    def test_get_objective_none_passthrough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(github, "get_objective", _Recorder(None))
        assert GitHubObjectiveStore(tmp_path).get_objective(objective_id="252") is None

    def test_update_objective_header(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(github.ObjectiveHeaderUpdate(fields_updated=("status",), dry_run=False))
        monkeypatch.setattr(github, "update_objective_header", rec)
        result = GitHubObjectiveStore(tmp_path).update_objective_header(
            objective_id="252", fields={"status": "done"}
        )
        assert rec.kwargs == {
            "number": 252,
            "fields": {"status": "done"},
            "repo_root": tmp_path,
            "dry_run": False,
        }
        assert result == objective_store.ObjectiveHeaderUpdate(
            fields_updated=("status",), dry_run=False
        )

    def test_update_objective_node(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(
            github.ObjectiveNodeUpdate(
                number=252, node_id="1.2", comment_updated=True, dry_run=False
            )
        )
        monkeypatch.setattr(github, "update_objective_node", rec)
        result = GitHubObjectiveStore(tmp_path).update_objective_node(
            objective_id="252",
            node_id="1.2",
            status=objective.NodeStatus.DONE,
            pr="#325",
            description=None,
        )
        assert rec.kwargs == {
            "number": 252,
            "node_id": "1.2",
            "status": objective.NodeStatus.DONE,
            "pr": "#325",
            "description": None,
            "repo_root": tmp_path,
            "dry_run": False,
        }
        assert result == objective_store.ObjectiveNodeUpdate(
            objective_id="252", node_id="1.2", comment_updated=True, dry_run=False
        )

    def test_add_objective_node(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(
            github.ObjectiveNodeAdd(number=252, node_id="1.3", comment_updated=True, dry_run=False)
        )
        monkeypatch.setattr(github, "add_objective_node", rec)
        result = GitHubObjectiveStore(tmp_path).add_objective_node(
            objective_id="252",
            phase=1,
            description="Gamma",
            depends_on=("1.1",),
        )
        assert rec.kwargs == {
            "number": 252,
            "phase": 1,
            "description": "Gamma",
            "status": objective.NodeStatus.PENDING,
            "slug": None,
            "depends_on": ("1.1",),
            "comment": None,
            "repo_root": tmp_path,
            "dry_run": False,
        }
        assert result == objective_store.ObjectiveNodeAdd(
            objective_id="252", node_id="1.3", comment_updated=True, dry_run=False
        )

    def test_update_objective_body(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(
            github.ObjectiveBodyUpdate(number=252, comment_id=777, updated=True, dry_run=False)
        )
        monkeypatch.setattr(github, "update_objective_body", rec)
        result = GitHubObjectiveStore(tmp_path).update_objective_body(objective_id="252", prose="p")
        assert rec.kwargs == {
            "number": 252,
            "prose": "p",
            "repo_root": tmp_path,
            "dry_run": False,
        }
        assert result == objective_store.ObjectiveBodyUpdate(
            objective_id="252", comment_id="777", updated=True, dry_run=False
        )

    def test_update_objective_body_none_comment_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(
            github.ObjectiveBodyUpdate(number=252, comment_id=None, updated=False, dry_run=True)
        )
        monkeypatch.setattr(github, "update_objective_body", rec)
        result = GitHubObjectiveStore(tmp_path).update_objective_body(
            objective_id="252", prose="p", dry_run=True
        )
        assert result.comment_id is None

    def test_save_node_plan_returns_none(self, tmp_path: Path) -> None:
        # GitHub does not unify node + plan: always None so the caller takes the standalone path.
        result = GitHubObjectiveStore(tmp_path).save_node_plan(
            objective_id="252", node_id="1.1", header_fields={"run_id": "R"}, plan_markdown="# p"
        )
        assert result is None

    def test_close_objective_closes_issue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(True)
        monkeypatch.setattr(github, "close_issue", rec)
        result = GitHubObjectiveStore(tmp_path).close_objective(objective_id="252")
        assert rec.kwargs == {"number": 252, "repo_root": tmp_path, "dry_run": False}
        assert result is True

    def test_close_objective_dry_run_passthrough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(False)
        monkeypatch.setattr(github, "close_issue", rec)
        result = GitHubObjectiveStore(tmp_path).close_objective(objective_id="252", dry_run=True)
        assert rec.kwargs == {"number": 252, "repo_root": tmp_path, "dry_run": True}
        assert result is False

    def test_post_status_update_is_noop_false(self, tmp_path: Path) -> None:
        # GitHub has no Project Updates surface (Node 4.3) — always False, never raises, no `gh`.
        store = GitHubObjectiveStore(tmp_path)
        assert store.post_status_update(objective_id="252", body="x") is False
        assert store.post_status_update(objective_id="252", body="x", dry_run=True) is False


class TestErrorTranslation:
    def test_github_error_wrapped_message_verbatim_cause_chained(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = github.GitHubError("objective node '9.9' not found on #252")

        def boom(**kwargs: Any) -> None:
            raise original

        monkeypatch.setattr(github, "get_objective", boom)
        with pytest.raises(ObjectiveStoreError) as excinfo:
            GitHubObjectiveStore(tmp_path).get_objective(objective_id="252")
        assert str(excinfo.value) == "objective node '9.9' not found on #252"
        assert excinfo.value.__cause__ is original

    def test_non_numeric_objective_id_raises_store_error(self, tmp_path: Path) -> None:
        store = GitHubObjectiveStore(tmp_path)
        with pytest.raises(ObjectiveStoreError, match="LIN-42"):
            store.get_objective(objective_id="LIN-42")
        with pytest.raises(ObjectiveStoreError, match="numeric"):
            store.update_objective_body(objective_id="abc", prose="p")


class TestLateBinding:
    def test_patch_after_construction_still_intercepts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Backends delegate via attribute access on the github module object at CALL time, so a
        # monkeypatch applied after the store was constructed is still seen (the equivalence lock
        # that keeps the CLI objective tests green through the extraction).
        store = GitHubObjectiveStore(tmp_path)
        rec = _Recorder(github.ObjectiveIssue(number=7, url="u7", existed=True))
        monkeypatch.setattr(github, "find_objective_issue", rec)
        result = store.find_objective(run_id="RUN1")
        assert result is not None
        assert result.id == "7"


# The six objective-tier functions on the perk/github/ package (the GitHubObjectiveStore
# substrate). Production code must reach them through
# perk.backends.objective_stores.resolve_objective_store, never directly.
OBJECTIVE_TIER_FUNCTIONS: tuple[str, ...] = (
    "find_objective_issue",
    "create_objective_issue",
    "get_objective",
    "update_objective_header",
    "update_objective_node",
    "update_objective_body",
    "add_objective_node",
)


class TestConsumerBoundary:
    def test_no_production_module_calls_objective_tier_directly(self) -> None:
        """Source scan: outside perk/backends/objective_stores.py (the adapter) and the
        perk/github/ package itself, no module under perk/ may contain a
        `github.<objective-tier-fn>(` call."""
        perk_dir = Path(perk.__file__).parent
        allowed = {perk_dir / "backends" / "objective_stores.py"}
        github_pkg_dir = perk_dir / "github"
        pattern = re.compile(
            r"github\.(" + "|".join(re.escape(fn) for fn in OBJECTIVE_TIER_FUNCTIONS) + r")\("
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
            "objective-tier calls must go through perk.backends.objective_stores:\n"
            + "\n".join(offenders)
        )
