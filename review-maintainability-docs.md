# Adversarial review — plan #633 (SIMPLICITY/MAINTAINABILITY + DOCS/CONTRACTS ACCURACY)

Branch `plan-633`. Reviewed the full diff (`git diff origin/main...HEAD`), the new how-to, the
edits to `reference/{configuration,cli,objectives,in-session}.md`, and `shared/contracts.md`.
Cross-checked every concrete doc claim against the implementation. Ran the relevant Python suites
(`test_plan_save`, `test_config`, `test_launch`, `test_pr_submit`, `test_objective_cmd`) — 200
passed.

Overall the docs are accurate and the contract amendment is faithful. Findings are all minor; no
blockers. Listed by value (docs accuracy first), then simplicity/dignified-python.

## Findings

### 1. (minor) `perk implement` reference entry is now stale on its default start-point
- **File:** `docs/user-docs/reference/cli.md:91`
- **Evidence:** `"Adds \`--base\` to branch off a ref other than \`origin/<trunk>\` (e.g. to stack
  on an unlanded branch)."`
- **Why:** With #633, `implement`'s *default* start-point is no longer always `origin/<trunk>` —
  `resolve_base` now bases off `origin/<plan_base>` when the plan pinned a base (`launch.py`:
  `trunk = plan_base or git.detect_trunk_branch(...)`). The behavior of this very command changed,
  but its reference entry still implies trunk is the only default, and (unlike the `plan save` and
  `objective create` entries) it does **not** cross-link the new how-to or note the `base` vs
  `--base` distinction the how-to draws.
- **Fix:** Add a clause noting the worktree now cuts from the plan's pinned base when set (else
  trunk), and cross-link `../how-to/target-a-non-default-base-branch.md` — mirroring the `plan save`
  entry's treatment.

### 2. (minor) Silent broad `except Exception` diverges from the repo's fail-open-WITH-report norm and dignified-python
- **File:** `perk/cli/commands/plan/save_cmd.py:239-241` (`_resolve_plan_base`)
- **Evidence:** `except Exception:  # fail-soft: a base lookup must never block a save.` — it does
  not even bind `exc`, and emits nothing.
- **Why:** Every other fail-open boundary in this codebase binds and *reports* the error
  (`land_cmd.py:220/296/325/360`, `objective/create_cmd.py:139`, `reconcile_cmd.py:73` all
  `except Exception as exc:` + a `user_output`/warning). AGENTS.md's dignified-python rule is
  explicit: "error boundaries that report (never silent)." A wholly silent swallow here means a
  misconfigured/unreachable objective store silently drops a declared base with zero operator
  signal — exactly the drift the plan's `base` feature is meant to make predictable.
- **Fix:** Bind `exc` and emit a one-line non-fatal `user_output` note (matching the sibling
  fail-open sites), so a base lookup failure is visible but still non-blocking.

### 3. (minor) Inconsistent base-coercion between the two Python consumers
- **File:** `perk/cli/commands/pr/submit_cmd.py:156` vs `perk/run/launch.py:200-201` & `save_cmd.py:243`
- **Evidence:** submit does `base = plan_ref.get("base") or state.header.get("base") or
  github.default_branch(...)` then `base = str(base)`; launch/`_resolve_plan_base` instead guard
  `plan_base if isinstance(plan_base, str) and plan_base.strip() else None`.
- **Why:** Three sites read the same field from the same JSON-decoded `plan_ref`, but submit
  *coerces* with `str(...)` while launch/save *validate* with `isinstance`. A corrupted/non-string
  cached `base` (e.g. a number or list) would be silently ignored by launch but stringified into a
  bogus branch name (`"['x']"`) and handed to `create_pr`/`_probe_mergeability` by submit — the
  less-safe outcome. The `str()` is also redundant on the happy path (the field is `str|None` and
  `default_branch()` returns `str`).
- **Fix:** Drop `base = str(base)` and mirror the `isinstance(..., str) and .strip()` guard used by
  the other two readers, so all three consumers treat a malformed pinned base identically.

### 4. (minor) Explicit `--worktree NAME` recovers the *active* plan-ref's base, which may belong to a different plan
- **File:** `perk/run/launch.py:196-198` (the new `else` branch of `resolve_worktree`)
- **Evidence:** `# Explicit --worktree NAME: best-effort recover the active plan-ref ...` →
  `plan_ref = cache.read_plan_ref(repo_root)`.
- **Why:** When `--worktree NAME` is given for a *create+materialize* path, the recovered plan-ref
  is whatever `cache.plan-ref` currently points at — not necessarily the plan named `NAME`. If they
  diverge, `NAME`'s worktree could be cut from the wrong plan's pinned base. The plan/comment only
  document the missing-ref case (`plan_base=None`), not the mismatched-ref case. Edge, but a latent
  correctness surprise.
- **Fix:** Either note the assumption explicitly in the comment (the explicit-worktree path assumes
  the active plan-ref matches), or gate the recovered base on the ref's name matching `NAME`.

### 5. (nit) Contract continuation-comment indentation
- **File:** `shared/contracts.md:1299-1300` (and the `plan-header` twin)
- **Evidence:** the wrapped `# null ⇒ fall back ...` line is indented two columns shy of the field
  comment above it, unlike the aligned `consumed_learn` comment it sits beside.
- **Fix:** Align the continuation comment for readability (cosmetic only).

## Things checked and found correct (no action)
- **How-to precedence** (`objective base → [workflow] base → GitHub default`) matches
  `_resolve_plan_base` and `create_cmd.resolved_base = base or load_config(...).workflow_base`.
- **Standalone plans inherit the config default** — accurate: `_resolve_plan_base` returns
  `load_config(repo_root).workflow_base` when `objective_id is None`.
- **`base` vs `--base` flag distinction** — accurate vs `launch.resolve_base` (`base_override`
  still wins verbatim) and `submit_cmd` (PR target = pinned base).
- **Submit resolution chain** in contracts (`cache.plan-ref.base → plan-header.base →
  default_branch()`) byte-matches `submit_cmd.py:156`.
- **`reconstruct_plan_ref` carries `base`** — `resume.py` adds `plan_state.header.get("base")`;
  contracts and how-to state matches.
- **Field sets** — `PLAN_HEADER_FIELDS`, `PlanHeader`/`PlanRef.to_data`, `OBJECTIVE_HEADER_FIELDS`,
  `ObjectiveHeader.to_data` all gained `base`, consistent with contracts §8.4 and objectives.md.
- **`#workflow` anchor** in the how-to resolves (heading `### \`[workflow]\`` → slug `workflow`);
  the how-to footer matches the sibling how-to convention; index router + objectives.md + cli.md
  cross-links all present and pointing at the real new file.
- **`_parse_workflow_base`** is idiomatic, not duplication — it follows the established one-helper-
  per-table pattern (`_parse_subagents_selection`, `parse_compaction_table`); no generic string-key
  reader exists to reuse. (Docstring says "mirrors `parse_issues_backend`" while the dataclass
  comment says it mirrors the subagents guard — harmless wording drift, not worth a fix.)
- **TS lenient-decode** (`planSave.ts decodePlanRef`, `cache.ts PlanRef.base?: string | null`) is
  correctly parity-only and tolerant of legacy refs; comment is accurate.
- **No missed user-doc surface:** `[workflow] base` (configuration.md), `objective create --base`
  (cli.md), `objective_draft`/`objective_save` base param (in-session.md), `plan save` no-flag
  (cli.md), objective-header `base` (objectives.md) are all documented. plan-header schema is a
  developer-plane concept (contracts only) with no user-doc twin, so nothing stale there.

## Verdict
Ship-worthy: docs and the contract amendment are accurate and complete; findings are minor polish —
the highest-value one is the stale `perk implement` reference entry (#1), then the silent
exception-swallow (#2) against dignified-python's "report, never silent" rule.
