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
            f"footer={resolved.footer.id}, web={resolved.web.id})",
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


def _review_cli_check(root: Path) -> Check:
    """Presence probe for the external ``hunk`` CLI (warn-level, unconditional).

    Always probes PATH — the hunk CLI converges unconditionally (it is the review surface
    ``/pr-review-terminal`` drives, not a config consequence), so the check reads no
    config. Present is ``ok``, absent is a **warn** carrying the manual install hint (exit
    stays 0; ``perk doctor --fix`` retries the install). Callers still gate this behind
    ``verify`` — the PATH probe depends on the host machine (keeps ``verify=False`` check
    lists byte-stable). The ``root`` parameter is unused but retained for check-family
    uniformity and signature stability.
    """
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


# The pi-owned install dir of the unpinned `npm:pi-subagents` BORROWED_PACKAGES entry
# (pi lazy-installs it under `.pi/npm/node_modules/` at launch).
_SUBAGENTS_PACKAGE_DIRNAME = "pi-subagents"

# The pi-subagents version perk's guidance was source-read against; bumped only on a
# deliberate re-verify of the guidance (never a pin — the package stays unpinned).
_SUBAGENTS_GUIDANCE_VERIFIED_VERSION = "0.43.0"

# One row per surface expectation perk's subagent guidance assumes:
# (label, relative file path in the installed package, required substrings). Probes are
# file-scoped with NO tree-wide fallback — a moved/renamed file IS a surface change worth a
# re-verify (the early-warning posture).
_SUBAGENT_COMPAT_PROBES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("workflowScript orchestration", "src/extension/schemas.ts", ("workflowScript",)),
    ("outputSchema param", "src/extension/schemas.ts", ("outputSchema",)),
    ("structuredOutput results", "src/shared/types.ts", ("structuredOutput",)),
    ("subagent_wait async wait tool", "src/runs/background/wait-tool.ts", ('"subagent_wait"',)),
    (
        "supervisor channel",
        "src/intercom/native-supervisor-channel.ts",
        ('"contact_supervisor"', '"subagent_supervisor_request"', "triggerTurn"),
    ),
    (
        "workflowScript-only public execution",
        "src/extension/public-execution.ts",
        ("Direct execution was removed",),
    ),
    (
        "v1 extension RPC events",
        "src/extension/rpc.ts",
        ("subagents:rpc:v1:request", "subagents:rpc:v1:ready", "subagents:rpc:v1:reply"),
    ),
    (
        "retained children",
        "src/runs/background/retained-children.ts",
        ("listRetainedChildren",),
    ),
    (
        "statement-body explicit-return scripts",
        "src/workflows/scripted-workflow.ts",
        ("(async () => {",),
    ),
    (
        "retained-child resume",
        "src/workflows/scripted-workflow.ts",
        ("resume and agent are mutually exclusive",),
    ),
)


def _installed_subagents_version(pkg_dir: Path) -> str | None:
    """The ``version`` of the installed pi-subagents package, or ``None``.

    Best-effort, never raises: ``None`` when the file is absent or the JSON / ``version`` is
    unreadable. Mirrors ``installed_perk_version``'s posture (TypeError: valid JSON that is a
    non-dict — indexing it raises, but an unparseable version still means "unverifiable").
    """
    try:
        return json.loads((pkg_dir / "package.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _subagent_compat_check(root: Path) -> Check:
    """Informational pi-subagents surface-compatibility probe (``package``; warn, never fail).

    perk's subagent orchestration guidance (the pr-review door prompts, contracts.md's streaming
    fan-out spec, docs/learned/pi/subagents.md) assumes specific pi-subagents surfaces, but the
    package is deliberately **unpinned** — so this check is the early-warning tripwire: it reads
    the installed version and probes the installed source for the assumed surfaces, warning
    **loudly** on divergence without ever failing (``report.healthy`` and the exit code are
    never affected). No pin, no enforced range, no ``--fix`` arm. Probes are substring presence
    only — mechanics beyond these markers stay source-read-derived.
    """
    pkg_dir = init.consumer_npm_install_root(root) / "node_modules" / _SUBAGENTS_PACKAGE_DIRNAME
    if not pkg_dir.is_dir():
        # No silent pass: the reason compatibility was not evaluated is carried.
        return Check(
            "subagent-compat",
            "package",
            "info",
            "pi-subagents not installed — compatibility not evaluated",
            "pi lazy-installs the unpinned npm:pi-subagents borrowed package at launch "
            "(.pi/npm/node_modules/pi-subagents)",
        )

    version = _installed_subagents_version(pkg_dir)
    divergences: list[str] = []
    for label, relpath, required in _SUBAGENT_COMPAT_PROBES:
        probe_file = pkg_dir / relpath
        try:
            content = probe_file.read_text(encoding="utf-8")
        except OSError:
            divergences.append(f"{label}: {relpath} missing")
            continue
        missing = [marker for marker in required if marker not in content]
        if missing:
            divergences.append(f"{label}: marker(s) {', '.join(missing)} absent from {relpath}")
    if version is None:
        divergences.append("package.json version unreadable")

    if divergences:
        return Check(
            "subagent-compat",
            "package",
            "warn",
            f"pi-subagents {version or 'version unreadable'} — installed surface diverges "
            f"from perk's guidance ({len(divergences)} expectation(s) unmet)",
            "; ".join(divergences),
            "Informational (no pin): re-verify perk's subagent guidance against the installed "
            "pi-subagents source and reconcile docs/learned/pi/subagents.md, "
            "shared/contracts.md's streaming fan-out spec, and the pr-review door prompts.",
        )

    detail = (
        "probed surfaces: workflowScript + outputSchema/structuredOutput + subagent_wait + "
        "supervisor channel (contact_supervisor, subagent_supervisor_request, triggerTurn) + "
        "workflowScript-only public execution + v1 RPC events (subagents:rpc:v1:*) + "
        "retained children/resume + statement-body explicit-return scripts; "
        "report-only — the package stays unpinned"
    )
    if version != _SUBAGENTS_GUIDANCE_VERIFIED_VERSION:
        detail += (
            f"; installed {version} != guidance-verified "
            f"{_SUBAGENTS_GUIDANCE_VERIFIED_VERSION} — mechanics beyond these markers are "
            "source-read-derived; re-verify perk's subagent guidance on bumps"
        )
    return Check(
        "subagent-compat",
        "package",
        "ok",
        f"pi-subagents {version} — installed orchestration surface matches perk's guidance",
        detail,
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


# The pi resource kinds an object-form `packages` entry (or a top-level override array) can
# filter (pi docs/packages.md). Shared by both `_resource_overrides_check` arms.
_RESOURCE_OVERRIDE_KEYS = ("extensions", "skills", "prompts", "themes")


def _resource_overrides_check(root: Path, self_repo: bool) -> Check:
    """Report-only probe for pi resource overrides touching perk's resources (``package``).

    pi's ``pi config -l`` flow lets a user filter a package's resources by rewriting its
    ``packages`` entry to object form, or disable resources via ``-``/``!`` patterns in the
    top-level override arrays. Both are supported pi surfaces — but filtering **perk's own
    extension** off silently breaks every interactive stage session (no stage tools, no footer,
    no gates), so doctor names it. **Warn at worst, never fail, no ``--fix`` arm**: the only
    conceivable repair would strip user-chosen filters, which is hostile — the remediation tells
    the operator what to review instead. Two arms:

    - **Object-form perk entry:** any dict ``packages`` entry whose identity is perk's own
      (`@mgiles/perk`, or ``..`` in the self-repo), reported with its filter keys.
    - **Disable-pattern sweep:** any ``-``/``!``-prefixed entry in a top-level override array
      whose body mentions ``@mgiles/perk`` or a perk skill name. An honest **substring
      heuristic** — perk does not reimplement pi's filter-pattern semantics, so a pattern that
      matches perk resources without naming them escapes this sweep (accepted).

    Missing settings / no overrides → ``ok``. Malformed settings → ``warn`` deferring to the
    settings-wiring check (which owns that finding — don't double-fail).
    """
    settings_path = root / ".pi" / "settings.json"
    if not settings_path.is_file():
        return Check("resource-overrides", "package", "ok", "no perk resource overrides")
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        settings = None
    if not isinstance(settings, dict):
        return Check(
            "resource-overrides",
            "package",
            "warn",
            "resource overrides not evaluated — settings invalid; see the settings-wiring check",
        )

    problems: list[str] = []
    perk_identity = init._npm_name(init.NPM_PACKAGE)
    packages = settings.get("packages")
    if isinstance(packages, list):
        for entry in packages:
            if not isinstance(entry, dict):
                continue
            identity = init._package_identity(entry)
            if identity != perk_identity and not (self_repo and identity == ".."):
                continue
            filters = ", ".join(
                f"{key}: {json.dumps(value)}"
                for key, value in entry.items()
                if key in _RESOURCE_OVERRIDE_KEYS
            )
            problems.append(
                f"perk's own packages entry is object-form ({filters or 'no filter keys'}) — "
                "filtering perk's extension breaks every stage session"
            )
    perk_bodies = ("@mgiles/perk", *init.PERK_SKILLS)
    for key in _RESOURCE_OVERRIDE_KEYS:
        overrides = settings.get(key)
        if not isinstance(overrides, list):
            continue
        for pattern in overrides:
            if not isinstance(pattern, str) or not pattern.startswith(("-", "!")):
                continue
            body = pattern[1:]
            if any(name in body for name in perk_bodies):
                problems.append(f"{key} override `{pattern}` disables a perk resource")

    if not problems:
        return Check("resource-overrides", "package", "ok", "no perk resource overrides")
    shown = "; ".join(problems[:3])
    if len(problems) > 3:
        shown += f" (+{len(problems) - 3} more)"
    return Check(
        "resource-overrides",
        "package",
        "warn",
        f"resource overrides: {len(problems)} problem(s)",
        shown,
        "Review/remove the overrides via `pi config -l` (or edit .pi/settings.json), or restore "
        "perk's pinned string packages entry.",
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

    The `.agents/skills/` delivery read path is the only "delivered" state. The committed
    ``skills/`` layout classification applies to **perk-authored names only** (``PERK_SKILLS``);
    a required external skill (``REQUIRED_EXTERNAL_SKILLS`` — upstream sources, never in the
    committed ``skills/`` dir) can never be "committed" here, so a missing one fails plainly
    instead of misreading as "not committed anywhere". For the perk-authored names:

    - committed AND present on the skills source ref as locally known (``origin/<ref>``, ONE
      ``git ls-tree`` call — shelled only when a perk-authored name is both missing and
      committed) → **fail**: the delivered set is stale and a re-sync fixes it now (the
      dangling-pointer R3 case);
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
    perk_authored = set(init.PERK_SKILLS)
    external = [n for n in missing if n not in perk_authored]
    own = [n for n in missing if n in perk_authored]
    committed = [
        n
        for n in own
        if (root / bindings.SELF_REPO_SKILLS_DIR / n / bindings.SKILL_FILENAME).is_file()
    ]
    absent = [n for n in own if n not in set(committed)]
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
    if stale or absent or external:
        parts: list[str] = []
        if stale:
            parts.append(
                f"delivered set stale — .agents/skills/ lacks {', '.join(stale)} "
                f"present on origin/{init.PERK_SKILL_SOURCE.ref}"
            )
        if absent:
            parts.append(f"not committed anywhere: {', '.join(absent)}")
        if external:
            parts.append(f"required external skill(s) not delivered: {', '.join(external)}")
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
    gesture with `apply=True`). Fail arms first-match-win; the warn tier aggregates every
    advisory part into one check:

    (a) structural `errors` (bad SKILL.md / source collision / no GitHub remote) → **`fail`**,
        consistent with skills-delivery being fail-level;
    (b) on-disk fragment drift (`changes`, including a stale fragment to prune) → **`fail`**;
    (c) advisory parts — untracked `warnings` (an uncommitted SKILL.md), skills with no
        ``stages:`` declaration (exposed to every stage launch, contracts.md §8.39), and declared
        stage ids that are not registry stages (silently inert) → one **`warn`** joining them;
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
    warn_parts = list(manifest.warnings)
    undeclared = [s.name for s in manifest.skills if s.stages_field is None]
    if undeclared:
        warn_parts.append(
            f"{len(undeclared)} repo-authored skill(s) don't declare stages: "
            f"(exposed to every stage launch): {', '.join(undeclared)}"
        )
    try:
        stage_ids: set[str] | None = registry.load_registry().stage_ids()
    except (registry.RegistryError, FileNotFoundError):
        stage_ids = None  # the registry check owns this finding — don't double-warn
    if stage_ids is not None:
        for skill in manifest.skills:
            declared = skill.stages_field
            if not isinstance(declared, frozenset):
                continue
            unknown = sorted(declared - stage_ids)
            if unknown:
                warn_parts.append(
                    f"{skill.name}: stages: id(s) {', '.join(unknown)} are not registry "
                    "stages (inert)"
                )
    if warn_parts:
        return Check(
            "repo-skills",
            "skills",
            "warn",
            "repo-authored skill notes",
            "; ".join(warn_parts),
            "Declare stages: in the SKILL.md frontmatter (a stage-id list, all, or []).",
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
