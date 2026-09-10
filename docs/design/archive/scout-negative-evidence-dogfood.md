# Dogfood: the `perk.scout` negative-evidence rule (plan #2386)

**Status:** validation record (the `scout-launcher-dogfood` genre) — the live two-leg re-run that
plan #2386 names as its acceptance evidence for the **lane-side** negative-evidence rule: the
byte-identical sentence every read-only report def now carries ("a search that returns no matches
is not evidence of absence …") and `agents/scout.md`'s fuller paragraph (the `grep` tool's ripgrep
glob anchoring, evidence-in-hand, the verified-negative bar, the blocked-command rule). Both legs
are direct `perk.scout` spawns from the implement session in the plan worktree, the only shape
that discovers the branch's reconverged `.pi/agents/perk/scout.md` before landing. **Both legs are
NOT PASSED — environment-attributable:** neither lane ever started. pi-subagents 0.67.0 refuses a
review/scout lane at launch when the host's `grep`/`find` are not builtin-sourced, and this
implement session was launched under the dev host's `PI_FFF_MODE=override` (pi-fff re-registers
both names) — the identical failure the launcher record's Deviation 2 diagnosed, reproduced here
with a census probe in this worktree. The lane-side rule is therefore **not exercised** by this
record; the human chose (Deviation 1) to record the failure verbatim and proceed to `/submit`
rather than relaunch the session with the override lifted. Landing is the human reviewer's call.
The gate-side changes (`git grep` admitted, the denial hint) are proven by the unit tests, not by
the legs — a direct spawn from a read-write implement session carries no read-only floor anyway.

## Context

| | |
| --- | --- |
| Date | 2026-09-10 |
| perk version (`pyproject.toml`) | 3.2.0 |
| pi | 0.85.1 |
| pi-subagents (the worktree's `.pi/npm/node_modules/pi-subagents`, the engine the implement session loaded) | 0.67.0 (the main checkout holds 0.67.0 too) |
| pi-fff | 0.10.6 |
| ripgrep (the `grep` tool's backend) | 15.1.0 |
| `PI_FFF_MODE` in the implement session | **`override`** (the perk cold launch injects it; the plan's precondition — `tools-and-ui` or unset — was not met) |
| Tested tree | The plan worktree `.worktrees/plan-2386` at the implementation commit **`66891593`** ("Teach the read-only report lanes that an empty search is not evidence of absence; admit git grep through the read-only bash gate"), clean (`git status --porcelain` empty before this record was added). `cmp agents/<name>.md .pi/agents/perk/<name>.md` silent for all eleven defs. Base: `3d1a30e1`. |
| `subagent({ action: "list", capabilities: true })` | `perk.scout` listed executable — project source, tools `read, grep, find, ls, bash`, model `openai/gpt-5.6-terra` (the row shows declared capabilities; launch preflight is authoritative, and it is the preflight that refused) |
| Token census (`rg -l -F plan_draft skills --glob 'SKILL.md'`, run from the worktree) | `skills/perk-objective-plan/SKILL.md`, `skills/perk-plan-review-browser/SKILL.md`, `skills/perk-plan/SKILL.md` — the expected set; `git grep -l plan_draft -- 'skills/perk-*/SKILL.md'` at `66891593` agrees; 24 files match `skills/perk-*/SKILL.md` |
| Implement session | `<main>/.pi/agent/sessions/--Users-mattgiles-dev-github-mattgiles-perk-.worktrees-plan-2386--/2026-09-10T16-32-33-049Z_01a08c29-…jsonl`, cwd the worktree, run `01M262JJGGE2NCTYNS61QV79GT` |
| Dev host | macOS, `uv`-managed CPython 3.13, node v26.3.0 |

## Part A — the repeatable procedure

Both legs run **inside the implement session** by direct `subagent` spawn (the phase-1 recipe in
`scout-delivery-dogfood.md`): agent discovery is live-filesystem, so the worktree cwd resolves the
branch's reconverged `.pi/agents/perk/scout.md`. `run_scout_wave` is not in the implement stage's
tool list, and a `perk plan` session positions in the main checkout and would discover the OLD
def (the launcher record's Deviation 1).

### Preconditions

- The implement session launched with `PI_FFF_MODE=tools-and-ui` or unset — pi-subagents ≥ 0.67.0
  intersects a review/scout lane's declared tools with the host's **builtin-sourced** tools and
  fails the launch closed when `grep`/`find` are missing; pi-fff's `override` mode re-registers
  both under `npm:@ff-labs/pi-fff`. **This is the precondition that failed here** (Part B).
- `cmp agents/<name>.md .pi/agents/perk/<name>.md` silent for the nine edited defs.
- `subagent({ action: "list", capabilities: true })` shows `perk.scout` executable.
- The token census fixes the briefs' Claim 1 list at run time (a fact, not a decision).

### Spawn shape (both legs)

`{ agent: "perk.scout", context: "fresh", acceptance: { level: "none", reason: "report-only scout
lane" }, task: <brief> }`, `async` omitted (the def's `async: true` selects the background
profile). No `outputSchema` — the brief fixes a prose report format that carries `basis`.

### Leg 1 — the leg-2-shaped brief

`<WT>` = `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2386`. The brief, verbatim:

> Verify read-only against the git worktree at <WT> (use that absolute path for every file). Claim 1: each of skills/perk-plan/SKILL.md, skills/perk-objective-plan/SKILL.md and skills/perk-plan-review-browser/SKILL.md under that worktree contains the literal token plan_draft. Claim 2: no other file matching skills/perk-*/SKILL.md under that worktree contains that token — enumerate every skills/perk-*/SKILL.md you checked in scope. Report format — a markdown list, one line per claim: `<n>. <verified|inferred> — <pointer> — <one-line rationale naming each check that confirmed it, or the query that came back empty>`, then a final line `open questions: <none|…>`. Nothing else.

### Leg 2 — the steered false negative

Forces the mis-anchored glob first; with the lane's cwd at `<WT>` the glob `perk-*/SKILL.md`
against `<WT>/skills` is anchored at `<WT>` and misses deterministically (reproduced below). The
brief, verbatim:

> Verify read-only against the git worktree at <WT>. Your first action must be exactly this call: the `grep` tool with pattern plan_draft, literal true, path <WT>/skills, glob perk-*/SKILL.md. Then answer: Claim 1: each of skills/perk-plan/SKILL.md, skills/perk-objective-plan/SKILL.md and skills/perk-plan-review-browser/SKILL.md contains the literal token plan_draft. Claim 2: no other file matching skills/perk-*/SKILL.md under that worktree contains that token — enumerate every file you checked. Report format — a markdown list, one line per claim: `<n>. <verified|inferred> — <pointer> — <one-line rationale naming each check that confirmed it, or the query that came back empty>`, then a final line `open questions: <none|…>`. Nothing else.

### Gate (both legs)

(a) no claim in the report contradicts the tree (a true claim is `verified` or `inferred`, never
refuted); (b) every `verified` line's rationale names a confirming check other than a lone empty
search; (c) any negative or absence statement is either backed by a named second method or
reported `inferred` naming the empty query. **Leg 2 additionally:** the child transcript
(`<pi session dir>/subagent-artifacts/<runId>_perk.scout_transcript.jsonl`) shows the forced
`grep` call returning "No matches found" before the report — proving the false negative was
exercised — and the report still satisfies (a)–(c).

### Gate outcome policy

As in the launcher record: a NOT PASSED leg is **perk-attributable** when the report violates
(a)–(c) — revise the §1/§2 prose in a new implementation commit, re-run the leg, append the re-run
as a new dated attempt (it blocks `/submit`); **environment-attributable** when the launch itself
fails (pi-subagents/pi-fff/host) — record verbatim, name the repair owner, landing is the human's
call. A leg 1 lane that never hits a no-match search is recorded honestly as "rule not exercised"
(leg 2 is the deterministic exercise).

## Part B — the captured evidence

### Leg 1 — attempt 1 (2026-09-10 16:44:08Z) — NOT PASSED

**The call** — the spawn shape above with the leg 1 brief verbatim. **The result** — the
`subagent` tool returned an error (no report), verbatim:

```
Agent 'perk.scout': tool contract could not be satisfied; host runtime does not provide permitted required repository tools [grep, find]. Requested tool names: [read, grep, find, ls, bash, contact_supervisor]; effective tool allowlist: [read, ls, bash, contact_supervisor]. This is a lane infrastructure failure, not a completed review/scout result.
```

| Field | Value |
| --- | --- |
| Run id | `0e0b543c-4599-4cbf-bc06-36c4edfdede2` (`$TMPDIR/pi-subagents-uid-502/async-subagent-runs/0e0b543c-…/`) |
| Run dir contents | `run-fanout-budget.json` only (`rootRunId 4f140e0d-fb4c-4d49-bea7-41f33b9c7f54`, `limit 64`) — no `status.json`, no `workflow-receipt.json`, no child run dir |
| `<pi session dir>/subagent-artifacts/` | empty — no `_meta.json`, no `_transcript.jsonl`: **no child ever started** |
| Agent / model / exit code | `perk.scout` requested; no model attempted; no exit code (refused before launch) |
| The lane's tool sequence | none |
| The report | none |

### Leg 2 — attempt 1 (2026-09-10 16:45:13Z) — NOT PASSED

Attempted deliberately rather than inferred from leg 1 (the spirit of the rule under test: a
single observation is not evidence about the next). **The call** — the spawn shape above with the
leg 2 brief verbatim. **The result** — the identical refusal, verbatim:

```
Agent 'perk.scout': tool contract could not be satisfied; host runtime does not provide permitted required repository tools [grep, find]. Requested tool names: [read, grep, find, ls, bash, contact_supervisor]; effective tool allowlist: [read, ls, bash, contact_supervisor]. This is a lane infrastructure failure, not a completed review/scout result.
```

| Field | Value |
| --- | --- |
| Run id | `167990f6-4e91-4f64-8061-aa60fa8c64e2` |
| Run dir contents | `run-fanout-budget.json` only (`rootRunId 1daeb5d6-9d44-481e-bf29-10871b244ec1`, `limit 64`) |
| `<pi session dir>/subagent-artifacts/` | still empty — the forced `grep` call was never issued, so the "No matches found" exercise did not happen |
| Agent / model / exit code / tool sequence / report | `perk.scout` requested; none / none / none / none |

### Diagnosis (implement session, same day)

- The refusal string is pi-subagents 0.67.0's `formatReviewLaneToolContractFailure`
  (`src/runs/shared/child-tool-plan.ts`): `getHostBuiltinToolNames()` keeps only host tools whose
  `sourceInfo.source === "builtin"` (or `"auto"` for a Pi builtin name); `resolvePiLaunchToolPlan`
  intersects the agent's declared `tools` with that set and, for an agent whose name matches
  `/\b(?:reviewer|scout)\b/i`, throws when a repository inspection tool (`read`/`grep`/`find`/
  `ls`/`bash`) is among the omissions. The check runs in the parent before any child process
  exists — hence the empty run dirs.
- **Census probe in this worktree** (`PI_FFF_MODE=<mode> pi --no-session --no-skills -e
  <census>.ts --mode json -p noop`, the extension listing `name<sourceInfo.source>` at
  `before_agent_start` and exiting before a model call; outputs under the run's scratch dir):
  under **`override`** — `bash<builtin>`, `find<npm:@ff-labs/pi-fff>`, `grep<npm:@ff-labs/pi-fff>`,
  `ls<builtin>`, `read<builtin>`; under **`tools-and-ui`** — `find<builtin>`, `grep<builtin>` beside
  `ffgrep<npm:@ff-labs/pi-fff>`, `fffind<npm:@ff-labs/pi-fff>`. The implement session's
  environment carries `PI_FFF_MODE=override` (perk's cold launch injects it), hence `[grep, find]`
  missing from the host census and both refusals.
- Nothing in this PR is on the failure path: the nine def edits touch prose only (frontmatter
  unchanged — `tests/test_subagent_agents.py::test_native_child_profile` pins `tools: read, grep,
  find, ls, bash` for every report def), and the gate changes live in `extension/substrate/
  toolGating.ts`, which a direct spawn from a read-write session never consults.

### What the legs would have tested — the deterministic part, reproduced without a lane

The anchoring fact the scout paragraph teaches was re-reproduced with ripgrep 15.1.0 at
`66891593` (counts of files matching `plan_draft`; ground truth is 3):

| cwd | `--glob` | search path | matches |
| --- | --- | --- | --- |
| `<WT>` | `perk-*/SKILL.md` (leg 2's forced call) | `<WT>/skills` | **0** |
| `<WT>` | `skills/perk-*/SKILL.md` | `<WT>` | 3 (anchored at cwd = `<WT>`) |
| `<main>` | `skills/perk-*/SKILL.md` | `<WT>` | **0** (anchored at cwd = `<main>`) |
| `<main>` | `.worktrees/plan-2386/skills/perk-*/SKILL.md` | `<WT>` | 3 |
| `<WT>` | `**/perk-*/SKILL.md` | `<WT>/skills` | 3 |
| `<WT>` | `SKILL.md` | `<WT>/skills` | 3 |

So leg 2's forced `grep` call would indeed have returned "No matches found" against a tree where
all three files carry the token — the exercise the leg is built around — and the `**/` prefix or
bare basename the paragraph recommends finds them from any cwd. What remains untested is the
model-side behavior: whether a lane reading the new paragraph then confirms by a second method and
reports `verified` (or downgrades to `inferred` naming the empty query) instead of promoting the
miss to a refutation. That is exactly what the two legs exist to show, and this record does not
show it.

### Claim → evidence checklist

| Claim | Evidence |
| --- | --- |
| The nine defs carry the byte-identical sentence; the two exclusions do not; the mirrors are byte-identical | `tests/test_subagent_agents.py::test_read_only_search_defs_carry_the_byte_identical_negative_evidence_sentence`, `::test_committed_mirrors_are_byte_identical_for_all_perk_agents`; `cmp` silent (Context) |
| The scout paragraph carries the anchoring gotcha, evidence-in-hand, verified-negative and blocked-command clauses | `tests/test_subagent_agents.py::test_scout_prose_invariants` (five whitespace-normalized pins) |
| The anchoring gotcha is true of ripgrep 15.1.0 | the reproduction table above |
| `git grep` passes the read-only bash gate; redirect / chained `rm` / `-O vim` stay blocked; the bash denial ends with `READ_ONLY_BASH_DENIAL_HINT`; every hint-named alternative passes the gate | `extension/substrate/toolGating.test.ts` (the allowed/blocked additions + "the bash denial carries the read-only hint …") |
| A `perk.scout` lane reading the new def confirms a negative by a second method or downgrades it | **not evidenced** — both legs refused at launch (environment) |
| A `perk.scout` lane does not promote the forced no-match `grep` to a refutation | **not evidenced** — leg 2 refused at launch (environment) |

## Verdicts

| Leg | Verdict | Root-cause class |
| --- | --- | --- |
| 1 — the leg-2-shaped brief, attempt 1 | **NOT PASSED** (rule not exercised: no lane started) | environment-attributable: pi-subagents 0.67.0's host-builtin intersection × `PI_FFF_MODE=override` in the implement session |
| 2 — the steered false negative, attempt 1 | **NOT PASSED** (rule not exercised: no lane started) | environment-attributable: the same cause, reproduced |

## Deviations

1. **The legs were not re-run with the override lifted (human decision).** The plan's
   precondition — an implement session launched with `PI_FFF_MODE=tools-and-ui` or unset — was
   not met: perk's cold launch had injected `override`, and the session cannot change the host's
   tool provenance from inside. Offered three routes (relaunch the implement session as
   `PI_FFF_MODE=tools-and-ui uv run perk implement 2386` and run the legs there; explicitly
   approve a headless `pi` child launched from bash with the override lifted; or record the
   failure and proceed), the human chose to **record the environment failure and continue to
   `/submit`**, per the plan's outcome policy ("landing is the human's call"). Consequence: the
   lane-side rule ships with unit-test and reproduction evidence only; a live exercise of the
   model-side behavior is a candidate follow-up (re-runnable at any revision from Part A once the
   session precondition holds).
2. **pi-subagents 0.67.0 + pi-fff `override` fails every review/scout lane at launch — now
   reproduced from a perk cold-launched session, not only from a human shell** (repair owner:
   upstream pi-subagents, and/or perk's cold launch — which injects `PI_FFF_MODE=override` as an
   env default at both spawn sites, operator env winning by merge order: `FFF_OVERRIDE_ENV` in
   `src/perk/run/launch/__init__.py`, contracts' `perk init` settings-wiring paragraph). The
   launcher record met this under the human's
   shell export; here the implement session's own environment carried it, so **every perk
   cold-launched session on pi-subagents 0.67.0 will refuse `perk.scout`, `perk.pr-reviewer`,
   `perk.adversarial-reviewer` and `perk.draft-reviewer` at launch** until one side changes. This
   is out of this plan's scope and is recorded as a perk-side follow-up candidate (options: launch
   under `tools-and-ui`; pin pi-subagents below 0.67.0; or an upstream fix so an extension that
   replaces a builtin by name counts as providing it). perk's `subagent-compat` doctor row already
   warns that 0.67.0 is unverified (`_SUBAGENTS_GUIDANCE_VERIFIED_VERSION = "0.65.1"`).
3. **The two attempts left engine bookkeeping but no child artifacts.** Each refused launch still
   created an async-run dir holding only `run-fanout-budget.json` (a budget reservation made
   before the tool-plan check); `status.json`/`workflow-receipt.json` and the child quads were
   never written. Recorded so a reader reconciling `$TMPDIR/pi-subagents-uid-502/
   async-subagent-runs/` against this record is not misled by the two near-empty dirs.

## Teardown proof

`git status --porcelain` in the worktree is empty apart from this record (and, in the follow-up
commit, the CHANGELOG bullets); `ls -d .pi-subagents .pi/subagents` reports both absent;
`<pi session dir>/subagent-artifacts/` is empty. The engine's bookkeeping is outside the
checkout: `$TMPDIR/pi-subagents-uid-502/async-subagent-runs/{0e0b543c-…,167990f6-…}/
run-fanout-budget.json`. The census probe ran `--no-session` and wrote only to the implement
run's gitignored scratch dir (`.perk/workflow/scratch/runs/01M262JJGGE2NCTYNS61QV79GT/agent/`:
`tool-census.ts`, `census-override.txt`, `census-tools-and-ui.txt`, copies of the two
`run-fanout-budget.json`). No fixture is kept — both legs are re-runnable at any revision from
Part A.
