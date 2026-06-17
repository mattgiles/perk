# Adversarial review — TESTS & VALIDATION ADEQUACY (perk #633, branch plan-633)

Scope: judge test layer + assertion strength + coverage gaps for "let plans/objectives target a
non-default base branch". Evidence from the repo/diff, not conversation history.

`just ci` proxy: all changed suites pass — `pytest` on the 11 changed files = **335 passed**;
`node --test` on the 3 changed `.test.ts` files = **67 pass / 0 fail**. So the *added* tests are
green. The findings below are about what is **not** tested, not failures.

## Test-plan → test mapping (plan's `## Test plan`)

| Plan bullet | Satisfied? | Evidence |
|---|---|---|
| `PlanHeader`/`PlanRef` round-trip `base`; `"base" in PLAN_HEADER_FIELDS` | ✅ | `test_plan.py::test_plan_header_base_round_trips`, `::test_plan_ref_base_in_to_data`, shape tests assert `base is None` default |
| config `[workflow] base` parse; absent/non-string → None | ✅ (exceeds) | `test_config.py` — string, strip, non-string, blank, absent, **local-overrides-committed** |
| `objective create --base` stores base; config-pin; neither→none | ✅ **GitHub path only** | `test_objective_cmd.py::test_create_base_{flag_stored,from_config,flag_wins_over_config,none_when_unset}` — all assert `captured["base"]` on a monkeypatched `create_objective_issue` |
| plan-save inherits objective base into header+ref; config-pin; re-save preserves; precedence; fail-soft get_objective | ✅ | `test_plan_save.py` — `pins_base_from_config`, `inherits_objective_base`, `objective_without_base_falls_through`, `get_objective_failure_falls_through`, `no_base_anywhere_is_none`, `resave_preserves_base` |
| `resolve_base` with plan_base; explicit --base wins; no plan_base→detect_trunk | ✅ (pure-fn) + resumed-branch | `test_launch.py::test_resolve_base_*` (4 tests) |
| submit resolves base from plan-ref→header→default, passes to create_pr + probe | ✅ | `test_pr_submit.py::test_submit_targets_pinned_base_from_plan_ref`, `::test_submit_falls_back_to_header_then_default_base` |
| `reconstruct_plan_ref` carries base | ✅ | `test_resume.py::test_reconstruct_plan_ref_carries_base` |
| TS: draft base persists write/read | ✅ | `objectiveDraft.test.ts` core write/read + omit-when-absent |
| TS: `saveObjective`/`objectiveApprovalSave` push/omit `--base`; tool decode | ✅ | `objectiveSave.test.ts` 3 tests |
| TS: `decodePlanRef` carries base | ⚠️ partial | `planSave.test.ts::"...active_plan_ref"` — present-string case only |

## Findings (prioritized)

### MAJOR 1 — Linear base persistence is signature-only, never asserted (confirms the suspicion)
The plan's "Key changes" explicitly changes **both** Linear stores
(`perk/backends/linear_backend.py`: `LinearObjectiveStore.create_objective` ~L1234 and
`LinearProjectObjectiveStore.create_objective` ~L1606) to thread `base` into the composed
`objective-header` block. **No test asserts either Linear path actually persists `base`.** The only
"Linear-side" diffs in tests are passive signature sync:
- `tests/test_objective_store.py` — `_FakeObjectiveStore.create_objective` just gains `base: str | None = None` (a fake; asserts nothing).
- `tests/test_objective_stores.py::TestGitHubDelegation` — adds `"base": None` to the **GitHub** delegation expectation (not Linear).

`tests/test_linear_backend.py` / `test_linear_lifecycle.py` got **zero** base coverage (grep:
no `base` create-objective assertion in any `test_linear*.py`). A regression dropping `base=base`
from either `ObjectiveHeader(...)` — especially the **project-backed** composer, which the plan
itself flags as a separate concern ("The project-backed overview header composer must include
`base`") — would ship green.
- *Suggested tests:* in `test_linear_backend.py`, call `LinearObjectiveStore.create_objective(..., base="develop")` against the existing `FakeLinearWorkspace`/scripted-GraphQL fake and assert the created issue/document body contains the rendered `objective-header` `base` (inline-code form). Add the parallel test for `LinearProjectObjectiveStore.create_objective(..., base="develop")` asserting the project overview header carries it. Also add a `base=None` negative (header omits `base`, body byte-unchanged vs today).

### MAJOR 2 — No end-to-end worktree materialization test proving the branch is cut from `origin/<base>`
All four new `resolve_base` tests are **pure-function** (`resolve_base(tmp_path, "plan-42", None,
"develop") == "origin/develop"`). The integration glue added to `resolve_worktree` in
`perk/run/launch.py` is **entirely untested**:
- reading `plan_ref.get("base")` + the `isinstance(...) and .strip()` guard,
- threading `plan_base` into `resolve_base` on both the materialize and dry-run arms.

There is a ready-made e2e harness — `git_repo_with_remote` +
`test_create_bases_off_fresh_origin_trunk` (L995) asserts `_sha(wt) == advanced` to prove the cut
point — but **no #633 test extends it**. `_PLAN_REF` (L28) has no `base`, so every existing e2e
test exercises only the default path. The reviewer's specific ask (worktree cut from
`origin/develop`) is unmet.
- *Suggested test:* push an `origin/develop` distinct from `origin/main` in `git_repo_with_remote`, `cache.write_plan_ref(clone, {**_PLAN_REF, "base": "develop"})`, run `launch_stage(..., dry_run=False)`, assert the new worktree HEAD `_sha(wt) == _sha(clone, "origin/develop")` (or capture `worktree_add(base=...)` like `test_remote_branch_exists_bases_off_tracking` does and assert `["origin/develop"]`).

### MAJOR 3 — The explicit `--worktree NAME` plan-ref recovery branch is untested
New code in `resolve_worktree`'s `else` arm does a best-effort `cache.read_plan_ref(repo_root)` so
an explicit `--worktree NAME` still picks up the pinned base. No test invokes `resolve_worktree`
with an explicit name + a base-carrying plan-ref. A regression (e.g. not recovering the ref, or a
missing-ref blowing up instead of `plan_base=None`) is uncaught.
- *Suggested test:* `resolve_worktree(repo_root, worktree="custom", materialize=False, ...)` with a written plan-ref carrying `base` → assert the resolved base reflects it; and a no-ref variant → `plan_base` stays `None` (no error).

### MAJOR 4 — Remote dispatch base preference (`_drive_remote_target`) untested
`_drive_remote_target` now prefers `plan_ref.get("base")` over `github.default_branch`. The
existing remote-drive test (`test_remote_drive_persists_verified_linkage...`) asserts
`fake.calls[0]["base"] == "trunk"` — but that's the **fallback** path (`_PLAN_REF` has no base). No
test feeds a base-carrying plan-ref and asserts the runner `inputs["base"]`/dispatch `base` equals
the pinned value. The §8.13 "honest input" claim in the diff comment is unverified.
- *Suggested test:* clone `test_remote_drive_persists...` with `cache.write_plan_ref(tmp_path, {**_PLAN_REF, "base": "develop"})` and assert `fake.calls[0]["base"] == "develop"` (and that `github.default_branch` is *not* consulted).

### MINOR 5 — TS `decodePlanRef` lenient base: legacy-absent / mistyped cases not directly tested
`planSave.test.ts` covers only the present-string case (active_plan_ref carries `"develop"`). The
lenient contract in the diff comment — "legacy pre-#633 plan-refs lack the field" (absent →
omitted, never a decode failure) and a mistyped value omitted — leans entirely on
`nullableStringField`'s own tests. Cheap to pin directly given the explicit comment promising it.
- *Suggested test:* a `plan_save` cold-JSON `plan_ref` **without** `base` still links and yields `active_plan_ref.base === undefined` (no `bad_output`); and a `plan_ref` with `base: 7` still succeeds (base dropped). Mirrors the objectiveDraft mistyped-refusal test which *does* exist (`base: 7 ⇒ null`).

### Vacuity / tautology scan — clean
No vacuous assertions found. The plan-save/submit/objective-cmd tests capture the value flowing
into the real boundary (`captured["base"]`, `ref["base"]`, `create_base`/`probe_base`, body
substring `"base: develop"`) — each would fail if the feature were broken. `resave_preserves_base`
asserting `header["fields"] == {"base": "develop"}` is meaningfully strict (proves base survives the
re-save merge). The TS argv assertions (`/--base\ndevelop/`, `argv[indexOf("--base")+1]`) are
positional and real. The default-path `base is None`/`base: undefined` assertions are honest
regression guards, not tautologies.

## Verdict
Test plan is satisfied for the **GitHub + plan-save + config + TS-parity** surfaces with strong,
non-vacuous assertions — but **Linear base persistence (both stores) and every worktree/remote
start-point integration path are untested**, so the feature's behavioral spine (cut the branch from
`origin/<base>`, target the runner, persist on Linear) rests on pure-unit + signature-only coverage:
**adequate for the GitHub happy path, materially under-tested at the integration and Linear layers.**
