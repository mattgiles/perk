"""Worktree materialization helpers for the cold-door launch.

The canonical materialization paths:
the ``[worktree] setup`` runner (:func:`run_worktree_setup`), the plan-body snapshot — split into
the one best-effort network read (:func:`fetch_plan_body`) and the silent local write
(:func:`write_plan_body_snapshot`), composed by :func:`materialize_plan_body` (the shape
``run_worker.position_worktree`` consumes; the cold-door launch calls the two halves separately so
the fetched body can also seed the handoff's naming hints) — the
per-skill symlink mirror (:func:`materialize_skills`), and the isolated extension-install staging
(:func:`materialize_extensions` — a copy-on-write clone or detached hardlinks, then a verification
against the worktree's own settings). The launch banner (:func:`print_launch_banner`) is the
idempotent once-per-process emitter that heads a real launch's output. ``_WORKTREE_SETUP_TIMEOUT_S``
(the per-command wall-clock cap) travels with
:func:`run_worktree_setup` and is re-exported by the package facade so
``launch._WORKTREE_SETUP_TIMEOUT_S`` resolves verbatim.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import click

from perk import __version__, plan
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.cli.ensure import UserFacingCliError
from perk.convergence.init.extension_install import consumer_npm_install_root
from perk.convergence.init.settings import _entry_spec, _npm_name, _npm_version
from perk.github import GitHubError
from perk.state import cache
from perk.substrate import fsclone
from perk.substrate.output import io_step, log_done, log_warn, user_output
from perk.substrate.semver import parse_semver

# Per-command wall-clock cap for `[worktree] setup` commands (10 minutes) — `uv sync` / `npm ci`
# can be slow on a cold cache, but a hung command must not wedge the launch forever.
_WORKTREE_SETUP_TIMEOUT_S = 600


def run_worktree_setup(worktree: Path, commands: list[str]) -> None:
    """Run the project's `[worktree] setup` commands, in order, inside a newly materialized
    worktree (freshly created or restored from the remote plan branch — the marker-gated
    ``launch.run_pending_setup`` decides *whether* to run; this function is the *how*).

    Each command runs via ``bash -lc <command>`` (the same mechanism the CI executor uses) with
    ``cwd`` = the worktree and **captured** stdio: output is swallowed on success (the per-command
    ``$`` echoes narrate progress), and the full captured output is replayed to stderr before the
    abort on failure. Each command has a ``_WORKTREE_SETUP_TIMEOUT_S`` (10-minute) wall-clock cap.

    Abort-on-failure: a non-zero exit, a timeout, or a missing ``bash`` raises a
    ``UserFacingCliError`` (``error_type="worktree_setup_failed"``) and stops before any later
    command runs — the caller aborts the launch (the worktree is left in place for a fixed re-run).
    A no-op when ``commands`` is empty (no subprocess).

    The single canonical setup-execution path; the cold door and ``perk worktree create`` both
    consume it through the marker-gated ``run_pending_setup`` (mirrors ``materialize_plan_body``).
    """
    if not commands:
        return
    # The `$ {command}` echoes stay `user_output` — they bump the output revision (disabling the
    # in-place rewrite), which is correct: they are the deliberate multi-line narration
    # (sub-bullets under the step line), so the final ✓ must append rather than rewrite in place.
    # The three raise paths escape the step (dangling + the error text below, as today).
    with io_step("running worktree setup") as s:
        for command in commands:
            user_output(f"    $ {command}")
            try:
                result = subprocess.run(
                    ["bash", "-lc", command],
                    cwd=worktree,
                    check=False,
                    timeout=_WORKTREE_SETUP_TIMEOUT_S,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                )
            except subprocess.TimeoutExpired as exc:
                raise UserFacingCliError(
                    f"worktree setup command timed out after {_WORKTREE_SETUP_TIMEOUT_S}s: "
                    f"{command}",
                    error_type="worktree_setup_failed",
                ) from exc
            except FileNotFoundError as exc:
                raise UserFacingCliError(
                    f"worktree setup needs `bash` on PATH to run: {command}\n"
                    "Install bash, or remove the [worktree] setup commands.",
                    error_type="worktree_setup_failed",
                ) from exc
            if result.returncode != 0:
                # Replay the full captured output — a failed setup aborts the launch, so complete
                # diagnostics beat terseness. The error message stays the one-liner so the
                # supervisor's --json error payload does not bloat with command output.
                if result.stdout:
                    user_output(result.stdout.rstrip("\n"))
                raise UserFacingCliError(
                    f"worktree setup command failed: {command} (exit {result.returncode})",
                    error_type="worktree_setup_failed",
                )
        s.done("worktree setup complete")


def fetch_plan_body(repo_root: Path, plan_ref: plan.PlanRef | None) -> str | None:
    """The ONE best-effort network read of the plan body from its canonical source.

    Returns the body when the fetch succeeded with content, else ``None`` — a missing/empty id,
    any backend failure, or an empty body. Best-effort: a failure is reported (the step resolves
    to a warn) but never blocks the launch (the snapshot is simply absent; ``perk pr
    review-context`` falls back to a live backend fetch). Honest, not silent. Backend-agnostic:
    the resolved issue backend owns the id shape (GitHub numeric, Linear ``ENG-123``).

    Performs no write — the caller decides where the body lands (:func:`write_plan_body_snapshot`)
    and may also derive naming hints from it, so the fetch can run before any persisted write.
    """
    if plan_ref is None:
        return None
    pr_id = plan_ref.pr_id.strip()
    if not pr_id:
        return None
    with io_step(f"fetching plan #{pr_id} body") as s:
        try:
            body = resolve.resolve_issue_backend(repo_root).get_plan_body(issue_id=pr_id)
        except (GitHubError, IssueBackendError) as exc:
            s.warn(f"plan snapshot: could not fetch plan #{pr_id} body — {exc}")
            return None
        if body:
            s.done(f"fetched plan #{pr_id} body")
            return body
        # An empty/whitespace body is a successful fetch with nothing to cache (the snapshot is
        # simply absent; review-context falls back to a live fetch).
        s.warn(f"plan snapshot: plan #{pr_id} body is empty")
        return None


def write_plan_body_snapshot(worktree: Path, body: str) -> None:
    """Cache a fetched plan body into the worktree as the per-worktree plan snapshot.

    The snapshot is what ``perk pr review-context`` reads first — fetched once at positioning
    time so it reviews the plan as implemented, offline, not whatever the issue says today.
    Silent: a local write is not a perceptible wait, so it earns no step line (the fetch that
    preceded it already narrated).
    """
    cache.write_plan_body(worktree, body)


def materialize_plan_body(repo_root: Path, worktree: Path, plan_ref: plan.PlanRef | None) -> None:
    """Fetch the plan body from its canonical source and cache it into the worktree — the
    composition of :func:`fetch_plan_body` + :func:`write_plan_body_snapshot`.

    Public: ``run_worker.position_worktree`` is the consumer of this composed shape (the cold-door
    launch calls the two halves separately so the fetch can precede the handoff write). A failed
    or empty fetch leaves no snapshot.
    """
    body = fetch_plan_body(repo_root, plan_ref)
    if body is not None:
        write_plan_body_snapshot(worktree, body)


def materialize_skills(repo_root: Path, worktree: Path) -> None:
    """Mirror repo_root's `.agents/skills/*` into the worktree as per-skill symlinks.

    Linked worktrees never carry the gitignored `.agents/skills/` tree, and pi discovers skills
    only up to the worktree's own git root (never the main repo), so without this a worktree
    session sees zero skills (ENOENT on `perk-implement/SKILL.md`). Replicates the exact per-skill
    structure pi already discovers in repo_root, delivering ALL skills (perk + borrowed).

    Best-effort + loud-but-non-fatal: a missing/empty source set (perk init never ran / skills sync
    failed) warns and continues — doctor's fail-level `skills-delivery` check owns the hard gate.
    Idempotent (D4 resume): an already-correct symlink is left untouched; a stale symlink is
    repointed; a real (non-symlink) entry already present is left alone (never clobbered).
    """
    src = repo_root / ".agents" / "skills"
    if not src.is_dir():
        log_warn(
            "skills: repo .agents/skills/ missing — run `perk init`; "
            "this session may have no skills"
        )
        return
    sources = [entry for entry in sorted(src.iterdir()) if entry.is_dir()]
    if not sources:
        log_warn("skills: repo .agents/skills/ is empty — run `perk init`")
        return
    dst = worktree / ".agents" / "skills"
    dst.mkdir(parents=True, exist_ok=True)
    linked = 0
    for entry in sources:
        target = entry.resolve()  # single-hop symlink to the real skill dir (cache or self)
        link = dst / entry.name
        if link.is_symlink():
            if link.readlink() == target:
                continue
            link.unlink()
        elif link.exists():
            continue  # a real dir/file already there — never clobber
        link.symlink_to(target, target_is_directory=True)
        linked += 1
    # Confirm the total delivered (not just freshly `linked`) so the count matches the banner and
    # reads correctly on an idempotent resume (where every skill is present and linked == 0).
    log_done(f"mirrored {len(sources)} skills")


def _count_skill_sources(repo_root: Path) -> int:
    """Count the skill dirs in ``repo_root/.agents/skills/`` — the exact set
    :func:`materialize_skills` mirrors. Best-effort: ``0`` when the dir is absent, never raises."""
    src = repo_root / ".agents" / "skills"
    try:
        return len([entry for entry in src.iterdir() if entry.is_dir()])
    except OSError:
        return 0


def _count_extension_packages(repo_root: Path) -> int:
    """Count the ``packages`` entries in ``repo_root/.pi/settings.json`` — the extensions pi loads.
    Best-effort: ``0`` on any read/JSON error."""
    settings = repo_root / ".pi" / "settings.json"
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
        packages = data.get("packages")
        return len(packages) if isinstance(packages, list) else 0
    except (OSError, ValueError, AttributeError):
        return 0


# The launch banner heads a process's launch output exactly once. A narrating cold-door command
# emits it before its own pre-launch narration; launch_stage emits it for every other launch.
# This guard makes the second emitter a no-op so the banner never doubles.
_LAUNCH_BANNER_EMITTED = False


def render_launch_banner(*, skills: int, extensions: int) -> str:
    """The 4-line perk launch banner: the compact box-drawing wordmark, the version, and a summary
    line that absorbs the old ``(skills: mirrored …)`` line plus the extension count."""
    return (
        " \u250c\u2500\u2510\u250c\u2500\u2510\u252c\u2500\u2510\u252c\u250c\u2500\n"
        " \u251c\u2500\u2518\u251c\u2524 \u251c\u252c\u2518\u251c\u2534\u2510\n"
        f" \u2534  \u2514\u2500\u2518\u2534\u2514\u2500\u2534 \u2534   perk v{__version__}\n"
        f" {skills} skills \u00b7 {extensions} extensions ready"
    )


def print_launch_banner(repo_root: Path) -> None:
    """Render the launch banner from ``repo_root``'s up-front counts and emit it via
    ``user_output``. Both counts are knowable before any worktree work, so the first render is
    already accurate — no re-render.

    Idempotent: emits at most once per process; later calls are no-ops. A narrating cold-door
    command can head its own pre-launch narration with the banner while ``launch_stage`` keeps its
    call as the no-op fallback for every other launch command.

    TTY-gated styling: the summary line is dimmed only on an interactive stderr with ``NO_COLOR``
    unset; ``--json``/piped/CI output stays plain and escape-code-free.
    """
    global _LAUNCH_BANNER_EMITTED
    if _LAUNCH_BANNER_EMITTED:
        return
    _LAUNCH_BANNER_EMITTED = True  # latch before emitting so re-entrancy cannot double-print
    skills = _count_skill_sources(repo_root)
    extensions = _count_extension_packages(repo_root)
    wordmark, _, summary = render_launch_banner(skills=skills, extensions=extensions).rpartition(
        "\n"
    )
    if sys.stderr.isatty() and not os.environ.get("NO_COLOR"):
        summary = click.style(summary, dim=True)
    user_output(f"{wordmark}\n{summary}")


def print_launch_banner_gated(repo_root: Path, *, dry_run: bool, remote: str | None) -> None:
    """Emit the launch banner only for a real local launch — the single gate the four narrating
    cold-door commands share to head their own pre-launch narration with the banner.

    Skipped on ``--dry-run`` (the preview path owns the output) and on ``--remote`` (the remote
    path prints no banner). ``remote is None`` is the exact "this is a local launch" test: absent
    ``--remote`` → ``None`` (local); ``--remote``/``--remote=x`` → ``""``/``"x"`` (both remote).
    Idempotent via :func:`print_launch_banner`, so ``launch_stage``'s later call is the no-op
    fallback.
    """
    if not dry_run and remote is None:
        print_launch_banner(repo_root)


def _is_exact_version(version: str) -> bool:
    """Whether a spec's version is an exact plain ``X.Y.Z`` (not a range, tag or prerelease)."""
    parsed = parse_semver(version)
    return parsed is not None and not parsed.prerelease and version == str(parsed)


def _installed_npm_version(manifest: Path) -> str | None:
    """An installed package's ``package.json`` ``version``; ``None`` when absent/unreadable."""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = data.get("version") if isinstance(data, dict) else None
    return version if isinstance(version, str) else None


def _stale_extension_specs(worktree: Path) -> list[str]:
    """The worktree's ``.pi/settings.json`` npm specs its staged ``.pi/npm`` does not satisfy.

    Mirrors Pi's ``needsInstall`` with one deliberate narrowing: an exact ``X.Y.Z`` spec must be
    installed at exactly that version; an unversioned or range spec needs only presence (Pi
    applies the range in-session). A package whose ``package.json`` is absent or unreadable is
    stale. Non-npm entries (local paths, ``git:``) are ignored; object-form entries are read
    through their ``source``. Missing/unreadable settings or a non-list ``packages`` → ``[]``
    (``skill_exposure`` owns that diagnosis). Returns bare specs (no ``npm:``), in settings order.
    """
    try:
        data = json.loads((worktree / ".pi" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    packages = data.get("packages") if isinstance(data, dict) else None
    if not isinstance(packages, list):
        return []
    modules = consumer_npm_install_root(worktree) / "node_modules"
    stale: list[str] = []
    for entry in packages:
        spec = _entry_spec(entry)
        name = _npm_name(spec) if spec is not None else None
        if spec is None or name is None:
            continue
        installed = _installed_npm_version(modules / name / "package.json")
        wanted = _npm_version(spec)
        exact_mismatch = wanted is not None and _is_exact_version(wanted) and installed != wanted
        if installed is None or exact_mismatch:
            stale.append(spec.removeprefix("npm:"))
    return stale


def _install_populated(modules: Path) -> bool:
    """Whether ``modules`` is a non-empty readable directory (an unreadable one counts as empty)."""
    try:
        return modules.is_dir() and any(modules.iterdir())
    except OSError:
        return False


def materialize_extensions(repo_root: Path, worktree: Path) -> None:
    """Stage the converged repo-root ``.pi/npm/`` into the worktree so pi installs nothing at
    startup (a silent + faster launch beneath the banner), then verify the worktree's install.

    A fresh worktree starts with an empty gitignored ``.pi/npm/``; at startup pi would ``npm
    install`` every configured extension with inherited stdio (the ``added N packages`` noise). A
    staged copy of the converged repo-root install satisfies pi's ``needsInstall`` short-circuit
    for every package. Two steps:

    1. **Stage.** An unpopulated worktree install (``node_modules`` missing, empty or unreadable —
       only regenerable metadata) is removed and staged from a populated repo-root install
       through :func:`perk.substrate.fsclone.clone_tree`: a ``clonefile(2)`` copy-on-write clone
       on macOS, else per-file hardlinks whose install-root metadata files (the ones package
       managers and Pi rewrite in place) get their own inodes. There is no byte-copy tier. A
       populated install is never clobbered (D4 resume) and needs no repo-root install at all;
       detaching one staged by the former all-hardlink layout is the exec pipeline's job
       (``pi_exec._detach_extension_install``), which every launch — resumes included — reaches.
    2. **Verify + warn.** The worktree's install is checked against its own
       ``.pi/settings.json`` (:func:`_stale_extension_specs`) and any mismatch warned once — perk
       installs nothing; Pi's ``needsInstall`` installs in-session.

    Loud-but-non-fatal, mirroring :func:`materialize_skills`: a staging failure warns and degrades
    to pi installing in-session (the noise reappears below the banner) but never blocks the
    launch.
    """
    dst = consumer_npm_install_root(worktree)
    if not _install_populated(dst / "node_modules"):
        src = consumer_npm_install_root(repo_root)
        if not _install_populated(src / "node_modules"):
            log_warn("extensions: repo .pi/npm not staged — pi will install them in-session")
            return
        # An unpopulated install root holds only regenerable metadata (Pi rewrites package.json /
        # .gitignore on demand), so removal — not merge — prepares clone_tree's absent `dst`.
        shutil.rmtree(dst, ignore_errors=True)
        # The staging is perceptible blocking I/O (python-cli-guidelines.md §7.5), so it earns a
        # step line, not just a bare confirmation.
        with io_step("staging extensions") as s:
            try:
                method = fsclone.clone_tree(src, dst)
            except OSError as exc:
                # A staging that fails mid-way leaves a partial tree behind. Remove it so the
                # presence-only resume guard above doesn't permanently cache a half-staged
                # (corrupt) install — a failed stage must degrade to pi installing fresh
                # in-session, never to a broken tree.
                shutil.rmtree(dst, ignore_errors=True)
                s.warn(
                    f"extensions: could not stage .pi/npm — {exc}; pi will install them in-session"
                )
                return
            s.done(f"staged extensions ({method})")
    stale = _stale_extension_specs(worktree)
    if stale:
        log_warn(
            f"extensions: {len(stale)} staged extension(s) do not match this worktree's "
            f".pi/settings.json ({', '.join(stale)}) — pi will install them in-session"
        )
