---
title: Converting perk to a uv-workspace root-package src-layout — the ty/pytest resolution traps, the byte-identical-wheel proof, and the member-pruning gotcha
read_when: You are converting or maintaining a uv-workspace root-package `src`-layout (`src/perk`, root `pyproject.toml` is both workspace root and perk's `[project]`), hit the ty-root/pytest dotted-import trap after moving to `src/`, need the byte-identical-wheel structural-only proof, are editing the lockstep config surfaces (wheel packages / sdist only-include / ty.src / ruff / the `__file__` resolvers) + the resolver-depth rule, or hit the `uv sync --all-packages` dev-member-pruning trap.
---

# The uv-workspace root-package `src`-layout conversion

perk moved from a flat `perk/` package at the repo root to a **uv-workspace root-package
`src`-layout**: the sources live under `src/perk/`, and the repo-root `pyproject.toml` is *both* the
workspace root **and** perk's own `[project]`. This is the durable arc of the traps that move
in lockstep with that layout — the ty/pytest resolution roots, the structural-only build proof, and
the dev-only workspace member's pruning behavior.

## The ty-root + editable-`src`-layout dotted-import trap

Changing `[tool.ty.environment] root` from `[".", "tests"]` to `["src", "tests"]` **silently drops
`.`** — and that break lands in **two planes at once**:

- **ty**: with `.` gone from `root`, a dotted cross-test import like `from tests._schemas import …`
  no longer resolves (`tests.*` is not on any root).
- **the pytest runtime**: the `src`-layout editable install puts `src/` on `sys.path`, **not** the
  repo root — so `import tests.…` fails at runtime too.

Two fixes exist:

1. Keep `.` in ty `root` **and** put the repo root on `sys.path` (pytest `pythonpath`); or
2. Convert the dotted imports to the suite's dominant **bare** form (`from _schemas import …`),
   which resolves via pytest's `tests/` rootdir insertion + ty's `tests` root.

perk chose (2) — matching the suite's dominant style. **Lesson:** when a `src`-layout move changes
ty/pytest resolution roots, audit **every** `from tests.<helper>` dotted call-site import, not just
the helper module's own internals — the break is at the *importers*, not the moved module.

## The "byte-identical wheel" proof is 261/263, not a literal `IDENTICAL`

To prove the `src` move is structural-only, build the wheel on base + branch and diff the payloads
(excluding `*.dist-info/`). The result is **not** a bare `IDENTICAL` — exactly **2 of 263 members
differ**: the two `__file__`-relative resolvers that had to move one level deeper
(`parent.parent` → `parents[2]`) in `src/perk/_resources.py` + `src/perk/__init__.py`.

Those changed lines are the **editable/dev-only fallback** — dead code in the *installed* wheel,
which resolves resources via `importlib.metadata` + the `_shared`/`_agents`/`_prompts` package data,
not the `__file__` walk. So runtime is unchanged and `METADATA` is identical.

**Lesson:** write the proof to enumerate the *allowed* diff (the resolver files) rather than
demanding a bare `IDENTICAL`. Note also: the **sdist** paths legitimately shift (`perk/…` →
`src/perk/…`), yet build the *identical wheel* — so it is the **wheel**, not the sdist, that is the
meaningful structural-only proof.

## Config surfaces that move in lockstep + the resolver-depth rule

The build backend stays **hatchling** (`uv_build` cannot map the sibling `shared/`→`perk/_shared`
force-includes — see `workflow/distribution.md`). Under hatchling, the lockstep edits for the `src`
move are:

- `[tool.hatch.build.targets.wheel] packages` `["perk"]` → `["src/perk"]` — hatchling **strips the
  `src/` prefix**, so the built wheel still contains `perk/…` (this is why the wheel stays
  byte-identical).
- sdist `only-include` `"perk"` → `"src/perk"`.
- `[tool.ty.src] include` and `[tool.ruff] include` repathed to `src/perk`.
- the two `__file__` resolvers `parent.parent` → `parents[2]` (one directory deeper).

**Force-includes stay unchanged** because the build root stays the repo-root `pyproject.toml`. This
is precisely *why root-package layout beats a nested/virtual-root layout*: no `../` external
force-include paths, no sdist→wheel round-trip breakage. `[tool.perk] self` stays at the root too.

## Two expected non-events

- **`uv lock` produces zero diff.** The root project's `source = { editable = "." }` is unchanged,
  and the `members = ["packages/*"]` glob matched nothing at the time of the move.
- **The global editable `perk` tool binary breaks mid-work** with `ModuleNotFoundError: No module
  named 'perk.cli.cli'` — a stale `uv tool install --editable` finder still expecting `perk/` at the
  repo root. Use `uv run perk` inside the worktree, and re-run `just install-cli` to repair. A
  dev-environment footgun, **not** a shipped regression.

## The `uv sync --all-packages` member-pruning trap

On uv 0.11.24, plain `uv sync` installs **only the root project + its dependency closure** and
**prunes** extraneous workspace members. So a **dev-only member that nothing depends on**
(`packages/perk-dev`) is pruned, and `import perk_dev` fails until you run `uv sync --all-packages`.

Both call sites use `--all-packages` so the dev member resolves in the shared test venv that
`tests/test_perk_dev_cli.py` depends on: the `justfile` `sync` recipe and `.github/workflows/ci.yml`.

Note the exact/inexact distinction: `uv run` performs an *inexact* sync (won't prune), but plain
`uv sync` is *exact* (does prune) — so **CI's explicit `uv sync` step is the one that matters**.

**Correction worth recording:** the plan asserted (reading uv-docs wording) that plain `uv sync`
installs *all* members editable — that is **false** on 0.11.24.

## Cross-references

- `docs/learned/workflow/distribution.md` — the never-published `perk-dev` member discipline (what
  gets published) and the KEEP-hatchling build-backend decision.
- `docs/learned/toolchain/python-package-splits.md` — the sibling module→package split recipe.
