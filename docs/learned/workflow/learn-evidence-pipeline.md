---
title: The `/learn` evidence pipeline — cross-run session pointers, JSONL export, normalization, the bundle manifest, and the multi-angle orchestrator (+ the harvest gather/partition core)
read_when: You are touching the `/learn` evidence pipeline — session pointers, JSONL export, the bundle, the orchestrator — or the harvest gather/partition core (harvest.py, lane caps, containment, ordering).
cluster: knowledge-stewardship
---

# The `/learn` evidence pipeline

`/learn` reconstructs what *actually happened* across a plan's planning + implementation sessions and
hands a curated evidence bundle to a fan-out of analyst children. The pipeline is five separately-landed
nodes of objective #896; this doc captures the architecture decisions and the load-bearing Pi
session-internals facts the consumers depend on.

## Distillation

- Five stages, one module each: pointer carrier/resolver → JSONL byte-copy export →
  bundle-manifest CLI → `--render` normalization → the warm multi-angle orchestrator; each
  degrades gracefully — "The pipeline spine".
- Cross-run identity rides the plan header (`run_id` + `impl_run_ids`); session POINTERS ride the
  self-keyed run-cache record (each run writes only under its own `run_id`) — "Cross-run
  linkage: header-linkage + self-keyed pointers".
- Session files live under Pi's home agent dir (they survive worktree deletion); the stored
  absolute `session_file` is authoritative — never re-derive from cwd; pi defers the first flush
  until an assistant message lands, so a pre-provider print-mode run persists NO session JSONL —
  "Pi session-file persistence facts".
- The JSONL read edge is a lenient per-entry grammar (skip-don't-fail) — "The Pi session JSONL
  grammar"; match a reader's exception posture to its consumer's contract (its own section).
- `--render` is a deterministic pipeline — branch selection, boilerplate-drop, dedup, prune,
  truncation, split-by-budget at entry boundaries — "Session normalization / render".
- The docs-harvest consumers build on the pure gather/partition core (lane-count decides
  routing, never total docs; readability precedes membership; refuse-vs-filter lives in the
  caller) — "The harvest gather/partition core".
- Snapshot cleanliness proofs need status-clean + no index flags + two-sided set equality; strict
  twins serve fail-closed boundaries — "The dream door's cleanliness census".
- Session-derived packets pass iterative privacy gates (adversarial canaries; an unconfirmed
  repair is an explicit coverage limitation) — "Privacy gates for session-derived packets".

## The pipeline spine

Five stages, each a separate node, each owning one module:

1. **Cross-run pointer carrier + resolver** (node 2.1) — `perk/state/session_pointers.py` (the
   `session-pointers.json` store) + `perk/learn/sessions.py` (`resolve_plan_sessions`).
2. **JSONL byte-copy export seam** (node 2.2) — `perk/learn/export.py`.
3. **Bundle-manifest CLI** (node 3.1) — `perk/cli/commands/learn/evidence_cmd.py` over the gatherer
   `perk/learn/evidence.py`.
4. **`--render` session-normalization pass** (node 3.2) — `perk/learn/normalize.py`.
5. **Warm `/learn` multi-angle orchestrator** (node 4.2) — consumes the bundle; the analyst wave
   is code on the report-wave module (`extension/learning/analystWave.ts` — the feature op,
   installed by `extension/pi/v1/learning/learn.ts` — over
   `extension/waves/reportWave.ts`) driven by the flow-scoped `run_learn_wave` tool; the
   judgment seed is `prompts/stages/learn-orchestrate.md`.

Each stage degrades gracefully so a missing or corrupt upstream artifact never crashes `/learn`.

## Cross-run linkage: header-linkage + self-keyed pointers (the chosen architecture)

Planning and implementation are genuinely separate OS processes: planning runs in the main checkout
with `worktree: none` (minting `run_id_P`); implementation runs in a linked worktree (minting
`run_id_I`). They must correlate so `/learn` can find both sessions.

> **Update (stacked objective-plan positioning shipped).** "Planning runs in the main checkout"
> is no longer universal: a stacked child-layer planning session is positioned in the
> predecessor's plan worktree (contracts §8.46). Learn's gathering is unaffected —
> `session-pointers.json` writes under the **main checkout** keyed by `run_id`
> (`captureSessionPointer` resolves the main root), and learn gathers by pointer, never by a
> worktree sweep; planning-session residue in the predecessor worktree is inert gitignored
> scratch owned by `state gc`/`worktree wipe`.

The chosen design makes the **plan-header the canonical cross-run linkage** (planning via the existing
`run_id` field; implementation via a new submit-staged `impl_run_ids` field) and the **run cache the
pointer store**, with **each run writing only its own record keyed by its own run_id**. The rejected
alternative was a single record keyed by `run_id_P`, which forced a cross-run write and ferrying
`run_id_P` into the implement session.

**Generalizable rule:** when two processes must correlate, prefer a durable issue-side linkage + a
per-process self-keyed record over cross-process writes.

`impl_run_ids` is submit-staged exactly like `branch`/`pr` (empty at save, union-merged at `/submit`),
so a new staged field is just a `PLAN_HEADER_FIELDS` frozenset entry plus a
`PlanHeader`/`PlanHeaderOut`/`from_domain` triple — no per-backend logic. A new `PlanHeaderOut`
field is appended at the **tail of the declaration order** — stored-YAML byte order is load-bearing
for re-save: `impl_run_ids` is declared last *among the base fields*, and the stacked-delivery
fields (contracts §8.42) follow as the final block, each stripped when `None` so pre-growth headers
stay byte-identical (`plan.py`'s own field comments state the invariant). See
`plan-save-surfaces.md`.

## The shared-main-checkout carrier + the TS twin

The `session-pointers.json` carrier lives under `main_worktree_root(cwd) or cwd` so a linked-worktree
implement run and a later resolver agree on one location. The TS twin `mainCheckoutRoot(cwd)`
(`extension/substrate/git.ts`, node-builtins only) folds the `or cwd` fallback inline.

macOS `/private`↔`/var` symlink nuance: `path.resolve` is lexical, so the TS path string can differ
from Python's realpath-based `.resolve()` — but both hit the same inode through the symlink
(functionally fine; tests realpath both sides).

The carrier uses a **four-slot always-present null shape** — `planning.{main,worker}` +
`implementation.{main,worker}`, each `Pointer | null`. The always-present nulls let the
read-modify-write merge never clobber a sibling write. `main` vs `worker` is distinguished by
**deterministic capture site**, never by inspecting content. See `worktree-lifecycle.md` for the
`main_worktree_root` primitive.

## Capture sites + fork provenance

Four best-effort, **loud-but-non-fatal** (never throw) TS capture sites:

- `savePlan` → `planning/main`,
- `index.ts` `session_start` → `implementation/main` (claimer-only, first-write-wins),
- worker `runStage` → `implementation/worker`,
- the `/submit` warm door (the publish operation, `extension/delivery/submit.ts::publishVerified`
  over `publishDepsFor`) → `implementation/main` at `impl_run_ids`-stamping time
  (first-write-wins) — any run id entering the linkage gets its pointer captured in the same
  gesture, so an address/warm session that submits resolves `found` instead of `missing`.

**Fork-stage inheritance:** a `fork` decision carries no launched stage, so the implement-capture gate
derives the effective stage from the fork decision and threads the parent session id — without this a
forked implement session never captures.

Planning capture is a silent no-op under an in-memory `SessionManager` (`getSessionFile()` returns
null), which is why existing in-memory `planSave` tests were unaffected.

**Session-pointer shadowing (corroborated recurring defect — fixed).** Subagent children are
spawned as separate `pi` processes inheriting the parent's env, so they arrived carrying the
parent's `PERK_RUN_ID`; with no branch state they re-claimed the run and their `session_start`
capture overwrote `implementation/main` (last child wins). Four independent `/learn` bundles
showed the implementation-session capture holding the wrong transcript: a subagent
acceptance-contract child (13 entries) instead of the implement session (run
`01KWX7KD3NFMVY6Z51Z7BPJ822/main`); a post-implementation test-review subagent transcript; a
4-entry export capturing only the review-fetch step; an address-stage classification portion with
worker-session sources missing. Practical consequence: deviation-angle learn analysts ran on
planning sessions + PR diffs instead of the implement transcript. Fixed by three coordinated
mechanisms: the **env-child adopt arm** in `decideClaim` (a handoff already consumed by a
different session is not claimable — the child adopts a derived `<run_id>.<n>` identity, inherits
`mode`, never consumes/captures/impersonates the stage), the **first-write-wins guard**
(`preserveForeign` on the interior + submit-door captures — a foreign overwrite is skipped with a
loud stderr warning, so any future shadow vector surfaces instead of silently corrupting
evidence), and the **submit-side capture** in the publish operation (closing the `missing` half: a submitted
run's pointer is captured where its `impl_run_ids` linkage is created). Records written by
already-landed runs are not repaired — `/learn` on old plans may still see shadowed pointers.

## Match a reader's exception posture to its consumer's contract

(The review-caught fail-soft gap.) Single cache readers only translate pydantic `ValidationError` and
let `OSError`/`JSONDecodeError` propagate; only the batch reader catches them. A resolver that documents
"never raises for a missing/bad record" (and whose lenient TS twin returns `null` on corrupt JSON) must
wrap its read in `try/except (OSError, JSONDecodeError, CacheError) → warn + None`.

**Durable rule:** match a reader's exception posture to its consumer's contract (and its cross-plane
twin), not to a sibling reader's shape.

A second instance of the same lesson: a seam that "degrades absence to missing" can still **raise** on
a genuine backend error. When composing it under a per-source-degrade contract, the composing helper
owns the exception boundary; never assume the callee swallows backend errors (the
`resolve_plan_sessions` re-fetch-the-plan case).

## The JSONL byte-copy export seam — Option A beat Option B

The session file *is* the JSONL: Pi's `SessionManager` persists each session as an append-only JSONL
log; `getSessionFile()` returns its absolute path.

- **Option A** = read the on-disk file on demand at `/learn` time.
- **Option B** = TS capture-time export.

**Option A wins** because all three capture sites are mid-session (the log keeps appending after every
capture, so a capture-time export is a partial prefix), and `/learn` runs later in a separate session
by when planning + implementation have finished writing. Option B also duplicates large JSONL on every
capture even when `/learn` never runs.

Disciplines that generalize:

- **Byte-copy at the export edge** (`shutil.copyfile`), **parse downstream** — preserves the raw log
  exactly (version header, compaction/branch-summary entries, abandoned branches, unknown custom
  entries).
- **Degrade-to-missing-never-raises**, accepting `SessionPointer | None` so the export composes with
  resolution.
- **No `OutputModel` because no consumer yet** — the serialize edge is deferred to the consuming node
  (reaffirms the boundary-direction rule: don't author a serialize-edge model with no reader; see
  `pydantic-boundary-models.md`).
- **Dest-agnostic seam** — the caller composes the full target path.

## Pi session-file persistence facts (load-bearing for the consumers)

Files live under the **home agent dir** (`~/.pi/agent/sessions/--<encoded-cwd>--/<id>.jsonl`), **not**
the worktree, so they **survive worktree deletion** (only Pi-side GC removes one → `missing`). The
session-dir path is **cwd-encoded**, so the stored absolute `session_file` is **authoritative — never
re-derive the path from cwd** (the capture cwd may be a deleted worktree).

Three further facts are encoded in the session-census extractor
(`packages/perk-dev/src/perk_dev/audit/corpus.py` — pointers only; the mechanics live there):

- The session-dir encoding is **lossy**, so dir names are a prefilter only — the header `cwd`
  inside each file is the membership authority.
- Workflow-state `stage` exists only in **cold-claimed** sessions; warm mints carry a `run_id`
  but no stage — the basis of the extractor's stage/warm identity split.
- Marker scanning must **exclude assistant/toolResult text**: sessions in this repo routinely
  quote perk's own source, so content-level markers false-positive outside user/header entries.

**Pi defers the first session flush until an assistant message lands** (the session-manager's
has-assistant persist gate). A print-mode run that completes before any provider call — e.g. slash
commands, which execute pre-provider — persists **no session JSONL at all**; `--no-session` is
irrelevant to this arm (there was never a write to suppress). Consequence for evidence/measurement
protocols: a headless command-only run leaves no JSONL — capture from stdout/stderr instead, or
force one assistant turn if a session file is required.

## The Pi session JSONL grammar

(Verified against real logs + the installed type decl. Presented as the data-shape exception to the One
Code Rule — a field-shape list, no code.)

- Line 1 is the `{type:"session", …}` header (excluded from the entry index).
- `message` entries nest the payload under `message.{role,content,toolName,isError}`, with
  `role ∈ user/assistant/toolResult`; a `toolResult`'s body lives in `message.content[].text`.
- A `toolCall`'s `arguments` is a **dict**.
- `bashExecution` is a **top-level** entry kind (command/output/exitCode at the entry root).
- `compaction` carries `details.{readFiles,modifiedFiles}` + `tokensBefore`.
- Per-assistant-message `usage` (`input`/`cacheRead`/`cacheWrite`) is the **ground truth** that
  pi's `showCacheMissNotices` TUI notices summarize; the notices themselves are TUI-only and NOT
  persisted to session JSONL, so human verbatim capture of them is lossy. Consequence for any
  cache-measurement protocol: make JSONL usage inspection the primary instrument — evidence is
  reconstructable **after the fact** from `~/.pi/agent/sessions/<encoded-cwd>/*.jsonl`; notices
  are color.
- Mining a **streaming timeline** needs the non-message entry shapes: supervisor progress
  updates are `type: "custom_message"` entries with `customType: "subagent_supervisor_request"`
  (top-level fields, **not** under `message.role`); completion is a separate
  `customType: "subagent-notify"` shape; tool results carry their typed payload under
  `message.details`. Ordinary `message`/`role` filters miss injected-batch timestamps entirely.
  The millisecond adjacency of a wait-expiry toolResult and its injected `custom_message` is the
  delivery-mechanics proof.

## Session normalization / render (the `--render` pass)

Port **decisions** from erk's preprocessor, diverge on shape.

The one decision worth porting: **bound by splitting at entry boundaries, never elide the middle** —
accumulate token estimates and start a new chunk when the next entry would exceed the budget *and the
current chunk is non-empty*, so every kept entry survives in some chunk (the only lossy compression is
per-payload).

erk was a linear log; **Pi sessions are a `parentId` tree**, so the pipeline needed a first step the
objective prose glossed: **branch selection** — walk `parent_id` from the leaf (highest-index entry) to
the root via a by-id map (cycle-safe, terminates on missing parent), then filter to on-branch ids.
Off-branch entries drop, counted as pruned.

The tree fact is more general than leaf-to-root branch *selection*: **any consumer slicing or
windowing session entries must be branch-aware** — file order interleaves sibling branches after a
fork, so file adjacency is not causal adjacency. That consequence had to be re-derived painfully by
a later consumer (the audit evidence bounder); `packages/perk-dev/src/perk_dev/audit/bounding.py`
is the descendant-restricted windowing instance (windows computed over the parents table, with a
`<branch_point/>` marker wherever a rendered slice jumps lineage).

**The lone-surrogate write hazard.** An escaped `\ud800` in session/backend JSON survives
`json.loads` into a Python `str` and raises `UnicodeEncodeError` (ValueError family, **not**
`OSError`) at the UTF-8 file write — any code writing session/backend-derived text behind an
`except OSError` boundary has this gap. Sanitize at compose time: the shared helper is
`sanitize_surrogates` in `perk/learn/normalize.py` (the `errors="replace"` re-encode posture),
applied at the learn-pipeline write sites (the rendered chunk write plus the evidence bundle's
plan-body and diff writes); `atomic_write_text`'s docstring (`perk/state/cache.py`) carries the
seam-side statement of the exception.

**"Drop boilerplate" means classify by entry TYPE, not by content:**

- PRESERVED = `compaction` / `branch_summary`;
- EVIDENCE = `message` / `bashExecution`;
- BOILERPLATE = the metadata entry kinds **plus any unknown type**.

The unknown-type-is-boilerplate rule is what makes the parse edge safely lenient — real logs carry
entry kinds absent from the installed type union. Repeated content is handled separately by a dedup
step, not the boilerplate drop.

Boundary discipline: a clean `LenientParseModel` → `to_domain()` → frozen domain dataclass; never
raises (missing file → empty; non-JSON / type-less line → `malformed_lines += 1`); the additive
`render` field is declared **last**, always serialized, `null` unless `--render`, keeping the
no-`--render` envelope byte-stable except the new null key.

## The bundle-manifest CLI: test the human-render default AND every degrade branch

A net-new command with a non-`--json` default render: the `--json` envelope test (exact key set) is
necessary but **not** sufficient — the **human-render default path** and **every documented "degrades
to X + warning" branch** each need their own test, because they're the easy-to-skip paths a
JSON-focused suite misses.

The self-contained-bundle reason the manifest exists: `perk learn evidence` writes
`<bundle_dir>/manifest.json` (the full `--json` payload) unconditionally on a materialized non-skip
bundle, because the spawned analyst children read a **file**, not the parent door's stdout — so the
bundle must be self-contained (artifacts + chunks + manifest in one dir). No write on a skip.

## The multi-angle orchestrator (TS deterministic spine + model judgment)

The reusable split:

- The **door owns the deterministic spine** — gather-once via `runColdDoor`, then branch
  (short-circuit / graceful-degrade / orchestrate).
- The **wave mechanics are code** — the `run_learn_wave` tool (registered beside `learn`) runs
  the analyst fan-out through the report-wave module over the pi-subagents extension RPC:
  module-rendered script, async spawn, engine-validated structured reports, best-effort
  completeness (a failed analyst = an explicitly-reported skipped angle). The angle policy (2–4,
  `session-deviations` mandatory) is tool-enforced (`angleSelectionError`).
- The **injected prompt seed owns the judgment** — choose angles/emphasis, call the tool,
  reconcile, capture. A wave-level tool failure routes the parent to a single-context analysis
  of the bundle (never a silent fallback to model-authored scripts).

The `[models.subagents]`-key model is resolved by the tool at execute time and applied as the
wave's **workflow-level `model` default** (flowing onto every lane) because an `agentOverrides`
entry cannot displace the def's frontmatter-pinned `model:` (the 0.52 custom-agent override path
is frontmatter-sensitive — see `pi/subagents.md`).

`decodeEvidence` is **lenient-never-null** (returns defaults, never `null`), so `runColdDoor`'s
`bad_output` arm is **deliberately unreachable**. The decode-policy criterion: be lenient when a success
envelope is the authoritative signal and the fields are render/branch-only; strict decode is reserved
for fields appended to workflow-state (see `cold-door-client.md`).

### First live proof — passed; what stays under-tested

The wave shipped with **design/structural mitigation only** on its three watch axes (the RPC seam
vs a real engine, schema strictness vs real analyst models, the blocking-turn shape at real wave
duration) — every wave test uses the memory adapter or a fake RPC responder, and the module
timeout is overridden to 20ms in tests. Those axes were **discharged by the first post-land
`/learn` run**: `run_learn_wave` executed over the real RPC adapter, all lanes returned
engine-validated schema-valid reports (no lane failures, no malformed reports), and the
blocking-turn shape was unremarkable at real duration.

What stays under-tested:

- **Real timeout behavior** — only the 20ms structural override is exercised; no test covers what
  a 15-minute blocked tool call does to the parent session.
- **The wave-failure single-context fallback** ("analyze the bundle yourself") — tested only to
  the soft-fail return; it has never fired live.
- **The best-effort no-retry quality bar** (a failed analyst = a skipped angle, deliberately NOT
  mirroring `/pr-review`'s bounded retry) — no dogfood evidence yet, because no lane has failed
  live.
- **The consciously-accepted trust posture**: `bundle_dir` is model-relayed with only a
  manifest-existence check, and per-angle `emphasis` is appended verbatim into lane tasks. Same
  trust plane as the prior model-authored scripts — flag only if the trust plane changes.

### Fallback state tables must be total and artifact-aware

A model-orchestrated wave policy must route **every** failure boundary through one explicit
incomplete outcome — pre-spawn refusals (`bad_input`/`bad_state`), wave failures, and
zero-valid-reports alike — or the parent improvises differently at each boundary (a partial table
is an invitation to invent a new degrade per arm). And the reporting destinations depend on **what
artifacts exist at that point in the flow**: the session summary always exists; objective prose
exists only when an objective is authored; the evidence report exists only when the flow got that
far before stopping. Enumerate the arms against the artifacts, not against the happy path.

## Session-corpus extractor hardening

Two edge cases from the session-corpus audit that stopped first extraction passes:

- **Real Pi session trees can exceed Python's recursion limit** — parent-link depth/topology
  walks must be iterative with cycle protection, never recursive.
- **A tool call's joined result can be absent (`null`)**, not merely a result object carrying
  `isError` — keep *missing* separate from *error* and guard nullable joins explicitly.

## Privacy gates for session-derived packets

Redaction correctness is **iterative, not assumed**. When a new leak class is found, expand the
adversarial canaries, regenerate all affected packets from the frozen seed, rerun the exhaustive
deterministic gates, and validate the packets independently. If post-repair independent
confirmation fails, preserve that as an **explicit coverage limitation** rather than claiming a
clean privacy gate.

## Byte-identical learn-header via one shared renderer

Both backends render the learn-header through a single shared helper (declaration-ordered dict;
`decision` / `target` appended **only when present**, distinguishing "no target" from a value).
`render_metadata_block` uses `yaml.safe_dump(sort_keys=False)` so insertion order *is* the stored
order, guaranteeing the header is byte-identical across GitHub (HTML) and Linear (inline-code) and
round-trips via `find_metadata_block`.

**Reuse pattern for any future header-field growth:** grow the shared renderer, not each call site. The
captured-classification set is the reconciliation DECISION set **minus `SKIP`** (a skip creates no
issue). See `linear-backend.md` for the dual-encoding markers.

## Meta-gotcha: a just-shipped tool param is not live in the session that landed it

The `/learn` capture for the PR that adds the new `decision` param could not pass it — the running
session's `learn` tool still had the pre-PR JSON schema, so the new field was rejected as an additional
property. A tool/param added by a PR is callable only after the extension is rebuilt/reloaded; the
classification rides the header only on the next run.

## The rich existing-docs scan (`scan_docs_richly`) — facts feed judgment

`scan_docs_richly` (`perk/learn/docs_scan.py`) is the deterministic, advisory corpus scan consumed by
both `perk/learn/evidence.py` (the bundle manifest's `docs_findings`) and the docs-factory inbox
(`factory_common.py`'s `_scan_section`). It surfaces verifiable facts about the three docs roots so
the docs-plan analyst can do cleanup-first + UPDATE-vs-NEW placement. Three cross-cutting learnings:

- **Deterministic-FACTS vs LLM-JUDGMENT split.** The Python layer emits only **verifiable FACTS** —
  stale source pointers (phantom `path::symbol` spans), broken doc→doc references (Markdown links
  **plus** full-span backtick `.md`/`.mdx` path tokens, the latter tri-base-resolved — repo root /
  doc parent / the doc's scan root — with slashless name-mentions skipped), and exact normalized
  title/`read_when` collisions. The de-dup **DECISION** stays with the LLM analyst and is
  **candidate-vs-corpus** ("does THIS capture already live in an existing doc?"), powered by those
  facts plus the full docs inventory — the scan **never decides de-dup**. Within-corpus
  exact-collision detection (`_duplicate_groups`) fires **0× on a curated corpus** (every title is
  unique), so it is a cheap **GUARD, never the dedup mechanism**. Reusable rule: whenever you split
  a deterministic detector from an LLM decider, the detector emits facts + guards; the decision is
  the model's.

- **Validate detection heuristics against the LIVE corpus — learned docs intentionally carry
  historical pointers.** The rules were shaped by running them on `docs/learned` live: **~30% of
  code-pointers are `missing-file`** because learned docs cite filenames **as-they-were**
  (landing-log narrative surviving module→package splits) — **intentional history, NOT drift to
  fix**. Broken catalog links to *renamed* files are the high-value signal. A corpus-hygiene
  scanner is **high-recall by design** — weigh findings by relevance and tune precision against the
  real corpus before committing the rules. (This is the principle that governs a doc-cleanup
  judgment call: fix present-tense mechanics pointers, leave narrative history — see
  `cold-door-launch.md`'s stale-pointer cleanup.) The backtick doc-token widening repeated the
  method: at the dream-dogfood audit (`docs/design/archive/learn-dream-dogfood.md`, objective #1926, commit
  `5c3b5058`) the deterministic scan was blind to the analysts' verified stale `docs/planning/…`
  backtick refs, and a live-corpus acceptance survey of every backtick `.md`/`.mdx` token (326
  doc/token pairs) produced the two suppressions — skip slashless tokens, add the scan-root
  resolution base — that cut ~100+ structural false positives down to the genuine handful.

- **"Never raises" must catch `UnicodeDecodeError` and guard text-derived path ops.** A file scanner
  guarded only by `except OSError` is **incomplete**: `read_text(encoding="utf-8")` on a
  non-UTF-8/binary file raises `UnicodeDecodeError` (a `ValueError` subclass, **not** `OSError`),
  and `.is_file()`/`.resolve()` on a path **derived from untrusted document text** can raise
  `ValueError` (embedded NUL) or `OSError` (OS-illegal chars). The airtight pattern (as built):
  catch `(OSError, UnicodeDecodeError)` on **every** read, route text-derived existence checks
  through a guarded helper (`_is_existing_file` catching `(OSError, ValueError)`), and wrap the
  per-link `resolve()` in its own try/except → degrade to skip. Absence/badness always degrades to
  "skip this finding", never a crash out of the advisory scan.

- **The plain-scalar hazard family: two YAML traps in a learned doc's frontmatter, enforced by
  `docs-check`.** A learned doc's `title`/`read_when` are parsed by never-raise `yaml.safe_load`
  (`_frontmatter_dict` in `src/perk/learn/docs_scan.py`), and an unquoted plain scalar has two
  distinct failure members: an inline `: ` (colon-space) is a YAML error, so the **whole
  frontmatter parse fails** — `_frontmatter_dict` degrades to `{}` and the doc gets an empty
  index row + empty ambient routing cue; an inline ` #` (space-then-hash) starts a YAML comment,
  so the parse **succeeds** and the cue is **silently truncated** (looks valid, measures short).
  They manifest differently (parse failure vs truncation), neither is detectable from parsed
  values alone, and quoting the scalar escapes both. Enforcement: `perk learn docs-check` flags
  the closed hazard set (`space-hash`, `colon-space`, `multiline`) via `scan_cues` in
  `src/perk/learn/docs_sync.py` and **gates its exit** on them (exit 0 ok · 1 stale or cue
  violation · 2 not-a-repo), alongside the 200-char parsed-value ceiling (`READ_WHEN_MAX_CHARS`);
  the live-corpus pytest `tests/test_learned_docs_cues.py` enforces the same budget in CI.

- **A skipped gate must render UNCHECKED, never green.** When an invalid cluster registry makes
  the docs-check freshness comparison impossible, the report's defaults (`fresh=True`, an empty
  stale set) mean "not compared", not "fresh" — document the non-compared semantics on the report
  shape and render the gate as UNCHECKED, or a broken registry silently reads as a passing gate.
  Companion trap: **generated artifacts that embed their own explanation must vary with the
  generating mode** — a legacy-mode repo must not receive a bootstrap preamble describing a
  registry it doesn't have; when a generator grows modes, sweep its baked prose constants for
  mode-specific claims.

## The harvest gather/partition core

`src/perk/learn/harvest.py` is the pure core the docs-harvest consumers build on —
`resolve_harvest_docs` (target resolution over `docs/learned/`) + `partition_lanes`
(deterministic per-group lane chunking); the downstream handoffs (single- vs multi-lane routing
is decided by the **lane count**, never a total-doc count; the TS validator pins
`schema_version` as the byte-identical string `"1"`) are encoded in `harvest.py`'s docstrings —
point there, don't duplicate.

### Pipeline-fed test suites silently under-test downstream ordering contracts

When every test case routes the composed pipeline (resolver output → partition), the suite stays
green even if the downstream function stops sorting — the upstream already emits sorted order.
For any pure function whose contract includes ordering/determinism, include at least one
**direct-input** case where input order and the competing sort key *diverge* (the shipped test
constructs shuffled nested-path docs pushing a doc across the chunk boundary). This generalizes
beyond harvest: a fully enumerated test matrix misses it whenever all cases compose the pipeline.

### The "eligible corpus" containment pattern for path-selection APIs

Filter the enumerator's output *once* by resolved-path containment against the root before any
selection arm — the default selection becomes ≡ an explicit root-directory target *by
construction* (no per-arm symlink policy to keep in sync), and escaped symlinks are excluded
everywhere. Targets get the mirrored posture (resolve before the containment check, so an
escaping symlink is invalid). Bonus idiom: `is_relative_to` covers equality, so one predicate
serves file-equality, directory-containment, and the root-passes-containment cases.

**A containment check is only as trusted as its root.** A `docs/learned` that is itself a symlink
out of the repository would make the outside target the trusted containment root and launder
outside-tree files into the manifest (which the launched session is then told to read). Validate
the root first — `learned_root.is_relative_to(repo_root)` → `invalid_input`, guarded in
`src/perk/learn/harvest.py` with a core test — before any per-doc containment runs.

### The per-lane report cap vs the parent's global curation

The harvest-analyst lane caps its report at **≤5** ranked opportunities (+ `omitted_count`),
while the parent's curation policy (`skills/perk-learn-harvest/SKILL.md`) selects a global
top-≤8 — a lane with >5 high-rank candidates exposes only 5 + a count, which can starve
cross-lane curation. Deliberately kept (user-ratified), and re-affirmed now that multi-lane
harvests run live through `run_harvest_wave` (contracts §8.48): `HARVEST_MAX_OPPORTUNITIES`
stays 5 — starvation is made *visible* (a nonzero `omitted_count` is disclosed in coverage
reporting, with a bounded `--from` re-run scoped to that lane's exact doc paths as the deepening
move: ≤ 8 docs partitions to one lane and is analyzed directly, uncapped) rather than widened
away; widening stays a one-constant edit.

### Orthogonal error-vocabulary composition

`invalid_from` is purely per-target (containment/existence); `no_harvest_docs` is purely "the
union selected zero docs" — keeping them orthogonal removes any ambiguity about which error wins
on mixed inputs.

### Refusal ordering + refuse-vs-filter over the shared primitive

- **Refusal ordering over never-raising scanners:** the primitive failure (readability) precedes
  any derived classification (membership) — pinned as §8.59's "readability precedes
  membership". Test the failure on the richest mode path: the registry-absent path bypassed the
  buggy ordering entirely (#2001).
- **Refuse-vs-filter is a caller-side posture split over one shared primitive**
  (`eligible_learned_docs`): harvest keeps silent-filter semantics; dream derives its refusal by
  diffing against the raw enumeration — the posture lives in the caller, not as a flag on the
  primitive (#2001).

## The dream door's cleanliness census

- **`git status --porcelain` cleanliness proofs have three blind spots** — gitignored files,
  assume-unchanged/skip-worktree index flags (probe `git ls-files -v` for lowercase/`S` tags),
  and sparse checkouts (tracked files absent from disk). The census for any snapshot proof:
  status-clean + no index flags + TWO-SIDED set equality between the filesystem enumeration and
  the tracked set — each direction defends a different failure (#1990).
- **Fail-open helpers must not serve fail-closed boundaries.** When two `None` causes need
  different repair actions, grow a strict twin (`git.head_commit` raising `GitError` vs
  `resolve_commit`'s fold-to-`None`) and document the split on both (#1990).
- **Operational facts:** an open same-origin curation objective blocks `perk learn dream` with
  `origin_conflict` by design until it completes. Dated calibration point — 66 docs / 13
  clusters ⇒ 14 analyst lanes + 3 reducers, a ~15 min wave, and a 127 KB finalized bundle
  against the 384 KB budget (#2006).
- **Credential-smoke prompts must demand no punctuation** — an exact-match `READY` expectation
  fails on `READY.` (#2006).

## Cross-references

- `perk/learn/docs_scan.py` — `scan_docs_richly` + the `_is_existing_file` / per-read exception guards.
- `perk/learn/harvest.py` — `resolve_harvest_docs` + `partition_lanes` (docstrings carry the downstream handoffs).
- `cold-door-launch.md` — the stale-pointer cleanup judgment (fix present-tense, leave narrative history).
- `plan-save-surfaces.md` — the `impl_run_ids` staged header field.
- `worktree-lifecycle.md` — the `main_worktree_root` primitive.
- `pydantic-boundary-models.md` — the parse→domain boundary + the deferred serialize edge.
- `cold-door-client.md` — the `runColdDoor` decode policy.
- `pi/subagents.md` — the workflow-level model default, orchestrator spawn shape.
- `linear-backend.md` — dual-encoding header markers.
- `issue-backend.md` — the protocol-growth conformance census this feature triggered.
- `doc-reconciliation.md` — the sibling-style "Landed (PR #n)" node-description reconcile these nodes
  used.
