"""Load and validate the shared provider-selection supported set (`shared/providers.yaml`).

This is the Python plane's reader of the *third* parsed cross-plane contract (the first two being
`shared/registry.yaml` and `shared/bindings.yaml`).

It is the **supported set** — the catalog of plan/todo/askuser/footer/web providers perk knows how
to wire — distinct from the per-repo *selection* (the flat `[providers]` table in
`.perk/config.toml`, a pointer into the catalog).

The TS extension has an independent reader (`extension/substrate/providers.ts`) over the *same*
bundle file.

Validation is **shape-only and repo-free**: the validator checks that each provider entry is well
formed (non-empty unique `id`, `seam ∈ {plan, todo, askuser, footer, web}`, exactly one `default:
true` per seam), but it does NOT cross-check that any repo *selection* names a real provider — that
cross-file validation is `doctor`'s job (D6, mirroring how bindings target-existence lives in
doctor, not the loader).

The selection substrate is **consumed**: runtime consumption of the selection (init's
two-directional `[providers]` settings wiring + `doctor`'s selection checks, and the extension's
plan-seam registration-time vacating / todo-seam runtime deferral) is live.

The validator returns structured ``Issue`` records (it never raises for invalid *content*) so
callers decide how to surface them; ``ProvidersError`` is reserved for structural load failures.
LBYL throughout (dignified-python): shapes are checked before use.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BeforeValidator, Field, ValidationInfo, model_validator

from perk._resources import shared_dir
from perk.boundary import (
    StrictBoundaryModel,
    ValidationError,
    translate_validation_errors,
)
from perk.substrate.registry import FindingSeverity, Issue

PROVIDERS_FILENAME = "providers.yaml"
SUPPORTED_SCHEMA_VERSION = 1

SEAMS: tuple[str, ...] = ("plan", "todo", "askuser", "footer", "web")


def _as_text(v: object) -> object:
    """Lenient string coercion: a non-str (incl. absent→None) becomes ``""`` (today's `_str`)."""
    return v if isinstance(v, str) else ""


def _as_opt_text(v: object) -> object:
    """Lenient optional-string coercion: a non-str becomes ``None`` (today's `_opt_str`)."""
    return v if isinstance(v, str) else None


def _as_flag(v: object) -> object:
    """Lenient flag coercion: only literal ``True`` is truthy (today's `... is True`)."""
    return v is True


def _as_opt_dict(v: object) -> object:
    """Lenient optional-dict coercion: a non-dict becomes ``None``."""
    return v if isinstance(v, dict) else None


_Text = Annotated[str, BeforeValidator(_as_text)]
_OptText = Annotated[str | None, BeforeValidator(_as_opt_text)]
_Flag = Annotated[bool, BeforeValidator(_as_flag)]
_OptDict = Annotated[dict[str, Any] | None, BeforeValidator(_as_opt_dict)]


class Provider(StrictBoundaryModel):
    """One supported-set provider entry.

    ``package``/``adapter`` are ``None`` for perk's own bundled reference providers (nothing to
    add to ``packages``; perk produces the contract natively). ``package_filter`` is the optional
    Pi object-form filter merged into a foreign package's ``packages`` entry.

    Fields are leniently coerced (missing/ill-typed → ``""``/``None``/``False``) so the *validator*
    (not construction) owns content findings — except a stray key, which ``extra="forbid"`` rejects
    at load (a boundary-first tightening over today's silent ignore).
    """

    id: _Text = ""
    seam: _Text = ""
    package: _OptText = None
    adapter: _OptText = None
    default: _Flag = False
    package_filter: _OptDict = None


class ProviderSet(StrictBoundaryModel):
    schema_version: int
    providers: list[Provider] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    def by_id(self) -> dict[str, Provider]:
        """Map ``id -> Provider`` (last wins on a duplicate id; the validator flags duplicates)."""
        return {p.id: p for p in self.providers if p.id}

    def default_for(self, seam: str) -> Provider | None:
        """The first ``default: true`` provider for ``seam`` (validator enforces exactly one)."""
        for provider in self.providers:
            if provider.seam == seam and provider.default:
                return provider
        return None

    @model_validator(mode="after")
    def _enforce_single_default(self, info: ValidationInfo) -> "ProviderSet":
        """Raise iff the caller opts in via ``context["enforce_single_default"]``.

        Gated so ``load_providers()`` (no context) stays lenient — default-count stays a
        ``validate()`` ``Issue`` — while ``validate()`` opts in and converts the raised
        ``ValidationError`` back into ``Issue`` records. Direct construction (``info.context is
        None``) never raises.
        """
        if info.context and info.context.get("enforce_single_default"):
            problems = _one_default_per_seam_problems(self.providers)
            if problems:
                raise ValueError("; ".join(problems))
        return self


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
        entries = [
            Provider.model_validate(raw if isinstance(raw, dict) else {})
            for raw in _as_list(data.get("providers"))
        ]
        # Direct ``ProviderSet(...)`` construction has ``info.context is None`` → the
        # single-default validator skips, keeping load lenient on default-count.
        return ProviderSet(schema_version=schema_version, providers=entries, raw=data)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


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

    # The exactly-one-default-per-seam invariant lives once, as the context-gated
    # ``ProviderSet`` validator; surface it here via catch-and-convert (gains pydantic's
    # "Value error, " prefix, and per-seam violations combine into one ``Issue``).
    try:
        ProviderSet.model_validate(providers.model_dump(), context={"enforce_single_default": True})
    except ValidationError as exc:
        issues.extend(Issue(FindingSeverity.ERROR, "providers", err["msg"]) for err in exc.errors())

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
