import dataclasses
import tomllib
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from pydantic import ValidationError

from perk.cli.context import PerkContext
from perk.cli.ensure import UserFacingCliError
from perk.convergence.init import PERK_TOML_TEMPLATE
from perk.substrate.bindings import Binding
from perk.substrate.config import (
    Config,
    ConfigError,
    ConfigFileModel,
    StageModel,
    load_committed_compaction,
    load_committed_issues_backend,
    load_committed_issues_team,
    load_committed_models,
    load_committed_models_table,
    load_config,
    load_local_linear_api_key,
)

# Map the legacy config filenames callers still pass to the `.perk/` target locations, so the
# seeding helper writes where the readers now look (`.perk/config.toml` / `.perk/local.toml`).
_NAME_MAP = {"perk.toml": "config.toml", "perk.local.toml": "local.toml"}


def _write(repo: Path, name: str, text: str) -> None:
    cfg = repo / ".perk"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / _NAME_MAP.get(name, name)).write_text(text, encoding="utf-8")


def _write_legacy(repo: Path, name: str, text: str) -> None:
    """Seed a LEGACY config file at `.pi/<name>` (must be ignored by every reader)."""
    pi = repo / ".pi"
    pi.mkdir(parents=True, exist_ok=True)
    (pi / name).write_text(text, encoding="utf-8")


def test_defaults_when_absent(tmp_path):
    assert load_config(tmp_path).worktree_root == tmp_path / ".worktrees"


def test_legacy_pi_config_is_ignored(tmp_path):
    # A config left at the legacy `.pi/perk.toml` is never consumed: the readers resolve only the
    # `.perk/` target. With no `.perk/config.toml`, load_config falls back to defaults.
    _write_legacy(tmp_path, "perk.toml", '[worktree]\nroot = "legacy-wt"\n')
    assert load_config(tmp_path).worktree_root == tmp_path / ".worktrees"
    # And when both exist, the `.perk/` target wins (legacy is fully ignored, not overlaid).
    _write(tmp_path, "perk.toml", '[worktree]\nroot = "new-wt"\n')
    assert load_config(tmp_path).worktree_root == tmp_path / "new-wt"


def test_legacy_pi_local_secret_is_ignored(tmp_path):
    # The Linear secret reader resolves only `.perk/local.toml`; a legacy `.pi/perk.local.toml`
    # secret is never read.
    _write_legacy(tmp_path, "perk.local.toml", '[linear]\napi_key = "lin_legacy"\n')
    assert load_local_linear_api_key(tmp_path) is None
    _write(tmp_path, "perk.local.toml", '[linear]\napi_key = "lin_new"\n')
    assert load_local_linear_api_key(tmp_path) == "lin_new"


def test_relative_root_resolves_against_repo(tmp_path):
    _write(tmp_path, "perk.toml", '[worktree]\nroot = "wt"\n')
    assert load_config(tmp_path).worktree_root == tmp_path / "wt"


def test_local_overrides_committed(tmp_path):
    _write(tmp_path, "perk.toml", '[worktree]\nroot = "wt"\n')
    _write(tmp_path, "perk.local.toml", '[worktree]\nroot = "local-wt"\n')
    assert load_config(tmp_path).worktree_root == tmp_path / "local-wt"


def test_absolute_root_preserved(tmp_path):
    _write(tmp_path, "perk.toml", '[worktree]\nroot = "/abs/wt"\n')
    assert load_config(tmp_path).worktree_root == Path("/abs/wt")


def test_worktree_setup_absent_is_empty(tmp_path):
    assert load_config(tmp_path).worktree_setup == []


def test_worktree_setup_no_table_is_empty(tmp_path):
    _write(tmp_path, "perk.toml", '[workflow]\nbase = "main"\n')
    assert load_config(tmp_path).worktree_setup == []


def test_worktree_setup_parses_ordered_list(tmp_path):
    _write(tmp_path, "perk.toml", '[worktree]\nsetup = ["uv sync", "npm ci"]\n')
    assert load_config(tmp_path).worktree_setup == ["uv sync", "npm ci"]


def test_worktree_setup_non_list_raises(tmp_path):
    _write(tmp_path, "perk.toml", '[worktree]\nsetup = "uv sync"\n')
    with pytest.raises(ConfigError, match=r"worktree\.setup"):
        load_config(tmp_path)


def test_worktree_setup_strips_and_drops_blank_entries(tmp_path):
    _write(tmp_path, "perk.toml", '[worktree]\nsetup = ["  uv sync  ", "", "npm ci"]\n')
    assert load_config(tmp_path).worktree_setup == ["uv sync", "npm ci"]


def test_worktree_setup_non_string_element_raises(tmp_path):
    _write(tmp_path, "perk.toml", '[worktree]\nsetup = ["uv sync", 7]\n')
    with pytest.raises(ConfigError, match=r"worktree\.setup"):
        load_config(tmp_path)


def test_worktree_root_blank_falls_back_to_default(tmp_path):
    # A blank root normalizes away (previously `Path("")` resolved to the repo root itself).
    _write(tmp_path, "perk.toml", '[worktree]\nroot = ""\n')
    assert load_config(tmp_path).worktree_root == tmp_path / ".worktrees"


def test_worktree_setup_local_replaces_committed_wholesale(tmp_path):
    _write(tmp_path, "perk.toml", '[worktree]\nsetup = ["a"]\n')
    _write(tmp_path, "perk.local.toml", '[worktree]\nsetup = ["b"]\n')
    assert load_config(tmp_path).worktree_setup == ["b"]


def test_worktree_setup_seeded_template_is_inert(tmp_path):
    # The seeded template carries a *commented* `setup` example; it must parse to no commands.
    _write(tmp_path, "perk.toml", PERK_TOML_TEMPLATE)
    assert load_config(tmp_path).worktree_setup == []


def test_user_bindings_absent_is_empty(tmp_path):
    assert load_config(tmp_path).user_bindings == []


def test_workflow_base_absent_is_none(tmp_path):
    assert load_config(tmp_path).workflow_base is None


def test_workflow_base_parses_string(tmp_path):
    _write(tmp_path, "perk.toml", '[workflow]\nbase = "develop"\n')
    assert load_config(tmp_path).workflow_base == "develop"


def test_workflow_base_strips_whitespace(tmp_path):
    _write(tmp_path, "perk.toml", '[workflow]\nbase = "  develop  "\n')
    assert load_config(tmp_path).workflow_base == "develop"


def test_workflow_base_non_string_raises(tmp_path):
    _write(tmp_path, "perk.toml", "[workflow]\nbase = 7\n")
    with pytest.raises(ConfigError, match=r"workflow\.base"):
        load_config(tmp_path)


def test_local_overlay_illtyped_value_raises(tmp_path):
    # The overlay merges *before* validation, so `.perk/local.toml` is inside the boundary.
    _write(tmp_path, "perk.toml", '[workflow]\nbase = "develop"\n')
    _write(tmp_path, "perk.local.toml", "[workflow]\nbase = 7\n")
    with pytest.raises(ConfigError, match=r"workflow\.base"):
        load_config(tmp_path)


def test_workflow_base_blank_is_none(tmp_path):
    _write(tmp_path, "perk.toml", '[workflow]\nbase = "   "\n')
    assert load_config(tmp_path).workflow_base is None


def test_workflow_base_local_overrides_committed(tmp_path):
    _write(tmp_path, "perk.toml", '[workflow]\nbase = "develop"\n')
    _write(tmp_path, "perk.local.toml", '[workflow]\nbase = "release"\n')
    assert load_config(tmp_path).workflow_base == "release"


def test_seeded_template_is_inert(tmp_path):
    # The seeded `.perk/config.toml` carries a *commented* [[bindings]] example; it must
    # parse to zero user bindings (guards the comment-only invariant against edits).
    _write(tmp_path, "perk.toml", PERK_TOML_TEMPLATE)
    assert load_config(tmp_path).user_bindings == []


def test_user_bindings_parsed_from_array_of_tables(tmp_path):
    _write(
        tmp_path,
        "perk.toml",
        '[[bindings]]\ntrigger = "stage:plan"\nskill = "house-style"\nmode = "transclude"\n',
    )
    bindings = load_config(tmp_path).user_bindings
    assert [(b.trigger, b.kind, b.target_id, b.skill, b.mode) for b in bindings] == [
        ("stage:plan", "stage", "plan", "house-style", "transclude")
    ]


def test_local_bindings_replace_committed_array(tmp_path):
    _write(
        tmp_path,
        "perk.toml",
        '[[bindings]]\ntrigger = "stage:plan"\nskill = "committed"\nmode = "nudge"\n',
    )
    _write(
        tmp_path,
        "perk.local.toml",
        '[[bindings]]\ntrigger = "stage:implement"\nskill = "local"\nmode = "nudge"\n',
    )
    bindings = load_config(tmp_path).user_bindings
    # Whole-array replace (local wins): the committed binding is gone entirely.
    assert [(b.trigger, b.skill) for b in bindings] == [("stage:implement", "local")]


# --- [providers] selection -------------------------------------------------------


def test_providers_selection_absent_is_empty(tmp_path):
    assert load_config(tmp_path).providers == {}


def test_providers_selection_parsed(tmp_path):
    _write(
        tmp_path,
        "perk.toml",
        '[providers]\nplan = "tombell-plan"\ntodo = "perk-checkpoints"\n'
        'askuser = "juicesharp-ask-user"\nfooter = "pi-bar-footer"\nweb = "ollama-web-search"\n',
    )
    assert load_config(tmp_path).providers == {
        "plan": "tombell-plan",
        "todo": "perk-checkpoints",
        "askuser": "juicesharp-ask-user",
        "footer": "pi-bar-footer",
        "web": "ollama-web-search",
    }


def test_providers_selection_local_overlay_wins(tmp_path):
    _write(tmp_path, "perk.toml", '[providers]\nplan = "perk-plan"\n')
    _write(tmp_path, "perk.local.toml", '[providers]\nplan = "tombell-plan"\n')
    assert load_config(tmp_path).providers == {"plan": "tombell-plan"}


def test_providers_selection_non_string_raises(tmp_path):
    _write(tmp_path, "perk.toml", '[providers]\nplan = "perk-plan"\ntodo = 3\n')
    with pytest.raises(ConfigError, match=r"providers\.todo"):
        load_config(tmp_path)


def test_providers_selection_keeps_blank_value(tmp_path):
    # No blank normalization here (unlike other string keys): a blank selection is kept, and
    # the providers resolver reports it loud-but-non-fatal.
    _write(tmp_path, "perk.toml", '[providers]\nplan = ""\n')
    assert load_config(tmp_path).providers == {"plan": ""}


# --- [models.subagents] selection -----------------------------------------------------------


def test_subagents_selection_absent_is_empty(tmp_path):
    assert load_config(tmp_path).subagents == {}


def test_subagents_selection_parsed(tmp_path):
    _write(
        tmp_path,
        "perk.toml",
        '[models.subagents]\npr-reviewer = "a/sonnet"\nreview-classifier = "a/haiku"\n'
        'objective-explorer = "a/haiku2"\nconflict-resolver = "a/sonnet2"\n'
        'learn-analyst = "a/analyst"\n',
    )
    assert load_config(tmp_path).subagents == {
        "pr-reviewer": "a/sonnet",
        "review-classifier": "a/haiku",
        "objective-explorer": "a/haiku2",
        "conflict-resolver": "a/sonnet2",
        "learn-analyst": "a/analyst",
    }


def test_subagents_selection_local_overlay_wins(tmp_path):
    _write(tmp_path, "perk.toml", '[models.subagents]\npr-reviewer = "base/model"\n')
    _write(tmp_path, "perk.local.toml", '[models.subagents]\npr-reviewer = "local/model"\n')
    assert load_config(tmp_path).subagents == {"pr-reviewer": "local/model"}


def test_subagents_selection_non_string_raises(tmp_path):
    _write(
        tmp_path,
        "perk.toml",
        '[models.subagents]\npr-reviewer = "a/sonnet"\nreview-classifier = 3\n',
    )
    with pytest.raises(ConfigError, match="review-classifier"):
        load_config(tmp_path)


def test_subagents_selection_ignores_unknown_agent_key(tmp_path):
    _write(tmp_path, "perk.toml", '[models.subagents]\nbogus = "a/x"\n')
    assert load_config(tmp_path).subagents == {}


# --- [models.stages.<id>] per-stage model/thinking -------------------------------------------


def test_stage_models_absent_is_empty(tmp_path):
    assert load_config(tmp_path).stage_models == {}


def test_stage_models_parsed(tmp_path):
    _write(
        tmp_path,
        "perk.toml",
        '[models.stages.implement]\nmodel = "a/opus"\nthinking = "high"\n'
        '[models.stages.plan]\nthinking = "xhigh"\n',
    )
    assert load_config(tmp_path).stage_models == {
        "implement": StageModel(model="a/opus", thinking="high"),
        "plan": StageModel(model=None, thinking="xhigh"),
    }


def test_stage_models_model_only(tmp_path):
    _write(tmp_path, "perk.toml", '[models.stages.implement]\nmodel = "a/opus"\n')
    assert load_config(tmp_path).stage_models == {"implement": StageModel(model="a/opus")}


def test_stage_models_non_string_values_raise(tmp_path):
    _write(tmp_path, "perk.toml", "[models.stages.implement]\nmodel = 3\nthinking = true\n")
    with pytest.raises(ConfigError, match=r"stages\.implement"):
        load_config(tmp_path)


def test_stage_models_blank_values_normalize_to_none(tmp_path):
    _write(
        tmp_path, "perk.toml", '[models.stages.implement]\nmodel = "  a/opus  "\nthinking = "   "\n'
    )
    assert load_config(tmp_path).stage_models == {"implement": StageModel(model="a/opus")}


def test_stage_models_all_blank_subtable_omitted(tmp_path):
    _write(tmp_path, "perk.toml", '[models.stages.implement]\nmodel = "  "\nthinking = ""\n')
    assert load_config(tmp_path).stage_models == {}


def test_stage_models_empty_subtable_omitted(tmp_path):
    _write(tmp_path, "perk.toml", '[models.stages.foo]\n[models.stages.plan]\nthinking = "low"\n')
    assert load_config(tmp_path).stage_models == {"plan": StageModel(thinking="low")}


def test_stage_models_local_overlay_leaf_merges(tmp_path):
    _write(tmp_path, "perk.toml", '[models.stages.implement]\nmodel = "a/opus"\n')
    _write(tmp_path, "perk.local.toml", '[models.stages.implement]\nthinking = "high"\n')
    assert load_config(tmp_path).stage_models == {
        "implement": StageModel(model="a/opus", thinking="high")
    }


def test_stage_models_seeded_template_is_inert(tmp_path):
    _write(tmp_path, "perk.toml", PERK_TOML_TEMPLATE)
    assert load_config(tmp_path).stage_models == {}


# --- config schema v2 legacy-spelling tripwires ---------------------------------------


@pytest.mark.parametrize(
    ("legacy", "new_home"),
    [
        ('[trust]\nci = "true"\n', r"\[ci\] trusted"),
        ('[objective]\ncompact_threshold = "0.8"\n', r"\[compaction\] objective_threshold"),
        ('[stages.implement]\nmodel = "a/opus"\n', r"\[models\.stages\.<id>\]"),
        ('[subagents]\npr-reviewer = "a/sonnet"\n', r"\[models\.subagents\]"),
    ],
)
def test_legacy_toplevel_table_raises_with_new_home(tmp_path, legacy, new_home):
    # The hard tripwire: with extra="ignore" a retired spelling would silently vanish (the
    # documented config-tables trap) — instead every legacy table fails loudly, naming its home.
    _write(tmp_path, "perk.toml", legacy)
    with pytest.raises(ConfigError, match=new_home):
        load_config(tmp_path)


def test_legacy_ci_array_of_tables_raises(tmp_path):
    _write(tmp_path, "perk.toml", '[[ci]]\nname = "lint"\ncommand = "just lint"\n')
    with pytest.raises(ConfigError, match=r"\[\[ci\.checks\]\]"):
        load_config(tmp_path)


def test_new_ci_table_is_ignored_by_python(tmp_path):
    # The new [ci] is a dict (TS-read); Python drops it via extra="ignore" — no tripwire.
    _write(
        tmp_path,
        "perk.toml",
        '[ci]\ntrusted = true\n\n[[ci.checks]]\nname = "lint"\ncommand = "just lint"\n',
    )
    assert load_config(tmp_path).worktree_root == tmp_path / ".worktrees"


def test_legacy_table_in_local_overlay_raises(tmp_path):
    # The overlay merges before validation, so a legacy spelling in local.toml trips too.
    _write(tmp_path, "perk.toml", '[worktree]\nroot = "wt"\n')
    _write(tmp_path, "perk.local.toml", '[subagents]\npr-reviewer = "a/x"\n')
    with pytest.raises(ConfigError, match=r"\[models\.subagents\]"):
        load_config(tmp_path)


def test_legacy_models_model_key_raises(tmp_path):
    _write(tmp_path, "perk.toml", '[models]\nmodel = "anthropic/claude-opus-4-1"\n')
    with pytest.raises(ConfigError, match="renamed to default"):
        load_committed_models(tmp_path)
    with pytest.raises(ConfigError, match="renamed to default"):
        load_config(tmp_path)


# --- [compaction] committed-only read ------------------------------------------------


def test_compaction_absent_is_empty(tmp_path):
    assert load_committed_compaction(tmp_path) == {}


def test_compaction_seeded_template_is_inert(tmp_path):
    # The seeded `.perk/config.toml` carries only a *commented* [compaction] example.
    _write(tmp_path, "perk.toml", PERK_TOML_TEMPLATE)
    assert load_committed_compaction(tmp_path) == {}


def test_compaction_parses_all_keys_with_camelcase_mapping(tmp_path):
    _write(
        tmp_path,
        "perk.toml",
        "[compaction]\nenabled = false\nreserve_tokens = 8192\nkeep_recent_tokens = 10000\n",
    )
    assert load_committed_compaction(tmp_path) == {
        "enabled": False,
        "reserveTokens": 8192,
        "keepRecentTokens": 10000,
    }


@pytest.mark.parametrize("value", ["0", "-1"])
def test_compaction_nonpositive_token_value_raises(tmp_path, value):
    _write(tmp_path, "perk.toml", f"[compaction]\nreserve_tokens = {value}\n")
    with pytest.raises(ConfigError, match="reserve_tokens"):
        load_committed_compaction(tmp_path)


def test_compaction_lax_coercions_pinned(tmp_path):
    # The LenientParseModel house posture: a truthy string coerces to a bool and a numeric
    # string coerces to an int (both previously silently dropped).
    _write(tmp_path, "perk.toml", '[compaction]\nenabled = "yes"\nreserve_tokens = "8192"\n')
    assert load_committed_compaction(tmp_path) == {"enabled": True, "reserveTokens": 8192}


def test_compaction_bool_token_value_raises(tmp_path):
    # `bool` is an `int` subclass; `reserve_tokens = true` must NOT be read as 1 — the explicit
    # before-validator rejects it (previously silently dropped).
    _write(tmp_path, "perk.toml", "[compaction]\nreserve_tokens = true\n")
    with pytest.raises(ConfigError, match="reserve_tokens"):
        load_committed_compaction(tmp_path)


def test_compaction_non_table_value_raises(tmp_path):
    # A present non-dict `compaction` must raise, not vanish.
    _write(tmp_path, "perk.toml", 'compaction = "oops"\n')
    with pytest.raises(ConfigError):
        load_committed_compaction(tmp_path)


def test_compaction_is_committed_only_ignores_local_overlay(tmp_path):
    # The committed-only guarantee: perk.local.toml's [compaction] is NEVER read.
    _write(tmp_path, "perk.toml", "[compaction]\nenabled = true\n")
    _write(tmp_path, "perk.local.toml", "[compaction]\nenabled = false\nreserve_tokens = 999\n")
    assert load_committed_compaction(tmp_path) == {"enabled": True}


def test_compaction_objective_threshold_is_ignored_by_python(tmp_path):
    # `objective_threshold` is the TS-read sibling living in the same table; it must never map
    # into pi settings (extra="ignore" drops it here).
    _write(tmp_path, "perk.toml", "[compaction]\nenabled = true\nobjective_threshold = 0.8\n")
    assert load_committed_compaction(tmp_path) == {"enabled": True}


# --- [models] committed-only read -----------------------------------------------------


def test_models_absent_is_empty(tmp_path):
    assert load_committed_models(tmp_path) == {}


def test_models_empty_table_is_inert(tmp_path):
    _write(tmp_path, "perk.toml", "[models]\n")
    assert load_committed_models(tmp_path) == {}


def test_models_seeded_template_is_inert(tmp_path):
    # The seeded `.perk/config.toml` carries only a *commented* [models] example.
    _write(tmp_path, "perk.toml", PERK_TOML_TEMPLATE)
    assert load_committed_models(tmp_path) == {}


def test_models_default_alone_splits_provider_and_id(tmp_path):
    _write(tmp_path, "perk.toml", '[models]\ndefault = "anthropic/claude-opus-4-1"\n')
    assert load_committed_models(tmp_path) == {
        "defaultProvider": "anthropic",
        "defaultModel": "claude-opus-4-1",
    }


def test_models_thinking_alone(tmp_path):
    _write(tmp_path, "perk.toml", '[models]\nthinking = "high"\n')
    assert load_committed_models(tmp_path) == {"defaultThinkingLevel": "high"}


def test_models_thinking_suffix_split(tmp_path):
    _write(tmp_path, "perk.toml", '[models]\ndefault = "anthropic/claude-opus-4-1:high"\n')
    assert load_committed_models(tmp_path) == {
        "defaultProvider": "anthropic",
        "defaultModel": "claude-opus-4-1",
        "defaultThinkingLevel": "high",
    }


def test_models_non_vocab_suffix_stays_in_id(tmp_path):
    # The pi-subagents-shared suffix rule: a last-colon segment outside the thinking vocabulary
    # stays part of the model id (ollama-style tags are safe).
    _write(tmp_path, "perk.toml", '[models]\ndefault = "ollama/llama3:70b"\n')
    assert load_committed_models(tmp_path) == {
        "defaultProvider": "ollama",
        "defaultModel": "llama3:70b",
    }


def test_models_first_slash_split_keeps_openrouter_ids(tmp_path):
    _write(tmp_path, "perk.toml", '[models]\ndefault = "openrouter/meta-llama/llama-3-70b"\n')
    assert load_committed_models(tmp_path) == {
        "defaultProvider": "openrouter",
        "defaultModel": "meta-llama/llama-3-70b",
    }


def test_models_explicit_thinking_wins_over_suffix(tmp_path):
    _write(tmp_path, "perk.toml", '[models]\ndefault = "a/b:high"\nthinking = "low"\n')
    settings = load_committed_models(tmp_path)
    assert settings["defaultThinkingLevel"] == "low"
    assert settings["defaultModel"] == "b"  # the valid suffix is still stripped from the id
    # The conflict stays inspectable for doctor's warn.
    table = load_committed_models_table(tmp_path)
    assert table.suffix_thinking() == "high" and table.thinking == "low"


def test_models_default_without_slash_raises(tmp_path):
    _write(tmp_path, "perk.toml", '[models]\ndefault = "claude-opus-4-1"\n')
    with pytest.raises(ConfigError, match="provider/id"):
        load_committed_models(tmp_path)


def test_models_invalid_thinking_raises(tmp_path):
    # Hard ConfigError: a typo never converges into the committed settings.json.
    _write(tmp_path, "perk.toml", '[models]\nthinking = "hgih"\n')
    with pytest.raises(ConfigError, match="hgih"):
        load_committed_models(tmp_path)


def test_models_non_string_value_raises(tmp_path):
    _write(tmp_path, "perk.toml", "[models]\ndefault = 7\n")
    with pytest.raises(ConfigError):
        load_committed_models(tmp_path)


def test_models_non_table_value_raises(tmp_path):
    # A present non-dict `models` must raise, not vanish.
    _write(tmp_path, "perk.toml", 'models = "oops"\n')
    with pytest.raises(ConfigError):
        load_committed_models(tmp_path)


def test_models_is_committed_only_ignores_local_overlay(tmp_path):
    # The committed-only guarantee: perk.local.toml's [models] is NEVER read.
    _write(tmp_path, "perk.toml", '[models]\ndefault = "anthropic/claude-opus-4-1"\n')
    _write(tmp_path, "perk.local.toml", '[models]\ndefault = "other/model"\nthinking = "low"\n')
    assert load_committed_models(tmp_path) == {
        "defaultProvider": "anthropic",
        "defaultModel": "claude-opus-4-1",
    }


# --- [issues] committed-only read ----------------------------------


def test_issues_backend_absent_file_is_none(tmp_path):
    assert load_committed_issues_backend(tmp_path) is None


def test_issues_backend_seeded_template_is_inert(tmp_path):
    # The seeded `.perk/config.toml` carries only a *commented* [issues] example.
    _write(tmp_path, "perk.toml", PERK_TOML_TEMPLATE)
    assert load_committed_issues_backend(tmp_path) is None


def test_issues_backend_absent_table_is_none(tmp_path):
    _write(tmp_path, "perk.toml", '[worktree]\nroot = ".worktrees"\n')
    assert load_committed_issues_backend(tmp_path) is None


def test_issues_backend_reads_value(tmp_path):
    _write(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\n')
    assert load_committed_issues_backend(tmp_path) == "linear"


@pytest.mark.parametrize("value", ["true", "7"])
def test_issues_backend_illtyped_raises(tmp_path, value):
    _write(tmp_path, "perk.toml", f"[issues]\nbackend = {value}\n")
    with pytest.raises(ConfigError, match="backend"):
        load_committed_issues_backend(tmp_path)


@pytest.mark.parametrize("value", ['""', '"   "'])
def test_issues_backend_blank_is_none(tmp_path, value):
    _write(tmp_path, "perk.toml", f"[issues]\nbackend = {value}\n")
    assert load_committed_issues_backend(tmp_path) is None


def test_issues_backend_strips_surrounding_whitespace(tmp_path):
    # Stripped at the boundary (previously the raw value reached the resolver unstripped and
    # failed as an unknown backend).
    _write(tmp_path, "perk.toml", '[issues]\nbackend = "  github  "\n')
    assert load_committed_issues_backend(tmp_path) == "github"


def test_issues_backend_is_committed_only_ignores_local_overlay(tmp_path):
    # The committed-only guarantee: perk.local.toml's [issues] is NEVER read.
    _write(tmp_path, "perk.local.toml", '[issues]\nbackend = "linear"\n')
    assert load_committed_issues_backend(tmp_path) is None


def test_issues_backend_malformed_toml_raises(tmp_path):
    _write(tmp_path, "perk.toml", "[issues\nbackend =")
    with pytest.raises(tomllib.TOMLDecodeError):
        load_committed_issues_backend(tmp_path)


def test_issues_team_absent_file_is_none(tmp_path):
    assert load_committed_issues_team(tmp_path) is None


def test_issues_team_seeded_template_is_inert(tmp_path):
    _write(tmp_path, "perk.toml", PERK_TOML_TEMPLATE)
    assert load_committed_issues_team(tmp_path) is None


def test_issues_team_absent_table_is_none(tmp_path):
    _write(tmp_path, "perk.toml", '[worktree]\nroot = ".worktrees"\n')
    assert load_committed_issues_team(tmp_path) is None


def test_issues_team_reads_value(tmp_path):
    _write(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\nteam = "ENG"\n')
    assert load_committed_issues_team(tmp_path) == "ENG"


def test_issues_team_strips_surrounding_whitespace(tmp_path):
    _write(tmp_path, "perk.toml", '[issues]\nteam = "  ENG  "\n')
    assert load_committed_issues_team(tmp_path) == "ENG"


@pytest.mark.parametrize("value", ["true", "7"])
def test_issues_team_illtyped_raises(tmp_path, value):
    _write(tmp_path, "perk.toml", f"[issues]\nteam = {value}\n")
    with pytest.raises(ConfigError, match="team"):
        load_committed_issues_team(tmp_path)


@pytest.mark.parametrize("value", ['""', '"   "'])
def test_issues_team_blank_is_none(tmp_path, value):
    _write(tmp_path, "perk.toml", f"[issues]\nteam = {value}\n")
    assert load_committed_issues_team(tmp_path) is None


def test_issues_team_is_committed_only_ignores_local_overlay(tmp_path):
    _write(tmp_path, "perk.local.toml", '[issues]\nteam = "ENG"\n')
    assert load_committed_issues_team(tmp_path) is None


def test_issues_team_malformed_toml_raises(tmp_path):
    _write(tmp_path, "perk.toml", "[issues\nteam =")
    with pytest.raises(tomllib.TOMLDecodeError):
        load_committed_issues_team(tmp_path)


def test_local_linear_api_key_absent_file_is_none(tmp_path):
    assert load_local_linear_api_key(tmp_path) is None


def test_local_linear_api_key_reads_local_value(tmp_path):
    _write(tmp_path, "perk.local.toml", '[linear]\napi_key = "lin_api_abc"\n')
    assert load_local_linear_api_key(tmp_path) == "lin_api_abc"


def test_local_linear_api_key_strips_surrounding_whitespace(tmp_path):
    _write(tmp_path, "perk.local.toml", '[linear]\napi_key = "  lin_api_abc  "\n')
    assert load_local_linear_api_key(tmp_path) == "lin_api_abc"


def test_local_linear_api_key_is_local_only_ignores_committed(tmp_path):
    # The inverse of the committed-only readers: a committed perk.toml value is ignored.
    _write(tmp_path, "perk.toml", '[linear]\napi_key = "lin_api_committed"\n')
    assert load_local_linear_api_key(tmp_path) is None


def test_local_linear_api_key_absent_table_is_none(tmp_path):
    _write(tmp_path, "perk.local.toml", '[worktree]\nroot = ".worktrees"\n')
    assert load_local_linear_api_key(tmp_path) is None


@pytest.mark.parametrize("value", ["true", "7", '""', '"   "'])
def test_local_linear_api_key_illtyped_or_blank_is_none(tmp_path, value):
    _write(tmp_path, "perk.local.toml", f"[linear]\napi_key = {value}\n")
    assert load_local_linear_api_key(tmp_path) is None


def test_local_linear_api_key_seeded_template_is_inert(tmp_path):
    from perk.convergence.init import PERK_LOCAL_TOML_TEMPLATE

    _write(tmp_path, "perk.local.toml", PERK_LOCAL_TOML_TEMPLATE)
    assert load_local_linear_api_key(tmp_path) is None


def test_local_linear_api_key_malformed_toml_is_none(tmp_path):
    # Diverges from the committed-only readers: fail-soft (returns None, never raises).
    _write(tmp_path, "perk.local.toml", "[linear\napi_key =")
    assert load_local_linear_api_key(tmp_path) is None


# --- Pydantic model validation at the assembled `Config` boundary ----------------------------


def test_config_is_frozen():
    # The domain object is a frozen dataclass: mutation raises `FrozenInstanceError`.
    config = Config(worktree_root=Path("/tmp/x"))
    with pytest.raises(FrozenInstanceError):
        config.workflow_base = "x"  # ty: ignore[invalid-assignment]


def test_config_is_dataclass():
    # The domain-object-is-a-dataclass contract: both the type and a freshly loaded instance.
    assert dataclasses.is_dataclass(Config)


def test_load_config_returns_dataclass(tmp_path: Path):
    assert dataclasses.is_dataclass(load_config(tmp_path))


def test_config_rejects_non_coercible_field():
    # Runtime field validation lives in the `ConfigFileModel` parse boundary, not the dataclass.
    # A bare `str` where `list[str]` is required cannot be coerced -> ValidationError.
    with pytest.raises(ValidationError):
        ConfigFileModel.model_validate({"worktree": {"setup": "oops"}})


def test_config_user_bindings_round_trip():
    # The frozen dataclass carries the `Binding` list by identity (not rebuilt — bindings never
    # pass through a pydantic model on the config path; `parse_user_bindings` owns their seam).
    binding = Binding(trigger="stage:plan", skill="perk-plan", mode="nudge")
    config = Config(worktree_root=Path("/tmp/x"), user_bindings=[binding])
    assert config.user_bindings == [binding]
    assert config.user_bindings[0] is binding


# --- The CLI boundary (`PerkContext.config()`) ------------------------------------------------


def test_perk_context_maps_config_error_to_user_facing(tmp_path):
    _write(tmp_path, "perk.toml", "[workflow]\nbase = 7\n")
    ctx = PerkContext.for_test(cwd=tmp_path, repo_root=tmp_path)
    with pytest.raises(UserFacingCliError) as excinfo:
        ctx.config()
    assert "workflow.base" in excinfo.value.message
    assert "perk doctor" in excinfo.value.message
