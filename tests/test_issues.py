"""Tests for the GitHub issue backend + resolver (Objective #252, Node 1.2).

Covers: static protocol conformance (ty-checked), per-method delegation onto ``perk.github``'s
issue-tier functions (constructor-bound ``repo_root``, ``dry_run`` passthrough, str-id results),
``GitHubError`` → ``IssueBackendError`` translation (message verbatim, cause chained), the
non-numeric-id guard, the resolver, the late-binding monkeypatch-interception guarantee, and the
consumer-boundary source scan (no production module outside ``perk/backends/issues.py`` calls a
``github.<issue-tier-fn>`` directly).
"""

import re
from pathlib import Path
from typing import Any

import pytest

import perk
from perk import github
from perk.backends import issue_backend, issues
from perk.backends.issue_backend import IssueBackendError
from perk.backends.issues import GitHubIssueBackend, resolve_issue_backend, resolve_issue_backend_id
from perk.backends.linear_backend import LinearIssueBackend


def _make_backend(repo_root: Path) -> issue_backend.IssueBackend:
    """The static conformance check: ty verifies ``GitHubIssueBackend`` satisfies the protocol."""
    backend: issue_backend.IssueBackend = GitHubIssueBackend(repo_root)
    return backend


class TestConformance:
    def test_backend_satisfies_protocol(self, tmp_path: Path) -> None:
        backend = _make_backend(tmp_path)
        assert isinstance(backend, GitHubIssueBackend)


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
        assert resolve_issue_backend_id(tmp_path) == issues.LINEAR_BACKEND_ID

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
        assert resolve_issue_backend_id(tmp_path) == issues.GITHUB_BACKEND_ID

    def test_github_backend_id(self) -> None:
        assert GitHubIssueBackend.backend_id == "github"


class _Recorder:
    """Record a delegate call's kwargs and return a canned value."""

    def __init__(self, result: object) -> None:
        self.result = result
        self.kwargs: dict[str, Any] = {}
        self.args: tuple[Any, ...] = ()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.args = args
        self.kwargs = kwargs
        return self.result


class TestDelegation:
    """Each method delegates with the bound repo_root, converts ids, and passes dry_run."""

    def test_ensure_label(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(github.Label(name="perk:plan", created=True))
        monkeypatch.setattr(github, "create_label", rec)
        result = GitHubIssueBackend(tmp_path).ensure_label(
            "perk:plan", color="ababab", description="d", dry_run=True
        )
        assert rec.args == ("perk:plan",)
        assert rec.kwargs == {
            "color": "ababab",
            "description": "d",
            "repo_root": tmp_path,
            "dry_run": True,
        }
        assert result == issue_backend.Label(name="perk:plan", created=True)

    def test_find_plan_issue(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(github.PlanIssue(number=7, url="u7", existed=True))
        monkeypatch.setattr(github, "find_plan_issue", rec)
        result = GitHubIssueBackend(tmp_path).find_plan_issue(run_id="RUN1")
        assert rec.kwargs == {"run_id": "RUN1", "repo_root": tmp_path}
        assert result == issue_backend.IssueRef(id="7", url="u7", existed=True)

    def test_find_plan_issue_none_passthrough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(github, "find_plan_issue", _Recorder(None))
        assert GitHubIssueBackend(tmp_path).find_plan_issue(run_id="RUN1") is None

    def test_create_plan_issue(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(github.PlanIssue(number=12, url="u12", existed=False))
        monkeypatch.setattr(github, "create_plan_issue", rec)
        result = GitHubIssueBackend(tmp_path).create_plan_issue(title="t", body="b", run_id="RUN1")
        assert rec.kwargs == {
            "title": "t",
            "body": "b",
            "repo_root": tmp_path,
            "run_id": "RUN1",
            "dry_run": False,
        }
        assert result == issue_backend.IssueRef(id="12", url="u12", existed=False)

    def test_update_plan_issue(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(
            github.PlanUpdate(number=12, body_updated=True, title_updated=True, dry_run=False)
        )
        monkeypatch.setattr(github, "update_plan_issue", rec)
        result = GitHubIssueBackend(tmp_path).update_plan_issue(
            issue_id="12", title="t", body_comment="bc"
        )
        assert rec.kwargs == {
            "number": 12,
            "title": "t",
            "body_comment": "bc",
            "repo_root": tmp_path,
            "dry_run": False,
        }
        assert result == issue_backend.PlanUpdate(
            issue_id="12", body_updated=True, title_updated=True, dry_run=False
        )

    def test_update_plan_header(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(github.PlanHeaderUpdate(fields_updated=("stage",), dry_run=True))
        monkeypatch.setattr(github, "update_plan_header", rec)
        result = GitHubIssueBackend(tmp_path).update_plan_header(
            issue_id="3", fields={"stage": "implement"}, dry_run=True
        )
        assert rec.kwargs == {
            "issue": 3,
            "fields": {"stage": "implement"},
            "repo_root": tmp_path,
            "dry_run": True,
        }
        assert result == issue_backend.PlanHeaderUpdate(fields_updated=("stage",), dry_run=True)

    def test_get_plan(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pr = github.PullRequest(number=9, url="pu", is_draft=True, state="OPEN", existed=True)
        rec = _Recorder(
            github.PlanState(
                number=3, url="u3", title="t", header={"stage": "implement"}, pr=pr, state="OPEN"
            )
        )
        monkeypatch.setattr(github, "get_plan", rec)
        result = GitHubIssueBackend(tmp_path).get_plan(issue_id="3")
        assert rec.kwargs == {"number": 3, "repo_root": tmp_path}
        assert result == issue_backend.PlanState(
            id="3", url="u3", title="t", header={"stage": "implement"}, pr=pr, state="OPEN"
        )

    def test_get_plan_none_passthrough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(github, "get_plan", _Recorder(None))
        assert GitHubIssueBackend(tmp_path).get_plan(issue_id="3") is None

    def test_get_plan_body(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder("# the plan\n")
        monkeypatch.setattr(github, "get_plan_body", rec)
        result = GitHubIssueBackend(tmp_path).get_plan_body(issue_id="3")
        assert rec.kwargs == {"number": 3, "repo_root": tmp_path}
        assert result == "# the plan\n"

    def test_find_learn_issue(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(github.PlanIssue(number=8, url="u8", existed=True))
        monkeypatch.setattr(github, "find_learn_issue", rec)
        result = GitHubIssueBackend(tmp_path).find_learn_issue(run_id="RUN1")
        assert rec.kwargs == {"run_id": "RUN1", "repo_root": tmp_path}
        assert result == issue_backend.IssueRef(id="8", url="u8", existed=True)

    def test_create_learn_issue(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(github.PlanIssue(number=14, url="u14", existed=False))
        monkeypatch.setattr(github, "create_learn_issue", rec)
        result = GitHubIssueBackend(tmp_path).create_learn_issue(
            title="t", body="b", run_id="RUN1", plan_id="12", dry_run=True
        )
        assert rec.kwargs == {
            "title": "t",
            "body": "b",
            "repo_root": tmp_path,
            "run_id": "RUN1",
            "plan_number": 12,
            "dry_run": True,
        }
        assert result == issue_backend.IssueRef(id="14", url="u14", existed=False)

    def test_list_learn_issues(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder((github.LearnIssueSummary(number=5, title="t5", url="u5", body="b5"),))
        monkeypatch.setattr(github, "list_learn_issues", rec)
        result = GitHubIssueBackend(tmp_path).list_learn_issues()
        assert rec.kwargs == {"repo_root": tmp_path}
        assert result == (issue_backend.LearnIssueSummary(id="5", title="t5", url="u5", body="b5"),)

    def test_close_and_label_consolidated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(True)
        monkeypatch.setattr(github, "close_and_label_consolidated", rec)
        assert GitHubIssueBackend(tmp_path).close_and_label_consolidated(issue_id="5") is True
        assert rec.kwargs == {"issue": 5, "repo_root": tmp_path, "dry_run": False}

    def test_close_issue(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(True)
        monkeypatch.setattr(github, "close_issue", rec)
        assert GitHubIssueBackend(tmp_path).close_issue(issue_id="5", dry_run=True) is True
        assert rec.kwargs == {"number": 5, "repo_root": tmp_path, "dry_run": True}

    def test_add_issue_comment(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(github.CommentResult(posted=True))
        monkeypatch.setattr(github, "add_issue_comment", rec)
        result = GitHubIssueBackend(tmp_path).add_issue_comment(issue_id="5", body="hi")
        assert rec.kwargs == {"issue": 5, "body": "hi", "repo_root": tmp_path, "dry_run": False}
        assert result == issue_backend.CommentResult(posted=True)

    def test_find_comment_id_by_marker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rec = _Recorder(98765)
        monkeypatch.setattr(github, "find_comment_id_by_marker", rec)
        result = GitHubIssueBackend(tmp_path).find_comment_id_by_marker(
            issue_id="5", marker="<!-- m -->"
        )
        assert rec.kwargs == {"issue": 5, "marker": "<!-- m -->", "repo_root": tmp_path}
        assert result == "98765"

    def test_find_comment_id_by_marker_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(github, "find_comment_id_by_marker", _Recorder(None))
        backend = GitHubIssueBackend(tmp_path)
        assert backend.find_comment_id_by_marker(issue_id="5", marker="m") is None

    def test_upsert_marked_comment(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = _Recorder(github.CommentResult(posted=False))
        monkeypatch.setattr(github, "upsert_marked_comment", rec)
        result = GitHubIssueBackend(tmp_path).upsert_marked_comment(
            issue_id="5", marker="m", body="b", dry_run=True
        )
        assert rec.kwargs == {
            "issue": 5,
            "marker": "m",
            "body": "b",
            "repo_root": tmp_path,
            "dry_run": True,
        }
        assert result == issue_backend.CommentResult(posted=False)


class TestErrorTranslation:
    def test_github_error_wrapped_message_verbatim_cause_chained(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = github.GitHubError("objective node '9.9' not found on #252")

        def boom(**kwargs: Any) -> None:
            raise original

        monkeypatch.setattr(github, "get_plan", boom)
        with pytest.raises(issue_backend.IssueBackendError) as excinfo:
            GitHubIssueBackend(tmp_path).get_plan(issue_id="252")
        assert str(excinfo.value) == "objective node '9.9' not found on #252"
        assert excinfo.value.__cause__ is original

    def test_non_numeric_issue_id_raises_backend_error(self, tmp_path: Path) -> None:
        backend = GitHubIssueBackend(tmp_path)
        with pytest.raises(issue_backend.IssueBackendError, match="LIN-42"):
            backend.get_plan(issue_id="LIN-42")
        with pytest.raises(issue_backend.IssueBackendError, match="numeric"):
            backend.create_learn_issue(title="t", body="b", run_id=None, plan_id="abc")


class TestLateBinding:
    def test_patch_after_construction_still_intercepts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The guarantee the whole pytest suite relies on: backends delegate via attribute
        # access on the github module object at CALL time, so a monkeypatch applied after the
        # backend was constructed is still seen.
        backend = GitHubIssueBackend(tmp_path)
        rec = _Recorder(
            github.PlanState(number=1, url="u", title="t", header={}, pr=None, state="OPEN")
        )
        monkeypatch.setattr(github, "get_plan", rec)
        result = backend.get_plan(issue_id="1")
        assert result is not None
        assert result.id == "1"
        assert rec.kwargs == {"number": 1, "repo_root": tmp_path}


# The 15 issue-tier functions on the perk/github/ package (the GitHubIssueBackend substrate).
# Production code must reach them through perk.backends.issues.resolve_issue_backend, never
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
        """Source scan: outside perk/backends/issues.py (the adapter) and the perk/github/
        package itself, no module under perk/ may contain a `github.<issue-tier-fn>(` call.

        `objective_stores.py` is also allowed: `GitHubObjectiveStore.close_objective` (Node 3.4)
        deliberately reaches the issue-tier close primitive (`github.close_issue`) to retire a
        GitHub objective issue — a GitHub objective IS an issue, so its close is byte-identical to
        the issue close, and routing it through the objective adapter (not the issue backend) is the
        point of moving the close onto the `ObjectiveStore`."""
        perk_dir = Path(perk.__file__).parent
        allowed = {
            perk_dir / "backends" / "issues.py",
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
            "issue-tier calls must go through perk.backends.issues:\n" + "\n".join(offenders)
        )
