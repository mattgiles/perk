# Phase 0 · Turn 7 — the Phase-0 dogfood gate

> Implementation-level plan for **T7**. A **half-turn checkpoint**, not a build turn: tie the bow on
> Phase 0 and prove the ROADMAP gate that opens Phase 1. Mostly **verification + a docs pass + one
> dogfood demonstration**, plus the small cleanups that let Phase 0 land clean. The headline move is
> **recursive**: use the perk-scaffolded environment to *plan Phase 1 itself*, in read-only plan mode
> with a live todo overlay. **Python-touch only** (one tiny T6 correctness fix); **no new dependency**.

---

## 1. Objective & the gate

**Objective.** Make "Phase 0 is done" an **explicit, visible boundary** rather than an implicit tail
of T6. Reconcile the docs against what actually got built, bulk up the README to current reality, and
**demonstrate end-to-end** that the scaffolding is a usable planning substrate — by authoring the
Phase-1 plan on it.

**Acceptance gate (the ROADMAP's Phase-0 gate, from `phase-0-plan.md` §T7).** A later phase can be
**planned in read-only plan mode with a live todo overlay, on a `perk init`-scaffolded,
`perk doctor`-healthy repo** — ideally by authoring the **Phase-1 plan itself** this way.

**The gate, made concrete.** The gate's abstract phrases map onto wiring `perk init` already lays
down (the borrowed crossover scaffolding, `init.py:BORROWED_PACKAGES`):

| Gate phrase | Provided by (borrowed, Phase-0 borrow window) |
| --- | --- |
| read-only **plan mode** | `@tombell/pi-plan` — the `/plan` slash command (registry stage `command: plan`) |
| live **todo overlay** | `@juicesharp/rpiv-todo` |
| (supporting) statusline / diff review | `@tombell/pi-status`, `@tombell/pi-diff` |
| **scaffolded** + **healthy** | `perk init` wires all four; `perk doctor`'s `settings-wiring` check verifies they are present |

So the dogfood flow is: **launch `pi` in the perk repo (plan mode — read-only over the codebase),
explore Phase-1 requirements with the todo overlay tracking the planning sub-tasks live, and produce
`docs/planning/phase-1-plan.md` as the session output.** perk-owned `/plan-save` does not land until
Phase 1, so the plan is saved by hand at the end — that is the **borrow-then-own seam working as
designed**, not a gap.

**Honesty flag (a real T7 finding, not an assumption).** The `rpiv-todo` / `pi-plan` capabilities are
*inferred* from package names + the registry comments. T7's demonstration must **actually launch them
and confirm what they do**. If `rpiv-todo` is not a genuine live overlay (or `pi-plan` is not
read-only over the codebase), the gate prose or the borrowed set needs adjusting — and recording that
adjustment *is* a legitimate T7 deliverable.

---

## 2. Grounding & doc lineage (what governs T7)

- **`docs/phase-0-plan.md` §T7** — the deliverables (finalize `AGENTS.md`/conventions; bulk up
  `README.md`; demonstrate the gate) and the acceptance gate wording. Also §"Explicitly deferred"
  (what Phase 0 does *not* ship — quoted into the README/gate record so the boundary is honest).
- **`docs/ROADMAP.md`** — the Phase-0 → Phase-1 boundary this gate proves.
- **`shared/registry.yaml`** — the six-stage spine (`plan → save → implement → submit → land →
  learn`) and the `command:` mapping that ties stages to the borrowed `/plan` during the borrow
  window. The Phase-1 plan (this turn's dogfood artifact) decomposes the *handlers* for these stages.
- **`shared/contracts.md`** — the cross-plane contracts already locked (§8.1–§8.6); the Phase-1 plan
  fills the deferred per-stage `requires`/`reads`/`writes` *values* turn-by-turn, never up front.
- **The T1–T6 turn docs (`docs/phase-0-turn-1..4.md`, `docs/planning/phase-0-turn-5..6.md`)** and
  their **§15 outcomes** — the source of truth for "what actually got built," which AGENTS.md and the
  README are reconciled against.
- **`AGENTS.md`** — the init-managed block (never hand-edited) plus the new human-authored
  "developing perk" section this turn adds.
- **Pending review items** — the two T6 dignified-python findings (the `OSError` no-silent-pass
  broadening; promoting `init._is_self_repo` → public) folded in so Phase 0 closes clean.

---

## 3. What this turn is (and is not)

**Is.** A checkpoint: verification, doc reconciliation, the dogfood demonstration, and the small
hygiene that lets Phase 0 land as clean history.

**Is not.** New machinery. No new CLI commands, no new contracts, no new dependency. The only code
change is one tiny T6 correctness fix (§6 D1a). The Phase-1 *plan* is authored, but Phase-1
*machinery* is Phase 1's job.

**Anti-recursion note.** The dogfood artifact is **`phase-1-plan.md`**, authored in plan mode. The
**turn-7 doc itself** (this file) is normal planning, written ahead of the demonstration. We do not
chase our tail: T7 plans the checkpoint; the checkpoint produces the Phase-1 plan.

---

## 4. Repo changes (end of T7)

| Path | State | Why |
| --- | --- | --- |
| `perk/doctor.py` | CHANGED | D1a: broaden `_managed_checks` except to `(UserFacingCliError, OSError)` — honor T6's no-silent-pass at the file-read boundary. |
| `perk/init.py` | CHANGED | D1a: promote `_is_self_repo` → public `is_self_repo` (doctor's legitimate shared query); keep a thin private alias only if any internal caller needs it. |
| `perk/cli/commands/doctor_cmd.py` / `tests/test_doctor.py` | CHANGED | follow the rename; add one unreadable-managed-file test. |
| `README.md` | CHANGED | D4: bulk up from the stale "Turn 1" stub to the real Phase-0 surface. |
| `AGENTS.md` | CHANGED | D5: add the human-authored "developing perk" conventions section (above/below the managed block). |
| `docs/phase-0-turn-1.md` → `docs/planning/phase-0-turn-1.md` (and 2,3,4) | MOVED | D1b: finish the `docs/planning/` reorg; fix `./`→`../` links inside the moved docs. |
| `docs/index.md` | CHANGED | D1b: repoint turn-1..4 links to `./planning/…`; add the turn-7 + phase-1-plan + phase-0-gate entries. |
| `docs/planning/phase-1-plan.md` | NEW | D3: the dogfood artifact — Phase-1 decomposition authored in plan mode. |
| `docs/phase-0-gate.md` | NEW | D2: the gate record — what was run/observed end-to-end; the "Phase 0 is done" boundary. |
| `scripts/verify-t7.sh` | NEW | D2: the automatable *preconditions* of the gate. |
| `justfile` | CHANGED | `verify` runs t1..t7. |

**Not touched:** `pyproject.toml`, `package.json`, `shared/` (no contract or registry change — T7
verifies, it does not redefine). The turn-4/5/6 plan *bodies* are **left as-is** (their §15 outcomes
already reconcile them; they are historical records, not living specs — D1c).

---

## 5. Locked choices (D1–D7, all agreed)

- **D1 — Scope = the three deliverables + targeted hygiene.** Fold in **(a)** the two T6 review fixes
  (`OSError` broadening + `is_self_repo` promotion) and **(b)** the `docs/planning/` reorg; **(c)**
  leave the turn-4/5/6 plan-body drift (the §15 outcomes reconcile it — don't rewrite history).
- **D2 — "Demonstrate the gate" = three artifacts.** `scripts/verify-t7.sh` (automatable
  preconditions), `docs/planning/phase-1-plan.md` (living proof), and `docs/phase-0-gate.md` (the
  end-to-end gate record, its own file).
- **D3 — Phase-1 plan at phase-decomposition granularity.** Objective, acceptance gate, a turn
  decomposition (T1..Tn), dependencies, deferrals — **not** full per-turn docs. The drift-prone
  per-stage state-I/O stays deferred to each handler's turn (mirrors the registry's empty
  `requires`/`reads`/`writes`); a phase decomposition is legitimately forward-looking, fiction is not.
- **D4 — README depth = built surface + a tight "where this is going" pointer.** Describe what is
  built; flag the spine as clearly-future; no aspirational command docs.
- **D5 — AGENTS.md gains a human-authored "developing perk" section** distinct from the init-managed
  "using perk" block (which stays untouched by hand).
- **D6 — Commit strategy = per-turn catch-up** (T4/T5/T6/T7), matching the existing `Phase 0, Turn N`
  history. T7 **leaves the tree ready and staged-clean**; the human runs the commits (the agent does
  not auto-commit).
- **D7 — Anti-recursion** (§3): the dogfood artifact is `phase-1-plan.md`; this turn doc is normal
  planning.

---

## 6. Work breakdown (ordered)

### T7.a — Fold in the T6 review fixes (D1a)
- `perk/doctor.py` — `_managed_checks`: `except (UserFacingCliError, OSError) as exc:` with branched
  detail (`exc.format_message()` for `UserFacingCliError`, else `str(exc)`); the un-evaluable managed
  piece becomes a `fail` check, never a crash.
- `perk/init.py` — rename `_is_self_repo` → `is_self_repo` (public); update `doctor.py`,
  `init.py`'s own callers, and any test references.
- `tests/test_doctor.py` — add `test_unreadable_managed_file_is_fail` (chmod a managed file
  unreadable → `_managed_checks` reports `fail`, `run_doctor` does not raise). *(Skip-guard on
  platforms/CI where the test runs as root and `chmod` cannot revoke read.)*
- Re-run T6 gate + `just ci`; both must stay green.

### T7.b — Finish the `docs/planning/` reorg (D1b)
- `git mv docs/phase-0-turn-{1,2,3,4}.md docs/planning/`.
- Fix relative links *inside* the moved docs (`./` → `../` for `docs/`-root targets; sibling
  `phase-0-turn-N.md` links stay relative within `planning/`).
- `docs/index.md` — repoint the turn-1..4 rows to `./planning/…`; keep the table ordering sane.

### T7.c — Bulk up `README.md` (D4)
Sections (built-surface-first):
1. **What perk is** — Pi-native plan-oriented workflow; the *exterior* (Python `perk` CLI) /
   *interior* (TS Pi extension) split; self-bootstrapping.
2. **Quickstart** — `uv tool install` / `perk init` / `perk doctor` on a target repo.
3. **The Phase-0 command surface (as built)** — `init`, `doctor`, `worktree create/list/remove`,
   `state`, `registry`, and the `perk <stage> -- <pi args>` launchers. One line each; no fiction.
4. **Where this is going** — the `plan → save → implement → submit → land → learn` spine (Phase 1),
   borrow-then-own, a pointer to `docs/index.md` and `docs/ROADMAP.md`.
5. **Develop** — keep the existing toolchain/`just` block; drop the stale "Turn 1" status line and
   replace with "Phase 0 complete; Phase 1 next."

### T7.d — Finalize `AGENTS.md` conventions (D5)
Add a human-authored **"Developing perk"** section (outside the managed markers) capturing the
conventions that emerged building T1–T6:
- the two-plane exterior/interior split and where each kind of logic lives;
- the **verify-gate discipline** (`scripts/verify-tN.sh`, `just verify`, dogfood gates per phase);
- **dignified-python** as the Python standard; the two pinned parallel toolchains (uv/ruff/ty +
  npm/biome/tsc) wired through the `justfile`;
- **"amend the contract, don't drift"** (contract behavior changes ⇒ same-turn `shared/contracts.md`
  amendment);
- the **per-turn-doc + §15-outcomes** convention (plan → implement → record what actually built).

### T7.e — The gate record `docs/phase-0-gate.md` (D2)
A short, honest record: the end-to-end run (init → doctor healthy → launch pi → plan mode + todo
overlay observed → Phase-1 plan produced), what the borrowed packages *actually* did (the §1 honesty
flag, resolved), the Phase-0 deferral list (quoted from `phase-0-plan.md`), and the explicit
assertion **"Phase 0 gate met."** This is the visible boundary.

### T7.f — The dogfood artifact `docs/planning/phase-1-plan.md` (D3)
Authored in the scaffolded plan mode (the demonstration itself). Phase-decomposition granularity: the
Phase-1 objective + acceptance gate, the turn breakdown for the workflow spine handlers + the SDK
command/extension test harness, dependencies, and deferrals. Per-stage state-I/O stays deferred.

### T7.g — `scripts/verify-t7.sh` + `justfile` (D2)
The automatable preconditions (see §7). `just verify` runs t1..t7.

---

## 7. Acceptance gate — concrete, runnable checks (`scripts/verify-t7.sh`)

The *interactive* part of the gate (a human launching `pi`, observing plan mode + the live overlay,
authoring the plan) cannot run in CI. `verify-t7.sh` asserts the **preconditions** that make that
demonstration possible; the interactive proof is captured in `docs/phase-0-gate.md`.

1. **Scaffold + healthy.** Fresh git repo → `perk init` → `perk doctor --json` reports
   `healthy: true`, exit 0.
2. **Borrowed substrate wired.** `.pi/settings.json` `packages` contains all four borrowed entries
   (`@tombell/pi-plan`, `@juicesharp/rpiv-todo`, `@tombell/pi-diff`, `@tombell/pi-status`) **and** the
   `@perk/pi` self entry — and `perk doctor` reports the `settings-wiring` check `ok`.
3. **`pi` launchable.** `pi` is on PATH (the plan-mode host exists); `perk plan --dry-run` resolves a
   primed launch (read-only stage; side-effect-free).
4. **Dogfood artifact exists.** `docs/planning/phase-1-plan.md` is present and non-trivial (has the
   Phase-1 objective + a turn decomposition).
5. **Gate record exists.** `docs/phase-0-gate.md` is present and asserts the gate is met.
6. **Cumulative gates still green.** `bash scripts/verify-t{1..6}.sh` all PASS (T7 changed code in
   doctor/init — prove no regression) and `just ci` is green.

CI-robust: GitHub stays non-fatal; checks assert `healthy`/exit/`packages`, never live `pi`-session
behavior.

---

## 8. Risks & mitigations

- **R1 — The borrowed packages don't deliver the gate's promise** (rpiv-todo isn't a live overlay;
  pi-plan isn't read-only over the codebase). *Mitigation:* §1 honesty flag — the demonstration
  *tests* them; a mismatch is recorded in `phase-0-gate.md` and, if material, the borrowed set or the
  gate prose is adjusted (a real, allowed T7 outcome, not a silent pass).
- **R2 — The Phase-1 plan drifts into fiction** about unbuilt stage state-I/O. *Mitigation:* D3
  granularity cap — decomposition only; per-stage `requires`/`reads`/`writes` stay deferred, mirroring
  the registry.
- **R3 — README/AGENTS over-promise** (documenting commands that don't exist). *Mitigation:*
  built-surface-first (D4); every documented command is one that ships in T1–T6.
- **R4 — The `is_self_repo` rename misses a caller.** *Mitigation:* grep + `just ci`; ty catches the
  unresolved reference.
- **R5 — The unreadable-file test is flaky under root/CI** (chmod can't revoke read for root).
  *Mitigation:* skip-guard when running as root or when a probe write-after-chmod still succeeds.

---

## 9. Explicitly out of scope for T7 (pointers)

- Everything in `phase-0-plan.md` §"Explicitly deferred" — the stage *handlers* and spine commands
  (Phase 1), per-stage state-I/O *values* (filled per handler), tool-gating + perk-owned plan mode
  (Phase 2), the full SDK command/extension test harness (Phase 1; T7 only *plans* it), GitHub
  mutation (Phase 1), `doctor workflow` CI smoke (Phase 3), objectives/CI-executor/review loop
  (Phase 2), untrusted-input hygiene (Phase 2), shell-activation movement primitives (Phase 1).
- **Perk-owned `/plan-save`** — the Phase-1 plan is hand-saved in T7; the terminating save tool is the
  first Phase-1 turn (borrow-then-own).
- **Committing** — T7 leaves a staged-clean tree; the human runs the per-turn commits (D6).

---

## 10. Open questions settled (D1–D7)

All seven decisions in §5 are agreed. No open questions remain for T7. Any *finding* from the live
demonstration (R1) is recorded in `docs/phase-0-gate.md`, not deferred.

---

## 11. Definition of done

- [ ] T7.a: `_managed_checks` no-silent-pass at the read boundary; `is_self_repo` public; new test;
      T6 gate + `just ci` green.
- [ ] T7.b: turn-1..4 docs live under `docs/planning/`; internal links fixed; `index.md` repointed.
- [ ] T7.c: `README.md` reflects the real Phase-0 surface; stale "Turn 1" status gone.
- [ ] T7.d: `AGENTS.md` has the "developing perk" conventions section (managed block untouched).
- [ ] T7.e: `docs/phase-0-gate.md` records the end-to-end demonstration and asserts the gate met
      (incl. the resolved §1 honesty flag).
- [ ] T7.f: `docs/planning/phase-1-plan.md` exists at phase-decomposition granularity, authored on the
      scaffold.
- [ ] T7.g: `scripts/verify-t7.sh` passes; `just verify` runs t1..t7; `just ci` green.
- [ ] Tree staged-clean and ready for per-turn commits (T7 does not commit).

---

## 12. T7 outcomes (recorded after the checkpoint)

**Status: Phase 0 gate MET. All seven hard gates PASS (t1–t7); `just ci` green (80 pytest + 11
node:test).** The full record is [`docs/planning/phase-0-gate.md`](./phase-0-gate.md).

**The §1 honesty flag — resolved positively.** `npm view` metadata confirms the gate mapping
*exactly*, so **no gate-prose or borrowed-set adjustment was needed**:
- `@tombell/pi-plan` @ 0.0.4 — *"Read-only planning mode for safe investigation before editing."*
- `@juicesharp/rpiv-todo` @ 1.16.1 — *"A todo list for the model, rendered as a **live overlay** that
  survives /reload and conversation compaction."* (a genuine live overlay, not merely a todo tool).
- `@tombell/pi-status` @ 0.0.6 (statusline) · `@tombell/pi-diff` @ 0.0.4 (session diff).

**Built (as planned), with one scope simplification:**
- **T7.a** — `_managed_checks` except broadened to `(UserFacingCliError, OSError)` with branched
  detail (no-silent-pass now covers the file-read boundary); `init._is_self_repo` → public
  `init.is_self_repo`; new `test_unreadable_managed_file_is_fail_not_crash` (chmod-revoke with a
  root/CI skip-guard). T6 gate + `just ci` stayed green.
- **T7.b** — the `docs/planning/` reorg was **already tracked** at the new location (turn-1..6 under
  `docs/planning/`), so the `git mv` was a no-op; the remaining work was real: fixed the moved
  turn-1..4 internal links (`./` → `../` for docs-root targets; turn-3's `../shared/` →
  `../../shared/`) and repointed the `index.md` turn-1..4 rows to `./planning/…`. A link-resolution
  sweep confirms every relative `.md` link in `docs/planning/` and `docs/index.md` resolves.
- **T7.c** — `README.md` rewritten built-surface-first (what perk is / quickstart / the Phase-0
  command table / where this is going / develop); the stale “Turn 1” status line is gone.
- **T7.d** — `AGENTS.md` gained a human-authored **“Developing perk”** section *after* the managed
  `END` marker (so `init`'s `_apply_managed_block`, which only rewrites between markers, never
  disturbs it).
- **T7.e** — `docs/phase-0-gate.md` records the mapping, the resolved honesty flag, the automatable
  preconditions, the reproduce-the-interactive-demo steps, the Phase-0 deferral boundary, and the
  **“Phase 0 gate met”** verdict.
- **T7.f** — `docs/planning/phase-1-plan.md` authored at phase-decomposition granularity (objective,
  the dogfood acceptance gate, a six-turn spine breakdown P1.T1–T6, dependencies, deferrals);
  per-stage state-I/O stays deferred per turn.
- **T7.g** — `scripts/verify-t7.sh` (6 precondition checks, all PASS); `just verify` runs t1..t7.

**Scope note (honest deviation from §4).** The §4 table anticipated `git mv` of turn-1..4 and a code
change in `perk/cli/commands/doctor_cmd.py`. Neither happened: the reorg was already tracked
(T7.b above), and the `is_self_repo` rename touched only `init.py`/`doctor.py`/`test_doctor.py` —
`doctor_cmd.py` never referenced `_is_self_repo`. No behavior lost.

**The interactive half is honestly bounded.** `verify-t7.sh` proves the *preconditions* (scaffold
healthy, substrate wired, `pi` launchable, artifacts present); the live plan-mode-with-overlay
observation is a human-operator step whose proof is the artifact it produces (`phase-1-plan.md`).
The gate record gives exact reproduce steps rather than claiming a TUI overlay was watched in CI.

**Deps:** **none added** (Python-touch only: the one T6 correctness fix). No TS, no contract, no
registry change.

**Post-T7 relocation (doc layout).** After this turn landed, the artifacts were moved to their
preferred homes — `phase-0-plan.md` and `phase-0-gate.md` now live under `docs/planning/`, and
`phase-1-plan.md` now lives at `docs/`. The §4/§6 paths above record the as-planned locations; all
links (and `scripts/verify-t7.sh`'s checks 4–5) were reconciled to the new layout, and `just verify`
stays green.

**Tree state (D6):** staged-clean and ready for **per-turn catch-up commits** (T4/T5/T6/T7); T7 does
not auto-commit.

**Verify:** `bash scripts/verify-t7.sh` (6/6 PASS) · `just verify` (t1–t7 ALL PASS) · `just ci` green
(ruff + biome + ty + tsc + 80 pytest + 11 node:test).
