---
title: Splitting a large Python module into a package — the script-generated recipe
read_when: You are splitting a large `perk/<mod>.py` into a `perk/<mod>/` package (preserving import paths), rewriting call-site bindings, proving a verbatim split is complete, or hitting the package-`__init__` submodule-import fallback / sorted-`__all__` F401 / hatchling auto-include facts.
---

# Splitting a Python module into a package

Turning a large single-file module (e.g. a ~2100-line `perk/github.py`) into a `perk/<mod>/`
package while **preserving every public import path** is mechanically risky if hand-edited. The
durable insight: treat it as a **script-generated** transform with completeness *proofs*, not a
careful manual edit. Validated by the `perk/github.py` → `perk/github/` split (plan #438 → PR #446).

## A plan that fronts the cycles + the census makes it a one-pass job

The two "deviations" in the #438 split — relocating the four generic issue/comment REST helpers into
`plans.py` to break an `objectives` ↔ `prs` import cycle, and a 9th collateral monkeypatch site —
were both **authored into the plan**, not discovered mid-implementation. A plan whose Findings front
a **cycle audit** + a **complete monkeypatch-target census** turns a 2100-line split into pure
mechanics. Do that investigation before writing the generator, not while debugging it.

## The script-generated recipe

For a large verbatim module→package split, a one-shot generator script is the safe path:

1. **Slice by line ranges** off the `git mv`'d original. **Commit 1 = a bare `git mv`** of the
   original to the *largest* resulting module (preserves blame); **commit 2 = the split**. Anchor
   the ranges with `grep -n '^(def |class |@|CONST =)'`, take generous ranges, and edge-strip each
   chunk.
2. **Rewrite bindings with call-site-only regexes** — paren/word-boundary-anchored (`\b_run\(`,
   `raise GitHubError\(`, `-> CommentResult`), **never bare-name** patterns. Docstrings cite names
   without a following paren (`` ``_run`` ``, `` :class:`CommentResult` ``), so paren-anchored
   patterns leave prose untouched for free. Apply **cross-module `module.X` rules before `_exec`
   rules** so already-prefixed names aren't double-hit.
3. **Prove block completeness with a name census**: `diff` the sorted `^(def |class )` and
   module-constant lines of the old file against `cat new_pkg/*.py`. Catches a dropped or duplicated
   block instantly.
4. **Prove binding completeness with per-consumer negative greps**: for each consumer module, grep
   each helper call **unprefixed** (`grep -E '(^|[^.\w])_run\(' | grep -v '_exec\.'`) — **empty
   output is the proof** that every call was rewritten.

## Confirmed Python-packaging facts

- **The partially-initialized-package submodule import fallback works.** `from perk.github import
  _exec` *inside a submodule* during the package's own `__init__` execution resolves (Python ≥3.5
  falls back to the submodule import on a partially-initialized package); `github._exec is
  perk.github._exec` holds. So submodules can import shared internals from the package root even
  mid-`__init__`.
- **A sorted `__all__` silences ruff F401 with no per-file-ignore.** Listing every re-export in a
  sorted `__all__` in the new `__init__.py` is enough — no `[tool.ruff] per-file-ignores` entry
  needed.
- **hatchling `packages = ["perk"]` auto-includes the new subpackage.** No `pyproject.toml` change;
  `tests/test_packaging.py` stayed green untouched.

## The run_ci-green-≠-committable trap on generated files

Pre-commit's `ruff format` reflowed one generator-emitted expression **after** `run_ci` passed,
failing the first commit. Always run the **pinned** `uv run ruff format` (a bare `uvx ruff`
disagreed with the pinned version on import-sorting) before committing generated files. See
`toolchain/ruff.md` for the full check-vs-format split.

## Cross-references

- `docs/learned/workflow/github-gateway.md` — the gateway this split produced (and where the
  relocated generic REST helpers broke the `objectives` ↔ `prs` cycle)
- `docs/learned/toolchain/ts-module-moves.md` — the TS sibling (two-commit mv + import sweep)
- `docs/learned/toolchain/ruff.md` — the check-vs-format split / pinned-formatter trap
