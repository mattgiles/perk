"""The pure diff-anchor parser (`perk.github.diff_anchors`) — no subprocess, no gh."""

from perk.github import parse_diff_anchors

# --- fixtures -------------------------------------------------------------------------


def _modified_file_diff() -> str:
    """One file, two hunks: added, deleted, and context lines with distinct counters."""
    return (
        "diff --git a/src/mod.py b/src/mod.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/src/mod.py\n"
        "+++ b/src/mod.py\n"
        "@@ -1,3 +1,4 @@\n"
        " keep_one\n"
        "-old_two\n"
        "+new_two\n"
        "+new_three\n"
        " keep_three\n"
        "@@ -10,3 +11,2 @@\n"
        " keep_ten\n"
        "-old_eleven\n"
        " keep_twelve\n"
    )


def _new_file_diff() -> str:
    return (
        "diff --git a/added.py b/added.py\n"
        "new file mode 100644\n"
        "index 0000000..3333333\n"
        "--- /dev/null\n"
        "+++ b/added.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+line_one\n"
        "+line_two\n"
    )


def _deleted_file_diff() -> str:
    return (
        "diff --git a/gone.py b/gone.py\n"
        "deleted file mode 100644\n"
        "index 4444444..0000000\n"
        "--- a/gone.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-was_one\n"
        "-was_two\n"
    )


# --- side/line classification ---------------------------------------------------------


def test_added_lines_anchor_right():
    anchors = parse_diff_anchors(_modified_file_diff())
    assert anchors.check(path="src/mod.py", line=2, side="RIGHT") is None
    assert anchors.check(path="src/mod.py", line=3, side="RIGHT") is None


def test_deleted_lines_anchor_left():
    anchors = parse_diff_anchors(_modified_file_diff())
    assert anchors.check(path="src/mod.py", line=2, side="LEFT") is None
    assert anchors.check(path="src/mod.py", line=11, side="LEFT") is None


def test_context_lines_anchor_both_sides_across_hunks():
    anchors = parse_diff_anchors(_modified_file_diff())
    # Hunk 1: `keep_one` is old 1 / new 1; `keep_three` is old 3 / new 4.
    assert anchors.check(path="src/mod.py", line=1, side="LEFT") is None
    assert anchors.check(path="src/mod.py", line=1, side="RIGHT") is None
    assert anchors.check(path="src/mod.py", line=3, side="LEFT") is None
    assert anchors.check(path="src/mod.py", line=4, side="RIGHT") is None
    # Hunk 2: `keep_ten` is old 10 / new 11; `keep_twelve` is old 12 / new 12.
    assert anchors.check(path="src/mod.py", line=10, side="LEFT") is None
    assert anchors.check(path="src/mod.py", line=11, side="RIGHT") is None
    assert anchors.check(path="src/mod.py", line=12, side="LEFT") is None
    assert anchors.check(path="src/mod.py", line=12, side="RIGHT") is None


def test_side_mismatches_rejected():
    # Non-colliding numbering: LEFT 2 is a pure deletion (RIGHT 2 does not exist), RIGHT 6 is a
    # pure addition (LEFT 6 does not exist).
    diff = (
        "diff --git a/m.py b/m.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/m.py\n"
        "+++ b/m.py\n"
        "@@ -1,2 +1,1 @@\n"
        " kept\n"
        "-dropped\n"
        "@@ -50,1 +40,2 @@\n"
        " ctx\n"
        "+added\n"
    )
    anchors = parse_diff_anchors(diff)
    assert anchors.check(path="m.py", line=2, side="LEFT") is None
    assert anchors.check(path="m.py", line=41, side="RIGHT") is None
    # A `-` line is not RIGHT-anchorable, a `+` line is not LEFT-anchorable.
    assert anchors.check(path="m.py", line=2, side="RIGHT") == (
        "line 2 (RIGHT) is not part of the diff for m.py"
    )
    assert anchors.check(path="m.py", line=41, side="LEFT") == (
        "line 41 (LEFT) is not part of the diff for m.py"
    )


# --- file-boundary keying ---------------------------------------------------------------


def test_new_file_has_no_left_anchors():
    anchors = parse_diff_anchors(_new_file_diff())
    assert anchors.check(path="added.py", line=1, side="RIGHT") is None
    assert anchors.check(path="added.py", line=2, side="RIGHT") is None
    assert anchors.check(path="added.py", line=1, side="LEFT") is not None


def test_deleted_file_keys_on_old_path_left_only():
    anchors = parse_diff_anchors(_deleted_file_diff())
    assert anchors.check(path="gone.py", line=1, side="LEFT") is None
    assert anchors.check(path="gone.py", line=2, side="LEFT") is None
    assert anchors.check(path="gone.py", line=1, side="RIGHT") is not None


def test_rename_with_hunks_keys_on_new_path():
    diff = (
        "diff --git a/old/name.py b/new/name.py\n"
        "similarity index 90%\n"
        "rename from old/name.py\n"
        "rename to new/name.py\n"
        "index 5555555..6666666 100644\n"
        "--- a/old/name.py\n"
        "+++ b/new/name.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-before\n"
        "+after\n"
        " ctx\n"
    )
    anchors = parse_diff_anchors(diff)
    assert anchors.check(path="new/name.py", line=1, side="RIGHT") is None
    assert anchors.check(path="old/name.py", line=1, side="RIGHT") == "path not in the PR diff"


def test_binary_or_hunkless_file_present_but_empty():
    diff = (
        "diff --git a/pic.png b/pic.png\n"
        "index 7777777..8888888 100644\n"
        "Binary files a/pic.png and b/pic.png differ\n"
        "diff --git a/script.sh b/script.sh\n"
        "old mode 100644\n"
        "new mode 100755\n"
    )
    anchors = parse_diff_anchors(diff)
    # Binary files carry no ---/+++ headers, so the path is absent; a pure mode change too.
    # Both fail as "path not in the PR diff" — never a crash, never a bogus anchor.
    assert anchors.check(path="pic.png", line=1, side="RIGHT") == "path not in the PR diff"
    assert anchors.check(path="script.sh", line=1, side="RIGHT") == "path not in the PR diff"


def test_hunkless_file_with_headers_present_but_empty():
    # A file whose ---/+++ headers appear without hunks (e.g. a mode-only change in some diff
    # renderers): the path is KNOWN (present in the map) but nothing is commentable.
    diff = (
        "diff --git a/script.sh b/script.sh\n"
        "old mode 100644\n"
        "new mode 100755\n"
        "--- a/script.sh\n"
        "+++ b/script.sh\n"
    )
    anchors = parse_diff_anchors(diff)
    assert anchors.by_path["script.sh"] == frozenset()
    assert anchors.check(path="script.sh", line=1, side="RIGHT") == (
        "line 1 (RIGHT) is not part of the diff for script.sh"
    )


# --- counter integrity ------------------------------------------------------------------


def test_no_newline_marker_skipped_without_desync():
    diff = (
        "diff --git a/tail.txt b/tail.txt\n"
        "index 9999999..aaaaaaa 100644\n"
        "--- a/tail.txt\n"
        "+++ b/tail.txt\n"
        "@@ -1,2 +1,2 @@\n"
        " first\n"
        "-second\n"
        "\\ No newline at end of file\n"
        "+second!\n"
        "\\ No newline at end of file\n"
    )
    anchors = parse_diff_anchors(diff)
    assert anchors.check(path="tail.txt", line=2, side="LEFT") is None
    assert anchors.check(path="tail.txt", line=2, side="RIGHT") is None
    assert anchors.check(path="tail.txt", line=3, side="RIGHT") is not None


def test_file_header_after_hunk_not_misread_as_deletion():
    # `--- a/<path>` starts with `-`: hunk-count tracking must end the body first.
    diff = _modified_file_diff() + _deleted_file_diff()
    anchors = parse_diff_anchors(diff)
    assert set(anchors.by_path) == {"src/mod.py", "gone.py"}
    assert anchors.check(path="gone.py", line=1, side="LEFT") is None


def test_check_unknown_path_reason():
    anchors = parse_diff_anchors(_modified_file_diff())
    assert anchors.check(path="nope.py", line=1, side="RIGHT") == "path not in the PR diff"
