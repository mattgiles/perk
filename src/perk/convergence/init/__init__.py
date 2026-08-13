"""Minimal, idempotent ``perk init`` — the init spine.

`init` is **declarative and convergent**: it edits files toward a desired state and
is safe to re-run (re-running on a converged repo is a no-op). It owns *all* Pi
wiring from the first turn (the init-spine principle).

**Package layout.** This ``__init__`` keeps the orchestration
(``run_init``, ``managed_convergences``, ``_linear_readiness``,
``_converge_workflow_dir``, ``_write_post_init``, ``is_self_repo``) and re-exports every submodule
symbol behind a sorted ``__all__``, preserving the ``init.X`` attribute-access import path.
The orchestrators reference the moved helpers as
facade globals, so the existing ``init_mod.sync_skills`` monkeypatch keeps working. Submodules:
``templates``, ``report``, ``blocks``, ``settings``, ``agents``, ``skills``, ``onboarding``
(the interactive gestures — guided tool installs, gh login, git identity, the Linear key
prompt).
"""

import shutil
import subprocess
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from perk import github
from perk.backends import linear
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import client as linear_client
from perk.convergence import capabilities, env, managed_state
from perk.convergence.env import EnvCheck
from perk.convergence.init.agents import PERK_AGENTS, _converge_subagent_agents
from perk.convergence.init.blocks import (
    AGENTS_BEGIN,
    AGENTS_END,
    GITIGNORE_BEGIN,
    GITIGNORE_BODY,
    GITIGNORE_END,
    _agents_inner,
    _apply_managed_block,
)
from perk.convergence.init.extension_install import (
    ExtensionInstallStatus,
    _extension_install_lock,
    _install_perk_extension,
    consumer_npm_install_root,
    consumer_perk_package_dir,
    ensure_extension_install_present,
    extension_install_status,
    installed_perk_version,
    materialize_extension_install,
)
from perk.convergence.init.onboarding import (
    PI_NPM_SPEC,
    SKILLS_GO_SPEC,
    SKILLS_INSTALL_SCRIPT,
    ensure_git_identity,
    guide_missing_tools,
    offer_gh_login,
    prompt_linear_api_key,
)
from perk.convergence.init.repo_skills import (
    RepoSkillsConvergence,
    RepoSkillsManifest,
    build_repo_skills_manifest,
    converge_repo_skills_manifest,
)
from perk.convergence.init.report import (
    GitHubReport,
    InitReport,
    InitReportOut,
    LinearReport,
    report_to_dict,
)
from perk.convergence.init.review_cli import (
    HUNK_INSTALL_HINT,
    ensure_review_cli,
    hunk_cli_path,
    hunk_cli_present,
)
from perk.convergence.init.settings import (
    BORROWED_PACKAGES,
    GIT_PACKAGE,
    LINEAR_PACKAGE,
    NPM_PACKAGE,
    _converge_compaction,
    _converge_linear_package,
    _converge_provider_packages,
    _converge_settings,
    _desired_packages,
    _entry_spec,
    _git_identity,
    _managed_identities,
    _merge_static_packages,
    _npm_name,
    _package_identity,
    _ProviderChanges,
    consumer_git_clone_root,
)
from perk.convergence.init.skills import (
    MANAGED_SKILL_NAMES,
    PERK_GITHUB_URL,
    PERK_SKILL_SOURCE,
    PERK_SKILLS,
    PERK_SKILLS_MANIFEST_DIR,
    PERK_SKILLS_MANIFEST_FILENAME,
    REQUIRED_EXTERNAL_SKILLS,
    REQUIRED_SKILL_SOURCES,
    SKILLS_MANAGED_PATHSPECS,
    SkillSource,
    _converge_skills_manifest,
    _desired_skills_manifest,
    _skill_link_state,
    _skills_conflict_message,
    _sync_failure,
    skills_conflict_paths,
    sync_skills,
)
from perk.convergence.init.templates import (
    PERK_LOCAL_TOML_TEMPLATE,
    PERK_TOML_TEMPLATE,
    POST_INIT_TEMPLATE,
    converge_config,
)
from perk.convergence.init.version_pin import (
    converge_version_pin,
    read_version_pin,
    render_version_pin,
)
from perk.github import AuthStatus, GitHubError, RepoAccess
from perk.run import workflow_artifacts
from perk.state import cache
from perk.substrate import git, paths
from perk.substrate.config import (
    ConfigError,
    load_committed_issues_backend,
    load_committed_issues_team,
)

__all__ = [
    "AGENTS_BEGIN",
    "AGENTS_END",
    "BORROWED_PACKAGES",
    "GITIGNORE_BEGIN",
    "GITIGNORE_BODY",
    "GITIGNORE_END",
    "GIT_PACKAGE",
    "HUNK_INSTALL_HINT",
    "LINEAR_PACKAGE",
    "MANAGED_SKILL_NAMES",
    "NPM_PACKAGE",
    "PERK_AGENTS",
    "PERK_GITHUB_URL",
    "PERK_LOCAL_TOML_TEMPLATE",
    "PERK_SKILLS",
    "PERK_SKILLS_MANIFEST_DIR",
    "PERK_SKILLS_MANIFEST_FILENAME",
    "PERK_SKILL_SOURCE",
    "PERK_TOML_TEMPLATE",
    "PI_NPM_SPEC",
    "POST_INIT_TEMPLATE",
    "REQUIRED_EXTERNAL_SKILLS",
    "REQUIRED_SKILL_SOURCES",
    "SKILLS_GO_SPEC",
    "SKILLS_INSTALL_SCRIPT",
    "SKILLS_MANAGED_PATHSPECS",
    "ExtensionInstallStatus",
    "GitHubReport",
    "InitReport",
    "InitReportOut",
    "LinearReport",
    "ManagedConvergence",
    "RepoSkillsConvergence",
    "RepoSkillsManifest",
    "SkillSource",
    "_ProviderChanges",
    "_agents_inner",
    "_apply_managed_block",
    "_converge_compaction",
    "_converge_linear_package",
    "_converge_provider_packages",
    "_converge_settings",
    "_converge_skills_manifest",
    "_converge_subagent_agents",
    "_converge_workflow_dir",
    "_desired_packages",
    "_desired_skills_manifest",
    "_entry_spec",
    "_extension_install_lock",
    "_git_identity",
    "_install_perk_extension",
    "_linear_readiness",
    "_managed_identities",
    "_merge_static_packages",
    "_missing_tool_failure",
    "_npm_name",
    "_package_identity",
    "_reconcile_extension_install",
    "_skill_link_state",
    "_skills_conflict_message",
    "_sync_failure",
    "_write_post_init",
    "build_repo_skills_manifest",
    "consumer_git_clone_root",
    "consumer_npm_install_root",
    "consumer_perk_package_dir",
    "converge_config",
    "converge_repo_skills_manifest",
    "converge_version_pin",
    "ensure_extension_install_present",
    "ensure_git_identity",
    "ensure_review_cli",
    "extension_install_status",
    "git",
    "guide_missing_tools",
    "hunk_cli_path",
    "hunk_cli_present",
    "installed_perk_version",
    "is_self_repo",
    "linear",
    "managed_convergences",
    "managed_state",
    "materialize_extension_install",
    "offer_gh_login",
    "prompt_linear_api_key",
    "read_version_pin",
    "render_version_pin",
    "report_to_dict",
    "run_init",
    "shutil",
    "skills_conflict_paths",
    "subprocess",
    "sync_skills",
]


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


def _converge_workflow_dir(root: Path, *, apply: bool = True) -> list[str]:
    """Converge the `.perk/workflow/` cache layout: the four (gitignored, on-demand) cache
    subtrees. This *is* the ``workflow-dir`` capability, so init creates it and ``perk doctor``
    verifies the very same shape (D2). The whole tree is gitignored cache — no committed
    ``.gitkeep`` (a fresh clone has no tracked workflow artifact)."""
    workflow = cache.workflow_dir(root)
    missing_subdirs = [sub for sub in cache.SUBDIRS if not (workflow / sub).is_dir()]
    if not missing_subdirs:
        return []
    if apply:
        workflow.mkdir(parents=True, exist_ok=True)
        for sub in missing_subdirs:
            (workflow / sub).mkdir(parents=True, exist_ok=True)
    return [".perk/workflow/: created"]


def _write_post_init(root: Path, self_repo: bool) -> str:
    """Write the agent-readable post-init handoff; return its repo-relative path."""
    path = cache.workflow_dir(root) / "post-init.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "self" if self_repo else "consumer"
    path.write_text(POST_INIT_TEMPLATE.format(mode=mode), encoding="utf-8")
    return str(path.relative_to(root))


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
            "required-perk-version",
            ("required-perk-version",),
            lambda apply: converge_version_pin(root, apply=apply),
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
    changes: list[str] = []
    warnings: list[str] = []
    if verify:
        checks = env.check_environment()
        # The interactive guided-install pass runs ONCE, before any git shell-out (git itself
        # may be the missing tool), then the environment is re-probed. Gap-driven: with every
        # required tool present it prompts for nothing and returns `([], [])`.
        if interactive and not env.required_tools_ok(checks):
            guided_changes, guided_warnings = guide_missing_tools(checks)
            changes.extend(guided_changes)
            warnings.extend(guided_warnings)
            checks = env.check_environment()
        # Preflight order (both modes): a still-missing `git` classifies `missing_tool` BEFORE
        # `git.repo_root` is ever called (a missing git in a real repo must never degrade the
        # probe into `not_a_repo`); then the repo gate; then the remaining required tools.
        git_check = next((c for c in checks if c.name == "git"), None)
        if git_check is not None and not git_check.ok:
            return _missing_tool_failure(checks, changes, warnings, interactive=interactive)
        if git.repo_root(root) is None:
            return InitReport.env_failure(
                "not_a_repo",
                "Not a git repository — run 'perk init' inside a git repository.",
                checks,
            )
        if not env.required_tools_ok(checks):
            return _missing_tool_failure(checks, changes, warnings, interactive=interactive)
        # Pre-flight the skills-CLI tracked-content conflict BEFORE any convergence: `skills
        # init` would hard-refuse later, so fail fast with the migration remediation. A failed
        # probe (GitError) degrades to *no* short-circuit — the fatal sync below fails loudly
        # instead (no silent pass, no spurious block).
        try:
            conflicts = skills_conflict_paths(root)
        except git.GitError:
            conflicts = []
        if conflicts:
            return InitReport.env_failure(
                "skills_conflict", _skills_conflict_message(conflicts), checks
            )

    self_repo = is_self_repo(root)
    # Legacy-only refusal: a repo carrying the legacy committed config (`.pi/perk.toml`) but not
    # the new marker (`.perk/config.toml`) must be migrated by `doctor --fix` before init will
    # converge it — never warn-and-seed a fresh template over an unmigrated legacy config. Keyed
    # on the COMMITTED marker only (a lone legacy local file does not block). Unconditional: a
    # fresh repo has neither file so it never fires there.
    if not paths.config_file(root).is_file() and paths.legacy_config_file(root).is_file():
        return InitReport.env_failure(
            "legacy_config",
            "Legacy perk config at .pi/perk.toml (no .perk/config.toml). Run 'perk doctor --fix' "
            "to migrate it to .perk/, then re-run 'perk init'.",
            checks,
        )
    for mc in managed_convergences(root, self_repo):
        changes.extend(mc.converge(True))
    converge_config(root, changes, force=force, interactive=interactive)
    # Record `.perk/managed-state.toml` as a convergence side effect — after converge_config (so
    # the recorded hashes reflect the repo's committed config, including a freshly seeded one).
    # Content-gated: a converged repo appends nothing (the pure-delta `changes` invariant); a
    # one-time backfill reports once. Pure filesystem, so it runs under verify=False too.
    state_change = managed_state.record_managed_state(root, self_repo=self_repo)
    if state_change is not None:
        changes.append(state_change)
    # Materialize the declared skills under the covers via the `skills` CLI — the single delivery
    # path in both self-repo and consumer trees (the Pi package no longer declares `pi.skills`,
    # so Pi discovers `perk-*` only through `.agents/skills/`).
    # Gated on `verify`: the external `skills` shells run on real inits but not in unit tests.
    # Load-bearing: a sync failure is fatal (exit 2) — but convergence already happened,
    # so the failed report preserves `changes` (not `env_failure`, which zeroes them).
    if verify:
        # Converge the repo-authored-skills manifest fragment BEFORE the sync so the skills CLI
        # sees the declared `.perk/skills/` source. A verify-gated network gesture (not a
        # ManagedConvergence): structural errors are NON-FATAL here (init exits 0 and keeps
        # converging) and flow onto `InitReport.warnings`; only the sync-time remote
        # `missing-skill` stays fatal. Never touches `.agents/manifest.yaml`.
        conv = converge_repo_skills_manifest(root, apply=True)
        changes.extend(conv.changes)
        warnings.extend((*conv.manifest.warnings, *conv.manifest.errors))
        repo_skill_names = tuple(s.name for s in conv.manifest.skills)
        sync_error = sync_skills(root, changes, repo_skill_names=repo_skill_names)
        if sync_error is not None:
            return InitReport(
                ok=False,
                mode="self" if self_repo else "consumer",
                env=checks,
                changes=changes,
                github=None,
                handoff=None,
                error_type="skills_sync_failed",
                message=sync_error,
                warnings=warnings,
            )
        # Forward-reconcile perk's own @mgiles/perk npm install (install-if-absent /
        # reinstall-if-version-mismatch). Best-effort + non-fatal: a network op (verify-gated),
        # it degrades to a swallowed NpmError when the pin is unpublished / offline.
        _reconcile_extension_install(root, changes, self_repo)
        # Best-effort hunk-CLI install — unconditional, not gated on the review selection
        # (verify-gated network gesture; an install failure degrades to a warning, never fatal).
        review_changes, review_warnings = ensure_review_cli(root)
        changes.extend(review_changes)
        warnings.extend(review_warnings)
        # Git commit identity (contracts.md §8.5): interactive offers to set it; the
        # non-interactive probe degrades to a warning carrying the manual commands.
        identity_changes, identity_warnings = ensure_git_identity(root, interactive=interactive)
        changes.extend(identity_changes)
        warnings.extend(identity_warnings)

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
        # Interactive onboarding: offer the `gh auth login` flow, then rebuild the report from
        # a re-probe (the re-probe is the authority; the same GitHubError degrade applies).
        if not auth.ok and interactive and offer_gh_login():
            try:
                auth = github.check_auth()
                repo = github.check_repo_access(root) if auth.ok else RepoAccess.skipped()
            except GitHubError as exc:
                auth = AuthStatus(ok=False, user=None, scopes=(), error=str(exc))
                repo = RepoAccess.skipped()
        github_report = GitHubReport(auth=auth, repo=repo)
    linear_report: LinearReport | None = None
    if verify:
        # The prompted + validated key seed runs first so the readiness probe right after
        # finds the freshly-saved key via `client_from_env(repo_root=root)`.
        if interactive:
            key_changes, key_warnings = prompt_linear_api_key(root)
            changes.extend(key_changes)
            warnings.extend(key_warnings)
        linear_report = _linear_readiness(root)
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
        linear=linear_report,
        warnings=warnings,
    )


def _missing_tool_failure(
    checks: list[EnvCheck], changes: list[str], warnings: list[str], *, interactive: bool
) -> InitReport:
    """The `missing_tool` failure report (exit 2).

    Interactive builds an **inline** failed report that preserves the guided pass's
    accumulated `changes`/`warnings` (the `skills_sync_failed` pattern — `env_failure` would
    zero them); non-interactive keeps `env_failure` (no guided pass ran, nothing to preserve).
    The message names REQUIRED checks only — a failing optional check (e.g. ast-grep) is
    non-fatal and must never be reported as a missing required tool.
    """
    missing = ", ".join(c.name for c in checks if not c.ok and not c.optional)
    message = f"Missing or outdated required tool(s): {missing}."
    if not interactive:
        return InitReport.env_failure("missing_tool", message, checks)
    return InitReport(
        ok=False,
        mode="unknown",
        env=checks,
        changes=changes,
        github=None,
        handoff=None,
        error_type="missing_tool",
        message=message,
        warnings=warnings,
    )


def _reconcile_extension_install(root: Path, changes: list[str], self_repo: bool) -> None:
    """Best-effort forward reconcile of perk's ``@mgiles/perk`` npm install.

    Materializes the install (``materialize_extension_install``): install-if-``absent`` /
    reinstall-if-``mismatch`` (the pinned ``@mgiles/perk@{__version__}``), no-op on
    ``self``/``present``/``unverifiable``. An ``NpmError`` (unpublished pin / offline) is swallowed
    into a non-fatal change line — it never blocks init, mirroring how the clone reconcile and
    GitHub readiness degrade (D3). A change line is recorded only when materialize actually changed
    something. Kept a small free helper so it is unit-testable.
    """
    message = materialize_extension_install(root, self_repo=self_repo)
    if message is not None:
        changes.append(message)


def _linear_readiness(root: Path) -> LinearReport | None:
    """The verify-gated Linear readiness step (non-fatal, the GitHub D3 mirror).

    ``None`` unless the committed backend selection is ``"linear"`` (a config error → skip;
    the config/issues checks own it). Missing ``LINEAR_API_KEY`` / ``[issues] team`` degrade
    to an errored report; otherwise the shared probe runs with ``ensure_labels=True`` (init
    converges the six perk labels upfront — created names land on the report, not `changes`).
    The follow-on ``load_committed_issues_team`` read runs only after a successful backend read
    (same table, same validity), so it needs no guard of its own.
    """
    try:
        selected = load_committed_issues_backend(root)
    except (tomllib.TOMLDecodeError, ConfigError):
        return None
    if selected != "linear":
        return None
    team = load_committed_issues_team(root)
    if team is None:
        return LinearReport(
            readiness=None,
            error='[issues] team is required when backend = "linear" — '
            "set the Linear team key in .perk/config.toml",
        )
    try:
        client = linear_client.client_from_env(repo_root=root)
    except IssueBackendError as exc:
        return LinearReport(readiness=None, error=str(exc))
    readiness = linear.check_readiness(client, team_key=team, ensure_labels=True)
    project = None
    if readiness.auth_ok and readiness.team_ok:
        project = linear.check_project_readiness(client, team_key=team)
    return LinearReport(readiness=readiness, team=team, project=project)
