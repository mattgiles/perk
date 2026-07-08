"""Pure unified-diff anchor parsing/validation (no subprocess — the gateway package is where
gh output shapes are parsed).

`perk pr review-submit` validates a review batch's `{path, line, side}` anchors against the PR's
merge-base 3-dot diff (`get_pr_diff`) *before* anything touches GitHub, so the agent repairs bad
anchors instead of burning an atomic review POST on a 422. The anchor model mirrors GitHub's
review-comment addressing: a `+` line anchors `("RIGHT", new_line)`, a `-` line anchors
`("LEFT", old_line)`, a context line anchors **both** sides.

Scope: single-line anchors only (mirrors `InlineReviewComment` and the guest-reviewer output
contract, §8.4 — no `start_line` ranges). Quoted/escaped `diff --git` paths (special-char
filenames) are out of scope: an unparsed path simply fails validation and the gateway's
last-resort ladder remains the backstop.
"""

import re
from dataclasses import dataclass

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

Anchor = tuple[str, int]
"""A commentable `(side, line)` pair — side ∈ `LEFT|RIGHT`, line on that side's numbering."""


@dataclass(frozen=True)
class DiffAnchors:
    """The commentable anchors of one PR diff: `path -> frozenset[(side, line)]`.

    A path present with an **empty** set is a file in the diff with nothing commentable
    (binary, pure mode-change/rename — no hunks)."""

    by_path: dict[str, frozenset[Anchor]]

    def check(self, *, path: str, line: int, side: str) -> str | None:
        """``None`` when ``(path, line, side)`` is anchorable, else a human-readable reason
        distinguishing the two failure classes (unknown path vs line-not-in-diff)."""
        anchors = self.by_path.get(path)
        if anchors is None:
            return "path not in the PR diff"
        if (side, line) not in anchors:
            return f"line {line} ({side}) is not part of the diff for {path}"
        return None


def _strip_prefix(header_path: str, prefix: str) -> str:
    """Strip the `a/`/`b/` prefix off a `---`/`+++` header path (kept verbatim otherwise)."""
    return header_path[len(prefix) :] if header_path.startswith(prefix) else header_path


def parse_diff_anchors(diff_text: str) -> DiffAnchors:
    """Walk a unified diff into its commentable anchor map.

    File boundaries come from `--- a/<old>` / `+++ b/<new>` header pairs; the file keys on the
    **new** path, except a deleted file (`+++ /dev/null`) keys on the old path — matching
    GitHub's comment addressing. Hunk bodies advance old/new line counters per marker
    (`' '` context → both sides, `'+'` → RIGHT/new, `'-'` → LEFT/old); `\\ No newline at end
    of file` markers are skipped without desyncing either counter.
    """
    by_path: dict[str, set[Anchor]] = {}
    current: set[Anchor] | None = None  # the current file's anchor set (None between files)
    old_path: str | None = None  # the pending `---` header, awaiting its `+++` pair
    old_line = 0
    new_line = 0
    # The hunk header's side counts delimit the body precisely — load-bearing: a `--- a/<path>`
    # header after a finished hunk starts with `-` and must NOT read as a deleted line.
    old_remaining = 0
    new_remaining = 0

    for raw in diff_text.splitlines():
        if old_remaining > 0 or new_remaining > 0:
            if raw.startswith("\\"):
                continue  # `\ No newline at end of file` — advances neither counter
            if raw.startswith("+"):
                if current is not None:
                    current.add(("RIGHT", new_line))
                new_line += 1
                new_remaining -= 1
            elif raw.startswith("-"):
                if current is not None:
                    current.add(("LEFT", old_line))
                old_line += 1
                old_remaining -= 1
            else:
                # A context line (leading space; an empty line is a stripped-space context line).
                if current is not None:
                    current.add(("RIGHT", new_line))
                    current.add(("LEFT", old_line))
                old_line += 1
                new_line += 1
                old_remaining -= 1
                new_remaining -= 1
            continue
        if raw.startswith("diff --git "):
            current = None
            old_path = None
            continue
        if raw.startswith("--- "):
            old_path = raw[4:]
            continue
        if raw.startswith("+++ ") and old_path is not None:
            new_path = raw[4:]
            if new_path == "/dev/null":
                key = _strip_prefix(old_path, "a/")
            else:
                key = _strip_prefix(new_path, "b/")
            current = by_path.setdefault(key, set())
            old_path = None
            continue
        match = _HUNK_RE.match(raw)
        if match and current is not None:
            old_line = int(match.group(1))
            new_line = int(match.group(3))
            old_remaining = int(match.group(2)) if match.group(2) is not None else 1
            new_remaining = int(match.group(4)) if match.group(4) is not None else 1

    return DiffAnchors(by_path={path: frozenset(anchors) for path, anchors in by_path.items()})
