"""Skills-delivery cluster: the manifest fragment, conflict probe, and ``skills`` CLI sync."""

import shutil
from dataclasses import dataclass
from pathlib import Path

from perk.substrate import bindings, git
from perk.substrate.proc import ProcFailure, run_captured

# The canonical perk skill names (directory names under `skills/`). This list is the SSOT
# for the skills-CLI manifest fragment; update it here when perk skills are added/removed.
PERK_SKILLS: tuple[str, ...] = (
    "ast-grep",
    "perk-address",
    "perk-domain-modeling",
    "perk-expert",
    "perk-gist-author",
    "perk-grill",
    "perk-implement",
    "perk-learn",
    "perk-learn-code",
    "perk-learn-docs",
    "perk-learn-dream",
    "perk-learn-harvest",
    "perk-objective-author",
    "perk-objective-plan",
    "perk-objective-reconcile",
    "perk-objective-replan",
    "perk-objective-review-browser",
    "perk-plan",
    "perk-plan-review-browser",
    "perk-pr-review",
    "perk-pr-review-browser",
    "perk-pr-review-dynamic",
    "perk-pr-review-terminal",
    "perk-replan",
    "perk-skill-author",
)

# The skills CLI's managed runtime pathspecs, duplicated by value (no machine-readable export
# exists) from `internal/project/project.go` + `managedRuntimeIgnoreRules` in
# `internal/project/ownership.go` of github.com/mattgiles/skills. `skills init` hard-refuses when
# any of these is tracked, so `perk init` pre-flights the same probe and fails fast (exit 2)
# instead of letting the sync fail later. If the skills CLI's set drifts, the probe under-/over-
# matches — accepted; the post-sync fatal path still catches the failure generically.
SKILLS_MANAGED_PATHSPECS: tuple[str, ...] = (
    ".agents/state.yaml",
    ".agents/local.yaml",
    ".agents/skills",
    ".claude/skills",
    ".agents/cache",
)

# perk manages a *slice* of the skills-CLI manifest (its own skills) via a committed fragment
# in the standard `.d/` convention, leaving the main `.agents/manifest.yaml` user-editable.
PERK_SKILLS_MANIFEST_DIR = ".agents/manifest.d"
PERK_SKILLS_MANIFEST_FILENAME = "perk.yaml"
PERK_GITHUB_URL = "https://github.com/mattgiles/perk"

# The header line every perk-managed skills-CLI manifest fragment opens with. Shared so the
# perk fragment (`perk.yaml`) and the repo-authored fragment (`perk-repo-skills.yaml`, rendered
# by `repo_skills.py`) stay byte-identical in their header.
MANAGED_HEADER = "# Managed by perk init — do not edit by hand.\n"


# A skills-CLI manifest source: a named upstream repo + ref the skills CLI clones to resolve
# skills. Same `@dataclass(frozen=True)` style as `_ProviderChanges`.
@dataclass(frozen=True)
class SkillSource:
    key: str
    url: str
    ref: str


# The skills perk delivers split into two SSOTs:
#   - `PERK_SKILLS` (above): perk-authored skill names, all from source `perk`.
#   - The external set below: non-perk skills perk *requires*, promoted from repo-specific to
#     managed/required and declared from their upstream sources.
# `MANAGED_SKILL_NAMES` is the union — the SSOT for "every skill perk requires delivered" used
# by the fragment generator's verification consumers (`sync_skills`, `_skills_delivery_check`).
PERK_SKILL_SOURCE = SkillSource("perk", PERK_GITHUB_URL, "main")
REQUIRED_SKILL_SOURCES: tuple[SkillSource, ...] = (
    SkillSource("astral", "https://github.com/astral-sh/claude-code-plugins", "main"),
    SkillSource("dagster", "https://github.com/dagster-io/skills", "master"),
    SkillSource("mattpocock", "https://github.com/mattpocock/skills", "main"),
)
# `(source_key, skill_name)` pairs, kept sorted by `(source, name)`.
REQUIRED_EXTERNAL_SKILLS: tuple[tuple[str, str], ...] = (
    ("astral", "ruff"),
    ("astral", "ty"),
    ("astral", "uv"),
    ("dagster", "dignified-python"),
    ("mattpocock", "codebase-design"),
)
MANAGED_SKILL_NAMES: tuple[str, ...] = tuple(
    sorted({*PERK_SKILLS, *(name for _, name in REQUIRED_EXTERNAL_SKILLS)})
)


def _desired_skills_manifest(self_repo: bool) -> str:
    """The YAML content of the perk-managed manifest fragment.

    Both perk's own tree and consumers track ``main``. perk has no release cadence (a
    single, long-stale ``v0.0.1`` tag), so ``main`` is the only ref that reflects current
    state; a stale clone is refreshed by re-sync / ``git pull``. Mirrors how
    ``_desired_packages`` resolves the git package entry from ``main`` for consumers.
    """
    sources = sorted([PERK_SKILL_SOURCE, *REQUIRED_SKILL_SOURCES], key=lambda s: s.key)
    skills = sorted([("perk", name) for name in PERK_SKILLS] + list(REQUIRED_EXTERNAL_SKILLS))
    sources_block = "\n".join(f"  {s.key}:\n    url: {s.url}\n    ref: {s.ref}" for s in sources)
    skills_block = "\n".join(f"  - source: {src}\n    name: {name}" for src, name in skills)
    return f"{MANAGED_HEADER}sources:\n{sources_block}\nskills:\n{skills_block}\n"


def _converge_skills_manifest(root: Path, self_repo: bool, *, apply: bool = True) -> list[str]:
    """Converge the committed skills-CLI manifest fragment (`.agents/manifest.d/perk.yaml`).

    Like every managed convergence: ``init`` applies it, ``perk doctor`` dry-runs it for drift
    and ``--fix`` re-applies it. The fragment is a *committed declaration* (not transient state),
    so it is never gitignored. The user's own `.agents/manifest.yaml` is left untouched.
    """
    fragment_path = root / PERK_SKILLS_MANIFEST_DIR / PERK_SKILLS_MANIFEST_FILENAME
    desired = _desired_skills_manifest(self_repo)
    current = fragment_path.read_text(encoding="utf-8") if fragment_path.is_file() else None
    if current == desired:
        return []
    if apply:
        fragment_path.parent.mkdir(parents=True, exist_ok=True)
        fragment_path.write_text(desired, encoding="utf-8")
    verb = "created" if current is None else "updated"
    return [f"{PERK_SKILLS_MANIFEST_DIR}/{PERK_SKILLS_MANIFEST_FILENAME}: {verb}"]


def skills_conflict_paths(root: Path) -> list[str]:
    """Tracked paths under the skills-CLI managed pathspecs — the `skills init` hard-refusal.

    Returns a deduplicated, truncated listing (first 5 + "…and N more"); ``[]`` when clean.
    Propagates ``GitError`` — the caller decides how a failed probe degrades.
    """
    paths = list(dict.fromkeys(git.tracked_paths(root, list(SKILLS_MANAGED_PATHSPECS))))
    if len(paths) > 5:
        return [*paths[:5], f"…and {len(paths) - 5} more"]
    return paths


def _skills_conflict_message(conflicts: list[str]) -> str:
    listing = "\n".join(f"  - {p}" for p in conflicts)
    return (
        "Tracked content found under skills-CLI managed paths:\n"
        f"{listing}\n"
        "These paths are managed by the `skills` CLI (perk's skill-delivery substrate); it\n"
        "refuses to initialize over tracked Git content. Migrate the committed skill bodies\n"
        "out of them (e.g. into a committed top-level `skills/` dir declared in\n"
        "`.agents/manifest.yaml`), untrack the paths (`git rm --cached -r <path>`), then\n"
        "re-run `perk init`."
    )


def _skill_link_state(root: Path) -> dict[str, str]:
    """Snapshot the `.agents/skills/` link set as ``{name: symlink-target}`` (target ``""`` for
    non-symlinks / unreadable). Used to detect whether a `skills sync` actually changed state,
    so init's change-reporting stays idempotent (a converged repo re-runs clean)."""
    skills_dir = root / ".agents" / "skills"
    if not skills_dir.is_dir():
        return {}
    state: dict[str, str] = {}
    for entry in sorted(skills_dir.iterdir()):
        try:
            state[entry.name] = str(entry.readlink()) if entry.is_symlink() else ""
        except OSError:
            state[entry.name] = ""
    return state


def _repo_authored_hint(repo_skill_names: tuple[str, ...]) -> str:
    """The repo-authored remediation clause appended to every skills-sync failure message.

    Returns ``""`` unless repo-authored skills are declared (gated solely on "are there any?",
    no per-skill stderr matching). A freshly-declared `.perk/skills/` skill is unresolvable until
    it is committed + pushed to the repo's default branch — the most common first-appearance
    cause of a skills-sync failure once repo-authored skills exist.
    """
    if not repo_skill_names:
        return ""
    return (
        "\nIf a skill under `.perk/skills/` was just added, commit + push it to your repo's "
        "default branch, then re-run `perk init` (or `perk doctor --fix`)."
    )


def _sync_failure(command: str, reason: str, repo_skill_names: tuple[str, ...] = ()) -> str:
    return (
        f"skills delivery failed: `{command}` {reason}\n"
        "perk's skills reach sessions only through the `skills` CLI-managed `.agents/skills/`;\n"
        "fix the failure above, then re-run `perk init` (or `perk doctor --fix`)."
        f"{_repo_authored_hint(repo_skill_names)}"
    )


def sync_skills(
    root: Path,
    changes: list[str],
    *,
    repo_skill_names: tuple[str, ...] = (),
) -> str | None:
    """Materialize the declared skills via the skills CLI (both self-repo and consumer trees).

    The ``skills`` CLI is the single delivery path for perk's own skills: the ``..``/``git:`` Pi
    package no longer declares ``pi.skills``, so Pi never discovers the package ``skills/`` dir —
    every ``perk-*`` skill reaches a session only through the CLI-managed ``.agents/skills/``
    symlinks. Runs for both self-repo and consumers under ``verify``.

    **Load-bearing** (supersedes the old best-effort/D3 posture for skills specifically):
    returns ``None`` on success, else a failure message naming the failing command plus its
    stderr (or the ``OSError``/timeout text). After a successful sync, every ``MANAGED_SKILL_NAMES``
    name (perk-authored + the required external skills) must be installed
    (``bindings.is_skill_installed`` — strict on the ``.agents/skills/`` delivery read path, in
    the self-repo too: a sync that exits 0 without linking a managed skill fails loudly, never a
    silent pass over the committed ``skills/`` layout). ``skills init`` is idempotent
    (no-op once initialized); ``skills update --sync`` enforces the declared state by (re)linking
    ``.agents/skills/*``. A ``changes`` entry is appended only when the link set actually changes,
    so a converged repo reports no churn.

    ``repo_skill_names`` are the declared repo-authored skill names (from
    ``converge_repo_skills_manifest``). They are folded into the post-sync presence loop (a free
    backstop for a CLI that exits 0 but skips an unresolvable skill) and gate a single repo-aware
    remediation clause appended to every failure message (commit + push the new skill).
    """
    # Defense in depth — env gating already fails exit 2 before this on verified runs.
    if shutil.which("skills") is None:
        return (
            "skills delivery failed: the `skills` CLI is not on PATH — "
            "install it, then re-run `perk init`."
            f"{_repo_authored_hint(repo_skill_names)}"
        )
    before = _skill_link_state(root)
    for command, timeout in (("skills init --cache=local", 30), ("skills update --sync", 180)):
        try:
            proc = run_captured(command.split(), cwd=root, timeout=timeout)
        except ProcFailure as exc:
            if exc.kind == "timeout":
                return _sync_failure(command, f"timed out after {timeout}s", repo_skill_names)
            return _sync_failure(command, f"could not run: {exc.cause_text}", repo_skill_names)
        if proc.returncode != 0:
            stderr = "\n".join((proc.stderr or "").strip().splitlines()[:5]) or "(no stderr)"
            return _sync_failure(command, f"exited {proc.returncode}:\n{stderr}", repo_skill_names)
    missing = [
        name
        for name in (*MANAGED_SKILL_NAMES, *repo_skill_names)
        if not bindings.is_skill_installed(root, name)
    ]
    if missing:
        return (
            f"skills sync completed but did not deliver: {', '.join(missing)}\n"
            "the installed `skills` CLI may be outdated — upgrade it, then re-run `perk init`."
            f"{_repo_authored_hint(repo_skill_names)}"
        )
    if _skill_link_state(root) != before:
        changes.append(".agents/skills/: synchronized via skills update --sync")
    return None
