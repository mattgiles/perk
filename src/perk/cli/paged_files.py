"""The ONE byte-exact paged-file writer + pointer measurement shared by every CLI worker that
hands large text to a model through a file (``pr review-context``, the objective node context).

Why files: the consumers are model sessions (fresh-context reviewer children, the planning
session) whose ``read`` tool refuses a single line above Pi's per-line bound (50 KiB) and whose
``bash`` keeps only the tail of an oversized output. A JSON string cannot be split across lines
by pretty-printing, so a large body inlined in a ``--json`` payload is unreadable by
construction. Writing the text to its own line-oriented file and returning a small pointer
(``{path, bytes, lines, max_line_bytes}``) lets the consumer page with ``read``/``grep``; the
pointer also carries the longest line's byte length so the consumer knows up front when a line
still exceeds the per-line bound and must fall back to
``sed -n 'Np' <path> | tail -c +<offset> | head -c`` byte slices.

Text is written byte-exact — no trimming, no newline normalization, no truncation: a reformatted
diff would break the ``line`` anchors reviewers report against, and a reformatted refinement would
no longer be "the entire decoded body, unchanged".

A CLI-neutral leaf beside ``emit.py`` / ``seed_file.py`` (command groups never import another
group's modules): it imports only ``perk.boundary`` and ``perk.substrate.fs`` (the atomic
writer, whose temp + ``replace`` seam is the durability story — no read-back here).
"""

from dataclasses import dataclass
from pathlib import Path

from perk.boundary import OutputModel
from perk.substrate.fs import atomic_write_text


@dataclass(frozen=True)
class TextFileRef:
    """A materialized text section: where it lives plus the sizes a pager needs up front.

    ``bytes`` is the UTF-8 length, ``lines`` the ``splitlines()`` count, and ``max_line_bytes``
    the UTF-8 length of the longest line — the number a reviewer child compares against Pi's
    per-line ``read`` bound (51,200 bytes) to decide whether a byte-slice fallback is needed.
    """

    path: Path
    bytes: int
    lines: int
    max_line_bytes: int


def measure_text(path: Path, text: str) -> TextFileRef:
    """The pointer for ``text`` as if it lived at ``path`` (pure — no I/O): UTF-8 byte length,
    ``splitlines()`` count, and the longest line's UTF-8 length (``0`` for empty text)."""
    lines = text.splitlines()
    return TextFileRef(
        path=path,
        bytes=len(text.encode("utf-8")),
        lines=len(lines),
        max_line_bytes=max((len(line.encode("utf-8")) for line in lines), default=0),
    )


def write_text_file(path: Path, text: str) -> TextFileRef:
    """Write ``text`` to ``path`` byte-exact through the atomic seam and return its pointer.

    The pointer is measured over the text handed to the writer, not read back from disk: the
    atomic writer's same-directory temp + ``replace`` either leaves the target untouched or
    fully replaced, so a read-back would add an I/O and an error arm without strengthening the
    guarantee. A repeat call overwrites atomically. Precondition: ``path.parent`` exists
    (callers ``mkdir``). Propagates the writer's failure set unchanged — ``OSError`` for the
    filesystem arms and ``UnicodeEncodeError`` for text UTF-8 cannot encode (a lone surrogate).
    """
    atomic_write_text(path, text)
    return measure_text(path, text)


class TextFileRefOut(OutputModel):
    """One materialized text section: its absolute ``path`` plus the sizes a reviewer pages
    against — ``max_line_bytes`` is the longest line's UTF-8 length (compared against Pi's
    per-line ``read`` bound to pick the byte-slice fallback)."""

    path: str
    bytes: int
    lines: int
    max_line_bytes: int

    @classmethod
    def from_domain(cls, ref: TextFileRef) -> "TextFileRefOut":
        return cls(
            path=str(ref.path),
            bytes=ref.bytes,
            lines=ref.lines,
            max_line_bytes=ref.max_line_bytes,
        )
