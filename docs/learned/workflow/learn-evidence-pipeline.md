---
title: The `/learn` evidence pipeline — cross-run session pointers, JSONL export, normalization, the bundle manifest, and the multi-angle orchestrator
read_when: You are touching any stage of the `/learn` evidence pipeline (objective #896) — the run-cache `session-pointers.json` carrier + `resolve_plan_sessions`, the `perk/learn/export.py` JSONL byte-copy seam, `perk learn evidence` (the bundle manifest + `--render` normalization), or the warm `/learn` multi-angle orchestrator — or you need the Pi session-file persistence / JSONL-grammar facts those consumers depend on, the rich existing-docs scan (`scan_docs_richly` — the deterministic-FACTS vs LLM-JUDGMENT split, the live-corpus heuristic-validation discipline, the never-raises path-guard family), or splitting a deterministic detector from an LLM decider.
---

# The `/learn` evidence pipeline

`/learn` reconstructs what *actually happened* across a plan's planning + implementation sessions and
hands a curated evidence bundle to a fan-out of analyst children. The pipeline is five separately-landed
nodes of objective #896; this doc captures the architecture decisions and the load-bearing Pi
session-internals facts the consumers depend on.

## The pipeline spine

Five stages, each a separate node, each owning one module:

1. **Cross-run pointer carrier + resolver** (node 2.1) — `perk/state/session_pointers.py` (the
   `session-pointers.json` store) + `perk/learn/sessions.py` (`resolve_plan_sessions`).
2. **JSONL byte-copy export seam** (node 2.2) — `perk/learn/export.py`.
3. **Bundle-manifest CLI** (node 3.1) — `perk/cli/commands/learn/evidence_cmd.py` over the gatherer
   `perk/learn/evidence.py`.
4. **`--render` session-normalization pass** (node 3.2) — `perk/learn/normalize.py`.
5. **Warm `/learn` multi-angle orchestrator** (node 4.2) — consumes the bundle; spine seeded by
   `prompts/stages/learn-orchestrate.md`.

Each stage degrades gracefully so a missing or corrupt upstream artifact never crashes `/learn`.

## Cross-run linkage: header-linkage + self-keyed pointers (the chosen architecture)

Planning and implementation are genuinely separate OS processes: planning runs in the main checkout
with `worktree: none` (minting `run_id_P`); implementation runs in a linked worktree (minting
`run_id_I`). They must correlate so `/learn` can find both sessions.

The chosen design makes the **plan-header the canonical cross-run linkage** (planning via the existing
`run_id` field; implementation via a new submit-staged `impl_run_ids` field) and the **run cache the
pointer store**, with **each run writing only its own record keyed by its own run_id**. The rejected
alternative was a single record keyed by `run_id_P`, which forced a cross-run write and ferrying
`run_id_P` into the implement session.

**Generalizable rule:** when two processes must correlate, prefer a durable issue-side linkage + a
per-process self-keyed record over cross-process writes.

`impl_run_ids` is submit-staged exactly like `branch`/`pr` (empty at save, union-merged at `/submit`),
so a new staged field is just a `PLAN_HEADER_FIELDS` frozenset entry plus a
`PlanHeader`/`PlanHeaderOut`/`from_domain` triple — no per-backend logic. The new `PlanHeaderOut` field
must be declared **last** (stored-YAML byte order is load-bearing for re-save). See
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
- worker `driveStage` → `implementation/worker`,
- the `/submit` warm door (`submitPr`) → `implementation/main` at `impl_run_ids`-stamping time
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
evidence), and the **submit-door capture** in `submitPr` (closing the `missing` half: a submitted
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

## The Pi session JSONL grammar

(Verified against real logs + the installed type decl. Presented as the data-shape exception to the One
Code Rule — a field-shape list, no code.)

- Line 1 is the `{type:"session", …}` header (excluded from the entry index).
- `message` entries nest the payload under `message.{role,content,toolName,isError}`, with
  `role ∈ user/assistant/toolResult`; a `toolResult`'s body lives in `message.content[].text`.
- A `toolCall`'s `arguments` is a **dict**.
- `bashExecution` is a **top-level** entry kind (command/output/exitCode at the entry root).
- `compaction` carries `details.{readFiles,modifiedFiles}` + `tokensBefore`.

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

TS doors **cannot call the `subagent` tool**, so any spawn/reconcile is necessarily prompt-driven (same
as `/pr-review`). The reusable split:

- The **door owns the deterministic spine** — gather-once via `runColdDoor`, then branch
  (short-circuit / graceful-degrade / orchestrate).
- The **injected prompt seed owns the judgment** — spawn 2–4 fresh-context children, reconcile,
  capture.

The `[subagents]`-key model is injected as a **per-call inline `model` override** on every spawn
because `subagents.agentOverrides` does not reach project agents (see `pi/subagents.md`).

`decodeEvidence` is **lenient-never-null** (returns defaults, never `null`), so `runColdDoor`'s
`bad_output` arm is **deliberately unreachable**. The decode-policy criterion: be lenient when a success
envelope is the authoritative signal and the fields are render/branch-only; strict decode is reserved
for fields appended to workflow-state (see `cold-door-client.md`).

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
  stale source pointers (phantom `path::symbol` spans), broken doc→doc `.md` links, and exact
  normalized title/`read_when` collisions. The de-dup **DECISION** stays with the LLM analyst and is
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
  `cold-door-launch.md`'s stale-pointer cleanup.)

- **"Never raises" must catch `UnicodeDecodeError` and guard text-derived path ops.** A file scanner
  guarded only by `except OSError` is **incomplete**: `read_text(encoding="utf-8")` on a
  non-UTF-8/binary file raises `UnicodeDecodeError` (a `ValueError` subclass, **not** `OSError`),
  and `.is_file()`/`.resolve()` on a path **derived from untrusted document text** can raise
  `ValueError` (embedded NUL) or `OSError` (OS-illegal chars). The airtight pattern (as built):
  catch `(OSError, UnicodeDecodeError)` on **every** read, route text-derived existence checks
  through a guarded helper (`_is_existing_file` catching `(OSError, ValueError)`), and wrap the
  per-link `resolve()` in its own try/except → degrade to skip. Absence/badness always degrades to
  "skip this finding", never a crash out of the advisory scan.

- **An unquoted colon-space in a learned doc's frontmatter silently zeroes its routing.** A learned
  doc's `title`/`read_when` are parsed by never-raise `yaml.safe_load` (`_frontmatter_dict` in
  `src/perk/learn/docs_scan.py`) — an unquoted `: ` (colon-space) inside the plain scalar is a YAML
  error, so the parse degrades to `{}` and the doc gets an **empty index row + empty ambient
  routing cue** rather than an error; `docs-check` reports it only as missing-frontmatter. Author
  `read_when` without inline colon-space, or quote the scalar.

## Cross-references

- `perk/learn/docs_scan.py` — `scan_docs_richly` + the `_is_existing_file` / per-read exception guards.
- `cold-door-launch.md` — the stale-pointer cleanup judgment (fix present-tense, leave narrative history).
- `plan-save-surfaces.md` — the `impl_run_ids` staged header field.
- `worktree-lifecycle.md` — the `main_worktree_root` primitive.
- `pydantic-boundary-models.md` — the parse→domain boundary + the deferred serialize edge.
- `cold-door-client.md` — the `runColdDoor` decode policy.
- `pi/subagents.md` — per-call model override, orchestrator spawn shape.
- `linear-backend.md` — dual-encoding header markers.
- `issue-backend.md` — the protocol-growth conformance census this feature triggered.
- `doc-reconciliation.md` — the sibling-style "Landed (PR #n)" node-description reconcile these nodes
  used.
