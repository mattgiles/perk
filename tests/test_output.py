"""The leveled progress-log vocabulary (`log_step` / `log_done` / `log_warn`).

Each helper writes a glyph-prefixed, two-space-indented line to **stderr** (never stdout) and
emits **no ANSI escape sequence** — the glyph carries the semantics, no color.
"""

import pytest

from perk.substrate.output import log_done, log_step, log_warn


@pytest.mark.parametrize(
    ("fn", "glyph"),
    [(log_step, "\u203a"), (log_done, "\u2713"), (log_warn, "\u26a0")],
)
def test_log_helper_writes_glyph_prefixed_line_to_stderr(fn, glyph, capsys):
    fn("doing the thing")
    captured = capsys.readouterr()
    assert captured.out == ""  # nothing on stdout — --json consumers are unaffected
    assert captured.err == f"  {glyph} doing the thing\n"
    assert "\x1b[" not in captured.err  # glyph-only: no ANSI escape sequence
