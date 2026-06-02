# Phase 1 · Turn 6 — the Phase-1 dogfood gate (perk ships perk)

> The visible boundary that closes **Phase 1** and opens **Phase 2**. A **checkpoint turn**, not a
> build turn — it mirrors Phase 0's T7 + [phase-0-gate.md](./phase-0-gate.md) precedent. It ships
> almost no new spine code; its work is (a) driving a **real perk change** through the whole loop on
> perk's own repo, (b) **reconciling** the prose (`README`/`AGENTS`/`contracts`) against built
> reality, (c) an **offline precondition gate** (`scripts/verify-p1-t6.sh`), and (d) the **gate
> record** ([phase-1-gate.md](./phase-1-gate.md)). The dogfood change is authored *through* the
> loop; everything else commits directly as "Phase 1, Turn 6".
>
> **Status:** plan written (this doc). The live run is human-executed (D2); the gate record, verify
> script, reconciliation, and this doc's §12 outcomes are written **after** the run reports back.

---

## 1. Objective & the gate

**The gate (verbatim, from [phase-1-plan.md](../phase-1-plan.md) §"Acceptance gate"):**

> **perk ships perk.** A real change to perk is **authored and saved as a perk plan, then
> implemented, submitted, landed, and learned-from through perk's own thin loop** — end to end, on
> perk's own repo. From that point, every Phase-2/3 change rides the validated spine, not planning
> alone.

This is the **first turn that hits live GitHub and a live `pi` session** — every prior Phase-1 gate
ran fully offline (gh faked / `--dry-run`; node offline). The spine it exercises was closed
end-to-end across T1–T5: `plan → save → implement → submit → land → learn`, resumable via
`perk resume`. T6 proves it on a real change rather than against fakes.

**T6 ships no new spine handlers.** The only product change is the **dogfood payload** (a real perk
improvement, authored through the loop — see §4), plus the gate's own deliverables (verify script,
reconciliation edits, two docs). The loop's mechanics are already built; T6 *uses* them.

## 2. Grounding & doc lineage (what governs T6)

- **[phase-1-plan.md](../phase-1-plan.md) §P1.T6** — "Drive a real perk change through the whole loop
  on perk's own repo; record the run as the gate. Reconcile `AGENTS.md`/README/contracts against what
  got built; confirm the registry's per-stage state-I/O is now filled for the spine."
- **[phase-0-gate.md](./phase-0-gate.md)** — the structural precedent: gate verbatim → how it maps to
  what got built → what was demonstrated (automatable preconditions PASS + the interactive artifact)
  → the deferral boundary → the verdict.
- **[phase-0-turn-7.md](./phase-0-turn-7.md)** — the checkpoint-turn shape (verify + docs pass + the
  gate record; "no new machinery").
- **[cli-vs-pi.md](../cli-vs-pi.md) §4.1 (door legality)** — the **two doors per stage** model the
  gate validates live: a **cold door** (CLI → fresh `pi`) and a **warm door** (in-session slash
  command). T6 exercises both wherever both exist (D-both, §3).
- **contracts §8.4 (D1, T5a)** — warm doors **delegate** to the Python gateway via `pi.exec`
  (`submit.ts`/`land.ts` call `perk pr-submit`/`pr-land --json`). Because both doors hit the **same
  idempotent op**, running them back-to-back against one artifact is a live **parity** assertion.

## 3. Decisions (locked with the user before writing)

- **D1 — the dogfood change is "add `prek` + a ruff pre-commit hook."** A real, small, self-validating
  perk improvement (§4). Pulled from genuine want, not a contrived diff.
- **D2 — the user runs the live loop; this doc provides the runbook.** The faithful primary path runs
  `plan` + `save` in a read-only **plan-mode** `pi` session (author in `/plan`, persist with the warm
  `/plan-save` command), `implement` (execs `pi`), and `learn` (warm-only — no cold worker, by T5b
  design) in sessions; the GitHub-mutating **cold workers** (`plan-save` / `pr-submit` / `pr-land`)
  remain the bash-scriptable supervisor/parity surface. The runbook (§6) marks each interactive step
  + each **report-back** point.
- **1a — `ruff check` plain (no `--fix`).** Mirrors `just lint` exactly; never mutates the tree on
  commit. The hook is a *gate*, not an auto-fixer.
- **2a — free-author the implement.** The `pi` implement session authors `prek` from the plan (§4.2)
  rather than applying pre-baked file bodies — a more faithful dogfood. The plan encodes the
  *decisions* (local hook + `uv run`, plain check); the session realizes the *mechanics* (perk's own
  judgment-in-the-plan / mechanics-in-implement division).
- **2b — test BOTH doors.** Wherever a stage has two doors, exercise both live. perk's idempotency
  (`create_plan_issue` on `run_id`, `create_pr` on the head branch, `merge_pr` on "already merged")
  makes this safe: **one door mutates, the other confirms an idempotent no-op** against the same
  artifact — validating warm/cold **parity** (§5), not just coverage.
- **D-write-order — turn doc now; gate record after the run.** This doc (plan + runbook) is written
  first; the user runs it; on report-back, the gate record + `verify-p1-t6.sh` + reconciliation +
  §12 outcomes are written, then committed.
- **D-two-commits — the dogfood change is its own merged PR (the gate evidence); the T6 deliverables
  commit directly** as "Phase 1, Turn 6" (the same way every prior turn doc committed). The gate
  record cites the dogfood PR # / issue #.

## 4. The dogfood change — `prek` + a ruff pre-commit hook

### 4.1 Why this change

A real perk dev-tooling improvement: run ruff automatically before each commit so lint/format drift
can't land. [`prek`](https://prek.j178.dev/) is a fast, drop-in `.pre-commit-config.yaml`-compatible
reimplementation of `pre-commit` (already installed: `prek 0.4.3`). Small, low-risk (config + docs,
no Python product code), and **self-validating** (§6 runs ruff across the tree green).

### 4.2 The plan content (saved in step 2; the implement session authors against it)

The plan markdown the user saves (`/tmp/perk-prek-plan.md` or similar). It states intent + the locked
decisions and leaves authoring to implement (2a):

```markdown
# Add prek + a ruff pre-commit hook

## Objective
Run ruff automatically before each commit so lint/format drift cannot land. Wire
[prek](https://prek.j178.dev/) (a drop-in `.pre-commit-config.yaml` runner) over the repo's
already-pinned ruff.

## Decisions
- **Local hook over `uv run`, not the remote `astral-sh/ruff-pre-commit` repo.** The hook must use
  the project-pinned ruff (`uv run ruff`) so it and `just lint` / `just ci` never drift to two
  ruff versions — single source of truth.
- **`ruff check` plain (no `--fix`).** A commit *gate*, not an auto-fixer; mirrors `just lint`.
- **Two hooks:** `ruff check` then `ruff format --check`-equivalent (format must not rewrite on
  commit). `types_or: [python, pyi]`, `require_serial: true`, `--force-exclude` so ruff honors its
  configured excludes even when pre-commit passes filenames.

## Acceptance
- `.pre-commit-config.yaml` exists with the two local ruff hooks.
- `just hooks` installs the git pre-commit hook via `uvx prek install`.
- `prek run --all-files` runs ruff across the codebase GREEN.
- README "Develop" + AGENTS "Developing perk" each note enabling the hook.
- `just ci` stays green; no Python product code changes.

## Anchors (no line numbers — durable anchors only)
- new file: `.pre-commit-config.yaml`
- `justfile`: add a `hooks` recipe near `setup`
- `README.md` "Develop" section; `AGENTS.md` "Developing perk" section
```

> **Note (2a):** the file *bodies* above are intentionally **not** pre-written — the implement
> session authors them from these decisions. The reference shape (a `local` repo with `id: ruff` /
> `id: ruff-format`, `entry: uv run ruff …`, `language: system`) is what a correct realization looks
> like; the gate proves the **loop**, so minor authoring variance is fine.

## 5. The door-coverage matrix (what the live run demonstrates)

The gate validates the **two-doors-per-stage** model (cli-vs-pi §4.1) live, using idempotency to run
both safely against one artifact:

| Stage | Cold door | Warm door | How both are tested |
| --- | --- | --- | --- |
| **save** | `perk plan-save --plan-file` | `/plan-save` (delegates) | **warm `/plan-save`** is the in-session primary (plan authored in read-only plan mode); the cold worker is the scriptable/supervisor equivalent (idempotent on `run_id`), proven by the offline `--dry-run` gate + T3 harness — optional live parity re-run |
| **implement** | `perk implement #N` (the jump) | `/implement` **guard-only** | cold performs the plan→impl jump; warm `/implement` in the impl session replies *"already implementing — continue"* (legal), demonstrating `doors.warm:false` enforcement (T4b) |
| **submit** | `perk pr-submit --json` | `/submit` | **warm opens** the draft PR; **cold re-run** returns `existed: true` (idempotent on the head branch) |
| **land** | `perk pr-land --json` | `/land` | **cold merges** + sets `pending-learn`; **warm re-run** reports "already merged" + marker idempotent |
| **learn** | *(none — by design, T5b)* | `/learn` | warm clears `pending-learn` (`was_pending: true`) — the one warm-only step |
| **resume** | `perk resume #N` | *(none — cross-stage verb)* | `perk resume #N --dry-run --json` resolves "nothing to resume" once the loop is closed |

This is a complete **door-legality + parity** demonstration, not merely "the loop ran once."

## 6. The live runbook (the user executes; reports each ▶ back)

> Pre-baked, copy-pasteable. Cold steps are bash; interactive steps (`pi` sessions) are marked.
> Capture the **bold** values (issue #, PR #, JSON) and report them at each ▶. Run from the perk
> repo root on branch `main`, clean tree.

**Step 0 — pre-flight (bash).**
```bash
cd /Users/mattgiles/dev/github/mattgiles/perk
git switch main && git status --porcelain        # expect: empty (clean)
just ci                                            # expect: all green
gh auth status                                     # expect: logged in as mattgiles
prek --version                                     # expect: prek 0.4.x
```
▶ Report: clean tree, `just ci` green, gh authed.

**Step 1 — plan (interactive `pi` session, read-only plan mode).** Author the plan the way a real
perk user would — *in plan mode*, not a heredoc:
```bash
uv run perk plan        # launches pi primed for the read-only plan stage
```
In the session:
- `/plan` → enter read-only plan mode (borrowed `@tombell/pi-plan`); explore the codebase read-only.
- Converge with the model on the prek plan — target shape is §4.2 (objective; decisions: **local hook
  over `uv run ruff`** + **plain check**; acceptance; durable anchors, no line numbers).
- Have the model emit the final plan as its **latest message wrapped in
  `<proposed_plan>…</proposed_plan>`** (so the save command extracts exactly the plan).
▶ Report: the authored plan (the `<proposed_plan>` block).

**Step 2 — save (warm door, same session).** Persist the authored plan in-session:
- Run the **`/plan-save` command** (its twin — plan mode hides custom *tools*, so use the command,
  which reads your latest assistant message; T3). It delegates to `perk plan-save --json` (with the
  session's `run_id`), creates the GitHub issue, links the session, and **terminates the turn**.
- Expect a `Saved plan #N → <url>` notification; `.pi/workflow/plan-ref.json` written.
▶ Report: **issue #N**, the issue URL, the save `details` (ok / issue / plan_ref / cached).

> **Optional cold parity (2b for save):** from a bash shell, re-run the worker idempotently —
> `uv run perk plan-save --plan-file <plan.md> --run-id <session-run_id> --json` → expect
> `issue.existed = true`. Low-value vs the submit/land parity (both save doors call the *identical*
> worker), so skip unless you want it; the cold worker is already proven by the offline `--dry-run`
> gate + the T3 harness.

**Step 3 — implement (interactive `pi` session).**
```bash
uv run perk implement              # NO plan positional — reads the active plan-ref (T4a D2)
```
> **Do not pass the issue number.** `perk implement` takes `[PI_ARGS]...`, not a plan id — it derives
> the worktree (`plan-<pr_id>`) from the active `cache.plan-ref`. A stray positional (`perk implement
> 1`) is **forwarded to `pi` as the initial prompt**, confusing the session. **Gate finding (§12):** a
> Phase-2 guard should reject/redirect a plan-id-looking positional (e.g. "did you mean `perk resume
> 1`?"). It materializes worktree `plan-N` on branch `plan-N` (idempotent reuse on re-run) and execs
> `pi` there.

In the session (read the plan via `gh issue view N --comments`, then free-author it — 2a):
- author `.pre-commit-config.yaml` (local ruff + ruff-format hooks over `uv run`), the `just hooks`
  recipe, and the README/AGENTS notes;
- `just hooks` → `uvx prek install` (installs the git pre-commit hook);
- **`prek run --all-files`** → ruff check + format run GREEN across the tree (the self-validation);
- `just ci` → green;
- commit (the prek commit stages no `.py`, so the hooks skip — `prek run --all-files` above is the
  ruff proof);
- **door check:** run `/implement` → expect *"perk: already implementing — continue in this
  session."* (the legal warm use; demonstrates `doors.warm:false` enforcement).
▶ Report: the diff, `prek run --all-files` output (ruff green), `just ci` green, the `/implement`
guard message.

**Step 4 — submit (warm, then cold — BOTH doors).**
- Warm (in the `pi` session): run `/submit` → opens the **draft PR**, sets the plan-header
  (`branch`/`pr`/`lifecycle_stage=impl`). Note the PR #.
- Cold (a bash shell, `cd` into the worktree `…/plan-N`):
```bash
cd <worktrees-root>/plan-"$N"
uv run perk pr-submit --json        # expect: success, pr.existed=true (idempotent no-op)
```
▶ Report: **PR #M**, draft state, the warm `/submit` content, the cold `--json` showing
`pr.existed: true` (parity confirmed).

**Step 5 — land (cold, then warm — BOTH doors).**
```bash
uv run perk pr-land --json          # marks ready (if draft) + squash-merges; sets pending-learn
ls .pi/workflow/markers/            # expect: pending-learn present
```
Then warm (in the `pi` session): `/land` → expect "already merged" (idempotent), marker still set.
▶ Report: the cold `--json` (merged + pending_learn), `pending-learn` marker present, the warm
`/land` idempotent message.

> **Friction flag:** `pr-land` self-merges your own draft PR to `main`. If `main` has branch
> protection requiring reviews, the merge fails — that is a **real finding** the gate surfaces (not a
> bug); report it and we adapt (e.g. relax protection for the gate, or record the limitation).

**Step 6 — learn (warm — the only door).** In a `pi` session in the worktree (or `perk learn`
→ session): run `/learn` → clears `pending-learn`.
```bash
ls .pi/workflow/markers/            # expect: pending-learn GONE
```
▶ Report: `/learn` reported `was_pending: true`; marker cleared.

**Step 7 — resume sanity (cold, live GitHub read).**
```bash
uv run perk resume "$N" --dry-run --json
```
Expect "nothing to resume" (PR merged + learned → the state machine returns no stage).
▶ Report: the `--json` output.

**Step 8 — post-conditions (bash / GitHub).**
```bash
gh pr view M --json state,merged                   # expect: MERGED
gh issue view "$N" --json state                    # expect: CLOSED (Closes #N on squash-merge)
```
▶ Report: PR merged, plan issue closed, links to both.

## 7. The offline precondition gate — `scripts/verify-p1-t6.sh`

Mirrors `verify-t7.sh` (uv-only, fresh throwaway scaffold). Asserts the **automatable** half — the
spine is present, healthy, and launchable **fully offline**. The interactive/live half (§6) is
recorded in the gate record, not CI-automatable.

Checks (all offline; gh never invoked):
1. **Spine launchers + workers resolve `--dry-run` with no side effects.** In a fresh `perk init`
   scaffold with a **seeded fake `plan-ref.json`**: `perk plan --dry-run`, `perk implement
   --dry-run`, `perk pr-submit --dry-run`, `perk pr-land --dry-run` each emit `{"success": true, …}`
   and create **no worktree / no marker / no GitHub call**.
2. **Registry I/O + doors filled for all 6 spine stages.** `plan`/`save`/`implement`/`submit`/`land`/
   `learn` each carry non-placeholder `doors` + (where applicable) `requires`/`reads`/`writes` — the
   "per-stage state-I/O is now filled for the spine" assertion from §P1.T6.
3. **contracts §8.4 status complete** through T5c (+ the new T6/gate closing note).
4. **Gate record present** — `docs/planning/phase-1-gate.md` exists and asserts the gate met.
5. **The dogfood artifact is present** — `.pre-commit-config.yaml` exists with the ruff hook (proof
   the dogfood change landed on `main`).

> **`resume --dry-run` is *not* in the offline gate** — it reads GitHub (`require_github` runs even
> for `--dry-run`, since the read *is* the job; T5c §13). It is exercised live in §6 step 7 and noted
> here as the one spine command not offline-gateable.

Wired into the `justfile` `verify` target after `p1-t5c`.

## 8. Reconciliation scope (the audit — drift found vs built reality)

- **`README.md`** — currently Phase-0-framed: "Status: **Phase 0 complete**", "The **Phase-0**
  command surface", Phase 1 in **future tense**, `just verify` = "the cumulative **Phase-0** hard
  gates (t1..t7)". Update to: Phase-1-spine-complete status; add the spine command rows
  (`plan-save`, `pr-submit`, `pr-land`, `resume`, and the in-session warm doors `/plan-save`,
  `/submit`, `/land`, `/learn`); correct the `verify` line.
- **`AGENTS.md` "Developing perk"** — the verify-gate bullet says `scripts/verify-tN.sh`; Phase-1
  uses `scripts/verify-p1-tN.sh`. Light correction. The **managed block stays `init`-owned** (never
  hand-edited).
- **`shared/contracts.md`** — add a closing **Status (P1.T6 / Phase-1 gate)** note: the spine is
  closed end-to-end; the gate run is recorded in `phase-1-gate.md`. Confirm §8.4 reflects the
  delegation reality (already amended in T5a).
- **`shared/registry.yaml`** — **verify-only** (already filled for all 6 stages in T2a/T4a/T5a/b); T6
  asserts it via `verify-p1-t6.sh` check 2, authors nothing.
- **`docs/index.md`** — add the `phase-1-turn-6.md` + `phase-1-gate.md` entries; full link-resolution
  sweep.

## 9. The gate record — `docs/planning/phase-1-gate.md` (written after the run)

Mirrors `phase-0-gate.md`:
- the gate verbatim (§1);
- **how the gate maps onto what Phase 1 built** — the spine table (the six stages + their doors);
- **what was demonstrated** — the automatable preconditions (PASS via `verify-p1-t6.sh`) **and** the
  live run's real artifacts (the dogfood **PR #**, plan **issue #**, the squash-merge, `pending-learn`
  set→cleared, the door-parity confirmations from §5);
- the **Phase-1 deferral boundary** (quoted from phase-1-plan §"Explicitly deferred");
- the **verdict** ("Phase 1 gate met. Phase 2 may begin.").

## 10. Out of scope (Phase 2+)

Quoted from [phase-1-plan.md](../phase-1-plan.md) §"Explicitly deferred", recorded here so the
boundary is a *choice*: perk-owned plan mode + the tool-gating primitive; objectives, the CI
executor, the review/`address` loop, feedback classification; PR-body two-target craft / `pr check`
/ draft→ready nuance / reconciliation typing / deep learn tooling; the end-to-end **worker** tests
(Phase 3); subagent delegation + untrusted-input hygiene; the in-process `ctx.newSession` warm-path
fresh context. T6 adds nothing here — it only *uses* the spine and records the boundary.

## 11. Definition of done

- [ ] A real perk change (`prek` + ruff hook) **authored, saved, implemented, submitted, landed, and
      learned-from through perk's own loop** on perk's own repo — real issue #, branch, draft PR,
      squash-merge, `pending-learn` set→cleared.
- [ ] **Both doors** exercised for `submit` and `land` (warm/cold parity confirmed via idempotency);
      the `/implement` guard's "continue" path demonstrated; `learn` (warm-only) and `resume`
      (cold-only) exercised.
- [ ] `scripts/verify-p1-t6.sh` — all offline preconditions PASS; wired into `just verify`.
- [ ] Reconciliation landed: `README` (Phase-1 framing + command rows), `AGENTS` (verify naming),
      `contracts` (closing status), `docs/index.md` (entries + link sweep).
- [ ] `docs/planning/phase-1-gate.md` written with the real artifacts; asserts the gate met.
- [ ] `just verify` (t1–t7 + p1-t1…p1-t6) and `just ci` green.
- [ ] This doc's §12 outcomes filled.

## 12. Outcomes (recorded on landing)

*(filled after the live run reports back — the real PR #/issue #, any friction surfaced, deviations
from this runbook, and the verify/reconciliation as-built.)*
