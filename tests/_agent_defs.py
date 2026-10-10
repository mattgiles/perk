"""The one frontmatter layout perk's subagent defs use for their descendant ceiling.

Every perk leaf def denies descendant launches in engine terms with a blank ``allowedAgents:``
line. pi-subagents' frontmatter parser (read at 0.76.1) stores a key with an empty value and no
indented continuation as ``""``, which its list parser turns into the empty list — the engine's
"deny every descendant launch" ceiling. The literal ``allowedAgents: []`` is a one-item list
``["[]"]`` that fails the ceiling's name pattern at def load, taking the def out of discovery;
an indented ``- name`` continuation would turn the blank value into a block list.

PyYAML reads the blank line as ``None``, so its view cannot stand in for the engine's; tests may
not import the installed engine either (``extension/installedPackageGuard.test.ts``,
``docs/developers/pi-subagents-reverify.md``). So this module pins the ONE mandated layout in raw
frontmatter text — the key alone on its line, directly after ``tools:`` and directly before the
column-zero ``systemPromptMode:`` key. It is a layout check, not a parser model; the engine's
acceptance and enforcement are measured live
(``docs/design/archive/pi-subagents-descendant-ceilings.md``).
"""

import re

_CEILING = re.compile(r"^allowedAgents:\s*$")
_CEILING_KEY = re.compile(r"^allowedAgents:")


def frontmatter_block(text: str) -> list[str]:
    """Return the lines between the leading ``---`` line and the next ``---`` line.

    CRLF is normalized first, mirroring the engine's slice. Text without a leading fence (or
    without a closing one) has no frontmatter block, so the result is empty.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0] != "---":
        return []
    try:
        end = lines.index("---", 1)
    except ValueError:
        return []
    return lines[1:end]


def assert_descendant_ceiling(text: str, path: object = "") -> None:
    """Assert the def's frontmatter carries the blank descendant ceiling in the mandated layout.

    Raises ``AssertionError`` naming ``path`` and the cause unless exactly one column-zero
    ``allowedAgents:`` line exists, its value is blank, the line before it is the column-zero
    ``tools:`` key, and the line after it is the column-zero ``systemPromptMode:`` key (so no
    indented continuation can turn the empty value into a block list).
    """
    block = frontmatter_block(text)
    keyed = [i for i, line in enumerate(block) if _CEILING_KEY.match(line)]
    if not keyed:
        raise AssertionError(f"{path}: allowedAgents descendant ceiling absent")
    if len(keyed) > 1:
        raise AssertionError(f"{path}: allowedAgents duplicate ({len(keyed)} lines)")
    index = keyed[0]
    if not _CEILING.match(block[index]):
        raise AssertionError(f"{path}: allowedAgents nonblank ({block[index]!r})")
    if index == 0 or not block[index - 1].startswith("tools:"):
        raise AssertionError(f"{path}: allowedAgents is not directly after the tools: line")
    if index + 1 >= len(block) or not block[index + 1].startswith("systemPromptMode:"):
        raise AssertionError(
            f"{path}: allowedAgents is not directly before the systemPromptMode: line"
        )
