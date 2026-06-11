"""Minimal, idempotent ``perk init`` — the init spine begins here (T1).

`init` is **declarative and convergent**: it edits files toward a desired state and
is safe to re-run (re-running on a converged repo is a no-op). It owns *all* Pi
wiring from the first turn (the init-spine principle, docs/phase-0-plan.md).

T1 scope: wire ``.pi/settings.json`` (perk's own extension + the borrowed default
set), create the base ``.pi/workflow/`` dir, manage ``.gitignore``, and write a
managed ``AGENTS.md`` block. Env/GitHub verification, capability tracking, flags,
``--json``, and the post-init handoff are T5; the TOML config scaffold is T4.
"""

import json
import shutil
import subprocess
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from perk import __version__, cache, capabilities, env, git, github, workflow_artifacts
from perk.cli.ensure import UserFacingCliError
from perk.config import (
    CONFIG_FILENAME,
    LOCAL_CONFIG_FILENAME,
    load_committed_compaction,
    load_config,
)
from perk.env import EnvCheck
from perk.github import AuthStatus, GitHubError, RepoAccess
from perk.output import user_confirm
from perk.providers import ProviderSet, load_providers, resolve_providers

GIT_PACKAGE = "git:github.com/mattgiles/perk"

# Borrowed default set (the crossover scaffolding). Independent npm: entries; Pi
# auto-installs them on the next launch. `@tombell/pi-plan` was retired in P2.T2a
# (perk now owns plan mode end-to-end via the tool-gating primitive + `/plan`).
# `@juicesharp/rpiv-todo` was retired in P2.T12 (perk now owns implement-progress via
# perk-owned checkpoints, the `perk:checkpoint` entry seeded from the plan body, T2c).
# `pi-subagents` is the borrowed *spawned delegation engine* (P2.T6): perk takes the
# engine (the `subagent` tool + spawn/handoff machinery) and owns the workflow-specific
# agent definitions itself (in `.pi/agents/`, scaffolded by init); the engine is
# `ctx.hasUI`-clean (children run `--mode json -p`).
# `pi-web-access` is the borrowed *web-research engine* (zero-config Exa search + content
# fetch, no API keys required); perk borrows it wholesale (extension + its `librarian` skill).
BORROWED_PACKAGES = [
    "npm:@tombell/pi-diff",
    "npm:@tombell/pi-status",
    "npm:pi-subagents",
    "npm:pi-web-access",
]

# The canonical perk skill names (directory names under `skills/`). This list is the SSOT
# for the skills-CLI manifest fragment; update it here when perk skills are added/removed.
PERK_SKILLS: tuple[str, ...] = (
    "perk-address",
    "perk-implement",
    "perk-learn",
    "perk-learn-docs",
    "perk-objective-author",
    "perk-objective-plan",
    "perk-objective-reconcile",
    "perk-plan",
    "perk-pr-review",
    "perk-replan",
)

# perk manages a *slice* of the skills-CLI manifest (its own skills) via a committed fragment
# in the standard `.d/` convention, leaving the main `.agents/manifest.yaml` user-editable.
PERK_SKILLS_MANIFEST_DIR = ".agents/manifest.d"
PERK_SKILLS_MANIFEST_FILENAME = "perk.yaml"
PERK_GITHUB_URL = "https://github.com/mattgiles/perk"

GITIGNORE_BEGIN = "# BEGIN perk managed"
GITIGNORE_END = "# END perk managed"
# Pi install caches + perk's transient tier-2 cache subtrees + per-user config +
# worktrees. The `.pi/workflow/` dir itself stays tracked (via .gitkeep); only the
# transient subtrees/sentinels are ignored (contracts.md §8.1) — including the
# materialized `cache.plan` body (`plan.md`), a per-worktree mirror of the GitHub plan.
GITIGNORE_BODY = "\n".join(
    [
        "/.pi/npm/",
        "/.pi/git/",
        f"/.pi/{LOCAL_CONFIG_FILENAME}",
        "/.worktrees/",
        "/.pi/workflow/.perk-loaded",
        "/.pi/workflow/.perk-t3.json",
        "/.pi/workflow/post-init.md",
        "/.pi/workflow/plan.md",
        "/.pi/workflow/plan-ref.json",
        "/.pi/workflow/handoff/",
        "/.pi/workflow/scratch/",
        "/.pi/workflow/markers/",
    ]
)

PERK_TOML_TEMPLATE = """\
# perk project config (committed). Edit freely; per-user overrides go in
# .pi/perk.local.toml (gitignored). The schema grows as perk does.

[worktree]
# Where `perk worktree create` and cold-door stages place worktrees.
# Relative paths resolve against the repo root.
root = ".worktrees"

# Skill bindings (optional) — attach a skill to a stage or command, delivered
# into that session. Each [[bindings]] row binds one trigger to one skill:
#   trigger — "<kind>:<id>"; kind is `stage` or `command`.
#               stage:<id>   fires at that stage's launch / session entry.
#                            (ids: plan, implement, address, learn,
#                             objective-author, objective-plan, … — see
#                             `perk registry`.)
#               command:<id> fires when that perk command runs.
#                            (deliverable: objective-reconcile, learn-docs.)
#   skill   — a skill name installed under .agents/skills/<name>/.
#   mode    — `nudge` delivers a short pointer to follow the skill (its body
#             stays ambient / Pi-discovered); `transclude` inlines the skill's
#             SKILL.md into the prompt. Pick `nudge` for an already-installed
#             skill Pi can find on its own; `transclude` to force the full body
#             in (heavier context, but guaranteed present).
# A row at a trigger perk already binds OVERRIDES perk's default there; a new
# trigger is added. `perk doctor` validates every binding's skill + target.
#
# [[bindings]]
# trigger = "stage:implement"
# skill = "house-style"
# mode = "nudge"
#
# [[bindings]]
# trigger = "command:learn-docs"
# skill = "house-style"
# mode = "transclude"

# Per-agent subagent models — override the model each perk-owned subagent uses
# (the frontmatter default in .pi/agents/<name>.md is used when unset). Set a
# per-user override in .pi/perk.local.toml to avoid dirtying this file.
#
# [subagents]
# pr-reviewer = "anthropic/claude-sonnet-4-5"
# review-classifier = "anthropic/claude-haiku-4-5"
# objective-explorer = "anthropic/claude-haiku-4-5"

# Trust (optional) — declare parts of this repo trusted so perk skips a safety
# prompt. With `ci = "true"`, the [ci] checks above run WITHOUT a per-session
# confirm (and headless runs need no --allow-project-ci). Leave it unset for
# cloned/untrusted repos. Value is a quoted string. The table may grow later.
#
# [trust]
# ci = "true"

# Interactive auto-compaction — tunes pi's global compaction for `perk <stage>`
# sessions by converging the specified keys into .pi/settings.json's `compaction`
# object (pi reads that natively at session boot). Keys are committed-only (read
# from THIS file, never the perk.local.toml overlay) so the committed settings.json
# stays deterministic; per-user overrides belong in pi's global ~/.pi/agent/settings.json.
# Editing this requires re-running `perk init` (or `perk doctor --fix`) to converge.
# Removing this block leaves a stale settings.json `compaction` to clean up by hand.
#
# [compaction]
# enabled = true            # turn pi's auto-compaction on/off
# reserve_tokens = 16384    # tokens reserved for the response (pi default)
# keep_recent_tokens = 20000 # recent tokens kept verbatim (pi default)
"""

PERK_LOCAL_TOML_TEMPLATE = """\
# perk per-user local overrides (gitignored). Mirrors .pi/perk.toml's shape; values
# here win over the committed config. Example:
#   [worktree]
#   root = "/abs/path/to/worktrees"
#
# A local [[bindings]] array REPLACES the committed [[bindings]] array wholesale
# (whole-array override, not element-wise merge — unlike scalar leaf-merge).
"""

# The post-init handoff — an agent-readable markdown on-ramp (distinct from the T3/T4
# machine run-handoff JSON). Regenerated each init; kept true to what's built.
POST_INIT_TEMPLATE = """\
# perk is initialized ({mode})

This repo follows the **perk** plan-oriented workflow on Pi. Conventions live in `AGENTS.md`
(the perk-managed block). `perk init` owns all Pi wiring and is safe to re-run.

The spine `plan -> save -> implement -> submit -> land -> learn` is **closed and deepened**
(Phase 2 complete): perk-owned plan mode + tool-gating, a read-only CI executor, the
`/address` review loop, and objectives as plan factories. `objective-plan` is the new initial
node (select the next actionable objective node, emit a bounded plan); `/address` sits between
`submit` and `land` (classify review feedback, resolve threads).

**Start here:** `perk plan` (or `perk objective-plan` to drive from an objective roadmap)
mints a `run_id`, positions a worktree, and launches a primed `pi` session. `perk resume`
resolves any plan to its current actionable stage. `perk doctor` reports on this setup.
"""


@dataclass(frozen=True)
class GitHubReport:
    """The init-time GitHub readiness snapshot (verification-only)."""

    auth: AuthStatus
    repo: RepoAccess


@dataclass(frozen=True)
class InitReport:
    """Structured result of a ``run_init`` (rendered human or ``--json`` by the command)."""

    ok: bool
    mode: str
    env: list[EnvCheck]
    changes: list[str]
    github: GitHubReport | None
    handoff: str | None
    capabilities: tuple[str, ...] = ()
    error_type: str | None = None
    message: str | None = None

    @property
    def exit_code(self) -> int:
        if self.ok:
            return 0
        if self.error_type in ("not_a_repo", "missing_tool"):
            return 2
        return 1

    @classmethod
    def env_failure(cls, error_type: str, message: str, checks: list[EnvCheck]) -> "InitReport":
        return cls(
            ok=False,
            mode="unknown",
            env=checks,
            changes=[],
            github=None,
            handoff=None,
            error_type=error_type,
            message=message,
        )


def _env_to_dict(check: EnvCheck) -> dict[str, object]:
    return {
        "name": check.name,
        "ok": check.ok,
        "detail": check.detail,
        "remediation": check.remediation,
    }


def report_to_dict(report: InitReport) -> dict[str, object]:
    """Serialize an ``InitReport`` for the ``--json`` supervisor surface (cli-vs-pi §3.2)."""
    gh = report.github
    return {
        "success": report.ok,
        "mode": report.mode,
        "error_type": report.error_type,
        "message": report.message,
        "env": [_env_to_dict(c) for c in report.env],
        "github": None
        if gh is None
        else {
            "auth": {
                "ok": gh.auth.ok,
                "user": gh.auth.user,
                "scopes": list(gh.auth.scopes),
                "error": gh.auth.error,
            },
            "repo": {
                "ok": gh.repo.ok,
                "repo": gh.repo.repo,
                "can_push": gh.repo.can_push,
                "error": gh.repo.error,
            },
        },
        "capabilities": list(report.capabilities),
        "changes": report.changes,
        "handoff": report.handoff,
    }


AGENTS_BEGIN = "<!-- BEGIN perk managed -->"
AGENTS_END = "<!-- END perk managed -->"


def _agents_inner() -> str:
    return f"""## perk conventions (managed by `perk init` — do not edit between these markers)

This repo is wired for the **perk** plan-oriented workflow on Pi.

- **`perk init` owns all Pi wiring.** Every managed piece — `.pi/settings.json`
  package entries, `.pi/workflow/` dirs, `.gitignore` entries, this block — is
  written by `perk init`. Converge any repo by (re-)running `perk init`; it is
  idempotent (a no-op on an already-converged repo).
- **`init` converges *forward*; `doctor --fix` repairs oddities.** Do not bake
  backwards-compat migrations into `init`.
- **Headless-fail-safe.** In extensions, guard every rich-UI call with `ctx.hasUI`
  and block dangerous operations when `!ctx.hasUI`.
- **State tiers:** GitHub (canonical) / `.pi/workflow/` (cache) / session entries
  (transient). Cross-plane contracts live in `shared/`.

perk version: {__version__}"""


def is_self_repo(root: Path) -> bool:
    """True if ``root`` is perk's own source tree (``[tool.perk] self = true``)."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return False
    # No LBYL check exists for TOML validity, so parsing may raise; an unparseable
    # pyproject simply means "can't confirm self" -> consumer. A read error (OSError)
    # is genuinely exceptional and is allowed to bubble.
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return False
    return data.get("tool", {}).get("perk", {}).get("self") is True


def _npm_name(entry: str) -> str | None:
    """``npm:@scope/name@1.2.3`` -> ``@scope/name`` (identity for dedup)."""
    if not entry.startswith("npm:"):
        return None
    spec = entry[len("npm:") :]
    at = spec.rfind("@")
    return spec[:at] if at > 0 else spec  # at == 0 is a scope's leading @


def _git_identity(entry: str) -> str | None:
    """``git:host/user/repo@ref`` -> ``git:host/user/repo`` (identity for dedup, ignores ref)."""
    if not entry.startswith("git:"):
        return None
    at = entry.rfind("@")
    # Only strip the ref if @ appears after the "git:" prefix (len("git:") == 4)
    return entry[:at] if at > 4 else entry


def _package_identity(entry: object) -> str | None:
    """Identity of a `packages` entry (string OR object-form), for dedup/removal.

    Object-form entries (the provider-wired shape, `{ "source": <spec>, **filter }`) carry the
    package spec under ``source``; string entries are the spec directly. The spec is reduced to
    its npm/git identity (a non-npm/git spec is its own identity). ``None`` for an entry with no
    string spec.
    """
    spec = cast("dict[str, object]", entry).get("source") if isinstance(entry, dict) else entry
    if not isinstance(spec, str):
        return None
    return _npm_name(spec) or _git_identity(spec) or spec


def _desired_packages(self_repo: bool) -> list[str]:
    own = ".." if self_repo else f"{GIT_PACKAGE}@v{__version__}"
    return [own, *BORROWED_PACKAGES]


def _converge_settings(root: Path, self_repo: bool, *, apply: bool = True) -> list[str]:
    settings_path = root / ".pi" / "settings.json"

    old_text = settings_path.read_text(encoding="utf-8") if settings_path.is_file() else None
    try:
        settings = json.loads(old_text) if old_text else {}
    except json.JSONDecodeError as exc:
        raise UserFacingCliError(
            f".pi/settings.json is not valid JSON ({exc})\n"
            "Fix or remove it, then re-run 'perk init'.",
            error_type="invalid_settings",
        ) from exc
    if not isinstance(settings, dict):
        raise UserFacingCliError(
            ".pi/settings.json must contain a JSON object\n"
            "Fix or remove it, then re-run 'perk init'.",
            error_type="invalid_settings",
        )

    packages = settings.get("packages")
    if not isinstance(packages, list):
        packages = []

    # Migration: strip legacy npm perk entries written by earlier perk init runs.
    packages = [p for p in packages if not (isinstance(p, str) and p.startswith("npm:@perk/pi"))]

    have_local = {p for p in packages if isinstance(p, str) and not p.startswith(("npm:", "git:"))}
    have_npm = {n for n in (_npm_name(p) for p in packages if isinstance(p, str)) if n}
    have_git = {i for i in (_git_identity(p) for p in packages if isinstance(p, str)) if i}

    added: list[str] = []
    for want in _desired_packages(self_repo):
        if want.startswith("npm:"):
            name = _npm_name(want)
            if name is None or name in have_npm:
                continue
            packages.append(want)
            have_npm.add(name)
        elif want.startswith("git:"):
            identity = _git_identity(want)
            if identity is None or identity in have_git:
                continue
            packages.append(want)
            have_git.add(identity)
        else:
            if want in have_local:
                continue
            packages.append(want)
            have_local.add(want)
        added.append(want)

    # Provider-driven two-directional wiring (Node 2.1). Composes on top of the static layer
    # within this same body, so it stays inside the `settings-wiring` ManagedConvergence (D5 SSOT
    # — doctor dry-runs/fixes it for free). perk's own package is never filtered (Invariant 2).
    packages, provider_changes = _converge_provider_packages(root, packages)
    added.extend(provider_changes.added)

    settings["packages"] = packages
    # Converge pi's interactive auto-compaction from committed `[compaction]` (composes within
    # this same body, so it flows into the no-op short-circuit and stays inside `settings-wiring`
    # — doctor dry-runs/fixes it for free).
    compaction_changes = _converge_compaction(root, settings)
    new_text = json.dumps(settings, indent=2) + "\n"
    if new_text == old_text:
        return []
    if apply:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(new_text, encoding="utf-8")

    parts: list[str] = []
    if added:
        parts.append(f"added {', '.join(added)}")
    if provider_changes.removed:
        parts.append(f"removed {', '.join(provider_changes.removed)}")
    parts.extend(compaction_changes)
    return [f".pi/settings.json: {'; '.join(parts)}" if parts else ".pi/settings.json: normalized"]


def _converge_compaction(root: Path, settings: dict[str, object]) -> list[str]:
    """Merge committed `[compaction]` over `settings["compaction"]` (write-when-present).

    Reads **committed** `.pi/perk.toml` only (no local overlay; D2). When the parsed table is
    non-empty, its mapped keys are merged over any existing `compaction` dict (perk-specified
    keys win; unrelated hand-added keys survive; unspecified keys are left to pi's defaults). When
    empty/absent, `settings` is left untouched (perk cannot prove ownership of a bare `compaction`
    key, so removal is unsafe). A malformed-TOML error defers to the config check (treated as
    empty here, mirroring `_converge_provider_packages`). Returns a human-readable change fragment
    list, or `[]` when nothing was written.
    """
    try:
        desired = load_committed_compaction(root)
    except tomllib.TOMLDecodeError:
        desired = {}
    if not desired:
        return []
    existing = settings.get("compaction")
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged.update(desired)
    settings["compaction"] = merged
    fragment = ", ".join(f"{key}={value}" for key, value in desired.items())
    return [f"compaction: {fragment}"]


@dataclass(frozen=True)
class _ProviderChanges:
    added: list[str]
    removed: list[str]


def _converge_provider_packages(
    root: Path, packages: list[object]
) -> tuple[list[object], _ProviderChanges]:
    """Reconcile provider-managed `packages` entries against the repo `[providers]` selection.

    Two-directional (the new wrinkle over the append-only static layer): the **whole supported
    set** (`shared/providers.yaml`) gives the provider-managed identity set — the discriminator
    separating provider packages from `BORROWED_PACKAGES` and the user's hand-added packages. The
    resolved selection gives the *desired* foreign packages. We **remove** any managed entry that
    is no longer desired (a deselect) and **add** each desired foreign package in object form,
    merging its `package_filter`. Entries outside the managed set (perk's own, borrowed, user) are
    never touched. Any `packages` entry whose identity matches a provider's `package` is treated
    as provider-managed (removable when deselected); hand-adding a provider package *without*
    selecting it is unsupported — select it via `[providers]` instead (D5).
    """
    provider_set = load_providers()
    managed_identities = _managed_identities(provider_set)

    # Guard a malformed perk.toml: defer surfacing to the config check (mirrors _bindings_check).
    try:
        selection = load_config(root).providers
    except tomllib.TOMLDecodeError:
        selection = {}
    resolved = resolve_providers(selection, provider_set)

    desired: dict[str, dict[str, object] | None] = {}  # spec -> filter (for object-form addition)
    for provider in (resolved.plan, resolved.todo):
        if provider.package:
            desired[provider.package] = provider.package_filter
    desired_identities = {i for spec in desired if (i := _package_identity(spec))}

    removed: list[str] = []
    kept: list[object] = []
    for entry in packages:
        identity = _package_identity(entry)
        if identity in managed_identities and identity not in desired_identities:
            removed.append(identity)
            continue
        kept.append(entry)

    present = {i for entry in kept if (i := _package_identity(entry))}
    added: list[str] = []
    for spec, package_filter in desired.items():
        identity = _package_identity(spec)
        if identity is None or identity in present:
            continue
        entry: dict[str, object] = {"source": spec}
        if package_filter:
            entry.update(package_filter)
        kept.append(entry)
        present.add(identity)
        added.append(spec)

    return kept, _ProviderChanges(added=added, removed=removed)


def _managed_identities(provider_set: ProviderSet) -> set[str]:
    """Every non-null `package`'s identity across the supported set (the removal discriminator)."""
    return {
        identity
        for provider in provider_set.providers
        if provider.package and (identity := _package_identity(provider.package))
    }


def _desired_skills_manifest(self_repo: bool) -> str:
    """The YAML content of the perk-managed manifest fragment.

    The source ref pins to a tag (``v{__version__}``) for consumers and tracks ``main`` in
    perk's own tree — mirroring how ``_desired_packages`` pins the git package entry.
    """
    ref = "main" if self_repo else f"v{__version__}"
    skills_block = "\n".join(f"  - source: perk\n    name: {name}" for name in PERK_SKILLS)
    return (
        "# Managed by perk init — do not edit by hand.\n"
        "sources:\n"
        "  perk:\n"
        f"    url: {PERK_GITHUB_URL}\n"
        f"    ref: {ref}\n"
        "skills:\n"
        f"{skills_block}\n"
    )


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


def _sync_skills(root: Path, changes: list[str]) -> None:
    """Materialize the declared skills via the skills CLI (both self-repo and consumer trees).

    The ``skills`` CLI is the single delivery path for perk's own skills: the ``..``/``git:`` Pi
    package no longer declares ``pi.skills``, so Pi never discovers the package ``skills/`` dir —
    every ``perk-*`` skill reaches a session only through the CLI-managed ``.agents/skills/``
    symlinks. Runs for both self-repo and consumers under ``verify``.

    Best-effort + non-fatal, exactly like the GitHub readiness probe (D3): a missing or failing
    ``skills`` never blocks init — file convergence (incl. the perk fragment) has already
    succeeded. ``skills init`` is idempotent (no-op once initialized); ``skills update --sync``
    enforces the declared state by (re)linking ``.agents/skills/*``. A ``changes`` entry is
    appended only when the link set actually changes, so a converged repo reports no churn.
    """
    if shutil.which("skills") is None:
        return
    before = _skill_link_state(root)
    try:
        # Idempotent local-state scaffold (manifest + local config + gitignore block).
        subprocess.run(
            ["skills", "init", "--cache=local"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        subprocess.run(
            ["skills", "update", "--sync"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    if _skill_link_state(root) != before:
        changes.append(".agents/skills/: synchronized via skills update --sync")


def _converge_workflow_dir(root: Path, *, apply: bool = True) -> list[str]:
    """Converge the full `.pi/workflow/` cache layout: the committed `.gitkeep` + the four
    (gitignored, on-demand) cache subtrees. This *is* the ``workflow-dir`` capability, so
    init creates it and ``perk doctor`` verifies the very same shape (D2)."""
    workflow = root / ".pi" / "workflow"
    gitkeep = workflow / ".gitkeep"
    need_gitkeep = not gitkeep.is_file()
    missing_subdirs = [sub for sub in cache.SUBDIRS if not (workflow / sub).is_dir()]
    if not need_gitkeep and not missing_subdirs:
        return []
    if apply:
        workflow.mkdir(parents=True, exist_ok=True)
        if need_gitkeep:
            gitkeep.write_text("", encoding="utf-8")
        for sub in missing_subdirs:
            (workflow / sub).mkdir(parents=True, exist_ok=True)
    return [".pi/workflow/: created"]


def _converge_subagent_agents(root: Path, *, apply: bool = True) -> list[str]:
    """Converge the perk-owned agent-definitions home (`.pi/agents/`) for the borrowed
    `pi-subagents` engine (P2.T6). perk *owns and commits* its agent defs, so the dir ships
    with a committed `.gitkeep`; T7 drops the first real def in it. This is substrate only —
    no perk agent definition is authored here."""
    agents = root / ".pi" / "agents"
    gitkeep = agents / ".gitkeep"
    if gitkeep.is_file():
        return []
    if apply:
        agents.mkdir(parents=True, exist_ok=True)
        gitkeep.write_text("", encoding="utf-8")
    return [".pi/agents/: created"]


def _converge_config(
    root: Path, changes: list[str], *, force: bool = False, interactive: bool = True
) -> None:
    """Scaffold the committed + local TOML config.

    Seeded once; never overwritten — *unless* ``force`` re-seeds it back to the template
    (confirmed when ``interactive``). This is the one mildly-destructive init op.
    """
    pi_dir = root / ".pi"
    pi_dir.mkdir(parents=True, exist_ok=True)
    for name, template in (
        (CONFIG_FILENAME, PERK_TOML_TEMPLATE),
        (LOCAL_CONFIG_FILENAME, PERK_LOCAL_TOML_TEMPLATE),
    ):
        path = pi_dir / name
        if not path.is_file():
            path.write_text(template, encoding="utf-8")
            changes.append(f".pi/{name}: created")
        elif force and path.read_text(encoding="utf-8") != template:
            if interactive and not user_confirm(f"Re-seed .pi/{name} to defaults?", default=False):
                continue
            path.write_text(template, encoding="utf-8")
            changes.append(f".pi/{name}: re-seeded")


def _write_post_init(root: Path, self_repo: bool) -> str:
    """Write the agent-readable post-init handoff; return its repo-relative path."""
    path = root / ".pi" / "workflow" / "post-init.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "self" if self_repo else "consumer"
    path.write_text(POST_INIT_TEMPLATE.format(mode=mode), encoding="utf-8")
    return str(path.relative_to(root))


def _apply_managed_block(
    path: Path,
    *,
    begin: str,
    end: str,
    inner: str,
    label: str,
    header_if_new: str = "",
    apply: bool = True,
) -> list[str]:
    block = f"{begin}\n{inner.rstrip(chr(10))}\n{end}\n"
    old = path.read_text(encoding="utf-8") if path.is_file() else None

    if old is not None and begin in old and end in old:
        start = old.index(begin)
        stop = old.index(end) + len(end)
        new = old[:start] + block.rstrip("\n") + old[stop:]
        verb = "updated"
    else:
        base = old if old is not None else header_if_new
        if base and not base.endswith("\n"):
            base += "\n"
        if base and not base.endswith("\n\n"):
            base += "\n"
        new = base + block
        verb = "created"

    if new == old:
        return []
    if apply:
        path.write_text(new, encoding="utf-8")
    return [f"{label}: {verb}"]


@dataclass(frozen=True)
class ManagedConvergence:
    """One structural managed piece, as a dry-run/apply convergence (the D2 SSOT).

    ``run_init`` applies these (``apply=True``); ``perk doctor`` calls them with
    ``apply=False`` to verify drift and ``apply=True`` to fix it. ``covers`` lists the
    capability names this convergence verifies (the coherence guard asserts full coverage).
    """

    name: str
    covers: tuple[str, ...]
    converge: Callable[[bool], list[str]]


def managed_convergences(root: Path, self_repo: bool) -> list[ManagedConvergence]:
    """The shared structural convergences: ``init`` applies, ``doctor`` verifies/fixes."""
    return [
        ManagedConvergence(
            "settings-wiring",
            ("perk-extension", "borrowed-packages", "settings-wiring"),
            lambda apply: _converge_settings(root, self_repo, apply=apply),
        ),
        ManagedConvergence(
            "workflow-dir",
            ("workflow-dir",),
            lambda apply: _converge_workflow_dir(root, apply=apply),
        ),
        ManagedConvergence(
            "subagent-agents",
            ("subagent-engine",),
            lambda apply: _converge_subagent_agents(root, apply=apply),
        ),
        ManagedConvergence(
            "skills-manifest",
            ("skills-manifest",),
            lambda apply: _converge_skills_manifest(root, self_repo, apply=apply),
        ),
        ManagedConvergence(
            "runner-workflow",
            ("runner-workflow",),
            lambda apply: workflow_artifacts.converge_runner_workflow(root, self_repo, apply=apply),
        ),
        ManagedConvergence(
            "gitignore-block",
            ("gitignore-block",),
            lambda apply: _apply_managed_block(
                root / ".gitignore",
                begin=GITIGNORE_BEGIN,
                end=GITIGNORE_END,
                inner=GITIGNORE_BODY,
                label=".gitignore",
                apply=apply,
            ),
        ),
        ManagedConvergence(
            "agents-block",
            ("agents-block",),
            lambda apply: _apply_managed_block(
                root / "AGENTS.md",
                begin=AGENTS_BEGIN,
                end=AGENTS_END,
                inner=_agents_inner(),
                label="AGENTS.md",
                header_if_new="# AGENTS\n",
                apply=apply,
            ),
        ),
    ]


def run_init(
    root: Path | None = None,
    *,
    force: bool = False,
    interactive: bool = True,
    verify: bool = True,
) -> InitReport:
    """Converge the repo and return a structured report (rendered by the command layer).

    Pipeline: verify env -> converge managed pieces -> verify GitHub (never mutate) ->
    write the post-init handoff. Environment-not-ready short-circuits before convergence.

    ``verify=False`` skips the **external** verification (repo/tooling/GitHub shells) and
    runs pure convergence — the seam unit tests use so they don't depend on an installed,
    authenticated toolchain. The CLI always verifies (default).
    """
    root = (root or Path.cwd()).resolve()
    checks: list[EnvCheck] = []
    if verify:
        checks = env.check_environment()
        if git.repo_root(root) is None:
            return InitReport.env_failure(
                "not_a_repo",
                "Not a git repository — run 'perk init' inside a git repository.",
                checks,
            )
        if not env.required_tools_ok(checks):
            missing = ", ".join(c.name for c in checks if not c.ok)
            return InitReport.env_failure(
                "missing_tool", f"Missing or outdated required tool(s): {missing}.", checks
            )

    self_repo = is_self_repo(root)
    changes: list[str] = []
    for mc in managed_convergences(root, self_repo):
        changes.extend(mc.converge(True))
    _converge_config(root, changes, force=force, interactive=interactive)
    # Materialize the declared skills under the covers via the `skills` CLI — the single delivery
    # path in both self-repo and consumer trees (the Pi package no longer declares `pi.skills`,
    # so Pi discovers `perk-*` only through `.agents/skills/`).
    # Gated on `verify`: the external `skills` shells run on real inits but not in unit tests.
    if verify:
        _sync_skills(root, changes)

    github_report: GitHubReport | None = None
    if verify:
        # GitHub readiness is non-fatal (D3): a flaky/slow/broken `gh` (timeout or
        # unparseable output -> GitHubError) must not crash init — file convergence has
        # already succeeded. Degrade to an unauthed report and continue.
        try:
            auth = github.check_auth()
            repo = github.check_repo_access(root) if auth.ok else RepoAccess.skipped()
        except GitHubError as exc:
            auth = AuthStatus(ok=False, user=None, scopes=(), error=str(exc))
            repo = RepoAccess.skipped()
        github_report = GitHubReport(auth=auth, repo=repo)
    handoff = _write_post_init(root, self_repo)
    managed = tuple(cap.name for cap in capabilities.applicable(self_repo))

    return InitReport(
        ok=True,
        mode="self" if self_repo else "consumer",
        env=checks,
        changes=changes,
        github=github_report,
        handoff=handoff,
        capabilities=managed,
    )
