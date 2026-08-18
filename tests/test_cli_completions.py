"""Tests for the plan/objective-id shell-completion callbacks (``perk/cli/completions.py``).

Covers: candidates shaped as ``CompletionItem``s with bare-id values and truncated-title help
(the pinned truncation bytes), ``incomplete`` prefix filtering (leading ``#`` stripped), input
order preserved (newest-created-first comes from the list read), and the fail-soft arms — the
callbacks catch ``Exception`` broadly and return ``[]`` (a completion callback has no reporting
surface; stderr mid-TAB garbles the prompt).
"""

from pathlib import Path

import pytest

from perk.backends import issue_backend, objective_store, resolve
from perk.backends.issue_backend import IssueBackendError
from perk.cli import completions, plan_selection


class _FakeIssueBackend:
    """Rows in, ``PlanSummary`` tuple out; an ``Exception`` payload raises (the fail-loud list
    read the callback boundary must swallow)."""

    def __init__(self, rows: list[tuple[str, str]] | Exception) -> None:
        self.rows = rows
        self.roots: list[Path] = []

    def list_open_plans(self) -> tuple[issue_backend.PlanSummary, ...]:
        if isinstance(self.rows, Exception):
            raise self.rows
        return tuple(issue_backend.PlanSummary(id=i, title=t) for i, t in self.rows)


class _FakeObjectiveStore:
    def __init__(self, rows: list[tuple[str, str]] | Exception) -> None:
        self.rows = rows

    def list_open_objectives(self) -> tuple[objective_store.ObjectiveSummary, ...]:
        if isinstance(self.rows, Exception):
            raise self.rows
        return tuple(objective_store.ObjectiveSummary(id=i, title=t) for i, t in self.rows)


@pytest.fixture
def anchored_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Pin the cwd→main-root resolution to ``tmp_path`` (no git shelling in the callback path)."""
    monkeypatch.setattr(plan_selection, "main_repo_root", lambda root: tmp_path)
    return tmp_path


def _wire_backend(
    monkeypatch: pytest.MonkeyPatch, rows: list[tuple[str, str]] | Exception
) -> _FakeIssueBackend:
    backend = _FakeIssueBackend(rows)

    def _resolver(root: Path) -> _FakeIssueBackend:
        backend.roots.append(root)
        return backend

    monkeypatch.setattr(resolve, "resolve_issue_backend", _resolver)
    return backend


def _wire_store(
    monkeypatch: pytest.MonkeyPatch, rows: list[tuple[str, str]] | Exception
) -> _FakeObjectiveStore:
    store = _FakeObjectiveStore(rows)
    monkeypatch.setattr(resolve, "resolve_objective_store", lambda root: store)
    return store


class TestPlanCompletion:
    def test_candidates_are_bare_ids_with_title_help_in_input_order(
        self, monkeypatch: pytest.MonkeyPatch, anchored_root: Path
    ) -> None:
        backend = _wire_backend(
            monkeypatch, [("45", "Newest plan"), ("ENG-9", "Linear plan"), ("41", "Oldest plan")]
        )
        items = completions.complete_plan_id(None, None, "")  # ty: ignore[invalid-argument-type]
        # The list read's newest-created-first order is preserved verbatim.
        assert [(i.value, i.help) for i in items] == [
            ("45", "Newest plan"),
            ("ENG-9", "Linear plan"),
            ("41", "Oldest plan"),
        ]
        # The main-root anchoring: the resolver saw the pinned root, never ctx state.
        assert backend.roots == [anchored_root]

    def test_prefix_filter_strips_leading_hash_and_whitespace(
        self, monkeypatch: pytest.MonkeyPatch, anchored_root: Path
    ) -> None:
        _wire_backend(monkeypatch, [("45", "A"), ("41", "B"), ("ENG-4", "C")])
        items = completions.complete_plan_id(None, None, " #4")  # ty: ignore[invalid-argument-type]
        assert [i.value for i in items] == ["45", "41"]

    def test_truncation_bytes_pinned(
        self, monkeypatch: pytest.MonkeyPatch, anchored_root: Path
    ) -> None:
        exactly_60 = "t" * 60
        longer_61 = "u" * 61
        _wire_backend(monkeypatch, [("1", exactly_60), ("2", longer_61)])
        items = completions.complete_plan_id(None, None, "")  # ty: ignore[invalid-argument-type]
        # A <=60-char title passes verbatim; a longer one is title[:59] + "…" — exactly 60.
        assert items[0].help == exactly_60
        assert items[1].help == "u" * 59 + "\u2026"
        assert len(items[1].help) == 60

    def test_resolver_failure_fails_soft_to_no_candidates(
        self, monkeypatch: pytest.MonkeyPatch, anchored_root: Path
    ) -> None:
        def _raising_resolver(root: Path) -> _FakeIssueBackend:
            raise IssueBackendError("unknown issue backend")

        monkeypatch.setattr(resolve, "resolve_issue_backend", _raising_resolver)
        assert completions.complete_plan_id(None, None, "") == []  # ty: ignore[invalid-argument-type]

    def test_backend_list_failure_fails_soft_to_no_candidates(
        self, monkeypatch: pytest.MonkeyPatch, anchored_root: Path
    ) -> None:
        _wire_backend(monkeypatch, IssueBackendError("HTTP 500"))
        assert completions.complete_plan_id(None, None, "") == []  # ty: ignore[invalid-argument-type]

    def test_cwd_resolution_failure_fails_soft_to_no_candidates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The not-a-repo/vanished-cwd arm: even the root resolution failing yields [].
        def _raising_root(root: Path) -> Path:
            raise OSError("no such directory")

        monkeypatch.setattr(plan_selection, "main_repo_root", _raising_root)
        assert completions.complete_plan_id(None, None, "") == []  # ty: ignore[invalid-argument-type]


class TestObjectiveCompletion:
    def test_candidates_are_ids_with_title_help(
        self, monkeypatch: pytest.MonkeyPatch, anchored_root: Path
    ) -> None:
        _wire_store(monkeypatch, [("252", "Objective A"), ("proj-abc", "Objective B")])
        items = completions.complete_objective_id(None, None, "")  # ty: ignore[invalid-argument-type]
        assert [(i.value, i.help) for i in items] == [
            ("252", "Objective A"),
            ("proj-abc", "Objective B"),
        ]

    def test_prefix_filter_strips_leading_hash(
        self, monkeypatch: pytest.MonkeyPatch, anchored_root: Path
    ) -> None:
        _wire_store(monkeypatch, [("252", "A"), ("31", "B")])
        items = completions.complete_objective_id(None, None, "#2")  # ty: ignore[invalid-argument-type]
        assert [i.value for i in items] == ["252"]

    def test_store_failure_fails_soft_to_no_candidates(
        self, monkeypatch: pytest.MonkeyPatch, anchored_root: Path
    ) -> None:
        _wire_store(monkeypatch, IssueBackendError("down"))
        assert completions.complete_objective_id(None, None, "") == []  # ty: ignore[invalid-argument-type]
