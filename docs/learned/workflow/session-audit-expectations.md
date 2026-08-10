---
title: The session-audit expectation catalog — curation semantics, census pins, checker constraints
read_when: You are curating perk-dev audit expectations (expectations.yaml), the audit census/vintage reckoning, a session-audit checker, evidence packets, the verdicts-write/fold seam, or the read-only gate.
---

# The session-audit expectation catalog

The perk-dev session-audit expectation catalog lives in
`packages/perk-dev/src/perk_dev/audit/` (`expectations.yaml` + the `load_catalog` loader in
`expectations.py`). Each entry states an expectation about how a perk-driven session should have
behaved, for auditors — human or checker — to grade transcripts against. This doc carries the
curation semantics that entry prose and the schema can't express on their own.

## Expectation prose must mirror the enforcing surface's actual semantics, not its intent

When an entry claims determinism or structural impossibility, verify the claim against the
enforcing code *at the leniency level*, not the headline behavior — the false-violation paths
hide in the documented carve-outs. Two shipped instances, both reworded in review:

- **Prompt-hidden skills reach a session by more than one route.** `disable-model-invocation:
  true` hides a skill from the *model* prompt but preserves human `/skill:<name>` invocation,
  which injects the body without any exact-path read — and a transclude-mode binding inlines the
  body at delivery time with no read to demand at all. The `bindings.nudge-skill-read` entry
  accepts any of these as uptake evidence — an exact-SKILL.md read (read tool or read-only
  bash), a `/skill:<name>` invocation, or a transcluded delivery — presence-anywhere in the
  session file, and the shipped deterministic checker
  (`packages/perk-dev/src/perk_dev/audit/checks.py`) implements exactly those routes. A checker
  keyed to fewer routes reports false violations for humanly-invoked or transcluded skills.
- **The read-only gate is an allowlist backstop with accepted, documented leniencies — not a
  mutation classifier.** The gate (`extension/substrate/toolGating.ts`) deliberately permits
  argument-blind `curl`, `agent-browser`
  (whose output flags can write files), and `subagent` with no agent allowlist, so a gate-active
  session *can* mutate the checkout through an accepted leniency with nothing broken. The
  `read-only.no-worktree-mutation` structural canary is scoped to the gate's *direct backstop*
  with the leniencies explicitly carved out of the "should be impossible" claim — otherwise a
  leniency-path mutation would falsely indict the gate, defeating the canary's calibration
  purpose.

## Coverage-shaped self-checks don't pin inventory

Self-checks shaped like "non-empty" or "spans all kinds" still pass if the catalog silently
shrinks. The census test (`test_committed_catalog_census` in
`tests/test_perk_dev_expectations.py`) is an **exact-id-set pin** — set equality plus
`validate()`'s duplicate-id rejection also pins the count — so curating a new expectation is a
deliberate two-file edit (catalog YAML + census). A fresh instance of the exact-set-pin pattern
in `test-pin-sweeps.md`.

## The audit census + vintage reckoning

The census/corpus/vintage subsystem lives in `packages/perk-dev/src/perk_dev/audit/`
(`corpus.py` for membership, `vintage.py` for release reckoning). The durable rules:

- **A cheap prefilter must be at least as permissive as its downstream authority under every
  normalization the authority accepts.** Membership compares header cwds against both given and
  resolved root spellings (the macOS `/private` symlink family), so the candidate-dir prefilter
  must encode both spellings too — asymmetric normalization silently filters out sessions before
  the authority runs: **silent false negatives, the worst failure mode for a census/coverage
  tool**.
- **Comparing dates across clock domains needs a skew margin, not strict comparison.** Changelog
  release headers carry the maintainer's local day; session timestamps are UTC — a release
  stamped locally on day D can occur as late as UTC day D+1, so "latest release strictly before
  the session" can promote a session past a release it predates (the exact false-violation
  family the gate exists to prevent). Shipped rule: the estimate is the latest release dated
  **more than one day** before the session's UTC date; pre-history means "qualifies for no
  release". General form: the margin must cover the maximum offset skew (≥1 day down to UTC-12).
- **A plan decision surviving grilling is not proof of correctness.** The strict-before tie-break
  was explicitly grilled-and-confirmed and still wrong; the independent correctness lane
  reasoning from the *invariant* (not the plan) caught it.
- Coordination/coarseness notes: the `perk_version` stamp key is coordinated by docstring prose
  (`vintage.py`/`corpus.py`), not a shared constant — the workflow-state writer must honor it
  byte-for-byte. Accepted coarseness errs toward not-applicable (between-release dev sessions
  report the last released version; the one-day margin can estimate one release low).
  Skill→trigger classification uses the shipped default bindings, not the user overlay — a
  flagged best-effort approximation.

## Writing a session-audit checker — the false-verdict families

The deterministic tier (`perk-dev audit run`; `packages/perk-dev/src/perk_dev/audit/checks.py` +
`runner.py`) grades live transcripts, so a checker's failure mode is a **false verdict**, not a
test failure. The recurring families:

- **A live corpus means absence needs a pending arm.** Still-appending sessions make
  absence-shaped verdicts (no claim, no classifier run, no uptake) flippable by a pending
  execution → return `unchecked`, never a definitive `violated`. Presence-shaped violations stay
  decisive (a pending call cannot un-happen them). The status vocabulary grew a 4th checker
  status (`unchecked`) and the runner's `UNCHECKED_REASONS` a 5th member (`in-flight`) —
  consumers of the report JSON should know the reason vocabulary is five-membered.
- **Mention is not execution.** Command-string signatures must match in *command position* per
  top-level segment — a whole-string scan false-violates on an echo/grep of an example. Applied
  uniformly: the raw-fetch veto, reader-command uptake, and the classifier launch (matched in
  *agent position*, never a task-string mention).
- **Substring is not structure.** Classifier evidence requires an agent-position match plus a
  best-effort decode of the rendered return payload (`ok: true` + a non-null report) — a
  workflow that completed while its child failed is not evidence; an undecodable payload falls
  back to the error-flag gate alone.
- **Ancestor chains don't order same-entry calls.** One assistant message batches multiple tool
  calls; ordering checks need tool-call position *within* the entry in addition to branch
  ancestry.
- Shipped memoization shape worth reusing: compute the parents table once per checker invocation
  and thread it (`parents_table` in `checks.py`); gate-engagement is one O(n) forward pass
  (every parent index precedes its child).
- **Catalog prose and this doc state one rule** — an `expectations.yaml` evidence-semantics
  amendment drags the matching bullet here in the same PR (that lockstep already fired once).

Calibration leads for later checker work: the gate-policy plain copy (`gate_policy.py`) has no
drift guard by decision; pinned string anchors drift as **false verdicts, not test failures**;
id-less call/result lines pair FIFO-by-name best-effort; a fabricated ok/report return is not
deterministically detectable.

## Bounding judgment-tier evidence packets

The judgment tier's packet bounding (`perk-dev audit evidence`;
`packages/perk-dev/src/perk_dev/audit/bounding.py`) has its own trap families:

- **File adjacency ≠ causal adjacency.** Pi session JSONL is a `parentId` tree, so any windowing
  must be descendant-restricted (over `parents_table`) or a sibling branch's entries ride
  another branch's anchor window; a rendered slice interleaves a `<branch_point id parent/>`
  marker wherever an included entry doesn't continue from the preceding one, so the slice
  carries its own lineage.
- **A known data-shape fact must be re-checked against each new access pattern** (selection vs
  slicing vs windowing) — the tree fact was already documented but its windowing consequence
  wasn't re-derived at plan time. And **audit sibling consumers of a data shape for invariants
  they already encode**: the deterministic checkers had the branch discipline the bounding plan
  re-forgot; the fix promoted the checkers' parents table to a public seam.
- **A status reused by a defensive arm needs its field-semantics variant made explicit.** The
  defensive no-slicer arm reuses `unboundable` but honestly supplies neither pinned field; the
  resolution is a documented + test-pinned variant, never fabricated values. When a status
  vocabulary is a downstream-consumed contract, every arm reusing a status either satisfies its
  pinned field semantics or ships a named pinned variant.
- A new instance of the existing "a plan decision surviving grilling is not proof of
  correctness" rule: the file-order windowing defect survived grilling; the review wave caught
  it.

## The verdicts-write hardening patterns (audit judge → run_audit_wave → audit fold)

The judgment tier's write path — `perk-dev audit judge` builds the bundle, the wave
(`extension/waves/auditWave.ts` + `extension/doors/auditWaveTools.ts`) writes `verdicts.json`,
`perk-dev audit fold` (`packages/perk-dev/src/perk_dev/audit/fold.py`) folds it — hardened into
a reusable pattern set:

- **Strict wholesale consumer ⇒ per-record sanitizing producer.** The Python fold's `validate()`
  rejects unknown vocabulary wholesale (`bad_bundle`), so the wave's writer re-sanitizes each
  engine-validated auditor report before the `verdicts.json` write: an out-of-vocabulary
  verdict/confidence/citation shape degrades to `malformed-report`, an echoed-identity mismatch
  degrades to `lane-failed`, and `session_path` stays code-owned (copied from the manifest pair,
  never child-echoed). One unsanitized lane must degrade honestly, not poison the bundle.
- **Invalidate-before-publish.** In a multi-artifact snapshot build, unlink stale derived
  artifacts (the prior `verdicts.json`) FIRST, before publishing any new input artifact — an
  interruption mid-sequence must leave a fail-safe state, not prior verdicts beside a fresh
  snapshot that the fold's bundle-dir check cannot detect.
- **"Every degradation carries a presentable diagnosis" means guarding blanks, not just
  absences** — the detail fallback covers `detail: ""` as well as a missing key.
- **Uniqueness invariants span the whole artifact** — the fold keys cells by
  `(expectation_id, session_path)` with one `seen` set across all result rows; a per-row scope
  lets cross-row duplicates double-fold.
- **The zero-lane arm is narrow**: `lanes: []` holds only when no packetized pair *degraded* —
  pre-dispatch degrades (basename collision, missing packet path) still ride `lanes` as
  `lane-failed`.
- **Read-then-parse catch sets need `UnicodeDecodeError`** — it escapes `read_text` before
  `json.loads` runs, so `(OSError, JSONDecodeError)` silently misses invalid UTF-8. The fold's
  bundle reads carry the full set; `learn-evidence-pipeline.md` and `session-data.md` record the
  same fact — cross-reference rather than restate.

Residual: the wave suites are memory-adapter/fake-RPC only — the first live wave run is the
integration test; the scale envelope is ~≤15 lanes at default ceilings.

## Known open edges for checker work

- `command:<id>` `applies_to` selectors are declared but **not existence-validated**; their
  session-mapping semantics land only with the classifier.
- `vintage_floor` values are round-up estimates; a release-history mapping may lower some — a
  data edit, not a schema event.
- One entry's headless exemption (grill-before-review) lives only in its evidence prose — the
  trigger grammar cannot express interactivity, so judgment auditors must honor it from the text.

## perk-dev subpackage conveniences

- A new `perk_dev/<sub>/` needs **zero toolchain wiring** — the hatchling package glob, the
  ruff/ty scopes, and the root `tests/test_perk_dev_*.py` convention all cover it automatically.
- Dev-only editable packages use plain `Path(__file__).with_name(...)` resource lookup — no
  dual-mode resolution needed when the package is never published.

## Cross-references

- `docs/learned/workflow/test-pin-sweeps.md` — the exact-set-pin pattern the census instantiates
- `docs/learned/workflow/pydantic-boundary-models.md` — the loader/validator house pattern
  (`load_catalog` is the family's canonical fixed shape)
- `docs/learned/workflow/skill-bindings.md` — the skill-delivery routes the nudge entry grades
