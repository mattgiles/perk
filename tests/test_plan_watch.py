"""`perk plan watch` — the hunk watch launcher.

Driven through the registered `cli` object (CliRunner). The process boundary is stubbed on the
module under test (`watch_cmd.os.chdir` / `watch_cmd.os.execve` recorders), so every "exec'd"
assertion here is explicitly a **stubbed argv/env-construction test** — the real exec never
returns. The git/cache seams are stubbed as module functions (`git.fetch`, `git.merge_base`,
…), keeping the suite offline and deterministic.
"""

import dataclasses
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from perk import plan
from perk.cli.cli import cli
from perk.cli.commands.plan import watch_cmd
from perk.delivery.layer import LayerContext
from perk.state import cache
from perk.substrate import git
from perk.substrate.git import GitError

MERGE_SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
PARENT_SHA = "e" * 40
HUNK_PATH = "/opt/hunk/bin/hunk"
EXT_PATH = "/opt/perk-install/_hunk/perkFeedback.ts"


def _hunk_argv(*tail: str, sha: str | None = MERGE_SHA[:12]) -> list[str]:
    """The expected exec argv: perk-owned args first, then user pass-through."""
    return ["hunk", "diff", *([sha] if sha else []), "--watch", "--extension", EXT_PATH, *tail]


def _plan_ref(**overrides) -> plan.PlanRef:
    ref = plan.PlanRef(
        provider="github", pr_id="42", url="https://gh/o/r/issues/42", labels=("perk:plan",)
    )
    return dataclasses.replace(ref, **overrides)


def _layer_context() -> LayerContext:
    return LayerContext(
        objective_id="10",
        node_id="1.2",
        plan_id="42",
        delivery_lineage="01JB0000000000000000000000",
        predecessor_plan_id="41",
        base="main",
        parent_branch="plan-41",
        branch="plan-42",
    )


@pytest.fixture
def watch_env(tmp_path, monkeypatch, unborn_git_repo_factory):
    """A real repo at cwd, a `plan-42` worktree dir, and the stubbed process/git seams.

    Ordering matters: `monkeypatch.chdir` first, THEN the `os.chdir` stub — monkeypatch undoes
    in LIFO order, so the real `os.chdir` is restored before the cwd restore runs.
    """
    unborn_git_repo_factory(tmp_path)
    monkeypatch.chdir(tmp_path)
    worktree = tmp_path / ".worktrees" / "plan-42"
    worktree.mkdir(parents=True)

    # Every git fake records the REPO it was pointed at (resolved, so macOS /tmp symlink
    # prefixes never skew comparisons) plus an `ops` name log pinning the operation order —
    # the diff-base ladder must run against the PLAN WORKTREE, never the invocation root.
    calls = SimpleNamespace(
        chdir=[], execs=[], envs=[], fetches=[], merge_bases=[], trunks=[], ops=[]
    )
    monkeypatch.setattr(watch_cmd, "hunk_cli_path", lambda: HUNK_PATH)

    def _resolve_ext():
        calls.ops.append("resolve-extension")
        return Path(EXT_PATH)

    monkeypatch.setattr(watch_cmd, "hunk_feedback_extension_path", _resolve_ext)

    def _chdir(p):
        calls.ops.append("chdir")
        calls.chdir.append(Path(p))

    monkeypatch.setattr(watch_cmd.os, "chdir", _chdir)

    def _execve(path, argv, env):
        calls.execs.append((path, list(argv)))
        calls.envs.append(dict(env))

    monkeypatch.setattr(watch_cmd.os, "execve", _execve)

    def _fetch(repo, **k):
        calls.ops.append("fetch")
        calls.fetches.append(Path(repo).resolve())

    monkeypatch.setattr(git, "fetch", _fetch)

    def _trunk(repo, **k):
        calls.ops.append("trunk")
        calls.trunks.append(Path(repo).resolve())
        return "main"

    monkeypatch.setattr(git, "detect_trunk_branch", _trunk)

    def _merge_base(repo, a, b):
        calls.ops.append("merge_base")
        calls.merge_bases.append((Path(repo).resolve(), a, b))
        return MERGE_SHA

    monkeypatch.setattr(git, "merge_base", _merge_base)
    monkeypatch.setattr(git, "resolve_commit", lambda repo, ref: None)
    return SimpleNamespace(root=tmp_path, worktree=worktree, calls=calls)


def _invoke(args):
    return CliRunner().invoke(cli, ["plan", "watch", *args])


# --- the happy path + the diff-base ladder ----------------------------------------------


def test_since_base_happy_path_execs_hunk_in_the_worktree(watch_env):
    wt = watch_env.worktree.resolve()
    result = _invoke(["42"])
    assert result.exit_code == 0, result.output
    # The absolute probed path is exec'd (argv[0] stays the conventional bare name).
    assert watch_env.calls.execs == [(HUNK_PATH, _hunk_argv())]
    assert [p.resolve() for p in watch_env.calls.chdir] == [wt]
    # Every diff-base git op ran against the PLAN WORKTREE, fetch before merge-base; the
    # bundled extension resolves BEFORE the chdir (the shadowing defense).
    assert watch_env.calls.fetches == [wt]
    assert watch_env.calls.merge_bases == [(wt, "HEAD", "origin/main")]
    assert watch_env.calls.ops == ["resolve-extension", "trunk", "fetch", "merge_base", "chdir"]


def test_unpinned_base_consults_the_detected_trunk(watch_env):
    result = _invoke(["42"])
    assert result.exit_code == 0, result.output
    assert watch_env.calls.trunks == [watch_env.worktree.resolve()]  # no plan-ref -> trunk
    assert [(a, b) for _r, a, b in watch_env.calls.merge_bases] == [("HEAD", "origin/main")]


def test_pinned_base_wins_over_the_trunk(watch_env):
    cache.write_plan_ref(watch_env.worktree, _plan_ref(base="release/1.x"))
    result = _invoke(["42"])
    assert result.exit_code == 0, result.output
    assert [(a, b) for _r, a, b in watch_env.calls.merge_bases] == [("HEAD", "origin/release/1.x")]
    assert watch_env.calls.trunks == []  # the pinned base preempts trunk detection


def test_stacked_layer_arm_uses_the_recorded_parent(watch_env, monkeypatch):
    monkeypatch.setattr(cache, "read_layer_parent_sha", lambda root: PARENT_SHA)
    monkeypatch.setattr(git, "resolve_commit", lambda repo, ref: PARENT_SHA)
    result = _invoke(["42"])
    assert result.exit_code == 0, result.output
    assert watch_env.calls.execs == [(HUNK_PATH, _hunk_argv(sha=PARENT_SHA[:12]))]
    # The layer was cut from the recorded parent: no fetch, no merge-base needed.
    assert watch_env.calls.fetches == [] and watch_env.calls.merge_bases == []


def test_unresolvable_recorded_parent_falls_through_to_since_base(watch_env, monkeypatch):
    monkeypatch.setattr(cache, "read_layer_parent_sha", lambda root: PARENT_SHA)
    result = _invoke(["42"])  # the fixture's resolve_commit returns None
    assert result.exit_code == 0, result.output
    assert watch_env.calls.execs == [(HUNK_PATH, _hunk_argv())]
    assert "falling back to the since-base merge-base" in result.stderr


def test_movable_recorded_parent_is_rejected_even_when_resolvable(watch_env, monkeypatch):
    # A movable revision (e.g. `HEAD`) in the never-authoritative record resolves locally but
    # is NOT an immutable full object id — the stacked arm must degrade to since-base.
    monkeypatch.setattr(cache, "read_layer_parent_sha", lambda root: "HEAD")
    monkeypatch.setattr(git, "resolve_commit", lambda repo, ref: PARENT_SHA)
    result = _invoke(["42"])
    assert result.exit_code == 0, result.output
    assert watch_env.calls.execs == [(HUNK_PATH, _hunk_argv())]
    assert "falling back to the since-base merge-base" in result.stderr


def test_abbreviated_recorded_parent_is_rejected(watch_env, monkeypatch):
    monkeypatch.setattr(cache, "read_layer_parent_sha", lambda root: PARENT_SHA[:12])
    monkeypatch.setattr(git, "resolve_commit", lambda repo, ref: PARENT_SHA)
    result = _invoke(["42"])
    assert result.exit_code == 0, result.output
    assert watch_env.calls.execs == [(HUNK_PATH, _hunk_argv())]


def test_malformed_plan_ref_warns_and_continues_on_the_trunk_arm(watch_env):
    path = cache.plan_ref_path(watch_env.worktree)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    result = _invoke(["42"])
    assert result.exit_code == 0, result.output
    assert "unreadable plan-ref" in result.stderr
    assert [(a, b) for _r, a, b in watch_env.calls.merge_bases] == [("HEAD", "origin/main")]


def test_unresolvable_merge_base_degrades_to_a_working_tree_watch(watch_env, monkeypatch):
    monkeypatch.setattr(git, "merge_base", lambda repo, a, b: None)
    result = _invoke(["42"])
    assert result.exit_code == 0, result.output
    assert watch_env.calls.execs == [(HUNK_PATH, _hunk_argv(sha=None))]
    assert "watching the working tree only" in result.stderr


def test_fetch_failure_is_non_fatal(watch_env, monkeypatch):
    def _boom(repo, **k):
        raise GitError("offline")

    monkeypatch.setattr(git, "fetch", _boom)
    result = _invoke(["42"])
    assert result.exit_code == 0, result.output
    assert "could not fetch origin" in result.stderr
    assert watch_env.calls.execs == [(HUNK_PATH, _hunk_argv())]


# --- the pass-through grammar ------------------------------------------------------------


def test_unknown_tokens_pass_through_in_order(watch_env):
    result = _invoke(["42", "--theme", "dark", "--wrap"])
    assert result.exit_code == 0, result.output
    # User tokens land AFTER the perk-owned args (--watch + the bundled --extension), in order.
    assert watch_env.calls.execs == [(HUNK_PATH, _hunk_argv("--theme", "dark", "--wrap"))]


def test_perk_owned_token_after_the_separator_reaches_hunk(watch_env):
    result = _invoke(["42", "--", "--dry-run"])
    assert result.exit_code == 0, result.output
    # perk's dry-run was NOT triggered: the exec happened, carrying the literal token.
    assert watch_env.calls.execs == [(HUNK_PATH, _hunk_argv("--dry-run"))]


def test_double_separator_hands_hunk_its_own_pathspec_separator(watch_env):
    result = _invoke(["42", "--", "--", "src/ui"])
    assert result.exit_code == 0, result.output
    assert watch_env.calls.execs == [(HUNK_PATH, _hunk_argv("--", "src/ui"))]


def test_help_epilog_states_the_grammar(watch_env):
    result = _invoke(["--help"])
    assert result.exit_code == 0, result.output
    assert "type it twice" in result.output


# --- dry-run ------------------------------------------------------------------------------


def test_dry_run_prints_the_command_without_launching(watch_env):
    result = _invoke(["42", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert watch_env.calls.chdir == [] and watch_env.calls.execs == []
    assert str(watch_env.worktree) in result.stderr
    # The printed command carries the ABSOLUTE bundled extension path (paste-launchable).
    assert f"hunk diff {MERGE_SHA[:12]} --watch --extension {EXT_PATH}" in result.stderr


def test_dry_run_renders_spaced_args_shlex_quoted(watch_env):
    result = _invoke(["42", "--dry-run", "--note", "two words"])
    assert result.exit_code == 0, result.output
    assert "'two words'" in result.stderr


# --- the failure arms ---------------------------------------------------------------------


def test_missing_worktree_is_a_hinted_refusal(watch_env):
    result = _invoke(["99"])
    assert result.exit_code == 1
    assert "Worktree not found" in result.stderr
    assert "perk implement 99" in result.stderr
    assert watch_env.calls.execs == []


def test_absent_hunk_cli_carries_the_install_hint(watch_env, monkeypatch):
    monkeypatch.setattr(watch_cmd, "hunk_cli_path", lambda: None)
    result = _invoke(["42"])
    assert result.exit_code == 1
    assert "npm i -g hunkdiff" in result.stderr
    assert watch_env.calls.execs == []


def test_exec_failure_is_a_launch_failed_error(watch_env, monkeypatch):
    def _boom(path, argv, env):
        raise OSError("exec race")

    monkeypatch.setattr(watch_cmd.os, "execve", _boom)
    result = _invoke(["42"])
    assert result.exit_code == 1
    assert "could not launch hunk" in result.stderr


def test_not_a_repo_exits_2(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _invoke(["42"])
    assert result.exit_code == 2
    assert "Not a git repository" in result.stderr


# --- resolution shapes ---------------------------------------------------------------------


def test_linked_worktree_invocation_resolves_under_the_main_root(watch_env, monkeypatch):
    main_root = watch_env.root / "mainco"
    main_wt = main_root / ".worktrees" / "plan-42"
    main_wt.mkdir(parents=True)
    monkeypatch.setattr(git, "main_worktree_root", lambda cwd: main_root)
    result = _invoke(["42"])
    assert result.exit_code == 0, result.output
    assert watch_env.calls.chdir == [main_wt]
    # The diff-base git ops target the MAIN root's worktree too, never the invocation root.
    assert watch_env.calls.fetches == [main_wt.resolve()]
    assert watch_env.calls.merge_bases == [(main_wt.resolve(), "HEAD", "origin/main")]


def test_hash_prefixed_id_resolves_the_plain_worktree(watch_env):
    result = _invoke(["#42"])
    assert result.exit_code == 0, result.output
    assert watch_env.calls.execs  # resolved to plan-42 (the fixture's worktree)


def test_backend_native_id_resolves_its_own_worktree(watch_env):
    (watch_env.root / ".worktrees" / "plan-SAV-456").mkdir(parents=True)
    result = _invoke(["SAV-456"])
    assert result.exit_code == 0, result.output
    assert [p.name for p in watch_env.calls.chdir] == ["plan-SAV-456"]
    assert "watching plan #SAV-456" in result.stderr


def test_invalid_id_is_rejected(watch_env):
    result = _invoke(["a/b"])
    assert result.exit_code == 1
    assert "Invalid plan id" in result.stderr
    assert watch_env.calls.execs == []


# --- the feedback bridge (contracts §8.58) --------------------------------------------------


def test_real_launch_carries_the_bridge_env_without_mutating_os_environ(watch_env):
    result = _invoke(["42"])
    assert result.exit_code == 0, result.output
    [env] = watch_env.calls.envs
    # A fresh ULID watch INSTANCE id (26-char Crockford base32) — not a workflow run_id.
    assert len(env["PERK_HUNK_WATCH_ID"]) == 26
    assert env["PERK_HUNK_PLAN_ID"] == "42"
    assert env["PERK_HUNK_WORKTREE_ROOT"] == str(watch_env.worktree.resolve())
    # The exec env was a COPY — the launcher's own environment is never mutated.
    for key in ("PERK_HUNK_WATCH_ID", "PERK_HUNK_PLAN_ID", "PERK_HUNK_WORKTREE_ROOT"):
        assert key not in os.environ


def test_backend_native_plan_id_is_carried_verbatim(watch_env):
    (watch_env.root / ".worktrees" / "plan-SAV-456").mkdir(parents=True)
    result = _invoke(["SAV-456"])
    assert result.exit_code == 0, result.output
    assert watch_env.calls.envs[0]["PERK_HUNK_PLAN_ID"] == "SAV-456"


def test_user_supplied_extension_composes_after_perks(watch_env):
    # hunk's --extension is repeatable: the user's extension loads WITH perk's, never instead.
    result = _invoke(["42", "--extension", "/user/ext.ts"])
    assert result.exit_code == 0, result.output
    assert watch_env.calls.execs == [(HUNK_PATH, _hunk_argv("--extension", "/user/ext.ts"))]


@pytest.mark.parametrize(
    "args",
    [
        ["42", "--no-extensions"],
        ["42", "--", "--no-extensions"],
        ["42", "--dry-run", "--no-extensions"],
        ["42", "--dry-run", "--", "--no-extensions"],
    ],
)
def test_no_extensions_is_refused_everywhere(watch_env, args):
    # hunk's hard-off switch would silently disable the bridge — refused pre-exec, dry-run
    # included, before or after the escaped `--`.
    result = _invoke(args)
    assert result.exit_code == 1
    assert "feedback bridge" in result.stderr
    assert "hunk diff <base> --watch --no-extensions" in result.stderr  # the alternative
    assert watch_env.calls.execs == [] and watch_env.calls.chdir == []


@pytest.mark.parametrize("dry_run", [False, True], ids=["real", "dry-run"])
def test_missing_bundled_extension_refuses(watch_env, monkeypatch, dry_run):
    def _boom():
        raise FileNotFoundError("perk: could not locate the bundled Hunk feedback extension")

    monkeypatch.setattr(watch_cmd, "hunk_feedback_extension_path", _boom)
    result = _invoke(["42", "--dry-run"] if dry_run else ["42"])
    # A dry-run must not print an unlaunchable command — the refusal applies there too.
    assert result.exit_code == 1
    assert "Reinstall perk" in result.stderr
    assert watch_env.calls.execs == [] and watch_env.calls.chdir == []


def test_dry_run_mints_nothing_and_creates_no_storage(watch_env, monkeypatch):
    def _no_mint():
        raise AssertionError("dry-run must not mint a watch instance id")

    monkeypatch.setattr(watch_cmd, "ULID", _no_mint)
    result = _invoke(["42", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert watch_env.calls.envs == []  # no exec env was built
    assert not (watch_env.worktree / ".perk").exists()  # no hunk-watch/ storage


# --- cache.read_layer_parent_sha (the fail-soft reader) ------------------------------------


def test_read_layer_parent_sha_absent_is_none(tmp_path):
    assert cache.read_layer_parent_sha(tmp_path) is None


def test_read_layer_parent_sha_reads_a_valid_record(tmp_path):
    cache.write_layer_context(tmp_path, _layer_context(), PARENT_SHA)
    assert cache.read_layer_parent_sha(tmp_path) == PARENT_SHA


def test_read_layer_parent_sha_malformed_json_is_none(tmp_path):
    path = cache.layer_context_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert cache.read_layer_parent_sha(tmp_path) is None


def test_read_layer_parent_sha_schema_mismatch_is_none(tmp_path):
    path = cache.layer_context_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    assert cache.read_layer_parent_sha(tmp_path) is None
