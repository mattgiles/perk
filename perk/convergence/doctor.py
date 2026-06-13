"""`perk doctor` — `init`'s diagnostic twin (the verify/repair engine).

Where `init` converges a repo *forward*, `doctor` **reports** coherence and `--fix`
**repairs** drift. The managed-piece checks reuse `init`'s convergence helpers in **dry-run**
mode (`apply=False`) — so init and doctor share one desired-state SSOT (D2) — and `--fix` runs
the same helpers with `apply=True`. Everything downstream of the group *builders* is **pure**
over a `list[Check]` (report / exit-code / json / render), so that layer tests without any
monkeypatch.

Principles (T6, from the erk prior-art pass):
- **No silent pass:** a check that cannot be evaluated reports `warn`/`info` *with the reason*,
  never a silent `ok`.
- **GitHub is non-fatal** (D3): unauthed / no-access / `gh` errored ⇒ `warn`, never `fail`.
- **Report, don't refuse** (D5): a missing required tool is a failing check (exit 1); only
  `not_a_repo` blocks (exit 2).
"""

import json
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Self

from perk import github
from perk.backends import issues, linear, linear_backend
from perk.backends.issue_backend import IssueBackendError
from perk.cli.ensure import UserFacingCliError
from perk.convergence import capabilities, env, init
from perk.github import GitHubError
from perk.run.workflow_artifacts import RUNNER_ENABLED_VAR, RUNNER_PAT_SECRET
from perk.state import cache, gc
from perk.substrate import bindings, git, providers, registry
from perk.substrate.config import (
    CONFIG_FILENAME,
    LOCAL_CONFIG_FILENAME,
    load_committed_issues_backend,
    load_committed_issues_team,
    load_config,
)

Status = Literal["ok", "warn", "info", "fail"]

# Render groups for the managed convergences: settings under "package", the workflow-dir/cache
# layout under "state", the rest under "repository".
_MANAGED_GROUP: dict[str, str] = {
    "settings-wiring": "package",
    "workflow-dir": "state",
    "skills-manifest": "skills",
    "runner-workflow": "repository",
}


@dataclass(frozen=True)
class Check:
    """A single health finding — pure data, so the report/render layer needs no monkeypatch."""

    name: str
    group: str
    status: Status
    message: str
    detail: str = ""
    remediation: str = ""


@dataclass(frozen=True)
class DoctorReport:
    """Structured result of a ``run_doctor`` (rendered human or ``--json`` by the command)."""

    checks: list[Check]
    fixed: list[str]
    self_repo: bool
    error_type: str | None = None
    message: str | None = None
    fix_errors: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return self.error_type is None and not any(c.status == "fail" for c in self.checks)

    @property
    def exit_code(self) -> int:
        if self.error_type == "not_a_repo":
            return 2
        return 1 if any(c.status == "fail" for c in self.checks) else 0

    @classmethod
    def not_repo(cls) -> Self:
        return cls(
            checks=[],
            fixed=[],
            self_repo=False,
            error_type="not_a_repo",
            message="Not a git repository — run 'perk doctor' inside a git repository.",
        )


# --- group builders (impure: shells / file reads) -------------------------------------------


def _env_checks() -> list[Check]:
    checks: list[Check] = []
    for c in env.check_environment():
        checks.append(
            Check(
                name=c.name,
                group="environment",
                status="ok" if c.ok else "fail",
                message=f"{c.name} {'ok' if c.ok else 'missing/outdated'}",
                detail=c.detail,
                remediation="" if c.ok else c.remediation,
            )
        )
    return checks


def _github_checks(root: Path) -> list[Check]:
    """GitHub readiness — always non-fatal (`warn`); never mutates; no silent pass."""
    try:
        auth = github.check_auth()
    except GitHubError as exc:
        return [
            Check(
                "github-auth",
                "github",
                "warn",
                "GitHub auth not verified",
                str(exc),
                "Run: gh auth login",
            )
        ]
    if not auth.ok:
        return [
            Check(
                "github-auth",
                "github",
                "warn",
                "GitHub not authenticated",
                auth.error or "",
                "Run: gh auth login",
            )
        ]
    checks = [Check("github-auth", "github", "ok", f"authenticated as {auth.user or '?'}")]
    try:
        repo = github.check_repo_access(root)
    except GitHubError as exc:
        checks.append(Check("github-repo", "github", "warn", "repo access not verified", str(exc)))
        return checks
    if repo.ok and repo.can_push:
        checks.append(Check("github-repo", "github", "ok", f"push access to {repo.repo}"))
    elif repo.ok:
        checks.append(
            Check(
                "github-repo", "github", "warn", f"no push access to {repo.repo}", repo.error or ""
            )
        )
    else:
        checks.append(Check("github-repo", "github", "warn", "no GitHub repo", repo.error or ""))
    return checks


def _runner_enabled_check(root: Path) -> tuple[Check, bool]:
    """D4.2 — always report the enabled state; ``disabled=True`` is the D4.3 early-stop."""
    enabled = github.get_repo_variable(name=RUNNER_ENABLED_VAR, repo_root=root)
    if enabled is None:
        return (
            Check(
                "runner-enabled",
                "runner",
                "info",
                f"remote runner enabled ({RUNNER_ENABLED_VAR} unset → default-on)",
            ),
            False,
        )
    if enabled == "false":
        return (
            Check(
                "runner-enabled",
                "runner",
                "info",
                f"remote runner disabled ({RUNNER_ENABLED_VAR}=false)",
            ),
            True,
        )
    return (
        Check(
            "runner-enabled",
            "runner",
            "info",
            f"remote runner enabled ({RUNNER_ENABLED_VAR}={enabled})",
        ),
        False,
    )


def _runner_pat_check(root: Path, absent_detail: str) -> Check:
    """D5.1 — the checkout/push PAT."""
    pat = github.secret_exists(name=RUNNER_PAT_SECRET, repo_root=root)
    if pat is True:
        return Check("runner-pat-secret", "runner", "ok", f"{RUNNER_PAT_SECRET} configured")
    if pat is False:
        return Check(
            "runner-pat-secret",
            "runner",
            "warn",
            f"{RUNNER_PAT_SECRET} not configured",
            absent_detail,
            f"gh secret set {RUNNER_PAT_SECRET}",
        )
    return Check(
        "runner-pat-secret",
        "runner",
        "info",
        f"could not verify {RUNNER_PAT_SECRET} (insufficient permission?)",
    )


# Model credentials the runner accepts (the workflow's "either" validate logic — §8.14).
_MODEL_SECRETS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")


def _runner_model_check(root: Path, absent_detail: str) -> Check:
    """D5.2 — the model credential (either ANTHROPIC_API_KEY or OPENAI_API_KEY)."""
    model_results = {
        name: github.secret_exists(name=name, repo_root=root) for name in _MODEL_SECRETS
    }
    present = [name for name, ok in model_results.items() if ok is True]
    if present:
        return Check(
            "runner-model-secret",
            "runner",
            "ok",
            f"model credential configured ({', '.join(present)})",
        )
    if all(ok is False for ok in model_results.values()):
        return Check(
            "runner-model-secret",
            "runner",
            "warn",
            "no model credential configured",
            absent_detail,
            "gh secret set ANTHROPIC_API_KEY   # or OPENAI_API_KEY",
        )
    return Check(
        "runner-model-secret",
        "runner",
        "info",
        "could not verify model credential",
    )


def _runner_permissions_check(root: Path) -> Check:
    """D5.3 — workflow permissions (advisory ``info`` in all non-error cases — perk pushes with
    a PAT, not github.token, so this is not blocking for the runner).
    """
    perms_detail = "advisory — perk's runner pushes with a PAT, not github.token"
    perms = github.get_workflow_permissions(repo_root=root)
    if perms is None:
        return Check(
            "runner-workflow-permissions",
            "runner",
            "info",
            "could not verify workflow permissions",
            perms_detail,
        )
    if perms.can_approve_pull_request_reviews:
        return Check(
            "runner-workflow-permissions",
            "runner",
            "info",
            "Actions may create PRs",
            perms_detail,
        )
    return Check(
        "runner-workflow-permissions",
        "runner",
        "info",
        "Actions cannot create PRs",
        perms_detail,
        "gh api --method PUT repos/{owner}/{repo}/actions/permissions/workflow "
        "-F can_approve_pull_request_reviews=true",
    )


def _runner_checks(root: Path, self_repo: bool) -> list[Check]:
    """Pre-flight health-checks for the remote-runner's prerequisites (§8.16, Node 2.4).

    Report-only and **non-fatal** (never ``fail``): present → ``ok``; actionable-absent → ``warn``;
    unverifiable → ``info``. A ``warn`` keeps exit 0 (``report.healthy`` keys off ``fail`` only),
    matching erk's always-passes posture and §8.6's GitHub-non-fatal rule. Shells ``gh``, so it
    runs only under ``verify=True``; a ``GitHubError`` is degraded by ``_build_checks`` to a single
    ``info``. Kept a free function so Node 3.3's ``perk doctor workflow`` can compose it directly.
    """
    # D6 — same check set for both repo kinds (the runner-workflow capability is scope="both");
    # only the `detail` wording adapts.
    if self_repo:
        absent_detail = "expected on perk's own repo (perk dogfoods `--remote` drives)"
    else:
        absent_detail = "required only if you use `perk … --remote` drives"

    # D4.1 — auth gate: re-probe auth; unauthed ⇒ a single info, no further gh calls.
    auth = github.check_auth()
    if not auth.ok:
        return [
            Check(
                "runner-prereqs",
                "runner",
                "info",
                "runner prereqs not checked (GitHub not authenticated)",
                auth.error or "",
            )
        ]

    # Composition: enabled → (if deliberately disabled, stop — don't nag about credentials,
    # D4.3) → pat → model → permissions.
    enabled_check, disabled = _runner_enabled_check(root)
    checks: list[Check] = [enabled_check]
    if disabled:
        return checks
    checks.append(_runner_pat_check(root, absent_detail))
    checks.append(_runner_model_check(root, absent_detail))
    checks.append(_runner_permissions_check(root))
    return checks


def _runner_workflow_managed_check(root: Path, self_repo: bool) -> Check:
    """The ``runner-workflow`` managed-artifact-present check (same shape as ``_managed_checks``).

    Locates the ``runner-workflow`` ``ManagedConvergence`` and dry-runs it: drift ⇒ ``fail`` (the
    runner cannot work without the managed workflow), converged ⇒ ``ok``. Wrapped so an
    unverifiable file (``UserFacingCliError``/``OSError``) is a loud ``fail``, never a silent pass.
    Group ``"repository"`` (mirrors ``_MANAGED_GROUP``). Kept free so ``workflow_checks`` composes
    it without duplicating the convergence wiring.
    """
    mc = next(
        (m for m in init.managed_convergences(root, self_repo) if m.name == "runner-workflow"),
        None,
    )
    if mc is None:  # defensive: the convergence list always carries it (capability scope="both")
        return Check(
            "runner-workflow",
            "repository",
            "fail",
            "runner-workflow convergence missing",
            "no runner-workflow ManagedConvergence registered",
            "Reinstall perk.",
        )
    try:
        drift = mc.converge(False)
    except (UserFacingCliError, OSError) as exc:
        detail = exc.format_message() if isinstance(exc, UserFacingCliError) else str(exc)
        return Check(
            "runner-workflow",
            "repository",
            "fail",
            "runner-workflow unverifiable",
            detail,
            "Fix the file, then re-run 'perk init'.",
        )
    if drift:
        return Check(
            "runner-workflow",
            "repository",
            "fail",
            "runner-workflow drift",
            "; ".join(drift),
            "perk doctor --fix",
        )
    return Check("runner-workflow", "repository", "ok", "runner-workflow converged")


def workflow_checks(root: Path, self_repo: bool, *, verify: bool = True) -> list[Check]:
    """The workflow-focused static layer for ``perk doctor workflow`` (Node 3.3, §8.19).

    Reuses the same builders as bare ``perk doctor`` (doctor's SSOT): the GitHub readiness +
    remote-runner prereq checks (under ``verify``) ⊕ the ``runner-workflow``
    managed-artifact-present check (always). A ``GitHubError`` while probing the runner prereqs
    degrades to a single ``info``
    ``runner-prereqs`` (mirrors ``_build_checks``).
    """
    checks: list[Check] = []
    if verify:
        checks.extend(_github_checks(root))
        try:
            checks.extend(_runner_checks(root, self_repo))
        except GitHubError as exc:
            checks.append(
                Check("runner-prereqs", "runner", "info", f"runner prereqs not checked: {exc}")
            )
    checks.append(_runner_workflow_managed_check(root, self_repo))
    return checks


def _managed_checks(root: Path, self_repo: bool) -> list[Check]:
    """The structural managed pieces, as converge dry-runs (`apply=False`); filtered by scope."""
    applicable = {cap.name for cap in capabilities.applicable(self_repo)}
    checks: list[Check] = []
    for mc in init.managed_convergences(root, self_repo):
        if not any(name in applicable for name in mc.covers):
            continue
        group = _MANAGED_GROUP.get(mc.name, "repository")
        try:
            drift = mc.converge(False)
        except (UserFacingCliError, OSError) as exc:
            # No silent pass: an unverifiable managed piece (malformed file, or one we cannot
            # even read) fails loudly with the reason in `detail`, never reads as a silent ok.
            detail = exc.format_message() if isinstance(exc, UserFacingCliError) else str(exc)
            checks.append(
                Check(
                    mc.name,
                    group,
                    "fail",
                    f"{mc.name} unverifiable",
                    detail,
                    "Fix the file, then re-run 'perk init'.",
                )
            )
            continue
        if drift:
            checks.append(
                Check(
                    mc.name,
                    group,
                    "fail",
                    f"{mc.name} drift",
                    "; ".join(drift),
                    "perk doctor --fix",
                )
            )
        else:
            checks.append(Check(mc.name, group, "ok", f"{mc.name} converged"))
    return checks


def _config_check(root: Path) -> Check:
    """Config is user-editable: present + parses + (defaulted) keys — never a content diff."""
    pi = root / ".pi"
    missing = [n for n in (CONFIG_FILENAME, LOCAL_CONFIG_FILENAME) if not (pi / n).is_file()]
    if missing:
        return Check(
            "config",
            "repository",
            "fail",
            "config missing",
            ", ".join(f".pi/{n}" for n in missing),
            "perk doctor --fix",
        )
    try:
        load_config(root)
    except tomllib.TOMLDecodeError as exc:
        return Check(
            "config",
            "repository",
            "fail",
            "config invalid (bad TOML)",
            str(exc),
            "Fix .pi/perk.toml by hand (perk will not overwrite your edits).",
        )
    return Check("config", "repository", "ok", "config present + valid")


def _registry_check() -> Check:
    try:
        reg = registry.load_registry()
    except registry.RegistryError as exc:
        return Check(
            "registry", "registry", "fail", "registry not loadable", str(exc), "Reinstall perk."
        )
    issues = registry.validate(reg)
    errors = [i for i in issues if i.severity is registry.Severity.ERROR]
    if errors:
        return Check(
            "registry",
            "registry",
            "fail",
            "registry invalid",
            "; ".join(str(i) for i in errors[:3]),
            "Reinstall perk.",
        )
    warnings = [i for i in issues if i.severity is registry.Severity.WARNING]
    if warnings:
        return Check(
            "registry",
            "registry",
            "warn",
            f"registry: {len(warnings)} warning(s)",
            "; ".join(str(i) for i in warnings[:3]),
        )
    return Check("registry", "registry", "ok", f"registry valid ({len(reg.stages)} stages)")


def _bindings_check(root: Path, self_repo: bool) -> Check:
    """Validate the FULL resolved skill-binding set: dropped-user issues + target existence (3.1).

    Loud-but-non-fatal (D1): every binding misconfiguration is a ``warn`` so ``perk doctor`` stays
    exit-0 over it. A ``BindingsError`` on the *bundled* file is a ``fail`` (cannot happen in a
    healthy install; mirrors ``_registry_check``). The full resolved set is validated (D3): the
    resolver's dropped-user-binding ``issues`` plus, per delivered binding, skill-presence and
    trigger-target existence (D5). Self-repo accepts the ``skills/<name>`` skill layout (D4).
    """
    try:
        defaults = bindings.load_bindings().bindings
    except bindings.BindingsError as exc:
        return Check(
            "bindings", "bindings", "fail", "bindings not loadable", str(exc), "Reinstall perk."
        )

    problems: list[str] = []
    try:
        user = load_config(root).user_bindings
    except tomllib.TOMLDecodeError:
        user = []
        problems.append("user bindings not evaluated — config invalid; see the config check")

    resolved = bindings.resolve_bindings(user, defaults=defaults)
    problems.extend(str(i) for i in resolved.issues)

    try:
        stage_ids: set[str] | None = registry.load_registry().stage_ids()
    except registry.RegistryError:
        stage_ids = None
        problems.append("stage targets not validated — registry unloadable; see the registry check")

    for binding in resolved.bindings:
        if not bindings.is_skill_installed(root, binding.skill, self_repo=self_repo):
            problems.append(
                f"{binding.trigger}: skill `{binding.skill}` is not installed "
                f"(no .agents/skills/{binding.skill}/SKILL.md)"
            )
        if binding.kind == "stage" and stage_ids is not None and binding.target_id not in stage_ids:
            problems.append(
                f"{binding.trigger}: stage `{binding.target_id}` is not a registry stage"
            )
        elif (
            binding.kind == "command"
            and binding.target_id not in bindings.DELIVERABLE_COMMAND_TARGETS
        ):
            problems.append(
                f"{binding.trigger}: command `{binding.target_id}` has no perk binding-delivery "
                "surface (this binding never fires)"
            )

    if not problems:
        return Check("bindings", "bindings", "ok", f"bindings valid ({len(resolved.bindings)})")
    shown = "; ".join(problems[:3])
    if len(problems) > 3:
        shown += f" (+{len(problems) - 3} more)"
    return Check(
        "bindings",
        "bindings",
        "warn",
        f"bindings: {len(problems)} problem(s)",
        shown,
        "Fix .pi/perk.toml [[bindings]], or re-run 'perk init' / 'perk doctor --fix' to sync.",
    )


def _providers_check(root: Path) -> Check:
    """Validate the provider-selection supported set + the repo selection (loud-but-non-fatal).

    A ``ProvidersError`` on the *bundled* file is a ``fail`` (cannot happen in a healthy install;
    mirrors ``_registry_check``). An ``ERROR`` Issue from the shape validator on the bundled file
    is a ``fail``. The repo ``[providers]`` selection is resolved against the supported set; any
    resolver issue (unknown id / seam mismatch) is a single ``warn`` so ``perk doctor`` stays
    exit-0 over it. Package-wired / orphan drift is NOT checked here — that is owned by the
    `settings-wiring` managed convergence (D6).
    """
    try:
        provider_set = providers.load_providers()
    except providers.ProvidersError as exc:
        return Check(
            "providers", "providers", "fail", "providers not loadable", str(exc), "Reinstall perk."
        )

    errors = [i for i in providers.validate(provider_set) if i.severity is registry.Severity.ERROR]
    if errors:
        return Check(
            "providers",
            "providers",
            "fail",
            "providers invalid",
            "; ".join(str(i) for i in errors[:3]),
            "Reinstall perk.",
        )

    problems: list[str] = []
    try:
        selection = load_config(root).providers
    except tomllib.TOMLDecodeError:
        selection = {}
        problems.append("selection not evaluated — config invalid; see the config check")

    resolved = providers.resolve_providers(selection, provider_set)
    problems.extend(str(i) for i in resolved.issues)

    if not problems:
        return Check(
            "providers",
            "providers",
            "ok",
            f"providers valid (selection: plan={resolved.plan.id}, todo={resolved.todo.id})",
        )
    shown = "; ".join(problems[:3])
    if len(problems) > 3:
        shown += f" (+{len(problems) - 3} more)"
    return Check(
        "providers",
        "providers",
        "warn",
        f"providers: {len(problems)} problem(s)",
        shown,
        "Fix .pi/perk.toml [providers], or re-run 'perk init' / 'perk doctor --fix' to sync.",
    )


def _issues_check(root: Path) -> Check:
    """Validate the committed `[issues]` selection (contracts.md §8.21).

    Maps ``issues.resolve_issue_backend_id``'s outcomes (never duplicates the vocabulary):
    absent/``"github"`` → ``ok``; ``"linear"`` **with** a committed team → ``ok``; ``"linear"``
    **without** a team → ``fail`` (offline-decidable, hard-breaks every issue-touching command);
    unknown → ``fail`` — unlike `[providers]` (which falls back gracefully and only warns), a bad
    selection hard-breaks **every** issue-touching command, so doctor must say so loudly. A
    malformed committed TOML → ``warn`` deferring to the config check (mirrors
    ``_providers_check``). No ``--fix`` arm: the selection is user-owned config; nothing is
    convergeable. Network readiness (auth/team-existence/labels) is the verify-gated ``linear``
    group's job, not this offline check's.
    """
    try:
        load_committed_issues_backend(root)
    except tomllib.TOMLDecodeError:
        return Check(
            "issues-backend",
            "issues",
            "warn",
            "selection not evaluated — config invalid; see the config check",
        )
    try:
        backend_id = issues.resolve_issue_backend_id(root)
    except IssueBackendError as exc:
        return Check(
            "issues-backend",
            "issues",
            "fail",
            str(exc),
            "",
            'Fix .pi/perk.toml [issues] — backend must be "github" or "linear".',
        )
    if backend_id == issues.LINEAR_BACKEND_ID:
        team = load_committed_issues_team(root)
        if team is None:
            return Check(
                "issues-backend",
                "issues",
                "fail",
                '[issues] team is required when backend = "linear"',
                "",
                'Set [issues] team (the Linear team key, e.g. "ENG") in .pi/perk.toml.',
            )
        return Check("issues-backend", "issues", "ok", f"issues backend: linear (team {team})")
    return Check("issues-backend", "issues", "ok", f"issues backend: {backend_id}")


def _linear_selected(root: Path) -> bool:
    """The verify-gate read for the `linear` group (malformed TOML defers to the config check)."""
    try:
        return load_committed_issues_backend(root) == issues.LINEAR_BACKEND_ID
    except tomllib.TOMLDecodeError:
        return False


_LINEAR_KEY_REMEDIATION = (
    "export LINEAR_API_KEY (create a personal API key at linear.app Settings → Security & access)"
)


def _linear_checks(root: Path) -> list[Check]:
    """Linear readiness — verify-gated; always non-fatal (`warn`, the github-group D3 mirror).

    Built from one ``check_readiness(..., ensure_labels=False)`` call (lookup-only — the repair
    is `perk init` / `perk doctor --fix`). Phases short-circuit like the probe: no auth → no
    team/labels checks (no silent pass — the failure carries its reason).
    """
    team = load_committed_issues_team(root)
    try:
        client = linear.client_from_env()
    except IssueBackendError as exc:
        return [
            Check(
                "linear-auth",
                "linear",
                "warn",
                "Linear auth not verified",
                str(exc),
                _LINEAR_KEY_REMEDIATION,
            )
        ]
    if team is None:
        # The offline `issues-backend` check already fails on this; the network probe needs a
        # team to run, so report the gap here too (no silent pass) and stop.
        return [
            Check(
                "linear-team",
                "linear",
                "warn",
                "[issues] team not set — readiness not checked",
                "",
                "Set [issues] team in .pi/perk.toml.",
            )
        ]
    readiness = linear_backend.check_readiness(client, team_key=team, ensure_labels=False)
    if not readiness.auth_ok:
        return [
            Check(
                "linear-auth",
                "linear",
                "warn",
                "Linear not authenticated",
                readiness.error or "",
                _LINEAR_KEY_REMEDIATION,
            )
        ]
    checks = [Check("linear-auth", "linear", "ok", f"authenticated as {readiness.user or '?'}")]
    if not readiness.team_ok:
        checks.append(
            Check(
                "linear-team",
                "linear",
                "warn",
                f"team {team} not verified",
                readiness.error or "",
                'Set [issues] team to your Linear team key (e.g. "ENG") in .pi/perk.toml.',
            )
        )
        return checks
    checks.append(Check("linear-team", "linear", "ok", f"team {team} found"))
    if readiness.error:
        checks.append(
            Check("linear-labels", "linear", "warn", "labels not verified", readiness.error)
        )
    elif readiness.missing_labels:
        checks.append(
            Check(
                "linear-labels",
                "linear",
                "warn",
                f"missing label(s): {', '.join(readiness.missing_labels)}",
                "",
                "Run `perk init` or `perk doctor --fix`.",
            )
        )
    else:
        checks.append(Check("linear-labels", "linear", "ok", "perk labels present"))
    return checks


def _subagent_engine_check(root: Path) -> Check:
    """Informational pointer for the borrowed spawned-delegation seam (P2.T6).

    Enumerates the committed perk-owned agent defs (`.pi/agents/*.md`) for the detail — package/dir
    drift itself is owned by `settings-wiring` (the `npm:pi-subagents` entry) and `subagent-agents`
    (`.pi/agents/`). Status `ok` keeps a healthy repo's summary clean; the detail carries the
    honesty note that the live-spawn smoke is a Phase-3 deferral.
    """
    agents_dir = root / ".pi" / "agents"
    names = sorted(p.stem for p in agents_dir.glob("*.md")) if agents_dir.is_dir() else []
    listing = ", ".join(f"perk.{n}" for n in names) if names else "(none)"
    return Check(
        "subagent-engine",
        "package",
        "ok",
        "borrowed pi-subagents engine + perk-owned agent defs",
        "presence owned by settings-wiring; defs dir owned by subagent-agents; "
        "perk agents are namespaced (package: perk) and invoked by explicit perk.* name; "
        f"committed defs: {listing}; legacy .agents/skills/*/SKILL.md surface as stray agents "
        "(benign — never invoked); the live-spawn smoke is deferred to Phase 3 `doctor workflow`.",
    )


def _skills_delivery_check(root: Path, self_repo: bool) -> Check:
    """The fail-level skills-delivery substrate check (#289 — skills delivery is load-bearing).

    perk's own skills reach sessions only through the `skills` CLI-managed `.agents/skills/`
    symlinks, so a broken delivery substrate is a **fail** (unlike `_bindings_check`, which owns
    user-binding *config* and stays warn-level). Evaluated under ``verify`` only (it shells git
    and validates external-CLI outcomes). First match wins:

    (a) tracked content under the skills-CLI managed pathspecs (the `skills init` hard-refusal);
        a ``GitError`` during the probe degrades to ``warn`` (no silent pass);
    (b) the perk manifest fragment exists but `.agents/manifest.yaml` does not — `skills init`
        failed or never ran (so `skills update --sync` can never run);
    (c) any ``PERK_SKILLS`` name is not installed (``bindings.is_skill_installed``).
    """
    try:
        conflicts = init.skills_conflict_paths(root)
    except git.GitError as exc:
        return Check(
            "skills-delivery",
            "skills",
            "warn",
            "skills delivery not fully verified",
            f"tracked-content probe not evaluated: {exc}",
        )
    if conflicts:
        return Check(
            "skills-delivery",
            "skills",
            "fail",
            "tracked content under skills-CLI managed paths",
            ", ".join(conflicts),
            "Migrate the committed skill bodies out of the skills-CLI managed paths "
            "(e.g. into a committed top-level skills/ dir declared in .agents/manifest.yaml), "
            "untrack them (git rm --cached -r <path>), then re-run 'perk init'.",
        )
    fragment = root / init.PERK_SKILLS_MANIFEST_DIR / init.PERK_SKILLS_MANIFEST_FILENAME
    if fragment.is_file() and not (root / ".agents" / "manifest.yaml").is_file():
        return Check(
            "skills-delivery",
            "skills",
            "fail",
            "skills workspace not initialized — `skills init` failed or never ran",
            ".agents/manifest.d/perk.yaml exists but .agents/manifest.yaml does not",
            "Run 'perk doctor --fix' (or 'perk init') and review its output.",
        )
    missing = [
        name
        for name in init.PERK_SKILLS
        if not bindings.is_skill_installed(root, name, self_repo=self_repo)
    ]
    if missing:
        return Check(
            "skills-delivery",
            "skills",
            "fail",
            f"{len(missing)} perk skill(s) not delivered",
            ", ".join(missing),
            "Run 'perk doctor --fix'.",
        )
    return Check("skills-delivery", "skills", "ok", "perk skills delivered via .agents/skills/")


def _bad_handoffs(workflow_dir: Path) -> list[str]:
    handoff_dir = workflow_dir / "handoff"
    if not handoff_dir.is_dir():
        return []
    bad: list[str] = []
    for path in sorted(handoff_dir.glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            bad.append(path.name)
    return bad


def _cache_check(root: Path) -> Check:
    """Handoff-blob integrity. (The `.pi/workflow/` *layout* is the workflow-dir convergence.)"""
    bad = _bad_handoffs(cache.workflow_dir(root))
    if bad:
        return Check("cache-handoff", "state", "warn", "unreadable handoff blob(s)", ", ".join(bad))
    return Check("cache-handoff", "state", "ok", "handoff blobs valid")


def _gc_check(root: Path) -> Check:
    """Report prunable run state (warn + remediation). No ``--fix`` arm: deletion is exclusively
    ``perk state prune`` (doctor's fixes are documented non-destructive). Pure filesystem + the
    bundled registry, so it is not verify-gated (deterministic in unit tests, like the cache check).
    """
    plan = gc.plan_prune(root)
    n = len(plan.eligible)
    if n == 0:
        return Check("cache-gc", "state", "ok", "no prunable run state")
    detail = "; ".join(f"{c.run_id} ({c.reason})" for c in plan.eligible[:3])
    if n > 3:
        detail += f" (+{n - 3} more)"
    return Check(
        "cache-gc",
        "state",
        "warn",
        f"{n} prunable run dir(s)/handoff blob(s)",
        detail,
        "perk state prune",
    )


def _build_checks(root: Path, self_repo: bool, *, verify: bool) -> list[Check]:
    """Assemble all groups. ``verify=False`` skips only the external shells (env/github)."""
    checks: list[Check] = []
    if verify:
        checks.extend(_env_checks())
        checks.extend(_github_checks(root))
        try:
            checks.extend(_runner_checks(root, self_repo))
        except GitHubError as exc:
            checks.append(
                Check("runner-prereqs", "runner", "info", f"runner prereqs not checked: {exc}")
            )
        # Verify-gated like env/github (network readiness); only when linear is selected.
        if _linear_selected(root):
            checks.extend(_linear_checks(root))
        # Verify-gated like env/github: it shells git + validates external-CLI outcomes.
        checks.append(_skills_delivery_check(root, self_repo))
    checks.extend(_managed_checks(root, self_repo))
    checks.append(_config_check(root))
    checks.append(_registry_check())
    checks.append(_bindings_check(root, self_repo))
    checks.append(_providers_check(root))
    checks.append(_issues_check(root))
    checks.append(_subagent_engine_check(root))
    checks.append(_cache_check(root))
    checks.append(_gc_check(root))
    return checks


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

    `.pi/workflow/plan.md` is a transient materialized cache (contracts.md §8.1) — it must be
    gitignored (now in the managed block) and never tracked. Early repos committed it and
    hand-added an ungrouped `/.pi/workflow/plan.md` ignore line *outside* the managed block.
    This forward-only repair removes the stray line and `git rm --cached`s the file; it is a
    no-op (returns `([], [])`) once converged, so `--fix` stays idempotent. Returns
    ``(changes, errors)`` — a failed untrack is reported, never swallowed.
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


# The legacy/one-off migration seam (erk's `init --upgrade` repairs, perk's home for them).
# Forward-only repairs for oddities `init` does not undo (e.g. a previously-tracked transient
# cache file). Each must be idempotent: a no-op (`([], [])`) once the repo is converged; each
# returns `(changes, errors)` so failures land loudly on `fix_errors`.
_MIGRATIONS: tuple[Callable[[Path], tuple[list[str], list[str]]], ...] = (
    _untrack_materialized_plan_cache,
)


def _fix_config(root: Path) -> list[str]:
    """Re-seed *missing* config files only (never overwrite a present/edited one)."""
    changes: list[str] = []
    init.converge_config(root, changes, force=False, interactive=False)
    return changes


def _fix_linear_labels(root: Path) -> tuple[list[str], list[str]]:
    """The verify-gated `--fix` label repair: ensure the four perk labels in Linear.

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
        client = linear.client_from_env()
    except IssueBackendError:
        return [], []
    readiness = linear_backend.check_readiness(client, team_key=team, ensure_labels=True)
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
    for migration in _MIGRATIONS:
        changes, migration_errors = migration(root)
        fixed.extend(changes)
        errors.extend(migration_errors)
    return fixed, errors


# --- entry point + pure serialization -------------------------------------------------------


def run_doctor(root: Path, *, fix: bool = False, verify: bool = True) -> DoctorReport:
    """Diagnose (and optionally repair) a perk-managed repo.

    ``verify=False`` skips the external shells (env/github), leaving the pure
    managed/config/registry/cache checks deterministic for unit tests. ``fix`` applies known
    repairs, then re-verifies so the exit code reflects the *post-fix* state. doctor's fixes are
    non-destructive (re-converge managed blocks; seed *missing* config only) so it never prompts.
    """
    self_repo = init.is_self_repo(root)
    checks = _build_checks(root, self_repo, verify=verify)
    fixed: list[str] = []
    fix_errors: list[str] = []
    if fix:
        fixed, fix_errors = _apply_fixes(root, self_repo, checks)
        # Materialize skills under the covers (the repair gesture) via the `skills` CLI —
        # load-bearing (#289): a failure is carried loudly on `fix_errors` (rendered by the
        # command + serialized in --json), and the post-fix re-verify below then also shows the
        # failing `skills-delivery` check, so the exit code reflects the still-broken state.
        # Gated on `verify` so the external shell runs on real `--fix` runs but not in unit
        # tests; a sync that links missing skills clears the `bindings`/`skills-delivery`
        # findings on the post-fix re-verify.
        if verify:
            sync_error = init.sync_skills(root, fixed, self_repo=self_repo)
            if sync_error is not None:
                fix_errors.append(sync_error)
            # The Linear label repair gesture (verify-gated like sync_skills — network I/O;
            # `_apply_fixes`' check-keyed loop only acts on `fail` checks, and the linear group
            # is warn-level). Lookup-first idempotency: a converged workspace reports nothing.
            linear_fixed, linear_errors = _fix_linear_labels(root)
            fixed.extend(linear_fixed)
            fix_errors.extend(linear_errors)
        if fixed or fix_errors:
            checks = _build_checks(root, self_repo, verify=verify)
    return DoctorReport(checks=checks, fixed=fixed, self_repo=self_repo, fix_errors=fix_errors)


def report_to_dict(report: DoctorReport) -> dict[str, object]:
    """Serialize for the ``--json`` supervisor surface (contracts §8.6)."""
    passed = sum(1 for c in report.checks if c.status == "ok")
    warnings = sum(1 for c in report.checks if c.status in ("warn", "info"))
    failed = sum(1 for c in report.checks if c.status == "fail")
    return {
        "success": report.error_type is None,
        "healthy": report.healthy,
        "self_repo": report.self_repo,
        "error_type": report.error_type,
        "message": report.message,
        "checks": [
            {
                "name": c.name,
                "group": c.group,
                "status": c.status,
                "message": c.message,
                "detail": c.detail,
                "remediation": c.remediation,
            }
            for c in report.checks
        ],
        "summary": {"passed": passed, "warnings": warnings, "failed": failed},
        "fixed": report.fixed,
        "fix_errors": report.fix_errors,
    }
