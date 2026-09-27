"""Docs-gate wiring proof: CI exercises every docs gate, structurally.

The docs coverage story spans four config surfaces — the root and site `package.json`
scripts, the `justfile` recipes, `.github/workflows/ci.yml`, and the `.perk/config.toml`
`[[ci.checks]]` rows. Each gate is only as real as its wiring: a dropped script or recipe
line would silently stop running a whole validation family while everything stays green.
These source-scan checks (the `test_docs_site_tokens.py` style) make the wiring itself
regression-tested: GitHub CI runs `just lint`/`just typecheck`/`just test`, those recipes
reach the site lint/typecheck/build/check surfaces, and in-session `run_ci` reaches each
surface exactly once per changed-file class — the scope-aware `docs-check` row carries the
docs-scoped guards plus every Astro invocation (sync + typecheck, then build + post-build
checks) serially, as the ONLY row that runs Astro (two rows syncing Astro content at once race
on the same generated files), while site lint and the site unit tests ride the `lint-js` /
`test-js` rows' `docs/site/**` globs and the non-Astro typecheck rides independently globbed
rows over the root package scripts.
"""

import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DOCS_CHECK_PYTEST_TARGETS = (
    "tests/test_user_docs_metadata.py",
    "tests/test_user_docs_cli_reference.py",
    "tests/test_user_docs_reference_facts.py",
    "tests/test_explanation_boundary.py",
    "tests/test_user_docs_findability.py",
    "tests/test_docs_site_tokens.py",
    "tests/test_docs_site_system.py",
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
    # Site lint coverage is verified here, not re-wired; `packages/perk-dev` rides along for the
    # startup profiler's module tracer (.mjs) and its node:test smoke.
    assert scripts["lint"] == "biome check extension docs/site tools packages/perk-dev"
    assert scripts["docs:typecheck"] == "npm run typecheck --workspace docs/site"
    assert scripts["docs:check"] == "npm run check --workspace docs/site"


def test_site_package_scripts_carry_the_gate_commands():
    scripts = json.loads((REPO_ROOT / "docs/site/package.json").read_text(encoding="utf-8"))[
        "scripts"
    ]
    # `astro sync` first, so a fresh checkout (no gitignored `.astro/types.d.ts`) typechecks.
    assert scripts["typecheck"] == "astro sync && tsc --noEmit"
    # Build (schema/link/anchor/escape gates), then the two site tests that read the
    # `docs/user-docs/` corpus (the source/runtime vocabulary guard and the sidebar guard — so a
    # user-docs-only change, which skips `test-js`, still reaches them) plus the post-build
    # checks outside `src/`.
    assert scripts["check"] == (
        'astro build && node --test "src/in-session-reference.test.mjs" "src/sidebar.test.mjs" '
        '"checks/**/*.test.mjs"'
    )


def test_justfile_recipes_reach_every_docs_gate():
    # The GitHub CI recipes keep the full union: `just typecheck` reaches the site typecheck
    # through `typecheck-js`, and `just test` reaches the site build + checks.
    assert "npm run docs:typecheck" in _recipe_body("typecheck-js")
    assert "npm run docs:check" in _recipe_body("test")

    docs_check = _recipe_body("docs-check")
    commands = [line.strip() for line in docs_check.splitlines() if line.strip()]
    assert len(commands) == 3, docs_check
    pytest_lines = [line for line in commands if "uv run pytest" in line]
    assert len(pytest_lines) == 1, docs_check
    for target in DOCS_CHECK_PYTEST_TARGETS:
        assert target in pytest_lines[0], f"docs-check pytest line missing {target}"
    # Single-process: the docs-scoped cases are few and fast, so an xdist pool is pure spin-up
    # cost beside the two concurrent tier pools.
    assert "-n0" in pytest_lines[0]
    assert pytest_lines[0].index("-n0") < pytest_lines[0].index(DOCS_CHECK_PYTEST_TARGETS[0])
    # Sync + typecheck, THEN build: Astro runs serially inside this one row.
    assert "npm run docs:typecheck" in docs_check
    assert "npm run docs:check" in docs_check
    assert docs_check.index("npm run docs:typecheck") < docs_check.index("npm run docs:check")
    # De-duplication: site lint and the site unit tests reach `docs/site` through the
    # `lint-js`/`test-js` rows' globs, never again from inside the docs row.
    assert "biome check" not in docs_check
    assert "node --test" not in docs_check


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
    # Canonical/site docs, the perk-expert mirror, provider/schema authorities, root Node
    # manifests, and docs task configuration all select the fact/corpus guard family.
    members = (
        "docs/user-docs/**",
        "docs/site/**",
        "skills/perk-expert/**",
        "shared/providers.yaml",
        "shared/schemas/**",
        "package.json",
        "package-lock.json",
        "justfile",
    )
    for member in members:
        assert member in globs, f"docs-check glob missing {member}"


def _ci_rows() -> list[dict[str, str]]:
    config = tomllib.loads((REPO_ROOT / ".perk/config.toml").read_text(encoding="utf-8"))
    return config["ci"]["checks"]


def _row(name: str) -> dict[str, str]:
    rows = [row for row in _ci_rows() if row["name"] == name]
    assert len(rows) == 1, f"expected exactly one {name} [[ci.checks]] row"
    return rows[0]


def _recipe_dependencies(name: str) -> list[str]:
    """The prerequisite recipes named on one justfile recipe's header line."""
    for line in (REPO_ROOT / "justfile").read_text(encoding="utf-8").splitlines():
        match = re.match(rf"^{re.escape(name)}(\s[^:]*)?:(.*)$", line)
        if match:
            return match.group(2).split()
    raise AssertionError(f"justfile has no `{name}` recipe")


def _reaches_astro(command: str) -> bool:
    """Whether a `[[ci.checks]]` command reaches a docs-site npm script (every one runs Astro:
    `docs:typecheck` syncs content, `docs:check`/`docs:build` build) — directly, or through a
    `just` recipe's body or its prerequisite recipes."""
    if "docs:" in command:
        return True
    tokens = command.split()
    if len(tokens) < 2 or tokens[0] != "just":
        return False
    pending = [tokens[1]]
    seen: set[str] = set()
    while pending:
        recipe = pending.pop()
        if recipe in seen:
            continue
        seen.add(recipe)
        if "docs:" in _recipe_body(recipe):
            return True
        pending.extend(_recipe_dependencies(recipe))
    return False


def test_docs_check_is_the_only_astro_owner():
    rows = _ci_rows()
    assert [row["name"] for row in rows if _reaches_astro(row["command"])] == ["docs-check"]
    # The explicit shapes that would re-introduce a second Astro run: a docs-site script in any
    # other row, or a row that runs one of the aggregating recipes that reach it.
    aggregating = {"just typecheck-js", "just typecheck", "just test", "just ci"}
    for row in rows:
        assert row["command"] not in aggregating, f"{row['name']} runs an Astro-reaching recipe"
        if row["name"] != "docs-check":
            assert "docs:" not in row["command"], f"{row['name']} runs a docs-site script"


def test_site_tooling_reaches_docs_site_through_the_code_rows():
    # The coverage the docs row gave up: site lint and the site unit tests run from the code
    # rows whenever anything under `docs/site` changes.
    for name in ("lint-js", "test-js"):
        assert "docs/site/**" in _row(name)["glob"].split(","), f"{name} glob missing docs/site/**"


def test_typecheck_rows_point_at_the_root_package_scripts():
    scripts = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
    assert scripts["typecheck"] == "tsc --noEmit"
    assert scripts["prose-review:typecheck"] == "npm run typecheck --workspace tools/prose-review"

    assert _row("typecheck-js")["command"] == "npm run typecheck"
    prose_review = _row("typecheck-prose-review")
    assert prose_review["command"] == "npm run prose-review:typecheck"
    assert "tools/prose-review/**" in prose_review["glob"].split(",")

    # Every typecheck the `typecheck-js` recipe aggregates (the union GitHub CI runs) is reached
    # in-session: the site typecheck inside `docs-check`, every other one by its own row.
    recipe_scripts = {
        line.strip().removeprefix("npm run ")
        for line in _recipe_body("typecheck-js").splitlines()
        if line.strip().startswith("npm run ")
    }
    row_scripts = {
        row["command"].removeprefix("npm run ")
        for row in _ci_rows()
        if row["command"].startswith("npm run ")
    }
    assert "docs:typecheck" in _recipe_body("docs-check")
    assert recipe_scripts == row_scripts | {"docs:typecheck"}
