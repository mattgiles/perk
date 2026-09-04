---
title: Session data, run identity, provenance & GC
read_when: You are working on run_id minting/claiming, sessionData.ts / state/cache.py, atomic workflow writes, provenance pointers, the perk_version stamp, session-data consumers, or state prune/cache-gc.
cluster: plan-lifecycle
---

# Session data, run identity, provenance & GC

Objective #339 built one lifecycle: a session gets a run identity (minted or claimed), keys its
scratch data dirs by it, records provenance pointers for artifacts it writes, and a GC eventually
prunes the dirs. The pieces only make sense against each other — this doc carries the whole
narrative: identity → data dirs → provenance → the read-only writer → GC.

## Distillation

- Warm sessions mint a hand-rolled ULID in `session_start`'s `none` arm (NOT `decideClaim`);
  cross-plane validity is proven by grammar, not subprocess; the mint append is
  loud-but-non-fatal — "Warm run_id minting".
- The perk version is stamped into workflow-state at **run-identity establishment** (the four
  identity arms — claim/fork/adopt/mint); ordinary state appends carry no stamp — "The
  `perk_version` vintage stamp".
- TWO current-run resolvers exist ON PURPOSE with opposite degradation (`activeRunId` stamps a
  fallback; `activeSessionRunId` degrades to null) — do not unify; a null-degrading resolver
  never feeds a refuse/allow gate — "The accessor seam + the two-resolver doctrine".
- Multi-file trusted state chains digests through ONE workflow-state anchor; marker-clears are
  verified invalidation — "Provenance pointers".
- All `.perk/workflow/` writes route through the per-plane atomic seam; corruption has a DECODE
  stage before the parse stage (catch `UnicodeDecodeError` too) — "The atomic-write seam +
  corruption posture of `.perk/workflow/`".
- Reclaim features follow the destructive-op triad: pure-read policy module + report-only doctor
  check + ONE destructive command — "GC: the destructive-op triad".
- Adding a consumer of session data follows the full recipe — "Adding a session-data consumer
  (the full recipe)".

## Warm run_id minting

- **The mint lives in `index.ts`'s `session_start` `none` arm, NOT in `decideClaim`** — keeping the
  pure decision function byte-identical bought claim/keep/fork stability *by construction* (the
  existing lifecycle tests were the regression proof, literally).
- `extension/substrate/runId.ts` is a **hand-rolled spec-conformant ULID** (~40 lines, no npm dep): 10 time
  chars by repeated div/mod of `Date.now()` (48-bit, plain `Math.floor` arithmetic — no BigInt),
  16 randomness chars by a standard 5-bit bit-walk over `randomBytes(10)`.
- **Cross-plane validity is proven by grammar, not subprocess**: the TS test pins the exact
  Crockford regex (`/^[0-9A-HJKMNP-TV-Z]{26}$/`) as the proof Python's `ULID.from_str` parses
  minted ids — no node→pytest bridge. Cheap and sufficient when the foreign parser is
  spec-anchored.
- The sentinel `source: "mint"` is observability, deliberately NOT pinned in contracts §8.7;
  `shared/registry.yaml`'s per-stage `run_id` policy governs stage *transitions* — don't "fix" it
  to mention warm minting (§8.2's three-way doctrine is canonical).
- The mint append is **loud-but-non-fatal on read-back failure**: the session continues
  unidentified and re-mints on the next `session_start`; downstream accessors must tolerate
  `run_id === undefined`.

## The `perk_version` vintage stamp

(Anchors: `extension/substrate/resources.ts` `versionStamp`, the `session_start` identity arms in
`extension/index.ts`, the additive `WorkflowState.perk_version` field, contracts §8.3.)

- The running perk version is stamped into workflow-state at **run-identity establishment** (all
  four identity arms — claim/fork/adopt/mint); the read side is the audit census's vintage
  reckoning (cross-ref `session-audit-expectations.md`, which carries the docstring-coordinated
  key rule).
- **Failure sentinels that are valid domain values must be filtered at the write boundary.** The
  version reader's `"0.0.0"` failure sentinel parses as strict X.Y.Z — if stamped it would flip
  the vintage reader from an honest timestamp-estimate to a *wrong exact* answer. The pattern: a
  tiny pure filter (`versionStamp`) living beside the sentinel's producer, keeping sentinel
  knowledge confined to the owning module instead of leaking equality checks to call sites.
- **A deliberate non-write deserves its own regression test.** The keep arm intentionally never
  backfills (LWW backfill would mis-stamp an old session with today's version); that absence is
  load-bearing behavior pinned by a negative test (plant a legacy pre-stamp session, assert the
  field stays undefined through keep and reload) — never just narrated in prose.
- Accepted coarseness: under a stale lazy-loaded extension the stamp records the *extension's*
  version, not the launching CLI's — bounded by the vintage layer's conservative min-wins
  posture; pre-stamp sessions stay timestamp-estimated forever by design.

## The accessor seam + the two-resolver doctrine

There are intentionally **TWO** current-run resolvers in the extension with opposite degradation:

- `coldDoor.activeRunId` stamps a `cold-door-<ts>` fallback — right for stdin-staging
  debuggability.
- `sessionData.activeSessionRunId` degrades to `null` — a stamp would orphan data dirs and break
  run_id-keyed provenance.

**Do not unify them.** The divergence is documented in both headers and in contracts §8.1.

Also: `list_dispatch_records` composes through `list_run_ids` (dirs-only enumeration) — any future
stray-file-in-`runs/` semantics live in one place.

A third grade for gates (#1992): **a null-degrading resolver is unsafe as input to a
refuse/allow gate.** Gates that branch on presence/absence read one snapshot with error
distinction and refuse `bad_state` on couldn't-read — "confirmed absent" ≠ "couldn't read".

## Provenance pointers

- **The repo digest convention**: `sha256:<hex>` lowercase, computed by
  `extension/substrate/sessionData.ts:digestSessionData` over bytes **read back from disk after the write**
  — not the in-memory string (catches encoding/disk surprises). Reuse the exported helper; never
  mint a second convention.
- **Per-field LWW means map-valued workflow-state fields must append the whole merged map**:
  rebuild, spread the prior map, append `{...prior, [name]: pointer}`. Appending only the new
  entry clobbers siblings. Any future per-name map field in `WorkflowState` inherits this rule.
- **A recorded `path` is informational only** — workflow-state entries are reconstructable from
  untrusted session history, so validation always re-derives the path from `run_id` + `name`
  through the owning seam and never dereferences `pointer.path`. Generalizes: never trust a
  path/locator stored in a session entry.
- **Refusal tiering is two-grade by design**: run_id mismatch → *silently classified `absent`*
  (it IS the fork-no-inheritance / concurrent-isolation mechanism, not an anomaly);
  pointer-present-but-broken (missing file, digest mismatch) → the seam's `invalid{problem}`
  arm plus its own stderr warn (a broken promise). Don't "fix" the
  silent arm into a warning — forks would spam. Review-style draft consumers (gist/objective)
  fold `invalid` into a classified `refused{problem}` resume arm and STOP with a refusal
  rendered at the Pi edge — never a fallback.
- **Writer success = fully recorded**: an `applied`/`unchanged` write result (carrying the
  session-owned `SessionArtifactReceipt` — validated/re-derived `{runId, path, digest}`, never
  the persisted pointer) means file written + read back + pointer strict-appended.
  Pointer-append failure classifies `unverified` and deliberately leaves an orphan file
  (gitignored scratch; GC prunes). Consumers must treat a non-`applied`/`unchanged` result as
  "not consumable", even if the file visibly exists.
- **Two digests, two roles.** The pointer digest validates *file integrity* (rewind/tamper,
  enforced inside the `WorkflowSession` read seam, `readArtifact`). A consumer wanting *cache
  invalidation* must add its own
  content-key field (historically: the since-removed checkpoint generator's `plan_body_digest`
  over the current `plan.md`) and
  check it **after** the seam validates. Reuse the `sha256:` convention for both so there is one
  digest vocabulary, but never conflate the roles.
- **Recompute, don't store, derived flags.** Generated-ness of checkpoint steps was *derived*
  (non-inert AND `extractSteps(planBody)` empty) rather than stored — no entry-schema fork, zero
  downstream migration for rebuild/advance/render (the example is the since-removed checkpoint
  generator; the rule stands). Storing an always-derivable flag forks the
  schema for nothing. Bonus: an empty `extractSteps` result deliberately covered both "missing" and
  "malformed" `## Steps` with one trigger — no new parser state.
- **Chained digest authority for multi-file trusted state** (#1992): keep ONE trusted anchor in
  workflow-state and chain each additional file's digest through the already-authenticated
  artifact — the finalize step binds `manifest_digest` (the sha256 of the manifest bytes the
  wave decoded) into the bundle; recovery verifies marker→bundle, then bundle→manifest. Echoed
  identity FIELDS (paths/counts/bytes) are not authentication.
- **Verified invalidation** (#1992): when a marker-clear is the mechanism that makes later
  partial failures safe, the clear returns the verified append+read-back result, and an
  unverified clear refuses BEFORE any filesystem work — otherwise the safety story is prose.

## The atomic-write seam + corruption posture of `.perk/workflow/`

The contracts "Atomic workflow writes + corruption posture" clause is normative — point at it;
these are the cross-cutting traps:

- Every `.perk/workflow/` write on both planes routes through the per-plane atomic seam —
  `src/perk/state/cache.py` (`atomic_write_text`) / `extension/substrate/cache.ts`
  (`atomicWriteFileSync`); cross-plane write guards enforce it (see
  `workflow/source-scan-guards.md`).
- **Corruption has a decode stage before the parse stage.** A torn write can end
  mid-multibyte-UTF-8-sequence, so `Path.read_text()` raises `UnicodeDecodeError` before
  `json.loads` ever runs — a "translate malformed JSON" posture catching only
  `json.JSONDecodeError` still leaks tracebacks. Catch both (both are `ValueError` subclasses,
  so fail-soft `except (OSError, ValueError)` readers stay intact).
- **Content/residue assertions cannot prove atomic replacement.** Byte-content,
  shorter-over-longer, and no-tmp-residue tests all pass for a plain in-place write too. The
  deterministic black-box discriminator: hold the file **open** across the write — atomic replace
  swaps the directory entry (the held-open handle keeps the intact old bytes; a fresh read sees
  the new), while an in-place write mutates the held-open file and fails the test. Embodied in
  `extension/substrate/cache.test.ts`.
- **Atomicity is not mutual exclusion** — whole-file last-writer-wins between concurrent writers
  is the accepted, documented residual (no locking/versioning).

## Adding a session-data consumer (the full recipe)

The full producer→consumer recipe, composed from the rules proven above and in contracts §8.1
(`plan_draft` → `resolvePlanSource` is the end-to-end precedent):

1. **Producer**: a fixed artifact-name constant (the `PLAN_DRAFT_ARTIFACT` precedent,
   `extension/authoring/plan/draft.ts`); write only via the session seam's `writeArtifact`
   (the one engine in `extension/session/workflowSession.ts` — file + provenance pointer in one
   gesture; results carry the session-owned receipt, never the persisted pointer); pointer
   appends carry the **whole merged map** (per-field LWW — see "Provenance pointers" above); a
   `rejected`/`unverified` result ⇒ not consumable, even if the file visibly exists.
2. **Read-only writer** (only if the producer must run under the gate) — the carve-out recipe
   below.
3. **Consumer**: read only via the `WorkflowSession` seam's `readArtifact` (digest-validated,
   classified `found`/`absent`/`invalid`); design the
   fallback chain up front and pick the tier law deliberately — save-style (`absent` → … → a
   universal fallback, e.g. the transcript scrape) vs review-style (validated sources only,
   never the scrape — see `plan-review-flow.md`; the gist/objective draft consumers STOP on a
   `refused` resume with a rendered refusal instead of falling back); never dereference
   `pointer.path` (re-derive from `run_id` + `name` through the seam).
4. **Refusal tiers**: run_id mismatch → silently `absent` (fork isolation, not an anomaly);
   broken-promise (missing file / digest mismatch) → the `invalid{problem}` arm (+ the seam's
   stderr warn); draft-less fallbacks key off `absent` only.
5. **GC**: artifacts are prunable (`src/perk/state/gc.py`); pruned runs leave dangling pointers **by
   design** — a later same-run read classifies `invalid` (pointer-but-no-file); every other run
   reads `absent` (run_id mismatch). Consumers must tolerate both forever — a prune is never an
   anomaly to repair.
6. **Guards + registry**: manual `scratch`/`runs` path construction trips
   `extension/cacheGuard.test.ts` / `tests/test_cache_guard.py` — go through the seam; if a stage
   owns the artifact, declare `cache.session-data` in its registry `writes` (vocabulary keys land
   with their first declaring stage — see `shared-contracts.md`).

### The read-only carve-out recipe (a proven 2-instance template)

For any future writer that must work in read-only mode (step 2 above). `objective_draft` confirmed
the `plan_draft` checklist generalizes — a third stage-scoped draft tool should copy
`extension/authoring/objective/draft.ts` mechanically:

1. A **fixed artifact-name constant** — no path/name tool parameter.
2. The path derived **exclusively through the session-data accessor seam**
   (the session seam's `writeArtifact` = file + provenance pointer in one gesture).
3. Allowlist only the tool *name* in `extension/substrate/toolGating.ts::READ_ONLY_TOOLS`, with a carve-out
   comment — the gate's edit/write/bash blocking stays untouched.
4. Register in the installer **before the gate snapshots tools**.
5. The `invalid_input`/`no_run_id`/`write_failed` failure taxonomy via `failFor`.
6. A contracts §8.1 paragraph + registry `cache.session-data` in the owning stage's `writes` +
   both planes' registry tests.

**JSON-artifact variant**: when the draft carries structured data, serialize one explicit-literal
payload, compute the digest over the **serialized JSON** (not the prose), and let the structured
part ride verbatim (`unknown[]`) — deep validation stays with the owning plane at save time (see
`objective-lifecycle.md` for the store-as-JSON / render-at-the-door split).

Harness proof pattern: plant a session with `mode: "read-only"`, then `invokeTool` succeeds while
`workflowState().mode` confirms the gate is up. `READ_ONLY_CONTEXT` is exported and interpolates
`READ_ONLY_TOOLS.join(", ")` — allowlist changes track automatically; tests pin one representative
name.

## GC: the destructive-op triad

`src/perk/state/gc.py` + `perk state prune` + the `cache-gc` doctor check established the shape to reuse for
any future reclaim/cleanup feature:

- **Pure-read policy module** (`src/perk/state/gc.py::plan_prune`, injectable `now`).
- **Report-only doctor check** (`cache-gc`: warn + remediation, no `--fix` arm — doctor fixes stay
  documented-non-destructive; pure FS + bundled registry, so deterministic in unit tests).
- **A single destructive command** (`perk state prune`, alias `gc`) — the ONLY deletion site.

Key policies:

- **Registry-derived terminal set**: `terminal_stage_ids()` (`src/perk/state/gc.py`) computes the
  successor-less stages from the bundled registry (currently `{gist-save, learn, audit}`),
  degrading to `frozenset()` with a stderr warn on `RegistryError` — never hardcode stage names
  into GC-like policies; a graph change must flow through automatically.
- **Conservative eligibility ladder**: current-run protection (`PERK_RUN_ID` base-ULID match covers
  fork children) → terminal-stage rule (requires a *consumed* handoff; unreadable handoff ⇒ never
  terminal-pruned, age rule only) → age rule (ULID self-date, `st_mtime` fallback for non-ULID
  names). **Never delete on a guess** — mirrors `worktree wipe`'s skip-on-uncertainty posture.
- **Pruned runs leave dangling provenance pointers by design**: no pointer cleanup exists by
  contract — the raw accessors (Python `perk/state/cache.py`, TS `readSessionData`) degrade a
  missing file to `None`/`null`, and the TS `WorkflowSession.readArtifact` seam classifies the
  dangling pointer `invalid{problem}` (consumers tolerate both forever) — check contracts §8.1
  before "fixing" this.
- `DEFAULT_MAX_AGE_DAYS` is a module constant pinned in §8.1; a `[gc]` config table was
  deliberately deferred as premature.
- The result-envelope helpers (`fail`/`emit`/`EXIT_FOR_TYPE`) live once in `src/perk/cli/emit.py`, a
  neutral `src/perk/cli/`-level leaf — groups never import another group's `shared.py` (see
  `cli-command-groups.md`).

## Test recipes

- A **live shared branch array** backing both the `EntrySink` fake and the ctx's `getBranch()`
  makes the append→rebuild→verify loop testable with zero mocking; **rewind** is simulated by
  `branch.slice(0, n)` into a fresh ctx, **fork** by appending a `run_id: "RID.1"` entry atop the
  parent's entries.
- `captureStderr` (swap `console.error`, restore in `finally`) cleanly asserts the warn-tier vs
  silent-tier distinction.
- `ULID.from_datetime(...)` (python-ulid) mints backdated run_ids for age-rule tests; `os.utime`
  covers the mtime-fallback branch.
- **CliRunner + macOS symlinks**: `git rev-parse --show-toplevel` resolves `/var/folders/…` to
  `/private/var/folders/…`, so JSON payloads carrying repo-rooted paths won't equal paths built
  from `runner.isolated_filesystem()`'s raw dir — `.resolve()` the tmp dir before constructing
  expected payload paths (same family as the worktree `.resolve()`-both-sides rule).
- **The ordering-pin recipe through the real session-data seam** (#1922): empirically measure
  how many branch reads one validated artifact read makes (a self-adapting probe, never a
  hardcoded count), swap pointer + bytes TOGETHER at that boundary so both versions
  digest-validate, invoke the executor directly so unrelated reads don't shift the boundary,
  and mutation-proof by temporarily reversing the implementation.
- **Persisted-format decode policy** (#1992): enforce key closure only at the levels the new
  decoder authors (wrapper/entry — an unknown key refuses); reused row decoders stay the single
  authority (whitelisted construction ignores extras); pin both halves. Shared persisted-format
  fixtures are deliberately two-tier: one minimal shared encoding for consumers, richer fixtures
  only in the suite about the format's failure surface.

## Sources

- Issues #350, #358, #363, #372, #367 (PRs #348, #355, #362, #371, #366)

## Cross-references

- `docs/learned/pi/extension-seams.md` — the strict-append seam + object-valued `equals`
- `docs/learned/pi/extension-api.md` — the `PERK_RUN_ID` harness leak
- `docs/learned/workflow/worktree-lifecycle.md` — the `.resolve()`-both-sides rule's origin
- `docs/learned/workflow/plan-save-surfaces.md` — the save surface that consumes the plan-draft
  artifact
- `docs/learned/workflow/source-scan-guards.md` — the path guards confining the data-dir literals
