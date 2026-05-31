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

---

## §8.1 · `.pi/workflow/` layout (Q2)

The local cache tier — written and read by **both** the CLI (exterior) and the extension
(interior). Fixed layout:

```
.pi/workflow/
├── plans/                  # materialized plan cache (canonical copy stays in GitHub)
├── scratch/runs/<run_id>/  # per-run inter-process workflow files (diffs, generated bodies)
├── handoff/<run_id>.json   # pre-session CLI->extension cold-door state (claimed on session_start)
└── markers/                # existence-based friction semaphores (e.g. pending-learn)
```

- Keyed by the perk-owned **`run_id`** (a ULID — see §8.2), never the Pi session id (which
  does not exist yet at cold-door launch time).
- **GC is perk-owned:** prune `scratch/runs/<id>/` + `handoff/<id>.json` for runs whose
  terminal stage completed, or older than N days — surfaced later as a `doctor` check + a
  prune command (erk accumulated session dirs precisely because GC was undefined).
- `.gitignore`: `.pi/workflow/` transient subtrees are not committed; `plans/` may be cached
  locally but GitHub is canonical. `init` manages the relevant `.gitignore` entries.

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
| `mode` | string | the active registry stage `mode` (`read-only` / `read-write`) |
| `active_plan_ref` | object \| null | the provider-agnostic plan ref (§8.4); null during early `plan` |
| `active_objective` | string \| null | the active objective id (Phase 2; null in MVP) |
| `last_review_batch` | object \| null | the last processed review batch (Phase 2; null in MVP) |

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

State key (registry vocabulary): `session.workflow-state`.

---

## §8.4 · The GitHub gateway contract (Q9/Q10)

**One contract, implemented once per plane** (no shared module, no in-process coupling):
a `gh`-shelling gateway in the Python CLI (`init`/worker) and a `gh`-shelling gateway in the
TS extension (in-session mutations). Both conform to the **same operation names + payload
shapes**, so either can later swap `gh`-shell → API-backed independently, and `doctor` can
verify both.

### Verification-only operations (Phase 0 — authored now, **no mutation**)

These are all `init`/`doctor` needs in Phase 0 (`Q9`: verification-only; the first label is
created lazily by `/plan-save` in Phase 1).

```
check_auth()         -> { ok: bool, user: string|null, scopes: string[], error: string|null }
                        # `gh auth status`; never mutates.
check_repo_access()  -> { ok: bool, repo: string|null, can_push: bool, error: string|null }
                        # repo readable/writable for the authed user.
```

### Mutation operations (named only — **payloads deferred to Phase 1**, Q7/Q9)

Listed so the surface is visible; **not authored** (authoring payloads for unbuilt stages is
fiction). Each lands with its stage's handler:

- `create_label` — lazily create `perk:plan` et al. (`/plan-save`, Phase 1).
- `create_plan_issue` / `update_plan_header` — plan = issue with a queryable header (`Q7`,
  `Q8`: stored `lifecycle_stage` collapses `planned → impl`; post-states derived from PR).
- `create_pr` / `mark_pr_ready` / `merge_pr` — the `submit` → `land` path.
- `resolve_review_threads` — the `address` loop (Phase 2).
  - **Known durable shape to keep when authored** (PRIOR_ART §5/§11): the payload is
    `[{ thread_id, comment }]` (objects, not a flat list). Review threads are a *distinct*
    GitHub API from discussion comments — counted separately.

### Plan-ref payload (provider-agnostic; full schema → Phase 1)

`active_plan_ref` / `cache.plan-ref` is **provider-agnostic** from day one (PRIOR_ART §2 —
erk migrated away from GitHub-specific refs and issue-numbers-in-branch-names):

```
{ provider: string,            # e.g. "github"
  pr_id: string,               # STRING (allows non-numeric ids like Jira "PROJ-123")
  url: string,
  labels: string[],
  objective_id: string|null }  # Phase 2
```

Only the *direction* is locked in Phase 0; the exact header/body schema and label taxonomy
land with `/plan-save` in Phase 1.
