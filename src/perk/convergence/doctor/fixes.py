"""The ``--fix`` repair layer: config re-seed, Linear labels, and the migration seam."""

import filecmp
import shutil
from collections.abc import Callable
from pathlib import Path

from perk.backends import linear
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import client as linear_client
from perk.convergence import init
from perk.convergence.doctor.data import Check
from perk.convergence.doctor.linear_checks import _linear_selected
from perk.state import cache
from perk.substrate import git, paths
from perk.substrate.config import load_committed_issues_team

# --- fixes ----------------------------------------------------------------------------------


def _strip_ungrouped_ignore_line(text: str, line: str) -> str:
    """Drop standalone ``line`` occurrences that sit OUTSIDE the perk-managed block.

    `init` now owns the line *inside* the managed block; an identical hand-added line outside it
    is a stray duplicate. Lines within `# BEGIN/END perk managed` are preserved untouched.
    """
    out: list[str] = []
    inside = False
    for raw in text.splitlines(keepends=True):
        stripped = raw.strip()
        if stripped == init.GITIGNORE_BEGIN:
            inside = True
        elif stripped == init.GITIGNORE_END:
            inside = False
        elif not inside and stripped == line:
            continue
        out.append(raw)
    return "".join(out)


def _untrack_materialized_plan_cache(root: Path) -> tuple[list[str], list[str]]:
    """Repair the legacy tracked `cache.plan` body + its stray ungrouped `.gitignore` line.

    `.pi/workflow/plan.md` is a transient materialized cache (contracts.md §8.1) — it was always
    gitignored and never tracked. Post-move the managed block no longer ignores it (the whole
    `.perk/workflow/` tree is gitignored instead), so a hand-added ungrouped
    `/.pi/workflow/plan.md` ignore line is now a fully-legacy stray (no longer a managed
    duplicate). This forward-only repair removes the stray line and `git rm --cached`s a tracked
    legacy file; it is a no-op (returns `([], [])`) once converged, so `--fix` stays idempotent.
    Returns ``(changes, errors)`` — a failed untrack is reported, never swallowed.
    """
    changes: list[str] = []
    errors: list[str] = []
    rel = ".pi/workflow/plan.md"
    gitignore = root / ".gitignore"
    if gitignore.is_file():
        text = gitignore.read_text(encoding="utf-8")
        pruned = _strip_ungrouped_ignore_line(text, f"/{rel}")
        if pruned != text:
            gitignore.write_text(pruned, encoding="utf-8")
            changes.append(".gitignore: removed stray /.pi/workflow/plan.md (now managed)")
    if git.is_tracked(root, rel):
        try:
            git.rm_cached(root, rel)
            changes.append(".pi/workflow/plan.md: untracked (transient cache.plan body)")
        except git.GitError as exc:
            errors.append(f"{rel}: untrack failed (git rm --cached): {exc}")
    return changes, errors


def _migrate_legacy_workflow_cache(root: Path) -> tuple[list[str], list[str]]:
    """Migrate a legacy `.pi/workflow/` cache forward to `.perk/workflow/`.

    The workflow cache root moved from `.pi/workflow/` to `.perk/workflow/`
    (the `cache.workflow_dir` seam). This forward-only, filesystem-only repair handles only the
    durable/active remnants (mirrors `_legacy_workflow_check`):

    - a tracked `.pi/workflow/.gitkeep` (the old committed layout sentinel) → `git rm --cached`;
    - the simple active root mirrors (`plan-ref.json`/`agent-session.json`) → `shutil.move` to
      `.perk/workflow/` **only when the target is absent** (never clobber a live target).

    Disposable scratch (run dirs, handoff blobs, markers) is **never** merged/moved/deleted — it is
    gitignored cache the user may delete at leisure (the roadmap's workflow-cache rule). Idempotent
    (returns `([], [])` once converged). Legacy paths are flat-string literals (exempt from the
    operator-adjacency `paths` guard). Returns ``(changes, errors)`` — failures land loudly on
    `fix_errors`, never swallowed.
    """
    changes: list[str] = []
    errors: list[str] = []
    legacy = root / ".pi/workflow"
    target = cache.workflow_dir(root)
    gitkeep_rel = ".pi/workflow/.gitkeep"
    if git.is_tracked(root, gitkeep_rel):
        try:
            git.rm_cached(root, gitkeep_rel)
            changes.append(f"{gitkeep_rel}: untracked (legacy committed layout sentinel)")
        except git.GitError as exc:
            errors.append(f"{gitkeep_rel}: untrack failed (git rm --cached): {exc}")
    for name in ("plan-ref.json", "agent-session.json"):
        src = legacy / name
        dst = target / name
        if src.is_file() and not dst.exists():
            try:
                target.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                changes.append(f".pi/workflow/{name}: moved to .perk/workflow/{name}")
            except OSError as exc:
                errors.append(f".pi/workflow/{name}: migration failed: {exc}")
    return changes, errors


def _remove_orphaned_git_clone(root: Path) -> tuple[list[str], list[str]]:
    """Migrate a former git-clone consumer forward by removing the orphaned on-disk clone.

    The `npm:@mgiles/perk` install path superseded pi's `git:`-clone extension lifecycle, leaving a
    consumer that was previously on the clone with an orphaned `.pi/git/<host>/<path>` tree. This
    forward-only repair `rmtree`s it once (filesystem-only, gitignored path — no network); it is a
    no-op (returns `([], [])`) once the clone is absent, so `--fix` stays idempotent. Returns
    ``(changes, errors)`` — a failed removal is reported, never swallowed.
    """
    changes: list[str] = []
    errors: list[str] = []
    clone = init.consumer_git_clone_root(root)
    if clone.is_dir():
        rel = clone.relative_to(root)
        try:
            shutil.rmtree(clone)
            changes.append(
                f"{rel}: removed orphaned perk clone (migrated to @mgiles/perk npm install)"
            )
        except OSError as exc:
            errors.append(f"{rel}: orphaned-clone removal failed (rmtree): {exc}")
    return changes, errors


def _dirs_identical(left: Path, right: Path) -> bool:
    """True iff two directory trees hold the same relative files, every counterpart byte-identical.

    Any structural divergence (a file present on only one side, a differing/unreadable file,
    recursively) ⇒ not identical. Used to decide whether a legacy skill dir is redundant (safe to
    drop) or conflicting (left in place, reported).
    """
    cmp = filecmp.dircmp(left, right)
    # `common_funny` catches same-name type collisions (a dir on one side, a file on the other) —
    # `dircmp` files those there, not in the other buckets, so they must be rejected explicitly.
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files or cmp.common_funny:
        return False
    # `dircmp`'s `diff_files` is a shallow (size+mtime) signature compare; force a byte-for-byte
    # content compare so equal-stat-but-differing files are caught (D4 requires byte-identity).
    _, mismatch, errors = filecmp.cmpfiles(left, right, cmp.common_files, shallow=False)
    if mismatch or errors:
        return False
    return all(_dirs_identical(left / sub, right / sub) for sub in cmp.common_dirs)


def _migrate_legacy_repo_skills(root: Path) -> tuple[list[str], list[str]]:
    """Migrate repo-authored skill source forward from legacy `.pi/skills/` to `.perk/skills/`.

    Objective #878 moved the repo-skills source root from `.pi/skills/` to `.perk/skills/` (the
    `paths.repo_skills_dir` seam). This forward-only, filesystem-only repair relocates any skill
    still under the frozen legacy `.pi/skills/<name>` root:

    - target absent → `shutil.move` it to `.perk/skills/<name>`;
    - target present and byte-identical → drop the redundant legacy copy;
    - target present and differing → leave it, report a conflict for manual resolution.

    Idempotent (returns `([], [])` once `.pi/skills/` is gone). The fragment is re-rendered later by
    the verify-gated repo-skills reconverge from the new location — no fragment bookkeeping here.
    Returns ``(changes, errors)`` — failures land loudly on `fix_errors`, never swallowed.
    """
    changes: list[str] = []
    errors: list[str] = []
    legacy_root = root / ".pi/skills"
    if not legacy_root.is_dir():
        return changes, errors
    target_root = paths.repo_skills_dir(root)
    for child in sorted(p for p in legacy_root.iterdir() if p.is_dir()):
        name = child.name
        target = target_root / name
        try:
            if not target.exists():
                target_root.mkdir(parents=True, exist_ok=True)
                shutil.move(str(child), str(target))
                changes.append(f".pi/skills/{name}: moved to .perk/skills/{name}")
            elif _dirs_identical(child, target):
                shutil.rmtree(child)
                changes.append(
                    f".pi/skills/{name}: removed legacy (identical to .perk/skills/{name})"
                )
            else:
                errors.append(
                    f".pi/skills/{name}: conflicts with .perk/skills/{name} "
                    "(not identical) — resolve manually"
                )
        except OSError as exc:
            errors.append(f".pi/skills/{name}: migration failed: {exc}")
    if legacy_root.is_dir() and not any(legacy_root.iterdir()):
        try:
            legacy_root.rmdir()
        except OSError as exc:
            errors.append(f".pi/skills: removal of empty legacy dir failed (rmdir): {exc}")
    return changes, errors


def _migrate_legacy_config(root: Path) -> tuple[list[str], list[str]]:
    """Migrate the legacy `.pi/perk.toml` / `.pi/perk.local.toml` config to `.perk/`.

    Forward-only and idempotent (a no-op `([], [])` once converged). The committed and local
    files migrate **independently** (committed↔committed, local↔local), so the gitignored local
    secret is **never** copied into the committed file. Per file:

    - legacy absent → skip (already migrated / never existed);
    - target absent → move legacy → target (creating `.perk/`);
    - target present and **byte-identical** → remove the redundant legacy file;
    - target present and **differs** → error (resolve by hand) — never clobber either side.

    Secret-safety is by construction: messages/errors carry **paths only**, never config values
    (the byte-compare logs nothing); the local target is gitignored by the managed `.gitignore`
    block (regenerated in the same `--fix`). Returns ``(changes, errors)``.
    """
    changes: list[str] = []
    errors: list[str] = []
    pairs = (
        (paths.legacy_config_file(root), paths.config_file(root)),
        (paths.legacy_local_config_file(root), paths.local_config_file(root)),
    )
    for legacy, target in pairs:
        if not legacy.is_file():
            continue
        legacy_rel = legacy.relative_to(root)
        target_rel = target.relative_to(root)
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy), str(target))
            changes.append(f"{legacy_rel}: migrated to {target_rel}")
        elif legacy.read_bytes() == target.read_bytes():
            legacy.unlink()
            changes.append(f"{legacy_rel}: removed (identical to {target_rel})")
        else:
            errors.append(
                f"{legacy_rel} and {target_rel} differ — resolve by hand, then remove {legacy_rel}"
            )
    return changes, errors


def _untrack_subagent_artifacts(root: Path) -> tuple[list[str], list[str]]:
    """Untrack legacy-committed `.pi-subagents/` run artifacts (files kept on disk).

    `.pi-subagents/` is the borrowed `pi-subagents` engine's project-scoped transient artifact
    root, newly ignored by the managed `.gitignore` block — but a gitignore rule is inert for
    already-tracked files, so this forward-only repair `git rm -r --cached`s any tracked paths
    under it. Idempotent (a no-op `([], [])` once nothing is tracked). Returns
    ``(changes, errors)`` — a failed probe or untrack is reported, never swallowed.
    """
    changes: list[str] = []
    errors: list[str] = []
    rel = ".pi-subagents"
    try:
        tracked = git.tracked_paths(root, [rel])
    except git.GitError as exc:
        return changes, [f"{rel}: tracked-paths probe failed (git ls-files): {exc}"]
    if tracked:
        try:
            git.rm_cached(root, rel, recursive=True)
            changes.append(
                f"{rel}: untracked {len(tracked)} transient subagent artifact(s) (kept on disk)"
            )
        except git.GitError as exc:
            errors.append(f"{rel}: untrack failed (git rm -r --cached): {exc}")
    return changes, errors


# The legacy/one-off migration seam.
# Forward-only repairs for oddities `init` does not undo (e.g. a previously-tracked transient
# cache file). Each must be idempotent: a no-op (`([], [])`) once the repo is converged; each
# returns `(changes, errors)` so failures land loudly on `fix_errors`.
_MIGRATIONS: tuple[Callable[[Path], tuple[list[str], list[str]]], ...] = (
    _untrack_materialized_plan_cache,
    _migrate_legacy_workflow_cache,
    _remove_orphaned_git_clone,
    _migrate_legacy_repo_skills,
    _migrate_legacy_config,
    _untrack_subagent_artifacts,
)


def _fix_config(root: Path) -> list[str]:
    """Re-seed *missing* config files only (never overwrite a present/edited one)."""
    changes: list[str] = []
    init.converge_config(root, changes, force=False, interactive=False)
    return changes


def _fix_linear_labels(root: Path) -> tuple[list[str], list[str]]:
    """The verify-gated `--fix` label repair: ensure the five perk labels in Linear.

    Only acts when linear is selected AND key + team are available (otherwise the warn-level
    `linear` group already carries the remediation — nothing repairable here). Idempotent
    (lookup-first → no created labels once converged), satisfying the doctor idempotency rule.
    Returns ``(fixed, errors)``.
    """
    if not _linear_selected(root):
        return [], []
    team = load_committed_issues_team(root)
    if team is None:
        return [], []
    try:
        client = linear_client.client_from_env()
    except IssueBackendError:
        return [], []
    readiness = linear.check_readiness(client, team_key=team, ensure_labels=True)
    fixed = [f"Linear: created label {name}" for name in readiness.created_labels]
    errors = [f"Linear: label ensure failed: {readiness.error}"] if readiness.error else []
    return fixed, errors


def _apply_fixes(root: Path, self_repo: bool, checks: list[Check]) -> tuple[list[str], list[str]]:
    fixed: list[str] = []
    errors: list[str] = []
    mc_by_name = {mc.name: mc for mc in init.managed_convergences(root, self_repo)}
    for check in [c for c in checks if c.status == "fail"]:
        if check.name in mc_by_name:
            fixed.extend(mc_by_name[check.name].converge(True))
        elif check.name == "config":
            fixed.extend(_fix_config(root))
        elif check.name == "extension-install":
            # Install/reinstall the pinned @mgiles/perk under .pi/npm/ (the perk-owned install)
            # under a cross-process lock; best-effort + non-fatal. Only triggers when the
            # verify-gated check flagged `fail` (absent/mismatch) — a real change, so a message
            # is returned.
            message = init.materialize_extension_install(root, self_repo=self_repo)
            if message is not None:
                fixed.append(message)
    for migration in _MIGRATIONS:
        changes, migration_errors = migration(root)
        fixed.extend(changes)
        errors.extend(migration_errors)
    return fixed, errors
