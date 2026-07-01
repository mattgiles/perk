"""The leveled progress-log vocabulary (`log_step` / `log_done` / `log_warn`) and the `io_step`
context-manager seam that groups a step's attempt/done/warn messages at one call site.

Each helper writes a glyph-prefixed, two-space-indented line to **stderr** (never stdout). In
append mode (non-TTY — CliRunner, CI, piped stderr) the output is deterministic and carries **no
ANSI escape sequence**; in rewrite mode (interactive stderr, `NO_COLOR` unset, unwrapped line, no
interleaved output) the resolution rewrites the step line in place via cursor-up + erase-line.
"""

import sys
from pathlib import Path

import pytest

from perk.substrate.output import (
    io_step,
    log_done,
    log_step,
    log_warn,
    machine_output,
    user_output,
)

_REWRITE_PREFIX = "\x1b[1A\x1b[2K"  # cursor up one line + erase line


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


class TestIoStepAppendMode:
    """Non-TTY (CliRunner/CI/piped) behavior: the plain, deterministic two-line shape."""

    def test_done_emits_step_then_done_line(self, capsys):
        with io_step("fetching origin") as s:
            s.done("fetched origin")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "  \u203a fetching origin\n  \u2713 fetched origin\n"
        assert "\x1b[" not in captured.err

    def test_warn_emits_step_then_warn_line(self, capsys):
        with io_step("fetching origin") as s:
            s.warn("could not fetch origin")
        captured = capsys.readouterr()
        assert captured.err == "  \u203a fetching origin\n  \u26a0 could not fetch origin\n"
        assert "\x1b[" not in captured.err

    def test_clean_exit_auto_resolves_with_the_attempt_message(self, capsys):
        with io_step("running worktree setup"):
            pass
        captured = capsys.readouterr()
        assert captured.err == (
            "  \u203a running worktree setup\n  \u2713 running worktree setup\n"
        )

    def test_exception_escape_leaves_the_step_line_unresolved(self, capsys):
        with pytest.raises(RuntimeError, match="boom"), io_step("looking up plan #42"):
            raise RuntimeError("boom")
        captured = capsys.readouterr()
        assert captured.err == "  \u203a looking up plan #42\n"  # the dangling step pinpoints

    def test_second_resolution_appends_instead_of_raising(self, capsys):
        with io_step("step") as s:
            s.done("first")
            s.warn("second")  # defensive: append, never raise
        captured = capsys.readouterr()
        assert captured.err == "  \u203a step\n  \u2713 first\n  \u26a0 second\n"


@pytest.fixture
def rewrite_tty(monkeypatch, capsys):
    """Fake an interactive stderr (rewrite mode): TTY on, `NO_COLOR` unset, a wide terminal.

    Depends on `capsys` so sys-level capture is active, then patches `isatty` on the capture
    *class* (not the instance): capsys swaps in a fresh CaptureIO between fixture setup and the
    test body, so an instance patch would silently vanish before `io_step` reads it.
    """
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("COLUMNS", "120")
    monkeypatch.setattr(type(sys.stderr), "isatty", lambda self: True)
    return capsys


class TestIoStepRewriteMode:
    """Interactive-terminal behavior: the guarded in-place rewrite + its append fallbacks."""

    def test_resolution_rewrites_the_step_line_in_place(self, rewrite_tty):
        with io_step("looking up plan #42") as s:
            s.done("found plan #42")
        err = rewrite_tty.readouterr().err
        assert err == (f"  \u203a looking up plan #42\n{_REWRITE_PREFIX}  \u2713 found plan #42\n")

    def test_warn_resolution_also_rewrites(self, rewrite_tty):
        with io_step("fetching origin") as s:
            s.warn("could not fetch origin")
        err = rewrite_tty.readouterr().err
        assert f"{_REWRITE_PREFIX}  \u26a0 could not fetch origin\n" in err

    def test_interleaved_user_output_forces_plain_append(self, rewrite_tty):
        with io_step("step") as s:
            user_output("  $ some-command")
            s.done("done")
        err = rewrite_tty.readouterr().err
        assert "\x1b[" not in err
        assert err == "  \u203a step\n  $ some-command\n  \u2713 done\n"

    def test_interleaved_machine_output_forces_plain_append(self, rewrite_tty):
        with io_step("step") as s:
            machine_output('{"payload": true}')
            s.done("done")
        captured = rewrite_tty.readouterr()
        assert captured.out == '{"payload": true}\n'
        assert "\x1b[" not in captured.err
        assert captured.err == "  \u203a step\n  \u2713 done\n"

    def test_step_line_wider_than_terminal_forces_plain_append(self, rewrite_tty, monkeypatch):
        monkeypatch.setenv("COLUMNS", "20")
        with io_step("x" * 60) as s:  # wraps onto two rows — cursor-up would erase the wrong row
            s.done("done")
        err = rewrite_tty.readouterr().err
        assert "\x1b[" not in err

    def test_no_color_forces_plain_append(self, capsys, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setenv("COLUMNS", "120")
        monkeypatch.setattr(type(sys.stderr), "isatty", lambda self: True)
        with io_step("step") as s:
            s.done("done")
        err = capsys.readouterr().err
        assert "\x1b[" not in err
        assert err == "  \u203a step\n  \u2713 done\n"


def test_log_step_call_sites_confined_to_the_output_module():
    """Step lines go through `io_step` — a raw `log_step(` call site in production code is a step
    that can dangle. `log_step` stays public as `io_step`'s emitter (this suite pins its format),
    but the only production file allowed to call it is the output module itself. The pattern
    requires the call paren, so import lines never match; comments are not stripped — don't name
    the call form in prose (say "step line" instead)."""
    src_root = Path(__file__).resolve().parent.parent / "src" / "perk"
    allowed = src_root / "substrate" / "output.py"
    files = sorted(src_root.rglob("*.py"))
    assert files, "vacuous scan: src/perk yielded no Python files"
    assert allowed in files, "vacuous scan: the sanctioned seam file was not discovered"
    violations: list[str] = []
    allowed_matches = False
    for file in files:
        for lineno, line in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
            if "log_step(" not in line:
                continue
            if file == allowed:
                allowed_matches = True
                continue
            violations.append(f"{file.relative_to(src_root)}:{lineno}: {line.strip()}")
    assert allowed_matches, "vacuous scan: output.py itself no longer matches the pattern"
    assert not violations, (
        "raw log_step( call sites outside perk/substrate/output.py — narrate through io_step "
        "instead (it emits the step AND makes its resolution structural):\n" + "\n".join(violations)
    )
