"""The config/registry/managed/state group builders."""

import json
import tomllib
from pathlib import Path

from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.cli.ensure import UserFacingCliError
from perk.convergence import capabilities, env, init
from perk.convergence.doctor.data import _MANAGED_GROUP, Check, Status
from perk.state import cache, gc
from perk.substrate import bindings, git, providers, registry
from perk.substrate.config import (
    CONFIG_FILENAME,
    LOCAL_CONFIG_FILENAME,
    load_committed_issues_backend,
    load_committed_issues_team,
    load_config,
)

# --- group builders (impure: shells / file reads) -------------------------------------------


def _env_checks() -> list[Check]:
    checks: list[Check] = []
    for c in env.check_environment():
        status: Status = "ok" if c.ok else ("warn" if c.optional else "fail")
        checks.append(
            Check(
                name=c.name,
                group="environment",
                status=status,
                message=f"{c.name} {'ok' if c.ok else 'missing/outdated'}",
                detail=c.detail,
                remediation="" if c.ok else c.remediation,
            )
        )
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
    errors = [i for i in issues if i.severity is registry.FindingSeverity.ERROR]
    if errors:
        return Check(
            "registry",
            "registry",
            "fail",
            "registry invalid",
            "; ".join(str(i) for i in errors[:3]),
            "Reinstall perk.",
        )
    warnings = [i for i in issues if i.severity is registry.FindingSeverity.WARNING]
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

    errors = [
        i for i in providers.validate(provider_set) if i.severity is registry.FindingSeverity.ERROR
    ]
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
            f"providers valid (selection: plan={resolved.plan.id}, todo={resolved.todo.id}, "
            f"askuser={resolved.askuser.id}, footer={resolved.footer.id}, "
            f"web={resolved.web.id})",
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

    Maps ``resolve.resolve_issue_backend_id``'s outcomes (never duplicates the vocabulary):
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
        backend_id = resolve.resolve_issue_backend_id(root)
    except IssueBackendError as exc:
        return Check(
            "issues-backend",
            "issues",
            "fail",
            str(exc),
            "",
            'Fix .pi/perk.toml [issues] — backend must be "github" or "linear".',
        )
    if backend_id == resolve.LINEAR_BACKEND_ID:
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


def _subagent_engine_check(root: Path) -> Check:
    """Informational pointer for the borrowed spawned-delegation seam.

    Enumerates the perk-owned agent defs delivered into `.pi/agents/perk/*.md` for the detail —
    package/dir drift itself is owned by `settings-wiring` (the `npm:pi-subagents` entry) and
    `subagent-agents` (which materializes + drift-repairs `.pi/agents/perk/`). Status `ok` keeps a
    healthy repo's summary clean; the detail carries the honesty note that the live-spawn smoke is
    deferred.
    """
    perk_dir = root / ".pi" / "agents" / "perk"
    names = sorted(p.stem for p in perk_dir.glob("*.md")) if perk_dir.is_dir() else []
    listing = ", ".join(f"perk.{n}" for n in names) if names else "(none)"
    return Check(
        "subagent-engine",
        "package",
        "ok",
        "borrowed pi-subagents engine + perk-owned agent defs",
        "presence owned by settings-wiring; defs delivered into .pi/agents/perk/ by init "
        "(subagent-agents convergence); perk agents are namespaced (package: perk) and invoked "
        f"by explicit perk.* name; delivered defs: {listing}; legacy .agents/skills/*/SKILL.md "
        "surface as stray agents (benign — never invoked); the live-spawn smoke is deferred to "
        "Phase 3 `doctor workflow`.",
    )


def _extension_clone_check(root: Path, self_repo: bool) -> Check:
    """Freshness of pi's git-package clone for perk (group ``package``; verify-gated network op).

    pi never self-advances a present project-scoped ``git:`` clone, so a clone first created at an
    old commit stays frozen and loads stale extension code. Built from
    ``init.extension_clone_status``: ``stale`` is a **fail** (with the ``perk doctor --fix``
    remediation — the reclone), ``unverifiable`` is a ``warn`` (no silent pass — carries the
    reason), and ``self``/``absent``/``fresh`` are benign (``info``/``info``/``ok``).
    """
    status, detail = init.extension_clone_status(root, self_repo=self_repo)
    if status == "self":
        return Check("extension-clone", "package", "info", "self-repo — local package, no clone")
    if status == "absent":
        return Check(
            "extension-clone",
            "package",
            "info",
            "clone absent — pi clones fresh main on next launch",
        )
    if status == "fresh":
        return Check("extension-clone", "package", "ok", "extension clone at current main")
    if status == "stale":
        return Check(
            "extension-clone",
            "package",
            "fail",
            "extension clone is stale",
            detail,
            "perk doctor --fix",
        )
    return Check("extension-clone", "package", "warn", "extension clone not verified", detail)


def _extension_install_check(root: Path, self_repo: bool) -> Check:
    """Presence + pinned version of perk's ``@perk/pi`` npm install (``package``; verify-gated).

    pi installs a missing project-scope ``npm:`` package lazily and **unlocked** at launch, so a
    missing / half-materialized install is a race window. Built from
    ``init.extension_install_status``. Unlike the clone check (where ``absent`` is benign ``info``),
    node 2.3's charter is that perk init/doctor *own installing*, so ``absent``/``mismatch`` are
    **fail** (with the ``perk doctor --fix`` install/reinstall remediation); ``unverifiable`` is a
    ``warn`` (no silent pass — carries the reason); ``present`` is ``ok`` and ``self`` is ``info``.
    """
    status, detail = init.extension_install_status(root, self_repo=self_repo)
    if status == "self":
        return Check(
            "extension-install", "package", "info", "self-repo — local package, no npm install"
        )
    if status == "absent":
        return Check(
            "extension-install",
            "package",
            "fail",
            "@perk/pi extension not installed",
            detail,
            "perk doctor --fix",
        )
    if status == "mismatch":
        return Check(
            "extension-install",
            "package",
            "fail",
            "@perk/pi install version drift",
            detail,
            "perk doctor --fix",
        )
    if status == "present":
        return Check(
            "extension-install", "package", "ok", "@perk/pi installed at the pinned version"
        )
    return Check("extension-install", "package", "warn", "@perk/pi install not verified", detail)


def _skills_delivery_check(root: Path, self_repo: bool) -> Check:
    """The fail-level skills-delivery substrate check (skills delivery is load-bearing).

    perk's own skills reach sessions only through the `skills` CLI-managed `.agents/skills/`
    symlinks, so a broken delivery substrate is a **fail** (unlike `_bindings_check`, which owns
    user-binding *config* and stays warn-level). Evaluated under ``verify`` only (it shells git
    and validates external-CLI outcomes). First match wins:

    (a) tracked content under the skills-CLI managed pathspecs (the `skills init` hard-refusal);
        a ``GitError`` during the probe degrades to ``warn`` (no silent pass);
    (b) the perk manifest fragment exists but `.agents/manifest.yaml` does not — `skills init`
        failed or never ran (so `skills update --sync` can never run);
    (c) any ``MANAGED_SKILL_NAMES`` name (perk-authored + the required external skills) is not
        installed (``bindings.is_skill_installed``).
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
        for name in init.MANAGED_SKILL_NAMES
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
