"""Minimal, idempotent ``perk init`` — the init spine begins here (T1).

`init` is **declarative and convergent**: it edits files toward a desired state and
is safe to re-run (re-running on a converged repo is a no-op). It owns *all* Pi
wiring from the first turn (the init-spine principle).

T1 scope: wire ``.pi/settings.json`` (perk's own extension + the borrowed default
set), create the base ``.pi/workflow/`` dir, manage ``.gitignore``, and write a
managed ``AGENTS.md`` block. Env/GitHub verification, capability tracking, flags,
``--json``, and the post-init handoff are T5; the TOML config scaffold is T4.

**Package layout (Node 2.2 module->package split).** The single-file ``init`` module was
decomposed into a package along its natural seams — a pure verbatim relocation (no logic edits,
beyond the audit §4.2 ``cast``->``isinstance`` cleanup in ``settings``), following the
``perk/backends/linear_backend`` precedent (Node 2.1). This ``__init__`` keeps the orchestration
(``run_init``, ``managed_convergences``, ``_reconcile_extension_clone``, ``_linear_readiness``,
``_converge_workflow_dir``, ``_write_post_init``, ``is_self_repo``) and re-exports every submodule
symbol behind a sorted ``__all__``, preserving the ``init.X`` attribute-access import path
verbatim (zero consumer/test import churn). The orchestrators reference the moved helpers as
facade globals, so the existing ``init_mod.sync_skills`` / ``init_mod.materialize_extension_clone``
monkeypatches keep working. Submodules: ``templates``, ``report``, ``blocks``, ``settings``,
``agents``, ``skills``, ``extension_clone``.
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
from perk.convergence import capabilities, env
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
from perk.convergence.init.extension_clone import (
    ExtensionCloneStatus,
    _clone_extension_fresh,
    _extension_clone_lock,
    _extension_clone_url,
    _freshen_extension,
    consumer_git_clone_root,
    ensure_extension_clone_present,
    extension_clone_status,
    materialize_extension_clone,
)
from perk.convergence.init.report import (
    GitHubReport,
    InitReport,
    LinearReport,
    _env_to_dict,
    _linear_to_dict,
    report_to_dict,
)
from perk.convergence.init.settings import (
    BORROWED_PACKAGES,
    GIT_PACKAGE,
    LINEAR_PACKAGE,
    _converge_compaction,
    _converge_linear_package,
    _converge_provider_packages,
    _converge_settings,
    _desired_packages,
    _git_identity,
    _managed_identities,
    _merge_static_packages,
    _npm_name,
    _package_identity,
    _ProviderChanges,
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
from perk.github import AuthStatus, GitHubError, RepoAccess
from perk.run import workflow_artifacts
from perk.state import cache
from perk.substrate import git
from perk.substrate.config import (
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
    "LINEAR_PACKAGE",
    "MANAGED_SKILL_NAMES",
    "PERK_AGENTS",
    "PERK_GITHUB_URL",
    "PERK_LOCAL_TOML_TEMPLATE",
    "PERK_SKILLS",
    "PERK_SKILLS_MANIFEST_DIR",
    "PERK_SKILLS_MANIFEST_FILENAME",
    "PERK_SKILL_SOURCE",
    "PERK_TOML_TEMPLATE",
    "POST_INIT_TEMPLATE",
    "REQUIRED_EXTERNAL_SKILLS",
    "REQUIRED_SKILL_SOURCES",
    "SKILLS_MANAGED_PATHSPECS",
    "ExtensionCloneStatus",
    "GitHubReport",
    "InitReport",
    "LinearReport",
    "ManagedConvergence",
    "SkillSource",
    "_ProviderChanges",
    "_agents_inner",
    "_apply_managed_block",
    "_clone_extension_fresh",
    "_converge_compaction",
    "_converge_linear_package",
    "_converge_provider_packages",
    "_converge_settings",
    "_converge_skills_manifest",
    "_converge_subagent_agents",
    "_converge_workflow_dir",
    "_desired_packages",
    "_desired_skills_manifest",
    "_env_to_dict",
    "_extension_clone_lock",
    "_extension_clone_url",
    "_freshen_extension",
    "_git_identity",
    "_linear_readiness",
    "_linear_to_dict",
    "_managed_identities",
    "_merge_static_packages",
    "_npm_name",
    "_package_identity",
    "_reconcile_extension_clone",
    "_skill_link_state",
    "_skills_conflict_message",
    "_sync_failure",
    "_write_post_init",
    "consumer_git_clone_root",
    "converge_config",
    "ensure_extension_clone_present",
    "extension_clone_status",
    "git",
    "is_self_repo",
    "linear",
    "managed_convergences",
    "materialize_extension_clone",
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


def _write_post_init(root: Path, self_repo: bool) -> str:
    """Write the agent-readable post-init handoff; return its repo-relative path."""
    path = root / ".pi" / "workflow" / "post-init.md"
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
    changes: list[str] = []
    for mc in managed_convergences(root, self_repo):
        changes.extend(mc.converge(True))
    converge_config(root, changes, force=force, interactive=interactive)
    # Materialize the declared skills under the covers via the `skills` CLI — the single delivery
    # path in both self-repo and consumer trees (the Pi package no longer declares `pi.skills`,
    # so Pi discovers `perk-*` only through `.agents/skills/`).
    # Gated on `verify`: the external `skills` shells run on real inits but not in unit tests.
    # Load-bearing (#289): a sync failure is fatal (exit 2) — but convergence already happened,
    # so the failed report preserves `changes` (not `env_failure`, which zeroes them).
    if verify:
        sync_error = sync_skills(root, changes, self_repo=self_repo)
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
            )
        # Forward-reconcile pi's git-package clone (reclone-when-stale). Best-effort + non-fatal:
        # a network op (verify-gated), it degrades to a no-op when offline (`unverifiable`).
        _reconcile_extension_clone(root, changes, self_repo)

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
    linear_report: LinearReport | None = None
    if verify:
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
    )


def _reconcile_extension_clone(root: Path, changes: list[str], self_repo: bool) -> None:
    """Best-effort forward reconcile of pi's git-package clone (verify-gated, non-fatal).

    Materializes the clone **in place** (``materialize_extension_clone``): clone-if-absent /
    ``fetch``+``reset``-if-stale (no ``npm install``), leaving a present, fresh clone for both
    ``absent`` and ``stale``. ``self``/``fresh`` are internal no-ops and ``unverifiable``
    (offline) is left as-is — it never blocks init, mirroring how GitHub readiness degrades (D3).
    A change line is recorded only when materialize actually changed something (``None`` no-ops
    keep a converged re-run change-free). Kept a small free helper so it is unit-testable.
    """
    message = materialize_extension_clone(root, self_repo=self_repo)
    if message is not None:
        changes.append(message)


def _linear_readiness(root: Path) -> LinearReport | None:
    """The verify-gated Linear readiness step (non-fatal, the GitHub D3 mirror).

    ``None`` unless the committed backend selection is ``"linear"`` (a config error → skip;
    the config/issues checks own it). Missing ``LINEAR_API_KEY`` / ``[issues] team`` degrade
    to an errored report; otherwise the shared probe runs with ``ensure_labels=True`` (init
    converges the five perk labels upfront — created names land on the report, not `changes`).
    """
    try:
        selected = load_committed_issues_backend(root)
    except tomllib.TOMLDecodeError:
        return None
    if selected != "linear":
        return None
    team = load_committed_issues_team(root)
    if team is None:
        return LinearReport(
            readiness=None,
            error='[issues] team is required when backend = "linear" — '
            "set the Linear team key in .pi/perk.toml",
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
