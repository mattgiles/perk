# Review — #633 (target a non-default base branch): correctness & cross-plane regressions

Angle: adversarial correctness review. Inspected the full `git diff origin/main...HEAD`, the
referenced functions, both Linear `create_objective`/`get_objective` impls, and ran the affected
suites (`test_launch`, `test_plan_save`, `test_pr_submit`, `test_config` — 166 passed).

## Review

### Major

- **Blocker-adjacent regression — `resolve_worktree` reassigns the *returned* `plan_ref` on the
  explicit `--worktree NAME` path, not just a local `plan_base`.**
  `perk/run/launch.py` · `resolve_worktree` (the new `else` branch, ~L188–199):
  ```python
  else:
      # Explicit --worktree NAME: best-effort recover the active plan-ref so the plan's pinned
      # base (#633) still drives the start-point. A missing ref simply leaves plan_base=None.
      plan_ref = cache.read_plan_ref(repo_root)
  plan_base = plan_ref.get("base") if plan_ref else None
  ```
  This mutates the `plan_ref` that is returned as `ResolvedWorktree(plan_ref=plan_ref, …)` (L229).
  Pre-#633, the explicit-`--worktree` path left `plan_ref = None`; now it is the **repo-root**
  `cache.plan-ref`. Two downstream consumers change behavior:
  1. `launch_stage` L478: `if resolved.plan_ref is not None: cache.write_plan_ref(wt, resolved.plan_ref)`
     flips from *skip* → *write*. The reuse stages **`submit`/`address`/`land`/`learn`** (confirmed
     `worktree=reuse` in the registry) all accept `--worktree` (via `address_cmd.py`,
     `stages.py`). Running e.g. `perk pr address --worktree plan-42` from the repo root now
     **overwrites the existing worktree's own `cache.plan-ref` with the repo-root ref** — which can
     point at a *different* plan in a multi-plan workflow → the worktree's plan-ref is clobbered.
  2. `_emit_dry_run_preview` L556: `if resolved.plan_ref is not None: payload["plan_ref"] = …` now
     emits `plan_ref` in the `--dry-run --json` output for explicit `--worktree`, where it was
     previously omitted (machine-surface shape change).

  The plan's stated intent was only "still drives the start-point … leaves plan_base=None". The
  fix is to read into a **local** variable and not touch the returned `plan_ref`:
  ```python
  else:
      explicit_ref = cache.read_plan_ref(repo_root)
      plan_base = explicit_ref.get("base") if explicit_ref else None
  ```
  (keeping `plan_ref = None` for the returned `ResolvedWorktree` as before). No test covers the
  explicit-`--worktree` `plan_ref` value, so this slipped through green CI.

### Minor

- **Latency regression — `_resolve_plan_base` shells `gh` on *every* objective-linked save.**
  `perk/cli/commands/plan/save_cmd.py` · `_resolve_plan_base`:
  `state = store.get_objective(objective_id=…)`. For the GitHub backend this routes
  `GitHubObjectiveStore.get_objective` → `github.get_objective` → a `gh issue view` round-trip
  (`perk/backends/objective_stores.py` L113–116). Every objective-linked `plan save` (the common
  path, driven through the cold door from the warm session) now pays an extra network call purely
  to read `objective-header.base`. It is correctly `try/except`-fail-soft (never blocks a save),
  and standalone saves only hit `load_config` (no network), so this is acceptable but worth
  flagging as a deliberate per-save cost. (No fix required — note the design tradeoff.)

- **Re-save can desync `cache.plan-ref.base` vs `plan-header.base` (benign, submit resolves it).**
  `save_cmd.py`: the re-save merge only writes base when present —
  `if resolved_base is not None: header_fields["base"] = resolved_base` — so an existing
  `plan-header.base` is never *dropped* (good, matches the "never drops it" intent). But the
  `cache.plan-ref` is *always* rewritten via `plan_ref.to_data()` with `base=resolved_base`, so a
  re-save where `resolved_base` resolves to `None` (objective base removed / config cleared) leaves
  `plan-header.base="develop"` while `cache.plan-ref.base=null`. `submit` resolves correctly via the
  `plan_ref.get("base") or state.header.get("base")` fallback, so behavior is fine — flagging the
  state inconsistency only.

### Correct (verified, no issue found)

- **`submit_cmd` base coercion is sound and fail-soft.** `_pr_submit_impl`:
  `base = plan_ref.get("base") or state.header.get("base") or github.default_branch(repo_root)`
  then `base = str(base)`. No falsy/empty-string bug: Python only ever *stores* a stripped non-empty
  base (`_parse_workflow_base`, `_resolve_plan_base`, `ObjectiveHeader`), so a stored value is
  either `None` or a real branch; the `or` chain skips `None`/`""` correctly, and `str(base)` runs
  only on a real string. `plan_ref` and `state` are both defined and non-`None` before this line.
  Dry-run keeps `base=""` (offline, unchanged).

- **TS `decodePlanRef` lenient-`base` vs strict-`objective_id` asymmetry is justified — no
  corruption risk.** `extension/factories/planSave.ts` · `decodePlanRef`: `base` via
  `nullableStringField` (string|null carried, mistyped→`undefined`→omitted, never a decode
  failure). `planRefsEqual` (`extension/substrate/workflowState.ts` L146) compares **only**
  `provider`+`pr_id`, so a malformed/absent `base` can never poison dedup or the read-back guard.
  Python's `PlanRef.to_data()` always emits `base` (via `_result_to_dict` → `plan_ref.to_data()`),
  so the cold door's `--json` `plan_ref` always carries the field for a fresh save; legacy refs lack
  it and are harmlessly omitted. Parity-only, as documented.

- **`base: null` byte-shape change is contained; no parser/idempotency break.** `PlanHeader`/
  `PlanRef`/`ObjectiveHeader.to_data()` now always emit `"base": None`, so issue bodies gain a
  `base: null` YAML line (serialization is **not** byte-identical — the plan's "byte-identical"
  claim is about *behavior*, which holds). Verified safe: `PLAN_HEADER_FIELDS` and
  `OBJECTIVE_HEADER_FIELDS` both include `"base"` (so `update_plan_header`/`update_objective_header`
  unknown-key LBYL passes), `find_metadata_block` round-trips it, and idempotency is keyed on
  `run_id` (find-then-return) not body bytes. Suites green.

- **Linear: both `create_objective` impls persist `base`, and both `get_objective` read it back.**
  Issue-backed (`LinearObjectiveStore`, ~L1268) and project-backed (`LinearProjectObjectiveStore`,
  ~L1640) compose `ObjectiveHeader(…, base=base)` into the inline-code header block; the
  project-backed overview composer includes it via
  `overview = to_linear_markdown(f"{header_block}\n\n{manifest_block}\n\n{reconcilable}\n")`. Both
  `get_objective` impls parse `header = find_metadata_block(…, OBJECTIVE_HEADER_KEY)` and return it
  in `ObjectiveState.header`, so `_resolve_plan_base`'s `state.header.get("base")` works on every
  backend. No path drops `base`.

- **`resolve_base` precedence is correct.** Explicit `--base` (`base_override`) wins verbatim →
  `origin/<name>` (resume) → `origin/<plan_base or trunk>` → `None`. Covered by the four new
  `test_resolve_base_*` cases. `reconstruct_plan_ref` carries `base` from the canonical
  `plan-header` for resume/remote recovery.

## Verdict
One **major** correctness regression: `resolve_worktree`'s explicit-`--worktree` branch reassigns
the returned `plan_ref` (should be a local `plan_base` only), which can clobber a reuse-stage
worktree's `cache.plan-ref` and alters the dry-run `--json` shape; everything else (precedence,
submit coercion, cross-plane base flow, TS leniency, byte-shape) is correct and fail-soft.
