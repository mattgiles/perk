# Phase 0 · Turn 2 — Author & lock the shared contracts

Detailed execution plan for **T2** of [phase-0-plan.md](./phase-0-plan.md). T2 turns the
Q1–Q13 decisions (see [foundation-open-questions.md](./foundation-open-questions.md)) into
**concrete, parseable files in `shared/`** and makes "lock before building" executable via a
**self-check that runs on both planes**. It is the first turn that *may* be authored in borrowed
plan mode (the T1 crossover is green).

> **Scope discipline.** T2 **locks the registry *shape*, the stage *graph*, and the state-key
> *vocabulary*** and authors the four non-registry contracts as specs. It does **not** build the
> state-tiering helpers (T3), the config loader / subcommand generation / worktrees / launch
> (T4), the gateway *implementations* (T5), or `doctor` (T6). The genuinely-unknowable per-stage
> **`reads`/`writes`/`requires` values stay empty** — filling them now would author Phase-2
> fiction (see §5, revision-confirmed below).

---

## 1. Objective & the gate

**Goal.** Author `shared/registry.yaml` (the stage registry + the state-key vocabulary) and
`shared/contracts.md` (the four locked specs), and ship a **registry self-check** that both
planes exercise — Python authoritatively (`perk registry check`), TS as a parse-proof (the
existing `PERK_SELFCHECK` sentinel, extended). After T2, both planes parse their *own bundled*
`registry.yaml`, and the registry is provably internally consistent.

**Hard gate (must pass to land T2).** On a fresh clone, via `scripts/verify-t2.sh`:
1. `perk registry check` exits 0 on the bundled registry and reports `6 stages, graph
   consistent, N state keys` (the **Python** plane parses + fully validates).
2. The **TS** plane parses its bundled `registry.yaml` on load and the `PERK_SELFCHECK` sentinel
   reports `registry=ok stages=6` (proves the YAML loads + the `shared/` bundle resolves on the
   extension side).
3. A built **wheel** and a built **npm tarball** each physically carry `registry.yaml` **and**
   `contracts.md` (wheel → `perk/_shared/`; tarball → `shared/`).
4. `pytest tests/test_registry.py` passes: the validator **accepts** the real registry and
   **rejects** each negative fixture (dangling edge, asymmetric edge, unknown state key, bad
   enum value).

There is no "crossover" sub-goal in T2 — that was a T1-only concern.

---

## 2. Grounding & doc lineage (what governs T2, and what's superseded)

T2 is mostly transcription of already-decided things, but three lineage facts are load-bearing
and easy to get wrong:

- **The descriptor shape is Q4 (expanded), not cli-vs-pi §4.4.** cli-vs-pi.md §4.4 has a
  *candidate* stage table that is **pre-Q5/Q11** — it still shows `/pr-submit`, `/ship`,
  `/plan-save` and objective-coupled reads/writes. **Q5/Q11 supersede it:** the MVP set is
  `plan, save, implement, submit, land, learn` with **flat command ids** (`command = id`,
  slash = `/id`). Use Q4/Q5/Q11; treat §4.4 as motivation only.
- **No codegen — parse the one YAML directly in both planes (Q6).** cli-vs-pi.md §3 says the
  shared contract is consumed "often via codegen"; **Q6 overrode that** — one authored YAML,
  parsed directly by each plane, no generation step to drift. T2 therefore adds **two small
  YAML-parser deps** (§5), not a build step.
- **The registry must record *door legality per target* (cli-vs-pi §4.2/§4.5/§6.4–6.5).** The
  `doors {warm, cold_local, cold_remote}` field is not just "in-session vs cold" — `cold_local`
  vs `cold_remote` is the **local-vs-remote target** seam, and a stage may be *permanently*
  remote-blocked. So `cold_remote: false` in the MVP carries **real "remote-blocked" semantics**,
  not merely "the Phase-3 executor isn't built yet."

Pi mechanics the contracts reference (confirmed in pi--best-practices.md §3–§4, §8; cited inline
in §8 below) are unchanged from what T1 verified — `appendEntry` + `getBranch()` scan, restore on
`session_start` **and** `session_tree`, `parentSession`/`session_before_fork` for fork detection,
the `PERK_RUN_ID` env channel.

---

## 3. The seven revisions folded in (from the prior-art pass)

Recorded so the table below isn't mistaken for arbitrary:

1. **`plan` has a warm door** (cli-vs-pi §4.4 lists `/plan`) → `warm: true`.
2. **`cold_remote` is a locked field, `false` everywhere in MVP**, with documented
   remote-blocked semantics (Phase-3 executor flips specific stages on).
3. **Door legality is grounded in the fresh-context rule** (cli-vs-pi §4/§4.1): `implement` is
   **cold-only** (`warm: false`) — a deliberate tightening over §4.4's literal warm `/implement`,
   because implement must not inherit the planning conversation (the plan→implement transition is
   the canonical `ctx.newSession({parentSession})` handoff, pi §8).
4. **Flat command ids (Q11) supersede §4.4's slash names.** Nuance recorded: the *warm* `save`
   is implemented in Phase 1 by the plan-mode **terminating tool** (erk's `/plan-save`), but the
   stage **id stays `save`**.
5. **`perk registry check` is a developer/doctor/CI command, not an agent affordance** (cli-vs-pi
   §3.2/§6.6). `--json` is for the supervisor/CI/doctor; the *agent* reads registry data via an
   **extension tool** (Phase 1+), never by shelling `perk`. Do not rebuild erk's retired
   `erk schema` surface.
6. **`cache.plan-ref` is provider-agnostic** (PRIOR_ART §2: `provider`, `pr_id` as a **string**,
   `url`, `labels`, `objective_id`); full schema is Phase 1. The vocabulary key exists now; its
   payload is documented as provider-agnostic in `contracts.md`.
7. **`reads`/`writes`/`requires` stay empty** — *strengthened*, because §4.4's per-stage I/O
   leans on **objectives**, which are **Phase-2 deferred (Q5)**.

---

## 4. Repo additions (end of T2)

```
perk/
├── shared/
│   ├── README.md             # (updated: points at the authored contracts)
│   ├── registry.yaml         # NEW — stage registry + state-key vocabulary (parsed by both planes)
│   └── contracts.md          # NEW — the four locked specs (layout, PERK_RUN_ID, workflow-state, gateway)
├── perk/
│   ├── registry.py           # NEW — typed loader + validator (the self-check core; T6 doctor folds it in)
│   └── cli/commands/
│       └── registry_cmd.py    # NEW — `perk registry check` / `perk registry show` (thin, per python-cli-guidelines)
├── extension/
│   ├── registry.ts           # NEW — parse the bundled registry.yaml on the TS plane
│   └── index.ts              # (modified: PERK_SELFCHECK sentinel also reports `registry=ok stages=N`)
├── tests/
│   └── test_registry.py      # NEW — validator: accept real registry, reject negative fixtures
├── scripts/
│   └── verify-t2.sh          # NEW — the T2 hard gate (both planes + artifact bundling)
├── pyproject.toml            # (modified: add `pyyaml` runtime dep)
└── package.json              # (modified: add `yaml` runtime dep)
```

Bundling rides entirely on T1's mechanism — `force-include shared → perk/_shared` (wheel) and
`files: ["shared/", …]` (tarball). **The new files land in `shared/`, so they bundle for free;**
verify-t2.sh check 3 asserts it rather than assuming it.

---

## 5. Locked choices (decisions + revisions)

| Choice | Locked value | Why / easy-to-forget detail |
|---|---|---|
| Contract files | **2 files**: `registry.yaml` (parsed) + `contracts.md` (prose specs) | Each non-registry contract gets one hand-written impl per plane; prose locks them without a machine schema. |
| YAML deps | **`pyyaml`** (Python, runtime) + **`yaml`** (TS, runtime) | **Runtime, not dev** — the installed CLI and the installed extension parse the registry. TS installs run `--omit=dev`, so `yaml` **must be in `dependencies`**, not `devDependencies`. |
| ty + pyyaml | rely on bundled typeshed stubs | ty/pyright ship PyYAML stubs; if `import yaml` doesn't type-check, add **`types-pyyaml`** to the dev group (not a blanket ignore). |
| Per-stage fill depth | lock everything **except** `reads`/`writes`/`requires` (those = `[]`) | Includes `doors`, `worktree`, `mode`, `run_id`, `command`, `predecessors`, `successors`. |
| `doors` / `run_id` representation | two sibling maps over `{warm, cold_local, cold_remote}` (Q4 literal) | `run_id` policy is keyed by the **same three doors**; validator ties them (legal door ⇒ policy present). |
| `run_id` policy | uniform now: `warm: keep`, `cold_local: mint`, `cold_remote: mint` (Q2) | Field is kept though uniform — the **shape** is locked (Q4) and future stages may diverge; validator enforces the Q2 invariant (`warm⇒keep`, `cold⇒mint`). |
| Self-check surface | real `perk registry check` (+ `perk registry show`); **not** an agent affordance | `--json` for supervisor/CI/doctor only (revision 5). T6 `doctor` folds the validator in. |
| TS proof in T2 | extend the **existing `PERK_SELFCHECK` sentinel** | **Defer the TS unit-test runner to T3** — T2's TS job is "parse the bundled copy," provable end-to-end via the sentinel; no new TS test harness yet. |
| `schema_version` | `1` at the top of `registry.yaml` | Forward-compat hook so T6 `doctor --fix` can recognize an old shape; loader asserts it understands the value. |
| Gateway depth | **verification-only ops authored fully**; mutation ops **named-only** | `check_auth`, `check_repo_access` get payload shapes; `create_label`/plan/PR writes are listed by name, payloads deferred to Phase 1 (Q7/Q9) — no fiction. |
| Verify wiring | add `scripts/verify-t2.sh`; `just verify` runs **t1 + t2** | Gates are cumulative; T1's gate must keep passing. |

---

## 6. Work breakdown (ordered)

No de-risking spike this time — the riskiest mechanic (bundling/resolution) was retired in T1.

### T2.a — Author `shared/registry.yaml`
The full schema (§7): `schema_version`, the `state_keys` vocabulary (three tiers), and the six
MVP stages with every field locked except `reads`/`writes`/`requires` (`[]`). Inline comments
document *why* each transition is legal and what each state key means (the whole reason Q6 chose
YAML over JSON).
*Accept:* `pyyaml` `safe_load` parses it; the stage count is 6.

### T2.b — Author `shared/contracts.md`
The four locked specs (§8), with the easy-to-forget Pi mechanics cited inline: `.pi/workflow/`
layout, the `PERK_RUN_ID` protocol, the `perk:workflow-state` schema, and the GitHub gateway
contract (verification-only authored; mutation named-only).
*Accept:* contracts.md exists and is internally consistent with `registry.yaml`'s vocabulary.

### T2.c — Python loader + validator (`perk/registry.py`)
Typed `Stage` / `Registry` structures; `load_registry(shared_dir())` via `safe_load`; a
`validate() -> list[Issue]` implementing the §9 rules (shape, enums, symmetric graph, vocabulary
membership). LBYL throughout (dignified-python); raise `UserFacingCliError` only at the CLI
boundary, not in the validator (it returns structured issues so T6 `doctor` can reuse it).
*Accept:* `validate()` returns no issues on the real registry; returns the expected issue on each
fixture.

### T2.d — CLI command (`perk/cli/commands/registry_cmd.py`)
A `perk registry` group with `check` (run the validator; human summary to stderr; non-zero exit +
`UserFacingCliError` on issues; optional `--json` for CI) and `show` (dump the parsed registry —
a dev/doctor convenience, **not** an agent data path). Thin adapters over `perk/registry.py`, per
[python-cli-guidelines.md](./python-cli-guidelines.md).
*Accept:* hard-gate check 1.

### T2.e — TS loader + sentinel extension (`extension/registry.ts`, `index.ts`)
`extension/registry.ts`: `loadRegistry()` reads `sharedDir()/registry.yaml` and `yaml.parse`s it;
a thin structural assertion (top-level keys present, `stages` is a non-empty array). Extend the
**existing** `PERK_SELFCHECK` path in `index.ts` to call it and append `registry=ok stages=<n>` to
the sentinel line. Guard with `ctx.hasUI` discipline as before (the selfcheck path is env-gated,
not UI).
*Accept:* hard-gate check 2.

### T2.f — Deps, tests, verify script
Add `pyyaml` to `[project] dependencies`; add `yaml` to `package.json` `dependencies`; `uv lock`
+ `uv sync`; `npm install`. Write `tests/test_registry.py` (accept real + reject the four
negative fixtures) and `scripts/verify-t2.sh` (the four checks); wire `just verify` to run both
gate scripts. Keep `ruff`/`ty`/`biome`/`tsc` green on the new code.
*Accept:* the whole T2 gate is one command; `just ci` stays green.

---

## 7. `registry.yaml` — the locked spec

Top-level shape:

```yaml
schema_version: 1

# State-key vocabulary (Q4). reads/writes/requires draw ONLY from these, as dotted
# "<tier>.<key>" strings. The validator flattens this to a set for membership checks.
state_keys:
  github:  [plan, objective, pr, labels, comments, review-threads]   # tier 1 · canonical
  cache:   [plan, plan-ref, scratch, handoff, markers]               # tier 2 · .pi/workflow/
  session: [workflow-state]                                          # tier 3 · session entries

stages:
  - id: plan
    summary: Explore the codebase and draft a plan (read-only).
    mode: read-only            # read-only | read-write
    worktree: none             # none | reuse | create
    doors:   { warm: true,  cold_local: true,  cold_remote: false }
    run_id:  { warm: keep,  cold_local: mint,  cold_remote: mint }
    command: plan              # extension command (stub until Phase 1); slash = /plan
    requires: []               # LAZY — Q3 preconditions, filled when the handler lands
    reads:    []               # LAZY — enumerated state keys, filled per handler (Phase 1+)
    writes:   []               # LAZY
    predecessors: []
    successors:   [save]
  # … save, implement, submit, land, learn (full values per the §7.1 table) …
```

### 7.1 The six stages (every field except reads/writes/requires)

| id | summary (1-line) | mode | worktree | warm | cold_local | cold_remote | command | preds | succs |
|---|---|---|---|---|---|---|---|---|---|
| `plan` | draft a plan (read-only) | read-only | none | ✓ | ✓ | ✗ | `plan` | — | `save` |
| `save` | persist the plan to GitHub; the read-only→read-write boundary | read-write | none | ✓ | ✓ | ✗ | `save` | `plan` | `implement` |
| `implement` | do the work on a branch (fresh context) | read-write | create | ✗ | ✓ | ✗ | `implement` | `save` | `submit` |
| `submit` | branch → draft PR | read-write | reuse | ✓ | ✓ | ✗ | `submit` | `implement` | `land` |
| `land` | ready/approved PR → merge + reconcile; sets `pending-learn` | read-write | reuse | ✓ | ✓ | ✗ | `land` | `submit` | `learn` |
| `learn` | capture learnings; clears `pending-learn` | read-write | reuse | ✓ | ✓ | ✗ | `learn` | `land` | — |

`run_id` for every stage: `{warm: keep, cold_local: mint, cold_remote: mint}` (Q2 uniform).
`reads`/`writes`/`requires` for every stage: `[]` (lazy).

**Easy-to-forget rationale baked into comments:**
- `plan`/`save` are `worktree: none` — no implementation branch exists until `implement`
  (PRIOR_ART §2: `branch_name`/`pr_number` are null during planning, populated at submit).
- `implement` is **cold-only + `worktree: create`** — it both needs fresh context (no planning
  conversation) and is the first stage that needs a branch; the cold door's positioning *is*
  erk's `prepare` step folded in (cli-vs-pi §4.4 footnote).
- `submit`/`land`/`learn` are `worktree: reuse` — they operate in the implementation worktree;
  `land`'s `pending-learn` marker (a `cache.markers` semaphore) **blocks worktree deletion until
  `learn` runs** (Q5), which is why `learn` is in the MVP at all.
- `cold_remote: false` everywhere = remote-blocked in MVP (no Phase-3 executor yet); the field is
  locked so the executor flips specific stages on later without a shape change.

---

## 8. `contracts.md` — the four locked specs

Prose contracts (no parser), each pinning exact names/paths/fields so T3–T5 implement against a
fixed target and T6 `doctor` can verify conformance.

### 8.1 `.pi/workflow/` layout (Q2)
```
.pi/workflow/
├── plans/                  # materialized plan cache (canonical copy stays in GitHub)
├── scratch/runs/<run_id>/  # per-run inter-process workflow files
├── handoff/<run_id>.json   # pre-session CLI→extension cold-door state (claimed on session_start)
└── markers/                # existence-based friction semaphores (e.g. pending-learn)
```
Keyed by the perk-owned **`run_id`** (a ULID), never the Pi session id (which does not exist at
cold-door launch time). GC is perk-owned (prune by terminal-stage-complete or age) — surfaced as
a `doctor` check + prune command later.

### 8.2 `PERK_RUN_ID` protocol (Q2) — easy-to-forget rules
- **Channel:** the CLI sets `PERK_RUN_ID=<ulid>` in the env before `exec pi` (the only clean
  launch channel; an initial message would pollute LLM context).
- **Claim:** on `session_start`, the extension reads `process.env.PERK_RUN_ID`, loads + verifies
  `handoff/<run_id>.json`, records `run_id` in `perk:workflow-state`, and **marks the handoff
  consumed** (Q3 establish-before-consume; strict read-back).
- **Fork ≠ branch.** `/fork` `/clone` `ctx.newSession({parentSession})` create a **new session
  file with a `parentSession` header** (detect via that header / `session_before_fork`) →
  **derive a child id `<run_id>.<n>`**, do *not* blindly inherit the env var. `/tree` branches
  **in place** (same file/process) → `PERK_RUN_ID` survives, `run_id` stays stable. (pi §3, §8.)
- **Warm keeps / cold mints.** A warm transition keeps `run_id`; a cold relaunch mints a new one
  **recording its predecessor** (so resume chains stay traceable) — exactly the registry
  `run_id` policy.

### 8.3 `perk:workflow-state` schema (Q1) — easy-to-forget mechanics
- **One namespaced custom entry** `perk:workflow-state`, holding
  `{run_id, pi_session_id, mode, active_plan_ref, active_objective, last_review_batch}`.
- **Persistence channel:** `pi.appendEntry("perk:workflow-state", data)`. (The *other* channel,
  tool-result `details`, is for state that *is* a tool's output — not this.)
- **Rebuild:** scan `ctx.sessionManager.getBranch()` for
  `entry.type === "custom" && entry.customType === "perk:workflow-state"`, **on `session_start`
  AND `session_tree`** (skipping `session_tree` is *the* stale-state bug). Per-field
  last-write-wins; borrow plan-mode's subtlety — only re-scan entries **after** the marker that
  began the current execution so stale fields don't resurrect.
- **`active_plan_ref`** points at the provider-agnostic plan-ref (§8.4); **`pi_session_id`** is
  Pi's own UUID, stored so `SessionManager.open`/`continueRecent` can resume.

### 8.4 GitHub gateway contract (Q9/Q10) — one contract, one impl per plane
- **Verification-only (Phase 0, authored now, no mutation):**
  - `check_auth() -> {ok, user, scopes, error?}` — `gh auth status`.
  - `check_repo_access() -> {ok, repo, can_push, error?}` — repo readable/writable.
- **Mutation ops (named only; payloads deferred to Phase 1, Q7/Q9):** `create_label`,
  `create_plan_issue`, `update_plan_header`, `create_pr`, `mark_pr_ready`, `merge_pr`,
  `resolve_review_threads`, … Recorded so the surface is visible; **not authored** (no fiction).
  - Known durable shape to **keep when authored** (PRIOR_ART §5/§11): thread resolution payload is
    `[{thread_id, comment}]` (objects, not a flat list) — review threads ≠ discussion comments.
- **Two implementations, same contract** (Q10): a Python gateway (CLI/worker) and a TS gateway
  (in-session mutations); either can later swap `gh`-shell → API-backed independently, and
  `doctor` verifies both. No in-process coupling between planes.

---

## 9. The self-check — exact rules

`validate(registry) -> list[Issue]` (Python authoritative; TS does a thin structural parse-proof).

**Shape** (per stage, hard error):
- required fields present: `id, summary, mode, worktree, doors, run_id, command, requires, reads,
  writes, predecessors, successors`.
- enums: `mode ∈ {read-only, read-write}`; `worktree ∈ {none, reuse, create}`;
  `doors` keys **exactly** `{warm, cold_local, cold_remote}`, values `bool`; `run_id` keys the
  same three, values `∈ {keep, mint}`.
- `run_id` invariant (Q2): every legal door (`doors[d] == true`) has `run_id[d]`; `warm ⇒ keep`,
  `cold_local`/`cold_remote ⇒ mint`.
- `id` unique across stages; `command` non-empty.

**Graph** (hard error):
- every `predecessors`/`successors` entry names a **real** stage id (no dangling edges).
- **symmetric**: `B ∈ A.successors ⇔ A ∈ B.predecessors` (catches one-sided edits).
- exactly one initial stage (`predecessors == []`) and at least one terminal (`successors == []`)
  — a sanity check on the spine; not a hard DAG requirement (Phase-2 branches like `address` will
  add edges).

**Vocabulary membership** (hard error):
- every key in `reads`/`writes`/`requires` is a flattened `state_keys` member (`<tier>.<key>`).
- *Empty today* — so this check is **near-vacuous in T2** but the machinery is live and grows.

**Deferred (built later, not in T2):** the Q4 **reachability** check ("every `reads`/`requires`
key is produced by some upstream `writes`; no stage reads what nothing writes") — meaningless
while `reads`/`writes` are empty; it gains teeth in Phase 1. Documented, not implemented as dead
logic.

**`schema_version`:** the loader asserts it understands the value (currently `1`); an unknown
version is a clear error pointing at `doctor` (the init-converges-forward / doctor-repairs split).

---

## 10. Acceptance gate — concrete, runnable checks (`scripts/verify-t2.sh`)

1. **Python self-check** — `perk registry check`; assert exit 0 and output contains
   `6 stages` + `graph consistent`.
2. **TS parse-proof** — launch `pi` with `PERK_SELFCHECK=1` (print mode, `hasUI=false`); assert
   the sentinel file contains `registry=ok stages=6`. (Reuses T1's watchdog-wrapped `pi` runner
   and env-gated sentinel; **only `pi` is watchdog-wrapped** — macOS has no `timeout`.)
3. **Artifacts bundle the contracts** — `uv build` then assert (via Python `zipfile`) the wheel
   contains `perk/_shared/registry.yaml` **and** `perk/_shared/contracts.md`; `npm pack` then
   assert (via Python `tarfile`) the tarball contains `package/shared/registry.yaml` **and**
   `package/shared/contracts.md`. *(Membership via `zipfile`/`tarfile`, never `unzip|grep` under
   `pipefail` — that's nondeterministic; T1 §14 gotcha.)*
4. **Validator tests** — `uv run pytest tests/test_registry.py`: accepts the real registry;
   rejects four fixtures — **dangling** successor, **asymmetric** edge, **unknown** state key in
   `reads`, **bad enum** (`mode: read`). These negative fixtures are what actually exercise the
   membership/shape checks while the real registry's `reads`/`writes` are empty.

`just verify` runs `verify-t1.sh` **and** `verify-t2.sh`; `just ci` (ruff + biome + ty + tsc +
pytest) stays green on the new Python and TS.

---

## 11. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| `import yaml` (TS) not resolvable / wrong types in extension | low-med | add `yaml` to **`dependencies`** (ships under `--omit=dev`); it carries its own TS types; `tsc` covers it |
| ty can't resolve PyYAML types | low | rely on bundled typeshed; if it fails, add `types-pyyaml` to the dev group (rule-specific, no blanket ignore) |
| Near-vacuous membership check gives false confidence | med | **negative fixtures** (check 4) exercise the validator directly; the real registry's empty `reads`/`writes` don't reduce coverage |
| Door/worktree values prove wrong when T4's launch primitive lands | med | the registry is the source of truth T4 *obeys*; a wrong cell is a normal contract refinement, not a rework — flagged in §7 as first-pass for the design-y cells |
| `contracts.md` drifts from `registry.yaml` vocabulary | low | both authored in the same turn; T6 `doctor` later cross-checks; vocabulary lives canonically in `registry.yaml` (contracts.md references it) |
| Over-authoring gateway mutation payloads (fiction) | med | **named-only** rule (§8.4); only verification ops get shapes in Phase 0 |

---

## 12. Explicitly out of scope for T2 (pointers)

- **State-tiering *helpers*** (cache I/O, `run_id` mint, `PERK_RUN_ID` emit/claim, the
  workflow-state read/write, verified-linkage helper) — **T3**. T2 only *specs* them.
- **Per-stage `reads`/`writes`/`requires` *values*** and the **reachability** check — Phase 1+,
  as each handler lands.
- **TOML config, registry→subcommand *generation*, worktrees, launch primitive** — **T4** (T4
  *consumes* this registry).
- **Gateway *implementations*** (even the verification ops) — Python in **T5**, TS in Phase 1.
- **TS unit-test runner** — **T3** (T2's TS proof is the sentinel).
- **`perk doctor`** (which folds in this validator) — **T6**.
- **Objectives, the `address` review loop, remote executor** — Phase 2/3 (they add stages/edges
  and flip `cold_remote` on).

## 13. Open questions to settle during T2

1. **`perk registry show` output format** — plain human table vs YAML echo. (Lean: human table;
   it's a dev/doctor convenience, never an agent path.)
2. **`pyyaml` vs `ruamel.yaml`** — `pyyaml` `safe_load` is sufficient (we only read); confirm no
   comment-preservation need (there isn't — the file is authored by hand, not rewritten).
3. **`ty` + PyYAML stubs** — confirm bundled typeshed resolves `yaml`; else add `types-pyyaml`.
4. **`summary` length cap** — keep one line; worth a soft lint in the validator? (Lean: no, keep
   the validator about structure.)

## 14. Definition of done

The four hard-gate checks in §10 pass via `scripts/verify-t2.sh` on a fresh clone;
`tests/test_registry.py` passes; both planes parse their **own bundled** `registry.yaml`; the
registry is provably consistent (shape + symmetric graph + vocabulary membership); `contracts.md`
locks the four specs with the easy-to-forget Pi mechanics cited; `just ci` and `just verify` (t1
+ t2) are green. T2 lands; **T4 can generate subcommands from this registry and T3 can build the
state helpers against these contracts.**

---

## 15. T2 outcomes (recorded after implementation)

**Status: implemented; T2 hard gate ALL PASS; T1 gate still PASS; `just ci` green.**

**Built (as planned):** `shared/registry.yaml` (6 stages, `state_keys` 3-tier vocabulary,
`schema_version: 1`) and `shared/contracts.md` (the four specs); `perk/registry.py` (typed
`Stage`/`Registry` + `load_registry` + `validate -> list[Issue]`); `perk/cli/commands/registry_cmd.py`
(`perk registry check` / `show`, wired into the root group); `extension/registry.ts` +
the extended `PERK_SELFCHECK` sentinel; `tests/test_registry.py`; `scripts/verify-t2.sh`;
`just verify` now runs t1 + t2.

**Gate results:** (1) `perk registry check` → `registry OK: 6 stages, graph consistent, 12 state
keys`; (2) extension sentinel → `registry=ok stages=6`; (3) wheel carries
`perk/_shared/{registry.yaml,contracts.md}`, tarball carries `package/shared/{registry.yaml,contracts.md}`;
(4) `tests/test_registry.py` 8 passed (real registry valid + 6 negative fixtures + schema-version
guard). Full suite 16 passed.

**Decisions confirmed by building:**
- **No door/worktree cell revised** — the §7.1 table authored cleanly and validated first try.
- **`reads`/`writes`/`requires` stayed empty** — the vocabulary-membership check is exercised
  entirely by the negative fixture (`github.bogus`), exactly as designed; the real registry needs
  no state-I/O yet.
- **`run_id` Q2 invariant is enforced** (`warm⇒keep`, `cold⇒mint`) and tested
  (`test_rejects_bad_run_id_invariant`), so the otherwise-uniform field earns its keep.
- **`perk registry check --json`** puts the JSON object on **stdout** and any human/error text on
  **stderr** — the supervisor/CI split holds (it is not an agent path).

**Deps locked:** `pyyaml>=6.0.3` (Python runtime, in `[project] dependencies`) and `yaml 2.9.0`
(TS runtime, in `package.json` `dependencies` — ships under `--omit=dev`). **ty resolved `yaml`
from bundled typeshed — no `types-pyyaml` needed.** `tsc` resolved `yaml`'s own types; biome
applied no fixes to `registry.ts`.

**Implementation notes (easy-to-forget, for later turns):**
- ty does **not** narrow `raw.get("k") if isinstance(raw.get("k"), str)` (two `.get()` calls) —
  use a typed coercion helper (`_str`/`_map`/`_str_list`). `doors`/`run_id` are typed
  `dict[str, Any]` on `Stage` because the parser is deliberately lenient and `validate()` (not the
  parser) reports bad shapes.
- The parser tolerates missing/ill-typed fields (empty defaults) so **all** consistency findings
  surface in one place (the validator) — which is what lets T6 `doctor` reuse `validate()` wholesale.
- Extending the T1 sentinel (rather than adding a TS test runner) kept the TS proof to one line and
  left the unit-test runner for T3, as planned.

**Still deferred (unchanged):** per-stage `reads`/`writes`/`requires` values + the reachability
check (Phase 1+); gateway *implementations* (T5/Phase 1); the TS unit-test runner (T3);
`perk doctor` folding in `validate()` (T6).

**Verify:** `bash scripts/verify-t2.sh` (4/4 PASS), `bash scripts/verify-t1.sh` (6/6 PASS),
`uv run pytest` (16 passed), `just ci` green.
