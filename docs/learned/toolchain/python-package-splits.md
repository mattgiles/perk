---
title: Splitting a large Python module into a package — the script-generated recipe
read_when: You are splitting a large `perk/<mod>.py` into a `perk/<mod>/` package (preserving import paths), rewriting call-site bindings, proving a verbatim split is complete, hitting the package-`__init__` submodule-import fallback / sorted-`__all__` F401 / hatchling auto-include facts, applying the objective-#714 split-arc refinements (the seed-generous import-resolution loop, the monkeypatch-name-resolution contract, the module-object-vs-name-binding patch rule, constant-travels-with-helper, the E402 leaf data module, the `(stem,func)`-keyed guard ripple, the `__file__`→package-dir-glob source-scan-guard fix, the AST byte-identity recipe), or **folding a flat module into a package / a cross-package relocation** (the non-re-export census that misses type annotations + docstrings, patch-shape divergence across a fold, the four-really-five monkeypatch forms + ty's string-`setattr` hole, BSD-`sed`-`\b`-is-a-no-op, the E402-insert-after-FIRST-import trap, the vacuous-source-scan-guard-on-move, sibling-submodule imports avoiding the package-root cycle, or the package-organization north-star doc).
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

## Refinements from the objective-#714 split arc (linear_backend, init/doctor, objective/launch)

Objective #714 ("Dignified Python") re-ran this recipe across **three more applications** — #720
(the former ``linear_backend`` module — now `src/perk/backends/linear/` — → a 7-submodule package), #722 (`perk/convergence/doctor.py` →
a `doctor/` package), #726 (`perk/objective.py` → `perk/objective/` + the `run`/`launch` split) —
plus the long-method-extraction discipline (#732). The original recipe held; these are the durable
sharpenings.

- **The seed-generous import-resolution loop makes the upfront import census non-load-bearing.**
  Seed every new submodule the *full* external import header + *full* relative imports, then let
  `ruff --fix` (F401) trim the unused ones and `ruff` (F821) flag the few genuinely-missing
  cross-submodule references; `ty check` is the confirming oracle. You no longer need a perfect
  per-module import inventory before slicing — over-seed and let the linters converge it.
- **The composition audit must grep class-NAME usage across ALL function bodies, not just
  `__init__`s.** A constructor call inside a *method* body (e.g. a readiness probe constructing the
  backend) creates a submodule dependency that an `__init__`-only dependency graph misses; F821
  catches it post-trim regardless, but grep the class name everywhere so you place the submodule
  edge deliberately.
- **The monkeypatch contract is keyed on NAME RESOLUTION.** A relocated function reads its sibling
  helpers in its OWN submodule namespace, so a facade-level patch of a name that function reads
  *locally* misses. **Public names are a blind spot** an underscore-only grep won't catch. Some
  break loudly; others pass fragile-green (the patch silently no-ops). Census ANY test patching a
  name a relocated function reads as a sibling/local reference — not just the `_underscore` ones.
- **Module-OBJECT attribute patches survive a split for free; name-binding patches don't.** A test
  doing `monkeypatch.setattr(mod.os, "environ", …)` (patching an *attribute on an imported module
  object*) keeps working; one doing `monkeypatch.setattr(target, "os", …)` (rebinding the *name*
  `os` in `target`'s namespace) breaks if `os` no longer lives there. So the facade `__init__` must
  **re-import the patch-target modules** (`os`/`subprocess`/`git`/`github`/…) even when unused in
  `__init__`, listing them in `__all__` to silence F401 (re-export-for-tests is legitimate API).
  The explicit `import x as x` / `from perk import github as github` re-export-alias idiom is the
  F401 fix; `PLC0414` (useless-import-alias) is **not** enabled, so it needs no `# noqa`.
- **A constant used ONLY by a moved helper must travel WITH the helper** — define it in the owning
  submodule and re-export it on the facade. Defining it in `__init__` while the submodule imports it
  creates a facade↔submodule cycle. "Facade keeps X" means **resolvable on the facade**
  (re-export), not necessarily *defined in* `__init__`.
- **E402 forces a leaf data module** (e.g. `doctor/data.py`) for shared classes/constants, not
  "data in `__init__`" — a second import block placed after the class defs in `__init__` trips E402
  (module-level import not at top). Mirror the `linear_backend/_helpers` leaf: a dependency-light
  module holding the shared classes/constants that both the facade and the submodules import.
- **`(file_stem, func_name)`-keyed structural guards ripple on relocation.** Moving a function that
  carries a `subprocess.run` across files breaks the `_SANCTIONED_SUBPROCESS_WRAPPERS`-style guard
  (keyed on `(stem, func)`); only a full `just ci` catches it (targeted suites stay green). Census
  every `(stem, func)`-keyed guard when relocating a guarded function.
- **The `__file__`-based source-scan guard silently narrows to `__init__.py` under a package.**
  `Path(mod.__file__).read_text()` scans only `__init__.py` once `mod` is a package, so a guard that
  scanned a single-file module now misses everything in the submodules. Convert it to a package-dir
  glob (`Path(mod.__file__).parent.glob("*.py")`) and **re-verify it still fails** by planting +
  reverting a forbidden import. See `workflow/source-scan-guards.md`.
- **The AST byte-identity verification recipe.** Parse the pre-split blob with `ast`, pull each
  top-level def/class via `ast.get_source_segment`, and compare against `inspect.getsource` on the
  facade attribute. **Caveat:** `get_source_segment` omits the decorator line and drops trailing
  same-line comments — so strip `@`-decorator lines before comparing and treat trailing-comment-only
  diffs as identical.
- **Submodule-naming discipline.** Seam modules deliberately avoid clashing with sibling protocol
  modules (impl `backend.py`, not `issue_backend.py`; stores `objectives.py` / `project_store.py`).
- **Long-method extraction preserves the call-SEQUENCE.** When the test oracle asserts on the
  GraphQL query order (#732), the orchestrator keeps the once-only network resolutions and passes
  the resolved values *down* to the extracted helpers, so no network call is added / removed /
  reordered. Pure string recomputation inside a helper is fine — it adds no network call. See
  `workflow/linear-backend.md` for the originating selection-order oracle.

## Folds and cross-package relocations

The #714 recipe above covers a verbatim **split** (one file → a package, import paths preserved). A
later arc re-ran it for two harder shapes — **folding a flat module *into* an existing package** as a
non-re-exported submodule, and **relocating symbols *across* a package boundary**. These add
distinctions the split recipe doesn't cover (don't re-derive the monkeypatch/source-scan basics above —
these are the new edges).

- **Folding a flat module into a package as a NON-re-exported submodule.** When the old flat module was
  reachable *as the package name* and consumers wrote `pkg.<sym>`, folding it to a submodule **without
  re-exporting** means EVERY `pkg.<sym>` for a moved symbol must become an aliased submodule reference.
  A grep for the obvious call is **insufficient** — it misses **type annotations** (`def f(x: pkg.Type)`,
  an import-time `AttributeError`) and **module-docstring path references**. Use
  `python -c "import <every consumer module>"` as the **first oracle** (it surfaces missing-attribute
  breaks at import that grep won't). `git mv` ordering: move the **directory** first so the target
  exists, then `git mv` the flat files into it.

- **Monkeypatch targets diverge by patch SHAPE across a fold.** Three outcomes (this complements the
  "name-resolution" rule above): consumer-**attribute** patches **survive** if the alias name is
  preserved (the consumer re-binds the alias regardless of where it imports from);
  **absolute-module-path** patches **break** (the module no longer exists at that path); late-bound
  **package-attribute** patches must **move to the new owning module** (patching that module object
  covers all consumers that import it).

- **The cross-package relocation monkeypatch sweep — four (really five) forms, and ty has a HOLE.** A
  pure relocation across the package boundary is a type-resolution change, so **`ty check` catches
  missed import repoints and stale attribute references — but NOT
  `monkeypatch.setattr(mod, "NAME", ...)` (the attribute-name-as-a-STRING form)**, which is opaque to
  the type checker and raises only at runtime. **Never trust a green `ty` as proof the monkeypatch
  sweep is complete — run the full pytest suite too.** The five escalating forms: attribute access /
  single-line `setattr` / **multi-line `setattr`** (the regex must match the bare token so it spans
  line breaks — a multi-line `setattr` was the source of a 90-failure miss) / string-path (repoint to
  the substrate module path via late binding) / two-level `pkg.sub.NAME`. **Classify the moved-name set
  vs the stays-put set first; census the counts up front.**

- **macOS BSD `sed` `\b` is silently a no-op.** `sed -i '' 's/\bX\b/.../g'` does **nothing** but
  reports success — use a Python `re.sub(r"(?<![.\w])X\.", ...)` (or `perl -pe`) for any word-boundary
  replacement on macOS. The **negative-lookbehind** spares already-qualified names (don't re-prefix a
  `mod.X` that's already correct).

- **The E402 import-insertion-point trap.** Inserting a new top-level import "after the last `from perk`
  import" can land it **after** a file's mid-file `# noqa: E402` block, so an earlier module-level use
  `NameError`s at import. **Insert after the FIRST top-level `from perk` import.**

- **A source-scan boundary guard goes VACUOUS when its target moves.** A guard searching for
  `pkg.<fn>(` call patterns matches **nothing** once the functions move off `pkg` — silently passing
  forever (false-green). Re-anchor it to the NEW location (scan for dot-form imports of the new
  substrate package from production modules outside it) and **always run the self-check** (plant a
  violation, confirm FAIL, revert). See `workflow/source-scan-guards.md`.

- **Sibling-submodule imports avoid the package-root re-entry cycle.** A pure module moved *into* a
  package should import siblings via their **submodule paths directly** (not `from pkg import …`) and
  leave the package `__init__` **byte-unchanged** (the moved module NOT re-exported) — `__init__` loads
  fully first and never references the new module, so no cycle. The `import X as old_name` alias keeps
  existing call sites byte-identical (minimal-churn discipline). `ty check` (whole repo) is the
  completeness oracle for a pure rename.

- **The package-organization north-star (the durable rule, now without its doc).** This split arc was
  governed by a `perk/`-layering north-star — six governing principles, a reconciliation of known
  asymmetries, a target tree, and a staged A–D reorg roadmap. The planning doc that captured it
  (`docs/planning/package-organization.md`) was later **removed with the rest of `docs/planning/`**,
  so there is no live pointer to chase. The durable rule outlives the doc: **a `perk/` reorg should
  consult the established layering (the existing package structure + the codebase-design deep-module
  vocabulary) rather than re-deriving it ad hoc.**

The gateway-purification refinement from this same relocation arc lives in
`workflow/github-gateway.md` (hoisting a backend-specific read out of a neutral gateway into the
consumer).

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
- `docs/learned/toolchain/ty.md` — the narrowing oracle that confirms the seed-generous import loop
- `docs/learned/workflow/source-scan-guards.md` — the `__file__`→package-dir-glob guard fix
- `docs/learned/workflow/linear-backend.md` — the long-method-extraction call-sequence oracle (#732)
