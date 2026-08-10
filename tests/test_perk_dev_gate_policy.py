"""Gate-policy port tests (perk_dev.audit.gate_policy).

Behavior cases mirroring extension/substrate/toolGating.test.ts's paired allowed/blocked
lists in spirit — the plain Python copy must agree with the TS gate on the shared corpus.
"""

import pytest
from perk_dev.audit.gate_policy import is_read_only_bash_command, split_top_level_segments

ALLOWED = [
    "cat README.md",
    "cd x && grep -r y .",
    "git log --oneline -5",
    "git status",
    "gh pr view 1",
    "grep -iE 'a|b' f",  # quoted pipe must not split into a bare `b` segment
    "ls > /dev/null",  # /dev/null redirect is not a file write
    # The fd-dup carve-out neutralizes only the destructive scan; the leading command must
    # still be safe.
    "cat f 2>&1",
    "grep foo bar 2>&1",
    "ls -la 1>&2",
    "cat foo 2>/dev/null",
    "sed -n '1,10p' file",
    "cd repo && perk objective show 453 2>&1 | head -200",
    "gh search code registerTool --repo x/y",
    "gh auth status",
    "rg pattern src",
    "ast-grep run --pattern 'print($A)' --lang python .",
    "npx agent-browser skills get core",
]

BLOCKED = [
    "rm -rf x",
    "git commit -m x",
    "echo hi > file",
    "cat a >> file.txt",
    "cat a &> file.txt",
    "ls && rm x",  # destructive wins over a safe prefix
    "npx some-other-pkg",  # npx entry is anchored to agent-browser
    "touch f",
    "cmd 2>&1",  # fd-dup carve-out never makes a generic command safe
    "some-unknown-binary --flag",
    "git status && some-unknown-binary",  # per-segment: second segment non-safe
    "ls | rm -rf x",
    "gh api user",  # gh api stays blocked (can POST/PATCH)
    "gh issue view 12 > out.txt",  # destructive-wins blocks the redirect
    "code file.ts",  # the `code` editor in command position
    "ls; code .",
    "echo hi && code .",
    "cat $(code y)",
    "sudo reboot",
    "for f in a b c; do echo $f; done",
]


@pytest.mark.parametrize("cmd", ALLOWED)
def test_allowed(cmd: str):
    assert is_read_only_bash_command(cmd) is True, f"expected allowed: {cmd}"


@pytest.mark.parametrize("cmd", BLOCKED)
def test_blocked(cmd: str):
    assert is_read_only_bash_command(cmd) is False, f"expected blocked: {cmd}"


# --------------------------------------------------------------------- segments


def test_split_on_unquoted_sequencers():
    assert split_top_level_segments("a; b && c || d | e") == ["a", "b", "c", "d", "e"]


def test_split_keeps_quoted_operators_in_segment():
    assert split_top_level_segments("grep -iE 'a|b' f") == ["grep -iE 'a|b' f"]
    assert split_top_level_segments('echo "x && y"; ls') == ['echo "x && y"', "ls"]


def test_split_keeps_lone_ampersand_in_segment():
    # A lone `&` (background / part of `&>`) stays in-segment so the destructive veto
    # sees `&>` intact.
    assert split_top_level_segments("cat a &> f") == ["cat a &> f"]


def test_split_drops_empty_segments():
    assert split_top_level_segments("  ls ;; ; ") == ["ls"]


def test_split_empty_command_is_empty():
    assert split_top_level_segments("") == []
    assert is_read_only_bash_command("") is False
