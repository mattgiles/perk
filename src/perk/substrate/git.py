"""A thin ``git``-shelling gateway — the repo + worktree operations perk needs.

One implementation per plane (cli-vs-pi §3); shells ``git`` via subprocess, never with
``shell=True``. Failures raise ``GitError``; the command layer translates them to
``UserFacingCliError``. LBYL: "is this a repo?" is answered by running ``rev-parse`` and
returning ``None`` on failure (the operation is the authoritative test).
"""

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from perk.substrate.proc import ProcFailure, run_captured, run_checked

# GIT_TERMINAL_PROMPT=0: credential prompts fail fast instead of hanging to the timeout.
_GIT_ENV = {"GIT_TERMINAL_PROMPT": "0"}


@dataclass(frozen=True)
class Worktree:
    """One entry from ``git worktree list``."""

    path: Path
    branch: str | None
    head: str | None


@dataclass(frozen=True)
class CommitInfo:
    """One first-parent commit from ``log_first_parent`` (raw; presentation is the caller's
    concern)."""

    hash: str  # full 40-char SHA
    subject: str
    body: str  # full commit body (untruncated)
    files: tuple[str, ...]  # changed paths (unfiltered)


@dataclass(frozen=True)
class RefUpdate:
    """One branch update of an atomic multi-ref push (:func:`push_atomic_with_leases`).

    ``expected_remote_sha`` is the exact lease — the remote SHA the caller observed; the push
    succeeds only if the remote ref still sits there. Sync never pushes ref creations, so an
    empty expectation is rejected at the call boundary (a programming error, not a runtime
    arm).
    """

    branch: str
    expected_remote_sha: str
    new_sha: str


@dataclass(frozen=True)
class RebaseCompleted:
    """A clean :func:`rebase_onto` transplant; ``head_sha`` is the rebased HEAD commit."""

    head_sha: str


@dataclass(frozen=True)
class RebaseConflict:
    """A :func:`rebase_onto` stop with the conflicted rebase state deliberately left in place
    (no automatic ``--abort`` — the caller owns continuation/abort). ``detail`` is the
    combined output, bounded to its last 2000 chars."""

    detail: str


type RebaseOutcome = RebaseCompleted | RebaseConflict


@dataclass(frozen=True)
class MergeProbe:
    """The result of a best-effort local merge-conflict probe (`detect_merge_conflicts`).

    ``determined`` is True only when the probe ran to a definitive verdict (clean OR conflicted);
    a fetch failure, an unresolvable base, or an unexpected ``git merge-tree`` exit leaves it
    False (fail-open — the caller treats an undetermined probe as "mergeability unknown").
    ``mergeable`` carries the definitive verdict from the probe's **exit code** (clean exit → True,
    conflict exit → False) and is the authority — it must NOT be derived from ``conflicts`` being
    empty, because a conflict exit whose paths failed to parse still yields ``conflicts=()`` yet is
    genuinely unmergeable. ``mergeable`` is only meaningful when ``determined`` is True (False
    otherwise, but the caller gates on ``determined`` first). ``conflicts`` is the (possibly empty)
    tuple of conflicted paths parsed from the probe output.
    """

    determined: bool
    mergeable: bool
    conflicts: tuple[str, ...]


class GitError(Exception):
    """A git command exited non-zero (translated to ``UserFacingCliError`` at the boundary)."""


class PushRejectedError(GitError):
    """A push was rejected as non-fast-forward / failed the ``--force-with-lease`` check."""


_REJECT_MARKERS = ("non-fast-forward", "[rejected]", "stale info", "failed to push some refs")

# `git branch -D|-d` writes `Deleted branch <name> (was <sha>).` per removed branch to stdout.
_DELETED_BRANCH_RE = re.compile(r"^Deleted branch (\S+)", re.MULTILINE)
# `git push <remote> --delete` writes ` - [deleted]         <branch>` per removed ref to stderr.
_DELETED_REMOTE_RE = re.compile(r"\[deleted\]\s+(\S+)")

# `git merge-tree --write-tree` prints the merged tree OID on line 1, then (on conflict) a
# "Conflicted file info" block of `<mode> <object> <stage>\t<path>` lines (stages 1/2/3 per file)
# until a blank line, then informational "CONFLICT (...)" messages. We parse the conflicted paths
# from the structured info block (one unique path per conflicted file).
_MERGE_CONFLICT_INFO_RE = re.compile(r"^[0-7]{6} [0-9a-f]+ [123]\t(.+)$")


def _run(args: list[str], *, cwd: Path | None = None, timeout: int = 30) -> str:
    try:
        return run_checked(["git", *args], cwd=cwd, timeout=timeout, env_overlay=_GIT_ENV)
    except ProcFailure as exc:
        raise GitError(str(exc)) from exc


def _run_capture(
    args: list[str], *, cwd: Path | None = None, timeout: int = 30
) -> subprocess.CompletedProcess[str]:
    """Run ``git <args>`` best-effort: returns the completed process **without raising** on a
    non-zero exit so callers can parse stdout/stderr on partial failure.

    The sanctioned primitive for best-effort batch ops (``delete_branches`` /
    ``delete_remote_branches``); ``_run`` (which raises ``GitError``) remains the default for
    single ops. A ``TimeoutExpired`` is still exceptional and raises ``GitError``.
    """
    try:
        return run_captured(["git", *args], cwd=cwd, timeout=timeout, env_overlay=_GIT_ENV)
    except ProcFailure as exc:
        raise GitError(str(exc)) from exc


def repo_root(cwd: Path) -> Path | None:
    """The repository root containing ``cwd``, or ``None`` if it is not a git repo."""
    try:
        out = _run(["rev-parse", "--show-toplevel"], cwd=cwd)
    except GitError:
        return None
    return Path(out.strip())


def main_worktree_root(cwd: Path) -> Path | None:
    """The MAIN working tree's root, even when ``cwd`` is inside a linked worktree.

    Resolves ``git rev-parse --git-common-dir`` (the shared ``.git`` of the main checkout) and
    returns its parent — equal to ``repo_root`` in the main checkout. ``None`` when ``cwd`` is
    not inside a git repo. Used to locate the gitignored ``.perk/local.toml`` secret, which
    lives only in the main checkout and is never copied into a linked worktree.
    """
    try:
        out = _run(["rev-parse", "--git-common-dir"], cwd=cwd)
    except GitError:
        return None
    common = Path(out.strip())
    if not common.is_absolute():
        common = (cwd / common).resolve()
    return common.parent


def is_tracked(repo: Path, path: Path | str) -> bool:
    """Whether ``path`` (relative to ``repo``) is tracked in the index. Offline; never raises."""
    try:
        out = _run(["ls-files", "--", str(path)], cwd=repo)
    except GitError:
        return False
    return bool(out.strip())


def tracked_paths(repo: Path, pathspecs: list[str]) -> list[str]:
    """The tracked paths under ``pathspecs`` (relative to ``repo``); ``[]`` when clean.

    One ``git ls-files -- <pathspecs…>`` probe (sibling of ``is_tracked``, which takes a single
    path and swallows failures). Propagates ``GitError`` — callers decide how a failed probe
    degrades (no silent pass).
    """
    out = _run(["ls-files", "--", *pathspecs], cwd=repo)
    return [line for line in out.splitlines() if line]


def ls_tree_names(repo: Path, ref: str, pathspec: str) -> list[str]:
    """The entry names under ``pathspec`` on ``ref`` (``git ls-tree --name-only``); ``[]`` if none.

    Reads the LOCAL view of ``ref`` (e.g. the ``origin/main`` remote-tracking ref) — no network.
    Propagates ``GitError`` (unknown ref, not a repo) — callers decide how a failed probe
    degrades (no silent pass).
    """
    out = _run(["ls-tree", "--name-only", ref, "--", pathspec], cwd=repo)
    return [line for line in out.splitlines() if line]


def rm_cached(repo: Path, path: Path | str, *, recursive: bool = False) -> None:
    """Stop tracking ``path`` without deleting the working-tree file(s) (``git rm --cached``).

    With ``recursive`` the removal descends into a directory (``git rm -r --cached``), untracking
    every tracked path under it in one subprocess — the plain form refuses a directory.
    """
    args = ["rm"]
    if recursive:
        args.append("-r")
    args += ["--cached", "--quiet", "--", str(path)]
    _run(args, cwd=repo)


def current_branch(repo: Path) -> str | None:
    """The current branch name, or ``None`` if detached."""
    try:
        out = _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    except GitError:
        return None
    branch = out.strip()
    return None if branch == "HEAD" else branch


def push(cwd: Path, branch: str, *, set_upstream: bool = True, force: bool = False) -> None:
    """Push ``branch`` to ``origin`` from ``cwd`` (the worktree).

    With ``force`` the push uses ``--force-with-lease`` (a no-op on a brand-new branch; it
    replaces a rewritten history safely on a perk-owned single-author plan branch). A
    non-fast-forward / lease rejection raises ``PushRejectedError``; other git failures raise
    ``GitError``.
    """
    args = ["push"]
    if force:
        args.append("--force-with-lease")
    if set_upstream:
        args += ["-u", "origin", branch]
    else:
        args += ["origin", branch]
    try:
        _run(args, cwd=cwd)
    except GitError as exc:
        msg = str(exc).lower()
        if any(marker in msg for marker in _REJECT_MARKERS):
            raise PushRejectedError(str(exc)) from exc
        raise


def push_atomic_with_leases(cwd: Path, updates: list[RefUpdate]) -> None:
    """Push every ``updates`` ref to ``origin`` in ONE ``--atomic`` operation, each under its
    exact ``--force-with-lease`` expectation — the multi-ref mutation the suffix-sync cascade
    runs (contracts.md §8.49): either every ref moves or none does.

    The argv carries the same safety controls as :func:`probe_atomic_push` (minus
    ``--dry-run``): ``-c push.pushOption=`` clears configured push options;
    ``--no-verify`` skips pre-push hooks (the settled hook posture — the cascade republishes
    already-reviewed content and must match what the capability probe proved);
    ``--no-signed --no-follow-tags --recurse-submodules=no`` pin the push to exactly the
    given ref updates. Only ``origin`` is targeted (parity with :func:`push`; multi-push-URL
    policy stays a preflight concern). Empty ``updates`` or an empty/absence lease raises
    ``ValueError`` (sync never pushes ref creations). A lease/non-fast-forward rejection
    raises ``PushRejectedError`` — the atomic guarantee means NO ref moved; other failures
    raise ``GitError``. A network op (generous timeout).
    """
    if not updates:
        raise ValueError("push_atomic_with_leases needs at least one ref update")
    for update in updates:
        if not update.expected_remote_sha:
            raise ValueError(
                f"ref update for {update.branch!r} carries an empty lease expectation — "
                "sync never pushes ref creations"
            )
    args = [
        "-c",
        "push.pushOption=",
        "push",
        "--atomic",
        "--porcelain",
        "--no-verify",
        "--no-signed",
        "--no-follow-tags",
        "--recurse-submodules=no",
        "origin",
        *[f"{u.new_sha}:refs/heads/{u.branch}" for u in updates],
        *[f"--force-with-lease=refs/heads/{u.branch}:{u.expected_remote_sha}" for u in updates],
    ]
    try:
        _run(args, cwd=cwd, timeout=120)
    except GitError as exc:
        msg = str(exc).lower()
        if any(marker in msg for marker in _REJECT_MARKERS):
            raise PushRejectedError(str(exc)) from exc
        raise


def push_with_exact_lease(
    cwd: Path, branch: str, *, expected_remote_sha: str | None, set_upstream: bool = True
) -> None:
    """Push ``branch`` to ``origin`` under an **exact** ``--force-with-lease`` expectation.

    The §8.42 concurrency primitive for stacked layer publication: the lease pins the exact
    remote SHA the caller observed (``expected_remote_sha``), so competing writers are
    arbitrated by the remote itself — the push succeeds only if the remote ref still sits at
    the observed value. ``None`` means "the ref must not exist" (the empty-expect absence
    lease git defines for first pushes). ``--atomic`` is deliberately absent: this pushes ONE
    ref; the multi-ref atomic suffix push is :func:`push_atomic_with_leases` (§8.49). Only
    ``origin`` is targeted (parity with :func:`push`; multi-push-URL policy stays a preflight
    concern). A lease rejection raises ``PushRejectedError``; other failures ``GitError``.
    """
    expect = expected_remote_sha if expected_remote_sha is not None else ""
    args = ["push", "--porcelain"]
    if set_upstream:
        args += ["-u", "origin", branch]
    else:
        args += ["origin", branch]
    args.append(f"--force-with-lease=refs/heads/{branch}:{expect}")
    try:
        _run(args, cwd=cwd)
    except GitError as exc:
        msg = str(exc).lower()
        if any(marker in msg for marker in _REJECT_MARKERS):
            raise PushRejectedError(str(exc)) from exc
        raise


def is_dirty(cwd: Path) -> bool:
    """True if the worktree at ``cwd`` has uncommitted changes (tracked or untracked)."""
    return bool(_run(["status", "--porcelain"], cwd=cwd).strip())


def fetch(repo: Path, *, remote: str = "origin") -> None:
    """Fetch ``remote`` into ``repo`` (a **network** op; ``GitError`` on failure).

    Callers that need offline tolerance should treat the failure as best-effort. A longer
    ``timeout`` than the default is used because the network can be slow.
    """
    _run(["fetch", remote], cwd=repo, timeout=120)


def fetch_refspecs(
    repo: Path, refspecs: list[str], *, remote: str = "origin", timeout: int = 120
) -> None:
    """Fetch explicit ``refspecs`` from ``remote`` (a **network** op; ``GitError`` on failure).

    A refspec may be a forcing dst-qualified refspec (``+refs/pull/N/head:refs/perk/review/N``)
    or a bare branch name — the bare form also updates the remote-tracking ref
    (``refs/remotes/<remote>/<branch>``), the behavior ``detect_merge_conflicts`` relies on for
    its ``git fetch origin <base>`` step. Uses the generous network ``timeout`` like ``fetch``.
    """
    _run(["fetch", remote, *refspecs], cwd=repo, timeout=timeout)


def checkout_branch(repo: Path, name: str) -> None:
    """Check out the existing branch ``name`` (``git checkout <name>``); ``GitError`` on
    failure. Mutates the working tree — the remote-positioning path runs it on a clean CI
    checkout."""
    _run(["checkout", name], cwd=repo)


def create_branch_at(repo: Path, name: str, start: str) -> None:
    """Create AND check out branch ``name`` at ``start`` (``git checkout -b <name> <start>``);
    ``GitError`` on failure (including an already-existing branch)."""
    _run(["checkout", "-b", name, start], cwd=repo)


def reset_hard(repo: Path, ref: str) -> None:
    """Hard-reset the current branch + working tree to ``ref`` (``git reset --hard <ref>``);
    ``GitError`` on failure. Destructive by design — callers own the "this tree is
    disposable" judgment (the CI positioning checkout is)."""
    _run(["reset", "--hard", ref], cwd=repo)


def upstream_ref(repo: Path) -> str | None:
    """The current branch's upstream tracking ref (e.g. ``origin/main``), or ``None``.

    Reads ``git rev-parse --abbrev-ref --symbolic-full-name @{upstream}`` — local refs only (no
    network). Returns ``None`` when there is no upstream configured or HEAD is detached
    (``GitError`` → ``None``), so callers degrade rather than break.
    """
    try:
        out = _run(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], cwd=repo)
    except GitError:
        return None
    ref = out.strip()
    return ref or None


def merge_ff_only(repo: Path, ref: str) -> bool:
    """Fast-forward the current branch to ``ref`` (``git merge --ff-only <ref>``); best-effort.

    Returns ``True`` on a clean fast-forward (exit 0), ``False`` otherwise (a non-fast-forward /
    diverged history exits non-zero). Never raises on a non-FF result — runs through
    ``_run_capture`` (mirroring ``delete_branches``). A ``TimeoutExpired`` still raises
    ``GitError`` (inherited from ``_run_capture``). Mutates the working tree on success, so callers
    must guard on a clean tree + a real upstream first.
    """
    return _run_capture(["merge", "--ff-only", ref], cwd=repo).returncode == 0


def detect_trunk_branch(repo: Path, *, remote: str = "origin") -> str:
    """The repository's trunk branch name.

    (1) ``git symbolic-ref refs/remotes/<remote>/HEAD`` → strip the ``refs/remotes/<remote>/``
    prefix; (2) fallback — the first of ``main``/``master`` that exists as a local head;
    (3) final fallback ``"main"``. Each probe is local-only (no network) and a missing ref is
    swallowed rather than raised.
    """
    prefix = f"refs/remotes/{remote}/"
    try:
        out = _run(["symbolic-ref", f"{prefix}HEAD"], cwd=repo).strip()
        if out.startswith(prefix):
            return out.removeprefix(prefix)
    except GitError:
        pass
    for candidate in ("main", "master"):
        try:
            _run(["show-ref", "--verify", "--quiet", f"refs/heads/{candidate}"], cwd=repo)
            return candidate
        except GitError:
            continue
    return "main"


def remote_branch_head(repo: Path, branch: str, *, remote: str = "origin") -> str | None:
    """The SHA at ``refs/heads/<branch>`` on ``remote`` (a **network** op via ``ls-remote``).

    ``None`` when the remote has no such branch (an absent remote ref is an ordinary
    observation, never an error); ``GitError`` on a network/infra failure. Works from a fresh
    clone — unlike :func:`remote_ref_exists` it asks the remote itself, not local
    remote-tracking refs. Uses the generous network ``timeout`` like :func:`fetch`.
    """
    out = _run(["ls-remote", remote, f"refs/heads/{branch}"], cwd=repo, timeout=120)
    for line in out.splitlines():
        sha, _, ref = line.partition("\t")
        if ref.strip() == f"refs/heads/{branch}" and sha:
            return sha.strip()
    return None


def push_urls(repo: Path, remote: str = "origin") -> list[str]:
    """The push URLs configured for ``remote`` (``git remote get-url --push --all``).

    A remote may carry multiple push URLs (mirrors); an atomic-push capability probe must
    verify every one individually. Local config read only (no network). Raises ``GitError``
    when the remote is not configured.
    """
    out = _run(["remote", "get-url", "--push", "--all", remote], cwd=repo)
    return [line.strip() for line in out.splitlines() if line.strip()]


def probe_atomic_push(repo: Path, *, push_url: str, base_branch: str, base_sha: str) -> None:
    """The atomic-push capability probe: a **no-op** ``--atomic --dry-run`` push of the
    observed remote base SHA back to the base branch (contracts.md §8.45).

    Pushing ``<base_sha>:refs/heads/<base_branch>`` where ``base_sha`` IS the observed remote
    head is an up-to-date no-op, so the probe never mutates the remote; ``--dry-run`` guards
    the race where the remote moved. ``-c push.pushOption=`` clears any configured push
    options; ``--no-verify --no-signed --no-follow-tags --recurse-submodules=no`` pin the
    probe to exactly one ref update. Success proves the server accepts atomic pushes and the
    authentication works — **not** branch write permission (a protected branch can still
    reject the real push). A network op (generous timeout, ``GIT_TERMINAL_PROMPT=0`` via the
    module env); raises ``GitError`` on failure.
    """
    _run(
        [
            "-c",
            "push.pushOption=",
            "push",
            "--atomic",
            "--dry-run",
            "--no-verify",
            "--no-signed",
            "--no-follow-tags",
            "--recurse-submodules=no",
            "--porcelain",
            push_url,
            f"{base_sha}:refs/heads/{base_branch}",
        ],
        cwd=repo,
        timeout=120,
    )


def remote_ref_exists(repo: Path, ref: str) -> bool:
    """Whether ``ref`` (e.g. ``origin/main``) resolves locally. Reads local refs only (no
    network) so it is offline-safe and dry-run-safe."""
    try:
        _run(["rev-parse", "--verify", "--quiet", ref], cwd=repo)
    except GitError:
        return False
    return True


def detect_merge_conflicts(repo: Path, *, base: str, branch_ref: str = "HEAD") -> MergeProbe:
    """Best-effort probe: would merging ``branch_ref`` onto ``origin/<base>`` conflict?

    A deterministic, local ``git merge-tree --write-tree`` probe (no GitHub round-trip, no reliance
    on GitHub's eventually-consistent ``mergeable`` field). **Fail-open**: any step that can't run
    cleanly (offline fetch, unresolvable base, old git lacking ``--write-tree``) yields
    ``MergeProbe(determined=False, ())`` so the caller degrades rather than breaks. Never raises
    (a fetch ``GitError`` is swallowed; ``merge-tree`` runs best-effort via ``_run_capture``).

    1. Best-effort ``git fetch origin <base>`` — a failure means undetermined.
    2. Resolve ``origin/<base>`` locally; an unresolvable ref means undetermined.
    3. ``git merge-tree --write-tree origin/<base> <branch_ref>`` exits 0 (clean) or 1 (conflicts),
       printing the conflicted paths in its structured info block. Other exit codes → undetermined.
    """
    remote_base = f"origin/{base}"
    try:
        _run(["fetch", "origin", base], cwd=repo, timeout=120)
    except GitError:
        return MergeProbe(determined=False, mergeable=False, conflicts=())
    if not remote_ref_exists(repo, remote_base):
        return MergeProbe(determined=False, mergeable=False, conflicts=())
    proc = _run_capture(["merge-tree", "--write-tree", remote_base, branch_ref], cwd=repo)
    if proc.returncode == 0:
        return MergeProbe(determined=True, mergeable=True, conflicts=())
    if proc.returncode == 1:
        # Conflict exit: mergeable is False from the EXIT CODE, independent of whether the
        # conflicted paths parsed (an unparseable nonzero exit still means conflicts present).
        return MergeProbe(
            determined=True, mergeable=False, conflicts=_parse_merge_conflicts(proc.stdout)
        )
    # Old git (no --write-tree), bad ref, etc. — fail-open.
    return MergeProbe(determined=False, mergeable=False, conflicts=())


def _parse_merge_conflicts(stdout: str) -> tuple[str, ...]:
    """Parse unique conflicted paths from ``git merge-tree --write-tree`` stdout.

    The conflicted-file-info block (after the line-1 tree OID, up to the first blank line) carries
    one ``<mode> <object> <stage>\t<path>`` line per stage per conflicted file; we collect each
    path once, preserving first-seen order. An unparseable-but-nonzero output yields ``()`` — the
    caller still treats a determined nonzero exit as "conflicts present".
    """
    paths: list[str] = []
    seen: set[str] = set()
    for line in stdout.splitlines()[1:]:
        if line == "":
            break
        match = _MERGE_CONFLICT_INFO_RE.match(line)
        if match is None:
            continue
        path = match.group(1)
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return tuple(paths)


def resolve_commit(repo: Path, ref: str) -> str | None:
    """Full 40-char commit SHA that ``ref`` peels to, or ``None`` when it does not resolve.

    Peels tags/branches/short-hashes to a commit via ``rev-parse --verify --quiet <ref>^{commit}``;
    an unresolvable ref exits non-zero → GitError → None (LBYL, mirrors ``remote_ref_exists``).
    """
    try:
        out = _run(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd=repo)
    except GitError:
        return None
    return out.strip() or None


def merge_base(repo: Path, a: str, b: str) -> str | None:
    """The full SHA of ``git merge-base <a> <b>``, or ``None`` when there is none.

    ``GitError`` → ``None`` (LBYL, mirrors ``resolve_commit``); ``None`` covers both an
    unresolvable ref and unrelated histories (no common ancestor).
    """
    try:
        out = _run(["merge-base", a, b], cwd=repo)
    except GitError:
        return None
    return out.strip() or None


def update_ref(repo: Path, ref: str, sha: str) -> None:
    """Create or update ``ref`` to point at ``sha`` (``git update-ref <ref> <sha>``);
    ``GitError`` on failure. The temp-ref writer (e.g. sync's ``refs/perk/sync/…`` candidate
    refs); complements :func:`delete_ref`."""
    _run(["update-ref", ref, sha], cwd=repo)


def list_refs(repo: Path, prefix: str) -> list[str]:
    """The full refnames under ``prefix`` (``git for-each-ref --format=%(refname)``); ``[]``
    when none. The namespace enumeration ``delete``-side cleanup needs — unlike
    :func:`local_branches` it is not limited to ``refs/heads/*``. Raises ``GitError`` on
    failure."""
    out = _run(["for-each-ref", "--format=%(refname)", prefix], cwd=repo)
    return [line for line in out.splitlines() if line]


def checkout_detached(repo: Path, sha: str) -> None:
    """Detach HEAD at ``sha`` (``git checkout --detach <sha>``); ``GitError`` on failure.

    Repositions an existing (typically isolated) worktree between operations — distinct from
    :func:`worktree_add_detached`, which only creates the worktree.
    """
    _run(["checkout", "--detach", sha], cwd=repo)


def rebase_in_progress(worktree: Path) -> bool:
    """Whether ``worktree`` has a rebase in progress — the OBSERVABLE state check
    (worktree-specific ``rebase-merge`` / ``rebase-apply`` directories via
    ``git rev-parse --git-path``), never prose matching. Raises ``GitError`` on failure."""
    for kind in ("rebase-merge", "rebase-apply"):
        out = _run(["rev-parse", "--git-path", kind], cwd=worktree).strip()
        path = Path(out)
        if not path.is_absolute():
            path = worktree / path
        if path.exists():
            return True
    return False


def rebase_onto(worktree: Path, *, onto: str, upstream: str) -> RebaseOutcome:
    """Transplant the current (detached) HEAD's ``upstream..HEAD`` range onto ``onto``
    (``git rebase --onto <onto> <upstream>``), classifying the outcome by observable state.

    Zero exit → :class:`RebaseCompleted` with the rebased HEAD. A nonzero exit is classified
    by :func:`rebase_in_progress` — never by matching git's prose: in-progress →
    :class:`RebaseConflict` with the conflicted state deliberately RETAINED (no automatic
    ``--abort``; the caller owns continuation/abort); not-in-progress (e.g. an invalid
    ``upstream``) → ``GitError``.
    """
    proc = _run_capture(["rebase", "--onto", onto, upstream], cwd=worktree, timeout=120)
    if proc.returncode == 0:
        head = _run(["rev-parse", "HEAD"], cwd=worktree).strip()
        return RebaseCompleted(head_sha=head)
    detail = f"{proc.stdout}\n{proc.stderr}".strip()[-2000:]
    if rebase_in_progress(worktree):
        return RebaseConflict(detail=detail)
    raise GitError(
        f"git rebase --onto {onto} {upstream} failed without a retained rebase state: {detail}"
    )


def delete_ref(repo: Path, ref: str) -> None:
    """Delete ``ref`` (``git update-ref -d <ref>``); ``GitError`` on failure — callers decide
    whether the delete is best-effort. Deleting an already-absent ref is a git no-op (exit 0),
    so the delete is naturally idempotent."""
    _run(["update-ref", "-d", ref], cwd=repo)


def log_first_parent(repo: Path, *, since: str, until: str = "HEAD") -> list[CommitInfo]:
    """First-parent commits in ``<since>..<until>`` (newest first), each with its changed paths.

    Two ``git log --first-parent`` passes: metadata (RS/US-delimited hash/subject/body) and a
    ``--name-only`` pass keyed by hash. An empty range yields ``[]``. Raises ``GitError`` if
    ``since`` is unresolvable (callers resolve it first via ``resolve_commit``).

    A commit body containing the ``\x1e`` record separator is truncated at it and the orphaned
    fragment is dropped by the field-count guard (silent by design — delimiter collisions are
    vanishingly rare and non-fatal). A body containing ``\x1f`` survives intact (``maxsplit=2``).
    """
    rng = f"{since}..{until}"
    meta = _run(["log", rng, "--first-parent", "--format=%x1e%H%x1f%s%x1f%b"], cwd=repo)
    names = _run(["log", rng, "--first-parent", "--name-only", "--format=%x1e%H"], cwd=repo)

    files_by_hash: dict[str, tuple[str, ...]] = {}
    for chunk in names.split("\x1e"):
        lines = chunk.splitlines()
        if not lines:
            continue
        files_by_hash[lines[0]] = tuple(line for line in lines[1:] if line)

    commits: list[CommitInfo] = []
    for chunk in meta.split("\x1e"):
        if not chunk:
            continue
        fields = chunk.rstrip("\n").split("\x1f", 2)
        if len(fields) < 3:
            continue
        commit_hash, subject, body = fields
        commits.append(
            CommitInfo(
                hash=commit_hash,
                subject=subject,
                body=body,
                files=files_by_hash.get(commit_hash, ()),
            )
        )
    return commits


def worktree_add(
    repo: Path, path: Path, *, branch: str, create_branch: bool, base: str | None = None
) -> None:
    """Add a worktree at ``path``; create ``branch`` when ``create_branch``.

    When ``create_branch`` and ``base`` is given, the new branch starts at ``base`` (a
    start-point ref, e.g. ``origin/main``); otherwise it starts at the repo's current HEAD.
    """
    if create_branch:
        args = ["worktree", "add", "-b", branch, str(path)]
        if base is not None:
            args.append(base)
        _run(args, cwd=repo)
    else:
        _run(["worktree", "add", str(path), branch], cwd=repo)


def worktree_add_detached(repo: Path, path: Path, commit: str) -> None:
    """Add a **detached** worktree at ``path``, checked out at ``commit``.

    A separate function, not a ``worktree_add`` flag — branch-create semantics don't mix with
    detached-at-a-SHA. Detached cannot collide with a branch another worktree has checked out
    (the reason the review checkout uses it), and leaves no branch to create or delete.
    """
    _run(["worktree", "add", "--detach", str(path), commit], cwd=repo)


def local_branches(repo: Path, pattern: str) -> list[str]:
    """Local branch names matching ``pattern`` (``git branch --list``), as short names.

    ``--format=%(refname:short)`` sidesteps the ``*``/``+`` checked-out markers the default
    listing prefixes, so the returned names are clean. Raises ``GitError`` on failure.
    """
    out = _run(["branch", "--list", pattern, "--format=%(refname:short)"], cwd=repo)
    return [line for line in out.splitlines() if line]


def delete_branch(repo: Path, name: str, *, force: bool = False) -> None:
    """Delete local branch ``name``. ``-d`` (safe: refuses an unmerged branch) unless ``force``."""
    flag = "-D" if force else "-d"
    _run(["branch", flag, name], cwd=repo)


def delete_branches(repo: Path, names: list[str], *, force: bool = False) -> list[str]:
    """Batched local branch delete: ``git branch -D|-d <names…>`` (one subprocess).

    Best-effort — never raises on a per-branch failure (a branch git refused or couldn't find
    simply won't appear in the returned list). Returns the branch names git confirmed deleted,
    parsed from the ``Deleted branch <name>`` stdout lines. Empty ``names`` is a no-op → ``[]``
    (no subprocess).
    """
    if not names:
        return []
    flag = "-D" if force else "-d"
    proc = _run_capture(["branch", flag, *names], cwd=repo)
    return _DELETED_BRANCH_RE.findall(proc.stdout)


def has_remote(repo: Path, name: str = "origin") -> bool:
    """Whether ``name`` is a configured remote of ``repo`` (``git remote``). Local, never raises."""
    proc = _run_capture(["remote"], cwd=repo)
    return name in proc.stdout.split()


def remote_tag_commit(
    repo: Path, tag: str, *, remote: str = "origin", timeout: int = 120
) -> str | None:
    """The commit SHA ``refs/tags/<tag>`` points to on ``remote``, or ``None`` when absent.

    A single ``git ls-remote --tags`` probe (network op — uses a generous ``timeout`` like
    ``fetch``). Prefers the peeled ``refs/tags/<tag>^{}`` line (annotated tags peel to their
    commit); falls back to the tag-ref line itself (a lightweight tag points directly at the
    commit). ``None`` means the remote *answered* and the tag is absent; a failed probe
    (offline / bad remote / timeout) raises ``GitError`` so callers can distinguish *absent*
    from *unknown*.
    """
    ref = f"refs/tags/{tag}"
    # Both patterns are passed explicitly: an exact ref pattern alone SUPPRESSES the peeled
    # `^{}` line ls-remote would otherwise print for an annotated tag (patterns match ref
    # names, and the peeled pseudo-ref only matches when asked for by name).
    out = _run(["ls-remote", "--tags", remote, ref, f"{ref}^{{}}"], cwd=repo, timeout=timeout)
    peeled: str | None = None
    plain: str | None = None
    for line in out.splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        sha, name = parts
        if name == f"{ref}^{{}}":
            peeled = sha
        elif name == ref:
            plain = sha
    return peeled if peeled is not None else plain


def tags_pointing_at(repo: Path, ref: str = "HEAD") -> list[str]:
    """The tag names pointing at ``ref`` (``git tag --points-at``); ``[]`` when untagged.

    Annotated tags count as "pointing at" the commit they peel to. Local refs only (no
    network). Raises ``GitError`` (e.g. an unresolvable ``ref``).
    """
    out = _run(["tag", "--points-at", ref], cwd=repo)
    return [line for line in out.splitlines() if line]


def create_annotated_tag(repo: Path, name: str, *, message: str) -> None:
    """Create an **annotated** tag ``name`` at HEAD (``git tag -a -m``).

    Raises ``GitError`` when git refuses (e.g. the tag already exists) — callers decide
    whether an existing tag is a no-op or a conflict *before* calling.
    """
    _run(["tag", "-a", name, "-m", message], cwd=repo)


def push_tag(repo: Path, name: str, *, remote: str = "origin", timeout: int = 120) -> None:
    """Push ``refs/tags/<name>`` to ``remote`` (a **network** op; generous ``timeout``).

    Deliberately not routed through ``push()`` — that carries branch/upstream/lease
    semantics a tag push must not inherit. Pushing an identical existing remote tag is a
    git no-op ("Everything up-to-date"). Raises ``GitError`` on failure.
    """
    _run(["push", remote, f"refs/tags/{name}"], cwd=repo, timeout=timeout)


def delete_remote_branches(
    repo: Path, names: list[str], *, remote: str = "origin", timeout: int = 120
) -> list[str]:
    """Batched remote branch delete: ``git push <remote> --delete <survivors…>`` (best-effort).

    ``git push --delete`` aborts the **whole** batch client-side if *any* ref is missing
    (``remote ref does not exist``) — and an already-gone ref is the common case (GitHub's
    auto-delete-on-merge). So we probe ``git ls-remote --heads`` once and delete only the refs
    that still exist (the already-gone ones are silently treated as success). Never raises: a
    total failure (offline / no perms / all refs already gone) yields ``[]``. Returns the branch
    names confirmed deleted, parsed from the ``[deleted]`` lines git writes to stderr. Empty
    ``names`` is a no-op → ``[]``. Callers should guard with ``has_remote`` so a remote-less repo
    is a clean no-op (uses a network ``timeout`` like ``fetch``).
    """
    if not names:
        return []
    probe = _run_capture(["ls-remote", "--heads", remote, *names], cwd=repo, timeout=timeout)
    existing = {
        line.split("refs/heads/", 1)[1]
        for line in probe.stdout.splitlines()
        if "refs/heads/" in line
    }
    survivors = [n for n in names if n in existing]
    if not survivors:
        return []
    proc = _run_capture(["push", remote, "--delete", *survivors], cwd=repo, timeout=timeout)
    return _DELETED_REMOTE_RE.findall(proc.stderr)


def worktree_list(repo: Path) -> list[Worktree]:
    """All worktrees of ``repo`` (parsed from ``--porcelain``)."""
    return _parse_worktrees(_run(["worktree", "list", "--porcelain"], cwd=repo))


# Worktree removal shells a large `rm -rf` over the gitignored `node_modules`/`.venv`/
# `.pi/npm/node_modules` trees a perk worktree carries — far more than the default 30 s.
_WORKTREE_REMOVE_TIMEOUT = 300


def _is_recoverable_remove_failure(message: str) -> bool:
    """Whether a ``git worktree remove`` ``GitError`` is one of the two self-healable refusals.

    Matches a slow `rm -rf` (``timed out``) and a broken worktree whose `.git` gitlink is gone
    (``validation failed`` — which ``--force`` does NOT bypass). A *dirty* refusal
    (``contains modified or untracked files`` / ``use --force``) is deliberately NOT matched, so
    it re-raises and keeps `perk worktree remove` protecting uncommitted work.
    """
    lowered = message.lower()
    return "timed out" in lowered or "validation failed" in lowered


def worktree_remove(repo: Path, path: Path, *, force: bool) -> None:
    """Remove the worktree at ``path``, self-healing the two recoverable git refusals.

    Primary path: ``git worktree remove [--force] <path>`` with a generous
    ``_WORKTREE_REMOVE_TIMEOUT`` (the heavy `rm -rf` of large gitignored trees). On a recoverable
    ``GitError`` (slow removal that ``timed out``, or a broken worktree whose missing `.git`
    fails ``validation``) it falls back to a Python ``shutil.rmtree`` (no subprocess timeout,
    copes with partial trees). A non-recoverable ``GitError`` (the dirty-protection refusal)
    re-raises unchanged.

    **Contract:** when the fallback path is taken the working dir is gone but the stale
    ``.git/worktrees/<id>`` admin entry lingers, so every caller MUST follow up with a
    (serialized) ``worktree_prune``. The fallback does NOT prune itself — pruning rewrites the
    whole worktree set and is unsafe under a concurrent removal pool, so it is the caller's job.
    """
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(path))
    try:
        _run(args, cwd=repo, timeout=_WORKTREE_REMOVE_TIMEOUT)
    except GitError as exc:
        if not _is_recoverable_remove_failure(str(exc)):
            raise
        if path.exists():
            try:
                shutil.rmtree(path)
            except OSError as os_exc:
                raise GitError(f"worktree remove fallback failed: {os_exc}") from os_exc


def worktree_prune(repo: Path) -> None:
    """Clear stale ``.git/worktrees/<id>`` admin entries (``git worktree prune``).

    Removes the admin records of worktrees whose working dir / `.git` gitlink is gone — including
    the residue a ``worktree_remove`` fallback leaves behind. Raises ``GitError`` on failure.

    **Serialize this** — ``git worktree prune`` rewrites the whole worktree set, so it must NOT
    run concurrently with the removal pool; callers run it once on the main thread.
    """
    _run(["worktree", "prune"], cwd=repo)


def _parse_worktrees(porcelain: str) -> list[Worktree]:
    worktrees: list[Worktree] = []
    path: Path | None = None
    branch: str | None = None
    head: str | None = None
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            path = Path(line.removeprefix("worktree "))
        elif line.startswith("HEAD "):
            head = line.removeprefix("HEAD ")
        elif line.startswith("branch "):
            branch = line.removeprefix("branch ").removeprefix("refs/heads/")
        elif line == "" and path is not None:
            worktrees.append(Worktree(path, branch, head))
            path, branch, head = None, None, None
    if path is not None:
        worktrees.append(Worktree(path, branch, head))
    return worktrees
