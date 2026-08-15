"""Docs-gate wiring proof: CI exercises every docs gate, structurally.

The docs coverage story spans four config surfaces — the root and site `package.json`
scripts, the `justfile` recipes, `.github/workflows/ci.yml`, and the `.perk/config.toml`
`[[ci.checks]]` rows. Each gate is only as real as its wiring: a dropped script or recipe
line would silently stop running a whole validation family while everything stays green.
These source-scan checks (the `test_docs_site_tokens.py` style) make the wiring itself
regression-tested: GitHub CI runs `just lint`/`just typecheck`/`just test`, those recipes
reach the site lint/typecheck/build/check surfaces, and the scope-aware `docs-check` row
keeps a docs-only in-session `run_ci` verifying the same gates.
"""

import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DOCS_CHECK_PYTEST_TARGETS = (
    "tests/test_user_docs_metadata.py",
    "tests/test_user_docs_cli_reference.py",
    "tests/test_explanation_boundary.py",
    "tests/test_user_docs_findability.py",
    "tests/test_docs_site_tokens.py",
    "tests/test_docs_gates.py",
    '"tests/test_packaging.py::test_docs_site_publish_isolation"',
)


def _recipe_body(name: str) -> str:
    """The indented body of one justfile recipe (`name`, with or without parameters)."""
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


def test_root_package_scripts_cover_the_docs_site():
    scripts = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
    # Site lint coverage pre-delivered by node 2.1 — verified here, not re-wired.
    assert scripts["lint"] == "biome check extension docs/site tools"
    assert scripts["docs:typecheck"] == "npm run typecheck --workspace docs/site"
    assert scripts["docs:check"] == "npm run check --workspace docs/site"


def test_site_package_scripts_carry_the_gate_commands():
    scripts = json.loads((REPO_ROOT / "docs/site/package.json").read_text(encoding="utf-8"))[
        "scripts"
    ]
    # `astro sync` first, so a fresh checkout (no gitignored `.astro/types.d.ts`) typechecks.
    assert scripts["typecheck"] == "astro sync && tsc --noEmit"
    # Build (schema/link/anchor/escape gates), then the explicit source/runtime vocabulary guard
    # plus the post-build checks outside `src/`.
    assert scripts["check"] == (
        'astro build && node --test "src/in-session-reference.test.mjs" "checks/**/*.test.mjs"'
    )


def test_justfile_recipes_reach_every_docs_gate():
    assert "npm run docs:typecheck" in _recipe_body("typecheck-js")
    assert "npm run docs:check" in _recipe_body("test")

    docs_check = _recipe_body("docs-check")
    pytest_lines = [line for line in docs_check.splitlines() if "uv run pytest" in line]
    assert len(pytest_lines) == 1, docs_check
    for target in DOCS_CHECK_PYTEST_TARGETS:
        assert target in pytest_lines[0], f"docs-check pytest line missing {target}"
    # Site lint + typecheck run INSIDE the docs gate too: docs-scoped files like tokens.css or
    # tsconfig.json match no code-suffix [[ci.checks]] glob, so the docs row must reach every
    # gate GitHub CI runs for them.
    assert "npx biome check docs/site" in docs_check
    assert "npm run docs:typecheck" in docs_check
    assert 'node --test --test-reporter=dot "docs/site/src/**/*.test.mjs"' in docs_check
    assert "npm run docs:check" in docs_check


def test_github_ci_runs_the_gate_recipes():
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for recipe in ("just lint", "just typecheck", "just test"):
        assert f"run: {recipe}" in workflow, f"ci.yml must run `{recipe}`"


def test_perk_ci_has_the_scope_aware_docs_check_row():
    config = tomllib.loads((REPO_ROOT / ".perk/config.toml").read_text(encoding="utf-8"))
    rows = [row for row in config["ci"]["checks"] if row["name"] == "docs-check"]
    assert len(rows) == 1, "expected exactly one docs-check [[ci.checks]] row"
    row = rows[0]
    assert row["command"] == "just docs-check"
    globs = row["glob"].split(",")
    # The four scope families: canonical docs, the site tree, the root Node manifests, and
    # the docs task configuration.
    members = ("docs/user-docs/**", "docs/site/**", "package.json", "package-lock.json", "justfile")
    for member in members:
        assert member in globs, f"docs-check glob missing {member}"
