# Foundation Open Questions

Decisions that must be settled (or explicitly deferred) before **Phase 0** of
ROADMAP.md begins. Each question records: why it matters, the options, a
recommendation, and a **Resolution** field filled in once we agree.

Status legend: 🔴 **must settle before Phase 0** · 🟡 **cheap confirm** · 🟢 **structural,
unnamed in roadmap but Phase 0 forces it** · ⚪️ **safe to defer** (listed for completeness).

Working through these one at a time; resolutions are recorded verbatim as we agree.

---

## Q1 — State-tiering: session-entry shape 🔴

**Why it matters:** Phase 0's core deliverable is the state-tiering read/write helpers. The
shape of the in-session transient record determines how every command persists and restores
workflow state, and is the direct fix for erk's silently-failing "workflow markers."

**Options:**
- (a) **One namespaced custom entry** (`perk:workflow-state`) holding a small JSON record
  (`mode`, `active_plan_ref`, `active_objective`, `last_review_batch`), rebuilt last-write-wins
  by scanning entries on both `session_start` and `session_tree`.
- (b) Multiple scattered marker entries (erk-style), one per concern.

**Recommendation:** (a) — one namespaced entry. Simpler to reason about, makes "verify by
read-back" trivial, and directly answers erk's silent-marker failure mode.

**Resolution:** **(a) — one namespaced `perk:workflow-state` custom entry**, holding a small
JSON record (`run_id`, `pi_session_id`, `mode`, `active_plan_ref`, `active_objective`,
`last_review_batch`), rebuilt by
scanning entries on both `session_start` and `session_tree`, with **per-field last-write-wins**
(so two tools writing different fields in the same turn don't clobber each other — only the
fields a write actually touches are updated).

Qualifications carefully noted:

- **Why (b) does not transfer.** erk chose scattered single-purpose markers almost entirely
  for environmental reasons perk does not share. Per erk's `docs/learned/planning/workflow-markers.md`,
  erk had **no in-session state store** (Claude Code exposed none), and its workflow steps are
  **separate OS processes** (a hook fires and exits, a command runs and exits, a later hook
  fires), so state had to outlive a process via a file on disk keyed by `CLAUDE_SESSION_ID`.
  Each marker was therefore a **point-to-point handoff between one producer and one consumer**
  (`objective-context` → `plan-save`; `plan-saved-issue` → later ops), and the scattering fell
  out of a generic bash-invoked KV file primitive with no schema pressure to consolidate. perk
  holds session identity and state **in-process** (`ctx` + `appendEntry`), so within a session
  this is cross-*turn* state, not cross-*process* IPC — one consolidated record is strictly
  better.
- **erk documented (b)'s signature failure.** The same doc notes the `objective-context`
  marker "must be created before entering plan mode… If missing, plan-save cannot call
  update-objective-node, and the objective roadmap table **silently fails to update**." That
  silent-loss pathology is exactly what (a) + the verified-linkage rule (Q3) kills.
- **erk consolidated where it had schema control.** For its *durable* tier
  (erk's `docs/learned/architecture/metadata-blocks.md`), erk used structured keyed
  YAML blocks with the explicit best practices "Keep blocks self-contained" and "flat is
  better than nested" — i.e., it chose option (a)'s shape wherever it actually controlled the
  schema. The scattering appears only where it was forced into file-based IPC.
- **Tier-routing caveat (the part of (b) that does *not* vanish).** The cross-process need
  partially survives: the Python CLI must sometimes read workflow state *before* a Pi session
  exists (the cold-door launch in Q4–Q6), and existence-based **friction semaphores** (erk's
  `pending-learn`, which blocks a destructive *exterior* op until cleared — see
  erk's `docs/learned/architecture/markers.md`) are CLI-checked, not in-session. Such
  genuinely cross-process / pre-session / semaphore state lives in the **`.pi/workflow/` cache
  tier (Q2)**, *not* in session entries. Do not try to make `perk:workflow-state` carry
  handoffs it structurally cannot. Q1 governs the session-entry (tier 3) transient state only.
- **Identity fields (see Q2).** The record carries both a perk-owned **`run_id`** (a ULID,
  the cross-tier correlation key and cold-door launch token, delivered via the
  `PERK_RUN_ID` env var and claimed on `session_start`) and the **`pi_session_id`** (Pi's
  own session UUID, minted inside the process and needed for `SessionManager.open` /
  `continueRecent` on resume). Storing the `run_id ↔ pi_session_id` mapping here is what lets
  perk own run lifecycle/GC/scoping independently of Pi's session-tree semantics.

---

## Q2 — State-tiering: `.pi/workflow/` layout 🔴

**Why it matters:** The local cache tier's directory structure is written and read by both
the CLI (exterior) and the extension (interior); it must be fixed before the helpers exist.

**Options:**
- (a) Mirror erk: `plans/` (materialized plan cache) + `scratch/sessions/<id>/` (inter-process
  workflow files).
- (b) A flatter or differently-named layout.

**Recommendation:** (a) — mirror erk's proven structure.

**Resolution:** **(a)-extended.** Layout:

```
.pi/workflow/
├── plans/                 # materialized plan cache (canonical copy stays in GitHub)
├── scratch/runs/<run_id>/ # per-run inter-process workflow files
├── handoff/<run_id>.json  # pre-session CLI→extension cold-door state
└── markers/               # existence-based friction semaphores (pending-learn analogue)
```

This keeps erk's proven `plans/` + per-run scratch, and adds explicit homes for the two
things Q1 routed down to the cache tier (the cold-door handoff and friction semaphores).

**Keying — a perk-owned `run_id`, not the Pi session id:**

- **`run_id` = a perk-minted ULID** (time-sortable → trivial chronological ordering and
  "GC runs older than N" queries). It is simultaneously the **launch token**, the **cache
  key** (`scratch/runs/<run_id>/`, `handoff/<run_id>.json`), and the **correlation key**
  tying together the CLI launcher → handoff blob → session's `perk:workflow-state` entry →
  scratch dir → GitHub event blocks → worker logs.
- **Why not the Pi session id (confirmed against `~/dev/docs/pi/`):** `getSessionId()` is a
  UUID minted by `SessionManager.create()` *inside* the freshly-spawned `pi` process, so at
  cold-door launch time — when `perk <stage>` writes `handoff/…json` and execs `pi` — **no
  Pi session id exists yet**. Pre-session handoff therefore *cannot* be keyed on it. A
  perk-owned id also gives us lifecycle/GC/scoping boundaries we control, independent of
  Pi's session-tree semantics (fork/switch/compact/resume).
- **The Pi session UUID is kept as a secondary handle** (needed for
  `SessionManager.open` / `continueRecent` on resume); the `run_id ↔ pi_session_id` mapping
  is stored in the `perk:workflow-state` record (Q1).

**Launch-token / claim flow (env var — the only clean Pi channel):** Pi exposes no
first-class "pass control data to the extension at launch" flag (only an env var, an initial
message/`@file` which would pollute LLM context, or `--session <id>` to reuse a session). So
the CLI sets **`PERK_RUN_ID=<ulid>`** in the environment before `exec pi`; the extension
reads `process.env.PERK_RUN_ID` on `session_start`, loads + claims `handoff/<run_id>.json`,
records `run_id` in workflow-state, and marks the handoff consumed. Race-free (each launch is
unique by construction) and idiomatic — it is exactly how erk passed `CLAUDE_SESSION_ID` /
`ERK_HOOK_ID=`. (The id is visible in the agent's `bash` env — harmless, it is just an id.)

**Lifecycle / constraint boundaries (confirmed defaults):**

1. **Fork (isolation/subagent) → detect-and-derive a child-scoped id** (`<run_id>.<n>`), so
   the child's scratch is isolated but traceable to the parent. Per the Pi docs, `/fork` /
   `/clone` / `runtime.fork()` create a **new session file with a `parentSession` header**
   pointer (detectable), whereas `/tree` branches *in-place* (same file/UUID/process, so
   `PERK_RUN_ID` in env survives and the run_id stays stable). So the rule is *detect a
   fork/clone/spawn and derive a child id*, **not** blindly inherit the env var (which would
   hand the parent's id to the child). This also fixes erk's "sub-agents can't see the
   session id" wall — we pass a scoped id deliberately.
2. **Warm vs cold transition:** a **warm** in-session stage transition (no relaunch) **keeps**
   the `run_id`; a **cold relaunch** mints a **new** `run_id` that **records its predecessor**,
   so resume/relaunch chains stay traceable.
3. **GC is perk-owned:** prune `scratch/runs/<id>` + `handoff/<id>.json` for runs whose
   terminal stage completed (landed/closed) or older than N days, surfaced as a
   **`perk doctor` check + a prune command**. (erk accumulated session dirs precisely because
   GC was undefined.)

**Rejected alternative (recorded):** pre-create a session via `SessionManager.create()` to
obtain the UUID, write the handoff keyed by it, then launch `pi --session <uuid>`. Possible,
but it **couples perk to Pi's session-file internals and forfeits the lifecycle independence**
the `run_id` buys (the UUID's lifecycle is Pi's). Not adopted.

**Honest cost:** two ids now exist (`run_id` + `pi_session_id`); "which id is this?"
discipline matters — mitigated by storing the mapping and naming consistently.

---

## Q3 — State-tiering: verified-linkage rule 🔴

**Why it matters:** erk's objective↔plan link was a marker that failed silently when not set
at the right moment. Any cross-tier link must be explicit and verified.

**Options:**
- (a) Write-then-read-back-and-check for every cross-tier link (objective↔plan, plan↔branch),
  never fire-and-forget.
- (b) Best-effort writes with logging only.

**Recommendation:** (a) — already the documented lean; keep it.

**Resolution:** **(a), tiered, expressed as a two-part rule.** erk's failure was not only a
missing read-back — it was that the link was written *at the wrong moment* (the
`objective-context` marker had to exist **before** entering plan mode, and nothing enforced
that ordering, so it silently failed; see
erk's `docs/learned/planning/workflow-markers.md`). So verified-linkage means both:

1. **Read-back verification.** After writing a cross-tier link, read it back and assert it
   resolves to the expected target before proceeding; on mismatch raise a **hard, actionable
   error** — never a silent `pass`.
2. **Establish-before-consume ordering.** A stage that *depends* on a link must, at its
   entry, assert the link already exists (LBYL) rather than assume an earlier step set it.
   This is why the Q2 cold-door handoff is **claimed** (read + verified + marked-consumed)
   on `session_start`, not assumed.

**Tiered scope** — concentrate the cost where erk actually got burned:

- **Strict (both parts apply):** durable / canonical / cross-process links — anything
  touching GitHub, the provider-agnostic plan-ref, the `run_id ↔ pi_session_id` mapping, the
  objective↔plan link, and the cold-door handoff claim. Silent loss here is costly and
  hard to detect.
- **Best-effort-with-logging:** purely transient session-entry writes that are cheaply
  reconstructable on the next `session_start` / `session_tree` anyway — no read-back
  round-trip required, but failures are still logged (never silently swallowed).

This keeps every trivial `appendEntry` from becoming a round-trip while making the
canonical/cross-process links that burned erk explicitly verified and correctly ordered.

---

## Q4 — Stage registry: descriptor shape 🔴

**Why it matters:** This is the language-neutral contract that keeps the Python CLI and the
TS extension from drifting. Both planes generate behavior from it, so its shape must be locked
before either plane is built.

**Options:**
- (a) Per stage: `id`, `branch/worktree need`, `reads`, `writes`, `command`, `predecessors`,
  `successors`, `doors {warm, cold-local, cold-remote}`.
- (b) A leaner or richer descriptor.

**Recommendation:** (a) — exactly these fields.

**Resolution:** **(a) expanded.** The Q1/Q2/Q3 decisions surfaced state the registry should
encode directly (rather than retrofit), since both planes read it. Locked descriptor shape:

```
id                                 # stable identifier (Q11 naming; doubles as CLI subcommand)
summary                            # one-line human description
doors: { warm, cold_local, cold_remote }   # which entry doors are legal for this stage
worktree                           # none | reuse | create
mode                               # read-only | read-write  (tool-gating posture; Phase 2 primitive reads this)
requires                           # preconditions asserted at entry (Q3 establish-before-consume), as state keys
reads                              # state-tiering touch points (enumerated state keys)
writes                             # state-tiering touch points (enumerated state keys)
run_id                             # per door: keep | mint   (Q2 warm-keeps / cold-mints-with-predecessor)
command                            # extension command this stage maps to
predecessors                       # legal predecessor stage ids
successors                         # legal successor stage ids
```

`mode`, `requires`, and the `run_id` policy are added beyond the original (a) so that
plan-mode gating (Phase 2), Q3 precondition enforcement, and Q2 run lifecycle all read from
the single source both planes share.

**`reads` / `writes` / `requires` use enumerated state keys, not free-form prose**, drawn
from a fixed vocabulary aligned to the three tiers — so `perk doctor` can mechanically check
registry consistency (every `requires`/`reads` key is produced by some `writes` upstream; no
stage reads state nothing writes):

| Tier | State keys |
|---|---|
| **1 · GitHub (canonical)** | `github.plan`, `github.objective`, `github.pr`, `github.labels`, `github.comments`, `github.review-threads` |
| **2 · `.pi/workflow/` (cache)** | `cache.plan` (materialized body), `cache.plan-ref`, `cache.scratch`, `cache.handoff`, `cache.markers` |
| **3 · session entries (transient)** | `session.workflow-state` (the `perk:workflow-state` record: `run_id`, `pi_session_id`, `mode`, `active_plan_ref`, `active_objective`, `last_review_batch`) |

The vocabulary is extensible (add keys as stages are added in Phase 2), but every key must
name a real tier location so the doctor consistency check stays mechanical. Free-form intent,
when useful, goes in `summary`, not in `reads`/`writes`.

---

## Q5 — Stage registry: initial stage set 🔴

**Why it matters:** The registry should start with the smallest set that closes the loop;
erk over-split stages and had to consolidate.

**Options:**
- (a) `plan, save, implement, ship` (+ `resume`); defer `objective-plan / submit / address /
  land / learn` to Phase 2.
- (b) A larger initial set.

**Recommendation:** (a) — smallest loop-closing set.

**Resolution:** **MVP stage set = `plan, save, implement, submit, land, learn`.** (Revises
the original (a), which used a single thin `ship` stage.)

**On "ship" (resolved):** "ship" was only a ROADMAP shorthand for a *thin combined finish*
(commit + open PR + land-once-approved as one stage), which the roadmap then planned to split
into `submit` + `land` in Phase 2. It is **not an erk concept** and it conflates two
genuinely distinct operations, so it is dropped in favor of the explicit split:

- **`submit`** — branch → *draft* PR. `mode: read-write`; `requires` a committed branch;
  `writes github.pr`. (Named `submit`, not `pr-submit`, per Q11 — the stage is unambiguously
  PR submission and pairs with `land`.)
- **`land`** — *ready/approved* PR → merge + reconcile. Different precondition
  (approved/ready, not merely open); `writes github.pr` (merged) and sets the `cache.markers`
  `pending-learn` semaphore.

**Why six stages is correct, not over-split:**

- erk's over-split caution was about *durable lifecycle stages* not observably distinct from
  GitHub state (handled separately by Q8's `planned → impl` collapse). These are *workflow
  steps*; each is observably distinct and has its own gating posture / `requires` / `writes`
  (Q4).
- **`land` and `learn` are a coupled unit:** `land` sets the `pending-learn` marker (the Q2
  `cache.markers` semaphore) that blocks worktree deletion until learnings are captured.
  Ending the MVP at `land` would leave that semaphore dangling and leave perk unable to
  capture its own learnings — undercutting the dogfood thesis. Including `learn` closes the
  loop honestly.

**Deferred to Phase 2** (added as stages later): the review/classification loop
(`address`, erk's `pr-address`) and objectives (`objective-plan`). Also deferred is the *depth* of each MVP
stage (two-target PR body, `pr check`, reconciliation typing) — the MVP stages are thin;
close-then-deepen still holds.

**`resume` is a CLI verb, not a stage.** `perk resume <plan>` reopens the run
(`SessionManager.continueRecent`/`open`) and rehydrates `perk:workflow-state`, relocating you
*into* an existing stage rather than transforming state — so it has no
`predecessors`/`successors` and stays out of the registry.

**`save` stays a distinct stage:** it is the read-only(`plan`)→read-write boundary and the
idempotent GitHub-write point (`writes github.plan`, `cache.plan-ref`). In the warm flow the
`/plan-save` terminating tool implements it; the registry models the posture change.

**ROADMAP reconciliation — DONE.** This superseded the ROADMAP's "thin loop = plan/save/
implement/ship" framing; `ROADMAP.md` now carries the Phase-1 spine `plan → save → implement
→ submit → land → learn` (thin), leaving only `address`, `objective-plan`, and per-stage depth
in Phase 2. The locked Q1–Q13 outcomes are folded into the ROADMAP's "Foundational decisions
(locked)" section.

---

## Q6 — Stage registry: file format 🔴

**Why it matters:** One declarative file is the shared source of truth read by both languages;
the format affects dependencies and human-editability. (Highest-leverage format call.)

**Options:**
- (a) **YAML** — human-editable; both Python and TS parse trivially (small dep on each side).
- (b) **JSON** — zero-dep in both languages; less pleasant to hand-edit.

**Recommendation:** Leaning (a) YAML for editability, but (b) JSON is the safe zero-dep pick.
Needs an explicit call.

**Resolution:** **(a) YAML, authored as the single source of truth and parsed directly by
both planes for v1.** No generation step.

Rationale:

- **It is human-authored config, not hot-path data.** The registry is read at
  startup/generation time, edited by perk developers, and is the conceptual spine of the
  system — so editability and **inline comments** (documenting *why* a transition is legal,
  what a state key means) matter more than parse speed or zero-deps. JSON's no-comments rule
  is a real cost for a file whose whole job is to be the readable contract.
- **The dependency cost is negligible:** `pyyaml` is ubiquitous in Python tooling; the TS
  extension reads this file rarely.
- **Q4's nested per-door `doors:`/`run_id:` maps and `requires:`/`reads:`/`writes:` lists
  read far better in YAML** than punctuation-heavy JSON.

**Pipeline decision:** parse the one YAML file directly in both planes for v1 — one file, no
generation step to drift. The alternative (**YAML source → generated JSON artifact** that the
extension consumes for a zero-dep, schema-stable runtime read) is **deferred**: introduce it
only if the YAML dependency or parse cost ever actually bites. Keep the pipeline boring until
there is a reason not to.

---

## Q7 — Plan storage: direction 🔴 (direction only; full schema → Phase 1)

**Why it matters:** Shapes the whole GitHub layer; `init`'s GitHub scaffolding is gated on it.
Only the *direction* blocks Phase 0 — the full header/body schema and label taxonomy land in
Phase 1.

**Options:**
- (a) **Single canonical body + workflow-created PR** (erk's newer simplification); migration
  from legacy draft-PR plans becomes a Phase 3 import helper.
- (b) Reproduce erk-legacy draft-PR-backed plans for migration-friendliness up front.

**Recommendation:** (a) — adopt the simplification; keep migration-compat as a Phase 3 helper.

**Resolution:** **(a) — single canonical body + workflow-created PR.** A plan is a GitHub
**issue** (header in the body + full body); a **PR is created by the workflow at `pr-submit`
time** (Q5), not conflated with the plan's existence. Migration from legacy draft-PR plans is
a **Phase 3 import helper**, not a v1 architectural constraint.

Rationale:

- erk itself moved *toward* (a) — the draft-PR plumbing was legacy baggage it simplified
  away. Rebuilding what erk was retiring would be porting the binary, not the workflow.
- (a) keeps the GitHub layer thin and matches the Q5 stage split cleanly: `save` writes
  `github.plan`; `pr-submit` writes `github.pr`. (b) would entangle "plan exists" with
  "draft PR exists."
- Paying draft-PR complexity tax on every plan forever to ease a one-time import is a bad
  trade; perk's earliest user is perk itself (greenfield dogfooding), not migrating erk
  repos.
- **Consequence for Q9:** with (a), `init`'s GitHub scaffolding needs only what a
  plan-as-issue requires (at most a label or two), not draft-PR machinery — so Q9 stays
  genuinely thin.

---

## Q8 — Plan storage: minimal `lifecycle_stage` 🔴 (direction only)

**Why it matters:** A minimal, machine-readable lifecycle state must exist before any GitHub
scaffolding; over-splitting is a known erk trap.

**Options:**
- (a) `planned → impl`, with `merged`/`closed` inferred from PR state (not stored).
- (b) A richer durable stage set up front.

**Recommendation:** (a) — fewest stages observably distinct from GitHub state.

**Resolution:** **(a) — stored `lifecycle_stage` collapses to `planned → impl`; post-states
(`submitted`/`merged`/`closed`) are derived from PR state at read time, not stored.** Lives
**in the plan header** (the queryable metadata block on the issue body, per Q7's single-body
model), so it is fetched cheaply without reading the full plan or the PR; `merged`/`closed`
are overlaid from `github.pr` at read time.

Clarifying distinction (so this does not look like it contradicts Q5):

- **Q5 workflow stages** (`plan, save, implement, pr-submit, land, learn`) = "what step is
  the *agent/workflow* doing right now" — transient, in the registry.
- **`lifecycle_stage`** = "what durable condition is the *plan* in" — stored on the issue.
  The six workflow stages collapse to roughly two stored states (`planned` = issue exists,
  no implementation branch yet; `impl` = implementation underway); everything after is read
  from PR state.

Rationale:

- Directly applies erk's over-split lesson to the durable layer (PRIOR_ART §1): erk stored a
  rich lifecycle set and had to consolidate it after most stages proved inferable from
  GitHub or never observably distinct.
- Leans on Q3: *deriving* `merged`/`closed` from `github.pr` rather than *writing* a status
  means fewer cross-tier links to verify and fewer ways to drift — it sidesteps the
  "stale-status trap" by not storing what GitHub already knows.

---

## Q9 — Plan storage: keep `init`'s GitHub scaffolding thin 🔴 (direction only)

**Why it matters:** Lets Phase 0 proceed without the full label taxonomy; defers schema detail
to Phase 1 when `/plan-save` lands.

**Options:**
- (a) `init` does a minimal, idempotent GitHub step (auth check + at most a label or two);
  full label taxonomy deferred to Phase 1.
- (b) `init` lays down the complete label/state scaffolding now.

**Recommendation:** (a) — keep it thin and idempotent.

**Resolution:** **(a), and specifically verification-only in Phase 0.** `init`'s Phase 0
GitHub step does **no mutation** — it only **verifies** `gh` auth + repo access (a
`doctor`-style check). The first label(s) (e.g. `perk:plan`) are created **lazily and
idempotently by `/plan-save` in Phase 1**, when they are actually needed and their shape is
known.

Rationale:

- Q7 (plan = issue, no draft-PR machinery) and Q8 (no stored post-states) leave almost
  nothing to scaffold on GitHub beyond verifying access.
- A label taxonomy is *workflow logic*, which Phase 0 explicitly excludes ("substrate and
  state-tiering plumbing, no workflow logic yet") — it belongs with `/plan-save` in Phase 1.
- Verification-only keeps Phase 0 honestly side-effect-free on GitHub and avoids scaffolding
  a taxonomy before its shape is settled.

---

## Q10 — GitHub access seam 🟡

**Why it matters:** Decide the seam now even if v1 is shell-based, so metadata-sensitive ops
can be hardened later without churn.

**Options:**
- (a) Shell out to `gh` for v1, with **all GitHub mutations behind one Python gateway module**
  that can later be hardened into deterministic extension tools.
- (b) Build deterministic tools from the start.

**Recommendation:** (a) — shell-first, single hardening seam.

**Resolution:** **(a) — shell out to `gh` for v1, behind a single gateway *contract*
implemented once per plane.** Matches the auth assumptions `init`/`doctor` already verify
(Q9), and the swappable seam lets metadata-sensitive operations be hardened into
deterministic/API-backed implementations later without churn (ROADMAP foundational #4).

**Subtlety from Q5 — GitHub access happens on *both* planes:** the Python CLI touches GitHub
(`init` verification, the headless worker) and the TS extension touches GitHub (`/plan-save`
writes `github.plan`; `pr-submit` writes `github.pr`). So this is **not one shared module** —
it is **one gateway contract, implemented once per plane**:

- **Python side:** a `gh`-shelling gateway module (CLI + headless worker).
- **TS side:** a `gh`-shelling gateway module in the extension (in-session mutations).
- Both conform to the **same named operations + payload shapes**, so either can be swapped to
  a deterministic/API-backed implementation independently, and `doctor` can verify both.

This preserves the cli-vs-pi principle (no in-process coupling between planes — they share a
*contract*, not a module).

---

## Q11 — Command naming 🟡

**Why it matters:** Stage ids double as registry keys, CLI subcommands, and slash commands.

**Options:**
- (a) **Flat** (`plan`, `implement`, `ship`); reserve a `perk-` / `/perk-*` prefix only on
  collision.
- (b) Hyphenated/prefixed (`/perk-*`) from the start.

**Recommendation:** (a) — flat.

**Resolution:** **(a) flat — no namespace prefix.** Convention:

- **Stage id = the canonical name**, lowercase, hyphenated only when genuinely multi-word.
  The MVP set is fully single-word — `plan, save, implement, submit, land, learn` — with
  hyphenation reserved for later compound stages like `objective-plan`. (`submit`/`address`
  are used in preference to erk's `pr-submit`/`pr-address`: the `pr-` prefix is redundant in
  context, and the bare verbs pair cleanly — `submit` → `land`.) This is the Q4 `id` and the
  registry key.
- **CLI subcommand = the stage id verbatim:** `perk plan`, `perk submit`, `perk land`. The
  `perk` binary name already provides the namespace, so no prefix is needed.
- **Slash command = `/` + stage id:** `/plan`, `/submit`, `/land`. No `/perk-` prefix unless
  a borrowed package collides.

**Borrow-window collisions — handled by (i):** borrowed packages may already own slash
commands (`@tombell/pi-plan` registers `/plan`). During the borrow window perk simply *uses*
the borrowed command (that is the point of borrowing); perk registers its own flat command
only when it **internalizes** the stage (e.g. plan mode in Phase 2), by which point the
borrowed one is removed. The `perk` CLI binary namespaces all subcommands for free, so the
only collision surface is slash commands during borrowing — a rare, transient case, not worth
a permanent `/perk-` prefix.

---

## Q12 — Repo layout for the Python CLI + TS extension 🟢

**Why it matters:** Phase 0 stands up *both* artifacts; not named in the foundational list but
shapes everything downstream.

**Options:**
- (a) **Single repo, two build artifacts** (`pyproject.toml` for the `perk` CLI +
  `package.json` for the extension), with the stage-registry file at a shared path both read,
  and a documented co-versioning policy.
- (b) Two repos, or a different topology.

**Recommendation:** (a) — single repo, two artifacts, shared registry path.

**Resolution:** **(a) monorepo, lockstep single version, shared contracts authored in
`shared/` and bundled into each artifact at build time.**

Why monorepo: nearly every decision so far creates a **shared artifact both planes must
agree on** — the stage-registry YAML (Q6), the state-key vocabulary (Q4), the GitHub gateway
*contract* (Q10), the `.pi/workflow/` layout + `PERK_RUN_ID` protocol (Q2), the
`perk:workflow-state` schema (Q1). Two repos would force all of those into a third versioned
package and turn every cross-plane change into a multi-repo dance — hostile to dogfooding.

Indicative shape:

```
perk/
├── pyproject.toml            # the `perk` CLI (Python)
├── package.json              # the Pi extension package (TS)
├── perk/                     # Python CLI source
├── extension/                # TS extension source (extensions/, skills/, prompts/)
├── shared/                   # authored single source of truth for cross-plane contracts
│   └── registry.yaml         #   stage registry (Q6); state-key vocabulary (Q4) inline or alongside
├── docs/
└── .pi/settings.json         # loads the local extension (dogfooding)
```

**Sub-decisions:**

1. **Lockstep single version.** One version number for the whole repo; CLI and extension are
   released together. The shared contracts mean a CLI and extension from different versions
   cannot be trusted to agree, so a compatibility matrix would be needless cost while one
   team ships both. (Independent per-artifact SemVer + a compatibility range is the future
   escape hatch if that ever changes.)
2. **Shared contracts authored in `shared/`, bundled into each artifact at build time.** The
   registry/contracts must be readable by the *installed* CLI and the *installed* extension,
   not just in-repo — so each build artifact **bundles a copy** at package time (Python wheel
   as package data; npm package via `files`), and at runtime each plane reads its *own
   bundled* copy. The repo's `shared/` is the single authored source both are built from. No
   runtime dependency on repo layout.

---

## Q13 — perk's own config file (shared + per-user-local split) 🟢

**Why it matters:** `init` scaffolds erk's `config.toml` / `config.local.toml` analogue, but
the roadmap never names the format/location.

**Options:**
- (a) **`.pi/perk.toml` + `.pi/perk.local.toml`** (latter gitignored); TOML is Python-native
  (`tomllib`) and matches erk's idiom.
- (b) JSON for both, to share one format across planes.

**Recommendation:** Leaning (a) TOML; (b) if a single cross-plane format is preferred.

**Resolution:** **(a) TOML — `.pi/perk.toml` (committed) + `.pi/perk.local.toml` (gitignored).**

Rationale:

- Config is read primarily by the **Python CLI** (`init`, `doctor`, worktree settings,
  recommended-package tracking) and is mostly flat key-values — TOML is **Python-native**
  (`tomllib`, zero-dep) and is the idiom erk used (`config.toml` / `config.local.toml`).
- The committed/local split mirrors erk: shared project config is committed; per-user-local
  overrides are gitignored (and `init` manages the `.gitignore` entry).

**On the three-format surface (`.pi/settings.json` + `registry.yaml` + `perk.toml`):**
accepted as right, not sloppy — each format serves a distinct master. `.pi/settings.json` is
**Pi's**, not ours (fixed). The **registry is YAML** (Q6) because it is read by *both* planes
and is structural/nested (per-door maps, lists). **Config is TOML** because it is
Python-CLI-facing and mostly flat. (The considered alternative — YAML config to collapse to
two formats, reusing the Q6 parser — was set aside in favor of TOML's Python-native,
flat-config fit.)

---

## Deferred (no action before Phase 0) ⚪️

Recorded for completeness; these are explicitly Phase 1+ and do **not** gate Phase 0:

- **Open #1 — `@juicesharp/rpiv-pi` posture.** Leaning "study, don't bootstrap-depend." No action.
- **Open #2 — plan-mode reimplement vs wrap `@tombell/pi-plan`.** Phase 2 (decide from real
  usage when the gating primitive lands).
- **Open #3 — objective status model.** Phase 2. Leaning explicit-status-only.
- **Open #6 — subagent engine details.** Resolved direction (borrow `pi-subagents`); spike in
  Phase 2.
- **Full plan header/body schema + label taxonomy.** Phase 1.
- **Objectives layer entirely.** Phase 2.
