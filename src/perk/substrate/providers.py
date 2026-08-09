"""Load and validate the shared provider-selection supported set (`shared/providers.yaml`).

This is the Python plane's reader of the *third* parsed cross-plane contract (the first two being
`shared/registry.yaml` and `shared/bindings.yaml`).

It is the **supported set** — the catalog of plan/footer/web providers perk
knows how to wire — distinct from the per-repo *selection* (the flat `[providers]` table in
`.perk/config.toml`, a pointer into the catalog).

The TS extension has an independent reader (`extension/substrate/providers.ts`) over the *same*
bundle file.

Validation is **shape-only and repo-free**: the validator checks that each provider entry is well
formed (non-empty unique `id`, `seam ∈ {plan, footer, web}`, exactly one
`default: true` per seam), but it does NOT cross-check that any repo *selection* names a real
provider — that cross-file validation is `doctor`'s job (D6, mirroring how bindings
target-existence lives in doctor, not the loader).

The selection substrate is **consumed**: runtime consumption of the selection (init's
two-directional `[providers]` settings wiring + `doctor`'s selection checks, and the extension's
plan-seam registration-time vacating) is live.

The boundary follows the canonical lenient-parse → frozen-dataclass → `validate()` pattern: the
untrusted file is parsed through tolerant ``LenientParseModel`` models (``ProvidersFile`` /
``ProviderEntry``), converted into frozen ``@dataclass`` domain objects (``ProviderSet`` /
``Provider``), and only then does ``validate(ProviderSet) -> [Issue]`` run the content checks. The
validator returns structured ``Issue`` records (it never raises for invalid *content*) so callers
decide how to surface them; ``ProvidersError`` is reserved for structural load failures.
LBYL throughout (dignified-python): shapes are checked before use.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field

from perk._resources import shared_dir
from perk.boundary import LenientParseModel, translate_validation_errors
from perk.substrate.registry import FindingSeverity, Issue

PROVIDERS_FILENAME = "providers.yaml"
SUPPORTED_SCHEMA_VERSION = 1

SEAMS: tuple[str, ...] = ("plan", "footer", "web")


class ProviderEntry(LenientParseModel):
    """The lenient per-entry parse model at the file boundary.

    ``id``/``seam`` are typed ``str | None`` (not ``str = ""``) so an explicit YAML ``null`` parses
    cleanly; the converter normalizes ``None -> ""`` and ``validate()`` then surfaces the
    missing-``id`` / bad-``seam`` content findings. Other fields coerce leniently (drop unknown
    keys, coerce ordinary scalars) per the lenient base — content findings are the *validator*'s
    job, never construction's.
    """

    id: str | None = None
    seam: str | None = None
    package: str | None = None
    adapter: str | None = None
    default: bool = False
    package_filter: dict[str, Any] | None = None

    def to_domain(self) -> "Provider":
        """Explicit field-for-field conversion into the frozen domain object.

        Normalizes an absent/``null`` ``id``/``seam`` to ``""`` so ``validate()`` surfaces the
        missing-``id`` / bad-``seam`` content findings (rather than the parse model raising).
        """
        return Provider(
            id=self.id or "",
            seam=self.seam or "",
            package=self.package,
            adapter=self.adapter,
            default=self.default,
            package_filter=self.package_filter,
        )


class ProvidersFile(LenientParseModel):
    """The lenient whole-file parse model.

    ``schema_version`` is deliberately NOT a field: it stays a structural pre-check in
    ``load_providers`` (it must run before generic validation and raise its own message).
    ``extra="ignore"`` drops it (and any other top-level key) from this model.
    """

    providers: list[ProviderEntry] = Field(default_factory=list)

    def to_domain(self, schema_version: int) -> "ProviderSet":
        """Convert the whole validated file into the frozen ``ProviderSet`` domain object."""
        return ProviderSet(
            schema_version=schema_version,
            providers=tuple(e.to_domain() for e in self.providers),
        )


@dataclass(frozen=True)
class Provider:
    """One supported-set provider entry (frozen domain object).

    ``package``/``adapter`` are ``None`` for perk's own bundled reference providers (nothing to
    add to ``packages``; perk produces the contract natively). ``package_filter`` is the optional
    Pi object-form filter merged into a foreign package's ``packages`` entry. Every field is always
    set by the converter (no defaults).
    """

    id: str
    seam: str
    package: str | None
    adapter: str | None
    default: bool
    package_filter: dict[str, Any] | None


@dataclass(frozen=True)
class ProviderSet:
    """The loaded supported set (frozen domain object)."""

    schema_version: int
    providers: tuple[Provider, ...] = ()

    def by_id(self) -> dict[str, Provider]:
        """Map ``id -> Provider`` (last wins on a duplicate id; the validator flags duplicates)."""
        return {p.id: p for p in self.providers if p.id}

    def default_for(self, seam: str) -> Provider | None:
        """The first ``default: true`` provider for ``seam`` (validator enforces exactly one)."""
        for provider in self.providers:
            if provider.seam == seam and provider.default:
                return provider
        return None


def _one_default_per_seam_problems(providers: Sequence[Provider]) -> list[str]:
    """One message per seam whose ``default: true`` count ``!= 1`` (the single invariant source)."""
    counts: dict[str, int] = {seam: 0 for seam in SEAMS}
    for provider in providers:
        if provider.seam in counts and provider.default:
            counts[provider.seam] += 1
    return [
        f"seam `{seam}` must have exactly one `default: true` provider (found {counts[seam]})"
        for seam in SEAMS
        if counts[seam] != 1
    ]


class ProvidersError(Exception):
    """The providers file is missing or not parseable as the expected top-level shape.

    Distinct from validation *issues*: this means we could not load a provider set at all
    (vs. loading one that fails consistency checks). Mirrors ``BindingsError``/``RegistryError``.
    """


# --------------------------------------------------------------------------- load


def load_providers(path: Path | None = None) -> ProviderSet:
    """Parse ``providers.yaml`` from the bundled ``shared/`` dir (or an explicit path).

    Raises ``ProvidersError`` only for *structural* failures (missing file, not a mapping,
    unsupported ``schema_version``) — content consistency is the validator's job.
    """
    providers_path = path or (shared_dir() / PROVIDERS_FILENAME)
    if not providers_path.is_file():
        raise ProvidersError(f"providers not found at {providers_path}")

    data = yaml.safe_load(providers_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ProvidersError(f"{providers_path}: top level must be a mapping")

    schema_version = data.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise ProvidersError(
            f"{providers_path}: unsupported schema_version {schema_version!r} "
            f"(this perk understands {SUPPORTED_SCHEMA_VERSION}). Run 'perk doctor'."
        )

    with translate_validation_errors(ProvidersError, source=str(providers_path)):
        # proven == SUPPORTED_SCHEMA_VERSION above; the literal satisfies strict int + ty.
        return ProvidersFile.model_validate(data).to_domain(SUPPORTED_SCHEMA_VERSION)


# ----------------------------------------------------------------------- validate


def validate(providers: ProviderSet) -> list[Issue]:
    """Return every shape issue (empty list == valid). Never raises for content.

    Shape-only and repo-free (D2): each entry has a non-empty unique ``id``; ``seam ∈ SEAMS``;
    and **exactly one** ``default: true`` per seam. Does NOT check any repo selection — that
    cross-file validation is ``doctor``'s job (D6).
    """
    issues: list[Issue] = []
    seen: set[str] = set()

    for provider in providers.providers:
        where = provider.id or "providers"
        if not provider.id:
            issues.append(
                Issue(FindingSeverity.ERROR, "providers", "a provider is missing its `id`")
            )
        elif provider.id in seen:
            issues.append(Issue(FindingSeverity.ERROR, where, "duplicate `id`"))
        seen.add(provider.id)

        if provider.seam not in SEAMS:
            issues.append(Issue(FindingSeverity.ERROR, where, f"`seam` must be one of {SEAMS}"))

    # The exactly-one-default-per-seam invariant lives once, in
    # ``_one_default_per_seam_problems`` (the single source) — one Issue per violating seam.
    issues.extend(
        Issue(FindingSeverity.ERROR, "providers", msg)
        for msg in _one_default_per_seam_problems(providers.providers)
    )

    return issues


# ------------------------------------------------------------------------ resolve


@dataclass(frozen=True)
class ResolvedProviders:
    """The effective provider per seam after resolving a repo selection against the supported set.

    ``issues`` collects every loud-but-non-fatal finding (a selection naming an unknown id or a
    wrong-seam provider) for later surfacing; an absent selection falls back silently.
    """

    plan: Provider
    footer: Provider
    web: Provider
    issues: list[Issue]


def resolve_providers(
    selection: dict[str, str | None], providers: ProviderSet | None = None
) -> ResolvedProviders:
    """Resolve a per-seam selection against the supported set (pure).

    For each seam, the selection resolves to the named provider **iff** the id exists AND its
    ``seam`` matches the key; otherwise it falls back to ``default_for(seam)`` and appends a
    loud-but-non-fatal ``Issue`` (unknown id / seam mismatch). An **absent** key (``None``) falls
    back to the default **silently** (the zero-config default — no Issue). Defaults are trusted
    (not re-validated). The exact analog of ``resolve_bindings``.
    """
    if providers is None:
        providers = load_providers()
    by_id = providers.by_id()
    issues: list[Issue] = []

    def resolve_seam(seam: str) -> Provider:
        selected = selection.get(seam)
        default = providers.default_for(seam)
        if selected is None:
            return _require_default(seam, default)
        provider = by_id.get(selected)
        if provider is None:
            issues.append(
                Issue(
                    FindingSeverity.ERROR,
                    "providers",
                    f"`{seam}` selects unknown provider `{selected}`",
                )
            )
            return _require_default(seam, default)
        if provider.seam != seam:
            issues.append(
                Issue(
                    FindingSeverity.ERROR,
                    "providers",
                    f"provider `{selected}` is a `{provider.seam}` provider, not `{seam}`",
                )
            )
            return _require_default(seam, default)
        return provider

    return ResolvedProviders(
        plan=resolve_seam("plan"),
        footer=resolve_seam("footer"),
        web=resolve_seam("web"),
        issues=issues,
    )


def _require_default(seam: str, default: Provider | None) -> Provider:
    """Return the seam default, or raise if the bundled set has none (validate() guards this).

    A healthy bundled file always has exactly one default per seam, so this only fires on a
    corrupt install — surfaced as ``ProvidersError`` rather than returning a bogus provider.
    """
    if default is None:
        raise ProvidersError(f"no default provider for seam `{seam}` — reinstall perk")
    return default
