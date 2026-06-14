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
