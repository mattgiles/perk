"""perk's TOML config: `.perk/config.toml` (committed) overlaid by `.perk/local.toml`
(gitignored). Read-only via stdlib ``tomllib``; ``perk init`` *writes* the files.

The parse boundary is real: the raw merged TOML validates through per-table
``LenientParseModel`` boundary models (``ConfigFileModel`` + friends) and converts into the
frozen ``Config`` domain dataclass. An ill-typed value **fails loudly** as a ``ConfigError``
carrying the pydantic field path (mapped to a clean ``UserFacingCliError`` at the CLI boundary;
``perk doctor``'s ``config`` check pinpoints the field). Unknown keys stay ignored
(``extra="ignore"`` — TS-read keys/tables share the same file). A malformed file's
``TOMLDecodeError`` propagates unchanged (its catch sites are a separate contract).
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from pydantic import BeforeValidator, Field, field_validator, model_validator

from perk.boundary import LenientParseModel, ValidationError, translate_validation_errors
from perk.substrate import git, paths
from perk.substrate.bindings import Binding, parse_user_bindings
from perk.substrate.skill_exposure import SkillsPolicy

DEFAULT_WORKTREE_DIRNAME = ".worktrees"

# pi's `--thinking` level vocabulary (the contract surface the doctor check validates configured
# `[models.stages.<id>] thinking` values against). Model strings are NOT validated by perk — pi
# resolves those at session start.
PI_THINKING_LEVELS: frozenset[str] = frozenset({"off", "minimal", "low", "medium", "high", "xhigh"})


class ConfigError(Exception):
    """A `.perk` config value failed validation (the config-domain error).

    Raised only for value-validation failures (via ``translate_validation_errors``, so the
    message carries the pydantic field path). Malformed TOML stays ``tomllib.TOMLDecodeError``.
    """


def _normalize_blank(value: object) -> object:
    """Strip a ``str``; a blank one becomes ``None``. Non-strings pass through unchanged so the
    field's ``str | None`` annotation rejects them loudly (no silent drop)."""
    if isinstance(value, str):
        return value.strip() or None
    return value


StrippedStr = Annotated[str | None, BeforeValidator(_normalize_blank)]
"""A config string field normalized at the boundary: stripped, blank → ``None``, non-str raises."""


@dataclass(frozen=True)
class StageModel:
    """Per-stage pi launch overrides from `[models.stages.<id>]` (both optional; None ⇒ pi
    default)."""

    model: str | None = None
    thinking: str | None = None


class WorktreeTable(LenientParseModel):
    """The `[worktree]` table: the worktree root + the ordered setup commands."""

    root: StrippedStr = None
    # The `[worktree] setup` ordered shell commands run inside a freshly created worktree before
    # `pi` starts (overlay-aware, like `root` — a `local.toml` array replaces this one wholesale).
    setup: list[str] = Field(default_factory=list)

    @field_validator("setup", mode="after")
    @classmethod
    def _strip_setup(cls, value: list[str]) -> list[str]:
        """Normalize formatting: strip each entry, drop blanks (a non-``str`` element raises)."""
        return [stripped for entry in value if (stripped := entry.strip())]


class SkillsTable(LenientParseModel):
    """The `[skills]` namespace (+ the `[skills.stages]` sub-table) — the top-down controls of
    the layered skills-exposure model (contracts.md §8.39).

    Types/shape only: stage-id vocabulary stays registry-free here (unknown stage ids and skill
    names are kept, inert — mirroring `[models.stages.<id>]`); ill-typed values raise
    ``ConfigError`` via ``translate_validation_errors`` (the standard schema-v2 loud posture).
    """

    include_dirs: list[str] = Field(default_factory=list)
    include_packages: bool | None = None
    # Each value: the literal "all" or a list of non-empty stage-id strings.
    stages: dict[str, str | list[str]] = Field(default_factory=dict)

    @field_validator("include_dirs", mode="after")
    @classmethod
    def _strip_include_dirs(cls, value: list[str]) -> list[str]:
        """Normalize formatting: strip each entry, drop blanks (a non-``str`` element raises) —
        the ``WorktreeTable.setup`` validator pattern."""
        return [stripped for entry in value if (stripped := entry.strip())]

    @field_validator("stages", mode="after")
    @classmethod
    def _validate_stages(cls, value: dict[str, str | list[str]]) -> dict[str, str | list[str]]:
        """Each row is the literal ``"all"`` or a list of non-empty strings; anything else
        raises (an ill-typed row must never silently hide or widen a skill)."""
        normalized: dict[str, str | list[str]] = {}
        for name, row in value.items():
            if isinstance(row, str):
                if row.strip() != "all":
                    raise ValueError(
                        f'stages.{name}: a string value must be the literal "all" '
                        "(or use a list of stage ids)"
                    )
                normalized[name] = "all"
                continue
            entries = [entry.strip() for entry in row]
            if not all(entries):
                raise ValueError(f"stages.{name}: stage-id entries must be non-empty strings")
            normalized[name] = entries
        return normalized

    def to_domain(self) -> SkillsPolicy:
        """Explicit conversion into the frozen policy (`"all"` rows become ``None``)."""
        return SkillsPolicy(
            include_dirs=tuple(self.include_dirs),
            include_packages=self.include_packages,
            stages={
                name: (None if isinstance(row, str) else tuple(row))
                for name, row in self.stages.items()
            },
        )


class WorkflowTable(LenientParseModel):
    """The `[workflow]` table. Only ``base`` is Python-read (the default target branch: the
    trunk plans/objectives base off when no objective-level override is set; ``None`` ⇒ fall back
    to the GitHub default branch). The sibling ``plan_authoring`` key is TS-read and dropped by
    ``extra="ignore"``."""

    base: StrippedStr = None


# Retired `[providers]` keys — key → tripwire message (each retired seam adds one entry).
# A present retired key would silently vanish under ``extra="ignore"``; the mapping keeps the
# hard-fail-with-removal-guidance posture in one place as the retired set grows.
RETIRED_PROVIDER_KEYS: dict[str, str] = {
    "review": (
        "retired key [providers] review — the review seam is retired; the surface "
        "doors are the selection: /pr-review-terminal (hunk) or /pr-review-browser "
        "(plannotator). Remove `review` from [providers] in .perk/config.toml"
    ),
    "askuser": (
        "retired key [providers] askuser — the askuser seam is retired; the "
        "ask_user_question questionnaire tool is built-in (perk installs "
        "npm:@juicesharp/rpiv-ask-user-question for every repo). Remove `askuser` from "
        "[providers] in .perk/config.toml"
    ),
}


class ProvidersTable(LenientParseModel):
    """The flat `[providers]` per-seam selection.

    Deliberately **no** blank normalization: a blank selection (e.g. ``plan = ""``) is kept and
    the providers resolver reports it loud-but-non-fatal (resolution against the supported set
    happens in ``init``/``providers``, not here)."""

    plan: str | None = None
    todo: str | None = None
    footer: str | None = None
    web: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_retired_keys(cls, data: object) -> object:
        """Retired-key tripwire (deliberate hard break, no dual-read — the `_reject_legacy_tables`
        precedent): a retired seam key would silently vanish under ``extra="ignore"`` — fail
        loudly with removal guidance instead (``RETIRED_PROVIDER_KEYS``). Diagnostics, not
        compat — no ``doctor --fix`` arm; the TS plane needs no twin (its unread keys fail
        safe)."""
        if isinstance(data, dict):
            for key, message in RETIRED_PROVIDER_KEYS.items():
                if key in data:
                    raise ValueError(message)
        return data


class SubagentsTable(LenientParseModel):
    """The agent-keyed `[models.subagents]` table — a per-agent model override for each perk-owned
    project agent, injected as the top-level workflow-level ``model`` default on that agent's
    ``workflowScript`` launch (a default applied to every lane — single-child runs included).
    Absent/blank keys mean "use the agent's frontmatter default";
    unknown agent keys stay ignored (``extra="ignore"``). The field set is the SSOT for the
    known agent keys."""

    pr_reviewer: StrippedStr = Field(default=None, alias="pr-reviewer")
    review_classifier: StrippedStr = Field(default=None, alias="review-classifier")
    objective_explorer: StrippedStr = Field(default=None, alias="objective-explorer")
    conflict_resolver: StrippedStr = Field(default=None, alias="conflict-resolver")
    learn_analyst: StrippedStr = Field(default=None, alias="learn-analyst")
    adversarial_reviewer: StrippedStr = Field(default=None, alias="adversarial-reviewer")
    review_angle_selector: StrippedStr = Field(default=None, alias="review-angle-selector")


class StageTable(LenientParseModel):
    """One `[models.stages.<id>]` sub-table (pi ``--model``/``--thinking`` launch overrides).

    Types/shape only: thinking-level vocabulary and registry stage-id validation deliberately
    stay in doctor's ``_stage_models_check`` (warn-level; keeps this module registry-free)."""

    model: StrippedStr = None
    thinking: StrippedStr = None

    def to_domain(self) -> "StageModel":
        return StageModel(model=self.model, thinking=self.thinking)


class CompactionTable(LenientParseModel):
    """The `[compaction]` table (pi's interactive auto-compaction tuning; contracts.md §8.10).

    The sibling ``objective_threshold`` key is a TS-read runtime knob (the objective compaction
    threshold) that lives in the same table for the operator; it is deliberately dropped here
    (``extra="ignore"``) and must never be mapped by ``to_settings()`` — it is not a pi
    `settings.json` key."""

    enabled: bool | None = None
    reserve_tokens: int | None = Field(default=None, gt=0)
    keep_recent_tokens: int | None = Field(default=None, gt=0)

    @field_validator("reserve_tokens", "keep_recent_tokens", mode="before")
    @classmethod
    def _reject_bool(cls, value: object) -> object:
        """``bool`` is an ``int`` subclass; ``reserve_tokens = true`` must never read as 1 —
        reject it explicitly (independent of pydantic's conversion-table details)."""
        if isinstance(value, bool):
            raise ValueError("a boolean is not a token count")
        return value

    def to_settings(self) -> dict[str, object]:
        """Map to pi's camelCase `settings.json` `compaction` keys (non-``None`` keys only)."""
        result: dict[str, object] = {}
        if self.enabled is not None:
            result["enabled"] = self.enabled
        if self.reserve_tokens is not None:
            result["reserveTokens"] = self.reserve_tokens
        if self.keep_recent_tokens is not None:
            result["keepRecentTokens"] = self.keep_recent_tokens
        return result


class ModelsTable(LenientParseModel):
    """The `[models]` namespace — which AI runs where, precedence visible as nesting
    (flag > `[models.stages.<id>]` > `default`), plus the `[models.subagents]` per-agent
    overrides.

    ``default``/``thinking`` are converged into the committed `.pi/settings.json`
    `defaultProvider`/`defaultModel`/`defaultThinkingLevel` keys (which pi reads natively at
    session boot — cold doors, plain `pi`, and the headless worker alike); ``stages`` and
    ``subagents`` are runtime-read (overlay-aware).

    Validation is deliberately **hard** (a ``ValueError`` here surfaces as ``ConfigError``): a
    typo must never converge into the committed `settings.json`. pi's settings default is an
    **exact** provider+id lookup, so ``default`` must be ``provider/id`` — perk splits on the
    **first** ``/`` (openrouter ids contain slashes). A ``:thinking`` suffix on ``default`` is
    accepted and split at convergence; the suffix rule is shared with pi-subagents: the
    last-colon segment is a thinking level **only when** it is in ``PI_THINKING_LEVELS``
    (ollama-style tags like ``llama3:70b`` stay part of the id). An explicit ``thinking`` key
    wins over a differing suffix (doctor's ``models`` check warns on the conflict).
    """

    default: StrippedStr = None
    thinking: StrippedStr = None
    # Unknown stage ids are kept — registry validation is the doctor check's job, not the
    # parser's (keeps this module free of a registry import).
    stages: dict[str, StageTable] = Field(default_factory=dict)
    subagents: SubagentsTable = Field(default_factory=SubagentsTable)

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_model_key(cls, data: object) -> object:
        """Config schema v2 tripwire: the pre-v2 `model` key would silently vanish under
        ``extra="ignore"`` (the documented config-tables trap) — fail loudly instead."""
        if isinstance(data, dict) and "model" in data:
            raise ValueError(
                "legacy key [models] model — renamed to default (config schema v2); "
                "update .perk/config.toml"
            )
        return data

    @model_validator(mode="after")
    def _validate(self) -> "ModelsTable":
        if self.thinking is not None and self.thinking not in PI_THINKING_LEVELS:
            raise ValueError(
                f"thinking `{self.thinking}` is not a valid pi level "
                "(off/minimal/low/medium/high/xhigh)"
            )
        if self.default is not None and "/" not in self._base_model():
            raise ValueError(
                "default must be `provider/id` — pi's settings default is an exact "
                "provider+id lookup"
            )
        return self

    def suffix_thinking(self) -> str | None:
        """The vocab-valid ``:thinking`` suffix on ``default``, if any.

        The single home of the suffix-split logic (``to_settings`` and doctor's conflict warn
        both go through it): the last-colon segment counts only when it is a pi thinking level.
        """
        if self.default is None:
            return None
        _, sep, tail = self.default.rpartition(":")
        if sep and tail in PI_THINKING_LEVELS:
            return tail
        return None

    def _base_model(self) -> str:
        """``default`` with a vocab-valid thinking suffix stripped (``""`` when unset)."""
        if self.default is None:
            return ""
        suffix = self.suffix_thinking()
        if suffix is None:
            return self.default
        return self.default[: -(len(suffix) + 1)]

    def to_settings(self) -> dict[str, object]:
        """Map ``default``/``thinking`` to pi's top-level `settings.json` keys (non-absent only;
        empty table → ``{}``). ``stages``/``subagents`` are runtime-read — never settings."""
        result: dict[str, object] = {}
        if self.default is not None:
            provider, _, model_id = self._base_model().partition("/")
            result["defaultProvider"] = provider
            result["defaultModel"] = model_id
        thinking = self.thinking if self.thinking is not None else self.suffix_thinking()
        if thinking is not None:
            result["defaultThinkingLevel"] = thinking
        return result


class IssuesTable(LenientParseModel):
    """The `[issues]` table: the backend selection + the Linear team key.

    Vocabulary validation happens in ``perk/backends/resolve.py``'s ``resolve_issue_backend_id``
    — this model only answers "what did the user write?" (typed, stripped)."""

    backend: StrippedStr = None
    team: StrippedStr = None


class LinearLocalTable(LenientParseModel):
    """The `[linear]` table read from `.perk/local.toml` only (the secret seed)."""

    api_key: StrippedStr = None


# The retired pre-v2 top-level tables and where each moved (config schema v2). With
# ``extra="ignore"`` a legacy spelling would silently vanish (the documented config-tables
# trap); the tripwire below fails loudly with the new home instead.
_LEGACY_TABLE_HOMES: dict[str, str] = {
    "trust": "[ci] trusted",
    "objective": "[compaction] objective_threshold",
    "stages": "[models.stages.<id>]",
    "subagents": "[models.subagents]",
}


class ConfigFileModel(LenientParseModel):
    """The whole merged `.perk/config.toml` (+ `local.toml` overlay) parse boundary.

    Python-read tables only: `[[bindings]]` keeps its loud-but-non-fatal seam
    (``parse_user_bindings``), and the TS-read keys (`[ci]`, `[compaction]
    objective_threshold`) plus the committed-only reads (`[compaction]`, `[issues]`,
    `[linear]`) are absent here and dropped by ``extra="ignore"``. The `[models]` namespace
    (``default``/``thinking``/``stages``/``subagents``) validates as one table."""

    worktree: WorktreeTable = Field(default_factory=WorktreeTable)
    workflow: WorkflowTable = Field(default_factory=WorkflowTable)
    providers: ProvidersTable = Field(default_factory=ProvidersTable)
    models: ModelsTable = Field(default_factory=ModelsTable)
    skills: SkillsTable = Field(default_factory=SkillsTable)

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_tables(cls, data: object) -> object:
        """Config schema v2 tripwire (deliberate hard break, no dual-read): each retired
        top-level spelling fails loudly with a pointer to its new home. Diagnostics, not
        compat — the TS plane needs no twin (its unread legacy spellings all fail safe)."""
        if not isinstance(data, dict):
            return data
        # `.items()` iteration (not `.get`) keeps the object-narrowed dict ty-clean.
        for key, value in data.items():
            if not isinstance(key, str):
                continue
            new_home = _LEGACY_TABLE_HOMES.get(key)
            if new_home is not None:
                raise ValueError(
                    f"legacy table [{key}] — moved to {new_home} (config schema v2); "
                    "update .perk/config.toml"
                )
            # The new `[ci]` is a dict (`trusted` + `[[ci.checks]]`); a LIST-valued `ci` is
            # the legacy `[[ci]]` array-of-tables.
            if key == "ci" and isinstance(value, list):
                raise ValueError(
                    "legacy table [[ci]] — moved to [[ci.checks]] (config schema v2); "
                    "update .perk/config.toml"
                )
        return data

    def to_domain(self, repo_root: Path, *, user_bindings: list[Binding]) -> "Config":
        """Assemble the frozen ``Config`` (structural inputs as method params).

        ``user_bindings`` is passed through by identity — bindings never pass through a pydantic
        model here (their loud-but-non-fatal seam lives in ``parse_user_bindings``).
        """
        # `StrippedStr` already normalized a blank `root = ""` to None, so it falls back to the
        # default here (instead of `Path("")` resolving to the repo root itself).
        if self.worktree.root is not None:
            root = Path(self.worktree.root)
        else:
            root = Path(DEFAULT_WORKTREE_DIRNAME)
        if not root.is_absolute():
            root = repo_root / root
        providers: dict[str, str | None] = {
            seam: value
            for seam, value in (
                ("plan", self.providers.plan),
                ("todo", self.providers.todo),
                ("footer", self.providers.footer),
                ("web", self.providers.web),
            )
            if value is not None
        }
        subagents = {
            agent: value
            for agent, value in (
                ("pr-reviewer", self.models.subagents.pr_reviewer),
                ("review-classifier", self.models.subagents.review_classifier),
                ("objective-explorer", self.models.subagents.objective_explorer),
                ("conflict-resolver", self.models.subagents.conflict_resolver),
                ("learn-analyst", self.models.subagents.learn_analyst),
                ("adversarial-reviewer", self.models.subagents.adversarial_reviewer),
                ("review-angle-selector", self.models.subagents.review_angle_selector),
            )
            if value is not None
        }
        # An all-``None`` entry is omitted (an empty `[models.stages.foo]` stays inert).
        stage_models = {
            stage_id: entry.to_domain()
            for stage_id, entry in self.models.stages.items()
            if entry.model is not None or entry.thinking is not None
        }
        return Config(
            worktree_root=root,
            worktree_setup=self.worktree.setup,
            user_bindings=user_bindings,
            subagents=subagents,
            providers=providers,
            workflow_base=self.workflow.base,
            stage_models=stage_models,
            skills=self.skills.to_domain(),
        )


@dataclass(frozen=True)
class Config:
    """The immutable resolved-config domain object returned by ``load_config``.

    ``worktree_root`` is absolute. ``ConfigFileModel`` is its parse boundary; this frozen
    dataclass holds the domain values directly (e.g. ``user_bindings`` carries the
    ``parse_user_bindings`` output without Pydantic re-validation).
    """

    worktree_root: Path
    worktree_setup: list[str] = field(default_factory=list)
    user_bindings: list[Binding] = field(default_factory=list)
    subagents: dict[str, str] = field(default_factory=dict)
    providers: dict[str, str | None] = field(default_factory=dict)
    workflow_base: str | None = None
    stage_models: dict[str, StageModel] = field(default_factory=dict)
    skills: SkillsPolicy = field(default_factory=SkillsPolicy)


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _overlay(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``over`` onto ``base`` (local wins; tables merge, leaves replace)."""
    merged = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _overlay(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(repo_root: Path) -> Config:
    """Load ``.perk/config.toml`` overlaid by ``.perk/local.toml`` from ``repo_root``.

    The overlay merge happens *before* validation, so ill-typed ``local.toml`` values raise
    ``ConfigError`` too (the overlay is inside the boundary).
    """
    merged: dict[str, Any] = {}
    for path in (paths.config_file(repo_root), paths.local_config_file(repo_root)):
        merged = _overlay(merged, _read_toml(path))
    with translate_validation_errors(
        ConfigError, source=".perk/config.toml (+ local.toml overlay)"
    ):
        parsed = ConfigFileModel.model_validate(merged)
    return parsed.to_domain(repo_root, user_bindings=parse_user_bindings(merged.get("bindings")))


def load_committed_compaction(repo_root: Path) -> dict[str, object]:
    """Read the `[compaction]` table from **committed** `.perk/config.toml` only (no local overlay).

    Deliberately bypasses ``load_config`` (and thus ``local.toml``) so the committed
    `settings.json` stays a deterministic function of committed config — per-user compaction
    overrides belong in pi's native global `~/.pi/agent/settings.json`. A missing file yields
    ``{}``; a malformed-TOML ``tomllib.TOMLDecodeError`` propagates and an ill-typed value raises
    ``ConfigError`` (init guards both, deferring to the config check — mirrors
    ``_converge_provider_packages``). Note ``raw.get("compaction", {})``, not ``or {}`` — a
    present non-dict value must raise, not vanish.
    """
    raw = _read_toml(paths.config_file(repo_root))
    with translate_validation_errors(ConfigError, source=".perk/config.toml [compaction]"):
        table = CompactionTable.model_validate(raw.get("compaction", {}))
    return table.to_settings()


def load_committed_models_table(repo_root: Path) -> "ModelsTable":
    """Validate the `[models]` namespace from **committed** `.perk/config.toml` only (no overlay).

    Validates the whole namespace (``default``/``thinking``/``stages``/``subagents`` — one
    table, one validity), though only ``default``/``thinking`` feed ``to_settings()``.
    The table-shaped sibling of ``load_committed_models`` (which delegates here): doctor's
    ``models`` check inspects ``thinking`` vs ``suffix_thinking()`` for the conflict warn
    without re-parsing the TOML. Same error contract as ``load_committed_compaction``: a
    missing file yields the empty table; a malformed-TOML ``tomllib.TOMLDecodeError``
    propagates and an ill-typed value raises ``ConfigError`` (init guards both, deferring to
    the config check). Note ``raw.get("models", {})``, not ``or {}`` — a present non-dict
    value must raise, not vanish.
    """
    raw = _read_toml(paths.config_file(repo_root))
    with translate_validation_errors(ConfigError, source=".perk/config.toml [models]"):
        return ModelsTable.model_validate(raw.get("models", {}))


def load_committed_models(repo_root: Path) -> dict[str, object]:
    """Read the `[models]` table from **committed** `.perk/config.toml` only (no local overlay),
    mapped to pi's `settings.json` default-model keys.

    Deliberately bypasses ``load_config`` (and thus ``local.toml``) so the committed
    `settings.json` stays a deterministic function of committed config — per-user model
    overrides belong in pi's native global `~/.pi/agent/settings.json` (or `perk <stage>
    --model` / a `local.toml` `[models.stages.<id>]` override). A `local.toml` `[models]`
    ``default``/``thinking`` is deliberately ignored (the runtime-read ``stages``/``subagents``
    siblings DO honor the overlay, via ``load_config``). Error contract per
    ``load_committed_models_table``.
    """
    return load_committed_models_table(repo_root).to_settings()


def _committed_issues(repo_root: Path) -> IssuesTable:
    """Validate the `[issues]` table from **committed** `.perk/config.toml` only (no overlay).

    The whole table validates as one model: an ill-typed ``team`` fails the backend read too
    (one table, one validity).

    Read from the **main checkout's** config, not the invocation root's: the `[issues]`
    selection is repo-durable identity (where canonical issues are written), so a linked
    worktree's checkout state (detached / stale branch / missing `.perk/`) must never flip a
    Linear repo to the GitHub default. The ``or repo_root`` fallback keeps non-repo callers
    (tests rooted at a bare ``tmp_path``) reading the given root. Deliberate consequence: a
    plan branch that *edits* `[issues]` does not take effect from inside its worktree — the
    canonical-store selection must not fork mid-plan; it switches when the edit reaches the
    main checkout.
    """
    root = git.main_worktree_root(repo_root) or repo_root
    raw = _read_toml(paths.config_file(root))
    with translate_validation_errors(ConfigError, source=".perk/config.toml [issues]"):
        return IssuesTable.model_validate(raw.get("issues", {}))


def load_committed_issues_backend(repo_root: Path) -> str | None:
    """Read the `[issues] backend` selection from **committed** `.perk/config.toml` (no overlay).

    Deliberately bypasses ``load_config`` (and thus ``local.toml``): the backend decides
    where canonical durable state (plan/learn/objective issues) is written — a per-user override
    would fragment the canonical store. Anchored to the **main checkout** via
    ``_committed_issues`` so a linked worktree's checkout state can never flip the selection.
    A missing file yields ``None``; a malformed-TOML ``tomllib.TOMLDecodeError`` propagates and
    an ill-typed value raises ``ConfigError`` (the resolver maps both; the config check owns
    the finding).
    """
    return _committed_issues(repo_root).backend


def load_committed_issues_team(repo_root: Path) -> str | None:
    """Read the `[issues] team` key from **committed** `.perk/config.toml` only (no local overlay).

    Mirrors ``load_committed_issues_backend`` exactly (same committed-only rationale,
    main-checkout anchoring, and error contract). The value is the Linear **team key** (e.g.
    ``"ENG"``) — what ``LinearIssueBackend`` resolves to a team UUID via ``client.team_id(...)``.
    """
    return _committed_issues(repo_root).team


def load_local_linear_api_key(repo_root: Path) -> str | None:
    """Read `[linear] api_key` from **local** `.perk/local.toml` only (the inverse of the
    ``load_committed_*`` readers, which read the committed file only).

    A Linear personal API key is a secret, so it is read **only** from the gitignored
    ``local.toml`` — never the committed ``config.toml`` — structurally preventing a committed
    secret. Not threaded through the merged ``Config`` dataclass for the same reason (that would
    make it readable from the committed file and widen the surface). Returns the stripped string
    when set; otherwise ``None`` (absent table/key, ill-typed, or blank).

    **Fail-soft on malformed/ill-typed input**: a ``tomllib.TOMLDecodeError`` or a pydantic
    ``ValidationError`` is caught and yields ``None``. This deliberately diverges from the
    ``load_committed_*`` readers, which *propagate* their errors (the config check maps them): a
    best-effort secret seed must never crash a command, and a broken ``local.toml`` is not
    surfaced anywhere else today.
    """
    # The gitignored secret lives only in the MAIN checkout's `.perk/local.toml` (never copied
    # into a linked worktree), so resolve the main worktree root first; fall back to the given root
    # when `repo_root` is not inside a git repo (tests / non-repo callers).
    root = git.main_worktree_root(repo_root) or repo_root
    try:
        raw = _read_toml(paths.local_config_file(root))
        return LinearLocalTable.model_validate(raw.get("linear", {})).api_key
    except (tomllib.TOMLDecodeError, ValidationError):
        return None
