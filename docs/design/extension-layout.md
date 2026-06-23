# extension/ feature-directory layout

*Architecture record for Objective #349, Node 1.1 (`extension-taxonomy`), decided in plan #425.
Nodes 1.2 and 1.3 execute the moves recorded here; node 3.1 reconciles prose/docstring references.
This document is the contract for those nodes — they should require zero re-investigation.*

## Scope

`extension/` is today a flat directory of 47 production modules (incl. `index.ts`,
`workerMain.ts`), their colocated `.test.ts` files, 5 test-only files, and
`extension/testing/harness.ts` — ~23.4k lines total. All intra-package imports are relative
`./x.ts` specifiers (tsc `moduleResolution: "Bundler"`, `allowImportingTsExtensions`), so moves
are pure path sweeps that `tsc --noEmit` fully checks.

This document records four decisions:

1. the taxonomy — the full file→directory mapping;
2. the tranche plan nodes 1.2/1.3 execute;
3. the move-safety audit;
4. per-file split verdicts.

## Decision 1 — the taxonomy (file→directory mapping)

Seven feature directories + a deliberately small root. Colocated `.test.ts` files always move with
their module. Each directory is one architectural stratum the docs/learned vocabulary already
names.

### Target tree (production modules; every module's `.test.ts` sits beside it)

```
extension/
├── index.ts                      # entry point (pi.extensions) — stays
├── workerMain.ts                 # headless worker entry — path-pinned by perk/run_worker.py; stays
├── surfacesGuard.test.ts         # source-scan guard — scan root must stay extension/
├── cacheGuard.test.ts            # source-scan guard — scan root must stay extension/
├── sessionLifecycle.test.ts      # live index.ts-wiring test (harness-driven)
├── planRef.test.ts               # live index.ts-wiring test (harness-driven)
├── testing/
│   └── harness.ts                # dev-only test harness — unchanged
├── substrate/                    # state tiers, identity, config, shared readers, boundary seams
│   ├── cache.ts
│   ├── sessionData.ts
│   ├── workflowState.ts
│   ├── runId.ts
│   ├── config.ts
│   ├── registry.ts
│   ├── bindings.ts
│   ├── bindingDelivery.ts
│   ├── providers.ts
│   ├── resources.ts              # needs the one-line packageRoot "../.." fix
│   ├── toolGating.ts
│   ├── toolParams.ts
│   ├── structuredOutput.ts
│   ├── coldDoor.ts
│   └── result.ts
├── surfaces/                     # the guard-enforced rich-UI surfaces module
│   ├── surfaces.ts
│   └── report.ts
├── doors/                        # warm doors, commands, model-facing leaf tools
│   ├── address.ts
│   ├── askUser.ts
│   ├── ciExecutor.ts
│   ├── land.ts
│   ├── learn.ts
│   ├── learnDocs.ts
│   ├── lifecycleGates.ts
│   ├── prReview.ts
│   ├── ready.ts
│   ├── selfcheck.ts
│   └── submit.ts
├── factories/                    # the plan + objective authoring complex
│   ├── planMode.ts
│   ├── planDraft.ts
│   ├── planReview.ts
│   ├── planSave.ts
│   ├── planTitle.ts
│   ├── objective.ts
│   ├── objectiveAuthor.ts
│   ├── objectiveDraft.ts
│   ├── objectivePlan.ts
│   └── objectiveSave.ts
├── checkpoints/                  # implement-stage progress
│   ├── checkpoints.ts
│   └── planSteps.ts
├── adapters/                     # foreign-package provider shims
│   ├── planAdapterPlannotator.ts
│   ├── planAdapterTombell.ts
│   └── todoAdapterJuicesharp.ts
├── worker/                       # headless stage-drive machinery
│   ├── worker.ts                 # (+ worker.test.ts, workerE2e.test.ts)
│   └── readOnlySession.ts
└── vendor/                       # foreign-origin extensions vendored-and-adapted from upstream
    ├── btw/
    │   ├── btw.ts
    │   └── core.ts
    └── whimsical/
        └── whimsical.ts
```

Counts: 2 root + 15 substrate + 2 surfaces + 11 doors + 10 factories + 2 checkpoints + 3 adapters
+ 2 worker + 3 vendor = 50 production modules — the full census. (`vendor/` was added in #752 to
house the `btw`/`whimsical` extensions vendored from `mitsuhiko/agent-stuff` (MIT) in #625, after
the original taxonomy was decided.)

`vendor/` is a distinct stratum from `adapters/`: `adapters/` holds injection-only shims that bridge
to foreign *npm packages* (plannotator/tombell/juicesharp) perk does **not** copy in; `vendor/`
holds foreign *source* copied in and adapted (`btw`/`whimsical`). Future vendored-and-adapted
extensions land in `vendor/`.

### Root (stays put) — rationale

| File | Why it stays |
|---|---|
| `index.ts` | package entry point (`pi.extensions`) |
| `workerMain.ts` | headless worker entry point — path-pinned by `perk/run_worker.py`'s four-candidate ladder + the `PERK_WORKER_ENTRY` contract; entry points don't move |
| `surfacesGuard.test.ts`, `cacheGuard.test.ts` | source-scan guards; their `import.meta.dirname` scan root must stay the package root |
| `sessionLifecycle.test.ts`, `planRef.test.ts` | live wiring tests of `index.ts`'s registration (harness-driven) — they test the root entry, not one module |
| `testing/` | unchanged (dev-only harness; its repo-root-is-two-levels-up comment stays true) |

(`whimsical.ts` is no longer a root file and `btw/` is no longer a one-off root subdirectory — both
moved under `vendor/` in #752.)

### Conventions

- Cross-directory imports are ordinary relative paths (`../substrate/cache.ts`).
- **No barrel/index re-export files** are introduced — imports stay explicit, guard scans stay
  simple.
- The provider *adapter shims* are a distinct stratum from the `shared/providers.yaml` *reader*:
  the reader (`providers.ts`) stays in `substrate/` with its sibling readers (`registry.ts`,
  `bindings.ts`); the three shims get `adapters/` (avoids a confusing `providers/providers.ts`).

## Decision 2 — tranche plan (executed by nodes 1.2 / 1.3)

Each tranche is a `git mv`-only commit followed by a separate import-sweep commit
(blame-preserving, per `docs/learned/workflow/cli-command-groups.md`). **Zero test-logic edits**;
only path literals (imports, guard allowlists/self-checks, the justfile glob) may change.

- **Tranche 1 (node 1.2, one PR): `doors/`** (11 module+test pairs).
  Sweep checklist:
  - moved files' relative imports gain `../`;
  - moved tests' harness import becomes `../testing/harness.ts`;
  - `index.ts` import paths;
  - **the justfile fix** — `node --test extension/*.test.ts` →
    `node --test "extension/**/*.test.ts"` (Node ≥22 expands glob args itself; the quotes keep
    `sh` from mangling it). Verify the new pattern matches both root-level and nested tests
    before committing.
- **Tranche 2 (node 1.3, commit pair A): `factories/` + `checkpoints/` + `adapters/` + `worker/`.**
  The `planReview.ts` ↔ `planAdapterPlannotator.ts` mutual import pair lands in different
  directories but moves in this same tranche, so the pair's paths update together.
- **Tranche 3 (node 1.3, commit pair B): `substrate/` + `surfaces/`.** Sweep additionally covers:
  - guard allowlists/self-checks/messages: `surfacesGuard.test.ts`'s
    `["report.ts", "surfaces.ts"]` allowlist, `files.includes("surfaces.ts")` self-check, and
    guidance text → `surfaces/surfaces.ts` / `surfaces/report.ts`; `cacheGuard.test.ts`'s
    `["cache.ts"]` allowlist, `files.includes("cache.ts")` self-check, and the
    `readFileSync(..., "cache.ts")` non-vacuous pattern check → `substrate/cache.ts`;
  - `testing/harness.ts`'s `../cache.ts` and `../workflowState.ts` imports (its `../index.ts`
    import is unchanged);
  - `resources.ts::packageRoot` `".."` → `"../.."` (the module moves one level down);
  - the final `index.ts` import tidy.

Node 1.3 lands tranches 2+3 as one PR with two mv+sweep commit pairs. After every sweep run
`npx biome check --write extension` then `just ci`.

## Decision 3 — move-safety audit (the recorded checklist)

1. `tsconfig.json` — recursive `include: ["extension"]`; **no change**.
2. `biome.json` — recursive `files.includes: ["extension/**/*.ts"]`; **no change** (run
   `biome check --write` post-sweep).
3. `package.json` — `files` globs (`extension/`, `!extension/**/*.test.ts`,
   `!extension/testing/`) are recursive; `pi.extensions: ./extension/index.ts` entry stays;
   **no change**; `tests/test_packaging.py` is the regression net.
4. `justfile` test glob — `node --test extension/*.test.ts` is **NOT recursive; fix in
   tranche 1** (see Decision 2). CI calls `just test`, so this is the single CI-coverage hazard:
   tests moved into subdirectories would otherwise silently stop running.
5. Guard tests (`surfacesGuard.test.ts`, `cacheGuard.test.ts`) — stay at root; their
   `import.meta.dirname` recursive scan already covers subdirectories; **path-literal updates in
   tranche 3** (classified as path-sweep edits, not test-logic edits).
6. `perk/run_worker.py` worker-entry ladder (`_clone_worker_entry`, `resolve_worker_entry`:
   self-repo path, clone path, published `node_modules/@perk/pi/extension/workerMain.ts`, plus
   the `PERK_WORKER_ENTRY` error message) — the only *behavior-bearing* cross-plane path
   reference into `extension/`; **neutralized by keeping `workerMain.ts` at root**; no Python
   edits in any extension tranche.
7. `extension/resources.ts::packageRoot()` computes `import.meta.url + "/.."` — the only
   production module whose own location is load-bearing; **one-line `"../.."` fix in tranche 3**.
   (`sharedDir()`'s `existsSync` throw makes a mistake loud at load time; `selfcheck`/version
   reads exercise it.)
8. `testing/harness.ts` — stays put; two of its three imports (`../cache.ts`,
   `../workflowState.ts`) update in tranche 3; `../index.ts` is unchanged.
9. `workerE2e.test.ts` — loads the extension via `resourceLoaderOptions.extensionFactories`
   injection (imports `./index.ts`), not via an on-disk path; **no string-path hazard**.
10. Prose/docstring references — `perk/*.py` and `shared/contracts.md` contain ~70
    `extension/<file>.ts` references, but apart from `run_worker.py`'s ladder they are ALL
    docstrings/comments/prose. Likewise `docs/learned/` and `AGENTS.md`. **Out of scope for the
    move tranches; node 3.1's reconciliation scope** — this census is its input.
11. `vendor/` move (#752) — the `btw`/`whimsical` relocation is a **pure recursive-glob path
    sweep** needing no `tsconfig`/`biome`/`package.json`/`justfile`/guard edits: the config globs
    are already recursive (items 1–4) and both source-scan guards' `import.meta.dirname` recursive
    scan + leading-dot member-access patterns already cover `vendor/` (`whimsical.ts` calls
    `setWorkingMessage(ctx, …)` as a bare function — no leading-dot member access — so the surfaces
    guard does not flag it; neither file carries the cache guard's banned path-segment literals).

## Decision 4 — per-file split verdicts

**No splits in `extension/`.** Long files are okay; a split is warranted only where a file
genuinely spans multiple feature directories — none does. Verdicts for every file >400 lines:

| File | Lines | Verdict |
|---|---|---|
| `worker.ts` | 757 | keep — one primitive (`driveStage`) + its event plumbing, all `worker/` |
| `objectivePlan.ts` | 588 | keep — one factory surface (warm entry + claim/resume), all `factories/` |
| `planSave.ts` | 584 | keep — one door (save + linkage), all `factories/` |
| `checkpoints.ts` | 509 | keep — one progress tracker, all `checkpoints/` |
| `ciExecutor.ts` | 447 | keep — one stateless oracle, all `doors/` |
| `surfaces.ts` | 435 | keep — the charter says ONE surfaces module; splitting would widen the guard allowlist |
| `index.ts` | 424 | keep — registration belongs at the entry point; tranche 3 tidies imports only |
| `planReview.ts` | 423 | keep — dispatch + first-party review are one door; the plannotator arm already lives in `adapters/`'s bridge |

Test files ≥400 lines colocate with their modules and are never split — test-logic edits are
banned in move tranches.
