# perk cross-plane contracts

The four language-neutral contracts both planes obey, authored once here and bundled into
each build artifact (`Q12`). These are **prose specs** (no parser): the Python CLI (`perk`)
and the TS extension (`@mgiles/perk`) each implement one side, against the exact names/paths/
fields pinned below. `perk doctor` (T6) verifies conformance.

There are now **three** parsed contracts (siblings of this file): `registry.yaml` — the stage
graph, whose `state_keys` block is the canonical vocabulary referenced throughout this
document — `bindings.yaml` — the skill-binding set (trigger→skill delivery), specified
in §8.9 — and `providers.yaml` — the provider-selection supported set, specified in §8.10.

Source decisions: `Q1` (workflow-state), `Q2` (layout + run_id), `Q3` (verified linkage),
`Q9`/`Q10` (gateway). Pi mechanics are cited against
[pi--best-practices.md](../docs/pi--best-practices.md).

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
├── plan.md                 # cache.plan: the materialized plan body (transient per-worktree mirror)
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

  **perk-owned dot-path construction seam.** Construction of the four **perk-owned** dot-path
  families — the perk dir, the config files (`config.toml`/`local.toml`), the repo-skills dir
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
  `plan_review` in an objective-author session reviews the **rendered markdown** —
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
  transient local copies and must never be tracked. `perk doctor --fix` untracks a legacy-committed
  copy and drops any stray ungrouped ignore line, and migrates a legacy `.pi/workflow/` cache
  forward (untracking a tracked `.gitkeep`, moving the `plan-ref.json`/`agent-session.json` mirrors
  when the target is absent; disposable scratch is left for the user to delete).
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
   error — never a silent `pass`);
3. record `run_id` in `perk:workflow-state` (§8.3);
4. mark the handoff **consumed**.

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
branch `run_id`, no `PERK_RUN_ID`: ad-hoc `pi`, `pi --plan`, spawned subagent children) **mints
its own ULID in the TS plane** (`extension/substrate/runId.ts`) on `session_start`, recording
`{run_id, pi_session_id}` via the strict append seam (§8.3) — **no predecessor, no handoff, no
disk artifacts**. A **failed cold claim never falls back to a mint** (`PERK_RUN_ID` set but the
handoff missing/mismatched stays a loud unclaimed error — minting would mask a launcher bug).
Under `PERK_SELFCHECK`, the T3 sentinel records a successful warm mint as `source: "mint"`.

The Pi session UUID is kept as a **secondary handle** (needed for `SessionManager.open` /
`continueRecent` on resume); the `run_id ↔ pi_session_id` mapping lives in `perk:workflow-state`.

---

## §8.3 · The `perk:workflow-state` schema (Q1)

The single namespaced session entry holding transient (tier-3) workflow state.

**Record (per-field last-write-wins):**

| field | type | meaning |
|---|---|---|
| `run_id` | string (ULID) | the perk run this session belongs to (§8.2) |
| `predecessor` | string \| null | the prior `run_id` this run forked from (or cold-relaunched after), §8.2; null for an original run |
| `pi_session_id` | string | the current session handle — the basename of Pi's session file; the **fork discriminator** (§8.2) and the key to resume via `SessionManager.open`/`continueRecent` |
| `mode` | string | the active registry stage `mode` (`read-only` / `read-write`) — **structurally gates tools** (P2.T1, see below) |
| `stage` | string | the registry stage id this run is acting on, recorded at cold **claim** from the handoff (P3.T2); lets the interior distinguish two read-only stages (e.g. `objective-author` vs `plan`) and inject the right authoring context |
| `active_plan_ref` | object \| null | the provider-agnostic plan ref (§8.4); null during early `plan` |
| `active_objective` | string \| null | the active objective id; **live since P2.T9** (`/objective <id>` sets it, `/objective clear` nulls it) |
| `last_review_batch` | object \| null | the last processed review batch (P2.T7): `{ pr, counts:{actionable,informational,praise,question}, resolved_thread_ids:[…], at:ISO }` |
| `session_artifacts` | object \| null | per-name session-artifact provenance pointers `{run_id, name, path, digest, at}` (Node 1.3, §8.1); appends carry the **whole merged map** (per-field LWW); strict-append tier |
| `objective_node_claim` | object \| null | the objective node this session has claimed `planning` (`{ objective, node }`, Node 2.3 of #339); written by the warm `objective_node` tool on a successful `planning` transition, cleared on a successful non-planning transition for the same node and after a successful node-linked plan save; best-effort tier (cheaply reconstructable; loud-but-non-fatal) |
| `conflict_resolution_attempts` | number | the bounded conflict-resolution re-drive counter (#556): incremented each time `/submit` drives the `perk.conflict-resolver` subagent on a definitively-unmergeable PR, reset to 0 on a clean submit; best-effort tier (cheaply reconstructable) |

**Persistence channel:** `pi.appendEntry("perk:workflow-state", data)`. (The *other* Pi
channel — tool-result `details` — is for state that *is* a tool's output; this is not that.)

**Rebuild (non-negotiable discipline, pi §4):** scan `ctx.sessionManager.getBranch()` for
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

**`active_plan_ref` reconciliation (T2b, stage-gated #43):** on `session_start`, after the
run_id claim, the extension reconciles `cache.plan-ref` into `active_plan_ref` — but **only
when the launched stage *consumes* the ref**, i.e. the stage's registry `requires`/`reads`
list `cache.plan-ref`. That is exactly the worktree binding stages
(`implement`/`submit`/`address`/`land`/`learn`); the root `worktree: none` stages
(`plan`/`objective-plan`/`save`) do **not** consume it, so a fresh planning session never
inherits the stale **root selector** (§8.1's duality). The launched stage is read from the
run's **handoff** blob (`stage`); only a settled run has one — `claim` (cold) reads it from
the claimed run, `keep` (reload) from the kept run, and `fork`/`none` carry **no launched
stage** (so they never re-read the file, relying on the LWW rebuild). When the stage does
consume the ref, the extension appends `active_plan_ref` **iff** the rebuilt value does not
already match the file — **idempotent by `(provider, pr_id)`** (so reloads don't duplicate
and a fork keeps the inherited ref), with a **strict read-back** (loud-but-non-fatal on
mismatch, headless-safe). When it does not consume the ref, an already-linked
`active_plan_ref` is still **preserved** via the LWW rebuild, but the file is never read.
`session_tree` re-reads nothing — the per-field LWW rebuild already restores
`active_plan_ref`, so branch navigation preserves it. The registry is the gate's source of
truth; if it fails to load, reconciliation stays **permissive** when a launched stage is
present (to preserve implement linkage). **No clearing** of the selector anywhere — gating
alone fixes the leak, and the Python plane is untouched.

**Warm `/plan-save` direct linkage (T3):** the in-session warm door appends `active_plan_ref`
**directly** after a successful save (same strict read-back, idempotent by `(provider, pr_id)`),
so the live session is linked without waiting for the next `session_start`. Both writers feed the
same LWW field; a warm append makes the next reload's reconciliation a no-op. This makes the warm
`save` stage a direct writer of `session.workflow-state`. The warm door also **surfaces the
objective node→plan link outcome** returned by `perk plan-save` (`objective_node`): a successful
advance shows `→ in_progress`, a failed one shows a visible `⚠ … NOT advanced — re-run /plan-save`
warning (§8.4 "The node↔plan link") — it is not silently swallowed. The warm door's decode of the
`perk plan-save --json` payload is strict **only** on `plan_ref` (the field appended to
workflow-state); the rendered issue id/url are derived from it (byte-identical by construction in
the cold door, which builds the ref from the issue), and `existed`/`objective_node` are advisory —
so a successful cold save can never be reported as a warm failure by render-only payload fields
(e.g. under CLI↔extension version skew, the #387/#390 incident).

**Approval→save orchestration seam (Node 2.3 of #339).** The exported `approvalSave` seam
(`extension/factories/planSave.ts`) is the shared APPROVED-review → save orchestration: artifact-first plan
resolution (`resolvePlanSource`) → `savePlan` → gate exit on success (the D1a pattern — snapshot
`gating.isActive()` before the save, `gating.exit` only on a successful save; a failed save leaves
the gate on). The `/plan-save` command is now the **manual failsafe** invocation of the same seam;
the `plan_review` door wires **two review backends** into it — plannotator's browser review
(Node 2.4) and the **first-party in-TUI editor review (Node 2.5)** — and those two backends cover
**every** selection (plannotator → the browser bridge; any other selection, tombell included, →
the first-party in-TUI review); all three authoring contexts (`PLAN_AUTHORING_CONTEXT`,
`PLAN_ADAPTER_PLANNOTATOR_CONTEXT`, `PLAN_ADAPTER_TOMBELL_CONTEXT`) now speak review-first, and
APPROVED outcomes run this seam. No resolvable plan source → a `no-plan` outcome, nothing saved, gate untouched
(fail-open; callers render their own fallback). **Warm node-link recovery:** when a save reaches
`savePlan` with **both** `objectiveId` and `nodeId` absent (an approval-triggered save carries no
model params), the link is recovered **both-or-neither** from the rebuilt `objective_node_claim`;
any explicit value (even one) wins outright — never mixed; a malformed/missing claim never blocks
the save. The cold handoff recovery (`perk plan-save` `_link_from_handoff`, #78) is unchanged
underneath — if both carriers exist the recovered values match, and Python's explicit-flags-win
ordering is preserved. A successful node-linked save clears the matching claim (best-effort).

**Plan-issue title (#129).** The warm door now **actually forwards** an explicit `title` to
`perk plan-save --title` (it was previously accepted by `savePlan` but silently dropped). When no
explicit `title` is given, it **best-effort generates one** via the session model
(`extension/factories/planTitle.ts` → `extension/substrate/structuredOutput.ts`, a reusable structured-output substrate
over `@earendil-works/pi-ai` tool-calling) and forwards that. Every failure mode (no model,
unresolved auth, a model error, no tool call, schema-invalid args, an empty sanitized title) and the
`PERK_NO_LLM` offline gate (set by the test harness, never by the production CLI) yield **no**
`--title`, so the cold door's deterministic `plan.derive_title` fallback takes over — a save is never
blocked. The cold door's `--title`/`derive_title` contract is unchanged.

State key (registry vocabulary): `session.workflow-state`.

**Objective budget + compaction (P2.T9).** With `active_objective` now live, the TS substrate
(`extension/factories/objective.ts`, `registerObjective`) adds three pieces, all **inert when no objective
is active** and **never throwing** (logged-not-thrown, like checkpoints):
- **`/objective [<id>|clear]`** — `<id>` appends `{ active_objective: <id> }` to
  `perk:workflow-state` (LWW field) **and** seeds a dedicated `perk:objective-budget` activation
  marker `{ objective_id, activated_at: <ISO> }`; `clear` appends `{ active_objective: null }`; no
  arg shows the current objective + budget line. The dedicated `perk:objective-budget` entry keeps
  high-churn budget data **off** the shared `perk:workflow-state` record (mirrors checkpoints'
  dedicated entry).
- **Budget accounting** — a stateless rebuild (the `goal.ts` pattern): scan the branch for
  `role === "assistant"` messages **after** the latest `perk:objective-budget` marker, summing
  `max(0, usage.input) + max(0, usage.output)`; elapsed = `now − activated_at`. Surfaced as the
  **objective segment of the single composed `perk` status slot** (segments ordered objective →
  checkpoints per charter D2, joined with two spaces, composed by `surfaces.ts createPerkStatus` —
  headless calls are full no-ops); the `perk-objective` **widget is retired** (node 2.3) — the
  status segment carries id + tokens + elapsed (`🎯 <id> · <tokens> tok · <elapsed>`). In TUI mode
  the segment renders inside the **perk-owned footer** (node 3.1, see the checkpoints block below);
  the composed `perk` status slot keeps publishing and is the RPC-visible surface. Rebuilt on
  `session_start`, `session_tree`, **and** `agent_end` (survives reload/branch/compaction for
  free). Pure helpers
  (`sumAssistantTokens` / `formatBudgetLine` / `findBudgetMarker` / `rebuildBudget`) are
  offline-tested.
- **Threshold-triggered compaction** (the `trigger-compact.ts` pattern) — on `turn_end`, **only
  when `active_objective != null`**, read `ctx.getContextUsage()` and call `ctx.compact({…})` when
  usage crosses a threshold (default `0.8`; overridable via `[objective] compact_threshold` in
  `.perk/config.toml`, read through `extension/substrate/config.ts` — written as a **quoted** value because the
  TOML subset reads only strings). The decision is the pure `shouldCompact(usage, threshold)`;
  compaction is best-effort (`onError` logs and continues). The custom cheaper-model
  `session_before_compact` summary is **deferred** — T9 ships the simpler `ctx.compact` trigger.

No model-facing bounded transition tools are added here — the `objective-plan` stage, the plan
factory, and the "fire only when…" tools are **T10**.

**Objective authoring loop (P3.T2).** Objective *creation* is now a first-class read-only → save
loop, the mirror of the `plan → save` spine. Two new registry stages precede `objective-plan` as
the new single initial: `objective-author -> objective-save -> objective-plan -> plan -> …`.
- **`perk objective-author`** (a dedicated seeded cold door, like `objective-plan`) opens a
  **read-only** authoring session, seeded with the objective-authoring guidance. Its handoff records
  `stage: objective-author`, claimed into `perk:workflow-state.stage`.
- **Coupling break (the `stage` field).** `extension/factories/planMode.ts` previously injected its
  plan-authoring context on *any* read-only gate. An `objective-author` session is **also**
  read-only, so plan mode now **defers** when `stage === "objective-author"`, and
  `extension/factories/objectiveAuthor.ts` injects its own `perk:objective-author-context` instead (keyed off
  read-only gate **AND** the stage; stripped from `context` when no longer authoring — the same
  hygiene plan mode applies). Exactly one authoring context is present. The injected
  objective-authoring context is optionally extended by the **same** `[workflow] plan_authoring`
  addendum the plan-authoring injection consumes (read per-event via `extension/substrate/config.ts`'s
  `loadPerkConfig`) — verbatim reuse, no new config key.
- **`objective_save` warm door** (`extension/factories/objectiveSave.ts`, the mirror of `planSave.ts`). The
  `objective_save` **tool** takes `prose` + a **structured `roadmap`** (a JSON array of nodes —
  never hand-written YAML) and delegates the write to `perk objective create --body <file> --roadmap
  <json> --run-id <rid> --json` (canonical mutation in Python, idempotent on the run_id). On success
  it links the live session: appends `active_objective` **and** seeds a fresh `perk:objective-budget`
  activation marker (mirrors `/objective <id>`), so budget tracking starts immediately; it
  **terminates** the turn. The `/objective-save` **command is the artifact-first manual
  failsafe** (#352 Node 2.3): it invokes the shared `objectiveApprovalSave` seam (re-read the
  structured `objective-draft.json` artifact → `saveObjective` → D1a gate exit on success) and
  relays the save message (`error` severity on a failed save — the gate stays read-only). Only
  when **no draft exists** does it fall back to the legacy drive-the-session behavior: exit the
  read-only gate (so the `objective_save` tool becomes reachable) and inject guidance via
  `pi.sendUserMessage` instructing the model to call `objective_save` with `prose` + the
  structured `roadmap` (mirrors `/address`, `/objective-plan`) — objectives have no transcript
  scrape by design (a roadmap is structured data, unscrapeable), so a draftless session still
  needs the driven save path. The tool is structurally unreachable while read-only and remains
  the post-gate-exit direct failsafe.
- **Structured roadmap (never hand-written YAML).** `create_objective_issue` gains an optional
  `roadmap_nodes`; `perk objective create` gains `--roadmap <json>` (parsed via
  `objective.parse_structured_roadmap`, where per-node `status` is optional and defaults to
  `pending`). When `--roadmap`/`roadmap_nodes` is given the body is pure prose; otherwise the legacy
  body-embedded roadmap parse still applies (the cold-CLI path). **Creation requires ≥1 roadmap
  node**: `perk objective create` rejects an empty roadmap with `error_type: empty_roadmap` (exit 1)
  and `create_objective_issue` raises `GitHubError` — the parse/read layer stays lenient (existing
  node-less issues remain readable/closable). The judgment layer lives in the `perk-objective-author`
  skill, which now speaks the review-first discipline (draft via `objective_draft` → `plan_review`
  → approval auto-save; `/objective-save` is the artifact-first failsafe) — #352 Node 3.2.

**Objective plan factory + transition tools (P2.T10).** The objective **transition** surface on top
of T9's mechanics (`extension/factories/objectivePlan.ts`, `registerObjectivePlan`):
- **`/objective-plan [<number>] [--node ID]`** — the warm entry: resolve the objective (arg, else
  `active_objective` from the rebuilt `perk:workflow-state`) and `pi.sendUserMessage(...)` the
  factory guidance to start the loop (mirrors `/address`). Headless-safe. On invocation it ALSO
  **enters the read-only gate** when it is off (skip-if-active: no duplicate `mode` append or
  announce when already read-only): appends `mode: "read-only"` to `perk:workflow-state` via
  `gating.enter` and reports a dedicated announce line — parity with the cold door's registry
  `mode: read-only` handoff claim. Gate **exit** remains owned by `plan_save` (D1a, approval
  auto-save included) / `/plan` off; the no-objective warning path never enters the gate.
  (Objective #352 Node 1.2.) As of #352 Node 3.1 the injected factory guidance (warm
  `factoryGuidance`; mirrored by the cold `_seed_prompt`, which adds handoff claim recovery and
  drops the mark step) instructs the **file-first loop**: the **unconditional** `planning` mark
  (the successful transition records the `objective_node_claim`), `plan_draft`/`plan_review`,
  the approval-driven save with both-or-neither link recovery from the claim, and
  `plan_save`-with-both-ids as the manual failsafe.
- **`objective_node` tool** — the BOUNDED model-facing transition. It **delegates** the mutation to
  the Python cold door (`perk objective node`, canonical mutations in Python) and **never throws**
  (soft `details.ok`, mirrors `resolve_review_threads`). Params `{ objective, node, status?, pr?,
  audit? }`; exec args are built **conditionally** (matching T9's optional `--status`/`--pr` —
  `--status ""` is a Click error, so it is omitted when no status change): a **`pr`-only backlink**
  (`pr` present, `status` absent) → `["objective","node",N,"--node",id,"--pr",pr,"--json"]` (no
  `--status`, no audit); a **status change** adds `["--status",status]` (and `--pr` only if also
  given). A call with **neither `status` nor `pr`** is refused (`bad_input`, no exec).
- **Completion-audit gate (model-path-only).** When `status === "done"` the tool requires a
  **non-trivial `audit`** and refuses otherwise (`audit_required`, **no exec**). Non-trivial **iff**
  `audit` is a string whose value **after `.trim()` is ≥ 40 characters**. This is a property of the
  **model-facing boundary**, NOT an invariant on the node-`done` state: the canonical cold CLI
  (`perk objective node --status done`, human/CI) has **no** audit gate, and **T11's auto-on-merge
  node-done deliberately sets `done` without an audit**. Both are intentional non-audited paths — the
  refusal protects the model's path only. The "are we done?" judgment text (prompt-to-artifact
  checklist; treat uncertainty as not-done) lives in the `perk-objective-plan` skill.
- **The node↔plan link.** plan→objective is carried by the plan header/ref `objective_id` (threaded
  through `perk plan-save --objective-id` + the `plan_save` tool's `objective_id` param). The
  objective→plan backlink (`node.pr`) **and** the `planning → in_progress` advance are now set
  **atomically by `plan-save`** when invoked with `--objective-id` + `--node-id` (warm `plan_save`
  tool params `objective_id` + `node_id`) — a single `update_objective_node(status=in_progress,
  pr="#<issue>")` write, **fail-open + non-fatal + idempotent on re-save** (the plan already exists
  so a link failure is non-fatal and surfaces `objective_node.error`; the same `run_id` re-links on
  a retried save). On a failed advance, the **warm `/plan-save` door surfaces the outcome to the
  user** — it appends a `⚠ objective node <id> NOT advanced — re-run /plan-save to retry` note to
  the save-result text (rendered by both the `plan_save` tool and the `/plan-save` command) and
  notifies at **`warning`** severity (mirrored to stderr in headless runs), not merely a Python
  stderr line. Re-running `/plan-save` with no further arguments retries the advance idempotently.
  The standalone `objective_node` `pr`-only shape remains for **manual
  repair** but is no longer part of the factory loop. T11's reconciliation-on-land consumes both
  directions.
- **Node lifecycle = a resumable lease (factory selection).** `planning` is a **resumable claim**
  (intent to plan; no saved plan yet — `objective-plan` re-selects it, an abandoned claim self-heals;
  the eager mark is idempotent). `in_progress` is a **committed plan** (saved, node→plan backlinked,
  awaiting land). `done` is set by the land path (`nodes_for_pr`) or the audited tool. Factory
  selection lives in `objective.DependencyGraph`: `plannable_nodes()` (membership: unblocked ∧
  (`pending`, or `planning` with **no** `pr`), position order — feeds the explicit `--node` lookup);
  a `planning` node **with** a `pr` and any `in_progress` node are `in_flight_nodes()`;
  `resumable_claims()` is the unblocked `planning`-with-no-`pr` subset (the "live or abandoned
  claim" set the surfaces report). `next_plannable()` — the single implicit-selection method (so
  `objective next`/`show` resume a claim; the `--json` field name stays `next_node`) — is
  **pending-first**: the first unblocked `pending` node by position, then the first resumable claim
  by position. Rationale: a claim cannot be distinguished from a session actively planning in
  another terminal, so implicit selection never steals/duplicates a possibly-live claim while safe
  pending work exists; self-healing of abandoned claims is preserved as the fallback (and via
  explicit `--node`). This makes **parallel `objective-plan` launches** on independent nodes the
  supported behavior: the first launch marks its node `planning` (removing it from the pending
  set), the second launch selects the next unblocked pending node. The cold door surfaces the
  skipped-claim set (a stderr `note:` line on non-JSON-payload paths + a `skipped_claims` array in
  the `--dry-run --json` payload), and `objective show --json` carries `resumable_claims` (full
  node dicts) for multi-terminal coordination.
  **Accepted backlink race:** concurrent `update_objective_node` writes (two parallel `plan_save`s,
  or a save racing a second door's `planning` mark) are read-modify-write on the issue body, so a
  simultaneous write can drop one node's update. Accepted, not fixed (erk shipped the same as a
  tripwire): the loser is recoverable — `/plan-save` re-save is idempotent and retries the link,
  and `perk objective node` is the manual repair. No optimistic-concurrency machinery.
  `classify_for_planning()` returns
  `plannable`/`in_flight`/`blocked`/`complete` and drives the cold door's honest errors
  (`objective_in_flight` is a new `error_type`, exit 1, in place of the old misleading "all blocked
  or complete"). `objective show --json` gains `selection_kind`.

**Objective reconciliation after landing (P2.T11).** When a PR linked to an objective node merges,
the roadmap reconciles against what actually landed — two seams matching the D9 Mechanical/
Reconcilable/Immutable typing:
- **Mechanical (on land).** The land path auto-marks the backlinked node(s) `done` — fail-open and
  non-audited (the audit gate is the model-tool boundary only). The warm `/land` then **auto-drives**
  the reconcile pass: it injects the same `reconcileGuidance` message `/objective-reconcile` injects
  (`deliverAs: "followUp"` from the terminating `land` tool, an immediate turn from the idle `/land`
  command) instead of printing a manual nudge.
- **Reconcilable (warm, post-merge).** `/objective-reconcile [<number>]` resolves the objective via
  a **three-tier** lookup — arg → `active_objective` → `readPlanRef(cwd).objective_id` (the
  just-landed objective sitting in the plan-ref, so the post-land path works even when the user
  never ran `/objective`) — then `pi.sendUserMessage(...)` the reconcile guidance (mirrors
  `/objective-plan`; headless-safe). The `reconcile_objective` tool (`{ objective, prose }`) writes
  the prose to a run-scoped scratch file and delegates to `perk objective reconcile … --body <path>`
  (never throws); it rewrites ONLY the marker-bounded Reconcilable prose region (the roadmap table +
  Immutable notes are structurally never touched). The `objective_node` tool gains a `description?`
  param (node scope/naming reconciliation) — `buildObjectiveNodeArgs` relaxes its structural refusal
  so a `description`-only call is valid; the `status:"done"` audit gate is unchanged. The judgment
  text lives in the `perk-objective-reconcile` skill.

**Session-lifecycle gates (T4b).** The interior guards `session_before_switch` /
`session_before_fork` with a **dirty-repo check** (`git status --porcelain` via `pi.exec`),
**scoped to active perk workflows** (`active_plan_ref != null` — perk never interferes with
non-perk forks/switches). A dirty tree in an active workflow returns `{ cancel: true }` with a
loud message (notify if UI, else stderr) — **fail-safe-headless** (it cancels in both modes; there
is no proceed-anyway in Phase 1). A clean tree, or any transition outside a workflow, is allowed
(returns `undefined`); if `git status` itself fails (e.g. not a repo) the gate allows (it is a
hygiene guard, not a repo validator). The warm `/implement` command
*enforces* `implement.doors.warm: false` for the **cross-worktree** transition: outside an impl
context it refuses and points to the cold door `perk implement`. The proceed-anyway confirm dialog
+ `git-checkpoint` stash-on-turn are Phase 2.

**Warm `/implement` in-worktree handoff (P2.T2b).** `implement.doors.warm` stays **`false`** — the
plan→implement *stage transition* is cold-only because **no extension-reachable session API can
change cwd** (the `ExtensionCommandContext` surface exposes `newSession`/`switchSession`, neither of
which takes a cwd; `cwdOverride` lives only on the lower `SessionManager.open`, out of reach
in-session — D2). What T2b adds is the in-process twin of the cold door usable **inside** an active
impl worktree (same cwd): when `/implement` runs in an impl context (read-write + a linked
`active_plan_ref`), it offers a lossless `ctx.newSession` fresh-context handoff seeded (via
`withSession` → `sendUserMessage`) with the plan-read priming (`implementHandoffPrompt`, the
in-session twin of `perk/run/launch/prompts.py`'s `_initial_prompt`: read the plan from its canonical source,
implement, `/submit` — carry the plan forward, never summarize it). Model-visible output is capped
(a single short confirmation; the durable state is the worktree's materialized plan-ref + the plan
issue). Dirty-tree hygiene is gated **manually** in the handler (a `newSession` session-replace may
bypass the `session_before_*` gate, so the handler re-checks `git status --porcelain` and refuses on
a dirty tree), fail-safe-headless. This is a **context refresh, not a stage transition** — the
registry's `implement.doors.warm: false` is unchanged.

**Checkpoints (P2.T2c).** Implementation progress is tracked in a **dedicated `perk:checkpoint`**
session entry (D3) — kept OFF the `perk:workflow-state` record because progress is high-churn (an
append every advancing `turn_end`), and a separate entry avoids LWW-append smell on the shared
record. The interior (`extension/checkpoints/checkpoints.ts`) seeds an ordered step list from the plan body's
`## Steps` numbered list (read from the `cache.plan` body cache) on `session_start` — **only** in an
active workflow (`active_plan_ref != null`), **only once** (a later session keeps the existing
entry). The `cache.plan` body (`.perk/workflow/plan.md`) is **materialized by the Python cold door**:
`perk implement` (`launch._materialize_plan_body`) fetches the plan body from GitHub
(`github.get_plan_body` → the `plan-body` block in the issue's first comment, parsed by
`plan.extract_plan_body`) and writes it into the worktree alongside the plan-ref + handoff
(best-effort + loud-but-non-fatal — an unreachable body just yields inert checkpoints, never a failed
launch). The cold door also **mirrors `repo_root/.agents/skills/*` into the worktree** as per-skill
symlinks (`launch.materialize_skills`): a linked worktree never carries the gitignored
`.agents/skills/` tree and pi discovers skills only up to the worktree's own git root, so without the
mirror a worktree session sees zero skills (ENOENT on `perk-implement/SKILL.md`). Best-effort +
loud-but-non-fatal (a missing source set warns; doctor's fail-level `skills-delivery` check owns the
hard gate); idempotent on resume (an already-correct symlink is left untouched, a real non-symlink
entry is never clobbered). **After** materialization (and only when the cold door **freshly
created** the worktree, never on idempotent reuse/dry-run), the cold door runs the project's
`[worktree] setup` commands (`launch.run_worktree_setup`) — an ordered array of shell command lines
read from `.perk/config.toml` (overlay-aware) — each via `bash -lc` with `cwd` = the worktree and
inherited stdio, **aborting the launch** (a `UserFacingCliError`) on any non-zero exit / timeout /
missing `bash` (a half-built environment is worse than a clear failure; the worktree is left for a
fixed re-run). This is **Python-plane-only** (no TS twin — the extension never creates worktrees);
the manual `perk worktree create` runs the same hook, and the remote runner's `position_worktree`
deliberately does **not** (CI environment setup belongs to the GHA composite action). It is
**opt-in + inert-by-default (D4)**: perk plans are prose, so when no `## Steps` list is
present the checkpoint degrades to inert (no entry, no crash); the `perk-plan` skill documents the
optional `## Steps` section as the forward path. Cross-plane contract: the **file** `cache.plan`
(`.perk/workflow/plan.md`), written by Python and read by TS. State is **rebuilt on `session_start`, `session_tree`, AND
`session_compact`** (the `session_compact` re-render — rebuild + render only, NO re-seed, mirroring
`session_tree` — was adapted from `@juicesharp/rpiv-todo`; its `catch` arm swallows the pi-core
stale-`ctx` compaction race silently — the proxy `/stale after session replacement/` error fired
when pi replaces the running session out from under the in-flight handler — while logging genuine
replay failures); `turn_end` scans the assistant message for `[DONE:n]` and, when a step advances,
appends a new `perk:checkpoint` marker carrying completion forward. The rebuild uses the
**scan-after-marker** discipline: the latest `perk:checkpoint` entry is the marker, and `[DONE:n]`/
`[WIP:n]` are re-folded only from assistant messages **after** it (stale markers from a previous
execution cannot resurrect a step). An **in-progress (`current`) step** is derived (not persisted):
the latest live `[WIP:n]` after the marker whose step exists and is incomplete, falling back to the
lowest incomplete step, else `null`; completion always wins (`▸` never renders on a completed step).
The `📋 done/total` (plus ` · ▸n` when current) text renders as the **checkpoints segment of the
single composed `perk` status slot** (ordered objective → checkpoints per charter D2, two-space
join, composed by `surfaces.ts createPerkStatus` — node 2.3 retired the per-feature
`perk-checkpoints`/`perk-objective` status slots). The widget keeps its own `perk-checkpoints`
slot and is a **themed component factory** (`(tui, theme) => { render, invalidate }`, stateless render per charter D10 — themed
lines are computed inside `render()` per call, never cached) placed **`belowEditor`** (D4); lines
are `✓/▸/○ <n>. <text>` colored per the charter §5 table (`success`/`accent`/`dim`) with
completed-step text muted, **windowed to ≤ 4 step lines** (D1: a sliding window anchored on the
current step sitting second when possible; `… +N earlier` / `… +N later` dim elision markers
render *in addition* to the step lines, ≤ 6 rendered lines worst case), and every line is
width-truncated via pi-tui's `truncateToWidth` (D9). `/checkpoints` notifies a **single line**
(D8): `done/total · ▸n <current step text>` (the ` · ▸n <text>` tail drops when no step is
current). **Accepted RPC caveat:** pi drops component-factory widgets in RPC mode (only string
arrays forward), so the checkpoints widget is invisible to RPC clients — the status (now arriving
under the composed slot `perk`) and `/checkpoints` remain the RPC-visible surfaces. **Footer
ownership (node 3.1, charter D2):** in TUI mode perk **owns the footer by default** via
`ctx.ui.setFooter` (`surfaces.ts perkFooter`/`installPerkFooter` — installed once per session on
`session_start`, headful only) — **unless** a foreign `[providers] footer` provider is selected, in
which case perk **vacates `installPerkFooter`** (install-site runtime vacating keyed off `ctx.cwd`,
fail-safe to install; see §8.10's footer interface-seam note) and the foreign footer is the sole
footer surface. perk's default-owned footer composes one line, in charter order, perk identity
(`perk v<version>`), the 🎯 objective segment, the 📋 checkpoints segment (left group), then git
branch, model, context usage (`<pct>%/<window>`, warning >70 / error >90), and guest extension
statuses (right-aligned), with the extended D9 drop order on overflow (guests → model → branch →
context → checkpoints; identity + objective never drop). The composed `perk` status slot
**remains published** (the `createPerkStatus` dual-publish is deliberate) and is the RPC-visible
surface — `setFooter` is an RPC no-op. The `v<version> loaded` startup notify is **retired**
(charter D7: identity is standing footer state, not a transition) — `session_start` no longer
emits a startup notify or its headless stderr mirror; the `PERK_SELFCHECK` `.perk-loaded` sentinel
is unchanged. D5 (branded working indicator) is **rescinded**: perk never calls
`setWorkingIndicator`. The **marker protocol is taught to the implement session**
via `_implement_prompt` (the launch prompt) + the **`perk-implement` skill**, so the implementer
knows to emit `[WIP:n]`/`[DONE:n]`. **Coarse fallback (P2.T15):** when no `## Steps` checklist exists
but a plan is active, the status bar shows `📋 <stage>` (the stage label from the handoff,
`readHandoff(cwd, run_id).stage`, falling back to `"active"`) with a single dim widget line (the
same themed-factory path, `belowEditor`) noting the plan is prose — so an active plan never goes
dark; with no active plan, the segment and widget clear. All surfaces are headless-safe (the
composed-status handle and `setStandingWidget` no-op without UI — headless never touches rich
UI); `/checkpoints` lists progress (notify when UI, else stderr). State key: a transient tier-3 session entry (not in the registry vocabulary, like
`perk:workflow-state`'s sibling execution/todo entries). `@juicesharp/rpiv-todo` **is** retired in
P2.T12 (removed from `init.py`'s `BORROWED_PACKAGES` and `.pi/settings.json`): perk now owns the
implement-progress overlay via this perk-owned `perk:checkpoint` seam. `@tombell/pi-status` is
likewise **retired** from `BORROWED_PACKAGES`: `ctx.ui.setFooter` is a single last-wins slot, and
pi-status's `session_start` footer install replaced perk's footer — a *borrowed* package must never
own the footer. (Distinct from a *selected* `footer` provider, which legitimately does: the footer
seam is the sanctioned way to hand the footer to a foreign package — perk vacates `installPerkFooter`
so there is no last-wins clobber. See §8.10's footer interface-seam note.) **`@tombell/pi-status` is
now ALSO a selectable footer provider** (`pi-status-footer`, #670): selecting it via `[providers]
footer` makes `perk init` converge `npm:@tombell/pi-status` into `packages` (object form) and perk
vacates `installPerkFooter` — the machine-governed way to get pi-status's footer, replacing the
unmanaged settings.json hand-edit. Unlike `powerline-footer`/`pi-bar-footer`, pi-status does **not**
render extension statuses, so perk's objective/checkpoints progress is **not shown** under it (an
accepted limitation, no status-bridge adapter). A sibling `pi-default` provider (`package: null`)
adds **no** footer package and vacates perk's install gate, leaving pi's stock built-in footer.

**Rejected `@juicesharp/rpiv-todo` ideas (deliberate non-adoptions).** A survey of rpiv-todo's
model-driven todo design against perk's passive, plan-derived, linear checkpoints (see
`docs/design/checkpoints-rpiv-todo-comparison.md`) adopted only the `session_compact` stale-`ctx`
robustness above. Rejected with rationale: (1) the **model-callable `todo` tool / `blockedBy`
dependency graph / dynamic create-update-delete** — reverses the P2.T2c charter that separates a
read-only plan from a linear, marker-driven, never-model-mutated checklist; (2) the **`activeForm`
present-continuous label** — there is no channel for the model to supply one (markers are
`[WIP:n]`/`[DONE:n]`) and the step *text* already serves as the in-progress label (`▸n <text>`);
adopting it would expand the marker grammar (a protocol change, not polish); (3) the
**completed-fall-away overlay** — `windowProgress` already does richer overflow handling (a sliding
window with `… +N earlier`/`… +N later` elision); rpiv's drop-after-next-turn is a different
philosophy, not clearly better for an ordered linear checklist.

**Generated checkpoint steps for prose plans (#342).** When the implement-session `session_start`
seeding finds a **materialized plan body with no usable `## Steps`** (`extractSteps` → `[]` covers
both a missing and a malformed section), checkpoints **generate** the step list on the fly via the
structured-output substrate (`extension/checkpoints/planSteps.ts`, the `planTitle.ts` idiom: a single
`set_plan_steps` tool call, TypeBox-validated, 2–12 steps sanitized to ≤200 chars each). Trigger
conditions (ALL required): the perk-checkpoints reference is the selected todo provider; no
existing `perk:checkpoint` entry (seed-once); an active workflow (`active_plan_ref != null`); a
non-null plan body whose `extractSteps` is empty; and the **launched stage is `implement`** (the
handoff's `stage` — address/learn/plan sessions never generate). **Artifact reuse first**: the
generated list persists as the session artifact `plan-steps.json`
(`{ plan_id, plan_body_digest, steps }`) written through the §8.1 session-data accessor with a
§8.3 provenance pointer, and is trusted only when the pointer validates AND its stored
`plan_body_digest` (the §8.1 `sha256:` convention over the current `plan.md` bytes) matches — a
replan/rematerialized body invalidates the cache and regenerates. On success the seed is
byte-identical to the explicit-`## Steps` path (same `perk:checkpoint` entry shape — no schema
change; rebuild/advance/render untouched); generated-ness is **recomputed, never stored**
(non-inert AND the current plan body parses to no explicit steps). A once-only
**`perk:steps-context`** hidden context message (injected at `before_agent_start`, dedup-guarded by
the branch already carrying the type; **no strip handler** — the checklist never goes stale within
the session) teaches the model the exact step numbers for `[WIP:n]`/`[DONE:n]`. `/checkpoints`
appends ` (generated)` when generated-ness recomputes true. **Fail-safe ladder**: the `PERK_NO_LLM`
offline gate, no model/auth, a model error, schema-invalid args, an unusable sanitized list, or a
missing session-data substrate each fall back to the coarse prose behavior (byte-identical widget
text) — never a failed session start. The plan issue is never mutated (generated steps are
cache-tier, session-local state).

**Surfaces discipline (Objective #251, node 4.1).** Every interior rich-UI call — `ctx.ui.notify`,
`setStatus`, `setWidget`, `setFooter`, `setWorkingMessage` — lives in the surfaces module
(`extension/surfaces/surfaces.ts` + `extension/surfaces/report.ts`); every other extension module
reaches the UI only through the seams (`report()`, `createPerkStatus`, `setStandingWidget`,
`installPerkFooter`, `setWorkingMessage`). `setWorkingIndicator` is never called anywhere (D5
rescinded); the distinct **`setWorkingMessage`** call (text-only label on pi's default spinner,
headless-no-op) **is** permitted (it was never declined) and is routed through the
`setWorkingMessage` surfaces seam — `whimsical` flavors the spinner label through it. **`ctx.ui.custom`
stays declined for all workflow surfaces** (charter §6 D6); the sole sanctioned exception is **`/btw`**,
a human-only side-chat popover that is `hasUI`-gated, exposes no model tool, and is not a stage/door —
so it is never machine-reachable and cannot threaten the machine-executability the decline protects.
Enforced by the source-scan guard `extension/surfacesGuard.test.ts` (node:test, runs in
`just test`/`just ci`).

**Tool-gating (P2.T1).** The `mode` field **structurally gates tools** — enforcement, not
prompting. When `mode == "read-only"` the interior (`extension/substrate/toolGating.ts`):
(1) restricts the active tool set to `READ_ONLY_TOOLS` (`read`/`grep`/`find`/`ls`/`bash` +
`ask_user_question` + `plan_review` + the **`web` seam** providers' research tools — the **union**
of all provider tool names: `web_search`/`code_search`/`fetch_content`/`get_search_content`
(`pi-web-access`, the default), `ollama_web_search`/`ollama_web_fetch` (`@ollama/pi-web-search`),
and `web_fetch` (`@juicesharp/rpiv-web-tools`); foreign tool names are inert
when their package is absent) via `pi.setActiveTools`, **snapshot-then-restore** (snapshot `pi.getActiveTools()` on the off→on
transition; restore it on on→off, falling back to the **full** configured tool set
`pi.getAllTools()` if no snapshot exists — never a hardcoded list, so perk's custom tools survive);
(2) blocks `edit`/`write`
and non-allowlisted `bash` commands at `tool_call` with `{ block: true, reason }` (a perk-owned
copy of plan-mode's destructive/safe regex tables; the bash allowlist additionally includes
read-only `gh` query subcommands — `gh issue|pr|repo|run|release|label view|list|diff|status|checks`,
`gh search …`, `gh auth status` — while `gh api` and all mutating `gh` subcommands stay blocked, plus
the command-keyed `agent-browser` / `npx agent-browser` entries (the browser-automation skill,
command-keyed like `ast-grep` — its own output flags can write files outside the gate, an accepted
leniency like `curl`/`fetch_content`); (3) injects a hidden `[READ-ONLY MODE]`
context at `before_agent_start` and **strips** that marker from `context` when off. The allowlist
is **restored on both `session_start` and `session_tree`** (re-sync from the rebuilt `mode`).
**Fail-closed:** the in-memory gate flag drives `tool_call`; a failed state-rebuild never opens the
gate (the sync is skipped), and `tool_call` blocks on any internal error. `mode` writes are
best-effort transient (no strict read-back). The `enter(ctx?)`/`exit(ctx?)` surface
(append `mode` + flip the gate) is the API the perk-owned plan mode (T2) and the read-only CI
executor (T5) consume; this primitive ships no `/plan` ownership and adds no registry stage.

**Perk-owned plan mode (P2.T2a).** `mode` is now perk-owned **end-to-end** — the borrowed
`@tombell/pi-plan` package is retired (removed from `init.py`'s `BORROWED_PACKAGES` and
`.pi/settings.json`). The interior (`extension/factories/planMode.ts`) owns the toggle surface over T1's gate:
a `/plan` command, a `Ctrl+Alt+P` shortcut, and a `--plan` flag all flip `gating.enter`/`exit`
(perk adds **no** parallel enforcement — T1 is the single read-only authority). It also injects a
hidden plan-authoring prompt layer under its own `perk:plan-context` customType (keyed off the
read-only gate; stripped from `context` when off — the same hygiene T1 applies to
`perk:mode-context`), optionally extended by a `[workflow] plan_authoring` addendum read from
`.perk/config.toml` + `local.toml` (`extension/substrate/config.ts`, the TS twin of `perk/substrate/config.py`'s
overlay). `isPlanModeActive` (in `extension/factories/planSave.ts`) now reads perk's own `mode == "read-only"`
(the P1.T3b `plan-mode-state` soft coupling is gone). The `plan_save` **tool** is structurally
unreachable while read-only (T1's allowlist excludes it), so there is no auto-exit on the tool path;
the `/plan-save` **command** *can* run while read-only and, on a successful save, calls
`gating.exit()` — save marks the read-only → read-write boundary in one gesture (D1a). perk does
**not** adopt plan-mode's in-session "execution mode" flip: it separates plan (read-only session)
from implement (cold-door fresh worktree session); `[DONE:n]` checkpoints live in the implement
session (T2c). The `plan` registry stage now records `writes: [session.workflow-state]` (the
`/plan` enter/exit `mode` append).

**Plan-provider deferral (Node 2.2).** `planMode` now *consumes* the resolved `[providers] plan`
selection: it reads `loadPerkConfig(ctx.cwd).providers` through `extension/substrate/providers.ts`'s
`resolveProviders` per-event (`resolvedPlanProviderId(cwd)` / `isPerkPlanReferenceSelected(cwd)`,
fail-safe to `perk-plan` on any load failure) and **steps its authoring surface aside** when the
resolved plan provider ≠ `perk-plan` — the `/plan` toggle announces the deferral headless-safe and
returns, `Ctrl+Alt+P` routes through the same `toggle`, `--plan` defers **silently** (no gate
entry), and the `perk:plan-context` injection is suppressed (a second defer condition alongside the
objective-author one). The `context`-strip is unchanged. `savePlan`/the `plan_save` tool/`/plan-save`
/the read-only gate are the **seam-shared substrate** the Node 2.3 adapter bridges to — they are
always-registered and never defer (only perk's own authoring surface does).

**Todo-provider deferral (Node 3.1).** `checkpoints` (perk's reference todo provider,
`perk-checkpoints`) now *consumes* the resolved `[providers] todo` selection — the todo-seam mirror
of the plan-seam deferral above. It reads `loadPerkConfig(ctx.cwd).providers` through
`extension/substrate/providers.ts`'s `resolveProviders` per-event (`resolvedTodoProviderId(cwd)` /
`isPerkCheckpointsReferenceSelected(cwd)`, fail-safe to `perk-checkpoints` on any load failure) and
**steps its progress surface aside** when the resolved todo provider ≠ `perk-checkpoints`: the
`session_start` / `session_tree` / `turn_end` handlers early-return **silently** (no seed, no
advance, no `setStatus`/`setWidget` render — the foreign provider owns the surface uncontested) and
`/checkpoints` **announces** the deferral headless-safe and returns. The pure checkpoint helpers, the
`perk:checkpoint` session entry, and the `## Steps` seeding are the seam-shared substrate (untouched).
Fail-safe to the reference: any config-read error → treated as `perk-checkpoints` → everything runs
exactly as today (the default path is the hard guarantee, zero behavior change).

**The `@juicesharp/rpiv-todo` adapter (Node 3.2).** `juicesharp-todo` is now a **real, selectable**
todo provider (no longer illustrative); the todo seam is **behavior-complete**. The perk-owned shim
`extension/adapters/todoAdapterJuicesharp.ts` (`registerTodoAdapterJuicesharp`, always registered, wired right
after `registerCheckpoints`) is an **injection-only** bridge, inert unless `[providers] todo =
"juicesharp-todo"` **and** the session is an active workflow (`active_plan_ref != null`). When both
hold it injects a hidden (`display:false`) `perk:todo-adapter-juicesharp` context that carries perk's
implement-progress **discipline** onto the foreign checklist overlay (seed from `## Steps`, mark each
item complete in order); a `context` handler strips the stale `[TODO ADAPTER: JUICESHARP]` marker
once deselected. Two seam asymmetries this node resolves, both deliberate deviations from the Node
3.1 forward-assumption that "registration-time vacating is the concrete adapter's concern":
  - **(a) NO registration-time vacating** for the todo seam. The plan seam needed it purely because
    perk and `@tombell/pi-plan` both register `/plan` (Pi suffixes duplicate command names). The todo
    seam has **no command-name collision** — perk registers `/checkpoints`, the foreign overlay
    registers its own differently-named command(s) — so Node 3.1's runtime deferral is already
    sufficient and the shim adds none.
  - **(b) The bridge is injection-only + active-workflow-gated** and does **NOT** write
    `perk:checkpoint` or revive the deferred marker scanner (Correction 2). Unlike `cache.plan-ref`
    (a durable cross-plane artifact downstream stages read, so a foreign plan *must* be bridged into
    it), `perk:checkpoint` is a transient TS-only overlay nothing downstream consumes and perk's
    render + scanner are already deferred — re-populating it would be dead duplication. The foreign
    overlay is the sole, uncontested progress surface.

  The shim **never** owns the read-only gate, **never** `setActiveTools`, and **never** restamps any
  provider field (the todo-provider id lives only in `[providers] todo`). Validation record:
  `docs/design/provider-smoke-juicesharp-todo.md`.

**In-process read-only child sessions (P2.T4).** The first context-isolation primitive: a
deterministic, fully-isolated read-only child spun at the SDK level (`extension/worker/readOnlySession.ts`,
interior/TS-only). This is the **shared handoff contract** both context-isolation primitives honor
(T4 in-process here; T6 the spawned shape later), so its shape is locked now and T6 conforms.

- **SDK read-only via `createReadOnlySession`.** The child's allowlist is
  `SDK_READ_ONLY_TOOLS = ["read", "grep", "find", "ls"]` — **no `bash`**, stricter than T1's
  in-session `READ_ONLY_TOOLS` (a separate constant, not a reuse). T5 composes its own allowlist
  when it needs a gated test-runner command.
- **Isolation = `DefaultResourceLoader` `no*` flags + the tools allowlist** — **not**
  `extensionFactories: []` (that is already the default and controls only inline factories; it does
  **not** stop `loader.reload()` from resolving the project's `.pi/settings.json` packages and
  loading perk's own extension into the child). The child loader sets
  `noExtensions/noSkills/noPromptTemplates/noThemes/noContextFiles`, so **no perk machinery loads
  into the child** and the path stays offline/deterministic. A custom loader is **reloaded by the
  caller** (`await loader.reload()` before `createAgentSession`); `agentDir` is a throwaway temp dir
  (a locked-down child loads nothing from it). The read-only guarantee is **structural** —
  provable offline via `getActiveToolNames()` with no `prompt()`.
- **The handoff contract (`runReadOnlyChild`).** Cap the **model-visible** output
  (`DEFAULT_MODEL_VISIBLE_CAP = 50 KiB`, UTF-8-byte-safe, overridable), keep the **full** result in
  a **verified** scratch file (`write → verify → pass-path`), and return **double-delivery**: compact
  `prose` for the human + a `structured` block for the orchestrator (which T5 places in a tool's
  forking-safe `details`). **Route-don't-relay** is enforced structurally — the raw output never
  enters the parent; only a path/summary does (`scratchPath`). **Fail loud + fail closed:** never
  throws to the parent — on any error (session-create/task throw, failed scratch-verify, or abort)
  it returns `{ success: false, scratchPath: null }` with the error in **both** `prose` and
  `structured.error`. Offline-testability is a hard requirement: the session-running step is behind
  an injectable `runTask` dependency so the cap/scratch/verify/double-delivery machinery is exercised
  with no model turn.
- **Substrate only.** No registry stage, no door change, no cross-CLI behavior. The consumer is the
  read-only CI executor (T5).

**Read-only CI executor (P2.T5).** The `run_ci` tool + `/ci` command run the project's `[ci]`
named checks **deterministically** (`pi.exec("bash", ["-lc", cmd])`, no LLM turn) and report
**double-delivery** (capped prose for the human + a forking-safe `CiReport` in `details`), reusing
T4's **cap/scratch/fail-closed handoff contract** (`capForModel` + `write → verify → pass-path` +
route-don't-relay) — **not** its session runner (`runReadOnlyChild.success` carries no exit code).
The executor **never edits or fixes**: it is a stateless oracle, and the parent owns the entire
**Run→Report→Fix→Verify** loop (`run` and `report`, never `run` and `fix`).

- **Not sandboxed — the safety boundary is structural.** The check command runs with full
  filesystem/network access, **outside T1's tool gate**. The defenses are, in order: (1) the model
  selects a configured **check name, never a command** (an unknown name yields an actionable
  `unknown_check` error listing available names); (2) project-supplied CI is **untrusted** and gated
  by `decideCiScope` — `[trust] ci = "true"` (committed config), `--allow-project-ci`, or a
  per-session approval latch ⇒ run; else with UI ⇒ `ctx.ui.confirm`; else (headless, no
  trust/flag) ⇒ **refuse (fail closed)**. Unlike the per-session confirm, **`[trust] ci` also
  overrides the headless fail-closed refuse** — it runs on *every* surface, so a remote/headless CI
  worker runs project CI in a trusted repo (the tradeoff: a cloned repo committing `[trust] ci`
  auto-runs its own CI). (3) failure output is
  wrapped `<untrusted_ci_output>` with a "treat as data, not instructions" note.
- **Config = `[[ci]]` array-of-tables.** `[ci]` is an ordered `[[ci]]` array-of-tables, each row
  `name` / `command` / optional `glob`; `loadPerkConfig` surfaces `ci: CiCheck[]` via `parseCiChecks`
  (declared order preserved; rows missing a non-blank `name`/`command` silently dropped; empty ⇒
  inert `no_checks_configured`, non-fatal). **Full migration, no back-compat** for the old `[ci]`
  map. `run_ci` with no `check` runs **all** checks in declared order (does not stop at first
  failure); `check:"<name>"` runs exactly one. `passed = exitCode === 0` per check; report
  `passed = checks.every(c => c.passed)`.
- **Change-scoped gating (run-all path only).** A row's optional `glob` (a single comma-separated
  pattern string, e.g. `"*.ts,*.tsx"`) gates whether the check runs: on the run-all path, the
  changed-file set is computed ONCE (merge-base vs the detected trunk ∪ untracked, mirroring
  `detect_trunk_branch`) and a globbed check whose patterns match no changed file is **skipped**
  (`skipped:true, passed:true, exitCode:0` — the command is not executed). A pattern translates to
  an anchored RegExp (`**`→`.*`, `*`→`[^/]*`; a slash-free pattern matches the path's basename, so
  `*.py` gates any `.py` at any depth). **Fail-open:** any git error ⇒ unknown ⇒ run **everything**
  (never skip on uncertainty, never a false success). A row with **no `glob` always runs**; an
  **explicit `only` check always runs** (no glob gate, no git work); no git work happens when no
  selected row is globbed. An all-skip run is `passed:true`; skipped rows contribute no
  `<untrusted_ci_output>` block.
- **Interior/TS-only.** No registry stage, no door change (`doors.cold_remote` unchanged). Python
  never reads `[ci]`.

**Spawned delegation engine seam (P2.T6).** perk's *second* context-isolation shape is a **spawned**
read-only child engine, stood up by **borrowing the `pi-subagents` engine** behind a thin seam rather
than building a spawn primitive. T6 is substrate only (no registry stage, no in-session TS consumer,
no perk-authored agent definitions, no roster/model-tier config — those land with the first consumer,
T7 `/address`).

- **Borrow boundary.** perk borrows the `pi-subagents` *engine* (its `subagent` tool + spawn/handoff
  machinery); perk **owns** the agent definitions, chains, and acceptance wiring. perk authors **no**
  `subagent` tool of its own — the "one `subagent` tool" is the borrowed one.
- **Defs location.** perk-owned agent definitions live in **`.pi/agents/`** (committed; scaffolded by
  `perk init` with a `.gitkeep`, *not* gitignored — perk owns and commits its defs). `pi-subagents`
  discovers them as project agents (`agentScope` default `both`).
- **Handoff reuse.** Spawned children honor the **same handoff contract as the P2.T4 amendment above**
  (cap-model-visible-output, full result in a verified scratch file, double-delivery of compact prose
  + a structured block, route-don't-relay, fail-closed) — the shared contract both context-isolation
  primitives honor (T4 in-process; T6 spawned).
- **Never-delegate boundaries** (`erk-subagent-usage.md`): judgment, user interaction, and
  durable-state writes stay with the parent; spawned children do bounded, ideally read-only,
  mechanical work.
- **Model tiering convention (locked, value deferred to T7).** perk agent defs set a **cheap model** in
  frontmatter for mechanical child work; the parent keeps the top-tier model.
- **Standing signal vs spike vs live smoke.** `perk doctor`'s `settings-wiring` (the `npm:pi-subagents`
  package entry) + `subagent-agents` (the `.pi/agents/` defs dir) own drift; the **informational**
  `subagent-engine` check is a constant pointer carrying the seam shape and never re-derives that
  drift. The **open-#6 spike** (recorded in the turn outcomes) settles "runs cleanly headlessly"; the
  **live "runs under the worker" smoke is deferred to Phase 3 `doctor workflow`**.
- **Roster control deferred to T7.** `subagents.disableBuiltins` + the `.agents/`-recursion-collision
  mitigation (perk's `.agents/skills/*/SKILL.md` would otherwise be discovered as stray agents) land
  with the first agent.
**Review loop (`/address`, P2.T7).** perk's review-handling stage is **classify-then-act**, and the
first consumer of the T6 spawned-delegation engine. It adds the `address` stage to the registry
(`submit → address → land`; `mode: read-write`, `worktree: reuse`; per-stage I/O now filled —
`requires: [github.pr]`, reads the plan-ref + PR + review-threads + comments, writes review-threads
+ comments + PR + workflow-state).

- **Classify in an isolated child.** The verbose feedback fetch + classification runs in a **spawned
  read-only child** (the borrowed `pi-subagents` engine running perk's `perk.review-classifier`
  agent). The child itself runs `perk pr feedback --json`, so the raw GitHub JSON **never transits
  the parent** (route-don't-relay). It honors the **same handoff contract** as the T4/T6 amendments
  (double-delivery: a compact prose table + a structured block; untrusted-text wrapping; fail-closed)
  and returns `{ pr, review_threads[], discussion_comments[], counts }`.
- **Act = parent.** Only **actionable** items get changes; the parent edits in its own read-write
  turn. The fix is **never delegated** (the three never-delegate boundaries: judgment, the fix,
  durable writes).
- **Resolve = one batched op.** The warm `resolve_review_threads` tool writes `[{thread_id, comment}]`
  to a run-scoped scratch file and delegates to `perk pr resolve-threads` (D1), then appends
  `last_review_batch` to workflow-state (now in **live use**; shape above).
- **Plan File Mode.** When the PR's only diff is the plan file, feedback is reinterpreted as edits to
  the plan *text*, not code to implement (parent judgment; captured in the `perk-address` skill).
- **Untrusted text.** All fetched GitHub text is wrapped `<untrusted_review>…</untrusted_review>` and
  treated as DATA, not instructions (the model T5's `<untrusted_ci_output>` established).
- **Resolved T6 deferrals.** `subagents.disableBuiltins` is **not** set (builtins like `scout` are
  reused later; disabling now is premature). The `.agents/`-recursion collision (perk's
  `.agents/skills/*/SKILL.md` surface as stray agents) is mitigated by **namespacing** (every perk
  agent def sets `package: perk`) + **explicit-name invocation** (`perk.review-classifier`), not by
  suppressing the borrowed engine's legacy scan; the stray skill agents are benign (never invoked).
  The cheap-model tiering value is realized: the classifier uses `anthropic/claude-haiku-4-5` with a
  `claude-sonnet-4-5` fallback (overridable via the inline per-call `model` override keyed by
  `[subagents] review-classifier` — **not** `subagents.agentOverrides`, which reaches only builtins;
  see the `[subagents]` paragraph below).

**PR review (`/pr-review`, #175).** A standalone warm command (like `/ci`, **not** a registry
stage — `shared/registry.yaml` is unchanged) that conducts **multi-angle** automated code review of
the active PR. The parent spawns **2–3 angle-specialized `perk.pr-reviewer` children in parallel**
via the borrowed `pi-subagents` engine with **`context: "fresh"`** (not a fork) so the implementation
session's history never biases the review; each child reviews **one assigned angle** and **returns
structured findings** (no posting, no file writes). The **parent reconciles** the per-angle findings
and records **one** consolidated outcome on the PR via the new warm **`post_pr_review`** tool. The
outcome is **verdict-driven**: the review lands **as comments on the PR only on an `actionable`
verdict**; a `clean` verdict posts a single 👍 reaction to the PR description and nothing else —
comments and `/address` are reserved for actionable feedback, and a clean verdict unambiguously
routes to `/land`.

- **Verdict-driven batch.** The review batch requires a `verdict` of exactly `"clean"` or
  `"actionable"` (a clean verdict with non-empty `comments` is a `bad_batch`). The optional
  `fyi: string[]` field carries borderline notes that are validated and echoed **in-session only**
  — it is structurally never part of any GitHub payload. The clean path's 👍 reaction
  (`add_pr_reaction`, the issues-reactions endpoint — idempotent on rerun) is a **hard error** on
  failure (mutations raise; no fallback ladder — nothing review-shaped is lost).

- **Follows the read-only-child convention (multi-angle classify-then-act, #658).** Like `/address`,
  the reviewer children are **read-only and report-only** — they classify their assigned angle and
  **return** findings; the **parent** reconciles and posts. The parent always spawns the **Plan
  fidelity & completeness** reviewer plus **1–2** of: **Correctness & regressions** (security/edge
  cases), **Tests & validation adequacy**, **Code quality, simplicity & docs/contracts accuracy** —
  chosen to fit the change (2–3 reviewers total), with the angle passed per-call in the spawn `task`
  (one parameterized agent, no new defs). Each child returns a fenced JSON block
  `{angle, verdict, findings:[{path,line,body}], fyi}` with inline findings **already anchored to
  diff lines**; the parent **unions + dedupes** across angles (same `path`+`line` → merge bodies),
  **derives the overall verdict** (`actionable` if **any** reviewer is actionable, else `clean`), and
  passes the findings straight into `post_pr_review`'s `comments[]` — the parent **never re-anchors**
  (the raw diff never enters the parent; each child runs its own `review-context`). D1 is still
  honored — the GitHub mutation stays canonical in the **Python gateway**: `post_pr_review` delegates
  to `perk pr review-post` (the existing cold door) via `runColdDoor` (stdin `--batch`). The review is
  **advisory `COMMENT` only** — `event` is hardcoded `COMMENT` in the gateway, so the parent can never
  approve/request-changes.
- **Configurable models via the agent-keyed `[subagents]` table (#196).** Every perk-owned project
  agent's model is configurable through one flat `[subagents]` table in `.perk/config.toml` (overlaid by
  `.perk/local.toml`), keyed by the bare agent name — `pr-reviewer`, `review-classifier`,
  `objective-explorer`, `conflict-resolver` (matching each def's `name:` frontmatter and the
  `perk.<name>` invocation).
  Each configured value is injected as a **per-call inline `model` override** on that agent's
  `subagent` spawn (the agent's frontmatter `model` stays the default when the key is unset). This
  is wired at the authored spawn sites: the warm TS doors (`prReviewGuidance`,
  `addressGuidance`, `factoryGuidance`, `conflictResolutionGuidance`), the cold Python prompts
  (`_address_prompt`, `_seed_prompt`), and the headless worker (`initialPromptFor`). The earlier
  `[pr-review] model` key is removed
  outright (clean break, no alias — perk `0.0.1` pre-release, init converges forward). Unknown/typo'd
  agent keys are silently ignored (mirrors `_parse_providers_selection`); no doctor validation.
  **Correction to the T7 note above:** `subagents.agentOverrides` does **not** reach project agents
  — `pi-subagents`' `applyBuiltinOverrides` applies overrides only to **builtin** agents — so the
  inline per-call override (not an override map) is the configuration mechanism for project agents
  like `perk.review-classifier` and `perk.pr-reviewer`.
- **Workflow-state record (`last_pr_review`, #658).** The `post_pr_review` parent tool turn appends
  a compact `last_pr_review` (`{pr, verdict, angles, comment_count, mode, at}`) to
  `perk:workflow-state`, best-effort / non-fatal (mirrors `resolve_review_threads`'s
  `last_review_batch`). The PR comment stays the canonical record; this is the in-session twin
  (the earlier deferral is delivered).
- **Still a warm command, not a `DriveStage`.** `/pr-review` remains human-invoked — the registry is
  unchanged and `DriveStage = implement | address` (the headless worker drives only those two). But
  the new `post_pr_review` tool turn + `last_pr_review` append make it **structurally symmetric with
  `address`** (an ok tool result + an appended workflow-state field is exactly the terminal signal
  the worker's `applyEvent`/`evaluateTerminal` latches onto), so a future promotion to a
  headless-drivable stage is a clean follow-up (deferred — not built here).
- **Agent-def delivery.** perk's agent **sources** live at top-level `agents/<name>.md` (no leading
  dot, so pi never discovers them in the source tree) and are bundled into the wheel as `perk/_agents`
  (hatchling `force-include`) + the sdist `only-include`. `perk init` materializes them into the
  consumer-owned **`.pi/agents/perk/`** subdir as a **committed managed convergence** (the
  `subagent-agents` capability): each `<name>.md` is written byte-for-byte from its source, strays
  inside `perk/` are pruned, and drift is `doctor --fix`-repaired. The agent frontmatter (`name`,
  `package: perk`, …) is unchanged, so the runtime names stay `perk.*` and the spawn sites need no
  edits. perk owns ONLY the `.pi/agents/perk/` subdir — **custom user agents** live at
  `.pi/agents/<name>.md` (top-level or any non-`perk/` subdir), set their model/tools in frontmatter,
  and are invoked via pi's native `subagent` tool (the fixed-key `[subagents]` table configures only
  perk's own agents). Linked worktrees inherit the delivered defs via git checkout (no worktree
  mirror).

**Conflict resolution (`/submit`, #556).** After `/submit` opens the draft PR, the Python
`perk pr submit` cold door probes the PR's mergeability against the base branch with a deterministic
local `git merge-tree` probe and surfaces `base` / `mergeable` (bool \| null) / `conflicts[]` in its
`--json` (see §8.4). When the probe is a definitive `mergeable: false` with conflicts, the warm
`submit` door (shared by the `/submit` command and the headless worker — both route through the same
`submit` tool) drives the perk-owned **`perk.conflict-resolver`** agent via the borrowed
`pi-subagents` engine with **`context: "fresh"`** (not a fork). Unlike the read-only
classifier/reviewer, the conflict-resolver is **write-capable** and **inherits project context +
skills** (resolving conflicts correctly requires understanding the code and running the repo's
checks); like the reviewer it **fetches its own plan + PR context** read-only via
`perk pr review-context` (the verbatim `plan_body` + `diff` are what let it resolve *correctly*, not
merely cleanly), then rebases onto `base_ref`, resolves every conflict, verifies, and force-pushes —
the parent then re-runs `/submit` to confirm. The re-drive is **bounded** by
`CONFLICT_RESOLUTION_ATTEMPT_CAP = 2` via the `conflict_resolution_attempts` workflow-state field
(§8.3; reset to 0 on a clean submit); past the cap the unresolved conflict is surfaced loudly
instead of looping. The probe is **fail-open**: an undetermined probe (`mergeable: null`) never
blocks submit. Configurable model via `[subagents] conflict-resolver`.

- **Filing note (deferral).** This §8.3 cluster (T1/T2a/T2b/T2c/T4/T5/T6/T7) has outgrown "the
  workflow-state schema"; promoting the context-isolation/handoff paragraphs (T4/T5/T6) into a
  dedicated "context-isolation" section is a **deferred** doc refactor — T6 files as a sibling here to
  preserve cohesion now.

---

## §8.4 · The GitHub gateway contract (Q9/Q10)

**One contract, implemented once per plane** (no shared module, no in-process coupling):
a `gh`-shelling gateway in the Python CLI (`init`/worker) and a `gh`-shelling gateway in the
TS extension (in-session mutations). Both conform to the **same operation names + payload
shapes**, so either can later swap `gh`-shell → API-backed independently, and `doctor` can
verify both.

### Verification-only operations (Phase 0 — authored now, **no mutation**)

These are all `init`/`doctor` needs in Phase 0 (`Q9`: verification-only; the first label is
created lazily by `/plan-save` in Phase 1). **Implemented in the Python plane (T5):**
`perk/github/` (typed dataclasses mirroring these shapes); the TS plane follows in Phase 1.

```
check_auth()         -> { ok: bool, user: string|null, scopes: string[], error: string|null }
                        # `gh auth status` (+ `gh api user`); never mutates.
check_repo_access()  -> { ok: bool, repo: string|null, can_push: bool, error: string|null }
                        # `gh repo view`; can_push from viewerPermission ∈ {WRITE,MAINTAIN,ADMIN}.
```

`require_github(ctx)` is the **strict DI binding** for Phase-1+ commands (raises
`UserFacingCliError` / `error_type: github_unauthed` when unauthed); `init`/`doctor` call the
`check_*` ops directly to *report* (non-fatal — see §8.5).

### Mutation operations

**Authored (P1.T2a — the plan write).** REST `gh api`; mutations **raise** on failure (the
command boundary maps to `UserFacingCliError`), lookups return `… | null`:

```
create_label{ name, color, description }            -> Label{ name, created }
    # POST repos/{o}/{r}/labels; HTTP 422 ⇒ created:false (idempotent)
create_plan_issue{ title, body, labels[], run_id }  -> PlanIssue{ number, url, existed }
    # POST repos/{o}/{r}/issues (-F body=@file); idempotent on run_id
add_issue_comment{ issue, body }                    -> CommentResult{ posted }
    # POST repos/{o}/{r}/issues/{n}/comments (the plan-body first comment)
find_plan_issue{ run_id }                           -> PlanIssue | null
    # GET repos/{o}/{r}/issues?labels=perk:plan&state=open + header run_id match
```

- **Idempotency** is keyed on the header `run_id`, discovered via the **list** endpoint (not
  the eventually-consistent search index), create-then-return (`Q3` establish-before-record).
- **`perk:plan` label** is created lazily on first save.
- **`perk plan-save` is an upsert keyed on `run_id` (P2.T13).** The *first* save with a `run_id`
  creates the issue and posts the `plan-body` comment; a *re-save* with the same `run_id` updates
  the existing issue **in place** instead of no-opping — `create_plan_issue` still dedups (never a
  second issue per `run_id`), then `update_plan_issue{ number, title, body_comment }` PATCHes the
  `plan-body` comment with the revised markdown and PATCHes the issue **title** from the (possibly
  revised) plan H1. The comment is found by marker (REST comment list → first body containing the
  `plan-body` block; perk stores no comment id), which also repairs legacy plan issues; a missing
  comment falls back to a fresh POST so the body is never stranded. The anti-duplicate guarantee is
  preserved. Because `update_plan_issue` rewrites only the `plan-body` comment + the title (never
  the `plan-header`), a re-save **additionally** merges the planning header fields (`objective_id`,
  `consumed_learn`) back into the existing `plan-header` via `update_plan_header` when provided —
  additive, so an omitted field is left intact (no clobber of a previously linked objective/learn
  set, no reset of the submit-populated `branch`/`pr`/`lifecycle_stage`). This keeps the canonical
  header (the source `reconstruct_plan_ref` and the on-land `consumed_learn` consume read from)
  current on every save, not just the first create; the header write is fail-loud (a failure raises
  `GitHubError` → `github_error`, since this is the canonical save). `--json` carries a top-level
  `updated` (true on re-save, false on fresh create);
  `cached` stays true on every real save. The warm `/plan-save` surfaces `details.updated` and an
  "Updated plan #N" message on the re-save path.

```
update_plan_issue{ number, title, body_comment }    -> PlanUpdate{ number, body_updated, title_updated, dry_run }
    # find the plan-body comment by marker -> PATCH .../issues/comments/{id} (-F body=@file)
    #   (fallback: POST a fresh comment, body_updated:false) ; PATCH .../issues/{n} (-f title=)
```

**Authored (P1.T5a — the submit path).** REST `gh api`; idempotent via the list endpoint:

```
default_branch()                                    -> string
    # gh repo view --json defaultBranchRef (the PR base)
find_pr_for_branch{ branch }                        -> PullRequest | null
    # GET .../pulls?head=<owner>:<branch>&state=all (prefers an open PR)
create_pr{ head, base, title, body, draft }         -> PullRequest{ number, url, is_draft, state, existed }
    # POST .../pulls (-F body=@file); idempotent on head (find-then-create)
update_plan_header{ issue, fields }                 -> PlanHeaderUpdate{ fields_updated[], dry_run }
    # GET issue body -> merge fields into the plan-header block -> PATCH .../issues/{n}
    # rejects unknown header keys (LBYL on the schema); submit sets branch/pr/lifecycle_stage=impl
prepend_plan_callout{ issue, callout, command }     -> bool (#664)
    # GET issue body -> plan.prepend_callout(body, callout, command=) -> PATCH .../issues/{n}
    # idempotent on `command`; True iff a write occurred (False when already present / dry-run)
get_plan{ number }                                  -> PlanState{ number, url, title, header, pr, state } | null
    # gh issue view --json (+ pulls/{n} when the header carries pr); the `perk resume` read (T5c).
    # `state` is the issue's OPEN/CLOSED state (the `replan` OPEN guard reads it).
```

- **`perk replan <plan>` re-authors an OPEN plan *in place*.** A **dedicated cold door** (not a
  registry stage): it borrows the `plan` stage descriptor (`mode: read-only`, `worktree: none`) and
  re-launches it with `run_id_override` = the target plan's **original `run_id`** (a deliberate,
  documented exception to the registry's "cold mints" `run_id` policy — the override re-enters an
  existing plan's run). Because the warm `plan_save` is an upsert keyed on `run_id` (above), the
  re-save **updates the same plan issue in place** rather than creating a new one — preserving the
  `plan-header` and thus the plan→objective link (`objective_id`) and the node→plan backlink. The
  cold door performs every GitHub read up front (read-only `gh` query subcommands are
  allowlisted, but the cold door still materializes every GitHub read up front — deterministic
  and token-cheap) and
  materializes the prior plan body into a `<untrusted_plan>` scratch file the session reads. It
  **refuses** a non-OPEN plan (`plan_not_open` — a closed plan would silently create a new issue),
  a missing plan (`plan_not_found`), a header without `run_id` (`no_run_id`), or an empty body
  (`no_plan_body`). **No extension change is required** (the interior sees an ordinary read-only
  `plan`-stage session). **Single-plan only** — erk's multi-plan consolidation (`erk-consolidated`)
  is deliberately deferred.

- **PR body (P1.T5a, minimal):** `Closes #<issue>` (so the squash-merge closes the plan) + a
  `Plan: #<issue>` link + a **plain-text** `` `gh pr checkout <n>` `` footer (no HTML — erk's
  tripwire). Full-plan re-embedding + AI body craft are Phase 2.

**Authored (P1.T5b — the land path).** Idempotent; the caller checks PR state before merging:

```
mark_pr_ready{ number }                             -> void
    # gh pr ready <n> — the ONE non-REST op (draft->ready is GraphQL-only); called only on a draft
merge_pr{ number, commit_message? }                 -> PullRequest (state MERGED)
    # PUT .../pulls/{n}/merge (merge_method=squash); idempotent ("already merged" ⇒ success)
```

- **`Closes #<issue>`** rides in the PR body (T5a) so the squash-merge closes the plan issue;
  `commit_message` repeats it belt-and-suspenders. Post-merge state is **derived from PR**, never
  stored (Q8).

**Authored (P2.T8b — deep `/land` + `/learn`).** Land deepens the squash commit message; learn
graduates from a thin marker-clear into a real knowledge-capture pass:

```
find_learn_issue{ run_id }                          -> PlanIssue | null
    # GET .../issues?labels=perk:learn&state=open + learn-header run_id match. LABEL-SCOPED to
    # perk:learn (+ the learn-header block) so it CANNOT return the plan issue, which shares the
    # plan's run_id under the warm:keep learn stage. Implemented by parameterizing find_plan_issue
    # with label/header_key (the perk:plan/plan-header defaults preserved — no caller changes).
create_learn_issue{ title, body, run_id, plan_number } -> PlanIssue{ number, url, existed }
    # lazy create_label("perk:learn"); idempotent via find_learn_issue (NOT find_plan_issue);
    # renders a learn-header block { run_id, created, plan } into the body so the finder matches.
```

**Authored (hop-2 — the learned-docs consumer).** The factory cold door gathers + lands the
consume; both ops follow the established conventions (REST `gh api`, LIST endpoint, lazy label,
mutations raise / lookups never mask infra failure):

```
list_learn_issues{}                                 -> LearnIssueSummary[]{ number, title, url, body }
    # GET .../issues?labels=perk:learn&state=open (the find_plan_issue list call, label-scoped to
    # perk:learn). Returns every open learn issue's full body for the inbox; raises on infra
    # failure (never masks as empty); skips non-dict / pull_request entries.
close_and_label_consolidated{ issue }               -> bool
    # lazy create_label("perk:consolidated"); POST .../issues/{n}/labels (-f labels[]=perk:consolidated,
    # ADD not replace) THEN PATCH .../issues/{n} (-f state=closed). Idempotent (re-closing /
    # re-labelling is success). Raises GitHubError on infra failure.
```

- **Deepened squash commit message (D8).** Land now passes `merge_pr(commit_message=)` =
  plain `"<plan title>\n\nCloses #<issue>"` (`get_plan(...).title`, fallback `Closes #<issue>` on an
  empty title). Plain text only — the second of the **two PR targets** (the GitHub HTML body, T8a,
  is the other); HTML never leaks into `git log`.
- **`/learn` (D10).** The `learn capture` worker (`perk learn capture --json --body <file>`) reads
  the agent-captured learnings markdown from a run-scoped scratch file (the stdin-less worker
  pattern), `create_learn_issue`, posts a back-link comment on the plan issue (best-effort), and
  clears `pending-learn`. The warm `/learn` (`extension/doors/learn.ts`) takes an optional `summary`:
  present → scratch + delegate + mirror the marker-clear; absent → the thin TS-only marker-clear
  (graceful — no empty issue). `learn` now reads `[cache.markers, cache.plan-ref]` and writes
  `[cache.markers, github.learn, github.comments]` (the `github.learn` vocabulary key is new).
  The warm door's `learn_issue` decode is **lenient** (render-only field): a `success: true`
  envelope yields the captured-ok terminating result and mirrors the marker-clear even when the
  sub-object is undecodable (e.g. under CLI↔extension version skew); the generic decode-null
  `bad_output` message across doors now names probable version skew while keeping the
  `unexpected payload` substring.

  **P2.T17 — learn is now ACTIVE (primed launch + guided warm door).** The capture mechanism above
  is unchanged; what's added is the *driver*. The `learn` cold launch is **primed** (`launch/prompts.py`
  `_learn_prompt`): the session opens already investigating the landed change (read the plan +
  derive the merged PR from the `plan-<pr_id>` head branch) and is told to call the `learn` tool
  with synthesized learnings. The warm **bare `/learn`** (interactive) **injects `perk-learn`
  guidance** via `pi.sendUserMessage` instead of silently clearing the marker (the agent clears it
  by calling the `learn` tool); **`/learn skip`** preserves the pure marker-clear and **`/learn
  <text>`** still captures verbatim; **headless** bare `/learn` stays the safe marker-clear
  (can't drive a turn). The **`perk-learn` skill** is the judgment layer both surfaces point at.
  No new gateway op — the existing `learn` tool / `learn capture` worker remain the durable-write
  path. **Tier 3 update (hop-2):** the **`docs/learned/*.md` documentation-plan loop is now BUILT**
  (see the *Learned-docs consumer (hop-2)* subsection below). The remaining Tier-3 pieces
  (session-material bundling on land, multi-agent session/diff/docs analysis) stay **deferred** —
  perk's already-synthesized `perk:learn` records are the materials, replacing erk's session
  preprocessing.
- **Reconciliation typing (D9 — vocabulary established; Reconcilable + objective reconciliation
  implemented in P2.T11).** Three section types on land: **Mechanical** (command-updated,
  deterministic — T8b: `pending-learn` + the plain squash commit message; **P2.T11a**: the
  auto-on-merge node-done); **Reconcilable** (LLM-updated post-merge — **implemented in P2.T11**,
  see the P2.T11 subsection below); **Immutable** (never touched). The merged state is **PR-derived
  and not stored** (Q8), so land authors no new stored field. Objective-node reconciliation is
  **implemented in P2.T11** (the auto-on-merge node-done + the warm `/objective-reconcile` pass).

**Authored (P2.T7 — the `/address` review loop).** Review threads + their resolution are
**GraphQL-only** (REST has no `isResolved`, no `resolveReviewThread`/`addPullRequestReviewThreadReply`);
discussion comments stay REST. The GraphQL shapes are verbatim from erk (the durable prior art). The
read **raises** on infra failure; the resolve captures **per-item** failures into its result (one bad
thread does not sink the batch) but still raises on a hard infra failure (gh missing / timeout):

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
    # The warm TS twin writes the batch to a run-scoped scratch file (pi.exec has no stdin) and
    # delegates via `perk pr resolve-threads --json --batch <path>`.
```

- **Batch shape (PRIOR_ART §5/§11):** `[{ thread_id, comment }]` (objects, not a flat list).

**Authored (#175 — the `/pr-review` automated-review door).** The read gathers everything the
fresh-context `perk.pr-reviewer` child needs to review the active PR; the mutation submits the
child's review back. `event` is **hardcoded `COMMENT`** (the agent can never approve/block).
Resilience: if the inline-anchored review submission fails (e.g. a `line` not present in the diff),
`post_pr_review` falls back to posting the summary (+ rendered findings) as a single discussion
comment, so a review **always** lands on the PR:

```
get_pr_review_context{ pr_number, branch, plan_body } -> PrReviewContext{ pr_number, base_ref, head_ref, title, body, diff, plan_body }
    # Read-only. PR meta via `gh api pulls/{n}`, diff via `gh pr diff {n}`. The gateway no longer
    # reads plan/issue state: `plan_body` is resolved backend-neutrally by the consumer
    # (`perk pr review-context`) — the materialized `cache.plan` mirror first, else
    # `IssueBackend.get_plan_body` via the resolver (GitHub numeric ids AND Linear `ENG-123`) —
    # and passed straight in (best-effort; null lets the review run from the diff). What the
    # spawned child runs (Objective #746 Node 2.2 hoist: the gateway is pure PR/CI/auth/review).
post_pr_review{ pr_number, summary, comments:[{path,line,body}] } -> ReviewPostResult{ ok, mode, pr_number, comment_count }
    # ONE review via POST .../pulls/{n}/reviews with event=COMMENT (hardcoded) + inline comments[]
    # (path, line, side=RIGHT). mode ∈ {"review" (inline-anchored), "comment_fallback" (discussion
    # comment when the review submission fails)}. The warm twin is `/pr-review`'s parent-side
    # `post_pr_review` tool (#658), which delegates via `perk pr review-post --json --batch <path>`
    # (the reviewer children no longer call it directly — they report findings to the parent).
```

**Authored (P2.T8a — PR-body craft + the deliberate review gate).** The submit body is composed
in `perk pr submit` via **create-then-update** (the checkout footer needs the PR number, unknown
until `create_pr` returns), which also fixes a latent correctness bug (the Phase-1 footer carried
the **issue** number, not the PR's — erk's single most common agent mistake):

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
    # …checkout 123). This is the self-check that catches the issue-numbered-footer bug.
```

- **The two-target split (D4).** The HTML-enhanced body — a best-effort `<details>` embed of the
  verbatim plan (via `get_plan_body`; `None` → no embed, no raise) + the checkout footer — goes
  **only** into the GitHub PR body (`update_pr_body`). The squash **commit message** is the OTHER
  target: plain text, set at land (T8b) so HTML never leaks into `git log`.
- **Mergeability probe (#556).** **After** the PR is created + the body validated, `perk pr submit`
  runs a deterministic **local** `git merge-tree --write-tree origin/<base> <branch>` probe (no
  GitHub round-trip, no reliance on GitHub's eventually-consistent `mergeable` field) and surfaces
  three new `--json` fields: `base` (the target branch), `mergeable` (`true` clean / `false`
  conflicts present / `null` undetermined), and `conflicts[]` (the conflicted paths). The probe is
  **fail-open**: a best-effort `git fetch origin <base>`, an unresolvable base, or any `merge-tree`
  exit other than 0/1 (e.g. old git lacking `--write-tree`) yields `mergeable: null` and never
  changes submit's exit code — the gate (the warm-door conflict-resolver drive, §8.3) fires only on
  a **definitive** `mergeable: false`. `--dry-run` stays fully offline (`base: ""`, `mergeable:
  null`, no probe). The submit still **succeeds mechanically** (exit 0) when conflicts are present —
  mergeability is reported separately, not an op failure.
- **`pr check` (D5).** `perk pr submit` runs `validate_pr_body` as a **post-write self-check** and
  **raises** (`error_type: pr_check_failed`) on failure. A thin `perk pr check --json` (active
  plan-ref → find PR → `get_pr_body` → `validate_pr_body`) is the supervisor surface (exit 0 valid /
  1 invalid·op-failure / 2 not-a-repo).
- **Draft → ready is a deliberate gesture (D6).** Submit keeps the PR **draft**; perk does **not**
  auto-publish (unlike erk's `finalize_pr`). The new `perk pr ready` (warm `/ready`, `extension/
  ready.ts`) is the explicit review gate — `mark_pr_ready` if draft, idempotent. Land's
  mark-ready-if-draft stays a safety net. **Correction:** perk plans are GitHub *issues*, not repo
  files, so erk's plan-file-diff completion heuristic does **not** map — the explicit draft→ready
  transition is the gate, and no plan-file-diff detector is built (never infer completion from PR
  open/closed state alone).
- **Re-submit on rewritten history (P2.T8a follow-up).** `perk pr submit` **force-pushes the
  perk-owned plan branch with `--force-with-lease`** (auto-force; a no-op on the first push). Plan
  branches (`plan-<n>`) are single-author and expected to diverge after amend/squash/rebase, so a
  plain push would be rejected non-fast-forward on every re-submit after a history rewrite. The
  lease still rejects an *unexpected* origin move (teammate safety) — no `git fetch` is needed
  because only this worktree pushes this branch. Two stable error surfaces front this:
  - **`error_type: dirty_tree`** — submit refuses on a dirty worktree (commit-first guard, fired
    before the push) because uncommitted work isn't pushed and would silently fail to update the PR.
  - **`error_type: push_rejected`** — a non-fast-forward / lease failure maps to an actionable
    "remote moved unexpectedly; fetch/rebase and re-submit" message instead of raw git stderr
    (`error_type: git_error` remains the fallback for other git failures).
  - **Phase-2 caveat:** a fresh-clone resume (remote branch with no local remote-tracking ref) may
    hit a `stale info` lease failure and need a targeted `git fetch origin <branch>` before the
    lease; deferred with remote-branch resume (Phase 2).

### Plan-ref payload (provider-agnostic; full schema → Phase 1)

`active_plan_ref` / `cache.plan-ref` is **provider-agnostic** from day one (PRIOR_ART §2 —
erk migrated away from GitHub-specific refs and issue-numbers-in-branch-names):

```
{ provider: string,            # the resolved issue backend ("github" today — §8.21)
  pr_id: string,               # STRING (allows non-numeric ids like Jira "PROJ-123")
  url: string,                 # during planning: the plan issue url/id; branch/pr staged null
  labels: string[],            # ["perk:plan"]
  objective_id: string|null,   # Phase 2
  consumed_learn: string[],    # hop-2: perk:learn issue ids a docs plan consolidates (closed on
                               # land) — opaque strings (§8.21; Node 4.1)
  base: string|null }          # #633: the pinned PR merge target / worktree start-point branch;
                               # null ⇒ fall back to the GitHub default branch
```

**Plan-header block (P1.T2a — the queryable metadata in the issue *body*).** The minimal
observably-distinct set; rendered as a `perk:metadata-block:plan-header` collapsible YAML
block; the full plan markdown lives in the `plan-body` first comment:

```
{ run_id: string,              # the §8.2 run that created the plan (idempotency key)
  lifecycle_stage: string,     # "planned" (Q8: collapses planned→impl; post-states from PR)
  branch: string|null,         # staged — populated at submit
  pr: string|null,             # staged — populated at submit
  created: string,             # ISO-8601 UTC
  objective_id: string|null,   # Phase 2
  consumed_learn: string[],    # hop-2: perk:learn issue ids (opaque strings — §8.21; Node 4.1)
  base: string|null }          # #633: the pinned PR merge target / worktree start-point branch;
                               # null ⇒ fall back to the GitHub default branch
```

**The copyable command callout (#664).** A freshly-created plan issue's **body/description** (which
otherwise holds only the hidden `plan-header` block) now **leads with a visible, copyable command
callout** — a bold label, a bare fenced ` ```perk impl <id>``` ` block (GitHub/Linear render a
one-click copy button), and an italic hint. It is injected on the **fresh standalone-create** path
of `plan save` (in `_plan_save_impl`, via the new `IssueBackend.prepend_plan_callout`) with the
**server-assigned** id (`issue.id`), since that id is only known post-create. `<id>` is the
artifact's own ref id (GitHub number, Linear `ENG-N`, or — for project-backed objectives — the raw
project UUID), all already accepted by `parse_plan_id`/`parse_objective_id`. The callout is pure
portable Markdown (no HTML/`<details>`/perk sentinels), so `to_linear_markdown` passes it through
unchanged. It is **idempotent** (keyed on the literal command string — no duplicate on re-save) and
sits **structurally above** the `plan-header` block, so `extract_run_id`/header parsing and the
submit-time `update_plan_header` rewrite (which touches only the header block) are unaffected.
Forward-only: artifacts created before #664 are not retro-fitted. For the Linear **project node↔plan
unified** plan the same `perk impl <ENG-N>` callout is folded into the node-issue description by
`save_node_plan` (no extra write).

**The pinned base (`base`, #633).** A plan or objective can declare a **non-default target
branch**. `perk plan save` resolves the effective base **once** — the linked objective's own
`base` (the `objective-header` `base`, the source of truth for its node plans) → the repo's
`[workflow] base` config → `None` — and pins it into BOTH the `plan-header.base` and the
`cache.plan-ref.base`. Three consumers read it: `create_pr` (the PR merge target), the worktree
start-point (`launch.resolve_base` bases the `plan-<id>` branch off `origin/<base>` instead of the
detected trunk), and the `/submit` merge-conflict probe. The submit base-resolution chain is
`cache.plan-ref.base` → `plan-header.base` → `default_branch()`; when `base` is absent everywhere
the behavior is byte-identical to pre-#633 (fall back to the GitHub default / `detect_trunk_branch`).
The explicit `implement`/`run-worker` `--base` flag (a one-off git start-point override for
stacking) still wins the start-point verbatim. `reconstruct_plan_ref` carries `base` from the
`plan-header` so `implement`/`resume`/the remote `run-worker` recover the pinned value when the
local `cache.plan-ref` is absent.

**Label taxonomy (minimal, PRIOR_ART §2/§6):** `perk:plan` (green `1f883d`), `perk:learn` (purple
`8250df`), `perk:objective` (indigo `5319e7`, description "perk objective issue", since P2.T9),
`perk:objective-node` (indigo `5319e7`, on Linear project-backed roadmap node-issues; #669), and
— since hop-2 — `perk:consolidated` (gray `6e7781`, description "perk learn issue consolidated into
docs/learned"), each **lazily created** by its gateway create-op on first use (perk never seeds
labels in `init`). Query by a **single** label — GitHub label filters are AND-semantics. (On
Linear, `perk init` / `doctor --fix` proactively ensure the five `perk:*` labels at **workspace**
scope — §8.21.)

**The `pending-learn` semaphore (P1.T5b; Q2/Q5).** An existence-only `cache.markers` file
(`.perk/workflow/markers/pending-learn`, name shared as `PENDING_LEARN` in both planes): **`land`
sets it** (after a successful merge), **`learn` clears it**. While present it signals the
land→learn cycle is open and the worktree is not yet releasable (a future `worktree remove` /
`doctor` honors it). `learn` is **thin and TS-only** this phase — it clears the marker; the
agentic capture + a `perk:learn` label/issue is Phase 2.

### Authored (P2.T9 — objective storage + mechanics)

> **Forward pointer (Objective #548).** The objective methods described here as living on
> `IssueBackend` have since been **extracted into the objective-storage tier** (`ObjectiveStore`,
> §8.24) — the issue tier and the objective tier are now distinct seams sharing the `[issues]`
> selection. The objective substrate ops listed below are unchanged: they remain
> `GitHubObjectiveStore`'s delegation target (the equivalence lock) and now live in the GitHub
> backend package at `perk/backends/github/objectives.py` (moved out of the `perk/github/` forge
> gateway in Objective #746, Node 2.2). The historical record below is left intact per the
> keep-and-annotate discipline.

The **objective layer's deterministic foundation** — a long-running goal that *generates* bounded
plans (PRIOR_ART §3). The pure mechanics live in the `perk/objective/` package (the `plan.py` twin,
reusing its block engine); the GitHub writes live in `perk/backends/github/objectives.py`; the cold-door workers are the
`perk objective` group. **No registry stage and no model-facing tools** — those are T10.

**Storage blocks (perk-namespaced, schema 1).** An objective is an issue + first comment:
- `objective-header` (issue body) — compact, queryable: `{ run_id, created,
  objective_comment_id, status, base }` (`status` is the explicit objective-level rollup, e.g.
  `"active"`; `objective_comment_id` is backfilled in the two-step create; `base` (#633) is the
  objective's target branch, inherited by every node plan, `null` when unset).
- `objective-roadmap` (issue body) — the **canonical** flat-node YAML frontmatter:
  `{ schema_version: "1", nodes: [ { id, slug, description, status, pr, depends_on?, comment? } ] }`.
  Phase membership is derived from the **ID prefix** (`"1.2" → phase 1`, `"2A.1" → phase 2A`); phase
  *names* are not stored (extracted from `### Phase N: name` headers when rendering). `depends_on`
  is `null`/absent (infer sequential deps) vs `[]` (explicitly none). The `depends_on`/`comment`
  columns are omitted from the serialization unless some node specifies them.
- `objective-body` (first comment) — the human-readable rendered roadmap table (marker-bounded by
  `<!-- perk:roadmap-table -->`, deterministically re-rendered from the frontmatter) + prose.

**The copyable command callout (#664).** An objective's human-readable surface — the `objective-body`
comment (issue-backed) / the project **overview** (Linear project-backed) — now **leads with a
visible, copyable ` ```perk objective plan <id>``` ` callout** (bold label + fenced block + italic
hint), the objective sibling of the plan callout. For an issue-backed objective the callout is folded
into the `objective-body` comment at compose time (the `created.number`/`created.id` is known before
the comment is posted — **no extra write**); for a Linear project-backed objective it is written into
the overview with one post-create `update_project_content` (the project UUID is only known after
`create_project`). It is idempotent (keyed on the command string), pure portable Markdown, and sits
**above** every metadata/marker block, so the table re-render and the §8.4 reconcile splice (which
work strictly between markers) preserve it.

**Explicit-status-only (foundation open #3).** A node's `status` is **never inferred from a PR
column** — `update_node` takes `status` verbatim or preserves it; setting `pr` never changes
`status`. This is the deliberate departure from erk's two-tier infer-from-PR model.

**Gateway ops (canonical Python plane; same idempotency + two-step pattern as plan/learn):**
- `find_objective_issue(*, run_id, repo_root) -> ObjectiveIssue | None` — label-scoped to
  `perk:objective` + the `objective-header` block (delegates to the parameterized `find_plan_issue`).
- `create_objective_issue(*, title, body, repo_root, run_id, status="active", base=None,
  dry_run=False) -> ObjectiveIssue` — the **two-step** create (`base` (#633) persists into the
  `objective-header`): idempotency check → lazy `perk:objective` label →
  compose body (`objective-header` with `objective_comment_id: null` + `objective-roadmap`) → POST
  issue → POST `objective-body` comment (capturing its id) → **backfill** `objective_comment_id`
  into the header.
- `get_objective(*, number, repo_root) -> ObjectiveState | None` — parse header + roadmap nodes;
  `None` if absent, raises on infra failure / invalid roadmap.
- `update_objective_node(*, number, node_id, status=None, pr=None, description=None, repo_root,
  dry_run=False) -> ObjectiveNodeUpdate` — re-render the authoritative `objective-roadmap` block in
  the issue body **and** the rendered table in the `objective-body` comment (best-effort); raises if
  the node is not found.
- `add_objective_node(*, number, phase, description, status=PENDING, slug=None, depends_on=None,
  comment=None, repo_root, dry_run=False) -> ObjectiveNodeAdd` — insert a new node into `phase`
  (auto-assigned `<phase>.<n>`, appended after that phase's last node) with the same re-render
  discipline; raises on an id collision. The rare node-insertion surface for reconciliation
  (prose-guarded, no audit gate — like the other workers).
- `update_objective_header(*, number, fields, repo_root, dry_run=False) -> ObjectiveHeaderUpdate` —
  the `update_plan_header` twin (read-merge-PATCH), rejecting unknown keys (LBYL on
  `OBJECTIVE_HEADER_FIELDS`).

**Cold-door workers (`perk objective …` — a dev/CI/T10 surface, not an agent affordance):**
`create --body @FILE [--title]`, `show NUMBER`, `node NUMBER --node ID [--status][--pr][--description]`,
`node-add NUMBER --phase N --description STR [--status][--slug][--depends-on …][--comment]`,
`next NUMBER` (the dependency-graph `build_graph(nodes).next_plannable()` selection T10's
`/objective-plan` consumes). All supervisor surfaces (`--json` → stdout, human → stderr, exit
`0`/`1`/`2`). The objective issues are pure REST (issues + comments), no GraphQL.

State key (registry vocabulary): `github.objective` (live since P2.T9 storage; its **stage** —
`objective-plan` — exists since P2.T10).

### Authored (P2.T10 — the objective plan factory)

The objective **transition** layer on top of T9's mechanics — the plan factory + the node↔plan link.

- **`objective-plan` registry stage + cold door.** A new stage (`mode: read-only`, `worktree:
  none`, `doors.cold_remote: false`) inserted as the **single initial** before `plan`
  (`objective-plan → plan`); `requires/reads: [github.objective]`, `writes: [github.objective,
  session.workflow-state]`. Its cold door is a **dedicated** command (`DEDICATED_STAGES`),
  `perk objective-plan [NUMBER] [--node ID]` (the generic launcher cannot select a node): it
  requires an explicit NUMBER (a cold session has no `active_objective`), selects the next actionable
  node (pending-first dependency-graph order — unblocked `pending` nodes by position, then resumable
  `planning`-no-`pr` claims; or `--node`), marks it `planning` (`update_objective_node`), and launches
  a read-only
  plan-mode session seeded with the node (via `launch_stage(prompt_override=…)`). Supervisor surface
  (`--json`/exits `0`/`1`/`2`); error types `objective_required`/`objective_not_found`/
  `no_actionable_node`/`remote_blocked`.
- **`launch_stage(prompt_override=…)`.** A minimal seam: when given, the override is the seeded
  initial prompt instead of the stage-derived `_initial_prompt` (objective-plan has no plan-ref, so
  `_initial_prompt` returns `None`). All existing callers pass `None`, unaffected.
- **`--objective-id` thread.** `perk plan-save --objective-id N` (and the warm `plan_save` tool's
  `objective_id` param) populate `plan.PlanHeader.objective_id` + `plan.PlanRef.objective_id` (both
  fields already existed). This persists the plan→objective direction; non-objective plans omit it.
- **Node mutations stay canonical Python.** The `objective_node` model tool delegates to
  `perk objective node` — there is **no audit gate at the CLI layer** (the audit refusal is the
  model-facing tool boundary only, §8.3). Whole-objective rollup-to-`done` (`update_objective_header`
  via a CLI) is **deferred** (T10's completion-audit unit is the node); auto-on-merge node-done is
  **T11**.

### Authored (P2.T11 — objective reconciliation after landing)

Close the objective loop: when a PR linked to an objective node merges, the roadmap reconciles
against what was *actually* built. Two seams (PRIOR_ART §3), matching the D9 section-boundary typing:

**T11a — Mechanical (deterministic, on land).** The cold land path (`perk pr land`) auto-marks the
objective node(s) backlinked to the just-merged plan `done` — **fail-open** (the merge already
succeeded; objective tracking must never block landing) and **deliberately non-audited** (per the
T10 §8.3 note, the audit gate protects the model-facing tool path only).
- `objective.nodes_for_pr(nodes, pr_number) -> [ObjectiveNode]` (pure) — returns nodes whose `pr`
  backlink matches `pr_number` canonicalized to `"#<n>"` (`"#6"` / `6` / `"6"` interchangeably).
- `pr_land_cmd._reconcile_objective_on_land(*, plan_ref, repo_root) -> ObjectiveLandUpdate`
  (`{ objective, nodes_marked, skipped_reason, closed }`) — best-effort, **never raises**: it parses
  `plan_ref.objective_id` (`skipped_reason` ∈ `no_objective_link` / `bad_objective_id` /
  `objective_not_found` / `no_linked_node`, or `error: <exc>` on any failure, logged loud-but-non-fatal
  to stderr), then `update_objective_node(... status=DONE)` for each non-terminal matched node. Called
  in `_pr_land_impl`'s **non-dry-run** branch only, **after** `set_marker(PENDING_LEARN)`; the
  dry-run branch sets an inert `ObjectiveLandUpdate(None, (), "dry_run")` and stays fully offline.
  `_result_to_dict` always emits `"objective": { id, nodes_marked, skipped_reason, closed }`
  (`id` an opaque string objective id — §8.21; Node 4.1);
  `_render_human` adds an `objective #N: marked node(s) X done` line when non-empty (and an
  `objective #N complete — closed` line when `closed`).
- **Close-on-complete.** After the marking loop (targets non-empty only — the early-return skips
  above never reach it), the land path checks completeness **locally** over the post-mark node
  list (every backlinked target counts as terminal, all other nodes as fetched — the same
  all-terminal predicate as `DependencyGraph.is_complete`, no re-fetch, no graph construction).
  When complete it calls `github.close_issue(number=...)` — idempotent REST PATCH, **no closing
  comment** (symmetric with the §8.20 supervisor close) — and sets `closed=True`. The check runs
  even when zero nodes were marked (all targets already terminal), so a **re-land is idempotent**:
  re-landing the final PR still converges the objective to closed. The close is wrapped in its own
  **isolated fail-open** handler: a close failure preserves the already-marked `nodes_marked`,
  logs loud-but-non-fatal to stderr, and reports `skipped_reason = "close_failed: <exc>"` with
  `closed=False` — the land result is never affected.
- The warm `extension/doors/land.ts` surfaces `objective.nodes_marked` and **auto-drives** the reconcile
  pass via `driveReconcileAfterLand`, which injects
  `reconcileGuidance(...) + bindingSuffix(..., "command:objective-reconcile")` — byte-for-byte the
  message `/objective-reconcile` injects — when the land succeeded with a node marked done.
  Delivery branches on `ctx.isIdle()`: the streaming `land` tool path uses
  `deliverAs: "followUp"` (delivered after the terminating batch), the idle `/land` command path an
  immediate turn. `land` stays **terminating** because `terminate` only skips the *automatic*
  follow-up LLM call — an injected `followUp` user message is a separate deliberate new turn, so the
  two compose. The success text reports the auto-reconciliation rather than a copy-pasteable nudge;
  the merge itself is unchanged. `land.ts` decodes `objective.closed` **leniently** (missing or
  non-boolean → `false`, sub-object kept — advisory display detail) and adds an
  `Objective #N complete — closed.` success line when `closed`; `driveReconcileAfterLand` is
  unchanged — the reconcile pass still auto-drives after a closing land (a closed issue's
  body/comments remain editable).
- The `land` stage I/O gains `github.objective` in both `reads` (the node lookup) and `writes` (the
  mechanical node-done).

**T11b — Reconcilable (LLM judgment, post-merge, warm).** A `/objective-reconcile` surface +
`perk-objective-reconcile` skill drive the model to reconcile stale objective **prose** (and node
descriptions) against the real diff. The objective-body prose is a marker-bounded **Reconcilable**
region; everything outside it (the Mechanical roadmap table, any Immutable notes below) is
**structurally** protected.
- `objective.OBJECTIVE_RECONCILABLE_MARKER_START/_END` + `replace_reconcilable_section(comment_body,
  new_prose) -> str | None` (pure; splices between the markers, preserving the table block above +
  Immutable notes below; `None` when markers absent). `render_body_comment(nodes, *, prose="")` now
  wraps prose in the Reconcilable markers — even empty prose emits the (empty) marker pair so every
  objective has a splice target; objectives created before P2.T11 (no markers) yield a clean
  `reconcile_target_missing` rather than a clobber.
- `github.update_objective_body(*, number, prose, repo_root, dry_run=False) -> ObjectiveBodyUpdate`
  (`{ number, comment_id, updated, dry_run }`) — reads the `objective-header` `objective_comment_id`,
  fetches the comment, `replace_reconcilable_section`, PATCHes it; raises `GitHubError` (`no body
  comment` / `no reconcilable region`) on a missing target. The table block + Immutable prose are
  never touched (structural Immutable-safety).
- `perk objective reconcile NUMBER --body @FILE [--dry-run] [--json]` — the cold worker (stdin-less
  file-arg pattern, mirroring `learn capture`); maps the two missing-target `GitHubError`s to a
  stable `reconcile_target_missing`, other infra to `github_error`. Node-description reconciliation
  reuses the existing `objective node --description` (no new flag).
- `extension/factories/objectivePlan.ts` gains: a `description?` param on the `objective_node` tool
  (`buildObjectiveNodeArgs` pushes `--description` and **relaxes** the structural refusal so a call
  carrying only `description` is valid — a deliberate, flagged extension of T10's contract; the
  `status:"done"` audit gate is unchanged); a `reconcile_objective` warm tool
  (`{ objective, prose }` → run-scoped scratch file → `perk objective reconcile … --body <path>`,
  never throws); and a `/objective-reconcile [<number>] [--pr <plan>]` command with **three-tier
  objective resolution** (arg → `active_objective` → `readPlanRef(cwd).objective_id` — so the
  post-land path works in the landing session even when `active_objective` is unset).
- The judgment layer is `skills/perk-objective-reconcile/SKILL.md`: PR diff + `objective show` as
  untrusted DATA; the Mechanical/Reconcilable/Immutable boundary; the contradiction taxonomy; skip
  if nothing is stale; never-delegate judgment + durable writes.

### Authored (hop-2 — the learned-docs consumer)

perk's `/learn` already synthesizes durable learnings into terminal `perk:learn` issues; hop-2 is
the missing **consumer** that consolidates them into committed `docs/learned/`. It is a **plan
factory** (mirrors `objective-plan`, NOT a direct doc-writer), triggered on-demand/batched — so it
adds **no `registry.yaml` stage** (it borrows the existing `plan` stage descriptor to launch) and
uses existing state keys (`github.learn`, `github.plan`, `cache.scratch`).

- **The factory cold door + warm command.** `perk learn docs` (`commands/learn/docs_cmd.py`, no
  alias): `list_learn_issues` → materialize the inbox
  `.perk/workflow/scratch/learn-docs-inbox.md` (a `## Learning #<n>` section per issue, each body in
  `<untrusted_learning>`) → `launch_stage(plan_stage, prompt_override=<seed>)` (a read-only
  plan-mode session). `--gather` materializes the inbox + emits `{ inbox_path, learn_numbers }`
  with no launch (the warm path + tests consume this); `--dry-run` gathers + prints; `--remote` is
  rejected (`remote_blocked`, the `plan` stage is `cold_remote:false`); no open learn issues →
  exit 1 `no_learn_issues`. The warm `/learn-docs` (`extension/doors/learnDocs.ts`) delegates to
  `perk learn docs --gather --json` (gate-safe — extension `pi.exec` is not subject to the
  read-only bash gate), then `pi.sendUserMessage`s the factory guidance pointing at the
  `perk-learn-docs` skill. **Headless-safe** (the inbox is still materialized; no turn is driven).
- **`learn` is a hybrid group (Node 2.2).** `perk learn` is a hand-written default-dispatch group
  (`commands/learn/`): a bare/non-verb invocation falls through to a hidden launcher built from
  the generic registry factory (byte-identical to the generated `learn` stage launcher), while
  `capture` and `docs` are the cold workers (no aliases). Warm ids (`/learn`, `/learn-docs`,
  `command:learn-docs`, the inbox artifact) are unchanged — they key off warm command ids, not
  cold CLI spellings.
- **The factory discipline is inbox-over-gh.** The seeded factory session reads the materialized
  inbox via the `read` tool as its canonical input. Read-only `gh` query subcommands are now
  allowlisted in the read-only bash gate (`extension/substrate/toolGating.ts`), so ad-hoc GitHub reads are
  *possible* — but the cold door remains the canonical gatherer (deterministic, token-cheap), and
  factory sessions should not re-fetch the inbox's contents via `gh`.
- **The `consumed_learn` thread.** `perk plan-save --consumed-learn "45,50"` (and the warm
  `plan_save` tool's `consumed_learn` array param) populate `plan.PlanHeader.consumed_learn` +
  `plan.PlanRef.consumed_learn` (parsed to a sorted unique `tuple[str, ...]` of opaque string ids
  — §8.21; only empty tokens are dropped — there is no int parse). The warm param decode
  (`idArrayParam`) accepts strings and coerces bare numbers via `String()` (the learn-docs
  guidance renders bare numeric ids on GitHub). This persists which `perk:learn` issues the docs
  plan consolidates; non-factory
  plans omit it. Because the read-only factory saves via the `/plan-save` *command* (which forwards
  only `{plan, title}`), `plan-save` also recovers `consumed_learn` from the run's handoff
  (`_consumed_learn_from_handoff`, #102) when the flag is absent — see §8.2's handoff-carrier note.
- **On-land consume (Mechanical, deterministic).** `pr_land_cmd._consume_learn_on_land(*, plan_ref,
  repo_root) -> LearnConsumeUpdate{ closed, skipped_reason }` reads `plan_ref.consumed_learn` and
  `close_and_label_consolidated` for each issue — **fail-open, never raises, never changes the land
  result** (mirrors `_reconcile_objective_on_land`). Each issue is closed **independently** (#102
  per-issue isolation): one bad issue (already-deleted / transient infra error) is logged
  loud-but-non-fatal and rolled into a `failed: #a, #b` `skipped_reason` while the rest still close.
  `skipped_reason` ∈ `no_consumed_learn` / `bad_consumed_learn` / `failed: …` / `error: <exc>`.
  Called in `_pr_land_impl`'s non-dry-run branch after `set_marker(PENDING_LEARN)` and the objective
  reconcile; the dry-run branch sets an inert `LearnConsumeUpdate((), "dry_run")`. `_result_to_dict`
  emits `"learn": { closed, skipped_reason }`; `_render_human` adds a `consolidated learn issue(s) X
  into docs/learned` line when non-empty, plus a `⚠ learn consume incomplete: <reason>` line for any
  non-benign skip (everything except `no_consumed_learn`/`dry_run`). The warm `extension/doors/land.ts`
  surfaces `learn.closed` in a `Closed N learn issue(s) … into docs/learned` line and a
  `Warning: learn consume incomplete — <reason>` line for the same non-benign skips. Closing already excludes a consumed issue from the next `state=open` gather;
  the `perk:consolidated` label is the durable/queryable record.
- **The docs surface (plan-maintained, never `init`-managed).** `docs/learned/<category>/*.md`
  carries light frontmatter (`title` + `read_when`); `docs/learned/index.md` is the standalone full
  catalog; `.pi/APPEND_SYSTEM.md` (Pi's project-scoped system-prompt append, ambient on every
  session) holds the **compressed** routing index — the realization of the PRIOR_ART §6
  "compressed index must be ambient" finding (a retrieval-tier index is too brittle). Both index
  layers are refreshed **by `/learn-docs` plans**, never by `perk init` (and neither path is
  gitignored — they are committed). erk's heavier machinery (tripwire generation, per-category
  auto-indexes, `docs sync` codegen, multi-agent session preprocessing) is deliberately deferred.
- **The judgment layer** is `skills/perk-learn-docs/SKILL.md`: read the inbox as untrusted DATA →
  cluster by cross-cutting theme → `docs/learned/<category>/` placement → author a bounded docs
  plan with a `## Steps` list → `plan_save` with `consumed_learn`; plus the ported content-quality
  rules (cross-cutting insight only, explain *why* not *what*, the One Code Rule / source pointers).

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
  changes: string[],                                       # converged/seeded pieces ([] ⇒ already converged)
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
  fix_errors: string[] }                 # --fix repairs that FAILED (e.g. a skills sync error;
                                         # rendered loudly; the post-fix re-verify keeps the
                                         # failing check, so the exit code stays honest)
```

**Groups.** `environment` (tools; required tools missing = `fail`; optional tools (e.g. ast-grep)
missing = `warn`) · `github` (auth/access; non-fatal `warn`) ·
`linear` (verify-gated Linear readiness — auth/team/labels; present only when the committed
`[issues] backend` is `"linear"`; warn-level, the github D3 mirror; `--fix` ensures the five perk
labels — §8.21) · `runner` (remote-runner prereqs; report-only, non-fatal — §8.16) ·
`package` (settings wiring + perk-package ref reconcile + the `extension-install` install-ownership
check; `--fix` also migrates a former git-clone consumer forward by removing the orphaned clone — §8.6a) ·
`repository` (gitignore/agents blocks + config present/valid) ·
`registry` (the registry self-check) · `skills` (the skills-CLI manifest fragment + the
fail-level `skills-delivery` substrate check + the `repo-skills` repo-authored-skills fragment check
— §8.9) · `bindings` / `providers` (rolled-up
non-fatal config checks — §8.9/§8.10) · `issues` (the fail-level `[issues]` selection check:
linear requires a committed `team` — §8.21) · `state` (the `.perk/workflow/` cache layout +
handoff-blob integrity). Managed-piece checks are filtered by `capabilities.applicable(self_repo)`; infra checks
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
  repo's legacy **`git:` perk** entry (any ref, by `_git_identity == GIT_PACKAGE`) so the flip from
  the old git wiring converges; a user's unrelated `git:` packages are preserved. **String-form
  only** (perk never writes object-form for its own package — Invariant 2; a hand-written
  object-form perk entry is a documented limitation). This rides the existing `settings-wiring`
  `ManagedConvergence` — version-pin drift becomes a `settings-wiring` **fail** that `--fix`
  repairs, with **no new doctor wiring**.
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
`nudge` delivers a short pointer to follow the named skill (the skill body stays ambient /
Pi-discovered), `transclude` inlines the skill body. The same skill may be a nudge at one trigger
and a transclude at another.

**Shipped default set (all 9 shipped bindings, all `nudge` — perk's own skills are ambient package
skills, so a pointer suffices; `transclude` exists for the user-binding case):**

| trigger | skill | mode |
|---|---|---|
| `stage:plan` | `perk-plan` | `nudge` |
| `stage:objective-author` | `perk-objective-author` | `nudge` |
| `stage:objective-plan` | `perk-objective-plan` | `nudge` |
| `stage:implement` | `perk-implement` | `nudge` |
| `stage:address` | `perk-address` | `nudge` |
| `stage:learn` | `perk-learn` | `nudge` |
| `command:objective-reconcile` | `perk-objective-reconcile` | `nudge` |
| `command:learn-docs` | `perk-learn-docs` | `nudge` |
| `command:pr-review` | `perk-pr-review` | `nudge` |

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
`<skill>` skill.`` pointer line; `transclude` inlines `.agents/skills/<skill>/SKILL.md` with its YAML
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
exists, the resolved render is non-empty, **and** no entry on `ctx.sessionManager.getBranch()`
already carries `BINDING_HEADER` (the cold prompt OR a prior warm inject). The injected custom and the
cold prompt both carry the header → idempotent across turns/reloads; after compaction drops the
original the header disappears and it **re-delivers** (its ongoing value). Mechanism B is a one-shot
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
SKILL.md`, with a self-repo `skills/<name>/SKILL.md` *pre-sync safety net* fallback
(`bindings.is_skill_installed(root, skill, *, self_repo)`, D4). perk's own `perk-*` skills are
delivered into `.agents/skills/` by the `skills` CLI in **both** self-repo and consumer trees (the
Pi package no longer declares `pi.skills`, so Pi never discovers the package `skills/` dir); the
`skills/<name>` fallback covers only the window before `skills update --sync` has run — and
**target-existence**
— `stage:<id>` must be a `registry.load_registry().stage_ids()` member, and `command:<id>` must be in
`DELIVERABLE_COMMAND_TARGETS = {objective-reconcile, learn-docs}` (the only command triggers perk's
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
  skills) not installed per `bindings.is_skill_installed`.
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
and `bindings.yaml`), is the **supported set** — the catalog of plan/todo/askuser/footer/web *providers* perk
knows how to wire — distinct from the per-repo **selection** (a flat `[providers]` table in
`.perk/config.toml`, which is just a pointer into the catalog). It is bundled automatically via the
`shared/` force-include (wheel → `perk/_shared/`, npm tarball → `shared/`) and read by both planes
through independent readers: **`perk/substrate/providers.py`** (`load_providers` / `validate` /
`resolve_providers`, returning `ProviderSet`/`Provider` + the shared `Issue`/`FindingSeverity` findings,
raising `ProvidersError` only for structural failures) and **`extension/substrate/providers.ts`**
(`loadProviders` + the pure `resolveProviders`, returning `ResolvedProviders { plan, todo, askuser, footer, web, issues }`
with `issues` as **`string[]`** — the TS plane has no `Issue`/`FindingSeverity`). The Python plane is the
authoritative validator. The
design is locked in `docs/design/adapter-architecture.md` (Node 1.3), over
`docs/design/provider-contract.md` (the seven dimensions) and `docs/design/pluggability-taxonomy.md` (the C3 behavior-preserving
default).

**Provider entry shape — `{ id, seam, package, adapter, default, package_filter? }`:** `id` is the
stable provider id (it is **not** the `cache.plan-ref` `provider` string — see the
“`cache.plan-ref.provider` is the issue backend, not the seam id” paragraph below); `seam ∈
{plan, todo, askuser, footer, web}`; `package` is the foreign Pi package spec added to `.pi/settings.json` `packages`
(`null` for perk's own bundled reference provider — nothing to add; **not universal** — the `web`
seam's reference provider `pi-web-access` carries a **non-null** `package` because perk owns no
native web implementation, the documented exception); `adapter` is the perk-owned
shim module bridging a foreign surface to the artifact boundary (`null` for the reference
provider); `default` is a bool — **exactly one `true` per seam**, the behavior-preserving no-config
pick; `package_filter` is an optional Pi object-form filter (`extensions`/`skills`/… arrays) merged
into a foreign package's object-form `packages` entry. Because both planes read this with their
full YAML readers, it can carry the nested `package_filter` object that the narrow-TOML config
reader cannot.

**Shipped set (Node 2.1 → 3.2 + askuser):** the three reference entries `perk-plan` (seam `plan`),
`perk-checkpoints` (seam `todo`), and `perk-ask-user` (seam `askuser`), all `package: null` /
`adapter: null` / `default: true`, plus a **real** foreign entry per seam. `tombell-plan` (→ `npm:@tombell/pi-plan`, `adapter:
planAdapterTombell`) is a real, selectable plan provider (Node 2.3); `juicesharp-todo`
(→ `npm:@juicesharp/rpiv-todo`, `adapter: todoAdapterJuicesharp`) is now a real, selectable **todo**
provider (Node 3.2) — neither is illustrative any longer. **Both seams are behavior-complete:** the
**plan** seam (perk vacates its surface at registration time + the adapter bridges the foreign one —
see the Node 2.3 status note in contracts-history.md §8.10) and the **todo** seam (perk's `checkpoints` **defers at runtime** under
a foreign `[providers] todo` selection — Node 3.1 — with **no** registration-time vacating, because
the todo seam has no command-name collision; the `todoAdapterJuicesharp` shim carries perk's
progress discipline onto the foreign overlay — see the Node 3.2 status note in contracts-history.md §8.10). The **askuser** seam is an **interface seam** — see the askuser status
note in [`contracts-history.md`](./contracts-history.md) §8.10. A fourth reference entry `perk-footer` (seam `footer`, `package: null` / `adapter: null` /
`default: true`) plus **four** foreign/null footer providers — `powerline-footer` (→ `npm:pi-powerline-footer`),
`pi-bar-footer` (→ `npm:pi-bar`), `pi-status-footer` (→ `npm:@tombell/pi-status`, #670), and
`pi-default` (`package: null`, #670 — "install nothing / pi stock footer") — make the **footer** seam
a **second interface seam** (vacate-only, `adapter: null`). `pi-status-footer` does **not** render
extension statuses, so perk progress is not shown under it (accepted limitation). With these the
footer is governed **exclusively** by `[providers] footer` — no footer outcome needs a manual
`packages` edit. See the footer status note in contracts-history.md §8.10. A fifth reference entry `pi-web-access` (seam
`web`, **`package: "npm:pi-web-access"`** — the first non-null-package default — / `adapter: null` /
`default: true`) plus two **real** foreign web providers `ollama-web-search` (→ `npm:@ollama/pi-web-search`)
and `juicesharp-web-tools` (→ `npm:@juicesharp/rpiv-web-tools`) make the **web** seam a **third interface
seam** (vacate-only, `adapter: null`) — see the web status note in contracts-history.md §8.10. The **default** path (the reference providers) is unaffected and is the hard guarantee.

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
`seam ∈ {plan, todo, askuser, footer, web}`, and that **exactly one `default: true`** exists per seam. They do **not**
check that any repo *selection* names a real provider — that cross-file validation is **`doctor`**'s
job (mirroring how bindings target-existence lives in doctor, not the loaders).

**The `[providers]` selection — flat string table in `.perk/config.toml`:** a per-repo selection with
one key per seam (`plan` / `todo` / `askuser` / `footer` / `web`), values are **bare provider-id strings** (the TS narrow-TOML
reader `parseTomlSubset` reads string values only; richer structure lives in `providers.yaml`).
Both planes parse it raw (`perk/substrate/config.py` → `Config.providers`; `extension/substrate/config.ts` →
`PerkConfig.providers`); resolution against the supported set is `init`/`doctor` in Python and the
`extension/substrate/providers.ts` `resolveProviders` resolver in TS (added Node 2.2, consumed by `planMode`). An **absent table or absent key → the seam's
`default: true` provider** (zero behavior change, the no-config default). `local.toml` overlay
wins (standard local-override precedence). The pure resolver
`perk.substrate.providers.resolve_providers(selection, providers)` returns `ResolvedProviders { plan, todo,
askuser, footer, web, issues }`: an absent key falls back to the default **silently**; an unknown id or a seam mismatch
falls back to the default and records a **loud-but-non-fatal** `Issue`.

**`perk init` two-directional settings wiring:** provider wiring composes on top of the static
`_desired_packages` (perk + `BORROWED_PACKAGES`: `npm:@tombell/pi-diff`,
`npm:pi-subagents`) layer within the same `_converge_settings` body — `npm:pi-web-access` is **no
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
are never touched. **perk's own package is never filtered, never object-form** (Invariant 2: perk
defers at runtime, it is not filtered). **Resolved ambiguity (Node 1.3 step 4):** any `packages`
entry whose identity matches a provider's `package` is treated as **provider-managed** (removable
when deselected); hand-adding a provider's package *without* selecting it is unsupported — a user
who wants that package selects the provider via `[providers]`. The retired `@tombell/pi-plan` /
`@juicesharp/rpiv-todo` re-enter `packages` **only** when a selection names them.

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
`keep_recent_tokens`→`keepRecentTokens`. Validation is LBYL silent-omit (mirrors `[providers]`):
`enabled` kept only if a real `bool`; the token keys kept only if `int` (not `bool`) and `> 0`;
ill-typed/absent keys are dropped (pi fills defaults). The convergence composes inside
`_converge_settings` (`perk/substrate/config.py::parse_compaction_table` + `load_committed_compaction`,
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
up by hand). A malformed-TOML error defers to the config check (treated as empty here, mirroring
`_converge_provider_packages`). perk's headless worker (`compaction: { enabled: false }`) and the
objective threshold compaction (`[objective] compact_threshold`) are orthogonal and unaffected.

> **Interactive save discipline (as of Node 2.5 the present + `/plan-save` flow is
> FALLBACK-ONLY on every interactive path — perk-plan included):** the prior
> `PLAN_AUTHORING_CONTEXT` ending ("disable plan mode (/plan off), then call the plan_save
> tool") was structurally broken — `/plan` is a user command the model cannot run, and the
> `plan_save` tool is excluded from `READ_ONLY_TOOLS` (hidden while the gate is on). The
> review-first discipline, now spoken by `PLAN_AUTHORING_CONTEXT`,
> `PLAN_ADAPTER_PLANNOTATOR_CONTEXT`, `OBJECTIVE_AUTHORING_CONTEXT`, the objective-plan factory
> guidance on both planes (warm `factoryGuidance` / cold `_seed_prompt` — #352 Node 3.1),
> `skills/perk-plan/SKILL.md`, `skills/perk-objective-author/SKILL.md`, and
> `skills/perk-objective-plan/SKILL.md` (#352 Node 3.2): keep the working draft
> current with `plan_draft`, call `plan_review` when decision-complete, and an approval
> **auto-saves** via `approvalSave`. Only when `plan_review` reports **skipped or unavailable**
> (headless, dismissed, no surface) does the model **present the complete plan as its final
> message and never attempt to save**; the **human** runs `/plan-save` (its
> `extractPlanMarkdown` scrape is reliable by construction — the final message is the clean
> plan; as of Node 2.2 `/plan-save` prefers the validated plan-draft artifact when one exists,
> and the scrape is the demoted universal fallback). `PLAN_ADAPTER_TOMBELL_CONTEXT` (Node 2.6)
> now joins `PLAN_AUTHORING_CONTEXT` / `PLAN_ADAPTER_PLANNOTATOR_CONTEXT` in the review-first
> list; the present + `/plan-save` (artifact-preferred, scrape-fallback) flow remains its
> explicit **fail-open** arm — including when `@tombell/pi-plan`'s own interactive `/plan`
> `setActiveTools` restriction hides `plan_draft`/`plan_review` from the tool set.
> `savePlan()` / the `plan_save` tool / `/plan-save` are **untouched**. The orchestrated
> **factory flows** that still instruct an autonomous `plan_save` tool call narrow to
> **learn-docs and replan**; **objective-plan** is review-first as of #352 Node 3.1 — the
> approval-driven save recovers the node link from the `objective_node_claim` carrier, with
> `plan_save`-with-both-ids demoted to the manual failsafe.

## §8.11 · The headless stage-drive worker contract (Node 1.2)

The **stage-drive primitive** (`extension/worker/worker.ts` `driveStage`) drives ONE read-write stage
(`implement`/`address`) end-to-end on an **already-prepared** worktree, in-process via the SDK
runtime factory, running the **same** `@mgiles/perk` extension package. It is the substrate Node 1.3
(the structured event stream) and Node 4.1 (the e2e harness) consume. This section locks the
worker's inputs, determinism invariants, terminal-signal definition, and outcome shape (the full
audit is `docs/design/headless-worker.md`, Node 1.1). The worker makes **no GitHub mutation of its
own** — the stage's own tools (`submit`, `resolve_review_threads`) delegate to the Python gateway
exactly as in a warm session (§8.4).

### Inputs (the prepared-worktree contract)

| input | shape | source |
|---|---|---|
| `worktree` | absolute path, already positioned | the cold-door/runner positioning (`perk/run/launch/__init__.py`), **not** the worker (Gap 7) |
| `stage` | `"implement" \| "address"` | the only `doors.cold_remote: true` read-write stages (`shared/registry.yaml`) |
| `run_id` | ULID, present as `PERK_RUN_ID` in env | minted by positioning; the worker **inherits** it and never re-mints |
| handoff / plan-ref / plan-body | files under `<worktree>/.perk/workflow/` | materialized by positioning; the worker does not re-write them |
| `initialPrompt` | string | re-derived by `initialPromptFor(stage, planRef)` — the TS twin of `perk/run/launch/prompts.py._implement_prompt`/`_address_prompt` (parity asserted reciprocally in `extension/worker/worker.test.ts` + `tests/test_worker_prompt_parity.py`); the resolved skill-binding suffix is delivered by the cold door and is **deferred to Phase 2** |
| `model` + `auth` | `Model` + `AuthStorage`/`ModelRegistry` | explicit worker input, else env-var key resolution (`ANTHROPIC_API_KEY` etc., Gap 5); **no model ⇒ a fail-soft `failed`/`no_model` outcome, never a throw** |
| `budget` | `{ maxTurns, maxTokens, wallClockMs }` | worker input; the watchdog that drives abort (Gap 2) |
| `signal` | `AbortSignal` | external cancellation; OR'd with the budget watchdog |

### Determinism invariants (fixed by the worker; not caller-tunable)

- **`cwd = worktree`, `agentDir = throwaway temp dir`** (Gap 4): the project tier loads (perk's
  `@mgiles/perk` via the managed `.pi/settings.json`, the managed `AGENTS.md`/`APPEND_SYSTEM.md`); the
  user-global tier (extensions/settings/skills/models/auth) is locked out. The
  `createAgentSessionServices` factory builds the `DefaultResourceLoader` internally from
  `cwd`/`agentDir` — the runtime path does **not** take a pre-built loader (recipe correction #1).
- **Compaction-off + retry-off** via `SettingsManager.inMemory({ compaction:{enabled:false},
  retry:{enabled:false} })` (Gap 3) **AND** the **no-active-objective invariant**: positioning never
  writes an `active_objective`, so `objective.ts`'s `turn_end` `ctx.compact` is inert. Together
  these kill both SDK auto-compaction and perk's threshold compaction. The worker must **never**
  call `/objective`/`objective_save` in the driven session.
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
   fail-open) → `completed`/`submit_tool`; for `address`, `resolve_review_threads` ok **and**
   `perk:workflow-state.last_review_batch` appended → `completed`/`address_resolved`. The resolver
   re-drive (§8.3) runs as follow-up turns inside the same `prompt()` drive; the final clean
   re-`submit` overwrites the captured details with `mergeable: true`, so natural-idle then passes.
2. **Driving `prompt()` resolved (agent idle), verified against the success predicate.** Idle is
   **not** itself success — if the predicate does not hold, → `failed`/`agent_idle_incomplete`.
3. **Budget / timeout / external abort** → `session.abort()` (hard; propagates into the in-flight
   `ctx.signal`-aware shelled tools `submit`/`resolve_review_threads`/`run_ci`): the watchdog →
   `budget_exhausted`/`budget`; the external `signal` → `aborted`/`external_abort`.
4. **Post-acceptance model error** (with retry off, an assistant `message_end` with
   `stopReason:"error"`) → `failed`/`model_error`.

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

`error.summary` is a short, model-free synthesis capped via the `route-don't-relay`/double-delivery
discipline (`capForModel`); the PR is extracted **directly from the captured terminal tool event**,
not a new Python `find-pr-for-branch` JSON command. Node 1.3 surfaces this outcome as the run-event
stream's terminal `run_finished` event (§8.12) — the same frozen object, carried in the structured
channel.

> **Open dependency (carried risk).** The `address` drive's seeded prompt instructs the model to
> spawn `perk.review-classifier` via the borrowed `pi-subagents` `subagent` tool. The worker's
> address prompt now also injects the configured classifier model when `[subagents]
> review-classifier` is set in the worktree's `.perk/config.toml` (#196), as a per-call inline `model`
> override byte-identical to `_address_prompt`'s parity twin. The **subagent-under-worker live
> smoke** stays the open-#6 dependency (§8.3, T6) **deferred to the Phase-3 `doctor workflow`**;
> Node 1.2 does not prove it.

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
{ "kind": "step_marker",  "seq": 1, "t": 0, "marker": "wip" | "done", "step": 1 }
{ "kind": "tool_outcome", "seq": 2, "t": 0, "tool": "submit", "ok": true, "summary": null }
{ "kind": "run_finished", "seq": 3, "t": 0, "outcome": { /* the frozen §8.11 RunOutcome */ } }
```

- **`run_started`** — emitted once at drive start (after a successful bind, before `session.prompt`).
- **`step_marker`** — one per `[WIP:n]`/`[DONE:n]` in an assistant turn's text, in **textual
  appearance order** (`turn_end` fires once per turn, so each turn's markers emit exactly once).
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

The structured channel carries the *narrative* (which tools ran + ok/fail, step progress, terminal
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

The value types (all frozen dataclasses, JSON-stable via `to_data`/`from_data`):

- **`RunHandle`** — `runner` (the routed ref, `""` ⇒ default), `kind` (`"github-actions"`),
  `run_ref` (the runner-native run id — GitHub Actions' numeric id as a string), `url`. Stored
  inside the dispatch record. **Do not conflate** `run_ref` with the perk `run_id`: the perk
  `run_id` is the canonical, runner-agnostic correlation key; `run_ref` is the runner-side handle.
- **`RunObservation`** — `status` (`"queued"|"in_progress"|"completed"|"unknown"`), `conclusion`
  (`"success"|"failure"|"cancelled"|…|None`), `url`.
- **`DispatchRecord`** — the durable linkage (below).

### The dispatch record (the supervisor's correlation source)

`DispatchRecord` is persisted at **`.perk/workflow/scratch/runs/<run_id>/dispatch.json`** (the run's
scratch dir — `perk init` already creates `scratch/runs/` and `.gitignore` already excludes
`/.perk/workflow/scratch/`, so no layout/gitignore change). Shape:

```jsonc
{ "run_id": "<ULID>",            // perk's canonical correlation key (authoritative on write)
  "stage": "implement",
  "plan_ref": { /* the cache.plan-ref blob */ },
  "runner": "",                  // the routed runner ref ("" => default)
  "kind": "github-actions",
  "status": "dispatching" | "dispatched" | "failed",
  "dispatched_at": "<ISO-8601 UTC>",
  "run_handle": { /* RunHandle.to_data() */ } | null,
  "error": "<string>" | null }
```

The supervisor (Node 3.1) enumerates `scratch/runs/*/dispatch.json` to correlate
`run_id ↔ plan ↔ PR` (the `perk workflow run list` read surface, §8.17); that enumeration is its
work, not this node's. A **failed** record is kept
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
5. **Persist** the `DispatchRecord` (`status:"dispatching"`) via `cache.write_dispatch`, then
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
  (`actions/checkout`, the composite setup `uses:`, `Check out the plan branch`, `Drive the stage
  headlessly`) carries `if: inputs.smoke != 'true'`, so a smoke run does no plan checkout, no setup,
  no worker drive, and spends no model budget. Real dispatches omit `smoke` and inherit the
  `"false"` default (backward-compatible). The
  `drive` job validates required secrets — it fails fast when `PERK_GH_PAT` is missing **and** when
  **both** `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` are empty (pre-empting the worker's late
  `no_model`) — checks out the plan branch (`plan-<plan>`), runs the composite setup, then `perk
  run-worker`. An opt-out repo variable `PERK_ENABLED=false` disables the job without removing the
  file. **Auth model:** checkout + push use the `PERK_GH_PAT` PAT, **not** `github.token` — a
  PAT-pushed commit triggers downstream CI (the implement drive commits + `submit` pushes);
  `GITHUB_TOKEN`-pushed commits do not. This is a stated decision Node 2.4 inherited (the
  `runner-workflow-permissions` check is advisory `info` because of this PAT-push model — §8.16).
- **`.github/actions/perk-remote-setup/action.yml`** — the composite setup action: the two pinned
  toolchains (uv + Node 22), then perk (the exterior CLI — `--from . perk` for the self-repo,
  an exact-version-pinned PyPI install `uv tool install perk=={__version__}` for a consumer,
  baked in at `perk init` time so the runner reproduces the wiring perk version), pi (the interior the
  worker drives), the Node worker's peer deps, and a final **git-identity** step (`perk[bot]`,
  `--global`) so the worker's commits succeed on a fresh runner. The worker-deps step is repo-kind
  aware: **self** uses `npm ci` (the self-repo has the `package.json`/lockfile/devDeps the worker
  resolves); **consumer** installs the pinned `@mgiles/perk`
  (`npm install @mgiles/perk@{__version__} --prefix .pi/npm --legacy-peer-deps`, baked in at `perk init`
  time so the runner reproduces the wiring perk version) — landing `@mgiles/perk` *and its runtime deps*
  under `.pi/npm/node_modules/`, so the `consumer-npm` worker entry and its peer imports resolve.

Full-file managed (like the settings/gitignore/AGENTS blocks): a hand-edited file reads as drift and
is converged back to the template. The templates are authored as code (string constants), not
packaged data, so there is no wheel-data surface to guard.

### `perk run-worker` (the CI positioning + drive entrypoint, `perk/run/run_worker.py`)

`perk run-worker --run-id --stage --plan [--base]` is the runner's positioning job (Gap 7), invoked
by the workflow **after** it checks out the plan branch (so cwd = the checkout = the worktree):

1. Resolve a remotely-drivable stage (a `doors.cold_remote: true` stage) from the registry; else
   `UserFacingCliError(stage_not_drivable)`.
2. Reconstruct the `cache.plan-ref` from the plan's GitHub state (`github.get_plan` +
   `resume.reconstruct_plan_ref`); a missing plan ⇒ `plan_not_found`.
3. **Position** the worktree (mirroring `launch.launch_stage`): `cache.ensure_layout`,
   `write_handoff({stage, mode})`, `write_plan_ref`, then materialize the plan body. The worker
   inherits the prepared worktree and never re-writes it (the §B inputs table).
4. Resolve the Node worker entrypoint — `PERK_WORKER_ENTRY` override (`env`), else the self-repo
   `extension/workerMain.ts` (`self`), else the consumer npm install under
   `.pi/npm/node_modules/@mgiles/perk/extension/workerMain.ts` (`consumer-npm`); a miss ⇒
   `worker_entry_missing`.
5. **Spawn** `node <entry> <stage> --worktree <repo_root>` with `PERK_RUN_ID=<run_id>` in the env
   (inherited stdio — the worker owns stdout/the `RunOutcome` JSON), and **exit with the worker's
   exit code** so the workflow step reflects the drive outcome.

`run-worker` is a deterministic exterior command (no agentic reasoning): it positions and drives;
model/auth resolution is the Node worker's job (env-var key resolution, Gap 5). `--base` is part of
the §8.13 input contract and is carried for parity, but the plan branch is already checked out by the
workflow, so it is not consumed here. Reporting run progress/terminal status back into GitHub is
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

Both are **fully fail-soft**: any exception inside reporting is caught, logged via `user_output` to
stderr, and swallowed. Reporting must never change the worker's exit code or crash the runner —
observability is best-effort (mirrors the worker's fail-soft event sink).

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
surface that enumerates the durable dispatch records (§8.13) and correlates each
`run_id ↔ plan ↔ PR`, overlaying live GitHub run state. It mutates nothing (no GitHub writes, no
`.perk/workflow/` writes). `cancel`/`retry` (the `run` subgroup's mutating siblings) **shipped** in
Node 3.2 — see §8.18.

### Command surface (`perk/cli/commands/workflow_cmd.py`)

- `perk workflow run list` (aliases `perk workflow run ls`, `perk wf run list`). The `workflow`
  group (alias `wf`) holds the `run` subgroup so Node 3.2 extends the same subgroup.
- A dev/CI/supervisor surface (like `perk objective`/`perk state`), **not** an agent affordance.
- `--json` → a stable machine report on **stdout**; the human table → **stderr** (the cli-vs-pi
  §3.2 split). `--no-refresh` skips the live GitHub overlay; `--limit N` (default 50) caps the
  newest-first list.

### Source of truth + correlation

- **Local records are authoritative for *which* runs exist.** `cache.list_dispatch_records(root)`
  enumerates `scratch/runs/*/dispatch.json` (§8.13), newest-first by `dispatched_at` (descending;
  string ISO-8601 sort). A missing/unparseable/non-object record is skipped loud-but-non-fatal
  (stderr warning), never fatal — a corrupt record must not break the supervisor read; an absent
  `scratch/runs/` yields `[]`. GitHub is **not** enumerated for run discovery.
- **Plan block** comes straight from the record's `plan_ref` (`pr_id`, `url`) — offline-safe, always
  present. Note `plan_ref.pr_id` is the **plan issue** number, not a PR number.
- **PR correlation** derives the PR through `github.get_plan(number=int(pr_id)).pr` (memoized per
  `pr_id`), since the draft PR is separate from the plan issue.
- **Run state** overlays via the `Runner.observe` contract (§8.13): when the record's `run_handle`
  is non-null, `runner.select_runner(record.runner).observe(RunHandle.from_data(...))` yields the
  `RunObservation` (`status`/`conclusion`/`url`). A null `run_handle` (records still
  `dispatching`/`failed`) ⇒ no GitHub call.

### Fail-soft overlay discipline

The live overlay is **best-effort**: it does **not** call `require_github`; a missing/unauthed gh
simply yields no overlay (noted once on stderr). Each per-record read is wrapped — a
`runner.RunnerError` degrades the `run` block to `null`; a `github.GitHubError` degrades the `pr`
block to `null` — with a one-line stderr note, never raising and never changing the exit code (this
is a read surface, not a gate). `--no-refresh` forces `pr`/`run` to `null` with zero GitHub reads.

### The `--json` payload (stdout, stable)

```jsonc
{ "success": true, "error_type": null, "refreshed": true, "count": 1,
  "runs": [
    { "run_id": "01J…", "stage": "implement", "runner": "", "kind": "github-actions",
      "dispatch_status": "dispatched", "dispatched_at": "<ISO-8601 UTC>", "error": null,
      "plan": { "pr_id": "42", "url": "https://…/issues/42" },
      "pr":   { "number": 51, "url": "https://…/pull/51", "state": "OPEN" } | null,
      "run":  { "run_ref": "1234567", "url": "https://…/actions/runs/1234567",
                "status": "completed", "conclusion": "success" } | null } ] }
```

`refreshed = not no_refresh`; `pr`/`run` are `null` under `--no-refresh` or a failed/empty overlay.
`success` is always `true` for a successful enumeration (even zero runs); only `require_repo` failing
(`not_a_repo`) routes through `_fail` (exit 2). No other error type is introduced.

### Human table (stderr)

Plain, manually-aligned, newest-first columns
`RUN_ID  STAGE  DISPATCH  RUN  CONCLUSION  PLAN  PR  AGE`. The full `run_id` (the supervisor copies
it into Node 3.2's `cancel`/`retry`) is never truncated; the overlay columns show `-` when not
refreshed/unresolved; `AGE` is a compact relative age from `dispatched_at`. A `failed` record's
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
fail-soft `list`), the shared `_resolve_target` helper resolves it:

1. `record = cache.read_dispatch(root, run_id)`; `None` ⇒ `run_not_found` (exit 1).
2. `record.run_handle` falsy (still `dispatching`/`failed`, never triggered) ⇒ `run_not_dispatched`
   (exit 1) — nothing to act on.
3. otherwise reconstruct `RunHandle.from_data(...)` + `select_runner(record.runner)`; the runner op
   acts on the runner-native `run_ref`.

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
// failure → the shared _fail shape:
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
verifying by discovery on the minted `run_id`. It writes **no** `DispatchRecord` and creates **no**
GitHub artifacts (no branch/PR/issue), so `perk workflow run list` (§8.17) is unaffected and the smoke
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
// refusal / dispatch error — the shared _fail shape:
{ "success": false, "error_type": "<type>", "message": "<reason>" }
```

Error types + exits: `not_a_repo` → 2; `github_unauthed`, `runner_disabled`, `smoke_dispatch_failed`
→ 1.

## §8.20 · The capstone supervisor loop (`perk objective run`, Node 3.4)

The **scheduler** on top of the §8.13 dispatch-record substrate and the §8.17/§8.18 read/control
siblings: a **deterministic, no-agentic-reasoning** supervisor that advances an active objective's
backlog as far as is autonomously safe, then pauses at the human land gate. `perk objective run
<NUMBER>` (alias `obj r`) is a supervisor surface (cli-vs-pi §3.2): `--json` → stdout, human text →
stderr, stable exits (`0` ok · `1` invalid/op-failure · `2` not-a-repo), `_fail`/`UserFacingCliError`
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
2. `state = github.get_objective(NUMBER)`; `None` → `_fail(objective_not_found)`.
3. **Cumulative budget report** (always, before any action): enumerate
   `cache.list_dispatch_records`, keep records whose `plan_ref.objective_id` canonicalizes
   (`str(...).lstrip("#")`) to NUMBER, sum each `run_report.read_outcome` `budget`
   (`turns`/`tokens`/`elapsed_ms`, missing ⇒ 0) → `{runs, turns, tokens, elapsed_ms}`. **Report-only:
   no limits, no thresholds, no `budget_exhausted`.**
4. **Active-run gate** (skipped under `--dry-run`): an objective run is in-flight when a kept record
   has a `run_handle` and a live `observe` returns `queued`/`in_progress` (newest-first; observe
   fail-soft → treat as not-in-flight). Not `--wait` → `awaiting_run`, exit 0. `--wait` → poll to
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

### In-flight stage resolution (`get_plan(node.pr)` → branch on `plan_state.pr`)

| `plan_state.pr` | action | dispatch? |
|-----------------|--------|-----------|
| `None` (no PR yet) | `dispatched` `stage:"implement"` | yes (remote) |
| `MERGED` | `merged_pending_reconcile` | no |
| `CLOSED` (unmerged) | `pr_closed` (needs human) | no |
| `OPEN` + `is_draft` | `ready_for_review` | **no — never re-dispatch implement** |
| `OPEN` + not draft, `needs_address` true | `dispatched` `stage:"address"` | yes (remote) |
| `OPEN` + not draft, `needs_address` false | `awaiting_review` | no |

A missing `node.pr` or a `None` `get_plan` falls back to `plan_required` (defensive). A draft PR means
implement is **complete** — never re-dispatch `implement` from a draft.

### The `needs_address` predicate (pure, offline-testable)

`needs_address(feedback: PrFeedback) -> bool` is **True** when either any `review_thread.is_resolved is
False`, **or** the **latest review per author** is `CHANGES_REQUESTED`. "Latest per author" = the
`Review` with the max `submitted_at` (ISO-8601 string compare; `None` sorts oldest). A `COMMENTED`/
`APPROVED` latest review does **not** trigger address; `discussion_comments` are never address triggers
(conversation, not change requests).

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
  "node": "<id>" | null, "stage": "implement" | "address" | null,
  "run_id": "<ULID>" | null,     // present on dispatched
  "remediation": "<cmd>" | null, // present on plan_required
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
store. **`LINEAR_API_KEY` lives in the environment or the gitignored `.perk/local.toml`
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
- `linear-labels` — all five perk labels present (`perk:plan`, `perk:learn`, `perk:consolidated`,
  `perk:objective`, `perk:objective-node`): ok; otherwise warn listing the missing names,
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
key + team are available, `check_readiness(..., ensure_labels=True)` ensures the five labels;
created names land on `fixed` (`Linear: created label perk:plan`), failures on `fix_errors`.
Lookup-first idempotency: a converged workspace reports nothing (the doctor idempotency rule).

**The init readiness step** (`perk/convergence/init/__init__.py::_linear_readiness`, verify-gated, non-fatal — the
GitHub D3 mirror: file convergence already succeeded). Only when `verify` AND the committed
backend is `"linear"`: missing key/team degrade to an errored `LinearReport`; otherwise the probe
runs with `ensure_labels=True` (init converges the five perk labels upfront; the lazy write-time
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
unsupported). A malformed committed TOML defers to the config check (selection treated as absent).

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
  (`planSave.ts`/`learn.ts`/`land.ts`/`objectiveSave.ts`/`learnDocs.ts`) are lockstep-strict on
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
- **The fail-soft guarantee**: every emitter is fully wrapped (the
  `_reconcile_objective_on_land` fail-open discipline) — it never raises and never changes the
  host command's result/exit code/`--json` payload; failures print one loud-but-non-fatal stderr
  note (`perk linear-agent: <what> skipped (non-fatal): <exc>`).
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
  optional title argument.
- **The three backends.** All three speak review-first
  (`plan_draft` → `plan_review` → auto-save on approval):

  | provider id | authoring context | review surface | fail-open arm |
  |---|---|---|---|
  | `perk-plan` | `PLAN_AUTHORING_CONTEXT` | first-party in-TUI review | present + `/plan-save` |
  | `plannotator-plan` | `PLAN_ADAPTER_PLANNOTATOR_CONTEXT` | browser bridge | present + `/plan-save` |
  | `tombell-plan` | `PLAN_ADAPTER_TOMBELL_CONTEXT` (conditioned injection, Node 2.6) | first-party in-TUI review | present + `/plan-save` (incl. tombell's own interactive `/plan` `setActiveTools` restriction arm) |

- **Link/`consumed_learn` recovery carriers.** Approval-triggered saves carry **no model params**;
  the **cold** `handoff_extra` carrier (→ §8.2) and the **warm** `objective_node_claim` carrier
  (→ §8.3) recover `objective_id`/`node_id` with identical semantics — fill both-or-neither,
  explicit values win outright (even one — never mixed), fail-open (a malformed carrier never
  blocks a save). `consumed_learn` rides the cold handoff (`_consumed_learn_from_handoff`).

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

**Don't-churn unchanged.** Engagement is a new re-investigation *input*, not a new skip-rule clause;
the perk-replan skill's "skip if nothing material changed" rule is left verbatim.

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
  Idempotent on re-save; GitHub stamps HTML-encoded, Linear inline-code (Linear-safe).

**The cold door (`perk plan from <issue>`).** A dedicated launcher verb in the `plan` hybrid group
(mirrors `replan`/`resume`; `from` is a valid Click command string). It performs every Linear/GitHub
read up front (the read-only plan-mode session has no `gh`/Linear access), then re-launches the
`plan` stage seeded to author a plan over the materialized source. It **refuses** when: the issue is
not found (`adopt_not_found`), not OPEN (`adopt_not_open`), or already a perk plan
(`has_metadata_block(body, plan-header)` → `already_a_plan`, hinting `perk plan replan <id>`).
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
  `project_issues` selecting `title` too; the byte-stable `project_issues` left untouched).
  `read_objective_source` → the project overview `content` + its issues. `adopt_source_as_objective`
  composes the new overview preserving the original verbatim (`to_linear_markdown(`
  Reconcilable(`<model prose>`) + `objective-header`(`adopted_from=source_id`) + `objective-manifest`
  + `render_adopted_overview_note(<original overview>)` below the markers `)`), `update_project
  _content` (in place, NOT `create_project`), prepends the callout; one milestone per phase via
  `ensure_phase_milestone` seeded from `project_milestones` (de-dupe against existing); for each
  node in `node_sort_key` order a **mapped** node stamps the `objective-node` block additively into
  the existing issue (title/body verbatim, description PATCH + `perk:objective-node` label added +
  phase-milestone attach), an **unmapped** node mints a fresh node-issue; blocking relations per
  explicit `depends_on`. Raises on an `adopt_issue` id not in the project (fail-loud). Idempotent on
  `run_id`.
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
  learn/address/learnDocs/lifecycleGates doors, the warm pr-review / submit / objective-save /
  objective-reconcile doors, the objective-plan factory, and — on the Python side — the cold
  plan-from / replan / objective-author / objective-replan doors.

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
(`<untrusted_objective_unfinished_nodes>`) into a scratch file as DATA, seeds the unchanged
`objective_draft → plan_review → objective_save` flow, and stashes `supersedes=<OLD>` in the run
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
`adopt_issue` Linear move, the don't-churn rule), cross-referencing `perk-objective-author` for the
draft→review→save mechanics. The warm plane is unchanged — `objective_draft`/`objective_save`'s
structured roadmap path already carries `adopt_issue` per node, and `supersedes` rides the handoff
exactly as `adopt_from` does, so no TS schema edit is needed.

## §8.33 · Local-file seeding for the adoption cold doors (`plan from` / `objective author --from`)

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
