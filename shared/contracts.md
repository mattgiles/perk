# perk cross-plane contracts

The four language-neutral contracts both planes obey, authored once here and bundled into
each build artifact (`Q12`). These are **prose specs** (no parser): the Python CLI (`perk`)
and the TS extension (`@perk/pi`) each implement one side, against the exact names/paths/
fields pinned below. `perk doctor` (T6) verifies conformance.

The stage registry — the one *parsed* contract — is the sibling `registry.yaml`; its
`state_keys` block is the canonical vocabulary referenced throughout this document.

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
  `/.pi/workflow/plan-ref.json` — a local mirror; the canonical plan lives in GitHub).
- **`plan-ref.json` (`cache.plan-ref`, T2b):** the provider-agnostic plan-ref payload (§8.4)
  written verbatim. One active ref per checkout/worktree (`.pi/workflow/` is per-checkout). The
  **Python cold door** (`perk plan-save`) writes it on a real save; the **extension** reads it
  on `session_start` to reconcile `active_plan_ref` (§8.3). The cross-plane contract is the
  *file* (`perk/cache.py` ↔ `extension/cache.ts`), not a shared module.

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
| `active_plan_ref` | object \| null | the provider-agnostic plan ref (§8.4); null during early `plan` |
| `active_objective` | string \| null | the active objective id (Phase 2; null in MVP) |
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

**`active_plan_ref` reconciliation (T2b):** on `session_start`, after the run_id claim, the
extension reads `cache.plan-ref` and appends `active_plan_ref` **iff** the rebuilt value
does not already match the file — **idempotent by `(provider, pr_id)`** (so reloads don't
duplicate and a fork keeps the inherited ref), with a **strict read-back** (loud-but-
non-fatal on mismatch, headless-safe). `session_tree` re-reads nothing — the per-field LWW
rebuild already restores `active_plan_ref`, so branch navigation preserves it.

**Warm `/plan-save` direct linkage (T3):** the in-session warm door appends `active_plan_ref`
**directly** after a successful save (same strict read-back, idempotent by `(provider, pr_id)`),
so the live session is linked without waiting for the next `session_start`. Both writers feed the
same LWW field; a warm append makes the next reload's reconciliation a no-op. This makes the warm
`save` stage a direct writer of `session.workflow-state`.

State key (registry vocabulary): `session.workflow-state`.

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
**scan-after-marker** discipline: the latest `perk:checkpoint` entry is the marker, and `[DONE:n]` is
re-folded only from assistant messages **after** it (stale `[DONE:n]` from a previous execution
cannot resurrect a step). Status surfaces via `ctx.ui.setStatus`/`setWidget` **guarded by
`ctx.hasUI`** (headless never touches rich UI); `/checkpoints` lists progress (notify when UI, else
stderr). State key: a transient tier-3 session entry (not in the registry vocabulary, like
`perk:workflow-state`'s sibling execution/todo entries). `@juicesharp/rpiv-todo` is **not** retired
here — P2.T12 retires it, conditional on this seam landing.

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
get_plan{ number }                                  -> PlanState{ number, url, title, header, pr } | null
    # gh issue view --json (+ pulls/{n} when the header carries pr); the `perk resume` read (T5c)
```

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

### Plan-ref payload (provider-agnostic; full schema → Phase 1)

`active_plan_ref` / `cache.plan-ref` is **provider-agnostic** from day one (PRIOR_ART §2 —
erk migrated away from GitHub-specific refs and issue-numbers-in-branch-names):

```
{ provider: string,            # e.g. "github"
  pr_id: string,               # STRING (allows non-numeric ids like Jira "PROJ-123")
  url: string,                 # during planning: the plan issue url/id; branch/pr staged null
  labels: string[],            # ["perk:plan"]
  objective_id: string|null }  # Phase 2
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
  objective_id: string|null }  # Phase 2
```

**Label taxonomy (minimal, PRIOR_ART §2/§6):** one label `perk:plan` in the MVP; type labels
(learn/objective) land with their stages. Query by a **single** label — GitHub label filters
are AND-semantics.

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
