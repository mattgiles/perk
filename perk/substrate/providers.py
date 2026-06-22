"""Load and validate the shared provider-selection supported set (`shared/providers.yaml`).

This is the Python plane's reader of the *third* parsed cross-plane contract (the first two
being `shared/registry.yaml` and `shared/bindings.yaml`). It is the **supported set** — the
catalog of plan/todo/askuser/footer/web providers perk knows how to wire — distinct from the
per-repo *selection* (the flat `[providers]` table in `.pi/perk.toml`, a pointer into this catalog).
The TS extension has an independent reader (`extension/substrate/providers.ts`) over the *same*
bundled file.

Validation is **shape-only and repo-free**: the validator checks that each provider entry is
well formed (non-empty unique `id`, `seam ∈ {plan, todo, askuser, footer, web}`, exactly one
`default: true` per seam), but it does NOT cross-check that any repo *selection* names a real
provider — that
cross-file validation is `doctor`'s job (D6, mirroring how bindings target-existence lives in
doctor, not the loader).

The selection substrate is **consumed**: runtime consumption of the selection (init's
two-directional `[providers]` settings wiring + `doctor`'s selection checks, and the extension's
plan-seam registration-time vacating / todo-seam runtime deferral) is live.

The validator returns structured ``Issue`` records (it never raises for invalid *content*) so
callers decide how to surface them; ``ProvidersError`` is reserved for structural load failures.
LBYL throughout (dignified-python): shapes are checked before use.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from perk._resources import shared_dir
from perk.substrate.registry import FindingSeverity, Issue

PROVIDERS_FILENAME = "providers.yaml"
SUPPORTED_SCHEMA_VERSION = 1

SEAMS: tuple[str, ...] = ("plan", "todo", "askuser", "footer", "web")


@dataclass(frozen=True)
class Provider:
    """One supported-set provider entry.

    ``package``/``adapter`` are ``None`` for perk's own bundled reference providers (nothing to
    add to ``packages``; perk produces the contract natively). ``package_filter`` is the optional
    Pi object-form filter merged into a foreign package's ``packages`` entry.
    """

    id: str
    seam: str
    package: str | None
    adapter: str | None
    default: bool
    package_filter: dict[str, Any] | None


@dataclass(frozen=True)
class ProviderSet:
    schema_version: int
    providers: list[Provider]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def by_id(self) -> dict[str, Provider]:
        """Map ``id -> Provider`` (last wins on a duplicate id; the validator flags duplicates)."""
        return {p.id: p for p in self.providers if p.id}

    def default_for(self, seam: str) -> Provider | None:
        """The first ``default: true`` provider for ``seam`` (validator enforces exactly one)."""
        for provider in self.providers:
            if provider.seam == seam and provider.default:
                return provider
        return None


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

    providers = [_parse_provider(raw) for raw in _as_list(data.get("providers"))]
    return ProviderSet(schema_version=schema_version, providers=providers, raw=data)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _parse_provider(raw: Any) -> Provider:
    """Coerce one raw provider mapping into a ``Provider``, tolerating absent fields.

    Missing/ill-typed fields become empty/``None``/``False`` so the *validator* (not the parser)
    reports them — keeping all consistency findings in one place (matches ``_parse_binding``).
    """
    raw = raw if isinstance(raw, dict) else {}
    package_filter = raw.get("package_filter")
    return Provider(
        id=_str(raw.get("id")),
        seam=_str(raw.get("seam")),
        package=_opt_str(raw.get("package")),
        adapter=_opt_str(raw.get("adapter")),
        default=raw.get("default") is True,
        package_filter=package_filter if isinstance(package_filter, dict) else None,
    )


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


# ----------------------------------------------------------------------- validate


def validate(providers: ProviderSet) -> list[Issue]:
    """Return every shape issue (empty list == valid). Never raises for content.

    Shape-only and repo-free (D2): each entry has a non-empty unique ``id``; ``seam ∈ SEAMS``;
    and **exactly one** ``default: true`` per seam. Does NOT check any repo selection — that
    cross-file validation is ``doctor``'s job (D6).
    """
    issues: list[Issue] = []
    seen: set[str] = set()
    default_counts: dict[str, int] = {seam: 0 for seam in SEAMS}

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
        elif provider.default:
            default_counts[provider.seam] += 1

    for seam in SEAMS:
        count = default_counts[seam]
        if count != 1:
            issues.append(
                Issue(
                    FindingSeverity.ERROR,
                    "providers",
                    f"seam `{seam}` must have exactly one `default: true` provider (found {count})",
                )
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
    todo: Provider
    askuser: Provider
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
        todo=resolve_seam("todo"),
        askuser=resolve_seam("askuser"),
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
