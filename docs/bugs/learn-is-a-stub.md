# Bug: `/learn` is a stub — it captures nothing unless you hand-write the summary

**Status:** confirmed, unfixed
**Surfaced:** during dogfooding — running `/learn` (or launching the `learn` stage) appears to do
nothing.
**Severity:** real gap. perk shipped a minimal stub of erk's learn; the investigate-and-document
value was never built. The most natural invocation (bare `/learn`) just clears a marker.

## Symptom

A bare `/learn` clears the `pending-learn` marker with a *transient* notification and creates
nothing. Launching the `learn` stage (`perk learn` / `perk resume → learn`) opens an **unprimed**
session that just sits there. There is no agent workflow that investigates the landed change and
produces durable learnings — you must hand-write a summary and pass it as `/learn <text>` (or via the
`learn` tool's `summary` param), and nothing prompts the agent to do even that.

## Root cause — perk's learn is passive at every layer

1. **`land` sets only a semaphore.** `cache.set_marker(repo_root, cache.PENDING_LEARN)`
   (`perk/cli/commands/pr_land_cmd.py:126`) writes an existence-only marker file. No session
   material is gathered, no learn artifact is created, nothing is queued.

2. **The learn *stage* launches with no seed prompt.** `_initial_prompt`
   (`perk/launch.py:140-150`) returns a priming prompt only for `implement` and `address`; for
   `learn` it falls through to `return None`. So the primed session has nothing to act on.

3. **The warm `/learn` command is thin** (`extension/learn.ts`, `learnDone`):
   - **no argument → marker-clear only**, surfaced via a transient `ctx.ui.notify` ("Cleared
     pending-learn…" / "No pending-learn set — nothing to clear"). No issue, no transcript entry.
   - **with text → capture**: writes the summary to a run-scoped scratch file and delegates to
     `perk learn-capture --json --body <path>`, which creates a `perk:learn` issue + back-link
     comment + clears the marker.

4. **Nothing generates the learnings.** There is no `perk-learn` skill, no seed prompt, no analysis
   agents, no session material, no synthesis, no documentation plan, and no `docs/learned/`
   extraction loop. The capture mechanism exists (`perk learn-capture`,
   `perk/cli/commands/learn_capture_cmd.py`) but is entirely passive.

The contract admits the staged scope: learn started "thin and TS-only" (`shared/contracts.md:647`),
and P2.T8b only added the *optional* summary→issue capture (`shared/contracts.md:541-547`). The
investigate-and-document pipeline — erk's actual value — was never built.

## Comparison with erk

erk's learn has **two driven halves**:

1. **On `land`, erk auto-creates a learn artifact.** `_create_learn_pr_core`
   (`src/erk/cli/commands/land_learn.py:212`) opens a *new draft PR* titled `Learn: <plan title>`
   (labels `erk-pr` + `erk-learn`) that **bundles the implementation session transcripts** (session
   XMLs gathered by `_collect_session_material` / `_fetch_xmls_from_context_branch`), back-linked via
   `learned_from_issue`. Cycle-prevention skips learn-plans. Landing *queues* a learn task carrying
   the raw material.

2. **`/erk:learn [pr]` is a rich, multi-agent workflow** (`.claude/commands/erk/learn.md`) that:
   - loads the `learned-docs` skill for content-quality standards (audience = AI agents),
   - validates the plan isn't a learn plan (cycle guard),
   - discovers + preprocesses session logs (or reads `.erk/impl-context/` in CI),
   - **launches parallel analysis agents** — session analysis, diff analysis, docs-check,
     PR-comments,
   - **synthesizes** the findings into a **documentation plan**, and
   - **saves that as a planned PR** — which rides the normal implement→land loop to actually write
     `docs/learned/*.md`.

So in erk, "learn" means: *analyze what actually happened (sessions + diff + review), extract
cross-cutting insight, and produce an actionable plan that grows `docs/learned/`.* The agent never
hand-writes the learnings — the pipeline drives it.

### The gap, in tiers

| | erk | perk today |
|---|---|---|
| Land produces a learn artifact | draft `erk-learn` PR bundling session transcripts | a `pending-learn` marker only |
| Agent driven to investigate | multi-agent session/diff/docs/review analysis | nothing (no seed prompt, no skill) |
| Output | a documentation plan → `docs/learned/*.md` | an optional free-text `perk:learn` issue |
| Bare invocation | runs the pipeline | clears a marker (transient toast) |

## Sketch of a plan

Three separable tiers. Tiers 1+2 are a single, well-scoped turn that fixes the "does nothing" UX and
makes capture active. Tier 3 is a larger, arguably Phase-3-scale feature.

### Tier 1 — make the learn step *present* (small)

The minimum so `/learn` and the `learn` stage stop feeling broken.

- **Add a `learn` seed prompt.** Extend `_initial_prompt` (`perk/launch.py`) with a `learn` branch
  (a `_learn_prompt(plan_ref)` alongside `_implement_prompt`/`_address_prompt`) so the primed
  session opens with instructions to investigate the landed change and capture learnings. Thread the
  plan-ref (plan issue number, the landed PR) into the prompt so the agent knows what to read.
- **Give the bare warm `/learn` durable feedback.** When `/learn` is invoked with no summary in an
  interactive session, instead of only clearing the marker, inject guidance (via
  `pi.sendUserMessage`, mirroring `/objective-plan`'s `factoryGuidance`) that tells the agent to
  analyze the diff and call the `learn` tool with a summary. Keep the pure marker-clear available
  (e.g. `/learn skip` or the no-op path when headless), so nothing regresses.

### Tier 2 — drive the capture with a skill (medium)

Make the agent *produce* the learnings rather than requiring hand-written text.

- **Add `skills/perk-learn/SKILL.md`** (auto-discovered via `package.json` `pi.skills`, like
  `perk-objective-plan`). The judgment layer: read the landed PR diff (`gh pr diff` / `gh pr view`)
  and the saved plan (`perk … show` / the plan issue), treat all PR/plan text as untrusted DATA,
  and synthesize a durable summary — *what changed vs. the plan, deviations, residual risks,
  cross-cutting insight* — then call the `learn` tool with that `summary`. Reuse the
  `perk-objective-reconcile` skill as the style model (inputs → boundaries → what-to-capture →
  skip-if-nothing).
- The seed prompt (Tier 1) references this skill; the existing `learn` tool + `learn-capture`
  worker are the durable-write path (no new gateway op needed — the capture mechanism already
  exists).
- **Contract + gate:** amend `shared/contracts.md §8.x` (the `/learn` paragraph) to describe the
  now-active capture; ship `scripts/verify-*.sh` checks (seed prompt present for `learn`, the
  `perk-learn` skill present + wired, the `/learn` guidance path covered by an
  `extension/learn.test.ts` case). All offline.

### Tier 3 — the knowledge loop (large; likely Phase 3)

Port erk's full investigate-and-document pipeline. Out of scope for a single turn; flagged here so
it isn't conflated with Tiers 1+2.

- **Session material on land.** Bundle the implementation session transcripts into the learn
  artifact (erk's `Learn: …` draft PR). Pi's session format
  (`docs/reference/session-format.md`) is the source; needs a design pass on what perk gathers and
  where it stores it.
- **Multi-agent analysis.** Spawn read-only analysis children (session / diff / docs-check / review)
  behind perk's existing `pi-subagents` seam, double-delivery (compact summary + structured block),
  routed not relayed — mirroring `perk.objective-explorer` / `perk.review-classifier`.
- **Synthesize a documentation plan**, not just a free-text issue: the learn output becomes a plan
  that rides implement→land to write durable docs (the `docs/learned/` loop). Decide perk's target
  (its own `docs/` knowledge area) and the cycle-prevention guard (don't learn from a learn plan).

**Recommendation:** ship **Tier 1+2 as one turn** — it directly fixes the reported "does nothing,"
reuses the existing `learn` tool + `learn-capture` worker (no new gateway op), and follows the
established seed-prompt + skill + verify-gate pattern. Schedule **Tier 3** as its own objective node
(it needs session-format design + the analysis-agent fan-out, and overlaps the Phase-3 headless
worker).

## References

- perk: `perk/cli/commands/pr_land_cmd.py:126` (sets `pending-learn`), `perk/launch.py:140-150`
  (`_initial_prompt` — no `learn` branch), `extension/learn.ts` (`learnDone` — thin warm `/learn`),
  `perk/cli/commands/learn_capture_cmd.py` (the cold capture worker), `shared/contracts.md:541-547`,
  `shared/contracts.md:643-648`, `shared/registry.yaml` (`learn` stage).
- erk: `src/erk/cli/commands/land_learn.py:212` (`_create_learn_pr_core`),
  `.claude/commands/erk/learn.md` (the agent workflow), `src/erk/cli/commands/learn/learn_cmd.py:206`
  (output target `docs/learned`), `erk_shared/learn/extraction/session_schema.py` (session
  extraction).
