"""The Prose Review Workbench read-only Git observation adapter.

Owns ALL Git interaction for the app: one app-lifetime :class:`GitReader` reports
working-tree status and per-file HEAD↔worktree diffs, and exposes nothing mutating.
The argv tables below are module-level constants pinned by test — every execution is
a fixed command plus (for diffs) one catalog-membership-validated path placed after
``--``, so zero request-derived argv content ever reaches Git.

The process envelope is deliberately narrow and honestly claimed: the env overlay
pins off prompts (``GIT_TERMINAL_PROMPT``), opportunistic index writes
(``GIT_OPTIONAL_LOCKS``), partial-clone lazy fetches (``GIT_NO_LAZY_FETCH`` —
``git diff HEAD`` may otherwise contact a promisor remote), and pathspec expansion
(``GIT_LITERAL_PATHSPECS`` — the validated path stays one literal file, never a
glob), and ``core.fsmonitor`` is forced off per invocation (it may name an external
hook executable). Git-config-
driven content filters (``filter.<driver>.clean``) remain OUTSIDE the suppression
claim: the workbench adds no authority beyond what ``git status``/``git diff``
already execute in the repo owner's own shell. The timeout kill is
``subprocess.run``'s child-only kill (no process-group escalation) — an accepted,
documented residual (docs/design/prose-review-stack.md).

``perk.substrate.proc.run_captured`` is text-mode with strict locale decoding and is
therefore unusable here: porcelain ``-z`` emits raw pathname bytes and diff output
embeds file content bytes, either of which may be undecodable. The one bytes-mode
spawn site is :func:`_run_captured_bytes` (sanctioned in ``tests/test_tooling.py``);
all decoding happens inside the adapter's failure boundary so a request can never
surface an unhandled decode error.
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type GitFileState = Literal["modified", "added", "deleted", "untracked", "conflicted"]
# `git-missing` is nominal for a spawn OSError (an inaccessible cwd lands here too);
# `git-error` is the fail-closed bucket: nonzero exit, malformed porcelain.
type GitUnavailableReason = Literal["git-missing", "timeout", "too-large", "git-error"]

# Fixed argv tables (pinned by test). `core.fsmonitor=false` is forced per invocation
# because the config key may name an external hook executable; `--no-renames` keeps
# porcelain records one-path-per-record; `--no-ext-diff`/`--no-textconv` pin external
# diff drivers and textconv helpers off.
STATUS_ARGV = (
    "git",
    "-c",
    "core.fsmonitor=false",
    "status",
    "--porcelain",
    "--no-renames",
    "--untracked-files=all",
    "-z",
)
DIFF_HEAD_ARGV_PREFIX = (
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
DIFF_UNTRACKED_ARGV_PREFIX = (
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
# No prompts; no opportunistic index write; no partial-clone network fetch; and
# literal pathspec semantics — the request-derived path after `--` is otherwise a
# Git PATHSPEC (a catalog file legally named `docs/*.md`, or one starting with
# `:(magic)`, could match non-catalog files and leak past the one-file boundary).
GIT_ENV_OVERLAY = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_LITERAL_PATHSPECS": "1",
}

GIT_TIMEOUT_SECONDS = 10
# The only unbounded input is an arbitrary worktree file: refuse it BEFORE spawning
# git. HEAD-side content is committed repository state and status output is
# O(changed paths) porcelain with no file content — both accepted, documented bounds.
MAX_DIFF_SOURCE_BYTES = 5_000_000
# Post-capture cap over the decoded diff text, in Python str code points.
DIFF_TEXT_CAP_CHARS = 500_000

# Porcelain XY pairs that mark an unmerged path (renames are disabled).
_UNMERGED_XY = frozenset({"DD", "AU", "UD", "UA", "DU", "AA", "UU"})


@dataclass(frozen=True, slots=True)
class GitFileEntry:
    """One folded per-path working-tree state (repo-root-relative POSIX path)."""

    path: str
    state: GitFileState


@dataclass(frozen=True, slots=True)
class GitStatusAvailable:
    """All folded entries plus the count of anonymous undecodable-path records.

    The reader is catalog-agnostic: ``entries`` carries EVERY folded record and the
    web layer partitions them by catalog membership. ``other_paths`` counts records
    whose pathname bytes were not UTF-8 — catalog paths are always valid UTF-8, so
    such a record can never be a catalog entry and is only ever counted, never
    listed.
    """

    entries: tuple[GitFileEntry, ...]
    other_paths: int


@dataclass(frozen=True, slots=True)
class GitStatusUnavailable:
    reason: GitUnavailableReason


type GitStatusResult = GitStatusAvailable | GitStatusUnavailable


@dataclass(frozen=True, slots=True)
class GitDiffAvailable:
    """One decoded (``errors="replace"``) HEAD↔worktree patch, possibly capped."""

    diff: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class GitDiffUnavailable:
    reason: GitUnavailableReason


type GitDiffResult = GitDiffAvailable | GitDiffUnavailable


def _run_captured_bytes(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    timeout: float,
    env_overlay: dict[str, str],
) -> subprocess.CompletedProcess[bytes]:
    """The one bytes-mode captured spawn (sanctioned in ``tests/test_tooling.py``).

    Bytes mode is the point: porcelain ``-z`` emits raw pathname bytes and diff
    output embeds file content bytes — a text-mode strict decode would crash on
    either. ``subprocess.TimeoutExpired``/``OSError`` propagate to the caller's
    failure boundary. The timeout kill is child-only (no group escalation) — an
    accepted, documented residual.
    """
    return subprocess.run(
        list(argv),
        cwd=cwd,
        check=False,
        capture_output=True,
        timeout=timeout,
        env={**os.environ, **env_overlay},
    )


def _record_presence(xy: str) -> tuple[bool, bool]:
    """One record's ``(in_head, in_worktree)`` under the HEAD↔worktree baseline.

    ``X == "A"`` is a staged add and ``Y == "A"`` is Git's intent-to-add
    (``git add -N`` reports ``" A"``) — either way the path is new relative to
    HEAD; ``??`` is untracked. The worktree side is absent when the worktree copy
    is deleted (``Y == "D"``) or a staged delete has nothing left on disk
    (``"D "``).
    """
    x, y = xy[0], xy[1]
    in_head = not (x == "A" or y == "A" or xy == "??")
    in_worktree = not (y == "D" or (x == "D" and y == " "))
    return in_head, in_worktree


def _merge_states(xys: list[str]) -> GitFileState | None:
    """Fold one path's porcelain records into the closed per-file state (None = drop).

    Derived consistently with the served diff baseline so a badge never promises a
    change its diff can't show. Porcelain v1 can emit SEVERAL records for one
    pathname even with renames disabled: ``git rm --cached`` while the worktree copy
    remains yields ``"D "`` + ``"??"``. Tracked records win that merge because they
    describe exactly what the served HEAD-form diff shows (``git diff HEAD`` ignores
    the untracked copy and reports the staged deletion); the ``??`` record decides
    the state only when it is the path's sole record kind. Both absent (e.g. ``AD``
    — staged add then worktree delete) cancels out: its HEAD diff is empty, so the
    path is dropped entirely. Any unrecognized XY lands in the both-present
    quadrant → ``modified`` (safe: the badge says "changed", the diff shows the
    truth).
    """
    if any(xy in _UNMERGED_XY for xy in xys):
        return "conflicted"
    tracked = [xy for xy in xys if xy != "??"]
    if not tracked:
        return "untracked"
    presences = [_record_presence(xy) for xy in tracked]
    in_head = any(head for head, _ in presences)
    in_worktree = any(worktree for _, worktree in presences)
    if not in_head and not in_worktree:
        return None
    if not in_head:
        return "added"
    if not in_worktree:
        return "deleted"
    return "modified"


def _fold_porcelain(raw: bytes) -> tuple[tuple[GitFileEntry, ...], int] | None:
    """Fold raw ``-z`` porcelain bytes into entries + anonymous count (None = malformed).

    Decoding is strict UTF-8 PER RECORD: a record whose bytes fail to decode is
    counted anonymously (it can never name a catalog path) and never listed; a
    record that decodes but has the wrong shape fails the whole status closed
    (``git-error``) rather than guessing at the vocabulary. Same-path records are
    coalesced (first-seen order) so one path is always one entry — duplicate rows
    would split the badge from the served diff.
    """
    xys_by_path: dict[str, list[str]] = {}
    anonymous = 0
    for record in raw.split(b"\x00"):
        if record == b"":
            continue
        try:
            text = record.decode("utf-8")
        except UnicodeDecodeError:
            anonymous += 1
            continue
        if len(text) < 4 or text[2] != " ":
            return None
        xys_by_path.setdefault(text[3:], []).append(text[:2])
    entries: list[GitFileEntry] = []
    for path, xys in xys_by_path.items():
        state = _merge_states(xys)
        if state is not None:
            entries.append(GitFileEntry(path=path, state=state))
    return tuple(entries), anonymous


def _capped_diff(stdout: bytes) -> GitDiffAvailable:
    """Decode diff bytes display-safely and cap the text; can never raise."""
    text = stdout.decode("utf-8", errors="replace")
    if len(text) > DIFF_TEXT_CAP_CHARS:
        return GitDiffAvailable(diff=text[:DIFF_TEXT_CAP_CHARS], truncated=True)
    return GitDiffAvailable(diff=text, truncated=False)


@dataclass(frozen=True, slots=True)
class _SpawnFailure:
    """A spawn/timeout outcome from :meth:`GitReader._execute` (never an exit code)."""

    reason: GitUnavailableReason


class GitReader:
    """App-lifetime read-only Git observer over one resolved repository root.

    Status and diffs are computed fresh per call — no caching, no coupling to the
    catalog generation. Every path argument must already be catalog-membership
    validated by the caller (the web layer's admission boundary).
    """

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def status(self) -> GitStatusResult:
        executed = self._execute(STATUS_ARGV)
        if isinstance(executed, _SpawnFailure):
            return GitStatusUnavailable(reason=executed.reason)
        if executed.returncode != 0:
            return GitStatusUnavailable(reason="git-error")
        folded = _fold_porcelain(executed.stdout)
        if folded is None:
            return GitStatusUnavailable(reason="git-error")
        entries, anonymous = folded
        return GitStatusAvailable(entries=entries, other_paths=anonymous)

    def diff(self, path: str) -> GitDiffResult:
        refusal = self._size_refusal(path)
        if refusal is not None:
            return refusal
        # Classify against the SAME folded baseline the badges derive from: only a
        # currently-untracked path takes the synthesized no-index add-diff.
        status = self.status()
        if isinstance(status, GitStatusUnavailable):
            return GitDiffUnavailable(reason=status.reason)
        entry = next((item for item in status.entries if item.path == path), None)
        if entry is not None and entry.state == "untracked":
            return self._diff_untracked(path)
        return self._diff_head(path)

    def _size_refusal(self, path: str) -> GitDiffUnavailable | None:
        # The pre-spawn bound over the one unbounded input. A vanished file skips
        # the guard (git itself then reports or diffs the absence).
        try:
            size = (self._repo_root / path).stat().st_size
        except OSError:
            return None
        if size > MAX_DIFF_SOURCE_BYTES:
            return GitDiffUnavailable(reason="too-large")
        return None

    def _diff_head(self, path: str) -> GitDiffResult:
        executed = self._execute((*DIFF_HEAD_ARGV_PREFIX, path))
        if isinstance(executed, _SpawnFailure):
            return GitDiffUnavailable(reason=executed.reason)
        if executed.returncode != 0:
            # Not-a-repo, no HEAD, etc. — fail closed.
            return GitDiffUnavailable(reason="git-error")
        return _capped_diff(executed.stdout)

    def _diff_untracked(self, path: str) -> GitDiffResult:
        executed = self._execute((*DIFF_UNTRACKED_ARGV_PREFIX, path))
        if isinstance(executed, _SpawnFailure):
            return GitDiffUnavailable(reason=executed.reason)
        if executed.returncode == 0:
            # rc 0 with `--no-index` means "no difference" — the empty-untracked-file
            # case is a real, presentable empty diff.
            return _capped_diff(executed.stdout)
        if executed.returncode == 1:
            # `--no-index` implies `--exit-code`: rc 1 means "differs" OR an
            # operational error (e.g. `Could not access …` after a vanish race).
            # Only a clean-stderr, non-empty-patch rc 1 is a real difference.
            stderr = executed.stderr.decode("utf-8", errors="replace")
            if stderr == "" and executed.stdout != b"":
                return _capped_diff(executed.stdout)
        return GitDiffUnavailable(reason="git-error")

    def _execute(self, argv: tuple[str, ...]) -> subprocess.CompletedProcess[bytes] | _SpawnFailure:
        try:
            return _run_captured_bytes(
                argv,
                cwd=self._repo_root,
                timeout=GIT_TIMEOUT_SECONDS,
                env_overlay=GIT_ENV_OVERLAY,
            )
        except subprocess.TimeoutExpired:
            return _SpawnFailure(reason="timeout")
        except OSError:
            return _SpawnFailure(reason="git-missing")
