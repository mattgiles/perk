---
title: perk's subagent orchestration — project vs builtin agents, the two mutation shapes, and agent-def delivery to consumer repos
read_when: You are spawning a subagent for fresh-context work, configuring a project agent's model, choosing read-only-child-then-parent-mutates vs child-posts-own-mutation, the read-only fan-out shape (a report-only reviewer drops `write`, angle passed per-call), working on the `/pr-review` / `/address` orchestration, or delivering perk's agent defs to consumer repos (the frontmatter-derived runtime name, installed-packages-are-never-scanned, the committed managed convergence, no worktree mirror).
---

# perk's subagent orchestration

perk delegates fresh-context work (PR review, classification, objective exploration, conflict
resolution) to subagents via the `pi-subagents` package. perk's **four** agent defs are **delivered
into consumer repos by `perk init`** (a committed managed convergence — see below); the warm commands
(`/pr-review`, `/address`) and the `/submit` mergeability drive spawn them. This doc captures the
non-obvious rules an agent can't derive from any single file.

> **One Code Rule.** Everything below names files and describes behavior; it does not reproduce
> source (the one GitHub-API reference is flagged as such). Read the pointers.

## `subagents.agentOverrides` reaches only BUILTIN agents — never project agents

`subagents.agentOverrides` only applies to **builtin** agents; it does **not** reach project agents
loaded from `.pi/agents/`. Proof: `pi-subagents`' `applyBuiltinOverrides`
(`.pi/npm/node_modules/pi-subagents/src/agents/agents.ts`).

**Correction:** a prior `shared/contracts.md` §8.3 note claimed the classifier model is "overridable
via `subagents.agentOverrides`." That was **wrong** and is corrected — do not restate it as
still-true.

## The correct knob for a configurable project-agent model

A committed frontmatter `model` default + a **per-call inline `model` override** on the `subagent`
tool call (the `model` param exists in `pi-subagents`' `schemas.ts` for single runs). `/pr-review`
reads `[pr-review] model` from `perk.toml` (overlaid by `perk.local.toml` for per-user override) and
injects it inline — **no committed-file churn**.

## Two mutation shapes — when the spawned child posts vs. when the parent does

- **`/address`** keeps the spawned child **read-only**; the **parent** applies fixes/mutations.
- **`/pr-review`** deliberately departs: the child **posts its own review**, because the PR is the
  *sole output sink* and there is no parent-side fix — relaying back through the parent would
  reintroduce the session pollution the fresh context exists to avoid.

**Decision rule:** child-posts-own-mutation **iff** the spawned work's only output sink is the
external surface and there's no parent-side action; otherwise read-only child + parent mutates.

**D1 holds in both:** the GitHub mutation stays canonical in Python (`perk pr review-post`); the
child only has `bash` (run the CLI) + `write` (stage the payload file). It never holds a GitHub
token or composes the mutation itself.

**Update (#660): `/pr-review` was reshaped to report-only + parent-posts.** The single posting child
became the **same classify-then-act shape as `/address`** — the reviewer is now **read-only and
reports structured findings**, and the **parent** reconciles + posts once via `post_pr_review`. So
the "child-posts-own-mutation" shape no longer has a live `/pr-review` example; the decision rule
still holds, but the parallel angle-coverage need (below) tipped `/pr-review` onto the read-only
fan-out side.

- **Report-only means dropping `write`.** The single-angle `/pr-review` reviewer drops `write` from
  its `tools` (no temp-file staging — it only runs `review-context` and emits a fenced JSON block,
  then stops). **The angle is passed per-call in the spawn `task`** — one parameterized agent, no
  new agent defs, no new `[subagents]` keys, binding unchanged. This is the read-only fan-out shape:
  prefer the read-only reviewer for parallel angle coverage; a GitHub-**posting** agent run in
  parallel would spam duplicate reactions/reviews (the parent posts once, after reconciling).

## Isolation knob: `context: "fresh"` vs `"fork"`

`context: "fresh"` is a clean session (for independence — reviews want this); `context: "fork"`
branches the parent's history. Pick `fresh` whenever the child's judgment must not be colored by
parent context.

## Isolated `createAgentSession` bypasses perk's read-only gate (#628)

perk's read-only enforcement is a per-session `pi.on("tool_call")` hook on the **main** session. An
extension feature that spins up its **own** isolated `createAgentSession` (e.g. `/btw`'s side-chat)
runs **outside** that hook — so during a read-only perk session it could edit/write. The fix:
**thread the tool-gating state into the feature** and derive the side session's toolset from it —
read-only ⇒ `["read"]` only (a foreign session's `bash` can't be sandboxed by perk's read-only bash
check, so bash/edit/write are all excluded), read-write ⇒ the full set. And **fold the gate state
into the side-session cache key** so a gate flip **recreates** the side session instead of reusing a
stale toolset.

## Flat agent/seam-keyed config pattern

perk uses a flat selection pattern under `[subagents]` in `perk.toml` to map specific agent seams to
selected agents, mirroring the `[providers]` layout. This config is parsed in TypeScript
(`parseSubagentsSelection`) and in Python (`_parse_subagents_selection`) via simple dict comprehension
(or equivalent object mapping) over a fixed, known-keys tuple. Because it maps keys directly without
complex dynamic schemas, there is no specialized doctor validation required for these selections.

## Cross-plane parity literals

For shared subagent subsystems that are executed on both planes (like `review-classifier` in
`extension/worker/worker.ts` and `perk/run/launch.py`), the model and prompt clauses must remain byte-identical
across TypeScript and Python. This parity must be strictly pinned by reciprocal tests in both test
suites (e.g., `worker.test.ts` asserting `ADDRESS_MODEL_CLAUSE` and
`test_worker_prompt_parity.py` asserting `_ADDRESS_MODEL_CLAUSE` against the same expected prompt
template or model string).

## Guidance testing

To ensure warm-door pure guidance builders (such as `addressGuidance` or `factoryGuidance`) can be
thoroughly verified without launching heavy live sessions, they must be exported from their
defining modules. This makes it possible to unit-test the prompt generation logic offline in standard
test suites.

## TS TOML trailing-backslash continuation restriction

The simplified TOML subset parser implemented in the TypeScript plane does not support trailing-backslash
(`\`) multiline string continuation. When defining strings in `perk.toml` (or any other TOML file parsed
by TS), you must use either a single unbroken line or other narrow subset escapes supported by the parser.

## Resilience for inline-anchored GitHub review submission

`POST .../pulls/{n}/reviews` with `event=COMMENT` + `comments[]` can **422** when a `line` isn't in
the diff. The gateway **falls back** to posting summary + rendered findings as a single discussion
comment (`POST .../issues/{n}/comments`) so a review *always* lands, recording which path it took
(`mode: "review" | "comment_fallback"`). `event=COMMENT` is **hardcoded** so the agent can never
approve / request-changes. (This is an API-behavior reference — see `## Sources`.)

## The newest agent: `conflict-resolver` (first write-capable + context-inheriting)

The agent-def set is now **four**: `conflict-resolver`, `objective-explorer`, `pr-reviewer`,
`review-classifier` (`PERK_AGENTS` keeps them sorted). `conflict-resolver` is **the first
write-capable + context-inheriting** perk agent — `tools: read,grep,find,ls,bash,edit,write`,
`inheritProjectContext: true`, `inheritSkills: true` — **departing** from the read-only
classifier/reviewer, because resolving merge conflicts requires understanding the code and running
the repo's checks. Like the reviewer it **fetches its own context** read-only via
`perk pr review-context --json` and is **driven reactively by the `/submit` warm door**. (The verified
tree has four; do **not** restate the learning's "5th" wording.) The orchestration that drives it lives
in `workflow/mergeability-and-conflict-resolution.md`.

## Agent-def delivery to consumer repos (the realized design)

perk's **four** subagent defs (`conflict-resolver`, `objective-explorer`, `pr-reviewer`,
`review-classifier`) reach consumer repos via the Python wheel + `perk init`. This closed the former
"known gap."

### How pi-subagents discovers project agents

Discovery (`pi-subagents/src/agents/agents.ts`) is **recursive** over `<root>/.pi/agents` (+ legacy
`.agents`), and the runtime name is derived from **frontmatter** (`name` + `package`), **NOT the file
path** — so `.pi/agents/perk/<name>.md` with `package: perk` yields runtime name `perk.<name>`
identically to a top-level file (subdir placement is free). **Installed npm packages are never
scanned for agent defs** — shipping agents in the npm package would NOT make them discoverable. This
is *why* the carrier is the Python wheel + `perk init` materialization, not the npm package.

### The delivery design (mirror of skills / `shared/`)

- **Sources live OUT of the discovered tree**: top-level `agents/<name>.md` (no leading dot) so pi
  never double-loads them in perk's own repo — same trap/fix as skills.
- **Bundling mirrors `shared/`→`perk/_shared`**: a `force-include` adds `agents` → `perk/_agents` to
  the wheel + sdist; **npm `files` is unchanged** (Python-plane-only delivery; the packaging test
  asserts `agents/` is absent from the npm tarball).
- **The resolver mirrors `shared_dir()`**: package-data candidate `perk/_agents`, else editable repo
  sibling `<repo>/agents`, else a `FileNotFoundError` naming both.

### The widening-lockstep census (surfaces to touch when adding an agent)

Adding an agent touches, in lockstep: the `agents/<name>.md` source + `PERK_AGENTS` (kept sorted) +
the commented `[subagents]` sample + `_SUBAGENT_KEYS` (`config.py`) + `SUBAGENT_KEYS` / the
`subagents` field type (`config.ts`) + tests (`test_config.py`, `config.test.ts`, `test_packaging.py`
expecting `perk/_agents/<name>.md`). `test_doctor` / `test_init_idempotent` auto-cover delivery. The
model is configurable via `[subagents] <name>`, injected as a **per-call inline `model` override**
(agentOverrides don't reach project agents — see the top of this doc).

### A committed managed convergence

A `PERK_AGENTS` SSOT tuple drives a content convergence (`_converge_subagent_agents`) that delivers
each def **byte-for-byte** into the perk-owned `.pi/agents/perk/` subdir and **prunes stray `*.md`
inside that subdir** (perk owns the WHOLE subdir; it never touches anything outside it, e.g. a user's
own `.pi/agents/mine.md`). It computes the **identical change-list for `apply=True`/`apply=False`**
(the managed-convergence invariant) and is the auto-generated `subagent-agents` doctor check. There
is **no `self_repo` param** (unlike the skills sibling): the resolver works in both install modes, so
self-repo and consumers get byte-identical defs. Because `.pi/agents/perk/` is **committed
(tracked)**, linked worktrees inherit the defs via `git checkout` — **no worktree symlink mirror**
(contrast skills' `materialize_skills`; see `workflow/init-doctor.md` for the reusable contrast).

### Doctor

The `subagent-engine` enumeration moved from `.pi/agents/*.md` to `.pi/agents/perk/*.md` (still
informational; the `subagent-agents` convergence owns drift). The `[subagents]` config stays
**fixed-key** (perk's four agents only) — it does **not** configure user agents (those set `model:`
in frontmatter; see `how-to/write-a-custom-subagent.md`).

### Process note

Running `perk init` in perk's own dev worktree also delivers the self-repo's `.pi/agents/perk/`
(stage those committed defs). During that run the **skills sync may fail with a `conflict`** — a
**pre-existing local-env condition, unrelated and non-blocking** (the `subagent-agents` convergence
runs and reports its `created` lines BEFORE the skills step).

## Editing a perk agent's prose rubric — the reconverge ritual + the judgment-prompt anti-pattern

Editing how a perk agent *judges* (e.g. rewriting the `perk.pr-reviewer` review rubric) is a pure
prompt change. The non-obvious mechanics and the cross-cutting lesson:

### Where the rubric lives & how to reconverge it

The reviewer rubric is **entirely** in the agent **system prompt** — SSOT `agents/pr-reviewer.md`
(root `agents/`, no leading dot), materialized by `perk init`'s `_converge_subagent_agents` into
`.pi/agents/perk/pr-reviewer.md`. The skill (`skills/perk-pr-review/SKILL.md`) and the door
(`extension/doors/prReview.ts`) **defer** to it — **don't look there for review logic**. After
editing the source, **re-run `perk init`** to reconverge and commit **both** copies byte-identical
(the init-idempotency + doctor `subagent-agents` checks expect consistency). **Stale-path gotcha:**
the materialized copy is the `perk/`-namespaced `.pi/agents/perk/pr-reviewer.md`, **not** the old
`.pi/agents/pr-reviewer.md` the skill once cited — grep for the stale path when touching agent docs.

### Two `perk init` worktree gotchas (reality, not aspiration)

- In a worktree where skills are already materialized, `perk init` **fails the `skills --sync`
  step** but prints `Converged before failure:` listing the agent copy as `updated` — the **agent
  reconvergence happens before the skills failure**, so it's **non-fatal for an agent-only edit**
  (confirm the agent diff is clean; don't chase the skills failure).
- `perk init` also creates the **gitignored** `.pi/perk.local.toml` — **stage only the intended
  files explicitly** (don't `git add -A`).

### Testing reality

**No test asserts an agent's prose body verbatim.** The wheel-bundling + idempotency + doctor
guards check **presence + consistency**, not content. A pure prompt rewrite keeps `just ci` green
without touching a single string assertion.

### The judgment-agent prompt anti-pattern (the cross-cutting lesson)

A reviewer's "always says no/clean" bias was **structural in the prompt, not the plumbing**. The
verdict vocabulary (`clean` / `actionable`) and the `fyi` array already carried everything; only the
*quality of judgment* changed — a **pure prompt-engineering change** (no Python, no door, no
`shared/contracts.md` touch). Three structural biases caused the skew:

1. a verdict that **falls through to a default** (the default conclusion wins absent active
   contradiction);
2. a "decide the verdict first" instruction that **anchors the conclusion before findings are
   enumerated**;
3. anti-noise framing repeated with **no counterweight** to hunt for problems.

**Antidote:** an explicit *"earned, not defaulted"* balance statement →
**enumerate-findings-first → derive the verdict**, plus adversarial axes / investigation license —
while keeping the **binary posting bar unchanged** (a clean verdict stays first-class; noise isn't
manufactured). **Generalize to any judgment-agent prompt:** remove default verdicts, order
findings-before-conclusion, and add a counterweight to any anti-noise framing.

### Residual

A missing `plan_body` (the best-effort read returns `None`) is now **surfaced** in `summary` / `fyi`
rather than silently dropping the conformance axis; **no retrieval fallback was added** (flagged as a
follow-up if missing plan bodies prove common).

## Residual

No workflow-state record of a `/pr-review` (no parent tool turn → no `last_review_batch`-style
record); the posted PR comment is the canonical record. `perk/substrate/config.py`'s `pr_review_model` is
parsed-but-unused today (only the TS warm path consumes it — no cold `/pr-review` door yet).

## Sources

- GitHub Pull Request Reviews API: `POST /repos/{owner}/{repo}/pulls/{n}/reviews` (the `event` /
  `comments[].line` shape) and `POST /repos/{owner}/{repo}/issues/{n}/comments` (the comment
  fallback). The 422-on-out-of-diff-line behavior is the documented reason for the fallback.

## Cross-references

- `extension/doors/prReview.ts` — `prReviewGuidance`, `registerPrReview`, the child-posts-own-mutation header (defers the review rubric to the agent prompt)
- `docs/learned/workflow/mergeability-and-conflict-resolution.md` — the `/submit` orchestration that drives the `conflict-resolver` agent
- `agents/*.md` — the SSOT agent-def sources (delivered into `.pi/agents/perk/` by `perk init`); `agents/pr-reviewer.md` carries the entire reviewer rubric
- `skills/perk-pr-review/SKILL.md` — the orchestration skill that defers to the agent prompt (not where review logic lives)
- `perk/convergence/init.py` — `PERK_AGENTS`, `_converge_subagent_agents` (the committed managed convergence)
- `docs/learned/workflow/init-doctor.md` — the committed-convergence-vs-symlink-mirror contrast
- `docs/user-docs/how-to/write-a-custom-subagent.md` — user agents set `model:` in frontmatter (the fixed-key `[subagents]` boundary)
- `perk/cli/commands/pr_review_post_cmd.py` — the canonical Python mutation (D1)
- `shared/contracts.md` §8.3 — the corrected `agentOverrides` note, the agent-def delivery design, + workflow-state schema
- `docs/learned/workflow/warm-door-commands.md` — the driving-command shape `/pr-review` departs from
- `docs/learned/workflow/skill-bindings.md` — the `command:<id>` binding checklist (`/pr-review` is one)
- the `pi-subagents` skill — single/chain/parallel/forked-context delegation
