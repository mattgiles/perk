# perk cross-plane contracts — history

The changelog sibling of [`contracts.md`](./contracts.md). It carries the relocated chronological
`Status (…)` history so the spec file stays a compact current-spec document — the durable `## §N.M`
contract bodies live in `contracts.md`; the present-tense-of-a-past-node landing notes live here.
This file ships in **both** build artifacts alongside `contracts.md` (the whole `shared/` dir is
bundled — the Python wheel as package data `perk/_shared/`, the npm package under `shared/`).

## Entry convention

- Entries are **grouped by the originating `§N.M` anchor**, in `contracts.md`'s section order.
- **Chronological within** each group (oldest landing first).
- Each entry is the original `Status (…)` blockquote **verbatim** — keep-and-annotate, never
  reword, never "fix" a now-stale claim (the relocation is mechanical; reconciliation judgment
  stays out).
- Each group's `§N.M` heading **is** the cross-reference anchor.
- **Exception:** document-opening statuses not bound to a single section live under the leading
  **"General / opening"** group below.

## General / opening

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

## §8.4 · The GitHub gateway contract (Q9/Q10)

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

## §8.9 · Skill bindings (the trigger→skill delivery contract)

> **Status (Node 2.3):** cold-door (Python) **and** warm-door (TS) delivery landed, **and** perk's own
> hardcoded "Follow the … skill" strings are migrated onto the mechanism + deleted (Node 2.3) — the
> skill-binding mechanism is now the single delivery path for perk's own nudges. The render header
> was neutralized to `"The following skill binding(s) apply here:"` (the `.pi/perk.toml` parenthetical
> was false for the delivered perk defaults). Known residual (out of scope, documented): in a cold
> `learn-docs` session, after compaction Mechanism A re-renders the borrowed `stage:plan` and injects
> `perk-plan` rather than `perk-learn-docs` — benign (learn-docs *is* a planning factory); a
> pre-existing stage-vs-command `binding_trigger` quirk. Deferred: `doctor` target-existence
> validation → **Node 3.1**; `init` `[[bindings]]` template + user docs → **Node 3.2**.
>
> **Status (Node 3.1):** `doctor` target-existence/skill-presence validation landed (the non-fatal
> `bindings` check), plus the injection-time skill-presence mirror (the `nudge` path warns;
> `bindingSuffix` now logs its warnings). Deferred: `init` `[[bindings]]` commented template + user
> docs → **Node 3.2**.
>
> **Status (Node 3.2):** the `init` `[[bindings]]` commented template + user docs landed, resolving
> the deferral above. `PERK_TOML_TEMPLATE` now seeds a comment-only `[[bindings]]` block documenting
> `trigger` / `skill` / `mode` and the nudge-vs-transclude choice; `PERK_LOCAL_TOML_TEMPLATE` records
> the whole-array-replace override rule. README gains a `## Skill bindings` user section. The seeded
> block is inert (comment-only) — a fresh repo still resolves to zero user bindings and `doctor`
> stays exit-0 (pinned by a `tests/test_config.py` regression).

## §8.10 · Provider selection (the supported-set registry + the `[providers]` selection)

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
> **Status (Node 2.6):** the tombell bridge context is **re-aimed to review-first**
> (`plan_draft` → `plan_review` → the first-party in-TUI review → `approvalSave` auto-save), with
> the present + `/plan-save` flow as its explicit fail-open arm (see §8.10's interactive save
> discipline). The injection is now **conditioned** — it fires only when perk's gate is read-only
> (per the persisted `perk:workflow-state.mode`) **or** tombell's own persisted `plan-mode-state`
> entry has `enabled: true` (latest wins), and never in an objective-author session — replacing
> Node 2.3's unconditional-on-selection injection.
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
>
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
>
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
