---
title: perk's subagent orchestration — project vs builtin agents, the two mutation shapes, and agent-def delivery to consumer repos
read_when: You are spawning a subagent, configuring an agent's model, re-enabling a disabled builtin, supervisor-channel streaming, observing child token/cache usage, /pr-review or /address, or perk agent defs.
---

# perk's subagent orchestration

perk delegates fresh-context work (PR review, classification, objective exploration, conflict
resolution) to subagents via the `pi-subagents` package. perk's agent defs — the `PERK_AGENTS`
tuple in `src/perk/convergence/init/agents.py` — are **delivered into consumer repos by `perk
init`** (a committed managed convergence — see below); the warm commands (`/pr-review`, `/address`)
and the `/submit` mergeability drive spawn them. This doc captures the
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

## Builtins are OFF in every perk repo — and the re-enable precedence

pi-subagents' **builtin** agents are disabled in every perk repo via the managed
`subagents.disableBuiltins: true`, delivered by `_converge_subagents` (`perk/convergence/init/settings.py`).
perk borrows pi-subagents as the delegation *engine only* and ships its own `perk.*` defs, so the
builtins are model-facing noise everywhere — this is perk's posture, not a per-repo config knob
(there is no `.perk/config.toml` involvement; see `borrowed-packages.md` for why a borrowed
package's behavior must be converged, and `init-doctor.md` for the delta-gating this constant-desired
fragment forced).

**Re-enable precedence, verified in pi-subagents' `applyBuiltinOverrides`** (`.pi/npm/node_modules/pi-subagents/src/agents/agents.ts`):

- A **project-settings** per-agent `subagents.agentOverrides.<name>.disabled: false` **works** —
  the per-agent project override is consulted *before* the project bulk-disable flag, so it
  re-enables that one agent. perk's merge only ever touches the `disableBuiltins` key, so a
  hand-added sibling `agentOverrides` survives byte-for-byte.
- A **user-global** `~/.pi/agent/settings.json` re-enable does **not** work — the project bulk-disable
  branch returns `{disabled: true}` for the agent *before* user-scope overrides are consulted, so
  project scope wins. Re-enable at **project** scope.

## The correct knob for a configurable project-agent model

A committed frontmatter `model` default + a **top-level workflow-level `model` on the one
`subagent` workflowScript call** (a default flowing onto every lane — single-child runs included;
there are no non-workflowScript spawns anymore, so there is no per-call inline `model` shape
left). `/pr-review`'s `run_pr_review_wave` tool reads `[models.subagents] pr-reviewer` from
`.perk/config.toml` (overlaid by `.perk/local.toml` for per-user override) and the wave module
applies it as the wave's workflow-level `model` default — **no committed-file churn**.

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
  its `tools` (no temp-file staging — it only runs `review-context` and ends with a
  `structured_output` report, engine-validated against the wave's `outputSchema`, then stops).
  **The angle is passed per-lane in the `task`** — one parameterized agent, no
  new agent defs, no new `[models.subagents]` keys, binding unchanged. This is the read-only fan-out shape:
  prefer the read-only reviewer for parallel angle coverage; a GitHub-**posting** agent run in
  parallel would spam duplicate reactions/reviews (the parent posts once, after reconciling).

## Subagent context artifacts get swept by `git add -A` (recurring process hazard)

The `/pr-review` and `/address` flows spawn subagents that run `perk pr review-context --json` and
fetch the raw diff; these land as `formatted_context.json` and `pr_diff.diff` in the **worktree
CWD**. A later `git add -A` (used in implement/address commit steps) **silently sweeps both into the
commit** and pushes them — caught only in `/learn` before merge.

Mitigations for future agents:

- Prefer `git add <explicit paths>` over `git add -A` in worktree sessions where subagents may drop
  files.
- Inspect `git status` before committing.
- These well-known artifact names are good candidates for a repo `.gitignore` entry, or for the
  cold-door context fetch to write under the workflow scratch dir instead of CWD.

`formatted_context.json` is the `perk pr review-context` envelope (data-format shape:
`{success, error_type, message, branch, pr, base_ref, head_ref, title, …}`).

This reinforces the existing **stage only intended files explicitly / don't `git add -A`** gotcha
already captured under the `perk init` worktree notes below.

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

perk uses a flat selection pattern under `[models.subagents]` in `perk.toml` to map specific agent seams to
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
(`mode: "review" | "comment_fallback"`). **`event=COMMENT` is hardcoded only on the `review-post`
path** (the autonomous pr-reviewer agent — it can never approve / request-changes). The
human-in-the-loop review doors (`/pr-review-terminal`, `/pr-review-browser`) use a *different*
door, `perk pr review-submit`, which carries
explicit formal events (`approve`/`request-changes`/`comment`) behind a structural human gate, with
its own event-aware failure ladder — see `workflow/github-gateway.md` (don't duplicate the ladder
here). (This is an API-behavior reference — see `## Sources`.)

## `conflict-resolver` — the first write-capable + context-inheriting agent

`conflict-resolver` is **the first write-capable + context-inheriting** perk agent —
`tools: read,grep,find,ls,bash,edit,write`, `inheritProjectContext: true`, `inheritSkills: true` —
**departing** from the read-only classifier/reviewer, because resolving merge conflicts requires
understanding the code and running the repo's checks. Like the reviewer it **fetches its own
context** read-only via `perk pr review-context --json` and is **driven reactively by the `/submit`
warm door**. The orchestration that drives it lives in
`workflow/mergeability-and-conflict-resolution.md`.

## Agent-def delivery to consumer repos (the realized design)

perk's subagent defs — the `PERK_AGENTS` tuple (kept sorted), currently `adversarial-reviewer`,
`conflict-resolver`, `learn-analyst`, `objective-explorer`, `pr-reviewer`, `review-angle-selector`,
`review-classifier` — reach
consumer repos via the Python wheel + `perk init`. This closed the former "known gap." (Don't
restate a hard count in prose — counts are drift magnets per
`workflow/doc-reconciliation.md`; `PERK_AGENTS` is the SSOT.)

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
the commented `[models.subagents]` sample + `_SUBAGENT_KEYS` (`config.py`) + `SUBAGENT_KEYS` / the
`subagents` field type (`config.ts`) + tests (`test_config.py`, `config.test.ts`, `test_packaging.py`
expecting `perk/_agents/<name>.md`) + **this doc's agent listing** (the census is self-referencing:
adding an agent should touch the doc that teaches adding agents — that is how the listing stays
current instead of drifting). `test_doctor` / `test_init_idempotent` auto-cover delivery. The
model is configurable via `[models.subagents] <name>`, injected as the **top-level workflow-level
`model`** on the one `subagent` workflowScript call — a default flowing onto every lane,
single-child runs included (agentOverrides don't reach project agents — see the top of this doc). The census has been followed
verbatim on real additions (most recently the agent since renamed `adversarial-reviewer`, added as
`guest-reviewer`) and worked cleanly — a **rename** walks the identical census (plus a `git mv` of
the source and a reconverge that prunes the old delivered def) — the only
thing that ever drifted was this doc's hard counts, hence the listing-without-a-count discipline.

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
informational; the `subagent-agents` convergence owns drift). The `[models.subagents]` config stays
**fixed-key** (the `PERK_AGENTS` set only) — it does **not** configure user agents (those set `model:`
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

## Supervisor-channel streaming (progress updates → a live parent loop)

Mechanics verified in `pi-subagents/src/` (re-verified at 0.43.0; the chain re-verified again at
**0.45.0** for the RPC-spawned-wave verdict below) while wiring
`/pr-review-terminal`'s live findings streaming — they dictate the only workable parent loop
shape:

- **`contact_supervisor` exists in every child regardless of the agent's `tools:` allowlist** —
  it is registered by pi-subagents' injected prompt-runtime extension
  (`runs/shared/subagent-prompt-runtime.ts`); the `--tools` flag restricts builtin tools only. So
  a read-only agent def can still stream, and `workflowScript` children run through the same
  in-process `execute()` as direct children — child streaming is preserved by construction.
  `reason: "progress_update"` is **non-blocking** (returns "queued" immediately; requests capped
  at 64KB).
- **Delivery is an injected message, nothing else** (`intercom/native-supervisor-channel.ts`):
  a parent-side poller (≤500ms) injects each request via `pi.sendMessage({customType:
  "subagent_supervisor_request"})` with default `deliverAs: "steer"` — delivered **before the next
  LLM call** (i.e. when the current tool call returns) — with **`triggerTurn: true` on
  every request** (re-verified at 0.43.0): an idle parent wakes (progress updates included). Progress updates **never
  enter the `pending` map** — there is no polling surface for them.
- **The wait tool is `subagent_wait`, and it wakes on completion / needs-attention only** — a
  progress update does NOT break the wait. **`subagent_wait` expiry IS the streaming cadence**: a
  `subagent_wait({ timeoutMs })` loop's expiries are what let queued injected messages deliver —
  each expiry returns the tool call, the queued messages
  deliver, the parent processes/pushes, then re-waits. The parent
  **holds its turn open** — an ended turn degrades streaming to churny per-request wake-ups (the
  `triggerTurn` mechanic) instead of a held relay.
- **The grouped `tasks[]` / `chain[]` execution surfaces were REMOVED upstream (v0.41.0–v0.42.1)**
  — `workflowScript` (constrained JS: `runs.run`/`runs.all`) is the sole multi-agent
  orchestration surface, and combining it with `agent`/`tasks`/`chain`/`action` is rejected. A
  multi-lane fan-out is ONE async workflow (`async !== false` ⇒ background): a single all-settled
  `runs.all([...])` — a failed lane resolves `{key, ok: false, output, error}` instead of
  throwing (siblings never sink; duplicate keys with different params throw); `phase`/`label` are
  per-item trace metadata rendered by `action: "status"` step lines; top-level params (notably
  `context`, `model`) default onto every child launch, explicit child fields overriding. A
  workflow child's `output` is the child's **full final message**, and the script's return value
  persists in `<asyncDir>/status.json` under `workflow.value` (the asyncDir survives completion).
  **The completion notification does NOT carry per-child reports** — its text is a truncated
  (~1000-char) return preview; retrieve the full return via `subagent({action: "status", id})`
  (the `Dir:` line) → `read <Dir>/status.json`. **At 0.43 the cut went further: direct
  `{agent, task}` single-child execution was also removed** — `src/extension/public-execution.ts`
  rejects it with `Direct execution was removed. Use workflowScript: "return runs.run('main',
  { agent, task })".` — so `workflowScript` is the **sole public execution surface, one-child
  runs included**. perk's four remaining direct-spawn guidance surfaces (`/address` classify,
  the objective-plan explorer, `/submit`'s conflict-resolver, `/learn`'s analyst fan-out) were
  converted accordingly: an explicit-return one-child `runs.run` returning the compact
  `{key, ok, error, output}` projection (never the raw ChildResult — its `results` carries the
  full child metadata). The two read-only single-child flows (`/address` classify, the
  objective-plan explorer) additionally carry a top-level `outputSchema` on the one call and
  project `report: structuredOutput ?? null` beside `output` — engine-validated typed reports
  instead of fenced JSON (the schemas live once as `prompts/common/output-schemas/` include
  partials); `conflict-resolver` deliberately stays untyped — its child output is a merge
  resolution, not a report. `/learn`'s analyst fan-out has since migrated OFF model-authored
  scripts entirely: the wave is code on the report-wave module (`extension/waves/learnWave.ts`
  → `runReportWave`), driven by the flow-scoped `run_learn_wave` tool — an async RPC-spawned
  all-settled `runs.all` whose script the module renders, with engine-validated structured
  reports instead of fenced JSON.

### RPC-spawned async waves stream identically (the settled 0.45.0 verdict)

An RPC-spawned async workflowScript wave delivers supervisor-channel progress updates to the
parent session **identically** to a model-called wave, **by construction**: the v1 RPC `spawn` is
a thin envelope over the same executor with the parent session's context, and parent-side
delivery is **session-scoped file polling** (matching `orchestratorSessionId` against the current
session), never run-scoped. Supporting facts, source-read at 0.45.0:

- **Async workflows run in-process in the parent pi** — `status.json` carries
  `pid: process.pid`; only single/chain runs get the detached runner. Consequence: an "async"
  wave dies with the parent pi process — fine for session-scoped surfaces, disqualifying for
  anything that must outlive the session.
- **Workflow children default to foreground**, which is what satisfies the one conditional gate
  in the env-stamping chain (the supervisor channel dir is set iff orchestrator target +
  parentSessionId + runId + agent name).
- **The one silent killer is config**: `subagents.intercomBridge.mode: "off"` — or
  `"fork-only"`, since perk's wave children run fresh-context — suppresses the channel-dir stamp
  and degrades streaming to completion-only **with no error**. Now guarded by the report-only
  `subagent-bridge-config` doctor check (`src/perk/convergence/doctor/checks.py`; both scopes —
  project `.pi/settings.json` + user-global `~/.pi/agent/settings.json` — warn-never-fail, no
  `--fix`; perk deliberately does NOT reimplement pi's cross-scope merge, so either scope's
  explicit-off warns).
- **The dead fallback is dead**: code-owned spawn *without* live streaming is not to be built —
  the binding posture is RPC spawn + a model-held `subagent_wait` relay loop.

### Validation posture: the streaming protocol is still mostly prompt-followed

The fan-out and report retrieval are code now (the `start_review_wave`/`collect_review_wave`
tool pair over the report-wave module — no model-authored `workflowScript`, no `status.json`
read-back), but the streaming protocol around them is **model-followed prompt text**: the agent
def's progress-update step, the `subagent_wait({timeoutMs})` parent loop, the incremental
path+line dedupe ledger (terminal; the browser's ledger is tool-owned in `push_annotations`),
hold-until-handshake, and the skip-silently fallback are all guidance — tests pin only
guidance-string **presence**, never behavior. **The first live run is the integration test.**
The live-run watch axes:

- (a) do batches actually deliver on each wait-expiry (the steer-on-tool-return mechanic);
- (b) does the dedupe ledger hold across a long triage conversation;
- (c) is the 30s cadence right (too short → chatty loop; too long → stale findings);
- (d) the parent must hold its turn open — an ended turn degrades streaming to churny per-batch
  wake-ups instead of a held relay.

**Upstream-drift caveat:** the load-bearing delivery mechanics above are **source-read-derived**
(pi-subagents `src/` at 0.43.0) — an upstream change to the supervisor-channel or workflow
contract invalidates the loop shape silently; re-verify on pi-subagents bumps (the grouped
`tasks[]` removal across upstream v0.41.0–v0.42.1 is exactly this failure mode: it live-broke
both review doors with no test tripping). The doctor `subagent-compat` check is now the
early-warning tripwire for **surface-level** drift: it probes the installed source for marker
presence (`workflowScript`, `outputSchema`/`structuredOutput`, `"subagent_wait"`, the
supervisor-channel trio `"contact_supervisor"`/`"subagent_supervisor_request"`/`triggerTurn`,
the workflowScript-only public-execution cutover (`Direct execution was removed`), the v1 RPC
events (`subagents:rpc:v1:*`), retained children (`listRetainedChildren`) + the retained-child
resume contract (`resume and agent are mutually exclusive`), the statement-body
explicit-return vm wrapper (`(async () => {`), and the 0.45.0 completion-receipt surfaces —
the wait-completion projection (`toWaitCompletion`/`recordWaitCompletion`), `subagent_wait`'s
`completions` details, and the serialized workflow child `runId: child.runId`) and warns
loudly on divergence. Substring
presence only — the deeper wait/streaming mechanics remain source-read-derived and still
warrant a manual re-verify on bumps.

**The tripwire-marker pattern (for extending `_SUBAGENT_COMPAT_PROBES`):** choose the literal
whose *disappearance signals the architectural change you care about*, not just any stable string
— e.g. `pid: process.pid` is deliberately the async-workflow-status literal: if workflows ever
move to a detached runner it vanishes and doctor warns, which is exactly the re-verify signal.
File-scoped probes (no tree-wide fallback) make a *moved* file warn too — a wanted tripwire, not
noise.

The repeatable success pattern: when a feature depends on subtle dependency runtime behavior, the
**planning session** should read the dependency source and pre-digest the mechanics into the plan
body — the implementation had zero dead ends because discovery wasn't left to the implementer.

## Workflow structured output (`outputSchema` → engine-validated per-lane reports)

The `/pr-review` report wave rides these mechanics (now module-run: `extension/waves/prReviewWave.ts`
over the v1 RPC via the flow-scoped `run_pr_review_wave` tool), source-read in
`.pi/npm/node_modules/pi-subagents/src/` at 0.43.0 and re-verified at 0.45.0 (same
upstream-drift caveat as above — re-verify on bumps). The two model-authored single-child flows adopted the same mechanics as
foreground one-child workflows: the `/address` classify and objective-plan explorer guidance
passes a top-level `outputSchema` (the shared-template `prompts/common/output-schemas/` includes)
and reads the typed report from the projection's `report: structuredOutput ?? null`:

- **A top-level `outputSchema` is a workflow-level child default** — like `context`/`model`, it
  flows onto every `runs.run`/`runs.all` launch (explicit child fields override), so a wave writes
  the schema ONCE in the tool call, never inside the script.
- **`outputSchema` injects a `structured_output` tool into the child**
  (`runs/shared/structured-output.ts`, `runs/shared/subagent-prompt-runtime.ts`) — present
  regardless of the agent's `tools:` allowlist (INTERNAL_TOOLS in `runs/shared/permissions.ts`),
  plus prompt-runtime instructions making that call the child's final action. The child run FAILS
  (`structuredOutputFailed`) when the child never calls the tool or the payload is schema-invalid;
  `result.structuredOutput` (a `WorkflowScriptChildResult` field) is populated ONLY on a
  successful, schema-valid run — so in a report wave, covered lane ⟺ `ok: true` ⟺ a schema-valid
  report is present.
- **A foreground workflow (`async: false`) returns the full aggregate inline**
  (`runs/foreground/subagent-executor.ts`): the tool result carries `Return:` + the full
  JSON-serialized `workflow.value` with NO truncation — the ~1000-char preview caveat above
  applies to the ASYNC completion notification only. No `subagent_wait` loop, no `status.json`
  retrieval; foreground workflows default to a 30-minute timeout.
- **Acceptance can't poison completeness**: with `acceptance` omitted (the `subagent` tool
  description's own rule for reviewer/read-only calls), an acceptance-heuristic wobble cannot flip
  a lane's `ok` — the "report-only children trip `acceptance: auto`" hazard (below) cannot discard
  a schema-valid report.

## The v1 extension RPC seam (`extension/waves/reportWave.ts` is the consumer)

pi-subagents exposes an extension-to-extension RPC bridge on pi's in-process event bus, and
perk's report-wave module (`extension/waves/reportWave.ts` + `rpcAdapter.ts`) launches report
waves through it — the mechanics below are source-read in
`.pi/npm/node_modules/pi-subagents/src/extension/rpc.ts` at **0.43.0**, re-verified at
**0.45.0** (same upstream-drift caveat: re-verify the adapter on every pi-subagents bump; the
doctor `subagent-compat` probes grown over `rpc.ts` are the drift tripwire):

- **The envelope**: requests arrive on `subagents:rpc:v1:request` as
  `{version: 1, requestId, method, params?, source?}`; the reply is emitted once on
  `subagents:rpc:v1:reply:<requestId>` as `{…, success: true, data}` or
  `{…, success: false, error: {code, message}}`. Methods: `ping`, `status`, `spawn`, `steer`,
  `interrupt`, `stop`, `resume`.
- **`ping` is the capability check** — it works even with no active session context and returns
  `{methods[], capabilities: {asyncSpawn: true, …}, events: {…, asyncComplete}, session}`.
  `events.asyncComplete` is the ADVERTISED async-complete channel name (currently
  `"subagent:async-complete"`); perk's adapter takes it from ping rather than pinning it.
- **RPC `spawn` is async-only** (`async: false` ⇒ `invalid_params`) and workflowScript-only
  (params go through `normalizePublicSubagentExecution`; direct `{agent, task}` is rejected).
  The success `data.details` carries `asyncId` + `asyncDir` identifying the detached run.
- **The async-complete event** payload spreads the result-file data plus `runId`/`triggerTurn`;
  match a spawned run via `asyncDir` (fall back to `id` — both optional, at least one present).
  At 0.45.0 the payload also carries a normalized per-child `results` array (child `runId`,
  `success`, `outputState`, artifact paths — the row's `agent` field carries the workflow LANE
  KEY, not an agent name), which perk's `rpcAdapter` normalizes into output-free receipt
  children (`output`/`summary`/`structuredOutput` never copied; malformed rows dropped). And
  `subagent_wait` now surfaces slim `details.completions` (identity/artifact trail — never
  output; full reports still come from `status.json.workflow.value`).
- **The durable aggregate**: `<asyncDir>/status.json` survives completion; `state` is the
  terminal state (`"complete"`/`"failed"`/…), `error` the failure detail, and `workflow.value`
  the script's explicit return value.
- **`mission: false` is a valid spawn param** — every wave launch passes it (waves are ephemeral
  by explicit objective decision).
- **`pi-subagents` is NOT an allowed bare import** (`extension/bareImportGuard.test.ts`), so the
  module cannot import its constants/types: the v1 request/reply literals are pinned as perk
  module constants in `extension/waves/rpcAdapter.ts` — that is what the versioned envelope is
  for. Only the UNversioned async-complete channel name stays advertised-not-pinned.
- **pi's `EventBus.on` returns an unsubscribe function** (`dist/core/event-bus.d.ts`) —
  per-request reply subscriptions are cleanly disposed (unlike the plannotator bridge, which
  pre-dated this verification and uses a persistent-listener workaround).

## Parent-prepare large evidence lanes

For large evidence-backed review/audit waves, the **parent** does the deterministic aggregation
and gives reporter children bounded, line-oriented inputs through absolute-path manifests. Do
**not** ask read-only analyst children to parse a corpus or improvise ad-hoc shell/Python
aggregation: in the session-corpus audit, every lane that scripted its own aggregation failed its
first wave, while lanes fed precomputed bundles + absolute paths succeeded.

## Observing a child's token/cache usage (the artifact pair is the instrument)

Where to look when you need a subagent child's token or provider-cache numbers:

- **Child session files persist only when opted into** — `sessionFile`/`sessionDir`/`share` on the
  spawn config; otherwise the cwd-encoded sessions dir gets nothing for the child.
- **The always-present usage surface is the per-child artifact pair**
  `.pi-subagents/artifacts/<runId>_<agent>_<i>_transcript.jsonl` + `_meta.json` (at 0.43
  `getArtifactPaths` also yields a written `<base>.jsonl`, but the usage instrument remains the
  transcript + meta pair). Assistant records in the transcript carry per-message `usage`
  (`input`/`cacheRead`/`cacheWrite`); `_meta.json` carries aggregate usage, model, and duration.
- Measured through that surface: back-to-back spawns of the same agent show spawn-time
  **cross-process provider-cache prefix affinity** — later spawns read the shared agent prefix as
  `cacheRead` on their first assistant message.
- The SDK-level in-process child (`extension/worker/readOnlySession.ts`) is structurally
  unobservable live — in-memory session manager, no live production call sites.
- **Report-only children can trip the `acceptance: auto` heuristic** ("no edits made") despite
  returning a well-formed report — the report is still usable; don't discard it on that signal.

## Residual

The Python-parsed `[models.subagents] pr-reviewer` key (`src/perk/substrate/config.py`) is
parsed-but-unused on the Python plane today (only the TS warm path consumes it — no cold
`/pr-review` door yet). (A prior "no workflow-state record of a `/pr-review`" note here was stale:
the `post_pr_review` tool turn + the `last_pr_review` record have existed since the #660 reshape.)

## Sources

- GitHub Pull Request Reviews API: `POST /repos/{owner}/{repo}/pulls/{n}/reviews` (the `event` /
  `comments[].line` shape) and `POST /repos/{owner}/{repo}/issues/{n}/comments` (the comment
  fallback). The 422-on-out-of-diff-line behavior is the documented reason for the fallback.

## Cross-references

- `extension/doors/prReview.ts` — `prReviewGuidance` (judgment-bearing inputs only — the guidance no longer carries wave mechanics), `registerPrReview` (the flow-scoped `run_pr_review_wave` tool + the `post_pr_review` clean guard); defers the review rubric to the agent prompt
- `extension/waves/reportWave.ts` (+ `rpcAdapter.ts`, `memoryAdapter.ts`) — the Perk-owned report-wave module over the v1 RPC seam; `/pr-review` rides it via `extension/waves/prReviewWave.ts` (`PR_REVIEW_REPORT_SCHEMA`, `runPrReviewWave` — the bounded-retry entrypoint behind `run_pr_review_wave`)
- `docs/learned/workflow/report-waves.md` — the perk-side report-wave module doc (flow migrations, lane semantics, guard state, wave test machinery); this doc keeps the upstream mechanics
- `docs/learned/workflow/mergeability-and-conflict-resolution.md` — the `/submit` orchestration that drives the `conflict-resolver` agent
- `agents/*.md` — the SSOT agent-def sources (delivered into `.pi/agents/perk/` by `perk init`); `agents/pr-reviewer.md` carries the entire reviewer rubric
- `skills/perk-pr-review/SKILL.md` — the orchestration skill that defers to the agent prompt (not where review logic lives)
- `prompts/common/output-schemas/*.md` — the SSOT `outputSchema` include partials for the single-child flows (`review-classifier`, `objective-explorer`), included by the address + objective-plan stage templates on both planes
- `src/perk/convergence/init/agents.py` — `PERK_AGENTS`, `_converge_subagent_agents` (the committed managed convergence)
- `docs/learned/workflow/init-doctor.md` — the committed-convergence-vs-symlink-mirror contrast
- `docs/user-docs/how-to/write-a-custom-subagent.md` — user agents set `model:` in frontmatter (the fixed-key `[models.subagents]` boundary)
- `perk/cli/commands/pr/review_post_cmd.py` — the canonical Python mutation (D1)
- `shared/contracts.md` §8.3 — the corrected `agentOverrides` note, the agent-def delivery design, + workflow-state schema
- `docs/learned/workflow/warm-door-commands.md` — the driving-command shape `/pr-review` departs from
- `docs/learned/workflow/skill-bindings.md` — the `command:<id>` binding checklist (`/pr-review` is one)
- the `pi-subagents` skill — single-agent, scripted-workflow (`workflowScript`), async, and forked-context delegation
