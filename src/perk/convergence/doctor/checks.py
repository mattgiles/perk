"""The config/registry/managed/state group builders."""

import json
import tomllib
from pathlib import Path

from perk import __version__
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.cli.ensure import UserFacingCliError
from perk.convergence import capabilities, env, init, managed_state
from perk.convergence.doctor.data import _MANAGED_GROUP, Check, Status
from perk.convergence.managed_state import ArtifactHealth, HealthStatus
from perk.state import cache, gc
from perk.substrate import bindings, git, paths, providers, registry
from perk.substrate.config import (
    PI_THINKING_LEVELS,
    ConfigError,
    ModelsTable,
    load_committed_issues_backend,
    load_committed_issues_team,
    load_committed_models,
    load_committed_models_table,
    load_config,
)
from perk.substrate.paths import CONFIG_FILENAME, LOCAL_CONFIG_FILENAME

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
    """Config is user-editable: present + parses + (defaulted) keys — never a content diff.

    Also probes the committed-only ``[models]`` read: its validation is deliberately **hard**
    (a typo never converges into the committed `settings.json` — init defers, this check
    fails with the pydantic field path). Scope note: only ``[models]`` gets this
    committed-read probe here — the ``[compaction]``/``[issues]`` parse gaps keep their
    current owners.
    """
    files = {
        CONFIG_FILENAME: paths.config_file(root),
        LOCAL_CONFIG_FILENAME: paths.local_config_file(root),
    }
    missing = [name for name, path in files.items() if not path.is_file()]
    if missing:
        # Diagnose an unmigrated legacy config distinctly from a genuinely-absent one, keyed on
        # the committed marker: a present `.pi/perk.toml` with no `.perk/config.toml` means the
        # repo predates the `.perk/` move — `doctor --fix` migrates it.
        if CONFIG_FILENAME in missing and paths.legacy_config_file(root).is_file():
            return Check(
                "config",
                "repository",
                "fail",
                "legacy config not migrated",
                ".pi/perk.toml",
                "perk doctor --fix",
            )
        return Check(
            "config",
            "repository",
            "fail",
            "config missing",
            ", ".join(f".perk/{n}" for n in missing),
            "perk doctor --fix",
        )
    try:
        load_config(root)
        load_committed_models(root)
    except tomllib.TOMLDecodeError as exc:
        return Check(
            "config",
            "repository",
            "fail",
            "config invalid (bad TOML)",
            str(exc),
            "Fix .perk/config.toml by hand (perk will not overwrite your edits).",
        )
    except ConfigError as exc:
        # The detail carries the pydantic field path (e.g. `workflow.base: Input should be a
        # valid string`) — doctor is the diagnostic surface that pinpoints the bad field.
        return Check(
            "config",
            "repository",
            "fail",
            "config invalid (bad value)",
            str(exc),
            "Fix .perk/config.toml by hand (perk will not overwrite your edits).",
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


def _bindings_check(root: Path) -> Check:
    """Validate the FULL resolved skill-binding set: dropped-user issues + target existence (3.1).

    Loud-but-non-fatal (D1): every binding misconfiguration is a ``warn`` so ``perk doctor`` stays
    exit-0 over it. A ``BindingsError`` on the *bundled* file is a ``fail`` (cannot happen in a
    healthy install; mirrors ``_registry_check``). The full resolved set is validated (D3): the
    resolver's dropped-user-binding ``issues`` plus, per delivered binding, skill-presence and
    trigger-target existence (D5). Skill presence is strict on the ``.agents/skills/`` delivery
    read path — the only path warm injection reads — in self-repo and consumer trees alike (the
    committed ``skills/`` layout never substitutes; the R3 blind spot).
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
    except (tomllib.TOMLDecodeError, ConfigError):
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
        if not bindings.is_skill_installed(root, binding.skill):
            problems.append(
                f"{binding.trigger}: skill `{binding.skill}` is not installed "
                f"(no .agents/skills/{binding.skill}/SKILL.md — the only path warm injection "
                "reads)"
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
        "Fix .perk/config.toml [[bindings]], or re-run 'perk init' / 'perk doctor --fix' to sync.",
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
    except (tomllib.TOMLDecodeError, ConfigError):
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
            f"web={resolved.web.id}, review={resolved.review.id})",
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
        "Fix .perk/config.toml [providers], or re-run 'perk init' / 'perk doctor --fix' to sync.",
    )


def _review_cli_check(root: Path) -> Check | None:
    """Selection-aware presence probe for the review seam's external ``hunk`` CLI (warn-level).

    Returns ``None`` when the review selection cannot be resolved (a corrupt bundled providers
    file — the config/providers checks own that failure; mirrors ``_stage_models_check``'s
    quiet-``None`` shape). A non-``hunk`` selection is ``ok`` (the CLI is not required); a
    ``hunk`` selection probes PATH — present is ``ok``, absent is a **warn** carrying the manual
    install hint (exit stays 0; ``perk doctor --fix`` retries the install). Callers gate this
    behind ``verify`` — the PATH probe depends on the host machine.
    """
    resolved_id = init.resolved_review_provider_id(root)
    if resolved_id is None:
        return None
    if resolved_id != "hunk":
        return Check(
            "review-cli",
            "providers",
            "ok",
            f"review surface: {resolved_id} (hunk CLI not required)",
        )
    if init.hunk_cli_present():
        return Check("review-cli", "providers", "ok", "hunk CLI present")
    return Check(
        "review-cli",
        "providers",
        "warn",
        "hunk CLI not found",
        "",
        f"Install it: {init.HUNK_INSTALL_HINT}, or run 'perk doctor --fix'.",
    )


def _stage_models_check(root: Path) -> Check | None:
    """Validate the per-stage `[models.stages.<id>]` launch overrides (loud-but-non-fatal).

    Returns ``None`` when no per-stage models are configured (keeps a clean repo's `perk doctor`
    output quiet — the common case). A malformed committed TOML → ``warn`` deferring to the config
    check (mirrors ``_providers_check``/``_issues_check``). Otherwise each configured stage id is
    resolved against the registry stage ids and each non-None ``thinking`` against
    ``PI_THINKING_LEVELS``; any unknown stage id or invalid thinking is a single ``warn`` (exit
    stays 0). A broken registry skips the stage-id check (that's the registry check's finding —
    don't double-fail). No ``--fix`` arm: the selection is user-owned config; nothing is
    convergeable. Model strings are free-form and not validated here (pi validates them).
    """
    try:
        stage_models = load_config(root).stage_models
    except (tomllib.TOMLDecodeError, ConfigError):
        return Check(
            "stage-models",
            "repository",
            "warn",
            "stage models not evaluated — config invalid; see the config check",
        )
    if not stage_models:
        return None

    try:
        stage_ids: set[str] | None = registry.load_registry().stage_ids()
    except (registry.RegistryError, FileNotFoundError):
        stage_ids = None  # the registry check owns this finding — don't double-fail

    problems: list[str] = []
    for stage_id, sm in stage_models.items():
        if stage_ids is not None and stage_id not in stage_ids:
            problems.append(f"[models.stages.{stage_id}]: `{stage_id}` is not a registry stage")
        if sm.thinking is not None and sm.thinking not in PI_THINKING_LEVELS:
            problems.append(
                f"[models.stages.{stage_id}]: thinking `{sm.thinking}` is not a valid pi level"
            )

    if not problems:
        return Check(
            "stage-models",
            "repository",
            "ok",
            f"stage models: {sorted(stage_models)}",
        )
    shown = "; ".join(problems[:3])
    if len(problems) > 3:
        shown += f" (+{len(problems) - 3} more)"
    return Check(
        "stage-models",
        "repository",
        "warn",
        f"stage models: {len(problems)} problem(s)",
        shown,
        "Fix .perk/config.toml [models.stages.<id>] (model/thinking).",
    )


def _suspect_thinking_suffix(model: str) -> str | None:
    """A last-colon segment that *looks like* a botched thinking level, or ``None``.

    The shared heuristic behind doctor's ``models`` check (applied to ``[models].default``,
    every ``[models.subagents]`` value, and every ``[models.stages.<id>].model``): an
    **alphabetic-only**
    last-colon segment outside ``PI_THINKING_LEVELS`` is probably a typo'd thinking suffix
    (pi/pi-subagents will treat it as part of the model id). Digit-containing segments are
    skipped (ollama-style tags like ``llama3:70b``/``mixtral:8x7b``), as is the pi-subagents
    ``inherit`` sentinel (no colon — naturally quiet, named here for the contract).
    """
    _, sep, tail = model.rpartition(":")
    if not sep or not tail.isalpha() or tail in PI_THINKING_LEVELS:
        return None
    return tail


def _models_check(root: Path) -> Check | None:
    """Validate the configured model strings' thinking suffixes (loud-but-non-fatal).

    Returns ``None`` when nothing relevant is configured (no ``[models]`` keys, no
    ``[models.subagents]`` values, no ``[models.stages.<id>]`` models — keeps a clean repo's
    `perk doctor` output quiet). A malformed committed TOML or an ill-typed value → ``warn``
    deferring to the
    config check (mirrors ``_stage_models_check``). Two warn-level findings (exit stays 0):
    the ``[models]`` suffix-vs-explicit-``thinking`` conflict (the explicit key wins), and the
    :func:`_suspect_thinking_suffix` heuristic across all three model-string tables. No
    ``--fix`` arm: the values are user-owned config.
    """
    try:
        table: ModelsTable = load_committed_models_table(root)
        config = load_config(root)
    except (tomllib.TOMLDecodeError, ConfigError):
        return Check(
            "models",
            "repository",
            "warn",
            "models not evaluated — config invalid; see the config check",
        )
    subagents = config.subagents
    stage_models = {
        stage_id: sm.model for stage_id, sm in config.stage_models.items() if sm.model is not None
    }
    models_configured = table.default is not None or table.thinking is not None
    if not models_configured and not subagents and not stage_models:
        return None

    problems: list[str] = []
    suffix = table.suffix_thinking()
    if suffix is not None and table.thinking is not None and suffix != table.thinking:
        problems.append(
            f'[models]: default suffix `:{suffix}` conflicts with thinking = "{table.thinking}" '
            "— the explicit key wins"
        )
    candidates: list[tuple[str, str]] = []
    if table.default is not None:
        candidates.append(("[models] default", table.default))
    candidates.extend((f"[models.subagents] {agent}", model) for agent, model in subagents.items())
    candidates.extend(
        (f"[models.stages.{stage_id}]", model) for stage_id, model in stage_models.items()
    )
    for where, model in candidates:
        if (suspect := _suspect_thinking_suffix(model)) is not None:
            problems.append(
                f"{where}: suffix `:{suspect}` is not a pi thinking level — it will be "
                "treated as part of the model id"
            )

    if not problems:
        configured = [
            name
            for name, present in (
                ("[models]", models_configured),
                ("[models.subagents]", bool(subagents)),
                ("[models.stages]", bool(stage_models)),
            )
            if present
        ]
        return Check(
            "models",
            "repository",
            "ok",
            f"models: {', '.join(configured)} ok",
        )
    shown = "; ".join(problems[:3])
    if len(problems) > 3:
        shown += f" (+{len(problems) - 3} more)"
    return Check(
        "models",
        "repository",
        "warn",
        f"models: {len(problems)} problem(s)",
        shown,
        "Fix .perk/config.toml [models] / [models.subagents].",
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
    except (tomllib.TOMLDecodeError, ConfigError):
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
            'Fix .perk/config.toml [issues] — backend must be "github" or "linear".',
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
                'Set [issues] team (the Linear team key, e.g. "ENG") in .perk/config.toml.',
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


def _extension_install_check(root: Path, self_repo: bool) -> Check:
    """Presence + pinned version of perk's ``@mgiles/perk`` npm install (``package``; verify-gated).

    pi installs a missing project-scope ``npm:`` package lazily and **unlocked** at launch, so a
    missing / half-materialized install is a race window. Built from
    ``init.extension_install_status``. Unlike the clone check (where ``absent`` is benign ``info``),
    perk init/doctor *own installing*, so ``absent``/``mismatch`` are
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
            "@mgiles/perk extension not installed",
            detail,
            "perk doctor --fix",
        )
    if status == "mismatch":
        return Check(
            "extension-install",
            "package",
            "fail",
            "@mgiles/perk install version drift",
            detail,
            "perk doctor --fix",
        )
    if status == "present":
        return Check(
            "extension-install", "package", "ok", "@mgiles/perk installed at the pinned version"
        )
    return Check(
        "extension-install", "package", "warn", "@mgiles/perk install not verified", detail
    )


def _cli_version_check(root: Path) -> Check:
    """Report-only running-CLI-vs-repo-pin comparison (``package``; warn, never fail).

    The version-parity axis split: ``settings-wiring`` = wired npm pin vs ``__version__``;
    ``extension-install`` = installed npm vs pin; ``required-perk-version`` (managed) = file
    drift + ``--fix`` (reconverges the pin to the running CLI); ``cli-version`` = the running
    CLI vs the repo's committed requirement — warn-only because the repair may be "upgrade the
    CLI", which doctor cannot do. On a mismatch both the managed fail and this warn fire,
    deliberately (two remedies, two directions).
    """
    try:
        pin = init.read_version_pin(root)
    except OSError as exc:
        # No silent pass: an unreadable pin reports the reason (still never `fail` — the
        # managed `required-perk-version` check owns the loud unverifiable fail).
        return Check(
            "cli-version",
            "package",
            "warn",
            ".perk/required-perk-version not readable",
            str(exc),
        )
    if pin is None:
        return Check(
            "cli-version",
            "package",
            "info",
            "no .perk/required-perk-version pin",
            "presence/drift owned by the required-perk-version managed check — run `perk init`",
        )
    if pin == __version__:
        return Check(
            "cli-version",
            "package",
            "ok",
            f"perk CLI {__version__} matches the repo's required version",
        )
    return Check(
        "cli-version",
        "package",
        "warn",
        f"perk CLI {__version__} != repo required {pin}",
        "",
        "Upgrade perk (e.g. `uv tool upgrade perk`) to match the repo, or re-run `perk init` / "
        "`perk doctor --fix` to reconverge the pin to this CLI.",
    )


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
        installed (``bindings.is_skill_installed`` — strict on the `.agents/skills/` delivery
        read path, the only path warm injection reads). Consumers: a plain ``fail``. The
        self-repo classifies further (``_classify_self_repo_missing``): the committed ``skills/``
        layout is never an ok-level substitute — deliverable-but-stale is a ``fail``, the
        pre-merge first appearance a ``warn`` (visible, not fatal, never silently green).
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
        name for name in init.MANAGED_SKILL_NAMES if not bindings.is_skill_installed(root, name)
    ]
    if missing and self_repo:
        return _classify_self_repo_missing(root, missing)
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


def _classify_self_repo_missing(root: Path, missing: list[str]) -> Check:
    """Classify the self-repo's undelivered managed skills — never an ok, never silently green.

    The `.agents/skills/` delivery read path is the only "delivered" state; the committed
    ``skills/`` layout distinguishes only *which failure mode* a missing delivery is:

    - committed AND present on the skills source ref as locally known (``origin/<ref>``, ONE
      ``git ls-tree`` call — shelled only when something is missing) → **fail**: the delivered
      set is stale and a re-sync fixes it now (the dangling-pointer R3 case);
    - committed but NOT on the local ``origin/<ref>`` → **warn**: the documented pre-merge first
      appearance — `skills update --sync` resolves against the real remote, so the skill is
      deliverable only after merge + re-sync;
    - not committed anywhere → **fail** (same as a consumer tree).

    Known limitation (accepted, degrades safely): the probe reads the LOCAL remote-tracking ref,
    which can lag — a merged-but-unfetched skill misclassifies stale→fail down to the
    first-appearance→warn arm. Never a false fail and never silent; the warn text carries the
    fetch remediation. A ``GitError`` on the probe degrades to ``warn`` naming every missing
    skill (no silent pass).
    """
    committed = [
        n
        for n in missing
        if (root / bindings.SELF_REPO_SKILLS_DIR / n / bindings.SKILL_FILENAME).is_file()
    ]
    absent = [n for n in missing if n not in set(committed)]
    stale: list[str] = []
    first: list[str] = []
    if committed:
        # `origin/<ref>` is the local remote-tracking view of the perk skills source ref the
        # fragment declares (`PERK_SKILL_SOURCE.ref`) — the ref `skills update --sync` resolves.
        source_ref = f"origin/{init.PERK_SKILL_SOURCE.ref}"
        try:
            on_ref = set(git.ls_tree_names(root, source_ref, "skills/"))
        except git.GitError as exc:
            return Check(
                "skills-delivery",
                "skills",
                "warn",
                "skills delivery not fully verified",
                f"not delivered: {', '.join(missing)}; "
                f"source-ref probe ({source_ref}) not evaluated: {exc}",
                "Run 'perk doctor --fix'.",
            )
        stale = [n for n in committed if f"skills/{n}" in on_ref]
        first = [n for n in committed if f"skills/{n}" not in on_ref]
    if stale or absent:
        parts: list[str] = []
        if stale:
            parts.append(
                f"delivered set stale — .agents/skills/ lacks {', '.join(stale)} "
                f"present on origin/{init.PERK_SKILL_SOURCE.ref}"
            )
        if absent:
            parts.append(f"not committed anywhere: {', '.join(absent)}")
        if first:
            parts.append(
                f"pre-merge first appearance (deliverable after merge): {', '.join(first)}"
            )
        return Check(
            "skills-delivery",
            "skills",
            "fail",
            f"{len(missing)} perk skill(s) not delivered",
            "; ".join(parts),
            "Run 'perk doctor --fix' (skills update --sync).",
        )
    return Check(
        "skills-delivery",
        "skills",
        "warn",
        f"{len(first)} skill(s) pending first delivery (pre-merge)",
        "pre-merge first appearance (or an unfetched merge) — warm injection reads only "
        f".agents/skills/: {', '.join(first)}",
        "Deliverable after merge + re-sync ('perk doctor --fix'); fetch first if this already "
        "merged.",
    )


def _repo_skills_check(root: Path) -> Check:
    """The repo-authored-skills manifest-fragment health check (group `skills`, verify-gated).

    Reuses `init.converge_repo_skills_manifest` in dry-run (`apply=False`) — init and doctor share
    one desired-state SSOT — so it surfaces the same structured diagnostics the fragment
    convergence produces. Report-only (no `--fix` here; `run_doctor`'s fix path re-runs the
    gesture with `apply=True`). First match wins:

    (a) structural `errors` (bad SKILL.md / source collision / no GitHub remote) → **`fail`**,
        consistent with skills-delivery being fail-level;
    (b) on-disk fragment drift (`changes`, including a stale fragment to prune) → **`fail`**;
    (c) untracked `warnings` (an uncommitted SKILL.md) → **`warn`**;
    (d) declared+converged skills → **`ok`**;
    (e) no repo-authored skills → **`ok`**.
    """
    conv = init.converge_repo_skills_manifest(root, apply=False)
    manifest = conv.manifest
    if manifest.errors:
        return Check(
            "repo-skills",
            "skills",
            "fail",
            "repo-authored skills invalid",
            "; ".join(manifest.errors),
            "Fix the SKILL.md / source collision, then re-run 'perk init'.",
        )
    if conv.changes:
        return Check(
            "repo-skills",
            "skills",
            "fail",
            "repo-skills-manifest drift",
            "; ".join(conv.changes),
            "Run 'perk doctor --fix' (or 'perk init').",
        )
    if manifest.warnings:
        return Check(
            "repo-skills",
            "skills",
            "warn",
            "repo-authored skill(s) not committed",
            "; ".join(manifest.warnings),
        )
    if manifest.skills:
        return Check(
            "repo-skills",
            "skills",
            "ok",
            f"{len(manifest.skills)} repo-authored skill(s) declared",
        )
    return Check("repo-skills", "skills", "ok", "no repo-authored skills")


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
    """Handoff-blob integrity. (The `.perk/workflow/` *layout* is the workflow-dir convergence.)"""
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


# The pinned status vocabulary order for the artifact-health summary line.
_HEALTH_STATUS_ORDER: tuple[HealthStatus, ...] = (
    "up-to-date",
    "not-installed",
    "locally-modified",
    "changed-upstream",
    "state-missing",
)


def _artifact_health_check(root: Path, self_repo: bool) -> tuple[tuple[ArtifactHealth, ...], Check]:
    """The report-only artifact-health classification (group ``state``, never ``fail``).

    Offline (pure filesystem + bundled resources), so NOT verify-gated. Diagnostic only: the
    dry-run managed convergence stays authoritative for pass/fail — a drifted artifact already
    fails its managed check, and warns never move ``report.healthy`` / the exit code. The repair
    is the existing convergence + the ``--fix`` state write (no dedicated fix arm).
    """
    state_error: managed_state.ManagedStateError | None = None
    try:
        try:
            state = managed_state.load_managed_state(root)
        except managed_state.ManagedStateError as exc:
            state = None
            state_error = exc
        rows = managed_state.artifact_health(root, self_repo=self_repo, state=state)
    except OSError as exc:
        # No silent pass, no crash: an unreadable artifact degrades to one warn with the reason.
        return (), Check(
            "artifact-health", "state", "warn", "artifact health not evaluated", str(exc)
        )
    if state_error is not None:
        return rows, Check(
            "artifact-health",
            "state",
            "warn",
            ".perk/managed-state.toml malformed",
            str(state_error),
            "perk doctor --fix",
        )
    drifted = [row for row in rows if row.status != "up-to-date"]
    if drifted:
        counts = {
            status: sum(1 for r in rows if r.status == status) for status in _HEALTH_STATUS_ORDER
        }
        summary = ", ".join(
            f"{counts[status]} {status}" for status in _HEALTH_STATUS_ORDER if counts[status]
        )
        return rows, Check(
            "artifact-health",
            "state",
            "warn",
            f"artifact health: {summary}",
            "; ".join(f"{row.path} ({row.key}): {row.status}" for row in drifted),
            "perk doctor --fix",
        )
    if state is None:
        return rows, Check(
            "artifact-health",
            "state",
            "info",
            f"{len(rows)} managed artifacts up-to-date; state not yet recorded",
            "run 'perk init' or 'perk doctor --fix' to record .perk/managed-state.toml",
        )
    return rows, Check(
        "artifact-health", "state", "ok", f"{len(rows)} managed artifacts up-to-date"
    )


# The simple active root mirrors `doctor --fix` can safely relocate from a legacy `.pi/workflow/`
# to `.perk/workflow/` (target-absent only). Disposable scratch (run dirs, handoffs, markers) is
# never moved — it is gitignored cache the user may delete at leisure.
_LEGACY_WORKFLOW_MIRRORS: tuple[str, ...] = ("plan-ref.json", "agent-session.json")


def _legacy_workflow_check(root: Path) -> Check:
    """Flag a stale `.pi/workflow/` the move to `.perk/workflow/` left behind, but only when
    ``perk doctor --fix`` has something actionable to do (mirrors the legacy-workflow migration):

    - a **tracked** legacy `.pi/workflow/.gitkeep` (the old committed layout sentinel), or
    - a movable active mirror (`plan-ref.json`/`agent-session.json`) present at the legacy path
      while the `.perk/workflow/` target is absent.

    Pure disposable scratch (run dirs, handoffs, markers) is deliberately **not** flagged — it is
    gitignored cache the user may delete at leisure, and flagging it forever would be noise that
    never converges to ``ok``. Remediation: ``perk doctor --fix``.
    """
    legacy = root / ".pi/workflow"
    target = cache.workflow_dir(root)
    actionable: list[str] = []
    if git.is_tracked(root, ".pi/workflow/.gitkeep"):
        actionable.append(".gitkeep (tracked)")
    for name in _LEGACY_WORKFLOW_MIRRORS:
        if (legacy / name).is_file() and not (target / name).exists():
            actionable.append(name)
    if actionable:
        return Check(
            "legacy-workflow",
            "state",
            "warn",
            "legacy .pi/workflow/ cache present",
            ", ".join(actionable),
            "perk doctor --fix",
        )
    return Check("legacy-workflow", "state", "ok", "no legacy .pi/workflow/ cache")
