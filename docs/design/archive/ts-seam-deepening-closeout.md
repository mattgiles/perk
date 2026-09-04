# ts-decomposition seam deepening: objective #2130 closing record

**Status:** validation record (Objective #2130, Node 5.1; authored 2026-09-04). This record
closes the objective's **Phase-5 gate**: acceptance verification against the reworked Final
acceptance criteria, the final before/after measurement, and the per-feature-family live
dogfood. The archive location is the status signal.

**Code-state provenance.** The §1 ledger ran clean — **no verification fix was needed**, so
this layer ships **zero `extension/` changes** and the measurement binds to the predecessor
verified remote head `cead475a0b540a843b7c0e291451e7117a128a52` (plan-2147 / node 4.2's
ready-stamped head, the base of this branch). Every commit on this branch is docs-only. The
standing verification command for any later head of this branch:

```sh
git diff cead475a..HEAD -- extension/
```

**must be empty** — if it ever is not, the §2 measurement no longer binds and a dated
re-measurement addendum is owed (see §3's review-findings branch).

Session provenance for the observed legs: the planning session (run
`01M1PS2Z7R1RDFHR6JBJ9R69H3`) and this implementation session (run
`01M1PXSA1Y5ECM4MC861NE503Q`) both ran in this worktree against `cead475a` — pre-any-fix by
construction, and since no fix landed, against exactly the measured code state.

## §1 Acceptance verification — the criterion→evidence ledger

Verified against `docs/planning/ts-decomposition/migration-and-verification.md` § Final
acceptance criteria (the binding list, reworked in place by node 1.1 — every criterion under
all five headings). Classification vocabulary (closed): **guard-enforced** (a named Rule A–H
of `extension/importDirectionGuard.test.ts`, green under run-all CI), **suite-pinned** (a
named owning suite, green under CI), **derivation-verified** (a copy-paste-complete command
inlined with its result), **inspection-verified** (a bounded inspection whose scope is stated
honestly). Every anchor below was re-resolved at edit time (2026-09-04, at `cead475a`); the
full `node:test` suite — all guard rules and every suite named below included — was run green
during ledger execution (`run_ci` check `test-js`), ahead of the definitive run-all gate
before submit.

### Architecture

| Criterion | Verdict | Evidence |
| --- | --- | --- |
| Feature homes expose typed feature operations, not one common interface | PASS | inspection-verified: the four homes export named operation signatures — `authoring/` (`saveThroughApprovalGate`, `revisePlanDraft`, `reviewObjectiveDraft`, …), `delivery/` (`runCiChecks`, `decideCiScope`, …), `codeReview/` (`runAutomatedReview`, `publishAutomatedReview`, the curated-submission op), `learning/` (`finishLearn`, `judgeAuditBundle`, `analyzeHarvest`, `analyzeDream`) — each with its own input/result unions; `rg -n ' implements ' extension/authoring extension/delivery extension/codeReview extension/learning -g '!*.test.ts'` finds no shared protocol (one comment-line hit only). Supported by Rule C's set-exact top-level census (no kernel directory) |
| No application kernel / global catalog / generic invocation / universal result wrapper | PASS | derivation-verified: `rg -n 'UniversalResult\|InvokeResult\|CapabilityProtocol\|FeatureCatalog\|invokeFeature\|ApplicationKernel' extension -g '*.ts' -g '!*.test.ts'` → empty; guard-enforced: Rule C freezes the top-level directory census to the 13 named homes (`authoring/`, `codeReview/`, `delivery/`, `hunkFeedback/`, `learning/`, `pi/`, `session/`, `substrate/`, `surfaces/`, `testing/`, `vendor/`, `waves/`, `worker/` — no kernel, no `doors/`) |
| `WorkflowSession` authoritative for feature-facing state/artifacts | PASS | suite-pinned: `extension/session/workflowSession.test.ts` (the eight-arm change engine + session-owned receipt) + `extension/session/lifecycle.test.ts`; node 2.2's landed narrative |
| `ReportWave` exposes report assignments + opaque references, not RPC/Pi lanes | PASS | suite-pinned: `extension/waves/reportWave.test.ts`, `extension/waves/adapterContract.test.ts`; guard-enforced: Rule G (interior ban on `waves/transport.ts` + `waves/rpcAdapter.ts`, supplier floor, word-bounded `WAVE_RPC_` token census, tests included) |
| Extension v1/application facets are adapters, not domain dispatchers | PASS | inspection-verified (stated scope: `pi/v1/` decode→delegate→render spot-inspection — `pi/v1/delivery/ci.ts` delegates to `delivery/ci.ts::runCiChecks`; `pi/v1/plan.ts` to `authoring/plan/*`; `pi/v1/learning/harvest.ts` to `learning/harvest.ts::analyzeHarvest` + `learning/containment.ts`) + Rules D/E structurally |
| Planning documents describe the built architecture; no contradictory architecture documents | PASS | derivation + the Deliverable-2 sweep outcome: targeted greps for retired vocabulary (`doors/`, `memoryWorkflowSession`, `memoryAdapter`, `startReportWave`, the stale 26/30 calibration) across the four planning docs found every hit inside a dated `Status`/`Update`/`Fresh stamp` blockquote or a framed frozen snapshot (`current-system-map.md`'s `95ff7cc7` snapshot and pinned `53fe2d7d` baseline) — a **legitimate no-op**: no instructive sentence became false without an existing dated reconciliation; this layer's only doc corrections are the four dated closing annotations themselves |
| Deferred seams (config/, PromptEvidence, StageRunner) recorded with one canonical rationale home | PASS | derivation-verified: `module-contracts.md` carries `## PromptEvidence`, `## StageRunner`, and `## PerkConfig` disposition sections (each with rationale + re-earn condition), and the acceptance list's binding criteria omit the seams (they live under its "Deferred seams (recorded)" subsection) |

### Dependency direction

| Criterion | Verdict | Evidence |
| --- | --- | --- |
| Feature modules free of Pi runtime/TUI/RPC/raw-branch/etc. dependencies | PASS | guard-enforced: Rule D (per-home anti-vacuity floors; controls 10/11 mutation fixtures), green |
| Feature homes storage-free per `module-contracts.md` § Storage freedom (allow-listed domain I/O excepted) | PASS | guard-enforced: Rule H (empty allowlist, per-home floor, control-14 mutation fixtures) + the census fresh stamps (nodes 2.2/2.3); the two `allowed-domain-I/O` rows re-inspected at edit time — `learning/containment.ts` imports `node:fs` `existsSync`/`realpathSync` only as injectable production defaults for `verifyDocContainment` (caller-supplied paths), and `learning/harvest.ts` imports `existsSync` only as the injectable default (`opts.exists ?? existsSync`) for `stampHarvestReport`'s pointer post-pass — both still satisfy the allow rule (probes over caller-supplied paths, not session-storage mechanics) |
| Stable mechanisms do not import features | PASS | guard-enforced: Rule B (control 8: every contractual prefix bites) |
| Provider adapters depend on feature role interfaces, not the reverse | PASS | guard-enforced: Rule B (providers among sources) + inspection of `pi/v1/providers/`: `tombell.ts` and `plannotator.ts` import feature vocabulary (`authoring/gist/draft.ts::GIST_AUTHOR_STAGE`, `authoring/objective/prose.ts`); the reverse grep — `rg -n 'pi/v1/providers' extension/authoring extension/delivery extension/codeReview extension/learning -g '!*.test.ts'` — is empty |
| Pi adapters carry no feature policy (decode, delegate, render) | PASS | Rules D/E structurally + inspection-verified with stated scope (the three-file spot-inspection above), citing the per-node review trail (each of nodes 2.1–4.2 shipped through plan review + PR review on exactly this boundary) |
| `extension/index.ts` composition-only | PASS | inspection-verified: the file is imports + one cross-plane sentinel helper (`writeT3Sentinel`) + the default installer function (named `install*` calls; per-`cwd` dependency loading); guard-enforced: Rule E names it a composition root and freezes the registrar census |
| Rich UI confined to sanctioned surfaces files | PASS | guard-enforced: `extension/surfacesGuard.test.ts`, green |
| No production import cycles | PASS | guard-enforced: Rule A (zero-cycles direct assertion; control 7 proves the rule bites) |

### Behavior

| Criterion | Verdict | Evidence |
| --- | --- | --- |
| Baseline tools/commands/flags/shortcuts/hooks registered exactly once | PASS | suite-pinned: the per-feature registration-parity pins with frozen-baseline deepEqual registrations — `pi/v1/gist.test.ts`, `pi/v1/plan.test.ts`, `pi/v1/objectiveAuthoring.test.ts` and their pi/v1 siblings (the 43-suite `extension/pi/` census) — plus Rule E's frozen registrar census |
| Perk/borrowed-tool access census retains read-only + stage coverage | PASS | suite-pinned: `extension/substrate/toolGating.test.ts` + `extension/substrate/stageTools.test.ts` |
| Schemas, prose placement, gating, completion, lifecycle ordering, progress, rendering, headless behavior retain coverage | PASS | suite-pinned: the pi/v1 feature suites — authoring (`gist`, `plan`, `planReview`, `planReviewBrowser`, `planTitle`, `objective`, `objectiveAuthoring`, `objectivePlanning`, `objectiveReview`, `objectiveReviewBrowser`, `draftReviewWaveTools`, `contextInjection`), delivery (`ci`, `commitCompact`, `submit`, `address`, `ready`, `land`, `stackStatus`, `stackSync`, `stackRecover`, `stackLand`, `stackDrive`), code review (`automated`, `browser`, `reviewWave`, `stack`, `submit`, `terminal`), learning (`learn`, `factory`, `audit`, `harvest`, `dream`), providers (`annotations`, `plannotator`, `plannotatorHandoff`, `tombell`), plus `lifecycleGates`, `selfcheck`, `waveIsolation`, `review`, `objectiveDreamGate` — and `extension/sessionLifecycle.test.ts` |
| Session writes retain verified read-back | PASS | suite-pinned: `extension/session/workflowSession.test.ts` (verified-write/`unverified` arms over both backings) |
| Compaction cannot turn unavailable Prompt evidence into durable absence | PASS | suite-pinned: `extension/pi/v1/contextInjection.test.ts` (strip/inject asymmetry pins) |
| Report waves do not leak pending state between sessions | PASS | suite-pinned: `extension/waves/reportWave.test.ts` session-isolation pins + `extension/pi/v1/waveIsolation.test.ts` (two-activation isolation) |
| Worker retains budget/terminal/handoff/disposal semantics | PASS | suite-pinned: `extension/worker/stageExecution.test.ts` + `extension/worker/stageExecutionE2e.test.ts` |
| Host generation replacement reconstructs standing state, leaks nothing | PASS | suite-pinned: `extension/index.test.ts` + `extension/sessionLifecycle.test.ts` (activation/rebuild arms) |
| Exactly one adapter registers each behavior | PASS | guard-enforced: Rule E (frozen census; approved registrars = `pi/` + the two composition roots; `LEGACY_REGISTRANTS` burned down to the 7 substrate/surfaces/vendor survivors — zero door registrants remain) |

### Tests and packaging

| Criterion | Verdict | Evidence |
| --- | --- | --- |
| Feature policy tested without Pi | PASS | derivation-verified: `rg -ln 'from "@earendil-works' extension/authoring extension/delivery extension/codeReview extension/learning` (tests **included**) → empty |
| Each host seam has a production adapter + deterministic test implementation | PASS | inspection-verified: the `extension/testing/` census mapped to seams — `memoryWorkflowSession.ts` ↔ `session/workflowSession.ts` (production: `session/branchWorkflowSession.ts`), `memoryAdapter.ts` ↔ the `ReportWave` adapter seam (production: `waves/rpcAdapter.ts`), `fakeSubagents.ts` ↔ the subagent RPC surface, `harness.ts` ↔ the Pi `ExtensionAPI` host; plus fixtures (`dreamFixtures.ts`, `objectiveStackFixtures.ts`), live-render surfaces (`renderLive.ts`, `renderBindingsLive.ts`), and the guard's import-graph infrastructure (`importGraph.ts` + test) |
| Adapters pass equivalent observable interface cases | PASS | suite-pinned: `extension/waves/adapterContract.test.ts` (memory vs RPC adapter contract) + the session engine's shared contract arms in `workflowSession.test.ts` (branch-backed and in-memory) |
| Framework suites and guards green | PASS | the one run-all `run_ci` immediately before submit (definitive per repo discipline); additionally the full `test-js` check ran green during ledger execution |
| No shipped test-only implementations / test-only exports | PASS | derivation-verified: `rg -n 'from "(\.\./)*testing/' extension -g '*.ts' -g '!*.test.ts' -g '!extension/testing/**'` → empty; `package.json` `files` excludes `!extension/testing/` (and `!extension/**/*.test.ts`); node 4.1's narrowed `worker/stageExecution.ts` seam checked by the §2 calibration gate (13 declarations / 16 names — passed) |
| npm tarball one package; entrypoints unchanged | PASS | derivation-verified: `package.json` `files` = `extension/` (minus tests + testing/), `shared/`, `prompts/`, `README.md`; entrypoints unchanged — `pi.extensions: ["./extension/index.ts"]` and `extension/workerMain.ts` (the §8.14 cross-plane worker entry, referenced by `src/perk/run/run_worker.py`). Noted: `workerMain.ts` now carries zero export declarations (a pure entrypoint) — the one zero-export production file, so §2's export table has 137 rows for 138 files |
| Workspaces + zero-runtime-dependency policy unchanged | PASS | derivation-verified: `package.json` has **no** `dependencies` key (peer + dev only); `workspaces` = `docs/site`, `tools/prose-review` — unchanged |
| No codegen / no additional package | PASS | inspection-verified: repo layout unchanged — one npm package, no generated-source step, no new workspace |

### Deletion

| Criterion | Verdict | Evidence |
| --- | --- | --- |
| Old registration and policy paths gone | PASS | guard-enforced: Rule E's frozen census (`LEGACY_REGISTRANTS` = 7 substrate/surfaces/vendor entries; all door registrants burned down) + Rule C (no `doors/` in the set-exact top-level census) |
| Transitional wrappers and re-exports gone | PASS | derivation-verified: the import-specifier absence greps in the next row; 0 star-exports in the §2 inventory |
| No legacy compatibility paths | PASS | derivation-verified absence greps for the retired API vocabulary — `rg -n 'startReportWave\|runReportWave' extension` → empty; `rg -ln 'WaveAdapter' extension -g '*.ts' -g '!*.test.ts' -g '!extension/waves/**' -g '!extension/testing/**'` → empty (test files reference the `testing/memoryAdapter.ts` deterministic adapter — the sanctioned seam, censused by Rule G, not a legacy path); `rg -n 'from "[^"]*doors/' extension -g '*.ts'` → empty; `rg -n 'from "[^"]*memoryWorkflowSession"' extension -g '*.ts' -g '!extension/testing/**'` → empty. NOTE: a bare-token grep is NOT the derivation — `session/workflowSession.ts:14`'s header comment legitimately names the testing module and is the classified comment-only survivor |
| Removing one feature edits no universal protocol | PASS | inspection-verified: follows from the no-kernel row — each home's operations are imported directly by its own `pi/v1/` installers; there is no shared protocol/catalog to edit |

**Failure disposition:** not taken — every row passed; no doc-level contradiction, no
code-level violation, no permitted-shape fix, no nontrivial STOP. The permitted-fix budget
(≤ 2 production files / ≤ 10 lines) was **not consumed**.

## §2 Final measurement (baseline `53fe2d7d` → measured `cead475a`)

The four pipelines from `current-system-map.md` § Objective #2130 baseline, re-run
**verbatim** (no new methodology) at the measured SHA `cead475a` — the last commit touching
`extension/` on this branch (this layer ships no fix; every subsequent commit is docs-only,
so `git diff cead475a..HEAD -- extension/` empty proves the measurement holds at any later
head of this branch).

| Measure | Baseline (`53fe2d7d`) | Final (`cead475a`) | Delta |
| --- | ---: | ---: | ---: |
| Production files (incl. vendor) | 136 | 138 | +2 |
| Production LOC (incl. vendor) | 42,376 | 42,455 | +79 |
| Production files (excl. vendor) | 133 | 135 | +2 |
| Production LOC (excl. vendor) | 40,687 | 40,766 | +79 |
| Vendor (unchanged) | 3 / 1,689 | 3 / 1,689 | 0 |
| Comment-only lines | 10,326 (≈ 24.4%) | 10,546 (≈ 24.8%) | +220 |
| **Non-comment production LOC** (the objective's bar) | **32,050** | **31,909** | **−141** |
| Pi importers (`from "@earendil-works` prefix) | 52 | 54 | +2 |
| Files with ≥ 1 export declaration | 136 | 137 | +1 |
| Export declarations | 1,146 | 1,139 | −7 |
| Exported names | 1,155 | 1,146 | −9 |
| Star-exports | 0 | 0 | 0 |

### Pipeline 1 — production census and LOC

```sh
rg --files extension -g '*.ts' -g '!*.test.ts' -g '!extension/testing/**' | wc -l
rg -c '' extension -g '*.ts' -g '!*.test.ts' -g '!extension/testing/**' | awk -F: '{s+=$2} END {print s}'
rg --files extension -g '*.ts' -g '!*.test.ts' -g '!extension/testing/**' -g '!extension/vendor/**' | wc -l
rg -c '' extension -g '*.ts' -g '!*.test.ts' -g '!extension/testing/**' -g '!extension/vendor/**' | awk -F: '{s+=$2} END {print s}'
```

Measured: **138 files / 42,455 LOC** including vendor; **135 files / 40,766 LOC** excluding
vendor.

File delta (excl. vendor) vs the baseline list at `53fe2d7d`, derived by diffing the two
sorted pipeline-1 file lists (`git ls-tree -r --name-only 53fe2d7d -- extension` filtered by
the same selector, against the live list):

- **Added (5):** `authoring/review/approvalGate.ts`, `authoring/review/draftContext.ts`
  (node 4.2 / 3.1 splits), `pi/v1/contextInjection.ts` (node 4.2),
  `pi/v1/objectiveDreamGate.ts` (node 2.3), `session/lifecycleGates.ts` (node 3.1).
- **Deleted (2):** `doors/pendingWave.ts` (node 2.1), `session/memoryWorkflowSession.ts`
  (node 4.1 — superseded by `testing/memoryWorkflowSession.ts`).
- **Moved out of production (1):** `waves/memoryAdapter.ts` → `extension/testing/` (node 4.1).
- **Moved within production (6, the `doors/` evacuation, node 3.1):**
  `doors/draftReviewWaveTools.ts` → `pi/v1/draftReviewWaveTools.ts`,
  `doors/lifecycleGates.ts` → `pi/v1/lifecycleGates.ts`,
  `doors/objectiveReviewBrowser.ts` → `pi/v1/objectiveReviewBrowser.ts`,
  `doors/planReviewBrowser.ts` → `pi/v1/planReviewBrowser.ts`,
  `doors/plannotatorHandoff.ts` → `pi/v1/providers/plannotatorHandoff.ts`,
  `doors/selfcheck.ts` → `pi/v1/selfcheck.ts`.

Net: **+2 files** (136 → 138 incl. vendor; 133 → 135 excl. vendor).

### Pipeline 2 — comment-only share

```sh
rg -c '^\s*(//|/\*|\*)' extension -g '*.ts' -g '!*.test.ts' -g '!extension/testing/**' | awk -F: '{s+=$2} END {print s}'
```

Measured: **10,546** comment-only lines (≈ 24.8% of the 42,455 production lines; baseline
10,326 / ≈ 24.4%). The classifier approximation stated at the baseline (a `*`-led line
inside a template string would miscount) is unchanged.

### Pipeline 3 — Pi importers

```sh
rg -l 'from "@earendil-works' extension -g '*.ts' -g '!*.test.ts' -g '!extension/testing/**' | wc -l
```

Measured: **54** Pi importers (baseline 52). The importer-list delta, file by file (derived
by diffing the sorted importer lists at `53fe2d7d` and `cead475a`):

- **Removed (6):** the `doors/` importers — `doors/draftReviewWaveTools.ts`,
  `doors/lifecycleGates.ts`, `doors/objectiveReviewBrowser.ts`, `doors/planReviewBrowser.ts`,
  `doors/plannotatorHandoff.ts`, `doors/selfcheck.ts`.
- **Added (8):** their six `pi/v1/` successors (`pi/v1/draftReviewWaveTools.ts`,
  `pi/v1/lifecycleGates.ts`, `pi/v1/objectiveReviewBrowser.ts`, `pi/v1/planReviewBrowser.ts`,
  `pi/v1/providers/plannotatorHandoff.ts`, `pi/v1/selfcheck.ts`) **plus exactly the two new
  sanctioned Pi-edge modules**: `pi/v1/contextInjection.ts` (node 4.2) and
  `pi/v1/objectiveDreamGate.ts` (node 2.3).

Net **+2**, both at the sanctioned Pi edge; **no feature home gained a Pi import** (Rule D
green; the feature-home selector in §1's "Feature policy tested without Pi" row is empty
with tests included).

### Pipeline 4 — export inventory

The baseline's AST script (the repository's `typescript` devDependency; identical counting
semantics) re-run verbatim at `cead475a`.

**Calibration gate (updated for the final state): passed** — the
`extension/worker/stageExecution.ts` row reports **13 declarations / 16 names** (node 4.1's
landed narrowing of the baseline's 26 / 30).

Measured totals: **137 files with exports / 1,139 export declarations / 1,146 exported
names / 0 star-exports** (baseline: 136 / 1,146 / 1,155 / 0). `extension/workerMain.ts` is
now the one zero-export production file (a pure entrypoint), so the table covers 137 of the
138 production files.

Per-file deltas vs the baseline table (rows whose counts changed, appeared, or disappeared;
declarations/names):

| File | Baseline | Final | Owning change |
| --- | ---: | ---: | --- |
| `authoring/gist/draft.ts` | 11 / 11 | 13 / 13 | node 2.2 (session receipts) |
| `authoring/gist/save.ts` | 7 / 7 | 6 / 6 | node 2.2 |
| `authoring/objective/draft.ts` | 10 / 10 | 12 / 12 | node 2.2 |
| `authoring/objective/dreamReportGate.ts` | 6 / 6 | 7 / 7 | node 2.3 (capability port) |
| `authoring/objective/save.ts` | 11 / 11 | 10 / 10 | node 2.2 |
| `authoring/plan/save.ts` | 10 / 10 | 9 / 9 | node 2.2 |
| `authoring/review/approvalGate.ts` | — | 2 / 2 | node 4.2 (new) |
| `authoring/review/draftContext.ts` | — | 5 / 5 | node 3.1 (new) |
| `delivery/ci.ts` | 13 / 13 | 14 / 14 | node 2.3 (`PersistCheckOutput` port) |
| `doors/draftReviewWaveTools.ts` | 13 / 13 | — | node 3.1 (moved) |
| `doors/lifecycleGates.ts` | 4 / 4 | — | node 3.1 (split/moved) |
| `doors/objectiveReviewBrowser.ts` | 7 / 7 | — | node 3.1 (moved) |
| `doors/pendingWave.ts` | 4 / 4 | — | node 2.1 (deleted) |
| `doors/plannotatorHandoff.ts` | 25 / 25 | — | node 3.1 (moved) |
| `doors/planReviewBrowser.ts` | 7 / 7 | — | node 3.1 (moved) |
| `doors/selfcheck.ts` | 19 / 19 | — | node 3.1 (moved) |
| `learning/analystWave.ts` | 8 / 8 | 11 / 11 | node 2.1 (wave lifecycle) |
| `pi/v1/codeReview/reviewWave.ts` | 8 / 8 | 9 / 9 | node 2.1 |
| `pi/v1/contextInjection.ts` | — | 2 / 2 | node 4.2 (new) |
| `pi/v1/delivery/ci.ts` | 7 / 7 | 9 / 9 | node 2.3 |
| `pi/v1/draftReviewWaveTools.ts` | — | 8 / 8 | node 3.1 (moved; narrowed from 13) |
| `pi/v1/lifecycleGates.ts` | — | 1 / 1 | node 3.1 (moved; narrowed from 4) |
| `pi/v1/objectiveDreamGate.ts` | — | 1 / 1 | node 2.3 (new) |
| `pi/v1/objectiveReviewBrowser.ts` | — | 7 / 7 | node 3.1 (moved) |
| `pi/v1/planReviewBrowser.ts` | — | 7 / 7 | node 3.1 (moved) |
| `pi/v1/providers/plannotatorHandoff.ts` | — | 25 / 25 | node 3.1 (moved) |
| `pi/v1/selfcheck.ts` | — | 19 / 19 | node 3.1 (moved) |
| `session/lifecycleGates.ts` | — | 2 / 2 | node 3.1 (new split) |
| `session/memoryWorkflowSession.ts` | 2 / 2 | — | node 4.1 (moved to `testing/`) |
| `session/workflowSession.ts` | 13 / 13 | 20 / 20 | node 2.2 (deep session authority) |
| `substrate/cache.ts` | 28 / 28 | 29 / 29 | node 2.2 |
| `substrate/sessionData.ts` | 14 / 14 | 8 / 8 | nodes 2.3/4.1 (narrowing) |
| `substrate/workflowState.ts` | 22 / 22 | 20 / 20 | node 2.2 (narrowing) |
| `waves/memoryAdapter.ts` | 3 / 3 | — | node 4.1 (moved to `testing/`) |
| `waves/reportWave.ts` | 19 / 20 | 22 / 22 | node 2.1 (opaque lifecycle) |
| `worker/stageExecution.ts` | 26 / 30 | 13 / 16 | node 4.1 (test-shaped surface retired) |
| `workerMain.ts` | 1 / 1 | 0 (row absent) | node 4.1 (pure entrypoint) |

### Named rationale for remaining production excess

Written from the final numbers. The objective's stated bar excludes comments: **non-comment
production moved 32,050 → 31,909 (net −141)** while comment-only lines rose **+220** —
invariant documentation added on the deepened seams (the session engine's authority
contracts, the wave lifecycle's drain-once semantics, Rule H's classification vocabulary)
outweighed node 4.2's provenance-strip deletions. An honest sentence, not spin: the code
shrank; the explanation of its invariants grew.

The **+2 files and +2 Pi importers** are exactly the two new sanctioned Pi-edge modules the
seam work required — `pi/v1/contextInjection.ts` (node 4.2: the injection discipline
extracted to one adapter home) and `pi/v1/objectiveDreamGate.ts` (node 2.3: the
storage-freedom migration's runtime-minted capability edge). Neither adds feature policy at
the edge; both exist so the feature homes could shed Pi/storage knowledge.

Against the **38,063** pre-train reference point (`current-system-map.md`'s frozen
`95ff7cc7` headline census — a reference, not a gate: the objective prose asks for a named
rationale for significant remaining excess, not a target), the standing excess is the
delivered architecture itself, each source named with its owning node:

- the deep `WorkflowSession` engine + session-owned receipts (node 2.2);
- the opaque `ReportWave` start/collect/run lifecycle with wave-owned pending state
  (node 2.1);
- the Pi-edge capability modules that keep the feature homes storage-free
  (node 2.3: `pi/v1/objectiveDreamGate.ts`, the `PersistCheckOutput` port wiring in
  `pi/v1/delivery/ci.ts`);
- guard Rule H (storage freedom) with its control fixtures (node 2.3), riding the
  already-grown guard suite.

## §3 The per-family dogfood record (Part A pre-committed / Part B evidence)

**Design rule** (from `docs/learned/workflow/doc-reconciliation.md` and this objective's OWN
failure history — the phase-7 record's never-landed commit-3 placeholders and node 2.1's
never-posted live-gate comment): **no leg's completion may depend on a future commit.**
Everything observable pre-submit lands in-file by commit 2; each post-submit leg is an
explicit forward reference whose completion is **self-describing** — this committed record
states the exact external artifact whose existence completes it, and absent that artifact
the leg reads **UNOBSERVED — NOT PASSED** and the closeout is incomplete on that family.
In-file commits after commit 2 are permitted ONLY as dated evidence/re-certification addenda
(never new protocol legs).

**The named enforcement gap, stated plainly:** there is **no machine gate** enforcing the
post-submit choreography — perk's ready path stamps without reading the evidence comment.
The enforcement point is the operator's ready gesture (ready only after the evidence comment
exists), an **unenforced convention**, with the two historical failures cited above as the
reason it is named rather than assumed. The record cannot falsely read complete either way:
completion of the forward-referenced leg is checkable by anyone from the named artifact.

### Part A — the protocol (pre-committed)

1. **Authoring** — this node's own plan lifecycle: `plan_draft` → Plannotator `plan_review`
   (browser + reviewer wave) → DENY/revise round → approval auto-save — exercising
   `authoring/plan/*`, `authoring/review/approvalGate.ts::saveThroughApprovalGate` (4.2),
   `authoring/review/draftContext.ts`, `pi/v1/plan.ts`, `pi/v1/planReviewBrowser.ts` (3.1),
   `pi/v1/contextInjection.ts` (4.2). Session shape: the 5.1 planning session (already run,
   in this worktree, against predecessor head `cead475a` — pre-any-fix by construction).
2. **Delivery** — `/commit-and-compact` drives this record's own first record-commit
   (`pi/v1/delivery/commitCompact.ts`); one run-all `run_ci` immediately before `/submit`
   (`pi/v1/delivery/ci.ts` — the 2.3-migrated `PersistCheckOutput` port live); `/submit`
   publishes this plan (`pi/v1/delivery/submit.ts`). Session shape: the 5.1 implementation
   session (no fix landed, so no post-fix reload was required — the session executes exactly
   the measured code state).
3. **Code review** — `/pr-review` on this node's own PR: the blocking `run_pr_review_wave`
   flow over the deepened wave. No second flow (the streaming pair is deliberately NOT part
   of this leg). Session shape: a fresh post-submit session in this worktree.
4. **Learning** — `perk learn harvest --no-sync --from docs/learned/pi/extension-api.md
   --from docs/learned/workflow/report-waves.md`: exactly two docs from two distinct
   top-level corpus groups (`pi/`, `workflow/`) — lanes key on the FIRST PATH COMPONENT
   under `docs/learned/` (`src/perk/learn/harvest.py::partition_lanes`), so two groups → two
   lanes → the live `run_harvest_wave` (`learning/harvest.ts::analyzeHarvest`'s whitelist
   re-decode, 2.3; the wave lifecycle, 2.1). **Runnability gate:** the emitted manifest must
   report `lane_count >= 2`; if not, the leg is not runnable as specified and the selection
   is corrected before any wave is claimed. Substitution rule if a named doc is missing at
   run time: the alphabetically first doc in the SAME top-level group directory. The
   curation disposition is the operator's; a zero-opportunity report, a declined draft, or a
   genuinely-earned saved objective are ALL legitimate recorded outcomes. (Flag syntax
   confirmed from `perk learn harvest --help` at run time: repeatable `--from TEXT`.)
   Session shape: a separate harvest session launched from this worktree, post-commit-1 /
   pre-submit.

**The `## Dogfood legs (Node 5.1)` evidence-comment schema** (posted on this plan's issue,
github #2149, by the operator or by the review session at the operator's direction; the
code-review leg completes only when every field is present): leg name; session run id; exact
invocation; the PR head SHA reviewed; wave launch summary (`launch.requested` /
`launch.runnable`) and completion/coverage; the posted review's URL or id; outcome
classification + residuals.

**Review-findings branch (the ordinary address loop, decided now):** if the own-PR review
demands changes, the address pass moves the published head — a sanctioned re-certification
event, not a protocol violation. A docs-only address keeps the §2 measurement valid (this
record's standing `git diff cead475a..HEAD -- extension/` command proves it); an address
touching `extension/` re-runs the four pipelines and appends a dated re-measurement addendum
(an evidence-only commit). In either case run-all `run_ci` re-runs before the re-publish,
and the evidence comment records the FINAL reviewed head (the schema's SHA field).

**Ready:** not re-dogfooded (the 1.1 record's leg C owns the family evidence); this layer's
own ready evidence, when it lands, is the §8.43 `perk:stack-ready-stamp` journal comment on
issue #2130 naming this plan (#2149) and its verified head (a self-describing forward
reference; no re-stamp chasing).

### Part B — evidence

#### Authoring — observed-live at planning (2026-09-04)

The 5.1 planning session (run `01M1PS2Z7R1RDFHR6JBJ9R69H3`, this worktree, predecessor head
`cead475a`) drove the full migrated authoring lifecycle: `plan_draft` through the
Plannotator browser `plan_review` with the reviewer wave, a DENY/revise round, and the
approval auto-save through `saveThroughApprovalGate`. Durable evidence: this plan issue
(github #2149) with its `plan-header` metadata block carrying that run id, and the plan
body's own review-settled markers (the "grill- and review-settled" assumptions block — the
revise round's product). Classification: **observed-live**.

#### Delivery — commit-compact pending its execution (this record's first commit)

The protocol places the commit-compact observation at this record's own first commit: this
file plus the Deliverable-2 annotations and the Deliverable-3 addendum are the real dirty
tree the migrated `pi/v1/delivery/commitCompact.ts` binding commits. The observed
report/continuation render is appended here in commit 2 (the 1.1 record's leg-D shape).

The run-all `run_ci` instance is **protocol-recorded**: one run-all green immediately before
`/submit` — its green report is definitive per the repo discipline; this protocol statement
is its recording (the settled precedent).

The `/submit` instance is **self-describing**: it completes when the PR for this plan exists
with the `plan-header`'s `published_head_sha` set; absent that, UNOBSERVED — NOT PASSED.

The commit-compact observation's report/continuation render is appended here in commit 2
with the real observed values (never authored ahead of the event); if the addendum is
absent, the commit-compact half of this leg reads UNOBSERVED — NOT PASSED. Commit 2 is a
planned pre-submit commit, so the published record carries the addendum or the honest gap —
never a placeholder that publication can strand.

#### Code review — forward-referenced, self-describing

Completes ONLY when the `## Dogfood legs (Node 5.1)` comment (the schema above, every field
present) exists on this plan issue (github #2149), recording the `/pr-review` blocking-wave
run on this node's own PR at its final reviewed head. Absent that comment, this leg reads
**UNOBSERVED — NOT PASSED** and the closeout is incomplete on the code-review family. No
machine gate enforces this (see the named enforcement gap above); the operator's ready
gesture is the enforcement point.

#### Learning — runs post-commit-1 / pre-submit; evidence appended in commit 2

The harvest leg runs as Part A item 4 specifies, after this record's first commit and before
`/submit`. Its evidence — the harvest run id, the manifest path including the observed
`lane_count` (the `>= 2` runnability gate's verdict), the wave launch/coverage manifest, and
the operator's curation outcome — is appended here in commit 2 with the real observed values
(never authored ahead of the event). If the addendum is absent, this leg reads UNOBSERVED —
NOT PASSED. Commit 2 is a planned pre-submit commit, so the published record carries the
addendum or the honest gap — never a placeholder that publication can strand.

## §4 Cleanup / residue

Named per leg:

- **Authoring:** no residue — the plan lifecycle's artifacts (the plan issue, its review
  trail) are the real workflow's own products, kept.
- **Delivery:** no residue — commit, compaction, CI, and submit are ordinary publication
  gestures this node needs anyway.
- **Code review:** the review artifacts on this node's own PR (the wave's posted review or
  👍) are a real workflow's products, kept. **Named standing residual:** the leg's
  completion is convention-enforced — no machine gate exists in the ready path; the
  `## Dogfood legs (Node 5.1)` comment is the only completion artifact, and its absence
  means UNOBSERVED — NOT PASSED. Building a machine gate is follow-up material, not this
  node.
- **Learning:** the harvest run's scratch manifest is ordinary run-scoped scratch (not
  authoritative; swept with the run directory); the curation outcome — recorded in the
  commit-2 addendum — is the operator's, and each arm (zero-opportunity report, declined
  draft, saved objective) is a legitimate outcome; nothing sacrificial is created by the
  protocol.
- **Measurement:** no generated baseline was stored; the pipelines are inlined commands over
  the working tree.

Residuals table:

| Residual | Disposition |
| --- | --- |
| Code-review leg completion is convention-enforced (no machine gate in the ready path) | Named, accepted; the evidence-comment artifact keeps it checkable; machine gate = follow-up material |
| Phase-7 record's leg E (the 7.5 stack-family protocol) remains UNOBSERVED — NOT PASSED | Recorded honestly in that record's Node 5.1 reconciliation addendum; deliberately not re-run by this node (out of scope); #2130's own land-time operations will exercise the sync/recover/land bindings as future events — not evidence for the 7.5 protocol |
| Phase-7 record's leg A commit-2-head run remains unrecorded | Recorded honestly in the same addendum; the final-head instance stays protocol-recorded per that record's own Part A step 3 |
