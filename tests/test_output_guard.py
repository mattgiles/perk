"""Bare-``print(`` source-scan regression guard.

Production Python code writes human-facing text through ``perk.substrate.output.user_output``
(stderr) and machine data through ``machine_output`` (stdout) — never a bare ``print(``. A
stray print corrupts the human/machine stream split (python-cli-guidelines.md §7) and dodges
the output-revision bookkeeping ``io_step`` relies on. Repo-wide ban, empty allowlist (the
output seam itself uses ``click.echo``, not ``print``); the scan covers production only —
test code may print freely.
"""

import re
from pathlib import Path

import perk

# A bare `print(` call site: not preceded by a word character or a dot, so `pprint(` and
# `self.print(` never false-positive.
PATTERN = re.compile(r"(?<![\w.])print\(")


def _perk_dir() -> Path:
    return Path(perk.__file__).parent


def _strip_comment(line: str) -> str:
    # Naive `#`-suffix stripping is enough here: no banned token plausibly appears inside a
    # string literal today (a `"print("` string would be its own smell), and prose mentions of
    # print( live in comments/docstring lines that either strip away or are real offenders.
    return re.sub(r"#.*$", "", line)


class TestOutputGuard:
    def test_no_production_module_calls_bare_print(self) -> None:
        """Source scan: no module under perk/ may call bare ``print(`` — route through the
        sanctioned seams instead."""
        perk_dir = _perk_dir()
        offenders: list[str] = []
        files = sorted(perk_dir.rglob("*.py"))
        # Self-checks: a layout change that empties the scan must fail loudly, not vacuously.
        assert files, "production-file scan came up empty — guard is vacuous"
        rel_names = {str(p.relative_to(perk_dir)) for p in files}
        assert "substrate/output.py" in rel_names, "scan missed output.py — guard is misaimed"
        assert "cli/commands/pr/land_cmd.py" in rel_names, (
            "scan missed land_cmd.py — guard is misaimed"
        )
        for path in files:
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if PATTERN.search(_strip_comment(line)):
                    offenders.append(
                        f"{path.relative_to(perk_dir.parent)}:{lineno}: {line.strip()}"
                    )
        assert not offenders, (
            "bare print( in production perk code — route human text through user_output and "
            "machine data through machine_output (perk.substrate.output):\n" + "\n".join(offenders)
        )

    def test_pattern_matches_a_bare_print_call(self) -> None:
        """Non-vacuous self-check: the pattern DOES catch a synthetic offender."""
        assert PATTERN.search('print("x")')
        assert PATTERN.search('    print(f"note: {exc}", file=sys.stderr)')

    def test_pattern_ignores_lookalikes(self) -> None:
        """``pprint(`` / ``self.print(`` / a commented print never false-positive."""
        assert not PATTERN.search("pprint(payload)")
        assert not PATTERN.search("self.print(payload)")
        assert not PATTERN.search(_strip_comment('user_output(msg)  # not print("x")'))
