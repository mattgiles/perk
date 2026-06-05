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
> (`perk/github.py` — `check_auth` / `check_repo_access`, verification-only, never mutating);
> the TS plane authors the same shapes in Phase 1. The §8.5 init machine-surface contract is
> live (`perk init --json`).
>
> **Status (P1.T2a):** the §8.4 **plan-write mutations are implemented in the Python plane**
> (`perk/github.py` `create_label` / `create_plan_issue` / `add_issue_comment` /
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
├── handoff/<run_id>.json   # pre-session CLI->extension cold-door state (claimed on session_start)
└── markers/                # existence-based friction semaphores (e.g. pending-learn)
```

- Keyed by the perk-owned **`run_id`** (a ULID — see §8.2), never the Pi session id (which
  does not exist yet at cold-door launch time).
- **Handoff blob:** `{ run_id, stage, mode, consumed }` (+ `pi_session_id` once claimed). The
  CLI's cold launch (`perk <stage>`, T4) writes it; the extension claims it on `session_start`
  and sets `consumed: true` (§8.2). `stage` is the target stage id — the launched session's
  interior *handler* acts on it (Phase 1); T4's extension reads only `mode`/`run_id`.
- **GC is perk-owned:** prune `scratch/runs/<id>/` + `handoff/<id>.json` for runs whose
  terminal stage completed, or older than N days — surfaced later as a `doctor` check + a
  prune command (erk accumulated session dirs precisely because GC was undefined).
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
  *file* (`perk/cache.py` ↔ `extension/cache.ts`), not a shared module.
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
`cache.handoff`, `cache.markers`.

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
surface the model used** — the `/plan-save` *command* forwards only `{plan, title}` (it cannot
carry the link), whereas the `plan_save` *tool* passes it explicitly. `plan-save` reads the
handoff and defaults `objective_id`/`node_id` from it only when neither flag was passed (explicit
flags always win; a non-objective handoff has no `objective_id`, so plain planning is unaffected).

The same carrier ferries `consumed_learn` (#102). `learn-docs` launches a **read-only** plan-mode
session, where the `plan_save` *tool* is gated out (`toolGating.ts`), so the model saves via the
`/plan-save` *command* — which forwards only `{plan, title}`, dropping the gathered `perk:learn`
numbers. The `learn-docs` cold door stashes them as `handoff_extra={"consumed_learn": […]}`, and
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

**Warm keeps / cold mints (matches the registry `run_id` policy).** A warm in-session stage
transition keeps the `run_id`; a cold relaunch mints a **new** `run_id` that **records its
predecessor**, so resume/relaunch chains stay traceable.

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
`save` stage a direct writer of `session.workflow-state`.

State key (registry vocabulary): `session.workflow-state`.

**Objective budget + compaction (P2.T9).** With `active_objective` now live, the TS substrate
(`extension/objective.ts`, `registerObjective`) adds three pieces, all **inert when no objective
is active** and **never throwing** (logged-not-thrown, like checkpoints):
- **`/objective [<id>|clear]`** — `<id>` appends `{ active_objective: <id> }` to
  `perk:workflow-state` (LWW field) **and** seeds a dedicated `perk:objective-budget` activation
  marker `{ objective_id, activated_at: <ISO> }`; `clear` appends `{ active_objective: null }`; no
  arg shows the current objective + budget line. The dedicated `perk:objective-budget` entry keeps
  high-churn budget data **off** the shared `perk:workflow-state` record (mirrors checkpoints'
  dedicated entry).
- **Budget accounting** — a stateless rebuild (the `goal.ts` pattern): scan the branch for
  `role === "assistant"` messages **after** the latest `perk:objective-budget` marker, summing
  `max(0, usage.input) + max(0, usage.output)`; elapsed = `now − activated_at`. Surfaced via
  `ctx.ui.setStatus`/`setWidget` **guarded by `ctx.hasUI`**; rebuilt on `session_start`,
  `session_tree`, **and** `agent_end` (survives reload/branch/compaction for free). Pure helpers
  (`sumAssistantTokens` / `formatBudgetLine` / `findBudgetMarker` / `rebuildBudget`) are
  offline-tested.
- **Threshold-triggered compaction** (the `trigger-compact.ts` pattern) — on `turn_end`, **only
  when `active_objective != null`**, read `ctx.getContextUsage()` and call `ctx.compact({…})` when
  usage crosses a threshold (default `0.8`; overridable via `[objective] compact_threshold` in
  `.pi/perk.toml`, read through `extension/config.ts` — written as a **quoted** value because the
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
- **Coupling break (the `stage` field).** `extension/planMode.ts` previously injected its
  plan-authoring context on *any* read-only gate. An `objective-author` session is **also**
  read-only, so plan mode now **defers** when `stage === "objective-author"`, and
  `extension/objectiveAuthor.ts` injects its own `perk:objective-author-context` instead (keyed off
  read-only gate **AND** the stage; stripped from `context` when no longer authoring — the same
  hygiene plan mode applies). Exactly one authoring context is present.
- **`objective_save` warm door** (`extension/objectiveSave.ts`, the mirror of `planSave.ts`). The
  `objective_save` **tool** takes `prose` + a **structured `roadmap`** (a JSON array of nodes —
  never hand-written YAML) and delegates the write to `perk objective create --body <file> --roadmap
  <json> --run-id <rid> --json` (canonical mutation in Python, idempotent on the run_id). On success
  it links the live session: appends `active_objective` **and** seeds a fresh `perk:objective-budget`
  activation marker (mirrors `/objective <id>`), so budget tracking starts immediately; it
  **terminates** the turn. The `/objective-save` **command** is the fragile fallback (scrapes the
  latest message as prose, **no** roadmap) and, like `/plan-save`, exits the read-only gate on a
  successful save (the read-only → read-write boundary). The tool is structurally unreachable while
  read-only, so the model exits read-only (`/plan` off) before calling it.
- **Structured roadmap (never hand-written YAML).** `create_objective_issue` gains an optional
  `roadmap_nodes`; `perk objective create` gains `--roadmap <json>` (parsed via
  `objective.parse_structured_roadmap`, where per-node `status` is optional and defaults to
  `pending`). When `--roadmap`/`roadmap_nodes` is given the body is pure prose; otherwise the legacy
  body-embedded roadmap parse still applies (the cold-CLI path). The judgment layer lives in the
  `perk-objective-author` skill.

**Objective plan factory + transition tools (P2.T10).** The objective **transition** surface on top
of T9's mechanics (`extension/objectivePlan.ts`, `registerObjectivePlan`):
- **`/objective-plan [<number>] [--node ID]`** — the warm entry: resolve the objective (arg, else
  `active_objective` from the rebuilt `perk:workflow-state`) and `pi.sendUserMessage(...)` the
  factory guidance to start the loop (mirrors `/address`). Headless-safe.
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
  so a link failure only warns to stderr and surfaces `objective_node.error`; the same `run_id`
  re-links on a retried save). The standalone `objective_node` `pr`-only shape remains for **manual
  repair** but is no longer part of the factory loop. T11's reconciliation-on-land consumes both
  directions.
- **Node lifecycle = a resumable lease (factory selection).** `planning` is a **resumable claim**
  (intent to plan; no saved plan yet — `objective-plan` re-selects it, an abandoned claim self-heals;
  the eager mark is idempotent). `in_progress` is a **committed plan** (saved, node→plan backlinked,
  awaiting land). `done` is set by the land path (`nodes_for_pr`) or the audited tool. Factory
  selection lives in `objective.DependencyGraph`: `plannable_nodes()` / `next_plannable()` (unblocked
  ∧ (`pending`, or `planning` with **no** `pr`)); a `planning` node **with** a `pr` and any
  `in_progress` node are `in_flight_nodes()`. `next_node()` now delegates to `next_plannable()` (so
  `objective next`/`show` resume a claim). `classify_for_planning()` returns
  `plannable`/`in_flight`/`blocked`/`complete` and drives the cold door's honest errors
  (`objective_in_flight` is a new `error_type`, exit 1, in place of the old misleading "all blocked
  or complete"). `objective show --json` gains `selection_kind`.

**Objective reconciliation after landing (P2.T11).** When a PR linked to an objective node merges,
the roadmap reconciles against what actually landed — two seams matching the D9 Mechanical/
Reconcilable/Immutable typing:
- **Mechanical (on land).** The land path auto-marks the backlinked node(s) `done` — fail-open and
  non-audited (the audit gate is the model-tool boundary only). The warm `/land` surfaces the marked
  node(s) and a copy-pasteable `/objective-reconcile #<n>` nudge (no auto model turn).
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
in-session twin of `perk/launch.py`'s `_initial_prompt`: read the plan from its canonical source,
implement, `/submit` — carry the plan forward, never summarize it). Model-visible output is capped
(a single short confirmation; the durable state is the worktree's materialized plan-ref + the plan
issue). Dirty-tree hygiene is gated **manually** in the handler (a `newSession` session-replace may
bypass the `session_before_*` gate, so the handler re-checks `git status --porcelain` and refuses on
a dirty tree), fail-safe-headless. This is a **context refresh, not a stage transition** — the
registry's `implement.doors.warm: false` is unchanged.

**Checkpoints (P2.T2c).** Implementation progress is tracked in a **dedicated `perk:checkpoint`**
session entry (D3) — kept OFF the `perk:workflow-state` record because progress is high-churn (an
append every advancing `turn_end`), and a separate entry avoids LWW-append smell on the shared
record. The interior (`extension/checkpoints.ts`) seeds an ordered step list from the plan body's
`## Steps` numbered list (read from the `cache.plan` body cache) on `session_start` — **only** in an
active workflow (`active_plan_ref != null`), **only once** (a later session keeps the existing
entry). The `cache.plan` body (`.pi/workflow/plan.md`) is **materialized by the Python cold door**:
`perk implement` (`launch._materialize_plan_body`) fetches the plan body from GitHub
(`github.get_plan_body` → the `plan-body` block in the issue's first comment, parsed by
`plan.extract_plan_body`) and writes it into the worktree alongside the plan-ref + handoff
(best-effort + loud-but-non-fatal — an unreachable body just yields inert checkpoints, never a failed
launch). It is **opt-in + inert-by-default (D4)**: perk plans are prose, so when no `## Steps` list is
present the checkpoint degrades to inert (no entry, no crash); the `perk-plan` skill documents the
optional `## Steps` section as the forward path. Cross-plane contract: the **file** `cache.plan`
(`.pi/workflow/plan.md`), written by Python and read by TS. State is **rebuilt on `session_start` AND
`session_tree`**; `turn_end` scans the assistant message for `[DONE:n]` and, when a step advances,
appends a new `perk:checkpoint` marker carrying completion forward. The rebuild uses the
**scan-after-marker** discipline: the latest `perk:checkpoint` entry is the marker, and `[DONE:n]`/
`[WIP:n]` are re-folded only from assistant messages **after** it (stale markers from a previous
execution cannot resurrect a step). An **in-progress (`current`) step** is derived (not persisted):
the latest live `[WIP:n]` after the marker whose step exists and is incomplete, falling back to the
lowest incomplete step, else `null`; completion always wins (`▶` never renders on a completed step).
Status renders `📋 done/total` plus ` · ▶n` when current; widget/`/checkpoints` lines use `☑`
completed / `▶` current / `☐` pending. The **marker protocol is taught to the implement session**
via `_implement_prompt` (the launch prompt) + the **`perk-implement` skill**, so the implementer
knows to emit `[WIP:n]`/`[DONE:n]`. **Coarse fallback (P2.T15):** when no `## Steps` checklist exists
but a plan is active, the status bar shows `📋 <stage>` (the stage label from the handoff,
`readHandoff(cwd, run_id).stage`, falling back to `"active"`) with a single widget line noting the
plan is prose — so an active plan never goes dark; with no active plan, status/widget clear. Status
surfaces via `ctx.ui.setStatus`/`setWidget` **guarded by `ctx.hasUI`** (headless never touches rich
UI); `/checkpoints` lists progress (notify when UI, else stderr). State key: a transient tier-3 session entry (not in the registry vocabulary, like
`perk:workflow-state`'s sibling execution/todo entries). `@juicesharp/rpiv-todo` **is** retired in
P2.T12 (removed from `init.py`'s `BORROWED_PACKAGES` and `.pi/settings.json`): perk now owns the
implement-progress overlay via this perk-owned `perk:checkpoint` seam.

**Tool-gating (P2.T1).** The `mode` field **structurally gates tools** — enforcement, not
prompting. When `mode == "read-only"` the interior (`extension/toolGating.ts`):
(1) restricts the active tool set to `["read", "grep", "find", "ls", "bash"]` via
`pi.setActiveTools`, **snapshot-then-restore** (snapshot `pi.getActiveTools()` on the off→on
transition; restore it on on→off, falling back to the **full** configured tool set
`pi.getAllTools()` if no snapshot exists — never a hardcoded list, so perk's custom tools survive);
(2) blocks `edit`/`write`
and non-allowlisted `bash` commands at `tool_call` with `{ block: true, reason }` (a perk-owned
copy of plan-mode's destructive/safe regex tables); (3) injects a hidden `[READ-ONLY MODE]`
context at `before_agent_start` and **strips** that marker from `context` when off. The allowlist
is **restored on both `session_start` and `session_tree`** (re-sync from the rebuilt `mode`).
**Fail-closed:** the in-memory gate flag drives `tool_call`; a failed state-rebuild never opens the
gate (the sync is skipped), and `tool_call` blocks on any internal error. `mode` writes are
best-effort transient (no strict read-back). The `enter(ctx?)`/`exit(ctx?)` surface
(append `mode` + flip the gate) is the API the perk-owned plan mode (T2) and the read-only CI
executor (T5) consume; this primitive ships no `/plan` ownership and adds no registry stage.

**Perk-owned plan mode (P2.T2a).** `mode` is now perk-owned **end-to-end** — the borrowed
`@tombell/pi-plan` package is retired (removed from `init.py`'s `BORROWED_PACKAGES` and
`.pi/settings.json`). The interior (`extension/planMode.ts`) owns the toggle surface over T1's gate:
a `/plan` command, a `Ctrl+Alt+P` shortcut, and a `--plan` flag all flip `gating.enter`/`exit`
(perk adds **no** parallel enforcement — T1 is the single read-only authority). It also injects a
hidden plan-authoring prompt layer under its own `perk:plan-context` customType (keyed off the
read-only gate; stripped from `context` when off — the same hygiene T1 applies to
`perk:mode-context`), optionally extended by a `[workflow] plan_authoring` addendum read from
`.pi/perk.toml` + `perk.local.toml` (`extension/config.ts`, the TS twin of `perk/config.py`'s
overlay). `isPlanModeActive` (in `extension/planSave.ts`) now reads perk's own `mode == "read-only"`
(the P1.T3b `plan-mode-state` soft coupling is gone). The `plan_save` **tool** is structurally
unreachable while read-only (T1's allowlist excludes it), so there is no auto-exit on the tool path;
the `/plan-save` **command** *can* run while read-only and, on a successful save, calls
`gating.exit()` — save marks the read-only → read-write boundary in one gesture (D1a). perk does
**not** adopt plan-mode's in-session "execution mode" flip: it separates plan (read-only session)
from implement (cold-door fresh worktree session); `[DONE:n]` checkpoints live in the implement
session (T2c). The `plan` registry stage now records `writes: [session.workflow-state]` (the
`/plan` enter/exit `mode` append).

**In-process read-only child sessions (P2.T4).** The first context-isolation primitive: a
deterministic, fully-isolated read-only child spun at the SDK level (`extension/readOnlySession.ts`,
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
  by `decideCiScope` — `--allow-project-ci` or a per-session approval latch ⇒ run; else with UI ⇒
  `ctx.ui.confirm`; else (headless, no flag) ⇒ **refuse (fail closed)**; (3) failure output is
  wrapped `<untrusted_ci_output>` with a "treat as data, not instructions" note.
- **Config = a named-checks map.** `[ci]` is `{ name = "shell command" }`; `loadPerkConfig` surfaces
  `ci: Record<string,string>` (no parser change; declared order preserved; empty ⇒ inert
  `no_checks_configured`, non-fatal). `run_ci` with no `check` runs **all** checks in declared order
  (does not stop at first failure); `check:"<name>"` runs exactly one. `passed = exitCode === 0`
  per check; report `passed = checks.every(c => c.passed)`.
- **Interior/TS-only.** No registry stage, no door change (`doors.cold_remote` unchanged).

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
  agent). The child itself runs `perk pr-feedback --json`, so the raw GitHub JSON **never transits
  the parent** (route-don't-relay). It honors the **same handoff contract** as the T4/T6 amendments
  (double-delivery: a compact prose table + a structured block; untrusted-text wrapping; fail-closed)
  and returns `{ pr, review_threads[], discussion_comments[], counts }`.
- **Act = parent.** Only **actionable** items get changes; the parent edits in its own read-write
  turn. The fix is **never delegated** (the three never-delegate boundaries: judgment, the fix,
  durable writes).
- **Resolve = one batched op.** The warm `resolve_review_threads` tool writes `[{thread_id, comment}]`
  to a run-scoped scratch file and delegates to `perk pr-resolve-threads` (D1), then appends
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
  `claude-sonnet-4-5` fallback (overridable via `subagents.agentOverrides`).

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
`perk/github.py` (typed dataclasses mirroring these shapes); the TS plane follows in Phase 1.

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
  cold door performs every GitHub read up front (the read-only bash allowlist excludes `gh`) and
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
- **`/learn` (D10).** The `learn-capture` worker (`perk learn-capture --json --body <file>`) reads
  the agent-captured learnings markdown from a run-scoped scratch file (the stdin-less worker
  pattern), `create_learn_issue`, posts a back-link comment on the plan issue (best-effort), and
  clears `pending-learn`. The warm `/learn` (`extension/learn.ts`) takes an optional `summary`:
  present → scratch + delegate + mirror the marker-clear; absent → the thin TS-only marker-clear
  (graceful — no empty issue). `learn` now reads `[cache.markers, cache.plan-ref]` and writes
  `[cache.markers, github.learn, github.comments]` (the `github.learn` vocabulary key is new).

  **P2.T17 — learn is now ACTIVE (primed launch + guided warm door).** The capture mechanism above
  is unchanged; what's added is the *driver*. The `learn` cold launch is **primed** (`launch.py`
  `_learn_prompt`): the session opens already investigating the landed change (read the plan +
  derive the merged PR from the `plan-<pr_id>` head branch) and is told to call the `learn` tool
  with synthesized learnings. The warm **bare `/learn`** (interactive) **injects `perk-learn`
  guidance** via `pi.sendUserMessage` instead of silently clearing the marker (the agent clears it
  by calling the `learn` tool); **`/learn skip`** preserves the pure marker-clear and **`/learn
  <text>`** still captures verbatim; **headless** bare `/learn` stays the safe marker-clear
  (can't drive a turn). The **`perk-learn` skill** is the judgment layer both surfaces point at.
  No new gateway op — the existing `learn` tool / `learn-capture` worker remain the durable-write
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
    # Read-only; what the spawned `perk.review-classifier` child runs (via `perk pr-feedback`).
resolve_review_threads{ batch:[{thread_id, comment?}] } -> BatchResolveResult{ success, results[] }
    # for each item: optional reply (addPullRequestReviewThreadReply) THEN resolveReviewThread,
    # both GraphQL. results[] is per-item {thread_id, success, comment_added, error}; top-level
    # success = all resolved. An already-resolved thread re-resolves to success (idempotent).
    # The warm TS twin writes the batch to a run-scoped scratch file (pi.exec has no stdin) and
    # delegates via `perk pr-resolve-threads --json --batch <path>`.
```

- **Batch shape (PRIOR_ART §5/§11):** `[{ thread_id, comment }]` (objects, not a flat list).

**Authored (P2.T8a — PR-body craft + the deliberate review gate).** The submit body is composed
in `perk pr-submit` via **create-then-update** (the checkout footer needs the PR number, unknown
until `create_pr` returns), which also fixes a latent correctness bug (the Phase-1 footer carried
the **issue** number, not the PR's — erk's single most common agent mistake):

```
update_pr_body{ number, body }                      -> PrBodyUpdate{ number, dry_run }
    # PATCH .../pulls/{n} (-F body=@file); mirrors update_plan_header (PR body, not issue body).
    # Re-writes the full body WITH the plain-backtick `gh pr checkout <pr_number>` footer once the
    # PR number is known. Idempotent (overwrites).
get_pr_body{ number }                               -> string | null
    # GET .../pulls/{n} --jq .body; the read `perk pr-check` re-validates against.
validate_pr_body(body, *, pr_number)                -> string[]   (empty == valid)
    # PURE (no gh). Footer-scoped ONLY (the <details> embed is explicitly fine): the footer must be
    # present, plain-backtick (not HTML-wrapped), and carry the PR number (word-boundary: #12 ≠
    # …checkout 123). This is the self-check that catches the issue-numbered-footer bug.
```

- **The two-target split (D4).** The HTML-enhanced body — a best-effort `<details>` embed of the
  verbatim plan (via `get_plan_body`; `None` → no embed, no raise) + the checkout footer — goes
  **only** into the GitHub PR body (`update_pr_body`). The squash **commit message** is the OTHER
  target: plain text, set at land (T8b) so HTML never leaks into `git log`.
- **`pr check` (D5).** `perk pr-submit` runs `validate_pr_body` as a **post-write self-check** and
  **raises** (`error_type: pr_check_failed`) on failure. A thin `perk pr-check --json` (active
  plan-ref → find PR → `get_pr_body` → `validate_pr_body`) is the supervisor surface (exit 0 valid /
  1 invalid·op-failure / 2 not-a-repo).
- **Draft → ready is a deliberate gesture (D6).** Submit keeps the PR **draft**; perk does **not**
  auto-publish (unlike erk's `finalize_pr`). The new `perk pr-ready` (warm `/ready`, `extension/
  ready.ts`) is the explicit review gate — `mark_pr_ready` if draft, idempotent. Land's
  mark-ready-if-draft stays a safety net. **Correction:** perk plans are GitHub *issues*, not repo
  files, so erk's plan-file-diff completion heuristic does **not** map — the explicit draft→ready
  transition is the gate, and no plan-file-diff detector is built (never infer completion from PR
  open/closed state alone).
- **Re-submit on rewritten history (P2.T8a follow-up).** `perk pr-submit` **force-pushes the
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
{ provider: string,            # e.g. "github"
  pr_id: string,               # STRING (allows non-numeric ids like Jira "PROJ-123")
  url: string,                 # during planning: the plan issue url/id; branch/pr staged null
  labels: string[],            # ["perk:plan"]
  objective_id: string|null,   # Phase 2
  consumed_learn: number[] }   # hop-2: perk:learn issues a docs plan consolidates (closed on land)
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
  consumed_learn: number[] }   # hop-2: perk:learn issues a docs plan consolidates (closed on land)
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
> (`perk pr-submit`/`perk pr-land --json`) over the §3.2 machine-JSON channel — they do **not**
> reimplement the writes. (Cache/session tiers keep their per-plane I/O — `cache.ts`/`cache.py` —
> because those are *files*, not GitHub.) The "two gh gateways" idea is retired; there is **one
> canonical Python GitHub gateway**. So **T5a** opens a **draft** PR (`Closes #<issue>` so the
> squash-merge closes the plan), then `update_plan_header` populates the staged `branch=plan-<pr_id>`,
> `pr=<number>`, `lifecycle_stage=impl`. `submit` reads `cache.plan-ref` + `github.plan` and writes
> `github.pr` + `github.plan`.
>
> **Status (P1.T5b):** the **land path** is built. `land` (warm `/land` + cold `perk pr-land`)
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
> The resolution is a **pure, unit-tested** function (`perk/resume.py`). For `reuse` stages
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
> `perk pr-submit` composes an HTML-enhanced GitHub PR body (best-effort verbatim-plan `<details>`
> embed via `get_plan_body`) and appends the checkout footer via **create-then-update**
> (`update_pr_body`) carrying the **PR** number, then runs `validate_pr_body` as a post-write
> self-check (`pr_check_failed` on failure). A thin `perk pr-check --json` is the supervisor surface.
> Submit keeps the PR **draft**; the new `perk pr-ready` (warm `/ready`) is the deliberate review
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
its block engine); the GitHub writes live in `perk/github.py`; the cold-door workers are the
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
`next NUMBER` (the dependency-graph `build_graph(nodes).next_node()` selection T10's
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
  node (or `--node`), marks it `planning` (`update_objective_node`), and launches a read-only
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

**T11a — Mechanical (deterministic, on land).** The cold land path (`perk pr-land`) auto-marks the
objective node(s) backlinked to the just-merged plan `done` — **fail-open** (the merge already
succeeded; objective tracking must never block landing) and **deliberately non-audited** (per the
T10 §8.3 note, the audit gate protects the model-facing tool path only).
- `objective.nodes_for_pr(nodes, pr_number) -> [ObjectiveNode]` (pure) — returns nodes whose `pr`
  backlink matches `pr_number` canonicalized to `"#<n>"` (`"#6"` / `6` / `"6"` interchangeably).
- `pr_land_cmd._reconcile_objective_on_land(*, plan_ref, repo_root) -> ObjectiveLandUpdate`
  (`{ objective, nodes_marked, skipped_reason }`) — best-effort, **never raises**: it parses
  `plan_ref.objective_id` (`skipped_reason` ∈ `no_objective_link` / `bad_objective_id` /
  `objective_not_found` / `no_linked_node`, or `error: <exc>` on any failure, logged loud-but-non-fatal
  to stderr), then `update_objective_node(... status=DONE)` for each non-terminal matched node. Called
  in `_pr_land_impl`'s **non-dry-run** branch only, **after** `set_marker(PENDING_LEARN)`; the
  dry-run branch sets an inert `ObjectiveLandUpdate(None, (), "dry_run")` and stays fully offline.
  `_result_to_dict` always emits `"objective": { number, nodes_marked, skipped_reason }`;
  `_render_human` adds an `objective #N: marked node(s) X done` line when non-empty.
- The warm `extension/land.ts` surfaces `objective.nodes_marked` and appends a **copy-pasteable**
  `/objective-reconcile #<n>` nudge to the success text (no auto model turn from this terminating
  tool); the merge itself is unchanged.
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
  file-arg pattern, mirroring `learn-capture`); maps the two missing-target `GitHubError`s to a
  stable `reconcile_target_missing`, other infra to `github_error`. Node-description reconciliation
  reuses the existing `objective node --description` (no new flag).
- `extension/objectivePlan.ts` gains: a `description?` param on the `objective_node` tool
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

- **The factory cold door + warm command.** `perk learn-docs` (alias `ldocs`,
  `learn_docs_cmd.py`): `list_learn_issues` → materialize the inbox
  `.pi/workflow/scratch/learn-docs-inbox.md` (a `## Learning #<n>` section per issue, each body in
  `<untrusted_learning>`) → `launch_stage(plan_stage, prompt_override=<seed>)` (a read-only
  plan-mode session). `--gather` materializes the inbox + emits `{ inbox_path, learn_numbers }`
  with no launch (the warm path + tests consume this); `--dry-run` gathers + prints; `--remote` is
  rejected (`remote_blocked`, the `plan` stage is `cold_remote:false`); no open learn issues →
  exit 1 `no_learn_issues`. The warm `/learn-docs` (`extension/learnDocs.ts`) delegates to
  `perk learn-docs --gather --json` (gate-safe — extension `pi.exec` is not subject to the
  read-only bash gate), then `pi.sendUserMessage`s the factory guidance pointing at the
  `perk-learn-docs` skill. **Headless-safe** (the inbox is still materialized; no turn is driven).
- **The read-only gate forces inbox-over-gh.** The read-only tool gate's bash allowlist excludes
  `gh`/`perk` (`extension/toolGating.ts`), so the seeded factory session reads the materialized
  inbox via the `read` tool — it cannot query GitHub. This is why the cold door (not the model)
  performs every GitHub read up front.
- **The `consumed_learn` thread.** `perk plan-save --consumed-learn "45,50"` (and the warm
  `plan_save` tool's `consumed_learn` array param) populate `plan.PlanHeader.consumed_learn` +
  `plan.PlanRef.consumed_learn` (parsed to a sorted unique `tuple[int, ...]`; an invalid token →
  `invalid_input`). This persists which `perk:learn` issues the docs plan consolidates; non-factory
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
  non-benign skip (everything except `no_consumed_learn`/`dry_run`). The warm `extension/land.ts`
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
`2` environment-not-ready (`not_a_repo` / `missing_tool`). GitHub-unauthed is **non-fatal** in
`init` (reported, exit 0); `github_unauthed` is reserved for the strict `require_github` path.

**`--json` object.**
```
{ success: bool, mode: "self"|"consumer"|"unknown", error_type: string|null, message: string|null,
  env:     [ { name, ok, detail, remediation } ],          # required-tooling checks
  github:  { auth: { ok, user, scopes[], error },          # null when env-not-ready / verify skipped
             repo: { ok, repo, can_push, error } },
  capabilities: string[],                                  # the managed inventory (perk/capabilities.py)
  changes: string[],                                       # converged/seeded pieces ([] ⇒ already converged)
  handoff: string|null }                                   # path to the post-init markdown on-ramp
```

The **post-init handoff** (`handoff`) is an *agent-readable* markdown at
`.pi/workflow/post-init.md` (gitignored; regenerated each init) — distinct from the §8.1
machine run-handoff JSON. It is the Phase-0 dogfood on-ramp.

**Capability inventory.** `perk/capabilities.py` is the declared SSOT of what `init` manages
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
  fixed: string[] }                      # repairs applied by --fix ([] otherwise)
```

**Groups.** `environment` (tools; missing = `fail`) · `github` (auth/access; non-fatal `warn`) ·
`package` (settings wiring) · `repository` (gitignore/agents blocks + config present/valid) ·
`registry` (the registry self-check) · `state` (the `.pi/workflow/` cache layout + handoff-blob
integrity). Managed-piece checks are filtered by `capabilities.applicable(self_repo)`; infra checks
always run. Human render (stderr) follows the three-way condensed rule per group (collapse a clean
group; else expand only its failures/warnings); `--verbose` expands every check.

---

## §8.7 · Cross-plane session-context markers (the selfcheck verifier)

Two pieces of session context are converged by one plane and **read back** by the other, so the
literal markers are a cross-plane contract:

- **`<!-- BEGIN perk managed -->`** — the managed `AGENTS.md` block. `perk init` (Python plane)
  writes it; Pi loads `AGENTS.md` into `contextFiles`; the extension's `/perk-selfcheck` (TS plane,
  `extension/selfcheck.ts`) reads `getSystemPromptOptions().contextFiles` and confirms some file
  carries this marker. Changing the literal in `perk/init.py` **must** update
  `MANAGED_AGENTS_MARKER` in `extension/selfcheck.ts` in the same turn.
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
planes through independent readers: **`perk/bindings.py`** (`load_bindings` / `validate`, returning
`BindingSet`/`Binding` + the shared `Issue`/`Severity` findings, raising `BindingsError` only for
structural failures) and **`extension/bindings.ts`** (`loadDefaultBindings`, a thin structural
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
(`perk/config.py` → `Config.user_bindings`; `extension/config.ts` → `PerkConfig.bindings`) and
resolve it against the shipped defaults through a **pure free function** —
`perk.bindings.resolve_bindings(user_bindings, defaults=load_bindings().bindings)` /
`extension/bindings.ts resolveBindings(userBindings, defaults=loadDefaultBindings())` — each
returning a `ResolvedBindings { bindings, issues }`. The override is **trigger-keyed**: starting from
the defaults (order preserved), each *applied* user binding **replaces in place** the entry with the
same trigger or **appends** at a new trigger, so the resolved set has **unique triggers by
construction**. A user binding is applied iff it is **shape-valid** (same shape-only checks above)
AND its trigger was not already applied by an earlier user binding; otherwise it is dropped and its
shape/`duplicate` `Issue` recorded in `issues` for loud-but-non-fatal surfacing. **Defaults are
trusted** (not re-validated). The resolver remains registry-free: target-existence is still
**`doctor`** (Node 3.1), never the resolver. No removal/disable syntax and no multi-skill-per-trigger
co-delivery are defined yet.

**Cold-door delivery (Node 2.3, Python plane):** `perk/binding_delivery.py`
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

**Warm-door delivery (Node 2.2/2.3, TS extension):** `extension/bindingDelivery.ts` is the in-session
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
own them); only the transclude `warnings` are loud-but-non-fatal (Mechanism A logs them; the warm
command path degrades silently to the nudge).

> **Status (Node 2.3):** cold-door (Python) **and** warm-door (TS) delivery landed, **and** perk's own
> hardcoded "Follow the … skill" strings are migrated onto the mechanism + deleted (Node 2.3) — the
> skill-binding mechanism is now the single delivery path for perk's own nudges. The render header
> was neutralized to `"The following skill binding(s) apply here:"` (the `.pi/perk.toml` parenthetical
> was false for the delivered perk defaults). Known residual (out of scope, documented): in a cold
> `learn-docs` session, after compaction Mechanism A re-renders the borrowed `stage:plan` and injects
> `perk-plan` rather than `perk-learn-docs` — benign (learn-docs *is* a planning factory); a
> pre-existing stage-vs-command `binding_trigger` quirk. Deferred: `doctor` target-existence
> validation → **Node 3.1**; `init` `[[bindings]]` template + user docs → **Node 3.2**.
