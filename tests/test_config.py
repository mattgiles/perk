from pathlib import Path

from perk.config import load_config
from perk.init import PERK_TOML_TEMPLATE


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


def test_user_bindings_absent_is_empty(tmp_path):
    assert load_config(tmp_path).user_bindings == []


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
    _write(tmp_path, "perk.toml", '[providers]\nplan = "tombell-plan"\ntodo = "perk-checkpoints"\n')
    assert load_config(tmp_path).providers == {"plan": "tombell-plan", "todo": "perk-checkpoints"}


def test_providers_selection_local_overlay_wins(tmp_path):
    _write(tmp_path, "perk.toml", '[providers]\nplan = "perk-plan"\n')
    _write(tmp_path, "perk.local.toml", '[providers]\nplan = "tombell-plan"\n')
    assert load_config(tmp_path).providers == {"plan": "tombell-plan"}


def test_providers_selection_ignores_non_string_values(tmp_path):
    _write(tmp_path, "perk.toml", '[providers]\nplan = "perk-plan"\ntodo = 3\n')
    # Non-string `todo` is dropped (the resolver falls back to the seam default for it).
    assert load_config(tmp_path).providers == {"plan": "perk-plan"}
