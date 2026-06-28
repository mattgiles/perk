"""perk's TOML config: `.perk/config.toml` (committed) overlaid by `.perk/local.toml`
(gitignored). Read-only via stdlib ``tomllib``; ``perk init`` *writes* the files.

T4 needs only the worktree root; the ``Config`` dataclass grows as later turns add settings.
LBYL throughout (missing files -> defaults); a malformed file's ``TOMLDecodeError`` is
translated to a ``UserFacingCliError`` at the CLI boundary (``require_config``).
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import Field

from perk.boundary import LenientParseModel
from perk.substrate import git, paths
from perk.substrate.bindings import Binding, parse_user_bindings

DEFAULT_WORKTREE_DIRNAME = ".worktrees"

# pi's `--thinking` level vocabulary (the contract surface the doctor check validates configured
# `[stages.<id>] thinking` values against). Model strings are NOT validated by perk — pi resolves
# those at session start.
PI_THINKING_LEVELS: frozenset[str] = frozenset({"off", "minimal", "low", "medium", "high", "xhigh"})


@dataclass(frozen=True)
class StageModel:
    """Per-stage pi launch overrides from `[stages.<id>]` (both optional; None ⇒ pi default)."""

    model: str | None = None
    thinking: str | None = None


class ConfigModel(LenientParseModel):
    """Lenient parse / structural backstop over the *assembled* config.

    Validates the post-``_overlay`` ``_parse_*`` outputs as a typed, frozen structural backstop
    inside ``load_config`` — it does **not** replace the overlay layer (that semantic lives in the
    ``_parse_*`` helpers). The frozen ``Config`` dataclass is the domain object built from it.
    """

    worktree_root: Path
    # The `[worktree] setup` ordered shell commands run inside a freshly created worktree before
    # `pi` starts (overlay-aware, like `worktree_root` — a `local.toml` array replaces this
    # one wholesale). Empty when absent/ill-typed.
    worktree_setup: list[str] = Field(default_factory=list)
    user_bindings: list[Binding] = Field(default_factory=list)
    # The agent-keyed `[subagents]` table — a per-agent model override for each perk-owned
    # project agent (`pr-reviewer`, `review-classifier`, `objective-explorer`), injected as a
    # per-call inline `model` override on that agent's spawn. Absent keys mean "use the agent's
    # frontmatter default". Only known agent keys with string values are kept (mirrors `providers`).
    subagents: dict[str, str] = Field(default_factory=dict)
    # The raw `[providers]` per-seam selection (provider-id strings or None when absent). Exposed
    # raw — resolution against the supported set happens in `init`/`providers` (mirroring how
    # `user_bindings` is raw and `resolve_bindings` resolves it).
    providers: dict[str, str | None] = Field(default_factory=dict)
    # The `[workflow] base` default target branch: the trunk that plans/objectives base off
    # and target when no objective-level override is set. `None` (absent/non-string) ⇒ fall back
    # to the GitHub default branch (byte-identical to prior behavior). The sibling
    # `[workflow] plan_authoring` key is TS-read and untouched.
    workflow_base: str | None = None
    # The per-stage `[stages.<id>]` launch overrides — a `{stage_id: StageModel}` map injected as
    # pi `--model`/`--thinking` flags at the cold-launch seam (`launch_stage`). Unknown stage ids
    # are kept here (registry validation is the doctor check's job, not the parser's — keeps this
    # module free of a registry import); held by identity exactly like `user_bindings`.
    stage_models: dict[str, StageModel] = Field(default_factory=dict)

    def to_domain(self) -> "Config":
        """Convert the validated model into the frozen ``Config`` domain object.

        Explicit field-by-field copy (never ``Config(**model.model_dump())``: model_dump would
        recursively turn nested ``Binding`` models into plain dicts and corrupt ``user_bindings``).
        Attribute access preserves the original ``Binding`` instances by identity.
        """
        return Config(
            worktree_root=self.worktree_root,
            worktree_setup=self.worktree_setup,
            user_bindings=self.user_bindings,
            subagents=self.subagents,
            providers=self.providers,
            workflow_base=self.workflow_base,
            stage_models=self.stage_models,
        )


@dataclass(frozen=True)
class Config:
    """The immutable resolved-config domain object returned by ``load_config``.

    ``worktree_root`` is absolute. ``ConfigModel`` is its boundary backstop; this frozen dataclass
    holds the parsed values directly (e.g. ``user_bindings`` carries the ``parse_user_bindings``
    output without Pydantic re-validation).
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
    """Load ``.perk/config.toml`` overlaid by ``.perk/local.toml`` from ``repo_root``."""
    merged: dict[str, Any] = {}
    for path in (paths.config_file(repo_root), paths.local_config_file(repo_root)):
        merged = _overlay(merged, _read_toml(path))

    worktree = merged.get("worktree")
    root_value = worktree.get("root") if isinstance(worktree, dict) else None
    root = Path(root_value) if isinstance(root_value, str) else Path(DEFAULT_WORKTREE_DIRNAME)
    if not root.is_absolute():
        root = repo_root / root
    model = ConfigModel(
        worktree_root=root,
        worktree_setup=_parse_worktree_setup(worktree),
        user_bindings=parse_user_bindings(merged.get("bindings")),
        providers=_parse_providers_selection(merged.get("providers")),
        subagents=_parse_subagents_selection(merged.get("subagents")),
        workflow_base=_parse_workflow_base(merged.get("workflow")),
        stage_models=_parse_stage_models(merged.get("stages")),
    )
    return model.to_domain()


def _parse_worktree_setup(raw: Any) -> list[str]:
    """Read the `[worktree] setup` value into an ordered list of shell command strings.

    LBYL silent-omit (mirrors ``_parse_workflow_base``/``_parse_subagents_selection``): a non-dict
    table or a non-list ``setup`` yields ``[]``; within a list, only non-blank ``str`` entries are
    kept (each ``.strip()``-ed) and everything else is dropped.
    """
    table = raw if isinstance(raw, dict) else {}
    value = table.get("setup")
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _parse_stage_models(raw: Any) -> dict[str, StageModel]:
    """Read the `[stages.<id>]` sub-tables into a `{stage_id: StageModel}` map.

    LBYL silent-omit (mirrors ``_parse_subagents_selection``): a non-dict `[stages]` table yields
    ``{}``; each `[stages.<id>]` sub-table contributes a ``StageModel`` built from its **string**
    ``model``/``thinking`` values (each ``.strip()``-ed; blank/ill-typed dropped). A sub-table that
    yields neither a model nor a thinking is omitted (an empty `[stages.foo]` stays inert). Unknown
    stage ids are kept — registry validation is the doctor check's job, not the parser's.
    """
    table = raw if isinstance(raw, dict) else {}
    result: dict[str, StageModel] = {}
    for stage_id, sub in table.items():
        if not isinstance(sub, dict):
            continue
        model = _stripped_str(sub.get("model"))
        thinking = _stripped_str(sub.get("thinking"))
        if model is None and thinking is None:
            continue
        result[stage_id] = StageModel(model=model, thinking=thinking)
    return result


def _stripped_str(value: Any) -> str | None:
    """Return ``value.strip()`` when it is a non-blank ``str``, else ``None`` (ill-typed/blank)."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _parse_workflow_base(raw: Any) -> str | None:
    """Read the `[workflow] base` value when it is a non-blank ``str``.

    LBYL silent-omit (mirrors ``parse_issues_backend``): a non-dict/absent table or an
    absent/ill-typed/blank ``base`` yields ``None`` (callers fall back to the GitHub default
    branch). The sibling ``plan_authoring`` key is TS-read and ignored here.
    """
    table = raw if isinstance(raw, dict) else {}
    value = table.get("base")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


# The perk-owned project agents configurable via the `[subagents]` table.
_SUBAGENT_KEYS = ("pr-reviewer", "review-classifier", "objective-explorer", "conflict-resolver")


def _parse_subagents_selection(raw: Any) -> dict[str, str]:
    """Read the agent-keyed `[subagents]` table into a `{agent: model}` selection.

    A non-dict table (absent) yields ``{}``; only the known agent keys whose values are non-blank
    strings are kept (an absent/ill-typed/unknown key is omitted, so the spawn falls back to the
    agent's frontmatter default silently for it — mirrors ``_parse_providers_selection``).
    """
    table = raw if isinstance(raw, dict) else {}
    return {
        key: value
        for key in _SUBAGENT_KEYS
        if isinstance(value := table.get(key), str) and value.strip()
    }


def parse_compaction_table(raw: Any) -> dict[str, object]:
    """Map the raw `[compaction]` table to pi's camelCase `settings.json` `compaction` keys.

    snake_case TOML → camelCase: `enabled`→`enabled`, `reserve_tokens`→`reserveTokens`,
    `keep_recent_tokens`→`keepRecentTokens`. LBYL silent-omit (mirrors the providers/subagents
    parsers): `enabled` kept only if a real `bool`; the token keys kept only if `int` and `> 0`.
    A non-dict/absent input yields ``{}``; ill-typed/absent keys are dropped (pi fills defaults).
    """
    table = raw if isinstance(raw, dict) else {}
    result: dict[str, object] = {}
    enabled = table.get("enabled")
    if isinstance(enabled, bool):
        result["enabled"] = enabled
    token_keys = (("reserve_tokens", "reserveTokens"), ("keep_recent_tokens", "keepRecentTokens"))
    for snake, camel in token_keys:
        value = table.get(snake)
        # `bool` is a subclass of `int`; exclude it so `reserve_tokens = true` is not read as 1.
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            result[camel] = value
    return result


def load_committed_compaction(repo_root: Path) -> dict[str, object]:
    """Read the `[compaction]` table from **committed** `.perk/config.toml` only (no local overlay).

    Deliberately bypasses ``load_config`` (and thus ``local.toml``) so the committed
    `settings.json` stays a deterministic function of committed config — per-user compaction
    overrides belong in pi's native global `~/.pi/agent/settings.json`. A missing file yields
    ``{}``; a malformed-TOML ``tomllib.TOMLDecodeError`` propagates (init guards it, deferring to
    the config check — mirrors ``_converge_provider_packages``).
    """
    raw = _read_toml(paths.config_file(repo_root))
    return parse_compaction_table(raw.get("compaction"))


def parse_issues_backend(raw: Any) -> str | None:
    """Read the raw `[issues]` table's ``backend`` value when it is a non-blank ``str``.

    LBYL silent-omit (mirrors ``parse_compaction_table``): a non-dict/absent table or an
    absent/ill-typed/blank ``backend`` yields ``None`` (the resolver falls back to the
    default backend). Vocabulary validation happens in
    ``perk/backends/resolve.py``'s ``resolve_issue_backend_id`` — this parser only answers "what
    did the user write?".
    """
    table = raw if isinstance(raw, dict) else {}
    value = table.get("backend")
    if isinstance(value, str) and value.strip():
        return value
    return None


def load_committed_issues_backend(repo_root: Path) -> str | None:
    """Read the `[issues]` backend selection from **committed** `.perk/config.toml` (no overlay).

    Deliberately bypasses ``load_config`` (and thus ``local.toml``): the backend decides
    where canonical durable state (plan/learn/objective issues) is written — a per-user override
    would fragment the canonical store. A missing file yields ``None``; a malformed-TOML
    ``tomllib.TOMLDecodeError`` propagates (the resolver maps it; the config check owns malformed
    TOML — mirrors ``load_committed_compaction``).
    """
    raw = _read_toml(paths.config_file(repo_root))
    return parse_issues_backend(raw.get("issues"))


def parse_issues_team(raw: Any) -> str | None:
    """Read the raw `[issues]` table's ``team`` value when it is a non-blank ``str``.

    LBYL silent-omit (mirrors ``parse_issues_backend``): a non-dict/absent table or an
    absent/ill-typed/blank ``team`` yields ``None``. The value is the Linear **team key**
    (e.g. ``"ENG"``) — what ``LinearIssueBackend`` resolves to a team UUID via
    ``client.team_id(...)``. Returns the stripped string otherwise.
    """
    table = raw if isinstance(raw, dict) else {}
    value = table.get("team")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def load_committed_issues_team(repo_root: Path) -> str | None:
    """Read the `[issues] team` key from **committed** `.perk/config.toml` only (no local overlay).

    Mirrors ``load_committed_issues_backend`` exactly: deliberately bypasses ``load_config`` (and
    thus ``local.toml``) — the backend decides where canonical durable state is written, so a
    per-user team override would fragment the canonical store. A missing file yields ``None``; a
    malformed-TOML ``tomllib.TOMLDecodeError`` propagates (the resolver maps it; the config check
    owns malformed TOML).
    """
    raw = _read_toml(paths.config_file(repo_root))
    return parse_issues_team(raw.get("issues"))


def load_local_linear_api_key(repo_root: Path) -> str | None:
    """Read `[linear] api_key` from **local** `.perk/local.toml` only (the inverse of the
    ``load_committed_*`` readers, which read the committed file only).

    A Linear personal API key is a secret, so it is read **only** from the gitignored
    ``local.toml`` — never the committed ``config.toml`` — structurally preventing a committed
    secret. Not threaded through the merged ``Config`` dataclass for the same reason (that would
    make it readable from the committed file and widen the surface). Returns the stripped string
    when ``[linear]`` is a table and ``api_key`` is a non-blank ``str``; otherwise ``None`` (absent
    table/key, ill-typed, or blank).

    **Fail-soft on malformed TOML**: a ``tomllib.TOMLDecodeError`` is caught and yields ``None``.
    This deliberately diverges from the ``load_committed_*`` readers, which *propagate*
    ``TOMLDecodeError`` (the config check maps it): a best-effort secret seed must never crash a
    command, and malformed ``local.toml`` is not surfaced anywhere else today.
    """
    # The gitignored secret lives only in the MAIN checkout's `.perk/local.toml` (never copied
    # into a linked worktree), so resolve the main worktree root first; fall back to the given root
    # when `repo_root` is not inside a git repo (tests / non-repo callers).
    root = git.main_worktree_root(repo_root) or repo_root
    try:
        raw = _read_toml(paths.local_config_file(root))
    except tomllib.TOMLDecodeError:
        return None
    table = raw.get("linear")
    if not isinstance(table, dict):
        return None
    value = table.get("api_key")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _parse_providers_selection(raw: Any) -> dict[str, str | None]:
    """Read the flat `[providers]` table into a per-seam selection (string values).

    A non-dict table (absent) yields ``{}``; only `plan`/`todo`/`askuser`/`footer`/`web` keys with
    **string** values are kept (an absent/ill-typed key is simply omitted, so the resolver falls
    back to the seam default silently for it).
    """
    table = raw if isinstance(raw, dict) else {}
    return {
        seam: value
        for seam in ("plan", "todo", "askuser", "footer", "web")
        if isinstance(value := table.get(seam), str)
    }
