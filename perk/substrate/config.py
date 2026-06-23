"""perk's TOML config: `.pi/perk.toml` (committed) overlaid by `.pi/perk.local.toml`
(gitignored). Read-only via stdlib ``tomllib``; ``perk init`` *writes* the files.

T4 needs only the worktree root; the ``Config`` dataclass grows as later turns add settings.
LBYL throughout (missing files -> defaults); a malformed file's ``TOMLDecodeError`` is
translated to a ``UserFacingCliError`` at the CLI boundary (``require_config``).
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from perk.substrate import git
from perk.substrate.bindings import Binding, parse_user_bindings

CONFIG_FILENAME = "perk.toml"
LOCAL_CONFIG_FILENAME = "perk.local.toml"
DEFAULT_WORKTREE_DIRNAME = ".worktrees"


@dataclass(frozen=True)
class Config:
    """Resolved perk config. ``worktree_root`` is absolute."""

    worktree_root: Path
    # The `[worktree] setup` ordered shell commands run inside a freshly created worktree before
    # `pi` starts (overlay-aware, like `worktree_root` — a `perk.local.toml` array replaces this
    # one wholesale). Empty when absent/ill-typed.
    worktree_setup: list[str] = field(default_factory=list)
    user_bindings: list[Binding] = field(default_factory=list)
    # The agent-keyed `[subagents]` table — a per-agent model override for each perk-owned
    # project agent (`pr-reviewer`, `review-classifier`, `objective-explorer`), injected as a
    # per-call inline `model` override on that agent's spawn. Absent keys mean "use the agent's
    # frontmatter default". Only known agent keys with string values are kept (mirrors `providers`).
    subagents: dict[str, str] = field(default_factory=dict)
    # The raw `[providers]` per-seam selection (provider-id strings or None when absent). Exposed
    # raw — resolution against the supported set happens in `init`/`providers` (mirroring how
    # `user_bindings` is raw and `resolve_bindings` resolves it).
    providers: dict[str, str | None] = field(default_factory=dict)
    # The `[workflow] base` default target branch: the trunk that plans/objectives base off
    # and target when no objective-level override is set. `None` (absent/non-string) ⇒ fall back
    # to the GitHub default branch (byte-identical to prior behavior). The sibling
    # `[workflow] plan_authoring` key is TS-read and untouched.
    workflow_base: str | None = None


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
    """Load ``.pi/perk.toml`` overlaid by ``.pi/perk.local.toml`` from ``repo_root``."""
    pi_dir = repo_root / ".pi"
    merged: dict[str, Any] = {}
    for name in (CONFIG_FILENAME, LOCAL_CONFIG_FILENAME):
        merged = _overlay(merged, _read_toml(pi_dir / name))

    worktree = merged.get("worktree")
    root_value = worktree.get("root") if isinstance(worktree, dict) else None
    root = Path(root_value) if isinstance(root_value, str) else Path(DEFAULT_WORKTREE_DIRNAME)
    if not root.is_absolute():
        root = repo_root / root
    return Config(
        worktree_root=root,
        worktree_setup=_parse_worktree_setup(worktree),
        user_bindings=parse_user_bindings(merged.get("bindings")),
        providers=_parse_providers_selection(merged.get("providers")),
        subagents=_parse_subagents_selection(merged.get("subagents")),
        workflow_base=_parse_workflow_base(merged.get("workflow")),
    )


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
    """Read the `[compaction]` table from **committed** `.pi/perk.toml` only (no local overlay).

    Deliberately bypasses ``load_config`` (and thus ``perk.local.toml``) so the committed
    `settings.json` stays a deterministic function of committed config — per-user compaction
    overrides belong in pi's native global `~/.pi/agent/settings.json`. A missing file yields
    ``{}``; a malformed-TOML ``tomllib.TOMLDecodeError`` propagates (init guards it, deferring to
    the config check — mirrors ``_converge_provider_packages``).
    """
    raw = _read_toml(repo_root / ".pi" / CONFIG_FILENAME)
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
    """Read the `[issues]` backend selection from **committed** `.pi/perk.toml` only (no overlay).

    Deliberately bypasses ``load_config`` (and thus ``perk.local.toml``): the backend decides
    where canonical durable state (plan/learn/objective issues) is written — a per-user override
    would fragment the canonical store. A missing file yields ``None``; a malformed-TOML
    ``tomllib.TOMLDecodeError`` propagates (the resolver maps it; the config check owns malformed
    TOML — mirrors ``load_committed_compaction``).
    """
    raw = _read_toml(repo_root / ".pi" / CONFIG_FILENAME)
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
    """Read the `[issues] team` key from **committed** `.pi/perk.toml` only (no local overlay).

    Mirrors ``load_committed_issues_backend`` exactly: deliberately bypasses ``load_config`` (and
    thus ``perk.local.toml``) — the backend decides where canonical durable state is written, so a
    per-user team override would fragment the canonical store. A missing file yields ``None``; a
    malformed-TOML ``tomllib.TOMLDecodeError`` propagates (the resolver maps it; the config check
    owns malformed TOML).
    """
    raw = _read_toml(repo_root / ".pi" / CONFIG_FILENAME)
    return parse_issues_team(raw.get("issues"))


def load_local_linear_api_key(repo_root: Path) -> str | None:
    """Read `[linear] api_key` from **local** `.pi/perk.local.toml` only (the inverse of the
    ``load_committed_*`` readers, which read the committed file only).

    A Linear personal API key is a secret, so it is read **only** from the gitignored
    ``perk.local.toml`` — never the committed ``perk.toml`` — structurally preventing a committed
    secret. Not threaded through the merged ``Config`` dataclass for the same reason (that would
    make it readable from the committed file and widen the surface). Returns the stripped string
    when ``[linear]`` is a table and ``api_key`` is a non-blank ``str``; otherwise ``None`` (absent
    table/key, ill-typed, or blank).

    **Fail-soft on malformed TOML**: a ``tomllib.TOMLDecodeError`` is caught and yields ``None``.
    This deliberately diverges from the ``load_committed_*`` readers, which *propagate*
    ``TOMLDecodeError`` (the config check maps it): a best-effort secret seed must never crash a
    command, and malformed ``perk.local.toml`` is not surfaced anywhere else today.
    """
    # The gitignored secret lives only in the MAIN checkout's `.pi/perk.local.toml` (never copied
    # into a linked worktree), so resolve the main worktree root first; fall back to the given root
    # when `repo_root` is not inside a git repo (tests / non-repo callers).
    root = git.main_worktree_root(repo_root) or repo_root
    try:
        raw = _read_toml(root / ".pi" / LOCAL_CONFIG_FILENAME)
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
