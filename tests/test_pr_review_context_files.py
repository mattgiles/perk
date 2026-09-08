"""The review-context materialization leaf: layouts, byte-exact content, the size arithmetic
reviewer children page against, and the writer's propagated failure set."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from perk.cli.commands.pr.review.context_files import (
    MaterializedContext,
    context_dir_for,
    materialize_review_context,
)
from perk.state import cache

PI_READ_LINE_BOUND = 51_200


@dataclass(frozen=True)
class _Sections:
    pr_number: int
    body: str
    diff: str
    plan_body: str | None


def _single(
    tmp_path: Path,
    *,
    body: str = "does the thing\n",
    diff: str = "diff --git a/x b/x\n+new line\n",
    plan_body: str | None = "# Plan\n\nbody",
) -> MaterializedContext:
    top = _Sections(pr_number=42, body=body, diff=diff, plan_body=plan_body)
    return materialize_review_context(tmp_path / "ctx", top=top, members=(), combined_diff=None)


# ------------------------------------------------------------------------------ layouts


def test_single_pr_layout_writes_three_root_files_byte_exact(tmp_path):
    ctx = _single(tmp_path)
    assert ctx.context_dir == tmp_path / "ctx"
    assert ctx.members == () and ctx.combined_diff is None
    assert ctx.top.diff.path == ctx.context_dir / "diff.patch"
    assert ctx.top.body.path == ctx.context_dir / "body.md"
    assert ctx.top.plan_body is not None
    assert ctx.top.plan_body.path == ctx.context_dir / "plan.md"
    # Byte-exact: no trimming, no trailing-newline normalization in either direction.
    assert ctx.top.diff.path.read_bytes() == b"diff --git a/x b/x\n+new line\n"
    assert ctx.top.body.path.read_bytes() == b"does the thing\n"
    assert ctx.top.plan_body.path.read_bytes() == b"# Plan\n\nbody"
    assert sorted(p.name for p in ctx.context_dir.iterdir()) == ["body.md", "diff.patch", "plan.md"]


def test_single_pr_plan_file_absent_when_plan_body_is_none(tmp_path):
    ctx = _single(tmp_path, plan_body=None)
    assert ctx.top.plan_body is None
    assert not (ctx.context_dir / "plan.md").exists()
    assert sorted(p.name for p in ctx.context_dir.iterdir()) == ["body.md", "diff.patch"]


def test_stack_layout_writes_members_once_and_no_root_section_files(tmp_path):
    members = (
        _Sections(pr_number=1, body="body 1", diff="diff 1\n", plan_body="# Plan 301"),
        _Sections(pr_number=2, body="body 2", diff="diff 2\n", plan_body=None),
    )
    ctx = materialize_review_context(
        tmp_path / "ctx", top=members[-1], members=members, combined_diff="combined\n"
    )
    # The top aliases the last member's refs — the same objects, no second copy on disk.
    assert ctx.top is ctx.members[-1]
    assert [m.diff.path for m in ctx.members] == [
        ctx.context_dir / "stack" / "1" / "diff.patch",
        ctx.context_dir / "stack" / "2" / "diff.patch",
    ]
    assert ctx.members[0].plan_body is not None
    assert ctx.members[0].plan_body.path == ctx.context_dir / "stack" / "1" / "plan.md"
    assert ctx.members[1].plan_body is None
    assert not (ctx.context_dir / "stack" / "2" / "plan.md").exists()
    assert ctx.combined_diff is not None
    assert ctx.combined_diff.path == ctx.context_dir / "combined.patch"
    assert ctx.combined_diff.path.read_text(encoding="utf-8") == "combined\n"
    # NO root-level section files in stack mode.
    assert sorted(p.name for p in ctx.context_dir.iterdir()) == ["combined.patch", "stack"]
    assert (ctx.context_dir / "stack" / "2" / "diff.patch").read_text(
        encoding="utf-8"
    ) == "diff 2\n"


def test_stack_mode_requires_a_combined_diff_and_a_last_member_top(tmp_path):
    members = (_Sections(pr_number=1, body="", diff="", plan_body=None),)
    with pytest.raises(ValueError, match="combined diff"):
        materialize_review_context(
            tmp_path / "a", top=members[0], members=members, combined_diff=None
        )
    other = _Sections(pr_number=9, body="", diff="", plan_body=None)
    with pytest.raises(ValueError, match="last member"):
        materialize_review_context(tmp_path / "b", top=other, members=members, combined_diff="")


# ---------------------------------------------------------------------- size arithmetic


def test_ref_arithmetic_for_empty_text(tmp_path):
    ctx = _single(tmp_path, body="", diff="", plan_body="")
    for ref in (ctx.top.body, ctx.top.diff, ctx.top.plan_body):
        assert ref is not None
        assert ref.path.is_file() and ref.path.stat().st_size == 0
        assert (ref.bytes, ref.lines, ref.max_line_bytes) == (0, 0, 0)


def test_ref_arithmetic_without_trailing_newline_and_with_multibyte_line(tmp_path):
    # "é" is 2 bytes; the emoji is 4 bytes — bytes count UTF-8, not characters.
    diff = "short\n" + "é" * 10 + "\n" + "😀" * 3  # no trailing newline
    ctx = _single(tmp_path, diff=diff)
    ref = ctx.top.diff
    assert ref.bytes == len(diff.encode("utf-8")) == 6 + 20 + 1 + 12
    assert ref.lines == 3
    assert ref.max_line_bytes == 20


def test_ref_reports_the_oversized_line_reviewers_must_byte_slice(tmp_path):
    long_line = "+" + "x" * 60_000
    diff = "diff --git a/big b/big\n" + long_line + "\nlast\n"
    ctx = _single(tmp_path, diff=diff)
    assert ctx.top.diff.max_line_bytes == 60_001
    assert ctx.top.diff.max_line_bytes > PI_READ_LINE_BOUND
    assert ctx.top.diff.lines == 3
    assert ctx.top.body.max_line_bytes < PI_READ_LINE_BOUND


# ----------------------------------------------------------------------- dir placement


def test_context_dir_for_is_unique_per_invocation_and_names_pr_and_mode(tmp_path):
    a = context_dir_for(tmp_path, pr_number=42, stack=False, run_id="RUN")
    b = context_dir_for(tmp_path, pr_number=42, stack=False, run_id="RUN")
    s = context_dir_for(tmp_path, pr_number=42, stack=True, run_id="RUN")
    assert a != b
    assert a.parent == b.parent == s.parent
    assert a.parent == cache.run_scratch_dir(tmp_path, "RUN") / "review-context"
    assert a.name.startswith("pr-42-") and not a.name.startswith("pr-42-stack-")
    assert s.name.startswith("pr-42-stack-")
    assert len(a.name) == len("pr-42-") + 12


def test_context_dir_for_places_under_the_given_run_scratch_dir(tmp_path):
    path = context_dir_for(tmp_path, pr_number=7, stack=False, run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV")
    assert cache.run_scratch_dir(tmp_path, "01ARZ3NDEKTSV4RRFFQ69G5FAV") in path.parents
    # The directory is only named here — nothing is created until materialization.
    assert not path.exists()


def test_materialize_refuses_an_existing_context_dir(tmp_path):
    target = tmp_path / "ctx"
    target.mkdir()
    with pytest.raises(FileExistsError):
        materialize_review_context(
            target,
            top=_Sections(pr_number=1, body="", diff="", plan_body=None),
            members=(),
            combined_diff=None,
        )


# ---------------------------------------------------------------- propagated failure set


def test_os_error_propagates_unchanged(tmp_path):
    # The scratch path pre-exists as a FILE, so the directory mkdir fails with an OSError arm.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    with pytest.raises(OSError):
        materialize_review_context(
            blocker / "ctx",
            top=_Sections(pr_number=1, body="", diff="", plan_body=None),
            members=(),
            combined_diff=None,
        )


def test_unicode_encode_error_propagates_unchanged(tmp_path):
    with pytest.raises(UnicodeEncodeError):
        _single(tmp_path, body="lone surrogate: \udcff")
