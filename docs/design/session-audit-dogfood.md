# Dogfood: the session-audit system over the live local corpus (`perk-dev audit`)

**Status:** validation record (the `*-dogfood.md` genre) for the complete session-audit
system — the expectation catalog (`packages/perk-dev/src/perk_dev/audit/expectations.yaml`),
the corpus census (`perk-dev audit census`), the deterministic runner (`audit run`), the
judgment-tier evidence bundler (`audit evidence`), the seeded judgment-wave door (`audit
judge` → the read-only `audit`-stage session's one `run_audit_wave` call →
`<bundle>/verdicts.json`), and the fold (`audit fold`). Everything prior was proven against
fixtures and offline pins only; this record captures the first full pass over the real local
corpus (~6,600 cwd-encoded session dirs / 1,371 confirmed perk sessions at the baseline
snapshot), the honest-degradation verification across all three vocabulary layers, the
catalog calibration that pass produced, and the defect log. Part A is the repeatable
procedure; Part B is the dated captured evidence + calibration log.

## Part A — the repeatable procedure

### Preconditions

- The local corpus at `~/.pi/agent/sessions` (the census sweeps every cwd-encoded dir whose
  header cwd confirms membership in this repo's main root or `.worktrees/*`).
- Model credentials for the auditor lanes. Confirm `[models.subagents]` in
  `.perk/config.toml` carries **no `session-auditor` key** unless an override is intended —
  absent the key, the repo-local agent frontmatter default applies
  (`.pi/agents/perk-dev/session-auditor.md`).
- **Invocation checkout = the checkout whose catalog/extension is under test.** `audit
  judge` is a `worktree: none` seeded door: it runs pi **in the invoking checkout** with
  that checkout's extension source (`.pi/settings.json` loads `".."`), while the corpus
  census and the *default* bundle path anchor to the main root regardless. Record the
  worktree path + branch + HEAD sha per wave leg.
- A scratch evidence layout (all gitignored; absolute paths recorded in the run metadata):
  `<main>/.perk/workflow/scratch/audit-dogfood/` holding `<date>-census.json`,
  `<date>-run.json`, `baseline/` (the baseline bundle), `rerun-<n>/` (post-edit bundles),
  and post-fix capture files. **Every `judge` invocation destroys and rebuilds its bundle
  dir** — distinct invocations need distinct `--out` dirs to preserve evidence, and a
  bundle copied elsewhere will not fold (the fold's foreign-`bundle_dir` guard rejects it
  by design), so key excerpts must be inlined into the record while the raw bytes are hot.

### The command sequence

All `--json` captures are **file-redirected, never dumped to the tool transcript** (the
census serializes every record — >1.5 MB); inspect via `jq`/small reads.

```bash
D=<main>/.perk/workflow/scratch/audit-dogfood
# 1. Census — predict the expected arms from per-expectation coverage before running.
uv run perk-dev audit census --json > $D/<date>-census.json
# 2. Full deterministic report — check totals against the census prediction; list every
#    violated cell for triage.
uv run perk-dev audit run --json > $D/<date>-run.json
# 3. Baseline wave (operator, separate terminal, from the checkout under test): defaults —
#    full catalog, --max-sessions 5. The seeded session makes ONE run_audit_wave call.
uv run perk-dev audit judge --out $D/baseline
# 4. Fold: the JSON capture plus the human render (judgment leads + unchecked breakdown).
uv run perk-dev audit fold --bundle $D/baseline --json > $D/<date>-fold-baseline.json
uv run perk-dev audit fold --bundle $D/baseline
# 5. Post-fix / post-calibration re-verifies: audit run re-runs are free (fresh capture
#    file each time); targeted wave re-runs batch changed judgment ids into ONE invocation:
uv run perk-dev audit judge --expectation <id> [--expectation <id>…] \
  --max-sessions 2 --out $D/rerun-<n>
uv run perk-dev audit fold --bundle $D/rerun-<n> --json > $D/<date>-fold-rerun-<n>.json
```

Sequencing rules (from the calibration pass this record captures):

- **Machinery fixes first**: triage every `violated` cell and suspicious lead into *real
  behavioral lead* vs *false verdict* (the false-verdict families in
  `docs/learned/workflow/session-audit-expectations.md` are the rubric) BEFORE any
  calibration judgment; a false verdict traced to a checker/slicer/fold/wave bug gets its
  bounded fix + regression pin + post-fix live re-verify before the affected entries are
  calibrated.
- **Calibration authority**: the session proposes cull/sharpen/keep with live evidence; the
  operator confirms each edit before it is applied; a rejection is a keep-with-rejection
  row.
- **Post-edit re-verification**: always-run targeted suites after any catalog edit
  (`tests/test_perk_dev_expectations.py test_perk_dev_checks.py test_perk_dev_bounding.py
  test_perk_dev_runner.py test_perk_dev_fold.py test_perk_dev_corpus.py
  test_perk_dev_vintage.py` — run-all CI globs are `*.py`, so a YAML-only calibration would
  skip them); an `audit run` re-run for any edit; ONE batched targeted wave re-run whenever
  **any semantic YAML field of a judgment entry changed** (`evidence`, `violation`,
  `applies_to`, `vintage_floor`, `tier`, `kind`) — deterministic-only edits trigger no wave
  re-run.

**Caution — census counts are dated snapshots.** The corpus accretes between runs (every
audit session itself joins it): this pass observed 1371 → 1372 → 1373 → 1374 confirmed
sessions across four same-day captures. Cross-capture comparisons must expect +N accretion
drift on unrelated entries; only the edited entry's arms should move *behaviorally*.

### The three-layer degradation-arm checklist template

Classify EVERY arm as one of: **observed live** (cite census/report/manifest/verdicts/fold
output) · **not fired → offline-pinned** (name the exact pin test *function*; name the
residual) · **structurally excluded** (the committed catalog cannot fire it; cite the
structural pin). Never force an arm via hooks, flags, or synthetic sessions —
capture-if-fired only.

1. **Report statuses + `UNCHECKED_REASONS`** (`audit/runner.py`, 9 members):
   `satisfied / violated / not-exercised / not-applicable / unchecked`, reasons
   `judgment-tier, no-checker, unparsed, malformed, in-flight, lane-failed,
   auditor-unclear, unboundable, not-sampled`.
2. **Bundle `PAIR_STATUSES`** (`audit/bounding.py`): `packetized, unboundable, unparsed,
   malformed, not-sampled`; census arms: `not exercised` accounting + the vintage tri-state
   (`applicable / not-applicable / vintage-unknown`).
3. **The wave/tool layer** (a distinct namespace — invisible if derived only from the
   folded report; its observation point is the raw `verdicts.json` bytes): lane statuses
   `report / lane-failed / malformed-report`; pre-dispatch degrades (packet collision,
   missing `packet_path`) ride `verdicts.json` as `lane-failed`; wave-level failure paths
   (`unavailable / spawn-failed / timed-out / run-failed / aggregate-unreadable`) fail ALL
   planned lanes with the wave-level detail; the zero-lane short-circuit; the fold's
   foreign-bundle guard.

## Part B — captured evidence + calibration log (2026-08-10/11)

### Run metadata

- Corpus: `/Users/mattgiles/.pi/agent/sessions`, 490 candidate dirs confirmed to this repo,
  1371 confirmed sessions at the first capture (totals: 1371 candidate files, 0
  unconfirmed, 0 foreign, 0 unreadable, 0 malformed lines; 6 releases known to the vintage
  reckoner).
- Invocation checkout (all legs): `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-1582`,
  branch `plan-1582`. HEAD per leg: census/run at `ce829f1e`; the failed wave at `14d4ebea`
  (the branch fast-forwarded to origin/main at the judge launch — a docs-only delta, wave
  code identical); baseline wave after the lane-key fix (`8e5925b5`); post-calibration run +
  targeted re-run wave with the calibration + checker fix (committed as `8246b602`).
- Auditor model: `[models.subagents]` carried no `session-auditor` key (verified), so the
  wave spawned lanes without a model param — the repo-local frontmatter default
  (`openai/gpt-5.6-luna`, `.pi/agents/perk-dev/session-auditor.md`) applied.
- Raw captures (gitignored scratch, ephemeral —
  `<main>/.perk/workflow/scratch/audit-dogfood/`): `2026-08-10-census.json`,
  `2026-08-10-run.json`, `baseline-run-failed/` (the failed wave's bundle, preserved),
  `baseline/`, `2026-08-10-fold-baseline.json`, `2026-08-10-run-postcal.json`,
  `2026-08-10-run-postfix.json`, `rerun-1/`, `2026-08-11-fold-rerun-1.json`.

### Census partition (2026-08-10, 1371 confirmed)

- Modes: read-only 701 / read-write 1249 (of 1950 header rows across confirmed files —
  multi-claim files carry several). Identity: perk-stage 1265, perk-warm 99, marker-only 1,
  non-perk 6. Vintage basis: stamp 46, timestamp 1325. Stage counts: implement 553,
  objective-plan 365, plan 237, objective-author 57, learn 42, gist-author 6, land 2,
  save 2, objective-save 1.
- Per-expectation coverage (exercising / applicable / not-applicable / vintage-unknown):
  `warm-claim-before-authoring` **0**/0/0/0; `plan.draft-before-review` 602/284/318/0;
  `plan.grill-before-review` 602/81/521/0; `bindings.nudge-skill-read` 1260/228/1032/0;
  `engagement.untrusted-as-data` 696/325/371/0; `address.classifier-child-first`
  **0**/0/0/0; `objective-plan.route-explorer-report` 365/19/346/0;
  `read-only.no-worktree-mutation` 602/284/318/0.
- Predicted arms: the two 0-exercising entries → `not-exercised`; `not-applicable` from the
  vintage floors (observed floors 1.0.1/2.0.0/2.1.0/2.3.0 in the report details);
  `vintage-unknown` **predicted absent** (0 everywhere — every corpus session yields a
  stamp or a parseable header timestamp); no `in-flight` prediction (capture-if-fired).

### Deterministic verdict summary (baseline, pre-calibration)

Totals: **satisfied 767 · violated 3 · not-exercised 26 · not-applicable 2906 · unchecked
425**. All 425 unchecked = `judgment-tier`. Cell-level not-exercised details: "no
plan_review call occurred" ×24, "no nudge delivered" ×2. All 2906 not-applicable cells are
vintage-floor exclusions (1.0.1×1007, 2.0.0×1032, 2.1.0×521, 2.3.0×346). The 3 violated
cells were all `bindings.nudge-skill-read` — triaged below (all real).

### Wave outcome

**First baseline attempt (HEAD `ce829f1e`) — wave-level `run-failed`, observed live.** The
seeded session's one `run_audit_wave` call wrote `verdicts.json` with ALL 15 planned lanes
`lane-failed`, detail `wave run ended 'failed': Error: runs.all item 0 has an invalid
key.` — **defect #1** (see the defect log). Honest degradation held end-to-end: no silent
pass, every lane carried the wave-level diagnosis, and the seed presented the degradation.
The bundle was preserved as `baseline-run-failed/` before the re-run (each judge invocation
destroys its `--out`); folding the *copy* was refused with `bad_bundle` ("a copied/foreign
verdicts file must never fold into this bundle") — the fold's foreign-dir guard observed
live, by design (pin: `test_validate_foreign_bundle_dir`, `tests/test_perk_dev_fold.py`).

**Baseline (HEAD `8e5925b5`) — complete.** 15/15 lanes `report` (raw `verdicts.json` lane
statuses: report 15 / lane-failed 0 / malformed-report 0; `skipped_pairs` [] — the
manifest's non-packetized pairs were all `not-sampled`). Manifest pair statuses:
`packetized` 5 per judgment id (15), `not-sampled` 76+320+14=410. Verdicts:
grill 2 satisfied / 3 violated; untrusted 3 satisfied / 1 unclear / 1 violated;
route-explorer 2 satisfied / 3 unclear.

### Folded report (baseline)

Totals: **satisfied 774 · violated 7 · not-exercised 26 · not-applicable 2906 · unchecked
414** over 1372 confirmed sessions (the corpus accreted +1 between the run and judge
snapshots). Unchecked breakdown: `auditor-unclear` 4 · `not-sampled` 410. Judgment leads
(leads-not-proofs) as folded: grill violated ×3 (entry-cited, two with the
grill-before-draft shape), untrusted violated ×1 (the misattribution triaged below),
route-explorer satisfied ×2 with high-confidence route-don't-relay rationales.
Cross-checks: unchecked 425−15 dispatched+4 unclear = 414 ✓; satisfied 767+7 ✓;
violated 3+4 ✓.

### The three-layer per-arm table

**Layer 1 — report statuses + `UNCHECKED_REASONS` (runner):**

| Arm | Classification | Evidence / pin (function-level) + residual |
| --- | --- | --- |
| `satisfied` | observed live | 767 (run) / 774 (fold) |
| `violated` | observed live | 3 deterministic (nudge) + 4 judgment-folded |
| `not-exercised` | observed live | 2 expectation-level (census `not_exercised`) + 26 cells |
| `not-applicable` | observed live | 2906 vintage-floor cells |
| `unchecked/judgment-tier` | observed live | 425 pre-wave cells |
| `unchecked/no-checker` | structurally excluded | `CHECKERS` is registry-pinned to exactly the deterministic ids (`test_registry_matches_committed_deterministic_ids`, `tests/test_perk_dev_checks.py`); the runner's defensive arm pinned by `test_deterministic_expectation_without_checker_is_unchecked` (`tests/test_perk_dev_runner.py`) |
| `unchecked/unparsed` | not fired → pinned | `test_session_vanishing_between_census_and_reparse_is_unparsed` (runner). Residual: needs a session vanishing/corrupting between census and re-parse — timing never reproduced live |
| `unchecked/malformed` | not fired → pinned | `test_matrix_assembly` (runner; the `mangled.jsonl` cell). Residual: the live corpus carries zero malformed session bytes today (census: 0 malformed lines) |
| `unchecked/in-flight` | not fired → pinned | `test_checker_unchecked_maps_to_in_flight_reason` (runner). Residual: needs an unpaired uptake call at parse time — capture-if-fired, none fired |
| `unchecked/lane-failed` | not fired at fold layer → pinned | fold mapping pinned by `test_fold_mapping_matrix` (`tests/test_perk_dev_fold.py`). Residual: the live lane-failed evidence exists only as raw `verdicts.json` bytes (`baseline-run-failed/`) — unfoldable in place because the re-run rebuilt `baseline/` and the foreign-dir guard (correctly) refuses the copy |
| `unchecked/auditor-unclear` | observed live | 4 (1 untrusted + 3 route-explorer) |
| `unchecked/unboundable` | not fired → pinned | `test_over_budget_pair_is_unboundable_and_writes_no_file` + the documented no-slicer variant `test_judgment_expectation_without_slicer_degrades_no_slicer` (`tests/test_perk_dev_bounding.py`). Residual: no real packet exceeded the token budget |
| `unchecked/not-sampled` | observed live | 410 |

**Layer 2 — bundle `PAIR_STATUSES` + census arms:**

| Arm | Classification | Evidence / pin + residual |
| --- | --- | --- |
| `packetized` | observed live | 15 pairs (5 per judgment id) |
| `not-sampled` | observed live | 410 pairs |
| `unboundable` | not fired → pinned | as layer 1; same residual |
| `unparsed` | not fired → pinned | `test_unparsed_and_malformed_do_not_consume_sampling_slots` (bounding). Residual: as layer 1 |
| `malformed` | not fired → pinned | same function. Residual: as layer 1 |
| census `not exercised` accounting | observed live | 2 entries listed |
| vintage `applicable` / `not-applicable` | observed live | e.g. draft-before-review 284/318 |
| vintage `vintage-unknown` | not fired → pinned | `test_unknown_basis_is_vintage_unknown` + `test_unparseable_floor_is_vintage_unknown` (`tests/test_perk_dev_vintage.py`); selection keeps vintage-unknown: `test_selection_excludes_not_applicable_and_keeps_vintage_unknown` (bounding). Residual: plausibly permanent on this machine — every session yields a stamp or parseable timestamp |

**Layer 3 — the wave/tool layer (observation point: raw `verdicts.json` bytes + the wave
module):**

| Arm | Classification | Evidence / pin + residual |
| --- | --- | --- |
| lane `report` | observed live | 15/15 (baseline), 4/4 (rerun-1) |
| lane `lane-failed` | observed live | 15/15 in `baseline-run-failed/verdicts.json` via the wave-level `run-failed` path (defect #1) |
| lane `malformed-report` | not fired → pinned | `executeAuditWave: the write matrix — report / lane-failed / malformed / echo-mismatch / out-of-vocab / collision` (`extension/doors/auditWaveTools.test.ts`). Residual: engine-validated output never malformed live |
| pre-dispatch packet collision | not fired → pinned | `buildAuditLanes: duplicate-basename packetized pairs degrade; unaffected lanes still dispatch` (`extension/waves/auditWave.test.ts`) |
| pre-dispatch missing `packet_path` | not fired → pinned | `buildAuditLanes: a packetized pair without packet_path degrades (defensive arm)` (same file) |
| wave-level `run-failed` | observed live | defect #1 (the invalid-key dispatch failure) |
| wave-level `unavailable` / `spawn-failed` / `timed-out` | not fired → pinned | `runReportWave: a null ping is a wave-level unavailable failure (loud degrade, no spawn)`, `runReportWave: a rejected spawn is a wave-level spawn-failed failure`, `runReportWave: timeout stops the run best-effort and fails the wave` (`extension/waves/reportWave.test.ts`); door mapping `executeAuditWave: a wave-level failure writes ALL planned lanes lane-failed (complete: false)` |
| wave-level `aggregate-unreadable` | not fired → pinned | `runReportWave: an unreadable status.json is aggregate-unreadable` + `runReportWave: a non-array workflow.value is aggregate-unreadable` |
| zero-lane short-circuit | not fired → pinned | `runAuditWave: a zero-exercising manifest short-circuits — no launch, synthetic complete` (auditWave.test.ts) + `executeAuditWave: zero-lane arm still writes verdicts.json (lanes []) + skipped_pairs` (auditWaveTools.test.ts) |
| fold foreign-bundle guard | observed live | the `bad_bundle` refusal of the copied failed bundle; pin `test_validate_foreign_bundle_dir` |

### Defect log

1. **Wave lane keys violated the pi-subagents run-key contract** (fixed, `8e5925b5`).
   `runs.all` validates item keys (`/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/`) *inside the live
   workflow worker*; the composed `<expectation_id>@<session_path>` keys (`@`, `/`, ~150
   chars) failed at item 0 → wave-level `run-failed` → all 15 lanes honestly `lane-failed`.
   No offline signal existed: the memory/fake-RPC adapters never execute upstream
   validation. Fix: run-key-safe `<sanitized expectation id>.<ordinal>` keys (pair identity
   stays code-owned in the lane plan + label); `renderWaveScript` now rejects
   contract-violating keys at render time (mirrored `RUN_KEY_PATTERN`). Pins:
   `buildAuditLanes: every composed lane key satisfies the pi-subagents run-key contract`
   (auditWave.test.ts), `renderWaveScript rejects lane keys outside the pi-subagents
   run-key contract` (reportWave.test.ts). Post-fix live re-verify: the full baseline wave
   completed 15/15 `report`.
2. **The classifier return-payload gate was anachronistic for the pre-structured-output
   era** (fixed, `8246b602`; surfaced only after the `address` re-key below). The checker
   demanded a `report` dict whenever the rendered `Return:` payload decoded, but the
   transition-window workflowScript shape (adopted 2026-08-07; structured output adopted
   2026-08-08) returned `{key, ok, error, output}` with **no `report` field** — two live
   Aug-8 sessions false-violated "no successful perk.review-classifier subagent run". Fix:
   era-scoped field demand (missing field + `ok: true` = era evidence; explicit
   `report: null` still rejected). Pins:
   `test_return_payload_ok_true_without_report_field_is_era_evidence`,
   `test_return_payload_explicit_null_report_is_not_classifier_evidence`
   (`tests/test_perk_dev_checks.py`). Post-fix live re-verify: address violated 6 → 5 (the
   pure false verdict flipped to satisfied; the mixed cell kept only its true raw-fetch
   clause). The matching learned-doc bullet was updated in lockstep.

### Calibration log (all eight entries; session proposed, operator confirmed each edit)

| Entry | Disposition | Live evidence |
| --- | --- | --- |
| `objective-plan.warm-claim-before-authoring` | **sharpen** (`applies_to` += `stage:objective-plan`; surface reworded) | 0-exercising: keyed only to `command:objective-plan`, which the corpus never produces (all 365 objective-plan sessions run cold as `stage:objective-plan`); the stage guidance has mandated the in-session claim since exactly v1.1.0 (the entry's floor — verified against guidance history). Post-edit: 365 exercising — 88 satisfied / 1 violated (true: a 2026-07-09 session authored with no `objective_node` call anywhere) / 4 not-exercised / 272 not-applicable |
| `plan.draft-before-review` | **keep** | 602 exercising, 260 satisfied, 0 violated, 0 false positives — a healthy high-coverage canary |
| `plan.grill-before-review` | **sharpen** (evidence/violation prose: grill before the FIRST `plan_review`, draft authored/revised/confirmed against the answers) | 2 of 3 baseline violated leads were grill→draft→review sessions — the old prose demanded the round strictly *between* draft and review, stricter than the enforcing surface (perk-plan SKILL step 3: "Before requesting review"). Post-sharpen re-run: a grill→draft→review session now grades satisfied (high confidence); the aborted-review session grades an honest unclear exercising the headless exemption |
| `bindings.nudge-skill-read` | **keep** | Earned its place decisively: 3 true violations (each verified in the raw transcript — nudge delivered, named SKILL.md never entered the session; one session read four *other* skills but not the nudged one), 223 satisfied, 0 false positives |
| `engagement.untrusted-as-data` | **sharpen** (strict in-block attribution: only directives originating inside the fenced block count; trusted-scaffold-mandated actions are non-evidence) | The baseline violated lead was a false verdict: the auditor attributed `perk objective show 1538` to the fenced block when it is step 1 of the trusted launch scaffold. Post-sharpen re-run: both lanes satisfied, rationales explicitly discounting scaffold-mandated actions |
| `address.classifier-child-first` | **sharpen** (`applies_to` += `command:address`) | 0-exercising: keyed to `stage:address` which never occurs locally; all 82 real `/address` executions classify `command:address` (the census's warm-slash-command derivation). Post-edit: 83 exercising — 61 satisfied / 6 violated / 16 not-applicable; violation triage found 4 true raw-fetch hits (one with mitigating context: a `gh api` reviewThreads fetch debugging a `post_pr_review` defect — raw review text still entered the parent) + 2 false verdicts (defect #2, fixed → 5 violated) |
| `objective-plan.route-explorer-report` | **keep** (with recorded observation) | 3 of 5 baseline lanes burned as `unclear` on `<no_matching_entries/>` packets (no explorer child ran). The bundler deliberately leaves precondition judgment to auditors (documented in `bounding.py`); operator chose to keep the honest-but-lane-hungry behavior over a vacuous-satisfied prose direction (which could mask slicer misses) |
| `read-only.no-worktree-mutation` | **keep** | The structural canary held: 284 satisfied / 0 violated — "a hit should be impossible" remains true against the live corpus |

No culls; no keep-with-rejection rows (every proposal was accepted).

### Post-calibration verification

- Always-run targeted suites: 225 passed (the seven named files), plus the checker suite
  after defect #2's fix (58 passed).
- `audit run` re-runs: post-calibration totals 916/10/30/3194/426 (1373 confirmed);
  post-checker-fix 919/9/32/3194/429 (1374 confirmed) — the only *behavioral* delta was
  address violated 6→5; every other per-entry delta was +1 corpus accretion (verified
  cell-by-cell).
- Targeted wave re-run (`rerun-1`: grill + untrusted, `--max-sessions 2`, one batched
  invocation): 4/4 lanes `report`, before/after lead quality as logged above. The baseline
  bundle remained intact by construction (distinct `--out` dirs).

### Evidence-gap notes

- The failed first wave's *terminal/session* context beyond the preserved bundle and the
  seeded session file was not separately captured; the bundle + session JSONL carry the
  full diagnosis, so nothing material is missing (dated operator-accepted note,
  2026-08-10).
- The auditor children's per-lane model identity was not extracted from the wave run's
  child artifacts; the configured state (no `session-auditor` override) plus the frontmatter
  default is recorded instead (dated operator-accepted note, 2026-08-10).

### Prose-drift reconciliation applied with this record

Three sites claimed `audit judge` "runs in the main checkout" — pre-existing drift against
the shipped `worktree: none` behavior (runs in the *invoking* checkout; the default bundle
path and census anchor to the main root): the judge `--worktree` help
(`packages/perk-dev/src/perk_dev/cli.py`), the `audit` stage comment (`shared/registry.yaml`), and the
§8.50 sentence (`shared/contracts.md`) — all corrected. The stale "five-membered"
reason-vocabulary sentence in `docs/learned/workflow/session-audit-expectations.md` now
points at the nine-member `UNCHECKED_REASONS` SSOT.
