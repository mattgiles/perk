"""Materialize `perk pr review-context`'s large text sections as paged files (the pointer envelope).

Why files: the command's consumers are fresh-context reviewer children whose `read` tool refuses
a single line above Pi's per-line bound (50 KiB) and whose `bash` keeps only the tail of an
oversized output. A JSON string cannot be split across lines by pretty-printing, so a large diff
inlined in the `--json` payload is unreadable by construction. Writing every free-text section
(PR body, per-PR diff, plan body, combined diff) to its own line-oriented file — and returning a
small envelope of file references — lets the child page with `read`/`grep`; each reference also
carries the longest line's byte length so the child knows up front when a line still exceeds the
per-line bound and must fall back to `sed -n 'Np' <path> | tail -c +<offset> | head -c` byte slices.

Layout (under a per-invocation directory — concurrent lanes never share one):

- single-PR mode: `diff.patch`, `body.md`, and `plan.md` (only when a plan body exists);
- stack mode: `combined.patch` + `stack/<pr>/{diff.patch,body.md,plan.md}` per member
  (bottom→top) and NO root-level section files — the top PR is the last member, referenced
  twice in the envelope but written exactly once.

Text is written byte-exact (no trimming, no newline normalization): a reformatted diff would
break the `line` anchors and hunk headers the reviewers report against.

A leaf beside the cache seam: imports `perk.state.cache` (the run scratch dir is the one
sanctioned scratch path root) and `perk.cli.paged_files` (the shared byte-exact paged-file
writer + `TextFileRef` measurement — the same leaf the objective node context writes through)
— never the command module.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from perk.cli.paged_files import TextFileRef, write_text_file
from perk.state import cache


@dataclass(frozen=True)
class MaterializedSections:
    """The three per-PR section files (``plan_body`` is None when the PR has no plan body)."""

    body: TextFileRef
    diff: TextFileRef
    plan_body: TextFileRef | None


@dataclass(frozen=True)
class MaterializedContext:
    """Everything one invocation wrote.

    In stack mode ``top`` IS ``members[-1]`` (the same :class:`TextFileRef` objects — no second
    copy on disk); in single-PR mode ``members == ()`` and ``combined_diff is None``.
    """

    context_dir: Path
    top: MaterializedSections
    members: tuple[MaterializedSections, ...]
    combined_diff: TextFileRef | None


class ContextSections(Protocol):
    """The structural shape both the gateway's ``PrReviewContext`` and the command's stack
    member satisfy — the only fields materialization reads."""

    @property
    def pr_number(self) -> int: ...

    @property
    def body(self) -> str: ...

    @property
    def diff(self) -> str: ...

    @property
    def plan_body(self) -> str | None: ...


def context_dir_for(repo_root: Path, *, pr_number: int, stack: bool, run_id: str) -> Path:
    """The per-invocation context directory under the run's scratch dir.

    ``pr-<n>[-stack]-<12-hex token>``: the token makes concurrent lanes fetching the same PR
    never share (or race on) a directory; the run-dir placement keeps the files gitignored and
    under the existing run-dir age GC.
    """
    suffix = "-stack" if stack else ""
    return (
        cache.run_scratch_dir(repo_root, run_id)
        / "review-context"
        / f"pr-{pr_number}{suffix}-{uuid.uuid4().hex[:12]}"
    )


def _write_sections(directory: Path, sections: ContextSections) -> MaterializedSections:
    directory.mkdir(parents=True, exist_ok=True)
    plan_body = sections.plan_body
    return MaterializedSections(
        body=write_text_file(directory / "body.md", sections.body),
        diff=write_text_file(directory / "diff.patch", sections.diff),
        plan_body=None if plan_body is None else write_text_file(directory / "plan.md", plan_body),
    )


def materialize_review_context(
    context_dir: Path,
    *,
    top: ContextSections,
    members: Sequence[ContextSections],
    combined_diff: str | None,
) -> MaterializedContext:
    """Create ``context_dir`` and write every text section into it (see the module layout).

    ``members`` empty selects single-PR mode (``combined_diff`` is ignored — None by contract);
    a non-empty ``members`` selects stack mode, where ``combined_diff`` is required (a None is a
    programmer error — the stack arm always renders one) and ``top`` must describe the last
    member (its files are referenced, never rewritten). An empty section string yields an
    existing empty file (``bytes 0, lines 0, max_line_bytes 0``).

    Propagates the writer's documented failure set unchanged: ``OSError`` for the filesystem
    arms (including a pre-existing ``context_dir`` — ``exist_ok=False`` keeps invocations from
    ever sharing a directory) and ``UnicodeEncodeError`` for text UTF-8 cannot encode (e.g. a
    lone surrogate). The command maps both to its ``write_failed`` arm.
    """
    context_dir.mkdir(parents=True, exist_ok=False)
    if len(members) == 0:
        return MaterializedContext(
            context_dir=context_dir,
            top=_write_sections(context_dir, top),
            members=(),
            combined_diff=None,
        )
    if combined_diff is None:
        raise ValueError("stack-mode materialization requires a combined diff")
    if members[-1].pr_number != top.pr_number:
        raise ValueError(
            f"stack-mode top (PR #{top.pr_number}) must be the last member "
            f"(PR #{members[-1].pr_number})"
        )
    written = tuple(
        _write_sections(context_dir / "stack" / str(member.pr_number), member) for member in members
    )
    return MaterializedContext(
        context_dir=context_dir,
        top=written[-1],
        members=written,
        combined_diff=write_text_file(context_dir / "combined.patch", combined_diff),
    )
