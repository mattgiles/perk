"""Python test-tier wiring proof: the full gates run the whole suite, the tiers complement it.

`just test-py`, `just test`, GitHub CI (`just test`) and perk's in-session `run_ci` (the
`[[ci.checks]]` `test-py` row) all run the **full default Python suite** — slow cases included.
`just test-py-fast` (`-m "not slow"`) and `just test-py-slow` (`-m slow`) are complementary
*selections* of that same suite, never a skip or a different regression standard. The wiring is
regression-tested because a stray `-m` on `test-py` or `test` would silently narrow every gate
while everything stays green, and an unquoted compound expression on a tier recipe would break
that recipe for every caller. Marker *validity* (a misspelt `slow`) is enforced natively by strict
collection (`strict_markers` in `pyproject.toml`) and is deliberately not mirrored here.

Self-contained by design: its own recipe parser, no import from another test module, and not part
of the `docs-check` pytest line (this is a gate-scope guard, not a docs gate).
"""

import re
import shlex
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

FULL_GATE_RECIPES = ("test-py", "test")
GUIDE_NAMED_RECIPES = (
    "just test-py",
    "just test-py-fast",
    "just test-py-slow",
    "just prose-review-test",
)
TESTING_GUIDE = REPO_ROOT / "docs/developers/testing.md"


def _recipe_body(name: str) -> str:
    """The indented body of one justfile recipe (`name`, with or without parameters).

    Raises when the recipe is missing so a renamed recipe fails loudly rather than vacuously.
    """
    lines = (REPO_ROOT / "justfile").read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if re.match(rf"^{re.escape(name)}(\s[^:]*)?:", line):
            body: list[str] = []
            for continuation in lines[index + 1 :]:
                if continuation and not continuation[0].isspace():
                    break
                body.append(continuation)
            return "\n".join(body)
    raise AssertionError(f"justfile has no `{name}` recipe")


def _pytest_line(body: str) -> str:
    """The single recipe line that invokes pytest."""
    lines = [line for line in body.splitlines() if "uv run pytest" in line]
    assert len(lines) == 1, f"expected exactly one `uv run pytest` line, got {lines!r}"
    return lines[0]


def _argv(line: str) -> list[str]:
    """What bash hands to `uv` when the recipe is called with no caller args.

    `{{args}}` is interpolated as one space-joined string (the justfile does not set
    `positional-arguments`), so with no caller args it vanishes and the rest is a plain bash
    command line — `shlex.split` models bash's word splitting and quote removal.
    """
    return shlex.split(line.replace("{{args}}", ""))


def _marker_filters(argv: list[str]) -> list[str]:
    """Every marker-expression option token: `-m`, `-m<expr>`, `--markexpr`, `--markexpr=<expr>`."""
    return [token for token in argv if token.startswith(("-m", "--markexpr"))]


def test_full_gate_recipes_run_the_whole_python_suite():
    pytest_lines: dict[str, str] = {}
    for recipe in FULL_GATE_RECIPES:
        line = _pytest_line(_recipe_body(recipe))
        filters = _marker_filters(_argv(line))
        assert filters == [], (
            f"`just {recipe}` carries the marker filter {filters!r} — that silently narrows every "
            f"gate built on it (`just test`, GitHub CI, run_ci's test-py row)"
        )
        pytest_lines[recipe] = line.strip()
    # The two full entrypoints must agree: ci.yml's `just test` and the config row's
    # `just test-py` are only the same gate while they run the same pytest invocation.
    assert pytest_lines["test"] == pytest_lines["test-py"], pytest_lines


def test_tier_recipes_select_complementary_markers():
    fast = _pytest_line(_recipe_body("test-py-fast"))
    slow = _pytest_line(_recipe_body("test-py-slow"))
    # Exact argv: the compound expression survives bash as one word, `-m` is the only added
    # option, and no `-n` is set (so `addopts`' xdist defaults and a caller's `-n0` both apply).
    assert _argv(fast) == ["uv", "run", "pytest", "-m", "not slow"]
    assert _argv(slow) == ["uv", "run", "pytest", "-m", "slow"]
    for line in (fast, slow):
        # Caller args ride on the END so `-n0`, `-k expr` and paths follow the tier selection.
        assert line.rstrip().endswith("{{args}}"), line


def test_perk_python_gate_runs_the_full_recipe():
    # ci.yml's `run: just test` is pinned by
    # tests/test_docs_gates.py::test_github_ci_runs_the_gate_recipes; this is the in-session twin.
    config = tomllib.loads((REPO_ROOT / ".perk/config.toml").read_text(encoding="utf-8"))
    rows = [row for row in config["ci"]["checks"] if row["name"] == "test-py"]
    assert len(rows) == 1, "expected exactly one test-py [[ci.checks]] row"
    assert rows[0]["command"] == "just test-py"
    assert rows[0]["glob"] == "*.py"


def test_testing_guide_names_every_tier_recipe():
    assert TESTING_GUIDE.is_file(), (
        f"{TESTING_GUIDE.relative_to(REPO_ROOT)} is the one canonical testing guide and must exist"
    )
    guide = TESTING_GUIDE.read_text(encoding="utf-8")
    for recipe in GUIDE_NAMED_RECIPES:
        assert f"`{recipe}`" in guide, f"testing guide does not name `{recipe}`"
    # Discoverable from both the developer-docs index and the README's Develop section.
    index = (REPO_ROOT / "docs/developers/index.md").read_text(encoding="utf-8")
    assert "(./testing.md)" in index, "docs/developers/index.md must link the testing guide"
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/developers/testing.md" in readme, "README must link the testing guide"
