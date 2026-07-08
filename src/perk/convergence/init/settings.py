"""Package + settings convergence: the static/provider/linear package wiring + identity helpers."""

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from perk import __version__
from perk.cli.ensure import UserFacingCliError
from perk.substrate.config import (
    ConfigError,
    load_committed_compaction,
    load_committed_issues_backend,
    load_committed_models,
    load_config,
)
from perk.substrate.providers import ProviderSet, load_providers, resolve_providers

# Legacy `git:` identity for perk's own extension. The git-clone lifecycle is retired (the npm
# install path supersedes it); `_converge_settings` strips a repo's legacy `git:` perk entry by
# this identity when flipping to the pinned npm wiring, and `consumer_git_clone_root` derives the
# orphaned-clone path so `doctor --fix` can migrate a former git-clone consumer forward.
GIT_PACKAGE = "git:github.com/mattgiles/perk"


def consumer_git_clone_root(repo_root: Path) -> Path:
    """The root of pi's git-package clone for perk, derived from ``GIT_PACKAGE``.

    pi clones a ``git:`` package to ``.pi/git/<host>/<path>`` (docs/packages.md). Deriving the
    path from ``GIT_PACKAGE`` (rather than hardcoding segments) keeps every consumer of the clone
    location — the run-worker entrypoint resolver — in lockstep with the package URL, so a URL
    change cannot silently desync them.
    """
    remainder = GIT_PACKAGE.removeprefix("git:")
    clone = repo_root / ".pi" / "git"
    for segment in remainder.split("/"):
        clone = clone / segment
    return clone


# perk's own extension is now wired as an exact version-pinned npm spec. `_perk_npm_entry()`
# mirrors the PyPI install pin SSOT in `workflow_artifacts.py` (both pin `perk.__version__`).
NPM_PACKAGE = "npm:@mgiles/perk"


def _perk_npm_entry() -> str:
    """The pinned npm spec for perk's own extension (`npm:@mgiles/perk@{__version__}`)."""
    return f"{NPM_PACKAGE}@{__version__}"


# Borrowed default set (the crossover scaffolding). Independent npm: entries; Pi
# auto-installs them on the next launch. `@tombell/pi-plan` was retired
# (perk now owns plan mode end-to-end via the tool-gating primitive + `/plan`).
# `@juicesharp/rpiv-todo` was retired (perk now owns implement-progress via
# perk-owned checkpoints, the `perk:checkpoint` entry seeded from the plan body).
# `pi-subagents` is the borrowed *spawned delegation engine*: perk takes the
# engine (the `subagent` tool + spawn/handoff machinery) and owns the workflow-specific
# agent definitions itself (in `.pi/agents/`, scaffolded by init); the engine is
# `ctx.hasUI`-clean (children run `--mode json -p`).
# `pi-web-access` is NO LONGER borrowed: it became the `web` seam's `default: true` provider.
# It is now converged via the PROVIDER path (`_converge_provider_packages`), not this
# static borrowed set — the novelty being that this is the first seam whose reference/default
# provider has a NON-NULL `package` (perk owns no native web-research implementation, so the
# behavior-preserving default is itself a foreign npm package). The committed `.pi/settings.json`
# `npm:pi-web-access` entry is UNCHANGED but RECLASSIFIED from borrowed to provider-managed: a
# default-config repo still installs it (via the provider path), and deselecting `web` away from
# `pi-web-access` now REMOVES it like any other provider package (two-directional convergence).
# `@tombell/pi-status` was retired — pi's `setFooter` is a single last-wins
# slot, and pi-status's `session_start` footer replaced perk's charter-D2 footer (perk owns
# the footer wholesale).
BORROWED_PACKAGES = [
    "npm:@tombell/pi-diff",
    "npm:pi-subagents",
]

# `pi-mono-linear` is the borrowed *Linear-tools Pi extension*, converged only when the repo
# selects the linear issue backend (`[issues] backend = "linear"` in committed .perk/config.toml) —
# two-directional like provider packages: added on select, removed on deselect (hand-adding it
# without selecting linear is unsupported). Unpinned plain-string entry (the borrowed-set
# convention); its bundled `linear` skill is accepted wholesale (no package_filter).
LINEAR_PACKAGE = "npm:pi-mono-linear"


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
    # ``entry`` narrows only to ``dict[Unknown, Unknown]`` (key type is lost), so iterate items
    # to read ``source`` instead of ``.get`` — equivalent, and accepted without a cast.
    if isinstance(entry, dict):
        spec: object = next((v for key, v in entry.items() if key == "source"), None)
    else:
        spec = entry
    if not isinstance(spec, str):
        return None
    return _npm_name(spec) or _git_identity(spec) or spec


def _desired_packages(self_repo: bool) -> list[str]:
    own = ".." if self_repo else _perk_npm_entry()
    return [own, *BORROWED_PACKAGES]


def _merge_static_packages(
    packages: list[object], desired: list[str]
) -> tuple[list[object], list[str], list[str]]:
    """Merge the static perk+borrowed package set; returns (packages, added, updated).

    Append-merges the borrowed/npm/local entries (dedup by identity) AND reconciles perk's own
    `npm:@mgiles/perk` **version pin** *forward*: when perk's own npm identity already exists as a
    **string-form** entry whose full spec differs from the desired pin (e.g. a stale
    `npm:@mgiles/perk@0.0.0`), the entry is **rewritten in place** (list position preserved) to the
    desired pinned spec instead of being skipped; any extra string entries sharing that identity
    are dropped so the repo converges to a single canonical perk entry. Only perk's own identity
    is version-reconciled — borrowed npm packages (`BORROWED_PACKAGES`) are unpinned and stay
    **append-only** (never version-reconciled), distinguished by comparing the entry's `_npm_name`
    identity to `_npm_name(NPM_PACKAGE)`. A user's own packages are never in ``desired`` and stay
    append-only/untouched. Object-form entries are left alone (perk never writes object-form for
    its own package — Invariant 2; a hand-written object-form perk entry is a documented
    limitation). Idempotent: once at the desired pin, the entry equals it → no change.
    """
    have_local = {p for p in packages if isinstance(p, str) and not p.startswith(("npm:", "git:"))}
    have_npm = {n for n in (_npm_name(p) for p in packages if isinstance(p, str)) if n}
    perk_npm_identity = _npm_name(NPM_PACKAGE)

    added: list[str] = []
    updated: list[str] = []
    for want in desired:
        if want.startswith("npm:"):
            name = _npm_name(want)
            if name is None:
                continue
            if name == perk_npm_identity and name in have_npm:
                # perk's own identity present — reconcile the version pin forward (string-form
                # entries only), collapsing any duplicates so the repo converges to one entry.
                matches = [
                    (i, entry)
                    for i, entry in enumerate(packages)
                    if isinstance(entry, str) and _npm_name(entry) == name
                ]
                if matches:
                    first, existing = matches[0]
                    if existing != want:
                        packages[first] = want
                        updated.append(f"updated {existing} -> {want}")
                    # Drop any further duplicate string entries for this identity (high index
                    # first so earlier indices stay valid).
                    for i, dup in reversed(matches[1:]):
                        packages.pop(i)
                        updated.append(f"removed duplicate {dup}")
                continue
            if name in have_npm:
                continue
            packages.append(want)
            have_npm.add(name)
        else:
            if want in have_local:
                continue
            packages.append(want)
            have_local.add(want)
        added.append(want)
    return packages, added, updated


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

    # Migration: strip the legacy `git:` perk entry written by earlier perk init runs (any ref);
    # _merge_static_packages then adds the pinned npm entry. A user's unrelated `git:` packages
    # (different identity) are preserved.
    packages = [p for p in packages if not (isinstance(p, str) and _git_identity(p) == GIT_PACKAGE)]

    packages, added, updated = _merge_static_packages(packages, _desired_packages(self_repo))

    # Provider-driven two-directional wiring. Composes on top of the static layer
    # within this same body, so it stays inside the `settings-wiring` ManagedConvergence (D5 SSOT
    # — doctor dry-runs/fixes it for free). perk's own package is never filtered (Invariant 2).
    packages, provider_changes = _converge_provider_packages(root, packages)
    added.extend(provider_changes.added)

    # Linear-selection two-directional wiring. Composes within this same body, so it
    # rides the `settings-wiring` ManagedConvergence — doctor dry-runs/fixes it for free.
    packages, linear_changes = _converge_linear_package(root, packages)
    added.extend(linear_changes.added)

    settings["packages"] = packages
    # Converge pi's interactive auto-compaction from committed `[compaction]` (composes within
    # this same body, so it flows into the no-op short-circuit and stays inside `settings-wiring`
    # — doctor dry-runs/fixes it for free).
    compaction_changes = _converge_compaction(root, settings)
    # Converge pi's default model/thinking from committed `[models]` (same composition: flows
    # into the no-op short-circuit and rides the `settings-wiring` ManagedConvergence).
    models_changes = _converge_models(root, settings)
    # Converge the borrowed pi-subagents engine's builtin suppression (same composition).
    subagents_changes = _converge_subagents(settings)
    new_text = json.dumps(settings, indent=2) + "\n"
    if new_text == old_text:
        return []
    if apply:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(new_text, encoding="utf-8")

    parts: list[str] = []
    if added:
        parts.append(f"added {', '.join(added)}")
    removed = [*provider_changes.removed, *linear_changes.removed]
    if removed:
        parts.append(f"removed {', '.join(removed)}")
    parts.extend(updated)
    parts.extend(compaction_changes)
    parts.extend(models_changes)
    parts.extend(subagents_changes)
    return [f".pi/settings.json: {'; '.join(parts)}" if parts else ".pi/settings.json: normalized"]


def _converge_compaction(root: Path, settings: dict[str, object]) -> list[str]:
    """Merge committed `[compaction]` over `settings["compaction"]` (write-when-present).

    Reads **committed** `.perk/config.toml` only (no local overlay; D2). When the parsed table is
    non-empty, its mapped keys are merged over any existing `compaction` dict (perk-specified
    keys win; unrelated hand-added keys survive; unspecified keys are left to pi's defaults). When
    empty/absent, `settings` is left untouched (perk cannot prove ownership of a bare `compaction`
    key, so removal is unsafe). A malformed-TOML or ill-typed-value error defers to the config
    check (treated as empty here, mirroring `_converge_provider_packages`). Returns a
    human-readable change fragment list, or `[]` when nothing was written.
    """
    try:
        desired = load_committed_compaction(root)
    except (tomllib.TOMLDecodeError, ConfigError):
        desired = {}
    if not desired:
        return []
    existing = settings.get("compaction")
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged.update(desired)
    settings["compaction"] = merged
    fragment = ", ".join(f"{key}={value}" for key, value in desired.items())
    return [f"compaction: {fragment}"]


def _converge_models(root: Path, settings: dict[str, object]) -> list[str]:
    """Write committed `[models]` over pi's top-level default-model settings (write-when-present).

    Reads **committed** `.perk/config.toml` only (no local overlay), mirroring
    ``_converge_compaction`` with one structural difference: the mapped keys
    (``defaultProvider``/``defaultModel``/``defaultThinkingLevel``) are **top-level scalars** in
    `settings.json`, not a nested dict — so write-when-present is per-key assignment and an
    empty desired mapping touches nothing (leave-when-absent: perk cannot prove ownership of a
    bare settings key, so removal is unsafe). A malformed-TOML or ill-typed-value error defers
    to the config check (treated as empty here — init still converges everything else; the
    hard ``ConfigError`` surfaces via doctor's config check). Returns a human-readable change
    fragment list, or ``[]`` when nothing was written.
    """
    try:
        desired = load_committed_models(root)
    except (tomllib.TOMLDecodeError, ConfigError):
        desired = {}
    if not desired:
        return []
    for key, value in desired.items():
        settings[key] = value
    fragment = ", ".join(f"{key}={value}" for key, value in desired.items())
    return [f"models: {fragment}"]


def _converge_subagents(settings: dict[str, object]) -> list[str]:
    """Merge `subagents.disableBuiltins: true` into `settings` (constant desired, no config read).

    The deliberate divergence from the ``_converge_compaction``/``_converge_models``
    write-when-present siblings: perk borrows pi-subagents as the delegation *engine only* and
    delivers its own ``perk.*`` agent defs, so the builtin agents are model-facing noise in
    every perk repo — builtins-off is perk's posture everywhere, with no ``.perk/config.toml``
    involvement. The sanctioned re-enable is a project-settings per-agent
    ``subagents.agentOverrides.<name>.disabled: false`` entry, which pi-subagents consults
    *before* the bulk flag and which this merge never touches (only the ``disableBuiltins`` key
    is perk-owned; sibling keys survive byte-for-byte). Delta-gated because the desired value is
    a constant: an ungated fragment would append a phantom "subagents: …" change line to every
    future run that changes anything else, violating the genuine-delta rule for
    ``report.changes``. Idempotency on a fully-converged repo remains the ``new_text ==
    old_text`` short-circuit in ``_converge_settings``.
    """
    existing = settings.get("subagents")
    if isinstance(existing, dict):
        # ``existing`` narrows only to ``dict[Unknown, Unknown]`` (key type is lost), so iterate
        # items to read ``disableBuiltins`` instead of ``.get`` — equivalent, cast-free.
        current = next((v for key, v in existing.items() if key == "disableBuiltins"), None)
        if current is True:
            return []
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged["disableBuiltins"] = True
    settings["subagents"] = merged
    return ["subagents: disableBuiltins=true"]


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

    # Guard a malformed/ill-typed config.toml: defer surfacing to the config check (mirrors
    # _bindings_check).
    try:
        selection = load_config(root).providers
    except (tomllib.TOMLDecodeError, ConfigError):
        selection = {}
    resolved = resolve_providers(selection, provider_set)

    desired: dict[str, dict[str, object] | None] = {}  # spec -> filter (for object-form addition)
    for provider in (
        resolved.plan,
        resolved.todo,
        resolved.askuser,
        resolved.footer,
        resolved.web,
        resolved.review,
    ):
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


def _converge_linear_package(
    root: Path, packages: list[object]
) -> tuple[list[object], _ProviderChanges]:
    """Reconcile the `npm:pi-mono-linear` entry against the committed `[issues]` selection.

    Two-directional, mirroring ``_converge_provider_packages``: ``backend = "linear"`` selected →
    the plain-string ``LINEAR_PACKAGE`` entry is appended (unless an entry with its identity is
    already present); not selected → any entry matching the identity is **removed** (perk treats
    the package as managed by the selection; hand-adding it without selecting linear is
    unsupported). A malformed or ill-typed committed TOML defers to the config check by treating
    the selection as absent.
    """
    try:
        selected = load_committed_issues_backend(root)
    except (tomllib.TOMLDecodeError, ConfigError):
        selected = None
    identity = _package_identity(LINEAR_PACKAGE)
    if identity is None:  # unreachable for the constant LINEAR_PACKAGE; proves `str` to the checker
        return packages, _ProviderChanges(added=[], removed=[])

    if selected != "linear":
        removed: list[str] = []
        kept: list[object] = []
        for entry in packages:
            if _package_identity(entry) == identity:
                removed.append(identity)
                continue
            kept.append(entry)
        return kept, _ProviderChanges(added=[], removed=removed)

    if any(_package_identity(entry) == identity for entry in packages):
        return packages, _ProviderChanges(added=[], removed=[])
    return [*packages, LINEAR_PACKAGE], _ProviderChanges(added=[LINEAR_PACKAGE], removed=[])
