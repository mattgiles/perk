# Python test-suite speedup, phase 2 — the resolve-boundary guard (Objective #2306, node 2.1)

Evidence record for the plan branch `plan-2361`: a **safety** record with **no timing section**.
`tests/test_resolve.py::TestConsumerBoundary::test_no_production_module_imports_the_substrate_directly`
asserted an empty offender list without ever proving it inspected a file, and its textual rule
matched zero real import statements. Safety-only work requires discriminating regression evidence,
not an invented timing claim, so the campaign is the two before/after faults in section 3. Summary
tables and verbatim lines only — no raw logs.

## 1. Scope and revisions

| Item | Value |
|---|---|
| Plan branch base revision (as measured) | `c81f4ac3` — clean (`git status --porcelain` empty before every fault edit and after every restore) |
| Candidate revision | `92538f06` — the single test-only commit on top of the base; clean before every fault edit and after every restore |
| Tools | Python 3.13.9 · pytest 9.0.3 · pytest-xdist 3.8.0 · uv 0.12.3 |
| Command (every run) | `uv run pytest -n0 -q tests/test_resolve.py -k ConsumerBoundary` |
| Timing | no timing samples were taken |

## 2. What changed and how it is classified

**The rule hole.** At the base revision the rule was `any(mod in line for mod in
SUBSTRATE_MODULES)` with `SUBSTRATE_MODULES = ("perk.backends.github.plans",
"perk.backends.github.objectives")` — a dotted-path substring. Across `src/perk/` it matches only
docstring lines (`backends/github/backend.py`, `backends/github/objective_store.py`). The three real
substrate import statements are all the package-level from-import shape (`from perk.backends.github
import plans` in `backends/github/backend.py` and `backends/github/objectives.py`; `from
perk.backends.github import objectives, plans` in `backends/github/objective_store.py`) — all inside
the allowed package, and all invisible to the substring. A consumer writing that shape outside the
package passed the old guard; production has zero relative imports, so this absolute from-import
shape was the real hazard.

**Helpers extracted.** Discovery and the per-line rule are lifted into module-level helpers the live
guard and the synthetic controls share: `_reaches_substrate(line)` (the rule), `_production_files(
perk_dir)` (discovery), `_substrate_offenders(perk_dir)` (the checker). Byte-identical behaviour was
kept for the walk (`Path(perk.__file__).parent.rglob("*.py")`, sorted), the exclusion
(`is_relative_to(perk_dir / "backends" / "github")`), strict decoding
(`read_text(encoding="utf-8")`, never `errors="ignore"`) and the diagnostic format
(`<path from the package parent>:<lineno>: <stripped line>`).

**Fail closed.** `_production_files` raises `AssertionError("production-file scan came up empty —
guard is vacuous")` on an empty walk, so the empty-discovery control exercises the exact code path
the live guard runs.

**The widening (strict superset).** `_reaches_substrate` keeps the substring predicate verbatim and
ORs in `SUBSTRATE_FROM_IMPORT = re.compile(r"^\s*from\s+perk\.backends\.github\s+import\s+.*\b(plans|objectives)\b")`
— the single-line absolute from-import shape.

**Anchors.** `LIVE_ANCHORS` = `backends/resolve.py` (the door), `backends/linear/backend.py` (a
sibling backend — the exclusion must not swallow all of `backends/`), `github/__init__.py` (the `gh`
gateway package sharing the `github` name; its docstring mentions the substrate as a slash path,
which is not a match). `EXCLUDED_ANCHOR` = `backends/github/plans.py` — must exist on disk and must
not be scanned.

**Collected cases** (`uv run pytest --collect-only -q tests/test_resolve.py -k ConsumerBoundary`):
`1/24 tests collected (23 deselected)` before → `4/27 tests collected (23 deselected)` after. The
four methods: the live guard (node id unchanged), `test_rule_matches_the_adapters_own_substrate_imports`
(a real import *statement* in each of the three adapter/substrate modules matches the rule —
docstring lines excluded), `test_checker_flags_prohibited_and_permits_neighbouring_synthetic_imports`
(one planted tree: the from-import hole and the dotted shape flagged with the exact payload; the
resolver, the adapter, `engagement` and the excluded package permitted), and
`test_checker_fails_closed_on_empty_discovery` (a tree whose only file is excluded raises).
`tests/test_resolve.py` is green serially (`27 passed`) and under the default `-n auto --dist
loadgroup` (`27 passed`).

**Classification: safety.** No speed benefit is claimed or measured.

## 3. Fault-injection evidence

Each fault was a temporary edit on a clean tree, run once against the old guard (base `c81f4ac3`,
before any edit) and once against the new guard (candidate `92538f06`), then restored with
`git restore <file>`; `git status --porcelain` printed nothing after every restore.

| Fault | Edit | Old guard (observed) | New guard (observed) |
|---|---|---|---|
| F-empty — empty walk | `tests/test_resolve.py`: the walker's `"*.py"` → `"*.nope"` (`1 file changed, 1 insertion(+), 1 deletion(-)`) | `1 passed, 23 deselected` — the demonstrated vacuity | `2 failed, 2 passed, 23 deselected`. `FAILED …::TestConsumerBoundary::test_no_production_module_imports_the_substrate_directly` and `FAILED …::TestConsumerBoundary::test_checker_flags_prohibited_and_permits_neighbouring_synthetic_imports`, both with `AssertionError: production-file scan came up empty — guard is vacuous` raised from `_production_files`; `test_checker_fails_closed_on_empty_discovery` and `test_rule_matches_the_adapters_own_substrate_imports` green |
| F-import — the from-import hole | `src/perk/backends/resolve.py`: `from perk.backends.github import plans  # fault` appended after the last line of the import block (`1 file changed, 1 insertion(+)`) | `1 passed, 23 deselected` — the real import shape escapes | `1 failed, 3 passed, 23 deselected`. `FAILED …::TestConsumerBoundary::test_no_production_module_imports_the_substrate_directly` with the offender line `perk/backends/resolve.py:25: from perk.backends.github import plans  # fault` under the message `substrate imports must go through perk.backends.resolve (resolve_issue_backend / resolve_objective_store); only perk/backends/github/ may import perk.backends.github.{plans,objectives}:`; every other method green |

The fault import executed without a cycle (`perk.backends.github.plans` does not import the
resolver). Dotted-import retention is proven by the retained substring predicate plus the
`learn/exporter.py` synthetic sample; exclusion targeting by the live included/excluded anchors —
neither needed a mutation run.

## 4. Observations and limitations

- The textual rule is a backstop, not a completeness proof: a relative import, a parenthesised
  multi-line import list, and `from perk.backends import github` followed by attribute access all
  escape it. Production has none of these shapes today (zero relative imports under `src/perk/`).
- `backends/github/engagement.py` is imported nowhere outside its package and is not a substrate
  module; the banned set stays `plans` + `objectives` (objective scope) and was not grown.
- `packages/perk-dev/src` is outside the walker (`Path(perk.__file__).parent`) and carries no
  `backends.github` / `backends/github` reference.
- `tests/conftest.py::source_corpus` (Git-backed `git ls-files`, `errors="ignore"` decoding) was
  deliberately not substituted: different discovery and decoding semantics.
- `docs/learned/workflow/issue-backend.md` describes this guard as "`SUBSTRATE_MODULES` = … one test
  covers both tiers", which now under-describes the rule (the from-import shape, the anchors, the
  fail-closed discovery, the controls). Learned docs change only via `/learn` — flagged here for
  that pass, not edited.
