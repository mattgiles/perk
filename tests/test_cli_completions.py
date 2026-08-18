"""Tests for the plan/objective-id shell-completion surface.

Covers the callbacks (``perk/cli/completions.py``): candidates shaped as ``CompletionItem``s
with bare-id values and truncated-title help (the pinned truncation bytes), ``incomplete``
prefix filtering (leading ``#`` stripped), input order preserved (newest-created-first comes
from the list read), and the fail-soft arms — the callbacks catch ``Exception`` broadly and
return ``[]`` (a completion callback has no reporting surface; stderr mid-TAB garbles the
prompt). Plus the post-``--`` suppression integration through Click's own completion machinery
(``PlanLauncherCommand``) and the name-vocabulary wiring census over the registered CLI tree.
"""

from pathlib import Path

import click
import pytest
from click.shell_completion import CompletionItem, ShellComplete

from perk.backends import issue_backend, objective_store, resolve
from perk.backends.issue_backend import IssueBackendError
from perk.cli import completions, plan_selection
from perk.cli.cli import cli as root_cli


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


def _get_completions(args: list[str], incomplete: str = "") -> list[CompletionItem]:
    """Drive Click's own completion machinery against the registered ``cli`` root — the same
    path a live shell's ``_PERK_COMPLETE`` invocation takes."""
    return ShellComplete(root_cli, {}, "perk", "_PERK_COMPLETE").get_completions(args, incomplete)


class TestPostSeparatorSuppression:
    """``PlanLauncherCommand``: everything after the first bare ``--`` is the pi pass-through
    region — no completions are offered there and the plan-id backend read never runs."""

    @pytest.mark.parametrize("head", [["impl"], ["implement"], ["address"], ["pr", "address"]])
    def test_post_separator_offers_nothing_and_never_reads_the_backend(
        self, monkeypatch: pytest.MonkeyPatch, anchored_root: Path, head: list[str]
    ) -> None:
        backend = _wire_backend(monkeypatch, [("42", "A plan")])
        # Separator presence (not tail emptiness) is the signal: an empty tail is covered too.
        assert _get_completions([*head, "--"]) == []
        assert _get_completions([*head, "--", "--model"]) == []
        assert _get_completions([*head, "--"], "--m") == []
        assert backend.roots == []  # the resolver/backend was never touched

    @pytest.mark.parametrize("head", [["impl"], ["pr", "address"]])
    def test_pre_separator_still_completes_plan_ids(
        self, monkeypatch: pytest.MonkeyPatch, anchored_root: Path, head: list[str]
    ) -> None:
        _wire_backend(monkeypatch, [("42", "A plan"), ("7", "Another")])
        items = _get_completions(head)
        assert [(i.value, i.help) for i in items] == [("42", "A plan"), ("7", "Another")]

    def test_pre_separator_option_names_still_complete(
        self, monkeypatch: pytest.MonkeyPatch, anchored_root: Path
    ) -> None:
        backend = _wire_backend(monkeypatch, [("42", "A plan")])
        values = {i.value for i in _get_completions(["impl"], "--")}
        assert "--dry-run" in values
        assert backend.roots == []


# The name-vocabulary census: every plan/objective-selecting argument is spelled with one of
# these names today, so a future selector argument reusing a name fails the census until wired.
_PLAN_ARG_NAMES = frozenset({"plan"})
_OBJECTIVE_ARG_NAMES = frozenset({"number", "objective", "objective_arg"})
# Deliberately-unwired exceptions, keyed (command path, argument name). Initially empty.
_CENSUS_EXCEPTIONS: frozenset[tuple[str, str]] = frozenset()


def _walk_commands(command: click.Command, path: str):
    yield path, command
    if isinstance(command, click.Group):
        for name, sub in command.commands.items():
            yield from _walk_commands(sub, f"{path} {name}".strip())


class TestWiringCensus:
    """Exhaustive over the registered CLI tree: every ``click.Argument`` named ``plan`` carries
    ``complete_plan_id`` and every one named ``number``/``objective``/``objective_arg`` carries
    ``complete_objective_id`` (via the parameter's stored custom shell-complete callback),
    against the explicit — initially empty — exceptions set.

    The guarantee is the NAME VOCABULARY: a future selector argument reusing one of these names
    fails this census until wired; an argument under a different name is out of the guard's
    reach.
    """

    def _arguments(self):
        seen: set[int] = set()
        for path, command in _walk_commands(root_cli, ""):
            if id(command) in seen:  # aliases register the same Command object twice
                continue
            seen.add(id(command))
            for param in command.params:
                if isinstance(param, click.Argument):
                    yield path, command, param

    def test_every_plan_and_objective_argument_is_wired(self) -> None:
        checked = 0
        for path, _command, param in self._arguments():
            callback = getattr(param, "_custom_shell_complete", None)
            if (path, param.name) in _CENSUS_EXCEPTIONS:
                continue
            if param.name in _PLAN_ARG_NAMES:
                assert callback is completions.complete_plan_id, (
                    f"`{path}` argument {param.name!r} must carry complete_plan_id"
                )
                checked += 1
            elif param.name in _OBJECTIVE_ARG_NAMES:
                assert callback is completions.complete_objective_id, (
                    f"`{path}` argument {param.name!r} must carry complete_objective_id"
                )
                checked += 1
        # The census is live: the known wired population is present (6 plan-id arguments and
        # the objective family), not vacuously empty.
        assert checked >= 21

    def test_plan_from_issue_argument_is_deliberately_unwired(self) -> None:
        # `perk plan from ISSUE` takes a NON-perk source issue — offering perk plan ids there
        # would be wrong (the pinned deliberate negative).
        for path, _command, param in self._arguments():
            if path == "plan from" and param.name == "issue":
                assert getattr(param, "_custom_shell_complete", None) is None
                return
        pytest.fail("`plan from` ISSUE argument not found in the census walk")
