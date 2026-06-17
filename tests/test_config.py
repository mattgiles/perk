import tomllib
from pathlib import Path

import pytest

from perk.convergence.init import PERK_TOML_TEMPLATE
from perk.substrate.config import (
    load_committed_compaction,
    load_committed_issues_backend,
    load_committed_issues_team,
    load_config,
    load_local_linear_api_key,
)


def _write(repo: Path, name: str, text: str) -> None:
    pi = repo / ".pi"
    pi.mkdir(parents=True, exist_ok=True)
    (pi / name).write_text(text, encoding="utf-8")


def test_defaults_when_absent(tmp_path):
    assert load_config(tmp_path).worktree_root == tmp_path / ".worktrees"


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


def test_worktree_setup_non_list_is_empty(tmp_path):
    _write(tmp_path, "perk.toml", '[worktree]\nsetup = "uv sync"\n')
    assert load_config(tmp_path).worktree_setup == []


def test_worktree_setup_filters_and_strips_entries(tmp_path):
    _write(tmp_path, "perk.toml", '[worktree]\nsetup = ["  uv sync  ", "", 7, "npm ci"]\n')
    assert load_config(tmp_path).worktree_setup == ["uv sync", "npm ci"]


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


def test_workflow_base_non_string_is_none(tmp_path):
    _write(tmp_path, "perk.toml", "[workflow]\nbase = 7\n")
    assert load_config(tmp_path).workflow_base is None


def test_workflow_base_blank_is_none(tmp_path):
    _write(tmp_path, "perk.toml", '[workflow]\nbase = "   "\n')
    assert load_config(tmp_path).workflow_base is None


def test_workflow_base_local_overrides_committed(tmp_path):
    _write(tmp_path, "perk.toml", '[workflow]\nbase = "develop"\n')
    _write(tmp_path, "perk.local.toml", '[workflow]\nbase = "release"\n')
    assert load_config(tmp_path).workflow_base == "release"


def test_seeded_template_is_inert(tmp_path):
    # The seeded `.pi/perk.toml` carries a *commented* [[bindings]] example; it must
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


# --- [providers] selection (Node 2.1) -------------------------------------------------------


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


def test_providers_selection_ignores_non_string_values(tmp_path):
    _write(tmp_path, "perk.toml", '[providers]\nplan = "perk-plan"\ntodo = 3\n')
    # Non-string `todo` is dropped (the resolver falls back to the seam default for it).
    assert load_config(tmp_path).providers == {"plan": "perk-plan"}


# --- [subagents] selection (#196) -----------------------------------------------------------


def test_subagents_selection_absent_is_empty(tmp_path):
    assert load_config(tmp_path).subagents == {}


def test_subagents_selection_parsed(tmp_path):
    _write(
        tmp_path,
        "perk.toml",
        '[subagents]\npr-reviewer = "a/sonnet"\nreview-classifier = "a/haiku"\n'
        'objective-explorer = "a/haiku2"\nconflict-resolver = "a/sonnet2"\n',
    )
    assert load_config(tmp_path).subagents == {
        "pr-reviewer": "a/sonnet",
        "review-classifier": "a/haiku",
        "objective-explorer": "a/haiku2",
        "conflict-resolver": "a/sonnet2",
    }


def test_subagents_selection_local_overlay_wins(tmp_path):
    _write(tmp_path, "perk.toml", '[subagents]\npr-reviewer = "base/model"\n')
    _write(tmp_path, "perk.local.toml", '[subagents]\npr-reviewer = "local/model"\n')
    assert load_config(tmp_path).subagents == {"pr-reviewer": "local/model"}


def test_subagents_selection_ignores_non_string_values(tmp_path):
    _write(tmp_path, "perk.toml", '[subagents]\npr-reviewer = "a/sonnet"\nreview-classifier = 3\n')
    assert load_config(tmp_path).subagents == {"pr-reviewer": "a/sonnet"}


def test_subagents_selection_ignores_unknown_agent_key(tmp_path):
    _write(tmp_path, "perk.toml", '[subagents]\nbogus = "a/x"\n')
    assert load_config(tmp_path).subagents == {}


# --- [compaction] committed-only read (#206) ------------------------------------------------


def test_compaction_absent_is_empty(tmp_path):
    assert load_committed_compaction(tmp_path) == {}


def test_compaction_seeded_template_is_inert(tmp_path):
    # The seeded `.pi/perk.toml` carries only a *commented* [compaction] example.
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


def test_compaction_drops_illtyped_and_nonpositive_values(tmp_path):
    _write(
        tmp_path,
        "perk.toml",
        # `enabled` non-bool, `reserve_tokens` zero, `keep_recent_tokens` negative → all dropped.
        '[compaction]\nenabled = "yes"\nreserve_tokens = 0\nkeep_recent_tokens = -1\n',
    )
    assert load_committed_compaction(tmp_path) == {}


def test_compaction_drops_bool_token_value(tmp_path):
    # `bool` is an `int` subclass; `reserve_tokens = true` must NOT be read as 1.
    _write(tmp_path, "perk.toml", "[compaction]\nreserve_tokens = true\n")
    assert load_committed_compaction(tmp_path) == {}


def test_compaction_is_committed_only_ignores_local_overlay(tmp_path):
    # The committed-only guarantee: perk.local.toml's [compaction] is NEVER read.
    _write(tmp_path, "perk.toml", "[compaction]\nenabled = true\n")
    _write(tmp_path, "perk.local.toml", "[compaction]\nenabled = false\nreserve_tokens = 999\n")
    assert load_committed_compaction(tmp_path) == {"enabled": True}


# --- [issues] committed-only read (objective #252 node 1.3) ----------------------------------


def test_issues_backend_absent_file_is_none(tmp_path):
    assert load_committed_issues_backend(tmp_path) is None


def test_issues_backend_seeded_template_is_inert(tmp_path):
    # The seeded `.pi/perk.toml` carries only a *commented* [issues] example.
    _write(tmp_path, "perk.toml", PERK_TOML_TEMPLATE)
    assert load_committed_issues_backend(tmp_path) is None


def test_issues_backend_absent_table_is_none(tmp_path):
    _write(tmp_path, "perk.toml", '[worktree]\nroot = ".worktrees"\n')
    assert load_committed_issues_backend(tmp_path) is None


def test_issues_backend_reads_value(tmp_path):
    _write(tmp_path, "perk.toml", '[issues]\nbackend = "linear"\n')
    assert load_committed_issues_backend(tmp_path) == "linear"


@pytest.mark.parametrize("value", ["true", "7", '""', '"   "'])
def test_issues_backend_illtyped_or_blank_is_none(tmp_path, value):
    _write(tmp_path, "perk.toml", f"[issues]\nbackend = {value}\n")
    assert load_committed_issues_backend(tmp_path) is None


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


@pytest.mark.parametrize("value", ["true", "7", '""', '"   "'])
def test_issues_team_illtyped_or_blank_is_none(tmp_path, value):
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
