# perk cross-plane contracts

The four language-neutral contracts both planes obey, authored once here and bundled into
each build artifact (`Q12`). These are **prose specs** (no parser): the Python CLI (`perk`)
and the TS extension (`@perk/pi`) each implement one side, against the exact names/paths/
fields pinned below. `perk doctor` (T6) verifies conformance.

There are now **two** parsed contracts (siblings of this file): `registry.yaml` — the stage
graph, whose `state_keys` block is the canonical vocabulary referenced throughout this
document — and `bindings.yaml` — the skill-binding set (trigger→skill delivery), specified
in §8.9.

Source decisions: `Q1` (workflow-state), `Q2` (layout + run_id), `Q3` (verified linkage),
`Q9`/`Q10` (gateway). Pi mechanics are cited against
[pi--best-practices.md](../docs/pi--best-practices.md).

> **Status (T2):** specs locked. Implementations land later — state helpers in **T3**, the
> launch/`PERK_RUN_ID` emit in **T4**, the gateway verification ops in **T5** (Python) /
> Phase 1 (TS). Gateway *mutation* ops are named here but **not authored** (payloads land in
> Phase 1, when `/plan-save` knows their shape — `Q7`/`Q9`).
>
> **Status (T5):** the §8.4 **verification ops are implemented in the Python plane**
> (`perk/github/auth.py` — `check_auth` / `check_repo_access`, verification-only, never mutating);
> the TS plane authors the same shapes in Phase 1. The §8.5 init machine-surface contract is
> live (`perk init --json`).
>
> **Status (P1.T2a):** the §8.4 **plan-write mutations are implemented in the Python plane**
> (`perk/github/plans.py` `create_label` / `create_plan_issue` / `add_issue_comment` /
> `find_plan_issue` + `perk/plan.py` storage) — the **cold/worker** save door
> (`perk plan-save`). The warm in-session twin (the TS `/plan-save` tool) is T3. Both planes
> use **REST `gh api`** (never porcelain — porcelain's GraphQL has a separate, often-exhausted
> rate-limit quota) and pass large bodies via `-F body=@file`.

---

## §8.1 · `.pi/workflow/` layout (Q2)

The local cache tier — written and read by **both** the CLI (exterior) and the extension
(interior). Fixed layout:

```
.pi/workflow/
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
- `.gitignore`: `.pi/workflow/` transient subtrees are not committed; `plans/` may be cached
  locally but GitHub is canonical. `init` manages the relevant `.gitignore` entries (incl.
  `/.pi/workflow/plan-ref.json` and `/.pi/workflow/plan.md` — local mirrors; the canonical plan
  lives in GitHub). The materialized `plan.md` body is transient and must never be tracked;
  `perk doctor --fix` untracks a legacy-committed copy and drops any stray ungrouped ignore line
  (#43).
- **`plan-ref.json` (`cache.plan-ref`, T2b):** the provider-agnostic plan-ref payload (§8.4)
  written verbatim. One active ref per checkout/worktree (`.pi/workflow/` is per-checkout). The
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
  `.pi/perk.toml`, read through `extension/substrate/config.ts` — written as a **quoted** value because the
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
in-session twin of `perk/run/launch.py`'s `_initial_prompt`: read the plan from its canonical source,
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
entry). The `cache.plan` body (`.pi/workflow/plan.md`) is **materialized by the Python cold door**:
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
entry is never clobbered). It is **opt-in + inert-by-default (D4)**: perk plans are prose, so when no `## Steps` list is
present the checkpoint degrades to inert (no entry, no crash); the `perk-plan` skill documents the
optional `## Steps` section as the forward path. Cross-plane contract: the **file** `cache.plan`
(`.pi/workflow/plan.md`), written by Python and read by TS. State is **rebuilt on `session_start`, `session_tree`, AND
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
so there is no last-wins clobber. See §8.10's footer interface-seam note.)

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
`setStatus`, `setWidget`, `setFooter` — lives in the surfaces module (`extension/surfaces/surfaces.ts` +
`extension/surfaces/report.ts`); every other extension module reaches the UI only through the seams
(`report()`, `createPerkStatus`, `setStandingWidget`, `installPerkFooter`). `setWorkingIndicator`
is never called anywhere (D5 rescinded). Enforced by the source-scan guard
`extension/surfacesGuard.test.ts` (node:test, runs in `just test`/`just ci`).

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
`gh search …`, `gh auth status` — while `gh api` and all mutating `gh` subcommands stay blocked); (3) injects a hidden `[READ-ONLY MODE]`
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
`.pi/perk.toml` + `perk.local.toml` (`extension/substrate/config.ts`, the TS twin of `perk/substrate/config.py`'s
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
stage — `shared/registry.yaml` is unchanged) that conducts automated code review of the active PR.
The outcome is **verdict-driven**: the review lands **as comments on the PR only on an
`actionable` verdict**; a `clean` verdict posts a single 👍 reaction to the PR description and
nothing else — comments and `/address` are reserved for actionable feedback, and a clean verdict
unambiguously routes to `/land`. It spawns the perk-owned **`perk.pr-reviewer`** agent via the
borrowed `pi-subagents` engine with **`context: "fresh"`** (not a fork) so the implementation
session's history never biases the review.

- **Verdict-driven batch.** The review batch requires a `verdict` of exactly `"clean"` or
  `"actionable"` (a clean verdict with non-empty `comments` is a `bad_batch`). The optional
  `fyi: string[]` field carries borderline notes that are validated and echoed **in-session only**
  — it is structurally never part of any GitHub payload. The clean path's 👍 reaction
  (`add_pr_reaction`, the issues-reactions endpoint — idempotent on rerun) is a **hard error** on
  failure (mutations raise; no fallback ladder — nothing review-shaped is lost).

- **Deliberate departure from the read-only-child convention.** Unlike `/address` (read-only child
  classifies; the **parent** acts), the reviewer child **posts its own review**. Rationale: the PR
  is the sole output sink and there is no parent-side fix to apply, so relaying the review back
  through the parent would reintroduce exactly the session pollution this command avoids. D1 is
  still honored — the mutation stays canonical in the **Python gateway**: the child posts via
  `perk pr review-post` (the child has `write` only to stage the payload file + `bash` to run the
  CLI). The review is **advisory `COMMENT` only** — `event` is hardcoded `COMMENT` in the gateway,
  so the agent can never approve/request-changes.
- **Configurable models via the agent-keyed `[subagents]` table (#196).** Every perk-owned project
  agent's model is configurable through one flat `[subagents]` table in `.pi/perk.toml` (overlaid by
  `.pi/perk.local.toml`), keyed by the bare agent name — `pr-reviewer`, `review-classifier`,
  `objective-explorer` (matching each def's `name:` frontmatter and the `perk.<name>` invocation).
  Each configured value is injected as a **per-call inline `model` override** on that agent's
  `subagent` spawn (the agent's frontmatter `model` stays the default when the key is unset). This
  is wired at **all six** authored spawn sites: the warm TS doors (`prReviewGuidance`,
  `addressGuidance`, `factoryGuidance`), the cold Python prompts (`_address_prompt`, `_seed_prompt`),
  and the headless worker (`initialPromptFor`). The earlier `[pr-review] model` key is removed
  outright (clean break, no alias — perk `0.0.1` pre-release, init converges forward). Unknown/typo'd
  agent keys are silently ignored (mirrors `_parse_providers_selection`); no doctor validation.
  **Correction to the T7 note above:** `subagents.agentOverrides` does **not** reach project agents
  — `pi-subagents`' `applyBuiltinOverrides` applies overrides only to **builtin** agents — so the
  inline per-call override (not an override map) is the configuration mechanism for project agents
  like `perk.review-classifier` and `perk.pr-reviewer`.
- **No workflow-state record (deferral).** There is no parent-side tool turn (the child posts), so
  no `last_review_batch`-style record is written; the PR comment is the canonical record. A richer
  in-session record is a future enhancement.
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
  perk's own three agents). Linked worktrees inherit the delivered defs via git checkout (no worktree
  mirror).

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
  is unchanged; what's added is the *driver*. The `learn` cold launch is **primed** (`launch.py`
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
get_pr_review_context{ pr_number, branch }          -> PrReviewContext{ pr_number, base_ref, head_ref, title, body, diff, plan_body }
    # Read-only. PR meta via `gh api pulls/{n}`, diff via `gh pr diff {n}`. `plan_body` is
    # best-effort: the materialized `cache.plan` body if present, else the plan issue body, else
    # null (the review still runs from the diff). What the spawned child runs (`perk pr review-context`).
post_pr_review{ pr_number, summary, comments:[{path,line,body}] } -> ReviewPostResult{ ok, mode, pr_number, comment_count }
    # ONE review via POST .../pulls/{n}/reviews with event=COMMENT (hardcoded) + inline comments[]
    # (path, line, side=RIGHT). mode ∈ {"review" (inline-anchored), "comment_fallback" (discussion
    # comment when the review submission fails)}. The warm twin is the /pr-review child, which
    # delegates via `perk pr review-post --json --batch <path>`.
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
  consumed_learn: string[] }   # hop-2: perk:learn issue ids a docs plan consolidates (closed on
                               # land) — opaque strings (§8.21; Node 4.1)
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
  consumed_learn: string[] }   # hop-2: perk:learn issue ids (opaque strings — §8.21; Node 4.1)
```

**Label taxonomy (minimal, PRIOR_ART §2/§6):** `perk:plan` (green `1f883d`), `perk:learn` (purple
`8250df`), `perk:objective` (indigo `5319e7`, description "perk objective issue", since P2.T9), and
— since hop-2 — `perk:consolidated` (gray `6e7781`, description "perk learn issue consolidated into
docs/learned"), each **lazily created** by its gateway create-op on first use (perk never seeds
labels in `init`). Query by a **single** label — GitHub label filters are AND-semantics.

**The `pending-learn` semaphore (P1.T5b; Q2/Q5).** An existence-only `cache.markers` file
(`.pi/workflow/markers/pending-learn`, name shared as `PENDING_LEARN` in both planes): **`land`
sets it** (after a successful merge), **`learn` clears it**. While present it signals the
land→learn cycle is open and the worktree is not yet releasable (a future `worktree remove` /
`doctor` honors it). `learn` is **thin and TS-only** this phase — it clears the marker; the
agentic capture + a `perk:learn` label/issue is Phase 2.

> **Status (P1.T2b):** the plan-ref is **materialized**. T2a emits it (`--json`); T2b persists
> it as the `cache.plan-ref` file (`.pi/workflow/plan-ref.json`, written by the cold door,
> read by both planes) and reconciles it into the `active_plan_ref` session field on
> `session_start` (§8.3).
>
> **Status (P1.T3):** the **warm door** is built. The in-session `plan_save` tool + `/plan-save`
> command **wrap** this cold `--json` write (via process launch + the §3.2 machine-JSON surface —
> **not** a TS reimplementation): they delegate to `perk plan-save --json`, then append
> `active_plan_ref` to link the live session. This is the read-only → read-write boundary; the
> plan→implement transition is the **cold door** (T4, fresh context). `save.writes` is now
> `[github.plan, cache.plan-ref, session.workflow-state]`.
>
> **Status (P1.T4a):** the **cold door** consumes the plan-ref. `perk implement` (no positional —
> the *active* ref; arbitrary `#N` is `perk resume`, T5c) reads `cache.plan-ref` from the repo root,
> **derives a deterministic worktree/branch name `plan-<pr_id>`** (`pr_id` stays a string), creates
> the worktree **idempotently** (an existing one is reused — resume), and **materializes the
> handoff + plan-ref into the worktree** so the launched `pi` (cwd = worktree) reconciles
> `active_plan_ref` on `session_start` (§8.3) with no extension change. The plan-header's `branch`
> field stays `null` until it is recorded at **submit** (T5a). `implement` reads `cache.plan-ref`
> and writes `session.workflow-state` (the worktree link).
>
> **Status (origin-aware create base).** On **create** (not reuse), `perk implement` does a
> **best-effort `git fetch origin`** and bases the new `plan-<pr_id>` branch on **`origin/<trunk>`**
> (trunk via `git symbolic-ref refs/remotes/origin/HEAD`, fallback `main`/`master`, final `main`) —
> so work starts on up-to-date trunk, not stale local HEAD. If the plan's branch already exists on
> the remote it bases off **`origin/<branch>`** (tracking the resumed/remote branch). A
> **`--base <ref>` override wins verbatim** (deliberate stacking on an unlanded branch, even a
> non-origin ref). An **offline fetch failure is non-fatal but warns loudly** and falls back to the
> last-known origin ref (or local HEAD when there is no remote — `base: null`). The
> **reuse/resume** path (an existing worktree) never fetches or re-bases (D4). `--dry-run`/`--json`
> surfaces the resolved start-point as a `base` field (resolved from local refs, no fetch). No
> registry I/O change.
>
> **Status (P1.T4c) — implement gains a plan arg + session priming.** The Phase-1 dogfood run
> surfaced two cold-door gaps and corrected them forward (T4a's no-positional D2 was the deviation
> from phase-1-plan §P1.T4's `perk implement <plan>`): (1) **`perk implement [PLAN]`** is now a
> *dedicated* command — an optional issue number (`perk implement 42`) resolves the plan via
> `github.get_plan`, writes it as the active `cache.plan-ref` (mirroring `perk resume`), then
> launches; omitting it uses the active ref (the T4a behavior). (2) The launcher **primes the
> implement session** — `launch_stage` passes an initial prompt to `pi` (read the plan via
> `gh issue view <n> --comments`, implement on the branch, `/submit` when committed) so the session
> starts working instead of opening idle. Only the `implement` stage is primed; `plan` stays
> user-driven. No registry I/O change (still `reads:[cache.plan-ref]`, `writes:[session.workflow-state]`).
>
> **Status (P1.T5a) + the delegation decision.** The §8.4 opening's "one contract, implemented
> **once per plane**" (a Python gateway *and* a TS gateway, same shapes) was a Phase-0 hypothesis.
> **T3 deviated** (the warm `/plan-save` delegates to `perk plan-save` via `pi.exec`), and T5
> **confirms delegation as the standing pattern for GitHub mutations**: the **Python gateway is
> canonical**; the TS warm doors (`/submit`, and `/land` in T5b) **delegate** to thin Python workers
> (`perk pr submit`/`perk pr land --json`) over the §3.2 machine-JSON channel — they do **not**
> reimplement the writes. (Cache/session tiers keep their per-plane I/O — `cache.ts`/`cache.py` —
> because those are *files*, not GitHub.) The "two gh gateways" idea is retired; there is **one
> canonical Python GitHub gateway**. So **T5a** opens a **draft** PR (`Closes #<issue>` so the
> squash-merge closes the plan), then `update_plan_header` populates the staged `branch=plan-<pr_id>`,
> `pr=<number>`, `lifecycle_stage=impl`. `submit` reads `cache.plan-ref` + `github.plan` and writes
> `github.pr` + `github.plan`.
>
> **Status (P1.T5b):** the **land path** is built. `land` (warm `/land` + cold `perk pr land`)
> marks the PR ready (if draft), **squash-merges** it (idempotent — `already merged` ⇒ success), and
> sets the **`pending-learn`** marker; `learn` (warm `/learn`, TS-only) clears it. The cold worker
> sets the marker on its real run; the warm door also sets it post-delegate (idempotent existence
> file), so each plane's path is independently correct. `land` reads `cache.plan-ref` + `github.pr`
> and writes `github.pr` + `cache.markers`; `learn` reads/writes `cache.markers`. Reconciliation
> typing + the review/`address` loop + deep learn tooling stay Phase 2.
>
> **Status (P1.T5c):** `perk resume <plan>` is built — the cross-stage verb. It reads the plan via
> `get_plan`, **reconstructs `cache.plan-ref`** from the GitHub state, derives the **current
> actionable stage** (no PR → `implement`; PR open → `submit`; PR merged + `pending-learn` →
> `learn`; merged + learned → nothing), then reuses T4a's `launch_stage` (idempotent worktree +
> materialize + `exec pi`). `--dry-run`/`--json` resolve + print without launching (no ref write).
> The resolution is a **pure, unit-tested** function (`perk/run/resume.py`). For `reuse` stages
> (`submit`/`land`/`learn`) it assumes a **local** worktree; recreating one from a remote branch on
> a fresh clone is Phase 2. This closes the spine: `plan → save → implement → submit → land →
> learn`, resumable at any stage.
>
> **Status (P1.T6 — the Phase-1 gate; + T4c/T3b corrections).** The spine is **closed end-to-end and
> dogfooded** — perk shipped a real change (`prek` + a ruff hook) through its own loop on its own
> repo (plan #1 → PR #2 merged → learned; `perk resume 1` reports "nothing to resume"). The gate run
> is recorded in [`phase-1-gate.md`](../docs/planning/phase-1-gate.md). Two dogfood-surfaced fixes
> converged forward: **T4c** — `perk implement [PLAN]` takes a plan arg and `launch_stage` **primes**
> the implement session (it launched bare/idle before); **T3b** — `save` fails fast while plan mode
> is active and the `plan_save` tool (explicit `plan` param) is the canonical save (the borrowed
> `pi-plan` emits no structured plan, so the `<proposed_plan>` scrape was dropped). Neither changed
> any stage's state-I/O. The registry per-stage `requires`/`reads`/`writes` + `doors` are filled for
> all six spine stages.
>
> **Status (P2.T8a):** the **submit body is deepened + the issue-numbered-footer bug is fixed**.
> `perk pr submit` composes an HTML-enhanced GitHub PR body (best-effort verbatim-plan `<details>`
> embed via `get_plan_body`) and appends the checkout footer via **create-then-update**
> (`update_pr_body`) carrying the **PR** number, then runs `validate_pr_body` as a post-write
> self-check (`pr_check_failed` on failure). A thin `perk pr check --json` is the supervisor surface.
> Submit keeps the PR **draft**; the new `perk pr ready` (warm `/ready`) is the deliberate review
> gate. The two-target split is explicit: HTML in the GitHub body, plain text in the squash commit
> (deepened at T8b). `submit`'s registry I/O is unchanged.
>
> **Status (P2.T8b):** `/land` + `/learn` are **deepened**. Land's squash commit message is now
> plain `"<plan title>\n\nCloses #N"` (fallback on empty title) — the second of the two PR targets.
> `/learn` graduates to a real knowledge-capture pass: with a `summary` it creates a `perk:learn`
> issue (idempotent via the **`perk:learn`-scoped `find_learn_issue`** — label + `learn-header`
> block, so it never matches the plan issue) + a back-link comment, then clears `pending-learn`;
> without one it stays the thin marker-clear. `learn` reads `[cache.markers, cache.plan-ref]` and
> writes `[cache.markers, github.learn, github.comments]` (the new `github.learn` key). The
> reconciliation-typing vocabulary (Mechanical/Reconcilable/Immutable) is established; only the
> deterministic **Mechanical** type is applied this turn (Reconcilable + objective reconciliation are
> **implemented in P2.T11** — see the P2.T11 subsection of §8.4).
>
> **Status (P2.T8c — the CLI plumbing slice).** The `--remote` stub graduates to a real **target
> resolver** (`launch.resolve_target(stage, remote) -> Target`, pure + unit-tested): `None` → local
> (unchanged); a `cold_remote:false` stage → `UserFacingCliError`/`remote_blocked`; a
> `cold_remote:true` stage → a `RemoteTarget` descriptor (runner ref + run_id→plan linkage) surfaced
> in `--dry-run`/`--json`, then a stable `UserFacingCliError`/`remote_not_driven` exit (it does **not**
> persist intent or trigger a runner — the Phase-3 consumer is not built, cli-vs-pi §4.5). The
> registry now records `doors.cold_remote: true` on **`implement` + `address`** (the agentic,
> headless-runnable stages a Phase-3 CI worker drives) and `false` on the other five — the reused
> seam = resolver + validated registry doors + the `--json` target descriptor. **Phase 2 builds and
> resolves the target; Phase 3 drives it.** The `--remote` help text on the three launchers is
> reconciled from "Phase 3; currently blocked" to "Local (default) or a remote runner; remote
> dispatch is driven by the Phase-3 worker."

### Authored (P2.T9 — objective storage + mechanics)

The **objective layer's deterministic foundation** — a long-running goal that *generates* bounded
plans (PRIOR_ART §3). The pure mechanics live in `perk/objective.py` (the `plan.py` twin, reusing
its block engine); the GitHub writes live in `perk/github/objectives.py`; the cold-door workers are the
`perk objective` group. **No registry stage and no model-facing tools** — those are T10.

**Storage blocks (perk-namespaced, schema 1).** An objective is an issue + first comment:
- `objective-header` (issue body) — compact, queryable: `{ run_id, created,
  objective_comment_id, status }` (`status` is the explicit objective-level rollup, e.g.
  `"active"`; `objective_comment_id` is backfilled in the two-step create).
- `objective-roadmap` (issue body) — the **canonical** flat-node YAML frontmatter:
  `{ schema_version: "1", nodes: [ { id, slug, description, status, pr, depends_on?, comment? } ] }`.
  Phase membership is derived from the **ID prefix** (`"1.2" → phase 1`, `"2A.1" → phase 2A`); phase
  *names* are not stored (extracted from `### Phase N: name` headers when rendering). `depends_on`
  is `null`/absent (infer sequential deps) vs `[]` (explicitly none). The `depends_on`/`comment`
  columns are omitted from the serialization unless some node specifies them.
- `objective-body` (first comment) — the human-readable rendered roadmap table (marker-bounded by
  `<!-- perk:roadmap-table -->`, deterministically re-rendered from the frontmatter) + prose.

**Explicit-status-only (foundation open #3).** A node's `status` is **never inferred from a PR
column** — `update_node` takes `status` verbatim or preserves it; setting `pr` never changes
`status`. This is the deliberate departure from erk's two-tier infer-from-PR model.

**Gateway ops (canonical Python plane; same idempotency + two-step pattern as plan/learn):**
- `find_objective_issue(*, run_id, repo_root) -> ObjectiveIssue | None` — label-scoped to
  `perk:objective` + the `objective-header` block (delegates to the parameterized `find_plan_issue`).
- `create_objective_issue(*, title, body, repo_root, run_id, status="active", dry_run=False) ->
  ObjectiveIssue` — the **two-step** create: idempotency check → lazy `perk:objective` label →
  compose body (`objective-header` with `objective_comment_id: null` + `objective-roadmap`) → POST
  issue → POST `objective-body` comment (capturing its id) → **backfill** `objective_comment_id`
  into the header.
- `get_objective(*, number, repo_root) -> ObjectiveState | None` — parse header + roadmap nodes;
  `None` if absent, raises on infra failure / invalid roadmap.
- `update_objective_node(*, number, node_id, status=None, pr=None, description=None, repo_root,
  dry_run=False) -> ObjectiveNodeUpdate` — re-render the authoritative `objective-roadmap` block in
  the issue body **and** the rendered table in the `objective-body` comment (best-effort); raises if
  the node is not found.
- `update_objective_header(*, number, fields, repo_root, dry_run=False) -> ObjectiveHeaderUpdate` —
  the `update_plan_header` twin (read-merge-PATCH), rejecting unknown keys (LBYL on
  `OBJECTIVE_HEADER_FIELDS`).

**Cold-door workers (`perk objective …` — a dev/CI/T10 surface, not an agent affordance):**
`create --body @FILE [--title]`, `show NUMBER`, `node NUMBER --node ID [--status][--pr][--description]`,
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
  `.pi/workflow/scratch/learn-docs-inbox.md` (a `## Learning #<n>` section per issue, each body in
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
  env:     [ { name, ok, detail, remediation } ],          # required-tooling checks
  github:  { auth: { ok, user, scopes[], error },          # null when env-not-ready / verify skipped
             repo: { ok, repo, can_push, error } },
  linear:  { ok, team, error,                              # null unless verify ran AND the committed
             readiness: { auth_ok, user, team_ok,          #   [issues] backend is "linear" (§8.21);
                          missing_labels[], created_labels[], error } | null },  # non-fatal like github
  capabilities: string[],                                  # the managed inventory (perk/convergence/capabilities.py)
  changes: string[],                                       # converged/seeded pieces ([] ⇒ already converged)
  handoff: string|null }                                   # path to the post-init markdown on-ramp
```

The **post-init handoff** (`handoff`) is an *agent-readable* markdown at
`.pi/workflow/post-init.md` (gitignored; regenerated each init) — distinct from the §8.1
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

**Groups.** `environment` (tools; missing = `fail`) · `github` (auth/access; non-fatal `warn`) ·
`linear` (verify-gated Linear readiness — auth/team/labels; present only when the committed
`[issues] backend` is `"linear"`; warn-level, the github D3 mirror; `--fix` ensures the four perk
labels — §8.21) · `runner` (remote-runner prereqs; report-only, non-fatal — §8.16) ·
`package` (settings wiring) · `repository` (gitignore/agents blocks + config present/valid) ·
`registry` (the registry self-check) · `skills` (the skills-CLI manifest fragment + the
fail-level `skills-delivery` substrate check — §8.9) · `bindings` / `providers` (rolled-up
non-fatal config checks — §8.9/§8.10) · `issues` (the fail-level `[issues]` selection check:
linear requires a committed `team` — §8.21) · `state` (the `.pi/workflow/` cache layout +
handoff-blob integrity). Managed-piece checks are filtered by `capabilities.applicable(self_repo)`; infra checks
always run. Human render (stderr) follows the three-way condensed rule per group (collapse a clean
group; else expand only its failures/warnings); `--verbose` expands every check.

---

## §8.7 · Cross-plane session-context markers (the selfcheck verifier)

Two pieces of session context are converged by one plane and **read back** by the other, so the
literal markers are a cross-plane contract:

- **`<!-- BEGIN perk managed -->`** — the managed `AGENTS.md` block. `perk init` (Python plane)
  writes it; Pi loads `AGENTS.md` into `contextFiles`; the extension's `/perk-selfcheck` (TS plane,
  `extension/doors/selfcheck.ts`) reads `getSystemPromptOptions().contextFiles` and confirms some file
  carries this marker. Changing the literal in `perk/convergence/init.py` **must** update
  `MANAGED_AGENTS_MARKER` in `extension/doors/selfcheck.ts` in the same turn.
- **`.pi/APPEND_SYSTEM.md`** — the ambient routing index (maintained by `/learn-docs`, never
  `init`). Pi joins it into `appendSystemPrompt`; selfcheck confirms the on-disk content reached the
  prompt verbatim (a trimmed-substring probe).

The division of labor: **`perk doctor` checks the disk** (files converged); **`/perk-selfcheck`
checks the prompt** (the converged context actually reached the model via Pi's
`getSystemPromptOptions()`, available only on a command context). selfcheck logs only derived
booleans/counts — never the raw prompt text (the options expose the full system prompt).

The `.pi/workflow/.perk-t3.json` diagnostics sentinel additionally records **`run_mode`** — Pi's
`ctx.mode` (`tui`/`rpc`/`json`/`print`) — distinct from the workflow **`mode`** (`read-only`/
`read-write`) that drives tool gating. `run_mode` is observability `ctx.hasUI` (a binary) can't
express; it is written from `ctx.mode` on both `session_start` and `session_tree`.

---

## §8.9 · Skill bindings (the trigger→skill delivery contract)

The **second parsed cross-plane contract**, `shared/bindings.yaml` (sibling of `registry.yaml`),
maps a **trigger** to a **skill** plus a per-binding delivery **mode**. It is bundled automatically
via the `shared/` force-include (wheel → `perk/_shared/`, npm tarball → `shared/`) and read by both
planes through independent readers: **`perk/substrate/bindings.py`** (`load_bindings` / `validate`, returning
`BindingSet`/`Binding` + the shared `Issue`/`Severity` findings, raising `BindingsError` only for
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

**Shipped default set (all 8 perk skills, all `nudge` — perk's own skills are ambient package
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

**Validation depth (shape-only, registry-free):** the loaders/validators check that
`schema_version == 1` (else a structural load error), each binding has a non-empty `skill`, a
`mode ∈ {nudge, transclude}`, and a `trigger` that parses as `<kind>:<id>` with a known `kind` and a
non-empty `<id>`, and that no `trigger` repeats. They do **not** check that a `stage:`/`command:`
target actually exists — that cross-contract, target-existence validation is **`doctor`**'s job.

**Resolver — `shipped-defaults ⊕ user-bindings` (Node 1.2, pure + unit-tested both planes):** a
user **skill-binding overlay** is authored in `.pi/perk.toml` as a `[[bindings]]` array-of-tables
(`trigger`/`skill`/`mode` strings); `.pi/perk.local.toml` overlays it with a **whole-array replace**
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
check (`perk/convergence/doctor.py::_bindings_check`) over the **full resolved set** (`resolve_bindings(user,
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
  happened). After a successful sync, every `PERK_SKILLS` name must pass
  `bindings.is_skill_installed` — a sync that delivers nothing (e.g. an outdated `skills` CLI) is
  the same fatal failure, never a silent pass.
- **`doctor` check:** a fail-level **`skills-delivery`** check (group `skills`, evaluated under
  `verify` only — it shells git + validates external-CLI outcomes). Fail conditions, first match
  wins: (a) tracked content under the managed pathspecs (a `GitError` degrades to `warn`, no
  silent pass); (b) the perk fragment (`.agents/manifest.d/perk.yaml`) exists but
  `.agents/manifest.yaml` does not (`skills init` failed or never ran, so `skills update --sync`
  can never run); (c) any `PERK_SKILLS` name not installed per `bindings.is_skill_installed`.
- **`doctor --fix`:** the repair-gesture sync's failure message is carried on
  `DoctorReport.fix_errors` (rendered loudly; `fix_errors` in the `--json` report — §8.6); the
  post-fix re-verify keeps the failing `skills-delivery` check so the exit code reflects the
  still-broken state.

> **Status (Node 3.1):** `doctor` target-existence/skill-presence validation landed (the non-fatal
> `bindings` check), plus the injection-time skill-presence mirror (the `nudge` path warns;
> `bindingSuffix` now logs its warnings). Deferred: `init` `[[bindings]]` commented template + user
> docs → **Node 3.2**.

> **Status (Node 2.3):** cold-door (Python) **and** warm-door (TS) delivery landed, **and** perk's own
> hardcoded "Follow the … skill" strings are migrated onto the mechanism + deleted (Node 2.3) — the
> skill-binding mechanism is now the single delivery path for perk's own nudges. The render header
> was neutralized to `"The following skill binding(s) apply here:"` (the `.pi/perk.toml` parenthetical
> was false for the delivered perk defaults). Known residual (out of scope, documented): in a cold
> `learn-docs` session, after compaction Mechanism A re-renders the borrowed `stage:plan` and injects
> `perk-plan` rather than `perk-learn-docs` — benign (learn-docs *is* a planning factory); a
> pre-existing stage-vs-command `binding_trigger` quirk. Deferred: `doctor` target-existence
> validation → **Node 3.1**; `init` `[[bindings]]` template + user docs → **Node 3.2**.

> **Status (Node 3.2):** the `init` `[[bindings]]` commented template + user docs landed, resolving
> the deferral above. `PERK_TOML_TEMPLATE` now seeds a comment-only `[[bindings]]` block documenting
> `trigger` / `skill` / `mode` and the nudge-vs-transclude choice; `PERK_LOCAL_TOML_TEMPLATE` records
> the whole-array-replace override rule. README gains a `## Skill bindings` user section. The seeded
> block is inert (comment-only) — a fresh repo still resolves to zero user bindings and `doctor`
> stays exit-0 (pinned by a `tests/test_config.py` regression).

## §8.10 · Provider selection (the supported-set registry + the `[providers]` selection)

The **third parsed cross-plane contract**, `shared/providers.yaml` (sibling of `registry.yaml`
and `bindings.yaml`), is the **supported set** — the catalog of plan/todo/askuser/footer/web *providers* perk
knows how to wire — distinct from the per-repo **selection** (a flat `[providers]` table in
`.pi/perk.toml`, which is just a pointer into the catalog). It is bundled automatically via the
`shared/` force-include (wheel → `perk/_shared/`, npm tarball → `shared/`) and read by both planes
through independent readers: **`perk/substrate/providers.py`** (`load_providers` / `validate` /
`resolve_providers`, returning `ProviderSet`/`Provider` + the shared `Issue`/`Severity` findings,
raising `ProvidersError` only for structural failures) and **`extension/substrate/providers.ts`**
(`loadProviders` + the pure `resolveProviders`, returning `ResolvedProviders { plan, todo, askuser, footer, web, issues }`
with `issues` as **`string[]`** — the TS plane has no `Issue`/`Severity`). The Python plane is the
authoritative validator. The
design is locked in `docs/design/adapter-architecture.md` (Node 1.3), over
`docs/design/provider-contract.md` (the seven dimensions; the `cache.plan-ref` `provider` field ==
the plan provider id) and `docs/design/pluggability-taxonomy.md` (the C3 behavior-preserving
default).

**Provider entry shape — `{ id, seam, package, adapter, default, package_filter? }`:** `id` is the
stable provider id (for the `plan` seam, exactly the `cache.plan-ref` `provider` string); `seam ∈
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
see the Node 2.3 status note) and the **todo** seam (perk's `checkpoints` **defers at runtime** under
a foreign `[providers] todo` selection — Node 3.1 — with **no** registration-time vacating, because
the todo seam has no command-name collision; the `todoAdapterJuicesharp` shim carries perk's
progress discipline onto the foreign overlay — see the Node 3.2 status note). The **askuser** seam is an **interface seam** — see the askuser status
note below. A fourth reference entry `perk-footer` (seam `footer`, `package: null` / `adapter: null` /
`default: true`) plus two **real** foreign footer providers `powerline-footer` (→ `npm:pi-powerline-footer`)
and `pi-bar-footer` (→ `npm:pi-bar`) make the **footer** seam a **second interface seam** (vacate-only,
`adapter: null`) — see the footer status note below. A fifth reference entry `pi-web-access` (seam
`web`, **`package: "npm:pi-web-access"`** — the first non-null-package default — / `adapter: null` /
`default: true`) plus two **real** foreign web providers `ollama-web-search` (→ `npm:@ollama/pi-web-search`)
and `juicesharp-web-tools` (→ `npm:@juicesharp/rpiv-web-tools`) make the **web** seam a **third interface
seam** (vacate-only, `adapter: null`) — see the web status note below. The **default** path (the reference providers) is unaffected and is the hard guarantee.

**`cache.plan-ref.provider` is the issue backend, not the seam id.** Despite
`docs/design/provider-contract.md` framing the `cache.plan-ref` `provider` field as the plan
provider id, today it is the **issue backend** (`"github"`) — `perk/run/launch.py` branches on
`provider == "github"`. The stamp sites (`plan_save_cmd.py` / `resume.py`'s
`reconstruct_plan_ref` callers) no longer hardcode the `"github"` literal: the field is stamped
from the **resolved issue backend's `backend_id`** (§8.21) — still the issue backend, still ≠
the seam id. That "id == provider field" equivalence is aspirational; Node 2.2 does **not**
restamp it (restamping would break `launch.py`'s backend branching). `cache.plan-ref` is
untouched by the plan-seam deferral.

**Validation depth (shape-only, repo-free):** the loaders/validators check that
`schema_version == 1` (else a structural load error), each provider has a non-empty unique `id`, a
`seam ∈ {plan, todo, askuser, footer, web}`, and that **exactly one `default: true`** exists per seam. They do **not**
check that any repo *selection* names a real provider — that cross-file validation is **`doctor`**'s
job (mirroring how bindings target-existence lives in doctor, not the loaders).

**The `[providers]` selection — flat string table in `.pi/perk.toml`:** a per-repo selection with
one key per seam (`plan` / `todo` / `askuser` / `footer` / `web`), values are **bare provider-id strings** (the TS narrow-TOML
reader `parseTomlSubset` reads string values only; richer structure lives in `providers.yaml`).
Both planes parse it raw (`perk/substrate/config.py` → `Config.providers`; `extension/substrate/config.ts` →
`PerkConfig.providers`); resolution against the supported set is `init`/`doctor` in Python and the
`extension/substrate/providers.ts` `resolveProviders` resolver in TS (added Node 2.2, consumed by `planMode`). An **absent table or absent key → the seam's
`default: true` provider** (zero behavior change, the no-config default). `perk.local.toml` overlay
wins (standard local-override precedence). The pure resolver
`perk.substrate.providers.resolve_providers(selection, providers)` returns `ResolvedProviders { plan, todo,
askuser, footer, web, issues }`: an absent key falls back to the default **silently**; an unknown id or a seam mismatch
falls back to the default and records a **loud-but-non-fatal** `Issue`.

**`perk init` two-directional settings wiring:** provider wiring composes on top of the static
`_desired_packages` (perk + `BORROWED_PACKAGES`: `npm:@tombell/pi-diff`,
`npm:pi-subagents`) layer within the same `_converge_settings` body — `npm:pi-web-access` is **no
longer borrowed** (#529): it is the `web` seam's `default: true` provider, converged via the
provider path (see the web status note), so a default repo still installs it but deselecting `web`
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

**Validation (`doctor`):** `perk doctor` adds one **`providers`** check (`perk/convergence/doctor.py::
_providers_check`). A `ProvidersError` on the *bundled* file is a `fail` (cannot occur in a healthy
install; "Reinstall perk"); an `ERROR` shape `Issue` on the bundled file is a `fail`. The repo
selection is resolved against the supported set and any resolver `issue` (unknown id / seam
mismatch) is a single **`warn`** (loud-but-non-fatal — `perk doctor` stays exit-0 over a selection
typo), remediation pointing at `.pi/perk.toml [providers]` / `perk init`. There is **no** separate
package-wired / orphan check — that drift is owned by the `settings-wiring` managed convergence
(which `doctor` already dry-runs); `_providers_check` owns only what convergence cannot repair (an
invalid bundled file, a selection naming a non-existent / wrong-seam provider).

**`[compaction]` → `settings.json` `compaction` convergence (init-owned, #206):** a `[compaction]`
table in `.pi/perk.toml` tunes pi's **interactive** global auto-compaction for `perk <stage>`
sessions by converging into the committed `.pi/settings.json` `compaction` object (pi reads that
natively at session boot). It is **Python-plane-only** — the extension never reads it (pi consumes
`settings.json` itself), so `extension/substrate/config.ts` is untouched. Three snake_case keys map to pi's
camelCase `settings.json` keys: `enabled`→`enabled`, `reserve_tokens`→`reserveTokens`,
`keep_recent_tokens`→`keepRecentTokens`. Validation is LBYL silent-omit (mirrors `[providers]`):
`enabled` kept only if a real `bool`; the token keys kept only if `int` (not `bool`) and `> 0`;
ill-typed/absent keys are dropped (pi fills defaults). The convergence composes inside
`_converge_settings` (`perk/substrate/config.py::parse_compaction_table` + `load_committed_compaction`,
`perk/convergence/init.py::_converge_compaction`), so it stays in the `settings-wiring` `ManagedConvergence` —
`doctor` dry-runs/fixes it for free, **no** new check. **Committed-only read** (the deliberate
divergence from `[providers]`' overlaid `load_config` read): `[compaction]` is read from committed
`.pi/perk.toml` **only**, never the `perk.local.toml` overlay, so the committed `settings.json`
stays a deterministic function of committed config (no stray per-user git diff). Per-user overrides
belong in pi's native global `~/.pi/agent/settings.json` (pi merges it under project settings).
**Write semantics are non-destructive write-when-present / leave-when-absent:** when `[compaction]`
is present, its mapped keys merge over any existing `settings.json` `compaction` dict (perk keys
win; unrelated hand-added keys survive; unspecified keys are left to pi's defaults); when
**absent**, `settings.json` is left untouched (perk cannot prove ownership of a bare `compaction`
key, so removal is unsafe — removing `[compaction]` from `perk.toml` leaves a stale block to clean
up by hand). A malformed-TOML error defers to the config check (treated as empty here, mirroring
`_converge_provider_packages`). perk's headless worker (`compaction: { enabled: false }`) and the
objective threshold compaction (`[objective] compact_threshold`) are orthogonal and unaffected.

> **Status (Node 2.1):** ships the selection **substrate** only — `shared/providers.yaml`, the two
> shape-only loaders + the pure resolver, the `[providers]` config-reading in both planes, the
> two-directional `init` wiring, and the `doctor` selection cross-check. The concrete adapter shims
> (`planAdapterTombell`, `todoAdapterJuicesharp`) are **Nodes 2.3 / 3.2**; the read-only tool-gate
> (`extension/substrate/toolGating.ts`, Invariant 1) is untouched.
>
> **Status (Node 2.2):** lands the TS resolver (`resolveProviders`) and the **plan-seam runtime
> deferral** — perk's `planMode` authoring surface (`/plan`, `Ctrl+Alt+P`, `--plan`, the
> `perk:plan-context` injection) steps aside when the resolved `[providers] plan` ≠ `perk-plan`
> (fail-safe to the reference). `savePlan`/`plan_save`/`/plan-save`/the read-only gate are
> seam-shared substrate — always-registered, the produced-contract landing the Node 2.3 adapter
> bridges to — and do **not** defer. The **todo**-seam deferral (`checkpoints`) is still **Node 3.1**.
>
> **Status (Node 3.1):** lands the **todo-seam runtime deferral** — perk's `checkpoints` reference
> surface (`session_start`/`session_tree`/`turn_end` render + the `/checkpoints` command) steps
> aside when the resolved `[providers] todo` ≠ `perk-checkpoints` (`resolvedTodoProviderId` /
> `isPerkCheckpointsReferenceSelected`, fail-safe to the reference) — the exact todo-seam mirror of
> the Node 2.2 plan-seam deferral: silent early-returns on the event handlers, an announced deferral
> on `/checkpoints`. The pure checkpoint helpers + the `perk:checkpoint` entry + `## Steps` seeding
> are seam-shared substrate (untouched). **Runtime** deferral only — the concrete
> `@juicesharp/rpiv-todo` adapter is **Node 3.2** (which, per Correction 1 below, adds **no**
> registration-time vacating: the todo seam has no command-name collision, so runtime deferral is
> already sufficient — the forward-assumption here that registration-time vacating would be needed
> turned out not to transfer from the plan seam).
>
> **Status (Node 2.3):** the **first 3rd-party plan adapter** lands `tombell-plan` as a real,
> selectable plan provider. (1) The shipped entry drops `package_filter` (the illustrative
> `extensions/*.ts` matched nothing — `@tombell/pi-plan`'s sole extension is its root `index.ts`,
> so omitting the filter loads exactly that one extension); the `package_filter` field stays in the
> vocabulary for future providers. (2) perk's plan surface now **vacates at REGISTRATION time** (not
> just handler-time): `registerPlanMode` resolves the plan provider once at factory time and, under a
> foreign selection, registers NONE of `/plan` / `Ctrl+Alt+P` / `--plan` / the injection — so the
> foreign surfaces are the sole registrants (Pi suffixes duplicate command names, so handler-time
> deferral alone is insufficient once the foreign package is loaded). Fail-safe to the reference
> registers everything. (3) The new `extension/adapters/planAdapterTombell.ts` shim is an **injection-only**
> bridge — always registered, inert unless `[providers] plan = "tombell-plan"`, injecting a hidden
> `perk:plan-adapter-tombell` context that directs the foreign free-form prose `/plan` output into
> perk's canonical save. The prose→plan-ref bridge **reuses the existing** `/plan-save`
> `extractPlanMarkdown` scrape (planSave.ts); no new save machinery. The shim **never** owns or
> duplicates the read-only gate and **never** calls `setActiveTools` (Invariant 1 — the gate stays
> perk's, engaged by the cold-door launch; the foreign package self-enforces ad-hoc). (4) The adapter
> does **NOT** restamp `cache.plan-ref.provider` — a tombell-authored prose plan lands with
> `provider="github"` exactly like a perk-authored plan; the authoring-provider id lives only in the
> `[providers] plan` selection, and all downstream stages bind only to the provider-agnostic
> plan-ref (unchanged).
>
> **Status (Node 2.6):** the tombell bridge context is **re-aimed to review-first**
> (`plan_draft` → `plan_review` → the first-party in-TUI review → `approvalSave` auto-save), with
> the present + `/plan-save` flow as its explicit fail-open arm (see §8.10's interactive save
> discipline). The injection is now **conditioned** — it fires only when perk's gate is read-only
> (per the persisted `perk:workflow-state.mode`) **or** tombell's own persisted `plan-mode-state`
> entry has `enabled: true` (latest wins), and never in an objective-author session — replacing
> Node 2.3's unconditional-on-selection injection.
>
> **Status (Node 3.2):** the **first 3rd-party todo adapter** lands `juicesharp-todo` as a real,
> selectable todo provider (no longer illustrative); the todo seam is **behavior-complete**. (1) The
> shipped entry carries no `package_filter` (single-concern checklist overlay — mirrors the tombell
> case). (2) **NO registration-time vacating** (an explicit deviation from the Node 3.1
> forward-assumption): the plan seam needed it only because perk and `@tombell/pi-plan` both register
> `/plan` (Pi suffixes duplicate names); the todo seam has **no command-name collision** — perk
> registers `/checkpoints`, the foreign overlay registers its own differently-named command(s) — so
> Node 3.1's runtime deferral is already sufficient. (3) The new
> `extension/adapters/todoAdapterJuicesharp.ts` shim is an **injection-only**, **active-workflow-gated**
> (`active_plan_ref != null`) bridge — always registered, inert unless `[providers] todo =
> "juicesharp-todo"`, injecting a hidden `perk:todo-adapter-juicesharp` context that carries perk's
> implement-progress **discipline** (seed from `## Steps`, mark each item complete in order) onto the
> foreign overlay. (4) It does **NOT** write `perk:checkpoint` or revive the deferred marker scanner
> (Correction 2): that entry is a transient TS-only overlay nothing downstream consumes, and perk's
> render + scanner are already deferred (Node 3.1), so re-populating it would be dead duplication —
> the lighter bridge the todo seam's lack of a downstream consumer permits. The shim **never** owns
> the read-only gate, **never** `setActiveTools`, and **never** restamps any provider field.
> Validation record: `docs/design/provider-smoke-juicesharp-todo.md`.
>
> **Status (plannotator-plan):** the **second 3rd-party plan adapter** lands `plannotator-plan`
> (→ `npm:@plannotator/pi-extension`, `adapter: planAdapterPlannotator`) — the first provider with
> the **AUGMENT posture** (contrast tombell's REPLACE posture). (1) Plannotator does **not** replace
> perk's plan surface: perk's `/plan` command, the `perk:plan-context` authoring injection, and the
> read-only gate **stay registered**; `registerPlanMode` is now a **three-tier** branch — full
> registration for `perk-plan` (and the fail-safe error path), a **partial vacate** under
> `plannotator-plan` (skip only the `--plan` flag + the `Ctrl+Alt+P` shortcut + the `--plan`
> session_start handler — the two real registration collisions; duplicate flag/shortcut
> registration is the potentially-fatal Pi behavior), and the full vacate for any other foreign id
> (tombell, unchanged). (2) **`plan_review` is the backend-neutral review door** (Node 2.5,
> `extension/factories/planReview.ts`): the `plan` param is **optional/fallback** — the reviewed plan
> resolves **file-first** via `resolvePlanSource` (the validated `plan-draft.md` artifact → the
> param; the **transcript tier is explicitly excluded from review** — no draft + no param
> soft-skips with `reason: "no_plan"` and a `plan_draft` redirect, since an approval would
> otherwise auto-save scraped conversation bytes). **Dispatch:** when `plannotator-plan` is
> selected the door runs the **event-bus bridge** (`createPlannotatorBridge`, kept in
> `extension/adapters/planAdapterPlannotator.ts`): it emits plannotator's published `plannotator:request`
> plan-review envelope on the in-process `pi.events` bus (pinned against
> `@plannotator/pi-extension@0.20.0`), awaits the in-payload `respond` handshake bounded at 5s,
> then awaits the human decision on `plannotator:review-result` (no decision timeout; honors the
> turn-abort signal). On **ANY other selection** (perk-plan, tombell, unknown ids) the door runs
> the **first-party in-TUI editor review** (`runFirstPartyReview`): the plan is displayed in pi's
> built-in `ctx.ui.editor` dialog (scrollable; Ctrl+G opens the user's external `$EDITOR`); a
> non-blank human edit differing from the displayed plan is **written back to the draft via
> `writePlanDraft` BEFORE the verdict** (reviewed bytes == artifact bytes == saved bytes — a
> failed write-back **aborts the review fail-open** with a loud `unavailable` warning, nothing
> saved); then a 3-option approve/deny/skip `ctx.ui.select` verdict, with optional deny feedback
> via a second editor dialog. **Esc anywhere = fail-open skip** (`reason: "dismissed"`,
> mirroring `ask_user_question`'s dismissal — deny is always explicit); `ctx.ui.editor` takes no
> AbortSignal, so `signal?.aborted` is checked between dialogs (the aborted arm wins over an
> in-flight dialog's result). An **APPROVED** decision (either backend) wires into the
> **`approvalSave` seam** (auto-save → D1a gate exit on success → a **terminating** result; on
> the first-party path the saved bytes carry any write-back edits and the result flags
> `edited: true`; the objective node link is recovered from the `objective_node_claim` carrier
> inside `savePlan`; a failed save is non-terminating, leaves the gate read-only, and directs
> the human `/plan-save` failsafe). A human **DENY** is strict: feedback returned with a
> directive to rewrite the working draft via `plan_draft` + re-review. **The objective-author
> arm (#352 Node 2.2):** in an objective-author session the door routes to
> `executeObjectiveReview` — the review subject is the **rendered objective draft** (§8.1's
> `readObjectiveDraft` + `renderObjectiveDraft`; the `plan` param is decoded first — a mistyped
> param still `bad_input` — but never a source), dispatched to the same backends; the
> first-party editor runs **view-only** (edits are never written back — deny+feedback is the
> change channel) with objective verdict labels. An **APPROVED** outcome (#352 Node 2.3) wires
> into the **`objectiveApprovalSave` seam** (the structured artifact is re-read at save time —
> never the rendered bytes → `saveObjective` → D1a gate exit on success): a successful save is a
> **terminating** result (`details.subject: "objective"`, `saved: true`, `gateExited`,
> `terminate: true`); a failed save is non-terminating, leaves the gate read-only, and directs
> the human `/objective-save` failsafe.
> **Fail-open semantics:** headless (`!ctx.hasUI`) / dismissed / handshake-timeout /
> `unavailable` / `error` all **soft-skip** with a result instructing the model to present the
> plan to the user directly — plan authoring never wedges. `plan_review` is in
> `READ_ONLY_TOOLS` so review happens **inside** plan mode, before the gate ever comes off.
> (3) The plannotator adapter shim is **injection-only again** (Node 2.5): it owns the hidden
> `perk:plan-adapter-plannotator` context (gate-active AND selected; **two content flavors, one
> customType** — the plan bridge context, or `OBJECTIVE_ADAPTER_PLANNOTATOR_CONTEXT` in an
> objective-author session, whose marker `[OBJECTIVE ADAPTER: PLANNOTATOR]` the strip handler
> also covers)
> plus the bridge core, and otherwise keeps the standard adapter hygiene: never
> `setActiveTools`, never a `tool_call` handler, never restamps `cache.plan-ref.provider` (stays
> `"github"`); the door composes the gate and the save **only** through the `approvalSave` seam
> (never owns the gate, never writes GitHub itself). The catalog entry carries no
> `package_filter` (`pi.extensions: ["./"]` — the sole extension is the package root).
>
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
>
> **Status (askuser — the third seam, an INTERFACE seam):** a third seam, **`askuser`**, lets a repo
> swap perk's first-party `ask_user_question` tool (`extension/doors/askUser.ts`) for the foreign
> `@juicesharp/rpiv-ask-user-question` extension, which registers a tool with the **identical name**
> `ask_user_question` (a richer multi-question dialog). (1) **Interface seam, not artifact seam:**
> ask-user produces **no** durable state key or session-entry vocabulary (no `cache.plan-ref` /
> `perk:checkpoint` analogue); its stable contract is the **tool name `ask_user_question` + its
> non-terminating-answer semantics**. (2) **Vacate-only adapter** (`adapter: null` in
> `providers.yaml`, **no shim module**, no injected context): the foreign tool self-documents via
> its own `promptGuidelines`, so there is nothing to bridge. (3) **Registration-time vacating** in
> `registerAskUser` (mirroring the plan seam's `registerPlanMode`): because the foreign tool shares
> the **exact** name `ask_user_question` and tools — unlike commands — are **not** `:N`-suffixed
> (they replace/warn by extension load order, non-deterministically), `registerAskUser` resolves the
> provider id once at factory time (`resolvedAskUserProviderId(process.cwd())`, fail-safe to
> `perk-ask-user`) and **early-returns before `pi.registerTool`** under any foreign selection,
> leaving exactly one `ask_user_question` standing. The default/fail-safe path registers exactly as
> before (zero behavior change). (4) The foreign package is **two-directionally** wired by
> `_converge_provider_packages` (installed only when selected, removed on deselect), so under the
> default the foreign package is never loaded and perk's tool is the sole registrant. (5) **No
> `READ_ONLY_TOOLS` / `SDK_READ_ONLY_TOOLS` change:** `ask_user_question` is already in
> `READ_ONLY_TOOLS` (`extension/substrate/toolGating.ts`), so the foreign same-named tool is
> allowlisted in read-only/plan mode automatically (the shared-name allowlist precedent); the
> read-only notice interpolates `READ_ONLY_TOOLS` so it self-updates. `SDK_READ_ONLY_TOOLS`
> (`extension/worker/readOnlySession.ts`) intentionally does **not** include `ask_user_question`
> (headless children never prompt a human) — unchanged. Catalog entry carries no `package_filter`
> (verified manifest `{"extensions": ["./index.ts"]}`). Validation record:
> `docs/design/provider-smoke-juicesharp-ask-user.md`.

> **Status (footer — the fourth seam, a SECOND INTERFACE seam):** a fourth seam, **`footer`**, lets a
> repo swap perk's own footer (`installPerkFooter`, `extension/surfaces/surfaces.ts`) for a foreign
> footer package — either `powerline-footer` (→ `npm:pi-powerline-footer`) or `pi-bar-footer`
> (→ `npm:pi-bar`). (1) **Interface seam, not artifact seam** (mirrors askuser): the footer produces
> **no** durable state key or session-entry vocabulary; its “contract” is purely the rendered footer
> surface. (2) **Vacate-only adapter** (`adapter: null` for **both** foreign entries, **no shim
> module**, no injected context): both foreign footers already **render extension statuses**, so
> perk's composed `perk` `setStatus` slot (the objective + checkpoints segments, published
> unconditionally by `createPerkStatus`/`checkpoints.ts` independent of footer ownership) appears in
> the foreign footer automatically — the bridge is automatic, there is nothing to shim. (3)
> **Install-site (runtime) vacating, NOT registration-time vacating** (the key divergence from
> askuser/plan): perk installs its footer inside the `session_start` event handler (not at
> factory-bind), so the natural mechanism is a **runtime guard at that single install site, keyed off
> `ctx.cwd`** — `index.ts` calls `installPerkFooter` only when
> `isPerkFooterReferenceSelected(ctx.cwd)` (`extension/surfaces/footerProvider.ts`,
> `resolvedFooterProviderId` fail-safe to `perk-footer`). The easier tier: `ctx.cwd` flows through the
> event, so tests need no `process.chdir`. (4) The foreign package is **two-directionally** wired by
> `_converge_provider_packages` (installed only when selected, removed on deselect), so under the
> default (`perk-footer`) the foreign package is never loaded and perk owns the footer exactly as
> before (zero behavior change — the hard guarantee). (5) **No `surfaces.ts` change:** `perkFooter` /
> `installPerkFooter` stay the reference footer; the only change is whether `index.ts` calls it.
> Catalog entries carry no `package_filter` (each package ships a single footer extension).

> **Status (web — the fifth seam, a THIRD INTERFACE seam with a NOVEL foreign default):** a fifth
> seam, **`web`**, lets a repo swap its web-research provider among three packages: `pi-web-access`
> (the **default** — zero-config Exa search + content fetch + the bundled `librarian` skill,
> exactly today's behavior), `ollama-web-search` (→ `npm:@ollama/pi-web-search`, needs a local
> Ollama daemon) and `juicesharp-web-tools` (→ `npm:@juicesharp/rpiv-web-tools`, needs an API key;
> default provider Brave; registers a `/web-tools` command — no perk collision). (1) **Interface
> seam, not artifact seam** (mirrors askuser/footer): web produces **no** durable state key or
> session-entry vocabulary; its “contract” is the loose “web search + fetch capability is
> available”. (2) **The NOVEL property — the first non-null-package default:** perk owns **no**
> native web implementation, so the behavior-preserving reference (`pi-web-access`) is itself a
> **foreign npm package** — its `default: true` entry carries a **non-null `package`** (every prior
> seam's default was `package: null`). This needs **no** substrate change: `_converge_provider_packages`
> already builds `desired` from every resolved provider's truthy `package` and the managed-identity
> set from every non-null `package`, and `validate()` enforces only exactly-one-default-per-seam
> (it never required a default to be `package: null`). (3) **Vacate-only adapter** (`adapter: null`
> for **all three** entries, **no shim module**, no injected context) with **no surface to vacate**
> at all: perk registers **no** web tools of its own, so unlike askuser (registration-time vacating)
> or footer (install-site vacating) there is **nothing** to step aside — selection simply **swaps**
> which web package `_converge_provider_packages` installs. The entire seam is Python convergence +
> the census widening + the read-only allowlist. (4) **Static union allowlist, no normalization:**
> the three packages expose **divergent** tool names (`web_search`/`code_search`/`fetch_content`/
> `get_search_content` vs `ollama_web_search`/`ollama_web_fetch` vs `web_search`/`web_fetch`), and
> perk does **not** normalize them — `READ_ONLY_TOOLS` (`extension/substrate/toolGating.ts`) carries
> the **union** of all known web tool names, inert when a package is absent (the shared-name
> allowlist precedent). `SDK_READ_ONLY_TOOLS` (`extension/worker/readOnlySession.ts`) intentionally
> omits them (headless children) — unchanged. (5) The foreign package is **two-directionally** wired
> by `_converge_provider_packages` (installed only when selected, removed on deselect); under the
> default the committed `npm:pi-web-access` entry stays installed (now **provider-managed**, no
> longer in `BORROWED_PACKAGES`). (6) **`librarian` is accepted as lost under a foreign web
> selection** — it is pi-web-access-specific (it depends on `fetch_content`'s GitHub-clone path),
> documented and not re-homed. Catalog entries carry no `package_filter` (each package's sole
> extension is its root `./index.ts`, verified via `npm view <pkg> pi`).

## §8.11 · The headless stage-drive worker contract (Node 1.2)

The **stage-drive primitive** (`extension/worker/worker.ts` `driveStage`) drives ONE read-write stage
(`implement`/`address`) end-to-end on an **already-prepared** worktree, in-process via the SDK
runtime factory, running the **same** `@perk/pi` extension package. It is the substrate Node 1.3
(the structured event stream) and Node 4.1 (the e2e harness) consume. This section locks the
worker's inputs, determinism invariants, terminal-signal definition, and outcome shape (the full
audit is `docs/design/headless-worker.md`, Node 1.1). The worker makes **no GitHub mutation of its
own** — the stage's own tools (`submit`, `resolve_review_threads`) delegate to the Python gateway
exactly as in a warm session (§8.4).

### Inputs (the prepared-worktree contract)

| input | shape | source |
|---|---|---|
| `worktree` | absolute path, already positioned | the cold-door/runner positioning (`perk/run/launch.py`), **not** the worker (Gap 7) |
| `stage` | `"implement" \| "address"` | the only `doors.cold_remote: true` read-write stages (`shared/registry.yaml`) |
| `run_id` | ULID, present as `PERK_RUN_ID` in env | minted by positioning; the worker **inherits** it and never re-mints |
| handoff / plan-ref / plan-body | files under `<worktree>/.pi/workflow/` | materialized by positioning; the worker does not re-write them |
| `initialPrompt` | string | re-derived by `initialPromptFor(stage, planRef)` — the TS twin of `perk/run/launch.py._implement_prompt`/`_address_prompt` (parity asserted reciprocally in `extension/worker/worker.test.ts` + `tests/test_worker_prompt_parity.py`); the resolved skill-binding suffix is delivered by the cold door and is **deferred to Phase 2** |
| `model` + `auth` | `Model` + `AuthStorage`/`ModelRegistry` | explicit worker input, else env-var key resolution (`ANTHROPIC_API_KEY` etc., Gap 5); **no model ⇒ a fail-soft `failed`/`no_model` outcome, never a throw** |
| `budget` | `{ maxTurns, maxTokens, wallClockMs }` | worker input; the watchdog that drives abort (Gap 2) |
| `signal` | `AbortSignal` | external cancellation; OR'd with the budget watchdog |

### Determinism invariants (fixed by the worker; not caller-tunable)

- **`cwd = worktree`, `agentDir = throwaway temp dir`** (Gap 4): the project tier loads (perk's
  `@perk/pi` via the managed `.pi/settings.json`, the managed `AGENTS.md`/`APPEND_SYSTEM.md`); the
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
   carrying a `pr` → `completed`/`submit_tool`; for `address`, `resolve_review_threads` ok **and**
   `perk:workflow-state.last_review_batch` appended → `completed`/`address_resolved`.
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
> review-classifier` is set in the worktree's `.pi/perk.toml` (#196), as a per-call inline `model`
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
  `<cwd>/.pi/workflow/scratch/runs/<runId>/events.ndjson` — a **cache-tier** artifact (the
  `.pi/workflow/scratch/` tree is gitignored), co-located with the run's read-only-child scratch.
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
(`perk/run/launch.py` `_drive_remote_target`) + the runner library (`perk/run/runner.py`); the GitHub
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

`DispatchRecord` is persisted at **`.pi/workflow/scratch/runs/<run_id>/dispatch.json`** (the run's
scratch dir — `perk init` already creates `scratch/runs/` and `.gitignore` already excludes
`/.pi/workflow/scratch/`, so no layout/gitignore change). Shape:

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
rides the existing `.pi/workflow/` GC story (§8.1): records live *inside* `scratch/runs/<run_id>/`
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
  `git+https://github.com/mattgiles/perk@v{__version__}` for a consumer), pi (the interior the
  worker drives), the Node worker's peer deps, and a final **git-identity** step (`perk[bot]`,
  `--global`) so the worker's commits succeed on a fresh runner. The worker-deps step is repo-kind
  aware: **self** uses `npm ci` (the self-repo has the `package.json`/lockfile/devDeps the worker
  resolves); **consumer** is a **loud Node-2.4 deferral** (`::error::` + `exit 1`) because the
  consumer worker-clone genuinely cannot exist in CI yet (`.pi/git` + `.pi/npm` are gitignored and
  nothing in the composite runs `pi` to trigger pi's git-package `npm install`).

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
   `extension/workerMain.ts` (`self`), else the consumer git-package clone
   `.pi/git/<host>/<path>/extension/workerMain.ts` (`consumer-git`, derived from `GIT_PACKAGE` so a
   package-URL change cannot desync the resolver), else the consumer npm install under
   `.pi/npm/node_modules/@perk/pi/extension/workerMain.ts` (`consumer-npm`); a miss ⇒
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

### The report-only `runner` check group (`perk/convergence/doctor.py::_runner_checks`)

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
`.pi/workflow/` writes). `cancel`/`retry` (the `run` subgroup's mutating siblings) **shipped** in
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
  `.pi/workflow/` writes in this node.
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
composite setup or the worker/model drive (the consumer worker-deps step is a loud Node-2.2
deferral, so including it would make the smoke self-repo-only) — the `smoke=true` short-circuit keeps
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
contract, Node 1.1; the `GitHubIssueBackend` adapter + resolver in `perk/backends/issues.py`, Node 1.2;
the `LinearIssueBackend` over the `perk/backends/linear.py` GraphQL client, Nodes 2.1–2.3, wired live in
Node 2.4) is **backend-selectable** via one committed config table:

```toml
[issues]
backend = "linear"   # "github" is the default when unset
team = "ENG"         # the Linear team key — required when backend = "linear"
```

**Committed-only read, both planes.** The selection (`backend` AND `team`) is read from committed
`.pi/perk.toml` **only** — never the `perk.local.toml` overlay (Python:
`load_committed_issues_backend` / `load_committed_issues_team`; TS: `resolveIssueBackendId` reads
only the committed file). Rationale: the backend decides where canonical durable state
(plan/learn/objective issues) is *written*; a per-user override would fragment the canonical
store. **`LINEAR_API_KEY` lives in the environment only** — never in config/committed files
(`linear.client_from_env`; matches pi-mono-linear's own auth order, which reads the same var).

**Python is the authoritative validator** (`perk/backends/issues.py::resolve_issue_backend_id`):

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
requirement is missing: no committed `[issues] team` → remediation pointing at `.pi/perk.toml`;
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
| `"linear"` without `team` | `fail` | offline-decidable; remediate: set `[issues] team` in `.pi/perk.toml` |
| anything else | `fail` | `unknown issue backend '<x>'`; fix `.pi/perk.toml [issues]` |
| malformed TOML | `warn` | selection not evaluated — defers to the config check (mirrors `providers`) |

`fail` (not `warn`) for a bad selection is deliberate: unlike `[providers]` (graceful fallback →
warn), a bad `[issues]` selection hard-breaks **every** issue-touching command. Network readiness
is *not* this offline check's job — that is the `linear` group's (below).

**The verify-gated `linear` doctor group** (`perk/convergence/doctor.py::_linear_checks`; present only when
`verify` AND the committed backend is `"linear"`). All warn-level on failure — network readiness
is non-fatal, mirroring the `github` group's D3 discipline. Built from one
`linear_backend.check_readiness(client, team_key, ensure_labels=False)` call (the shared
init/doctor probe — report-shaped, never raises; phases short-circuit auth → team → labels):

- `linear-auth` — ok: `authenticated as <user>`; failure (or missing `LINEAR_API_KEY`): warn,
  remediation "export LINEAR_API_KEY (create a personal API key at linear.app Settings →
  Security & access)".
- `linear-team` — ok: `team <key> found`; failure: warn with the error detail.
- `linear-labels` — all four perk labels present (`perk:plan`, `perk:learn`, `perk:consolidated`,
  `perk:objective`): ok; otherwise warn listing the missing names, remediation "run `perk init`
  or `perk doctor --fix`".

**The `--fix` label repair gesture** (`_fix_linear_labels`, verify-gated like the skills sync —
network I/O, so never a `ManagedConvergence`): when `fix` AND `verify` AND linear is selected AND
key + team are available, `check_readiness(..., ensure_labels=True)` ensures the four labels;
created names land on `fixed` (`Linear: created label perk:plan`), failures on `fix_errors`.
Lookup-first idempotency: a converged workspace reports nothing (the doctor idempotency rule).

**The init readiness step** (`perk/convergence/init.py::_linear_readiness`, verify-gated, non-fatal — the
GitHub D3 mirror: file convergence already succeeded). Only when `verify` AND the committed
backend is `"linear"`: missing key/team degrade to an errored `LinearReport`; otherwise the probe
runs with `ensure_labels=True` (init converges the four perk labels upfront; the lazy write-time
`ensure_label` calls remain the safety net). Created labels are reported through the
`LinearReport` (the `--json` `linear` key, §8.5; the human `✓ Linear: <user>, team <key>` line) —
**never** appended to `InitReport.changes`, which stays a pure filesystem-delta list.

**The `npm:pi-mono-linear` settings convergence** (`perk/convergence/init.py::_converge_linear_package`,
composed inside `_converge_settings` — it rides the `settings-wiring` managed convergence, so
doctor dry-runs and `--fix`es it for free; no new doctor check, no new capability).
Two-directional, mirroring `_converge_provider_packages`: `backend = "linear"` selected → the
unpinned plain-string entry is appended (bundled `linear` skill accepted wholesale — no
`package_filter`); not selected → any entry matching the `pi-mono-linear` identity is **removed**
(perk treats the package as managed by the selection; hand-adding it without selecting linear is
unsupported). A malformed committed TOML defers to the config check (selection treated as absent).

**Backend-aware prompt rendering (Node 3.1).** Every plan-read prompt site branches on
`cache.plan-ref.provider` via the per-plane helpers `perk/run/launch.py::_plan_read_instruction` and
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

**Opaque string issue ids at every machine boundary (Node 4.1).** Issue ids (plan / learn /
objective) are **opaque strings** end-to-end — GitHub's are numeric strings (`"42"`), Linear's
are the human identifier (`"ENG-123"`; the backend resolves identifier→UUID internally for
mutations — `LinearIssueBackend._uuid_for`). **PR numbers stay `int`** under `pr.number`
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
- **Land closure branches per backend.** GitHub keeps the squash footer `Closes #N` (autoclose
  — byte-identical); non-github backends get a plain `Plan: <id> — <url>` footer (no commit
  magic words — Linear's commit-linking needs a non-assumable webhook) **plus** an explicit
  fail-open `close_issue` on the plan issue after the merge (`_close_plan_issue_on_land`,
  surfaced as the envelope's `plan_issue_closed: bool`; idempotent beside any tracker
  Done-on-merge automation).
- The live validation surface is `tests/test_linear_lifecycle.py` (the stateful
  `FakeLinearWorkspace` offline suite) plus the manual live smoke gate runbook
  `docs/linear-smoke-gate.md`.

## §8.22 · Linear agent-session emission (Objective #252, Node 5.1 — stretch)

An **opt-in, fail-soft, one-way** mirror of an implement run into Linear's Agents UI
(`perk/backends/linear_agent.py` — Python-plane only; the warm TS doors delegate to the Python hooks, so
there is no TS twin).

- **The gate** (checked inside every emitter): the worktree's stamped
  `cache.plan-ref.provider == "linear"` (the stamped provider, never config — the Node 3.1 rule)
  **and** a non-empty **`LINEAR_AGENT_TOKEN`** env var. Without the token, behavior is
  byte-identical to today (dormant by default; "additive only").
- **`LINEAR_AGENT_TOKEN` env contract**: an OAuth `actor=app` access token from a user-created
  Linear agent application — a personal `LINEAR_API_KEY` is rejected by Linear's agent API. Sent
  in the OAuth `Authorization: Bearer <token>` header form (`LinearClient(bearer=True)`;
  personal-key requests keep the plain header byte-identically). Environment only — never
  config/committed files. No new config keys, no doctor check — the live smoke doc
  (`docs/linear-smoke-gate.md`) is the verification surface.
- **The file**: `.pi/workflow/agent-session.json` (cache tier, §8.1) —
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
(the `approvalSave` seam + the warm claim carrier), and §8.10 (the plannotator/Node 2.5/2.6 Status
blocks + the interactive save discipline); this section is the one-stop current shape.

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
