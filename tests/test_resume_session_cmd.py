"""`perk resume [TARGET]` — the root session-picker door (contracts.md §8.71).

Driven through the registered `cli` object (CliRunner) with an injected `PerkContext.for_test`
(no real chdir needed, so the shared `launch_exec_recorder` — which stubs `os.chdir` — composes
freely). Fixtures seed REAL bound worktrees; the TTY seam swaps the command module's `sys`
(CliRunner replaces `sys.stdin`, so patching `sys.stdin.isatty` alone would not reach it).
"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from perk import github, plan
from perk.backends import issue_backend, resolve
from perk.backends.github import plans
from perk.cli import plan_selection
from perk.cli.cli import cli
from perk.cli.commands import resume_session_cmd
from perk.cli.context import PerkContext
from perk.cli.ensure import UserFacingCliError
from perk.run.launch import session_resume
from perk.state import cache, session_pointers
from perk.state.run_id import mint
from perk.state.session_pointers import RunSessionEntry, SessionPointers
from perk.substrate import git
from perk.substrate.config import Config

pytestmark = pytest.mark.usefixtures("stub_launch_extension_warm")


def _fake_sys(*, stdin_tty: bool, stdout_tty: bool) -> type:
    class _Stream:
        def __init__(self, tty: bool) -> None:
            self._tty = tty

        def isatty(self) -> bool:
            return self._tty

    class _Sys:
        stdin = _Stream(stdin_tty)
        stdout = _Stream(stdout_tty)

    return _Sys


def _tty(monkeypatch, *, stdin: bool = True, stdout: bool = True) -> None:
    monkeypatch.setattr(resume_session_cmd, "sys", _fake_sys(stdin_tty=stdin, stdout_tty=stdout))


def _ref(pr_id: str) -> plan.PlanRef:
    return plan.PlanRef(
        provider="github", pr_id=pr_id, url=f"https://gh/o/r/issues/{pr_id}", labels=("perk:plan",)
    )


def _state(pr_id: str, *, header: dict | None = None) -> plans.PlanState:
    """A github-native plan state whose reconstructed ref EQUALS `_ref(pr_id)` (the worktree
    binding the validator compares against)."""
    return plans.PlanState(
        number=int(pr_id),
        url=f"https://gh/o/r/issues/{pr_id}",
        title="T",
        header=header or {},
        pr=None,
        has_plan_header=True,
    )


def _bound_worktree(root: Path, name: str, *, branch: str, bound_to: str | None) -> Path:
    wt = root / ".worktrees" / name
    git.worktree_add(root, wt, branch=branch, create_branch=True)
    if bound_to is not None:
        cache.write_plan_ref(wt, _ref(bound_to))
    return wt


def _github_plan(monkeypatch, pr_id: str) -> list[str]:
    """Fake the GitHub plan read for `pr_id` + record `require_github` calls."""
    monkeypatch.setattr(plans, "get_plan", lambda **k: _state(pr_id))
    calls: list[str] = []
    monkeypatch.setattr(
        resume_session_cmd, "require_github", lambda ctx: calls.append("require_github")
    )
    return calls


def _invoke(root: Path, args: list[str], *, cwd: Path | None = None):
    ctx = PerkContext.for_test(
        cwd=cwd if cwd is not None else root,
        repo_root=cwd if cwd is not None else root,
        config=Config(worktree_root=root / ".worktrees"),
    )
    return CliRunner().invoke(cli, ["resume", *args], obj=ctx)


def _assert_nothing_written(root: Path) -> None:
    assert not cache.plan_ref_path(root).exists()
    workflow = root / ".perk" / "workflow"
    assert not workflow.exists() or not any(workflow.rglob("handoff*"))


def _run_record(root: Path, rid: str, *names: str) -> list[RunSessionEntry]:
    """A real `session-pointers.json` for `rid` under `root` whose entries point at REAL tmp
    paths (a `.jsonl` file + a cwd directory each); `at` ascends in list order."""
    entries: list[RunSessionEntry] = []
    for n, name in enumerate(names, start=1):
        checkout = root / f"recorded-{name}"
        checkout.mkdir(exist_ok=True)
        session_file = root / f"{name}.jsonl"
        session_file.write_text("{}\n", encoding="utf-8")
        entries.append(
            RunSessionEntry(
                pi_session_id=f"{name}.jsonl",
                session_file=str(session_file),
                cwd=str(checkout),
                at=f"2026-06-01T0{n}:00:00.000Z",
            )
        )
    session_pointers.write_session_pointers(
        root, rid, SessionPointers(run_id=rid, sessions=tuple(entries))
    )
    return entries


def _no_selector_reads(monkeypatch) -> None:
    """Raising fakes proving the run arm reads no `[worktree]` config, no backend, no `gh`,
    and never reaches `select_plan`."""

    def _boom(*args, **kwargs):
        raise AssertionError("the run arm must not read selector config, a backend, or gh")

    monkeypatch.setattr(resume_session_cmd, "load_main_config", _boom)
    monkeypatch.setattr(resume_session_cmd, "select_plan", _boom)
    monkeypatch.setattr(resume_session_cmd, "require_github", _boom)
    monkeypatch.setattr(resolve, "resolve_issue_backend_id", _boom)


# --- _require_terminal: the typed code ------------------------------------------------------


def test_require_terminal_passes_on_both_ttys(monkeypatch):
    _tty(monkeypatch)
    resume_session_cmd._require_terminal()  # must not raise


@pytest.mark.parametrize(("stdin", "stdout"), [(False, True), (True, False), (False, False)])
def test_require_terminal_refuses_not_a_tty(monkeypatch, stdin, stdout):
    _tty(monkeypatch, stdin=stdin, stdout=stdout)
    with pytest.raises(UserFacingCliError) as exc:
        resume_session_cmd._require_terminal()
    assert exc.value.error_type == "not_a_tty"
    assert "pass --dry-run" in str(exc.value)


# --- the terminal-only rule at the command boundary ------------------------------------------


def test_non_tty_without_dry_run_fails_fast_before_any_config_or_backend_read(
    git_repo, monkeypatch, launch_exec_recorder
):
    # The default CliRunner is non-TTY. The raising fakes prove NO config load and NO backend
    # resolution happen before the refusal (only `require_repo` runs first).
    def _no_config(root):
        raise AssertionError("config must not load before the TTY check")

    def _no_backend(root):
        raise AssertionError("the backend must not resolve before the TTY check")

    monkeypatch.setattr(plan_selection, "load_main_config", _no_config)
    monkeypatch.setattr(resume_session_cmd, "load_main_config", _no_config)
    monkeypatch.setattr(resolve, "resolve_issue_backend_id", _no_backend)
    result = _invoke(git_repo, ["42"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Error: perk resume opens Pi's interactive session picker" in result.stderr
    assert "pass --dry-run" in result.stderr
    assert "not_a_tty" not in result.stderr  # the human surface never renders the code
    assert launch_exec_recorder.calls == [] and launch_exec_recorder.chdirs == []


def test_dry_run_under_non_tty_previews_and_writes_nothing(
    git_repo, monkeypatch, launch_exec_recorder
):
    result = _invoke(git_repo, ["--dry-run"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {
        "success": True,
        "checkout": str(git_repo),
        "session_file": None,
        "agent_dir": str(launch_exec_recorder.agent_dir),
        "agent_dir_source": "env",
        "argv": ["pi", "--resume"],
        "dry_run": True,
    }
    assert "resume --dry-run (session picker" in result.stderr
    assert f"  checkout: {git_repo}" in result.stderr
    assert "  command:  pi --resume" in result.stderr
    assert launch_exec_recorder.calls == []
    _assert_nothing_written(git_repo)


# --- the target table through the door (TTY fake + exec recorder) -----------------------------


def _assert_exec_in(recorder, checkout: Path) -> None:
    assert recorder.chdirs == [checkout]
    program, argv, env = recorder.calls[0]
    assert program == recorder.pi_path
    assert argv == ("pi", "--resume")
    assert "--approve" not in argv
    assert "PERK_RUN_ID" not in env


def test_bare_opens_the_picker_in_the_invocation_root(git_repo, monkeypatch, launch_exec_recorder):
    _tty(monkeypatch)
    monkeypatch.setenv("PERK_RUN_ID", "01OPERATOR")
    result = _invoke(git_repo, [])
    assert result.exit_code == 0, result.output
    _assert_exec_in(launch_exec_recorder, git_repo)
    assert f"opening Pi's session picker in {git_repo}: pi --resume" in result.stderr
    assert result.stdout == ""
    assert "skills \u00b7" not in result.stderr  # no launch banner: a picker is not a stage launch
    _assert_nothing_written(git_repo)


def test_worktree_name_opens_the_named_checkout(git_repo, monkeypatch, launch_exec_recorder):
    _tty(monkeypatch)
    wt = _bound_worktree(git_repo, "plan-42", branch="plan-42", bound_to="42")
    result = _invoke(git_repo, ["--worktree", "plan-42"])
    assert result.exit_code == 0, result.output
    _assert_exec_in(launch_exec_recorder, wt)


def test_worktree_root_opens_the_main_checkout(git_repo, monkeypatch, launch_exec_recorder):
    _tty(monkeypatch)
    result = _invoke(git_repo, ["--worktree", "root"])
    assert result.exit_code == 0, result.output
    _assert_exec_in(launch_exec_recorder, git_repo)


def test_plan_target_opens_the_bound_worktree(git_repo, monkeypatch, launch_exec_recorder):
    _tty(monkeypatch)
    calls = _github_plan(monkeypatch, "42")
    wt = _bound_worktree(git_repo, "plan-42", branch="plan-42", bound_to="42")
    result = _invoke(git_repo, ["42"])
    assert result.exit_code == 0, result.output
    assert calls == ["require_github"]  # the GitHub backend authenticates through `gh`
    _assert_exec_in(launch_exec_recorder, wt)
    assert "looking up plan #42" in result.stderr
    _assert_nothing_written(git_repo)


def test_plan_target_with_its_own_worktree_name(git_repo, monkeypatch, launch_exec_recorder):
    _tty(monkeypatch)
    _github_plan(monkeypatch, "42")
    wt = _bound_worktree(git_repo, "plan-42", branch="plan-42", bound_to="42")
    result = _invoke(git_repo, ["42", "--worktree", "plan-42"])
    assert result.exit_code == 0, result.output
    _assert_exec_in(launch_exec_recorder, wt)


def test_plan_target_with_another_plans_checkout_refuses_branch_mismatch(
    git_repo, monkeypatch, launch_exec_recorder
):
    _tty(monkeypatch)
    _github_plan(monkeypatch, "42")
    _bound_worktree(git_repo, "other", branch="plan-43", bound_to="43")
    result = _invoke(git_repo, ["42", "--worktree", "other"])
    assert result.exit_code == 1
    assert "Error:" in result.stderr and "expected 'plan-42'" in result.stderr
    assert launch_exec_recorder.calls == []


def test_plan_target_with_worktree_root_is_invalid_input(
    git_repo, monkeypatch, launch_exec_recorder
):
    _tty(monkeypatch)
    _github_plan(monkeypatch, "42")
    result = _invoke(git_repo, ["42", "--worktree", "root"])
    assert result.exit_code == 1
    assert "never a plan's implementation worktree" in result.stderr
    assert launch_exec_recorder.calls == []


def test_plan_target_missing_worktree_refuses_not_found(
    git_repo, monkeypatch, launch_exec_recorder
):
    _tty(monkeypatch)
    _github_plan(monkeypatch, "42")
    result = _invoke(git_repo, ["42"])
    assert result.exit_code == 1
    assert "no checkout for plan #42" in result.stderr
    assert "perk implement 42 creates or restores it" in result.stderr
    assert launch_exec_recorder.calls == []


@pytest.mark.parametrize("selector", ["#42", "https://github.com/o/r/issues/42"])
def test_hash_and_issue_url_selectors_route_through_select_plan(
    git_repo, monkeypatch, launch_exec_recorder, selector
):
    _tty(monkeypatch)
    _github_plan(monkeypatch, "42")
    wt = _bound_worktree(git_repo, "plan-42", branch="plan-42", bound_to="42")
    result = _invoke(git_repo, [selector])
    assert result.exit_code == 0, result.output
    _assert_exec_in(launch_exec_recorder, wt)


def test_pr_url_selector_peels_to_the_plan(git_repo, monkeypatch, launch_exec_recorder):
    _tty(monkeypatch)
    monkeypatch.setattr(resume_session_cmd, "require_github", lambda ctx: None)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _state("42", header={"pr": 55}))
    monkeypatch.setattr(
        github,
        "get_pr",
        lambda **k: github.PullRequest(
            number=55, url="u/pr/55", is_draft=True, state="OPEN", existed=True, head_ref="plan-42"
        ),
    )
    wt = _bound_worktree(git_repo, "plan-42", branch="plan-42", bound_to="42")
    result = _invoke(git_repo, ["https://github.com/o/r/pull/55"])
    assert result.exit_code == 0, result.output
    assert "PR #55 \u2192 plan #42" in result.stderr
    _assert_exec_in(launch_exec_recorder, wt)


# --- backend-conditional auth ----------------------------------------------------------------


def test_linear_backend_skips_require_github(git_repo, monkeypatch, launch_exec_recorder):
    _tty(monkeypatch)
    (git_repo / ".perk").mkdir(exist_ok=True)
    (git_repo / ".perk/config.toml").write_text('[issues]\nbackend = "linear"\n', encoding="utf-8")

    def _boom(ctx):
        raise AssertionError("a Linear-backed repo must not require gh auth")

    monkeypatch.setattr(resume_session_cmd, "require_github", _boom)

    class _FakeBackend:
        backend_id = "linear"

        def get_plan(self, *, issue_id: str):
            return issue_backend.PlanState(
                id=issue_id,
                url=f"https://linear.app/acme/issue/{issue_id}/x",
                title="T",
                header={},
                pr=None,
                state="OPEN",
                has_plan_header=True,
            )

    monkeypatch.setattr(resolve, "resolve_issue_backend", lambda _root: _FakeBackend())
    wt = git_repo / ".worktrees" / "plan-ENG-9"
    git.worktree_add(git_repo, wt, branch="plan-ENG-9", create_branch=True)
    cache.write_plan_ref(
        wt,
        plan.PlanRef(
            provider="linear",
            pr_id="ENG-9",
            url="https://linear.app/acme/issue/ENG-9/x",
            labels=("perk:plan",),
        ),
    )
    result = _invoke(git_repo, ["ENG-9"])
    assert result.exit_code == 0, result.output
    _assert_exec_in(launch_exec_recorder, wt)


# --- invoked from inside a linked worktree -----------------------------------------------------


def test_bare_from_linked_worktree_opens_that_worktree(git_repo, monkeypatch, launch_exec_recorder):
    _tty(monkeypatch)
    cache.write_plan_ref(git_repo, _ref("99"))  # a FOREIGN main-root selector: never read
    wt = _bound_worktree(git_repo, "plan-42", branch="plan-42", bound_to="42")
    result = _invoke(git_repo, [], cwd=wt)
    assert result.exit_code == 0, result.output
    _assert_exec_in(launch_exec_recorder, wt)


def test_plan_from_linked_worktree_resolves_under_the_main_worktree_root(
    git_repo, monkeypatch, launch_exec_recorder
):
    _tty(monkeypatch)
    _github_plan(monkeypatch, "42")
    wt42 = _bound_worktree(git_repo, "plan-42", branch="plan-42", bound_to="42")
    wt9 = _bound_worktree(git_repo, "plan-9", branch="plan-9", bound_to="9")
    result = _invoke(git_repo, ["42"], cwd=wt9)
    assert result.exit_code == 0, result.output
    _assert_exec_in(launch_exec_recorder, wt42)


# --- failure boundary --------------------------------------------------------------------------


def test_not_a_repo_exits_2_even_on_a_non_tty():
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init; the default runner is non-TTY
        result = runner.invoke(cli, ["resume"])
    assert result.exit_code == 2
    assert "Not a git repository" in result.stderr


def test_plan_not_found_exits_1(git_repo, monkeypatch, launch_exec_recorder):
    _tty(monkeypatch)
    monkeypatch.setattr(resume_session_cmd, "require_github", lambda ctx: None)
    monkeypatch.setattr(plans, "get_plan", lambda **k: None)
    monkeypatch.setattr(github, "get_pr", lambda **k: None)  # hermetic fallback-probe miss
    result = _invoke(git_repo, ["999"])
    assert result.exit_code == 1
    assert "Plan issue #999 not found" in result.stderr
    assert launch_exec_recorder.calls == []


def test_headerless_issue_refuses_kind_mismatch(git_repo, monkeypatch, launch_exec_recorder):
    _tty(monkeypatch)
    monkeypatch.setattr(resume_session_cmd, "require_github", lambda ctx: None)
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **k: plans.PlanState(number=63, url="u/63", title="T", header={}, pr=None),
    )
    monkeypatch.setattr(github, "get_pr", lambda **k: None)
    result = _invoke(git_repo, ["63"])
    assert result.exit_code == 1
    assert "Error:" in result.stderr
    assert launch_exec_recorder.calls == []


def test_backend_error_exits_1_with_resume_failed(git_repo, monkeypatch, launch_exec_recorder):
    _tty(monkeypatch)
    monkeypatch.setattr(resume_session_cmd, "require_github", lambda ctx: None)

    def _raise(**k):
        raise issue_backend.IssueBackendError("backend unavailable")

    monkeypatch.setattr(plans, "get_plan", _raise)
    result = _invoke(git_repo, ["42"])
    assert result.exit_code == 1
    assert "resume failed" in result.stderr and "backend unavailable" in result.stderr
    assert launch_exec_recorder.calls == []


def test_invalid_worktree_name_is_invalid_input(git_repo, monkeypatch, launch_exec_recorder):
    _tty(monkeypatch)
    result = _invoke(git_repo, ["--worktree", "../x"])
    assert result.exit_code == 1
    assert "Invalid worktree name" in result.stderr
    assert launch_exec_recorder.calls == []


def test_help_renders_the_target_table_and_examples():
    result = CliRunner().invoke(cli, ["resume", "--help"])
    assert result.exit_code == 0
    assert "Browse and reopen Pi conversations for a checkout (pi --resume)" in result.output
    for line in (
        "perk resume --worktree NAME",
        "perk resume --worktree root",
        "perk resume PLAN --worktree NAME",
        "perk resume PLAN --worktree root  refused",
        "perk resume RUN_ID                the run's newest recorded conversation",
        "perk resume RUN_ID --worktree NAME  refused: a run id pins its checkout",
        "perk resume 42 --worktree plan-42-b",
        "perk resume 42 --dry-run",
        "perk resume 01ARZ3NDEKTSV4RRFFQ69G5FAV  # reopen that run's conversation",
    ):
        assert line in result.output, line
    assert "no --approve" in result.output
    assert "TARGET may also be a perk run id" in result.output
    assert "Run ids are not yet accepted" not in result.output


# --- the run arm: routing by grammar -----------------------------------------------------------


@pytest.mark.parametrize("selector", ["42", "#42", "ENG-1", "https://github.com/o/r/issues/42"])
def test_plan_selectors_route_to_select_plan_never_the_run_arm(
    git_repo, monkeypatch, launch_exec_recorder, selector
):
    _tty(monkeypatch)
    monkeypatch.setattr(resume_session_cmd, "require_github", lambda ctx: None)
    seen: list[str] = []

    def _select(main_root, raw, **kwargs):
        seen.append(raw)
        raise UserFacingCliError(f"Plan {raw} not found", error_type="plan_not_found")

    def _no_run_arm(main_root, run_id):
        raise AssertionError("a plan selector must never reach the run arm")

    monkeypatch.setattr(resume_session_cmd, "select_plan", _select)
    monkeypatch.setattr(session_resume, "resolve_run_session", _no_run_arm)
    result = _invoke(git_repo, [selector])
    assert result.exit_code == 1
    assert seen == [selector]
    assert launch_exec_recorder.calls == []


def _assert_run_exec(recorder, entry: RunSessionEntry) -> None:
    assert recorder.chdirs == [Path(entry.cwd)]
    program, argv, env = recorder.calls[0]
    assert program == recorder.pi_path
    assert argv == ("pi", "--session", entry.session_file)
    assert "--approve" not in argv
    assert "PERK_RUN_ID" not in env


@pytest.mark.parametrize("suffix", ["", ".1.2"])
def test_run_id_routes_to_the_run_arm_offline(git_repo, monkeypatch, launch_exec_recorder, suffix):
    # No selector config, no backend, no gh, no select_plan (raising fakes). The agent-dir
    # resolution is NOT claimed absent here — the engine's config-arm test covers that parity.
    _tty(monkeypatch)
    _no_selector_reads(monkeypatch)
    monkeypatch.setenv("PERK_RUN_ID", "01OPERATOR")
    rid = f"{mint()}{suffix}"
    (entry,) = _run_record(git_repo, rid, "only")
    result = _invoke(git_repo, [rid])
    assert result.exit_code == 0, result.output
    _assert_run_exec(launch_exec_recorder, entry)
    assert result.stderr.splitlines() == [
        f"reopening run {rid}'s recorded conversation only.jsonl in {entry.cwd}: "
        f"pi --session {entry.session_file}"
    ]
    assert result.stdout == ""
    _assert_nothing_written(git_repo)


def test_malicious_suffix_fails_the_grammar_and_falls_to_select_plan(
    git_repo, monkeypatch, launch_exec_recorder
):
    _tty(monkeypatch)
    monkeypatch.setattr(resume_session_cmd, "require_github", lambda ctx: None)
    monkeypatch.setattr(plans, "get_plan", lambda **k: None)
    monkeypatch.setattr(github, "get_pr", lambda **k: None)

    def _no_run_arm(main_root, run_id):
        raise AssertionError("an off-grammar id must never reach the run arm")

    monkeypatch.setattr(session_resume, "resolve_run_session", _no_run_arm)
    result = _invoke(git_repo, [f"{mint()}./../x"])
    assert result.exit_code == 1
    assert "Error:" in result.stderr
    assert launch_exec_recorder.calls == []
    assert not cache.runs_dir(git_repo).exists()


# --- the run arm: refusals through the door ----------------------------------------------------


def test_run_id_with_worktree_is_refused_before_any_config_load(
    git_repo, monkeypatch, launch_exec_recorder
):
    _tty(monkeypatch)
    _no_selector_reads(monkeypatch)

    def _no_record_read(root, run_id):
        raise AssertionError("--worktree is refused before the record is read")

    monkeypatch.setattr(session_pointers, "read_session_pointers", _no_record_read)
    result = _invoke(git_repo, [mint(), "--worktree", "plan-42"])
    assert result.exit_code == 1
    assert "drop --worktree" in result.stderr
    assert launch_exec_recorder.calls == []


def test_run_not_found_is_a_typed_refusal_through_the_door(
    git_repo, monkeypatch, launch_exec_recorder
):
    _tty(monkeypatch)
    _no_selector_reads(monkeypatch)
    rid = mint()
    result = _invoke(git_repo, [rid])
    assert result.exit_code == 1
    assert f"Error: no recorded Pi conversation for run {rid}" in result.stderr
    assert "perk state prune" in result.stderr
    assert "Traceback" not in result.stderr
    assert launch_exec_recorder.calls == []
    _assert_nothing_written(git_repo)


def test_non_tty_without_dry_run_fails_fast_for_a_run_id(
    git_repo, monkeypatch, launch_exec_recorder
):
    def _no_record_read(root, run_id):
        raise AssertionError("the record must not be read before the TTY check")

    monkeypatch.setattr(session_pointers, "read_session_pointers", _no_record_read)
    result = _invoke(git_repo, [mint()])  # the default CliRunner is non-TTY
    assert result.exit_code == 1
    assert "pass --dry-run" in result.stderr
    assert launch_exec_recorder.calls == []


# --- the run arm: dry-run + collisions ----------------------------------------------------------


def test_run_id_dry_run_under_non_tty_previews_the_session_file(
    git_repo, monkeypatch, launch_exec_recorder
):
    _no_selector_reads(monkeypatch)
    rid = mint()
    (entry,) = _run_record(git_repo, rid, "only")
    result = _invoke(git_repo, [rid, "--dry-run"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {
        "success": True,
        "checkout": entry.cwd,
        "session_file": entry.session_file,
        "agent_dir": str(launch_exec_recorder.agent_dir),
        "agent_dir_source": "env",
        "argv": ["pi", "--session", entry.session_file],
        "dry_run": True,
    }
    assert "resume --dry-run (recorded session" in result.stderr
    assert f"  session:  {entry.session_file}" in result.stderr
    assert launch_exec_recorder.calls == []
    _assert_nothing_written(git_repo)


def test_run_id_with_several_conversations_opens_the_newest_and_lists_the_others(
    git_repo, monkeypatch, launch_exec_recorder
):
    _tty(monkeypatch)
    _no_selector_reads(monkeypatch)
    rid = mint()
    older, newest = _run_record(git_repo, rid, "older", "newest")
    result = _invoke(git_repo, [rid])
    assert result.exit_code == 0, result.output
    _assert_run_exec(launch_exec_recorder, newest)
    assert result.stderr.splitlines() == [
        f"run {rid} has 2 recorded conversations — opening the newest (newest.jsonl); "
        "others: older.jsonl",
        f"reopening run {rid}'s recorded conversation newest.jsonl in {newest.cwd}: "
        f"pi --session {newest.session_file}",
    ]
    assert older.pi_session_id == "older.jsonl"
