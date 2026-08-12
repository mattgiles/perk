# perk cross-plane contracts

The language-neutral contracts both planes obey, authored once here and bundled into each
build artifact. This document holds the numbered **prose contract sections** (`§8.1`–`§8.57`,
non-contiguous: `§8.8` is skipped and `§8.6a` exists; no parser): the Python CLI (`perk`)
and the TS extension (`@mgiles/perk`) each implement one side, against the exact names/paths/
fields pinned in each section. `perk doctor` verifies conformance. The numbering convention:
section numbers are stable anchors, never renumbered; grep the existing headings before
assigning a new one (a gap like `§8.8` stays a gap).

Three **parsed** contracts are siblings of this file: `registry.yaml` — the stage
graph, whose `state_keys` block is the canonical vocabulary referenced throughout this
document — `bindings.yaml` — the skill-binding set (trigger→skill delivery), specified
in §8.9 — and `providers.yaml` — the provider-selection supported set, specified in §8.10.
Two more siblings: `contracts-history.md` (the chronological changelog, below) and
`schemas/` (committed golden snapshots of the boundary models, §8.34).

> **History.** The chronological `Status (…)` landing-note changelog lives in the sibling
> [`contracts-history.md`](./contracts-history.md), grouped by `§N.M` anchor; this file is the
> compact current spec.

---

## §8.1 · `.perk/workflow/` layout (Q2)

The local cache tier — written and read by **both** the CLI (exterior) and the extension
(interior). Fixed layout:

```
.perk/workflow/
├── plans/                  # materialized plan cache (canonical copy stays in GitHub)
├── plan.md                 # cache.plan: the per-worktree plan snapshot for review fidelity (Python-only; transient)
├── plan-ref.json           # cache.plan-ref: the active plan->branch ref pointer (local mirror)
├── scratch/runs/<run_id>/  # per-run inter-process workflow files (diffs, generated bodies)
│   └── data/               # the session data dir (Node 1.2): run-scoped session artifacts
├── handoff/<run_id>.json   # pre-session CLI->extension cold-door state (claimed on session_start)
├── agent-session.json      # cache.agent-session: the Linear AgentSession pointer (§8.22)
└── markers/                # existence-based friction semaphores (e.g. pending-learn)
```

- Keyed by the perk-owned **`run_id`** (a ULID — see §8.2), never the Pi session id (which
  does not exist yet at cold-door launch time). The keying `run_id` may be **CLI-minted**
  (cold launch, `perk/state/run_id.py`) or **extension-minted** (a warm session with no identity,
  §8.2 — `extension/substrate/runId.ts`); handoff blobs remain cold-launch-only.
- **Handoff blob:** `{ run_id, stage, mode, consumed }` (+ `pi_session_id` once claimed). The
  CLI's cold launch (`perk <stage>`, T4) writes it; the extension claims it on `session_start`
  and sets `consumed: true` (§8.2). `stage` is the target stage id — the launched session's
  interior *handler* acts on it (Phase 1); T4's extension reads only `mode`/`run_id`.
- **Session-data accessor seam (Objective #339 Node 1.2).** The session data dir is
  `scratch/runs/<run_id>/data/` — a dedicated subdir so run-scoped session artifacts never
  overlap perk machine records (`dispatch.json`, `events.ndjson`, `ci-*.md`) living directly in
  the run dir — created lazily on first write (`session_start` stays artifact-free). All
  scratch/session-data paths flow through one accessor per plane: `perk/state/cache.py` (exterior;
  consumers hold an explicit `run_id`) and `extension/substrate/cache.ts` + `extension/substrate/sessionData.ts`
  (interior; the ctx seam resolves the current `run_id` from `perk:workflow-state` and degrades
  to `null` when the session has no identity — never a stamp `run_id`, contrast
  `coldDoor.activeRunId`). Helpers degrade gracefully: absence and I/O failure → `None`/`null`
  plus a stderr warning, never an exception. Manual construction of the `scratch`/`runs` path
  segments outside the seam is forbidden and guard-tested in both planes
  (`extension/cacheGuard.test.ts`, `tests/test_cache_guard.py`). The dedicated
  `cache.session-data` state key is now real (Node 2.1): it names the run-scoped session data
  dir artifacts and is declared in `writes` by the read-only authoring stages — `plan`,
  `objective-plan`, and `objective-author` (`cache.scratch` still names the broader substrate).

  **perk-owned dot-path construction seam.** Construction of the **perk-owned** dot-path
  families — the perk dir, the config files (`config.toml`/`local.toml`), the required-perk-version
  pin (`.perk/required-perk-version`, constructed via `paths.required_version_file`; Python-only,
  not mirrored in the TS guard, like skills), the committed managed-state file
  (`.perk/managed-state.toml`, constructed via `paths.managed_state_file`; Python-only, not
  mirrored in the TS guard — the TS plane never reads it), the repo-skills dir
  (`.perk/skills`), and the workflow dir — is confined to a per-plane seam: `perk/substrate/paths.py`
  + `extension/substrate/paths.ts` (perk dir / config / skills) plus `cache.workflow_dir` /
  `workflowDir` for the workflow family. Each family is independently redirectable from its single
  helper (Objective #878 migrates them to `.perk/` one phase at a time). The **workflow family now
  resolves to `.perk/workflow/`**. The **repo-skills family has moved**: it now resolves to
  `.perk/skills` via `repo_skills_dir`. The **config family has moved**: it now resolves to
  `.perk/config.toml` (committed) / `.perk/local.toml` (gitignored) on **both planes** —
  `config_dir`/`configDir` return `root/".perk"` and the filename constants are
  `config.toml`/`local.toml`. `.perk/config.toml` is the repo **initialization marker**: `perk init`
  **refuses** a legacy-only repo (a committed `.pi/perk.toml` with no `.perk/config.toml`) with
  `error_type="legacy_config"` (exit 2) and an actionable `perk doctor --fix` remediation — never
  warn-and-seed over legacy. `perk doctor` diagnoses the legacy config ("legacy config not migrated")
  and `perk doctor --fix` **migrates it secret-safely** (an idempotent `_MIGRATIONS` entry:
  move-when-target-absent / remove-when-byte-identical / error-on-conflict; committed and local
  migrate independently so the secret is never promoted into the committed file). The legacy
  `.pi/perk.toml` / `.pi/perk.local.toml` paths are constructed only via the allowlisted
  `paths.legacy_config_file` / `paths.legacy_local_config_file` helpers (Python; migration source
  only — never read); the TS plane reads the `.perk/` target only and has no legacy helpers. The
  confinement is guard-tested in both planes (`tests/test_paths_guard.py`,
  `extension/pathsGuard.test.ts`): a family-scoped source scan bans a quoted `".pi"` segment built
  adjacent to a legacy config follow-segment **and** a quoted `".perk"` segment adjacent to a current
  perk-owned follow-segment, outside the seams. **Pi-native** `.pi/...` paths (`.pi/settings.json`,
  `.pi/agents/`, `.pi/npm`, `.pi/APPEND_SYSTEM.md`, `~/.pi/agent`) are
  explicitly *not* perk-owned and stay hand-built at their Pi-native sites.

  **The plan-draft file tool (Node 2.1).** The tool `plan_draft` (interior-only; no Python
  twin) is the first session-data producer: it writes the working plan during read-only plan
  authoring. It is allowlisted in `READ_ONLY_TOOLS` (`extension/substrate/toolGating.ts`) as a **narrow
  structural carve-out**: the tool has no path/name parameter — the artifact name is the fixed
  constant `plan-draft.md` (`PLAN_DRAFT_ARTIFACT`, `extension/factories/planDraft.ts`) and the path is
  derived exclusively through the accessor seam (`writeSessionArtifact`: file + provenance
  pointer) — so the only bytes it can ever write are the one working-plan artifact in the
  current run's data dir (gitignored scratch); the gate's `tool_call` `edit`/`write`/bash
  blocking is unchanged. Semantics: full rewrite per call, non-terminating, NOT a save —
  `plan_save`/`/plan-save` remain the canonical GitHub persist surface. Failure taxonomy (soft
  results, never throws): mistyped params → `bad_input`; empty/whitespace plan →
  `invalid_input`; no session `run_id` → `no_run_id`; file-or-pointer write failure →
  `write_failed`. Consumers read the draft only via `readSessionArtifact` (digest-validated,
  fail-open).

  **File-first plan save (Node 2.2).** Both save surfaces resolve their plan through one shared
  resolver (`resolvePlanSource`, `extension/factories/planSave.ts`), in order: (1) the validated
  `plan-draft.md` artifact (`readSessionArtifact` — digest-validated, fail-open: no run_id / no
  pointer / fork run_id mismatch / missing file / digest mismatch all fall through); (2) the
  explicit `plan` param (tool only — now **optional** in the `plan_save` schema); (3) the
  `extractPlanMarkdown` transcript scrape — the universal fail-open last resort for every save
  surface; else the save refuses (`invalid_input` on the tool, a warning report on the command).
  When the artifact wins over a differing non-blank `plan` param, the ignored param is **surfaced**
  in the success message ("⚠ differing plan param ignored"), never silent and never a hard-fail.
  Non-param sources are announced in the success message (`plan source: …`; param-path messages
  stay byte-stable) and the machine-readable `plan_source` (`"plan-draft" | "param" |
  "transcript" | null`) always lands in the tool's `details`.

  **The objective-draft file tool (Objective #352 Node 2.1).** The tool `objective_draft`
  (interior-only; no Python twin) is the objective-flavored twin of `plan_draft`: it writes the
  working objective during read-only objective authoring. It is allowlisted in `READ_ONLY_TOOLS`
  via the same structural carve-out argument (no path/name parameter; the artifact name is the
  fixed constant `objective-draft.json` — `OBJECTIVE_DRAFT_ARTIFACT`,
  `extension/factories/objectiveDraft.ts` — and the path derives exclusively through the accessor seam;
  the gate's `edit`/`write`/bash blocking is unchanged). The artifact is a **single JSON file**
  carrying `{schema_version: 1, title?, prose, roadmap}` — the structured roadmap rides
  **verbatim** (node-shape validation stays with the Python plane at save time, the
  `parse_structured_roadmap` path; an empty roadmap is allowed — only creation rejects
  roadmap-free objectives). **The JSON is storage/transport only** — the human review surface
  (node 2.2, Plannotator or the first-party editor) displays rendered markdown (the prose + a
  markdown roadmap table) derived from the artifact, never raw JSON. Semantics: full rewrite per
  call, non-terminating, NOT a save — `objective_save`/`/objective-save` remain the canonical
  GitHub persist surface. Failure taxonomy (soft results, never throws): mistyped params →
  `bad_input`; empty/whitespace prose → `invalid_input`; no session `run_id` → `no_run_id`;
  file-or-pointer write failure → `write_failed`. Consumers read the draft only via
  `readSessionArtifact` (digest-validated, fail-open). **The review surface (node 2.2, landed):**
  `plan_review` in an objective-authoring session (stage `objective-author` or
  `objective-save`) reviews the **rendered markdown** —
  `readObjectiveDraft` (fail-open validation over the artifact: stderr warning + `null` on
  malformed JSON / non-object payload / wrong `schema_version` / blank prose) +
  `renderObjectiveDraft` (the prose plus a `## Roadmap` markdown table; a `Phase` column only
  when some node carries one; cells sanitized) — **never raw JSON, never the `plan` param,
  never the transcript**. No draft → soft-skip `reason: "no_objective_draft"` with an
  `objective_draft` redirect. **The approval→save orchestration (node 2.3, landed):** an
  APPROVED outcome wires into the `objectiveApprovalSave` seam (`extension/factories/objectiveSave.ts`,
  the objective sibling of `approvalSave`): the seam **re-reads the structured artifact at save
  time** (`readObjectiveDraft` — never the rendered markdown, never a param, never the
  transcript) → `saveObjective` → D1a gate exit on a successful save (snapshot
  `gating.isActive()` before the save) → a **terminating** result; a failed save is
  non-terminating, the gate stays read-only, and the human `/objective-save` failsafe is
  directed. Title precedence: an explicit title wins; else the draft's `title`; else the cold
  door derives from the prose heading.

  **Provenance (Node 1.3).** Session artifacts become *consumable* only via their
  `session_artifacts` pointer in `perk:workflow-state` (§8.3) — a bare file on disk is never
  trusted. The digest convention is `sha256:<hex>` of the bytes **read back** from disk after
  the write. Validation derives the path from `run_id` + `name` through the accessor seam; the
  recorded `path` is informational only and never dereferenced (workflow-state entries are
  reconstructable from untrusted session history). Lifecycle: **rewind** ⇒ the rebuilt branch
  carries an older pointer while disk holds newer bytes ⇒ digest mismatch ⇒ refusal; **fork /
  concurrent sessions** ⇒ the pointer's `run_id` ≠ the active one ⇒ refusal (no inheritance —
  a fork child's data dir starts empty); **reload / compaction** ⇒ same `run_id` ⇒ pointer and
  dir persist through the LWW rebuild. Consumers fail open to their fallback when validation
  refuses (the reader returns `null`; mismatched-run_id refusals are silent by design, broken
  promises — missing file, digest mismatch — warn on stderr).
- **Atomic workflow writes + corruption posture.** Every `.perk/workflow/` file write on both
  planes goes through the per-plane atomic-write seam — `perk/state/cache.py::atomic_write_text`
  (exterior) / `extension/substrate/cache.ts::atomicWriteFileSync` (interior): a temp file in the
  same directory + an atomic replace, so a concurrent writer can never tear a file (a reader sees
  either the old bytes or the new bytes, never a mix). Guard-tested in both planes
  (`tests/test_write_guard.py`, `extension/writeGuard.test.ts`): bare write APIs are banned
  outside a justified allowlist of non-workflow writers. Two documented exemptions: the
  **append-only** `events.ndjson` stream (O_APPEND appends cannot truncate-tear; whole-file
  replace would introduce a read-modify-write race) and **existence-only markers** (Python
  `set_marker`'s `.touch()` carries no content; the TS `setMarker` is routed anyway — uniformity
  is free). Atomicity is **not** mutual exclusion — whole-file last-writer-wins between
  concurrent writers is the accepted residual (no locking/versioning). Corruption posture:
  Python's fail-closed workflow readers translate malformed JSON / invalid UTF-8 into `CacheError` — now
  `(UserFacingCliError, ValueError)`-based with `error_type: "cache_invalid"`, so an uncaught
  corruption presents as a clean actionable CLI error naming the corrupt file and the
  move-it-aside remediation (never a traceback), while every best-effort
  `except (OSError, ValueError)` reader keeps its fail-soft behavior; TS readers keep their
  total loud-null degradation (`readJsonOrNull`) — the cross-plane contract remains the *files*,
  not error semantics.
- **GC is perk-owned:** prune `scratch/runs/<id>/` + `handoff/<id>.json` per two rules —
  **terminal-stage** (a *consumed* handoff whose `stage` has empty registry `successors`;
  currently exactly `learn`, computed never hardcoded) ⇒ eligible regardless of age; and
  **age** (older than `max_age_days`, default **14**) ⇒ eligible. The age is the run's ULID
  self-date (`run_id` names self-date; fork suffixes strip via the base ULID), with the run
  dir's / handoff file's `st_mtime` as the fallback for stray non-ULID names. Warm-minted run
  dirs (no handoff ⇒ no stage) are age-pruned only. Current-run protection: a candidate whose
  base ULID matches `$PERK_RUN_ID` (incl. its `<ulid>.<n>` fork children) is always kept.
  Degrade-graceful: an unreadable handoff contributes no stage (age rule only — never
  terminal-prune on a guess); a broken registry degrades the terminal set to empty (the age
  rule still applies — GC never crashes on a broken install). Surfaces: the `cache-gc` `doctor`
  check (a `warn` with remediation `perk state prune` whenever anything is prunable — **no
  `--fix` arm**: deletion is *exclusively* `perk state prune`) and the `perk state prune`
  command (alias `gc`; `--dry-run`/`--max-age-days`/`--json`). Policy home: `perk/state/gc.py`
  (exterior-owned; no TS twin). (erk accumulated session dirs precisely because GC was undefined.)
- `.gitignore`: the **whole `.perk/workflow/` cache tree** is gitignored (a single
  `/.perk/workflow/` entry managed by `init`) — it is runtime/cache state, not durable source, so
  there is **no committed `.gitkeep`**; a fresh clone has no tracked workflow artifact. The
  canonical plan lives in GitHub; the materialized `plan.md` body and `plan-ref.json` mirror are
  transient local copies and must never be tracked. The managed block also ignores
  `/.pi-subagents/` — the borrowed `pi-subagents` engine's project-scoped run-artifact root
  (debug artifacts + chain runs in the session cwd): transient, never tracked. `perk doctor --fix`
  untracks a legacy-committed
  copy and drops any stray ungrouped ignore line, migrates a legacy `.pi/workflow/` cache
  forward (untracking a tracked `.gitkeep`, moving the `plan-ref.json`/`agent-session.json` mirrors
  when the target is absent; disposable scratch is left for the user to delete), and untracks
  legacy-committed `.pi-subagents/` artifacts (files kept on disk — a gitignore rule is inert for
  already-tracked files).
- **`plan-ref.json` (`cache.plan-ref`, T2b):** the provider-agnostic plan-ref payload (§8.4)
  written verbatim. One active ref per checkout/worktree (`.perk/workflow/` is per-checkout). The
  **Python cold door** (`perk plan-save`) writes it on a real save; the **extension** reads it
  on `session_start` to reconcile `active_plan_ref` (§8.3). The cross-plane contract is the
  *file* (`perk/state/cache.py` ↔ `extension/substrate/cache.ts`), not a shared module.
  - **Selector vs binding duality (#43).** The file plays **two roles by checkout**. In the
    **repo root** it is a mutable **selector** — "the plan a no-arg cold `perk implement`
    consumes next" — written by `save`; the `worktree: none` stages (`plan`/`objective-plan`/
    `save`) run here. In a **`plan-<N>` worktree** it is the durable **binding** — "this
    worktree IS implementing plan #N" — materialized by the implement cold door; the worktree
    stages (`implement`/`submit`/`address`/`land`/`learn`) run here. The selector is *not*
    canonical history (GitHub is); it self-heals at the next `save`. The extension must never
    let a stale **root selector** leak into a fresh planning session — hence the stage-gated
    reconciliation in §8.3.

State keys (registry vocabulary): `cache.plan`, `cache.plan-ref`, `cache.scratch`,
`cache.handoff`, `cache.markers`, `cache.session-data`.

---

## §8.2 · The `PERK_RUN_ID` protocol (Q2)

`run_id` is a perk-minted **ULID** (time-sortable → trivial chronological ordering and
"GC older than N" queries). It is simultaneously the **launch token**, the **cache key**
(`scratch/runs/<run_id>/`, `handoff/<run_id>.json`), and the **correlation key** tying the
CLI launcher → handoff blob → the session's `perk:workflow-state` entry → scratch dir →
GitHub event blocks → worker logs.

**Channel — an env var (the only clean Pi launch channel).** Pi exposes no first-class
"pass control data to the extension at launch" flag. The CLI sets `PERK_RUN_ID=<ulid>` in the
environment before `exec pi`; an initial message or `@file` would pollute LLM context.

**Claim (on `session_start`)** — strict verified linkage (`Q3` establish-before-consume):
1. read `process.env.PERK_RUN_ID`;
2. load + verify `handoff/<run_id>.json` (read-back; on mismatch raise a hard, actionable
   error — never a silent `pass`). A handoff already **`consumed: true` by a *different* (or
   unrecorded) session is not claimable** — the id was inherited across a process spawn, so the
   session is an **env-child** and takes the adopt arm below. (A consumed handoff whose recorded
   `pi_session_id` matches the *current* session re-claims idempotently — the original claimer
   whose branch state was lost.);
3. record `run_id` in `perk:workflow-state` (§8.3);
4. mark the handoff **consumed**.

**Adopt (the env-child arm).** Spawned subagent children run as separate `pi` processes with the
parent's environment, so they arrive carrying the parent's leaked `PERK_RUN_ID`. When the branch
has no `run_id` and the env id's handoff is already consumed by a different session (the
verification rule above), the session **adopts a derived child identity** instead of re-claiming:
derive **`<run_id>.<n>`** (the fork sibling scheme), isolate the child's scratch, and record
`{run_id: <child>, pi_session_id, predecessor: <parent run_id>, mode}` with `mode` **inherited
from the handoff** — so a read-only parent's exploration children keep perk's read-only tool
gating. The adopted child **never re-consumes the handoff** (its `pi_session_id` keeps the true
claimer), carries **no `stage`** (no launched-stage impersonation, no stage-binding injection),
and **never captures session pointers** (§8.35) — it cannot shadow the launched session's
evidence. Under `PERK_SELFCHECK` the T3 sentinel records `source: "env-child"`.

**Corrupt-blob posture (total TS readers).** The TS cache-tier readers
(`extension/substrate/cache.ts`) are *total*: an unreadable/corrupt `handoff/<run_id>.json` (or
`plan-ref.json`) is reported loudly on stderr and treated as **absent** (`null`) — so a corrupt
cold-launch blob degrades to the same loud-unclaimed error as a missing handoff (gate off, never
an aborted `session_start`), rather than crashing mid-handler. Defense in depth: the interior
orders the read-only gate sync **before** the plan-ref/stage reconciliation in `session_start`,
so no cache read can prevent gate engagement — a session that already claimed
`mode: "read-only"` re-gates on reload even when its handoff has since been corrupted. The Python
readers (`src/perk/state/cache.py`) deliberately keep **raising** `CacheError` (launch-time
fail-closed, exterior plane); the cross-plane contract is the *files*, not error semantics.

**Optional handoff link context (`objective_id`/`node_id`, #78).** Beyond the claim fields, a
stage may stash extra keys in its handoff blob (the TS `Handoff` interface already carries
`[key: string]: unknown`). `objective-plan` writes the `objective_id`/`node_id` it just marked
`planning` so a later `perk plan-save` recovers the objective→node link **regardless of which save
surface the model used** — the `plan_save` *tool* passes the link explicitly, but an
approval-triggered `approvalSave` (and its `/plan-save` manual-failsafe invocation, which takes
only an optional title) carries no link params at all; the warm `objective_node_claim` carrier
(§8.3) covers those in-session, and this cold handoff carrier covers the relaunch/cold path
(→ §8.23). `plan-save` reads the
handoff and defaults `objective_id`/`node_id` from it only when neither flag was passed (explicit
flags always win; a non-objective handoff has no `objective_id`, so plain planning is unaffected).

The same carrier ferries `consumed_learn` (#102). `learn-docs` launches a **read-only** plan-mode
session, where the `plan_save` *tool* is gated out (`toolGating.ts`); the save lands review-first
through `approvalSave` (or the `/plan-save` failsafe), and only the `plan_save` tool's explicit
`consumed_learn` param can carry the numbers warm — the handoff carrier makes the consume
mechanism independent of which surface fired. The `learn-docs` cold door stashes them as
`handoff_extra={"consumed_learn": […]}`, and
`plan-save` recovers them (`_consumed_learn_from_handoff`) when `--consumed-learn` is absent
(explicit flag wins; a non-factory handoff has no key, so plain planning is unaffected). This makes
the consume mechanism independent of which save surface the model used.

**Fork ≠ branch (easy to get wrong).**
- A **fork** (`/fork`, `/clone`, `ctx.newSession({ parentSession })`, or a headless
  `pi --fork`) creates a **new session file** that inherits the parent's entries — so the
  parent's `perk:workflow-state` (hence its `run_id`) is present in the child's
  `getBranch()`. **Detect a fork by the `run_id ↔ pi_session_id` mapping, not the
  `session_start` reason:** a headless `pi --fork` arrives as `reason: "startup"` (not
  `"fork"`) with no `previousSessionFile`, so reason-based detection is unreliable. On
  `session_start`, compare the rebuilt entry's recorded `pi_session_id` to the **current**
  session handle (the basename of `getSessionFile()`): **equal ⇒ reload** (keep the
  `run_id`); **different ⇒ fork** — the `run_id` was inherited from another session, so
  **derive a child-scoped id `<run_id>.<n>`**, record the parent as `predecessor`, and
  isolate the child's scratch. Do **not** blindly inherit `PERK_RUN_ID` (that would hand the
  parent's id to the child).
- `/tree` branches **in place** (same file / UUID / process), so `PERK_RUN_ID` in the env
  survives and the `run_id` stays **stable**.

**Mint doctrine (three-way).** A warm in-session *stage transition* **keeps** the `run_id`
(matches the registry per-stage `run_id` policy); a *cold* relaunch **mints** a new `run_id`
in the **Python plane** (`perk/state/run_id.py`) that **records its predecessor**, so resume/relaunch
chains stay traceable; and a **warm session with no identity** (decideClaim's `none` arm — no
branch `run_id`, no `PERK_RUN_ID`: ad-hoc `pi`, `pi --plan`) **mints its own ULID in the TS
plane** (`extension/substrate/runId.ts`) on `session_start`, recording `{run_id, pi_session_id}`
via the strict append seam (§8.3) — **no predecessor, no handoff, no disk artifacts**. Spawned
subagent children arrive *with* the parent's leaked `PERK_RUN_ID` and take the **adopt** arm
above (a derived `<run_id>.<n>`, not a mint). A **failed cold claim never falls back to a mint**
(`PERK_RUN_ID` set but the handoff missing/mismatched stays a loud unclaimed error — minting
would mask a launcher bug).
Under `PERK_SELFCHECK`, the T3 sentinel records a successful warm mint as `source: "mint"`.

The Pi session UUID is kept as a **secondary handle** (needed for `SessionManager.open` /
`continueRecent` on resume); the `run_id ↔ pi_session_id` mapping lives in `perk:workflow-state`.

---

## §8.3 · The `perk:workflow-state` schema (Q1)

The single namespaced session entry holding transient (tier-3) workflow state. This section pins
the state record and the cross-plane delegated shapes (the TS-tool ↔ Python-CLI boundaries);
single-plane interior mechanics live in their owning modules' headers (the pointer list at the
end of the section).

**Record (per-field last-write-wins):**

| field | type | meaning |
|---|---|---|
| `run_id` | string (ULID) | the perk run this session belongs to (§8.2) |
| `predecessor` | string \| null | the prior `run_id` this run forked from (or cold-relaunched after), §8.2; null for an original run |
| `pi_session_id` | string | the current session handle — the basename of Pi's session file; the **fork discriminator** (§8.2) and the key to resume via `SessionManager.open`/`continueRecent` |
| `mode` | string | the active registry stage `mode` (`read-only` / `read-write`) — **structurally gates tools** (see below) |
| `stage` | string | the registry stage id this run is acting on, recorded at cold **claim** from the handoff; lets the interior distinguish two read-only stages (e.g. `objective-author` vs `plan`) and inject the right authoring context |
| `active_plan_ref` | object \| null | the provider-agnostic plan ref (§8.4); null during early `plan` |
| `active_objective` | string \| null | the active objective id (`/objective <id>` sets it, `/objective clear` nulls it) |
| `last_review_batch` | object \| null | the last fully processed review batch, appended by `finalize_address` only after publication and thread resolution succeed: `{ pr, counts:{actionable,informational,praise,question}, resolved_thread_ids:[…], at:ISO }` |
| `last_pr_review` | object \| null | the last `/pr-review` (or the experimental `/pr-review-dynamic`) outcome posted via the shared warm `post_pr_review` tool: `{ pr, verdict, angles, comment_count, mode, at:ISO }`; best-effort tier (the PR review is the canonical record) |
| `last_review` | object \| null | the last review-door outcome posted via the warm `submit_pr_review` tool: `{ pr, event, comment_count, mode, at:ISO }`; best-effort tier (the submitted PR review is the canonical record) |
| `session_artifacts` | object \| null | per-name session-artifact provenance pointers `{run_id, name, path, digest, at}` (§8.1); appends carry the **whole merged map** (per-field LWW); strict-append tier |
| `objective_node_claim` | object \| null | the objective node this session has claimed `planning` (`{ objective, node }`); written by the warm `objective_node` tool on a successful `planning` transition, cleared on a successful non-planning transition for the same node and after a successful node-linked plan save; best-effort tier (cheaply reconstructable; loud-but-non-fatal) |
| `conflict_resolution_attempts` | number | the bounded conflict-resolution re-drive counter: incremented each time `/submit` drives the `perk.conflict-resolver` subagent on a definitively-unmergeable PR (cap `CONFLICT_RESOLUTION_ATTEMPT_CAP = 2`), reset to 0 on a clean submit; best-effort tier (cheaply reconstructable) |
| `perk_version` | string | the running perk (extension) version, stamped when run identity is established (the claim/fork/adopt/mint arms, §8.2) — the session-audit **exact-vintage** basis (the key literal is the cross-plane coordination point; the read side is `perk-dev`'s audit corpus/vintage layer); omitted when only the `perkVersion()` failure sentinel is available; best-effort tier |

**Persistence channel:** `pi.appendEntry("perk:workflow-state", data)`. (The *other* Pi
channel — tool-result `details` — is for state that *is* a tool's output; this is not that.)

**Rebuild (non-negotiable discipline):** scan `ctx.sessionManager.getBranch()` for
`entry.type === "custom" && entry.customType === "perk:workflow-state"`, **on both
`session_start` AND `session_tree`** (skipping `session_tree` is the bug that makes state
stale after the user navigates the tree). Apply **per-field last-write-wins** so two tools
writing different fields in the same turn don't clobber each other.

**Subtlety borrowed from `plan-mode`:** when reconstructing state tied to a current
execution, only re-scan entries **after** the marker that began it, so stale fields from a
previous execution don't resurrect.

**Verified linkage tier (Q3):** the `run_id ↔ pi_session_id` mapping and `active_plan_ref`
are **strict** (durable/cross-process → read-back + correct ordering); purely transient
fields cheaply reconstructable on the next `session_start`/`session_tree` are
best-effort-with-logging (never silently swallowed).

**`active_plan_ref` reconciliation (stage-gated):** on `session_start`, after the run_id claim,
the extension reconciles `cache.plan-ref` into `active_plan_ref` — but **only when the launched
stage *consumes* the ref**, i.e. the stage's registry `requires`/`reads` list `cache.plan-ref`
(the worktree binding stages; the root `worktree: none` stages do not consume it, so a fresh
planning session never inherits the stale **root selector** — §8.1's duality). The launched stage
is read from the run's **handoff** blob (`stage`); `fork`/`none` claims carry no launched stage
and never re-read the file (the LWW rebuild preserves an already-linked ref). The append is
**idempotent by `(provider, pr_id)`** with a **strict read-back** (loud-but-non-fatal on
mismatch, headless-safe). If the registry fails to load, reconciliation stays **permissive** when
a launched stage is present (to preserve implement linkage). **No clearing** of the selector
anywhere — gating alone fixes the leak.

**Warm `/plan-save` direct linkage + the version-skew decode posture:** the in-session warm door
appends `active_plan_ref` **directly** after a successful save (same strict read-back, idempotent
by `(provider, pr_id)`), so the live session is linked without waiting for the next
`session_start` — both writers feed the same LWW field. Its decode of the `perk plan-save --json`
payload is strict **only** on `plan_ref` (the field appended to workflow-state); the rendered
issue id/url are derived from it and `existed`/`objective_node` are advisory — so a successful
cold save can never be reported as a warm failure by render-only payload fields (the
CLI↔extension version-skew lesson). The objective node→plan link outcome is **surfaced, never
swallowed**: a failed advance shows a visible `⚠ … NOT advanced — re-run /plan-save` warning
(the node↔plan link — the objective transition surface below).

**Tool gating.** The `mode` field **structurally gates tools** — enforcement, not prompting. When
`mode == "read-only"` the interior (`extension/substrate/toolGating.ts`): (1) restricts the
active tool set to `READ_ONLY_TOOLS` (`read`/`grep`/`find`/`ls`/`bash` + `ask_user_question` +
`plan_review` + the `plan_draft`/`objective_draft`/`gist_draft` session-data carve-outs + `objective_node`
(delegates a bounded node transition to the canonical Python plane) + the **`web` seam**
providers' research tools, the read-only Linear tools, the pi-fff search family (both mode
name-sets — `fffind`/`ffgrep`/`fff-multi-grep` + override's `multi_grep`; the override names
`find`/`grep` are already present — local search belongs in read-only exploration, and FFF's
frecency state lives under `~/.pi/agent/fff/`, outside the worktree), and the pi-subagents delegation family
(`subagent`/`wait` + the parent supervisor pair — kept reachable for the gated delegation flows
and for answering child `contact_supervisor` asks; **accepted no-backstop posture**: spawned
children are unscoped by design (§8.40 adopt-never-impersonates) — `subagent` itself can spawn
ad-hoc read-write children, a deliberate documented leniency like the arg-blind
`curl`/`agent-browser` entries, with no agent allowlist) + `explore_objective_node` (the gated
objective-plan session's OPTIONAL explore step: it spawns the read-only `perk.objective-explorer`
child over the already-carved-in delegation family and writes nothing to the worktree) + the pi-subagents
**child-side engine tools** (`structured_output`/`contact_supervisor`/`subagent_wait` — the first
two register only inside spawned children, so inert in parents; `subagent_wait` is also
registered by the top-level parent extension, an accepted wait-only non-repo-mutating widening in
gated parents; kept active so a gated **adopted** child can
make the engine-required `structured_output` completion call — stripping it fails an
`outputSchema` run with `structuredOutputFailed`) — a static union of foreign
tool names, inert when a package is absent — plus `run_audit_wave` (the gated audit-judge
session's wave call: its one write is structurally bound to the cold door's handoff
`audit_bundle_dir`, §8.50 — no caller-supplied path exists) and `run_harvest_wave` (the gated
learn-harvest session's wave call: its manifest read is structurally bound to the session's
claimed run-scoped scratch path, §8.48 — the relayed param is verified against it and any
other path refused; no worktree writes)) via `pi.setActiveTools`, **snapshot-then-restore** (the restore
falls back to the full configured `pi.getAllTools()` set — never a hardcoded list); (2) blocks
`edit`/`write` and non-allowlisted `bash` at `tool_call`. The bash sub-allowlist covers read-only
inspection commands (read-only `git` queries, `jq`, `curl`, …), read-only `gh` **query**
subcommands (view/list/diff/status/checks/search + `gh auth status`; `gh api` and every mutating
subcommand stay blocked), the read-only `perk objective` queries (`show`/`next` + aliases and
`node-engagement`; the mutating subcommands stay blocked), and the command-keyed `ast-grep` /
`agent-browser` (+ `npx agent-browser`) entries (an accepted arg-blind leniency, like `curl`);
(3) injects a hidden `[READ-ONLY MODE]` context at `before_agent_start` — **once-only per live
copy**: the injection is branch-scan dedup'd on the marker (`branchCarries`), so a session carries
one live copy; compaction dropping the copy makes the scan come up clean and the next
`before_agent_start` naturally re-injects — and **strips** it from `context` when off. The allowlist is restored on both `session_start` and `session_tree` (re-sync
from the rebuilt `mode`). **Fail-closed:** a failed state-rebuild never opens the gate, and
`tool_call` blocks on any internal error. The `enter(ctx?)`/`exit(ctx?)` surface is the API the
interior consumers (plan mode, the factories, the CI executor) compose — the gate is the single
read-only authority. Beside the gate, the same rebuild points apply **stage-scoped active tools**
keyed off the `stage` field (§8.40) — fail-open where the gate is fail-closed.

**The audit-wave write binding (`audit_bundle_dir`, §8.50).** The `perk-dev audit judge` cold
door stashes `handoff_extra={"audit_bundle_dir": <absolute bundle dir>}` in its launch handoff
blob (the §8.2 optional-extra carrier, the `consumed_learn` shape). The warm `run_audit_wave`
tool takes **no parameters** and recovers the dir through the rebuilt workflow-state `run_id` →
the run's handoff blob — the field is the tool's **sole write-target authority** (the structural
boundary justifying its `READ_ONLY_TOOLS` carve-in: no model-relayed path exists, so a gated
session cannot aim the writer anywhere). A session whose launch state lacks the field — i.e.
every session that is not a claimed `audit judge` launch — is refused `bad_state`.

**Progress tracking (checkpoints retired).** perk mints **no** progress state of its own: the
checkpoint substrate is removed — the `perk:checkpoint` entry, the `## Steps` seeding machinery,
the `[WIP:n]`/`[DONE:n]` marker grammar, the generated checklist, `/checkpoints`, and the 📋
widget/footer segment are all gone. Implementation progress is the borrowed `@juicesharp/rpiv-todo`
checklist, driven by prompt-carried discipline (the implement launch prompt + the `perk-implement`
skill): the plan's `## Steps` list is the **initial seed of a dynamic, model-owned checklist** (one
item per step, in order; the implementer derives its own short checklist for a prose plan) — an
explicit **supersession of the P2.T2c decision** ("passive, plan-derived, never model-mutated"):
the checklist is discipline, not enforcement. Historical `perk:checkpoint` entries render as
generic custom entries (no renderer, no shim). The `perk` status slot is **single-value**
(objective only) and keeps its RPC `setStatus` dual-publish.

**The objective transition surface (TS tool ↔ Python CLI).** The genuinely cross-plane shapes:

- `active_objective` is set by `/objective <id>` / a successful `objective_save`, nulled by
  `/objective clear`.
- The warm `objective_save` tool takes `prose` + a **structured `roadmap`** (a JSON array of
  nodes — never hand-written YAML) and delegates to `perk objective create --body <file>
  --roadmap <json> --run-id <rid> --json` — canonical mutation in Python, idempotent on the
  run_id; creation requires **≥1 roadmap node** (`error_type: empty_roadmap`).
- The warm `objective_node` tool delegates to `perk objective node` with **conditional argv** (a
  `pr`-only backlink omits `--status`; a call carrying none of `status`/`pr`/`description` is
  refused `bad_input`, no exec). When `status === "done"` it requires a non-trivial `audit`
  (`.trim()` ≥ 40 chars, else `audit_required`, no exec) — a **model-boundary-only** property:
  the cold CLI (`perk objective node --status done`) and the on-land auto-node-done are
  deliberately non-audited paths.
- `objective_node_claim` is a **resumable lease**: `planning` = a claim (intent to plan, no saved
  plan yet — re-selectable; an abandoned claim self-heals); `in_progress` = a committed plan
  (saved, node→plan backlinked, awaiting land).
- The node↔plan link (the `node.pr` backlink **and** the `planning → in_progress` advance) is
  set **atomically by `plan-save`** when invoked with `--objective-id` + `--node-id` (warm
  `plan_save` params `objective_id` + `node_id`) — fail-open + non-fatal + idempotent on re-save;
  a failed advance is warm-surfaced as `⚠ objective node <id> NOT advanced — re-run /plan-save to
  retry`. When an approval-triggered save carries neither id, the link is recovered
  **both-or-neither** from the rebuilt `objective_node_claim` (any explicit value wins outright —
  never mixed; a malformed claim never blocks the save).
- **Accepted backlink race:** concurrent `update_objective_node` writes are read-modify-write on
  the issue body, so a simultaneous write can drop one node's update. Accepted, not fixed: the
  loser is recoverable (`/plan-save` re-save retries the link idempotently; `perk objective node`
  is the manual repair). No optimistic-concurrency machinery.

State key (registry vocabulary): `session.workflow-state`.

**Owning modules (single-plane interior mechanics).** The narrative detail this section once
carried lives in the owning modules' headers: approval→save orchestration + plan-title
generation (`extension/factories/planSave.ts` / `planTitle.ts` / `planReview.ts`; §8.23 keeps the
review-backend contract); objective budget + threshold compaction
(`extension/factories/objective.ts`); the objective authoring loop
(`extension/factories/objectiveAuthor.ts` / `objectiveSave.ts`; §8.23/§8.24 own the save/store
contracts); the objective plan factory + node-lifecycle selection
(`extension/factories/objectivePlan.ts`, `src/perk/objective/`; §8.24); objective reconciliation
(the reconcile modules + `skills/perk-objective-reconcile/`; the land-path facts stay in §8.4);
session-lifecycle gates + the warm `/implement` handoff (`extension/doors/lifecycleGates.ts`,
`extension/factories/implementHere.ts`); status/footer rendering detail
(`extension/surfaces/surfaces.ts`,
`docs/design/tui-charter.md`); plan mode + the plan provider deferral
(`extension/factories/planMode.ts`; §8.10
owns the provider seams); in-process read-only child sessions
(`extension/worker/readOnlySession.ts`); the read-only CI executor
(`extension/doors/ciExecutor.ts`); the spawned delegation seam + `/address` + `/pr-review` + `/pr-review-dynamic` + `/pr-review-terminal` + `/pr-review-browser`
(`extension/doors/address.ts` / `prReview.ts` / `prReviewDynamic.ts` / `prReviewTerminal.ts` /
`prReviewBrowser.ts` / `submitPrReview.ts` / `hunkHandoff.ts` / `plannotatorHandoff.ts`, `agents/*.md`, `skills/perk-address/` /
`perk-pr-review/` / `perk-pr-review-dynamic/` / `perk-pr-review-terminal/` / `perk-pr-review-browser/`; the gateway op shapes stay in §8.4); the conflict-resolution drive
(`extension/doors/submit.ts`; the probe contract stays in §8.4).


---

## §8.4 · The GitHub gateway contract (Q9/Q10)

**One gateway contract, canonical in the Python plane** (`src/perk/github/` — the forge gateway:
PR/CI/auth/review ops — plus `src/perk/backends/github/` — the issue/objective adapters). The TS
extension never reimplements a mutation: the warm doors delegate to the cold `perk … --json`
doors and decode the shapes pinned here — that decode boundary is the actual cross-plane binding,
and `doctor` verifies conformance.

**Durable invariants (all ops):**

- **Idempotency is keyed on the header `run_id`**, discovered via the **LIST** endpoint (not the
  eventually-consistent search index), create-then-return (`Q3` establish-before-record).
- **REST `gh api`, not porcelain** — with two deliberate exceptions: review threads (GraphQL-only:
  REST has no `isResolved` / `resolveReviewThread`) and `gh pr ready` (draft→ready is
  GraphQL-only).
- **Labels are created lazily** by each gateway create-op on first use (perk never seeds labels
  in `init`).
- **Mutations raise** on failure (the command boundary maps to `UserFacingCliError`); **lookups
  return `… | null`** — and never mask an infra failure as absence (infra failures raise).

### Verification ops (no mutation)

```
check_auth()         -> { ok: bool, user: string|null, scopes: string[], error: string|null }
                        # `gh auth status` (+ `gh api user`); never mutates.
check_repo_access()  -> { ok: bool, repo: string|null, can_push: bool, error: string|null }
                        # `gh repo view`; can_push from viewerPermission ∈ {WRITE,MAINTAIN,ADMIN}.
```

`require_github(ctx)` is the **strict DI binding** for mutating commands (raises
`UserFacingCliError` / `error_type: github_unauthed` when unauthed); `init`/`doctor` call the
`check_*` ops directly to *report* (non-fatal — see §8.5).

### The plan write (+ the run_id upsert)

```
create_label{ name, color, description }            -> Label{ name, created }
    # POST repos/{o}/{r}/labels; HTTP 422 ⇒ created:false (idempotent)
create_plan_issue{ title, body, labels[], run_id }  -> PlanIssue{ number, url, existed }
    # POST repos/{o}/{r}/issues (-F body=@file); idempotent on run_id
add_issue_comment{ issue, body }                    -> CommentResult{ posted }
    # POST repos/{o}/{r}/issues/{n}/comments (the plan-body first comment)
find_plan_issue{ run_id }                           -> PlanIssue | null
    # GET repos/{o}/{r}/issues?labels=perk:plan&state=open + header run_id match
update_plan_issue{ number, title, body_comment }    -> PlanUpdate{ number, body_updated, title_updated, dry_run }
    # find the plan-body comment by marker -> PATCH .../issues/comments/{id} (-F body=@file)
    #   (fallback: POST a fresh comment, body_updated:false) ; PATCH .../issues/{n} (-f title=)
```

- **`perk plan-save` is an upsert keyed on `run_id`.** The *first* save with a `run_id` creates
  the issue and posts the `plan-body` comment; a *re-save* with the same `run_id` updates the
  existing issue **in place** — `create_plan_issue` still dedups (never a second issue per
  `run_id`), then `update_plan_issue` PATCHes the `plan-body` comment with the revised markdown
  and PATCHes the issue **title** from the (possibly revised) plan H1. The comment is found by
  marker (perk stores no comment id — which also repairs legacy issues); a missing comment falls
  back to a fresh POST so the body is never stranded. A re-save **additionally** merges the
  planning header fields (`objective_id`, `consumed_learn`) back into the existing `plan-header`
  via `update_plan_header` when provided — additive, so an omitted field is left intact (no
  clobber of a previously linked objective/learn set, no reset of the submit-populated
  `branch`/`pr`/`lifecycle_stage`). The header write is fail-loud (this is the canonical save).
  `--json` carries a top-level `updated` (true on re-save); the warm `/plan-save` surfaces
  `details.updated` and an "Updated plan #N" message. A **node-linked** re-save
  (`objective_id` + `node_id`) additionally reads the existing issue's stored `plan-header`
  **before any mutation**: a stored `objective_node_id` that is non-null and names a
  **different** node is a typed **`node_conflict`** refusal (fail closed, zero mutation) — the
  same-run-id upsert would otherwise silently rewrite the other node's plan in place
  (self-predecessor header, two roadmap nodes pointing at one plan) while the command succeeds.
  A null stored node stays allowed (legitimately links a standalone plan to a node); same-node
  and non-node-linked re-saves are untouched. The remedy is a fresh run ID per node (the guard
  is a backstop; fresh-run-id-per-node remains the correct scripting posture).
- **`perk replan <plan>` re-authors an OPEN plan *in place*** — a dedicated cold door that
  re-launches the read-only `plan` stage with the target plan's **original `run_id`** (the
  documented exception to "cold mints `run_id`"), so the upsert rewrites the same issue and the
  `plan-header` (and thus the objective/node links) survives. The save lands review-first
  (`plan_review` approval → the same upsert; `/plan-save` is the manual failsafe). It refuses a
  non-OPEN plan (`plan_not_open`), a missing plan, a header without `run_id`, or an empty body.
  The full door contract: §8.27 (plan-issue engagement) +
  `src/perk/cli/commands/plan/replan_cmd.py`; the objective sibling is §8.32.

### The submit path

```
default_branch()                                    -> string
    # gh repo view --json defaultBranchRef (the PR base)
find_pr_for_branch{ branch }                        -> PullRequest | null
    # GET .../pulls?head=<owner>:<branch>&state=all (prefers an open PR)
create_pr{ head, base, title, body, draft }         -> PullRequest{ number, url, is_draft, state, existed }
    # POST .../pulls (-F body=@file); idempotent on head (find-then-create)
reopen_pr{ number }                                 -> void
    # PATCH .../pulls/{n} (state=open); reopens a CLOSED reused PR (submit guard); raises on failure
update_plan_header{ issue, fields }                 -> PlanHeaderUpdate{ fields_updated[], dry_run }
    # GET issue body -> merge fields into the plan-header block -> PATCH .../issues/{n}
    # rejects unknown header keys (LBYL on the schema); submit sets branch/pr/lifecycle_stage=impl
prepend_plan_callout{ issue, callout, command }     -> bool
    # GET issue body -> plan.prepend_callout(body, callout, command=) -> PATCH .../issues/{n}
    # idempotent on `command`; True iff a write occurred (False when already present / dry-run)
get_plan{ number }                                  -> PlanState{ number, url, title, header, pr, state } | null
    # gh issue view --json (+ pulls/{n} when the header carries pr); the `perk resume` read.
    # `state` is the issue's OPEN/CLOSED state (the `replan` OPEN guard reads it).
```

- **PR body:** `Closes #<issue>` (so the squash-merge closes the plan) + a `Plan: #<issue>` link
  + a **plain-text** `` `gh pr checkout <n>` `` footer (no HTML).

### The land path

```
mark_pr_ready{ number }                             -> void
    # gh pr ready <n> — the ONE non-REST op (draft->ready is GraphQL-only); called only on a draft
merge_pr{ number, commit_message? }                 -> PullRequest (state MERGED)
    # PUT .../pulls/{n}/merge (merge_method=squash); idempotent ("already merged" ⇒ success)
```

- **`Closes #<issue>`** rides in the PR body so the squash-merge closes the plan issue;
  `commit_message` repeats it belt-and-suspenders. Post-merge state is **derived from PR**, never
  stored (Q8).
- **Stacked lineage refuses before any mutation.** `perk pr land` (and the delegating `/land`)
  applies the §8.47 routing discriminator — stacked ⟺ the cache plan-ref carries
  `delivery_lineage` OR the fetched plan header does (**header wins**: a stale cached ref must
  not silently land a stacked layer) — and refuses fail-closed (`stacked_plan`) before
  mark-ready/merge: stacked layers land only as one atomic train, never individually.
  `--dry-run` refuses on the cached ref only (dry-run stays fully offline by contract; the real
  run enforces the header half).
- **The pre-merge plan read is load-bearing.** Land fetches the plan (`get_plan`) right after
  the dry-run early-return, before any mutation: a missing plan fails as `plan_not_found`
  (submit/ready's exact posture), the header feeds the stacked discriminator, and the squash
  title rides the same read.
- **Deepened squash commit message.** Land passes `merge_pr(commit_message=)` = plain
  `"<plan title>\n\nCloses #<issue>"` (the title from the hoisted pre-merge plan read, fallback
  `Closes #<issue>` on an empty title). Plain text only — the second of the **two PR targets**
  (the GitHub HTML body is the other); HTML never leaks into `git log`.
- **Post-merge finalization is a reusable delivery seam.** The four durable bookkeeping effects
  (learn-state stamp §8.36 → explicit plan-issue close → objective reconciliation → learn-issue
  consume) live in `perk.delivery.finalize.finalize_landed_plan` — **reconstructed inputs only**
  (a narrow `LandedPlan` + the captured `pr_base` merge evidence), never the worktree cache, and
  **convergent-final-state idempotency** over the four effects (never-downgrade stamp,
  terminal-node skip, backend-idempotent re-closes; sub-steps may re-issue idempotent backend
  calls — the contract is convergence, not zero repeat calls). `close_objective_on_complete=False`
  (the stacked per-layer callers) still marks nodes and posts the honest computed update but
  never calls `close_objective` — the aggregate objective close is that caller's obligation after
  every layer verifies; incremental land keeps the default. Activity reporting (the Linear agent
  "landed" emission) is worktree-session-scoped and **caller-owned** — it stays in `land_cmd.py`,
  outside the seam; the pending-learn marker (worktree-cache state) likewise stays in the caller.

### Learn ops

```
find_learn_issue{ run_id }                          -> PlanIssue | null
    # GET .../issues?labels=perk:learn&state=open + learn-header run_id match. LABEL-SCOPED to
    # perk:learn (+ the learn-header block) so it CANNOT return the plan issue, which shares the
    # plan's run_id under the warm:keep learn stage. Implemented by parameterizing find_plan_issue
    # with label/header_key (the perk:plan/plan-header defaults preserved — no caller changes).
create_learn_issue{ title, body, run_id, plan_number } -> PlanIssue{ number, url, existed }
    # lazy create_label("perk:learn"); idempotent via find_learn_issue (NOT find_plan_issue);
    # renders a learn-header block { run_id, created, plan } into the body so the finder matches.
list_learn_issues{}                                 -> LearnIssueSummary[]{ number, title, url, body }
    # GET .../issues?labels=perk:learn&state=open (the find_plan_issue list call, label-scoped to
    # perk:learn). Returns every open learn issue's full body for the factory inbox; raises on
    # infra failure (never masks as empty); skips non-dict / pull_request entries.
list_plans_pending_learn{ limit }                   -> PendingLearnPlan[]{ id, title, url, closed_at }
    # GET .../issues?labels=perk:plan&state=closed&sort=updated&direction=desc&per_page=<limit>
    # (Linear: terminal-state label query + plan-header attachment decode, paginated then truncated).
    # Filters to plan-header learn_state == "pending" (§8.36). Raises on infra failure; the
    # `perk learn pending` backlog view is the consumer.
close_and_label_consolidated{ issue }               -> bool
    # lazy create_label("perk:consolidated"); POST .../issues/{n}/labels (-f labels[]=perk:consolidated,
    # ADD not replace) THEN PATCH .../issues/{n} (-f state=closed). Idempotent (re-closing /
    # re-labelling is success). Raises GitHubError on infra failure.
```

- **The capture path.** `perk learn capture --json --body <file>` reads the agent-captured
  learnings markdown from a run-scoped scratch file (the stdin-less worker pattern),
  `create_learn_issue`, posts a back-link comment on the plan issue (best-effort), stamps the
  canonical `learn_state: captured` (§8.36, strictly — before the marker clear), and clears
  `pending-learn`. The warm `/learn` orchestration, the evidence bundle, and the classification
  vocabulary are §8.35 (+ `extension/doors/learn.ts`); the canonical skip path is §8.36.
- **The learned-docs/learn-code factories** consume the two list/close ops above; the factory
  contract (partition, inbox, `consumed_learn`) is §8.35 +
  `src/perk/cli/commands/learn/factory_common.py`.

### Review-loop ops (`/address` — GraphQL threads)

The read **raises** on infra failure; the resolve captures **per-item** failures into its result
(one bad thread does not sink the batch) but still raises on a hard infra failure (gh missing /
timeout):

```
get_pr_feedback{ pr_number }                        -> PrFeedback{ pr_number, review_threads[], discussion_comments[], reviews[] }
    # review threads + PR-level reviews via `gh api graphql`; discussion comments via REST
    # GET .../issues/{n}/comments. The three sources are kept SEPARATE (counted apart) — review
    # threads (inline, with a resolvable thread_id) are a distinct API from discussion comments.
    # Read-only; what the spawned `perk.review-classifier` child runs (via `perk pr feedback`).
resolve_review_threads{ batch:[{thread_id, comment?}] } -> BatchResolveResult{ success, results[] }
    # for each item: optional reply (addPullRequestReviewThreadReply) THEN resolveReviewThread,
    # both GraphQL. results[] is per-item {thread_id, success, comment_added, error}; top-level
    # success = all resolved. An already-resolved thread re-resolves to success (idempotent).
    # The internal TS resolve half writes the batch to run-scoped scratch (pi.exec has no stdin)
    # and delegates via `perk pr resolve-threads --json --batch <path>`; model-facing
    # `finalize_address` reaches it only after the normal submit operation succeeds (§8.52).
```

- **Batch shape:** `[{ thread_id, comment }]` (objects, not a flat list).

### Automated-review ops (`/pr-review`)

The `review-post` CLI never passes `event`, so the `/pr-review` posture is **hardcoded
`COMMENT`** (the agent can never approve/block). Resilience is **event-aware** in the gateway: a
failed COMMENT-review submission (e.g. a `line` not present in the diff) falls back to posting
the summary (+ rendered findings) as a single discussion comment, so an advisory review
**always** lands on the PR; the formal-event arms are documented under the PR-review toolbox
ops below:

```
get_pr_review_context{ pr_number, branch, plan_body } -> PrReviewContext{ pr_number, base_ref, head_ref, title, body, diff, plan_body }
    # Read-only. PR meta via `gh api pulls/{n}`, diff via `gh pr diff {n}`. The gateway no longer
    # reads plan/issue state: `plan_body` is resolved backend-neutrally by the consumer
    # (`perk pr review-context`) — the materialized `cache.plan` mirror first, else
    # `IssueBackend.get_plan_body` via the resolver — and passed straight in (best-effort; null
    # lets the review run from the diff). What the spawned child runs.
    # CLI arm: `perk pr review-context --pr <n>` resolves an arbitrary PR by number (existence +
    # head ref via `get_pr`, `plan_body` null, clean `pr_not_found` arm); the flagless plan-ref
    # resolution is byte-identical.
post_pr_review{ pr_number, summary, comments:[{path,line,body,side?}], event? } -> ReviewPostResult{ ok, mode, pr_number, comment_count }
    # ONE atomic review via POST .../pulls/{n}/reviews — comments + body + event land together or
    # not at all. `event` defaults to COMMENT (wire spelling: COMMENT|APPROVE|REQUEST_CHANGES) and
    # `comments[].side` defaults to RIGHT (LEFT anchors a deleted line) — both defaulted, so every
    # existing caller is byte-identical. The last-resort ladder is EVENT-AWARE:
    #   COMMENT — on failure, degrade to one discussion comment (mode "comment_fallback"); raises
    #     only when even the fallback fails. No own-PR classification (GitHub permits COMMENT
    #     reviews on own PRs).
    #   APPROVE/REQUEST_CHANGES — never converted to a non-review comment: an own-PR 422 (stable
    #     substring "your own pull request") raises OwnPrReviewError (no retry — it would fail
    #     identically); otherwise ONE retry with the comments folded into the body (LEFT anchors
    #     keep a " (LEFT)" marker) and the event preserved (mode "review_folded",
    #     comment_count = the batch size); a failed retry — or a bare-verdict failure (empty
    #     comments, no pointless identical retry) — raises loudly. Never a silent verdict drop.
    # mode ∈ {"review", "comment_fallback", "review_folded", "reaction"}. The warm twin is
    # `/pr-review`'s parent-side `post_pr_review` tool, which delegates via
    # `perk pr review-post --json --batch <path>` (the reviewer children report findings to the
    # parent; they never post; review-post never passes `event` — hardcoded-COMMENT posture).
add_pr_reaction{ pr_number }                        -> void
    # the clean-verdict 👍 (issues-reactions endpoint — idempotent on rerun); a hard error on
    # failure (mutations raise; nothing review-shaped is lost).
```

The experimental `/pr-review-dynamic` door shares `post_pr_review`/`review-post` and the clean
guard unchanged — angle selection is delegated to a fresh `perk.review-angle-selector` lane and
normalized in module-rendered code (`extension/waves/prReviewDynamicWave.ts`); the baseline
`/pr-review` stays canonical. The selector picks from the six-slug additional-angle allowlist
(`correctness`/`tests`/`quality`/`api-design`/`code-organization`/`idioms` — the shared
seven-angle vocabulary minus the structural `plan-fidelity`), capped at 3 additional angles
(2–4 lanes total, the same window as `/pr-review`; `force_angles` takes 1–3 slugs, merged
forced → picks → custom). The selector may additionally propose AT MOST ONE change-specific
custom angle: validated deterministically in the module-rendered normalization (kebab-case slug
3–32 chars, not a reserved lane key, whitespace-collapsed non-empty scope ≤ 300 chars; an
invalid proposal degrades to no-custom, never a failed selector lane), its lane task built from
a fixed scope-definition-only template (the one sanctioned exception to "reviewer tasks come
only from the embedded vocabulary"), its per-item report schema locked to echo the custom slug,
and the lane retryable through the per-lane `outputSchema` seam on `WaveLane`; the
correctness+tests fallback fires only with zero valid picks AND no valid custom. Both wave
tools (`run_pr_review_wave`, `run_pr_review_dynamic_wave`) persist ordered attempt receipts in
their tool-result details (observability only — §8.35's output-free receipt contract; the clean
guard and completeness are unchanged).

### PR-review toolbox ops (checkout / cleanup / review-submit)

The two human-in-the-loop review doors (`/pr-review-terminal`, `/pr-review-browser`) review a
PR — foreign or the active worktree's own. A foreign review needs a detached checkout of the PR
head so reviewer children can investigate real surrounding code at head and the review surface
can diff inside it. Plain cold workers (no registry stages), consumed by the two warm doors
below:

```
perk pr review checkout --pr <n> --json -> { success, error_type, message, path, pr, url, head_sha, base_sha, base_ref }
    # A DETACHED checkout of the PR head at <worktree_root>/review-<n> — outside the plan-<N>
    # namespace (invisible to `worktree wipe`; `worktree list`/`remove` are the manual fallback).
    # One fetch covers both refs: `git fetch origin "+refs/pull/<n>/head:refs/perk/review/<n>"
    # <base_ref>` — the head pins into an explicit temp ref (FETCH_HEAD is clobber-racy), deleted
    # best-effort once the worktree exists; the bare base refspec updates origin/<base_ref>.
    # base_sha = merge-base(origin/<base_ref>, head_sha) — the 3-dot base GitHub's PR diff (and
    # `gh pr diff`) uses, NOT REST base.sha. Refresh semantics: an existing review-<n> is
    # force-removed and re-created at the CURRENT head (no reuse, no dirty protection — the
    # checkout is disposable investigation material); a failed fetch leaves it untouched.
    # GC backstop: stale sibling review-<n> checkouts (gitlink mtime > 7 days, or a missing
    # gitlink — broken residue) are reaped before creating; per-item failures warn + continue.
    # Any PR state is checkout-able (OPEN/MERGED/CLOSED); non-OPEN adds a stderr note only.
    # UNTRUSTED-CODE POSTURE (structural): the head is foreign code — the door NEVER runs
    # `[worktree] setup` and never installs anything (pinned by a structural spy test).
    # Errors: pr_not_found · github_error · git_error · not_a_repo (exit 2); exits 0/1/2.
perk pr review cleanup --pr <n> --json -> { success, error_type, message, pr, path, removed }
    # Single-PR and idempotent: nothing to remove → success, removed:false, exit 0. Fully
    # offline (no GitHub calls). Removes a registered worktree (force) or an unregistered
    # leftover dir (rmtree), always followed by `git worktree prune`; also deletes a leftover
    # refs/perk/review/<n> temp ref best-effort.
perk pr review-submit --pr <n> --event <e> --batch <file> --json -> { success, error_type, message, dry_run, pr, event, mode, comment_count }
    # The comments-first review-submission substrate — consumed by the warm `submit_pr_review`
    # posting tool, not human-CLI-first (a plain cold worker: no launcher half, no registry stage; the
    # structural human gate for formal events lives at the warm layer). `--event` ∈
    # approve|request-changes|comment, DEFAULT comment (an omitted flag can never accidentally
    # post a verdict); the envelope echoes the flag spelling, the gateway gets the wire spelling.
    # Batch (strict; a stray key — incl. `fyi` — is bad_batch): { body: str = "",
    # comments?: [{path, line:int, side?: LEFT|RIGHT = RIGHT, body}] }. `line` is non-nullable:
    # unanchorable findings are folded into the review body UPSTREAM (triage curation), never
    # submitted inline. Event-conditioned checks: comment/request-changes require a non-empty
    # body (approve may be body-less; an entirely empty batch is only legal for approve).
    # VALIDATION (the door's reason to exist): every comment's {path, line, side} anchor is
    # checked against the PR diff (`get_pr_diff` — the merge-base 3-dot diff GitHub validates
    # against, parsed by the pure `diff_anchors` module) BEFORE anything touches GitHub; any
    # failure → bad_anchors (exit 1, NOTHING submitted) with per-comment
    # invalid:[{index, path, line, side, reason}] detail — identical shape for dry-run and real
    # runs (the agent's repair loop: re-run --dry-run until it exits 0). `--dry-run` stops before
    # the mutation (mode "validated") but — unlike review-post's fully-offline dry-run — REQUIRES
    # gh + auth (anchor validation fetches the diff): a deliberate, documented divergence.
    # Dry-run ADDITIONALLY predicts the own-PR 422 for formal events (before the diff fetch):
    # PR author == authenticated viewer ⇒ own_pr, nothing "submittable" — a validated batch must
    # mean the real call can land (the first dogfood saw a human-approved review lost to the
    # rejection). Fail-open when either login is unresolvable; the REAL path keeps GitHub as the
    # authority (the gateway's OwnPrReviewError arm), and `comment` never runs the check.
    # A real run is ONE atomic review submission (comments + body + event) via the gateway's
    # event-aware ladder above — never a silent verdict drop; mode ∈
    # validated|review|review_folded|comment_fallback. Errors: bad_batch · bad_anchors ·
    # pr_not_found · own_pr (OwnPrReviewError) · github_error · github_unauthed · not_a_repo
    # (exit 2); exits 0/1/2.
```

**The `submit_pr_review` warm tool** (`extension/doors/submitPrReview.ts`). The human-gated
curated-posting surface both review doors ride — the doors register **no tools of their own**.
Delegates to the `perk pr review-submit` cold worker above (the batch rides the run-scratch
stdin channel); nothing perk-driven reaches GitHub before the human triage, and `gh` mutations /
direct `perk pr review-submit` calls are forbidden on both doors:

- **Params (strict whole-batch decode — ANY malformed field ⇒ `bad_input`, nothing
  executed):** `{ pr: int, event: "approve"|"request-changes"|"comment", body: string
  (empty allowed — the cold door owns the event-conditioned body rule), comments?: [{path,
  line:int, side?: LEFT|RIGHT, body}], dry_run?: bool }`.
- **The gate ladder:** the conversational explicit human go-ahead ALWAYS precedes any non-dry-run
  call (pinned in the tool guidelines + skills + templates); formal events (`approve`/
  `request-changes`) additionally get the structural gate — headless (`!ctx.hasUI`) → soft
  refusal `headless_formal_event`; interactive → a blocking `ctx.ui.confirm` showing the wire
  event, inline-comment count, and the body's first line; declined → `user_declined`, nothing
  executed. `comment` posts on the conversational gate alone.
- **`dry_run` is the anchor-repair loop:** no gates, no `last_review` record, stops before the
  mutation (`mode: "validated"`). A `bad_anchors` failure whose `invalid[]` rows decode cleanly
  renders a per-comment repair table ("repair these anchors and re-run with dry_run: true");
  any payload drift renders a plain fail (never a half table). A formal event on the viewer's
  own PR fails the dry-run as `own_pr` (the cold door's prediction above) — the repair is the
  event, not the anchors.
- **Per-door posting ownership — the terminal contract (three invariants):** (1) nothing reaches
  GitHub before the human triage — every posted comment is human-authored or human-approved, raw
  findings are never auto-posted; (2) on `/pr-review-terminal` this tool is the SOLE posting
  path (hunk has no GitHub posting; `gh` mutations and direct `perk pr review-submit` calls are
  forbidden); (3) the verdict lands last, atomically with the comments — never before them.
- **Per-door posting ownership — the browser contract (the FLIPPED contract — the browser
  surface's native posting IS the GitHub path):** (1) findings stream only into the local
  plannotator session (a UI surface on localhost, never GitHub) — nothing **perk-driven**
  reaches GitHub; (2) **plannotator's native platform-posting is THE GitHub path** — the human
  posts inline comments (their own annotations and perk's pushed findings) plus an
  APPROVE/COMMENT verdict directly from the UI (the UI never posts REQUEST_CHANGES; a platform
  post is a session-ending action — the respond then carries a status string and no
  annotations); (3) **perk composes nothing by default** — all perk-side posting still flows
  through `submit_pr_review` (`gh` mutations and direct `perk pr review-submit` calls stay
  forbidden; the gate ladder applies unchanged), used ONLY for a `request-changes` verdict (the
  one verdict the UI cannot post) or on the human's explicit request, with the batch
  human-settled — never a perk-invented "remainder".
- **`last_review`** (§8.3): `{ pr, event, comment_count, mode, at:ISO }`, appended best-effort
  with strict read-back on non-dry-run success only.

**The `push_annotations` findings-delivery tool** (`extension/doors/annotationPush.ts`;
perk-registered — census §8.40). The finding→annotation mechanics are CODE, not prompt
discipline: the model hands the tool finding batches (one angle per call, findings passed
straight through) and never composes annotation HTTP. FLOW-SCOPED via the door-primed surface
handle: the browser door primes it on a PR-mode open with the deterministic URL (the
preset-`PLANNOTATOR_PORT` mechanism below) and clears it on bridge settle AND on the
readiness-degrade arm — the model never relays or sees the URL (the result prose never echoes
it), and outside a door-opened flow the tool refuses `no_surface`. The primed mode selects the
strict whole-refusal decode (review: line-anchored findings; plan: phrase-anchored — primed by
the `/plan-review-browser` door, §8.23):

- **Code-owned mapping:** the `[severity/confidence]` text prefix (the one severity carrier),
  LEFT→`old` / RIGHT-or-omitted→`new`, `line: null` + a path → file scope / no path → general
  scope (`line: null` findings ARE pushed on this surface but still fold into the review body
  for any GitHub posting); the composed `source: "perk:<angle>"` badge.
- **Anchor-keyed dedupe, global across sources** with 201-pinned `ids`: a pushed anchor is never
  re-pushed (skipped, never refused — re-pushing is always safe); a cross-source duplicate
  skipped from a FINAL (replace) batch is retained and promoted when the owning source releases
  the anchor.
- **Hold-and-accumulate:** a network-level failure holds the mapped batch and returns ok — held
  ≠ degrade (the door's readiness observer owns degrading); `findings: []` is the pure retry;
  a zero-item pure clear stays a visible pending operation (`held_batches`).
- **`replace: true` source-scoped atomic reshape:** delete-then-post supersedes the angle's
  provisional pushes in one unit — no manual cleanup step exists.
- **Structural delete authority:** the only expressible DELETE is `?source=perk:<angle>`
  composed from the validated slug — the human's and other sources' annotations are untouchable
  by construction.
- **Failure arms:** `no_surface` (unprimed — loud refusal), `bad_input` (the strict per-mode
  decode), `push_rejected` (any non-201 POST / non-2xx DELETE — plannotator version drift;
  the batch is dropped, retrying cannot succeed).

Forbidden on the door regardless: fetching the raw diff into the parent session (anchors come
from the children) and any `gh` mutation.

**The adversarial-reviewer angle agent.** A perk-owned project agent
`agents/adversarial-reviewer.md` (runtime `perk.adversarial-reviewer`) — fresh-context,
read-only, **report-only** (it never posts, never stages or writes files, never resolves
threads, never spawns subagents), delivered like its siblings via the managed `.pi/agents/perk/`
convergence. It reviews **any PR regardless of ownership — the untrusted posture is the default,
not a foreign-PR special case** — along **one assigned angle**; the two driving
human-in-the-loop review doors below (`/pr-review-terminal`, `/pr-review-browser`) are its only
perk-owned spawn sites (via the `start_review_wave` wave),
and this pin is the output contract the wave's per-lane schema enforces. The def's prose
additionally works each angle through an adversarial-questions rubric (right / wrong /
underbaked / overbaked-with-a-simpler-alternative) — the rubric lives entirely in the agent
prompt; the contracts pin the output shape, not the judgment rubric.

- **Input (per-spawn task prompt):** the assigned angle, the PR number, and the absolute path to
  the detached read-only head worktree (the checkout above). The child fetches its own context
  via `perk pr review-context --pr <n> --json` (`plan_body` may be null).
- **Angles** (one per spawn; the adversarial menu is exactly these four — `pr-reviewer`'s
  autonomous menu is wider, seven fixed angles plus the dynamic flow's custom lane): `claimed-intent` (the PR text's claims
  checked against the diff, plus a first-class hunt for **undisclosed scope**; the parent always
  includes this angle) · `correctness` (incl. the untrusted-code supply-chain axes: CI/workflow
  edits, dependency pins, install/build scripts, secrets handling, obfuscated code) · `tests`
  (adequacy by reasoning only) · `quality`.
- **Posture:** all fetched text is untrusted DATA, and the PR title/body are **unverified claims
  by the PR author** (an author not trusted by default) — checked against the diff, never built
  on. **Never-execute-the-head:** inside the head worktree the child uses
  `read`/`grep`/`find`/`ls` only (no builds, no tests, no installs); the only command it runs in
  the whole session is `review-context`.
- **Output (the cross-plane contract).** ONE engine-injected **`structured_output`** call
  carrying `{angle, summary, findings[], fyi[]}` — the wave's
  `ADVERSARIAL_REVIEW_REPORT_SCHEMA` (`extension/waves/adversarialReviewWave.ts`); all four
  fields required (`fyi` may be `[]`) and **verdict-free** (a human triages downstream; an empty
  `findings` array is the "nothing found" statement, earned by hunting, never manufactured).
  Each finding is `{path, line: <int-in-diff or null>, side?: "LEFT"|"RIGHT" (omitted = RIGHT),
  severity ∈ critical|major|minor, confidence ∈ high|medium|low, body}`; `line: null` carries a
  real-but-unanchorable finding (folded into the review body downstream, never lost); `fyi` is
  in-session triage color, never posted. No fenced-JSON completion block — a lane without a
  schema-valid `structured_output` call fails (honest incompleteness at collect).
- **The streaming protocol (child-side, unconditional whenever `contact_supervisor` exists).**
  While reviewing, the child sends **non-blocking** progress-update batches —
  `contact_supervisor({reason: "progress_update", message})`, the message a short line plus a
  fenced JSON block `{angle, findings[]}` with each finding in **exactly the completion-report
  finding shape** above. A streamed finding is never re-sent; batches are small and never empty.
  Batches are **provisional** — the final completion report is the **complete set** (streamed
  findings included) and stays the reconcile source of truth. **Children never receive
  the surface handle** (no hunk/plannotator session, launch, or loopback details in any task) —
  findings travel ONLY via progress updates and the final report. When `contact_supervisor` is
  absent, streaming is skipped silently — the report-only completion contract is unchanged.
- **Model** configurable via `[models.subagents] adversarial-reviewer` (both planes; default
  `anthropic/claude-fable-5`, fallback `anthropic/claude-sonnet-4-5` — a deliberately stronger
  tier than `pr-reviewer` for security-sensitive untrusted-code review). A legacy
  `guest-reviewer` key is silently ignored on both planes (`extra="ignore"` — no tripwire).

**The `/pr-review-terminal` warm door** (`extension/doors/prReviewTerminal.ts`). The TERMINAL
entry into human-in-the-loop adversarial PR review — hunk always, **no provider dispatch** (the
surface-named command IS the selection; it never reads `[providers]` — or config at all: the
`[models.subagents] adversarial-reviewer` override is resolved by `start_review_wave` at execute
time). It registers **no tools of its own** — the fan-out pair (`start_review_wave`/
`collect_review_wave`) and `push_annotations` are perk-registered globally (census §8.40), and
posting rides `submit_pr_review` above with its gate ladder and description unchanged. Its terminal substrate
— the door-common PR-token arg grammar (`parseReviewArgs`/`parseReviewDoorArgs`), the strict
checkout decode, the `hunk --version` presence probe, and the R7 handoff — lives in
`extension/doors/hunkHandoff.ts`/`prReviewTerminal.ts` (the browser door imports the door-common
pieces; a neutral re-home is a deferred residual).

- **Args:** `/pr-review-terminal [pr number|url] [focus note]` — both tokens optional
  (`parseReviewDoorArgs`). A leading
  PR number/URL (the shared PR-token grammar) selects the **foreign** mode; empty args select the
  **active** mode; any other text is the active-mode focus note — EXCEPT a leading `http(s)://`
  token that fails the PR parse, which is a usage error (a mistyped PR URL never silently becomes
  a focus note).
- **Entry gates, in order (nothing executed on refusal, each a loud error):** the arg parse →
  headless (`!ctx.hasUI` — the hunk surface and the human triage are constitutive) → the hunk
  probe (refuses with the install hint `npm i -g hunkdiff (or brew install hunk)`) — all before
  any cold-door call.
- **Foreign mode (a PR arg):** the detached `perk pr review checkout` + strict decode (a failure
  renders the envelope `error_type`/message,
  injects nothing), the adversarial-reviewer flow with the streaming fan-out below, guidance from
  `prompts/stages/pr-review-terminal/foreign.md` (the untrusted-foreign-code posture, the triage
  loop, the posting contract, and the `perk pr review cleanup` step).
- **The streaming fan-out (foreign + active; the CODE-owned wave —
  `extension/doors/reviewWaveTools.ts` over `extension/waves/adversarialReviewWave.ts`):** the
  guidance instructs ONE **`start_review_wave`** call — `{angles, pr, worktree, directive?}`
  (2–3 unique angle slugs, `claimed-intent` mandatory), the `pr`/`worktree` relayed verbatim
  from the guidance and the operator focus passed verbatim as `directive` — and the tool renders
  and launches the wave itself, NON-BLOCKING (module-owned mechanics; the model never authors
  workflowScripts): one fresh-context `perk.adversarial-reviewer` lane per angle, a task naming
  the angle, the PR number, and the worktree path ONLY — the surface handle is structurally
  unrepresentable (no URL parameter exists). The tool resolves the
  `[models.subagents] adversarial-reviewer` override at execute time (the doors read no config);
  a pending (launched, uncollected) wave makes a second start refuse `wave_active`; a launch
  failure is a LOUD soft-fail (`error_type` = the wave reason) with no retry — ZERO retries by
  design, honest incompleteness. The parent then holds the model-held
  `subagent_wait({ timeoutMs })` relay loop — unchanged as the streaming cadence: progress
  updates never wake `subagent_wait` and never enter pi-subagents' `pending` map — delivery is
  an injected (`triggerTurn`-bearing) message when a tool call returns — so the timed wait loop
  IS the cadence and the parent holds its turn open (an ended turn degrades streaming to churny
  per-batch wake-ups instead of a held relay). Each arriving fenced-JSON batch is pushed into
  hunk incrementally with **`path`+`line` dedupe** (an in-conversation ledger; a pushed anchor
  is never re-pushed; hold-and-accumulate until the handshake connects). On completion the
  parent calls **`collect_review_wave`** — the typed aggregate
  `{complete, covered, reports, failures}` (a bounded grace absorbs the
  completion-event-vs-wait wake race; an early collect soft-fails `wave_running` with the wave
  RETAINED; no pending wave → `no_wave`) — reconciles from the typed **reports** (union +
  dedupe — the source of truth for triage and posting; streamed batches were provisional; an
  incomplete wave is reported honestly to the human — uncovered angle(s) + failures, never
  papered over), pushes any not-yet-pushed remainder, and — when the handshake never connected
  — applies the unchanged check-in posture (ask, wait, degrade only on the human's explicit
  choice).
- **Active mode (no PR arg):** the shared active-PR resolution ladder — `perk pr url --json` →
  `resolveReviewTarget` with the plan-ref's pinned base. A resolved PR → the same flow re-homed
  to the human's own worktree (`active.md`: no checkout and **no cleanup step**; the children
  still fetch `perk pr review-context` themselves — the raw diff never enters the parent session;
  the own-PR authorship check carries over as the common case). Every non-`no_pr` fail arm (incl.
  `no_plan_ref`) errors loudly, appending the "pass a PR number/URL, or run from a plan worktree"
  hint.
- **Pre-PR mode (the `no_pr` arm):** a **surface-only** since-base review — hunk is launched on
  the working tree's since-base diff, **no reviewers are spawned and nothing posts to GitHub**;
  the minimal `local.md` guidance is a notes read-back loop (tell the human to review + leave
  notes, end the turn while they do — never poll on a timer — then
  `hunk session comment list … --type user` and triage the actionable notes in-session).
- **The since-base sha (active + pre-PR):** `sinceBaseSha(cwd, base)`
  (`extension/substrate/git.ts`, fail-open — null on any failure, never throws): resolve the base
  branch (the plan-ref's pinned base; null ⇒ the repo default via `origin/HEAD`), **best-effort**
  `git fetch origin <branch>` (bounded timeout; a failure — offline, no remote — falls back to
  the stale local ref, keeping the door usable offline), then `merge-base(HEAD, origin/<branch>)`.
  Null ⇒ a loud error naming the pass-a-PR fallback; nothing launched or injected.
- **The R7 launch handoff (door-side, fail-soft, non-blocking — `handleHunkLaunch` in
  `extension/doors/hunkHandoff.ts`, report-scope-parameterized):** every mode hands off
  `hunk diff <sha12> --agent-notes` (agent notes visible in hunk immediately) in the mode's
  worktree (foreign: the checkout; active/pre-PR: `ctx.cwd`). The door does not merely print the
  launch command — it (a) copies `cd <worktree> && hunk diff <sha12> --agent-notes` to the OS
  clipboard (best-effort) and (b) auto-launches hunk in a terminal the human can see, via a
  first-match ladder: a `PERK_TERMINAL_LAUNCH` custom launcher → a `tmux split-window` pane (when
  `$TMUX`) → the macOS terminal keyed off `$TERM_PROGRAM` (Ghostty ≥ 1.3 native surface / iTerm2 /
  Terminal.app as the universal fallback); no Linux emulator sniffing (tmux + the custom seam
  cover it) → otherwise no launch. The rc-less rungs — ghostty (an argv-exec'd surface command:
  quote-aware word split, a relative arg0 joined onto the working directory, never a shell line)
  and tmux (the server environment) — wrap the command in the human's interactive **login shell**
  (`$SHELL -i -l -c '…'`; `/bin/zsh` on darwin / `/bin/sh` elsewhere when `$SHELL`
  is unset or relative), so the launched window resolves `hunk` — and the `node` its
  `#!/usr/bin/env node` shebang re-resolves — exactly like the human's own terminal (rc-file PATH
  augmentation, e.g. mise/nvm activation, included); the shell-line rungs (iTerm2/Terminal.app)
  and the custom launcher receive the bare command (the former type into an interactive login
  shell the terminal opens; the latter owns its own environment). The printed/clipboard line
  keeps the bare `hunk` (the human's interactive shell resolves it). The launch is raced against
  a soft deadline (~2s) so a
  first-run macOS Automation/TCC dialog never stalls the guidance injection: a clean launch within
  the deadline reports **info** ("opened hunk in a new <surface>"); a failed/absent rung or a
  still-pending launch reports **warning** ("ACTION NEEDED — run hunk in another terminal") with
  the launch line (and "it's on your clipboard" when copied), and a pending launch that later
  succeeds adds a follow-up info note. Every rung is fail-soft (throw/nonzero/killed → no launch);
  the loud print + clipboard are the universal fallback, and the `hunk session get` handshake —
  never a spawn success — remains the ONLY verification hunk is actually up. Two env seams gate the
  side effects: `PERK_TERMINAL_LAUNCH` and `PERK_CLIPBOARD_CMD` each mean *unset* → the platform
  default, *empty* → disabled (the harness default, so no suite spawns a window or clobbers the
  clipboard), *non-empty* → a custom launcher/copier. A third, **internal-only** knob —
  `PERK_REVIEW_LAUNCH_DEADLINE_MS` — overrides the ~2s soft deadline (a test seam: suites drive
  the whole door handler, so env is the only injectable surface; not a user-facing seam,
  deliberately absent from user docs). Mid-flow surface failures DEGRADE instead of refusing:
  when the handshake never connects the degrade is the human's **explicit choice** at the
  check-in (the model re-prints the launch command and waits — never a timer, never the model's
  own initiative); findings surface in-session, the triage loop and posting are unchanged, every
  degradation is loud.
- **The triage loop:** a human-in-the-loop conversation, not a form — the flow opens
  with a plain-words map (finding count, one-at-a-time keep/drop/reword in the human's own words,
  the human's own surface notes as candidates, the "what kind of review to post" choice last, and
  nothing to GitHub without an explicit go-ahead); each `ask_user_question` names the human's
  position ("finding 2 of 5") and each option says what happens next; a conversational beat
  separates consecutive questionnaires; and a **declined questionnaire drops to plain
  conversation**, not another form.
- **Binding:** `command:pr-review-terminal` → `perk-pr-review-terminal` (nudge, §8.9), delivered
  on every
  injection — all three modes (the skill's hunk cheat sheets serve the pre-PR read-back too).

**The `/pr-review-browser` warm door** (`extension/doors/prReviewBrowser.ts`). The BROWSER entry
into human-in-the-loop adversarial PR review — plannotator always, **no provider dispatch** (the
surface-named command IS the selection; it never reads `[providers]` — or config at all: the
`[models.subagents] adversarial-reviewer` override is resolved by `start_review_wave` at execute
time). It registers **no tools of its own** — the fan-out pair and the door-primed
`push_annotations` (above) are perk-registered globally (census §8.40), and perk-side posting
rides `submit_pr_review` with its gate ladder unchanged. The door owns the `push_annotations`
surface-handle lifecycle: `primeAnnotationSurface({mode: "review", url})` the moment a PR-mode
browser open picks the port; `clearAnnotationSurface()` when the bridge settles AND on the
readiness-degrade arm (both clears idempotent; a post-degrade push refuses `no_surface`). The
local (pre-PR) mode never primes. Accepted concurrent double-open edge: a second
`/pr-review-browser` while the first browser is open re-primes (a new browser session supersedes
everything), and the first bridge's later settle would clear the second session's surface —
rare and loud already (the fixed-port EADDRINUSE caveat below), noted, not engineered around.
Its shared substrate lives in
`extension/doors/plannotatorHandoff.ts` (the `hunkHandoff.ts` mirror — the pinned `code-review`
envelope, the presence probe, the active-PR ladder, the respond routing, and the browser-open
core), imported by this door and `/pr-review-terminal`'s active mode.

- **Args:** `/pr-review-browser [pr number|url] [focus note]` — the exact `/pr-review-terminal`
  arg semantics (the door imports `parseReviewDoorArgs` — one function ⇒ identical grammar
  by construction): a leading PR number/URL selects the **foreign** mode; empty args select the
  **active** mode; any other text is the active-mode focus note — EXCEPT a leading `http(s)://`
  token that fails the PR parse, which is a usage error.
- **Entry gates, in order (nothing executed on refusal, each a loud error):** the arg parse →
  headless (`!ctx.hasUI` — the browser surface and the human are constitutive) → the plannotator
  presence probe (the `plannotator-review` command; the refusal names the fix: select the
  plannotator plan provider — `[providers] plan = "plannotator-plan"` —
  run `perk init`, then restart pi).
- **The background open (foreign + active):** the handler starts `startPlannotatorBrowser`,
  injects the mode guidance IMMEDIATELY (the URL is deterministic once the port is picked — no
  blocking readiness poll in the handler), and ends its turn. The readiness promise is observed
  in a background task: `ready` → an info note ("plannotator is up at <url> — browser opening");
  `timeout`, or a bridge that settled error/unavailable → a loud error report PLUS a degrade
  notice injected to the model (idle → immediate, streaming → `followUp`): render the findings
  in-session, posting unchanged — and the annotation surface is cleared, so a post-degrade
  `push_annotations` refuses `no_surface` (the notice says so). The bridge respond stays
  background-awaited and routes via the shared `respondMessage` (below).
- **Server addressing (the preset-`PLANNOTATOR_PORT` mechanism — `startPlannotatorBrowser`, the
  browser-open core in `plannotatorHandoff.ts`):** perk's extension and plannotator's
  in-process `node:http` review server share one Node process, and plannotator's port resolution
  reads `PLANNOTATOR_PORT` at bind time — so the server URL is KNOWN the moment the port is
  picked, before the server is up. The core picks a free ephemeral port, saves + presets the env
  var, emits the `code-review` bridge request (the PR-mode payload `{prUrl, cwd}` byte-for-byte,
  background-awaited), and polls `GET http://127.0.0.1:<port>/api/diff` (a review-server-only
  route; 1s cadence, 120s budget — the poll stops early on turn abort or when the bridge settles
  first, an early error/unavailable respond meaning the server never comes), ALWAYS restoring
  the prior env value (delete if previously unset) in a `finally` when the poll ends.
  Concurrency caveat: a second plannotator server starting in the same process during the window
  would collide on the fixed port — rare, loud (EADDRINUSE → plannotator throws → the bridge
  settles error), never silent.
- **Respond routing (the PR modes — `respondMessage` /
  `routeBrowserRespond` in `plannotatorHandoff.ts`):** the bridge's single respond routes back
  into the session via the pure `respondMessage(outcome)` mapping — `handled`+`exit` → the
  closed-without-submitting ask; `handled`+approved+no annotations → the review-is-complete note
  (perk posts nothing; `submit_pr_review` offered only on explicit ask); `handled` otherwise →
  the feedback text + (when annotations exist) a fenced JSON block of the decoded annotations +
  the flipped triage pointer (source-less = human-authored; `perk:*`-badged = perk's own
  findings returning; perk composes nothing by default — `submit_pr_review` ONLY for
  request-changes or on explicit request); `unavailable`/`error` → `report()` error, the flow
  continues in-session. Injection is idle → immediate, streaming → `followUp`. The decoded
  annotation shape (`CodeReviewAnnotation`: `{filePath, lineStart, lineEnd, side: "old"|"new"}`
  + optional `text`/`suggestedCode`/`type`/`scope`/`source`/`severity`) and the `exit` flag ride
  the shared bridge decode — the pre-PR local mode routes separately
  (`routePrReviewOutcome`, keyed on `annotationCount` alone, `exit` checked before the
  approved/feedback arms).
- **Foreign mode (a PR arg):** the same `perk pr review checkout` + strict decode as the
  terminal door (a failure renders the envelope `error_type`/message, injects nothing), then the
  background open on the checkout's PR `url`; guidance from
  `prompts/stages/pr-review-browser/foreign.md` (the untrusted-foreign-code posture, the
  `perk pr review cleanup` step).
- **The streaming fan-out (foreign + active; the CODE-owned wave):** ONE `start_review_wave`
  call and the model-held `subagent_wait({timeoutMs})` relay loop, exactly as on
  `/pr-review-terminal` (the wave-tool contract in that door's block) — but each arriving
  fenced-JSON batch is pushed via ONE `push_annotations` call per angle (the tool contract
  above: code-owned mapping/dedupe/hold; a held result ≠ degrade), and at reconcile each
  covered angle's final findings ride `replace: true` (the source-scoped atomic reshape — no
  manual cleanup step). Children never receive the surface handle — not the URL, not the port
  (structurally unrepresentable in the wave). Once the fan-out turn ends the session is free
  while the human reviews in the browser; the respond arrives later as a message (one shot).
- **Active mode (no PR arg):** the shared active-PR ladder — `perk pr url --json` →
  `resolveReviewTarget` with the plan-ref's pinned base. A resolved PR → the same flow re-homed
  to the human's own worktree (`active.md`: no checkout, **no cleanup step**; the browser door
  never computes a since-base sha — plannotator owns the diff). Every non-`no_pr` fail arm
  (incl. `no_plan_ref`) errors loudly, appending the "pass a PR number/URL, or run from a plan
  worktree" hint.
- **Pre-PR mode (the `no_pr` arm):** the since-base local browser review — the door reports
  "No PR yet …", emits the local bridge payload `{cwd, diffType: "since-base",
  defaultBranch: <plan-ref base, omitted when null>}` in the background, and ends immediately.
  **No reviewers, no guidance injection, no port dance** (no waves to stream — no endpoint
  needed; nothing posts to GitHub in this mode). The single respond routes via
  `routePrReviewOutcome` under the `pr-review-browser` scope (exit → the closed note, checked
  before the approved arm; approved → the approved note; feedback → an injected turn + the
  triage suffix when annotations exist).
- **The posting flip applies to both PR modes** (the browser posting contract above):
  native platform-posting from the UI is the GitHub path; perk composes nothing by default;
  `submit_pr_review` only for request-changes or on explicit request.
- **Binding:** `command:pr-review-browser` → `perk-pr-review-browser` (nudge, §8.9), delivered
  on the
  foreign/active injections (the pre-PR mode injects nothing).

### PR-body craft ops (+ the submit self-checks)

The submit body is composed in `perk pr submit` via **create-then-update** (the checkout footer
needs the PR number, unknown until `create_pr` returns):

```
update_pr_body{ number, body }                      -> PrBodyUpdate{ number, dry_run }
    # PATCH .../pulls/{n} (-F body=@file); mirrors update_plan_header (PR body, not issue body).
    # Re-writes the full body WITH the plain-backtick `gh pr checkout <pr_number>` footer once the
    # PR number is known. Idempotent (overwrites).
get_pr_body{ number }                               -> string | null
    # GET .../pulls/{n} --jq .body; the read `perk pr check` re-validates against.
validate_pr_body(body, *, pr_number)                -> string[]   (empty == valid)
    # PURE (no gh). Footer-scoped ONLY (the <details> embed is explicitly fine): the footer must be
    # present, plain-backtick (not HTML-wrapped), and carry the PR number (word-boundary: #12 ≠
    # …checkout 123). This is the self-check that catches an issue-numbered footer.
```

- **The two-target split.** The HTML-enhanced body — a best-effort `<details>` embed of the
  verbatim plan (via `get_plan_body`; `None` → no embed, no raise) + the checkout footer — goes
  **only** into the GitHub PR body (`update_pr_body`). The squash **commit message** is the OTHER
  target: plain text, set at land, so HTML never leaks into `git log`.
- **Mergeability probe.** **After** the PR is created + the body validated, `perk pr submit` runs
  a deterministic **local** `git merge-tree --write-tree origin/<base> <head-ref>` probe (no GitHub
  round-trip, no reliance on GitHub's eventually-consistent `mergeable` field). Incremental submit
  uses the local branch; stacked submit uses the verified published head SHA returned by publication,
  so a no-op cascade never probes a stale local trigger branch. The report surfaces three `--json`
  fields: `base` (the target branch), `mergeable` (`true` clean / `false` conflicts /
  `null` undetermined), and `conflicts[]` (the conflicted paths). The probe is **fail-open**: an
  unresolvable base or any `merge-tree` exit other than 0/1 yields `mergeable: null` and never
  changes submit's exit code — the warm-door conflict-resolver drive (§8.3's owning-modules list)
  fires only on a **definitive** `mergeable: false`. `--dry-run` stays fully offline. The submit
  still **succeeds mechanically** (exit 0) when conflicts are present — mergeability is reported
  separately, not an op failure.
- **`pr check`.** `perk pr submit` runs `validate_pr_body` as a **post-write self-check** and
  **raises** (`error_type: pr_check_failed`) on failure. A thin `perk pr check --json` (active
  plan-ref → find PR → `get_pr_body` → `validate_pr_body`) is the supervisor surface (exit 0
  valid / 1 invalid·op-failure / 2 not-a-repo).
- **`pr url` (the active-PR locator).** A thin read-only `perk pr url --json` worker (active
  plan-ref → `resolve_plan_worktree_name` → `find_pr_for_branch`) emits `{pr:{number,url}}` (exit
  0 ok / 1 no-plan·no-PR·op-failure / 2 not-a-repo). It fronts the active modes of the warm
  `/pr-review-browser` and `/pr-review-terminal` doors
  (`extension/doors/plannotatorHandoff.ts` owns the envelope + fallback ladder).
- **Draft → ready is a deliberate gesture.** Submit keeps the PR **draft**; perk does **not**
  auto-publish. `perk pr ready` (warm `/ready`) is the explicit review gate — `mark_pr_ready` if
  draft, idempotent. Land's mark-ready-if-draft stays a safety net. Completion is never inferred
  from PR open/closed state alone.
- **Re-submit on rewritten history.** `perk pr submit` **force-pushes the perk-owned plan branch
  with `--force-with-lease`** (auto-force; a no-op on the first push): plan branches (`plan-<n>`)
  are single-author and expected to diverge after amend/squash/rebase, while the lease still
  rejects an *unexpected* origin move (teammate safety). Two stable error surfaces:
  `error_type: dirty_tree` (submit refuses on a dirty worktree — uncommitted work isn't pushed
  and would silently fail to update the PR) and `error_type: push_rejected` (a non-fast-forward /
  lease failure maps to an actionable "remote moved unexpectedly; fetch/rebase and re-submit"
  message; `git_error` remains the fallback).
- **Non-OPEN reused PR (the replan-after-closed-attempt shape).** A replan reuses branch
  `plan-<n>`, so `find_pr_for_branch` can return a prior attempt's PR in a **non-OPEN** state.
  Submit never silently decorates it (which would re-embed the plan into a closed PR that `/land`
  then refuses to merge): a **CLOSED** reuse is reopened via `reopen_pr` (a loud
  `↺ reopened closed PR #n` note on stderr) and submit proceeds byte-identically; a **MERGED** reuse
  is refused with a new `error_type: pr_already_merged` (nothing sane to reuse). A reopen failure
  propagates as `error_type: github_error` (no silent fallback). OPEN reuse is unchanged.

### Plan-ref payload (provider-agnostic)

`active_plan_ref` / `cache.plan-ref` is **provider-agnostic** from day one:

```
{ provider: string,            # the resolved issue backend ("github" today — §8.21)
  pr_id: string,               # STRING (allows non-numeric ids like Jira "PROJ-123")
  url: string,                 # during planning: the plan issue url/id; branch/pr staged null
  labels: string[],            # ["perk:plan"]
  objective_id: string|null,   # the linked objective (opaque string id — §8.21)
  consumed_learn: string[],    # perk:learn issue ids a docs plan consolidates (closed on
                               # land) — opaque strings (§8.21)
  base: string|null }          # the pinned PR merge target / worktree start-point branch;
                               # null ⇒ fall back to the GitHub default branch
```

**Plan-header block (the queryable metadata in the issue *body*).** The minimal
observably-distinct set; rendered as a `perk:metadata-block:plan-header` collapsible YAML
block; the full plan markdown lives in the `plan-body` first comment. **Carrier is
backend-owned:** GitHub renders it in the issue body; **Linear stores the same fields as a
native issue-attachment envelope** (the §8.24 native-attachment metadata amendment) — the field
set below is the cross-backend contract either way:

```
{ run_id: string,              # the §8.2 run that created the plan (idempotency key)
  lifecycle_stage: string,     # "planned" (Q8: collapses planned→impl; post-states from PR)
  branch: string|null,         # staged — populated at submit
  pr: string|null,             # staged — populated at submit
  created: string,             # ISO-8601 UTC
  objective_id: string|null,   # the linked objective (opaque string id — §8.21)
  consumed_learn: string[],    # perk:learn issue ids (opaque strings — §8.21)
  base: string|null }          # the pinned PR merge target / worktree start-point branch;
                               # null ⇒ fall back to the GitHub default branch
```

**The copyable command callout.** A freshly-created plan issue's body **leads with a visible,
copyable ` ```perk impl <id>``` ` callout** (bold label + fenced block + italic hint), injected
on the fresh standalone-create path with the **server-assigned** id (only known post-create).
`<id>` is the artifact's own ref id (GitHub number, Linear `ENG-N`, or a raw project UUID). Pure
portable Markdown, **idempotent** (keyed on the literal command string), and structurally
**above** the `plan-header` block, so header parsing and the submit-time header rewrite are
unaffected. Forward-only (older artifacts are not retro-fitted). Objectives carry the sibling
` ```perk objective plan <id>``` ` callout on their human-readable surface (same idempotency, same
above-every-marker placement).

**The pinned base (`base`).** A plan or objective can declare a **non-default target branch**.
`perk plan save` resolves the effective base **once** — the linked objective's own `base` (the
`objective-header` `base`) → the repo's `[workflow] base` config → `None` — and pins it into BOTH
the `plan-header.base` and the `cache.plan-ref.base`. Three consumers read it: `create_pr` (the
PR merge target), the worktree start-point (`origin/<base>` instead of the detected trunk), and
the `/submit` merge-conflict probe (chain: `cache.plan-ref.base` → `plan-header.base` →
`default_branch()`). An explicit `implement` `--base` flag (a one-off git start-point
override) still wins the start-point verbatim for **incremental** plans only — on a stacked
layer an explicit `--base` is a typed `invalid_input` refusal (the parent is derived from the
delivery train, never chosen; §8.46). `reconstruct_plan_ref`
carries `base` from the `plan-header` so resume paths recover the pinned value.

**Label taxonomy (minimal):** `perk:plan` (green `1f883d`), `perk:learn` (purple `8250df`),
`perk:objective` (indigo `5319e7`, description "perk objective issue"), `perk:objective-node`
(indigo `5319e7`, on Linear project-backed roadmap node-issues), `perk:gist` (yellow `fbca04`,
description "perk gist issue (a rough statement of intent)" — §8.41), and `perk:consolidated`
(gray `6e7781`, description "perk learn issue consolidated into docs/learned"), each **lazily
created** by its gateway create-op on first use. Query by a **single** label — GitHub label
filters are AND-semantics. (On Linear, `perk init` / `doctor --fix` proactively ensure the six
`perk:*` labels at **workspace** scope — §8.21.)

**The `pending-learn` semaphore.** An existence-only `cache.markers` file
(`.perk/workflow/markers/pending-learn`, name shared as `PENDING_LEARN` in both planes): **`land`
sets it** (after a successful merge) — **except for a learn-docs plan** (non-empty
`consumed_learn`), which is exempt from the land→learn cycle entirely (no marker;
`learn_state: skipped` is stamped instead; the envelope's `pending_learn` reports which arm
ran) — **`learn` clears it**. While present it signals the
land→learn cycle is open and the worktree is not yet releasable. **Since §8.36** the marker is
demoted to cache/friction-semaphore: the canonical post-merge learn state lives on the
plan-header `learn_state` field, and the marker is only the local retry signal + the legacy
resolution fallback (and the `worktree wipe` guard).

### Objective storage + the land-path reconciliation (compact)

The objective tier's full storage contract lives in **§8.24** (the `ObjectiveStore` seam); the
mechanics live in `src/perk/objective/` + `src/perk/backends/github/objectives.py`, the land-path
handlers in `src/perk/cli/commands/pr/land_cmd.py` + `src/perk/delivery/finalize.py`. The
gateway-level facts:

- **Storage blocks (perk-namespaced, schema 1).** An objective is an issue + first comment:
  `objective-header` (issue body — compact, queryable: `{ run_id, created, objective_comment_id,
  status, base }`), `objective-roadmap` (issue body — the **canonical** flat-node YAML
  frontmatter: `{ schema_version: "1", nodes: [ { id, slug, description, status, pr, depends_on?,
  comment? } ] }`; phase membership derives from the ID prefix), and `objective-body` (first
  comment — the human-readable rendered roadmap table, marker-bounded and deterministically
  re-rendered from the frontmatter, + prose in a marker-bounded **Reconcilable** region).
- **Explicit-status-only.** A node's `status` is **never inferred from a PR column** —
  `update_node` takes `status` verbatim or preserves it; setting `pr` never changes `status`.
- **Two-step create.** `create_objective_issue` is idempotency-check → lazy `perk:objective`
  label → compose body (`objective-header` with `objective_comment_id: null` +
  `objective-roadmap`) → POST issue → POST `objective-body` comment (capturing its id) →
  **backfill** `objective_comment_id` into the header.
- **The land path is Mechanical + fail-open.** `perk pr land` auto-marks the node(s) backlinked
  to the just-merged plan `done` (non-audited by design — the audit gate is the model-tool
  boundary only, §8.3), checks completeness locally over the post-mark node list and
  **closes the objective when complete** (idempotent on re-land), and **consumes the
  `consumed_learn` issues** (`close_and_label_consolidated`, per-issue isolation — one bad issue
  never blocks the rest). All three are fail-open on expected store/backend failures and never
  change the land result; the warm `/land` surfaces the outcomes and auto-drives the Reconcilable
  pass (§8.28).

State key (registry vocabulary): `github.objective` (the objective storage); `github.learn` (the
learn issues).

## §8.5 · The `init` machine surface (T5; cli-vs-pi §3.2)

`perk init` is a **supervisor surface**: human text → stderr, `--json` → stdout (one object),
stable exit codes. The agent never parses it (it calls extension tools); the consumer is a
process orchestrating sessions.

**Exit codes.** `0` converged · `1` invalid input (`invalid_settings` / `invalid_config`) ·
`2` environment-not-ready (`not_a_repo` / `missing_tool` / `skills_conflict` /
`skills_sync_failed` — see the skills-delivery substrate clause in §8.9). GitHub-unauthed is
**non-fatal** in `init` (reported, exit 0); `github_unauthed` is reserved for the strict
`require_github` path. On `skills_sync_failed` the report **preserves `changes`** (convergence
already happened before the sync); `skills_conflict` short-circuits before any convergence
(`changes` is `[]`).

**`--json` object.**
```
{ success: bool, mode: "self"|"consumer"|"unknown", error_type: string|null, message: string|null,
  env:     [ { name, ok, detail, remediation, optional } ], # tooling checks; `optional:true` entries
                                                          #   (e.g. ast-grep) are non-fatal — present-or-
                                                          #   absent, never a `missing_tool` exit-2
  github:  { auth: { ok, user, scopes[], error },          # null when env-not-ready / verify skipped
             repo: { ok, repo, can_push, error } },
  linear:  { ok, team, error,                              # null unless verify ran AND the committed
             readiness: { auth_ok, user, team_ok,          #   [issues] backend is "linear" (§8.21);
                          missing_labels[], created_labels[], error } | null,  # non-fatal like github
             project: { projects_ok, projects_error,       # project-backed objective readiness (Node 4.2);
                        missing_state_types[], states_error } | null },  # null unless auth_ok && team_ok; non-fatal
  capabilities: string[],                                  # the managed inventory (perk/convergence/capabilities.py)
  changes: string[],                                       # converged/seeded pieces ([] ⇒ already converged);
                                                          #   init also records .perk/managed-state.toml as a
                                                          #   convergence side effect — a changes line appears only
                                                          #   when the file is created/updated (the one-time
                                                          #   backfill), preserving the pure-delta invariant
  warnings: string[],                                      # non-fatal clear-report lines (e.g. repo-authored-skills
                                                          #   structural errors / untracked SKILL.md); kept separate
                                                          #   from `changes` so `changes` stays a pure delta list
  handoff: string|null }                                   # path to the post-init markdown on-ramp
```

The **post-init handoff** (`handoff`) is an *agent-readable* markdown at
`.perk/workflow/post-init.md` (gitignored; regenerated each init) — distinct from the §8.1
machine run-handoff JSON. It is the Phase-0 dogfood on-ramp.

**Capability inventory.** `perk/convergence/capabilities.py` is the declared SSOT of what `init` manages
(required-vs-optional + self-vs-consumer scope). Phase 0 ships an all-required set; `doctor`
**(T6, implemented)** reuses it for health-check filtering (the inventory's `verify()` side). The
installed-optional state file + `Capability` ABC are deferred until the first *optional*
capability exists.

---

## §8.6 · The `doctor` machine surface (T6; cli-vs-pi §3.2)

`perk doctor` is the **second** supervisor surface (the agent never parses it). It is `init`'s
diagnostic twin: `init` converges *forward*, `doctor` **reports** coherence and `--fix` **repairs**
drift. Managed-piece checks reuse `init`'s convergence helpers in **dry-run** (`apply=False`) — so
init and doctor share one desired-state SSOT — and `--fix` runs the same helpers with `apply=True`.
Shipped as a Click **group** (`invoke_without_command=True`) so the Phase-3 `doctor workflow`
subgroup slots in without a breaking change.

**Exit codes (report-don't-refuse, D5).** `0` healthy (warnings allowed) · `1` unhealthy (≥1
failing check) · `2` `not_a_repo`. A **missing required tool is a failing check (exit 1)**, *not*
exit 2 — doctor's job is to report tool problems, not refuse to run; only `not_a_repo` blocks.
GitHub readiness is **non-fatal** (`warn`, never `fail`); doctor **never mutates** GitHub.

**No silent pass.** A check that cannot be evaluated (a shell raised, a file is unreadable) reports
`warn`/`info` with the reason in `detail` — never a silent `ok`.

**`--json` object.**
```
{ success: bool,                         # the command ran (false only on not_a_repo)
  healthy: bool,                         # no failing checks
  self_repo: bool,                       # self (perk's own repo) vs consumer dual-mode
  error_type: string|null,               # "not_a_repo" on the exit-2 path
  message: string|null,
  checks: [ { name, group, status, message, detail, remediation } ],   # status ∈ ok|warn|info|fail
  summary: { passed: int, warnings: int, failed: int },
  fixed: string[],                       # repairs applied by --fix ([] otherwise)
  fix_errors: string[],                  # --fix repairs that FAILED (e.g. a skills sync error;
                                         # rendered loudly; the post-fix re-verify keeps the
                                         # failing check, so the exit code stays honest)
  artifact_health: [                     # one row per managed-artifact registry descriptor
    { key, path, kind,                   #   (managed_artifacts(), sorted by key)
      status,                            # up-to-date | not-installed | locally-modified |
                                         #   changed-upstream | state-missing
      recorded_version: string|null,     # the .perk/managed-state.toml row (null = no recorded row)
      recorded_hash: string|null,
      desired_hash: string,
      observed_hash: string|null } ] }   # null = not installed
```

**Artifact health is report-only/diagnostic** (the `artifact-health` check reports `ok`/`info`/
`warn`, never `fail`): the dry-run managed convergence stays authoritative for pass/fail, and
`--fix` repairs through the existing convergence **then** records `.perk/managed-state.toml`
(content-gated — the write lands on `fixed` only when the file is created/updated, keeping a
second `--fix` at `fixed == []`).

**Groups.** `environment` (tools; required tools missing = `fail`; optional tools (e.g. ast-grep)
missing = `warn`) · `github` (auth/access; non-fatal `warn`) ·
`linear` (verify-gated Linear readiness — auth/team/labels; present only when the committed
`[issues] backend` is `"linear"`; warn-level, the github D3 mirror; `--fix` ensures the six perk
labels — §8.21) · `runner` (remote-runner prereqs; report-only, non-fatal — §8.16) ·
`package` (settings wiring + perk-package ref reconcile + the `extension-install` install-ownership
check + the `required-perk-version` managed check over the committed `.perk/required-perk-version`
pin + the report-only `cli-version` CLI-vs-repo-pin warning (warn, never fail) + the report-only
`resource-overrides` probe over pi resource overrides that touch perk's own resources (warn, never
fail, no `--fix` arm — §8.6a) + the report-only `subagent-compat` pi-subagents surface probe
(installed version + source-file markers for the orchestration surfaces perk's guidance assumes;
`info` when not installed; warn on divergence, never fail; no `--fix` arm — the package stays
unpinned) + the report-only `subagent-bridge-config` check (reads
`subagents.intercomBridge.mode` from the project `.pi/settings.json` and the user-global
`~/.pi/agent/settings.json`; warns — never fails, no `--fix` arm — when either scope sets
`"off"` or `"fork-only"`, either of which silently disables the supervisor channel perk's
live-streaming review flows require);
`--fix` also migrates a former git-clone consumer forward by removing the orphaned clone — §8.6a) ·
`repository` (gitignore/agents blocks + config present/valid) ·
`registry` (the registry self-check) · `skills` (the skills-CLI manifest fragment + the
fail-level `skills-delivery` substrate check + the `repo-skills` repo-authored-skills fragment check
— §8.9) · `bindings` / `providers` (rolled-up
non-fatal config checks — §8.9/§8.10) · `issues` (the fail-level `[issues]` selection check:
linear requires a committed `team` — §8.21) · `state` (the `.perk/workflow/` cache layout +
handoff-blob integrity + the report-only `artifact-health` classification over the managed-state
registry). Managed-piece checks are filtered by `capabilities.applicable(self_repo)`; infra checks
always run. Human render (stderr) follows the three-way condensed rule per group (collapse a clean
group; else expand only its failures/warnings); `--verbose` expands every check.

### §8.6a · perk-package ref reconcile + the npm-install extension (#635/#639/#812)

Keeping a consumer's pi-loaded perk extension runnable rests on two invariants:

- **perk's own extension is wired as an exact version-pinned `npm:@mgiles/perk` entry, reconciled
  *forward*** (no longer purely append-only). `_desired_packages` emits `npm:@mgiles/perk@{__version__}`
  for a consumer (`_perk_npm_entry()`, mirroring the PyPI install pin SSOT in
  `workflow_artifacts.py`); the self-repo still wires `..`. `_merge_static_packages` rewrites perk's
  own `packages` entry **in place** (list position preserved) when its `@mgiles/perk` identity already
  exists but the full spec differs from the desired pin — so a stale `npm:@mgiles/perk@0.0.0` is
  reconciled to `@{__version__}` (extra string duplicates of that identity collapse to one). Only
  perk's own npm identity is version-reconciled; the borrowed npm packages stay unpinned/append-only
  (distinguished by `_npm_name` identity vs `_npm_name(NPM_PACKAGE)`), and a user's other packages
  are never in the desired set so they stay untouched/append-only. The in-body migration strips a
  repo's legacy **`git:` perk** entry (any ref, **any entry form** — by
  `_package_identity == GIT_PACKAGE`, covering a user-rewritten object-form entry) so the flip from
  the old git wiring converges; a user's unrelated `git:` packages are preserved. **Presence is
  computed by identity across ALL entry forms** (string entries and pi's object-form
  `{ "source": <spec>, **filter }` shape alike, via `_entry_spec`) — pi's `pi config -l` flow
  rewrites entries to object form to filter resources, and an unrecognized object-form entry would
  otherwise be duplicate-appended (latent settings corruption). When perk's own identity exists in
  object form, the entry's `source` is reconciled to the desired pin **in place, preserving the
  user's filter keys byte-for-byte**; when both forms share perk's identity, the object-form entry
  is canonical (it carries user data perk cannot reconstruct — the filters) and the duplicates are
  dropped. Invariant 2, re-worded: **perk never *creates* an object-form entry for its own
  package**; it may update the `source` pin inside a user-created one. This rides the existing
  `settings-wiring` `ManagedConvergence` — version-pin drift becomes a `settings-wiring` **fail**
  that `--fix` repairs, with **no new doctor wiring**. The separate report-only
  **`resource-overrides`** doctor check (group `package`, offline, **warn at worst, never fail, no
  `--fix` arm**) names what convergence deliberately leaves alone: an object-form perk entry's
  filter keys (filtering perk's own extension silently breaks every interactive stage session),
  and any `-`/`!` disable pattern in the top-level `extensions`/`skills`/`prompts`/`themes`
  override arrays whose body mentions `@mgiles/perk` or a perk skill name (an honest substring
  heuristic — perk does not reimplement pi's filter-pattern semantics). The only conceivable
  `--fix` would strip user-chosen filters — hostile; the remediation tells the operator to review
  via `pi config -l` instead.
- **perk owns the `@mgiles/perk` *npm install*, superseding pi's `git:`-clone extension lifecycle
  (#812).**
  Node 2.2 flipped perk's own extension to a pinned `npm:@mgiles/perk@{__version__}` settings entry; this
  bullet makes init/doctor/launch **physically install** that pin. pi installs a missing
  project-scope `npm:` package lazily and **unlocked** at launch (`resolvePackageSources`) — a
  missing/half-materialized race for `npm:` packages. The npm install path now **fully supersedes**
  pi's `git:`-clone extension lifecycle, which is retired: the clone status/lock/materialize
  primitives, the `extension-clone` doctor check, and the launch warm-clone are all removed. A
  `doctor --fix` **migration** (`_remove_orphaned_git_clone`, in the `_MIGRATIONS` seam) carries a
  former git-clone consumer forward by `rmtree`-ing the orphaned `.pi/git/<host>/<path>` clone
  (filesystem-only, gitignored path; idempotent — a no-op once absent; a failed removal lands on
  `fix_errors`, never swallowed). perk now owns the install end-to-end:
  `materialize_extension_install` (init/doctor) reconciles the install **forward** —
  install-if-`absent` / reinstall-if-version-`mismatch` (the pinned `@mgiles/perk@{__version__}`,
  `npm install <pin> --prefix .pi/npm --legacy-peer-deps`, additive — borrowed entries untouched) —
  and `ensure_extension_install_present` warms it **pre-launch** in `launch_stage` (presence-only, a
  cheap `is_dir()` no-op once present, so the launch hot path stays network-free). Both run under an
  exclusive `fcntl.flock` on `<repo_root>/.pi/npm/.perk-npm-install.lock` (the lock lives in the
  install **root** `.pi/npm/` — already managed-gitignored — so a `node_modules` wipe never drops it;
  degrades to a no-op lock on non-POSIX), so concurrent launches **serialize** and a double-checked
  `is_dir()` installs exactly once. All npm work is best-effort + **non-fatal** (an `NpmError` —
  flaky network / not-yet-published pin — is swallowed, never raised); the self-repo (`..` package)
  is exempt. The verify-gated `extension-install` doctor check (group `package`) reports it:
  `absent`/`mismatch` → **fail** (+`perk doctor --fix`, which install/reinstalls — perk init/doctor
  *own installing*), `present` → `ok`, `unverifiable` → `warn`, `self` → `info`.
  This is **install ownership**: presence + the *install-vs-pin* version comparison.
- **Version-parity enforcement is complete (#838).** The *wired* pin is enforced by the
  `settings-wiring` check (`_perk_npm_entry()` reconciled forward to `npm:@mgiles/perk@{__version__}`,
  above) and the *installed* version by the `extension-install` check (install-vs-`__version__`
  `mismatch` → fail), both against the running CLI's `perk.__version__` SSOT — **no third
  `version-parity` doctor check** is added (it would only duplicate these). The only version perk
  cannot *statically* check is the **live loaded** extension at launch: pi can lazy-install / load a
  stale `npm:@mgiles/perk`, so the `@mgiles/perk` actually running may differ from the CLI that launched it.
  That runtime skew is surfaced by a **soft `session_start` drift signal**: the local launch seam
  (`launch_stage`) injects `PERK_CLI_VERSION = __version__` into the exec env (a second informational
  launch env var beside `PERK_RUN_ID` — §8.2 — but *not* run-control data: the extension only reads
  it to compare versions), and the extension's `session_start` handler compares it against its own
  `perkVersion()`. When both are present and differ, it emits a **soft, non-fatal `warning`** via
  `report()` (headless-safe; UI notify or stderr) pointing at `perk doctor --fix`. No once-guard
  (it may re-emit on reload — acceptable for a soft warning); silent for ad-hoc `pi` (no env) and the
  self-repo (versions equal). Injected at the **local launch only** (the operator-facing path); the
  remote worker loads from the same pinned install and is headless, so it is deliberately out of
  scope. `tests/test_packaging.py` now also guards the **wired + install pin lockstep** against the
  version SSOT (`test_npm_pin_lockstep`: `_perk_npm_entry()` and `_pinned_spec()` both track
  `_pyproject_version()`), beyond the existing `__version__` `test_version_lockstep`.
- **Two report-only CLI-vs-repo surfaces consume the committed pin.** Both compare
  `perk.__version__` against `.perk/required-perk-version` (via `read_version_pin`) — a *different
  axis* from the npm wired/installed pins above:
  - **The runtime stderr warning** (`perk/cli/version_check.py`, hooked in the root group
    callback): one soft line on an interactive mismatch, **never fatal**. Pinned suppression
    ladder (cheap gates before any I/O): `PERK_SKIP_VERSION_CHECK` (any non-empty value;
    documented as `=1`) · `CI` non-empty · non-TTY stderr · `--version`/`--help` in argv (covers
    subcommand `--help`, which runs the group callback) · any `--json`/machine-output command ·
    the `run-worker` worker path · outside a git repo · missing pin. An unreadable pin is
    reported softly (never swallowed); doctor owns the loud diagnosis.
  - **The `cli-version` doctor check** (group `package`, offline, appended right after the
    managed checks): `ok` on match, **`warn`** on mismatch (never `fail` — a running CLI cannot
    install itself), `info` when the pin is missing (presence/drift is the
    `required-perk-version` managed check's job). Distinct from `settings-wiring` /
    `extension-install` (the npm axis) and from the `required-perk-version` managed check (file
    drift + `--fix`, which reconverges the pin to the running CLI). On a mismatch both the
    managed **fail** and the `cli-version` **warn** fire, deliberately — two remedies, two
    directions (upgrade the CLI vs reconverge the pin); `--fix` never touches the warn.
- **A third report-only startup surface: the post-upgrade notice** (`perk/cli/version_check.py`,
  hooked right after the warning in the root group callback — warning first, notice second; both
  may appear). It consumes the **user-level max-seen store** `~/.perk/last-seen-version`
  (constructed only via `paths.user_perk_dir()`/`paths.last_seen_version_file()` — the one
  perk-owned path outside the repo), not the committed pin. Semantics: max-seen — on the first
  unsuppressed interactive run after an upgrade it records the new version **then** shows one
  line pointing at `perk release-notes` (record-then-notice: an unrecordable store shows
  nothing, or the notice would repeat); first-run and garbled stored content record silently;
  an equal stored version is a no-op with no write; downgrades never lower the max seen. Its
  suppression ladder is the warning's **shared six gates** (`_suppressed`: env opt-out · `CI` ·
  non-TTY · `--version`/`--help` · `--json` · `run-worker`) with **no repo gate** — it fires
  outside a git repo, like `perk release-notes` itself — and suppressed invocations perform
  **no store I/O** (a machine run never consumes the notice). Failure posture: **silent
  degrade** (any `OSError`/`Path.home()` failure → no-op, never a crash or a stderr report —
  the store is a UX nicety with no remediation surface); accordingly there is **no doctor
  check and no init convergence** for `~/.perk` (the store self-heals).

---

## §8.7 · Cross-plane session-context markers (the selfcheck verifier)

Two pieces of session context are converged by one plane and **read back** by the other, so the
literal markers are a cross-plane contract:

- **`<!-- BEGIN perk managed -->`** — the managed `AGENTS.md` block. `perk init` (Python plane)
  writes it; Pi loads `AGENTS.md` into `contextFiles`; the extension's `/perk-selfcheck` (TS plane,
  `extension/doors/selfcheck.ts`) reads `getSystemPromptOptions().contextFiles` and confirms some file
  carries this marker. Changing the literal in `perk/convergence/init/blocks.py` **must** update
  `MANAGED_AGENTS_MARKER` in `extension/doors/selfcheck.ts` in the same turn.
- **`.pi/APPEND_SYSTEM.md`** — the ambient routing index (maintained by `/learn-docs`, never
  `init`). Pi joins it into `appendSystemPrompt`; selfcheck confirms the on-disk content reached the
  prompt verbatim (a trimmed-substring probe).

The division of labor: **`perk doctor` checks the disk** (files converged); **`/perk-selfcheck`
checks the prompt** (the converged context actually reached the model via Pi's
`getSystemPromptOptions()`, available only on a command context). selfcheck logs only derived
booleans/counts — never the raw prompt text (the options expose the full system prompt).
`/perk-selfcheck` additionally reports a per-surface payload **census** (append prompt, context
files, skills section, tool definitions, perk-injected `custom_message` branch context) — still
derived identifiers/counts/chars only, never prompt text; report-only (no gate).

The `.perk/workflow/.perk-t3.json` diagnostics sentinel additionally records **`run_mode`** — Pi's
`ctx.mode` (`tui`/`rpc`/`json`/`print`) — distinct from the workflow **`mode`** (`read-only`/
`read-write`) that drives tool gating. `run_mode` is observability `ctx.hasUI` (a binary) can't
express; it is written from `ctx.mode` on both `session_start` and `session_tree`.

---

## §8.9 · Skill bindings (the trigger→skill delivery contract)

The **second parsed cross-plane contract**, `shared/bindings.yaml` (sibling of `registry.yaml`),
maps a **trigger** to a **skill** plus a per-binding delivery **mode**. It is bundled automatically
via the `shared/` force-include (wheel → `perk/_shared/`, npm tarball → `shared/`) and read by both
planes through independent readers: **`perk/substrate/bindings.py`** (`load_bindings` / `validate`, returning
`BindingSet`/`Binding` + the shared `Issue`/`FindingSeverity` findings, raising `BindingsError` only for
structural failures) and **`extension/substrate/bindings.ts`** (`loadDefaultBindings`, a thin structural
parse). The Python plane is the authoritative validator.

**Trigger vocabulary — one `"<kind>:<id>"` string, kind ∈ {`stage`, `command`}:**
- `stage:<id>` — `<id>` is a **registry stage id** (e.g. `stage:implement`). Fires at that stage's
  launch / session entry.
- `command:<id>` — `<id>` is a perk command / slash-command that is **not** a registry stage (e.g.
  `command:learn-docs`). Fires when that command runs.

**Kind-selection rule:** when a command corresponds 1:1 to a registry stage of the same name, bind
to `stage:<id>` (the canonical trigger — the delivery layer fires it across both the cold launch and
the warm slash-command of that name). Use `command:<id>` **only** for commands with no registry
stage. This keeps the default set free of redundant stage+command pairs for one skill.

**Binding model — `{ trigger, skill, mode }`:** `trigger` is the `<kind>:<id>` string; `skill` is a
skill name (a `skills/*/` dir name today); `mode ∈ {nudge, transclude}` is **per-binding** —
`nudge` delivers a short pointer to follow the named skill — the pointer line carries the skill's
read path (`.agents/skills/<skill>/SKILL.md`) unconditionally, so it works even for skills hidden
from the ambient system prompt — `transclude` inlines the skill body. The same skill may be a nudge
at one trigger and a transclude at another.

**Skill visibility (prompt-hidden workflow skills):** perk's workflow skills — every shipped
`perk-*` skill except `perk-expert` — ship `disable-model-invocation: true` in their frontmatter,
so pi excludes them from every session's ambient `<available_skills>` system-prompt listing. This
scopes **visibility only**: the on-disk body, its `references/` routing, and the `/skill:<name>`
command all remain, and the worktree mirror keeps delivering every skill's files. Each door reaches
its skill through the delivered pointer (a binding nudge or a seed-template line), which is why the
pointer carries the read path. `perk-expert` (description-discovery IS its routing — no binding
points at it) and `ast-grep` (general-purpose; nudged by the managed AGENTS.md block) stay ambient.
Older pi ignores unknown frontmatter keys, so the flag degrades gracefully (the skill simply stays
visible).

**Shipped default set (all `nudge` — the pointer carries the read path, so it suffices even though
perk's workflow skills are prompt-hidden; `transclude` exists for the user-binding case):**

| trigger | skill | mode |
|---|---|---|
| `stage:plan` | `perk-plan` | `nudge` |
| `stage:gist-author` | `perk-gist-author` | `nudge` |
| `stage:objective-author` | `perk-objective-author` | `nudge` |
| `stage:objective-plan` | `perk-objective-plan` | `nudge` |
| `stage:implement` | `perk-implement` | `nudge` |
| `stage:address` | `perk-address` | `nudge` |
| `stage:learn` | `perk-learn` | `nudge` |
| `command:objective-reconcile` | `perk-objective-reconcile` | `nudge` |
| `command:objective-replan` | `perk-objective-replan` | `nudge` |
| `command:replan` | `perk-replan` | `nudge` |
| `command:learn-docs` | `perk-learn-docs` | `nudge` |
| `command:learn-code` | `perk-learn-code` | `nudge` |
| `command:learn-harvest` | `perk-learn-harvest` | `nudge` |
| `command:pr-review` | `perk-pr-review` | `nudge` |
| `command:pr-review-dynamic` | `perk-pr-review-dynamic` | `nudge` |
| `command:pr-review-terminal` | `perk-pr-review-terminal` | `nudge` |
| `command:pr-review-browser` | `perk-pr-review-browser` | `nudge` |
| `command:plan-review-browser` | `perk-plan-review-browser` | `nudge` |
| `command:objective-review-browser` | `perk-objective-review-browser` | `nudge` |
| `command:skills-create` | `perk-skill-author` | `nudge` |
| `command:skills-refine` | `perk-skill-author` | `nudge` |

**Validation depth (shape-only, registry-free):** the loaders/validators check that
`schema_version == 1` (else a structural load error), each binding has a non-empty `skill`, a
`mode ∈ {nudge, transclude}`, and a `trigger` that parses as `<kind>:<id>` with a known `kind` and a
non-empty `<id>`, and that no `trigger` repeats. They do **not** check that a `stage:`/`command:`
target actually exists — that cross-contract, target-existence validation is **`doctor`**'s job.

**Resolver — `shipped-defaults ⊕ user-bindings` (Node 1.2, pure + unit-tested both planes):** a
user **skill-binding overlay** is authored in `.perk/config.toml` as a `[[bindings]]` array-of-tables
(`trigger`/`skill`/`mode` strings); `.perk/local.toml` overlays it with a **whole-array replace**
(local wins — the local array supersedes the committed one entirely, never merged element-wise,
mirroring the leaf-replace overlay for scalars). Both planes parse this into the same binding shape
(`perk/substrate/config.py` → `Config.user_bindings`; `extension/substrate/config.ts` → `PerkConfig.bindings`) and
resolve it against the shipped defaults through a **pure free function** —
`perk.substrate.bindings.resolve_bindings(user_bindings, defaults=load_bindings().bindings)` /
`extension/substrate/bindings.ts resolveBindings(userBindings, defaults=loadDefaultBindings())` — each
returning a `ResolvedBindings { bindings, issues }`. The override is **trigger-keyed**: starting from
the defaults (order preserved), each *applied* user binding **replaces in place** the entry with the
same trigger or **appends** at a new trigger, so the resolved set has **unique triggers by
construction**. A user binding is applied iff it is **shape-valid** (same shape-only checks above)
AND its trigger was not already applied by an earlier user binding; otherwise it is dropped and its
shape/`duplicate` `Issue` recorded in `issues` for loud-but-non-fatal surfacing. **Defaults are
trusted** (not re-validated). The resolver remains registry-free: target-existence is still
**`doctor`** (Node 3.1), never the resolver. No removal/disable syntax and no multi-skill-per-trigger
co-delivery are defined yet.

**Cold-door delivery (Node 2.3, Python plane):** `perk/substrate/binding_delivery.py`
(`render_cold_bindings(user_bindings, repo_root, trigger)`) renders the **full resolved** bindings
(shipped defaults ⊕ the user overlay) whose trigger matches the launch — Node 2.3 deleted perk's
hardcoded "Follow the … skill" strings, so the mechanism is now the **single delivery path** for
perk's own nudges and the defaults are **no longer subtracted**. `launch_stage` appends that
fragment to the initial prompt **only when there is one to augment** (D2): an **idle** launch (a
stage with no `_initial_prompt` — today only `plan`) stays idle, so a binding **never synthesizes** a
whole prompt and never auto-starts a turn; the idle stage's pointer is delivered **warm** by
Mechanism A instead. The launch trigger is `stage:<stage.id>` by default; the `learn-docs` cold door
(which borrows the `plan` stage) overrides it to `command:learn-docs` via `launch_stage`'s
`binding_trigger` parameter, so it never fires `stage:plan`. `objective-reconcile` is a non-launching
**worker** (it rewrites the objective body, no initial prompt), so `command:objective-reconcile` has
**no cold delivery surface** — it fires only at the warm door. `nudge` renders a ``Follow the
`<skill>` skill (read `.agents/skills/<skill>/SKILL.md`).`` pointer line (the read path is
unconditional — no frontmatter read at render time; it is identical for visible and prompt-hidden
skills alike); `transclude` inlines `.agents/skills/<skill>/SKILL.md` with its YAML
frontmatter stripped, degrading to the nudge pointer with a **loud-but-non-fatal** warning when the
file is absent/unreadable. Resolver `issues` and delivery `warnings` are surfaced loud-but-non-fatal
on every launch and never block it. Target-existence remains **`doctor`** (Node 3.1).

**Warm-door delivery (Node 2.2/2.3, TS extension):** `extension/substrate/bindingDelivery.ts` is the in-session
twin of the cold door. `resolvedBindings(cwd)` is the TS mirror of cold's `resolve_bindings(...)
.bindings` — the **full resolved** overlay (defaults ⊕ user, no subtraction — Node 2.3), and
`renderBindings(cwd, trigger)` / `bindingSuffix(cwd, trigger)` render exactly as the cold door does.
It delivers at two **warm surfaces**: **Mechanism A** — a `before_agent_start` handler injects the
launched **`stage:<id>`** bindings as a hidden (`display:false`) `perk:binding-context` message
(mirroring `planMode.ts` / `objectiveAuthor.ts`). This is the delivery path for **`stage:plan`**'s
`perk-plan` pointer (D6): a cold `perk plan` launches **idle** (no prompt to augment), so the one
previously-ambient `plan` skill is now made **explicit** here. **Mechanism B** — `bindingSuffix` is
appended into the guidance of **every** perk warm slash-command so each **self-delivers** its pointer
(D5): `/address`→`stage:address`, `/learn`→`stage:learn`, `/objective-plan`→`stage:objective-plan`
(a warm `/objective-plan` run *outside* a `stage:objective-plan` session would otherwise get none
from Mechanism A), `/objective-reconcile`→`command:objective-reconcile`, `/learn-docs`→
`command:learn-docs`. Delivery is the **single path** for perk's own nudges (Node 2.3 deleted the
hardcoded strings) and **never double-delivers**.

The **cross-plane dedup marker is the render header itself** — `BINDING_HEADER` (TS) is pinned
byte-for-byte to the cold `_HEADER` (Python) by a literal test in **both** planes. The cold door
already puts `stage:<id>` bindings in a cold-launched session's **initial prompt**, and
`before_agent_start` fires for that same session, so Mechanism A injects **iff** a launched `stage`
exists, the resolved render is non-empty, no entry on `ctx.sessionManager.getBranch()`
already carries `BINDING_HEADER` (the cold prompt OR a prior warm inject), **and** the submitting
turn's prompt (`event.prompt`) does not carry it either. The prompt scan is load-bearing on the
launch turn: at `before_agent_start` the just-submitted prompt is **not yet** on the branch, so the
branch scan alone missed the cold seed on that turn and double-delivered (the fixed hole). The
injected custom and the
cold prompt both carry the header → idempotent across turns/reloads; after compaction drops the
original the header disappears and it **re-delivers** (its ongoing value — later prompts don't
carry the header, so the prompt scan stays inert there). Mechanism B is a one-shot
`sendUserMessage` suffix at an invocation distinct from any cold launch, so it cannot auto-double. A
narrower-than-`planMode` `context` strip removes a **stale** `perk:binding-context` custom (stage
changed / overlay removed) while **never** stripping a user message that carries the header (a cold
prompt legitimately does). Resolver shape `issues` are **not** surfaced warm (the cold launch + doctor
own them); only the delivery `warnings` are loud-but-non-fatal: Mechanism A `console.error`s them,
and **`bindingSuffix` (Mechanism B) now `console.error`s them too** (Node 3.1) — previously it
degraded silently. The injection-time mirror is **skill-presence only** (the trigger is fixed at
injection): the **`nudge`** path now warns when its skill is not installed under
`.agents/skills/<name>/SKILL.md` (mirroring the long-standing `transclude` warning), so every
delivered binding whose skill is missing yields **exactly one** warning, in both planes — never
silently delivered. Injection checks only user-originated skills (installed under `.agents/skills`),
so it uses that path **only** (no self-repo fallback).

**Validation (`doctor`, Node 3.1):** `perk doctor` adds one rolled-up, non-fatal **`bindings`**
check (`perk/convergence/doctor/checks.py::_bindings_check`) over the **full resolved set** (`resolve_bindings(user,
defaults=load_bindings().bindings)`). It surfaces the resolver's dropped-user-binding `issues` plus,
per delivered binding: **skill-presence** — the skill is installed under `.agents/skills/<name>/
SKILL.md` (`bindings.is_skill_installed(root, skill)`), **strict on the delivery read path** in
self-repo and consumer trees alike — the only path warm injection reads, so the committed
self-repo `skills/<name>/SKILL.md` layout never substitutes (it once did, hiding a dangling
injected pointer — the R3 blind spot). perk's own `perk-*` skills are
delivered into `.agents/skills/` by the `skills` CLI in **both** self-repo and consumer trees (the
Pi package no longer declares `pi.skills`, so Pi never discovers the package `skills/` dir) — and
**target-existence**
— `stage:<id>` must be a `registry.load_registry().stage_ids()` member, and `command:<id>` must be in
`DELIVERABLE_COMMAND_TARGETS = {objective-reconcile, learn-docs, learn-code, …}` (the only command triggers perk's
delivery layer fires; a `command:<id>` outside it never fires). Every binding finding is a **`warn`**
(loud-but-non-fatal, D1): `perk doctor` stays exit-0 over a binding misconfiguration — the
`bindings` check owns user-binding *config* only. The delivery **substrate** (perk's own skills
actually reaching `.agents/skills/`) is load-bearing and owned by the fail-level
**`skills-delivery`** check below, not by `bindings`. A `BindingsError` on the *bundled* file is a `fail`
("Reinstall perk"; cannot occur in a healthy install). A `RegistryError`/bad-TOML during the check
degrades to a warn note rather than failing (the registry/config checks own those failures). The
check is report-only — no `--fix` for bindings.

**Skills-delivery substrate (load-bearing; #289).** Skills delivery via the `skills` CLI is
**load-bearing**, not best-effort: a consumer where perk's skills cannot be materialized is a
broken environment, surfaced at `init`/`doctor` time (never first at `perk plan` via the warm
dangling-pointer warning, which stays a last-resort signal).

- **`perk init` pre-flight:** before any convergence, `init` probes the five skills-CLI managed
  runtime pathspecs (`SKILLS_MANAGED_PATHSPECS` = `.agents/state.yaml`, `.agents/local.yaml`,
  `.agents/skills`, `.claude/skills`, `.agents/cache` — duplicated by value from the skills CLI's
  `internal/project/project.go`) for **tracked Git content** (`git ls-files`). Any hit
  short-circuits exit 2 (`skills_conflict`) with a migrate-then-rerun remediation; perk never
  auto-untracks (the migration is a human, per-repo task). A `GitError` during the probe degrades
  to *no* short-circuit — the fatal sync below fails loudly instead.
- **Fatal sync:** any `skills init --cache=local` / `skills update --sync` failure (non-zero exit,
  missing CLI, OSError, timeout) is fatal — `init` returns `skills_sync_failed` (exit 2) with the
  failing command + first stderr lines in `message`, **preserving `changes`** (convergence already
  happened). After a successful sync, every `MANAGED_SKILL_NAMES` name must pass
  `bindings.is_skill_installed` — a sync that delivers nothing (e.g. an outdated `skills` CLI) is
  the same fatal failure, never a silent pass. `MANAGED_SKILL_NAMES` is the verified set:
  perk-authored skills (source `perk`) **plus** a set of required external skills. The managed
  fragment now declares **multiple sources** — perk's own (`PERK_SKILL_SOURCE`) plus the required
  external sources (`REQUIRED_SKILL_SOURCES`: `astral`, `dagster`, `mattpocock`) — promoting those
  external skills from repo-specific to managed/required.
- **`doctor` check:** a fail-level **`skills-delivery`** check (group `skills`, evaluated under
  `verify` only — it shells git + validates external-CLI outcomes). Fail conditions, first match
  wins: (a) tracked content under the managed pathspecs (a `GitError` degrades to `warn`, no
  silent pass); (b) the perk fragment (`.agents/manifest.d/perk.yaml`) exists but
  `.agents/manifest.yaml` does not (`skills init` failed or never ran, so `skills update --sync`
  can never run); (c) any `MANAGED_SKILL_NAMES` name (perk-authored + the required external
  skills) not installed per `bindings.is_skill_installed` (strict on `.agents/skills/`).
  Consumers fail (c) plainly. The **self-repo** classifies a missing delivery further — the
  committed `skills/` layout is never an ok-level substitute. The classification applies to
  **perk-authored names only** (`PERK_SKILLS`); a missing required **external** skill
  (`REQUIRED_EXTERNAL_SKILLS` — upstream-sourced, never in the committed `skills/` dir) fails
  plainly ("required external skill(s) not delivered"), never misread as uncommitted. For
  perk-authored names: committed AND present on the skills
  source ref as locally known (`origin/main`, ONE `git ls-tree` probe, shelled only when a
  perk-authored name is missing-and-committed) → **fail** (delivered set stale — re-sync fixes it
  now); committed but not on the local
  `origin/main` → **warn** (the documented pre-merge first appearance — deliverable after merge +
  re-sync; the local remote-tracking ref can lag, so a merged-but-unfetched skill degrades to this
  warn, never a false fail and never silent — the warn text carries the fetch remediation);
  committed nowhere → **fail**. A `GitError` on the probe degrades to `warn` naming the missing
  skills (no silent pass).
- **`doctor --fix`:** the repair-gesture sync's failure message is carried on
  `DoctorReport.fix_errors` (rendered loudly; `fix_errors` in the `--json` report — §8.6); the
  post-fix re-verify keeps the failing `skills-delivery` check so the exit code reflects the
  still-broken state.

**Repo-authored skills (the `.perk/skills/` → manifest-fragment convergence).** A repo may author
its **own** skills under `.perk/skills/<name>/SKILL.md`; perk renders them into a second skills-CLI
manifest fragment `.agents/manifest.d/perk-repo-skills.yaml` (beside the perk-managed `perk.yaml`),
under a self-referential GitHub source derived from the repo's identity (`github.repo_identity` →
`perk-<repo>` alias, `url`, default-branch `ref`). The substrate is
`repo_skills.build_repo_skills_manifest`; the wiring is a **verify-gated convergence gesture**
`converge_repo_skills_manifest(root, *, apply)` — **not** a `ManagedConvergence` (rendering a valid
fragment does a GitHub read, and managed convergences run unconditionally in offline unit tests), so
it runs beside `sync_skills` under `verify` only. **`.agents/manifest.yaml` is never mutated.**

- **Convergence:** valid skills → write the fragment on a byte-difference (`<path>: created|updated`
  only on a real delta); no skills + no errors → remove a stale fragment (`<path>: removed`);
  errors present → **never** write or remove (a transient bad edit never clobbers a previously-good
  fragment). Idempotent (`apply=True/False` compute the same change list).
- **`perk init` posture:** the fragment is converged **before** `sync_skills` (so the skills CLI
  sees the declared source). Structural errors + untracked warnings are **non-fatal** — `init`
  exits 0 and keeps converging, surfacing them on the new **`InitReport.warnings`** field (§8.5).
  Only the sync-time remote `missing-skill` stays fatal (`skills_sync_failed`, exit 2).
- **`doctor` check:** a verify-gated **`repo-skills`** check (group `skills`, report-only, beside
  `skills-delivery`). First match wins: structural `errors` (bad SKILL.md / source-alias collision /
  no GitHub remote) → **`fail`**; on-disk fragment drift (incl. a stale fragment to prune) →
  **`fail`**; untracked SKILL.md → **`warn`**; declared+converged → **`ok`**; no repo-authored
  skills → **`ok`**.
- **`doctor --fix`:** re-converges the fragment (`apply=True`) **before** the sync; structural
  errors ride loudly on `DoctorReport.fix_errors`; the post-fix re-verify re-runs `repo-skills`.
- **Repo-aware sync remediation:** `sync_skills` takes the declared repo-authored skill **names**
  (`repo_skill_names`). They are folded into the post-sync presence loop (a free backstop for a CLI
  that exits 0 but skips an unresolvable skill) and gate one appended remediation clause on every
  failure message — "commit + push the new `.perk/skills/` skill to your default branch, then re-run"
  — emitted **only when** repo-authored skills are declared (no per-skill stderr parsing).

## §8.10 · Provider selection (the supported-set registry + the `[providers]` selection)

The **third parsed cross-plane contract**, `shared/providers.yaml` (sibling of `registry.yaml`
and `bindings.yaml`), is the **supported set** — the catalog of plan/footer/web *providers* perk
knows how to wire — distinct from the per-repo **selection** (a flat `[providers]` table in
`.perk/config.toml`, which is just a pointer into the catalog). It is bundled automatically via the
`shared/` force-include (wheel → `perk/_shared/`, npm tarball → `shared/`) and read by both planes
through independent readers: **`perk/substrate/providers.py`** (`load_providers` / `validate` /
`resolve_providers`, returning `ProviderSet`/`Provider` + the shared `Issue`/`FindingSeverity` findings,
raising `ProvidersError` only for structural failures) and **`extension/substrate/providers.ts`**
(`loadProviders` + the pure `resolveProviders`, returning `ResolvedProviders { plan, footer, web, issues }`
with `issues` as **`string[]`** — the TS plane has no `Issue`/`FindingSeverity`). The Python plane is the
authoritative validator. The
design is locked in `docs/design/adapter-architecture.md` (Node 1.3), over
`docs/design/provider-contract.md` (the seven dimensions) and `docs/design/pluggability-taxonomy.md` (the C3 behavior-preserving
default).

**Provider entry shape — `{ id, seam, package, adapter, default, package_filter? }`:** `id` is the
stable provider id (it is **not** the `cache.plan-ref` `provider` string — see the
“`cache.plan-ref.provider` is the issue backend, not the seam id” paragraph below); `seam ∈
{plan, footer, web}`; `package` is the foreign Pi package spec added to `.pi/settings.json` `packages`
(`null` for perk's own bundled reference provider — nothing to add; **not universal** — the `web`
seam's reference provider `pi-web-access` carries a **non-null** `package` because perk owns no
native web implementation, the documented exception); `adapter` is the perk-owned
shim module bridging a foreign surface to the artifact boundary (`null` for the reference
provider); `default` is a bool — **exactly one `true` per seam**, the behavior-preserving no-config
pick; `package_filter` is an optional Pi object-form filter (`extensions`/`skills`/… arrays) merged
into a foreign package's object-form `packages` entry. Because both planes read this with their
full YAML readers, it can carry the nested `package_filter` object that the narrow-TOML config
reader cannot.

**Shipped set:** the reference entry `perk-plan` (seam `plan`, `package: null` / `adapter: null` /
`default: true`), plus **real** foreign plan entries. `tombell-plan` (→ `npm:@tombell/pi-plan`, `adapter:
planAdapterTombell`) is a real, selectable plan provider (Node 2.3) — no longer illustrative.
The **plan** seam is behavior-complete: perk vacates its surface at registration time + the adapter bridges the foreign one —
see the Node 2.3 status note in contracts-history.md §8.10. There is **no askuser
seam** anymore: it is **retired to a required borrow** — after the first-party tool's deletion the
seam had exactly one selectable provider (nothing to select, the borrow-vs-seam criterion), so
`ask_user_question` is the borrowed `@juicesharp/rpiv-ask-user-question` questionnaire, installed
for every repo via `BORROWED_PACKAGES` and governed name-keyed by §8.40's borrowed census; the
full seam history lives in the askuser status note in
[`contracts-history.md`](./contracts-history.md) §8.10. There is **no todo seam** anymore
either: it is likewise **retired to a required borrow** — after the seam had exactly one
selectable provider (nothing to select, the borrow-vs-seam criterion), the checklist overlay is
the borrowed `@juicesharp/rpiv-todo`, installed for every repo via `BORROWED_PACKAGES` and
governed name-keyed by §8.40's borrowed census (the overlay is the **sole** checklist surface —
perk's checkpoint substrate is removed); the full seam history lives in the todo status
note in contracts-history.md §8.10. A second reference entry `perk-footer` (seam `footer`, `package: null` / `adapter: null` /
`default: true`) plus **four** foreign/null footer providers — `powerline-footer` (→ `npm:pi-powerline-footer`),
`pi-bar-footer` (→ `npm:pi-bar`), `pi-status-footer` (→ `npm:@tombell/pi-status`, #670), and
`pi-default` (`package: null`, #670 — "install nothing / pi stock footer") — make the **footer** seam
an **interface seam** (vacate-only, `adapter: null`). `pi-status-footer` does **not** render
extension statuses, so perk progress is not shown under it (accepted limitation). With these the
footer is governed **exclusively** by `[providers] footer` — no footer outcome needs a manual
`packages` edit. See the footer status note in contracts-history.md §8.10. A third reference entry `pi-web-access` (seam
`web`, **`package: "npm:pi-web-access"`** — the only non-null-package default — / `adapter: null` /
`default: true`) plus two **real** foreign web providers `ollama-web-search` (→ `npm:@ollama/pi-web-search`)
and `juicesharp-web-tools` (→ `npm:@juicesharp/rpiv-web-tools`) make the **web** seam the **other
interface seam** (vacate-only, `adapter: null`) — see the web status note in contracts-history.md §8.10. There is **no review
seam**: a sixth seam (the DISPATCH posture — the selection picked which review surface a
dispatching `/review` door drove) existed and is **retired** — the two surface-named review
doors (`/pr-review-terminal` = hunk, `/pr-review-browser` = plannotator; §8.4) ARE the
selection now (the command is the surface pick); the full seam history lives in the review-seam
status note in contracts-history.md §8.10. What remains outside the seam machinery: the hunk
CLI is an **external CLI** (npm `hunkdiff`, binary `hunk`), not a Pi package — `perk init`
(verified) attempts a best-effort `npm install -g hunkdiff` **unconditionally** when the binary
is absent (failure → a warning, never fatal), and doctor owns the warn-level **`review-cli`**
check (always probes PATH, verify-gated; `perk doctor --fix` retries the install). The
plannotator package `npm:@plannotator/pi-extension` is desired via the **plan** seam's
`plannotator-plan` entry alone; the desired-**union** convergence mechanism stays generic
(dict-keyed across every resolved seam) but its cross-seam instance retired with the seam. The
**default** path (the reference providers) is unaffected and is the hard guarantee.

**`cache.plan-ref.provider` is the issue backend, not the seam id.** Despite
`docs/design/provider-contract.md` framing the `cache.plan-ref` `provider` field as the plan
provider id, today it is the **issue backend** (`"github"`) — `perk/run/launch/prompts.py` branches on
`provider == "github"`. The stamp sites (`plan_save_cmd.py` / `resume.py`'s
`reconstruct_plan_ref` callers) no longer hardcode the `"github"` literal: the field is stamped
from the **resolved issue backend's `backend_id`** (§8.21) — still the issue backend, still ≠
the seam id. That "id == provider field" equivalence is aspirational; Node 2.2 does **not**
restamp it (restamping would break `launch`'s backend branching). `cache.plan-ref` is
untouched by the plan-seam deferral.

**Validation depth (shape-only, repo-free):** the loaders/validators check that
`schema_version == 1` (else a structural load error), each provider has a non-empty unique `id`, a
`seam ∈ {plan, footer, web}`, and that **exactly one `default: true`** exists per seam. They do **not**
check that any repo *selection* names a real provider — that cross-file validation is **`doctor`**'s
job (mirroring how bindings target-existence lives in doctor, not the loaders).

**The `[providers]` selection — flat string table in `.perk/config.toml`:** a per-repo selection with
one key per seam (`plan` / `footer` / `web`), values are **bare provider-id strings** (the TS narrow-TOML
reader `parseTomlSubset` reads string values only; richer structure lives in `providers.yaml`).
Both planes parse it raw (`perk/substrate/config.py` → `Config.providers`; `extension/substrate/config.ts` →
`PerkConfig.providers`); resolution against the supported set is `init`/`doctor` in Python and the
`extension/substrate/providers.ts` `resolveProviders` resolver in TS (added Node 2.2, consumed by `planMode`). An **absent table or absent key → the seam's
`default: true` provider** (zero behavior change, the no-config default). `local.toml` overlay
wins (standard local-override precedence). The pure resolver
`perk.substrate.providers.resolve_providers(selection, providers)` returns `ResolvedProviders { plan,
footer, web, issues }`: an absent key falls back to the default **silently**; an unknown id or a seam mismatch
falls back to the default and records a **loud-but-non-fatal** `Issue`. **The TS resolver is
per-seam fail-open on a missing default** (a named cross-plane difference): when the bundled
catalog carries no `default: true` entry for a seam, `resolveProviders` resolves that seam to a
synthesized built-in reference provider (the `REFERENCE_FALLBACKS` map, built from the exported
reference-id constants) and appends a loud-but-non-fatal issue — never a throw — so one seam's
catalog gap can never collapse another seam's resolution. The warm plane is the long-lived,
skew-prone one: an in-memory extension reading a live-edited `shared/providers.yaml` across a
seam add/retire (either direction) hits exactly this gap; the two TS resolution call sites
(plan/footer) keep their reference-id fallback catches but log the error loudly
(`consoleCapture` routes it into the session log). The Python `_require_default` **stays
strict**: Python is the authoritative validator and its processes are short-lived, reading the
wheel-bundled `perk/_shared`, so code/file skew cannot arise there. Per-event freshness of the
resolution reads is deliberately kept (config edits apply without relaunch). The retired `review`,
`askuser`, and `todo` keys get the **legacy-tripwire treatment** in the Python reader (`ProvidersTable`'s
mapping-driven `_reject_retired_keys` validator over `RETIRED_PROVIDER_KEYS`, the
`_reject_legacy_tables` precedent): a present `[providers] review`, `[providers] askuser`, or
`[providers] todo` key
**hard-fails config load** with removal guidance (`review` points at the two surface doors;
`askuser` points at the built-in borrowed questionnaire; `todo` points at the built-in borrowed
checklist overlay) — deliberate hard break, no dual-read,
no `doctor --fix` arm (diagnostics, not compat). The TS reader needs no twin — it silently
ignores the keys (the documented fail-safe posture, pinned by test on both planes).

**`perk init` two-directional settings wiring:** provider wiring composes on top of the static
`_desired_packages` (perk + `BORROWED_PACKAGES`: `npm:@tombell/pi-diff`,
`npm:pi-subagents`, `npm:@ff-labs/pi-fff`, `npm:@juicesharp/rpiv-ask-user-question`, `npm:@juicesharp/rpiv-todo`) layer within the same `_converge_settings` body —
perk launches inject the env default `PI_FFF_MODE=override` at **both spawn sites** (local
`_exec_pi`, remote `_spawn_worker`) with operator env winning by merge order, so stage sessions
get FFF as `find`/`grep` while warm/bare sessions keep pi-fff's additive default mode
(`fffind`/`ffgrep`) — `npm:pi-web-access` is **no
longer borrowed** (#529): it is the `web` seam's `default: true` provider, converged via the
provider path (see the web status note in contracts-history.md §8.10), so a default repo still installs it but deselecting `web`
removes it like any provider package —
so it stays inside the `settings-wiring` `ManagedConvergence` (one desired-state SSOT — `doctor`
dry-runs/fixes it for free). The **whole supported set** gives the *provider-managed identity set*
(every non-null `package`'s npm/git identity) — the discriminator separating provider packages from
borrowed and user-hand-added packages. The resolved selection gives the *desired foreign packages*.
Unlike today's append-only convergence, provider wiring is **two-directional**: it **removes** any
existing `packages` entry whose identity is provider-managed but **not** desired (a deselect), and
**adds** each desired foreign package in **object form** (`{ "source": <spec>, **package_filter }`,
omitting the filter keys when absent). Entries outside the managed set (perk's own, borrowed, user)
are never touched. An **unreadable** config (malformed TOML, an ill-typed value, or a retired-key
tripwire) makes the provider and linear convergences a **no-op** — never a destructive removal on a
config perk could not read (perk cannot know the selection it still names); surfacing defers to the
config check, and the next init after the repair reconciles normally. **perk never filters its own package and never *creates* an object-form entry
for it** (Invariant 2, re-worded — §8.6a: a user may rewrite perk's entry to object form via
`pi config -l`; perk recognizes it and reconciles only its `source` pin, preserving the filters). **Resolved ambiguity (Node 1.3 step 4):** any `packages`
entry whose identity matches a provider's `package` is treated as **provider-managed** (removable
when deselected); hand-adding a provider's package *without* selecting it is unsupported — a user
who wants that package selects the provider via `[providers]`. The retired `@tombell/pi-plan`
re-enters `packages` **only** when a selection names it.

**Validation (`doctor`):** `perk doctor` adds one **`providers`** check (`perk/convergence/doctor/checks.py::
_providers_check`). A `ProvidersError` on the *bundled* file is a `fail` (cannot occur in a healthy
install; "Reinstall perk"); an `ERROR` shape `Issue` on the bundled file is a `fail`. The repo
selection is resolved against the supported set and any resolver `issue` (unknown id / seam
mismatch) is a single **`warn`** (loud-but-non-fatal — `perk doctor` stays exit-0 over a selection
typo), remediation pointing at `.perk/config.toml [providers]` / `perk init`. There is **no** separate
package-wired / orphan check — that drift is owned by the `settings-wiring` managed convergence
(which `doctor` already dry-runs); `_providers_check` owns only what convergence cannot repair (an
invalid bundled file, a selection naming a non-existent / wrong-seam provider).

**`[compaction]` → `settings.json` `compaction` convergence (init-owned, #206):** a `[compaction]`
table in `.perk/config.toml` tunes pi's **interactive** global auto-compaction for `perk <stage>`
sessions by converging into the committed `.pi/settings.json` `compaction` object (pi reads that
natively at session boot). It is **Python-plane-only** — the extension never reads it (pi consumes
`settings.json` itself), so `extension/substrate/config.ts` is untouched. Three snake_case keys map to pi's
camelCase `settings.json` keys: `enabled`→`enabled`, `reserve_tokens`→`reserveTokens`,
`keep_recent_tokens`→`keepRecentTokens`. Validation goes through a pydantic table model
(`perk/substrate/config.py::CompactionTable`, read via `load_committed_compaction`): an ill-typed
or non-positive value raises a `ConfigError` surfaced by doctor's `config` check (init convergence
defers to that check); `reserve_tokens = true` is rejected explicitly (the bool-is-int gotcha —
it never reads as 1); absent keys still fall to pi defaults. The convergence composes inside
`_converge_settings` (`load_committed_compaction` +
`perk/convergence/init/settings.py::_converge_compaction`), so it stays in the `settings-wiring` `ManagedConvergence` —
`doctor` dry-runs/fixes it for free, **no** new check. **Committed-only read** (the deliberate
divergence from `[providers]`' overlaid `load_config` read): `[compaction]` is read from committed
`.perk/config.toml` **only**, never the `local.toml` overlay, so the committed `settings.json`
stays a deterministic function of committed config (no stray per-user git diff). Per-user overrides
belong in pi's native global `~/.pi/agent/settings.json` (pi merges it under project settings).
**Write semantics are non-destructive write-when-present / leave-when-absent:** when `[compaction]`
is present, its mapped keys merge over any existing `settings.json` `compaction` dict (perk keys
win; unrelated hand-added keys survive; unspecified keys are left to pi's defaults); when
**absent**, `settings.json` is left untouched (perk cannot prove ownership of a bare `compaction`
key, so removal is unsafe — removing `[compaction]` from `config.toml` leaves a stale block to clean
up by hand). A malformed-TOML or ill-typed-value error defers to the config check (treated as
empty here, mirroring `_converge_provider_packages`). perk's headless worker
(`compaction: { enabled: false }`) and the
objective threshold compaction (`[compaction] objective_threshold`) are orthogonal and unaffected.

**`[models]` → `settings.json` default-model convergence (init-owned):** the `[models]` namespace
in `.perk/config.toml` (`default` + `thinking`, either alone; the `stages`/`subagents` sub-tables
are runtime-read siblings) sets the **repo-default model + thinking**
by converging into pi's **top-level** `settings.json` keys `defaultProvider` / `defaultModel` /
`defaultThinkingLevel` (scalars, not a nested dict — the structural difference from
`[compaction]`), which pi reads natively at session boot: perk cold doors, plain `pi`, and the
headless worker (local **and** remote — the SDK session path resolves the same keys from the
checkout's disk-layered settings, so the worker's model becomes configurable here). It is
**Python-plane-only** — the extension never reads it (pi consumes `settings.json` itself), so
`extension/substrate/config.ts` reads only the runtime sub-tables. pi's settings default is an
**exact** provider+id lookup, so `default` must be `provider/id`; perk splits on the **first** `/`
(openrouter ids keep their inner slashes). A `:thinking` suffix on `default` is accepted and split
at convergence under
the **pi-subagents-shared suffix rule**: the last-colon segment is a thinking level **only when**
it is in pi's vocabulary (ollama-style tags like `llama3:70b` stay part of the id); an explicit
`thinking` key wins over a differing suffix (doctor's `models` check warns on the conflict).
Validation goes through `perk/substrate/config.py::ModelsTable` (read via
`load_committed_models` / `load_committed_models_table`) with a **hard-`ConfigError` posture**: an
invalid `thinking` or a slash-less `default` never converges into the committed `settings.json` —
init defers (converges everything else), and doctor's `_config_check` **fails** with the field
path (the one committed-read probe in `_config_check`; the `[compaction]`/`[issues]` parse gaps
keep their current owners). The convergence composes inside `_converge_settings`
(`perk/convergence/init/settings.py::_converge_models`), so it stays in the `settings-wiring`
`ManagedConvergence` (desired/observed portions fold the three keys — drift classifies like
compaction drift; `doctor --fix` reconverges). **Committed-only read** (a `local.toml` `[models]`
`default`/`thinking` is ignored) and **write-when-present / leave-when-absent per key**: an absent
table touches nothing; removing it leaves the written keys to clean up by hand (perk cannot prove
ownership of a bare settings key). Relatedly, `[models.subagents]` values are **blessed** to carry
the same `:thinking` suffix (and pi-subagents' `inherit` sentinel — child inherits the parent
session's model), resolved by pi-subagents from the workflow-level `model` the flow-scoped wave
tools pass on the spawn (read from config at execute time); doctor's
warn-level `models` check flags suspicious suffixes (alphabetic-only last-colon segment outside
the vocabulary) across `[models].default`, `[models.subagents]` values, and
`[models.stages.<id>].model`. Resulting precedence — cold launch: explicit `perk <stage>
--model/--thinking` > `[models.stages.<id>]` > `[models]`-converged settings default > pi's
curated per-provider defaults > first authenticated model; subagents: `[models.subagents]`
(optionally `…:level` / `inherit`) > agent frontmatter `model:` (the settings default never
applies to perk's agents — frontmatter picks per-role economy).

**`subagents.disableBuiltins` convergence (init-owned):** perk converges the constant
`"subagents": {"disableBuiltins": true}` into `.pi/settings.json` in **every** perk repo —
**constant desired with no config read**, the deliberate divergence from `[compaction]`/`[models]`'s
write-when-present shape: perk borrows pi-subagents as the delegation *engine only* and delivers
its own `perk.*` agent defs, so the builtin agents are model-facing noise everywhere perk works.
There is **no opt-out knob** (and none can be added under that spelling — the legacy `[subagents]`
table remains a schema-v2 tripwire in `perk/substrate/config.py` that hard-fails toward
`[models.subagents]`). It is **Python-plane-only** (pi-subagents consumes `settings.json` itself at
session boot; `extension/substrate/config.ts` is untouched), a **merge-preserving single-key
write** (only `disableBuiltins` is perk-owned — sibling keys in the user's `subagents` object
survive byte-for-byte) with a **delta-gated change fragment** (an already-`true` key contributes no
`report.changes` line — the genuine-delta rule; a constant desired would otherwise emit a phantom
fragment on every run that changes anything else). The write composes inside `_converge_settings`
(`perk/convergence/init/settings.py::_converge_subagents`), so it stays in the `settings-wiring`
`ManagedConvergence` (doctor dry-runs/fixes it for free — no new check) and folds into the
desired/observed settings portions like compaction (the observed twin reduces the live `subagents`
dict to the `disableBuiltins` key; drift classifies normally). The sanctioned re-enable is a
**project-settings** per-agent `subagents.agentOverrides.<name>.disabled: false` entry, which
pi-subagents' `applyBuiltinOverrides` consults **before** the bulk flag and which perk's merge
never touches; a **user-global** `~/.pi/agent/settings.json` re-enable does **not** work (the
project bulk-disable is checked before user-scope overrides).

**`tuiMode` seed (init-owned):** perk seeds `"tuiMode": "fullscreen"` into `.pi/settings.json`
**write-when-absent** — the third convergence shape beside write-when-present
(`[compaction]`/`[models]`) and constant-enforced (`subagents.disableBuiltins`): the key is
written once, only when absent, and never overwrites a present key (any value — presence, not
value, is the guard). Python-plane-only (pi consumes `settings.json` itself; the extension never
reads it), composed inside `_converge_settings`
(`perk/convergence/init/settings.py::_converge_tui_mode`) so it rides the `settings-wiring`
`ManagedConvergence`. **Excluded** from the desired/observed managed-state settings portions: a
seeded default is user-ownable after the seed — including it would misclassify an opt-out as
`locally-modified`. The opt-out is committing any `tuiMode` value (e.g. `"regular"`), which
survives init/doctor; a user-global `/settings` change does **not** durably override the project
key (pi merges project settings over global).

> **Interactive save discipline (as of Node 2.5 the present + `/plan-save` flow is
> FALLBACK-ONLY on every interactive path — perk-plan included):** the prior
> `PLAN_AUTHORING_CONTEXT` ending ("disable plan mode (/plan off), then call the plan_save
> tool") was structurally broken — `/plan` is a user command the model cannot run, and the
> `plan_save` tool is excluded from `READ_ONLY_TOOLS` (hidden while the gate is on). The
> review-first discipline — keep the working draft current with `plan_draft`, call
> `plan_review` when decision-complete, and an approval **auto-saves** via `approvalSave` — is
> stated per §8.57's one-canonical-carrier map: the plan stage's mode context
> (`PLAN_AUTHORING_CONTEXT`) carries it for the plan-stage shapes, the objective/gist
> authoring **seeds** carry it per launch shape (`OBJECTIVE_AUTHORING_CONTEXT` is live state +
> pointers only), the objective-plan factory guidance carries it on both planes (warm
> `factoryGuidance` / cold `_seed_prompt`), adapter blocks carry only their provider's surface
> delta (`PLAN_ADAPTER_PLANNOTATOR_CONTEXT` no longer restates the flow), and the stage skills
> are the read-on-demand detail tier pointing back at it. Only when `plan_review` reports **skipped or unavailable**
> (headless, dismissed, no surface) does the model **present the complete plan as its final
> message and never attempt to save**; the **human** runs `/plan-save` (its
> `extractPlanMarkdown` scrape is reliable by construction — the final message is the clean
> plan; as of Node 2.2 `/plan-save` prefers the validated plan-draft artifact when one exists,
> and the scrape is the demoted universal fallback). `PLAN_ADAPTER_TOMBELL_CONTEXT` also speaks
> review-first — as §8.57's REPLACE-posture designated flow carrier (perk's mode context is
> never injected under that selection); the present + `/plan-save` (artifact-preferred,
> scrape-fallback) flow remains its
> explicit **fail-open** arm — including when `@tombell/pi-plan`'s own interactive `/plan`
> `setActiveTools` restriction hides `plan_draft`/`plan_review` from the tool set.
> `savePlan()` / the `plan_save` tool / `/plan-save` are **untouched**. No orchestrated
> **factory flow** instructs an autonomous `plan_save` tool call any longer:
> **objective-plan** is review-first as of #352 Node 3.1 — the
> approval-driven save recovers the node link from the `objective_node_claim` carrier, with
> `plan_save`-with-both-ids demoted to the manual failsafe. The **learn factories**
> (learn-docs/learn-code) are review-first too (their seeds + skills speak it): in the gated
> read-only cold sessions the approval-driven save recovers `consumed_learn` from the cold
> handoff carrier (→ §8.2), and `plan_save`-with-`consumed_learn` applies only where the tool
> is active (warm read-write sessions — which write no handoff, so the explicit param is
> load-bearing there). **replan** and **plan-from** are review-first too — their gated
> read-only sessions land the save via `plan_review` approval (replan's approval-save updates
> the existing plan in place via the `run_id` upsert — the original `run_id` rides the
> session; plan-from's `adopt_from` link rides the handoff carrier), with `/plan-save` the
> manual failsafe.

## §8.11 · The headless stage-drive worker contract (Node 1.2)

The **stage-drive primitive** (`extension/worker/worker.ts` `driveStage`) drives ONE read-write stage
(`implement`/`address`) end-to-end on an **already-prepared** worktree, in-process via the SDK
runtime factory, running the **same** `@mgiles/perk` extension package. It is the substrate Node 1.3
(the structured event stream) and Node 4.1 (the e2e harness) consume. This section locks the
worker's inputs, determinism invariants, terminal-signal definition, and outcome shape (the full
audit is `docs/design/headless-worker.md`, Node 1.1). The worker makes **no GitHub mutation of its
own** — the stage's own tools (`submit`, `finalize_address`) delegate to the Python gateway
exactly as in a warm session (§8.4/§8.52).

### Inputs (the prepared-worktree contract)

| input | shape | source |
|---|---|---|
| `worktree` | absolute path, already positioned | the cold-door/runner positioning (`perk/run/launch/__init__.py`), **not** the worker (Gap 7) |
| `stage` | `"implement" \| "address"` | the only `doors.cold_remote: true` read-write stages (`shared/registry.yaml`) |
| `run_id` | ULID, present as `PERK_RUN_ID` in env | minted by positioning; the worker **inherits** it and never re-mints |
| handoff / plan-ref / plan-body | files under `<worktree>/.perk/workflow/` | materialized by positioning; the worker does not re-write them |
| `initialPrompt` | string | re-derived by `initialPromptFor(stage, planRef)` — the TS twin of `perk/run/launch/prompts.py._implement_prompt`/`_address_prompt` (parity asserted reciprocally in `extension/worker/worker.test.ts` + `tests/test_worker_prompt_parity.py`); the prompt carries **no skill-binding suffix** — the worker's bindings arrive via §8.9 Mechanism A (the extension's `before_agent_start` injection, which fires because the handoff records the stage and no branch entry carries `BINDING_HEADER`); the injected content is byte-identical to the cold door's prompt suffix (`tests/test_binding_render_parity.py`; the named mechanism difference is §8.38 row 2) |
| `model` + `auth` | `Model` + `AuthStorage`/`ModelRegistry` | explicit worker input, else env-var key resolution (`ANTHROPIC_API_KEY` etc., Gap 5); **no model ⇒ a fail-soft `failed`/`no_model` outcome, never a throw**. The workerMain shim resolves an explicit `--model` flag through pi's `resolveCliModel` (CLI parity: fuzzy matching, `provider/pattern`, a `:thinking` suffix — `resolveWorkerModel`); a parsed thinking level rides the additive `DriveStageOptions.thinkingLevel` input, applied at session creation (absent ⇒ the settings default) |
| `budget` | `{ maxTurns, maxTokens, wallClockMs }` | worker input; the watchdog that drives abort (Gap 2) |
| `signal` | `AbortSignal` | external cancellation; OR'd with the budget watchdog |

### Determinism invariants (fixed by the worker; not caller-tunable)

- **`cwd = worktree`, `agentDir = throwaway temp dir`** (Gap 4): the project tier **actually
  resolves** the managed `.pi/settings.json` `packages` list — perk's `@mgiles/perk` **plus** the
  borrowed packages (`npm:pi-subagents` etc.), the same package set as a warm session — alongside
  the managed `AGENTS.md`/`APPEND_SYSTEM.md`. Missing `npm:` packages **auto-install** into the
  project-scope root `.pi/npm` at session construction (an install failure throws → a loud
  `failed`/`drive_error` outcome; installs are skipped under `PI_OFFLINE`) — §8.14's composite
  worker-deps step pre-installs the pinned `@mgiles/perk` there for consumers. The user-global tier
  (extensions/settings/skills/models/auth) stays locked out via the throwaway `agentDir` (its
  `settings.json` does not exist ⇒ an empty global tier). The `createAgentSessionServices` factory
  builds the `DefaultResourceLoader` internally from `cwd`/`agentDir` — the runtime path does
  **not** take a pre-built loader (recipe correction #1).
- **Compaction-off + retry-off** via disk-layered settings — `SettingsManager.create(worktree,
  throwawayAgentDir)` + `applyOverrides({ compaction:{enabled:false}, retry:{enabled:false} })`
  (Gap 3; the SDK's sanctioned "with overrides" shape). The overrides ride the **merged** settings
  view only (what the compaction/retry getters read); package resolution reads the per-scope raws,
  so the overrides cannot leak into it. **AND** the **no-active-objective invariant**: positioning
  never writes an `active_objective`, so `objective.ts`'s `turn_end` `ctx.compact` is inert.
  Together these kill both SDK auto-compaction and perk's threshold compaction. The worker must
  **never** call `/objective`/`objective_save` in the driven session.
- **`ctx.hasUI === false`** (Gap 6): the session binds with `{ uiContext: undefined, mode: "json" }`,
  so every perk UI surface takes its headless `console.error` fallback.
- **Rebind defensiveness** (Gap 1): the worker is built on `createAgentSessionRuntime` (the
  services/from-services factory), and a `bindAndSubscribe`/`rebind` helper re-binds the extension
  and re-attaches the terminal/budget listener after any runtime replacement — but `bindExtensions`
  is **still called explicitly** at startup (the factory only *loads* extensions; binding emits
  `session_start` and runs perk's claim path). A mid-drive replacement is **not expected** on the
  happy path (the prompt instructs `/submit`, never `/implement`; `lifecycleGates.newSession` is
  `hasUI`-guarded; objective compaction is inert) — so an observed replacement is a **loud
  structured-log error** before the listener is kept alive.

### Terminal-signal definition

The drive terminates on the **first** of:

1. **Terminating-tool success** (the primary signal), observed via the `tool_execution_end`
   `result.details` captured by the subscribe listener: for `implement`, a successful `submit`
   carrying a `pr` **AND `mergeable !== false`** (#556 — a definitively-unmergeable PR with
   unresolved merge conflicts is NOT complete; `mergeable: true`/`null`/absent all allow completion,
   fail-open) → `completed`/`submit_tool`; for `address`, `finalize_address` ok **and**
   `perk:workflow-state.last_review_batch` appended **and** the latest submit-bearing evidence is
   successful with `mergeable !== false` → `completed`/`address_resolved`. The finalizer carries its nested submit
   facts; a later standalone clean `submit` from the conflict-resolver re-drive supersedes them,
   so natural-idle passes only after a definitively-unmergeable publication is repaired.
2. **Driving `prompt()` resolved (agent idle), verified against the success predicate.** Idle is
   **not** itself success — if the predicate does not hold, → `failed`/`agent_idle_incomplete`.
3. **Budget / timeout / external abort** → `session.abort()` (hard; propagates into the in-flight
   `ctx.signal`-aware shelled tools `submit`/`finalize_address`/`run_ci`): the watchdog →
   `budget_exhausted`/`budget`; the external `signal` → `aborted`/`external_abort`.
4. **Post-acceptance model error** (with retry off, an assistant `message_end` with
   `stopReason:"error"`) → `failed`/`model_error`.

**The terminating-tool preflight.** Immediately post-bind (before the driving `prompt()`), the
stage's terminating perk tool must be registered — `implement` → `submit`, `address` →
`finalize_address` — else the drive fails fast with a **zero-turn** `failed` outcome carrying
`error.type "no_extension_tools"` under the existing `model_error` terminal signal (the `no_model`
precedent: preflight failures reuse `model_error` + a distinct `error.type`; no new `TerminalSignal`
vocabulary). This closes disk discovery's silent-zero arm (a missing/unparseable `.pi/settings.json`
or an unresolvable local-path package yields zero tools without throwing) — the cause is on the
worker's stderr (drained settings errors + extension load errors), and the event stream stays a
well-formed `run_started`→`run_finished` pair. The check is presence-gated on the session's
`extensionRunner` and deliberately does **not** require the `subagent` tool for `address` (the live
subagent-under-worker smoke stays the carried risk below).

### Outcome shape (frozen; **additive-stable** — 1.3 may add fields, existing fields keep meaning)

```jsonc
{
  "run_id": "<ULID>",
  "stage": "implement" | "address",
  "status": "completed" | "failed" | "aborted" | "budget_exhausted",
  "terminal_signal": "submit_tool" | "address_resolved" | "agent_idle_incomplete"
                    | "budget" | "external_abort" | "model_error",
  "pr": { "number": 0, "url": "" } | null,   // populated on a completed implement; from SubmitDetails.pr
  "budget": { "turns": 0, "tokens": 0, "elapsed_ms": 0 },
  "error": { "type": "string", "message": "string", "summary": "string" } | null
}
```

`budget.tokens` counts **fresh work only** — assistant `input + output` per `turn_end`; cache
reads/writes and provider `reasoning` breakdowns (subsets of `output` in pi-ai's normalization)
are deliberately excluded from the sum.
`error.summary` is a short, model-free synthesis capped via the `route-don't-relay`/double-delivery
discipline (`capForModel`); the PR is extracted **directly from the captured terminal tool event**,
not a new Python `find-pr-for-branch` JSON command. Node 1.3 surfaces this outcome as the run-event
stream's terminal `run_finished` event (§8.12) — the same frozen object, carried in the structured
channel.

> **Open dependency (carried risk).** The `address` drive's seeded prompt instructs the model to
> classify via ONE call to the flow-scoped **`classify_review_feedback`** tool, which runs the
> `perk.review-classifier` child through the report-wave module (§8.35) over the pi-subagents v1
> extension RPC — the report schema is a module constant (`REVIEW_CLASSIFIER_REPORT_SCHEMA`, the
> engine-validated workflow `outputSchema`), and the tool reads the configured
> `[models.subagents] review-classifier` model at execute time (the worktree's committed
> `.perk/config.toml`, with the gitignored `.perk/local.toml` overlay anchored to the MAIN
> checkout — a per-user override survives the cold worktree launch; nothing schema- or
> model-shaped is prompt-transcribed). `pi-subagents` still loads in the
> worker from the managed settings `packages` list (Gap 4 above) — the tool's RPC adapter rides
> it. The **subagent-under-worker live smoke** stays an open dependency **deferred to the Phase-3
> `doctor workflow`**: the fake-RPC e2e validates perk's adapter, not the real pi-subagents
> workflow host under the headless worker, and the migration makes `classify_review_feedback`
> mandatory before a worker `/address` can reach `finalize_address`; Node 1.2 does not prove it.

## §8.12 · The structured run-event stream (Node 1.3)

The headless stage-drive worker (§8.11) emits a **structured run-event stream** while it drives one
`implement`/`address` stage to terminal. The stream is the *substrate* Node 2.3 (GitHub
progress/terminal reporting) and Node 4.1 (the e2e worker harness) consume: it carries full ordered
run detail in a **structured channel**, while the surfaced `RunOutcome` (§8.11) stays bounded — the
`route-don't-relay`/double-delivery discipline. This node is **purely additive** to §8.11: the
`RunOutcome` shape is unchanged, and every surface is opt-in/fail-soft.

### The `RunEvent` union (additive-stable; keyed on `kind`)

A small, JSON-serializable, **additive-stable** discriminated union. Every event carries a monotonic
`seq` (0-based, +1 per emit) and `t` (elapsed ms from the drive's injected clock — the SAME basis as
`RunOutcome.budget.elapsed_ms`). Future nodes may add variants/fields; existing ones keep meaning.

```jsonc
{ "kind": "run_started",  "seq": 0, "t": 0, "run_id": "<ULID>", "stage": "implement" | "address" }
{ "kind": "step_marker",  "seq": 1, "t": 0, "marker": "wip" | "done", "step": 1 } // deprecated — never emitted; historical files may carry it
{ "kind": "tool_outcome", "seq": 2, "t": 0, "tool": "submit", "ok": true, "summary": null }
{ "kind": "run_finished", "seq": 3, "t": 0, "outcome": { /* the frozen §8.11 RunOutcome */ } }
```

- **`run_started`** — emitted once at drive start (after a successful bind, before `session.prompt`).
- **`step_marker`** — **deprecated / never emitted**: the `[WIP:n]`/`[DONE:n]` marker protocol was
  removed with checkpoints, so nothing writes markers and the worker no longer scans for them. The
  variant stays in the grammar (additive-stable; historical `events.ndjson` files may carry it).
  **Accepted loss:** headless runs have no granular per-step progress signal — the in-session todo
  checklist is `hasUI`-gated and perk adds **no foreign-payload coupling** (no scraping of the
  borrowed todo tool's payloads) to synthesize one.
- **`tool_outcome`** — one per `tool_execution_end`. `ok` = `details.ok === true` when the result
  carries a `details.ok` boolean, else `!isError`. `summary` is `null` on success and, on failure, a
  **capped** synthesis (`capForModel(message, EVENT_SUMMARY_CAP=2KiB).shown`) — never the raw result.
- **`run_finished`** — emitted **exactly once** at every terminal exit (natural-idle/verdict,
  budget/abort, drive-error catch, AND the `no_model` early return), carrying the full frozen
  `RunOutcome` (terminal status + `error.summary` = the terminal failure summary). The stream's
  "terminal status" event. A zero-turn run still emits a `run_started` + `run_finished` pair.

### Dual delivery (the injectable sink seam)

`RunEventSink = (event: RunEvent) => void`, injectable via `DriveStageDeps.eventSink`. This satisfies
both consumers: Node 4.1 asserts events in-process via an injected array sink; Node 2.3 reads the
durable file out-of-process.

- **Default sink** (when `eventSink` is absent) = a run-scoped NDJSON **file** sink built from
  `opts.worktree` + the resolved `run_id` (`env.PERK_RUN_ID`, the same source `assembleOutcome`
  uses). It appends one JSON object + `\n` per event to `runEventsPath(cwd, runId)` =
  `<cwd>/.perk/workflow/scratch/runs/<runId>/events.ndjson` — a **cache-tier** artifact (the
  `.perk/workflow/scratch/` tree is gitignored), co-located with the run's read-only-child scratch.
- **No-op when `run_id` is empty** — keeps the offline drive tests (which set no `PERK_RUN_ID`)
  write-free; `workerMain` always has `PERK_RUN_ID`, so a real run always writes the file.
- **Fail-soft** — each append (and the emitter's `sink(...)` call) is try/caught and swallowed with a
  structured-log line; a broken/throwing sink never aborts or fails the drive.

### Cap (route-don't-relay)

The structured channel carries the *narrative* (which tools ran + ok/fail, terminal
outcome), **not** raw tool payloads (those already live in the session transcript). Per-event free
text is capped at `EVENT_SUMMARY_CAP = 2 KiB`. The surfaced `RunOutcome` is unchanged and already
bounded. The worker only *writes* the structured channel — **no GitHub mutation** here; surfacing it
as PR comments/checks from the runner is Node 2.3 (Phase 2).

---

## §8.13 · Remote dispatch: the `Runner` contract + the dispatch record (Node 2.1)

A `--remote` launch of a drivable stage (`implement`/`address`, the `doors.cold_remote:true`
stages) is a **real drive** (it was `remote_not_driven` through P2.T8c). The Python plane mints a
perk `run_id`, **persists the `run_id → plan` linkage**, reads it back to verify, then **triggers**
a runner that is discovered + matched back to the `run_id`. This node builds the dispatch driver
(`perk/run/launch/remote.py` `_drive_remote_target`) + the runner library (`perk/run/runner.py`); the GitHub
Actions workflow YAML it triggers is **Node 2.2** (named below, built there).

### The `Runner` contract (`perk/run/runner.py`)

A runner-agnostic `typing.Protocol`. GitHub Actions is the first (and currently only)
implementation; `select_runner(ref)` returns a `GitHubActionsRunner(ref)` for any ref today (the
"keep future runners open" seam — the ref is recorded but not yet mapped to a runner *kind*).

```python
class Runner(Protocol):
    kind: str
    def dispatch(self, *, stage, plan_ref, run_id, base, repo_root) -> RunHandle: ...
    def observe(self, handle: RunHandle, *, repo_root) -> RunObservation: ...
    def cancel(self, handle: RunHandle, *, repo_root) -> None: ...
    def retry(self, handle: RunHandle, *, failed_only, repo_root) -> None: ...
    def discover(self, *, repo_root, limit) -> list[DiscoveredRun]: ...
```

- **`dispatch`** triggers the run and returns the **verified** handle (verified = the runner-side
  run was discovered and matched to `run_id`); it raises `RunnerError` on a trigger/discovery
  failure.
- **`observe`/`cancel`/`retry`** operate on a previously-returned `RunHandle`. They are implemented (not
  stubbed) so the contract is validated end-to-end and the supervisor nodes (3.1/3.2) consume
  settled shapes — but the **supervisor command surfaces** (`perk workflow run list/cancel/retry`,
  tables, correlation) are those later nodes' work, not this one (`list` is §8.17;
  `cancel`/`retry` are §8.18). `retry` re-runs the existing run (same `run_ref`); `failed_only`
  re-runs only the failed jobs. `GitHubActionsRunner.retry` shells `github.rerun_workflow_run`
  (`gh run rerun [--failed]`), wrapping `github.GitHubError` as `RunnerError` exactly as `cancel`.
- **`discover`** enumerates the runner's perk runs from the **canonical remote source**,
  newest-first — each runner owns its run-name/token convention. `GitHubActionsRunner.discover`
  calls `github.list_workflow_runs(workflow="perk-run.yml", limit=…)` (a single REST page, at
  most 100 runs), parses each listing's rendered run-name via `parse_run_name`, **skips**
  unparseable titles and `stage == SMOKE_STAGE` (`"smoke"` — its canonical home is `runner.py`),
  and reconstructs a `RunHandle` per run (`run_ref` = the GHA numeric id, `runner` = the routed
  ref, `kind = "github-actions"`). Wraps `GitHubError` as `RunnerError` like the other ops. The
  thin orchestration seam above it is `perk/run/discovery.py` (`discover_runs` /
  `find_discovered_run`) — a sibling module because `cache` imports `runner`.

The value types: `RunHandle` is a frozen `@dataclass` whose JSON boundary is `RunHandleModel`
(`LenientParseModel`), JSON-stable via `model_dump(mode="json")`/`model_validate` on that boundary
model; `RunObservation` stays a frozen dataclass; the dispatch record's domain object is `Dispatch`
with `DispatchModel` (`LenientParseModel`) as the on-disk read boundary (below):

- **`RunHandle`** — `runner` (the routed ref, `""` ⇒ default), `kind` (`"github-actions"`),
  `run_ref` (the runner-native run id — GitHub Actions' numeric id as a string), `url`. Stored
  inside the dispatch record. **Do not conflate** `run_ref` with the perk `run_id`: the perk
  `run_id` is the canonical, runner-agnostic correlation key; `run_ref` is the runner-side handle.
- **`RunObservation`** — `status` (`"queued"|"in_progress"|"completed"|"unknown"`), `conclusion`
  (`"success"|"failure"|"cancelled"|…|None`), `url`.
- **`ParsedRunName`** — `(stage, plan_id, run_id)`, the three fields the managed run-name embeds;
  `parse_run_name(title)` recovers them (`None` for a non-matching title or a non-ULID token).
- **`DiscoveredRun`** — `run_id`, `stage`, `plan_id` (the parsed run-name fields),
  `dispatched_at` (the run's `created_at` — the discovery-side dispatch time), `status`,
  `conclusion`, `handle` (a reconstructed `RunHandle`).
- **`Dispatch`** — the durable linkage (below); its nested `plan_ref` (the unified `plan.PlanRef`,
  boundary `PlanRefModel`) and `run_handle` (a `RunHandle`, boundary `RunHandleModel`) are validated
  at the on-disk read boundary via `DispatchModel`.

### The run-name: the canonical remote-run existence record

The managed workflow renders `run-name: "perk {stage} · plan #{plan} · {run_id}"` — the run title
carries the stage, the plan id, and the perk `run_id` (a ULID). That rendered title, enumerable
via the GHA run listing, **is the canonical record that a remote run exists**: any machine can
reconstruct `run_id`/`stage`/`plan_id` + a `RunHandle` from it with zero local state. The
workflow template (`workflow_artifacts.PERK_RUN_WORKFLOW`) and `parse_run_name` are **pinned to
each other** (a template↔parser lockstep test renders the template and asserts the parser
recovers the inputs) — a run-name change must ripple both.

### The dispatch record (the local cache/correlation accelerator)

The `Dispatch` record is persisted at **`.perk/workflow/scratch/runs/<run_id>/dispatch.json`** (the run's
scratch dir — `perk init` already creates `scratch/runs/` and `.gitignore` already excludes
`/.perk/workflow/scratch/`, so no layout/gitignore change). It is a **cache**: for a successfully
triggered run it accelerates/enriches what discovery can reconstruct (precise `dispatched_at`,
the plan `url` + `objective_id` correlation, the routed `runner` ref) — and it is the **only
durable trace of failed/never-triggered dispatches** (a run that never started has no run-name to
discover). Shape:

```jsonc
{ "run_id": "<ULID>",            // perk's canonical correlation key (authoritative on write)
  "stage": "implement",
  "plan_ref": { /* the cache.plan-ref blob */ },
  "runner": "",                  // the routed runner ref ("" => default)
  "kind": "github-actions",
  "status": "dispatching" | "dispatched" | "failed",
  "dispatched_at": "<ISO-8601 UTC>",
  "run_handle": { /* RunHandle model_dump */ } | null,
  "error": "<string>" | null }
```

The supervisor read surface (`perk workflow run list`, §8.17) merges the canonical discovery with
these records (the record enriches a discovered run; a discovered run needs no record). A
**failed** record is kept
(not deleted) for that visibility — until the §8.1 age rule reclaims it. GC of dispatch records
rides the existing `.perk/workflow/` GC story (§8.1): records live *inside* `scratch/runs/<run_id>/`
and so are pruned wholesale with the run dir by `perk state prune` / the `cache-gc` check.

### Persist-then-trigger + read-back-verify (the establish-before-consume gate)

`_drive_remote_target` ordering (the establish-before-consume discipline, cross-referencing §8.2):

1. Resolve the plan from `cache.plan-ref`; **no plan ⇒** `UserFacingCliError(no_plan_ref)` (a
   remote drive must not invent a plan).
2. Mint `run_id` (a cold dispatch is a cold launch ⇒ mints).
3. Resolve `base` = the default branch (best-effort; loud fallback to `"main"` on failure — never
   silent).
4. **`--dry-run` ⇒ a side-effect-free dispatch preview** (`success:true`, `dry_run:true`, an
   `inputs` preview; **no** persist, **no** trigger) — mirroring the local dry-run.
5. **Persist** the `cache.DispatchCache` record (`status:"dispatching"`) via `cache.write_dispatch`, then
   **read it back** and assert `run_id` + `plan_ref.pr_id` round-tripped; a mismatch raises a
   **hard** `UserFacingCliError(dispatch_state_unverified)` (never a silent `pass`).
6. **Trigger** via the selected runner's `dispatch`. On `RunnerError`/`GitHubError`: rewrite the
   record `status:"failed"` + `error`, then raise `UserFacingCliError(dispatch_failed)`.
7. **Finalize** the record `status:"dispatched"` + `run_handle` (read-back is best-effort here —
   the critical verified linkage is step 5's). Surface a human line + a `--json`
   `{success, stage, run_id, runner, run_handle}` payload. Exit 0.

The **error types**: `remote_not_driven` is **retired**; the new types are `no_plan_ref`,
`dispatch_state_unverified`, `dispatch_failed`.

### The `workflow_dispatch` input contract (the Node 2.2 dependency)

`GitHubActionsRunner.dispatch` triggers a `workflow_dispatch` and then **verifies** the run by
polling `repos/{owner}/{repo}/actions/workflows/<workflow>/runs` and matching the run whose
`display_title`/`name` **contains the perk `run_id`** (exponential backoff `min(2**attempt, 8)`,
`max_attempts=11`; a matched `skipped`/`cancelled` run or exhaustion ⇒ `GitHubError`). So Node 2.2
**must** ship:

- a workflow file named **`perk-run.yml`** (`runner.GITHUB_ACTIONS_WORKFLOW`);
- typed `workflow_dispatch` inputs **`run_id`, `stage`, `plan`, `base`**;
- a `run-name` that **embeds `${{ inputs.run_id }}`** so the dispatcher can verify-by-discovery
  (the perk `run_id` unifies erk's separate `distinct_id`);
- a per-plan `concurrency` group is recommended (mirroring erk's `implement-plan-${{ … }}`).

Until 2.2 lands, a real `--remote` dispatch surfaces a clean `gh`-sourced "workflow not found"
`dispatch_failed` (an honest failure, not a crash). The CI-side positioning (the worktree/handoff
the worker consumes) is also Node 2.2's workflow; this node positions **nothing** locally.

## §8.14 · The GitHub Actions runner artifact + the CI worker entrypoint (Node 2.2)

The runner side of §8.13's cold remote door: the **managed** GitHub Actions workflow the dispatcher
triggers, plus the `perk run-worker` positioning entrypoint that workflow invokes. Both are built in
this node; §8.13's "until 2.2 lands" caveat is reconciled by it.

### The managed artifact (`perk/run/workflow_artifacts.py`)

Two perk-owned files, **managed by `perk init` and repaired by `perk doctor --fix`** (a
`ManagedConvergence` in `init.managed_convergences()`, covering the `runner-workflow` capability —
so `init` writes them and `doctor` verifies/repairs them through the one shared SSOT):

- **`.github/workflows/perk-run.yml`** — the runner workflow. It honors §8.13's `workflow_dispatch`
  input contract: a `run-name` embedding **`${{ inputs.run_id }}`** (verify-by-discovery); typed
  inputs **`run_id`, `stage`, `plan`, `base`** (`base` is `required: true` with no default — the
  dispatcher always sends it); a per-plan `concurrency` group `perk-run-${{ inputs.plan }}`. An
  additive **`smoke`** input (`required: false`, `default: "false"`, `type: string`) drives the
  doctor smoke short-circuit (§8.19): when `smoke == 'true'` the `drive` job runs only `Validate
  required secrets` + a `Smoke check` echo step and exits **success** — every subsequent step
  (`actions/checkout`, the composite setup `uses:`, `Drive the stage
  headlessly`) carries `if: inputs.smoke != 'true'`, so a smoke run does no checkout, no setup,
  no worker drive, and spends no model budget. Real dispatches omit `smoke` and inherit the
  `"false"` default (backward-compatible). The
  `drive` job validates required secrets — it fails fast when `PERK_GH_PAT` is missing **and** when
  **both** `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` are empty (pre-empting the worker's late
  `no_model`) — checks out the repository, runs the composite setup, then `perk run-worker`.
  **The workflow no longer positions the plan branch in shell**: the former "Check out the
  plan branch" step relocated into `perk run-worker` (`position_branch`, §8.46) — one
  pytest-testable implementation positions incremental (behavior-equivalent fetch-or-create:
  hard-reset to the remote tip when `origin/plan-<plan>` exists, else create from
  `origin/<base>`) and stacked plans alike. The `Drive the stage headlessly` step runs
  **`gh auth setup-git`** before invoking
  `perk run-worker` — it installs `gh` as git's https credential helper using the step's
  `GH_TOKEN` (= `PERK_GH_PAT`), so the skills CLI's sync during positioning (step 4 below) can
  clone private skill sources. A final **`Upload run diagnostics`** step (`actions/upload-artifact@v4`) uploads
  `.perk/workflow/scratch/runs/<run_id>/` — the §8.12 durable run-event stream (`events.ndjson`
  and friends), which is otherwise written into the runner's checkout and lost at teardown — as
  artifact `perk-run-<run_id>` for **every real run, pass or fail**
  (`if: always() && inputs.smoke != 'true'`, `if-no-files-found: ignore`; smoke runs write nothing
  and upload nothing). An opt-out repo variable `PERK_ENABLED=false` disables the job without
  removing the file. **Auth model:** checkout + push use the `PERK_GH_PAT` PAT, **not** `github.token` — a
  PAT-pushed commit triggers downstream CI (the implement drive commits + `submit` pushes);
  `GITHUB_TOKEN`-pushed commits do not. This is a stated decision Node 2.4 inherited (the
  `runner-workflow-permissions` check is advisory `info` because of this PAT-push model — §8.16).
- **`.github/actions/perk-remote-setup/action.yml`** — the composite setup action: the two pinned
  toolchains (uv + Node 22), then perk (the exterior CLI — `--from . perk` for the self-repo,
  an exact-version-pinned PyPI install `uv tool install perk=={__version__}` for a consumer,
  baked in at `perk init` time so the runner reproduces the wiring perk version), pi (the interior the
  worker drives), the **skills CLI** (`go install github.com/mattgiles/skills/cmd/skills@latest`
  — built from source because its release binaries are darwin-only; the runner's preinstalled Go +
  `GOTOOLCHAIN=auto` suffice, and the step is **fatal**: a failed install fails the job — no
  skills, no drive), the Node worker's peer deps, and a final **git-identity** step (`perk[bot]`,
  `--global`) so the worker's commits succeed on a fresh runner. The worker-deps step is repo-kind
  aware: **self** uses `npm ci` (the self-repo has the `package.json`/lockfile/devDeps the worker
  resolves); **consumer** installs the pinned `@mgiles/perk` **plus the unpinned pi SDK**
  (`npm install @mgiles/perk@{__version__} @earendil-works/pi-coding-agent --prefix .pi/npm
  --legacy-peer-deps`, the perk pin baked in at `perk init` time so the runner reproduces the wiring
  perk version). `@mgiles/perk` ships **zero** runtime `dependencies` (the pi packages are peers) and
  `--legacy-peer-deps` makes npm skip peer installation entirely — the SDK spec is what lands the
  worker's imports: its real deps (pi-ai, pi-tui, typebox) close the worker graph's bare-import set
  under `.pi/npm/node_modules/`, resolvable from the staged `consumer-npm` entry (step 5 below).

Full-file managed (like the settings/gitignore/AGENTS blocks): a hand-edited file reads as drift and
is converged back to the template. The templates are authored as code (string constants), not
packaged data, so there is no wheel-data surface to guard.

### `perk run-worker` (the CI positioning + drive entrypoint, `perk/run/run_worker.py`)

`perk run-worker --run-id --stage --plan [--base]` is the runner's positioning job (Gap 7), invoked
by the workflow on the plain repository checkout (cwd = the checkout = the worktree):

1. Resolve a remotely-drivable stage (a `doors.cold_remote: true` stage) from the registry; else
   `UserFacingCliError(stage_not_drivable)`.
2. Reconstruct the `cache.plan-ref` from the plan's GitHub state (`github.get_plan` +
   `resume.reconstruct_plan_ref`); a missing plan ⇒ `plan_not_found`.
3. **Position the plan branch** (`position_branch(repo_root, plan_ref, base)`, §8.46): an
   existing remote `plan-<N>` → checkout + hard-reset to the remote tip; absent + incremental
   → create from `origin/<base>`; absent + stacked → the readiness-gated parent-aware creation
   at the verified parent SHA.
4. **Position** the worktree (mirroring `launch.launch_stage`): `cache.ensure_layout`,
   `write_handoff({stage, mode})`, `write_plan_ref`, then materialize the plan body. Positioning
   also delivers `.agents/skills/` via the canonical `sync_skills` gesture (the same one
   `perk init` runs) against the checkout's **committed** manifests — the checkout has no
   `.agents/skills/` to mirror from (gitignored), so without the sync every stage skill-binding
   pointer would dangle. A delivery failure is **fatal** (`UserFacingCliError(skills_sync_failed)`)
   and pre-empts the worker spawn (and `report_started`) — the deliberate posture asymmetry vs the
   loud-but-non-fatal local worktree mirror (§8.38 named difference 2). The worker inherits the
   prepared worktree and never re-writes it (the §B inputs table).
5. Resolve the Node worker entrypoint — `PERK_WORKER_ENTRY` override (`env`), else the self-repo
   `extension/workerMain.ts` (`self`), else the consumer npm install under
   `.pi/npm/node_modules/@mgiles/perk/` (`consumer-npm`), which is **staged**: the whole package is
   copied (fresh per resolve) to `.pi/npm/perk-worker/` and the staged `extension/workerMain.ts`
   spawned — Node's type stripping refuses `.ts` files under any `node_modules` directory
   (`ERR_UNSUPPORTED_NODE_MODULES_TYPE_STRIPPING`), while the full-package copy keeps
   package-root-relative resources (`shared/`, `prompts/`, `package.json`) reachable and bare
   imports resolving by walking up to `.pi/npm/node_modules`. A miss ⇒ `worker_entry_missing`.
6. **Spawn** `node <entry> <stage> --worktree <repo_root>` with `PERK_RUN_ID=<run_id>` in the env
   (inherited stdio — the worker owns stdout/the `RunOutcome` JSON), and **exit with the worker's
   exit code** so the workflow step reflects the drive outcome.

`run-worker` is a deterministic exterior command (no agentic reasoning): it positions and drives;
model/auth resolution is the Node worker's job (env-var key resolution, Gap 5). `--base` is part of
the §8.13 input contract and is **consumed** by `position_branch`'s incremental fresh-branch arm
(§8.46). Reporting run progress/terminal status back into GitHub is
**Node 2.3**; the runner's secrets/health checks (the `PERK_GH_PAT`/model-credential prereqs) are
**Node 2.4** — the `perk doctor` `runner` check group (§8.16).

---

## §8.15 · Remote run reporting back into GitHub (Node 2.3)

The **runner-side** consumer of the §8.12 structured run-event stream + the §8.11 `RunOutcome`: when
`perk run-worker` drives a stage remotely, it makes that run **observable on GitHub**. The worker
itself never mutates GitHub (§8.12 is explicit — surfacing the stream is this node); the reporter is
a deterministic exterior task (no agentic reasoning) living in the Python plane (`perk/run/run_report.py`)
and wired into `perk run-worker` (`perk/run/run_worker.py`).

### The two reporting points (fail-soft, exit-code-neutral)

Two calls bracket the worker spawn in `run_worker(...)`:

- **started** — `report_started(...)` after the worker entry resolves and **before** `_spawn_worker`
  (the truest "drive is starting" point; positioning failures already raise loudly before this).
- **terminal** — `report_terminal(...)` after `_spawn_worker` returns the exit code and **before**
  `run-worker` returns it.

Both are **fail-soft for expected failures**: an `IssueBackendError` from the backend (plus a
filesystem `OSError` on the terminal path) inside reporting is caught, logged via `user_output` to
stderr, and swallowed — those never change the worker's exit code or crash the runner —
observability is best-effort (mirrors the worker's fail-soft event sink). A programming error in
reporting propagates.

### The surfaces

- **One marker-keyed plan-issue comment per `run_id`.** The target is the **plan issue** (the
  issue-canonical model — a perk plan *is* a GitHub issue; the implementation PR is referenced by
  URL when known). A single comment carrying the marker `<!-- perk:run-report:<run_id> -->` is
  **upserted** started → terminal (`github.upsert_marked_comment` →
  `find_comment_id_by_marker` PATCH-if-found, else POST), so the started note evolves into the
  terminal note (no two-comment spam; reruns are distinct `run_id`s). The plan issue is the only
  correlation anchor known at *started* time (for `implement` the PR does not exist until mid-drive).
- **The GitHub Actions job summary** (`$GITHUB_STEP_SUMMARY`) is the "checks"/run-page half: the
  terminal step appends a self-contained `## perk remote <stage>` summary (status + budget + the
  failure summary on non-success) when the env var is set (skipped silently when unset — local/test).

### Inputs the reporter derives

- The terminal `RunOutcome` is read from the **durable events file** out-of-process
  (`cache.read_scratch(repo_root, run_id, "events.ndjson")` → the last `run_finished` event's
  `outcome`), because `_spawn_worker` inherits stdio and does not capture the worker's stdout. A
  missing/empty/malformed events file ⇒ a clearly-labelled **degraded** terminal note derived from
  the worker exit code alone (so a terminal note always posts).
- The run URL is derived from standard GitHub Actions env
  (`GITHUB_SERVER_URL`/`GITHUB_REPOSITORY`/`GITHUB_RUN_ID` →
  `{server}/{repo}/actions/runs/{run_id}`); absent ⇒ notes post without the link.
- `outcome.pr` is present only for a successful `implement` drive (the worker captures the PR from
  `submit`); for `address`/failures it is `null`, and the report omits the PR line.

### Untrusted-data discipline (route-don't-relay end-to-end)

The reporter quotes **no** GitHub-sourced prose (no plan title, no fetched GitHub text is
interpolated into the bodies). The only free text it surfaces is the worker's own `error.summary`,
which is worker-generated and already capped at 2 KiB (§8.12) — never re-expanded. This preserves
route-don't-relay from the worker's structured channel all the way into the GitHub surfaces.

No change to `.github/workflows/perk-run.yml` or `perk/run/workflow_artifacts.py`: reporting hooks into
`run-worker` itself, so the managed artifact (and its convergence/doctor tests) stay untouched.

---

## §8.16 · Remote-runner prerequisites: credential + permission health-checks (Node 2.4)

The **pre-flight** twin of §8.14's execution-time `Validate required secrets` step: `perk doctor`'s
diagnostic side surfaces a mis-configured runner (missing checkout/push PAT, missing model
credential, restrictive workflow-permissions) **before** a `--remote` drive reaches CI, instead of
letting the CI job fail at its validate step. This is perk's analogue of erk's
`erk-queue-pat-secret` / `anthropic-api-secret` / `workflow-permissions` doctor checks, adapted to
Pi (multi-provider model keys) and perk's `{owner}/{repo}` gateway convention.

**Division of labor.** `init` *manages* the runner credentials by writing the managed workflow whose
`Validate required secrets` step is the execution-time gate (§8.14, Node 2.2); `doctor` *health-checks*
them ahead of time. perk init/doctor **never mutate** GitHub (Decision D2 — there is no
secret-setting command); each actionable finding instead carries an exact `gh` remediation string in
`Check.remediation` (e.g. `gh secret set PERK_GH_PAT`).

### The three verification-only gateway reads (`perk/github/workflows.py`)

All shell `gh` via `_run` with `cwd=repo_root` + gh's `{owner}/{repo}` placeholder auto-fill (no
remote-URL parsing); none mutate; a gh-missing/timeout raises `GitHubError`:

- `secret_exists(*, name, repo_root) -> bool | None` — `GET .../actions/secrets/{name}`: present →
  `True`, 404 → `False`, any other non-zero (e.g. 403) → `None` (unknown). Never reads the value.
- `get_workflow_permissions(*, repo_root) -> WorkflowPermissions | None` —
  `GET .../actions/permissions/workflow`; the frozen `WorkflowPermissions` carries
  `default_workflow_permissions: str` + `can_approve_pull_request_reviews: bool`. Non-zero → `None`;
  unparseable JSON → `GitHubError`.
- `get_repo_variable(*, name, repo_root) -> str | None` — `GET .../actions/variables/{name}`
  (`--jq .value`): value on returncode 0, `None` on 404/non-zero/empty. Used to read `PERK_ENABLED`.

### The report-only `runner` check group (`perk/convergence/doctor/github_checks.py::_runner_checks`)

A **report-only** check group (no `--fix` side — `_apply_fixes` is untouched), wired into
`_build_checks` **inside the `if verify:` block** after `_github_checks` (it shells `gh`), wrapped in
`try/except GitHubError` → a single `info` `runner-prereqs` degrade (no silent pass, never a crash).
**Non-fatal posture:** present → `ok`; actionable-absent → `warn`; unverifiable → `info`; **never
`fail`** — so a `warn` keeps exit 0 (`report.healthy` keys off `fail` only), matching §8.6's
GitHub-non-fatal rule. Order:

1. **Auth gate** — re-probe `check_auth()`; unauthed → a single `runner-prereqs` `info`, no further
   `gh` calls.
2. **`runner-enabled`** (always emitted) — reads `PERK_ENABLED` (`RUNNER_ENABLED_VAR`): `info`
   reporting unset→default-on / `=<value>` / `=false`→disabled.
3. **`PERK_ENABLED=false` → stop** (skip the three probes — don't nag about a deliberately-disabled
   runner). This is "check only what's enabled".
4. Otherwise the three probes (all group `"runner"`; names from `workflow_artifacts`):
   - **`runner-pat-secret`** ← `secret_exists(RUNNER_PAT_SECRET)`: `True`→`ok`; `False`→`warn`
     (remediation `gh secret set PERK_GH_PAT`); `None`→`info`.
   - **`runner-model-secret`** ← `secret_exists` for **both** `ANTHROPIC_API_KEY` and
     `OPENAI_API_KEY` (the workflow's "either" logic): either present→`ok`; both absent→`warn`;
     else→`info`.
   - **`runner-workflow-permissions`** ← `get_workflow_permissions`: **`info` in all non-error
     cases** (advisory — perk pushes with a PAT, not `github.token`, so it does not block the
     runner); `can_approve_pull_request_reviews` false carries the PUT remediation; `None`→`info`.

**Self-vs-consumer dual mode (D6).** The check *set* is identical for both repo kinds (the
`runner-workflow` capability is `scope="both"`); only the actionable-absent `detail` wording adapts —
self: "expected on perk's own repo (perk dogfoods `--remote` drives)"; consumer: "required only if
you use `perk … --remote` drives". No new capability is added (report-only), so the
`test_every_required_capability_has_a_doctor_check` coherence guard is unaffected.

**Human render.** `runner` is added to `doctor_cmd._GROUP_ORDER` (after `github`) — a group absent
from that tuple is invisible in human text (the `_GROUP_ORDER` trap); `--json` and the exit code
surface it regardless.

**Node 3.3 reuse.** `_runner_checks` is a free function (not inlined) and the three reads are the
**static** prereq layer that `perk doctor workflow` (Node 3.3) will compose with the
managed-artifact-present check and the live-spawn CI smoke. Node 2.4 adds checks to the **bare**
`perk doctor` run only; the `doctor workflow` subcommand is not built here.

## §8.17 · The supervisor read surface (`perk workflow run list`, Node 3.1)

The first command in the `perk workflow run` group: a deterministic, **read-only** supervisor
surface that enumerates runs from the **canonical GHA discovery** (§8.13's run-name record),
merged with the local dispatch-record cache, correlating each `run_id ↔ plan ↔ PR`. It mutates
nothing (no GitHub writes, no `.perk/workflow/` writes). `cancel`/`retry` (the `run` subgroup's
mutating siblings) **shipped** in Node 3.2 — see §8.18.

### Command surface (`perk/cli/commands/workflow_cmd.py`)

- `perk workflow run list` (aliases `perk workflow run ls`, `perk wf run list`). The `workflow`
  group (alias `wf`) holds the `run` subgroup so Node 3.2 extends the same subgroup.
- A dev/CI/supervisor surface (like `perk objective`/`perk state`), **not** an agent affordance.
- `--json` → a stable machine report on **stdout**; the human table → **stderr** (the cli-vs-pi
  §3.2 split). `--no-refresh` skips **all** GitHub reads (the cache-only view); `--limit N`
  (default 50) caps the newest-first list (applied **after** the merge).

### Source of truth + the merge

- **GitHub's run enumeration is the existence source.** When refreshing (the default), the command
  fetches `discovery.discover_runs(root, limit=limit)` **once** (one enumeration replaces the old
  per-record `observe` calls) and merges it with `cache.list_dispatch_records(root)` by `run_id`.
  The single-page bound applies: runs older than the newest `per_page` page surface via local
  records only. Each row carries a `source` field:
  - **`"both"`** — row fields from the local record (plan `url`, `objective_id` correlation, the
    precise `dispatched_at`, `error`); the `run` block from the `DiscoveredRun`
    (`run_ref`/`url`/`status`/`conclusion`) — no `observe` call.
  - **`"local"`** — failed/`dispatching` records or runs past the discovery page: the record row,
    with the per-record `observe` overlay when a handle exists (an error continuation line for
    failed records).
  - **`"discovered"`** — a run this clone never dispatched, reconstructed from the parsed
    run-name: `run_id`/`stage`/plan `pr_id` from the title; `runner: ""`,
    `kind: "github-actions"`, `dispatch_status: "dispatched"` (the run exists, so the dispatch
    evidently succeeded), `dispatched_at` = the run's `created_at`, `error: null`, plan
    `url: ""`.
  Merged rows sort **newest-first** by dispatch/created time (`datetime.fromisoformat`;
  unparseable sorts last).
- `cache.list_dispatch_records(root)` enumerates `scratch/runs/*/dispatch.json` (§8.13),
  newest-first by `dispatched_at`. A missing/unparseable/non-object record is skipped
  loud-but-non-fatal (stderr warning), never fatal — a corrupt record must not break the
  supervisor read; an absent `scratch/runs/` yields `[]`.
- **Plan block** comes from the record's `plan_ref` (`pr_id`, `url`) when one exists; a
  discovered-only row's `pr_id` is the parsed run-name plan id. Note `pr_id` is the **plan issue**
  id, not a PR number.
- **PR correlation** derives the PR through the resolved issue backend's
  `get_plan(issue_id=pr_id).pr` (memoized per `pr_id`), since the draft PR is separate from the
  plan issue — it works unchanged off a parsed plan id.

### Fail-soft overlay discipline

Every live read is **best-effort**: the command does **not** call `require_github`. A discovery
`RunnerError` degrades to an empty enumeration with a one-line stderr note — the local-cache view
(exactly the old behavior). Each per-record read on a `local` row is wrapped — a
`runner.RunnerError` degrades the `run` block to `null`; a `github.GitHubError` degrades the `pr`
block to `null` — with a one-line stderr note, never raising and never changing the exit code (this
is a read surface, not a gate). `--no-refresh` is the **cache-only** view: zero GitHub reads, local
records only (every row `source: "local"`, `pr`/`run` forced `null`).

### The `--json` payload (stdout, stable)

```jsonc
{ "success": true, "error_type": null, "refreshed": true, "count": 1,
  "runs": [
    { "run_id": "01J…", "stage": "implement", "runner": "", "kind": "github-actions",
      "dispatch_status": "dispatched", "dispatched_at": "<ISO-8601 UTC>", "error": null,
      "plan": { "pr_id": "42", "url": "https://…/issues/42" },
      "pr":   { "number": 51, "url": "https://…/pull/51", "state": "OPEN" } | null,
      "run":  { "run_ref": "1234567", "url": "https://…/actions/runs/1234567",
                "status": "completed", "conclusion": "success" } | null,
      "source": "local" | "discovered" | "both" } ] }
```

`refreshed = not no_refresh`; `pr`/`run` are `null` under `--no-refresh` or a failed/empty overlay.
The top-level shape is unchanged from the pre-discovery surface; `source` is the per-row addition.
`success` is always `true` for a successful enumeration (even zero runs); only `require_repo` failing
(`not_a_repo`) routes through `fail` (exit 2). No other error type is introduced.

### Human table (stderr)

Plain, manually-aligned, newest-first columns
`RUN_ID  STAGE  DISPATCH  RUN  CONCLUSION  PLAN  PR  AGE`. The full `run_id` (the supervisor copies
it into Node 3.2's `cancel`/`retry`) is never truncated; the overlay columns show `-` when not
refreshed/unresolved; `AGE` is a compact relative age from `dispatched_at`. Columns are unchanged
by the merge — a discovered-only row simply renders what it knows (plan column still `#<pr_id>`).
A `failed` record's
`error` is surfaced on an indented continuation line (the §8.13 "failed records kept for visibility"
rule). Empty state prints `No dispatched runs found`.

## §8.18 · The supervisor control surface (`perk workflow run cancel`/`retry`, Node 3.2)

The mutating control siblings of `list` (§8.17) in the same `perk workflow run` subgroup:
deterministic, **no agentic reasoning** dev/CI/supervisor commands (not agent affordances).

- `perk workflow run cancel <RUN_ID>` — cancel an in-flight (queued/in_progress) run.
- `perk workflow run retry <RUN_ID> [--failed]` — re-run a completed/failed run; `--failed` re-runs
  only the failed jobs.

Both take `--json` (stable machine report on **stdout**; human confirmation on **stderr**). The
group/subgroup aliases (`wf`, `run`) apply; the commands themselves carry no aliases.

### `<RUN_ID>` resolution (D1)

`<RUN_ID>` is the **perk `run_id`** — the never-truncated `RUN_ID` the supervisor copies from
`list` (§8.17). After `require_repo` + `require_github` (both commands *do* require auth — unlike
fail-soft `list`), the shared `resolve_target` helper resolves it via a **two-rung ladder** (the
local record is the cache accelerator; discovery is the canonical source — so **any machine** can
control a run it never dispatched):

1. `record = cache.read_dispatch(root, run_id)`; a record **with** a `run_handle` ⇒ use it +
   `select_runner(record.runner)`.
2. Otherwise (no record, **or** a handle-less record whose §8.13 finalize write-back never
   landed): `discovery.find_discovered_run(root, run_id)` — exact match on the parsed `run_id`
   token. Found ⇒ use the reconstructed `DiscoveredRun.handle`; route
   `select_runner(record.runner)` when a local record exists, else `select_runner(handle.runner)`
   (the default). A discovery `RunnerError` degrades fail-soft (one stderr note) into the miss
   arm below.
3. Both missed ⇒ `run_not_found` (exit 1) when there was **no local record** — the message names
   both misses (no local dispatch record, and not among the newest discovered `perk-run.yml`
   runs); `run_not_dispatched` (exit 1) when a handle-less local record exists and discovery
   found nothing (the dispatch really never triggered).

The resolved tuple's `record` slot is nullable (`Dispatch | None` — `None` for a discovered-only
run); `cancel`/`retry` act only on the handle. The error vocabulary is unchanged — no new type.

### No local mutation, no pre-gate (Corrections)

- **Retry reuses the SAME run** — `gh run rerun` re-runs the existing run (same `run_ref`,
  preserving the `run-name` that embeds the perk `run_id`), so the dispatch record and its
  `run_id ↔ plan ↔ PR` linkage stay valid. **No new ULID, no `cache.write_dispatch`.**
- **Neither command mutates the dispatch record.** The record's `status` is the *dispatch-attempt*
  lifecycle; live run state is observed via `Runner.observe` (surfaced by `list`'s overlay). No
  `.perk/workflow/` writes in this node.
- **No pre-flight run-state gating.** The commands do not `observe` to decide cancellability/
  retryability — they pass through to gh and surface gh's own error (e.g. "cannot cancel a
  completed run") as a clean `cancel_failed`/`retry_failed`.

### `--json` payload (stdout, stable)

```jsonc
// success (cancel)
{ "success": true, "error_type": null, "action": "cancel",
  "run_id": "01J…", "run_ref": "1234567", "runner": "", "kind": "github-actions",
  "url": "https://…/actions/runs/1234567" }
// success (retry) — adds: "failed_only": false
// failure → the shared fail shape:
{ "success": false, "error_type": "<type>", "message": "<gh's own error>" }
```

`run_ref`/`runner`/`kind`/`url` come from the reconstructed `RunHandle`. Error types + exits:
`not_a_repo` → 2; `github_unauthed`, `run_not_found`, `run_not_dispatched`, `cancel_failed`,
`retry_failed`, `invalid_input` → 1. The only free text in a failure payload is gh's own error
string (wrapped via `RunnerError`) — no model-authored interpretation.

---

## §8.19 · `perk doctor workflow` — static prereq checks + a live CI smoke (Node 3.3)

The workflow-focused diagnostic twin: a Click **subgroup** on the `doctor` group (the reserved
`invoked_subcommand` hook §8.6 left open). A dev/CI/supervisor surface, not an agent affordance. Bare
`perk doctor workflow` prints help; the two commands are `check` and `smoke-test [--wait]`. Both take
`-v/--verbose` + `--json` (stable machine report on **stdout**; grouped human render to **stderr**).

### `check` — the static layer (`doctor.workflow_checks`)

Composes the **same builders** as bare `perk doctor` (doctor's SSOT — no duplication): `_github_checks`
(GitHub readiness) ⊕ `_runner_checks` (the §8.16 remote-runner prereqs; a `GitHubError` degrades to a
single `info` `runner-prereqs`) — both under `verify=True` — ⊕ the **`runner-workflow`
managed-artifact-present** check (always): locate the `runner-workflow` `ManagedConvergence`, dry-run
it, and emit `ok` (converged) / `fail` (drift — detail = joined drift, remediation `perk doctor
--fix`; or unverifiable). Rendered grouped over `("github", "runner", "repository")`. Exit codes
mirror §8.6: **1** if any `fail`, else **0** (warns allowed); **2** only on not-a-repo.

### `smoke-test [--wait]` — the live proof (`perk/run/workflow_smoke.py`)

Proves the genuinely CI-only prerequisites a static check cannot: that the managed workflow is
**dispatchable**, the runner actually **starts a job**, and the secrets are **readable in the Actions
context** (environment-protection rules can hide an existing secret). It does **not** exercise the
composite setup or the worker/model drive — the `smoke=true` short-circuit keeps
it universal and ~0-cost. A future "full" smoke is out of scope.

Flow: `require_repo` + `require_github`; run `workflow_checks` (rendered like `check`). **Gate (refuse
→ exit 1):** if the `github-auth` check is not `ok` → `github_unauthed`; if
`get_repo_variable(PERK_ENABLED) == "false"` → `runner_disabled` (the job would be skipped and
verify-by-discovery would raise). PAT/model **warns do not block** — the live run is what verifies
them. Then `dispatch_smoke` triggers the managed workflow **directly** (`trigger_workflow` with
`stage=smoke`, `plan=smoke`, `smoke="true"`, ref/`base` = `default_branch` with a `"main"` fallback),
verifying by discovery on the minted `run_id`. It writes **no** dispatch record and creates **no**
GitHub artifacts (no branch/PR/issue), so `perk workflow run list` (§8.17) is unaffected — the
no-record half of that claim covers the local cache, and the discovery half rests on the
`stage == "smoke"` filter in `Runner.discover` (§8.13), which drops smoke runs from the canonical
enumeration — and the smoke
stays a pure doctor diagnostic. Without `--wait`: print the run URL, **exit 0**. With `--wait`:
`poll_smoke` loops to `completed` or `POLL_TIMEOUT_S` (600s, every `POLL_INTERVAL_S`=15s) —
`success` → exit 0; any other conclusion → exit 1; **timeout → `cancel_smoke` (best-effort
self-cancel) + exit 0** (inconclusive, not unhealthy).

### No `cleanup` command (deviation from erk)

erk's `doctor_workflow` ships `check`/`smoke-test`/`cleanup` because its smoke opens a one-shot PR.
perk's smoke creates nothing durable, so a `cleanup` would be fiction — only `check` + `smoke-test`
are built; `smoke-test --wait` self-cancels its own in-flight run on a poll timeout (the sole real
leftover).

### `--json` payloads (stdout, stable)

```jsonc
// check
{ "success": true, "healthy": true, "self_repo": false,
  "checks": [ { "name": "runner-workflow", "group": "repository", "status": "ok", … } ],
  "summary": { "passed": 1, "warnings": 0, "failed": 0 } }
// smoke-test (dispatch)
{ "success": true, "action": "smoke-test", "run_id": "01J…", "run_ref": "555",
  "url": "https://…/actions/runs/555", "waited": false, "conclusion": null, "timed_out": false }
// smoke-test (--wait) — "waited": true, "conclusion": "success"|…, "timed_out": bool
// refusal / dispatch error — the shared fail shape:
{ "success": false, "error_type": "<type>", "message": "<reason>" }
```

Error types + exits: `not_a_repo` → 2; `github_unauthed`, `runner_disabled`, `smoke_dispatch_failed`
→ 1.

## §8.20 · The capstone supervisor loop (`perk objective run`, Node 3.4)

The **scheduler** on top of the §8.13 runner/discovery substrate and the §8.17/§8.18 read/control
siblings: a **deterministic, no-agentic-reasoning** supervisor that advances an active objective's
backlog as far as is autonomously safe, then pauses at the human land gate. `perk objective run
<NUMBER>` (alias `obj r`) is a supervisor surface (cli-vs-pi §3.2): `--json` → stdout, human text →
stderr, stable exits (`0` ok · `1` invalid/op-failure · `2` not-a-repo), `fail`/`UserFacingCliError`
with a stable `error_type`.

### Autonomous reach: one dispatch, then stop — and **never land**

Per invocation the supervisor does **one** thing: it selects the next in-flight node and dispatches
the correct **remote** agentic stage (`implement`/`address`), or it pauses at a draft-PR /
awaiting-review / planning-required / completion boundary, then exits. It **never lands** — ready+merge
stays the human/interactive `/land`, and a node reaches `done` only via that path's
`_reconcile_objective_on_land`, which this loop merely *observes* (a `MERGED` PR ⇒
`merged_pending_reconcile`). Landing must not route through `launch_stage`: a local stage `os.execvpe`s
into interactive pi and never returns, which would destroy the loop.

### Options

- `--remote <ref>` — a normal string option (not a flag) defaulting to **`""`** (the default runner);
  dispatch is always remote, since the supervisor never drives an agentic stage locally.
  (`resolve_target` treats `""` as the default runner ref, not a kind.)
- `--wait` — poll an already-in-flight run to completion (cadence below), then re-evaluate selection
  **once**; never crosses the land gate.
- `--dry-run` — resolve + report the *selection* decision and would-be action only: **skip** the live
  `observe` overlay + active-run gate (stay offline-safe), and **mint/write/trigger/close nothing**.
- `--json` — machine report to stdout (human text to stderr).

### Single-pass control flow (deterministic)

1. `require_repo` + `require_config`; `require_github` unless `--dry-run`.
2. `state = github.get_objective(NUMBER)`; `None` → `fail(objective_not_found)`.
3. **Cumulative budget report** (always, before any action): enumerate
   `cache.list_dispatch_records`, keep records whose `plan_ref.objective_id` canonicalizes
   (`str(...).lstrip("#")`) to NUMBER, sum each `run_report.read_outcome` `budget`
   (`turns`/`tokens`/`elapsed_ms`, missing ⇒ 0) → `{runs, turns, tokens, elapsed_ms}`. **Report-only:
   no limits, no thresholds, no `budget_exhausted`.** The budget stays **local-cache-scoped by
   design**: run outcomes are local scratch artifacts, not reconstructable from the GHA
   enumeration — a fresh clone undercounts (stated, not silently implied).
4. **Active-run gate** (skipped under `--dry-run`) — **discovery-first**, so the gate works from a
   fresh clone (no double-dispatch on a machine that never dispatched): one
   `discovery.discover_runs(root, limit=100)` enumeration (replacing per-record `observe`s),
   keeping `queued`/`in_progress` runs whose parsed plan id (`#`-stripped) matches one of the
   objective's **node plan backlinks** (`node.pr`, computed from the already-fetched objective
   state — dispatch always happens after plan save, so the backlink exists for any dispatched
   node plan); the newest match gates. On a discovery `RunnerError`/`GitHubError`: one stderr
   note + the **legacy local-record loop** (a kept record with a `run_handle` whose fail-soft
   `observe` returns `queued`/`in_progress`, newest-first) — offline/degraded behavior unchanged.
   Not `--wait` → `awaiting_run`, exit 0. `--wait` → poll the (possibly reconstructed) handle to
   `completed` (or timeout → `awaiting_run` + `timed_out:true`, exit 0), then **re-fetch the
   objective state + rebuild the graph** (the settled run may have advanced GitHub) and re-evaluate
   selection once.
5. **Selection** via `graph.classify_for_planning()` → action:

   | kind | condition | action | effect |
   |------|-----------|--------|--------|
   | `complete` | every node terminal | `completed` | print the `(node→status→pr)` audit; unless `--dry-run`, `github.close_issue(NUMBER)` |
   | `blocked` | every remaining node blocked | `blocked` | pause |
   | `plannable` | a resumable node is ready | `plan_required` | emit node + remediation `perk objective-plan <NUMBER> --node <id>` (the supervisor cannot plan — `objective-plan` is `cold_remote:false`) |
   | `in_flight` | a committed plan exists | (stage resolution ↓) | |

### In-flight stage resolution (`get_plan(node.pr)` → the shared §8.37 classifier)

Classification delegates to `resume.resolve_next_action` (§8.37); the verdict maps onto the
supervisor's `action` vocabulary (unchanged) and is carried verbatim in the payload's
`next_action` field:

| §8.37 verdict | action | dispatch? |
|---------------|--------|-----------|
| `implement` | `dispatched` `stage:"implement"` | yes (remote) |
| `address` | `dispatched` `stage:"address"` | yes (remote) |
| `ready_for_review` | `ready_for_review` | **no — never re-dispatch implement** |
| `awaiting_review` | `awaiting_review` | no |
| `learn` | `merged_pending_reconcile` + `remediation: "perk plan resume <plan-id>"` | no (learn is local-only) |
| `done` | `merged_pending_reconcile` | no |
| `pr_closed` | `pr_closed` (needs human) | no |

A missing `node.pr` or a `None` `get_plan` falls back to `plan_required` (defensive). A draft PR means
implement is **complete** — never re-dispatch `implement` from a draft.

### The `needs_address` predicate

Moved to the shared classifier module — spec in §8.37 (canonical import path `perk.run.resume`).

### Remote dispatch mechanics

`_dispatch_stage_remote` reconstructs the node's plan-ref via `resume.reconstruct_plan_ref` (preserving
`objective_id` so the eventual human land reconciles the node), writes it to the **repo-root**
`cache.plan-ref` (the seam `_drive_remote_target` reads — both `objective-plan`/`run` are `worktree:
none`, so repo-root write ↔ repo-root read agree), then drives `launch.launch_stage(..., remote=...)`
— capturing its machine output so the supervisor emits a **single** unified payload, surfacing the
minted `run_id`. Only `implement`/`address` (the `cold_remote:true` stages) are dispatchable here
(`Ensure.invariant` guard; `resolve_target` is belt-and-suspenders).

### `--wait` polling cadence

`POLL_INTERVAL_S = 15`, `POLL_TIMEOUT_S = 600`, defined **locally** in the command module (same values
as the §8.19 smoke, independent lifecycle). The poll helper takes an injectable `sleep` for tests. A
timeout is **inconclusive, not unhealthy** (`awaiting_run` + `timed_out:true`, exit 0).

### `--json` payload (stdout, stable)

```jsonc
{ "success": true, "error_type": null,
  "objective": "<id>",           // opaque string objective id (§8.21; Node 4.1)
  "budget": { "runs": 0, "turns": 0, "tokens": 0, "elapsed_ms": 0 },
  "action": "dispatched" | "ready_for_review" | "awaiting_review" | "awaiting_run"
          | "plan_required" | "blocked" | "completed" | "merged_pending_reconcile" | "pr_closed",
  "next_action": "<§8.37 verdict>" | null, // set on every in-flight arm
  "node": "<id>" | null, "stage": "implement" | "address" | null,
  "run_id": "<ULID>" | null,     // present on dispatched
  "remediation": "<cmd>" | null, // present on plan_required AND the merged-learn-pending arm
  "closed": false,               // present on completed (+ "audit": [{node,status,pr}, …])
  "timed_out": false,            // present on awaiting_run under --wait
  "dry_run": false }
```

Error types + exits: `not_a_repo` → 2; `objective_not_found`, `github_error`, `dispatch_failed`
(propagated from `launch_stage`) → 1. Benign decision kinds (`plan_required`/`blocked`/`awaiting_*`/
`ready_for_review`/`merged_pending_reconcile`/`pr_closed`/`completed`) are **not** errors (exit 0).

---

## §8.21 · The issue-backend selection (`[issues]`, Objective #252 Nodes 1.3 + 2.4)

The issue-tracking tier (plan/learn/objective issues — `perk/backends/issue_backend.py`'s `IssueBackend`
contract, Node 1.1; the `GitHubIssueBackend` adapter in `perk/backends/github/backend.py` + the resolver in `perk/backends/resolve.py`, Node 1.2;
the `LinearIssueBackend` over the `perk/backends/linear/client.py` GraphQL client, Nodes 2.1–2.3, wired live in
Node 2.4) is **backend-selectable** via one committed config table:

> **Note (Objective #548).** Objective storage is now its **own seam** — the objective-storage tier
> (`ObjectiveStore`, §8.24), distinct from the issue-tracking tier described here. It shares this
> `[issues]` selection (`resolve_objective_store_id` re-exports `resolve_issue_backend_id` — an
> objective and its plan/learn issues share one tracker), so the "plan/learn/objective issues" and
> objective-id language throughout this section still resolves the same backend; the two tiers are
> just no longer one Protocol.

```toml
[issues]
backend = "linear"   # "github" is the default when unset
team = "ENG"         # the Linear team key — required when backend = "linear"
```

**Committed-only read, both planes.** The selection (`backend` AND `team`) is read from committed
`.perk/config.toml` **only** — never the `local.toml` overlay (Python:
`load_committed_issues_backend` / `load_committed_issues_team`; TS: `resolveIssueBackendId` reads
only the committed file). Rationale: the backend decides where canonical durable state
(plan/learn/objective issues) is *written*; a per-user override would fragment the canonical
store. **Main-checkout anchored, both planes.** Both planes resolve the read root to the **main
checkout** (git-common-dir resolution — Python `git.main_worktree_root(repo_root) or repo_root`,
TS `mainCheckoutRoot(cwd)`; both fall back to the invocation root outside a git repo), so a
linked worktree's checkout state (detached HEAD, a stale branch, a checkout without `.perk/`)
can never change where canonical durable state is written. Deliberate consequence: a plan branch
that *edits* `[issues]` does not take effect from inside its own worktree — the canonical-store
selection must not fork mid-plan; it switches when the edit reaches the main checkout. **`LINEAR_API_KEY` lives in the environment or the gitignored `.perk/local.toml`
`[linear] api_key`** (an exported env var wins over the config) — **never** in a committed file.
The config read is local-file-only (`config.load_local_linear_api_key`, the inverse of the
`load_committed_*` readers; fail-soft on malformed TOML — returns `None`, never raised). Two seams
bridge it: the Python clients pass `linear.client_from_env(repo_root=…)` (env-first, config
fallback), and `launch_stage` seeds the launched session's env with the local key (env wins) so the
borrowed in-session `linear_*` tools and any spawned `perk <stage> --json` cold-door worker (which
inherit the session env) authenticate. The local file is read from the **main checkout** at launch
(the env dict is built before `os.chdir(worktree)`); because it is gitignored it is never copied
into the linked worktree, so the env-seed is precisely the bridge that carries the key into the
worktree-resident session and its cold-door workers — those consumers read it from the inherited
env, never from a `local.toml` in the worktree. This is a deliberate, documented relaxation of the
"secrets in the environment only" rule: the secret may live in the gitignored local file, never a
version-controlled one. **Python-plane-only** — the TS plane reads no Linear key, so there is no
cross-plane TS mirror (the `launch_stage` env-seed is what carries the key into the TS session).

**Python is the authoritative validator** (`perk/backends/resolve.py::resolve_issue_backend_id`):

- absent / `"github"` → `"github"` (the default backend);
- `"linear"` → `"linear"` (a live selection);
- any other value → **raises** `IssueBackendError` ("unknown issue backend … (known: github,
  linear)");
- malformed committed TOML → `tomllib.TOMLDecodeError` re-raised as `IssueBackendError` (chained,
  pointing at `perk doctor`).

Raising (not falling back) is deliberate: a silent fallback would write canonical issues to the
wrong tracker. `resolve_issue_backend(repo_root)` resolves the id and constructs the matching
backend; every issue-tier consumer already routes `IssueBackendError` through its existing error
boundary. The **linear construction arm** raises a typed `IssueBackendError` when either
requirement is missing: no committed `[issues] team` → remediation pointing at `.perk/config.toml`;
no/blank `LINEAR_API_KEY` → the hinted message from `client_from_env`. Construction is lazy (no
network): the team key is bound and resolved to its UUID on first use.

**The TS mirror is fail-safe and dormant** (`extension/substrate/config.ts::resolveIssueBackendId`):
returns `"github" | "linear"`, falling back to `"github"` on absence/unknown value/any read or
parse error — safe because the TS plane only *renders prompts*, never writes canonical issues. No
TS consumer exists at this node; Node 3.1 (backend-aware prompt rendering) consumes it (mirrors
the providers.ts Node-2.1 dormant-loader precedent). `PerkConfig` carries no `issues` field — an
overlay-read shape would contradict the committed-only rule.

**The `backend_id` discipline + the stamping rule.** The `IssueBackend` Protocol carries
`backend_id: str` — the backend's id in the `[issues] backend` vocabulary, stamped **verbatim**
into `cache.plan-ref.provider` at every stamp site (`plan_save_cmd.py`'s `PlanRef`;
`resume.reconstruct_plan_ref(state, provider=…)`'s callers). This makes "the backend that wrote
the issue is the backend that gets stamped" structurally true (see also the §8.10 paragraph:
the field is the issue backend, not the seam id).

**The `issues-backend` doctor check** (group `issues`; no `--fix` arm — the selection is
user-owned config):

| committed selection | status | note |
| --- | --- | --- |
| absent / `"github"` | `ok` | `issues backend: github` |
| `"linear"` + committed `team` | `ok` | `issues backend: linear (team <key>)` |
| `"linear"` without `team` | `fail` | offline-decidable; remediate: set `[issues] team` in `.perk/config.toml` |
| anything else | `fail` | `unknown issue backend '<x>'`; fix `.perk/config.toml [issues]` |
| malformed TOML | `warn` | selection not evaluated — defers to the config check (mirrors `providers`) |

`fail` (not `warn`) for a bad selection is deliberate: unlike `[providers]` (graceful fallback →
warn), a bad `[issues]` selection hard-breaks **every** issue-touching command. Network readiness
is *not* this offline check's job — that is the `linear` group's (below).

**The verify-gated `linear` doctor group** (`perk/convergence/doctor/linear_checks.py::_linear_checks`; present only when
`verify` AND the committed backend is `"linear"`). All warn-level on failure — network readiness
is non-fatal, mirroring the `github` group's D3 discipline. Built from one
`linear.check_readiness(client, team_key, ensure_labels=False)` call (the shared
init/doctor probe — report-shaped, never raises; phases short-circuit auth → team → labels):

- `linear-auth` — ok: `authenticated as <user>`; failure (or missing `LINEAR_API_KEY`): warn,
  remediation "export LINEAR_API_KEY (create a personal API key at linear.app Settings →
  Security & access), or set [linear] api_key in .perk/local.toml".
- `linear-team` — ok: `team <key> found`; failure: warn with the error detail.
- `linear-labels` — all six perk labels present (`perk:plan`, `perk:learn`, `perk:consolidated`,
  `perk:objective`, `perk:objective-node`, `perk:gist`): ok; otherwise warn listing the missing
  names,
  remediation "run `perk init` or `perk doctor --fix`". perk's labels are created
  **workspace-scoped** (no `teamId` on create — Linear's cross-team-label guidance; the lookup is
  unscoped, so a pre-existing team-scoped label still counts).
- `linear-project-scopes` — ok: `Linear Projects accessible`; warn: `Linear Projects not
  accessible` (a non-mutating read probe of `team { projects(first:1) }` — read-access is the
  honest proxy; write/create scope is not probeable without a mutation).
- `linear-workflow-states` — ok: `workflow states cover the node-status mirror`; warn when the
  team lacks a state of a required `type` (the distinct values of `_NODE_STATUS_STATE_TYPE` =
  `unstarted/started/completed/canceled`, derived in lockstep); warn `workflow states not
  verified` on a probe error.

The last two are the **project-backed objective readiness** probe (Node 4.2): both run **only
after** `linear-auth` + `linear-team` succeed, via a separate
`linear.check_project_readiness(client, team_key)` call (report-shaped, never raises;
reuses the client's cached team id — no auth/team re-probe). Non-fatal like the rest of the group.
**No `--fix` arm** — workflow states and API-token scopes are user/workspace-owned (perk cannot
safely auto-create them).

**The `--fix` label repair gesture** (`_fix_linear_labels`, verify-gated like the skills sync —
network I/O, so never a `ManagedConvergence`): when `fix` AND `verify` AND linear is selected AND
key + team are available, `check_readiness(..., ensure_labels=True)` ensures the six labels;
created names land on `fixed` (`Linear: created label perk:plan`), failures on `fix_errors`.
Lookup-first idempotency: a converged workspace reports nothing (the doctor idempotency rule).

**The init readiness step** (`perk/convergence/init/__init__.py::_linear_readiness`, verify-gated, non-fatal — the
GitHub D3 mirror: file convergence already succeeded). Only when `verify` AND the committed
backend is `"linear"`: missing key/team degrade to an errored `LinearReport`; otherwise the probe
runs with `ensure_labels=True` (init converges the six perk labels upfront; the lazy write-time
`ensure_label` calls remain the safety net). Created labels are reported through the
`LinearReport` (the `--json` `linear` key, §8.5; the human `✓ Linear: <user>, team <key>` line) —
**never** appended to `InitReport.changes`, which stays a pure filesystem-delta list.
`LinearReport` also carries a nullable `project` readiness sub-report
(`LinearProjectReadiness` — the same `check_project_readiness` probe as the doctor group, run only
when `auth_ok && team_ok`): non-fatal — it does **not** flip `LinearReport.ok`. The init human
render adds a `⚠️` sub-line per gap (Projects read-access / missing workflow state types); a
fully-ready project readiness prints nothing extra.

**The `npm:pi-mono-linear` settings convergence** (`perk/convergence/init/settings.py::_converge_linear_package`,
composed inside `_converge_settings` — it rides the `settings-wiring` managed convergence, so
doctor dry-runs and `--fix`es it for free; no new doctor check, no new capability).
Two-directional, mirroring `_converge_provider_packages`: `backend = "linear"` selected → the
unpinned plain-string entry is appended (bundled `linear` skill accepted wholesale — no
`package_filter`); not selected → any entry matching the `pi-mono-linear` identity is **removed**
(perk treats the package as managed by the selection; hand-adding it without selecting linear is
unsupported). A malformed committed TOML is a **no-op** (never a destructive removal on an
unreadable config — the provider-convergence posture); surfacing defers to the config check.

**Backend-aware prompt rendering (Node 3.1).** Every plan-read prompt site branches on
`cache.plan-ref.provider` via the per-plane helpers `perk/run/launch/prompts.py::_plan_read_instruction` and
`extension/doors/lifecycleGates.ts::planReadInstruction` — byte-parity across planes, asserted by the
paired parity suites (`tests/test_worker_prompt_parity.py` + `extension/worker/worker.test.ts`). The
`linear` arm references the pi-mono-linear `linear_get_issue` + `linear_list_comments` tools (the
plan body is the first comment — true under every backend's `create_plan_issue`) with an
`open <url>` fallback; unknown providers keep the plain `open <url>` arm. Learn prompts
(`_learn_prompt`, `extension/doors/learn.ts::learnGuidance`) keep the `gh pr list --head plan-<pr_id>
--state merged` merged-PR derivation under every backend — PRs are GitHub-universal.
`extension/substrate/toolGating.ts::READ_ONLY_TOOLS` allowlists the 19 read-only `linear_*` tool names
unconditionally (foreign names are inert when the package is absent); the mutating/sensitive
tools (`linear_create_issue`, `linear_update_issue`, `linear_create_comment`, the two
`linear_upload_file*`, `linear_configure_auth`) are deliberately excluded. The perk-implement and
perk-learn skills carry per-backend `backends/` reference directories (`github`, `linear`),
delivered by the whole-directory skills sync. Historical Status notes elsewhere quoting
`gh issue view` (e.g. P1.T4c) are records — left untouched.

The **objective seed prompts** are backend-aware the same way (Node 4.1). The objective-plan cold
seed (`perk/cli/commands/objective/plan_cmd.py::_seed_prompt`) and the warm guidance
(`extension/factories/objectivePlan.ts::factoryGuidance` / `reconcileGuidance`) branch on the
objective backend via the seam-rendered `objective_read_instruction` /
`objectiveReadInstruction` helpers (cross-plane byte-parity owned by
the `objective-read-*` golden cases — `tests/test_prompts.py` +
`extension/substrate/prompts.test.ts` — with per-plane selection tests in
`tests/test_objective_prompt_parity.py` + `extension/factories/objectivePlan.test.ts`; see §8.31).
The helper returns a **supplemental** clause appended to the
existing `perk objective show <id>` step (never a replacement): the `linear` arm references the
Linear **Project URL** + the read-only `linear_get_issue` / `linear_list_comments` tools (an
`open <url>` fallback when the url is known; the indirect `run \`perk objective show <id>\` for its
URL` form when it is not); `github` (and any non-linear) → `""` (the `perk objective show` step
already covers GitHub — no churn). The warm plane resolves the backend from
`resolveIssueBackendId(ctx.cwd)` (committed `.perk/config.toml` — authoritative since cross-backend
objectives are unsupported by policy) and fetches the Project URL via `perk objective show <id>
--json` **only for `linear`** (github needs no clause → no fetch), **fail-open** (any fetch
failure / missing url → the indirect form). The cold plane reads `store.backend_id` + `state.url`
(both already in hand). New helper/handler params default to the github/empty arm
(`backend="github"`, `url=""`) — backward-compatible. PRs stay on `gh` (`reconcileGuidance`'s
`gh pr diff`/`gh pr view` is unchanged — PRs are GitHub-universal). `objective author` is excluded
(no objective/Project exists at author time).

**Opaque string issue ids at every machine boundary (Node 4.1).** Issue ids (plan / learn /
objective) are **opaque strings** end-to-end — GitHub's are numeric strings (`"42"`), Linear's
are the human identifier (`"ENG-123"`; the verified mutations — `issueUpdate`/`commentCreate` —
accept the identifier directly, live-verified at the Mode 2 smoke gate, so no identifier→UUID
resolution layer remains; `issueRelationCreate` receives issue UUIDs captured at issue-create
time, as it is not verified for identifiers). **PR numbers stay `int`** under `pr.number`
everywhere — PRs are GitHub-universal. Concretely:

- Every `--json` envelope emits string issue ids, with the id fields renamed for honesty:
  `plan-save`'s `issue.number` → **`issue.id`**; `learn capture`'s `learn_issue.number` →
  **`learn_issue.id`** (and `plan_issue` is a string); `objective create`/`show`'s
  `objective.number` → **`objective.id`**; `pr submit`/`pr land`'s top-level `issue` stays keyed
  `issue` but is a string; `pr land`'s `objective` sub-object `number` → **`id`** (string|null)
  and `learn.closed` carries string ids; `objective reconcile`'s `objective`/`comment_id` are
  strings; `learn docs --gather`'s `learn_numbers` carries string ids. TS decoders
  (`planSave.ts`/`learn.ts`/`land.ts`/`objectiveSave.ts`/`learnFactory.ts`) are lockstep-strict on
  the string shapes.
- CLI plan/objective arguments parse through the shared opaque-id validators
  (`resume_cmd.parse_plan_id` / `objective/shared.parse_objective_id`): strip `#`/whitespace;
  reject only empty or worktree-unsafe ids (`/`, `.`, `..`) — no int parse. The supervisor's
  in-flight resolution treats any non-empty node `pr` backlink as the plan id.
- Plan worktrees are `plan-<id>` for any id shape (`plan-ENG-123` exploits Linear's branch-name
  auto-link when the GitHub integration is installed); `worktree wipe` matches `^plan-(\S+)$`.
- **Land closure branches per backend.** GitHub keeps the squash footer `Closes #N` autoclose
  **for default-branch merges** (byte-identical); when the PR's base is a **non-default** branch
  (GitHub does not autoclose there), perk additionally performs the same explicit fail-open
  `close_issue` on the plan issue that non-github backends always get. Non-github backends get a
  plain `Plan: <id> — <url>` footer (no commit magic words — Linear's commit-linking needs a
  non-assumable webhook) **plus** that explicit fail-open close after the merge
  (`_close_plan_issue_on_land`, surfaced as the envelope's `plan_issue_closed: bool`; idempotent
  beside autoclose or any tracker Done-on-merge automation).
- The live validation surface is `tests/test_linear_lifecycle.py` (the stateful
  `FakeLinearWorkspace` offline suite) plus the manual live smoke gate runbook.

## §8.22 · Linear agent-session emission (Objective #252, Node 5.1 — stretch)

An **opt-in, fail-soft, one-way** mirror of an implement run into Linear's Agents UI
(`perk/backends/linear/agent.py` — Python-plane only; the warm TS doors delegate to the Python hooks, so
there is no TS twin).

- **The gate** (checked inside every emitter): the worktree's stamped
  `cache.plan-ref.provider == "linear"` (the stamped provider, never config — the Node 3.1 rule)
  **and** a non-empty **`LINEAR_AGENT_TOKEN`** env var. Without the token, behavior is
  byte-identical to today (dormant by default; "additive only").
- **`LINEAR_AGENT_TOKEN` env contract**: an OAuth `actor=app` access token from a user-created
  Linear agent application — a personal `LINEAR_API_KEY` is rejected by Linear's agent API. Sent
  in the OAuth `Authorization: Bearer <token>` header form (`LinearClient(bearer=True)`;
  personal-key requests keep the plain header byte-identically). Environment only — never
  config/committed files. No new config keys, no doctor check — the live smoke gate
  is the verification surface.
- **The file**: `.perk/workflow/agent-session.json` (cache tier, §8.1) —
  `{"session_id": str, "issue": str, "url": str | null}`, written at session create
  (`cache.write_agent_session`/`read_agent_session`). Absent at a follow-up hook → fail-soft
  skip with a stderr note (known consequence: a remote-run-created session is invisible to a
  later local land — that land's emission skips).
- **The four hook sites**:
  1. **implement start (local)** — `launch.launch_stage`, cold-local block, `stage.id ==
     "implement"` → `agentSessionCreateOnIssue` on the plan issue + one `thought` activity;
  2. **implement start (remote)** — `run_worker.run_worker` beside `report_started`, with the
     GitHub Actions run URL as an `externalUrls` entry; a **nonzero** worker exit additionally
     emits an `error` activity beside `report_terminal` (otherwise a failed remote drive leaves
     the session dangling-active); a zero exit emits nothing terminal (the in-run `perk pr
     submit` delegation already emitted the PR activity);
  3. **submit** — `pr submit`'s `_pr_submit_impl` (never on `--dry-run`) → an `action` activity
     (PR opened) + `agentSessionUpdate.addedExternalUrls` with the PR link;
  4. **land** — `pr land`'s `_pr_land_impl` (never on `--dry-run`) → a `response` activity
     ("PR #n squash-merged." + the objective-node summary line when any).
- **The fail-soft guarantee**: every emitter is wrapped for its typed expected failures
  (`IssueBackendError`, plus `OSError` on the session-create write — the
  `_reconcile_objective_on_land` fail-open discipline) — an expected failure never raises and
  never changes the
  host command's result/exit code/`--json` payload; it prints one loud-but-non-fatal stderr
  note (`perk linear-agent: <what> skipped (non-fatal): <exc>`). A programming error propagates.
- **Known limits + deferrals** (flagged in the module docstring): GraphQL field signatures are
  substring-pinned offline and verified live only at the smoke gate; Linear marks sessions
  `stale` ~30 min after the last activity (accepted, not mitigated); `perk address` emission,
  the `agentSessionUpdate.plan` checklist, elicitation activities, retry/backoff, and any
  webhook receiver (perk never *responds* to Linear prompts) are all deferred.

## §8.23 · The file-first plan contract (the three plan backends; Objective #339)

A consolidation-by-reference of the file-first plan pipeline Phase 1–2 of Objective #339 built.
The normative detail lives in §8.1 ("File-first plan save" + the `plan_draft` carve-out), §8.3
(the `approvalSave` seam + the warm claim carrier), and §8.10 (the interactive save discipline) —
with the plannotator/Node 2.5/2.6 Status blocks in contracts-history.md §8.10; this section is the
one-stop current shape.

- **The artifact.** The working plan lives in the session data dir as `plan-draft.md`
  (`PLAN_DRAFT_ARTIFACT`, `extension/factories/planDraft.ts`), written **only** by the `plan_draft` tool
  through the session-data accessor seam (`writeSessionArtifact`: file + provenance pointer in one
  gesture), and consumable **only** via its validated provenance pointer
  (`readSessionArtifact` — digest-validated, fail-open) (→ §8.1).
- **The two resolution chains + the asymmetry law.** **Save** surfaces resolve
  artifact → `plan` param → transcript scrape (the universal fail-open last resort)
  (`resolvePlanSource`, → §8.1 "File-first plan save"). **Review** surfaces resolve
  artifact → param **only** — the transcript tier is excluded because an approval auto-saves the
  reviewed bytes, and scraped conversation bytes must never be what gets approved (→ §8.10's
  plannotator Status block).
- **The review door + the approval seam.** `plan_review` (in `READ_ONLY_TOOLS`; backend-neutral,
  `extension/factories/planReview.ts`) dispatches: plannotator-selected → the event-bus bridge; **any**
  other selection → the first-party `ctx.ui.editor` review. APPROVED (either backend) runs
  `approvalSave` (`extension/factories/planSave.ts`): save → D1a gate exit on success (→ §8.3). The
  `/plan-save` command is the **manual failsafe** invocation of the same seam, taking only an
  optional title argument. Every `plan_review` arm carries the universal `details.ok` discriminant
  (`ok:false` + `error`/`error_type` on unavailable / save-failed / bad_input / no_plan /
  no_objective_draft; `ok:true` on verdicts and the sanctioned fail-open skips), so `tool_outcome`
  run events classify it via `details.ok` rather than the `!isError` fallback.
- **The three backends.** All three speak review-first
  (`plan_draft` → `plan_review` → auto-save on approval):

  | provider id | authoring context | review surface | fail-open arm |
  |---|---|---|---|
  | `perk-plan` | `PLAN_AUTHORING_CONTEXT` | first-party in-TUI review | present + `/plan-save` |
  | `plannotator-plan` | `PLAN_ADAPTER_PLANNOTATOR_CONTEXT` | browser bridge | present + `/plan-save` |
  | `tombell-plan` | `PLAN_ADAPTER_TOMBELL_CONTEXT` (conditioned injection, Node 2.6) | first-party in-TUI review | present + `/plan-save` (incl. tombell's own interactive `/plan` `setActiveTools` restriction arm) |

- **Plannotator "Direct Edits" (browser edits of the reviewed document).** Plannotator's
  plan-review browser lets the reviewer edit the reviewed document directly; the edits arrive as
  PROSE inside the existing `feedback` string, never a new envelope field — a `# Direct Edits`
  section (heading + preamble + a ```` ```diff ```` fence containing a jsdiff
  `createTwoFilesPatch(…, { context: 3 })` patch, `trimEnd()`'d, against the exact bytes perk
  submitted), composed FIRST, with non-sentinel annotation feedback following after
  `\n\n---\n\n` (format pin: plannotator `packages/editor/directEdits.ts`
  `buildDirectEditsSection`/`composeFeedbackWithDirectEdits` @ v0.26.1 — prose, not a pinned
  API). perk handles it asymmetrically per arm:
  - **Plan arm, APPROVE:** mechanical apply — strict extraction (`extractDirectEdits`,
    `extension/adapters/planAdapterPlannotator.ts`) → strict clean-apply (`applyUnifiedDiff`,
    `extension/substrate/unifiedDiff.ts`, a vendored zero-runtime-dep applier; null on any
    anomaly) → `writePlanDraft` write-back (reviewed bytes == artifact bytes == saved bytes) →
    save the EDITED bytes with `details.edited: true` and the annotation remainder as the only
    surviving feedback. The **fail-open ladder**: no section → today's path byte-stable; a
    heading that cannot be parsed / applied / written back → the verbatim save plus a loud
    warning in the approved text and `details.direct_edits_applied: false` (the diff stays in
    the surfaced feedback for a manual follow-up). Worst-case upstream format drift degrades to
    exactly the pre-Direct-Edits behavior.
  - **Objective arm, APPROVE with a Direct Edits section:** NO save — the save seam re-reads the
    STRUCTURED draft, so rendered-markdown edits (roadmap-table rows included) cannot be folded
    back mechanically. The arm returns a NON-terminating revise round (`details.status:
    "revise"`, `reason: "direct_edits"`, gate untouched): the model folds the diff into
    `objective_draft`, then calls `plan_review` again to confirm. perk never saves an objective
    the reviewer explicitly edited away from.
  - **Gist arm, APPROVE with a Direct Edits section:** NO save — the same shape as the
    objective arm: a NON-terminating revise round; the model folds the diff into the matching
    `gist_draft` fields (a `# <title>` heading hunk → `title`, a `Scope:` line hunk → `scope`,
    prose hunks → `prose`), then calls `plan_review` again to confirm.
  - **DENY (all arms):** model-mediated — the feedback (diff included) passes through verbatim
    for the `plan_draft`/`objective_draft`/`gist_draft` rewrite.

  The plan arm's mechanical apply is the exported `applyPlannotatorDirectEdits` helper
  (`extension/factories/planReview.ts`) — ONE apply path shared byte-identically by
  `executePlanReview`'s plannotator arm and the `/plan-review-browser` door below.

- **The `/plan-review-browser` warm door** (`extension/doors/planReviewBrowser.ts`): the
  summonable streaming draft review — from a plan-authoring session the human summons a
  plannotator **plan-review** browser on the working plan draft, a **draft-reviewer wave**
  streams phrase-anchored findings into it, and the browser decision routes through the
  existing seams. Plannotator always, no provider dispatch (the surface-named command IS the
  selection — the `/pr-review-browser` precedent); only the plannotator **presence** probe
  gates it. The door registers no tools of its own.
  - **Args:** `/plan-review-browser [custom angle text]` — the entire trimmed arg string is the
    optional custom-angle definition (empty ⇒ no custom lane; no parse-failure arm).
  - **Entry gates, in order (nothing executed on refusal, each a loud error):** headless
    (`!ctx.hasUI` — the browser surface and the human are constitutive) → the plannotator
    presence probe (the same refusal naming the fix) → the stage gate — the branch-LWW `stage`
    must be one of `{plan, save, objective-plan}` (the three registry stages whose
    `STAGE_TOOLS` carry `plan_draft`) → the draft resolve, **artifact ONLY**: the validated
    `plan-draft.md` artifact (`readSessionArtifact`); null or blank → a loud `plan_draft`
    redirect. No param tier, no transcript tier — the review-surface law tightened to
    drafts-only (an approval auto-saves the reviewed bytes).
  - **The deterministic plan-review open:** `startPlannotatorPlanReview`
    (`plannotatorHandoff.ts`) — the plan flavor of the preset-`PLANNOTATOR_PORT` browser-open
    core: free-port pick → env preset → the `plan-review` bridge request launched while the
    var is set (plannotator binds the plan server before the handshake respond) → the
    `GET /api/plan` readiness poll (plan-server-only — flavor-unique, can never false-positive
    against a code-review server) → the prior env value ALWAYS restored when the poll ends. The
    URL is deterministic the moment the port is picked, so the door primes its companions and
    injects the guidance immediately, then ends its turn.
  - **The dual prime/clear lifecycle:** the moment the port is picked the door primes BOTH
    companion surfaces — `primeAnnotationSurface({mode: "plan", url})` (the `push_annotations`
    plan mode, §8.4) and `primeDraftReviewContext({draftType: "plan", draft, custom?})`
    (`extension/doors/draftReviewWaveTools.ts` — priming resets the pending-wave slot: a new
    browser session supersedes everything). BOTH are cleared when the bridge settles AND on the
    readiness-degrade arm (idempotent), so a late push refuses `no_surface` and a late wave
    start refuses `no_draft_context`.
  - **The draft wave (the `start_draft_review_wave`/`collect_draft_review_wave` tool pair over
    `extension/waves/draftReviewWave.ts`):** the wave's inputs are **door-primed module
    state**, never tool params — `start_draft_review_wave` takes ONLY `{angles}` (2–3 unique
    slugs of `grounding`/`scope`/`decision-completeness`/`risk`, **none mandatory** — model
    judgment) and refuses unprimed, so the model can never substitute a transcript/arbitrary
    draft or invent a custom lane: reviewed bytes == browsed bytes == wave bytes by
    construction. The **custom lane is the draft doors' user-input channel** (no `directive`
    param exists), riding the primed context automatically as its own `custom` lane; the
    surface handle is structurally unrepresentable in the wave (no URL parameter exists).
    **Zero retries** — honest incompleteness surfaced to the human (the uncovered lane(s)
    named, never papered over); a pending wave makes a second start refuse `wave_active`;
    `collect_draft_review_wave` mirrors the PR pair (`no_wave` / grace-raced `wave_running`
    with the pending wave retained / the typed aggregate `{complete, covered, reports,
    failures}`, `covered` including the custom lane). The `[models.subagents] draft-reviewer`
    override is resolved by the tool at execute time (the door reads no config); the per-call
    signal is deliberately not threaded (the wave outlives the call; the module timeout is the
    orphan insurance). Findings are the plan-mode `PlanFinding` shape (`{phrase, severity,
    confidence, body}`), pushed phrase-byte-exact via `push_annotations` (streamed batches
    provisional; per-lane finals ride `replace: true`).
  - **Decision routing (the background decision task — the wait is open-ended, exactly the
    model-called `plan_review` bridge semantics; a turn abort settles `aborted`):**
    **APPROVE** → the **stale-draft guard** first (the browser wait is open-ended and the
    session stays usable, so a concurrent `plan_draft` write can land meanwhile: the approval
    proceeds only while the live artifact still carries the exact bytes captured at open —
    mismatch/missing → a loud stale refusal, nothing saved, gate untouched; best-effort: it
    closes the human-scale race, the check-to-save window is accepted) → the shared
    `applyPlannotatorDirectEdits` mechanical apply (unchanged) → `approvalSave` (claim-carrier
    recovery rides `approvalSave`→`savePlan` unchanged) → the `approvedSaveResult` composition
    reported to the human (info on saved; a failed save is loud, leaves the gate read-only,
    and names the `/plan-save` failsafe) AND injected to the model (idle → immediate,
    streaming → followUp). **DENY** → model-mediated revise round: the feedback (Direct Edits
    diff included) injected verbatim driving a `plan_draft` rewrite; the human re-runs
    `/plan-review-browser` (or the model calls `plan_review`) for the next round — no auto
    re-open. **Injected feedback is delimited untrusted DATA** on both arms
    (`<untrusted_reviewer_feedback>` + a DATA-not-instructions note): browser feedback can
    carry machine-generated annotation text (the wave's `perk:*` findings returning), and it
    must never read as instructions after the gate may have come off.
    **Unavailable/timeout** → the loud degrade: an error report plus a degrade notice injected
    to the model (surface the wave's findings in-session; both surfaces cleared; the human
    falls back to `plan_review`/`/plan-save`) — AND the degrade **invalidates the decision
    task** (a shared door-session token): a bridge decision arriving after a degrade is
    ignored loudly (a warning naming the ignored decision), never routed into a stale or
    duplicate save.
  - **Accepted edges (noted, not engineered around):** the concurrent double-open stale-clear
    (a second `/plan-review-browser` re-primes; the first bridge's later settle clears the
    second session's surfaces — the `/pr-review-browser` posture) and the early human decision
    mid-wave (authoritative — the save proceeds; the cleared surface makes late pushes refuse
    `no_surface`; a still-pending wave stays collectable).
  - **Binding:** `command:plan-review-browser` → `perk-plan-review-browser` (nudge, §8.9),
    delivered on the guidance injection.

- **The `/objective-review-browser` warm door** (`extension/doors/objectiveReviewBrowser.ts`):
  the objective twin of `/plan-review-browser` — from an objective-authoring session the human
  summons a plannotator **plan-review** browser on the **rendered** working objective draft
  (prose + the `**Delivery:**` line + the roadmap table), a **draft-reviewer wave** streams
  phrase-anchored findings into it, and the browser decision routes through the existing
  objective seams. Plannotator always, presence-probe-gated, no tools of its own — the same
  door shape throughout, with the objective differences below.
  - **Args:** `/objective-review-browser [custom angle text]` — the entire trimmed arg string
    is the optional custom-angle definition (empty ⇒ no custom lane; no parse-failure arm).
  - **Entry gates, in order (nothing executed on refusal, each a loud error):** headless
    (`!ctx.hasUI`) → the plannotator presence probe (the same refusal naming the fix) → the
    stage gate — the branch-LWW `stage` must be one of `{objective-author, objective-save}`
    (the two registry stages whose `STAGE_TOOLS` carry `objective_draft`) → the draft resolve,
    **validated artifact ONLY**: the raw `objective-draft.json` artifact
    (`readSessionArtifact`; null/blank → a loud `objective_draft` redirect), then
    `readObjectiveDraft` (null — malformed/invalid — → a loud `objective_draft` rewrite
    refusal) and `renderObjectiveDraft` — the reviewed bytes are the RENDERED markdown, never
    raw JSON, never a param, never the transcript. The raw artifact bytes captured at open are
    the stale guard's baseline (the micro-window between the two reads is the accepted
    check-to-open race — the plan door's check-to-save posture).
  - **The deterministic plan-review open:** the same `startPlannotatorPlanReview` engine — the
    `plan-review` bridge action carries the rendered objective as `planContent` (arbitrary
    markdown bytes; no plan-specific validation). The door primes its companions and injects
    the guidance immediately, then ends its turn.
  - **The dual prime/clear lifecycle:** identical — `primeAnnotationSurface({mode: "plan",
    url})` + `primeDraftReviewContext({draftType: "objective", draft: rendered, custom?})`;
    both cleared when the bridge settles AND on the readiness-degrade arm (idempotent).
  - **Decision routing:** **APPROVE** → the **Direct-Edits carve-out FIRST** (nothing is saved
    on that arm, so the stale guard is irrelevant there): an approval whose feedback opens a
    `# Direct Edits` heading is a NON-terminating revise round — rendered-markdown edits
    cannot be folded back into the structured `{prose, roadmap}` artifact mechanically, so
    NOTHING is saved, the gate stays untouched, and the model folds the diff in via
    `objective_draft` then re-reviews to confirm (`applyPlannotatorDirectEdits` is plan-only —
    it writes `plan-draft.md` — and never runs here); then the **stale guard on the RAW
    structured artifact bytes** captured at open (the save-authoritative surface — it catches
    render-invisible changes like `base` or a node `slug`/`pr`/`comment`): mismatch/missing →
    a loud stale refusal, nothing saved, gate untouched; then `objectiveApprovalSave` (⇒ D1a
    gate exit on an ok save; a failed save is loud, leaves the gate read-only, and names the
    `/objective-save` failsafe). **DENY** → the model-mediated `objective_draft` revise round
    (the feedback, Direct Edits diff included, injected verbatim; the human re-runs the door or
    the model calls `plan_review`). **Injected feedback is delimited untrusted DATA** on both
    arms (the `<untrusted_reviewer_feedback>` wrapper + the DATA note). The degrade
    invalidation token, the loud post-degrade decision ignore, and the accepted edges (the
    double-open stale-clear; the early decision mid-wave) all carry over unchanged.
  - **Binding:** `command:objective-review-browser` → `perk-objective-review-browser` (nudge,
    §8.9), delivered on the guidance injection.

- **Link/`consumed_learn` recovery carriers.** Approval-triggered saves carry **no model params**;
  the **cold** `handoff_extra` carrier (→ §8.2) and the **warm** `objective_node_claim` carrier
  (→ §8.3) recover `objective_id`/`node_id` with identical semantics — fill both-or-neither,
  explicit values win outright (even one — never mixed), fail-open (a malformed carrier never
  blocks a save). `consumed_learn` rides the cold handoff (`_consumed_learn_from_handoff`).

- **The implement-here exit (the no-save path).** A sanctioned, HUMAN-ONLY exit from plan
  authoring for changes too small to warrant the full lifecycle: the read-only gate comes off
  **without** an issue-backend save, and the model is instructed to implement the reviewed draft
  directly in the current session/checkout — edits only; git gestures (commit/branch/push) stay
  with the human. Two surfaces (`extension/factories/implementHere.ts` + the plan arm of
  `planReview.ts`), both machine-unreachable (no model tool exists — a verdict select or a
  human-run command; the model can never choose to skip the backend on its own):
  1. the **4th first-party verdict** — the plan arm's `ctx.ui.select` offers
     "Implement here — no issue saved" between approve and deny; selecting it routes (before the
     generic outcome mapper, mirroring approved-first) through the `implementHereExit` seam (the
     gate-exit-WITHOUT-save sibling of `approvalSave`'s D1a arm) into a **non-terminating** tool
     result carrying the implement-now guidance — the model continues the turn and implements
     immediately. When the human edited the plan during review, the final reviewed bytes are
     inlined in that guidance (the draft write-back already happened pre-verdict).
  2. the **`/implement-here` command** — the universal manual gesture: exits the gate through the
     same seam and injects the guidance (idle → an immediate turn; streaming → a followUp). With
     the gate already off it warns and does nothing (its meaning is *exiting plan mode without
     saving*).

  Semantics: **no issue, no `cache.plan-ref`, no branch** — the PR-lifecycle doors
  (`/submit`/`/address`/`/land`) stay inapplicable; the plan-draft artifact is left intact, so
  `/plan-save` can still create the canonical issue afterwards. **Objective-node carve-out**: in a
  node-claimed planning session (`objective_node_claim` present) the verdict is suppressed (back
  to the 3-option select) and the command refuses — a node-linked plan must always save (the node
  advance and backlink depend on it). **Plannotator note**: the browser review's envelope returns
  only approve/deny — the verdict is unreachable there; the command is the surface.

§8.10's per-node Status blocks remain the historical record of how each piece landed; this section
is the consolidated **current** contract.

## §8.24 · The objective-storage tier (the `ObjectiveStore` seam; Objective #548)

perk's durable state lives in two conceptually distinct populations: the **issue-tracking tier**
(plan/learn issues — the `IssueBackend` contract, §8.21) and the **objective-storage tier**
(objectives — the `ObjectiveStore` contract, this section). Today a single backend stores **both**
as issues, so the tiers are behaviorally fused; the split exists so a Phase 3 store can make a
Linear **Project** a canonical objective (not just an issue). Objective #548 Node 2.1 shipped the
dormant contract; Node 2.2 made it live; Node 2.3 (this section) amends the contract + user-docs.

The two tiers are **named distinctly** at the boundary: the objective tier drops the issue tier's
`_issue` method suffix (`find_objective`/`create_objective`, not `find_objective_issue`) and renames
the id field `issue_id → objective_id` everywhere, because the stored thing is an objective — a
GitHub issue **or** a Linear Project.

**The contract module** (`perk/backends/objective_store.py`, Node 2.1, dormant — mirrors the
`issue_backend.py` dormant-then-extract precedent: the contract ships dormant, a later node extracts
the concrete backend behind it):

- The `ObjectiveStore` `Protocol`: `backend_id: str` plus **twelve** keyword-only methods —
  `find_objective` / `create_objective` / `get_objective` / `update_objective_header` /
  `update_objective_node` / `update_objective_body` / `add_objective_node` / `save_node_plan` /
  `close_objective` / `post_status_update` / `detect_objective_drift` / `repair_objective_drift`
  (`objective_id` everywhere; the last two added at Node 4.4 — see the amendment). `add_objective_node` inserts
  a new roadmap node (auto-assigned `<phase>.<n>`, appended within the phase) — the rare
  node-insertion surface used sparingly during reconciliation (prose-guarded, no audit gate).
  Each concrete store inserts into the thing it stores: the GitHub + issue-backed Linear stores
  re-render the roadmap block; the project-backed store materializes a new node-**issue** under the
  phase milestone. `save_node_plan` + `close_objective` were added
  at Node 3.4 (see the Node 3.4 amendment): `save_node_plan` is the node↔plan **unification** write
  (returns the node-issue ref for a unifying store, **`None`** for a store that does not unify — the
  single "doesn't unify" signal), and `close_objective` retires the objective's **own** entity on
  completion (each backend closes the thing it actually stores). `post_status_update` was added at
  Node 4.3 (see the Node 4.3 amendment): it posts a human-readable status update to the objective's
  native update surface, returning `True` when posted and `False` for a store with no such surface
  (GitHub, issue-backed Linear) or a `dry_run`.
- Six frozen result dataclasses: `ObjectiveRef` (`id`/`url`/`existed`), `ObjectiveState`
  (`id`/`url`/`title`/`header`/`nodes`), `ObjectiveHeaderUpdate`, `ObjectiveNodeUpdate`,
  `ObjectiveBodyUpdate`, `ObjectiveNodeAdd` (`objective_id`/`node_id`/`comment_updated`/`dry_run`).
- One backend-neutral error type: `ObjectiveStoreError`.

**The state-ownership invariants** (the four contract disciplines every concrete store MUST honor):

- **Constructor-bound repo context.** Methods take no `repo_root`; a store instance is constructed
  for exactly one repo (GitHub binds `repo_root` as the `gh` cwd; Linear binds team/API-key config
  at construction).
- **String ids at the boundary.** Every objective/comment id crossing the boundary is a `str`
  (GitHub's issue numbers stringified; a Linear Project id is natively a string).
- **Backend-owned opaque header values.** The `header` dict is opaque `dict[str, object]`;
  header-embedded values (e.g. the objective-body comment id) are backend-owned — a caller must
  never interpret them.
- **Error discipline.** Mutations raise `ObjectiveStoreError`; lookups return `… | None` for
  not-found and **raise** on infra failure — never mask an error as `None`. Concrete stores map
  their native errors into `ObjectiveStoreError` at their boundary.

**The concrete stores + the facade refactor** (Node 2.2):

- `GitHubObjectiveStore` (`perk/backends/github/objective_store.py`) — **late-bound delegation** to
  the GitHub objective substrate (`perk/backends/github/objectives.py`, a sibling) plus the
  plan/issue substrate for `read_objective_source`/`close_objective` (a GitHub objective IS an
  issue); these are the same functions the fused `IssueBackend` used (the equivalence lock: the
  GitHub writes are byte-for-byte the prior behavior); `repo_root` constructor-bound; string-id
  boundary with an `int()` edge conversion; `GitHubError → ObjectiveStoreError` verbatim via
  `_translate`. Carries `backend_id = "github"`.
- The **Linear facade refactor** (`perk/backends/linear/`): a shared `_LinearIssueOps`
  substrate (client + caches + issue helpers); `LinearIssueBackend` as a thin facade over its
  `_ops`; and `LinearObjectiveStore` with its own `_LinearIssueOps`, the six objective methods, and
  `IssueBackendError → ObjectiveStoreError` per-method message-verbatim. Both carry
  `backend_id = "linear"`. The issue-backed `LinearObjectiveStore` is **kept dormant since Node
  3.4** (directly-constructable, still unit-tested) — the resolver's Linear arm now constructs the
  project-backed `LinearProjectObjectiveStore` (see the Node 3.4 amendment below).

**The resolver.** `resolve_objective_store(repo_root)` (`perk/backends/resolve.py`, alongside the
issue-tier `resolve_issue_backend`) dispatches on the **`[issues]` selection** (§8.21):
`github → GitHubObjectiveStore`; `linear →
LinearProjectObjectiveStore` (project-backed, since Node 3.4). Single-sourced:
`resolve_objective_store_id` re-exports `resolve_issue_backend_id` rather than reading a separate
config key, because an objective and its plan/learn issues share **one** tracker; project-vs-issue
is **not** separately selectable — it is simply what "linear" now means for objectives. Every
objective consumer routes through `resolve_objective_store(repo_root)`.

**The `backend_id` stamping rule.** `ObjectiveStore.backend_id` is stamped **verbatim** into
`cache.plan-ref.provider` — mirroring `IssueBackend.backend_id` (§8.21): "the backend that wrote the
objective is the backend that gets stamped." The objective tier and the issue tier share the stamp
vocabulary because (today) they share the backend.

**Node 3.4 amendment — the project-backed Linear objective is live; node↔plan unification; close
through the store.** The resolver's Linear arm is flipped to `LinearProjectObjectiveStore`, so
**every** Linear objective is now a Linear **Project** (overview = `objective-header` +
Reconcilable prose; the roadmap is materialized as one **node-issue** per node, each carrying an
`objective-node` block; phases = milestones; explicit `depends_on` = blocking relations). GitHub is
unchanged.

- **Node↔plan unification (`save_node_plan`).** In the project model a roadmap node already *is* a
  Linear issue, so an **objective-linked** `plan-save` writes the plan **into that node-issue**
  rather than minting a second `perk:plan` issue: the `plan-header` block is merged into the
  node-issue description (Linear-safe inline-code), the plan body is upserted as a single node-issue
  comment, and the node-issue's **title** (its roadmap identity `"{id}: …"`), `objective-node`
  block, and prose are untouched (node-issues carry **no** `perk:plan` label — discovered by project
  membership + the node block). `cache.plan-ref.pr_id` then points at the **node-issue**, and the
  implement→submit→land loop runs against it. `save_node_plan` returns the node-issue ref for a
  unifying store and **`None`** otherwise (`GitHubObjectiveStore` + issue-backed
  `LinearObjectiveStore` always return `None`; the caller falls back to the standalone path). A
  `dry_run` returns `None` (resolving the node-issue needs a network read). **Standalone
  (non-objective) `plan-save` is byte-unchanged.**
- **The node→plan backlink is the node-issue's own identifier.** `get_objective` derives a node's
  `pr` as `canonical_pr(identifier)` whenever the node-issue carries a `plan-header` block (a plan
  was saved into it), else `None` — self-referential (the plan *is* the node-issue) and stable
  across `pr submit` overwriting `plan-header.pr` with the GitHub PR number, so the land-path match
  (`nodes_for_pr(nodes, plan_ref.pr_id == identifier)`) holds with no change to `nodes_for_pr` /
  `pr submit` / `pr land`.
- **`close_objective` removes the issue-tier leak.** Objective completion (the `pr land`
  close-on-complete and the `perk objective run` `complete` branch) now closes through
  `store.close_objective`, never `IssueBackend.close_issue`: `GitHubObjectiveStore` **closes** the
  GitHub objective issue (byte-identical to the prior close); the issue-backed `LinearObjectiveStore`
  moves the objective issue to its Done state; `LinearProjectObjectiveStore` **marks the Linear
  Project complete** (`projectUpdate(state:"completed")`) — a Project is not an issue. Fail-open is
  preserved (a close failure never changes the land result).
- **`reopen_objective` is close-on-complete's mirror — the reopen-on-incomplete invariant.**
  `ObjectiveStore.reopen_objective{objective_id, dry_run} -> bool` is a **converge-to-open**
  gesture (`True` iff a reopen write actually happened; already-open / untouchable states /
  `dry_run` → `False`; infra failures raise `ObjectiveStoreError`): `GitHubObjectiveStore`
  re-opens the issue via `plans.reopen_issue` (GET `state`, PATCH `state=open` only when closed);
  `LinearProjectObjectiveStore` moves a `completed` Project back to `started` (and ONLY from
  `completed` — `canceled` is a human cancel, not perk's to undo); the issue-backed
  `LinearObjectiveStore` moves a `completed`-type issue state back to the team's `started` state.
  The ONE caller is `perk objective node-add`: a successful **non-dry-run** add of a
  **non-terminal** node (roadmap incomplete again ⇒ the objective must be open — an objective a
  human closed early *does* reopen; inserting live work expresses intent that it is live) calls it
  in an isolated **fail-open** block (the exact posture of land's close — a reopen failure never
  discards the add). The one exemption is **superseded lineage**, guarded backend-neutrally at the
  door (never in a store): a non-empty `superseded_by` in the objective-header (a perk-schema
  field) skips the reopen with a stderr note — policy, not an error. The node-add `--json` payload
  carries `reopened: bool` and `reopen_error: string|null` (`null` on the superseded skip).
  **Deliberate boundary:** the invariant rides `add_objective_node` only —
  `update_objective_node` flipping a terminal node back to non-terminal on a closed objective does
  NOT auto-reopen.
- The objective id is the opaque **Project UUID** across `active_objective` / `--objective-id` /
  the handoff / `cache.plan-ref.objective_id` — no numeric/`ENG-`-shape assumption anywhere.
- **Realized:** the `projectUpdate(state)` mark-complete is **live-verified 2026-06-16** (Node 5.1
  Mode-4 gate 4.6, `set_project_state`); the **docs/user-docs** operator narrative for the
  project-backed objective lifecycle was **reconciled in Node 5.2** (this node).

**Node 4.3 amendment — phase→milestone sync seam + fail-open Project Updates.** Two additive,
**non-fatal** enrichments to the Linear project-backed objective (GitHub unchanged: no Project
Updates, no milestone seam). Every Linear write added here is best-effort — a failure is logged
loud-but-non-fatal to stderr and **never** changes the command's result (a Linear bookkeeping
failure never breaks a merge or a node transition).

- **phases → milestones is a name-keyed lookup-or-create seam.** `_LinearProjectOps.ensure_phase_milestone(*, project_id, name, known=None)`
  reuses an existing milestone for `name` or creates one. **Name is the deterministic key** —
  milestone order is NOT insertion order (the 1.4 finding) — and the canonical name source is
  `objective.enrich_phase_names(prose, [key])` (the overview's `### Phase N: …` headers, falling
  back to `phase_label` → `"Phase N"`). `create_objective` routes its create-time milestone loop
  through the seam with a **seeded-empty `known`**, so its network calls stay byte-identical to the
  prior blind-create loop (no extra `project_milestones` read). The seam is the **"kept in sync on
  node add"** primitive a future `add_node`-to-an-existing-objective will reuse (with `known=None`)
  — load-bearing, not fiction; `objective.add_node` stays caller-less in this node. **No
  phase-key→id registry** — name is the dedup key. The phase-header-text-drift duplicate-milestone
  edge (reconciliation rewrites a `### Phase N:` header → the stored milestone name no longer
  matches the re-derived name → a duplicate) is **Node 4.4's** drift-detection + repair concern.
- **fail-open Project Updates** (`post_status_update` → `_LinearProjectOps.create_project_update`,
  the `projectUpdateCreate` mutation; `input = {projectId, body}` only — the `health` field is
  deliberately **omitted**) are posted on three transitions: **objective created** (`perk objective
  create`, fresh-create only — skipped on the idempotent found-existing path), **a plan lands**
  (`_reconcile_objective_on_land` in `pr land`, posted once when ≥1 node was marked, isolated like
  the existing close fail-open), and **reconciliation runs** (`perk objective reconcile`, on a real
  non-dry-run update). Bodies come from pure backend-neutral composers in `perk/objective/render.py`
  (`objective_created_update_body` / `plan_landed_update_body` / `reconciled_update_body`) computed
  from counts the call site already holds — **no extra network reads**. There is **no** plan-save
  Project Update (out of this node's scope).
- **Realized:** `projectUpdateCreate` / `set_project_state` / `list_projects` are **live-verified
  2026-06-16** (Node 5.1 Mode-4 gates 4.1 / 4.3 / 4.5 / 4.6).

**Node 4.4 amendment — the objective manifest + drift detection/repair (`perk objective doctor`).**
A Linear Project's roadmap is *observed* state (node-issues, blocking relations, milestones) that a
human can edit out from under perk. To detect that divergence, the project overview now persists an
authoritative **`objective-manifest`** block (inline-code, between the `objective-header` block and
the Reconcilable region) — the intended roadmap's **structural identity**: per node `id` / `slug` /
`description` + the explicit `depends_on` edge set (always a list), plus a `phases` map pinning the
canonical milestone name per `phase_key_str` (`"2A.1" → "2A"`). `status`/`pr` are **excluded** (they
are live/observed state, not identity). Drift is `diff(manifest, observed)`; repair makes the
observed state match the manifest for **safe, unambiguous** cases only (perk never *invents*
information it has no authority to invent). GitHub + the issue-backed Linear store edit their
roadmap atomically with the body — **no divergence surface** — so both new methods are empty no-ops
there (the `save_node_plan → None` / `post_status_update → False` precedent).

- **The pure drift engine** (`perk/objective/drift.py`, fully offline — no network/clock/Click): the
  store builds an `ObservedSnapshot` (the one network step) and `detect_drift(snapshot)` returns a
  `DriftReport` of `DriftCondition`s, each carrying a stable machine `code` (`DriftCode`), a
  `severity` (error/warning/info), `node_id`/`target`, a `message`, and a **`repairable`** flag. A
  malformed manifest (`MANIFEST_MALFORMED`) or an absent one (`MANIFEST_ABSENT`) short-circuits — no
  baseline to diff. The catalog of codes: `MANIFEST_ABSENT` (repairable: backfill) ·
  `MANIFEST_MALFORMED` · `MISSING_NODE_ISSUE` (repairable: recreate) · `DUPLICATE_NODE_IDS` ·
  `MISSING_NODE_STATUS_BLOCK` · `BLOCKING_RELATION_CYCLE` (manifest-enriched: names the human-added
  edges) · `UNKNOWN_BLOCKER_REFERENCE` · `DEPENDENCY_MISSING_IN_LINEAR` (repairable: create
  relation) · `DEPENDENCY_EXTRA_IN_LINEAR` · `DELETED_PHASE_MILESTONE` (repairable: recreate +
  reattach) · `RENAMED_PHASE_MILESTONE` · `OVERVIEW_MARKER_DAMAGE`.
- **Two new `ObjectiveStore` methods + two result dataclasses.** `detect_objective_drift(*,
  objective_id) → DriftReport` and `repair_objective_drift(*, objective_id, dry_run=False) →
  RepairResult`. `RepairResult` = `applied: tuple[RepairAction,…]` / `failed: RepairAction | None` /
  `remaining: tuple[DriftCondition,…]` / `aborted: bool` / `dry_run: bool`; `RepairAction` =
  `code` / `node_id` / `error` (the write-failure message on the failed action only). Repairs apply
  in a deterministic order — a manifest backfill short-circuits everything, else milestone → node-
  issue → dependency (parents before edges), then by node id — and **fail loud**: the first failed
  Linear write stops the batch (`aborted=True`, the failing condition in `failed`); `applied` records
  what landed before the abort (durable + idempotent on re-run). A `dry_run` plans the would-apply
  set without any write. Node-issue recreation is **deferred-edge**: all missing node-issues are
  created first, then a single post-loop sweep restores every manifest edge **touching a recreated
  node** that Linear still lacks — in **both** directions (the recreated node's own `depends_on` AND
  an already-existing dependent's edge to it). Detection cannot raise a `DEPENDENCY_MISSING_IN_LINEAR`
  action while either endpoint is absent (it only diffs deps between two observed nodes), so the
  recreate path owns those edges; observed↔observed missing edges stay with the explicit dependency
  repair (the sweep skips edges whose endpoints are both already-observed, so no double-create). The
  drain fails loud on a genuinely unresolvable endpoint, never silently skips.
- **Two new project ops** (`_LinearProjectOps`, **offline-covered / not-yet-live-proven** — see the
  correction below): `project_issues_with_milestones` (a `project_issues` sibling joining each node-issue's
  `projectMilestone`) and `attach_issue_to_milestone` (the deleted-milestone reattach — bare
  boundary identifier through `_request_issue_mutation`, mirroring post-#622 `attach_issue_to_project`;
  **no `uuid_for`**, deleted in #622). A recreated missing node-issue uses `_create_issue_raw` to
  capture the UUID for the UUID-only `issueRelationCreate`.
- **Manifest sync on the live write paths.** `create_objective` writes the manifest at create;
  `add_objective_node` appends the new node's entry (pinning a brand-new phase's name) and — because
  **the manifest is the phase-name authority for an existing phase** — attaches the node to the
  manifest-pinned milestone for an already-pinned phase (`enrich_phase_names` only seeds the name for
  a brand-new phase, so an external overview edit can't divert the node to a wrong/new milestone);
  `update_objective_node` syncs a node's manifest **description** on a description change (a
  status/pr-only change does **not** touch it); `update_objective_body` (reconcile) refreshes the
  `phases` pins to **match** the spliced overview in the **same** write — the overview is the
  authority on a reconcile, so a pin tracks exactly what `enrich_phase_names` derives, **including
  reverting to the `Phase N` default** when a reconcile removed/defaulted a header (never preserving
  a now-stale custom name). Every sync is a clean no-op on a pre-manifest objective (no manifest
  block); `doctor --fix` backfill is the path that adopts one.
- **The worker.** `perk objective doctor <id> [--fix] [--dry-run] [--json]` — detect-only by
  default; `--fix` applies the repairable repairs; `--dry-run` (with `--fix`) plans them. `--json`
  emits `{success, error_type, objective, drift: [condition…], fix: null | {applied, failed,
  remaining, aborted, dry_run}}` to stdout; human text to stderr. Exit `0` ran (drift, even
  ERROR-severity report-only drift, is a clean report) · `1` op-failure or an **aborted** repair ·
  `2` not-a-repo.
- **Live-unverified (corrected):** the two new project ops (`project_issues_with_milestones`,
  `attach_issue_to_milestone`) were added in #624 **after** the Node 5.1 gate ran. The Node 5.1
  Mode-4 run executed with the drift doctor design-only and substituted a `get_objective`
  perturbation baseline (gate 4.9) for the doctor run, so these two ops were **not** verified at 5.1
  and remain **offline-covered / not-yet-live-proven** — a live-unverified follow-up (no Phase-5
  gate now covers them).

**Node 5.2 amendment — Phase 5 close-out (docs-only reconciliation).** Phase 5 closed Objective
#548. Node 5.1 (PR #610) **live-proved** the four targeted Project ops on 2026-06-16 (Mode-4 gates
4.1–4.10: `list_projects`, `create_project_update`, `set_project_state`, `_workflow_state_id` both
directions). Node 5.2 (this node) finalized the contract + `docs/user-docs/` against what was built
and live-verified, relocated the three Linear docs (`linear-masterplan.md`,
`the-road-to-using-linear-projects-as-objectives.md`, `linear-smoke-gate.md`) into `docs/planning/`,
and annotated the two historical memos as realized. No production logic changed. The two drift ops
above remain the one honest live-unverified residual.

**Idiomatic-Linear amendment (#669) — attribution, attachments, labels, prose-first metadata.**
Additive, **Linear-only** (every GitHub-backed render path is byte-identical; the only cross-plane
artifact touched is this contract). perk authenticates with a personal `LINEAR_API_KEY`, so the
actor is the human user; these changes make perk's footprint read as native:

- **Attribution = the API-key user (the viewer).** `LinearClient.viewer_id()` resolves + caches
  the viewer UUID (`query { viewer { id } }`, mirroring `team_id` memoization). **Every**
  perk-created issue (plan, learn, objective-issue, node-issue — all through
  `_create_issue_raw`) sets `assigneeId` to the viewer, so it appears in the user's *My Issues*;
  **every** project (`create_project`) sets `leadId` to the viewer.
- **Project `startDate` at create.** `create_project` sets `startDate` to today (ISO `YYYY-MM-DD`),
  the prerequisite for Linear's project graph; target date stays unset (perk has no deadline
  signal).
- **Project lifecycle → Started on first node work.** `LinearProjectObjectiveStore.update_objective_node`
  best-effort advances the Project to `started` (`set_project_state`) when a node enters a
  `started`-type status (planning/in_progress/blocked per `_NODE_STATUS_STATE_TYPE`). Forward-only
  (it only ever writes `started`; completion is owned by `close_objective`), idempotent, and
  fail-open. The node-status workflow-state mirror beside it (which nudges the node-issue's Linear
  state to match the new status) is likewise fail-open, but its failures now print one
  loud-but-non-fatal stderr note (`perk linear: node status mirror skipped`); the project-lifecycle
  nudge itself stays a silent `suppress` (a truly-opportunistic forward-only write).
- **Workspace-scoped perk labels.** `_ensure_label_id` omits `teamId` on create, so the five
  `perk:*` labels are created at workspace level (Linear's cross-team-label guidance); the lookup
  is unscoped, so a pre-existing team-scoped label still counts (no duplicate).
- **The fifth label `perk:objective-node`.** Roadmap node-issues now carry it (additive
  human-filterability — discovery is still by project membership + the `objective-node` block, so
  `get_objective` is unaffected). It joins `_PERK_LABELS` (init / `doctor --fix` / readiness ensure
  it) and is applied at `create_objective`, `add_objective_node`, and node-issue drift-recreation.
- **Native PR attachments (idempotent by URL).** `_LinearIssueOps.create_attachment(issue_id, *,
  url, title, subtitle=None)` issues `attachmentCreate` (a sidebar card; re-creating the same URL
  updates in place — no id to track). `LinearIssueBackend.update_plan_header` posts one
  best-effort, **fail-open** when the stamped `pr` resolves to a GitHub PR (title `GitHub PR #N`,
  subtitle the PR state). This single seam covers both a standalone Linear plan issue and a unified
  node-issue (both stamp `pr` here). The attachment is bookkeeping — a Linear/PR-lookup failure
  never fails the header stamp, and prints one loud-but-non-fatal stderr note
  (`perk linear: PR attachment skipped`).
- **Prose-first metadata composition.** Linear bodies now render the human prose **first**, the
  machine blocks after: the project overview is `Reconcilable(prose)` then `objective-header` +
  `objective-manifest`; node-issues are `description` (prose) then the `objective-node` block.
  Reads are position-independent (`find_metadata_block` / `replace_reconcilable_section` scan by
  marker), and the manifest-backfill insert (`_insert_or_replace_manifest`) places the manifest
  **after** the Reconcilable region. The GitHub `style="html"` `<details>` render is unchanged.
- **Deferred — the collapsed-toggle render.** Wrapping the Linear metadata blocks in a native
  collapsible toggle (the true `<details>` analog) depends on an **undocumented** markdown
  round-trip and is gated on the live smoke gate (Mode 5).
  Per the plan's safe-degradation, prose-first ships now and the toggle is deferred until the live
  round-trip is proven lossless (else dropped). Becoming a true Linear **Agent** (`actor=app`) is a
  separate, out-of-scope follow-up.

**Native-attachment metadata amendment (#1355) — Linear perk metadata rides issue attachments.**
Linear-only (**GitHub renders are byte-identical**; the issue-tier protocol reshape below is the
one cross-backend change). The five machine metadata blocks — `plan-header`, `learn-header`,
`objective-node` (issue-scoped) and `objective-header`, `objective-manifest` (project-scoped) —
**no longer render into Linear bodies at all**: each rides a native issue **attachment** with a
machine-readable `metadata` envelope. Bodies/overviews are clean human prose. This supersedes the
prose-first-composition bullet above (there are no machine blocks left to position), the
collapsed-toggle deferral (moot), `_insert_or_replace_manifest` (deleted), and every
list-and-parse find scan. A **clean break**: no legacy read fallback — pre-existing Linear
artifacts with body-block metadata are simply not found (re-save/re-create them). Still inline in
bodies (structural sentinels, not metadata): the `plan-body`/marked-comment markers, the
Reconcilable region markers, the `Adopted-from` archive note, and the copyable command callouts.

- **The envelope** (`perk/backends/linear/attachments.py::encode`): `attachmentCreate` with
  `metadata: { source: "perk", schema_version: 1, kind: <block key>, payload_json: <JSON fields>,
  created, title, attributes: {…} }` — `payload_json` is the authoritative field payload (the
  same fields the body blocks carried); `attributes` duplicates scalars for Linear-side
  filterability. Cards render human-readable (title = the block kind, subtitle = a salient
  field). Decode is `find_perk_attachment(nodes, kind=)` — absent → `None` (tolerant),
  present-but-malformed → raises (fail-loud); `has_perk_attachment` is the presence-only check.
- **The URL scheme is the identity** (live-verified: Linear accepts non-resolving URLs, and
  `attachmentCreate` **upserts by `(url, issueId)` with REPLACE metadata semantics** — every
  write must carry the complete envelope): `https://perk.invalid/plan/<run_id-or-identifier>`,
  `/learn/<run_id-or-identifier>`, `/node/<issue identifier>` (carry-path stable),
  `/objective/<run_id>`, `/manifest/<run_id>`. Writers always **reuse a found attachment's URL**
  (never re-derive — re-deriving would orphan the existing card).
- **O(1) finds via `attachmentsForURL`** (`find_issue_by_attachment_url`): `find_plan_issue` /
  `find_learn_issue` / `find_objective` are each ONE workspace-wide exact-URL query (no
  team-scoped label scans). **Open-only parity rule:** the issue-tier finds treat a hit in a
  terminal state (`completed`/`canceled`) as not-found — parity with the legacy open-only scan,
  so a landed plan's run_id never resurrects the closed issue. On **multiple** hits (a landed
  plan's closed issue + an open re-save sharing the URL) the find prefers the first
  **non-terminal** hit, so the parity filter is deterministic — never at the mercy of the
  server's node order. The objective find is
  state-independent by design (its sentinel is born canceled) and takes the project ref from the
  hit issue's `project` (a header hit with no project raises — a broken sentinel).
- **The project metadata sentinel.** Linear exposes no project-attachment mutation, so each
  perk project carries one **sentinel issue** (`Perk: objective metadata`, empty body, born in
  the team's canceled state — cosmetic; created **fail-loud** immediately after `projectCreate`,
  before milestones/node-issues) holding the `objective-header` + `objective-manifest`
  attachments. Discovery keys on the header **attachment**, never the title. One best-effort
  `entityExternalLinkCreate` adds it to the project's Resources (fail-open). Readers find it in
  the same `project_issues` scan they already run (zero extra queries); it is excluded from
  roadmap reads, engagement, and adoption candidate maps. `update_objective_header` /
  manifest syncs (`_sync_manifest_*`, `_refresh_manifest_phase_pins`, the drift backfill) are
  merge-and-upsert against the sentinel's attachments; a sentinel-less project is **not a perk
  objective** (`get_objective → None`).
- **Node-issues + unified plans.** The `objective-node` payload rides a `/node/<identifier>`
  attachment (descriptions are clean prose); a unified node-issue carries TWO envelopes — node +
  plan — disambiguated by `kind`. The node→plan backlink derivation is unchanged but now keys on
  the **plan-header attachment's presence**. Attachments cascade-delete with their issue.
- **Accepted create window (issue tier).** Every Linear create is now two writes — `issueCreate`
  then the identity-carrying attachment upsert — so a crash between them orphans a header-less
  issue invisible to the URL finds (a retry mints a fresh one; the orphan is human-visible
  garbage to close). The same accepted one-round-trip window as the metadata sentinel's,
  now explicit for plan/learn/node creates too.
- **The issue-tier protocol reshape (all backends).** `create_plan_issue(title, header_fields,
  run_id, dry_run)` replaces the pre-rendered `body` param — the backend owns the header carrier
  (GitHub renders the body block itself, byte-identical; Linear creates a clean empty body + the
  attachment). Two additive fields: `LearnIssueSummary.header: LearnHeader | None` (decoded
  backend-side; GitHub parses the body, Linear the attachment — degrade-to-None either way) and
  `AdoptableIssue.already_plan: bool` (backend-decided — GitHub `has_metadata_block(body,
  plan-header)`, Linear the plan-header attachment), consumed by `plan from`'s `already_a_plan`
  refusal.

## §8.25 · The human-engagement read contract (Objective #682, Node 1.2)

A backend-neutral **READ** surface for human engagement — comments, description edits, and
agent-session activities — added to **both** the `IssueBackend` (`issue_id`) and `ObjectiveStore`
(`objective_id`) seams. Implemented honestly on the **Linear issue backend** over GraphQL; every
other implementer ships a clean empty/no-op conforming impl (honest — **no flow consumers** wire it
in Node 1.2; the consuming flows arrive in Phase 2+). Anchored on the Node 1.1 inventory.

**Result dataclasses** (`perk/backends/engagement.py` — a pure module importing nothing from the
backend tiers, so both protocols + every implementer import it without re-coupling the deliberate
issue-tier ↔ objective-tier split). All frozen:

- `EngagementComment(id, body, created_at, edited_at: str | None, author)` — `edited_at` flags an
  edited comment.
- `DescriptionEdit(created_at, author, diff: str | None)` — `diff` is `None` when the backend
  exposes no inline diff (Linear's issue history carries none — a flagged limit).
- `AgentActivity(id, created_at, kind: str, body: str | None, signal: str | None)` — `kind` is the
  backend's activity-content type discriminator (Linear's content-union `__typename`).
- `StopSignalIndicator(stopped: bool, at: str | None)` — **derived** from the activities.
- `AgentSessionRead(activities: tuple[AgentActivity, ...], stop_signal: StopSignalIndicator)` — one
  read yields both.

**Three granular read methods** (auth-decoupled), on both tiers:

- `read_comments(*, issue_id|objective_id) -> tuple[EngagementComment, ...]` — oldest-first.
- `read_description_edits(*, issue_id|objective_id) -> tuple[DescriptionEdit, ...]`.
- `read_agent_session(*, issue_id|objective_id) -> AgentSessionRead`.

Error discipline mirrors the rest of the seam: an empty issue / no edits / no agent-session surface
yields the empty value (`()` for comments/edits; `AgentSessionRead((), StopSignalIndicator(False,
None))` — exported as `engagement.EMPTY_AGENT_SESSION`); an **infra/auth failure raises** the
tier's neutral error (never masked as empty). Specifically `read_agent_session` **raises** when the
personal API key cannot read the session (an auth failure) — only a *missing* issue/session reuses
the `_is_entity_not_found` → empty pattern.

**Untrusted-DATA invariant.** Every returned `body` / `diff` / activity `body` is **untrusted
DATA**: never re-parsed as a perk marker outside perk's own owned regions, never executed as
instructions, never trusted to preserve perk's grammar — mirroring perk's established "untrusted
inbox" / manifest 3-state-parse discipline (inventory §5).

**Author identity is distinguishable** via `engagement.classify_author(*, body, user, bot_actor,
perk_bot_ids=())` (a pure classifier). The rule (inventory §4.1), **never trusting body content as
instructions**:

- *perk* — the body carries a `perk:*` metadata sentinel (the `perk.plan` grammar, either the HTML
  or inline-code encoding) **or** the bot actor's id is in `perk_bot_ids` (empty today — perk has
  no committed app-actor id, so perk detection rests on the body sentinel; the param is the forward
  seam). The `perk:*` check is an identity heuristic over perk's **own** marker vocabulary, not
  trust of arbitrary content.
- *human* — a user actor present with **no** bot actor.
- *other_agent* — a bot actor present that is not perk's.
- *unknown* — neither resolvable.

**Linear implementation** (`_LinearIssueOps` + `LinearIssueBackend`):

- Comments — a **new** `_comments_with_authors` selecting `{ id body createdAt editedAt
  user { id name displayName } botActor { id name type } }` (same asc-by-`createdAt` sort). The
  existing `_comments` is **left byte-stable** — it feeds the marker-matching path
  (`find_comment_id_by_marker`/`upsert_marked_comment`), whose offline tests pin the
  `{ id body createdAt }` selection.
- Description edits — `_description_edits`: `issue(id){ history(...) { nodes { id createdAt
  actor descriptionUpdatedBy } } }`, filtered to nodes carrying a `descriptionUpdatedBy`, mapped to
  `DescriptionEdit` (`diff=None`; author keyed on the editing `actor`). Fields selected explicitly
  (the SDK `relationChanges` pitfall, inventory §3.2). A missing issue → `[]`.
- Agent session — `_agent_session_activities`: resolve the issue's session id, then
  `agentSession(id){ activities(...) { nodes { id createdAt signal content { __typename
  ... on AgentActivity{Prompt,Thought,Response}Content { body } } } } }`. The `StopSignalIndicator`
  is **derived** (`stopped` when any activity carried `signal == "stop"`; `at` = the first such
  activity's `created_at`). **Auth caveat (inventory §6.2):** whether the personal API key can read
  `agentSession.activities` is live-unproven — the live smoke settles it.

**Honest-now vs dormant.** `LinearIssueBackend` is honest. `GitHubIssueBackend` is now honest for
comments + description edits (Node 1.3), both via read-only `gh api graphql`: comments from
`IssueComment` (`lastEditedAt` → the `edited_at` flag; `author { __typename databaseId login }` →
the bot/human discriminator + opaque id), description edits from `Issue.userContentEdits`
(`editedAt` / `editor` / a best-effort `diff` — GitHub may return null). `gh api graphql` does not
auto-template `{owner}/{repo}`, so the queries pass explicit `owner`/`name`/`number` variables
(cursor-paginated); a not-found issue folds to `()`. `perk_bot_ids` stays empty (perk has no
committed GitHub app actor — perk-authored content is detected by its body sentinel). Agent
sessions stay a clean GitHub no-op (no agent-session surface). All objective stores
(`GitHubObjectiveStore`, the dormant `LinearObjectiveStore`, the live `LinearProjectObjectiveStore`)
ship empty — honest project-level reads land with their Phase-2 consumer (Node 2.3). Conformance is
ty-enforced across every implementer + fake (the whole-repo `ty check` oracle).

**No** new config key / command / door / provider in Node 1.2 → **no** `docs/user-docs/` or
`perk-expert` change (the user-facing surface arrives with the Phase-2 consumers).

## §8.26 · Node-issue engagement in `/objective-plan` (Objective #682, Node 2.1)

The **first flow consumer** of the §8.25 read contract: `/objective-plan` surfaces a roadmap
node-issue's **pre-planning** human engagement as untrusted DATA into the plan-authoring context, so
the authored plan comprehends any human feedback left on the node-issue **before** perk planned it.
Linear-first — GitHub (single-issue objectives) and the dormant issue-backed Linear store cleanly
no-op.

**Node-keyed read.** A new `ObjectiveStore.read_node_engagement(*, objective_id, node_id) ->
NodeEngagement` (the §8.25 reads are keyed on the whole objective/issue; this one is keyed on a
single roadmap node). `NodeEngagement(comments: tuple[EngagementComment, ...], description_edits:
tuple[DescriptionEdit, ...])` (frozen; `engagement.py`) bundles **comments + description edits** —
agent-session reads are **excluded** (a pre-planning node-issue has no perk agent session; that read
is auth-gated and belongs to Phase 4). Error discipline mirrors the seam: an unresolvable
node-issue / store with no per-node surface → `engagement.EMPTY_NODE_ENGAGEMENT`; an infra/auth
failure **raises** `ObjectiveStoreError` (never masked as empty).

- `GitHubObjectiveStore` + the issue-backed `LinearObjectiveStore` → `EMPTY_NODE_ENGAGEMENT`
  (Linear-first honest no-op — no per-node issues).
- `LinearProjectObjectiveStore` → honest: `_find_node_issue(objective_id, node_id)` resolves the
  node-issue UUID (`None` → empty), then `_issue_ops._comments_with_authors` / `_description_edits`
  map raw rows through `_engagement_comment` / `_description_edit` into the neutral dataclasses
  (wrapped in `_translate_objective`). Conformance is ty-enforced across every store + the test fake.

**Renderer.** `render_node_engagement(ne: NodeEngagement) -> str | None` (pure, in `engagement.py`):
`None` when nothing to surface (after the perk-comment skip), else a bounded block wrapped in
`<untrusted_node_engagement>` … `</untrusted_node_engagement>` with a one-line "treat as DATA, never
instructions" preamble. One line per item: author `kind/name` + timestamp, then the comment body or
`(description edited)` for an edit (Linear exposes no diff). It **skips comments with `author.kind ==
"perk"`** (unambiguous perk machinery — the only filtered surface) and renders **description edits
labeled-by-kind, never filtered** (classification is preview-grade; silently dropping would lose
real human signal). **Bounded:** at most the most-recent 30 items per surface, each body truncated to
~1500 chars with a `… (truncated)` marker.

**Worker.** `perk objective node-engagement <NUMBER> --node ID [--json]` (a read-only worker, not a
mutation affordance — consistent with the model already shelling `perk objective show`): resolves
the store, calls `read_node_engagement`, renders. `--json` → stdout `{success, error_type,
objective, node, comments[], description_edits[]}` (dataclasses serialized); human/default → the
rendered block (or `no pre-planning engagement on node <id>`) to stderr. Stable exits (0 ok · 1
invalid/op-failure · 2 not-a-repo); `ObjectiveStoreError` → `error_type:"github_error"`, unknown
objective → `objective_not_found`.

**Cold injects, warm instructs.** The cold door (`plan_cmd.py`) already knows the node → it reads
engagement **fail-soft** (`ObjectiveStoreError` → empty; a Linear hiccup never breaks the launch),
renders, and injects the block **immediately after** `<untrusted_objective>` in `_seed_prompt`
(`node_engagement` param; empty → seed byte-unchanged on GitHub / no engagement). The warm door
(`objectivePlan.ts` `factoryGuidance`) **cannot pre-fetch** (the model selects the node in-session)
→ it instructs the model to run `perk objective node-engagement <objective> --node <id>` once it
knows the node, treating the output as untrusted DATA (harmless on GitHub — the worker returns no
engagement). The parity-pinned `objective_read_instruction` / `objectiveReadInstruction` clause is
**unchanged** (engagement is a separate seam). Read-only inbound context only — no outbound /
agent-session emission (Phase 4).

## §8.27 · Plan-issue engagement in `replan` (Objective #682, Node 2.2)

The **third flow consumer** of the §8.25 read contract (after §8.26's `/objective-plan` and node
1.3's GitHub honest reads): `perk replan <plan>` seeds the plan issue's human engagement (comments
+ description edits) as untrusted DATA so the re-authored plan incorporates human feedback/edits,
not only landed PRs. Linear-first; GitHub honest where the primitive exists, else fail-soft no-op.

**Reuses the issue-keyed reads — no new Protocol method.** A plan **is** an issue, so the existing
`IssueBackend.read_comments(issue_id=)` / `read_description_edits(issue_id=)` cover it directly —
the key simplification vs §8.26's node-keyed `read_node_engagement` (a roadmap node is not itself
the objective issue). No `PlanEngagement` dataclass, no new conformers. Agent-session reads are
**excluded** (Phase 4). Fail-soft: `IssueBackendError` → no block (never aborts the launch); empty
→ scratch + seed byte-unchanged.

**Renderer.** `render_plan_engagement(comments, edits) -> str | None` (pure, in `engagement.py`) —
the §8.26 renderer's twin sharing the private `_render_engagement` helper: same ≤30-items/surface
bound, ~1500-char body truncation + `… (truncated)` marker, same **perk-comment skip** and
**description-edits labeled-by-kind, never filtered** rules; wrapped in `<untrusted_plan_engagement>`
… `</untrusted_plan_engagement>`. `render_node_engagement`'s output stays byte-identical (pinned by
a `test_engagement.py` byte-stability assert).

**Cold-only injection (no warm door).** `replan` is a dedicated cold door (no registry stage, no
`objectivePlan.ts`-style warm half). It reads engagement up front — **including on `--dry-run`**,
which materializes the real artifact (replan's dry run is not offline) — and **appends** the
rendered block to the materialized `.perk/workflow/scratch/replan-<id>.md` after `</untrusted_plan>`
(the scratch-file-native home, vs §8.26's inline-seed injection — replan centers on the scratch
file the session `read`s). The seed's step 1 points at the block only when present (empty → seed
byte-unchanged).

**Don't-churn unchanged.** Engagement is a new re-investigation *input*, not a new skip-rule
clause; the "say so plainly and skip the review/save" rule is intact — its canonical carrier is
the replan **seed** (`prompts/stages/replan.md`, the launch statement's no-op exit arm; §8.57).

## §8.28 · Objective + node-issue engagement in `/objective-reconcile` (Objective #682, Node 2.3)

The **fourth flow consumer** of the §8.25 read contract (after §8.26's `/objective-plan`, node
1.3's GitHub honest reads, and §8.27's `replan`): the post-merge `/objective-reconcile` pass
comprehends **human engagement on the objective + its node-issues** (comments + description edits)
as untrusted DATA, not only the landed PR diff. The section-boundary discipline (only the
marker-bounded **Reconcilable** prose region is rewritten) and the skip-if-nothing-stale rule are
unchanged. Linear-first; GitHub honest where the primitive exists.

**Honest objective-keyed reads (no new Protocol method).** The §8.25 objective-keyed
`read_comments` / `read_description_edits` — empty stubs since 1.2 — become honest:

- **GitHub** (`GitHubObjectiveStore`): the objective IS a single issue, so `read_comments` /
  `read_description_edits` reuse `github.read_issue_comments` / `github.read_description_edits` +
  the shared `issues.py` mappers (`_engagement_comment` / `_description_edit`) over the objective
  issue. `read_node_engagement` stays a clean no-op (single-issue objective — no per-node issues).
- **Linear** (`LinearProjectObjectiveStore`): `read_comments` is honest over the **Linear
  project's comments** (`_LinearProjectOps._project_comments`, an author-aware cursor-paginated read
  mirroring the issue `_comments_with_authors` selection, oldest-first); `read_description_edits`
  stays an honest **empty** `()` — Linear projects expose no description-edit-history primitive
  analogous to issue `history.descriptionUpdatedBy` (the edit signal lives on the node-issues, which
  the per-node sections carry — a flagged preview-grade deferral, live-proven at node 4.3). The
  dormant issue-backed `LinearObjectiveStore` reads are unchanged.

**Project Updates are NOT read.** Linear Project Updates (`projectUpdates`) are perk's own outbound
status feed (`post_status_update` posts them on create/land/reconcile), so reading them back would
surface perk's own bookkeeping — explicitly declined. Node 2.3 surfaces project **comments** (human
discussion) + node-issue comments/edits only.

**Per-node reuse.** The worker composes the existing node-keyed `read_node_engagement` (§8.26)
looped over **every** roadmap node (reconcile rewrites the whole roadmap prose, so feedback on any
node-issue is relevant; empty per-node surfaces are skipped). Accepted cost: on Linear each
`read_node_engagement` re-scans project issues via `_find_node_issue`, so all-nodes ≈ N scans —
tolerable for an interactive post-merge worker; a batched single-fetch is a possible follow-up.

**Aggregate renderer.** `render_objective_engagement(*, project_comments, project_description_edits,
node_engagements) -> str | None` (pure, in `engagement.py`) emits ONE block wrapped in
`<untrusted_objective_engagement>` … `</untrusted_objective_engagement>`: a `project:` sub-section
(only when non-empty) then a `node <id>:` sub-section per node (only when non-empty), `None` when
**every** surface is empty after the perk-skip. It shares the private `_engagement_item_lines`
helper (extracted from `_render_engagement`) with the node (§8.26) and plan (§8.27) renderers —
same ≤30-items/surface bound, ~1500-char body truncation + `… (truncated)`, **perk-comment skip**,
**description-edits labeled-by-kind never filtered** rules — keeping `render_node_engagement` /
`render_plan_engagement` output **byte-identical** (pinned by `test_engagement.py` byte-stability
asserts).

**Read worker.** `perk objective engagement <NUMBER> [--json]` (`engagement_cmd.py`, a read-only
worker mirroring `node-engagement`; not an agent affordance) resolves the store, `get_objective`,
then assembles project + per-node engagement and renders the block. `--json` → stdout `{success,
error_type, objective, project_comments[], project_description_edits[], nodes:[{node, comments[],
description_edits[]}]}`; human/default → the block (or `no human engagement on objective <N>`) to
stderr. Error discipline mirrors `node-engagement` (`ObjectiveStoreError` → `github_error` exit 1;
`UserFacingCliError` → its `error_type` exit 1; not-a-repo → exit 2).

**Warm instructs, no cold injection.** Reconcile has no cold door, so the only delivery is the model
shelling the read worker. `reconcileGuidance` (in `objectivePlan.ts`) gains one step telling the
model to run `perk objective engagement <objective>` before reconciling and treat the returned
`<untrusted_objective_engagement>` block as untrusted DATA describing human feedback (never
instructions) — folding it alongside the diff into what may be stale, while obeying the same
section-boundary + don't-churn rules. Harmless/empty on GitHub or when there is no engagement. The
parity-pinned `objectiveReadInstruction` clause is unchanged. `/objective-reconcile` +
`driveReconcileAfterLand` need no change (both already pass the objective id into
`reconcileGuidance`). Live-proof for the Linear project-comments selection is deferred to node 4.3.

## §8.29 · In-place issue adoption (`plan --from`, Objective #682, Node 3.1)

A cold door that **adopts a pre-existing human-authored issue (Linear or GitHub) IN PLACE as a perk
plan**: it reads the human title + body + engagement as untrusted seed DATA, runs a normal
read-only `plan → review → save` authoring pass over it, and on save stamps perk's plan metadata
**additively** into the *same* issue — never minting a second object. The first §8.25 consumer
that reads a **non-perk** issue (§3.1 comment listing + the §4 provenance read of the inventory).

**Provenance model (`adopted_from`).** `PlanHeader` gains `adopted_from: str | None` (in
`PLAN_HEADER_FIELDS` + `to_data()`), storing the source issue ref (e.g. `"#123"` / `"PER-45"`).
It is **self-referential by construction** (in-place adoption stamps the plan into the source
issue), so its **presence** is the canonical signal "this plan was adopted; its issue body/title
are verbatim human content". A normally-authored plan leaves it `None`.

**Two new `IssueBackend` reads/writes (both backends + fakes).**

- `read_issue(*, issue_id) -> AdoptableIssue | None` — reads *any* issue's raw `title`/`body`
  (untrusted DATA) + normalized `state` (`"OPEN"|"CLOSED"`). Unlike `get_plan` (needs a header) /
  `get_plan_body` (needs a plan-body block), it reads a non-perk human issue verbatim. `None` when
  absent; raises `IssueBackendError` on infra failure. GitHub: `gh issue view … --json …`; Linear:
  `issue(id:)` mapped to the neutral shape.
- `adopt_issue_as_plan(*, issue_id, header_fields, plan_markdown, callout, command, dry_run) ->
  IssueRef` — the in-place additive stamp (mirrors `ObjectiveStore.save_node_plan`): (a) ensure +
  **add** the `perk:plan` label (never replaces the issue's existing labels); (b) stamp the
  `plan-header` block additively into the issue **body** (human prose preserved verbatim, **title
  untouched**); (c) idempotently prepend the `perk impl <id>` callout above the body; (d) upsert
  the `plan-body` comment carrying the authored markdown. Returns `IssueRef(existed=True)`.
  Idempotent on re-save; GitHub stamps the body block HTML-encoded; Linear upserts the
  plan-header **attachment** instead — the human body stays verbatim apart from the callout
  (the §8.24 native-attachment metadata amendment).

**The cold door (`perk plan from <issue>`).** A dedicated launcher verb in the `plan` hybrid group
(mirrors `replan`/`resume`; `from` is a valid Click command string). It performs every Linear/GitHub
read up front (the read-only plan-mode session has no `gh`/Linear access), then re-launches the
`plan` stage seeded to author a plan over the materialized source. It **refuses** when: the issue is
not found (`adopt_not_found`), not OPEN (`adopt_not_open`), or already a perk plan
(`AdoptableIssue.already_plan` — backend-decided: GitHub the body block, Linear the plan-header
attachment → `already_a_plan`, hinting `perk plan replan <id>`).
Engagement is read fail-soft (`render_adopted_engagement` → `<untrusted_adopted_issue_engagement>`;
`IssueBackendError` → omitted). The source is materialized to `scratch/adopt-<issue_id>.md` (title +
body wrapped in `<untrusted_adopted_issue>` + the optional engagement block). A **fresh** `run_id`
is minted (vs `replan` reusing the original); the default `binding_trigger` (`stage:plan`) fires the
`perk-plan` nudge. `--dry-run` materializes + prints the seed, launches nothing (reads are real,
like `replan`). `--remote` is rejected (local-only, resolved up front).

**The save (rides the handoff).** The `plan from` door stashes `adopt_from` in the run **handoff**,
so the adoption link survives **every** save surface (the `/plan-save` command, the `plan_save`
tool, approval-driven save — all forward only `{plan, title}`). `perk plan save` gains
`--adopt-from <issue>` + `_adopt_from_handoff` recovery (explicit flag wins, else the handoff key).
When set on a real save, `_plan_save_impl` sets `header.adopted_from`, calls
`adopt_issue_as_plan(...)`, **skips** `create_plan_issue` (`updated=True`, `labels=(perk:plan,)`,
`cache.plan-ref.pr_id = adopt_from`). **Mutual exclusion:** `--adopt-from` with
`--objective-id`/`--node-id` is rejected (`invalid_input`) — the node-unification path is the
in-place writer for objective nodes; the two in-place semantics never mix. `--dry-run` composes +
prints the header/body (now including `adopted_from`) without writes.

**Doctor (awareness note, not a check).** An adopted plan is identified by a populated
`adopted_from` plan-header field; `doctor` does **not** rewrite or validate the human prose/title —
the substantive deliverable is this contract section, not a new validating check.

**Backend parity.** Honest on **both** GitHub and Linear (+ clean fake conformers). Live validation
is a preview-grade observation here (Mode 7); final live
proof is node 4.3.

## §8.30 · In-place objective adoption (`objective author --from`, Objective #682, Node 3.2)

The **objective-level analog of §8.29**: it adopts a **pre-existing human source** — a Linear
**Project** (and its issues) or a GitHub **issue** — IN PLACE as a perk objective. It reads the
human prose + existing issues as untrusted seed DATA, runs a normal read-only objective-authoring
pass, and on save stamps perk's objective metadata **additively** into the *same* source, mapping
existing issues to roadmap nodes where the author chose, and **never minting a second
project/issue**. Linear is the first-class path (project + child issues); GitHub is bounded (single
issue, no children).

**Surface.** A `--from <source>` **flag on `objective author`** (not a new `objective from` verb —
an accepted divergence from §8.29's `plan from` verb): it keeps `objective author` the single
authoring entry point and matches the node title. When `--from` is absent the door is byte-unchanged
(the existing authoring seed).

**Provenance model (`adopted_from`).** `ObjectiveHeader` gains `adopted_from: str | None` (in
`OBJECTIVE_HEADER_FIELDS` + `to_data()`), storing the **source ref**: a Linear project UUID
(projects have no human identifier) or a GitHub issue ref (`"#<n>"`). Self-referential by
construction; its **presence** is the canonical signal "this objective was adopted; the
`Adopted-from` Immutable note holds the original human content". A normally-authored objective
leaves it `None`.

**The mapping carrier (`adopt_issue` + `parse_adopt_mapping`).** An optional per-node `adopt_issue`
field on the structured roadmap maps a node to an **existing** project issue (its id/identifier). It
is carried **separately** from `ObjectiveNode` (which stays pristine — used pervasively in
rendering/manifest/drift): the pure `objective.parse_adopt_mapping(raw) -> dict[str, str]` extracts
`{node_id: source_issue_id}` from the same raw roadmap shape `parse_structured_roadmap` accepts. The
TS `ROADMAP_PARAM_SCHEMA` (`additionalProperties: false`, shared by `objective_save` +
`objective_draft`) gains `adopt_issue` so the field is not rejected at the tool boundary; `roadmap`
flows through as `unknown[]`, so the field survives unchanged to the Python cold door.

**The verbatim-preservation model.** Decisions: (4) the model authors the objective's Reconcilable
prose (the human source prose is seed DATA); (5) the source's **original** overview/body is captured
verbatim into an `Adopted-from` **Immutable** archive note appended **below** the closing
Reconcilable marker (`objective.render_adopted_overview_note`, a perk HTML-comment marker that
round-trips through `to_linear_markdown` → inline-code; empty `original` → `""`), never rewritten by
reconcile. Mapped issues' titles/bodies are independently preserved verbatim by the additive
`objective-node` block stamp.

**The adoptable-source read contract (two new `ObjectiveStore` methods + result shapes).**

- `AdoptableSourceIssue` (`id`, `identifier`, `url`, `title`, `body`) — one pre-existing project
  issue (untrusted DATA). `AdoptableObjectiveSource` (`id`, `url`, `title`, `prose`, `issues`) —
  the source overview/body + its existing issues (`issues` empty on GitHub).
- `read_objective_source(*, source_id) -> AdoptableObjectiveSource | None` — reads *any*
  pre-existing source (Linear project / GitHub issue) verbatim for adoption (the objective-tier
  twin of `IssueBackend.read_issue`). `None` when absent; raises on infra failure. Returned even
  when CLOSED — the cold door does the not-open refusal. A store with no project-source surface
  (the dormant issue-backed Linear store) returns `None`.
- `adopt_source_as_objective(*, source_id, title, prose, run_id, status, base, roadmap_nodes,
  adopt_map, dry_run) -> ObjectiveRef | None` — stamps perk's objective metadata **additively** into
  the source IN PLACE. Returns the source's `ObjectiveRef` (`existed=True` on idempotent re-save via
  `run_id`); returns **`None`** for a store that does not support in-place adoption (the dormant
  issue-backed Linear store — the unambiguous "doesn't adopt" signal, mirroring `save_node_plan →
  None`). `dry_run` returns `None` (the source read is a network op; the cold door's `--dry-run` is
  offline). An empty roadmap raises (the storage backstop).

**Backend matrix (three implementers + fakes, ty-enforced).**

- **GitHub (bounded single-issue):** `read_objective_source` maps `github.read_issue` to the neutral
  source (`prose` = issue body, `issues=()`). `adopt_source_as_objective` → `github
  .adopt_issue_as_objective` (mirrors `create_objective_issue` + `adopt_issue_as_plan`): idempotency
  via `find_objective_issue(run_id=)`; read the issue body verbatim; compose `<human body verbatim>`
  + `objective-header` (`adopted_from="#<n>"`, `objective_comment_id: null`) + `objective-roadmap`
  blocks, **add** the `perk:objective` label (never replace), title untouched; post the
  `objective-body` comment (`render_body_comment(nodes, prose=<model prose>)` + the
  `render_adopted_overview_note(<original body>)` below the Reconcilable markers + the
  `perk objective plan <n>` callout prepended), backfill `objective_comment_id`. `adopt_map` is
  ignored (no child issues).
- **Linear project-backed (full):** `_LinearProjectOps.project_issues_for_adoption` (a sibling of
  `project_issues` selecting `title` too; both selections now also carry the attachment nodes —
  the §8.24 native-attachment metadata amendment).
  `read_objective_source` → the project overview `content` + its issues (the metadata sentinel
  excluded). `adopt_source_as_objective` composes the new overview preserving the original
  verbatim (`to_linear_markdown(` Reconcilable(`<model prose>`) +
  `render_adopted_overview_note(<original overview>)` below the markers `)`), `update_project
  _content` (in place, NOT `create_project`), prepends the callout; the
  `objective-header`(`adopted_from=source_id`) + `objective-manifest` ride a fresh metadata
  sentinel's attachments (the §8.24 native-attachment metadata amendment); one milestone per
  phase via `ensure_phase_milestone` seeded from `project_milestones` (de-dupe against existing);
  for each node in `node_sort_key` order a **mapped** node upserts the `objective-node`
  attachment onto the existing issue (title/body verbatim — no description write — +
  `perk:objective-node` label added + phase-milestone attach), an **unmapped** node mints a fresh
  node-issue; blocking relations per explicit `depends_on`. Raises on an `adopt_issue` id not in
  the project (fail-loud). Idempotent on `run_id`.
- **Issue-backed Linear (dormant):** both `read_objective_source` and `adopt_source_as_objective`
  return `None` (honest no-op; keeps `ty` green).

**The cold door (`perk objective author --from <source>`).** Reads the source up front
(`require_github`; the read-only session has no Linear/`gh`), then re-launches the
`objective-author` stage seeded to author over the materialized source. It **refuses**:
`adopt_not_found` (source `None`); GitHub-only `adopt_not_open` (the source issue is CLOSED, via the
issue tier's `read_issue.state` — skipped for Linear projects, which have no OPEN/CLOSED);
`already_an_objective` (the source prose already carries an `objective-header` block);
`adopt_unsupported` (a `None` adoption return — in practice the resolver never returns the dormant
store). Project-level engagement is read fail-soft (`render_adopted_engagement(comments, ())` →
`<untrusted_adopted_issue_engagement>`; `ObjectiveStoreError` → omitted; per-issue engagement is
Node 4.3's live concern). The source is materialized to `scratch/objective-adopt-<source_id>.md`
(title + prose in `<untrusted_adopted_objective>` + a `<untrusted_adopted_project_issues>` listing +
the optional engagement block). The seed instructs the model to author the prose + roadmap, mapping
existing issues via each node's `adopt_issue`. `--dry-run` materializes + prints the seed, launches
nothing; `--remote` is rejected (local-only, resolved up front).

**The save (rides the handoff).** The door stashes `adopt_from` in the run **handoff**, so the link
survives the `objective_save` tool path (which forwards only `{prose, roadmap, title, base,
run-id}` — no TS tool change for `adopt_from`). `perk objective create` gains `--adopt-from
<source>` + `_adopt_from_handoff` recovery (explicit flag wins, else the handoff key). On a real
save it parses `adopt_map = parse_adopt_mapping(raw)` from the same `--roadmap` JSON and calls
`adopt_source_as_objective(...)`, **skipping** `create_objective`; a `None` return →
`adopt_unsupported`. The fail-open `post_status_update` on fresh-create still fires (adoption
produces a fresh perk objective, `existed=False`). `--dry-run` falls through to the offline
`create_objective(dry_run=True)` compose-preview (the writer returns `None` on dry-run). No
mutual-exclusion guard is needed (`objective create` has no `--node-id`).

**Backend parity.** Honest on **both** GitHub and Linear (+ clean fake conformers). Live validation
is preview-grade here (Mode 8); final live proof is Node
4.3 — no new config key, provider seam, or `EXPECTED_SURFACE` change (a flag, not a new
command/verb).

## §8.31 · The prompt render seam + golden parity (Objective #791, Node 1.2)

Two cross-plane **render seams** load prompt templates by explicit `name` (root-relative under
`prompts/`, located via the node-1.1 resolvers `prompts_dir()` / `promptsDir()`) and render them
with a small, fixed feature surface — `{{ var }}` substitution, `{% include %}`, and
`{% if %}`/`{% elif %}`/`{% else %}` conditionals with string equality (`==`) and `and`/`or`/`not`
(no loops). This surface is **frozen** as the canonical mini-jinja subset, cataloged exactly in
"The frozen template-grammar subset" subsection below and enforced by a cross-plane conformance
guard. Every later node in this objective rides on this mechanism.

**A template may be single-plane.** Two render seams exist (jinja2 on Python, vendored mini-jinja
on TS), but a given *template* may be consumed in production by only one plane — e.g. a
warm-door-only or cold-door-only injected seed/guidance prompt. `prompts/` is the canonical home
for **every** externalized prompt string, single- or cross-plane; `live.yaml` renders **every**
template on **both** engines and asserts byte-equality regardless of the production consumer, so a
single-plane prompt still rides cross-engine parity for free (a portability guarantee that costs
nothing, the subset being shared).

- **Python:** `perk/prompts.py::render(name, variables)` over a module-level jinja2 `Environment`.
- **TS:** `extension/substrate/prompts.ts::render(name, vars)`, delegating to the vendored,
  zero-dependency `extension/substrate/miniJinja.ts` renderer (the frozen-subset engine that
  replaced nunjucks). The seam is LIVE on both planes: `render` is imported by the worker, the
  learn/address/learnFactory/lifecycleGates doors, the warm pr-review / submit / objective-save /
  objective-reconcile doors, the objective-plan factory, the tool-gating read-only mode context,
  the plan/objective authoring contexts, the three provider-adapter shims
  (tombell / plannotator / juicesharp), and — on the Python side — the cold
  plan-from / replan / objective-author / objective-replan doors. The seven injected mode/bridge
  contexts (the persistent `before_agent_start` injections stripped on `context`, each injection
  **dedup-guarded by a branch scan on its marker** — `branchCarries` in
  `extension/substrate/workflowState.ts` — so a session carries ONE live copy of each context;
  compaction dropping a copy naturally re-injects it) live under
  `prompts/contexts/` — the mode contexts at the top level, the adapter bridges under
  `prompts/contexts/adapters/` — with each module's identity marker passed as the `{{ marker }}`
  render var (never a template literal), so the marker the strip handler scans for cannot drift
  from the injected prose; the marker-as-render-var invariant now serves both the strip **and**
  the dedup key (plannotator's two flavors share one customType but dedup per-flavor on their
  distinct markers).

**Fail loudly on a missing var.** jinja2 uses `StrictUndefined` (raises `jinja2.UndefinedError`);
the vendored `miniJinja` renderer matches it — a referenced name that is **absent OR non-string**
throws (`perk mini-jinja: …`). This deliberately tightens nunjucks's looser `throwOnUndefined` (and
forbids a `String(value)` divergence): the render contract is string-only, so a missing required
variable — or a boolean/number/null — is an error, never an empty or coerced string. **The
string-only contract is enforced on BOTH planes:** the TS renderer throws lazily on a referenced
non-string; `perk/prompts.py::render` validates the whole var map eagerly (raising `TypeError`)
before delegating to jinja2.

**jinja2 is the reference engine — verification is two decoupled tiers.** The cross-plane render
seam is held in lockstep by two tiers that separate the frozen *contract* from real prompt *prose*:

- **Tier A — contract snapshots (golden, sui generis).** `prompts/_fixtures/cases.yaml` lists
  `(template, vars, golden)` cases over a small catalog of purpose-built FIXTURE templates under
  `prompts/_fixtures/templates/`, each isolating one feature of the frozen render contract
  (variable substitution, `{% include %}`, `if`/`else`, `elif` chain, `==`/`and`/`or`/`not`,
  `trim_blocks` block-tag-on-own-line vs inline, trailing-newline preservation, no-trailing-newline
  fragment). The committed golden files under `prompts/_fixtures/golden/` ARE jinja2's rendered
  output for these fixtures; `tests/test_prompts.py` asserts `jinja2-render == golden` and
  `extension/substrate/prompts.test.ts` asserts the vendored mini-jinja render `== golden`. These
  goldens are stable — they change only when the render **contract** changes, never when a real
  prompt's prose changes. Golden outputs are **separate committed files** (not inline multiline
  YAML) because the TS harness reads `cases.yaml` through the vendored `miniYaml` reader, which
  throws on `|`/`>` block scalars.
- **Tier B — live cross-engine equality (no goldens).** `prompts/_fixtures/live.yaml` lists every
  **real** template with representative vars and **no** `golden:` field. The Python-owned
  `tests/test_prompt_parity.py` renders each real template with jinja2 natively, shells out once to
  the dev-only node renderer `extension/testing/renderLive.ts` (which renders the same manifest with
  mini-jinja and prints a JSON array in manifest order), and asserts the two outputs are byte-equal
  per template — so editing a real prompt's prose touches **no** fixture. A coverage guard
  (`test_live_manifest_covers_every_real_template`) asserts every real template appears in
  `live.yaml`, so a newly-added prompt can't silently skip Tier B. The renderer lives under
  `extension/testing/` so it is excluded from the npm tarball yet still typechecked/linted, and is
  never picked up by `node --test` (it is not a `.test.ts`); the parity test **skips** when `node`
  is absent.

The frozen subset is "the jinja subset"; the vendored TS renderer reproduces jinja2's bytes for both
tiers. Fixture and manifest vars are strings only (matching the string-only render contract, which
also sidesteps any non-string rendering divergence); both `cases.yaml` and `live.yaml` are authored
in the dual-parseable miniYaml subset (block maps/seqs, double-quoted strings, no `|`/`>` block
scalars).

**Environment-config parity baseline** (both engines): `autoescape` off (prompts are plain text,
never HTML-escaped), `trim_blocks` **on** (as of Node 2.4) so a block tag on its own line emits no
spurious newline — conditional templates keep their `{% %}` tags off the content lines while
preserving the content's own indentation — `lstrip_blocks` off, and jinja2 `keep_trailing_newline`
on so jinja2 does not strip a trailing `\n` (the vendored TS renderer never strips one) — required
for byte-parity. (`trim_blocks` only affects block-tag templates — `stages/learn.md`,
`stages/objective-plan/{seed,guidance}.md`, and the `with_include` fixture; the remaining arm
templates use `{{ var }}` only and are unaffected.) The vendored renderer **bakes these in** — the
subset is frozen, so there is no config object.

**Dependencies:** `jinja2` is the Python runtime dependency and the reference engine. The TS plane
has **zero runtime dependencies**: the former lone runtime dep (`nunjucks`) is replaced by the
vendored, zero-dependency `extension/substrate/miniJinja.ts` renderer, restoring the
bare-clone-loadable / zero-runtime-dependency invariant. That invariant is durably guarded by
`extension/bareImportGuard.test.ts` (no shipped source imports a bare npm package) and
`tests/test_packaging.py::test_no_runtime_dependencies` (`package.json` declares no runtime
`dependencies`).

**The frozen template-grammar subset (the node-4.2 renderer's input contract).** The construct
surface actually used across every `prompts/` template is **frozen** as the canonical "mini-jinja"
subset — the input contract the vendored zero-dependency TS renderer (node 4.2) must implement
exactly and throw loudly outside of. It is exactly four categories:

1. **Variable substitution** — `{{ <ident> }}` where `<ident>` matches `^[A-Za-z_][A-Za-z0-9_]*$`.
   Nothing else inside `{{ }}`: no filters (`|`), no dotted/attribute access, no parentheses, no
   literals, no operators.
2. **Include** — `{% include "<path>" %}`, double-quoted root-relative path only.
3. **Conditionals** — `{% if <cond> %}` / `{% elif <cond> %}` / `{% else %}` / `{% endif %}`,
   where `<cond>` is built only from bare identifiers (truthiness), double-quoted string literals,
   the `==` operator, and the keywords `and`, `or`, `not`. `and` is admitted for boolean
   completeness (and/or/not) even though only `or`/`not` appear in templates today.
4. **Whitespace control** — plain `{% %}` tags only. The `{%- … -%}` / `{{- … -}}` markers are
   **not** in the subset; tag-line stripping is achieved by the render-env `trim_blocks` flag
   (specified in the "Environment-config parity baseline" paragraph above, not restated here).

Everything outside (1)–(4) is **outside the subset** — `{% for %}`/`{% endfor %}`, `{% set %}`,
`{% macro/block/extends/raw %}`, `{# … #}` comments, filters, attribute access, `!=`/`<`/`>`,
`in`, `is`, parentheses, numeric literals. The **conformance guard** enforces this in both planes
with an allowlist posture (fail on any block matching no recognized construct):
`tests/test_prompt_grammar.py` (Python) and `extension/substrate/promptGrammar.test.ts` (TS).
`shared/contracts.md §8.31` is the SSOT for the shared scan algorithm; the two guards mirror it.
The guard checks **construct membership only**, not if/endif nesting balance — structural balance
is already proven by the golden harness rendering every real template. Widening the subset later
(e.g. a future template needing `in` or parentheses) is a deliberate decision that amends this
subsection **and** both guards.

> **History.** The chronological per-node landing notes for this section (the seven
> "prompt moved onto the seam" entries, Nodes 2.1–2.7) live in
> [`contracts-history.md` §8.31](./contracts-history.md).

## §8.32 · Objective replan — the superseding re-author cold door (`objective replan`)

The objective analog of §8.27's plan-`replan`, but with a **different model**: where plan-`replan`
rewrites the plan IN PLACE (`plan_save` is an upsert keyed on `run_id`), objective-`replan`
**closes the old objective and creates a net-new one that supersedes it**. `create_objective` is
find-then-return idempotent on `run_id` (NOT an upsert — see §8.24's "objective_save is not an
upsert" residual), so an in-place objective rewrite has no storage primitive; the close-old/
create-new shape sidesteps that gap. The structural siblings are §8.27 (replan engagement) and
§8.30 (in-place adoption).

**Surface.** `perk objective replan <N>` — a **dedicated cold door** (a launcher, not a registry
stage) that *borrows* the `objective-author` stage for launch (exactly like `plan replan` borrows
`plan` and `objective author --from` borrows `objective-author`). It mints a **fresh** `run_id`
(the new objective is net-new — no `run_id_override`), refuses `--remote` (objective-author is
`cold_remote:false`), and refuses a not-found / already-superseded / non-OPEN (GitHub) objective
(`objective_not_found` / `objective_not_open`). `("replan", ())` joins the `objective` group in the
parity-smoke `EXPECTED_SURFACE`.

**The carry model.** Only the **unfinished** nodes carry forward (status ∈ {`pending`, `planning`,
`in_progress`, `blocked`}); `done`/`skipped` nodes stay as **history on the closed old objective**
(the new prose references the shipped phases). The cold door materializes the old objective's
title + prose (`<untrusted_objective>`) and the unfinished nodes
(`<untrusted_objective_unfinished_nodes>`) into a scratch file as DATA, seeds the review-first
flow (`objective_draft → plan_review`; an APPROVED review auto-saves via the
`objectiveApprovalSave` seam — `objective_save`/`/objective-save` stay the manual failsafe), and
stashes `supersedes=<OLD>` in the run
**handoff** so the link survives the save path (recovered by `_supersedes_from_handoff`, mirroring
`_adopt_from_handoff`). Objective + node-issue engagement is read fail-soft (`render_objective_engagement`).

**The lineage fields.** `ObjectiveHeader` gains `supersedes` and `superseded_by` (both
`str | None`, in `OBJECTIVE_HEADER_FIELDS` + `to_data()`): `supersedes=#<OLD>` on the NEW header,
`superseded_by=#<NEW>` on the OLD header. Bidirectional by construction; both `None` for a
normally-authored objective.

**The storage capability (`supersede_objective`).** A new `ObjectiveStore` method
(keyword-only, returns `ObjectiveRef | None`) joins the no-op-family Protocol pattern (3
implementers, ty-enforced; `None` = "this store doesn't support it", mirroring
`adopt_source_as_objective`). Semantics: create a net-new objective (idempotent on `run_id`)
carrying `supersedes`, then **close the old objective fail-open** (stamp `superseded_by`, post a
best-effort status update — create-new-first, close-old-last; a close failure never fails the
create — the §8.24 bookkeeping posture). `dry_run` → `None` (resolving the old objective needs a
network read; the cold door's `--dry-run` is offline); an empty `roadmap_nodes` raises.

**The §8.53 Protocol growth (deferred close).** `supersede_objective` carries keyword-only
`close_predecessor: bool = True`: `True` is the incremental path above, byte-identical;
`False` (the transfer protocol's arm) creates + carries WITHOUT any old-side stamp/close/
cancels, and its found-by-`run_id` arm is **convergent** instead of an early return — GitHub
heals a missing/vanished objective-body comment + the `objective_comment_id` backfill; Linear
re-materializes the manifest attachment, overview callout, milestones, each carried move
(idempotent re-move/re-stamp/re-attach), missing fresh node-issues, and missing dependency
relations. The extracted close side is the new Protocol method
`finalize_supersession(*, old_objective_id, new_objective_id) -> bool` — **raising** and
**idempotent** (a present matching stamp skips; a conflicting stamp raises; already
closed/completed/canceled converges; Linear additionally Cancels dropped still-open
node-issues), `False` from the dormant issue-backed store (the no-op-family signal).
`supersede_objective(close_predecessor=True)` wraps it fail-open — one implementation, two
postures.

**Transfer-aware routing.** The `--supersedes` dispatch performs §8.53's D1 classification
read first: only incremental→incremental takes the plain mutation above; a stacked
predecessor — or an incremental→stacked conversion — routes through the §8.53 transfer
protocol (which owns lineage copy-or-mint, prefix preservation, ownership transfer, deferred
close, and verification).

**Backend-specific carry-forward.**
- **GitHub** (a node is a row in one objective issue body): the new objective's roadmap rows are
  authored fresh; the old issue is closed. `carry_map` is ignored (no child issues).
  `objectives.supersede_objective_issue` extends `create_objective_issue` with a `supersedes`
  header field, then fail-open closes the old issue.
- **Linear project store** (a node *is* a live issue): `carry_map` (new-node-id →
  existing-node-issue-id) **moves** each carried node-issue into the new project
  (`issueUpdate(input:{projectId})`), re-stamps its `objective-node` block to the new node id, and
  re-attaches it to the new phase milestone (identity / open PRs / discussion preserved);
  non-carried nodes mint fresh. The old project: `superseded_by` stamped, **every dropped
  (un-carried) still-open node-issue Canceled** (state type ∉ {completed, canceled} →
  `_workflow_state_id("canceled")`), then marked complete. `done` node-issues are left untouched.
  Flagged not-live-proven (verify at the Linear smoke gate).
- **Issue-backed Linear store** (dormant): `supersede_objective → None` (the no-op-family signal).

**The dispatch carrier (`objective create --supersedes`).** Structurally symmetric to
`--adopt-from`: a `--supersedes` worker flag (recovered from the handoff via
`_supersedes_from_handoff`; explicit flag wins) parses the carry map via the reused
`objective.parse_adopt_mapping(raw_roadmap)` (the node→issue side-map, interpreted as **move**
semantics here) and calls `store.supersede_objective(...)`; a `None` return raises
`supersede_unsupported`. `--supersedes` and `--adopt-from` are **mutually exclusive** (`invalid_input`).

**Binding + skill.** `command:objective-replan → perk-objective-replan` (nudge) joins
`shared/bindings.yaml` (mirroring `command:objective-reconcile`) and `DELIVERABLE_COMMAND_TARGETS`
(it fires via the cold `binding_trigger="command:objective-replan"` override). The
`perk-objective-replan` skill is the re-author judgment layer (carry-only-unfinished, the
`adopt_issue` Linear move; the don't-churn rule's canonical carrier is the objective-replan
**seed** — §8.57), cross-referencing `perk-objective-author` for the objective prose + roadmap
structure and the decision-completeness bar. The warm plane is unchanged — `objective_draft`/`objective_save`'s
structured roadmap path already carries `adopt_issue` per node, and `supersedes` rides the handoff
exactly as `adopt_from` does, so no TS schema edit is needed.

## §8.33 · Local-file (and URL) seeding for the seed-from-source cold doors

*(`plan from` / `objective author --from` / `skills create --from`)*

Both adoption cold doors **also** accept a relative or absolute path to a local file. This is a
distinct **seed-from-file** mode, NOT in-place adoption: a file has no canonical backend identity,
so there is nothing to stamp perk's metadata into (the §8.29/§8.30 in-place model does not apply).

**Disambiguation (`seed_file.detect_seed_file`).** Both doors auto-detect an existing file
**before** any id parsing / backend read: `Path(arg).expanduser()` (relative resolves against the
invoking shell's cwd) — if it `is_file()`, file mode wins (using the `.resolve()`d path); otherwise
the arg falls through to the existing issue/source-id path **unchanged**. A non-existent path-like
arg (slash or not) always falls through (no new path-shape heuristics): `parse_plan_id` rejects
`/`-bearing ids as `invalid_input`, and a clean-but-unresolvable id errors `adopt_not_found` as
today.

**Behavior.** The file is read as untrusted DATA (`seed_file.read_seed_file`) and materialized into
a slash-free `seed-file-<safe-stem>-<hash8>.md` scratch (`seed_file.render_seed_file_scratch`; the
absolute-path SHA1 hash keeps two same-named files in different dirs from colliding), wrapped in an
`<untrusted_seed_file>` block. The read-only authoring session is primed with a file-mode seed
prompt; saving mints a **fresh** `perk:plan` / `perk:objective` issue via the normal create path —
**no `adopt_from` handoff, no `adopted_from` provenance, file untouched**.

**Surface.** File mode skips `require_github` (the only read is local; the backend write happens
in-session at save time, mirroring the bare authoring path) but keeps `require_repo` /
`require_config` (scratch dir + launch config) and the `--remote` rejection (local-only, same as the
doors it extends). Errors: `seed_file_error` (non-UTF-8 / unreadable / empty file). Stable exits
unchanged (`0` ok · `1` op-failure/refusal · `2` not-a-repo).

**Out of scope.** No in-place adoption of files (no backend identity), no change to `parse_plan_id`
/ the `adopt_from` handoff / `adopted_from` provenance / any §8.29/§8.30 machinery, no
directory/glob support (a single file only), no write-back to the seed file.

**`skills create --from` (third consumer + URL sub-mode).** `perk skills create NAME --from <SOURCE>`
reuses the same leaf. `SOURCE` is detected **URL-first, then file** (the disambiguation order
diverges from the doors above, which detect file-first then fall through to an id): an http(s) URL
(`seed_file.detect_seed_url` — `urlsplit(arg).scheme` in `{http, https}`) takes the **URL sub-mode**;
else an existing file (`detect_seed_file`) takes file mode; else a hard `seed_file_error` (no
id/adoption fall-through — a skill has no backend identity).

- **File mode** is identical to the doors above: materialized to an `<untrusted_seed_file>` scratch
  (written even on `--dry-run`, gitignored), the authoring session reads it as DATA, authoring a
  **fresh** skill.
- **URL sub-mode** diverges: the URL is **not** materialized to a scratch and there is **no network
  in the Python command** (no `require_github`). The command only scheme-detects and hands the URL
  to the write-capable authoring session, which fetches the `SKILL.md` **and any sibling
  `references/`/`scripts/`/linked files in-session** (it has fetch/web tools — read-write sessions
  are not tool-restricted), treats everything as DATA, and ports selectively. This keeps the door
  offline/fast and avoids GitHub-blob-HTML/raw-URL transforms in Python.

Both modes always produce a **fresh** skill (no in-place adoption / `adopt_from` / provenance — a
skill is not a backend object). `--dry-run` JSON adds `"from": <source>` and — file mode only —
`"scratch_path"`. This is a Python-only change (no TS plane); the authoring judgment lives in the
`perk-skill-author` skill.

## §8.34 · JSON Schema golden snapshots of the boundary models (Objective #943, Node 4.1)

perk's cross-plane machine surfaces are Pydantic boundary models (`perk/boundary.py`'s three roles).
Their `model_json_schema()` is committed as **golden snapshots** under `shared/schemas/` — their
function is making machine-surface shape changes reviewable in PRs via the drift test, not serving
as a runtime resource or a consumer-facing publication.

**What is snapshotted (19 top-level models, three categories).**

- **Shared-YAML parse contracts** (`LenientParseModel`) → `shared/schemas/contracts/`:
  `registry.schema.json` (`RegistryFile`), `bindings.schema.json` (`BindingsFile`),
  `providers.schema.json` (`ProvidersFile`).
- **Machine batch inputs** (`StrictInputModel` / `RootModel`) → `shared/schemas/inputs/`:
  `review-post-batch.schema.json` (`ReviewBatchInput`),
  `resolve-threads-batch.schema.json` (`ResolveThreadsBatch`),
  `handoff-arg.schema.json` (`HandoffArgInput`),
  `structured-roadmap-node.schema.json` (`StructuredRoadmapNode`).
- **`--json` output envelopes** (`OutputModel`) → `shared/schemas/outputs/`: `plan-save`,
  `pr-submit`, `pr-ready`, `pr-land`, `pr-feedback`, `pr-review-context`, `pr-review-checkout`,
  `pr-review-cleanup`, `learn-capture`, `learn-skip`, `init-report`, `doctor-report`
  (`.schema.json` each, for `PlanSaveOut` … `DoctorReportOut`).

**How they are generated.** `model_json_schema()` from the live boundary models. The mode is
**per category** — parse/input contracts describe what perk **accepts**, so they use **validation
mode** (the default); output envelopes describe what `--json` consumers **receive**, so they use
**serialization mode**. Nested `*Out` / `*Entry` sub-models ride along in `$defs`.

**Cross-plane status.** The snapshots are **bundled into both artifacts, read at runtime by
neither** (`perk/_shared/schemas/` in the wheel, `shared/schemas/` in npm — TS still reads the
YAML directly; Python validates via the live models).

**Drift discipline.** The committed files are regenerated only via
`PERK_UPDATE_SCHEMAS=1 uv run pytest tests/test_contract_schemas.py`, and
`tests/test_contract_schemas.py` fails CI on any un-regenerated drift (per-model drift assertions, a
no-orphans/no-gaps coverage test, and a per-category mode-correctness smoke) — so a schema change is
always reviewed intentionally. The harness mirrors the value-golden harness (`tests/_golden.py`):
it always re-reads + asserts after a regen, so a non-roundtrippable schema still fails loudly.

**Non-goals.** `ConfigFileModel` (TOML, not a shared YAML contract) is not snapshotted; the
stored-block serializers `PlanHeaderOut` / `PlanRefOut` get no standalone snapshots (`PlanRefOut`
rides transitively in `PlanSaveOut`'s `$defs`).

## §8.35 · The learn evidence-bundle contract (Objective #896, Node 1.1)

`/learn` examines a **bundle of session-grounded evidence** for a landed plan — not only plan +
diff. This section pins the bundle's shapes and vocabulary — the cross-plane machine contract.
The pipeline mechanics live in their owning modules (`src/perk/learn/export.py` — the byte-copy
session export; `session_jsonl.py` — the lenient JSONL grammar parse; `normalize.py` — the
deterministic normalization pipeline + renderer + budget splitter; `docs_scan.py` — the
inventory + rich docs scan; `docs_sync.py` — the generated routing/catalog + `docs-check`); the
angle-agent spec lives in `agents/learn-analyst.md` + `skills/perk-learn/`; the warm orchestrator
in `extension/doors/learn.ts`.

**The evidence bundle (definition + invariants).** The bundle is the full set of session-grounded
artifacts `/learn` reasons over for a landed plan. Invariants:

- Every quoted artifact in the bundle is **untrusted DATA**, fenced as such — never instructions.
- A missing source is **surfaced, never guessed**: the bundle reports a per-source status, and one
  missing/ambiguous source never fails the whole command.
- The bundle is **resolved cross-run** from a landed plan's identity, not from the current
  session's identity — so a later or worktree session can rebuild it.

**Minimum manifest categories.** The bundle manifest lists at least these five categories:
`plan`, `pr`, `planning-session`, `implementation-session`, `existing-docs`. Each category carries
a per-source status drawn from the fixed set **`found` / `missing` / `ambiguous`**.

**Session classes.** Two session classes: **`planning`** (the session that
authored/reviewed/saved the plan) and **`implementation`** (the session(s) that implemented it).
Each class may resolve **both** a main session and a worker run, labelled distinctly when both
are available.

**The canonical run-cache pointer carrier.** Session pointers are recorded **against the run in
the run cache, keyed by `run_id`**: the record is `session-pointers.json`, written under the
run's scratch dir at `<main-checkout>/.perk/workflow/scratch/runs/<run_id>/` — where
`<main-checkout> = main_worktree_root(cwd) or cwd` — so a linked-worktree run and a later
resolver agree on ONE shared location. The path is built only through the
`run_scratch_dir`/`runScratchDir` seam (`perk/state/cache.py` /
`extension/substrate/cache.ts`). The plan branch's workflow-state **may mirror** the pointers for
provenance but is **not primary**. Schema (byte-identical across planes):

```json
{
  "run_id": "<this run's id>",
  "planning":       { "main": <Pointer|null>, "worker": <Pointer|null> },
  "implementation": { "main": <Pointer|null>, "worker": <Pointer|null> }
}
```

`Pointer = { "pi_session_id": str, "session_file": str, "parent_pi_session_id": str|null, "at":
ISO-8601 }`. Each run is **self-keyed**: it writes ONLY under its OWN `run_id`, and fills only
the slots it owns (planning runs → `planning.*`; implement runs → `implementation.*`). The four
class/site slots are always present (null when unset) so a read-modify-write merges trivially.
`main` vs `worker` is distinguished by **capture site** (deterministic), not by inspection: the
interior `session_start` writes `.main`, the headless `worker.driveStage` writes `.worker`, and
the `/submit` warm door additionally captures `.main` at `impl_run_ids`-stamping time (so a
submitted run resolves `found` regardless of its launched stage). The interior capture is
**claimer-only and first-write-wins** (a foreign-session overwrite is skipped with a loud stderr
warning; a same-session re-capture refreshes), and **env-inherited children never capture** (the
§8.2 adopt arm carries no stage). The submit-door capture is first-write-wins too.

**The plan-header linkage.** The planning `run_id` is already on the `plan-header`. The
implementation run id(s) are stamped onto the header as `impl_run_ids: tuple[str, ...]`, a
**submit-staged** field (null/empty at save, exactly like `branch`/`pr`) union-merged at
`/submit` (`perk pr submit --run-id <run_id>` appends the current run id iff absent — dedup,
order-preserving). The header is the canonical, GC-proof cross-run LINKAGE; the run cache is the
primary POINTER store.

**Cross-run resolution (`perk/learn/sessions.py::resolve_plan_sessions`).** `plan_id →
plan-header → {run_id (planning), impl_run_ids (implementation)} → read each run's
session-pointers record under the main checkout`. Per-role status is from the fixed set: `found`
(the slot's pointer is present) / `missing` (plan/header/run_id absent, the record file
GC'd/absent, or the slot is null); a `found` resolution downgrades to `missing` at export time if
the source session file is gone.

**The classification vocabulary (two distinct, related sets).**

- **The reconciled DECISION set** — the transient, in-session reconciliation output of `/learn`'s
  angle analysis. One of `CAPTURE_LEARN`, `SHOULD_BE_CODE`, `UPDATE_EXISTING_DOC`, `NEW_DOC`,
  `STALE_DOC`, `SKIP`, with one locked meaning each:
  - `CAPTURE_LEARN` — a durable cross-cutting learning → create a `perk:learn` issue.
  - `SHOULD_BE_CODE` — belongs in code/comment/docstring/schema/user-docs, not a learned doc
    (corresponds to the perk-learn-docs knowledge-placement hierarchy).
  - `UPDATE_EXISTING_DOC` — update an identified existing learned/user doc.
  - `NEW_DOC` — a new learned doc is warranted.
  - `STALE_DOC` — an existing doc is stale/duplicate and should be cleaned up.
  - `SKIP` — nothing durable; create no issue, clear the marker only.
- **The durable CAPTURED metadata shape** — persisted on the `perk:learn` issue header (both
  backends). It is the DECISION set **minus `SKIP`** (a skip creates no issue) **plus an optional
  `target`** (a routable pointer, e.g. an existing doc path). The fields extend the existing
  `learn-header` metadata block → `{ run_id, created, plan, decision, target? }`, rendered via
  the shared `render_learn_header` helper (optional fields only when present) so the header is
  byte-identical in shape on both backends. `decision` is a `plan.CapturedDecision` `StrEnum`
  (the five captured tokens). The typed read-back is `plan.parse_learn_header(body) ->
  LearnHeader | None` — **never-raise**: it scans both block styles, returns `None` when the
  block is absent/malformed, and degrades an unknown/future `decision` token to `None`. It is the
  gather-time classification route the learn factories read.

The learn shapes follow perk's boundary-model convention (§8.34 / `perk/boundary.py`): lenient
read-edges for untrusted data (session JSONL, header read-back), `OutputModel` serialize-edges
for the `--json` envelopes, closed sets as `StrEnum`s.

**The docs/code factory partition rule.** The two learn plan factories (`perk learn docs` /
`/learn-docs` and `perk learn code` / `/learn-code`) are read-only plan factories sharing
`src/perk/cli/commands/learn/factory_common.py`. Gather partitions the open `perk:learn` issues
by their captured `decision`: a pre-stamped `SHOULD_BE_CODE` routes to the code factory;
**every other classification — and any legacy/unclassified issue — defaults to docs** (the
catch-all). The partition is the *default* route, not the only path to a destination
(`/learn-docs`'s verifier may re-route a doc-stamped item to code; `/learn-code`'s skill may note
an item better suited to a doc); each factory consumes its **full filtered inbox** into
`consumed_learn`. The docs navigation (`docs/learned/index.md` + `.pi/APPEND_SYSTEM.md`) is
generated from per-doc frontmatter — the SSOT — via `perk learn docs-sync`, never by hand, as a
**two-tier index** when the committed cluster registry `docs/learned/clusters.yaml` is present
(`clusters:` = a non-empty list of `{id, rollup}` entries — unique kebab-case ids, one-line
rollups; members are **derived from each doc's `cluster:` frontmatter field**, never listed in
the registry). Tier 1 (ambient, `.pi/APPEND_SYSTEM.md`) renders one line per cluster in
**registry file order** — `- **<id>** — <rollup> (<category/slug>, …)`, members sorted
`(category, slug)`, no parens when empty — then one trailing legacy per-doc line for every doc
whose `cluster` is missing or unknown (an unassigned doc never drops from the ambient tier;
`docs-check` gates it red meanwhile). Tier 2 (the catalog `docs/learned/index.md`) keeps the
**demoted full per-doc `read_when` cues** and gains a Cluster column (`| Category | Doc |
Cluster | When to read |`; the declared value verbatim, `|`-escaped, empty when undeclared).
Registry **absent** ⇒ the legacy fallback: byte-identical per-doc rendering, no cluster gates.
Registry **invalid** (unreadable / YAML error / wrong shape / empty `clusters` /
missing-empty-non-kebab id / duplicate id / missing/empty/multiline rollup) ⇒ `docs-sync`
refuses loudly and writes nothing (exit 1, the precise reason; `invalid_cluster_registry`) — a
broken registry can never silently regress the committed block to per-doc grain — and
`docs-check` reports the same reason as a gating finding. The `docs-check` gates: freshness
(against the registry-aware render; the routing/catalog comparison is skipped when the registry
itself is invalid — `fresh`/`stale_files` then carry the non-compared defaults, the
`registry_error` gate covers the exit, and the human render says UNCHECKED, never fresh); the
per-cue budget — each `read_when`
is ≤ `200` chars (measured on the parsed value — what the generators emit) and free of the YAML
plain-scalar hazards that silently corrupt the rendered cue (a ` #` truncates the plain scalar, a
`: ` fails the whole frontmatter parse, a multi-line value breaks the one-line routing grammar;
a quoted scalar is the sanctioned escape); and, in registry mode: registry validity, every doc's
`cluster` declared + a known id, no empty clusters, and each rollup ≤ `160` chars
(`CLUSTER_ROLLUP_MAX_CHARS`, measured on the parsed value — overlong gates but sync still
writes, parity with the overlong-cue posture). A pytest enforces the same cue budget — and pins
perk's own repo to registry mode with the cluster gates — in CI; freshness deliberately stays
out of CI (on-demand only).

**The non-empty `consumed_learn` discriminator.** A plan whose `plan-header` `consumed_learn` is
**non-empty** *is* a learn-docs consolidation plan. `/learn` and `perk learn evidence` detect
this **up-front** and return a stable **no-op**: clear `pending-learn`, create no `perk:learn`
issue, gather no bundle, spawn no children — reporting *"learn-docs plan; learn capture
skipped"*. A plan-**fetch** failure is **never** a skip signal — the command proceeds to gather
with the `plan` source `missing`.

**The bundle-manifest CLI (`perk learn evidence --json`).** Reads the local `cache.plan-ref` (no
positional arg, mirroring `perk learn capture`); gathers the bundle, materializes the artifacts
under `cache.scratch_dir(repo_root) / "learn-evidence"`, and emits the manifest. Exit codes: `0`
ok (skip OR gathered manifest) · `1` no plan-ref / invalid · `2` not-a-repo. `require_github` is
**not** called — GitHub reads degrade per-source (*expected absence* → `missing` silently; a
*genuine error* → `missing` + a stderr warning, loud-but-non-fatal), so the manifest still
gathers sessions + docs offline. The opt-in `--render` flag projects the found session JSONLs
into bounded, untrusted-DATA-fenced Markdown chunks under `<bundle_dir>/chunks/` and reports on
the envelope's **additive `render` field** (declared LAST, always serialized, `null` unless
`--render`); the pipeline, fence format, and report fields are `normalize.py`'s contract.

The `--json` envelope (`OutputModel` serialize edge — the contract the warm orchestrator decodes):

```
EvidenceBundle = {
  success, error_type, message,            # the standard envelope head
  skipped: bool, skip_reason: str|null,
  plan_id: str|null, bundle_dir: str|null, # bundle_dir relative to repo_root
  sources: EvidenceSource[],
  existing_docs: DocEntry[],
  docs_findings: DocFindings,              # the rich docs scan (declared after existing_docs)
  render: RenderReport|null,               # additive; null unless --render
}
EvidenceSource = { category, label, status, artifact: str|null, detail: str|null }
DocEntry       = { kind, path, title: str|null, snippet: str|null }
DocFindings    = { stale_pointers: StalePointer[], broken_doc_paths: BrokenDocPath[],
                   duplicate_groups: DuplicateGroup[] }
StalePointer   = { doc, pointer, reason }            # reason ∈ {missing-file, missing-symbol}
BrokenDocPath  = { doc, target }
DuplicateGroup = { basis, key, docs: str[] }         # basis ∈ {title, read_when}
```

`status ∈ {found, missing, ambiguous}`. `artifact` paths are **relative to repo_root**
(portable). The full shape is always serialized (no `exclude_unset`) so absent values render
`null`. `EvidenceBundleOut` is deliberately absent from `shared/schemas/` (§8.34's registered set
publishes `learn-capture` only), and there is no TS twin — the warm orchestrator shells the
Python command.

**Category → source mapping.** `plan` (1; materializes `plan-body.md`), `pr` (1; materializes
`pr.diff` when `found`; `0` branch matches → `missing`, exactly one MERGED match — or exactly one
match of any state — → `found`, otherwise → **`ambiguous`**, no diff materialized),
`planning-session` (2: `main`/`worker`), `implementation-session` (per `impl_run_ids` entry ×
`main`/`worker`; **one `missing` entry labelled `(none)`** when there are no impl runs),
`existing-docs` (1 roll-up: `found` when the inventory is non-empty, else `missing`; the detail
rides the separate `existing_docs[]` + `docs_findings`).

**The `manifest.json` write rule.** The warm orchestrator runs the gather ONCE (`perk learn
evidence --render --json`) and **also writes `<bundle_dir>/manifest.json`** — the full
`EvidenceBundleOut` payload, the same as `--json` stdout incl. `render` — so the spawned analyst
children can `read` the manifest (they cannot read the door's stdout). Written unconditionally on
a materialized bundle, deterministic (no wall-clock); no write on a skip.

**The analyst wave (the report-wave module).** The multi-angle analyst fan-out runs through the
Perk-owned report-wave module (`extension/waves/reportWave.ts`) via the flow-scoped
**`run_learn_wave`** tool (`extension/doors/learn.ts` — non-terminating; the parent continues to
reconcile): the module renders the tested `workflowScript`, spawns it async over the pi-subagents
v1 extension RPC (`mission: false`, `context: "fresh"`, and the fixed
`acceptance: {level: "none", reason}` disable — delivered onto every lane child via pi-subagents'
workflow-defaults spread, suppressing the auto-inferred acceptance contract whose fenced
`acceptance-report` completion instruction competes with the engine-validated `structured_output`
report; module-wide, no opt-out), blocks under the module-owned timeout,
and reads the durable `status.json` aggregate — the wave mechanics are CODE, never model-authored
prompt mechanics. Analyst reports are **engine-validated structured output** against the TS-owned
`LEARN_ANALYST_REPORT_SCHEMA` (`extension/waves/learnWave.ts` — closed shape, all-required,
`target` required-nullable, deliberately NO verdict↔candidates conditional: the parent derives
the real verdict from `candidates[]`, so salvaging an inconsistent report beats failing its
lane), replacing fenced-JSON scraping — covered angle ⟺ ok lane ⟺ schema-valid report.
Completeness is the module's **`best-effort`** policy as tested implementation: a lane-level
failure is an explicitly-reported **skipped angle** (never a failed pass, no retry); a
**wave-level** failure is a loud tool soft-failure (`error_type` = the wave failure reason) —
never a silent fallback to model-authored scripts — and the guidance routes the parent to a
single-context analysis of the bundle instead. The **angle policy is tool-enforced**
(`angleSelectionError`): 2–4 angles, no duplicates, only the four known slugs
(`session-deviations` / `plan-vs-implementation` / `existing-docs` / `validation-risk`), and
`session-deviations` always included; violations are `bad_input`. The tool takes the
guidance-rendered `bundle_dir` (the model relays it verbatim — the same trust plane as the task
text), derives `manifest.json` itself (`bad_input` when absent), and resolves the analyst model
from `[models.subagents] learn-analyst` at execute time (the wave's workflow-level `model`
default). The manifest write rule above and the DECISION vocabulary are unchanged.

**Attempt receipts (flow-generic).** Every code-owned wave flow records an **output-free**
`WaveAttemptReceipt` per top-level workflow launch when the completion payload carries the
projection (pi-subagents ≥ 0.45.0): the child lane key ↔ child `runId` ↔ artifact paths —
reports, summaries, and structured output NEVER enter a receipt. Retries retain every ordered
attempt (a failed lane and its relaunch stay distinguishable). `status.json.workflow.value`
remains the SOLE authority for reports and completeness; receipt absence (an identity-only
completion) never changes a verdict, completeness, retry selection, or mutation decision —
receipts are write-only correlation telemetry. The flow tools (`run_learn_wave`,
`run_harvest_wave`, `run_pr_review_wave`, `run_pr_review_dynamic_wave`, and the single-lane
`classify_review_feedback` / `explore_objective_node`) persist `attempts` in their structured
tool-result details only (never the model-facing prose); a wave-level soft-failure retains any
receipt known before the failure in its fail details.

**The `learn` tool's classification params.** The warm `learn` tool carries `decision` (a
JSON-schema enum of the five captured tokens) + `target` (string), threaded to `perk learn
capture --decision/--target`. The tool-boundary decode mirrors the `summary` strictness: a
present-but-mistyped or out-of-enum value ⇒ `bad_input`, marker NOT cleared; absent ⇒ the
decision-less path. Headless bare `/learn` stays the safe marker-clear; `/learn <text>` /
`/learn skip` stay the verbatim-capture / marker-clear escape hatches (decision-less).

## §8.36 · Canonical post-merge learn state (the plan-header `learn_state` field)

Post-merge learn state is **canonical in the issue backend**, not the local marker: the plan-header
carries a land-staged `learn_state` field, so a merged-but-unlearned plan resolves identically from
any machine, a fresh clone, or the main checkout. The local `pending-learn` marker (§8.4) is
**demoted to cache/friction-semaphore**: the in-worktree retry
signal and the `worktree wipe` guard — never the source of truth.

**Vocabulary (`plan.LearnState`, a `StrEnum`; `"learn_state"` ∈ `PLAN_HEADER_FIELDS`).**

- `pending` — merged, learn not yet run.
- `captured` — a `perk:learn` issue was created for this plan.
- `skipped` — learn deliberately skipped (terminal; never reads as pending again).
- **Absent** — a legacy (pre-field) plan or a failed stamp; resolution falls back to the local
  marker (exactly today's behavior — never worse).

The field is **land-staged**: never rendered at initial save (fresh headers stay byte-identical —
no `learn_state: null` line; `PlanHeader`/`PlanHeaderOut` do NOT grow), written only through the
existing `IssueBackend.update_plan_header` merge-write (both backends for free; unknown keys
preserved on re-save).

**The three writers.**

1. **`perk pr land`** (`_stamp_learn_state`, non-dry-run, after the merge; `set_marker` runs only
   on the non-exempt arm): stamps
   `skipped` when `plan_ref.consumed_learn` is non-empty (a learn-docs consolidation plan skips its
   learn pass by design — it must never read forever-pending) **and sets no marker** (the plan is
   exempt from the land→learn cycle; the envelope carries `pending_learn: false`); every other
   plan keeps today's set-marker + `pending` stamp (`pending_learn: true`). The warm `/land`
   mirrors the envelope's `pending_learn` (lenient decode — missing/mistyped defaults to `true`
   under version skew, degrading to the legacy marker + `/learn` nudge). **Never-downgrade
   guard**: an existing `captured`/`skipped` is kept (an idempotent re-land after `/learn` must not
   resurrect a done plan) and returned as the effective state. **Fail-open loud** (the on-land
   secondary-bookkeeping shape): never raises on an expected backend failure
   (`IssueBackendError`) — it warns on stderr and the envelope carries `learn_state: null`; a
   programming error propagates. `PrLandOut.learn_state` is declared last (field byte-order
   preserved).
2. **`perk learn capture`**: stamps `captured` **strictly** (an `IssueBackendError` propagates,
   exit 1) and **before** `cache.clear_marker` — the local marker is cleared only once canonical
   state is terminal; a failed stamp leaves the marker set and the retry converges (capture is
   idempotent via the `run_id` finder). Capture always stamps `captured`: a capture after a skip is
   a legitimate upgrade.
3. **`perk learn skip`** (the cold skip door; `LearnSkipOut` envelope
   `{success, error_type, message, plan_issue, learn_state, pending_cleared, dry_run}`): stamps
   `skipped` strictly before the marker clear — **unless** the existing value is `captured` (then a
   no-op stamp; the envelope reports the kept `captured`; the marker is still cleared). `--dry-run`
   composes offline (no write, no marker change). Exit codes mirror `learn capture` (0/1/2). The
   warm no-summary `/learn` arm (the `learn` tool without `summary`, `/learn skip`, headless bare
   `/learn`) **delegates here** — a deliberate skip is never a TS-only marker-clear; on a failed
   delegation the warm door does NOT clear the marker (never silently close the cycle on
   uncertainty). The warm decode is fully lenient (render-only fields; `bad_output` unreachable).
   The learn-docs short-circuit in bare `/learn` stays a local marker-clear only — land already
   stamped `skipped` for a `consumed_learn` plan (and, since the land→learn exemption, sets no
   marker for it — the short-circuit remains as the defensive path for markers set by older
   CLIs / legacy lands).

**The reader (`resume.resolve_next_action`'s MERGED arm, §8.37).**

| header `learn_state` | local marker | resolves to |
| --- | --- | --- |
| `pending` | (ignored) | `learn` |
| `captured` / `skipped` | (ignored — even stale) | `done` |
| absent / unrecognized | set | `learn` (the legacy fallback) |
| absent / unrecognized | unset | `done` |

`has_pending_learn` stays a kwarg — it is now explicitly the legacy/cache **fallback** signal.

The second reader is `perk learn pending`: it lists the closed plans whose header still reads
`pending` (canonical-field only — absent-field legacy plans are not listed; the local marker is
per-worktree cache and cannot power a repo-wide view).

**Registry.** `land.writes` and `learn.writes` both include `github.plan` (the header stamp).

---

## §8.37 · Unified next-stage resolution (the shared classifier, Objective #1093 Node 1.2)

`perk plan resume` and `perk objective run` answer the same question — *given this plan's
canonical state, what happens next?* — through **one shared pure function**,
`resume.resolve_next_action(plan_state, *, has_pending_learn, get_feedback) -> NextAction`
(`perk/run/resume.py`; pure, deterministic, no Click/subprocess/network), so the two surfaces
provably agree.

### The `NextAction` vocabulary (a `StrEnum`)

Seven verdicts: `implement` · `address` · `learn` (launchable — `NextAction.stage_id` returns the
registry stage id) and `ready_for_review` · `awaiting_review` · `pr_closed` · `done`
(gates/terminal — `stage_id` is `None`).

### The classification matrix (arm order over the normalized PR vocabulary)

| plan state | verdict |
|---|---|
| `pr is None` (no PR yet) | `implement` |
| `MERGED` + header `learn_state: pending` | `learn` |
| `MERGED` + header `captured`/`skipped` | `done` (even with a stale marker) |
| `MERGED`, field absent/unrecognized | `learn` iff `has_pending_learn`, else `done` |
| `CLOSED` (unmerged) | `pr_closed` |
| `is_draft` | `ready_for_review` (feedback is **never** fetched for a draft) |
| OPEN non-draft (any unknown state is treated as open) | `address` if `needs_address(get_feedback(pr.number))`, else `awaiting_review` |

`get_feedback: Callable[[int], PrFeedback]` is the **lazy injected** feedback fetch — called only
on the OPEN-non-draft arm (offline tests pass a raising stub for every other arm; the callers pass
`github.get_pr_feedback`, which raises `GitHubError` on infra failure — translated at each Click
boundary). `has_pending_learn` is the §8.36 legacy/cache **fallback** input (the local
`pending-learn` marker); the canonical plan-header `learn_state` field wins whenever recognized.

### The `needs_address` predicate (pure, offline-testable; moved here from §8.20)

`needs_address(feedback: PrFeedback) -> bool` — canonical import path `perk.run.resume` — is
**True** when either any `review_thread.is_resolved is False`, **or** the **latest review per
author** is `CHANGES_REQUESTED`. "Latest per author" = the `Review` with the max `submitted_at`
(ISO-8601 string compare; `None` sorts oldest). A `COMMENTED`/`APPROVED` latest review does
**not** trigger address; `discussion_comments` are never address triggers (conversation, not
change requests).

### The two consumers

- **`perk plan resume`** launches a launchable verdict's stage (dry-run previews it) and
  **reports** a gate/terminal verdict — gate arms never launch, in both real and dry-run modes
  (benign decisions, exit 0), naming the human gate instead of launching the wrong stage. There
  is **no `submit` resume target**: an open PR resolves to `address`, `awaiting_review`, or
  `ready_for_review`. Both resume payload shapes carry `next_action`; the launchable shape keeps
  `resumed_stage` (always equal to `next_action.stage_id`), gate shapes carry
  `{success: true, plan, next_action, resumed_stage: null, pr, message}`. A **cold-local**
  `implement`-verdict launch additionally appends the reuse advisory to the implement primer when
  the plan worktree pre-exists locally; a `--remote` dispatch never carries it (§8.38 named
  difference 9).
- **`perk objective run`** maps the verdict onto its §8.20 `action` vocabulary (table there) and
  carries the verdict verbatim in the payload's `next_action` field.

### The parity guarantee

For the same plan state, `perk plan resume <id> --dry-run --json` and
`perk objective run <N> --dry-run --json` report the **same `next_action`** — and, for
launchable verdicts, select the **same stage** (`resumed_stage` == `stage`), modulo the named
learn divergence (§8.38 row 1) — `tests/test_next_action_parity.py`.

## §8.38 · Per-stage path parity (warm / cold-local / remote)

The "one implementation per stage" claim (`docs/user-docs/explanation/how-perk-thinks.md`),
backed by tests: on the six surfaces where the warm, cold-local, and remote paths meet, each
row names the **shared implementation**, the **enforcing tests**, and — where a path
intentionally differs — the **named difference** (the docs name it instead of implying
identity).

| # | surface | shared implementation | enforced by |
|---|---|---|---|
| 1 | next-action resolution | `resume.resolve_next_action` (§8.37) — consumed by `plan resume` and the `objective run` supervisor (incl. its remote dispatch arm) | `tests/test_next_action_parity.py` (verdict **and** stage-selection equality across both dry-runs), `tests/test_resume.py` |
| 2 | prompt generation (local vs worker) | canonical templates `prompts/stages/*` via the §8.31 render seam; `_implement_prompt`/`_address_prompt` ↔ `initialPromptFor` ↔ `implementHandoffPrompt`/`addressGuidance` | `tests/test_prompt_parity.py` (live cross-engine byte parity) + goldens; reciprocal substring suites `tests/test_worker_prompt_parity.py` ↔ `extension/worker/worker.test.ts`; binding-content byte parity `tests/test_binding_render_parity.py` (via `extension/testing/renderBindingsLive.ts`) |
| 3 | submit side effects | one Python door, `perk pr submit --json`; the warm `submit` tool/`/submit` command delegate via `submitPr` (`extension/doors/submit.ts`), and the remote worker drives that same registered tool | `extension/worker/workerE2e.test.ts` (implement HAPPY drives the real tool through the real extension into a stubbed `PERK_BIN` router), `extension/doors/submit.test.ts`, `tests/test_pr_submit.py` |
| 4 | address terminal criteria | `finalize_address` (`extension/doors/address.ts`) runs submit first, delegates its internal resolve half to `perk pr resolve-threads --json`, and appends `last_review_batch`; the worker requires finalizer success + that write + successful effective submit evidence with `mergeable !== false` | `workerE2e.test.ts` (address HAPPY binds both real door writes to classification), `worker.test.ts` `evaluateTerminal` matrix; post-address the supervisor re-classifies via row 1 |
| 5 | plan-ref reconstruction + positioning | one function, `resume.reconstruct_plan_ref` — all four reconstruction sites converge on it (`plan/resume_cmd.py`, `objective/run_cmd.py`, `implement_cmd.py`, `run/run_worker.py`); `run_worker.position_worktree` mirrors `launch_stage`'s positioning, and stacked branch starts share `prepare_stacked_layer` (`require_ready_layer` + `prepare_layer_start`, §8.46) across `resolve_worktree` and `run_worker.position_branch` | `tests/test_plan_ref_parity.py` (the save→reconstruct round trip + the `PlanRef` field census), `tests/test_resume.py`, `tests/test_run_worker.py::test_positioning_parity_local_launch_vs_remote_worker` (artifact byte parity, `run_id` excepted), `tests/test_run_worker.py::test_positioning_parity_stacked_local_create_vs_remote_position` (same start SHA + `layer-context.json` parity, timestamps excepted) |
| 6 | run reporting | **remote-only by design**: `perk/run/run_report.py` derives the §8.15 plan-issue comments + job summary solely from the §8.12 events stream + exit code | `tests/test_run_report.py` (incl. the `RunOutcome` lockstep literals) ↔ `worker.test.ts` (the frozen `assembleOutcome` shapes) |

### The named intentional differences

1. **`learn` is resume-only.** `perk plan resume` launches the `learn` stage locally; the
   `objective run` supervisor never dispatches it — it reports `merged_pending_reconcile` with a
   `perk plan resume <id>` remediation. `submit`/`land`/`learn` have no remote door (registry
   `cold_remote: false`).
2. **Binding delivery mechanism differs; content does not.** Cold-local launches append the
   rendered bindings as a prompt suffix (`render_cold_bindings`); warm sessions and the remote
   worker receive the same render via §8.9 Mechanism A (in-session injection), dedup'd by
   `BINDING_HEADER`. Content byte-parity is enforced (`tests/test_binding_render_parity.py`).
   Skill *installation* also differs by path: cold-local mirrors `repo_root/.agents/skills/`
   into the worktree (`materialize_skills`, loud-but-non-fatal); the remote worker populates the
   checkout's `.agents/skills/` via the skills-CLI sync during positioning (**fatal**,
   `skills_sync_failed` — §8.14 step 4). Binding *content* parity is unchanged either way.
3. **`address --preview` is local-only.** The classify-only preview flag exists on the
   warm/cold-local doors; the remote worker always renders the action template.
4. **The `--run-id` impl-run stamp + the conflict-resolver drive need a session.** `submitPr`
   stamps the implement run (workflow-state `run_id`) and drives conflict resolution
   (`driveConflictResolution`) only where a session exists (warm + worker); a bare shell
   `perk pr submit` *reports* `mergeable`/`conflicts` without driving resolution.
5. **Terminal classification is worker-only.** Only the headless worker machine-classifies a
   stage terminal (`evaluateTerminal`); warm/cold-local stages end with the human observing the
   same tool results.
6. **Run reporting (§8.15) is remote-only.** Local runs are observed directly (the terminal /
   the session); no started/terminal plan-issue comments are posted for them.
7. **Skill-exposure scoping (§8.39) is cold-local-only.** Only the cold-local launch composes
   the `--no-skills`/`--skill` scoping argv; the remote worker builds its session via the SDK
   (no pi-CLI arg parsing) and gets skills on disk via the skills-CLI sync (difference 2) — no
   scoping applies there. Warm sessions and bare interactive `pi` are likewise untouched.
8. **The stacked branch-creation gesture differs; the prepared start does not.** A fresh
   stacked layer starts locally via `git worktree add … <parent_sha>` and remotely via an
   in-place `git checkout -b plan-<N> <parent_sha>` (§8.46) — both consume the same
   `LayerContext` + `prepare_layer_start`, land on the same verified parent commit, and write
   the same `layer-context.json` (timestamps excepted).
9. **The resume prior-work advisory is `plan resume`-cold-local-only.** When `perk plan resume`
   resolves to `implement` and the plan worktree already exists locally (the D4 reuse arm), the
   door appends `prompts/common/resume-advisory.md` to the implement primer via `launch_stage`'s
   augment-only `prompt_suffix` seam (between the primer and the binding suffix). `perk plan
   implement`, the warm `/implement` handoff, and the remote worker never carry it (the worker
   resets to the `origin/plan-<N>` tip — prior committed work *is* its branch state; uncommitted
   local work never exists there). The shared `stages/implement.md` render stays byte-identical
   across all paths.

## §8.39 · The layered skills-exposure model (cold stage launches)

A cold stage launch may scope pi's skill discovery to the skills relevant to its stage instead of
inheriting the full unscoped set. The Python plane owns the whole mechanism
(`perk/substrate/skill_exposure.py`, composed into the launch argv by
`perk/run/launch/__init__.py::_skill_exposure_argv`); the TS plane deliberately does **not**
consume the `[skills]` namespace (its `parseTomlSubset` drops array values and keeps scalars under
dotted sections — fail-safe by construction, pinned by a non-interference test).

**The three layers.** For each candidate skill, exposure resolves as:

1. a **`[skills.stages]` config row** (keyed by skill name — frontmatter `name` else the skill
   dir name) — wins whenever the key is present, including a config `"all"` re-widening a
   narrower frontmatter declaration;
2. the skill's **`stages:` SKILL.md frontmatter** — the string `all`, or a list of registry
   stage ids (pi ignores unknown frontmatter fields, so the declaration is upstream-safe);
3. **undeclared → `all`** (fail-open; an undeclared skill behaves like today).

A skill is exposed to a launch iff its resolved value is `all` or contains the launch stage's id.
An **explicit empty list** (`stages: []` or a `= []` config row) means exposed to **no** stage
launches (an interactive-only skill; bare interactive sessions are untouched). A **malformed**
`stages:` value (wrong type, blank/non-string entries, unparseable frontmatter) is treated as
`all` + one warning (fail-open, loud-but-non-fatal). Unknown stage ids are kept, inert — the
parser stays registry-free (mirroring `[models.stages.<id>]`); doctor owns any nudge. The
vocabulary is **stage ids only**: stage-borrowing commands resolve through the stage they borrow
(a `learn-docs` session sees `plan`-staged skills); their own orchestration skill arrives via the
bound-skill union on their `command:<id>` trigger.

**Bound skills always win.** Any skill referenced by a resolved binding (§8.9;
shipped-defaults ⊕ user overlay) whose trigger equals the launch trigger (`binding_trigger` else
`stage:<stage.id>` — the same defaulting the seed-prompt assembler uses) is unioned into the
exposed set, trumping every layer including an explicit `= []` row — even when not installed
(the entry dangles and pi emits its own missing-path diagnostic, the existing dangling-binding
symptom; remediation `perk init`).

**The `[skills]` config namespace** (overlay-aware via `load_config` — `.perk/local.toml`
dominates; a local `include_dirs` array replaces wholesale, matching `[worktree] setup`):

- `include_dirs` (default `[]`): a whitelist of directories passed wholesale as `--skill <dir>`
  args. Default: pi's global/user skill dirs (`~/.pi/agent/skills`, `~/.agents/skills`) and
  project `.pi/skills` are **dropped** from scoped launches unless whitelisted. Entries get
  `~`-expansion; relative entries resolve against the **main repo root** and are passed
  **absolute** (relative entries would silently break in worktree sessions).
- `include_packages` (`bool`; unset = participate): the blanket toggle for the npm-package tier.
  An explicitly-set value (either way) counts toward engagement.
- `[skills.stages]`: skill name → `"all"` or a list of stage-id strings, applying to project
  **and** package skills by name. Ill-typed values raise `ConfigError` (the standard loud
  posture); unknown skill names are kept inert.

**Engagement.** The composition engages only when the model is in use: at
least one enumerated skill (project or package) declares `stages:`, **or** any `[skills]` config
content exists (`stages` rows, non-empty `include_dirs`, or `include_packages` explicitly set).
Otherwise it contributes nothing and the launch argv (and stderr) is **byte-identical** to
unscoped discovery. Enumeration always runs to detect frontmatter declarations. The zero-change
rollout clause is now **historical**: perk's shipped skills declare `stages:` at source, so any
repo whose `.agents/skills/` mirror is synced to current perk is **engaged by default** — an
un-synced mirror stays unengaged (fail-open) until the next `perk init`/`doctor --fix` re-sync.
Personal/global skill dirs then need the `include_dirs` whitelist to reach scoped launches. New
repo-authored skills are **born declared**: the `perk skills scaffold`/`create` stub template
declares `stages: all` (with a narrowing TODO), and doctor's `repo-skills` check warns on
repo-authored skills that leave `stages:` undeclared or declare unknown stage ids.

**The composed argv.** When engaged, `launch_stage` inserts, between the per-stage model args and
`pi_args` (build-argv-once, so `--dry-run --json` previews it and user-passed flags stay last;
an extra user `--skill` stays additive — pi merges explicit skill paths even under
`--no-skills`):

1. `--no-skills`;
2. the `include_dirs` whitelist entries (absolute `--skill <dir>`, config order);
3. the **npm-package skills** (unless `include_packages = false`): from `.pi/settings.json`
   `packages` (strings or `{source}` rows), **`npm:` sources only** →
   `.pi/npm/node_modules/<name>`. Local-path sources (the self-repo's `".."`) and `git:` sources
   are deliberately **not** enumerated — first-party skills come from `.agents/skills` full stop
   (no committed-`skills/` fallback); enumerating the self-repo's local-path (`..`) package would
   also re-import the committed-`skills/` vs `.agents/skills` name-collision noise (the 16-way
   duplicate set in the self-repo) into scoped sessions. Per package, skill roots = `pi.skills` plain-path entries
   when declared, else the conventional `skills/` dir; each root is enumerated one level
   (`<root>/<name>/SKILL.md`), each skill resolved through the three layers. A root with no
   one-level `SKILL.md` children degrades to one wholesale `--skill <root>` arg; a pattern
   (non-path) `pi.skills` entry degrades the package to one wholesale `--skill <package dir>`
   arg. Paths are repo-relative (the worktree `.pi/npm` clone from `materialize_extensions`
   makes them resolve in worktree sessions);
4. the **project skills**: each child dir of `repo_root/.agents/skills/` (the exact set
   `materialize_skills` mirrors — the exposure path reads `.agents/skills` **only**; a
   just-landed un-synced skill is softly absent until `perk init`), resolved through the three
   layers; exposed ones become relative `--skill .agents/skills/<name>` args, sorted by name
   (bound-but-unenumerated skills join this tier as dangling delivery-path entries).

Relative paths resolve against pi's cwd *after* `launch_stage`'s `os.chdir` — the worktree for
worktree stages (mirror + `.pi/npm` clone exist by exec time), the repo root otherwise. The
2→3→4 order fixes first-wins collision outcomes (whitelisted dirs > packages > project),
approximating pi's native user-before-project precedence.

**Fail-open ladder.** The whole composition is wrapped: any unexpected exception → one warning +
**no flags** (the launch degrades to unscoped discovery; never blocked). A listed `npm:` package
whose install dir is absent at composition time (cold `.pi/npm`, first launch), or an
unreadable/malformed `.pi/settings.json` while the package tier is enabled, degrades the
**whole composition** to unscoped + a warning (argv is built before the warm-install phase, so
this is the honest fail-open — per-package skips would silently drop whole packages; it
self-heals on the next launch). Per-skill soft issues (unreadable/malformed SKILL.md or
`stages:`) default that skill to `all` + a warning. The only loud failure is `ConfigError` from
`load_config` — the pre-existing config gate, raised before composition runs.

**Scope boundaries.** Cold-local stage launches only: bare interactive `pi`, warm in-session
transitions, and the remote worker (§8.38 named difference 7) are untouched.

---

## §8.40 · Stage-scoped active tools (the warm plane)

A stage session's model carries only the perk tool schemas its stage's flows can actually invoke.
The mechanism is extension-owned end to end: a curated per-stage map (`STAGE_TOOLS`, beside
`READ_ONLY_TOOLS` in `extension/substrate/toolGating.ts`, keyed by registry stage ids) applied at
the existing `session_start`/`session_tree` rebuild points via `syncFromState(mode, stage)`. The
key is the branch-LWW workflow-state **`stage`** field (§8.3): claim syncs the handoff-recorded
stage just appended; keep/none sync the branch-rebuilt stage; **fork inherits** the parent's
stage (a forked implement session is an implement session); **adopt never impersonates** (spawned
subagent children stay unscoped — their fresh branch carries no stage). Stage-borrowing cold
doors land on real stage ids (`plan from`/`plan replan`/`learn docs`/`learn code` borrow `plan`;
`objective replan`/`objective author --from` borrow `objective-author`; `skills create/refine`
borrow `save`), so the per-stage sets cover every borrower. The gist stages (`gist-author`,
`gist-save` — §8.41) each carry `ask_user_question` + `gist_draft` + `gist_save` + the research
families (the objective-author shape; `plan_review` governs via the gate-ON set). The `audit`
stage (§8.50) carries `ask_user_question` + `run_audit_wave` + the research families — its
sessions run GATED (read-only mode), where the gate-ON set governs, so the row exists for the
keys≡registry pin and the defensive gate-off arm; `run_audit_wave` also joins `PERK_TOOLS`
and `READ_ONLY_TOOLS` (§8.3's carve-in — the write target is handoff-bound, never
caller-supplied). **Scoped universe:
`PERK_TOOLS ∪ BORROWED_TOOLS`** — perk's own name-keyed census plus the enumerated
borrowed-package census (the web-provider union, pi-mono-linear's 25 tools, pi-subagents'
delegation four, pi-fff's search names — both mode name-sets, `fffind`/`ffgrep`/`fff-multi-grep`
plus override's `multi_grep` — `todo`, `ask_user_question`, `plannotator_submit_plan`); builtins and un-enumerated foreign names
pass through untouched (fail-open — enumeration is diet-completeness, not correctness).

**The borrowed census posture.** Static names, inert when absent (the `READ_ONLY_TOOLS`
posture — `setActiveTools` simply has nothing to enable; no presence detection). Every census
name registers at load time EXCEPT pi-subagents' parent supervisor pair (`subagent_supervisor`,
`intercom`), which registers during `session_start` after perk's sync and deliberately leaks
past rebuild-point filtering at launch (accepted + test-pinned; a later tree-navigation
re-apply filters over the original snapshot — which lacks the late names — and drops them, the
pre-existing snapshot behavior). A name is governed ONCE — it lives in exactly one census
(hygiene-tested): perk registers no same-named `ask_user_question` anymore (the first-party tool
is deleted), so the name lives in `BORROWED_TOOLS` — the borrowed
`@juicesharp/rpiv-ask-user-question` package registers it at load time, then a `hasUI`-keyed
reconcile strips/restores it (headless sessions carry no `ask_user_question` schema at all).
`todo` is likewise a required-borrow name: the borrowed `@juicesharp/rpiv-todo` package
registers it at load time (its checklist overlay is `hasUI`-gated — headless-safe).
Foreign packages that run their own
`setActiveTools` (plannotator's phase machinery, @tombell/pi-plan's plan mode) win between
perk's rebuild points (the fail-open direction), and a mid-session rebuild re-installs perk's
stage set over a foreign restriction — recorded interplay, not re-engineered. Stage placement:
the research families (web union + Linear reads + FFF local search) ride EVERY stage list; delegation
(`subagent`/`wait`/the supervisor pair) and `todo` are worktree-family only among the gate-OFF
stage lists (delegation additionally rides the read-only gate — §8.3);
`LINEAR_MUTATING_TOOLS` (incl. `linear_configure_auth`, which writes `~/.pi/agent/auth.json`)
and `plannotator_submit_plan` appear in NO stage list — in the census, so subtracted from every
stage session; bare/unscoped sessions keep full access. Child-session tools
(`structured_output`/`contact_supervisor`/`subagent_wait`) live in **neither census**: children
stay **stage**-unscoped by design (adopt-never-impersonates above), so the stage filter never
sees a child session — but the read-only **gate** IS inherited by adopted children (§8.3), so
the child-side engine tools live in `READ_ONLY_TOOLS` (`SUBAGENT_CHILD_TOOLS`), gate membership
being their only governance surface.

**Composition with the read-only gate (§8.3).** Gate ON → `setActiveTools(READ_ONLY_TOOLS)`
**unchanged** — no stage filter, preserving every gated carve-out byte-for-byte (a strict
intersection would break the documented warm `/objective-plan` carve-out and recreate the
seed/gate contradiction class); the gated set includes the delegation family and
`explore_objective_node`, so the objective-plan explore step stays reachable while gated. Gate OFF + known stage → a **subtractive filter over the one
shared pre-engagement snapshot**: non-perk names pass through; perk names survive only when the
stage's list carries them. The rule "the gate never widens a stage's set and vice versa" holds:
engaging the gate only ever narrows, and stage scoping never adds a tool. Both concerns share
ONE snapshot, taken on first engagement of either; neither engaged → restore the snapshot if one
exists. The worktree family (implement/submit/address/land/learn) is deliberately **one shared
PR-loop list** — any PR-loop warm command works in any worktree session (warm doors inject
guidance naming their companion tool; a per-stage cut would dead-end e.g. `/land` run inside the
implement session). The reconcile trio (`reconcile_objective`/`add_objective_node`/
`objective_node`) rides the worktree family in addition to the three objective stages: `/land`
auto-drives the objective-reconcile pass inside the current worktree session and the manual
`/objective-reconcile` gesture is registered globally — both inject guidance naming all three;
`objective_node` likewise rides all three objective stages (the guidance's node-description
reconcile). The draft-review doors' companions (`start_draft_review_wave` /
`collect_draft_review_wave` / `push_annotations` — §8.23's `/plan-review-browser` +
`/objective-review-browser`) ride the
three plan-family stage lists (`plan`/`save`/`objective-plan` — gate-OFF coverage: after
`approvalSave` exits the gate mid-flow, late collects/pushes must not dead-end; the
drive-coverage guard forces this the moment the guidance names them) AND the two objective
stage lists (`objective-author`/`objective-save` — the same gate-OFF coverage after
`objectiveApprovalSave` exits the gate mid-flow), with `plan_review` joining those two lists
too (the objective door's guidance names it — in both objective stages it routes to the
objective review arm; drive-coverage) AND `READ_ONLY_TOOLS`
(plan-authoring sessions run GATED, so the companions must be reachable while read-only:
`push_annotations` only POSTs findings to the door-primed local plannotator server — no
worktree writes, the `fetch_content` cache-write precedent class — and the wave pair spawns the
read-only `perk.draft-reviewer` over the already-carved-in delegation family).

**Fail postures.** Stage scoping is **fail-open** where the gate is fail-closed: no stage, an
unknown stage id (version skew), or any lookup miss → no filtering. Absent tool names
are inert (`setActiveTools` ignores unknown names — e.g. the borrowed `ask_user_question` is
stripped by its package when `!hasUI`, so the name-keyed entries simply have nothing to enable
in a headless session). There is no `tool_call` backstop for stage scoping (schema removal is the same structural
lever the gate's allowlist uses; `edit`/`write`/`bash` blocking remains the gate's job) and no
config surface for the map (the §8.39 non-interference posture; fail-open on unknown ids covers
version skew). **Bare-session zero-change guarantee:** a session that never engages either
concern gets **zero `setActiveTools` calls** — bare warm sessions stay byte-identical.

## §8.41 · The gist tier (lightweight statements of intent)

A **gist** is a backend-tracked **statement of intent** — a rough, thematically
problem-space-focused note of "something we would likely want to do", upstream of both plans and
objectives. It is **code-informed but carries no implementation detail** (no steps, no roadmap,
no estimates) — it clearly centers the problem domain and may opine, at a strategic altitude, on
the few most consequential solution-domain elements (design/architecture/API/risk); the lightness
lives in the ARTIFACT and the skill guidance, not the machinery. A
gist's **scope** (`plan` | `objective`) records its intended consumption tier: a storage
discriminator on Linear (issue vs project), a header hint on GitHub.

**Registry topology (settled decision).** The two gist stages (`gist-author` → `gist-save`) form
a **separate, disconnected component** — no edges into the main loop. Gists are optional; nothing
routes off "which stage is initial" except the validator, which requires **at least one** initial
stage (zero initials — a pure cycle — stays an error). Consumption happens via the unchanged
§8.29/§8.30 in-place adoption doors (`perk plan from <gist>` /
`perk objective author --from <gist>`), never via stage edges: a gist is consumable because it is
an ordinary OPEN backend object without plan/objective metadata.

**Metadata.** The `perk:gist` label (yellow `fbca04`, description "perk gist issue (a rough
statement of intent)"), lazily created by its create-op on first use — the sixth `perk:*` label.
The `gist-header` metadata block carries `run_id`, `created`, and `scope` (`plan` | `objective`;
lenient read — an unknown stored scope parses to `None`). Per-backend storage:

- **GitHub** — an issue: the html-style `gist-header` block rendered into the body above the
  prose.
- **Linear, scope `plan`** — an issue: clean transcoded prose body + a `gist-header` **native
  attachment** (kind `gist-header`, URL `https://perk.invalid/gist/<run_id>`, title
  "Perk gist", subtitle = scope; the §8.24 attachment-metadata posture).
- **Linear, scope `objective`** — a **project**: the overview carries an inline-code
  `gist-header` block above the transcoded prose. No milestones, no node-issues, no metadata
  sentinel — deliberately light; the overview block IS the identity (projects have no
  attachments).

**The `IssueBackend` gist trio** (docstring contracts mirroring the learn trio):
`find_gist_issue{run_id}` (label + header-key scoped — cannot return a plan/learn issue),
`create_gist_issue{title, body, run_id, scope, dry_run}` (idempotent via the finder; stamps
`scope` into the header), and `list_gist_issues{} -> GistSummary[]{id, title, url, body, scope,
adopted}` — every OPEN `perk:gist` issue; raises on infra failure, never masks as empty. The
`ObjectiveStore` grows the project-tier pair in the no-op-return family:
`create_gist_source{title, prose, run_id, dry_run} -> ObjectiveRef | None` (`None` = "no project
surface" — the CLI falls back to the issue tier; the Linear project store creates/finds the gist
project) and `list_gist_sources{} -> GistSummary[]` (`()` outside the project store).

**Adopted detection.** A gist whose stored metadata ALSO carries the adopting tier's metadata
(distinct keys — adoption stamps additively beside the `gist-header`, no collision) is
**adopted**: on GitHub the `plan-header`/`objective-header` block joins the body; on a Linear
issue the signal is a `plan-header` attachment; on a Linear project it is the **Reconcilable
region** the adoption composer writes into the overview (the objective headers ride the
sentinel's attachments, never an overview block; the original gist overview — with its
`gist-header` — survives verbatim in the Immutable archive note, keeping the project scannable
as a gist). `perk gist list` default **hides** adopted gists (the "what's still unconsumed" backlog
view); `--all` shows everything with an adopted marker. No gist-specific consumption
bookkeeping: in-place adoption means the gist *becomes* the plan/objective and inherits its
lifecycle.

**The save worker (`perk gist create --json`).** Options `--body <path>` (required), `--title`,
`--scope [plan|objective]`, `--run-id`, `--dry-run`. Scope resolution: explicit `--scope` > the
`gist_scope` **handoff** key (a declared `Handoff` field, stashed by `perk gist author --scope`
— the `adopt_from` handoff pattern; best-effort recovery, never blocks a save) > `"plan"`. Scope
`objective` routes to `ObjectiveStore.create_gist_source` first, falling back to the issue tier
on a `None` return; scope `plan` goes to the issue backend directly. Envelope:
`{"success": true, "error_type": null, "gist": {"id", "url", "existed"}, "scope", "dry_run"}` —
opaque string ids (§8.21). Human output prints the created/found line plus a consumption hint
(`perk plan from <id>` / `perk objective author --from <id>`).

**The warm flow** is the full review-first mirror of plan/objective authoring: the `gist_draft`
tool (the third draft-file tool — §8.1's carve-out family; artifact `gist-draft.json`, shape
`{schema_version: 1, title?, scope?, prose}`) keeps the draft current; `plan_review` in a
`gist-author` session reviews the **rendered markdown** (title + scope line + prose — never raw
JSON), VIEW-ONLY first-party (the objective-arm shape; deny+feedback is the change channel);
under the plannotator selection the browser reviewer may edit the rendered gist — an approval
carrying `# Direct Edits` does NOT auto-save (§8.23's gist arm: a fold-and-re-review round);
APPROVED auto-saves via `gistApprovalSave` → the `gist_save` tool / `perk gist create`;
`/gist-save` is the manual failsafe. No draft → soft-skip `reason: "no_gist_draft"`. No session
linkage after save — nothing consumes a gist in-session.

## §8.42 · Objective delivery policy (stacked delivery — the stored domain contract)

**Vocabulary.** The domain terms live in `CONTEXT.md` § Objective delivery (delivery train,
layer, delivery lineage, delivery order, predecessor layer, parent checkpoint, published-head
checkpoint, …); the policy enum is `objective.DeliveryPolicy` (`incremental` | `stacked`).
**Absence of the objective-header `delivery` field ⇒ incremental**; the only value ever
serialized is the literal `"stacked"` — `"incremental"` is tolerated on read but never written.
The read classifier `objective.delivery_policy(header)` maps absent/`None` → incremental and
**fails closed** (`ValueError`) on any other value (junk/tampering never silently degrades to a
policy).

**Objective-header additive fields.** `delivery` and `delivery_lineage` join
`OBJECTIVE_HEADER_FIELDS` (merge-writable via `update_objective_header` on every store).
`render_header_block` emits them **only when set** — deliberately unlike the 8 null-emitting
base keys — so every existing objective and every fresh incremental create renders
byte-identically to before. `delivery_lineage` is the stable ULID identity of the delivery
train across supersession: minted at stacked authoring (`objective.mint_delivery_lineage()` —
the cold door mints/copies and passes the final value down; writers persist what they are
given, §8.45), copied by replan. Forward rule — now **enforced** by the §8.53 replan transfer
(the only policy/base-changing surface): after first publication (a non-empty
checkpoint-claimed prefix) the delivery policy is **immutable** (`policy_immutable`) and the
stored `base` is fixed (`base_immutable`).

**Plan-header additive fields.** Five stacked-layer fields join `PLAN_HEADER_FIELDS` and grow
`PlanHeader` + `PlanHeaderOut` (declared LAST — order is load-bearing): `objective_node_id`
(the roadmap node this plan implements), `delivery_lineage` (the train identity),
`predecessor_plan_id` (the predecessor layer's **stable plan identity — never a branch ref**;
null/absent on the bottom layer), `parent_checkpoint_sha` (the verified parent-ancestry commit;
the objective base for the bottom layer), and `published_head_sha` (the layer branch head last
verified after publication/synchronization). `render_plan_header_fields(header)` is the ONE
blessed emission path for stored headers: the `PlanHeaderOut` dump with each of the five
stripped when `None`, so fresh/incremental saves stay byte-identical. **Absent ≡ null at the
read boundary** for these five (reads are dict-based; a missing key and an explicit null mean
the same thing). They are merge-writable via `update_plan_header` on both backends. `base`
keeps its single meaning — the ultimate integration target, **never** the immediate stacked
parent. The checkpoint pair is written together only after publication verification (both may
be absent pre-publication). Deliberately absent: `planned_against_parent_sha`, any native stack
position, any per-plan copy of the policy. The cache plan-ref (`PlanRef`/`PlanRefModel`/
`PlanRefOut`) has since grown exactly ONE nullable field for launch routing —
`delivery_lineage` (§8.46; the deferred "later node's concern" this sentence originally named);
it routes, never decides — every decision reconstructs the train fresh.

**Deterministic delivery order.** `objective.delivery_order(nodes)` is a pure derivation — a
topological sort of the non-skipped roadmap nodes (edges via `build_graph`, preserving the
explicit-`depends_on`-wins / sequential-inference rule) with the ready pool ordered by
`node_sort_key`; skipped nodes vanish from the result with their edges **contracted
transitively** (a dependency on a skipped node inherits that node's dependencies, recursively).
Total, deterministic, input-order-independent; unknown dep ids ignored (validation reports
them); a cycle raises. The order is **derived, never persisted** (the architecture's authority
table).

**Strict train validation.** `objective.validate_stacked_roadmap(nodes)` (the errors-list
contract): 2–100 **non-skipped** nodes (the one-node error points at saving a standalone plan
instead), duplicate-id / unknown-dep / cycle errors — and **no DAG-shape constraint**: fan-out,
fan-in, and independent nodes are all valid shapes.

**Status.** The `DeliveryTrain` projection (§8.44) now **reads** every field above —
`delivery`/`delivery_lineage` via `delivery_policy`, the five stacked plan-header fields at
the node↔plan join, and `delivery_order`/`validate_stacked_roadmap` as the canonical-order
authority (with the 2–100 authoring bound deliberately filtered at runtime). The objective
fields are now **written** by stacked authoring: the `objective create` cold door populates
`delivery`/`delivery_lineage` on both store write arms, behind the §8.45 validation +
capability preflight; the TS plane carries the reviewed choice
end-to-end (`objective_draft`/`objective_save` → `--delivery`). The **layer-identity trio**
(`objective_node_id`/`delivery_lineage`/`predecessor_plan_id`) is now written at node-linked
plan save (§8.46); the checkpoint pair (`parent_checkpoint_sha`/`published_head_sha`) is
written by the §8.47 publish operation — together, in one write, only after publication
verification.

## §8.45 · Stacked authoring: the reviewed delivery choice + capability preflight

**The choice is typed end-to-end; storage stays absent-for-incremental.** `objective_draft` and
`objective_save` share an optional strict `delivery` enum param (`"incremental" | "stacked"` —
`DELIVERY_PARAM_SCHEMA`/`DeliveryChoice` in `objectiveDraft.ts`; junk → `bad_input`, mirroring
`base`'s tri-state decode). The value rides the `objective-draft.json` artifact (schema_version
stays 1 — an additive optional field; a junk artifact value recovers as absent) and forwards
verbatim as `perk objective create --delivery <choice>` from `saveObjective` and the
approval→save seam. Only `stacked` is ever serialized into the objective header (§8.42's
absence rule); an explicit `incremental` behaves byte-identically to absent at the cold door.
The review surface (`renderObjectiveDraft`) renders an **always-present** prominent
`**Delivery:**` line directly under the title — `**Delivery: STACKED** — … ONE atomic
pull-request train …` vs `**Delivery: incremental** (the default — …)` — so the human
approves the choice explicitly. The authoring agent must **ask** (the
objective-author cold seeds — bare, adopt, and file — and the objective-replan seed state
the ask step; the `perk-objective-author` skill carries the detail): `ask_user_question`
with incremental as the first, recommended option; the answer rides `objective_draft`'s
`delivery` param. A replan
re-asks the policy **pre-publication only** (pre-publication policy changes are legitimate;
once the predecessor's claimed prefix is non-empty the §8.53 door renders the immutability
facts and the seed instructs `delivery: stacked` without re-asking — the save enforces
`policy_immutable` regardless).

**Validation-at-save (stacked only), in the create cold door, in this order:** roadmap parse →
`validate_stacked_roadmap` (errors verbatim under the existing `invalid_roadmap` error_type —
including the one-node "save it as a standalone plan" message; a fan-out/fan-in DAG passes) →
the `--adopt-from` refusal (`invalid_input`: in-place adoption of a stacked objective is
deferred — no roadmap node owns it) → effective probe-base resolution → capability preflight
(**skipped on `--dry-run`**, which stays offline and still validates the bounds) → the write
gate (checked **last**, so the operator gets full honest capability feedback even while
gated) → the store mutation. Stored `base` semantics are unchanged; the **effective probe
base** is explicit `--base` → `[workflow] base` → `git.detect_trunk_branch(repo_root)`
(mirroring the train read path's `header.base or trunk`).

**The capability preflight** is `perk.delivery.capability.preflight_stacked_authoring(repo_root,
*, base)` → a `CapabilityReport` of `CapabilityCheck {name, ok, detail}` rows, probe callables
keyword-injectable (production defaults; tests pass fakes). Import direction stays §8.44's
(delivery → github/substrate; the CLI imports delivery). The checks, each with honest
expected-vs-observed detail:

- **`native-stack`** — `stacks.stack_capability(repo_root)`: a GraphQL schema-introspection
  read (`__type(name: "PullRequest")` → a `stack` field exists). **Fail closed** (introspection
  failure / missing field ⇒ unavailable). Schema presence proves the API surface exists on the
  host, **not** per-repository preview enrollment (the dogfood gate proves the rest).
- **`merge-rules`** — `stacks.base_merge_rules(repo_root, base)` → `MergeRules
  {squash_allowed, merge_queue_required}`: GraphQL `repository { squashMergeAllowed }` (squash
  direct merge must be allowed) + REST `GET repos/{owner}/{repo}/rules/branches/{base}` (any
  effective `merge_queue` rule ⇒ reject). Strict reads — an infra failure raises
  `GitHubError`, which the composer converts to a failed check (can't verify ⇒ don't promise).
- **`remote-base`** — `git.remote_branch_head`: the observed remote base SHA. An absent remote
  base branch is a **failed check** (honest message), never a crash; without it the push
  probes are skipped.
- **`atomic-push`** — one probe per push URL (`git.push_urls`; **all must pass**):
  `git.probe_atomic_push` runs the no-op `git -c push.pushOption= push --atomic --dry-run
  --no-verify --no-signed --no-follow-tags --recurse-submodules=no --porcelain <push-url>
  <base_sha>:refs/heads/<base>` (network timeout 120s, `GIT_TERMINAL_PROMPT=0`; `GitError` on
  failure). The detail states — on success AND failure — that the probe proves **server
  capability and authentication, not branch write permission**.

A preflight failure fails the save with `error_type="capability_unsupported"`, the message
carrying every failed check's expected-vs-observed detail. The probes run against the
Git/GitHub plane **regardless of issue backend** (GitHub is the universal PR plane even when
objectives live on Linear).

**The write gate (retired).** Stacked authoring shipped behind a development-only environment
opt-in (a missing opt-in failed the save with a typed gated refusal) until the publication
dogfood gate passed — a live three-layer train driven end-to-end in the designated dogfood
repo, evidence in `docs/design/stacked-publication-dogfood.md` (2026-08-10). The gate passed
and the opt-in was removed: a stacked save now proceeds directly from a passing capability
preflight to the store mutation.

**Lineage + the store arms.** The cold door computes the final `delivery_lineage` and passes it
down: create mints (`objective.mint_delivery_lineage()`); supersede **copies-or-mints** (reuse
the predecessor header's `delivery_lineage` when present — §8.42's "copied by replan" — else
mint; an infra failure reading the predecessor fails the save rather than silently forking the
train identity). `ObjectiveStore.create_objective` and `.supersede_objective` carry
keyword-only `delivery`/`delivery_lineage` (defaulted `None`) on all three concrete stores,
composed into the **initial** `ObjectiveHeader` atomically (never create-then-merge, which
could crash between writes and persist a stacked-reviewed objective as incremental). `None`
keeps every stored header byte-identical (§8.42). Adoption's write arm is deliberately NOT
widened (the door refuses the combination up front).

## §8.43 · The delivery operation journal + train persistence

**The journal.** A stacked delivery lineage's stack operations (§8.42's vocabulary) are recorded
in an **append-only operation journal**: one strict, marked, schema-versioned comment per event,
physically carried on the objective's **journal carrier** — GitHub: the objective issue's own
comments; Linear: the Project **metadata sentinel issue**'s comments (§8.31's sentinel). Carrier
resolution is the `ObjectiveStore.journal_carrier_id(objective_id)` store method: the issue-tier
id of the carrier (usable with the matching `IssueBackend` comment ops), `None` when the
objective is absent, a raise for a Linear project without a sentinel (a broken perk objective).
The pure grammar/fold lives in `perk/delivery/journal.py`; the adapter is
`perk.delivery.persistence.TrainPersistence`, composed by `resolve_train_persistence(repo_root)`
from `resolve_objective_store` + `resolve_issue_backend` — one committed `[issues]` selection
drives both (the backend-aligned guarantee). Journal reads go through the cursor-paginated
`IssueBackend.read_comments` (never a non-paginating marker finder).

**Marker grammar.** The canonical marker is the HTML comment
`<!-- perk:stack-operation-event:<operation-id>:<event-role> -->`; on Linear the existing marker
transcoder rewrites it to the inline-code form
`` `perk:stack-operation-event:<operation-id>:<event-role>` `` (perk never renders that form
directly). The parser accepts both encodings. A comment body is exactly one marker line + one
`yaml` fence carrying the payload; marker detection is substring-based (like every perk marker),
so ANY body carrying the marker text parses strictly or is corruption. One comment carries
exactly one event. The TRANSFER kind's `before`/`after` payload shapes are owned by
`perk/delivery/transfer.py` (§8.53's manifest models) — the journal stores them as opaque
mappings; outcome events route to the carrier **holding the operation's prepared event** (the
transfer prepares on the predecessor and keeps that operation's later events there).

**Records.** `schema_version` must be the literal `"1"`; payloads parse strictly
(`extra="forbid"`; unknown kinds/roles reject; `operation_id` is a ULID). The event vocabulary is
`prepared | accepted | completed | abandoned` (this intentionally supersedes the earlier
per-effect `effect_observed` design — observable effects are re-read from the remote, never
journaled one-by-one); operation kinds are `publish | sync | adopt | transfer | land`. The
prepared payload is `schema_version, event, operation_id, operation_kind, delivery_lineage,
objective_id, run_id, created, affected_plans, before, after` (declaration order load-bearing);
outcomes are `schema_version, event, operation_id, created, observed`. `before`/`after`/
`observed` stay opaque validated mappings here — their kind-specific shapes are owned by the
operation implementations. **`accepted` is structurally gated to `operation_kind == land`** (the
async-merge UUID is the only sanctioned non-reconstructable handle); the fold treats `accepted`
on any other kind as corruption and the append refuses to write one. A future handle widens this
only at an explicit schema revision.

**Byte identity + corruption.** Two events are “the same” iff their **canonical re-rendered
payloads** (the serialize-only model dump through `yaml.safe_dump(sort_keys=False)`) are
byte-equal — which makes GitHub (HTML marker) and Linear (transcoded marker) events comparable.
A byte-identical duplicate `(operation_id, event-role)` key is an idempotent duplicate (first
occurrence wins). Corruption — always a typed raise (`JournalCorruptionError`), never a silent
skip: a present-but-malformed perk-marked event; a detectably **edited** event (`edited_at` set
— perk never edits or deletes an event); a **conflicting** duplicate (same key, differing
payload); two prepared events for one operation on different carriers; both terminal outcomes;
an orphaned outcome (an outcome whose prepared event is absent anywhere in the fold —
out-of-band deletion of the prepared record; authorized deletion IS corruption); a
foreign-lineage prepared event on the journal.

**Succession folding.** The journal spans superseding objectives: `read_journal` walks the
`supersedes` chain (cycle guard + depth cap 50; breach = corruption), reads every chain member's
carrier, and folds all events against the active objective's `delivery_lineage`. The stored
`supersedes`/`superseded_by` values are the writer's canonical `#<n>` rendering on GitHub, and
the walker feeds them straight back into `get_objective` **and** `journal_carrier_id` — so
`GitHubObjectiveStore`'s id boundary (`_number`) accepts one leading `#` (a store must accept
its own writer's canonical form) and `journal_carrier_id` returns the NORMALIZED issue-tier id
(never the caller's spelling — the carrier must be usable with the numeric issue-tier comment
ops); remaining junk still fails honestly. New operations
append to the **active** objective's carrier; **transfer is the exception at its boundary** — it
prepares on the predecessor before successor creation, and that operation's later events stay on
the same predecessor carrier (outcome appends route to the carrier holding the operation's
prepared event, never copy history). Folding the stream yields the **unresolved** operations
(those lacking a terminal outcome; an `accepted`-only land is still unresolved) — there is no
overwriteable status field. **One unresolved remote-mutating operation per lineage**:
`append_prepared` refuses (`UnresolvedOperationError`) while any operation is unresolved;
recovery appends outcomes, never a second prepared.

**PUBLISH coverage of checkpoint claims (§8.54).** A plan-header checkpoint pair may only
exist because a PUBLISH operation completed, so the folded history is checkable evidence: the
train projection classifies every checkpoint-claiming plan's matching PUBLISH operations
(`affected_plans` naming the plan; other kinds never substitute) with **total precedence** —
any completed match satisfies coverage (older abandoned / newer unresolved attempts
notwithstanding; unresolved ones still ride `active_operation`), else any unresolved match is
the pending `publish_outcome_pending` blocker, else abandoned-only is
`checkpoint_after_abandoned_publish`, else `missing_publish_outcome`. An abandoned PUBLISH is
trusted as all-before evidence because recovery writes it only after the exact branch/PR/stack
proof (§8.51).

**Append discipline.** `append_prepared` cross-checks the record against the active objective
before any write: the record's `objective_id` must name the objective being appended to (a
lineage is shared across supersession, so identity is checked separately) and the record's
`delivery_lineage` must equal the stored one — mismatch is a typed refusal. Every event is
size-validated before posting against the one backend-neutral cap
`JOURNAL_EVENT_MAX_CHARS = 60_000` (margin under GitHub's 65,536-char comment limit; the
conservative shared cap for Linear's undocumented limit) — oversize is a typed refusal, never a
truncated write. Every append is **read back** before its boundary is crossed: the rescan is a
**complete carrier scan** that must find the deterministic event key with a byte-identical
payload — ANY differing payload under the key (even after a byte-identical match) is corruption.
An ambiguous POST (the backend raised; the write may have landed) follows **rescan → one retry
→ typed error**: rescan first (read convergence always precedes any retry); found byte-identical
⇒ success; proven absent ⇒ exactly one retry POST + rescan; still absent/ambiguous ⇒
`JournalAppendAmbiguous` (at most two POST attempts, ever). A **failed rescan is itself
ambiguous** — it proves neither presence nor absence, so it raises `JournalAppendAmbiguous`
without a retry (only a rescan that proved absence earns the retry). The remote effect an event
guards must not proceed past an ambiguous append.

**The rest of the stored train state** writes through `TrainPersistence`'s typed writers — thin
compositions over the §8.42 merge-write seams, enforcing the write-together rules structurally
(no single-field surface): `write_checkpoints` (the `parent_checkpoint_sha` +
`published_head_sha` pair in ONE `update_plan_header` write), `transfer_plan_ownership`
(`objective_id` + `objective_node_id`), `stamp_layer_identity` (`delivery_lineage` +
`predecessor_plan_id`; an explicit null predecessor is contract-legal for the bottom layer), and
`write_delivery_lineage` (`update_objective_header`; lineage *minting* stays the authoring
node's concern).

**Engagement exclusion.** Journal comments carry a `perk:*` sentinel in either encoding, so the
existing engagement classifier (§8.25) classifies them `perk` and the engagement renderers drop
them — journal comments structurally never reach human-engagement inputs (pinned by tests, no
new renderer code). Import direction: `perk.delivery` imports the `perk.backends.*` contracts
one-directionally; nothing in `perk/backends/` or `perk/github/` imports `perk.delivery`.

**Status.** The read side is consumed: the `DeliveryTrain` projection (§8.44) folds the journal
through `read_journal` and surfaces the first unresolved operation. No recovery engine, no
lineage minting, no mutating consumer yet — those land with their owning nodes. The TS plane is
deliberately untouched (no cross-plane consumer yet — mirroring §8.42's posture).

## §8.44 · The DeliveryTrain projection + stack status (read path)

**The projection.** `perk.delivery.train.reconstruct_train` rebuilds one **immutable**
`DeliveryTrain` projection of a stacked objective from the durable authorities — the objective
store (policy, lineage, roadmap), the plan issues (layer identity + checkpoints), the journal
fold (§8.43), Git refs, and GitHub PR + native-stack state. Pure orchestration over narrow
injected Protocols declared in `train.py` (`ObjectiveReader`/`PlanReader`/`JournalReader`/
`GitProbe`/`GitHubProbe`); the production wiring is the leaf `perk/delivery/observe.py`
(`RepoGitProbe`, `GatewayGitHubProbe`, `resolve_train_reads(repo_root)`, and the composed
`reconstruct_repo_train` convenience) — `observe.py` + `capability.py` (§8.45) + `layer.py`
(§8.46) + `finalize.py` (the land path) are the delivery leaves touching `perk.substrate.git` /
`perk.github`. Import
direction stays §8.43's: nothing in
`perk/backends/` or `perk/github/` imports `perk.delivery`. Read-only end to end; the
projection works from a **fresh clone** — no local worktree or branch is authoritative, and
local absence is never an error.

**Layer axes.** Layer state is orthogonal, never one lossy enum: `intent`
(`skipped|unplanned|planned|canceled` — skipped nodes contract out of the rendered layers;
`canceled` is an UNSAFE native cancellation held as a projection-only layer, §8.54),
`publication` (`unpublished|published|publication_drift`), `git`
(`unknown|absent|synced|remote_ahead|diverged|wrong_parent`), `pr`
(`absent|draft|ready|merged|closed|wrong_base`), `membership`
(`not_applicable|unknown|absent|exact|divergent`), `writer` (`free|active|dirty` — read-only:
is a local worktree checked out on the layer's branch, branch identity = plan-header `branch`
else the `plan-<plan-id>` convention), and `finalization` (`not_merged|merged|finalized`).
**Publication** (the load-bearing definition): the FULL checkpoint pair present (the pair is
written together — a half-pair is a `checkpoint_pair_incomplete` blocker and classifies as
drift, never publication; `checkpoint_drift` is reserved for remote/head/ancestry mismatch) AND the remote branch verified at `published_head_sha` (`synced` requires a
POSITIVE parent-ancestry result — unknowable ancestry maps to git `unknown`, never a silent
promotion) AND an open PR at the expected base serving the layer head (AND membership `exact`/
`not_applicable` once ≥2 published PRs exist — `unknown`/`absent`/`divergent` membership all
declassify to drift) ⇒ `published`; checkpoints with any observation mismatch ⇒
`publication_drift`; checkpoints absent ⇒ `unpublished`. `published_prefix_len` is the maximal
contiguous published run from the bottom; a published layer above a non-published one is a
`prefix_gap` blocker. Expected PR base: the predecessor layer's branch, or the objective base
(header `base`, else the detected trunk) for the bottom layer — an observed base mismatch is
surfaced for EVERY PR state (a merged/closed PR keeps its terminal axis value + finalization
while still emitting `pr_wrong_base`). Open PRs additionally corroborate their HEAD against
the layer: a head ref off the layer branch, or a head OID disagreeing with the
observed/recorded head, is a `pr_wrong_head` blocker and disqualifies publication.

**Blockers vs information.** Every discrepancy is a classified finding `{kind, code, message,
node_id?, plan_id?}` whose message embeds the **exact expected-vs-observed values**. Blocker
codes: `missing_lineage`, `missing_plan`, `duplicate_plan_link` (a **global pre-contraction
scan** across every roadmap node — duplicates involving skipped/canceled nodes are preserved),
`wrong_owner`, `node_link_mismatch`, `wrong_lineage`, `lineage_checkpoint_conflict`,
`malformed_plan_header`, `predecessor_mismatch`, `journal_corruption`, `checkpoint_drift`,
`checkpoint_pair_incomplete`, `checkpoint_prefix_gap`, `checkpoint_parent_mismatch` (stored
checkpoint-claim topology, §8.54), `missing_publish_outcome`, `publish_outcome_pending`,
`checkpoint_after_abandoned_publish` (journal coverage of checkpoint claims, §8.54),
`missing_pr`, `pr_wrong_base`, `pr_wrong_head`, `pr_closed`, `prefix_gap`, `stack_missing`,
`stack_divergent`, and the cancellation codes `canceled_status_conflict`,
`canceled_plan_unresolved`, `canceled_published_layer`, `canceled_publication_pending`,
`canceled_remote_work`, `cancellation_evidence_unavailable` (§8.54). Information codes:
`dynamic_singleton`, `all_skipped`, `active_operation` (one per unresolved
operation — see the detailed-status block below), `canceled_unpublished_projected` (§8.54),
`stack_read_unavailable`,
`base_unobserved`, `base_advanced`. Ownership corroboration is fail-closed on absence too: a linked
plan with NO `objective_id` / `objective_node_id` is a `wrong_owner` / `node_link_mismatch`
blocker (only lineage absence gets the pre-publication exception).
**Runtime never enforces the 2–100 authoring bound**: a one-layer order renders with
`dynamic_singleton` (membership `not_applicable`), a zero-layer order with `all_skipped`;
only structural invalidity that makes the canonical order underivable (duplicate ids /
unknown deps / a cycle) is the typed `invalid_train` failure carrying the exact error list.
Both lifecycle INFO messages are **projection-only** claims: `dynamic_singleton` says the
train *projects as* a single layer (lineage retained, membership not applicable, status
performs no landing) and `all_skipped` says every node *projects as* skipped (no layer
remains, status performs no objective completion) — singleton landing and all-skipped
objective completion are the landing mutation's contract (§8.56).

**Pipeline ordering (§8.54's crash-window-honest reordering).** For a stacked objective the
pipeline is: resolve + policy → lineage + ONE journal fold (before any contraction —
unresolved facts, PUBLISH coverage, and cancellation evidence all read it; corruption folds
``None`` and every consumer fails its question closed) → the global duplicate-backlink scan →
ONE `git fetch` → native-cancellation classification (§8.54's exact proof; unsafe nodes gain
projection-only PENDING ordering surrogates, never returned/persisted) → roadmap validation +
`delivery_order` over the effective nodes → the node↔plan join (idempotent per layer — a plan
preloaded by the cancellation proof is never re-joined, so canonical findings emit once) →
PUBLISH coverage + checkpoint topology → predecessors → Git observation (reusing the fetch) →
PRs → publication → membership → prefix → base → readiness. `DeliveryTrain` additionally
carries the §8.54 projection facts `projected_canceled_nodes` /
`repairable_canceled_nodes` (default-empty tuples of `ProjectedCancellation(node_id,
persisted_status)`).

**Failure-posture split.** Stable authorities hard-fail: a failed objective read, plan join,
journal **carrier** read, or `git fetch` is a command failure — `TrainReconstructionError`
with a stable `error_type` (`objective_not_found | invalid_delivery_policy | invalid_train |
git_error | github_error | supersession_corruption`). Only two reads degrade: the **preview**
native-stack read (membership `unknown` + information `stack_read_unavailable`, never a
blocker — but unverifiable membership still declassifies the affected layers' publication to
drift: the information posture governs the *finding*, not the verification bar) and journal
**corruption** (`JournalCorruptionError` → the `journal_corruption` blocker; unresolved-
operation facts report unknown). A superseded objective **redirects forward** along
`superseded_by` (cycle guard + depth cap 50; breach ⇒ `supersession_corruption`) to the active
objective and reports `redirected_from`. An incremental objective short-circuits before any
Git/GitHub work into the successful `NoDeliveryTrain` answer; a junk `delivery` value fails
closed (`invalid_delivery_policy`). `delivery: stacked` without a lineage renders the train
with the `missing_lineage` blocker and skips the journal fold (report, don't abort).

**The GitHub-native read adapter.** `perk/github/stacks.py` splits the reads by schema
stability: `pr_delivery_facts(number, repo_root)` reads the **stable** GraphQL surface
(`state,isDraft,baseRefName,headRefName,headRefOid`) with the honest lookup convention
(`None` on a missing PR; `GitHubError` on infra/malformed payload) — every stable field is
REQUIRED at the wire boundary and `state` is constrained to `OPEN|CLOSED|MERGED`, so a partial
payload raises rather than reading as empty/false observations; `pr_stack(number, repo_root)`
reads the **public-preview** fields (`PullRequest.stack { number size
entries(first:100){nodes{position pullRequest{number}} pageInfo{hasNextPage}} }`,
`stackEntry{position}`) in a **separate query** with the tolerant posture — any failure that
is not a PR lookup miss returns `StackObservation(available=False)`, and every selected
preview field (incl. `pageInfo.hasNextPage`) is required, so a malformed/partial preview shape
degrades rather than partially parsing (exactness relies on OBSERVED non-truncation); a null
`stack` with `available=True` means genuinely not stacked; `hasNextPage` ⇒ `truncated` (a perk
train never exceeds 100 layers, so a bigger stack is never exact). Entries are sorted by
`position` in the converter. `_graphql_proc`/`_graphql` live in `perk/github/_exec.py` (promoted from
`reviews.py` when the second GraphQL call site appeared). Native membership over the projection:
<2 published open PRs ⇒ `not_applicable`; ≥2 ⇒ read the stack through the bottom published PR
— unavailable ⇒ `unknown` (information), null stack ⇒ `absent` + `stack_missing`, entries
exactly the published PRs bottom→top (contiguous positions, no extras, not truncated) ⇒
`exact`, anything else ⇒ `divergent` + `stack_divergent`.

**The base-head observation.** The projection additionally reads the objective base's LIVE
remote head through `GitProbe.base_head` (production: `ls-remote`, never the fetched
remote-tracking ref — a plain fetch has no `--prune`, so a deleted remote base leaves a
stale tracking ref that still resolves). The read is **tolerant-degrade** where §8.49's sync
mutator fails closed: a read failure or an absent ref is the INFO finding `base_unobserved`
(naming which arm fired), never a blocker or an abort. The positively observed head is
carried as `DeliveryTrain.observed_base_head_sha` (`null` = not positively observed). When
the published prefix is non-empty, the bottom layer's `parent_checkpoint_sha` is set, and
the observed head differs from it, the INFO finding `base_advanced` carries both SHAs and
the remediation (`perk objective stack sync <N> --base`).

**Detailed status (all-unresolved exposure + the machine-local observations).** The
projection exposes EVERY unresolved operation: `DeliveryTrain.unresolved_operations` is the
full journal-fold tuple (oldest→newest); the legacy `unresolved_operation` stays its first
element (additive growth — no consumer breaks), and each unresolved operation emits one
`active_operation` INFO finding. Beside the durable projection the **CLI** adds two
machine-local observations (they live in the command, not the projection — a fresh clone's
train must never depend on another machine's residue): (a) this lineage's pending
continuation manifest (§8.49), read tolerantly — a malformed lineage or unreadable directory
reports no pending continuation, and an unparseable manifest file reports a
`parseable: false` row (nulls for every field the unreadable file cannot account for) rather
than being hidden; (b) the orphaned-sync-residue observation through recover's shared
classifier (§8.51), **fail-honest**: a Config-load or git/fs read failure — and the
classifier's own unparseable-manifest skip — reports `observed: false` plus the reason;
`observed: true` with empty lists means *genuinely clean*. The reported worktrees include
the stale worktree-admin entries (directory gone, inventory record left) beside the on-disk
ones — both are would-be sweep targets. An unobserved state is never
serialized as clean empty lists (the Config load is tolerant only in that it degrades the
observation, never the command).

**The cold worker.** `perk objective stack status [OBJECTIVE] [--json]`
(`commands/objective/stack/`, the recursive group-dir template; the group carries `status` +
`sync` (§8.49) + `recover` (§8.51) + `land` (§8.55 dry-run readiness + §8.56 the landing
mutation); the shared objective resolution and run-id resolution live in
`stack/shared.py`). Resolution:
explicit argument → the plan worktree's `cache.plan-ref` `objective_id` → a typed
`no_objective` refusal. Envelope (`ObjectiveStackStatusOut`, snapshotted at
`shared/schemas/outputs/objective-stack-status.schema.json`): `{success, error_type,
objective{id,url,redirected_from}, delivery: incremental|stacked, train|null, no_train|null,
operations[], continuation|null, orphaned_residue}` — the last three are the additive
detailed-status growth: `operations` mirrors `unresolved_operations`
(`{operation_id, kind, prepared_created}` each), `continuation` is the manifest observation
(`{operation_id|null, conflict_node_id|null, adopted_node|null, created|null,
worktree_path|null, manifest_path, parseable}`), `orphaned_residue` is the honest residue
block (`{observed, reason|null, worktrees[], refs[]}`). `train` carries `{delivery_lineage,
base, published_prefix_len, layers[], unresolved_operation|null, blockers[], information[],
next_build_ready, observed_base_head_sha}` (the readiness block, §8.46; the base observation
above). Exit codes: **blockers found ⇒ exit
0** (status is a successful *detection*, mirroring `objective doctor`'s report-vs-abort
split); `1` = the typed failures above (+ `no_objective`, backend errors as `github_error`);
`2` = not-a-repo. `--json` → stdout, human render → stderr (one line per layer bottom→top,
then `blockers:`/`information:` sections, then the pending-continuation and orphaned-residue
lines with their remediation hints; the incremental case prints the no-train explanation; a
dim `redirected from #N` note when redirected).

**Status.** Read path only: this section mutates nothing remote. The capability probes (stack
availability, direct-merge/queue rules, atomic-push dry-run) have since landed — §8.45 — and
remain read-only (the dry-run push is a no-op); build-ready derivation now rides the
projection (§8.46); suffix synchronization has since landed as its own operation (§8.49);
recovery and the warm stack surface (`/objective-stack` + the typed stack tools) have since
landed (§8.51); atomic landing has since landed (§8.55 readiness + §8.56 the mutation);
doctor findings are a later node's contract.

## §8.46 · Stacked build readiness + parent-aware execution

**Build readiness is a derived fact of the projection — never a node status.**
`reconstruct_train` computes a frozen `BuildReadiness {next_node_id, ready, reason}` at the end
of the pipeline and carries it on `DeliveryTrain.build_readiness`. `next_node_id` is the first
layer in delivery order whose `publication` is not `PUBLISHED` (`None` when every layer is
published, or the layer list is empty/all-skipped — the contiguous-prefix invariant makes the
candidate's predecessor published by construction; a violation is already a `prefix_gap`
blocker). **The veto set is train-wide and fail-closed**: `ready` is `True` iff a candidate
exists AND the train has **no BLOCKER findings** AND `unresolved_operation is None`; `reason`
is `None` when ready, otherwise it embeds the exact veto (the blocker codes + messages
verbatim, the unresolved operation id/kind, or "all layers published"). A dynamic singleton is
buildable under the bottom-layer rule; derivation mutates no axis and `TERMINAL` semantics are
untouched. `perk objective stack status` surfaces it additively: the `--json` `train` object
gains `next_build_ready {node_id, ready, reason}` (schema snapshot regenerated) and the human
render one line (`next build-ready: <id>` / `build blocked: <reason>`).

**Stacked selection replaces dep-terminal planning gating.** For a stacked objective the single
planning candidate is the readiness-derived next node — roadmap DAG deps still shape
`delivery_order` but stop acting as a separate terminal-status planning gate, which is what
permits planning layer k+1 while layer k is published-but-unmerged. The one shared seam is
`stacked_selection(repo_root, state)` (`commands/objective/shared.py`): `None` for incremental
(byte-identical behavior), else a `StackedSelection {kind, node, ready, reason, train}` with
`kind ∈ build_blocked | plannable | in_flight | no_candidate` (`no_candidate` = every layer
published → consumers fall through to the existing graph classification; completion semantics
unchanged). It reconstructs the train live (`reconstruct_repo_train`, the composed
`observe.py` convenience); `TrainReconstructionError` maps to a typed CLI error preserving its
`error_type`. Three consumers: the **plan door** (`perk objective plan` — auto-select takes the
candidate; `build_blocked` refuses with `error_type="node_not_build_ready"` + a
`perk objective stack status <N>` hint; an explicit `--node` must equal the candidate or the
same refusal names the actually-ready node; `in_flight` keeps the incremental
`objective_in_flight` message shape), **`perk objective next`** (`next_node` becomes the
plannable candidate or `null`, plus an additive `build_ready {ready, reason}` block), and the
**`objective run` supervisor** (a new honest `action: "build_blocked"` report arm, exit 0,
carrying `reason` + the stack-status remediation). **`--dry-run` skips train reconstruction**
on the plan door and the run supervisor (offline graph classification kept) — and BOTH
dry-run payloads gain `"build_readiness": "unchecked (dry-run)"` (stacked only; incremental
payloads stay byte-identical), saying so rather than pretending the check ran. `objective show`
stays a status renderer; the run supervisor's repair and lower-address prioritization has landed
in §8.52.

**Predecessor context seeds stacked planning.** The plan door's seed gains a stacked-only DATA
block (`_layer_context_block` → the `layer_context` template var; incremental seeds stay
byte-identical): the layer's position in the delivery order; for a child layer the predecessor
node/plan, its branch, and the verified remote head from the reconstructed train's observed
facts (the objective base for the bottom layer); a note that `origin/<parent branch>` is
already fetched and locally inspectable; and the explicit statement that perk records **no
planning-time parent SHA** — later movement of the predecessor/codebase is a normal
implementation danger.

**Save-time layer identity.** A **node-linked** save (`objective_id` + `node_id`, real run)
reads the linked objective **strictly** — a failed read fails the save (`github_error`) and a
proven-missing objective is a typed `objective_not_found` refusal; a save that cannot
determine the delivery policy must not guess or proceed unstamped (unlinked saves keep the
fail-soft base lookup). When the objective is
stacked, `perk plan save` composes the **layer-identity trio** into the plan header on every
write arm (initial create, the re-save `update_plan_header` merge, and the `save_node_plan`
unification arm via the same rendered fields): `objective_node_id = node_id`,
`delivery_lineage` = the objective header's lineage, `predecessor_plan_id` = the
delivery-order predecessor node's linked plan id (`None`/absent on the bottom layer). Two
typed refusals fire **before any write**: a stacked objective with a missing/invalid
`delivery_lineage` is **`missing_lineage`** (an unstamped routing field would silently send a
child layer down the incremental path), and a
non-bottom save whose predecessor node has no linked plan is
**`stacked_predecessor_missing`**. `parent_checkpoint_sha`/
`published_head_sha` stay unwritten — the durable checkpoint pair is publication-owned.
Incremental saves stay byte-identical. A dry run composes the trio best-effort from the same
read and omits it when the objective is unreadable.

**The `PlanRef` routing field.** `PlanRef`/`PlanRefModel`/`PlanRefOut` grow one nullable field,
`delivery_lineage` (amending §8.42's deliberate-non-growth note): stamped at save, recovered by
`resume.reconstruct_plan_ref` from the plan header (the field-census tripwire holds writer +
reconstructor in lockstep). It only **routes** a launch into the stacked path — every decision
still reconstructs the train fresh; the ref is never train-authoritative.

**`LayerContext` + the one parent-preparation path** (`perk/delivery/layer.py`, a delivery leaf
touching `perk.substrate.git` alongside `observe.py`/`capability.py`). Frozen
`LayerContext {objective_id, node_id, plan_id, delivery_lineage, predecessor_plan_id, base,
parent_branch, branch}` — `parent_branch` equals `base` for the bottom layer, else the
predecessor layer's branch (the train's branch resolution: plan-header `branch` else
`plan-<plan-id>`); `branch` is this layer's `plan-<plan_id>`. `derive_layer_context(train, *,
plan_id)` is pure (typed `unknown_layer`/`stacked_predecessor_missing` errors);
`require_ready_layer` additionally requires the layer to BE the readiness candidate
(`node_not_build_ready` carrying the exact veto). `prepare_layer_start(repo_root, ctx, *,
fetch=…, remote_head=…, resolve_commit=…)` (keyword-injectable probes, the `capability.py`
precedent) fetches exactly the parent ref, reads the live remote head, and verifies the commit
resolves locally — **always the LATEST head, never a stored checkpoint**; an absent remote
parent (`parent_missing`) or an unresolvable head (`parent_unverified`) is a typed error naming
the expected ref. The result is the **operational** record: `cache.write_layer_context(root,
ctx, parent_sha)` atomically writes `.perk/workflow/layer-context.json` (`LayerContextOut`:
the full context + verified `parent_sha` + `prepared_at`) — session-scoped, gitignored with the
workflow dir, and **NEVER authoritative** (publication re-verifies live; the durable
`parent_checkpoint_sha`/`published_head_sha` pair stays publication-owned).

**Local launch (fresh creation only).** `resolve_worktree`'s fresh-create arm, when
`plan_ref.delivery_lineage` is set and no `origin/plan-<id>` exists: reconstruct the train,
require the ready candidate, `prepare_layer_start`, then `git worktree add` **at the verified
`parent_sha`** (a real commit, not a moving ref) and write `layer-context.json` into the fresh
worktree. An explicit `--base` on a stacked layer is a typed `invalid_input` refusal (the
parent is derived, never chosen). Explicit `--worktree NAME`, reuse, `worktree: none`, and the
resume arm (an existing `origin/plan-<id>`) are untouched — the parent-aware path only governs
creation; a stacked dry run reports `"stacked layer — parent derived at create"` and stays
offline.

**Remote positioning relocates into `run_worker`.** The managed workflow's "Check out the plan
branch" shell step is **deleted** (§8.14 amended; the §8.13 input contract and `gh auth
setup-git` are unchanged); `run_worker` now calls `position_branch(repo_root, plan_ref, base)`
before `position_worktree`: an existing remote `plan-<N>` (either policy) → checkout +
`reset --hard origin/plan-<N>`; absent + incremental → create from `origin/<base>`
(behavior-equivalent to the removed shell arms; `base` = the dispatched input, else the plan's
pinned base, else the detected trunk — the `base` param is now consumed); absent + stacked →
the same readiness gate + `prepare_layer_start`, then `git checkout -b plan-<N> <parent_sha>`
and `layer-context.json`. The branch-creation **gesture** intentionally differs (local
`worktree add` vs remote in-place `checkout -b`) — a named §8.38 difference; both consume the
same `LayerContext` + `prepare_layer_start`, and local/remote parity is proven for fresh
creation (same start SHA, byte-identical `layer-context.json`, timestamps excepted).

**Status.** Everything here is inert for incremental objectives; stacked authoring and layer
publication are supported (the §8.45 dogfood gate passed —
`docs/design/stacked-publication-dogfood.md`; §8.47's `/submit` route writes the checkpoint
pair); published-suffix synchronization is available explicitly (§8.49) and converges
automatically from submit/address (§8.52); atomic landing is §8.56's contract — and
`perk pr land` / `/land` still refuse stacked lineage before any mutation (stacked layers
land only as one train).

## §8.47 · Stacked layer publication (/submit → the delivery publish operation)

**Routing (no new verb).** `perk pr submit`'s worker (`_pr_submit_impl`) routes on the
delivery-lineage discriminator: stacked ⟺ the cache plan-ref carries `delivery_lineage`, OR
(after the plan read) the plan header does — **header wins**: a stale cached ref without the
lineage must not silently route incremental. The warm `/submit` door and its
`perk pr submit --json` delegation are unchanged shapes; `--dry-run` stays FIRST and fully
offline (no routing, byte-identical envelope). The incremental path is untouched — no
reconstruction, byte-identical behavior (the additive envelope fields serialize as null).
(The §8.45 development write gate, which this route reused while stacked delivery was under
development, is retired — the dogfood gate passed.)

**The publish operation** is `perk.delivery.publish.publish_layer` (a gateway-touching
delivery leaf; every effectful callable keyword-injectable, the `capability.py` pattern). Its
required automatic-cascade dependencies are `remote_writers` and `worktree_root`; the injectable
`synchronize` seam defaults to §8.49's operation. Submit owns the identity-field composition
(`header_fields`, a `pr_number → fields` builder
reusing the incremental fields + `_merge_impl_run_ids`) and the PR-body composition; the
operation owns WHEN they are written. `PreparedRecord.run_id` resolves `--run-id` → the plan
header's `run_id`; both absent is a typed `invalid_input` refusal (a defensive arm — the
header run id is stamped at save). The protocol, in order:

1. **Reconstruct** the train fresh (`reconstruct_repo_train`, via the plan header's
   `objective_id`); no train / plan not a layer → `not_stacked`.
2. **Route on the checkpoint-claimed prefix before reading the publish journal fold.** Derive it
   through §8.49's public `derive_claimed_prefix` helper. If this plan is claimed and a claimed
   successor exists, delegate immediately to trigger-scoped synchronization (§8.52); sync owns the
   journal routing for this arm, including unresolved SYNC/ADOPT and pending continuations. Never
   route on `published_prefix_len`: operational drift may declassify a claimed successor and must
   reach sync's typed preflight instead of silently selecting republish. Otherwise read the fold:
   an unresolved PUBLISH whose `affected_plans` is exactly this plan → the resume path; any other
   unresolved operation → `unresolved_operation`.
3. **Candidate gate outside the cascade arm**: the claimed top that is also the published top →
   the republish/converge arm; otherwise `require_ready_layer` (a veto re-raises as
   `node_not_build_ready`).
4. **Capability recheck** — only when this publish will mutate the native stack:
   `stacks.stack_capability` must still hold → else `stack_capability_lost`. Checked twice:
   up front on the fresh route (position ≥ 2, before any effect — the cheap early refusal)
   AND at the create/append mutation seam itself (covering the resume and republish routes;
   an already-converged membership never probes). **Recorded deviation (since discharged):**
   the §8.45 atomic-push dry-run probe is NOT rerun — the single-ref exact-lease push fails
   honestly on its own; the multi-ref atomic probe now lives in §8.49's sync preflight.
5. **Resolve facts**: `prepare_layer_start` fetches + verifies the LATEST parent head
   (`parent_sha`); the layer's own remote head is the exact lease observation
   (`before_branch_sha`, null = the absence lease); the local branch head is the candidate.
6. **Ancestry**: the candidate must contain `parent_sha` → else `stale_parent` (the message
   tells the human to rebase onto the parent branch — the conflict-resolver gesture).
7. **Prepared record** (journal-first — appended via the §8.43 read-back discipline before
   ANY remote mutation). The publish-kind shapes (the journal envelope stays
   opaque-validated):
   `before: {branch: {ref, sha|null}, pr: {number|null, base|null, head_sha|null,
   state|null}, stack: {members: [bottom→top]|null}}` — the PR observed via the strict facts
   read when the train already knows its number; the stack observed on the bottom layer's PR.
   `after: {branch: {ref, sha}, pr: {base: <parent branch>, head_sha}, stack:
   {members: […]} | {not_applicable: true}}` — `not_applicable` for the bottom layer; a
   child layer's own not-yet-created PR is recorded as the sentinel `"self"` (every other
   member is a concrete number); recovery resolves `"self"` through the unique PR by exact
   head selector.
8. **Push** under the exact lease (`git.push_with_exact_lease`:
   `--force-with-lease=refs/heads/<branch>:<expect>`, empty expect = must-not-exist; one
   ref, `--atomic` deliberately absent). A lease rejection → `push_rejected`, the operation
   left unresolved (recoverable; blocks successor readiness).
9. **PR create/converge**: `create_pr` (idempotent by head, draft-by-default); a MERGED
   reuse → `pr_already_merged`; CLOSED → reopen; an observed base ≠ the parent branch →
   `update_pr_base` (the converge). Then the create-then-update body pass +
   `validate_pr_body` (failure → `postcondition_unverified`). The draft state of an existing
   PR is never changed — draft-by-default is for creation only; `/ready` stays the separate
   per-layer gesture.
10. **Stack membership convergence** (position ≥ 2 only; the bottom layer skips stack work).
    Pre-mutation convergence wait: the PR must reflect the pushed head + converged base
    (bounded observations, else `remote_settling_timeout`). Classify observed-before: exactly
    desired → already converged (no mutation); nothing observed at position 2 → **create**
    (`POST /stacks`, bottom→top); the exact prefix with this PR stackless → **append**
    (`POST /stacks/{n}/add`, only the exact missing suffix); anything else (partial,
    reordered, extras, a foreign stack) → `stack_registration_drift`, unresolved. The
    mutations are **total** gateway calls (`gh api --include`): the helper captures the HTTP
    status + `Retry-After` and never raises for non-2xx/network outcomes. Post-mutation
    classification (after applied, ambiguous network/5xx, 422, or rate-limited): a
    rate-limited reply with `Retry-After` sleeps `min(retry_after, 60s)` once; then refetch
    and classify — **exact-after → success**; **unchanged-before → retryable** (one bounded
    retry after the settling interval, then `stack_registration_failed`);
    **partial/different → `stack_registration_drift`**; a refetch that raises →
    `postcondition_unverified`. Mutations are strictly serialized: sequential in-process;
    cross-machine serialization = the one-unresolved-operation journal gate + the exact push
    lease. Never a blind re-POST.
11. **Postconditions** (the full remote refetch): branch head == candidate; PR OPEN (draft or
    ready) onto the parent branch at the candidate head; position ≥ 2: exactly the desired
    membership/order. A mismatch is the matching drift type; an unreadable refetch is
    `postcondition_unverified` — fail closed, operation unresolved.
12. **Persist, then complete** (write ordering is load-bearing): (a) the plan-header identity
    write (branch/pr/lifecycle_stage/merged `impl_run_ids`); (b) the checkpoint pair in ONE
    write (`TrainPersistence.write_checkpoints` — the §8.42 rule: only after verification);
    (c) the `completed` outcome (observed = branch sha, PR number, stack members|null). A
    crash between (a)–(c) reconstructs as roll-forward — all three are merge-writes /
    idempotent byte-identical appends.

**The republish/converge arm** (the TOP published layer only). The observed remote head must
equal the `published_head_sha` checkpoint → else `remote_drift` (out-of-band movement;
adoption is a later recovery surface). Candidate == published head AND PR facts + membership
already desired → the **pure no-op convergence**: no prepared record, `operation_id: null`,
observed facts returned. Otherwise (an amended top layer) the train must be blocker-free and
the full protocol runs with `before_branch_sha = published_head_sha` (membership is already
exact, so step 10 classifies "already converged"; the checkpoints move to the new head).
Rewriting the top layer is safe because no claimed successor exists above it. A claimed lower
layer instead enters the automatic cascade before this arm.

**The resume path** (an unresolved PUBLISH for this plan): re-derive the expected states from
the prepared record, observe fresh. The freshly reconstructed context must still AGREE with
the record's desired state before either same-operation arm runs — the delivery lineage, the
branch ref, the recorded PR base vs the re-derived parent branch, and the recorded stack
composition (the concrete prefix members vs the live train's; a concrete recorded own-PR pin
must be rediscovered exactly by the head selector) — any mismatch is `publication_drift`
(authority drift while unresolved is never silently re-derived into the old operation).
Branch at `after` → roll forward through steps 9–12 under the same operation (the `"self"`
member resolves through the unique PR by head). Branch at `before` with the PR + stack also
at their before states: an unchanged local candidate → retry under the same operation from
step 8; a moved candidate → append `abandoned` (observed = the proof: branch/PR/stack all at
before) and prepare FRESH in the same invocation. Anything mixed/unrelated →
`publication_drift`, fail closed, operation unresolved.

**The error vocabulary is bounded.** `PublicationError.error_type` draws from: `not_stacked`,
`unresolved_operation`, `node_not_build_ready`, `stack_capability_lost`, `remote_drift`,
`stale_parent`, `push_rejected`,
`pr_already_merged`, `remote_settling_timeout`, `stack_registration_drift`,
`stack_registration_failed`, `postcondition_unverified`, `publication_drift`, `git_error`,
`github_error` — plus the §8.46 layer codes passed through verbatim (`parent_missing`,
`parent_unverified`, `stacked_predecessor_missing`): honest self-describing preparation
failures, deliberately not folded into a vaguer code.

**Surface changes.** The github tier gains the `stack` state key; the submit stage reads
`[cache.plan-ref, github.plan, github.objective, github.stack]` and writes
`[github.pr, github.plan, github.objective, github.stack]` (the journal lives on the
objective's carrier; the stack is its own authority). `PrSubmitOut` gains additive optional
`delivery` (`"stacked"`), `stack {number, size, position}`, `operation_id`, and the §8.52
cascade-only `operation` block (all null on incremental); the envelope's `base` carries the PR's
real merge target — the parent branch — so the warm door's conflict-resolver rebases onto the
parent. `extension/doors/submit.ts` decodes the fields leniently (malformed → absent,
never a sunk decode) and appends a short stack/cascade suffix to the success message. The stacked PR
body inserts two sections between the plan link and the `<details>` embed — `### This layer`
(one informational disclaimer: the delivery train is authoritative; the body refreshes only
at publication) and a `### Train context` table bottom→top — both **non-authoritative**
presentation; `validate_pr_body` and the closing-keyword invariant are unchanged.

## §8.48 · The learn-harvest factory (door + manifest contract)

**The door.** `perk learn harvest [--from <path>]...` — a seeded cold door (the seeded-door
pipeline, `perk/cli/commands/seeded_door.py`) borrowing the `objective-author` stage
descriptor via `prompt_override` (no new registry stage, no `DEDICATED_STAGES` change),
`binding_trigger="command:learn-harvest"`, and **no GitHub read up front** (no
`require_github`, `backend_errors=()`) — the first backend mutation of a harvest run is the
in-session `objective_save`. `--from` takes a file or directory inside `docs/learned/`
(repo-root-relative or absolute), repeatable, union-deduped in corpus order; the empty
default is the full eligible corpus. Cold-only: there is no warm `/learn-harvest` door.

**The revision boundary (ordering, stated honestly).** The guarded fast-forward (the
`_sync_main_checkout` behavior + guards — best-effort, loud-but-non-fatal: it warns and skips
on detached/dirty/no-upstream/diverged; a remote-less checkout is a **silent** no-op) runs on
the **invocation checkout** BEFORE gather; the in-launch sync is suppressed
(`sync_main=False` unconditionally); the pre-gather sync is skipped on `--dry-run` and
`--no-sync`. The manifest's `commit_sha` is HEAD at gather time, captured immediately
post-sync — the revision **context** of a working-tree gather, not a clean-tree attestation
(a dirty tree may diverge; the sync warns and skips it). The claim is strictly about
*ordering*: one guarded fast-forward before gather, none after — nothing perk does moves the
tree between gather and session. An unresolvable HEAD (unborn) and a `docs/learned` root that
resolves outside the repository (a symlinked corpus root — the path-traversal guard) are
`invalid_input` refusals.

**The manifest.** Schema
`{schema_version: "1" (string), commit_sha, lanes: [{id, docs: [{path, title, read_when}]}]}`;
`None` cues are carried as JSON `null`, never dropped. Written run-scoped at
`.perk/workflow/scratch/runs/<run_id>/harvest-manifest.json` where `<run_id>` is the launched
session's `run_id_override` — pre-minted by the door so the manifest path and the session
agree on one id; written on `--dry-run` too (the materialize-on-dry-run posture; the orphaned
scratch dir is normal state-prune territory). The `run_harvest_wave` tool accepts ONLY this
path and re-validates the file: it takes one `manifest_path` param, but the param is a relay
handshake, not an authority — the execute recovers the session's claimed `run_id` from the
rebuilt workflow-state, derives the one acceptable path
`runScratchDir(run_id)/harvest-manifest.json`, requires the param to be absolute and
realpath-identical to it, and then reads the derived path, never the param. A session with no
run-scoped manifest is refused `bad_state` — the structural binding justifying the tool's
`READ_ONLY_TOOLS` carve-in (§8.3).

**The analyst wave (`run_harvest_wave`).** The flow-scoped wave tool
(`extension/doors/harvestWaveTools.ts` + `extension/waves/harvestWave.ts` on the report-wave
module): blocking, `best-effort` completeness, ONE attempt, NO retry — a failed analyst lane
is an explicitly-reported skipped lane; only a wave-level failure fails the call (a loud
soft-fail whose `error_type` is the wave-level reason). Strict pre-spawn validation (any
deviation refuses before spawn with a named detail): byte-identical `schema_version: "1"`,
string `commit_sha`, non-empty lanes with unique non-empty ids and non-empty docs, lexical
`docs/learned/` containment on every doc path PLUS resolved-symlink containment for existing
doc paths (realpath'd against the resolved corpus root, which must itself resolve inside the
resolved checkout — mirroring the gather core's symlinked-corpus-root guard; nonexistent doc
paths skip the resolved layer, and doc existence itself is not required).
Multi-lane only: a single-lane manifest is refused `bad_input` toward the seed's
direct-analysis path (the fallback state table's first row, enforced in code). One
`perk.harvest-analyst` lane per manifest lane; the
per-lane report is the wrapper `{opportunities, omitted_count}` — `opportunities` an array of
at most 5 items (`HARVEST_MAX_OPPORTUNITIES`, the one constant shared by the schema's
`maxItems` and the sanitizer's over-cap arm), each item
`{title, kind ∈ bug-risk|simplification|elegance|roundaboutness, pointer, evidence,
confidence ∈ high|medium|low}`, and `omitted_count` a non-negative integer. Each returned
report is defensively re-decoded (the aggregate crossed
a process boundary; an undecodable/over-cap report degrades that lane to `malformed-report`),
and a deterministic post-pass stamps each opportunity `pointer_status:
"resolved"|"unresolved"` — the path segment before the first `::`, judged by lexical
containment + existence on the checkout only (grounding stays the parent's mandatory pointer
re-read). `[models.subagents] harvest-analyst` rides the wave as the workflow-level model
default. Census: `PERK_TOOLS` + `READ_ONLY_TOOLS`, deliberately NO `STAGE_TOOLS`/drive
coverage (harvest is cold-only and gate-on; the gate-ON set ignores stage lists). The seed
teaches the fallback state table and names the tool for multi-lane manifests.

**The partition rule** (by reference to the landed core, `perk/learn/harvest.py`): group by
the first path component under `docs/learned/` (top-level docs → the literal `root`),
path-sorted within a group, chunked at max 8 docs/lane (`MAX_LANE_DOCS`), stable 1-based
`<category>-<n>` ids; single- vs multi-lane **routing** (direct analysis vs the wave) is
decided by the lane count (`len(partition_lanes(docs))`), never a total-doc-count check.

**CLI observability.** The `--dry-run`/`--json` payload keys:
`{success, error_type, manifest_path, doc_count, lane_count, lane_ids, launched: false}`.
The selection-specific error vocabulary: `invalid_from` / `no_harvest_docs`; the family
generics ride the same envelope — `remote_blocked`,
`invalid_input` (unborn HEAD / an out-of-tree corpus root), `manifest_write_failed` (the
run-scoped manifest could not be written), `not_a_repo`. Stable exits: `0` ok · `1`
op-failure/refusal · `2` not-a-repo.

**The fallback state table.** The settled rows, taught by the seed + the `perk-learn-harvest`
skill: exactly one lane → direct in-session analysis; multiple lanes → ONE `run_harvest_wave`
call relaying the seed-rendered manifest path verbatim. A failed/skipped lane → retain the
successful lanes and report the uncovered lanes honestly, NO retry — always named in the
session's final summary, with a short coverage note in the objective prose only when an
objective is actually authored (the no-survivor branch stops before `objective_draft` and
carries coverage in its evidence report instead). ANY `run_harvest_wave` failure on a
multi-lane manifest — a pre-spawn refusal (`bad_input`/`bad_state`) or a wave-level failure —
or zero valid reports → the incomplete-harvest outcome, recommending a bounded `--from`
re-run — never a whole-corpus direct read in one context, never improvisation. A lane with a
nonzero `omitted_count` had more eligible candidates than its report cap — disclosed in the
summary/coverage note with a bounded re-run scoped to that lane's exact doc paths as the
deepening move (repeatable `--from`, ≤ 8 docs, so the selection partitions to one lane and is
analyzed directly, uncapped — a whole-category re-run would just re-partition a large category
into multiple lanes and hit the same per-lane cap; `HARVEST_MAX_OPPORTUNITIES` stays 5:
starvation is made visible rather than widened away; widening stays a one-constant edit). The parent re-reads every cited pointer before a
candidate enters the roadmap — wave-reported (whatever its `pointer_status` stamp) and
directly-mined alike; an unresolved/contradicted pointer never enters the roadmap (its reason
lands in the objective backlog when an objective is authored, else the zero-opportunity
evidence report).

## §8.49 · Published-suffix synchronization (the sync operation + `perk objective stack sync`)

**The operation** is `perk.delivery.sync.synchronize_train` (a gateway-touching delivery leaf
mirroring §8.47's publish shape: every effectful callable keyword-injectable, production
defaults, tests pass fakes): change a published stacked layer — or re-anchor the whole train
onto an advanced objective base (`--base`) — and move every published successor with it, as
one transaction. `RemoteWriterProbe` is a **required** parameter (no fail-open default); the
delivery plane declares the Protocol (`active_plan_ids(plan_ids) → frozenset`, raising
`WriterObservationError` on ANY observation failure), the CLI wires the production adapter.

**The operation universe is the checkpoint-claimed prefix — never `published_prefix_len`.**
The train classifier truncates its verified prefix on exactly the discrepancies sync exists
to diagnose (publication drift, membership divergence), which would make the drift refusals
unreachable — a drifted bottom layer would read as a false no-op; a drifted upper layer would
silently shrink a lower-layer cascade. `published_prefix_len` stays a status fact only. The
public `derive_claimed_prefix(train)` helper is the single derivation consumed by sync and
publish routing. The claimed prefix: the maximal contiguous run, from the bottom of delivery order, of layers
carrying plan identity, a branch, a PR number, and the FULL checkpoint pair. Malformed claims
(a half pair, a checkpointed layer missing identity, a claimed layer above an unclaimed one)
are the typed refusal `claimed_prefix_malformed`.

**The operation lock.** Every mutating stack operation on a repo — sync (all modes),
continue, abort, recover (§8.51), and land (§8.56) — runs under ONE machine-local
non-blocking `flock` at
the main checkout (`.perk/workflow/stack-operation.lock`,
`perk/delivery/oplock.py::stack_operation_lock`); a busy lock is the typed refusal
`operation_in_progress` (never a wait — concurrent invocations are an operator error to
surface, not serialize). Machine-local by design: cross-machine concurrency is already
governed by the force-with-lease pushes and the journal; platforms without `fcntl` degrade
to a no-op (the leases remain the real guard).

**The protocol, in order.** One **centralized cleanup guard** wraps the candidate/mutation
steps: on EVERY exit — success, refusal, decline, error, post-prepare failure — it
best-effort deletes this operation's temp refs and removes its isolated worktree, then runs
one `git worktree prune` (the remove-then-prune ordering keeps git's bookkeeping consistent
with the directory sweep). Cleanup NEVER fails the operation, but it is never silent either:
every individual failure (the ref listing, each ref, the worktree, the prune) becomes a
human-facing note, and the RESULT-returning arms — fresh/continued success, declined,
dry-run — thread those notes onto `SyncResult.notes` (error/refusal exits clean
best-effort-silently; leftover residue is §8.51 sweep territory either way). The guard is
disarmed in exactly one case, the durably written continuation manifest (the conflict arm).
Post-push arms never need the temp refs (an applied push holds the candidates remotely; an
unapplied push's resume arm abandons and recomputes fresh). Orphaned (process-killed,
manifest-less) `sync-*` residue is inert until `recover`'s orphan sweep (§8.51) collects it.

1. **Reconstruct fresh** (`reconstruct_repo_train`); no train / no lineage → `not_stacked`.
2. **Continuation gate**: any manifest for this lineage → `sync_conflict_pending` (the
   message names the manifest path and the retained worktree; clearing is manual until the
   continue/abort surface). An unparseable manifest is treated as PRESENT — fail closed,
   never a fresh cascade over retained residue.
3. **Journal route** — a separate fresh journal read (the §8.43 fold is the single routing
   authority; the projection's `unresolved_operations` summary is status color only). An
   unresolved SYNC **or ADOPT** on this lineage → the resume path — routing is
   **flag-independent** (a plain sync resumes an unresolved ADOPT and vice versa: the record,
   not the invocation, names what must conclude); any other unresolved kind →
   `unresolved_operation`.
4. **Derive the claimed prefix** (above). Before ANY route (fresh or resume), structural
   identity/topology blockers on the reconstruction refuse as `claimed_prefix_malformed` — a
   structurally mis-linked plan must never be checkpointed; the OPERATIONAL blocker axes
   (checkpoint/PR/stack drift) deliberately pass through to sync's own fresh preflight below.
   The complete public `STRUCTURAL_BLOCKER_CODES` set lives in `delivery.train` and includes
   `missing_lineage`; that member is unreachable here because step 1 already classifies a
   lineage-less train as `not_stacked`, but the shared set is context-free for §8.52 consumers.
5. **Preflight every claimed layer** (all refusals before any candidate work): remote head ==
   the `published_head_sha` checkpoint → else `remote_drift` (adoption is a later node); a
   fresh strict PR-facts read per layer — OPEN, base == the expected predecessor branch (the
   objective base for the bottom layer), head == the checkpoint → else `pr_drift`; native
   membership exactly the claimed PRs (`not_applicable` below two) → else `membership_drift`;
   a DIRTY claimed worktree → `dirty_worktree` (a **clean** checked-out worktree does not
   block — the normal state of the just-amended layer; sync never touches local worktrees);
   an active remote writer on a claimed plan → `active_writer`; a probe failure →
   `writer_observation_unavailable` (an unreadable observation is never "no active writer").
6. **Detect the affected set.** Locally changed ⟺ the local branch head exists, differs from
   the checkpoint, AND is not an ancestor of it (a stale local branch is information, never a
   revert source). The affected set runs from the trigger through the top of the claimed prefix.
   Explicit sync (`trigger_plan_id=None`) stays unchanged: `--base` selects the bottom layer,
   otherwise the lowest locally-changed layer. Under §8.52's trigger, the normalized id must name
   a claimed layer (`claimed_prefix_malformed` otherwise), only that layer's local head is read and
   tested for change, and every successor source is its verified published head unconditionally;
   an unrelated locally-ahead successor is never published by another plan's submit. Trigger with
   `--base` or `--adopt` is `invalid_input`; `dry_run` composes. `--base` with no positively
   observed base head → `base_unobserved`. No trigger/change → the typed **no-op success** (carries
   the `base_advanced` notice so the CLI prints the `--base` hint). Every candidate SOURCE must
   contain its stored parent edge (the edge becomes the
   rebase `upstream`, so an unchecked corrupt checkpoint would replay the wrong range): a
   locally-changed head that lacks it → `stale_parent` (the actionable rebase-first arm); an
   UNCHANGED claimed layer whose published head lacks it → `claimed_prefix_malformed`
   (an internally inconsistent stored pair — broken stored state).
7. **Capability**: >1 configured push URL → `multiple_push_urls` (`--atomic` is atomic within
   ONE receiving repository — no pretended distributed atomicity); then the shared
   per-push-URL no-op probe (`capability.probe_atomic_push_urls`, the §8.45 probe factored
   out) pinned to the bottom affected layer's branch at its verified remote head → failure is
   `atomic_push_unsupported`. This discharges §8.47's recorded deviation.
8. **Candidate calculation** in ONE isolated worktree (`<worktree_root>/sync-<operation_id>`;
   temp refs `refs/perk/sync/<operation_id>/<branch>`; the freshly minted operation ULID
   names all residue). Bottom-up over the affected set: source = the local head when locally
   changed, else the verified published head; new parent edge = the observed base head
   (bottom, cascading) / the unchanged stored edge (bottom otherwise) / the predecessor's
   fresh candidate; under a trigger only the trigger may use a local source and every successor
   uses its verified published head; edges equal → candidate = source (fast path, no rebase); else a detached
   `rebase --onto`. A **conflict** writes the continuation manifest, disarms the guard, and
   raises `rebase_conflict` (the message names the node, the manifest path, and that no
   remote ref and no journal record was created; the conflicted worktree state is retained).
   A manifest WRITE failure keeps the guard armed — residue is cleaned, nothing is retained
   — and still classifies as `rebase_conflict` inside the typed boundary (the message says
   retention failed and why).
9. **Approval gate**: the ordered `SyncCascade` (per-ref before→after, node ids, PR numbers,
   base facts) → the `approve` callback (`None` = auto-approve). Declined → the guard
   cleans; the declined result returns — no journal record, nothing mutated.
10. **Post-approval re-observation** (closing the arbitrary-pause race before the journal
    write): re-read every lease input — affected remote heads, PR facts, membership, and the
    base head when cascading. ANY difference from the captured before-set → `remote_drift`
    with no prepared record written (the remedy is "rerun sync").
11. **Prepared record** (journal-first via the §8.43 read-back discipline;
    `OperationKind.SYNC`, `affected_plans` bottom→top). The sync-kind payload shapes (the
    journal envelope stays opaque-validated):
    `before: {base: {branch, sha}|null, branches: [{ref, sha}], prs: [{number, head_sha,
    base}], stack: {members: [bottom→top]}|null}` — the exact observed lease values (base
    present iff cascading; stack null below two claimed PRs);
    `after: {branches: [{ref, sha}], prs: [{number, head_sha, base}], base_parent:
    sha|null}` — the candidates; PR bases unchanged by construction (sync moves heads,
    never branch names).
12. **One atomic push** (`git.push_atomic_with_leases`): every affected ref in ONE
    `push --atomic --porcelain --no-verify --no-signed --no-follow-tags
    --recurse-submodules=no` to `origin` with `-c push.pushOption=` cleared, each ref under
    `--force-with-lease=refs/heads/<branch>:<exact before sha>` (never an absence lease —
    sync never pushes creations). A rejection → refetch and classify: all-at-before →
    append `abandoned` (observed = the all-before proof) + `push_rejected` (retry = rerun
    sync); an unreadable refetch → `postcondition_unverified` (unresolved); mixed →
    `sync_drift` (unresolved, fail closed). Individual refs are NEVER retried.
13. **Verify postconditions**: refetch every affected branch — head == candidate (else
    `sync_drift`); PR facts through the bounded settle poll (up to five observations through
    the injectable observe/sleep seam — GitHub's PR-head propagation lags a push) before a
    mismatch classifies as `pr_drift`; an unreadable read → `postcondition_unverified`;
    membership must still be exact (else `membership_drift`). Failed arms leave the
    operation unresolved (recoverable).
14. **Persist, then complete** (publish's step-12 ordering): per affected layer bottom→top,
    `write_checkpoints(plan_id, parent_checkpoint_sha=<its new parent edge>,
    published_head_sha=<its candidate>)`; then the `completed` outcome (observed = the
    verified branches + PR heads). A crash between the checkpoint writes and completion
    reconstructs as roll-forward — merge-writes + idempotent byte-identical appends.

**`--dry-run` (the side-effect-free preview).** Runs the full protocol up to the approval
boundary — preflight, capability, candidate calculation in the isolated worktree — then stops
and returns the would-be cascade as the `dry_run: true` result arm: **no journal record, no
push, no checkpoint write, no confirmation** (the preview needs no consent — nothing mutates).
The conflict arm is retention-free: a dry-run rebase conflict writes NO manifest (the guard
stays armed, residue is cleaned) and classifies as `rebase_conflict` with a message naming the
dry run. A pending unresolved operation still routes per step 3 — but the unresolved-kind
message is **kind-aware** (it names the blocking kind and its owning remedy) and a dry run
never resumes/abandons anything. Composes with `--base` and `--adopt`; the no-op arm reports
`dry_run: true, no_op: true`.

**`--adopt NODE` (adoption).** One claimed layer's **manually-pushed remote head** becomes the
intended source: the adopted layer's preflight accepts remote-head ≠ checkpoint (its lease
becomes the OBSERVED remote head; every other layer still requires checkpoint equality —
other-layer drift refuses as usual), the adopted layer's candidate source is that remote head,
and the layers above it cascade onto it. `--adopt` × `--base` is refused (`invalid_input`:
adoption re-anchors ONE layer; the base cascade re-anchors the bottom — composing them has no
coherent single trigger), and a node outside the claimed prefix is `invalid_input` too. The
typed refusal `adopt_blocked` names its reason: no remote head (nothing to adopt); the head
exactly at its checkpoint (nothing to adopt); the head does not CONTAIN the stored parent
edge (the out-of-band edit rewrote the layer's ancestry — repair before adopting); or the
layer is ALSO locally changed (an ambiguous source). Adopting the TOP claimed layer
with no successors is **checkpoint-only**: nothing needs pushing, but the operation still
journals (prepared → checkpoints → completed) — the record is what makes the adoption
durable. The journal kind is **ADOPT** (`OperationKind.ADOPT`): the payload is SYNC's shape
plus `after.adopted = {node_id, plan_id, remote_head}` (all strings, required — the resume
decoder is strict). **The push set excludes no-op refs** (before == after — the adopted
branch itself when nothing above it moved): pushing a ref at its own lease would be a no-op
with a stale-lease race window; excluding it has exactly the same race parity as the unleased
base head — the post-approval re-observation (step 10) is the close.

**The resume path** (an unresolved SYNC **or ADOPT** on this lineage). Re-derive the expected
states from
the prepared record; the payload decode is STRICT (sync payloads are opaque at the journal
envelope, so the decoder is the validation boundary): the parallel plans/branches/prs arrays
must be structurally complete; `before.base` and `after.base_parent` must be mutually
consistent (both absent, or a `{branch, sha}` capture with `base_parent == sha` — an
unvalidated `base_parent` would be persisted verbatim as a parent checkpoint); the recorded
stack must be `null` or exactly `{"members": [int, …]}`, may be `null` only for a
single-layer cascade, and must END with exactly the affected PR run bottom→top; an ADOPT
record must additionally carry the full `after.adopted` mapping (strict — a missing/partial
adopted block is `sync_drift`), and its adopted branch's lease is the recorded BEFORE sha,
never the checkpoint. The fresh
reconstruction must still agree with the record (lineage; the recorded
refs/plans exist and remain CONTIGUOUS in delivery order; recorded PR numbers AND bases match
— each base re-derived from the fresh train's topology (the predecessor layer's branch; the
objective base at the bottom); full stored checkpoint pairs) — any disagreement
is `sync_drift`, fail closed. Then observe every recorded ref: **all at `after`** → roll
forward under the same operation (steps 13–14, the parent edges re-derived from the record:
`base_parent` / the stored unchanged edge / the predecessor's recorded candidate); **all at
`before`** → append `abandoned` (observed = the all-before proof) and prepare a **fresh**
operation in the same invocation (the full protocol from step 4). This is a **deliberate
deviation** from publish's same-operation retry arm: sync's candidates live in disposable
temp refs that do not survive a crash, and a recomputed rebase yields different SHAs.
**Mixed/unrelated** → `sync_drift`, unresolved (`recover` owns explicit repair, §8.51).
For explicit sync these arms retain their existing result shapes. Under `trigger_plan_id`, an
**all-after** resume first rolls the old operation forward, then reconstructs and runs the full
fresh trigger protocol in the same invocation; it returns the fresh result (`resumed: false`, a
fresh operation id or the no-op arm) plus `notes: ["concluded unresolved operation <id>
(roll-forward) before cascading"]`. This prevents a completed old operation from masquerading as
publication of a newer trigger head. The all-before abandon already continues into fresh and keeps
the trigger; mixed remains fail-closed.
The validate/observe/classify/roll-forward/abandon steps are a **shared record-recovery
core** in `sync.py` (`SyncRecordFacts`, `validate_sync_record`, `observe_sync_record`,
`classify_sync_observation`, `roll_forward_sync_record`, `abandon_sync_record`, consumed
through the `SyncRecordSeams` Protocol) — `_resume` and `recover.py` run the SAME code, so
the two paths cannot drift. Classification is fail-closed: only the exact all-`after` /
all-`before` observation sets classify; anything else — including any single unreadable
observation or corroboration failure — is `mixed`.

**The continuation manifest** (`perk/delivery/continuation.py`). Written ONLY at the conflict
stop; lineage-keyed at the MAIN checkout
(`.perk/workflow/sync-continuations/<delivery_lineage>.json`, `main_worktree_root` fallback
`repo_root` — sync residue is repo-common, visible from every worktree; a conflict on lineage
B can never overwrite lineage A's manifest). The lineage is stored objective metadata (an
arbitrary string at the trust boundary) AND a filename, so it is validated as a **path-safe
token** (`[0-9A-Za-z][0-9A-Za-z_-]{0,63}` — no dots, no separators) before any path is
derived: the manifest module raises `ValueError` on a violation and sync refuses it earlier
as typed `invalid_input` — a hostile value can never escape the continuation directory. The
stored JSON is a schema-versioned boundary (`schema_version: "1"`, pinned for the
continue/abort reader) parsed through a lenient model into the frozen domain dataclasses the
delivery plane passes around (the parse→dataclass split; serialization is an explicit render,
never a domain dump): `operation_id`,
`objective_id`, `delivery_lineage`, `run_id`, `include_base`, `captured_base_head|null`,
ordered `layers: [{node_id, plan_id, branch, before_sha (the lease), old_parent_edge,
source_sha, new_parent_edge|null, candidate_temp_ref, candidate_sha|null}]`,
`conflict_node_id`, `worktree_path`, `created`, and the **additive v1 optional**
`adopted_node|null` (an ADOPT conflict records which layer was being adopted; the additive
policy: schema_version stays "1" for optional fields old readers ignore and old writers omit
— absent parses as `null`). Machine-local and **disposable**: a resumed
calculation must revalidate every captured remote/checkpoint input before proceeding. The
module also owns `clear_manifest` (missing-ok delete), `iter_manifests` (the recover/status
scan — unparseable files are reported, never skipped silently), and `validated_targets`
(below). The
delivery plane owns the module to avoid the import cycle (`state/cache.py` imports
`perk.delivery.layer` at module scope): `continuation.py` reaches the atomic-write seam
through `perk.substrate.fs.atomic_write_text` (relocated from `state/cache.py`, which
re-exports it) and never imports `perk.state`.

**Containment validation (the deletion-authority rule).** Manifest data is NEVER deletion
authority by itself: before continue or abort touches the filesystem or refs,
`continuation.validated_targets(manifest, worktree_root)` re-derives the deletable residue
from the manifest's own operation id and refuses (`ContainmentViolation` → typed
`continuation_invalid`) unless the id is a canonical 26-char Crockford ULID, the recorded
worktree path is EXACTLY `<worktree_root>/sync-<operation_id>` (the worktree ROOT is
resolved — a planted symlink cannot redirect the deletion), and every candidate temp ref is
EXACTLY `refs/perk/sync/<operation_id>/<branch>` for a recorded branch. A hostile or
corrupted manifest can therefore name nothing outside the operation's own residue.

**`--continue` (resume the human-resolved conflict).** perk never drives conflict
resolution: the human finishes the rebase in the retained worktree (`git rebase --continue`)
first; `--continue` then (1) loads the manifest (`no_continuation` when none;
unparseable → the typed direction to `--abort`), validates containment (above), and checks
the manifest belongs to this objective/lineage (`continuation_invalid`); (2) revalidates the
retained world — worktree present (missing → `continuation_stale`), no rebase still in
progress (`rebase_in_progress`), worktree clean (`continuation_stale`), every captured lease
(before_sha vs the fresh remote head, checkpoints, the captured base head) still true — any
mismatch is `continuation_stale` (a moved remote head classifies as stale, not
`remote_drift`: the capture, not the fresh preflight, is what it disagrees with); each stale
arm's message ends with the discard direction (`--abort` and rerun); every captured old
parent edge must equal the fresh stored `parent_checkpoint_sha` (a tampered/stale capture
must never become a rebase upstream). The pending layer's resolved worktree HEAD must
additionally CONTAIN the recorded new parent edge — a clean worktree alone proves nothing
(`git rebase --abort` leaves a clean worktree at the ORIGINAL source; adopting that head
would checkpoint a candidate that does not contain its parent) — else `continuation_stale`.
(3) The **resume
point** is the FIRST manifest layer with `candidate_sha: null`; the manifest's claimed
prefix must match the fresh claimed prefix and the already-candidated suffix must verify
against the retained temp refs (else stale). All layers non-null = a declined-after-complete
continuation — re-enter at the approval gate directly. (4) Candidate calculation resumes in
the RETAINED worktree; after EVERY completed candidate the manifest is atomically rewritten
(progress is durable — a second conflict on a higher layer retains under the SAME operation
id and classifies `rebase_conflict`). A progress-rewrite WRITE failure stays inside the
typed boundary (`GitError` → the CLI's `git_error`; on the new-conflict arm it rides the
typed `rebase_conflict`): the PREVIOUS durable snapshot stays retained and valid, and the
next `--continue` recomputes from it. (5) The approval gate re-renders the full cascade;
declined → everything stays retained (`declined: true, continued: true` — re-enterable).
(6) Post-approval re-observation, then the prepared record under the MANIFEST's identity
(its operation id + run id — the continuation concludes the operation the conflict
interrupted, never a new one). **The manifest retirement boundary**: everything up to and
including the approval gate is pre-journal — refusals and declines retain manifest +
worktree + temp refs; once the prepared record is appended the journal is sole authority —
the manifest is deleted, and a deletion failure is a loud result note, never a refusal.
After the prepared append the ordinary tail runs (push → verify → persist → complete) with
the cleanup guard armed: post-prepare failures leave the operation unresolved for the resume
path/`recover` (with NO manifest — a second `--continue` is `no_continuation`).
`--continue` takes no cascade flags (`--base`/`--dry-run`/`--adopt` refuse as
`invalid_input`). Both control modes (`--continue` AND `--abort`) ignore `--run-id`:
continue journals under the manifest's captured identity; abort never journals.

**`--abort` (discard the retained continuation).** Confirmation-gated: the `AbortPreview`
(manifest path, parseability, containment, operation id, conflict node, worktree path) goes
through the `approve` callback (`None` = auto-approve); declined → `aborted: false,
declined: true`, nothing deleted. Approved: a **contained** manifest (containment validation
AND objective/lineage match) best-effort deletes every temp ref, the retained worktree, and
one prune, then the manifest; each individual cleanup failure is a loud result note with the
`recover` remediation (the abort still succeeds and the manifest retires — leftovers become
orphan sweep territory). The focused abort bundle carries ONLY reconstruction, continuation,
and cleanup dependencies — it cannot accidentally reach publish/authority/candidate seams.
An uncontained or unparseable manifest deletes the MANIFEST FILE ONLY (the residue it names
is untrusted — left for `recover`'s pattern-based sweep). A manifest-delete failure is a
`git_error` refusal: the manifest remains authoritative, and the error includes the cleanup
report before directing a rerun. No journal record is written on ANY abort arm: the conflict stop
never crossed a remote boundary, so there is nothing to conclude — the interrupted
operation simply never happened. Like `--continue`, no cascade flags compose.

**The result arms** (`SyncResult`; invariant: `operation_id` non-null ⟺ a prepared record was
journaled by, or resumed by, this invocation). Identity fields (`objective_id`,
`objective_url`, `redirected_from`) ride the result so the CLI never re-reconstructs;
`base_advanced` is the §8.44 status notice, independent of `base_cascaded`.

| arm | operation_id | abandoned_operation_id | no_op | declined | resumed | base_cascaded | affected |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fresh success | new ULID | null | false | false | false | == include_base | synced layers |
| no-op | null | null | true | false | false | false | () |
| declined | null (minted ULID never journaled) | null | false | true | false | false | () |
| resume, all-after | the resumed op id | null | false | false | true | record's before carried base | layers from the record |
| resume all-before → fresh success | the fresh ULID | the abandoned op id | false | false | false | == include_base | synced layers |
| trigger resume all-after → fresh | fresh ULID or null on fresh no-op | null | fresh arm | fresh arm | false | false | fresh affected set |

The all-before abandon re-runs the FULL fresh protocol, so its no-op and declined arms are
reachable too: those results keep their arm's shape (`operation_id: null`) while carrying the
`abandoned_operation_id` — the invariant holds because the abandon journaled an OUTCOME under
the old id, never a prepared record. The control surface adds four additive fields —
`dry_run` (the preview arm: `operation_id: null`, `affected` = the would-be cascade),
`adopted_node|null` (rides every adopt-invocation arm, including its dry run),
`continued` (a `--continue` invocation: true on both the completed and the
declined-retained arm), `aborted` (`--abort` approved+deleted; a declined abort is
`aborted: false, declined: true`) — and `notes: [str]` on the operation result (loud
non-refusal notes, e.g. failed cleanup or manifest retirement). The JSON envelope includes
`notes` verbatim; both the cold human renderer and the warm TypeScript tools render every
one, so machine-routed success can never hide leftover residue.

**The error vocabulary is bounded.** `SyncError.error_type` ∈ {`not_stacked`,
`unresolved_operation`, `sync_conflict_pending`, `claimed_prefix_malformed`, `active_writer`,
`dirty_worktree`, `writer_observation_unavailable`, `remote_drift`, `pr_drift`,
`membership_drift`, `stale_parent`, `base_unobserved`, `multiple_push_urls`,
`atomic_push_unsupported`, `rebase_conflict`, `push_rejected`, `sync_drift`,
`postcondition_unverified`, `invalid_input`, `adopt_blocked`, `no_continuation`,
`continuation_stale`, `continuation_invalid`, `rebase_in_progress`,
`operation_in_progress`}. The operation deliberately PROPAGATES raw
infra errors (`GitError`/`GitHubError`); the CLI boundary maps those to `git_error`/
`github_error`, passes `TrainReconstructionError.error_type` through verbatim, and adds its
own boundary codes (`confirmation_required`, `journal_corruption`, `no_objective`,
`not_a_repo`) — the full envelope vocabulary is the union of those layers.

**The cold worker.** `perk objective stack sync [OBJECTIVE] [--base] [--dry-run]
[--adopt NODE] [--continue] [--abort] [--run-id RUN_ID] [--yes] [--json]`
(`commands/objective/stack/sync_cmd.py`). The control-flag matrix is validated FIRST as
typed `invalid_input`: `--continue`/`--abort` are mutually exclusive with each other and
with every cascade flag; `--adopt` × `--base` is refused; `--adopt`/`--base` × `--dry-run`
compose. Objective resolution mirrors
`status`'s exactly; `run_id` resolves `--run-id` → the **ACTIVE** objective header's
`run_id` (the fallback follows `superseded_by` forward, the same walk the reconstruction
performs — syncing through a superseded objective never journals the predecessor's run
identity), both absent → `invalid_input`. The production `GhaRemoteWriterProbe` lives in
`perk.run.writer_probe` and queries the gateway run listing with a **server-side status filter**
(queued + in-progress, one call each — active runs can
never be displaced off a newest-first page by completed runs; the existing 100-cap bounds
*simultaneously active* runs) and matches plan ids via the managed run-name convention; any
listing failure propagates as the probe's typed error → `writer_observation_unavailable`.
Explicit sync passes no exclusion. Automatic submit excludes a writer only as the pair
`(exclude_run_id, exclude_plan_id)`, after `PERK_RUN_ID`, a consumed implement/address handoff,
and the active plan-ref corroborate the caller-supplied id as this process's run on this plan.
Neither field excludes alone; uncorroborated ids exclude nothing. Only that exact run+plan pair is
skipped because its already-committed work is the trigger; every other active writer still blocks.
Confirmation: the `approve` callback renders the cascade to **stderr** and confirms via
`click.confirm(..., err=True)` — interactive `--json` never contaminates stdout; `--yes`
auto-approves; non-interactive without `--yes` → the typed `confirmation_required` refusal
(never a hang, never a silent push); declined → a success envelope with `declined: true`.
`--abort` gets its own confirmation render (the preview: operation id, conflict node,
retained worktree, and — on the uncontained/unparseable arms — that ONLY the manifest file
will be deleted) under the same `--yes`/non-interactive discipline; `--dry-run` needs no
confirmation (it stops before the approval boundary); `--continue` routes to
`continue_train_sync` and journals under the manifest's captured run identity (`--run-id`
is ignored). The `--json` envelope `ObjectiveStackSyncOut` (snapshotted at
`shared/schemas/outputs/objective-stack-sync.schema.json`), declaration order pinned:
`{success, objective{id,url,redirected_from}, operation_id|null,
abandoned_operation_id|null, no_op, declined, resumed, base_cascaded, base_advanced,
affected: [{node_id, plan_id, branch, pr_number, before_sha, after_sha}], dry_run,
adopted_node|null, continued, aborted}` (the last four are the additive control-surface
growth); failures use the
`{success, error_type, message}` fail shape with `SyncError.error_type` verbatim; the
reconstruction seam's `TrainReconstructionError.error_type` vocabulary passes through the
same way (the stack-status convention), and a corrupt journal read fails as
`journal_corruption`. Exit
discipline: 0 = success (incl. no-op, declined, dry-run, continued, aborted), 1 = typed
operation failures, 2 = not-a-repo. The explicit command remains the owner of base advancement,
adoption, conflict continuation, abort, and preview; ordinary submit/address propagation delegates
to the same operation through §8.52.

**Status.** Sync never changes PR bases or native stack membership — branch names are stable,
only heads move, membership is verified unchanged. Local branch refs of affected layers are
deliberately left stale after a successful sync (repositioning worktrees is existing
territory elsewhere). The warm surface over this worker is §8.51's.

## §8.50 · Session-audit judgment wave (judge → wave → fold)

The judgment tier's execution path: a seeded read-only orchestrator session (the dedicated
`audit` registry stage) launched by the dev-only cold door **`perk-dev audit judge`**, whose one
`run_audit_wave` call fans out one `perk-dev.session-auditor` lane per bounded evidence packet
and writes the engine-validated verdicts to `<bundle>/verdicts.json`; **`perk-dev audit fold`**
merges them into the deterministic report as **leads, not proofs**. Every degradation arm lands
honestly as `unchecked` — never a silent pass.

**The `audit` stage.** A deliberately **isolated** registry node (`predecessors`/`successors`
empty — its own initial AND terminal; GC's terminal-stage rule prunes its run scratch): an audit
session must classify honestly in future corpus sweeps, never as `plan`. `mode: read-only`,
`worktree: none` (runs in the **invoking** checkout — `resolve_worktree` returns the invoking
repo root unchanged, and `.pi/settings.json` loads the extension from `..`, so a judge invoked
from a plan worktree dogfoods that branch's door + extension; the default bundle path and the
corpus census anchor to the main root regardless; the one write is gitignored scratch), doors
cold-local-only, `run_id` mint. `command: audit judge` is a label — the dedicated door lives in
**perk-dev**, so `audit` joins `DEDICATED_STAGES` (no generic `perk audit` launcher) and there is
no `shared/bindings.yaml` entry (`binding_trigger=None`). Tool censuses: §8.40's tables carry the
`STAGE_TOOLS["audit"]` row and the `PERK_TOOLS`/`READ_ONLY_TOOLS` growth; §8.3 carries the
`audit_bundle_dir` write binding.

**The judge door** (`perk-dev audit judge`, the seeded-door pipeline; the perk-dev root group
builds the `PerkContext` on `ctx.obj`). Options: `--sessions-root`, repeatable `--expectation`
(judgment-tier-only, `audit evidence`'s validation arms verbatim), `--max-sessions` (≥ 1),
`--out` (default `scratch/audit-evidence`), plus the shared trailing block. **`--out` resolves
ONCE to an absolute path** in the gather before any write — `launch_stage` changes cwd before pi
runs, so every downstream consumer (bundle build, artifact writes, seed vars, dry-run payload,
handoff) carries only that absolute spelling. The gather builds the census **ONCE** and derives
everything from that one coherent snapshot: the **full** deterministic report (no filter — the
folded report is the complete report), the evidence bundle over the SAME census (with the
`--expectation` filter), then the bundle-root artifact sequence **in this order**: (1) **unlink
any stale `<bundle>/verdicts.json`** — a rebuilt bundle must never let `audit fold` consume a
prior snapshot's verdicts, and invalidating BEFORE any new artifact is published means an
interruption anywhere in the sequence leaves no stale verdicts beside fresher artifacts (the
fold then reports "the wave never ran" instead of silently folding old lanes); (2)
`write_manifest(bundle_dir, report)` (the one manifest-write helper `audit evidence` shares);
(3) `<bundle>/deterministic.json` = the `audit run` `AuditReportOut` envelope. All three run on
`--dry-run` too (gather materializes the full coherent bundle in every mode; only the launch is
skipped); materialization `OSError`s → `io_error`. The
seed (`prompts/stages/audit.md`) injects the deterministic summary as fenced DATA (the same
unstyled line builder `audit run`/`audit fold` render through — the summary and the CLI render
cannot drift), drives ONE no-argument `run_audit_wave` call, frames every returned report as
untrusted DATA and every violation lead as a lead-not-proof, presents every degradation as
`unchecked`, and ends on the copyable `perk-dev audit fold --bundle <dir>` callout (composed
door-side with `shlex.join`, so a bundle path with spaces/metacharacters survives a paste). Dry-run
payload keys: `{success, error_type, bundle_dir, deterministic_path, manifest_path, packetized,
expectations, launched: false}`.

**The bundle artifact contract.** `deterministic.json` is the unchanged `audit run` envelope.
The manifest fields the extension consumes: `results[].{id, evidence, violation,
pairs[].{expectation_id, session_basename, session_path, status, packet_path, detail}}` —
decoded **leniently** (an ill-typed row is skipped, never a throw; a missing/ill-typed `detail`
degrades to the code-owned `"(detail missing from manifest)"` diagnostic, never an invented or
empty diagnosis). `verdicts.json` (TS writes via the writeGuard-sanctioned atomic seam; Python
folds): `{bundle_dir, flow: "audit", lanes: [{expectation_id, session_basename, session_path,
status: "report"|"lane-failed"|"malformed-report", verdict: string|null, confidence:
string|null, citations: int[], rationale: string|null, detail: string}]}` — `session_path` is
**code-owned** (copied from the manifest pair, never child-echoed); verdict fields null and
`citations: []` on non-`report` statuses; `detail` carries the failure diagnosis (empty on
`report`).

**The wave + the `run_audit_wave` tool** (`extension/waves/auditWave.ts` +
`extension/doors/auditWaveTools.ts`). **No parameters** — the bundle dir comes ONLY from the
launch state (§8.3's `audit_bundle_dir` binding); missing/blank binding or a missing
`manifest.json`/`deterministic.json` → pre-launch `bad_state` (nothing written). One lane per
**packetized** pair, keyed `<sanitized expectation id>.<ordinal>` (run-key-safe under
pi-subagents' `runs.all` key contract, which the wave renderer also enforces up front; the
path-qualified pair identity `<expectation_id>@<session_path>` rides the lane label — basenames
are not globally unique — and the fold joins reports back to pairs through the code-owned lane
plan, never by parsing keys). Packetized pairs sharing `(expectation_id, session_basename)` share
a stem-keyed packet file, so their evidence is ambiguous — such pairs dispatch as NO lanes and
are recorded `lane-failed` ("duplicate session basename in bundle — ambiguous packet identity")
while unaffected lanes still dispatch. The per-lane `outputSchema` is the tri-state verdict
shape (`verdict: satisfied|violated|unclear`, `confidence: high|medium|low`, integer
`citations`, `rationale`, echoed identity) — closed, all required, NO conditionals (the salvage
rule; violated⇒citations is enforced at fold time). `best-effort` completeness, ONE attempt,
**no retry**; the `[models.subagents] session-auditor` key rides as the workflow-level model
default. **Zero-lane short-circuit**: no dispatched lanes ⇒ the wave is never launched (a
synthetic complete result) and the tool still writes `verdicts.json` — its `lanes` carry only
the pre-dispatch degrades (`lane-failed`: a basename collision / a missing `packet_path`), so
`lanes: []` only when no packetized pair degraded. **verdicts.json is
written in every arm in which the wave was launched (and the zero-lane arm)**: engine-validated
reports are re-sanitized before the write (an out-of-vocabulary shape degrades to
`malformed-report`; an echoed `expectation_id`/`session_basename` mismatch degrades to
`lane-failed` with the mismatch recorded — the Python fold's `validate()` rejects unknown
vocabulary wholesale, so an unsanitized write would poison the bundle); a wave-level failure
writes ALL planned lanes `lane-failed` with the wave-level detail. A throwing verdicts write →
`error_type: "io_error"` with the in-memory lane records attached to the fail payload (the
orchestrator can still present the leads). The tool result (untrusted DATA): `{complete, lanes,
skipped_pairs (the manifest's non-packetized pairs, detail always populated), verdicts_path,
bundle_dir}`.

**The fold** (`perk-dev audit fold --bundle <dir> [--json]`; `packages/perk-dev/…/audit/fold.py`).
Reads the three bundle artifacts through lenient boundary models + an explicit domain
`validate()` pass; every invariant violation routes uniformly to `bad_bundle` (exit 1) naming
the artifact + its producing command: `success: true` headers on deterministic.json/
manifest.json; verdicts.json `flow == "audit"` and `bundle_dir` equal to the folded bundle's
absolute path (a copied/foreign verdicts file never folds); statuses/verdicts/confidences drawn
from the known vocabularies; unique `(expectation_id, session_path)` identities within each
artifact. `UNCHECKED_REASONS` (the `runner.py` SSOT) grows, in order: `lane-failed`,
`auditor-unclear`, `unboundable`, `not-sampled`. `fold_report` is pure and keyed by
**`(expectation_id, session_path)`**; per judgment expectation **only cells with `status ==
"unchecked"` and `reason == "judgment-tier"` are replaceable** — vintage-gated `not-applicable`
cells (the runner's vintage-before-tier precedence) are preserved untouched. The mapping:
`packetized`+`report`+`satisfied` → **satisfied** (`entries=citations`, detail `judgment lead
(confidence <c>): <rationale>`); `packetized`+`report`+`violated` with ≥1 citation →
**violated** (detail `judgment lead, not proof (confidence <c>): <rationale>` — the
violated⇒citations invariant holds); `unclear` OR a cite-less `violated` → **unchecked**
`auditor-unclear` (a cite-less violation claim is named as such); lane
`lane-failed`/`malformed-report` or no lane for the pair → **unchecked** `lane-failed`; pair
`unboundable`/`not-sampled`/`unparsed`/`malformed` → **unchecked** with that reason; no manifest
entry (filtered at judge time) or no pair for the cell → the cell stays `judgment-tier`; a lane
matching no replaceable cell is ignored + surfaced on the warnings channel (`user_output`).
Deterministic-tier results and `not_exercised` pass through untouched; vintage fields are kept;
`status_counts`/`totals` are recomputed zero-filled over `VERDICTS`. The render is the same
shared line builder as `audit run` plus the judgment-fold section (per-lane leads with the
"lead, not proof" framing, the unchecked breakdown by reason, warnings, the bundle header);
`--json` is the **unchanged `AuditReportOut` envelope**. Prints only; writes nothing. Missing/
unparseable/invariant-violating artifacts → `bad_bundle` naming the producer (`judge` / "the
wave never ran — the seeded session writes verdicts.json via run_audit_wave"); `not_a_repo`
exits 2.

## §8.51 · Stack recovery (`perk objective stack recover`) + the warm stack surface

**The operation** is `perk.delivery.recover.recover_operations` — **conclude-only** recovery:
classify every unresolved stack operation against fresh authority, conclude the one selected
target (deterministic roll-forward, or a confirmed abandon-with-proof), then sweep orphaned
machine-local sync residue. Retry is never recover's verb — the report's detail names the
owning command (`stack sync`, `/submit`). Runs under the shared operation lock (§8.49);
`--dry-run` reports everything and mutates nothing.

**The phased protocol.** (0) **Fold-first TRANSFER routing (§8.53)**: read the REQUESTED
objective's succession journal before any train gate — a sole unresolved TRANSFER dispatches
to the transfer arm ahead of the `not_stacked` rejection and the structural gate (a
mid-transfer predecessor necessarily shows intentional `wrong_owner`/`node_link_mismatch`
blockers, and a finalized-but-uncompleted stacked→incremental transfer has no train at all;
the one-unresolved-per-lineage fold gate makes it the sole unresolved operation — a
gate-violating fold falls through to the report-only flow). The arm classifies via the
recorded manifest + the `run_id` successor lookup: successor found + corroborated (§8.53's
supersedes/lineage corroboration) → `all_after`, rolled forward automatically through
`transfer.roll_forward_transfer` under the same held lock; absent → `all_before`, abandonable
with the `successor_absent` proof under `--abandon` (confirmed + re-classified); an
undecodable manifest or a corroboration mismatch → a report-only `mixed` row. Hints name the
predecessor id (the documented recovery entry for an interrupted transfer is
`recover <predecessor-id>`); the transfer seams ride an injectable factory
(`transfer_seams_factory`); `TransferError` passes through the CLI under §8.53's vocabulary.
(0b) **Fold-first sole-PUBLISH routing (§8.54)**: when the ACTIVE train's fold — read after
reconstruction (which follows supersession forward), the SAME snapshot the classifier
consumes; the requested fold walks predecessors only, so a successor-recorded PUBLISH is
invisible to it — has PUBLISH as its SOLE unresolved operation, the existing PUBLISH
classifier/conclusion machinery runs **without** the generic structural gate — a real
unresolved PUBLISH legitimately produces structural cancellation/remote/checkpoint findings
(`canceled_remote_work`, `canceled_publication_pending`, `checkpoint_prefix_gap`, …) from its
own crash window, and the gate would dead-end exactly the operation recover exists to
conclude. The publish proof (`_validate_resume_context` + the exact before/after
branch/PR/stack observation) stays the safety gate, so the bypass never authorizes
checkpoint/identity mutation; all-after remains report-only with the owning `/submit`,
all-before remains confirmation + fresh reclassification + the abandoned outcome, mixed
remains report-only, and the orphan sweep still runs last. Other kinds and multi-unresolved
states keep today's gates.
(1) Reconstruct fresh; §8.49's fail-closed **structural gate**
applies before anything else (`refuse_structural_blockers` — identity/topology blockers
refuse as `claimed_prefix_malformed`: a mis-linked layer can still corroborate on
branch/checkpoint fields, and a roll-forward would checkpoint into the wrong plan); read the
journal fold; no unresolved
operations → the successful empty report (the sweep still runs). (2) **Classify per kind**
with kind-specific decoders — never a generic observer: SYNC/ADOPT through §8.49's shared
record-recovery core (strict decode + fresh-authority corroboration; ANY disagreement is
`sync_drift`-style `mixed`); PUBLISH through a proof helper owned by `publish.py`
(`classify_publish_record` — publish's own domain knowledge stays in publish): the record is
first corroborated against the FRESH train (lineage, affected plan still a layer, branch,
parent base, desired stack — the same `_validate_resume_context` publish's own resume
applies; any disagreement is `mixed`, so `--abandon` can never conclude a stale record from
record-relative remote facts alone); `all_after` requires the FULL read-only publish
postcondition — branch at the candidate, an OPEN head-selected PR with exact base/head facts,
and (for a child) exact desired native-stack membership (the `"self"` sentinel resolves to
the selected PR number); any partial PR/stack effect is `mixed`. Recover still never rolls a
PUBLISH forward — `/submit`'s own resume owns that conclusion. `all_before` strictly decodes
the COMPLETE canonical before branch/PR/stack shape (missing/malformed/unknown is never
absence proof), then requires exact live PR + stack equality; when the record captured NO
pre-operation PR, it requires a **positive PR-absence proof** by the recorded head branch
(ANY existing PR for it — open or closed — is an effect → `mixed`). Infra read failures propagate before any
outcome/checkpoint or orphan sweep. LAND (a future kind)
classifies `unsupported` and is never observed. The classification vocabulary is bounded:
`all_before | all_after | mixed | unsupported` — fail-closed, exactly as §8.49's (any
unreadable observation or corroboration failure is `mixed`, which only ever reports).
(3) **Select the target**: one unresolved operation is the implicit target; several require
`--operation ULID` — without it the report succeeds with `selection_required: true` (rows
still classified), except under `--abandon`, where acting ambiguously is the typed refusal
`operation_ambiguous`; an id matching nothing is `operation_not_found`. (4) **Conclude**:
`all_after` SYNC/ADOPT rolls forward automatically through the shared core (§8.49 steps
13–14 — checkpoints then the completed outcome; deterministic, never asks); `all_after`
PUBLISH reports (its roll-forward already lives in `/submit`'s own resume — the report says
so). `--abandon` requires `all_before` (else `abandon_blocked`), renders the
`AbandonPreview` through the `approve` callback, and **re-classifies after confirmation**
(the human may pause arbitrarily long on the prompt; a post-confirmation observation change
is `abandon_blocked`, nothing journaled) before appending the `abandoned` outcome (observed
= the all-before proof). Declined → `action: "declined"`, journal untouched. `mixed` only
ever reports — concluding it is neither automatic nor abandonable (human investigation).
**Cross-machine quiescence is an operator responsibility**: abandoning while another
machine's owner is still live cannot be excluded by observation; the residual is detected
downstream as `remote_drift`/drift by the next preflight.

**The orphan sweep** (after the conclude phase; skipped entirely under `--dry-run`, reported
as would-be targets). `observe_orphans` (shared with §8.44's status observation) classifies
machine-local sync residue: `sync-*` directories under the worktree root — on disk, PLUS
**stale worktree-admin entries** (still in `git worktree list`'s inventory but with the
directory gone, the residue a killed sync's rmtree fallback leaves) — and
`refs/perk/sync/*` temp refs are **orphaned** unless a PARSEABLE manifest — any lineage,
including foreign ones — claims their operation id (manifest protection: a retained
continuation is live state, never residue). **The unparseable-manifest fail-safe**: ANY
unparseable manifest skips the whole sweep (`sweep_skipped` names it) — an unreadable claim
could be protecting anything. The lock provides liveness protection (a live sync's
mid-operation residue is unreachable while recover holds the lock). Deletion order: refs →
on-disk worktrees → ONE prune (which also collects the stale admin entries — they ride
`swept_worktrees` on prune success and `sweep_failures` on prune failure); per-item failures
are collected as explicit
`sweep_failures: [{target, error}]`, never silent, never aborting the remaining sweep.
Typed refusals never sweep (the sweep runs only after a successful conclude/report phase).

**Errors.** `RecoverError.error_type` ∈ {`operation_ambiguous`, `operation_not_found`,
`abandon_blocked`, `unsupported_operation_kind`, `operation_in_progress`, `not_stacked`,
`invalid_input`}; the roll-forward tail raises §8.49's own arms (`sync_drift`, `pr_drift`,
`postcondition_unverified`, …) which pass through verbatim; infra and reconstruction errors
map at the CLI boundary exactly as sync's.

**The cold worker.** `perk objective stack recover [OBJECTIVE] [--dry-run]
[--operation ULID] [--abandon] [--yes] [--json]`
(`commands/objective/stack/recover_cmd.py`; registered in the stack group). No `--run-id` —
conclude-only recovery needs no run identity. `--dry-run` × `--abandon` is `invalid_input`
(preview first, then abandon). The abandon confirmation follows sync's discipline (stderr
render, `--yes` auto-approve, non-interactive without `--yes` → `confirmation_required`).
Envelope `ObjectiveStackRecoverOut` (snapshotted at
`shared/schemas/outputs/objective-stack-recover.schema.json`), declaration order pinned:
`{success, objective{id,url,redirected_from}, dry_run, selection_required, operations:
[{operation_id, kind, prepared_created, classification, action, detail}], swept_worktrees[],
swept_refs[], sweep_failures: [{target, error}], sweep_skipped|null}` with `classification ∈
{all_before, all_after, mixed, unsupported}` and `action ∈ {reported, rolled_forward,
abandoned, declined}`; under `dry_run` the swept lists carry the WOULD-BE targets. Exit
discipline: 0 = successful classification/report/no-op/actions (including declined and
`selection_required`), 1 = typed refusals + infra failures, 2 = not-a-repo.

**The warm stack surface** (`extension/doors/objectiveStack.ts`; mutations stay canonical in
Python — every tool delegates through the cold door). **Four commands**: `/objective-stack
[N]` is a direct read door (exec `stack status --json`, render the train + operations +
continuation + residue honoring `observed: false`; decode fully lenient/render-only; works
in every session including gate-on); `/objective-sync [N]`, `/objective-recover [N]`, and
`/objective-land [N]` (§8.56) are drive-the-session commands injecting pure exported
guidance (`objectiveSyncGuidance`/`objectiveRecoverGuidance`/`objectiveLandGuidance`,
`prompts/stages/objective-{sync,recover,land}.md` + the skill-binding suffix — no hardcoded
skill pointer): resolve the objective, preview first (`dry_run: true`), present the
cascade/classification/land plan to the human, act via the typed tools ONLY on explicit
human approval, follow the human's stated continue/abort intent. **Gate-on posture**: the
three driving commands soft-refuse under the read-only gate (notify + inject nothing;
headless stderr mirror) — the mutating stack tools never join `READ_ONLY_TOOLS`. **Five
separately-typed tools** (strict tri-state decode via `toolParams.ts` — refuse the whole
call on any malformed field; non-terminating; no broad action enum):
`objective_stack_status {objective?}`; `objective_stack_sync {objective?, base?, dry_run?,
continue?, abort?}` (the CLI's mode matrix enforced in the decode); `objective_stack_adopt
{objective?, node, dry_run?, confirm?}` (`node` required); `objective_stack_recover
{objective?, operation?, dry_run?, abandon?, confirm?}`; `objective_stack_land {objective?,
dry_run?, confirm?}` (§8.56). **Warm consent**: plain sync/continue/abort calls pass
`--yes` (the human's gesture/driven approval is the consent); `objective_stack_adopt`'s
mutating call, `objective_stack_recover` with `abandon`, and `objective_stack_land`'s
mutating call additionally require `confirm: true` (soft-refused `confirmation_required`
otherwise); report/dry-run argv pass neither `--abandon` nor `--yes`. **Objective
inference** everywhere: explicit param/argument → workflow `active_objective` → plan-ref
`objective_id` → a soft `no_objective` fail naming the fix; the warm layer always passes the
resolved objective explicitly to the cold door. **Gating census**: the five tools join
`PERK_TOOLS` and the worktree-family stage lists (`WORKTREE_STAGE_TOOLS` — explicit repair
from implement/address sessions and §8.52's converged workflow); the three drive rows join
the drive-coverage guard. No registry stage is added — the warm commands are
globally-registered doors/drivers (the `ready` non-stage precedent).

**Status.** Recovery/control is landed; automatic submit/address propagation consumes it through
§8.52. TRANSFER recovery is landed (§8.53); LAND recovery remains later work — it stays
report-only and its abandon is still the typed `unsupported_operation_kind` refusal (the
landing mutation itself is §8.56). Cold-envelope decodes on the warm surface stay
render-only — nothing is appended to workflow-state.

## §8.52 · Workflow convergence (automatic propagation, finalization, supervision, and reviewability)

**One structural vocabulary.** `perk.delivery.train.STRUCTURAL_BLOCKER_CODES` is the complete,
context-free set of train identity/topology blocker codes, including `missing_lineage` — and,
since §8.54, the non-recoverable cancellation/checkpoint-topology/journal-history codes
(`canceled_status_conflict`, `canceled_plan_unresolved`, `canceled_published_layer`,
`canceled_remote_work`, `cancellation_evidence_unavailable`, `checkpoint_pair_incomplete`,
`checkpoint_prefix_gap`, `checkpoint_parent_mismatch`, `missing_publish_outcome`,
`checkpoint_after_abandoned_publish`); only the two PENDING codes (`publish_outcome_pending`,
`canceled_publication_pending`) are excluded — a live unresolved PUBLISH concludes via
recover / the owning `/submit` (§8.51's sole-PUBLISH route), never as identity corruption.
Sync's
structural gate, supervisor veto classification, and reviewability consume this same public set;
no caller maintains a context-specific copy. Public `ClaimedLayer` facts plus
`derive_claimed_prefix(train) -> tuple[ClaimedLayer, ...]` are likewise the one
checkpoint-claimed-universe contract shared by publish routing and sync mutation.

**Automatic lower-layer submit.** After reconstructing, `publish_layer` derives the claimed prefix
*before* reading publish's journal fold. A claimed plan with a claimed successor delegates to
`synchronize_train(..., trigger_plan_id=<plan>, approve=None)`; the submit gesture is the consent,
so there is no second prompt and no warm/headless split. Sync therefore owns unresolved-operation
and pending-continuation routing for this arm. `published_prefix_len` never selects it: a successor
declassified by PR/membership/remote drift remains checkpoint-claimed and reaches sync's typed
preflight instead of turning a lower submit into a top republish. The automatic path never includes
the objective base.

**Trigger semantics.** `trigger_plan_id` is normalized like stored plan ids and must identify a
claimed layer, else `claimed_prefix_malformed` explains that publication classification and
checkpoint claims disagree and points to stack status. It is mutually exclusive with
`include_base` and adoption (`invalid_input`); dry-run remains legal. Only the trigger layer's
local committed head is read as a possible source, using the ordinary change rule (exists,
differs from checkpoint, and is not an ancestor of the checkpoint). Every successor source is its
verified published head even when its local branch is ahead; unrelated successor work is never
published by somebody else's submit. A trigger branch that does not resolve to a committed local
head fails closed as `git_error`; an unchanged/stale trigger is the existing no-op result, and
the selected trigger source must contain its stored parent edge (`stale_parent`).

A trigger resume preserves sync's fail-closed record recovery with one critical composition:
all-before abandons with proof and runs fresh with the trigger as usual; mixed is `sync_drift`;
all-after rolls the old operation forward, reconstructs, and runs the full fresh trigger protocol
in the same invocation. The returned arm is the fresh arm (`resumed: false`, fresh operation id or
null on no-op), with a note naming the concluded id: `concluded unresolved operation <id>
(roll-forward) before cascading`. A completed older operation can therefore never report that it
published a newer trigger head.

**Writer exclusion and result contract.** The production probe is
`perk.run.writer_probe.GhaRemoteWriterProbe`. Automatic submit supplies an exclusion only when
`_corroborated_remote_run_id` matches the caller-supplied id to inherited `PERK_RUN_ID`, a consumed
implement/address handoff, and this worktree's active plan-ref. The probe then excludes exactly the
matching `(run_id, plan_id)` pair; neither field excludes alone, an arbitrary/header-derived id
excludes nothing, and every other active writer (including one on the same plan) still blocks.
Explicit sync passes no exclusion. Cascade success returns frozen
`DeliveryOperationFacts {kind:"sync", operation_id|null, abandoned_operation_id|null, resumed,
no_op, affected: tuple[SyncedLayer,…], notes: tuple[str,…]}` on `PublicationResult.operation`;
non-cascade publish/republish/converge arms keep `operation=None`. Publish reconstructs after sync
so a roll-forward-then-fresh-no-op cannot return the pre-roll-forward checkpoint snapshot. The
target layer's PR is fetched from that fresh projection-correlated number, and its published
checkpoint must agree with the affected after-row (or the fresh checkpoint on a sync no-op);
absence/disagreement is `github_error`/`publication_drift`.

`PrSubmitOut` appends `operation {kind, operation_id, abandoned_operation_id, resumed, no_op,
affected:[{node_id, plan_id, branch, pr_number, before_sha, after_sha}], notes:[str]}|null`; flat
`operation_id` remains the compatibility alias and carries the sync id. The warm submit decoder
reduces a valid block to `{kind, operation_id, no_op, affected_count, notes}`, drops the whole block
when malformed without sinking submit, renders cascade/no-op suffixes, and reports every note.
`SyncError.error_type` passes through the submit fail envelope verbatim. On cascades an explicit
`--run-id` merges into `impl_run_ids`; a header-derived run id is not newly stamped, and the
already-existing PR emits no duplicate Linear PR-opened event. Worktree config/probe construction
exists only on the stacked route; incremental submit remains independent of it.

**`finalize_address` is the only model-facing address finalizer.** Parameters remain
`{threads:[{thread_id, comment?}], pr?, counts?}`. After the parent commits its own fixes, the tool
runs `submitPr` first for both incremental and stacked plans; only success enters the unchanged
internal `resolveReviewThreads` core and Python `perk pr resolve-threads` cold door. Submit failure
is non-terminating, preserves its error type, and guarantees threads were not resolved. A partial or
failed resolve is non-terminating and always carries the successful submit facts. When the cold door
returns valid per-thread rows, the failure also carries those rows plus `retry_threads`: successful
rows are omitted, replies positively reported as posted are stripped, and a requested row missing
from the report is retried without its reply because the posting outcome is unknown. An absent or
malformed result payload carries no per-thread claim and instructs inspection before a retry. Full
success appends `last_review_batch`, returns nested submit + resolve facts, drives the same bounded
conflict-resolution follow-up as `submit`, and terminates. The headless address predicate is
finalizer success + recorded batch + successful effective submit evidence with
`mergeable !== false`; the finalizer's nested submit is the first
evidence and a later standalone clean submit supersedes it (a later failed submit cannot satisfy
the predicate). The address stage registry rows include `github.plan`,
`github.objective`, and `github.stack` on both reads and writes because finalization is publication.

**Supervisor convergence.** `classify_stacked_veto(selection, objective_id)` runs before branching
on *every* stacked selection kind, including `no_candidate`. Precedence is: structural blockers →
`build_blocked` with `perk objective stack status`; unresolved operations → `repair_required` with
`perk objective stack recover`; remaining operational blockers → `repair_required` with stack
status. When the train has no veto, a selection-level `build_blocked` retains its own reason
(non-plannable node status or missing roadmap candidate) and the status remedy.

For otherwise-ready `plannable`, `in_flight`, and `no_candidate` selections,
`stacked_lower_attention` scans published layers bottom-to-top and classifies their current plan/PR
state through the shared resume classifier. It returns the node together with the plan authority
read through the train layer's corroborated `plan_id`; dispatch never re-keys that plan from stale
roadmap `node.pr` prose. The first `ADDRESS` layer is dispatched before upper planning or
implementation; fixing the lowest layer first avoids repeated upward cascades.
`READY_FOR_REVIEW` and `AWAITING_REVIEW` are waiting gates and never outrank upper work. A
projection-corroborated plan that disappears on read fails closed as `github_error`; drafts do not
fetch feedback. `objective run` renders the additive `repair_required` action with its reason and
copyable owning remedy, but never auto-runs sync/recover. Dry-run remains the existing offline graph
classification.

**Stacked `/ready` consumes the train.** `require_reviewable_layer(train, plan_id, mutating)` first
requires a known layer whose publication axis is exactly `PUBLISHED`; failure is
`layer_not_published` with axes and findings. A mutating draft additionally requires no unresolved
operation (`unresolved_operation`) and no train-wide structural blocker (`structural_blockers`,
including `missing_lineage`). Operational drift on unrelated layers does not block review.
`mutating=false` validates only target identity/publication, so an already-ready PR remains
idempotent even when a later global veto exists.

The worker keeps dry-run offline and first, then reads the plan and applies submit's header-wins
lineage discriminator. Incremental behavior is unchanged. Stacked ready reconstructs the train,
locates the layer, and fetches the full `PullRequest` from the projection-correlated number before
any gate/mutation (`no_pr` on absent number/object). The validation-only target gate then preserves
`layer_not_published` for a projection-classified merged/closed/wrong-base or otherwise drifted
target. Only when the projection still says `PUBLISHED` does the fetched state apply: a non-OPEN PR
(the post-reconstruction close race) refuses as `pr_not_open`; an OPEN draft enters the mutating gate
then `mark_pr_ready`; OPEN already-ready succeeds without a write after the validation-only gate.
`LayerError`/`TrainReconstructionError` codes pass through; backend/persistence failures map to
`github_error`. The fetched PR supplies the unchanged output envelope's number and URL.

**Status.** Ordinary `/submit` and `/address` now converge published suffixes automatically;
explicit sync remains the owner of base advancement, adoption, continuation/abort, preview, and
operator-driven repair. Reviewability and supervisor prioritization consume the train projection.
Atomic landing and ordinary-land stacked refusal remain separate later contracts.

## §8.53 · Objective replan transfer (stacked supersession — the convergence protocol)

**When it engages (the D1 routing matrix).** `objective create --supersedes` performs ONE
fail-closed predecessor classification read before the supersede mutation —
`get_objective(old)` → `objective.delivery_policy(header)`: not-found → `objective_not_found`;
a classifier `ValueError` → `invalid_delivery_policy` (junk never silently classifies a stacked
predecessor as incremental); an infra failure fails the save. The resulting state snapshot +
policy are threaded into `run_transfer` (which never re-reads/re-classifies the predecessor), and
the already-resolved store instance is reused: routing and planning consume the same ONE read.
Routing keys on the **authoritative policy classifier**, never on lineage presence:

| predecessor → successor | path |
| --- | --- |
| incremental → incremental | the plain §8.32 store mutation, byte-identical apart from the classification read |
| stacked → any | the full **journaled** transfer protocol (`perk.delivery.transfer.run_transfer`) |
| incremental → stacked | the transfer orchestration **minus the journal** (the §8.43 append gate requires stored-lineage equality and the predecessor stores none); interruption tolerance is by-construction — run_id-keyed convergent creation + idempotent merge-writes + close-last. Residual: cross-session abandonment of this arm is not journal-discoverable (drift-diagnostic territory). |

A stacked-policy predecessor with a missing/blank/junk `delivery_lineage` refuses fail-closed
(`missing_lineage`). A stacked→incremental successor stores **no** `delivery`/`delivery_lineage`
(§8.42's absence rule); the predecessor keeps its historical lineage, so its journal (including
the completed TRANSFER) stays readable via the predecessor id. `--dry-run` stays offline (the
transfer never engages).

**The protocol** (lock-first — the §8.49 machine-local operation lock is acquired before the
journal fold, planning, and probes, and held through completion): fold → rerun routing → plan →
**prepare → create → stamp → verify → finalize → complete**. The module is
`perk/delivery/transfer.py` (every effectful callable keyword-injectable with production
defaults); `roll_forward_transfer(seams, record)` is the lock-ASSUMED conclusion core shared by
the save's same-run rerun and recover's all-after arm.

**Planning (the preflight, split by predecessor policy — D13).** A stacked predecessor:
reconstruct the train, `refuse_structural_blockers`, `derive_claimed_prefix` (**"published" for
every immutability/prefix rule = the checkpoint-claimed prefix**, never the classifier's
verified prefix). An incremental predecessor (→ stacked successor): a direct observation path —
predecessor roadmap + `pr` backlinks, carried plan headers via `IssueBackend.get_plan`, open-PR
facts via the PR probe, worktree observation, and the writer probe; the claimed prefix is
trivially empty. A present plan-header `pr` must be a nonblank positive-number string; malformed
or non-string metadata refuses as `pr_exists` because conversion cannot prove the PR absent.
The enforced rules, each a typed refusal with exact expected-vs-observed
detail, **nothing written when planning raises**:

- **Post-publication immutability** (claimed prefix non-empty): the policy must remain stacked
  → `policy_immutable`; the successor stores the predecessor's stored `base` **verbatim** — an
  explicit different base → `base_immutable` (effective-base comparison: `header.base` else the
  detected trunk). Lineage is copied. This enforces §8.42's forward rule (replan is the only
  base-name-changing surface).
- **Prefix preservation**: the successor projection's first K delivery-order nodes must carry
  the K claimed plans **in exact order, each exactly once, none dropped** → `prefix_mismatch`
  (also: a duplicate carry, or a cited plan that does not exist on the predecessor). A node's
  carried plan identity is its `carry_map` entry (Linear — the plan IS the node-issue) else its
  `pr` backlink (GitHub), bare-normalized. The save boundary filters `adopt_issue` identities by
  backend before manifest construction: Linear retains them; GitHub passes an empty carry map
  because its store contract ignores `adopt_issue`. Node ids/descriptions may change freely
  (ownership writes the NEW node id).
- **Suffix reshaping + the open-PR guards**: below the prefix, reshaping is arbitrary — except
  every predecessor plan with an OPEN PR is **mandatory-carry** (dropping one → `dropped_open_pr`
  until the PR closes), and a policy-**changing** replan (stacked↔incremental, either direction)
  refuses while any carried plan has an OPEN PR → `pr_exists` (an existing remote PR already
  makes the layer published, so the conversion path no longer applies). No local branch is ever
  rewritten.
- **Dirty/active blocking** (sync's posture verbatim) over every carried plan plus every
  open-PR plan: a DIRTY worktree → `dirty_worktree`; positively observed remote writers →
  `active_writer`; an unreadable observation → `writer_observation_unavailable` (never "no
  writers").

**The transfer manifest (D7).** The predecessor-carried `PreparedRecord` (kind `transfer`) IS
the durable manifest — sufficient to re-drive creation cross-session (a recover process has no
session artifacts). This is the stored interpretation of the architecture doc's "successor
carries a transfer manifest": the **predecessor journal record** is the sole durable manifest;
the successor carries `supersedes` + lineage + its roadmap. Shapes (owned by `transfer.py`;
strict `StrictInputModel` edge models → frozen dataclasses, decoded fail-closed —
a malformed manifest is `JournalCorruptionError`, never a lenient re-interpretation):

- `before`: `{predecessor_objective_id, base, delivery, delivery_lineage|null, claimed_prefix:
  [{node_id, plan_id, branch, parent_checkpoint_sha, published_head_sha, pr_number|null}],
  carried_unpublished: [{node_id, plan_id}]}`;
- `after`: `{title, prose, base|null, delivery, delivery_lineage|null, roadmap_nodes: [full
  node dumps — id/slug/description/status/pr/depends_on/adopt_issue/comment], carry_map}`.

Decode cross-checks more than shape before any recovery write: envelope objective = recorded
predecessor; envelope lineage = predecessor lineage; journaled predecessor policy = stacked;
successor policy/lineage are coherent; node ids and predecessor plan/node identities are unique;
per-node `adopt_issue` equals `carry_map`; the successor's first K projected plans equal the
claimed prefix; its complete non-null plan projection equals claimed + carried-unpublished in
recorded order; and envelope `affected_plans` equals that projection. Any mismatch is
`JournalCorruptionError`. The successor's pre-creation identity is `record.run_id`; the
verification projection is `delivery_order(after.roadmap_nodes)` zipped with each node's carry
identity — computed from **recorded** data only while unresolved. **Size**: the §8.43 append cap refuses an oversize
record before any write; the transfer renders it as `transfer_manifest_oversize` (shorten the
prose). **Roll-forward corroboration**: a successor found by `record.run_id` must also carry
`supersedes` = the predecessor and the recorded lineage — mismatch fails closed
(`transfer_incomplete`; a foreign objective is never adopted as the successor).

**Execution (steps create → complete), every write convergent/idempotent.** Create:
`supersede_objective(close_predecessor=False)` — deferred close (§8.32's D8 Protocol growth),
find-then-return idempotent on `run_id` with a **convergent found-arm**. GitHub first discovers
an existing roadmap-marker objective-body comment before posting, so the comment-POST/header-id-
backfill interruption reuses the original REST id without a duplicate. Linear re-materializes the
manifest attachment, overview callout, milestones, carried moves, missing fresh node-issues, and
missing dependency relations. A fresh Linear node's issueCreate atomically stores a recoverable
fingerprint (target project + node-id-prefixed title + clean description + phase milestone + node
label); if its later objective-node attachment write was interrupted, the found-arm resumes the
unique matching issue, refuses ambiguity/conflict, and only mints when no match exists. Each write
is idempotent. Stamp: per carried plan, derived from the
manifest alone — claimed-prefix plans get `transfer_plan_ownership` (objective + NEW node id)
only; carried-unpublished plans under a stacked successor additionally get
`stamp_layer_identity` (lineage + the successor-delivery-order predecessor plan id, explicit
null when the layer below is unplanned); carried plans under an incremental successor instead
get `clear_delivery_metadata` (the four stacked fields to explicit null in ONE write). Every
stamp is skipped when the stored values already match (idempotent rerun, no duplicate header
effects). Verify (**before finalize**; failure → `transfer_unverified`, journal unresolved,
predecessor open, no auto-abandon): a stacked successor requires a fresh
`reconstruct_repo_train` whose full `(node_id, plan_id|null)` projection equals the recorded
manifest projection exactly (a never-materialized carried node fails here), zero structural
blockers, and `derive_claimed_prefix` equal to `before.claimed_prefix` (plan ids, branches,
checkpoint pairs, order); an incremental successor verifies by direct reads (roadmap rows match
the projection; every carried plan re-reads with the successor ownership pair and all four
stacked fields null). A git/GitHub infra failure during verification propagates raw (never a
false `transfer_unverified`). Finalize: `finalize_supersession(old, new)` — the extracted,
**raising, idempotent** close side (stamp `superseded_by` — a conflicting existing stamp
raises; cancel dropped still-open Linear node-issues; close/complete; best-effort status
update). Complete: the COMPLETED outcome appends to the **predecessor** carrier (§8.43's
outcome routing).

**Rerun + recovery (D11).** At the save, the predecessor fold routes first: an unresolved
TRANSFER strict-decodes its manifest, then `find_objective(run_id=record.run_id)` — found +
same run → **roll forward** from the recorded manifest and return success; found + different
run → `transfer_incomplete` naming the predecessor + operation (the documented entry is
`perk objective stack recover <predecessor-id>`); absent → provably all-before (creation is the
first post-prepare effect) → append ABANDONED with proof (`successor_absent`) and continue the
fresh pass in the same invocation. An unresolved other kind → `unresolved_operation`. The
`superseded_by` refusal runs AFTER this routing with a same-run convergence arm: a predecessor
stamped by THIS run's successor re-finalizes idempotently and returns success (the
interrupted-finalize tail and the idempotent re-save); any other stamp → `objective_not_open`.
The incremental→stacked arm's lineage resolution is likewise rerun-convergent: a same-run
successor's stored lineage wins over copy-or-mint (a fresh mint mid-convergence would fork the
train identity). `perk objective stack recover` owns cross-session conclusion (§8.51's TRANSFER
arm).

**The door posture** (`objective replan`, §8.32). The door classifies the predecessor policy
fail-closed and, for a stacked predecessor, refuses on any unresolved journal operation
(TRANSFER → `transfer_incomplete` + the recover hint; other kinds → `unresolved_operation`),
reconstructs the train, applies the same structural identity/topology blocker gate as save, and
renders a `<stacked_delivery_facts>` scratch block: the
claimed-prefix MUST-carry listing (exact order), the mandatory-carry open-PR plans, and the
immutability facts. The seed's delivery re-ask is **pre-publication only** (§8.45): a published
predecessor's seed instructs `delivery: stacked` without re-asking.

**Errors.** `TransferError.error_type` ∈ {`policy_immutable`, `base_immutable`,
`prefix_mismatch`, `dropped_open_pr`, `pr_exists`, `missing_lineage`, `transfer_incomplete`,
`transfer_unverified`, `transfer_manifest_oversize`, `unresolved_operation`, `dirty_worktree`,
`active_writer`, `writer_observation_unavailable`, `claimed_prefix_malformed`,
`operation_in_progress`, `objective_not_found`, `objective_not_open`,
`invalid_delivery_policy`, `invalid_roadmap`, `supersede_unsupported`, `invalid_input`} — the
CLI maps them verbatim; infra raises (git/GitHub/store/persistence) propagate under their own
vocabulary, always leaving any prepared operation unresolved (recoverable).

**Residuals (flagged).** The **D14 Linear creation window**: Linear cannot make its first write
run-id-discoverable (discovery IS the sentinel header attachment), so a crash inside the
`create_project` → header-attachment window leaves an **inert non-perk residue project** — no
sentinel ⇒ invisible to `find_objective`/journal/train, and no predecessor-touching write has
happened (carried moves run only after the sentinel — the pinned ordering invariant), so the
rerun's all-before proof stays safe; re-creation may strand the residue project (inherited from
the plain create path; GitHub has no such window — its issue POST carries the run-id header
atomically). This is the ONLY accepted Linear materialization window: after the sentinel, even a
fresh node issue whose create succeeded before its attachment is recoverable through the atomic
create-time fingerprint described above. The non-journaled incremental→stacked arm's cross-session abandonment is not
journal-discoverable. An oversize manifest refuses rather than truncating. The Linear transfer
path is fake-proven; live proof belongs to the Linear smoke gate.

## §8.54 · Native cancellation projection + unified train drift diagnostics

**Native-state observation (Linear).** The project store's `get_objective` reads each
node-issue's native workflow-state type through the state-bearing sibling query
`_LinearProjectOps.project_issues_for_objective_projection` (the byte-stable `project_issues`
selection plus `state { type }`, normalized lowercase or `null`; the original query stays
byte-stable). A roadmap node whose native type is **`canceled`** reads back with effective
`status=SKIPPED` while its PERSISTED attachment status rides the new provenance
`ObjectiveState.native_cancellations: tuple[NativeCancellation(node_id, persisted_status), ...]`
(default-empty — no provenance means existing behavior; GitHub and the dormant issue-backed
Linear store never emit one). The attachment is perk's persisted status; native canceled is the
explicit external-intent **read override** — `canceled` is the only overriding type
(missing/unknown observe nothing; completed/started/unstarted stay attachment-driven), the read
never mutates the attachment, and foreign issues + the born-canceled metadata sentinel never
enter provenance. Description, dependencies, slug/comment, and the plan backlink are untouched.

**The tolerant plan-PR read boundary.** `perk.backends.issue_backend.parse_plan_pr` is the ONE
shared nullable plan-PR parser both production `get_plan` adapters route through:
absent/null/blank/`"None"` = no claim; a positive integer (or string, optional leading `#`)
resolves; anything malformed/non-positive resolves **no** number while the raw header value
stays readable (for `malformed_plan_header` classification and cancellation evidence) — a
malformed PR claim no longer raises before train classification. Read-side tolerance only;
writers remain strict, and infra failures resolving a valid PR keep their typed errors.

**The exact safe-contraction proof.** A native-canceled node contracts (projects as skipped)
ONLY when every applicable predicate positively passes: persisted status is
pending/planning/in-progress/blocked/already-skipped (persisted done ⇒
`canceled_status_conflict`); no duplicate backlink involves it (the global scan); and — with a
plan backlink — the plan resolves (else `canceled_plan_unresolved` beside the canonical
`missing_plan`), the join emitted none of
`wrong_owner`/`node_link_mismatch`/`wrong_lineage`/`lineage_checkpoint_conflict`/
`malformed_plan_header`, both raw checkpoint fields are absent/null (else
`canceled_published_layer`), the raw `pr` is absent/null AND `PlanState.pr` is none (else
`canceled_remote_work`), the journal folded honestly with neither a completed
(`canceled_published_layer`) nor an unresolved (`canceled_publication_pending`) PUBLISH
affecting the plan (abandoned-only is acceptable — recovery writes it only after all-before
proof; missing lineage / corruption ⇒ `cancellation_evidence_unavailable`, fail closed), the
observed remote branch is absent, and the all-state branch-owned PR lookup
(`GitHubProbe.pr_for_branch → BranchPrView`, production `prs.find_pr_for_branch`; a STABLE
read — failure is a typed `github_error`) finds nothing (else `canceled_remote_work`). A
semantically stale but well-typed `predecessor_plan_id` does not prevent contraction; a
non-string one is malformed and unsafe. Failed predicates emit ALL applicable findings.
A SAFE contraction emits the INFO `canceled_unpublished_projected` (carrying the persisted
status) and a `ProjectedCancellation` fact; an UNSAFE node keeps a projection-only layer via a
private `replace(node, status=PENDING)` ordering surrogate (never returned/persisted) whose
layer freezes `intent: canceled` — persisted-skipped plus checkpoint/PR/journal/remote/identity
evidence can never disappear. `repairable_canceled_nodes` is the non-already-skipped projected
subset.

**Checkpoint topology + journal coverage.** Stored checkpoint claims are checked as topology
(header-derived, distinct from remote observation): a half-pair is
`checkpoint_pair_incomplete` (replacing the old half-pair `checkpoint_drift`;
`checkpoint_drift` is reserved for remote/head/ancestry mismatch), a claim above a layer
without a FULL pair is `checkpoint_prefix_gap`, and adjacent full claims whose child
`parent_checkpoint_sha` differs from the predecessor's `published_head_sha` is
`checkpoint_parent_mismatch` (`predecessor_mismatch` and the verified-publication `prefix_gap`
stay distinct). Journal coverage classifies every checkpoint-claiming plan's PUBLISH history
with total precedence (§8.43). The non-recoverable cancellation/topology/history codes join
`STRUCTURAL_BLOCKER_CODES` (§8.52); the two pending codes are excluded, and §8.51 gains the
fold-first sole-PUBLISH recovery route so a real unresolved PUBLISH stays concludable despite
its own structural evidence. Remediation is never "replan past it": repair the edited
Linear/plan/journal/GitHub authority, rerun status, then replan only if a coherent future
roadmap still needs reshaping.

**The diagnosis policy** (`perk/delivery/diagnostics.py`) annotates existing finding identity —
never a parallel drift engine. Base rules: BLOCKER → `error`/nonrepairable, INFO →
`info`/nonrepairable; an unknown future code keeps that kind-derived default with no auto
remediation (it can never become repairable accidentally). Complete overrides: a repairable
`canceled_unpublished_projected` → `warning`/repairable/`perk objective doctor <active> --fix`
(an already-skipped instance stays info/nonrepairable — repairability is tied to the typed
`repairable_canceled_nodes` candidate, never re-derived);
`active_operation`/`publish_outcome_pending`/`canceled_publication_pending` → recover/owning-
submit; `base_advanced` → `stack sync --base`; `checkpoint_drift` → inspect (adopt only for
intentional adoption); `missing_pr`/`pr_wrong_base`/`pr_wrong_head`/`pr_closed`/
`stack_missing`/`stack_divergent`/`canceled_remote_work` → explicit GitHub repair then status;
`stack_read_unavailable`/`base_unobserved` → restore read authority; `journal_corruption`/
`missing_publish_outcome`/`checkpoint_after_abandoned_publish`/
`cancellation_evidence_unavailable` → explicit append-only evidence audit (doctor never
synthesizes history); the identity/topology/status codes → restore the contradicted authority,
rerun status, then optionally replan; `dynamic_singleton`/`all_skipped` → none. Category sets
are pinned disjoint by tests.

**Race-aware metadata repair.** The runtime-checkable `NativeCancellationMetadataWriter`
Protocol (declared in `diagnostics.py`, implemented only by `LinearProjectObjectiveStore` as
`write_node_cancellation_status`) is the ONE narrow train repair: a conditional, ATTACHMENT-ONLY
compare-and-write (`expected_status`/`new_status`, `require_native_canceled: bool|None`,
`require_no_raw_publish_claims`, `dry_run`) returning `APPLIED | ALREADY_CONVERGED | STALE`.
The writer performs a FRESH state-bearing read at the effect boundary, compares the attachment
status, requires native canceled for the forward write, rechecks raw PR/checkpoint claims, and
upserts ONLY the `objective-node` attachment — never the generic status update, never a
workflow-state mirror/re-cancel. The repair pass (per candidate, node order): reconstruct
immediately before the write and require the exact repairable candidate; conditional write
persisted→skipped; STALE is skipped/not-applied, never an abort; after APPLIED, reconstruct and
require still-native-canceled + safely-projected + no-longer-repairable; on observed post-write
drift, compare/write the attachment BACK (no native predicate), VERIFY the rollback with a
fresh conditional read (a dry-run compare against the prior status — the writer's own fresh
state-bearing read is the observation), and abort
loudly (a failed or unverified rollback is included in the abort). Every reconstruction proof
(initial / fresh / post-write) is **pinned to the write-target objective**: the reconstruction
callback follows ``superseded_by``, so a mid-fix supersession hands back the successor's
projection — never a valid proof for the pinned target; a redirected proof reads as the
unavailable arm (no write, no blind rollback). Dry run executes the fresh proof +
conditional validation with no write/compensation. This is not distributed atomicity — it
prevents stale snapshots from writing and compensates observed drift. Doctor never repairs plan
identity, checkpoints, journal history, branches, PRs, or native stack membership.

**The two-part doctor.** Expected authority-read failures (issue-backend / objective-store /
train-persistence errors) normalize onto the typed reconstruction failure at doctor's
diagnosis and repair boundaries — a routine plan/journal outage is the modeled `unavailable`
state, never an escape. `perk objective doctor` resolves the requested objective through
`train.resolve_active_objective` ONCE — manifest detection/repair and train
reconstruction/repair all target the ACTIVE id (`objective` reports it; additive
`redirected_from` preserves the requested id; a predecessor is never mutated by
`doctor OLD --fix`). The report is two parts: the existing Linear manifest drift plus the exact
`DeliveryTrain` findings on every backend, each annotated with the diagnosis policy
(`TrainFindingOut: code, severity, node_id, plan_id, message, repairable, remediation`).
`TrainDiagnosisOut` (field order load-bearing): `state: stacked|incremental|unavailable,
objective_id, redirected_from, error_type, message, blockers[], information[]` — stacked
carries findings with null error/message; incremental the no-train message; unavailable the
typed error + message with empty findings. `--fix` additionally runs the cancellation repair
(`TrainRepairActionOut: code, node_id, outcome: applied|would_apply|skipped|failed, error`;
`TrainFixOut: state, applied, skipped, failed, remaining, aborted, dry_run` with states
`completed` (a NON-ABORTED pass — candidates applied/would-apply, or skipped as
converged/STALE race outcomes, so `completed` never implies every candidate converged; failed
null; aborted false),
`aborted` (write/post-verification/rollback failed), `skipped_manifest_abort` (the manifest
repair aborted first — no train action, initial diagnosis remains), `unavailable`
(current/post-repair train unavailable; failed null unless it follows an applied action, which
records the verification failure)). Sequence: initial manifest/train reports → existing
manifest repair → reconstruct if the manifest changed → per-action fresh conditional repair →
final diagnosis in `remaining`. Top-level payload order stays
`success,error_type,objective,drift,fix` then appends `redirected_from,train,train_fix`
(without `--fix`, `train_fix` is null). An assembled report keeps `success: true`/null error;
the EXIT code conveys unavailability/aborted repair: detect-with-findings 0; detect-unavailable
1; manifest-abort 1; current-train-unavailable 1; write/verification abort 1; fix-succeeded
(report-only drift remaining) 0; not-a-repo the fail envelope 2; active-resolution/store
failure the fail envelope 1.

**Compatibility.** No provenance ⇒ byte-existing behavior; the stack-status JSON shape is
unchanged (new findings and `intent: canceled` are values inside existing string fields);
doctor additions are additive. Missing journal/Git/GitHub/plan/header proof fails cancellation
closed. The Linear additions are offline/fake-proven; live smoke remains later hardening. This
section classifies/projects the cancellation-derived dynamic singleton and all-skipped train
only — singleton landing and all-skipped objective completion are the landing mutation's
contract (§8.56).

## §8.55 · Landing readiness (LandReadiness — the dry-run preflight projection)

**The projection.** `perk.delivery.land.assess_land_readiness(train_projection, *,
observations, remote_writers)` composes one typed, immutable `LandReadiness` for a stacked
objective's delivery train: the already-reconstructed `DeliveryTrain` (§8.44) plus **fresh**
GitHub observations — per-PR exact refs/mergeability/review decision/required-check flags/
aggregate rule state, base merge rules, host stack-API capability — with advisory unresolved
review threads reported separately as information. **Composition, never duplication**: train
blockers, unresolved operations, membership, and the INFO findings are consumed from the
projection as-is; only the landing-specific facts are freshly observed. The pure core imports
only `perk.delivery.writers` + `perk.delivery.train` (never `sync`/`observe` — `observe.py`
wires *this* module and `sync.py` imports `observe`); it owns its observation views
(`PrLandView`/`CheckView`/`MergeRulesView`, the `LandObservations` Protocol +
`LandObservationError`) and never sees `perk.github` types. The shared remote-writer seam
(`RemoteWriterProbe` + `WriterObservationError`) lives in the leaf `perk/delivery/writers.py`
(moved from `sync.py`, which re-exports both names) so mutating and readiness preflights share
one fail-closed observation contract. Production wiring:
`observe.GatewayLandObservations(repo_root, base=…)` over `perk/github/stacks.py`
(`pr_land_facts` / `base_merge_rules` / `stack_capability`), wrapping `GitHubError` into
`LandObservationError` — except the capability bool, which passes through (below).

**Dispositions.** `READY | BLOCKED | NOTHING_TO_LAND`. READY iff ≥1 layer and ZERO blockers
(information never vetoes — advisory threads, failed optional checks, and a clean ACTIVE
worktree all leave READY intact; landing merges remote PRs and never touches local worktrees).
Blockers take precedence over every disposition: a zero-layer (all-skipped) train is
`NOTHING_TO_LAND` **only when clean** (no composed blocker, no unresolved operation) —
otherwise BLOCKED; a zero-layer train skips every enrichment read (`rules=null`,
`native_stack_capability=null`, no writer probe, no per-PR reads). The landing mutation
(§8.56) treats `NOTHING_TO_LAND` as its permission to complete the objective without a
merge.
`LandPlan` is built only when READY: layers bottom→top with per-layer `base_sha` (parent
checkpoint — the incremental diff base) and `head_sha` (published-head checkpoint, freshly
corroborated), `merge_method: squash`, `top_pr_number`/`top_head_sha` from the last layer,
and `mode`: `singleton_squash` for a one-layer train (the §8.54 dynamic singleton — the
capability and composition arms are **not consulted**: `native_stack_capability` stays null
and the singleton's `NOT_APPLICABLE` membership is correct) else `stack_merge_async`.

**Assessment order.** (1) Train state composes first: every train BLOCKER passes through
verbatim; every `unresolved_operations` entry (ANY kind, including a prior LAND — recovery is
the recovery node's concern) becomes the blocker `unresolved_operation`; train INFO findings
compose as information. (2) Zero layers short-circuits (above). (3) Publication completeness, checked on BOTH axes:
every layer must be `published` — each offending layer is an `incomplete_publication` blocker
(embedding its publication axis value); a `published` layer missing any §8.46-guaranteed
identity/checkpoint field classifies back to `incomplete_publication` rather than being
trusted; and when every layer reads `published` but `published_prefix_len` still falls short
of the layer count, the inconsistent projection is one train-wide `incomplete_publication`
blocker (fail-closed — never READY). (4) Only published layers are **assessable**; non-published layers get honest
`assessed: false` rows with null observations while published siblings are STILL fully
assessed (the report stays complete on a partially published train). (5) Local writers from
the train's writer axis: `DIRTY` → blocker `dirty_worktree`; clean `ACTIVE` → information
`active_worktree`. (6) Remote writers over every layer with a plan id (planned-but-unpublished
included — an active writer anywhere in the train is affected): non-empty → blocker
`active_writer` naming the plans; `WriterObservationError` → blocker
`writer_observation_unavailable`. (7) Base merge rules → `rules`; `squash_allowed: false` →
`squash_forbidden`; `merge_queue_required: true` → `queue_required_base`; a failed read →
`rules=null` + `merge_rules_unobserved`. (8) Host stack capability (multi-layer only) →
`native_stack_capability`; `false` → `stack_capability_unavailable`. (9) Composition
(multi-layer only): every layer's membership axis must be `EXACT` — anything else (including
`UNKNOWN`: fail-closed) is a `composition_divergent` blocker. (10) Per-layer fresh readiness
for each assessable layer: a read failure is a localized `readiness_unobserved` blocker (the
remaining layers still assess); a vanished PR is `pr_missing`; an observed PR classifies
`pr_not_open`, `pr_draft`, `wrong_base`, `wrong_head_ref`, `head_moved`, `pr_conflicting`
(CONFLICTING), `mergeability_unknown` (UNKNOWN — transient), the **independent fail-closed
`mergeStateStatus` mapping** (`BEHIND` → `pr_behind`; `BLOCKED` → `pr_blocked` — GitHub's
aggregate enforced-rule verdict, where an enforced conversation-resolution rule materializes;
`UNKNOWN` → `merge_state_unknown`; `DIRTY` → `pr_conflicting` even when `mergeable` says
MERGEABLE; `DRAFT` → `pr_draft` even when `isDraft` is false — while AGREEING scalar +
aggregate facts emit one blocker row, never a duplicate; only `CLEAN | HAS_HOOKS |
UNSTABLE` add no blocker), required-check classification (`required_check_failed` /
`required_check_pending` blockers with names; failed optional checks are the information
`optional_check_failed`, never a blocker), review decision (`CHANGES_REQUESTED` →
`changes_requested`; `REVIEW_REQUIRED` → `review_required`; `APPROVED` or **null** pass — the
one deliberate nullable-pass: a null decision positively means the base requires no review),
and `unresolved_thread_count > 0` → information `unresolved_threads` (advisory — never a
perk-invented gate). (11) Disposition + plan.

**The finding vocabulary (the declared bound).** Findings reuse `train.TrainFinding`
(composition, not a parallel type). The public code set is the explicit union of (a) the
§8.44 vocabulary, **passed through as-is** (a declared passthrough class — future train codes
flow through legally), and (b) the land-only codes, enumerated exhaustively: blockers
`unresolved_operation`, `incomplete_publication`, `dirty_worktree`, `active_writer`,
`writer_observation_unavailable`, `squash_forbidden`, `queue_required_base`,
`merge_rules_unobserved`, `stack_capability_unavailable`, `composition_divergent`,
`readiness_unobserved`, `pr_missing`, `pr_not_open`, `pr_draft`, `wrong_base`,
`wrong_head_ref`, `head_moved`, `pr_conflicting`, `mergeability_unknown`, `pr_behind`,
`pr_blocked`, `merge_state_unknown`, `required_check_failed`, `required_check_pending`,
`changes_requested`, `review_required`; information `active_worktree`,
`optional_check_failed`, `unresolved_threads`. No raw error types pass into codes; failure
text goes into `message`.

**Fail-closed enrichment posture.** An enrichment-read failure after a sound reconstruction is
a specific BLOCKER, never an abort: disposition BLOCKED with the rest of the report still
rendered (can't-verify ⇒ not-ready). The **raising** reads — per-PR readiness
(`readiness_unobserved`), merge rules (`merge_rules_unobserved`), the writer probe
(`writer_observation_unavailable`) — each embed the exact failure text in the blocker message.
The capability probe is the ONE declared boolean arm: the gateway's `stack_capability()`
collapses read failure to `false` by design (§8.45), so unsupported and unobservable both map
to `stack_capability_unavailable` **without** failure detail. Every positive arm requires
positive evidence — absent/null observations block or stay null, never classify as passing.
**Capability-evidence limit**: `native_stack_capability` proves only that the host's GraphQL
`PullRequest` type exposes the native-stack API surface — NOT per-repository preview
enrollment and NOT `/merge-async` availability; those are observable only at mutation time and
belong to the landing mutation's failure classification (§8.56's
`merge_async_unavailable`). A READY verdict never claims more than was observed. Failures
*during* train reconstruction keep §8.44's typed exit-1 mapping.

**The gateway read.** `stacks.pr_land_facts(number, repo_root)` is a **strict per-PR
paginated** GraphQL read (`PR_LAND_READINESS_QUERY` — one document; variables
`$owner $repo $number $checksCursor $threadsCursor`): scalars
(`number state isDraft baseRefName headRefName headRefOid mergeable mergeStateStatus
reviewDecision`) repeated on every page, the head commit's `statusCheckRollup` contexts
(CheckRun + StatusContext, with `isRequired(pullRequestNumber:)`), and `reviewThreads`
(`isResolved` counting), both connections cursor-paginated at 100/page. Every selected field
is REQUIRED (nullable only where semantically nullable: `reviewDecision`, CheckRun
`conclusion`, a null `statusCheckRollup` = no checks); wire vocabularies are exhaustive
`Literal` sets and an unknown value raises; `commits.nodes` must be EXACTLY one dict
(`last: 1` fixes the cardinality — an empty list, a junk member, or an extra element is
malformed authority, never tolerantly filtered); a payload whose parsed PR `number` differs
from the requested one raises (the identity check — another PR's node never becomes this
PR's readiness evidence); `None` on a missing PR; `GitHubError` otherwise. Outcome
normalization to `passed | failed | pending`: CheckRun not-COMPLETED → pending; COMPLETED +
{SUCCESS, NEUTRAL, SKIPPED} → passed; COMPLETED + {FAILURE, TIMED_OUT, CANCELLED,
ACTION_REQUIRED, STALE, STARTUP_FAILURE} → failed; **COMPLETED + null conclusion → pending**
(contradictory wire state, fail-closed); StatusContext SUCCESS → passed, ERROR|FAILURE →
failed, EXPECTED|PENDING → pending. Pagination is deterministic, bounded, and coherent: nodes
accumulate from a connection only while it is unexhausted (an exhausted connection's
re-returned nodes are never re-accumulated); a continuing connection's `endCursor` must be
non-null and differ from the cursor just used (violation ⇒ `GitHubError` — non-advancing/
cyclic pagination); at most **20 requests per PR** (≥2,000 contexts/threads — beyond any legal
train); and the **scalar-coherence guard** re-parses the scalars (and rollup state) on every
page — ANY repeated value differing from the first page raises ("PR changed during the
readiness read"): checks/threads from different commits are never combined into one
`PrLandFacts`. A required check that never reported at all is invisible to the rollup read;
GitHub's own `mergeStateStatus: BLOCKED` is the covering authority for that case.

**The cold worker.** `perk objective stack land [OBJECTIVE] --dry-run [--json]`
(`commands/objective/stack/land_cmd.py`; the group's land verb). **No remote mutation
anywhere in this section**: bare `land` (no `--dry-run`) is the §8.56 landing mutation on
this same argv shape (it replaced the historical `land_unimplemented` refusal).
`--dry-run` resolves the objective (explicit arg → worktree plan-ref → `no_objective`),
reconstructs the train with exactly `stack status`'s exception→envelope mapping, maps
`NoDeliveryTrain` → typed `not_stacked` (exit 1), assesses, and reports. Envelope
(`ObjectiveStackLandOut`, snapshotted at
`shared/schemas/outputs/objective-stack-land.schema.json`; field order load-bearing):
`{success, error_type, objective{id,url,redirected_from}, dry_run, disposition, base,
delivery_lineage, rules{squash_allowed,merge_queue_required}|null,
native_stack_capability|null, layers[], blockers[], information[], plan|null}` — each layer
row mirrors `LandLayerReadiness` field-for-field (`node_id, plan_id, pr_number, branch,
expected_base_ref, expected_head_sha, base_sha, assessed, observed_state, observed_is_draft,
observed_base_ref, observed_head_ref, observed_head_sha, mergeable, merge_state_status,
review_decision, required_checks_failed[], required_checks_pending[],
optional_checks_failed[], unresolved_thread_count|null`; unassessed rows serialize their
nulls as-is), and `plan` is `{mode, merge_method, top_pr_number, top_head_sha,
layers[{node_id, plan_id, pr_number, base_sha, head_sha}]}` — plus the §8.56 mutation
fields declared strictly at the tail (`outcome, operation_id, merge_async_uuid,
landed_layers[], objective_closed, notes[]` — nulls/empties on every dry-run envelope, so
the §8.55 byte order is preserved). Exit codes: **a BLOCKED verdict
is a successful detection ⇒ exit 0** with every blocker rendered (the `stack status` split);
`1` = the typed failures where no honest assessment exists (reconstruction failures,
`not_stacked`, `no_objective`, invalid input); `2` = not-a-repo. `--json` →
stdout; the human render (stderr) is fed entirely from the `LandReadiness` value (no
finding-message scraping): disposition headline, the rules line (including the honest
"merge rules unobserved" arm), bottom→top layer lines with expected-vs-observed refs/SHAs
(unassessed rows say `not assessed`), the plan summary when READY, then
`blockers:`/`information:`.

**Status.** This section is the read path only; the landing mutation (journal writes, merge
submission, UUID polling, finalization, confirmation) and the all-skipped objective
*completion* have since landed as §8.56. Interrupted-LAND recovery remains a later node's
contract; here an unresolved LAND is simply a readiness blocker and the clean zero-layer
train is only the `NOTHING_TO_LAND` disposition.

## §8.56 · Objective landing (the journaled atomic merge)

**The operation.** `perk.delivery.landing.land_train(repo_root, *, objective_id, run_id,
remote_writers, approve=…, …seams)` is the landing **mutation** behind bare
`perk objective stack land` — a thin consumer of the §8.55 readiness projection
(`assess_land_readiness`, consumed as-is, never re-derived) plus the §8.43 journal
(`TrainPersistence.append_prepared`/`append_outcome`), the per-layer finalize seam
(`perk.delivery.finalize.finalize_landed_plan`), and the machine-local operation lock
(oplock scope grows to sync + recover + **land**; a busy lock is the typed
`operation_in_progress`). No extra merge modes, no queue emulation, no generalized landing
abstraction. Injection shape mirrors `sync.py`: one public entry with keyword-injectable
seams defaulting to production wiring. `land.py` stays the pure readiness core (its import
direction forbids `observe`/gateway imports); the mutation lives in the new
`perk/delivery/landing.py`. The squash-message helper is the public pure
`landing.squash_commit_message(*, issue, url, backend_id, title)` (byte-identical to the
incremental `pr land` footer format — GitHub `Closes #N`, non-github `Plan: <id> — <url>`;
`pr/land_cmd.py` imports it — one implementation, no drift).

**The wire contract (GitHub's stacked-PR merge API, public preview).** Submit:
`PUT /repos/{owner}/{repo}/pulls/{top}/merge-async` with EXACTLY
`{"merge_action": "direct_merge", "merge_method": "squash", "sha": "<expected top head>"}` —
`sha` is the head-pin (a non-matching PR head rejects the merge); no
`commit_title`/`commit_message` (GitHub's automatic per-PR squash messages stand;
plan-issue closes are finalize's explicit job). Reply arms: `202 {status: "pending",
details: {uuid, merge_method, merge_action, expected_head_sha, message}}`; `200
{status: "merged"}` (already merged); `409 {status: "pending", details: {…}}` — an EXISTING
merge request whose options **may differ** from the request's; `400 {status: "failed"}`
(closed/draft); `404` — async merge **not available for this repository**; `422` — body
validation failure. Poll: `GET …/merge-async/{uuid}` — `status ∈ pending | merged |
enqueued | failed` (exhaustive; unknown raises); `merged` carries `details.sha` (the merge
commit — required, else the read raises); `enqueued` is terminal for the REQUEST (the queue
owns the outcome), not for the train; the handle expires after 24h (404). A stack merge is
atomic: merged entirely or nothing. The **dynamic singleton** lands via the legacy
synchronous `PUT …/pulls/{n}/merge` with `merge_method=squash` + the same `sha` head-pin +
the squash commit message (it is never in a native stack — membership NOT_APPLICABLE — and
must land even where merge-async preview enrollment is absent). Gateway surface
(`perk/github/stacks.py`): `submit_merge_async` / `merge_pr_direct` are **total** (the
`--include` status + `Retry-After` classification; a spawn failure folds into the ambiguous
`status=None` arm; an unparseable 2xx/409 body leaves `state=None` — ambiguous, never a
guessed success); `merge_async_result` / `pr_merged_evidence` (per-PR
`state + baseRefName + headRefName + headRefOid + mergeCommit.oid` — the identity fields
the verification corroborates; a zero-exit reply carrying an explicitly-null PR node is the
ordinary lookup miss, `None`) are **strict** (they decide whether a journal outcome may be
appended — junk raises, never degrades).

**The protocol, in order.** (1) The operation lock. (2) Reconstruct
(`observe.resolve_train_reads` + `reconstruct_train`); `NoDeliveryTrain` or a null
`delivery_lineage` → typed `not_stacked`. (3) Assess (§8.55). (4) **NOTHING_TO_LAND** →
`approve` with the completion preview ("nothing to merge; close objective #N") — declined ⇒
`outcome: declined`; approved ⇒ `store.close_objective` (this arm's PRIMARY effect: a store
failure is a typed error, never fail-open) ⇒ `outcome: completed_without_merge`,
`objective_closed: true`. **No journal** (no remote train mutation to guard; the close is
idempotent/convergent). (5) **BLOCKED** → the typed refusal `land_blocked` carrying the full
composed readiness. (6) **READY**: for `singleton_squash` the load-bearing pre-merge
`get_plan` read happens NOW (missing ⇒ typed `plan_not_found`; it supplies the squash
title/url + the tolerantly-parsed `consumed_learn`); then `approve(readiness)` — the
rendered land plan; declined ⇒ `outcome: declined`, nothing journaled. (7) **Re-observe**
every layer PR after the arbitrary approval pause (`stacks.pr_delivery_facts`: OPEN, head ==
plan `head_sha`, base == expected base ref, head ref == branch); any mismatch/read failure →
typed `land_drift`, nothing journaled. (8) **Prepared** (journal-first, read back; the
one-unresolved gate and `JournalAppendAmbiguous` propagate typed). (9) **Submit** — classification
admits ONLY the exact protocol status/state pairs (202/409 + `pending`, 200 + `merged`,
404, 400 + `failed` or a bare 422); every discordant combination — a 5xx carrying ANY
parseable state, a body contradicting its status, an unparseable 2xx/409 body, no status —
is ambiguous (a 5xx never proves the merge was or was not scheduled, so it can never reach
a terminal abandon). The
async arm verifies a `pending` reply's returned options against the prepared request
(`merge_method == squash`, `merge_action == direct_merge`, `expected_head_sha == top pin`,
`uuid` present): match ⇒ append `accepted` (the one sanctioned non-reconstructable handle) ⇒
poll; mismatch (the foreign-409 arm) ⇒ typed `merge_request_conflict` with NO accepted
append (the prepared operation stays unresolved — a foreign merge may be in flight);
`merged` ⇒ skip the poll, go to verification; 404 ⇒ abandon-with-proof then typed
`merge_async_unavailable`; 400/422 ⇒ abandon-with-proof then typed `land_failed`;
ambiguous ⇒ ONE identical SHA-pinned retry — and a first-attempt ambiguity is PRESERVED:
only a matching pending handle (recovering the request) or a merged reply concludes it;
ANY other retry reply (404/400/422/failed/still-ambiguous) leaves `outcome: pending` with
NO outcome append — the first request may already have created the async job, so a
retry-side rejection proves nothing about it. The singleton arm merges directly: `merged`
⇒ verification; any 4xx ⇒ abandon-with-proof then `land_failed` (the 404 arm too — the
legacy endpoint exists everywhere; a missing PR is drift, not availability); ambiguous ⇒
one identical retry, with the same preserved-ambiguity rule — only a `merged` retry reply
(including the already-merged idempotent arm, which recovers an applied-but-unconfirmed
first attempt) concludes it; anything else leaves `pending`. **No `accepted` event ever on
the singleton** — there is no handle. (10) **Poll** (async
arm): up to 60 ticks, injected `sleep(1)`; `pending` continues; `merged` ⇒ verification;
`failed` ⇒ abandon-with-proof then `land_failed`; `enqueued` ⇒ stop immediately,
`outcome: unexpected_enqueued` (unresolved); per-tick read failures are tolerated within the
budget; exhaustion ⇒ `outcome: pending`. (11) **Abandon-with-proof** (terminal
non-application only): every layer PR re-observed OPEN at its exact expected head ⇒ append
`abandoned` and let the typed failure propagate (retry is legal — the operation is
resolved); ANY contradiction or read failure ⇒ NO outcome append, `outcome: pending` (never
claim before-state without proof). (12) **Verification**: per layer bottom→top
`pr_merged_evidence` — every PR `MERGED` with a non-null merge commit AND its identity
corroborated: head OID == the layer's approved published head (the re-observe→submit
window is not zero — a force-pushed lower layer must not pass under the top-only SHA pin),
head ref == the published branch, and base ref == the layer's expected base ref OR the
objective base (GitHub retargets a dependent PR onto the base when its parent branch is
deleted at merge — both targets are legitimate landings of the approved train; any other
base fails); any mismatch/read failure ⇒ NO
completed append, `outcome: pending` with a loud note; all verified ⇒ append `completed`.
**Invariant 20**: once per-PR verification succeeds, a failed/ambiguous `completed` append
or any finalize failure degrades to loud `notes` on `outcome: merged` — never an error
exit. (13) **Finalize** bottom→top per layer (`finalize_landed_plan` with
`close_objective_on_complete=False`; `pr_base` = the layer's verified expected base ref;
`consumed_learn` re-read per layer, fail-open to `()` — the singleton reuses its step-6
read); a per-layer finalize exception ⇒ `finalization: null` + a note, remaining layers
still finalize. (14) **Aggregate close**: re-fetch the objective; every node terminal ⇒
`store.close_objective` (isolated fail-open — a failure is `objective_closed: false` + a
loud note); else a note naming the non-terminal nodes. `outcome: merged`. The Linear agent
"landed" activity emission and the worktree `pending-learn` marker stay OUT (both are
worktree-session-scoped caller concerns; objective-scoped landing has no single plan
session) — durable `learn_state` is still stamped per layer by finalize.

**Journal payload shapes (kind-owned mappings inside the §8.43 envelope).** prepared
`before`: `{"mode", "merge_method", "base", "top_pr_number", "top_head_sha", "layers":
[{"node_id", "plan_id", "pr_number", "base_sha", "head_sha"}, …]}` — exactly the `LandPlan`
evidence plus `base` from `train.base`. prepared `after`: `{"merged_pr_numbers":
[bottom→top], "base": "<branch>"}`. accepted `observed`: `{"uuid", "merge_method",
"merge_action", "expected_head_sha", "http_status"}` (the VERIFIED accepted options).
completed `observed`: `{"layers": [{"pr_number", "merge_commit_sha"}, …], "reported_sha":
<poll details.sha / singleton body sha / null>, "final_base_sha": <the TOP layer's merge
commit — a direct stack merge lands the train as base commits; the singleton likewise>}`.
abandoned `observed`: `{"reason": "<submit_404 | submit_failed | submit_rejected |
poll_failed>", "detail": "<bounded failure text>", "reobserved": [{"pr_number", "state",
"head_sha"}, …]}`. Strict parse models for these payloads are the recovery node's read-side
concern.

**Vocabularies + exit semantics.** Outcomes (every one exit 0 — an honest envelope):
`merged | pending | unexpected_enqueued | completed_without_merge | declined`; `pending` /
`unexpected_enqueued` mean the LAND operation stays **unresolved** — never success, never
failure (interrupted-landing recovery concludes it — a later node; §8.51's `stack recover`
keeps LAND rows report-only). `LandError.error_type` (exit 1): `not_stacked | land_blocked |
land_drift | land_failed | merge_async_unavailable | merge_request_conflict | plan_not_found
| operation_in_progress | confirmation_required`; reconstruction/persistence/backend errors
keep their existing typed passthrough at the CLI boundary (the `sync_cmd` ladder, plus
`journal_corruption` and `git_error`); exit 2 = not-a-repo. `land_blocked` renders the full
readiness report to stderr (the shared human renderer with a "landing readiness" heading)
and attaches the dry-run-shaped readiness payload to the JSON fail envelope under the
`readiness` key.

**The cold worker.** `perk objective stack land [OBJECTIVE] [--dry-run] [--run-id ID]
[--yes] [--json]` — `--dry-run` stays the §8.55 read-only preview (behavior unchanged; the
envelope preserves the §8.55 field prefix/order with the §8.56 mutation fields appended as
trailing nulls/empties; no consent, `--yes`/`--run-id` ignored). Bare
`land` requires GitHub auth (`require_github`), resolves the run id (explicit `--run-id` →
the ACTIVE objective header's `run_id` → typed `invalid_input`; `stack/shared.py::
resolve_run_id`, shared with sync), and confirms: `--yes` auto-approves (still rendering
what it approved); a non-interactive session without `--yes` is the typed
`confirmation_required` refusal BEFORE any prompt. The success envelope grows the trailing
fields `{outcome, operation_id, merge_async_uuid, landed_layers: [{node_id, plan_id,
pr_number, merge_commit_sha, learn_state, plan_issue_closed, nodes_marked, finalized}],
objective_closed, notes[]}` with `dry_run: false` (and `objective.redirected_from` keeps
the dry-run semantics: the requested id when supersession redirected — derived from the
requested-vs-active objective ids, also on the `land_blocked` readiness attachment); the
human render reports the outcome
headline, per-layer merged/finalized lines, the objective-close line, notes, and the
pending/enqueued guidance (the LAND operation is unresolved — landing is blocked until it
concludes; recovery lands in a later node).

**The warm surface.** The fifth typed tool `objective_stack_land {objective?, dry_run?,
confirm?}` (strict tri-state decode; the adopt-shaped consent gate — `!dry_run && !confirm`
⇒ typed `confirmation_required`; dry-run argv passes `--dry-run`, the confirmed call passes
`--yes`) and the fourth driving command `/objective-land [N]` (gate-on soft refusal like
sync/recover; injects `prompts/stages/objective-land.md` + the binding suffix: preview
first via `objective_stack_status` + `objective_stack_land {dry_run: true}`, present the
plan or blockers, act ONLY on explicit human approval, report `pending`/
`unexpected_enqueued` as unresolved and STOP — never loop retries). Census: the tool joins
`PERK_TOOLS` and the worktree-family stage lists; the drive row joins the drive-coverage
guard; envelopes render leniently (render-only DATA).

**Status.** Landed: the mutation, the singleton arm, the NOTHING_TO_LAND completion, and
the happy-path aggregate objective close. Deferred to the recovery node: concluding an
interrupted landing (`pending`/`unexpected_enqueued` stay unresolved; `stack recover`
reports LAND rows without concluding them) and the ordered-journal-evidence objective
reconciliation. The wire shapes are pinned from GitHub's official stacked-PR merge-API
reference; CI stays hermetic against fakes — the live proof is the landing dogfood gate.

## §8.57 · Single-statement-of-contract prompt layering (Objective #1610, Node 3.1)

**The single-statement-of-contract layering rule.** Per stage, each contract statement has
exactly one **canonical carrier**; every other surface points at it, never restates it. The
standard carrier assignment:

- **Launch statement** — the one-time prose that opens a session, classified by delivery call
  site, never by template path: a cold door's seed, a warm door's guidance turn, or the headless
  worker's primer (`stages/implement.md` serves all three call-site classes) — carries **the
  flow, stated once per session shape**.
- **Injected context** (the persistent marker-dedup'd `before_agent_start` injections, §8.31) —
  carries **live state + pointers**: what is true of this session (mode, constraints, tool
  surface) plus pointers to where the flow and the detail live; never a restatement of either.
- **Adapter block** (`prompts/contexts/adapters/*`) — carries **only the surface delta**: what
  differs on this provider surface, nothing the base context or launch statement already
  establishes.
- **Bound skill** (§8.9) — carries **the read-on-demand detail**: the judgment layer behind the
  flow, in **every** session shape; it points back at the flow and never carries or restates it.
- **Skill ambient `description`** — for an ambient-visible skill, a discovery cue only (the
  tasks + trigger phrases), never a summary of the body; for a prompt-hidden bound skill
  (`disable-model-invocation: true`), not a live trigger surface at all — keep it a one-line
  accurate cue for catalog surfaces.

**The one named exception (stage-scoped):** the `plan` stage's mode context
(`prompts/contexts/plan-authoring.md`) is its **designated flow carrier** in every plan-stage
session shape **save the REPLACE-posture carve-out below**. The bare launch is idle by design (user-driven; `_initial_prompt`
returns no prompt), and the seeded plan-stage doors (e.g. `plan from`, `replan`) carry only
their launch-shape deltas — the untrusted-DATA framing, the shape-specific investigation
guidance, and the shape's save semantics — deferring the flow to the same mode context.
Marker-dedup guarantees one live copy, so the flow is still stated exactly once per session.
The carve-out: under a **REPLACE-posture** provider selection (the provider owns the plan
surface and perk's mode context is never injected — today `tombell-plan`), the **adapter
block** is the designated flow carrier for that session shape instead: carrying the flow there
is the surface delta, not a restatement (the seeds' flow pointers stay provider-neutral so they
name whichever carrier is injected). No other stage or surface may claim these exceptions without
amending this section.

**Enforcement posture (flagged deferral).** The rule is a prose convention with **no CI guard**
from this node; the byte ceilings that make regression loud arrive as node 5.2's named gates
#2/#3, their constants pointing at this section.

**Migration recipe** (what nodes 3.2–3.4 execute, one stage family per node): (a) inventory
each stage's contract statements across its launch statement(s), injected context(s), adapter
block(s), skill body, and ambient description; (b) assign each statement its one canonical
carrier per the standard map above; (c) rewrite the non-canonical surfaces to pointers / live
state / surface delta / detail — never inventing new contract prose mid-migration; (d) reconcile
suites that pin the edited prose in the same change (prompt-prose edits touch no parity
fixture — §8.31's Tier B is engine-vs-engine — but extension context/factory tests and binding
guards may pin strings).

**Scope.** The objective's migration nodes cover the named stage families; all other perk-owned
stage prose (e.g. the `skills` door family) is held to this rule as ordinary maintenance going
forward.
