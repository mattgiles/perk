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
`save` stage a direct writer of `session.workflow-state`. The warm door also **surfaces the
objective node→plan link outcome** returned by `perk plan-save` (`objective_node`): a successful
advance shows `→ in_progress`, a failed one shows a visible `⚠ … NOT advanced — re-run /plan-save`
warning (§8.4 "The node↔plan link") — it is not silently swallowed.

**Plan-issue title (#129).** The warm door now **actually forwards** an explicit `title` to
`perk plan-save --title` (it was previously accepted by `savePlan` but silently dropped). When no
explicit `title` is given, it **best-effort generates one** via the session model
(`extension/planTitle.ts` → `extension/structuredOutput.ts`, a reusable structured-output substrate
over `@earendil-works/pi-ai` tool-calling) and forwards that. Every failure mode (no model,
unresolved auth, a model error, no tool call, schema-invalid args, an empty sanitized title) and the
`PERK_NO_LLM` offline gate (set by the test harness, never by the production CLI) yield **no**
`--title`, so the cold door's deterministic `plan.derive_title` fallback takes over — a save is never
blocked. The cold door's `--title`/`derive_title` contract is unchanged.

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
  **terminates** the turn. The `/objective-save` **command drives the structured save**: it exits the
  read-only gate (so the `objective_save` tool becomes reachable) and injects guidance via
  `pi.sendUserMessage` instructing the model to call `objective_save` with `prose` + the structured
  `roadmap` (mirrors `/address`, `/objective-plan`, `/learn-docs`). It still performs **no GitHub
  mutation itself** — the canonical write flows through the tool, never a prose scrape. This
  is asymmetric with `/plan-save`: a plan *is* its prose, so the `/plan-save` command genuinely
  saves; an objective's roadmap is structured data that is unscrapeable, so its command cannot. The
  tool is structurally unreachable while read-only, so the model exits read-only (`/plan` off) before
  calling it.
- **Structured roadmap (never hand-written YAML).** `create_objective_issue` gains an optional
  `roadmap_nodes`; `perk objective create` gains `--roadmap <json>` (parsed via
  `objective.parse_structured_roadmap`, where per-node `status` is optional and defaults to
  `pending`). When `--roadmap`/`roadmap_nodes` is given the body is pure prose; otherwise the legacy
  body-embedded roadmap parse still applies (the cold-CLI path). **Creation requires ≥1 roadmap
  node**: `perk objective create` rejects an empty roadmap with `error_type: empty_roadmap` (exit 1)
  and `create_objective_issue` raises `GitHubError` — the parse/read layer stays lenient (existing
  node-less issues remain readable/closable). The judgment layer lives in the `perk-objective-author`
  skill.

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

**Plan-provider deferral (Node 2.2).** `planMode` now *consumes* the resolved `[providers] plan`
selection: it reads `loadPerkConfig(ctx.cwd).providers` through `extension/providers.ts`'s
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
`extension/providers.ts`'s `resolveProviders` per-event (`resolvedTodoProviderId(cwd)` /
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
`extension/todoAdapterJuicesharp.ts` (`registerTodoAdapterJuicesharp`, always registered, wired right
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

**PR review (`/pr-review`, #175).** A standalone warm command (like `/ci`, **not** a registry
stage — `shared/registry.yaml` is unchanged) that conducts automated code review of the active PR
and leaves the review **as comments on the PR**. It spawns the perk-owned **`perk.pr-reviewer`**
agent via the borrowed `pi-subagents` engine with **`context: "fresh"`** (not a fork) so the
implementation session's history never biases the review.

- **Deliberate departure from the read-only-child convention.** Unlike `/address` (read-only child
  classifies; the **parent** acts), the reviewer child **posts its own review**. Rationale: the PR
  is the sole output sink and there is no parent-side fix to apply, so relaying the review back
  through the parent would reintroduce exactly the session pollution this command avoids. D1 is
  still honored — the mutation stays canonical in the **Python gateway**: the child posts via
  `perk pr-review-post` (the child has `write` only to stage the payload file + `bash` to run the
  CLI). The review is **advisory `COMMENT` only** — `event` is hardcoded `COMMENT` in the gateway,
  so the agent can never approve/request-changes.
- **Configurable model + a correction.** The reviewer model is set by `[pr-review] model` in
  `.pi/perk.toml` (a string; overlaid by `.pi/perk.local.toml`). The warm `/pr-review` injects it as
  a **per-call inline `model` override** on the spawn (the agent's frontmatter `model` is the
  default). **Correction to the T7 note above:** `subagents.agentOverrides` does **not** reach
  project agents — `pi-subagents`' `applyBuiltinOverrides` applies overrides only to **builtin**
  agents — so the inline per-call override (not an override map) is the configuration mechanism for
  project agents like `perk.review-classifier` and `perk.pr-reviewer`.
- **No workflow-state record (deferral).** There is no parent-side tool turn (the child posts), so
  no `last_review_batch`-style record is written; the PR comment is the canonical record. A richer
  in-session record is a future enhancement.
- **Agent-def delivery (deferral).** `pr-reviewer.md` is hand-committed in perk's `.pi/agents/`
  (matching `review-classifier.md`/`objective-explorer.md`); delivering perk agent defs to *consumer*
  repos remains the pre-existing gap, out of scope here.

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
    # null (the review still runs from the diff). What the spawned child runs (`perk pr-review-context`).
post_pr_review{ pr_number, summary, comments:[{path,line,body}] } -> ReviewPostResult{ ok, mode, pr_number, comment_count }
    # ONE review via POST .../pulls/{n}/reviews with event=COMMENT (hardcoded) + inline comments[]
    # (path, line, side=RIGHT). mode ∈ {"review" (inline-anchored), "comment_fallback" (discussion
    # comment when the review submission fails)}. The warm twin is the /pr-review child, which
    # delegates via `perk pr-review-post --json --batch <path>`.
```

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
- The warm `extension/land.ts` surfaces `objective.nodes_marked` and **auto-drives** the reconcile
  pass via `driveReconcileAfterLand`, which injects
  `reconcileGuidance(...) + bindingSuffix(..., "command:objective-reconcile")` — byte-for-byte the
  message `/objective-reconcile` injects — when the land succeeded with a node marked done.
  Delivery branches on `ctx.isIdle()`: the streaming `land` tool path uses
  `deliverAs: "followUp"` (delivered after the terminating batch), the idle `/land` command path an
  immediate turn. `land` stays **terminating** because `terminate` only skips the *automatic*
  follow-up LLM call — an injected `followUp` user message is a separate deliberate new turn, so the
  two compose. The success text reports the auto-reconciliation rather than a copy-pasteable nudge;
  the merge itself is unchanged.
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
own them); only the delivery `warnings` are loud-but-non-fatal: Mechanism A `console.error`s them,
and **`bindingSuffix` (Mechanism B) now `console.error`s them too** (Node 3.1) — previously it
degraded silently. The injection-time mirror is **skill-presence only** (the trigger is fixed at
injection): the **`nudge`** path now warns when its skill is not installed under
`.agents/skills/<name>/SKILL.md` (mirroring the long-standing `transclude` warning), so every
delivered binding whose skill is missing yields **exactly one** warning, in both planes — never
silently delivered. Injection checks only user-originated skills (installed under `.agents/skills`),
so it uses that path **only** (no self-repo fallback).

**Validation (`doctor`, Node 3.1):** `perk doctor` adds one rolled-up, non-fatal **`bindings`**
check (`perk/doctor.py::_bindings_check`) over the **full resolved set** (`resolve_bindings(user,
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
(loud-but-non-fatal, D1): `perk doctor` stays exit-0 over a binding misconfiguration (a consumer that
has not run `skills update --sync` yet is not failed). A `BindingsError` on the *bundled* file is a `fail`
("Reinstall perk"; cannot occur in a healthy install). A `RegistryError`/bad-TOML during the check
degrades to a warn note rather than failing (the registry/config checks own those failures). The
check is report-only — no `--fix` for bindings.

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
and `bindings.yaml`), is the **supported set** — the catalog of plan/todo *providers* perk knows
how to wire — distinct from the per-repo **selection** (a flat `[providers]` table in
`.pi/perk.toml`, which is just a pointer into the catalog). It is bundled automatically via the
`shared/` force-include (wheel → `perk/_shared/`, npm tarball → `shared/`) and read by both planes
through independent readers: **`perk/providers.py`** (`load_providers` / `validate` /
`resolve_providers`, returning `ProviderSet`/`Provider` + the shared `Issue`/`Severity` findings,
raising `ProvidersError` only for structural failures) and **`extension/providers.ts`**
(`loadProviders` + the pure `resolveProviders`, returning `ResolvedProviders { plan, todo, issues }`
with `issues` as **`string[]`** — the TS plane has no `Issue`/`Severity`). The Python plane is the
authoritative validator. The
design is locked in `docs/design/adapter-architecture.md` (Node 1.3), over
`docs/design/provider-contract.md` (the seven dimensions; the `cache.plan-ref` `provider` field ==
the plan provider id) and `docs/design/pluggability-taxonomy.md` (the C3 behavior-preserving
default).

**Provider entry shape — `{ id, seam, package, adapter, default, package_filter? }`:** `id` is the
stable provider id (for the `plan` seam, exactly the `cache.plan-ref` `provider` string); `seam ∈
{plan, todo}`; `package` is the foreign Pi package spec added to `.pi/settings.json` `packages`
(`null` for perk's own bundled reference provider — nothing to add); `adapter` is the perk-owned
shim module bridging a foreign surface to the artifact boundary (`null` for the reference
provider); `default` is a bool — **exactly one `true` per seam**, the behavior-preserving no-config
pick; `package_filter` is an optional Pi object-form filter (`extensions`/`skills`/… arrays) merged
into a foreign package's object-form `packages` entry. Because both planes read this with their
full YAML readers, it can carry the nested `package_filter` object that the narrow-TOML config
reader cannot.

**Shipped set (Node 2.1 → 3.2):** the two reference entries `perk-plan` (seam `plan`) and
`perk-checkpoints` (seam `todo`), both `package: null` / `adapter: null` / `default: true`, plus a
**real** foreign entry per seam. `tombell-plan` (→ `npm:@tombell/pi-plan`, `adapter:
planAdapterTombell`) is a real, selectable plan provider (Node 2.3); `juicesharp-todo`
(→ `npm:@juicesharp/rpiv-todo`, `adapter: todoAdapterJuicesharp`) is now a real, selectable **todo**
provider (Node 3.2) — neither is illustrative any longer. **Both seams are behavior-complete:** the
**plan** seam (perk vacates its surface at registration time + the adapter bridges the foreign one —
see the Node 2.3 status note) and the **todo** seam (perk's `checkpoints` **defers at runtime** under
a foreign `[providers] todo` selection — Node 3.1 — with **no** registration-time vacating, because
the todo seam has no command-name collision; the `todoAdapterJuicesharp` shim carries perk's
progress discipline onto the foreign overlay — see the Node 3.2 status note). The **default** path
(both reference providers) is unaffected and is the hard guarantee.

**`cache.plan-ref.provider` is the issue backend, not the seam id.** Despite
`docs/design/provider-contract.md` framing the `cache.plan-ref` `provider` field as the plan
provider id, today it is the **issue backend** (`"github"`) — `perk/launch.py` branches on
`provider == "github"`, and `plan_save_cmd.py`/`resume.py`/all TS fixtures stamp `"github"`. That
"id == provider field" equivalence is aspirational; Node 2.2 does **not** restamp it (restamping
would break `launch.py`'s backend branching). `cache.plan-ref` is untouched by the plan-seam
deferral.

**Validation depth (shape-only, repo-free):** the loaders/validators check that
`schema_version == 1` (else a structural load error), each provider has a non-empty unique `id`, a
`seam ∈ {plan, todo}`, and that **exactly one `default: true`** exists per seam. They do **not**
check that any repo *selection* names a real provider — that cross-file validation is **`doctor`**'s
job (mirroring how bindings target-existence lives in doctor, not the loaders).

**The `[providers]` selection — flat string table in `.pi/perk.toml`:** a per-repo selection with
one key per seam (`plan` / `todo`), values are **bare provider-id strings** (the TS narrow-TOML
reader `parseTomlSubset` reads string values only; richer structure lives in `providers.yaml`).
Both planes parse it raw (`perk/config.py` → `Config.providers`; `extension/config.ts` →
`PerkConfig.providers`); resolution against the supported set is `init`/`doctor` in Python and the
`extension/providers.ts` `resolveProviders` resolver in TS (added Node 2.2, consumed by `planMode`). An **absent table or absent key → the seam's
`default: true` provider** (zero behavior change, the no-config default). `perk.local.toml` overlay
wins (standard local-override precedence). The pure resolver
`perk.providers.resolve_providers(selection, providers)` returns `ResolvedProviders { plan, todo,
issues }`: an absent key falls back to the default **silently**; an unknown id or a seam mismatch
falls back to the default and records a **loud-but-non-fatal** `Issue`.

**`perk init` two-directional settings wiring:** provider wiring composes on top of the static
`_desired_packages` (perk + `BORROWED_PACKAGES`) layer within the same `_converge_settings` body,
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

**Validation (`doctor`):** `perk doctor` adds one **`providers`** check (`perk/doctor.py::
_providers_check`). A `ProvidersError` on the *bundled* file is a `fail` (cannot occur in a healthy
install; "Reinstall perk"); an `ERROR` shape `Issue` on the bundled file is a `fail`. The repo
selection is resolved against the supported set and any resolver `issue` (unknown id / seam
mismatch) is a single **`warn`** (loud-but-non-fatal — `perk doctor` stays exit-0 over a selection
typo), remediation pointing at `.pi/perk.toml [providers]` / `perk init`. There is **no** separate
package-wired / orphan check — that drift is owned by the `settings-wiring` managed convergence
(which `doctor` already dry-runs); `_providers_check` owns only what convergence cannot repair (an
invalid bundled file, a selection naming a non-existent / wrong-seam provider).

> **Status (Node 2.1):** ships the selection **substrate** only — `shared/providers.yaml`, the two
> shape-only loaders + the pure resolver, the `[providers]` config-reading in both planes, the
> two-directional `init` wiring, and the `doctor` selection cross-check. The concrete adapter shims
> (`planAdapterTombell`, `todoAdapterJuicesharp`) are **Nodes 2.3 / 3.2**; the read-only tool-gate
> (`extension/toolGating.ts`, Invariant 1) is untouched.
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
> registers everything. (3) The new `extension/planAdapterTombell.ts` shim is an **injection-only**
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
> **Status (Node 3.2):** the **first 3rd-party todo adapter** lands `juicesharp-todo` as a real,
> selectable todo provider (no longer illustrative); the todo seam is **behavior-complete**. (1) The
> shipped entry carries no `package_filter` (single-concern checklist overlay — mirrors the tombell
> case). (2) **NO registration-time vacating** (an explicit deviation from the Node 3.1
> forward-assumption): the plan seam needed it only because perk and `@tombell/pi-plan` both register
> `/plan` (Pi suffixes duplicate names); the todo seam has **no command-name collision** — perk
> registers `/checkpoints`, the foreign overlay registers its own differently-named command(s) — so
> Node 3.1's runtime deferral is already sufficient. (3) The new
> `extension/todoAdapterJuicesharp.ts` shim is an **injection-only**, **active-workflow-gated**
> (`active_plan_ref != null`) bridge — always registered, inert unless `[providers] todo =
> "juicesharp-todo"`, injecting a hidden `perk:todo-adapter-juicesharp` context that carries perk's
> implement-progress **discipline** (seed from `## Steps`, mark each item complete in order) onto the
> foreign overlay. (4) It does **NOT** write `perk:checkpoint` or revive the deferred marker scanner
> (Correction 2): that entry is a transient TS-only overlay nothing downstream consumes, and perk's
> render + scanner are already deferred (Node 3.1), so re-populating it would be dead duplication —
> the lighter bridge the todo seam's lack of a downstream consumer permits. The shim **never** owns
> the read-only gate, **never** `setActiveTools`, and **never** restamps any provider field.
> Validation record: `docs/design/provider-smoke-juicesharp-todo.md`.

## §8.11 · The headless stage-drive worker contract (Node 1.2)

The **stage-drive primitive** (`extension/worker.ts` `driveStage`) drives ONE read-write stage
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
| `worktree` | absolute path, already positioned | the cold-door/runner positioning (`perk/launch.py`), **not** the worker (Gap 7) |
| `stage` | `"implement" \| "address"` | the only `doors.cold_remote: true` read-write stages (`shared/registry.yaml`) |
| `run_id` | ULID, present as `PERK_RUN_ID` in env | minted by positioning; the worker **inherits** it and never re-mints |
| handoff / plan-ref / plan-body | files under `<worktree>/.pi/workflow/` | materialized by positioning; the worker does not re-write them |
| `initialPrompt` | string | re-derived by `initialPromptFor(stage, planRef)` — the TS twin of `perk/launch.py._implement_prompt`/`_address_prompt` (parity asserted reciprocally in `extension/worker.test.ts` + `tests/test_worker_prompt_parity.py`); the resolved skill-binding suffix is delivered by the cold door and is **deferred to Phase 2** |
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
> spawn `perk.review-classifier` via the borrowed `pi-subagents` `subagent` tool. The
> **subagent-under-worker live smoke** stays the open-#6 dependency (§8.3, T6) **deferred to the
> Phase-3 `doctor workflow`**; Node 1.2 does not prove it.

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
(`perk/launch.py` `_drive_remote_target`) + the runner library (`perk/runner.py`); the GitHub
Actions workflow YAML it triggers is **Node 2.2** (named below, built there).

### The `Runner` contract (`perk/runner.py`)

A runner-agnostic `typing.Protocol`. GitHub Actions is the first (and currently only)
implementation; `select_runner(ref)` returns a `GitHubActionsRunner(ref)` for any ref today (the
"keep future runners open" seam — the ref is recorded but not yet mapped to a runner *kind*).

```python
class Runner(Protocol):
    kind: str
    def dispatch(self, *, stage, plan_ref, run_id, base, repo_root) -> RunHandle: ...
    def observe(self, handle: RunHandle, *, repo_root) -> RunObservation: ...
    def cancel(self, handle: RunHandle, *, repo_root) -> None: ...
```

- **`dispatch`** triggers the run and returns the **verified** handle (verified = the runner-side
  run was discovered and matched to `run_id`); it raises `RunnerError` on a trigger/discovery
  failure.
- **`observe`/`cancel`** operate on a previously-returned `RunHandle`. They are implemented (not
  stubbed) so the contract is validated end-to-end and the supervisor nodes (3.1/3.2) consume
  settled shapes — but the **supervisor command surfaces** (`perk workflow run list/cancel/retry`,
  tables, correlation) are those later nodes' work, not this one.

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
`run_id ↔ plan ↔ PR`; that enumeration is its work, not this node's. A **failed** record is kept
(not deleted) for that visibility. GC of dispatch records rides the existing `.pi/workflow/` GC
story (records live under `scratch/runs/<run_id>/`).

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

### The managed artifact (`perk/workflow_artifacts.py`)

Two perk-owned files, **managed by `perk init` and repaired by `perk doctor --fix`** (a
`ManagedConvergence` in `init.managed_convergences()`, covering the `runner-workflow` capability —
so `init` writes them and `doctor` verifies/repairs them through the one shared SSOT):

- **`.github/workflows/perk-run.yml`** — the runner workflow. It honors §8.13's `workflow_dispatch`
  input contract: a `run-name` embedding **`${{ inputs.run_id }}`** (verify-by-discovery); typed
  inputs **`run_id`, `stage`, `plan`, `base`** (`base` is `required: true` with no default — the
  dispatcher always sends it); a per-plan `concurrency` group `perk-run-${{ inputs.plan }}`. The
  `drive` job validates required secrets — it fails fast when `PERK_GH_PAT` is missing **and** when
  **both** `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` are empty (pre-empting the worker's late
  `no_model`) — checks out the plan branch (`plan-<plan>`), runs the composite setup, then `perk
  run-worker`. An opt-out repo variable `PERK_ENABLED=false` disables the job without removing the
  file. **Auth model:** checkout + push use the `PERK_GH_PAT` PAT, **not** `github.token` — a
  PAT-pushed commit triggers downstream CI (the implement drive commits + `submit` pushes);
  `GITHUB_TOKEN`-pushed commits do not. This is a stated decision Node 2.4 inherits.
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

### `perk run-worker` (the CI positioning + drive entrypoint, `perk/run_worker.py`)

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
**Node 2.4**.

---

## §8.15 · Remote run reporting back into GitHub (Node 2.3)

The **runner-side** consumer of the §8.12 structured run-event stream + the §8.11 `RunOutcome`: when
`perk run-worker` drives a stage remotely, it makes that run **observable on GitHub**. The worker
itself never mutates GitHub (§8.12 is explicit — surfacing the stream is this node); the reporter is
a deterministic exterior task (no agentic reasoning) living in the Python plane (`perk/run_report.py`)
and wired into `perk run-worker` (`perk/run_worker.py`).

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

No change to `.github/workflows/perk-run.yml` or `perk/workflow_artifacts.py`: reporting hooks into
`run-worker` itself, so the managed artifact (and its convergence/doctor tests) stay untouched.
