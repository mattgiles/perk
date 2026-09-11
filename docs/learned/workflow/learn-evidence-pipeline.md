---
title: The `/learn` session-evidence pipeline — cross-run session pointers, JSONL export, normalization, the bundle manifest, the multi-angle orchestrator
read_when: You are touching the `/learn` session-evidence pipeline — session pointers, JSONL export and `--render` normalization, the evidence bundle, or the multi-angle analyst orchestrator.
cluster: knowledge-stewardship
---

# The `/learn` session-evidence pipeline

`/learn` reconstructs what *actually happened* across a plan's planning + implementation sessions
and hands an evidence bundle to a fan-out of analyst children. Contracts §8.35 pins the shapes; this
doc carries the why + the traps. Siblings: `learn-docs-scan.md` (docs scanner + routing tier),
`learn-harvest-dream-core.md` (harvest/dream core).

## The pipeline spine

1. **Pointer carrier + resolver** — `perk/state/session_pointers.py` + `perk/learn/sessions.py`
   (`resolve_plan_sessions`).
2. **JSONL byte-copy export** — `perk/learn/export.py`.
3. **Bundle-manifest CLI** — `perk/cli/commands/learn/evidence_cmd.py` over
   `perk/learn/evidence.py`.
4. **`--render` normalization** — `perk/learn/normalize.py`.
5. **Warm multi-angle orchestrator** — the analyst wave is code on the report-wave module
   (`extension/learning/analystWave.ts`) driven by the `run_learn_wave` tool; the judgment seed is
   `prompts/stages/learn-orchestrate.md`.

Every stage degrades gracefully; nothing upstream can crash `/learn`.

## Cross-run linkage

The **plan header is the canonical linkage** (`run_id` + the submit-staged `impl_run_ids`) and the
**run cache the pointer store**, each run writing only its own record keyed by its own `run_id` (a
planning-keyed record was rejected: a cross-run write). Rule: correlate processes by a durable issue-side
linkage + per-process self-keyed records, never cross-process writes. Where planning runs (main
checkout, or the predecessor's worktree under stacked positioning, §8.46) is irrelevant: pointers
write under the main checkout keyed by `run_id`; learn gathers by pointer, never by worktree sweep.

A staged header field is one `PLAN_HEADER_FIELDS` entry plus a
`PlanHeader`/`PlanHeaderOut`/`from_domain` triple appended at the tail of the base fields, since
stored-YAML byte order is load-bearing for re-save (`plan-ref-lifecycle.md`'s `learn_state`
precedent; §8.35 owns the linkage).

## The shared-main-checkout carrier + the TS twin

§8.35 owns the schema. Traps: the **four always-present null slots** (`planning`/`implementation` ×
`main`/`worker`) let the read-modify-write merge never clobber a sibling; `main` vs `worker` is
fixed by capture site, never by inspecting content. The TS twin `mainCheckoutRoot`
(`extension/substrate/git.ts`) folds Python's `or cwd` fallback inline. macOS `/private`↔`/var`:
`path.resolve` is lexical, Python's `.resolve()` realpath-based; different strings, same inode;
tests realpath both sides.

## Capture sites + fork provenance

Four loud-but-non-fatal TS capture sites: `savePlan` → `planning/main`; `extension/index.ts`
`session_start` → `implementation/main` (claimer-only, first-write-wins); worker `runStage` →
`implementation/worker`; the `/submit` publish operation
(`extension/delivery/submit.ts::publishVerified`, deps from
`extension/pi/v1/delivery/submit.ts::publishDepsFor`) → `implementation/main` when stamping
`impl_run_ids`, so a submitting warm session resolves `found`. A `fork` decision carries no launched
stage: derive it from the fork decision or a forked implement session never captures. An in-memory
`SessionManager` makes planning capture a silent no-op.

**Shadowing (fixed).** Subagent children inherit `PERK_RUN_ID`, re-claimed the run, and their
`session_start` capture overwrote `implementation/main` (last child wins). Fix: the env-child adopt
arm in `decideClaim` (`extension/session/lifecycle.ts`: a consumed handoff is not claimable; the
child adopts a derived identity and never captures); the first-write-wins guard (`preserveForeign`,
`extension/substrate/sessionPointers.ts`: a foreign overwrite is skipped with a loud stderr warning,
so a new shadow vector surfaces); the submit-side capture above. Already-landed records are not
repaired.

## Match a reader's exception posture to its consumer's contract

Single cache readers translate only pydantic `ValidationError`; a resolver documented "never raises
for a missing/bad record" must catch `(OSError, JSONDecodeError, CacheError)` → warn + `None`. Match
the consumer's contract and the cross-plane twin, not a sibling reader. Corollary: a seam that
degrades *absence* to missing can still raise on a real backend error; the composing helper owns
that boundary (`resolve_plan_sessions` re-fetching the plan).

## The JSONL byte-copy export seam

The session file *is* the JSONL. Read it on disk at `/learn` time, never export at capture time:
every capture fires mid-session (an export then is a partial prefix) and would duplicate JSONL
`/learn` may never read. Disciplines: byte-copy at the export edge (`shutil.copyfile`), parse
downstream, so the raw log survives exactly; degrade-to-missing, never raise, accepting
`SessionPointer | None`; no `OutputModel` without a consumer; a dest-agnostic seam.

## Pi session-file persistence facts

Session files live under Pi's home agent dir (`~/.pi/agent/sessions/--<encoded-cwd>--/<id>.jsonl`)
and **survive worktree deletion** (only Pi-side GC → `missing`); the stored absolute `session_file`
is **authoritative — never re-derive from cwd**. The perk-dev census extractor
(`packages/perk-dev/src/perk_dev/audit/corpus.py`) also depends on: the dir encoding is lossy (the
header `cwd` is the membership authority); workflow-state `stage` exists only in cold-claimed
sessions; marker scans must exclude assistant/toolResult text (sessions quote perk's own source).
**Pi defers the first flush until an assistant message lands**: a pre-provider print-mode run (slash
commands) persists no JSONL at all; measure it from stdout/stderr or force one assistant turn.
Extractor hardening: walk parent links iteratively with cycle protection (real trees exceed the
recursion limit); a joined tool result can be `null`, and *missing* ≠ *error*.

## The Pi session JSONL grammar

Code-owned: `perk/learn/session_jsonl.py` (`SessionEntryModel` + module docstring). Two facts beyond
the model: per-assistant-message `usage` is the ground truth Pi's `showCacheMissNotices` TUI notices
summarize; the notices are not persisted, so JSONL usage is the cache-measurement instrument. And a
streaming timeline lives in top-level `custom_message` shapes
(`customType: "subagent_supervisor_request"` progress, `"subagent-notify"` completion; typed
payloads under `message.details`) that `message.role` filters miss.

## The `--render` normalization pass

- **Split at entry boundaries, never elide the middle:** open a new chunk when the next entry would
  overflow *and* the current chunk is non-empty, so every kept entry survives.
- **Pi sessions are a `parentId` tree; select the branch first** (leaf to root, cycle-safe;
  off-branch entries are pruned). Any windowing consumer must be branch-aware, since file adjacency
  is not causal adjacency after a fork (`packages/perk-dev/src/perk_dev/audit/bounding.py`'s
  `<branch_point/>` marks a lineage jump).
- **Lone-surrogate write hazard:** an escaped `\ud800` survives `json.loads` and raises
  `UnicodeEncodeError` (ValueError family, not `OSError`) at the UTF-8 write, past any
  `except OSError` boundary. `sanitize_surrogates` (`perk/learn/normalize.py`) runs at every learn
  write site; `atomic_write_text` (`perk/substrate/fs.py`, re-exported by `perk/state/cache.py`)
  documents the seam side.
- **Boilerplate is classified by entry TYPE:** PRESERVED = `compaction`/`branch_summary`; EVIDENCE =
  `message`/`bashExecution`; BOILERPLATE = metadata kinds plus any unknown type (what keeps the
  lenient parse safe). Dedup is a separate step.
- **`↑ duplicate of entry <id>` is a dedup projection, not chronology:** read the raw entry before
  alleging missing execution; never rerun CI to compensate.
- `LenientParseModel` → `to_domain()` → frozen dataclass, never raises; `render` is declared last,
  always serialized, `null` unless `--render`, so the base envelope stays byte-stable.

## The bundle-manifest CLI

A `--json` key-set test is necessary, not sufficient: the human-render default and every "degrades
to X + warning" branch need their own tests. `manifest.json` is written unconditionally on a
materialized bundle because analyst children read a file, not the door's stdout; never on a skip.

## The multi-angle orchestrator

The **door owns the deterministic spine** (gather once via `runColdDoor`, then short-circuit /
degrade / orchestrate); the **wave is code** (`run_learn_wave` on the report-wave module:
engine-validated reports; a failed analyst = a reported skipped angle; `parseAngleSelections` in
`extension/learning/analystWave.ts` enforcing 2–4 angles with `session-deviations` mandatory); the
**seed owns judgment**, and a wave-level failure routes the parent to single-context analysis, never
to model-authored scripts. The `[models.subagents]` model is the wave's workflow-level `model`
default (spawn-time, config-owned). `decodeEvidence` (`extension/pi/v1/learning/learn.ts`) is
lenient-never-null, so `runColdDoor`'s `bad_output` arm is unreachable.

**Fallback tables must be total and artifact-aware:** route every failure boundary (pre-spawn
refusals, wave failure, zero valid reports) through one explicit incomplete outcome, and enumerate
reporting destinations against the artifacts that exist at that point.

**Under-tested residuals** (the first post-land run discharged the RPC-seam, schema and duration
axes): real timeout behaviour; the wave-failure single-context fallback; the no-retry bar; the trust
posture (`bundle_dir` model-relayed with only a manifest-existence check, `emphasis` appended
verbatim into lane tasks).

## Privacy gates for session-derived packets

Redaction is iterative: a new leak class expands the adversarial canaries, regenerates every packet
from the frozen seed, reruns the gates and validates independently; a failed post-repair
confirmation is recorded as an explicit coverage limitation, never a clean gate.

## Byte-identical learn-header via one shared renderer

One shared renderer for both backends: a declaration-ordered dict, `decision`/`target` appended only
when present, emitted by `render_metadata_block` (`sort_keys=False`) and round-tripped via
`find_metadata_block`. Grow the renderer, never the call sites. The captured set is the
reconciliation DECISION set minus `SKIP`.

## A just-shipped tool param is not live in the session that landed it

The running session's tool still carries the pre-PR schema, so the new param is rejected as an
additional property; it is callable only after the extension is rebuilt/reloaded.

## Cross-references

- `learn-docs-scan.md`, `learn-harvest-dream-core.md` — the siblings.
- `plan-ref-lifecycle.md` — land-staged header-field growth.
- `worktree-lifecycle.md` — `main_worktree_root`.
- `pydantic-boundary-models.md` — the deferred serialize edge.
- `cold-door-client.md` — `runColdDoor` decode policy.
- `pi/subagents.md` — the workflow-level model default.
- `linear-backend.md` — dual-encoding header markers.
- `issue-backend.md` — the protocol-growth conformance census.
- `doc-reconciliation.md` — curation-batch craft.
- `session-audit-expectations.md` — the perk-dev consumer side.
