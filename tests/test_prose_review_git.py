"""The Prose Review GitReader: porcelain folding, pinned argv/env, bounds, real git."""

import os
import subprocess
from pathlib import Path

import pytest
from perk_dev.prose_review import git as git_module
from perk_dev.prose_review.git import (
    DIFF_HEAD_ARGV_PREFIX,
    DIFF_TEXT_CAP_CHARS,
    DIFF_UNTRACKED_ARGV_PREFIX,
    GIT_ENV_OVERLAY,
    GIT_TIMEOUT_SECONDS,
    MAX_DIFF_SOURCE_BYTES,
    STATUS_ARGV,
    GitDiffAvailable,
    GitDiffUnavailable,
    GitFileEntry,
    GitFileState,
    GitReader,
    GitStatusAvailable,
    GitStatusUnavailable,
)

# ── Test doubles ──────────────────────────────────────────────────────────────


def _completed(
    argv: tuple[str, ...], returncode: int, stdout: bytes = b"", stderr: bytes = b""
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(list(argv), returncode, stdout=stdout, stderr=stderr)


def _status_reader(
    monkeypatch: pytest.MonkeyPatch,
    repo: Path,
    stdout: bytes,
    *,
    returncode: int = 0,
) -> GitReader:
    """A GitReader whose every spawn serves one fixed status outcome."""

    def fake(
        argv: tuple[str, ...], *, cwd: Path, timeout: float, env_overlay: dict[str, str]
    ) -> subprocess.CompletedProcess[bytes]:
        return _completed(argv, returncode, stdout=stdout)

    monkeypatch.setattr(git_module, "_run_captured_bytes", fake)
    return GitReader(repo)


# ── The porcelain fold ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("xy", "state"),
    [
        (" M", "modified"),
        ("M ", "modified"),
        ("MM", "modified"),
        ("T ", "modified"),
        ("A ", "added"),
        ("AM", "added"),
        # Intent-to-add (`git add -N`): the path is new relative to HEAD.
        (" A", "added"),
        ("D ", "deleted"),
        (" D", "deleted"),
        ("MD", "deleted"),
        ("??", "untracked"),
        ("DD", "conflicted"),
        ("AU", "conflicted"),
        ("UD", "conflicted"),
        ("UA", "conflicted"),
        ("DU", "conflicted"),
        ("AA", "conflicted"),
        ("UU", "conflicted"),
        # Unrecognized XY lands in the both-present quadrant: the badge says
        # "changed" and the diff shows the truth.
        ("XZ", "modified"),
    ],
)
def test_porcelain_fold_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, xy: str, state: GitFileState
) -> None:
    reader = _status_reader(monkeypatch, tmp_path, f"{xy} file.md\x00".encode())
    assert reader.status() == GitStatusAvailable(
        entries=(GitFileEntry(path="file.md", state=state),),
        other_paths=0,
    )


def test_both_absent_record_is_dropped_entirely(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # `AD` (staged add then worktree delete) cancels out: its HEAD diff is empty,
    # so it gets no row, no badge, and is not counted.
    reader = _status_reader(monkeypatch, tmp_path, b"AD ghost.md\x00 M kept.md\x00")
    assert reader.status() == GitStatusAvailable(
        entries=(GitFileEntry(path="kept.md", state="modified"),), other_paths=0
    )


def test_same_path_records_coalesce_into_one_baseline_aware_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # `git rm --cached` with the worktree copy intact emits BOTH `D ` and `??` for
    # one pathname. The tracked record wins the merge — `git diff HEAD` ignores the
    # untracked copy and serves the staged deletion — so the one coalesced entry
    # (`deleted`) always agrees with the diff its row will show.
    reader = _status_reader(monkeypatch, tmp_path, b"D  a.md\x00?? a.md\x00 M b.md\x00")
    assert reader.status() == GitStatusAvailable(
        entries=(
            GitFileEntry(path="a.md", state="deleted"),
            GitFileEntry(path="b.md", state="modified"),
        ),
        other_paths=0,
    )


def test_nul_parsing_and_undecodable_path_record_is_counted_anonymously(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # \xc3\x28 is invalid UTF-8: the record can never name a catalog path, so it is
    # counted (never listed) while the surrounding records parse normally.
    raw = b"?? a.md\x00 M b.md\x00?? \xc3\x28mangled\x00"
    reader = _status_reader(monkeypatch, tmp_path, raw)
    assert reader.status() == GitStatusAvailable(
        entries=(
            GitFileEntry(path="a.md", state="untracked"),
            GitFileEntry(path="b.md", state="modified"),
        ),
        other_paths=1,
    )


@pytest.mark.parametrize("raw", [b"M\x00", b"MMxpath.md\x00", b" M \x00"])
def test_structurally_malformed_record_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raw: bytes
) -> None:
    reader = _status_reader(monkeypatch, tmp_path, raw)
    assert reader.status() == GitStatusUnavailable(reason="git-error")


def test_nonzero_status_exit_is_git_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reader = _status_reader(monkeypatch, tmp_path, b"", returncode=128)
    assert reader.status() == GitStatusUnavailable(reason="git-error")


# ── The argv / env / cwd / timeout pins ───────────────────────────────────────


def test_fixed_argv_constants_are_pinned() -> None:
    assert STATUS_ARGV == (
        "git",
        "-c",
        "core.fsmonitor=false",
        "status",
        "--porcelain",
        "--no-renames",
        "--untracked-files=all",
        "-z",
    )
    assert DIFF_HEAD_ARGV_PREFIX == (
        "git",
        "-c",
        "core.fsmonitor=false",
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-color",
        "HEAD",
        "--",
    )
    assert DIFF_UNTRACKED_ARGV_PREFIX == (
        "git",
        "-c",
        "core.fsmonitor=false",
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-color",
        "--no-index",
        "--",
        "/dev/null",
    )
    assert GIT_ENV_OVERLAY == {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_LAZY_FETCH": "1",
        # The request-derived path after `--` must stay one literal file: without
        # this a catalog file named like a glob (or `:(magic)`) is a pathspec.
        "GIT_LITERAL_PATHSPECS": "1",
    }


def test_structural_never_rules_over_every_fixed_argv() -> None:
    mutating = {
        "add",
        "am",
        "apply",
        "branch",
        "checkout",
        "clean",
        "clone",
        "commit",
        "fetch",
        "merge",
        "mv",
        "pull",
        "push",
        "rebase",
        "reset",
        "restore",
        "rm",
        "stash",
        "switch",
        "tag",
        "worktree",
    }
    for argv in (STATUS_ARGV, DIFF_HEAD_ARGV_PREFIX, DIFF_UNTRACKED_ARGV_PREFIX):
        assert argv[0] == "git"
        # Exactly one `-c`, and it only ever pins the fsmonitor hook off.
        assert [index for index, token in enumerate(argv) if token == "-c"] == [1]
        assert argv[2] == "core.fsmonitor=false"
        assert argv[3] in ("status", "diff")
        assert not mutating & set(argv)


def test_every_execution_uses_pinned_cwd_timeout_and_env_overlay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[tuple[str, ...], Path, float, dict[str, str]]] = []

    def fake(
        argv: tuple[str, ...], *, cwd: Path, timeout: float, env_overlay: dict[str, str]
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append((tuple(argv), cwd, timeout, dict(env_overlay)))
        stdout = b"?? untracked.md\x00" if tuple(argv) == STATUS_ARGV else b""
        return _completed(tuple(argv), 0, stdout=stdout)

    monkeypatch.setattr(git_module, "_run_captured_bytes", fake)
    reader = GitReader(tmp_path)
    reader.status()
    # An untracked path takes the no-index form; anything else the HEAD form.
    reader.diff("untracked.md")
    reader.diff("other.md")

    assert [call[0] for call in calls] == [
        STATUS_ARGV,
        STATUS_ARGV,
        (*DIFF_UNTRACKED_ARGV_PREFIX, "untracked.md"),
        STATUS_ARGV,
        (*DIFF_HEAD_ARGV_PREFIX, "other.md"),
    ]
    for _argv, cwd, timeout, env_overlay in calls:
        assert cwd == tmp_path
        assert timeout == GIT_TIMEOUT_SECONDS
        assert env_overlay == GIT_ENV_OVERLAY


# ── Failure arms ──────────────────────────────────────────────────────────────


def test_spawn_oserror_is_git_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake(
        argv: tuple[str, ...], *, cwd: Path, timeout: float, env_overlay: dict[str, str]
    ) -> subprocess.CompletedProcess[bytes]:
        raise OSError("no git on this machine")

    monkeypatch.setattr(git_module, "_run_captured_bytes", fake)
    reader = GitReader(tmp_path)
    assert reader.status() == GitStatusUnavailable(reason="git-missing")
    assert reader.diff("a.md") == GitDiffUnavailable(reason="git-missing")


def test_timeout_expired_is_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake(
        argv: tuple[str, ...], *, cwd: Path, timeout: float, env_overlay: dict[str, str]
    ) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd=list(argv), timeout=timeout)

    monkeypatch.setattr(git_module, "_run_captured_bytes", fake)
    reader = GitReader(tmp_path)
    assert reader.status() == GitStatusUnavailable(reason="timeout")
    assert reader.diff("a.md") == GitDiffUnavailable(reason="timeout")


def test_nonzero_head_diff_exit_is_git_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake(
        argv: tuple[str, ...], *, cwd: Path, timeout: float, env_overlay: dict[str, str]
    ) -> subprocess.CompletedProcess[bytes]:
        if tuple(argv) == STATUS_ARGV:
            return _completed(tuple(argv), 0, stdout=b" M a.md\x00")
        return _completed(tuple(argv), 128, stderr=b"fatal: bad revision 'HEAD'\n")

    monkeypatch.setattr(git_module, "_run_captured_bytes", fake)
    assert GitReader(tmp_path).diff("a.md") == GitDiffUnavailable(reason="git-error")


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr", "expected"),
    [
        # rc 0: no difference — the empty-untracked-file case is a real empty diff.
        (0, b"", b"", GitDiffAvailable(diff="", truncated=False)),
        # rc 1 with a clean stderr and a patch: a real difference.
        (1, b"+content\n", b"", GitDiffAvailable(diff="+content\n", truncated=False)),
        # rc 1 with stderr: an operational error (the vanish race), not a difference.
        (1, b"", b"error: Could not access 'a.md'\n", GitDiffUnavailable(reason="git-error")),
        # rc 1 with no patch and no stderr: fail closed.
        (1, b"", b"", GitDiffUnavailable(reason="git-error")),
        (2, b"", b"fatal: unable to read files\n", GitDiffUnavailable(reason="git-error")),
    ],
)
def test_no_index_return_code_matrix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    returncode: int,
    stdout: bytes,
    stderr: bytes,
    expected: GitDiffAvailable | GitDiffUnavailable,
) -> None:
    def fake(
        argv: tuple[str, ...], *, cwd: Path, timeout: float, env_overlay: dict[str, str]
    ) -> subprocess.CompletedProcess[bytes]:
        if tuple(argv) == STATUS_ARGV:
            return _completed(tuple(argv), 0, stdout=b"?? a.md\x00")
        assert tuple(argv) == (*DIFF_UNTRACKED_ARGV_PREFIX, "a.md")
        return _completed(tuple(argv), returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(git_module, "_run_captured_bytes", fake)
    assert GitReader(tmp_path).diff("a.md") == expected


# ── Bounds ────────────────────────────────────────────────────────────────────


def test_oversized_worktree_file_is_refused_before_any_spawn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    big = tmp_path / "big.md"
    big.touch()
    os.truncate(big, MAX_DIFF_SOURCE_BYTES + 1)

    def fake(
        argv: tuple[str, ...], *, cwd: Path, timeout: float, env_overlay: dict[str, str]
    ) -> subprocess.CompletedProcess[bytes]:
        pytest.fail("an oversized file must never reach a git spawn")

    monkeypatch.setattr(git_module, "_run_captured_bytes", fake)
    assert GitReader(tmp_path).diff("big.md") == GitDiffUnavailable(reason="too-large")


def test_exactly_at_the_size_bound_still_diffs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    edge = tmp_path / "edge.md"
    edge.touch()
    os.truncate(edge, MAX_DIFF_SOURCE_BYTES)

    def fake(
        argv: tuple[str, ...], *, cwd: Path, timeout: float, env_overlay: dict[str, str]
    ) -> subprocess.CompletedProcess[bytes]:
        stdout = b" M edge.md\x00" if tuple(argv) == STATUS_ARGV else b"+x\n"
        return _completed(tuple(argv), 0, stdout=stdout)

    monkeypatch.setattr(git_module, "_run_captured_bytes", fake)
    assert GitReader(tmp_path).diff("edge.md") == GitDiffAvailable(diff="+x\n", truncated=False)


def test_diff_text_is_capped_in_code_points_with_truncated_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake(
        argv: tuple[str, ...], *, cwd: Path, timeout: float, env_overlay: dict[str, str]
    ) -> subprocess.CompletedProcess[bytes]:
        if tuple(argv) == STATUS_ARGV:
            return _completed(tuple(argv), 0, stdout=b" M a.md\x00")
        return _completed(tuple(argv), 0, stdout=b"a" * (DIFF_TEXT_CAP_CHARS + 5))

    monkeypatch.setattr(git_module, "_run_captured_bytes", fake)
    result = GitReader(tmp_path).diff("a.md")
    assert result == GitDiffAvailable(diff="a" * DIFF_TEXT_CAP_CHARS, truncated=True)


def test_invalid_utf8_diff_bytes_decode_with_replacement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake(
        argv: tuple[str, ...], *, cwd: Path, timeout: float, env_overlay: dict[str, str]
    ) -> subprocess.CompletedProcess[bytes]:
        if tuple(argv) == STATUS_ARGV:
            return _completed(tuple(argv), 0, stdout=b" M a.md\x00")
        return _completed(tuple(argv), 0, stdout=b"+\xff\xfe\n")

    monkeypatch.setattr(git_module, "_run_captured_bytes", fake)
    assert GitReader(tmp_path).diff("a.md") == GitDiffAvailable(
        diff="+\ufffd\ufffd\n", truncated=False
    )


# ── Real-git integration ──────────────────────────────────────────────────────

_HERMETIC_GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        timeout=30,
        env=_HERMETIC_GIT_ENV,
    )


def _commit(repo: Path, message: str) -> None:
    _git(
        repo,
        "-c",
        "user.name=Prose Review",
        "-c",
        "user.email=prose-review@example.invalid",
        "commit",
        "-q",
        "-m",
        message,
    )


def _hermetic_reader_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the READER phase hermetic too: GitReader spawns with ``os.environ``, so a
    developer's global config (e.g. a ``core.excludesFile`` matching the fixture
    names) must not be able to hide fixtures or skew assertions."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")


@pytest.fixture()
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _hermetic_reader_env(monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "tracked.md").write_text("one\n", encoding="utf-8")
    (repo / "todelete.md").write_text("gone\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _commit(repo, "baseline")
    return repo


def test_real_git_folds_states_and_serves_head_and_no_index_diffs(git_repo: Path) -> None:
    (git_repo / "tracked.md").write_text("two\n", encoding="utf-8")
    (git_repo / "staged.md").write_text("staged\n", encoding="utf-8")
    _git(git_repo, "add", "staged.md")
    (git_repo / "todelete.md").unlink()
    (git_repo / "new.md").write_text("content\n", encoding="utf-8")
    (git_repo / "empty.md").touch()
    # The AD cancellation case: staged add, then worktree delete.
    (git_repo / "ghost.md").write_text("ghost\n", encoding="utf-8")
    _git(git_repo, "add", "ghost.md")
    (git_repo / "ghost.md").unlink()

    reader = GitReader(git_repo)
    status = reader.status()
    assert isinstance(status, GitStatusAvailable)
    assert status.other_paths == 0
    assert {entry.path: entry.state for entry in status.entries} == {
        "tracked.md": "modified",
        "staged.md": "added",
        "todelete.md": "deleted",
        "new.md": "untracked",
        "empty.md": "untracked",
    }

    modified = reader.diff("tracked.md")
    assert isinstance(modified, GitDiffAvailable)
    assert "-one" in modified.diff
    assert "+two" in modified.diff
    assert not modified.truncated

    added = reader.diff("staged.md")
    assert isinstance(added, GitDiffAvailable)
    assert "+staged" in added.diff

    deleted = reader.diff("todelete.md")
    assert isinstance(deleted, GitDiffAvailable)
    assert "-gone" in deleted.diff

    untracked = reader.diff("new.md")
    assert isinstance(untracked, GitDiffAvailable)
    assert "+content" in untracked.diff

    # An empty untracked file is a real, presentable no-index result: git reports
    # no content difference (rc 0) but still emits the header-only new-file patch.
    empty = reader.diff("empty.md")
    assert isinstance(empty, GitDiffAvailable)
    assert "new file mode" in empty.diff
    added_lines = [
        line
        for line in empty.diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    assert added_lines == []
    assert not empty.truncated
    # The dropped AD record's HEAD diff is empty — consistent with its absent badge.
    assert reader.diff("ghost.md") == GitDiffAvailable(diff="", truncated=False)


def test_real_git_coalesces_rm_cached_and_classifies_intent_to_add(git_repo: Path) -> None:
    # `git rm --cached`: one path, two porcelain records (`D ` + `??`) — one entry.
    _git(git_repo, "rm", "--cached", "-q", "tracked.md")
    # Intent-to-add: ` A` — a new path relative to HEAD, never "modified".
    (git_repo / "ita.md").write_text("intent\n", encoding="utf-8")
    _git(git_repo, "add", "-N", "ita.md")

    reader = GitReader(git_repo)
    status = reader.status()
    assert isinstance(status, GitStatusAvailable)
    assert {entry.path: entry.state for entry in status.entries} == {
        "tracked.md": "deleted",
        "ita.md": "added",
    }

    # The badge agrees with the served diff: `git diff HEAD` ignores the untracked
    # copy and reports the staged deletion.
    deleted = reader.diff("tracked.md")
    assert isinstance(deleted, GitDiffAvailable)
    assert "-one" in deleted.diff
    ita = reader.diff("ita.md")
    assert isinstance(ita, GitDiffAvailable)
    assert "+intent" in ita.diff


def test_real_git_diff_path_is_literal_never_a_pathspec(git_repo: Path) -> None:
    # A catalog file may legally be named like a glob; without literal pathspec
    # semantics `git diff … -- 'glob*.md'` would match (and leak) other files.
    (git_repo / "glob*.md").write_text("literal one\n", encoding="utf-8")
    (git_repo / "globX.md").write_text("other one\n", encoding="utf-8")
    _git(git_repo, "add", "-A")
    _commit(git_repo, "glob names")
    (git_repo / "glob*.md").write_text("literal two\n", encoding="utf-8")
    (git_repo / "globX.md").write_text("other two\n", encoding="utf-8")

    reader = GitReader(git_repo)
    result = reader.diff("glob*.md")
    assert isinstance(result, GitDiffAvailable)
    assert "+literal two" in result.diff
    assert "globX.md" not in result.diff


def test_real_git_clean_tree_and_clean_path(git_repo: Path) -> None:
    reader = GitReader(git_repo)
    assert reader.status() == GitStatusAvailable(entries=(), other_paths=0)
    # A clean catalog path still answers with an empty diff rather than an error.
    assert reader.diff("tracked.md") == GitDiffAvailable(diff="", truncated=False)


def test_real_git_outside_any_repository_is_git_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _hermetic_reader_env(monkeypatch)
    reader = GitReader(tmp_path)
    assert reader.status() == GitStatusUnavailable(reason="git-error")
    assert reader.diff("a.md") == GitDiffUnavailable(reason="git-error")
