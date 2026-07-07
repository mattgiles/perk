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

from pydantic import BeforeValidator, Field, field_validator

from perk.boundary import LenientParseModel, ValidationError, translate_validation_errors
from perk.substrate import git, paths
from perk.substrate.bindings import Binding, parse_user_bindings

DEFAULT_WORKTREE_DIRNAME = ".worktrees"

# pi's `--thinking` level vocabulary (the contract surface the doctor check validates configured
# `[stages.<id>] thinking` values against). Model strings are NOT validated by perk — pi resolves
# those at session start.
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
    """Per-stage pi launch overrides from `[stages.<id>]` (both optional; None ⇒ pi default)."""

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


class WorkflowTable(LenientParseModel):
    """The `[workflow]` table. Only ``base`` is Python-read (the default target branch: the
    trunk plans/objectives base off when no objective-level override is set; ``None`` ⇒ fall back
    to the GitHub default branch). The sibling ``plan_authoring`` key is TS-read and dropped by
    ``extra="ignore"``."""

    base: StrippedStr = None


class ProvidersTable(LenientParseModel):
    """The flat `[providers]` per-seam selection.

    Deliberately **no** blank normalization: a blank selection (e.g. ``plan = ""``) is kept and
    the providers resolver reports it loud-but-non-fatal (resolution against the supported set
    happens in ``init``/``providers``, not here)."""

    plan: str | None = None
    todo: str | None = None
    askuser: str | None = None
    footer: str | None = None
    web: str | None = None


class SubagentsTable(LenientParseModel):
    """The agent-keyed `[subagents]` table — a per-agent model override for each perk-owned
    project agent, injected as a per-call inline ``model`` override on that agent's spawn.
    Absent/blank keys mean "use the agent's frontmatter default"; unknown agent keys stay
    ignored (``extra="ignore"``). The field set is the SSOT for the known agent keys."""

    pr_reviewer: StrippedStr = Field(default=None, alias="pr-reviewer")
    review_classifier: StrippedStr = Field(default=None, alias="review-classifier")
    objective_explorer: StrippedStr = Field(default=None, alias="objective-explorer")
    conflict_resolver: StrippedStr = Field(default=None, alias="conflict-resolver")
    learn_analyst: StrippedStr = Field(default=None, alias="learn-analyst")


class StageTable(LenientParseModel):
    """One `[stages.<id>]` sub-table (pi ``--model``/``--thinking`` launch overrides).

    Types/shape only: thinking-level vocabulary and registry stage-id validation deliberately
    stay in doctor's ``_stage_models_check`` (warn-level; keeps this module registry-free)."""

    model: StrippedStr = None
    thinking: StrippedStr = None

    def to_domain(self) -> "StageModel":
        return StageModel(model=self.model, thinking=self.thinking)


class CompactionTable(LenientParseModel):
    """The `[compaction]` table (pi's interactive auto-compaction tuning; contracts.md §8.10)."""

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


class IssuesTable(LenientParseModel):
    """The `[issues]` table: the backend selection + the Linear team key.

    Vocabulary validation happens in ``perk/backends/resolve.py``'s ``resolve_issue_backend_id``
    — this model only answers "what did the user write?" (typed, stripped)."""

    backend: StrippedStr = None
    team: StrippedStr = None


class LinearLocalTable(LenientParseModel):
    """The `[linear]` table read from `.perk/local.toml` only (the secret seed)."""

    api_key: StrippedStr = None


class ConfigFileModel(LenientParseModel):
    """The whole merged `.perk/config.toml` (+ `local.toml` overlay) parse boundary.

    Python-read tables only: `[[bindings]]` keeps its loud-but-non-fatal seam
    (``parse_user_bindings``), and the TS-read tables (`[trust]`, `[[ci]]`, `[objective]`) plus
    the committed-only reads (`[compaction]`, `[issues]`, `[linear]`) are absent here and dropped
    by ``extra="ignore"``."""

    worktree: WorktreeTable = Field(default_factory=WorktreeTable)
    workflow: WorkflowTable = Field(default_factory=WorkflowTable)
    providers: ProvidersTable = Field(default_factory=ProvidersTable)
    subagents: SubagentsTable = Field(default_factory=SubagentsTable)
    # Unknown stage ids are kept — registry validation is the doctor check's job, not the
    # parser's (keeps this module free of a registry import).
    stages: dict[str, StageTable] = Field(default_factory=dict)

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
                ("askuser", self.providers.askuser),
                ("footer", self.providers.footer),
                ("web", self.providers.web),
            )
            if value is not None
        }
        subagents = {
            agent: value
            for agent, value in (
                ("pr-reviewer", self.subagents.pr_reviewer),
                ("review-classifier", self.subagents.review_classifier),
                ("objective-explorer", self.subagents.objective_explorer),
                ("conflict-resolver", self.subagents.conflict_resolver),
                ("learn-analyst", self.subagents.learn_analyst),
            )
            if value is not None
        }
        # An all-``None`` entry is omitted (an empty `[stages.foo]` stays inert).
        stage_models = {
            stage_id: entry.to_domain()
            for stage_id, entry in self.stages.items()
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


def _committed_issues(repo_root: Path) -> IssuesTable:
    """Validate the `[issues]` table from **committed** `.perk/config.toml` only (no overlay).

    The whole table validates as one model: an ill-typed ``team`` fails the backend read too
    (one table, one validity).
    """
    raw = _read_toml(paths.config_file(repo_root))
    with translate_validation_errors(ConfigError, source=".perk/config.toml [issues]"):
        return IssuesTable.model_validate(raw.get("issues", {}))


def load_committed_issues_backend(repo_root: Path) -> str | None:
    """Read the `[issues] backend` selection from **committed** `.perk/config.toml` (no overlay).

    Deliberately bypasses ``load_config`` (and thus ``local.toml``): the backend decides
    where canonical durable state (plan/learn/objective issues) is written — a per-user override
    would fragment the canonical store. A missing file yields ``None``; a malformed-TOML
    ``tomllib.TOMLDecodeError`` propagates and an ill-typed value raises ``ConfigError`` (the
    resolver maps both; the config check owns the finding).
    """
    return _committed_issues(repo_root).backend


def load_committed_issues_team(repo_root: Path) -> str | None:
    """Read the `[issues] team` key from **committed** `.perk/config.toml` only (no local overlay).

    Mirrors ``load_committed_issues_backend`` exactly (same committed-only rationale and error
    contract). The value is the Linear **team key** (e.g. ``"ENG"``) — what
    ``LinearIssueBackend`` resolves to a team UUID via ``client.team_id(...)``.
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
