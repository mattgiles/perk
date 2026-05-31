# Phase 0 Plan — Skeleton + dogfood substrate (borrow)

This decomposes **[ROADMAP.md](./ROADMAP.md) § Phase 0** into landable work units ("turns").
It assumes the locked foundational decisions and the Q1–Q13 resolutions in
[foundation-open-questions.md](./foundation-open-questions.md); references below point at the
decision (`foundational #N`) or question (`QN`) that governs a deliverable.

**What Phase 0 delivers.** A `perk init`-scaffolded, `perk doctor`-healthy repo carrying: the
two-plane monorepo skeleton (Python CLI + TS extension at one lockstep version), the *locked*
shared contracts, real state-tiering read/write helpers (no workflow logic yet), the borrowed
scaffolding (`pi-plan`, `rpiv-todo`, `pi-diff` + a status bar), and the CLI exterior plumbing
(`init`, `doctor`, worktree lifecycle, process-launch, registry→subcommand generation). The
bar is: **Phase 1 can be planned in read-only plan mode with a live todo overlay, on a repo
this phase scaffolds and keeps healthy.**

## Principles that shape the sequencing

- **Bootstrap paradox + crossover.** Phase 0 is the one phase perk cannot build through its
  own loop — there is no plan-save/implement substrate yet. **T1** is built by hand (ordinary
  Pi coding) and lands the minimal `perk init`, which installs perk's own (no-op) extension
  **and the borrowed plan mode + todo overlay**. After T1, the remaining turns (**T2–T7**) can
  themselves be *planned in read-only plan mode with the todo overlay* — perk's earliest
  self-use. Front-loading the install-via-init substrate is what buys that early crossover.
- **`perk init` is a growing, idempotent spine — not a single turn.** Every Pi-extension
  install and every managed scaffold (a package, a `.pi/settings.json` entry, a config file, a
  `.pi/workflow/` dir, a `.gitignore` line) is performed *by `perk init`*, never by hand. A
  minimal `init` is introduced in **T1**; each later turn that adds a managed piece **extends
  `init`'s convergence logic** and re-asserts idempotency. The invariant, held from T1 on:
  **you converge any repo — including perk's own — by (re-)running `perk init`, and re-running
  on an already-converged repo is a no-op.**
- **`init` converges forward; `doctor --fix` repairs oddities.** Keep `perk init` a *clean
  forward-convergence path* — it brings a coherent repo to the **current** desired state and
  does **not** accrete version-specific "if you have the old shape, migrate it" branches.
  `perk doctor --fix` (T6) is the home for **legacy oddities** — older-version artifacts,
  hand-edits, half-finished operations — that would be inelegant to bake into `init` for
  backwards compatibility alone. So: `init` *makes it current*, `doctor` *makes it coherent*.
- **Contracts before code** (`foundational #3, #6`; `Q4`, `Q12`). The shared contracts are
  "lock before building." They are already *decided*; authoring them as files (T2) is mostly
  mechanical, and both planes depend on them, so they come right after the skeleton.
- **Two planes, lockstep** (`Q12`). Most turns touch both the Python CLI and the TS
  extension. Each turn must leave **both** artifacts coherent and the `shared/` copy bundling
  into each.
- **A checkable gate per turn.** With no perk loop to lean on, every turn ends on an explicit,
  runnable acceptance check (`perk …` prints/does X; `pi` loads the extension and round-trips
  state).
- **A thin test seam is allowed for the deterministic core** (agreed). The full SDK
  command/extension test harness still stands up in Phase 1, but T2's registry validation and
  T3's cache/`run_id` round-trips are deterministic and high-value, so they get minimal tests
  (pytest on the Python side, a light TS test runner on the extension side) — not the SDK
  harness.

**Turn semantics.** A "turn" = one independently-landable, PR-sized unit. The dependency spine
is linear (T1 → … → T7); there is little parallelism by design, which keeps each PR reviewable
and each gate unambiguous. (T7 is a **checkpoint half-turn** — a verification + docs pass, not new
machinery.)

## How a turn lands

Each turn lands as a PR that (a) leaves both build artifacts installable, (b) keeps the
`shared/` bundle intact in each, (c) **converges via `perk init`** — any managed piece it adds
is installed/scaffolded by `init`, and re-running `init` is a no-op — and (d) **demonstrates its
acceptance gate** in the PR description (a command transcript or a passing test). T1 is authored
by hand; T2–T7 may be authored in borrowed plan mode (post-crossover).

---

## T1 — Monorepo skeleton + the `perk init` spine begins  ·  *crossover point*

**Goal.** Stand up the two-artifact monorepo, prove the `shared/` bundling mechanism, and land
the **minimal `perk init`** so that *all* Pi-extension wiring is owned by `init` from the start.

**Deliverables.**
- `pyproject.toml` (the `perk` CLI) and `package.json` (the Pi extension) at a **single
  lockstep version** (`foundational #6`, `Q12`). Extension `package.json` follows agent-stuff's
  packaging idiom (best-practices §2): `peerDependencies` for the Pi APIs
  (`@earendil-works/pi-coding-agent`, `pi-ai`, `pi-tui`, `typebox`); the `pi-package` /
  `pi-extension` / `pi-skill` keywords; glob resource dirs with `!` negation for opt-in pieces.
- `shared/` directory (placeholder for now) + **build-time bundling** into both artifacts:
  wheel `package-data` for Python, npm `files` (or a prepublish copy step) for the extension —
  so runtime never depends on repo layout (`Q12`).
- **Dev-vs-installed wiring** (corrected & confirmed in T1 — see phase-0-turn-1.md §3/§14;
  supersedes an earlier "dual-path manifest" framing). perk needs **no** agent-stuff-style
  list-twice manifest: `shared/` is bundled *data* (not a Pi resource) and borrowed packages are
  independent `npm:` entries. The real work is (a) **self-vs-consumer extension wiring** — `init`
  lists perk's own package as a local path (`".."`) in perk's own repo, `npm:@perk/pi` in a
  consumer — and (b) a **`shared/` resolver per plane** (installed bundle → editable repo-sibling
  fallback). This was the highest-risk unknown; it is now validated end-to-end.
- A **minimal, idempotent `perk init`** that owns the Pi wiring (the init spine begins here):
  write/update `.pi/settings.json` to load perk's own (no-op) extension via local install;
  install the **borrowed default set** (`@tombell/pi-plan`, `@juicesharp/rpiv-todo`,
  `@tombell/pi-diff` + a status bar); create the `.pi/workflow/` dirs. Convergent: a re-run adds
  only what's missing and is otherwise a no-op.
- `AGENTS.md` as a **compressed index** (context strategy) + project conventions; `.gitignore`
  (the entries `init` owns). Bake the **headless-fail-safe convention** in from the start —
  `ctx.hasUI`-guard every rich-UI call and block dangerous ops when `!ctx.hasUI`, even in the
  no-op extension (agent-stuff §8, pi §7).

**Acceptance gate (hard).** On a fresh clone: `uv`/`pip` install → `perk --version`; **`perk
init`** writes `.pi/settings.json`, loads perk's own no-op extension in `pi`, and creates the
`.pi/workflow/` dirs; **re-running `perk init` is a no-op**; a built wheel **and** npm tarball each
contain the bundled `shared/` copy.

**Crossover goal (may iterate).** `perk init` *also* installs the borrowed default set so plan
mode + the todo overlay work — the early-dogfood crossover that lets **T2–T7 be authored in
read-only plan mode**. This rides on the dev-vs-installed manifest above (the riskiest mechanic in
Phase 0), so it is a **goal of T1, not a blocker**: if package install/load needs iteration, the
hard gate still lands and T2–T7 fall back to hand-authoring. The dependency spine never assumes
the crossover.

**Depends on.** —

---

## T2 — Author & lock the shared contracts

**Goal.** Turn the Q1–Q13 decisions into concrete, parseable files in `shared/`, and make
"lock before building" executable via a self-check — locking the descriptor **shape** and the
stage **graph** now, while leaving the drift-prone per-stage state-I/O to be filled as handlers
land.

**Deliverables (all in `shared/`).**
- `registry.yaml` — the **descriptor *shape*** (the full **Q4** field set: `id, summary, doors
  {warm, cold_local, cold_remote}, worktree, mode, requires, reads, writes, run_id (per door),
  command, predecessors, successors`) plus, for each of the **6 MVP stages** (`plan, save,
  implement, submit, land, learn`, `Q5`), the fields T4's subcommand generation and the graph
  self-check need *now*: `id, command, doors, predecessors, successors` (`command` may point at
  not-yet-existing handlers). The drift-prone **`reads`/`writes`/`requires` values are filled per
  stage as its handler is built** (Phase 1+) — locking the *shape* and the *graph* now, not
  fiction about the state-I/O of unbuilt stages.
- The **state-key vocabulary** — the fixed three-tier set (`github.*`, `cache.*`,
  `session.workflow-state`) that `requires`/`reads`/`writes` draw from (`Q4`).
- The **`.pi/workflow/` layout spec** (`plans/`, `scratch/runs/<run_id>/`,
  `handoff/<run_id>.json`, `markers/`) (`Q2`).
- The **`PERK_RUN_ID` protocol** (ULID launch token; emit → claim-on-`session_start` →
  verify → mark-consumed; fork/warm/cold rules) (`Q2`).
- The **`perk:workflow-state` schema** (`run_id`, `pi_session_id`, `mode`, `active_plan_ref`,
  `active_objective`, `last_review_batch`; per-field last-write-wins) (`Q1`).
- The **GitHub gateway *contract*** — operation names + payload shapes, **verification-only
  set** for Phase 0 (`Q9`, `Q10`). Contract only; implementations land in T5/T6.

**Acceptance gate.** A **registry self-check** (precursor to a `perk doctor` check) validates
**graph integrity** (every predecessor/successor names a real stage; each stage conforms to the
descriptor shape) and **vocabulary membership for whatever `reads`/`writes`/`requires` keys are
declared** (the set grows as stages are built); **both planes parse `registry.yaml`** from their
bundled copy.

**Tests (thin seam).** A registry-validation test (vocabulary membership + graph integrity).

**Depends on.** T1.

---

## T3 — State-tiering helpers (both planes), no workflow logic

**Goal.** Real read/write helpers for the cache and session tiers — the ROADMAP's explicit
Phase-0 proof — with zero workflow semantics on top.

**Deliverables.**
- **Python (CLI/launcher side):** `.pi/workflow/` cache I/O; `run_id` mint (ULID); `PERK_RUN_ID`
  emit at launch.
- **TS (extension side):** claim `PERK_RUN_ID` on `session_start` (read + verify + mark
  consumed); the single **`perk:workflow-state`** custom entry via `appendEntry`, **rebuilt by
  scanning entries on both `session_start` and `session_tree`** with per-field last-write-wins
  (`Q1`); cache I/O mirroring the Python contract; the **tiered verified-linkage** helper
  (read-back + establish-before-consume; strict vs best-effort-with-logging) (`Q3`).

**Acceptance gate.** The ROADMAP's Phase-0 proof, demonstrated end-to-end: a command **persists
session state via `appendEntry`, restores it on reload and after `/tree`, and reads/writes the
local cache**; the `run_id` round-trips **shell → `PERK_RUN_ID` → claim → `perk:workflow-state`**.

**Tests (thin seam).** Cache round-trip test; `run_id` mint + round-trip test;
workflow-state rebuild/last-write-wins test.

**Depends on.** T2.

---

## T4 — CLI exterior core

**Goal.** The `perk` CLI plumbing that later stages plug into: config, registry-generated
subcommands, worktrees, and the launch primitive.

**Deliverables.**
- **TOML config loader** — `.pi/perk.toml` (committed) + `.pi/perk.local.toml` (gitignored),
  via `tomllib` (`Q13`).
- **Subcommand generation from `registry.yaml`** (`foundational #3`): `perk <stage>` exists for
  each stage with a stubbed handler ("not yet — Phase 1/2"). The cold-door *handlers* arrive
  with their stages later; T4 builds the generation.
- **Worktree lifecycle** — `perk worktree create / list / remove`.
- **Process-launch primitive** — exec `pi`, primed for a stage: sets `PERK_RUN_ID`, runs in the
  stage's worktree, selects the stage's mode/door.
- **Extend `perk init`** (init spine) to scaffold `.pi/perk.toml` (committed) +
  `.pi/perk.local.toml` (gitignored) and to manage the `.gitignore` transient-state entries —
  idempotently.

**Acceptance gate.** `perk <stage>` subcommands are present and **registry-generated**; `perk
worktree …` creates/lists/removes; the launch primitive starts a `pi` that **claims the run_id**
(closing the loop with T3 — shell-minted id appears in the launched session's
`perk:workflow-state`); **`perk init` now scaffolds the config files** and re-running it remains
a no-op.

**Depends on.** T2, T3.

---

## T5 — Complete & harden `perk init`

**Goal.** Finish the init spine begun in T1: the remaining verification, capability tracking,
flags, and handoff — so a single `perk init` *fully* converges a repo. (settings.json + borrowed
packages landed in T1; config + `.gitignore` in T4; T5 adds the rest.)

**Deliverables.** Port erk's idempotent, multi-step init (shell-first; the agent can't
bootstrap itself):
- **Verify environment** — git repo, `gh`/git/node available, GitHub auth (fail with
  remediation; never mutate).
- **GitHub — verification-only** in Phase 0 (no mutation); labels are created lazily by
  `/plan-save` in Phase 1 (`Q9`). Uses the gateway contract's verification ops (impl lands
  here).
- **Required-vs-optional capability tracking** — record which perk pieces and borrowed packages
  are enabled; required are always installed, optional are opt-in (capability model,
  PRIOR_ART §9).
- **Flags** — `--upgrade` / `--force` / `--no-interactive`: detect already-initialized repos,
  preserve user config on upgrade, re-sync managed pieces.
- **Post-init handoff** — hand the agent a markdown file to execute (the literal start of perk
  dogfooding itself).
- **Supervisor surface** — `perk init` exposes `--json` with stable exit-code /
  `{success, error_type, message}` semantics (cli-vs-pi §3.2): it is a canonical command the
  Phase 3 supervisor and the test harness parse, so the machine surface is established now, not
  retrofit.

**Acceptance gate.** `perk init` is now the **single convergence command** for a repo: on a
fresh clone it verifies env, installs/scaffolds every managed piece, and fires the post-init
handoff; on an initialized repo it is a no-op; `--upgrade` re-syncs managed pieces while
preserving user config; `--force` / `--no-interactive` behave.

**Depends on.** T4 (and the gateway contract from T2).

---

## T6 — `perk doctor`

**Goal.** Keep the borrowed-package + GitHub + state setup trustworthy while everything else is
in flux. `doctor` is `init`'s diagnostic twin: `init` converges a coherent repo *forward* to the
current desired state, while `doctor --fix` diagnoses and repairs drift and **legacy oddities**
that would be inelegant to bake into `init` for backwards compatibility alone.

**Deliverables.** Port erk's grouped health checks with **structured results** (`passed` /
`warning` / `info` / `message` / `details` / `remediation`), condensed-vs-`--verbose` output,
and consolidated remediation. Check groups, adapted to Pi:
- **Environment / User Setup** — pi version, `gh`/git/node, GitHub auth.
- **Package Setup** — perk package loaded, borrowed/recommended packages present and at
  expected versions, `.pi/settings.json` wiring intact.
- **Repository Setup** — `.pi/workflow/` integrity, config valid, `.gitignore` entries, GitHub
  scaffolding (uses the gateway verification impl).
- **State consistency** — `perk:workflow-state` coherent with the cache and GitHub.
- Folds in **T2's registry self-check**.
- **`--fix`** — apply known remediations, including **backwards-compat migrations and one-off
  repairs** of legacy/partial state. This is the deliberate home for transitional fixups, so
  `perk init` stays a clean forward-convergence path rather than accreting version-specific
  branches.
- **`--json` + stable exit codes** — `doctor` is the other canonical supervisor command
  (cli-vs-pi §3.2); serialize the structured results to machine-readable output alongside the
  condensed/`--verbose` human view, with stable exit codes.
- **Self-vs-consumer dual mode** — check everything in perk's own repo; only the enabled set in
  a consumer repo (PRIOR_ART §9).
- Defer erk's `doctor workflow` GitHub-CI smoke test to **Phase 3** (needs the worker + queue).

**Acceptance gate.** `perk doctor` reports health on an init'd repo; `--fix` remediates a
deliberately-broken setup; dual mode distinguishes self vs consumer.

**Depends on.** T5.

---

## T7 — Phase-0 dogfood gate *(checkpoint, not a build turn)*

**Goal.** Tie the bow and prove the gate that opens Phase 1. This is a **half-turn checkpoint** —
mostly verification and a docs pass, not new machinery — kept as its own boundary so "Phase 0 is
done" is an explicit, visible gate rather than an implicit tail of T6.

**Deliverables.**
- Finalize `AGENTS.md` / conventions against what actually got built.
- Demonstrate the gate end-to-end.

**Acceptance gate (the ROADMAP's Phase-0 gate).** A later phase can be **planned in read-only
plan mode with a live todo overlay, on a `perk init`-scaffolded, `perk doctor`-healthy repo** —
ideally by authoring the **Phase-1 plan itself** this way.

**Depends on.** T5, T6.

---

## Explicitly deferred (not Phase 0)

- Cold-door **stage handlers** and the spine commands (`/plan-save`, `/implement`, …) — Phase 1.
- **Per-stage `reads`/`writes`/`requires` *values*** — T2 locks the descriptor shape + the stage
  graph; each stage's actual state-I/O is filled as its handler lands (Phase 1+), so Phase 0 never
  authors unverified state-I/O for unbuilt stages.
- The **tool-gating primitive** and perk-owned plan mode — Phase 2.
- The **full SDK command/extension test harness** — Phase 1 (Phase 0 keeps only the thin seam).
- **GitHub mutation** (label creation, PR/issue writes) — lazily in Phase 1; `init` is
  verification-only.
- `doctor workflow` GitHub-CI smoke test — Phase 3.
- **Objectives**, CI executor, review/`address` loop — Phase 2.
- **Untrusted-input hygiene & project-agent scoping** (agent-stuff §10, pi §8) — no agents or
  GitHub-text-fed-to-model exist in Phase 0; the wrapping/scoping pattern lands with the first
  comment ingestion / agent spawn in Phase 2. (The T5 post-init handoff file is perk-owned and
  low-risk.)
- **Shell-activation / cd-the-parent-shell movement primitives** (`source <(perk … --script)`,
  cli-vs-pi §2.2) — Phase 0's `perk worktree create` only creates and reports the path; *moving*
  the parent shell into a worktree is deferred to Phase 1. Recorded here so it's a choice, not a
  gap.

## Definition of done for Phase 0

All seven gates pass, and the T7 gate holds: **perk can plan its own next phase**, on a repo it
scaffolded and keeps healthy, using the borrowed scaffolding — without any of perk's own
workflow stages existing yet.
