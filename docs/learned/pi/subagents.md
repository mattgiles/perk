---
title: perk's subagent orchestration — project vs builtin agents, the two mutation shapes, and agent-def delivery to consumer repos
read_when: You are spawning a subagent, an agent's model, re-enabling a builtin, supervisor streaming, the two-boolean child floor, the 0.67.0 host-tool intersection, scout lanes, /pr-review, /address, agent defs.
cluster: subagent-orchestration
---

# perk's subagent orchestration

perk delegates fresh-context work — PR review, classification, objective exploration, conflict
resolution, plan/objective draft review, and per-lane `docs/learned` harvest mining
(`harvest-analyst`, live as a multi-lane wave via `run_harvest_wave` — contracts §8.48) — to subagents
via the `pi-subagents` package. Draft review is live via `/plan-review-browser` and
`/objective-review-browser` (`extension/pi/v1/objectiveReviewBrowser.ts`). perk's agent defs — the `PERK_AGENTS`
tuple in `src/perk/convergence/init/agents.py` — are **delivered into consumer repos by `perk
init`** (a committed managed convergence — see below); the warm commands (`/pr-review`, `/address`)
and the `/submit` mergeability drive spawn them. This doc captures the
non-obvious rules an agent can't derive from any single file.

> **One Code Rule.** Everything below names files and describes behavior; it does not reproduce
> source (the one GitHub-API reference is flagged as such). Read the pointers.

> **Version anchoring.** Upstream mechanics in this doc are source-read against the installed
> pi-subagents at the version pinned by `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION`
> (`src/perk/convergence/doctor/checks.py`) — **0.65.1** at this writing (the 2026-09 baseline
> re-verify; the earlier "verified against the installed 0.64.x source" spot-markers are
> subsumed by it), bumped only on a deliberate guidance re-verify; the doctor `subagent-compat`
> check warns when installed ≠ verified, and the re-verify procedure is
> `docs/developers/pi-subagents-reverify.md`. Every **other** version number in this doc names
> an upstream **event** (when a behavior changed), never verification currency.

> **Second anchor — the ≥ 0.67.0 host-builtin intersection.** pi-subagents ≥ 0.67.0
> (`getHostBuiltinToolNames` / `resolvePiLaunchToolPlan`) intersects a child's declared tools with
> the HOST session's tools whose `sourceInfo.source === "builtin"`. Agents whose name matches
> `/\b(reviewer|scout)\b/i` **fail closed at launch** when `grep`/`find` are host-unavailable; every
> other child **silently loses the tool** (a `warnings` entry that reaches only the runner's
> `console.warn`, never the RPC reply). The trigger was pi-fff `override` mode re-registering
> `grep`/`find` as extension tools — perk's own injected default until the flip to
> `PI_FFF_MODE=tools-and-ui` (`workflow/cold-door-launch.md`). Doctor's `subagent-host-tools` row
> (`_subagent_host_tools_check`) gates on `_SUBAGENTS_HOST_INTERSECTION_AFFECTED = ("0.67.0", None)`
> — an **open upper bound** that only the re-verify ritual closes; the 0.65.1 guidance stamp did
> NOT move for it. The borrowed package is unpinned and refreshes at every pi launch, so the
> installed version can bump mid-session.

## Distillation

- Since 0.64.0, `subagents.agentOverrides` applies the FULL override set to custom agents too
  (an override can displace a frontmatter-pinned `model:`). perk's knob stays `[models.subagents]`
  + the workflow-level `model` (spawn-time — wins over the def model) — its own section below.
- Two version anchors: guidance is source-read at 0.65.1 (`subagent-compat` warns on any other
  installed version — a version tripwire, never a source probe); ≥ 0.67.0 intersects child tools
  with HOST builtins (reviewer/scout lanes fail closed on a shadowed `grep`/`find`; doctor
  `subagent-host-tools`) — the two blockquotes above.
- Builtins are OFF in every perk repo ("Builtins are OFF … re-enable precedence"); `context:
  "fresh"` = clean session, `"fork"` branches parent history — "Isolation knob".
- Mutation shapes: read-only child + PARENT posts once after reconciling; child-posts-own-mutation
  has no live example. Def-level `acceptance` (level "none" + reason) immunizes children against
  auto-inference; `completionGuard: false` is the report-only escape — "Def-level acceptance".
- perk's agent defs (the sorted `PERK_AGENTS` tuple, the SSOT — never restate counts) are
  delivered to consumer repos by `perk init`; audit design-doc universals for def-level vs
  spawn-level truth; scout lanes can return a confident false refutation (slash-glob `grep`,
  `worktree: none` parents run in `main`) — "Agent-def delivery", "Lane evidence pitfalls".
- The enabled native bridge supplies `contact_supervisor` without allowlist edits; `outputSchema`
  injects an engine-validated `structured_output` call, yet an engine-valid report is not always
  a completed assessment (`blocked` reclassifies to `lane-failed`); every wave spawn disables
  acceptance — "Supervisor-channel streaming", "Workflow structured output".
- A child's authorization is TWO booleans — the runner bit `PI_SUBAGENT_CHILD=1` + the constant
  packet `perk.parent-restrictions/1 = {readOnly: true}` — decoded fail-closed, latched per
  activation, composed into every gate observation; plan guidance rides the gate behind
  `isPlanGuidanceStage` + the runner fence — "Native child execution — the two-boolean policy".
- perk touches pi-subagents only through public surfaces; the installed-engine harnesses are
  deleted and the coverage reduction is accepted and named — "Engine-coupling posture".
- Historical correction blocks and landed-arc passages are records, not open work.

## `subagents.agentOverrides` — full overrides for builtins and (since 0.64) custom agents

`subagents.agentOverrides` takes two paths
(`.pi/npm/node_modules/pi-subagents/src/agents/agents.ts`), and since **0.64.0** both apply the
same full override set:

- **Builtins**: `applyBuiltinOverrides` — override fields displace unconditionally, with the
  bulk-disable/re-enable precedence in the next section.
- **Custom agents** (user/project/package sources): `applyCustomAgentOverrides` →
  `applyCustomAgentOverride`, which since 0.64.0 (#1796) applies the **full override set** — a
  settings override now DISPLACES a field the def's own frontmatter sets, `model` included
  (verified against the installed 0.64.x source). Scopes layer **user-then-project** (since
  0.54.0, #1348): the user override applies first, then the project override over the result —
  project fields win without dropping user-only fields.

Dated history: before 0.52, overrides reached builtins only; from 0.52 through 0.63 the
custom-agent path was a **frontmatter-sensitive fill** — an override never displaced a
frontmatter-set field (narrow exceptions: `description` and `disabled` always applied;
`model`/`tools` filled only when frontmatter had none) — and 0.64.0 removed the fill.

**Correction (kept as history):** a prior `shared/contracts.md` §8.3 note claimed the classifier
model is "overridable via `subagents.agentOverrides`." Wrong when made (overrides then reached
builtins only), and through 0.63 still effectively false for perk's agents (every perk def pins
`model:` in frontmatter and the fill never displaced it). Since 0.64.0 an override CAN displace a
perk def's model — but perk's sanctioned knob remains `[models.subagents]` + the workflow-level
`model` (spawn-time — wins over the def model however it was set); do not resurrect
`agentOverrides` as perk's mechanism.

## Builtins are OFF in every perk repo — and the re-enable precedence

pi-subagents' **builtin** agents are disabled in every perk repo via the managed
`subagents.disableBuiltins: true`, delivered by `_converge_subagents` (`src/perk/convergence/init/settings.py`).
perk borrows pi-subagents as the delegation *engine only* and ships its own `perk.*` defs, so the
builtins are model-facing noise everywhere — this is perk's posture, not a per-repo config knob
(there is no `.perk/config.toml` involvement; see `borrowed-packages.md` for why a borrowed
package's behavior must be converged, and `init-doctor.md` for the delta-gating this constant-desired
fragment forced).

**Re-enable precedence** (`applyBuiltinOverrides`, `.pi/npm/node_modules/pi-subagents/src/agents/agents.ts`):

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
public direct `{agent, task}` is a real top-level spawn shape again since the 0.49 restoration,
and a top-level `model` on such a call still works — the native single-child path consumes it
directly (`resolveEffectiveSubagentModel`) — the workflow-level-`model` knob guidance itself
stands).
`/pr-review`'s `run_pr_review_wave` tool reads `[models.subagents] pr-reviewer` from
`.perk/config.toml` (overlaid by `.perk/local.toml` for per-user override) and the wave module
applies it as the wave's workflow-level `model` default — **no committed-file churn**. (An
`agentOverrides` model can't displace the defs' frontmatter-pinned `model:` — see the
agentOverrides section — so the workflow-level `model` default, not an override map, is the
mechanism.)

*(Update at 0.64.0: an `agentOverrides` entry now CAN displace a frontmatter-pinned `model:` —
see the agentOverrides section — but the workflow-level `model` default is spawn-time and wins
over the def-level model however it was set, so it stays perk's mechanism.)*

Placement rule: a `[models.subagents]` key belongs beside a **code-owned spawn surface** only (a
wave module or flow tool that reads the key at execute time); an ad-hoc or hand-launched agent
rides its frontmatter `model:`/`fallbackModels:` instead — no config key.

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

## Def-level acceptance and completionGuard

Two separate def-level mechanisms govern child completion (verified against the installed 0.64.x
source):

- **Frontmatter `acceptance` is the def-level counter to acceptance auto-inference.** An agent
  def's `acceptance:` frontmatter becomes its `defaultAcceptance`, copied onto any launch that
  omits `acceptance` — an explicit call value always wins (`src/runs/foreground/subagent-executor.ts`).
  `level: "none"` requires a non-empty `reason` (`validateAcceptanceInput`,
  `src/runs/shared/acceptance.ts`). So a def can immunize its children against the auto-inferred
  acceptance contract without every spawn site restating the disable.
- **`completionGuard` is a separate mechanism** (`src/runs/shared/completion-guard.ts`): an
  implementation-shaped task on a mutation-capable child *expects* a mutation, and a child that
  completes without attempting one trips the guard; a mutation-expecting task on a child with NO
  mutation-capable tools is refused at launch. `bash` counts as mutation-capable (only the
  read-only builtin set — read/grep/find/ls and friends — doesn't), so a report-only analyst
  that carries `bash` for evidence-gathering rides the `completionGuard: false` escape, not a
  tools diet. `completionGuard` is a real frontmatter field (the parser reads the literal
  `"false"`); setting it `false` on the report profiles removes only the engine's *mutation*
  guard — the `structured_output` contract, perk's read-only floor, and the rubric prohibitions
  still enforce non-mutation.

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

Precedence (verified against the installed 0.64.x source — `resolveSubagentLaunchContext`,
`src/shared/fork-context.ts`): an explicit spawn `context` always wins; otherwise the configured
`defaultSubagentContext` (settings) beats the agent def's `defaultContext`; the fallback is
`fresh` (an implicit `fork` preference additionally requires a persisted parent session). So an
isolation-requiring fan-out passes `context: "fresh"` per spawn — a def-level default cannot
guarantee isolation against a configured fork preference.

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

For shared subagent-adjacent prompt fragments that are rendered on both planes, the wording must
remain byte-identical across TypeScript and Python, strictly pinned by reciprocal tests in both
suites (the pattern: paired literals asserted from `worker.test.ts` and
`test_worker_prompt_parity.py` against the same expected fragment). **Correction:** the original
instance — the address model clause (`ADDRESS_MODEL_CLAUSE` / `_ADDRESS_MODEL_CLAUSE`) — is
RETIRED: `review-classifier` is no longer a two-plane prompt subsystem (the
`classify_review_feedback` tool reads the model at execute time and no prompt carries a model
clause), so those constants are deleted; do not resurrect them. The pattern survives in the
remaining shared fragments (e.g. the linear plan-read substrings).

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
warm door**. It is dispatched **foreground** through the engine's structured delegation bridge,
never RPC/ReportWave. The orchestration that drives it lives in
`workflow/mergeability-and-conflict-resolution.md`.

## Agent-def delivery to consumer repos (the realized design)

perk's subagent defs — the `PERK_AGENTS` tuple (kept sorted), currently `adversarial-reviewer`,
`conflict-resolver`, `draft-reviewer`, `dream-analyst`, `dream-reducer`, `harvest-analyst`, `learn-analyst`,
`objective-explorer`, `pr-reviewer`, `review-classifier`, `scout` (`review-angle-selector` was
retired with `/pr-review-dynamic`, PR #2109) — reach
consumer repos via the Python wheel + `perk init`. This closed the former "known gap." (Don't
restate a hard count in prose — counts are drift magnets per
`workflow/doc-reconciliation.md`; `PERK_AGENTS` is the SSOT.)

### How pi-subagents discovers project agents

Discovery (`pi-subagents/src/agents/agents.ts`) is **recursive** over `<root>/.pi/agents` (+ legacy
`.agents`), and the runtime name is derived from **frontmatter** (`name` + `package`), **NOT the file
path** — so `.pi/agents/perk/<name>.md` with `package: perk` yields runtime name `perk.<name>`
identically to a top-level file (subdir placement is free). Installed npm packages ARE scanned
for **declared** agent dirs: `collectPackageSubagentPaths` reads the `package.json` keys
`pi-subagents.agents` / `pi.subagents.agents` (path arrays resolved against the package root)
across the project root itself, project/user `.pi/npm/node_modules/*`, settings-declared
packages, and the global npm root; hits load as `source: "package"` (lowest custom precedence in
`AGENT_SOURCE_PRIORITY`: builtin < package < user < project) with first-declaration-wins dedupe
by name, and custom `agentOverrides` apply to them. **Undeclared packages are still never
scanned**, and perk's own npm `package.json` declares no agent dirs (only `pi.extensions`) — so
the carrier remains the Python wheel + `perk init` materialization, not the npm package. The
"why" is now "perk declares none", not "structurally impossible"; switching to an npm-declared
agent dir is a design decision, explicitly not made.

**Discovery is live filesystem-based, not launch-time**: an agent def written to `.pi/agents/`
mid-session is immediately discoverable and usable by a same-session wave — no reload or restart
needed. This makes temporary, session-scoped agent defs viable (write the def, run the wave,
delete the def), but it also means their cleanup is on you (see the wave-residue note below).

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
`model`** on the one `subagent` workflowScript call — a default flowing onto every lane of
perk's own wave calls (all code-owned workflowScript spawns — perk's convention, not an
upstream constraint), single-child runs included (an `agentOverrides` model can't displace the
defs' frontmatter-pinned `model:` — see the agentOverrides section). The census has been followed
verbatim on real additions (most recently the agent since renamed `adversarial-reviewer`, added as
`guest-reviewer`) and worked cleanly — a **rename** walks the identical census (plus a `git mv` of
the source and a reconverge that prunes the old delivered def) — the only
thing that ever drifted was this doc's hard counts, hence the listing-without-a-count discipline.

**The prose layer the census guards don't cover.** Every cohort-wide invariant written in a design
doc must be audited for def-level vs spawn-level truth: a def with no launcher (a dev-only agent, a
def between delivery and its door) breaks any "every spawn adds X" universal, and `ReportWave` owns
`context: "fresh"` / `mission: false` / the acceptance disable **at spawn time**, so a def-level
claim about them is a category error. Coexistence/independence claims (the builtin `scout` beside
`perk.scout`) are characterized by actually flipping the builtin on and listing + spawning both —
not merely written down.

### A committed managed convergence

A `PERK_AGENTS` SSOT tuple drives a content convergence (`_converge_subagent_agents`) that delivers
each def **byte-for-byte** into the perk-owned `.pi/agents/perk/` subdir and **prunes stray `*.md`
inside that subdir** (perk owns the WHOLE subdir; it never touches anything outside it — e.g. a
hypothetical user-owned `.pi/agents/<mine>.md` is out of its reach). It computes the **identical change-list for `apply=True`/`apply=False`**
(the managed-convergence invariant) and is the auto-generated `subagent-agents` doctor check. There
is **no `self_repo` param** (unlike the skills sibling): the resolver works in both install modes, so
self-repo and consumers get byte-identical defs. Because `.pi/agents/perk/` is **committed
(tracked)**, linked worktrees inherit the defs via `git checkout` — **no worktree symlink mirror**
(contrast skills' `materialize_skills`; see `workflow/init-doctor.md` for the reusable contrast).

### Doctor

The `subagent-engine` enumeration moved from `.pi/agents/*.md` to `.pi/agents/perk/*.md` (still
informational; the `subagent-agents` convergence owns drift). The `[models.subagents]` config stays
**fixed-key** (the `PERK_AGENTS` set only) — it does **not** configure user agents (those set `model:`
in frontmatter; see `docs/user-docs/how-to/write-a-custom-subagent.md`).

### Parent-passed routing tokens are an injection surface

Any value the parent interpolates into a child's task that originates from repo/user-controlled
data (e.g. a lane id built from a directory name) needs **explicit untrusted-DATA coverage in the
agent def** AND **validate-or-fail-closed use**: the def instructs a byte-exact match against a
trusted manifest and an empty report on no-match — never improvising. The `harvest-analyst` def
(`agents/harvest-analyst.md`) is the precedent: its lane id is named an untrusted routing token,
used only to select the matching manifest lane byte-exact.

### Lane evidence pitfalls (scout waves)

Three traps observed in live `perk.scout` lanes (`docs/design/archive/scout-launcher-*`), each of
which produced a confident wrong answer rather than a failure:

- **The pi `grep` tool returns "No matches found" for a slash-containing glob** (`perk-*/SKILL.md`)
  against an absolute or prefixed path — use `**/…` or a bare filename glob. A lane trusted the
  empty result and reported a *false refutation* with `basis: "verified"`.
- **A `verified` basis can be wrong.** It records how the lane believes it looked, not that it
  looked correctly — re-read every `pointer` a lane returns before a plan relies on it, and treat a
  no-match search as "not found by that query", never as evidence of absence (the lane-side rule
  belongs in the def; routed as a follow-up).
- **A parent on a `worktree: none` stage runs in the MAIN checkout**, even when the door was invoked
  from a linked worktree (`workflow/cold-door-launch.md`). Briefs must name the target worktree by
  **absolute path** or every lane silently inspects `main` and reports on the wrong tree.

### The first repo-local agent-def namespace (`perk-dev`)

`.pi/agents/perk-dev/session-auditor.md` (frontmatter `package: perk-dev`) is the first agent def
living **outside `PERK_AGENTS`**: it is repo-local (never delivered to consumers), untouched by
the `.pi/agents/perk/` pruning convergence (which owns only that subdir), yet still config-keyed
via `[models.subagents]` (`session-auditor` — dev-only, dormant in consumer repos). Use this
namespace shape for future dev-only agents rather than growing the delivered set.

The former `perk-dev.analyst` was promoted into the delivered `perk.scout` (`agents/scout.md`, in
`PERK_AGENTS`) and retired without alias; `session-auditor` is the namespace's sole member.

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
(`extension/pi/v1/codeReview/automated.ts`) **defer** to it — **don't look there for review logic**. After
editing the source, **re-run `perk init`** to reconverge and commit **both** copies byte-identical
(the init-idempotency + doctor `subagent-agents` checks expect consistency). **Stale-path gotcha:**
the materialized copy is the `perk/`-namespaced `.pi/agents/perk/pr-reviewer.md`, **not** the
pre-namespace flat path directly under `.pi/agents/` that the skill once cited. When touching agent
docs, grep for any flat `.pi/agents/<name>.md` spelling — it is always stale.

### Two `perk init` worktree gotchas (reality, not aspiration)

- In a worktree where skills are already materialized, `perk init` **fails the `skills --sync`
  step** but prints `Converged before failure:` listing the agent copy as `updated` — the **agent
  reconvergence happens before the skills failure**, so it's **non-fatal for an agent-only edit**
  (confirm the agent diff is clean; don't chase the skills failure).
- `perk init` also creates the **gitignored** `.pi/perk.local.toml` — **stage only the intended
  files explicitly** (don't `git add -A`).

### Testing reality

The wheel-bundling + idempotency + doctor guards check **presence + consistency**, not content —
but the wave def↔schema lockstep tests (`extension/waves/draftReviewWave.test.ts`,
`adversarialReviewWave.test.ts`) regex-pin their defs' completion-protocol prose against the
in-code wave schema. So a pure prose rewrite keeps `just ci` green **except** for a wave-paired
def's pinned completion-protocol clauses.

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

Mechanics source-read in `pi-subagents/src/` (currency per the version-anchor convention above)
while wiring `/pr-review-terminal`'s live findings streaming — they dictate the only workable
parent loop shape:

- **The native supervisor bridge supplies `contact_supervisor` without widening agent defs** —
  `intercom/intercom-bridge.ts` appends it to explicit allowlists when the bridge is enabled.
  Bridge-off does not provide that capability; never infer delivery merely from a tool list.
  A read-only reviewer can stream without changes to its declared capabilities.
  `reason: "progress_update"` is **non-blocking** (returns "queued" immediately; requests capped
  at 64KB).

  A **decision-type** `contact_supervisor` request from a wave lane is a different animal: it is
  effectively unanswerable at parent-turn latency — two waves timed out at 0/5 covered while a
  lane awaited "is the run-all evidence available?", and every parent reply found no pending
  request. Treat a lane that needs a parent decision mid-run as a lane-design smell; reviewer
  prompts must classify parent-owned execution evidence (`run_ci` results, test runs, builds) as
  out of scope rather than asking for it (`agents/pr-reviewer.md` says so categorically).
- **Delivery is an injected message, nothing else** (`intercom/native-supervisor-channel.ts`):
  a parent-side poller (≤500ms) injects each request via
  `pi.sendMessage({customType: SUPERVISOR_REQUEST_MESSAGE_TYPE})` — since the v0.65.0
  native-session transition the `"subagent_supervisor_request"` literal lives in
  `intercom/supervisor-ui.ts` as that constant, imported by the channel file — with default
  `deliverAs: "steer"`, delivered **before the next LLM call** (i.e. when the current tool call
  returns), and **`triggerTurn: true` on every request**: an idle parent wakes (progress
  updates included). Progress updates **never enter the `pending` map** — there is no polling
  surface for them.
- **The `subagent_wait` alias was removed upstream (v0.61)** — the surviving wait tool is
  `bg_wait`, upstream-scoped to background work WITHOUT native completion notification
  (ordinary async runs notify natively; window expiry is a non-error `window_elapsed`), and
  perk does **not** adopt it. The held-turn `subagent_wait({ timeoutMs })` relay loop — wait
  expiry as the streaming cadence, queued injected messages delivering on each expiry return,
  the parent holding its turn open — is the **historical 0.52-era characterization**, not a
  current prescription or native-wake proof. Current guidance retains the launched workflow
  identity, ends the turn with Pi open, relays batches on native supervisor wakes, and collects
  only on matching native workflow completion (`"subagent-notify"`). Co-delivered progress
  reaches the sink before collection without a manufactured extra turn boundary. No child
  completion, unrelated notice, preview, or elapsed time authorizes reconciliation.
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
  **The completion notification does NOT carry authoritative per-child reports** — its text
  is a truncated return preview. Perk parents use the typed collect tools, never notification
  previews or manual `status.json` reads; aggregate retrieval is adapter-owned. **At 0.43 the cut went further: direct
  `{agent, task}` single-child execution was also removed** — `src/extension/public-execution.ts`
  rejects it with `Direct execution was removed. Use workflowScript: "return runs.run('main',
  { agent, task })".` — so `workflowScript` became, from 0.43, the **sole public execution
  surface, one-child runs included**. perk's four remaining direct-spawn guidance surfaces
  (`/address` classify,
  the objective-plan explorer, `/submit`'s conflict-resolver, `/learn`'s analyst fan-out) were
  converted accordingly at the time: an explicit-return one-child `runs.run` returning the
  compact `{key, ok, error, output}` projection (never the raw ChildResult — its `results`
  carries the full child metadata). **Correction:** the two read-only single-child flows
  (`/address` classify, the objective-plan explorer) have since migrated OFF model-authored
  scripts entirely too — they run as flow-scoped tools over the report-wave module
  (`classify_review_feedback` → `extension/waves/reviewClassifierWave.ts`;
  `explore_objective_node` → `extension/waves/objectiveExplorerWave.ts`), their report schemas
  now module constants (`REVIEW_CLASSIFIER_REPORT_SCHEMA` / `OBJECTIVE_EXPLORER_REPORT_SCHEMA`;
  the `prompts/common/output-schemas/` include partials are deleted). The motivating failure was
  a live schema mistranscription: the parent nested `counts` inside `discussion_comments` in the
  hand-copied `outputSchema`, so under `additionalProperties: false` every child payload was
  rejected and the run died as `Missing structured_output call`. `conflict-resolver` deliberately
  stays a guidance-instructed one-child `runs.run` and untyped — its child output is a merge
  resolution, not a report. `/learn`'s analyst fan-out likewise rides the report-wave module
  (`extension/learning/analystWave.ts`, installed by `extension/pi/v1/learning/learn.ts`, →
  `runReportWave`, behind `run_learn_wave`) — an async
  RPC-spawned all-settled `runs.all` whose script the module renders, with engine-validated
  structured reports instead of fenced JSON. **Update:**
  pi-subagents 0.49.0 (#1059) RESTORED public direct `{agent, task}` single-child execution. It
  is a **native structured single-child mode, not a generated workflowScript conversion**:
  `normalizePublicSubagentExecution` validates and passes `{agent, task}` through (trimming
  `agent`, defaulting `output: true`), and the executor dispatches it as mode `single`; public
  structured single-child calls stay synchronous when `asyncByDefault: false` and `async` is
  omitted (0.52.0 #1257). So `workflowScript` remains the sole MULTI-agent orchestration surface
  while direct `{agent, task}` is the idiomatic one-child shape (upstream's own tool description
  teaches this split). perk's code-owned wave spawns
  are unaffected; `conflict-resolver`'s explicit-return one-child workflowScript stays
  deliberate (perk controls the compact `{key, ok, error, output}` projection).

### RPC-spawned async waves stream identically (the settled verdict)

An RPC-spawned async workflowScript wave delivers supervisor-channel progress updates to the
parent session **identically** to a model-called wave, **by construction**: the v1 RPC `spawn` is
a thin envelope over the same executor with the parent session's context, and parent-side
delivery is **session-scoped file polling** (matching `orchestratorSessionId` against the current
session), never run-scoped. Supporting facts:

- **Async workflows run in-process in the parent pi** — the workflow status carries
  `pid: process.pid` (re-verified at 0.65.1: the literal sits on the `mode: "workflow"` status
  record in `src/runs/foreground/subagent-executor.ts`); only single/chain runs get the
  detached runner. Consequence: an "async" wave dies with the parent pi process — fine for
  session-scoped surfaces, disqualifying for anything that must outlive the session.
- **The child launch protocol is typed runtime config, not env stamps (since the v0.65.0
  native-session transition)**: `orchestratorSessionId` + `supervisorChannelDir` are fields of
  `src/runs/shared/child-runtime-config.ts`, stamped by `src/runs/shared/child-launch.ts` —
  the old `PI_SUBAGENT_ORCHESTRATOR_SESSION_ID`/`PI_SUBAGENT_SUPERVISOR_CHANNEL_DIR` env
  stamps and their `pi-args.ts` carrier are deleted.
- **Omitted child `async` honors the engine defaults** — globally background — while the
  workflow still AWAITS the async child: `asyncOmitted` spreads `workflowAwaitAsync: true` in
  `src/runs/foreground/subagent-executor.ts` (the v0.65.1 repair). The former
  "workflow children default to foreground" rule (`async: params.async ?? false` in
  `scripted-workflow.ts`) is gone. The original 0.65.1 baseline failed background child launch
  because host peers were missing (`docs/design/archive/pi-subagents-native-baseline-dogfood.md`).
  The repo-local five-package 0.85.1 dev composition now passes alias resolution and a real
  background smoke at `52c4fde5` (2026-09-05); see
  `docs/design/archive/pi-subagents-native-streaming-dogfood.md`. This resolves that tested
  development-host blocker only, not consumer/global compatibility or streaming acceptance.
  Production launch parameters and pi-subagents' unpinned policy are unchanged.
- **The one silent killer is config**: `subagents.intercomBridge.mode: "off"` — or
  `"fork-only"`, since perk's wave children run fresh-context — suppresses the channel-dir stamp
  and can leave only final reports. Reviewer protocol now requires `streamed: false` and factual
  `fyi` on unavailable streaming; collection visibly warns when such a lane has findings. Now guarded by the report-only
  `subagent-bridge-config` doctor check (`src/perk/convergence/doctor/checks.py`; both scopes —
  project `.pi/settings.json` + the user scope, i.e. `settings.json` inside the
  **launch-precedence agent dir** (`src/perk/substrate/config.py::launch_pi_agent_dir`:
  `PI_CODING_AGENT_DIR` → main-checkout `[pi] agent_dir` → `~/.pi/agent`), labeled by absolute
  path in the report, never `Path.home()` at check time — warn-never-fail, no `--fix`; perk
  deliberately does NOT reimplement pi's cross-scope merge, so either scope's explicit-off
  warns).
- **The dead fallback is dead**: code-owned spawn *without* live streaming is not to be built —
  the binding posture is RPC spawn + native-wake provisional relay, with explicit completion-only
  disclosure when streaming is unavailable (no replacement scheduler or polling tool).

### Validation posture: the streaming protocol is still mostly prompt-followed

The fan-out and report retrieval are code now (the `start_review_wave`/`collect_review_wave`
tool pair over the report-wave module — no model-authored `workflowScript`, no `status.json`
read-back), but the streaming protocol around them is **model-followed prompt text**: the agent
def's progress-update step, the native-wake parent relay, and the incremental path+line dedupe
ledger (terminal; the browser's ledger is tool-owned in `push_annotations`) still require live
prompt-following evidence. Required `streamed` is child-reported successful nonempty submission,
not a sink-delivery acknowledgement. False/no findings is neutral; false/findings is a visible
completion-only warning without changing coverage. Typed tests cover disclosure, grace/drain and
mid-flight push capability, not autonomous model behavior. The native protocol's separate live
record is `docs/design/archive/pi-subagents-native-streaming-dogfood.md`.

**Historical held-turn observations — not a current prescription or native-wake proof.**
The following four axes were observed across the three streaming browser doors
(2026-08-10; the per-leg timestamps and verbatim tool results are in
`docs/design/archive/streaming-doors-dogfood.md`):

- (a) do batches actually deliver on each wait-expiry (the steer-on-tool-return mechanic) —
  **confirmed**: every leg's first batch injected at the exact 30s-wait expiry, later batches
  also on `push_annotations` tool-call returns;
- (b) does the dedupe ledger hold across a long triage conversation — **confirmed** in both
  modes (review `path`+`line`, plan `comment:<phrase>`), across multi-minute windows and the
  reconcile boundary;
- (c) is the 30s cadence right (too short → chatty loop; too long → stale findings) —
  **confirmed with a characterization**: every wave spent exactly two empty expiries
  (~60–90s of child context-reading) before the first batch, then no stale backlog;
- (d) each leg's launch→wait→push→collect ran as one held turn. That observation did not test
  turn-yielding native delivery and cannot establish that a parent must hold its turn open.

**Upstream-drift caveat:** the load-bearing delivery mechanics above are **source-read-derived**
at the constant-pinned version (covering the supervisor-channel delivery chain, the v1 RPC
seam, the workflow-structured-output mechanics, and public execution) — an upstream change to
the supervisor-channel or workflow contract invalidates the loop shape silently; re-verify on
pi-subagents bumps (the grouped `tasks[]` removal across upstream v0.41.0–v0.42.1 is exactly
this failure mode: it live-broke both review doors with no test tripping). Since 0.51.0 the transport is platform-split —
watcher platforms (e.g. linux) use per-request-dir + root fs-watchers plus a 5s safety poller,
with a ≤500ms poll fallback on watcher failure; darwin uses only a demand-gated ≤500ms poller;
win32 an always-on ≤500ms poller — these are upstream delivery internals, not parent polling prescriptions. The
doctor `subagent-compat` check is a **version tripwire**, nothing more: `info` when the package is
absent ("compatibility not evaluated"), `warn` when its `package.json` version is unreadable OR
differs from `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION`, `ok` at the verified version. It **never reads a
borrowed package's source** — the old marker-presence probe table (`_SUBAGENT_COMPAT_PROBES`), the
`validateWorkflowScript` behavior arm over a shared representative wave script, and every other
installed-tree read are gone with the public-surfaces-only posture (below). The replacement early-drift
signal is that `warn` plus the manual re-verify how-to (`docs/developers/pi-subagents-reverify.md`):
the deeper wait/streaming mechanics are source-read-derived at the verified version and simply
unverified at any other. One decode detail worth knowing: `_installed_subagents_version` narrows to a
**non-empty string**, so a wrong-typed `{"version": 123}` takes the *unreadable* arm, never the
*mismatch* arm — a wrong-typed field is an unreadable manifest, not a version.

The repeatable success pattern: when a feature depends on subtle dependency runtime behavior, the
**planning session** should read the dependency source and pre-digest the mechanics into the plan
body — the implementation had zero dead ends because discovery wasn't left to the implementer.

## Workflow structured output (`outputSchema` → engine-validated per-lane reports)

The `/pr-review` report wave rides these mechanics (now module-run: `extension/waves/prReviewWave.ts`
over the v1 RPC via the flow-scoped `run_pr_review_wave` tool), source-read in
`.pi/npm/node_modules/pi-subagents/src/` (currency per the version-anchor convention; same
upstream-drift caveat as above — re-verify on bumps). The two single-child flows
(`/address` classify, the objective-plan explorer) ride the same mechanics through their own
single-lane wave entrypoints (`classify_review_feedback` / `explore_objective_node` — the
schemas are module constants, nothing prompt-transcribed):

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
- **Spawn-time `output` is the persistence mechanism.** Whether/where a child's final output is
  saved is a *launch* concern (`output` on the spawn; single-child runs default `output: true`),
  so agent defs never restate persistence in prose. Combined `outputSchema` + `output`, the
  child's contract is engine-injected: the `structured_output` call must be the FINAL action,
  with no prose-only completion ("Do not rely on prose-only completion" —
  `src/runs/shared/subagent-prompt-runtime.ts`; verified against the installed 0.64.x source).
- **A foreground workflow (`async: false`) returns the full aggregate inline**
  (`runs/foreground/subagent-executor.ts`): the tool result carries `Return:` + the full
  JSON-serialized `workflow.value` with NO truncation — the ~1000-char preview caveat above
  applies to the ASYNC completion notification only. No `subagent_wait` loop, no `status.json`
  retrieval; foreground workflows default to a 30-minute timeout.
- **Acceptance can't poison completeness**: with `acceptance` omitted (the `subagent` tool
  description's own rule for reviewer/read-only calls), an acceptance-heuristic wobble cannot flip
  a lane's `ok` — the "report-only children trip `acceptance: auto`" hazard (below) cannot discard
  a schema-valid report. **But omission is not enough against the distinct PROMPT-COMPETITION
  hazard** (since 0.46.0; `src/runs/foreground/subagent-executor.ts` + `src/runs/shared/acceptance.ts`):
  with `acceptance` absent, pi-subagents auto-infers a generic acceptance contract for
  reviewer/analyst-named or read-only children and injects a fenced `acceptance-report`
  completion instruction into the child's input — a COMPETING completion contract observed
  steering a child into acceptance-report-shaped `structured_output` attempts (schema-rejected,
  run failed). perk's report-wave module therefore passes the explicit disable
  `acceptance: {level: "none", reason}` on EVERY wave spawn (`WAVE_ACCEPTANCE` in
  `extension/waves/transport.ts` — the sanctioned shape: `explicitAcceptanceCanDisable`;
  `formatAcceptancePrompt` emits nothing at level none); delivery to each lane child rides the
  workflow-defaults spread (`prepareWorkflowLaunchParams`). Module-wide, no opt-out; the doctor
  `subagent-compat` version `warn` is the drift tripwire (no probe reads the engine's source).

## The inherited read-only gate vs the engine's child-side tools

A spawned child is **stage-unscoped** (adopt never impersonates) yet still **inherits the
parent's read-only gate** via the consumed-handoff adopt arm (env `PERK_RUN_ID` + a consumed
handoff → the adopt arm carries `mode: read-only`). pi-subagents injects its child-side engine
tools (`structured_output`, `contact_supervisor`) through the child prompt runtime/bridge at extension **load time** —
before perk's `session_start` gate sync — so a gate sync that omits them deactivates them: an
`outputSchema` child then runs its full exploration and fails with `structuredOutputFailed`,
physically unable to make the engine-REQUIRED `structured_output` completion call.

- **Landed fix shape:** `SUBAGENT_CHILD_TOOLS` carried in `READ_ONLY_TOOLS`
  (`extension/substrate/toolGating.ts`; the static-name inert-when-unregistered posture),
  deliberately in **neither** `PERK_TOOLS` nor `BORROWED_TOOLS` — children are stage-unscoped,
  so gate membership is their only governance surface. The obsolete wait name is retired and
  no replacement wait tool is adopted; native review delivery needs neither.
- **Debugging heuristic:** a "missing `structured_output` tool" in a child is a **composition**
  defect — trace (a) the launch allowlist injection (`resolvePiLaunchToolPlan` unions
  `structured_output` when `outputSchema` is set), (b) ambient-extension loading in the child
  (`disableAmbientExtensions` keys off `extensions:` in the agent def, not `tools:`), (c) perk's
  gate timing (load-time registration vs `session_start` sync). Never blame the agent def's
  `tools:` frontmatter — the engine unions the tool regardless.
- **Read-only prose is not a sandbox.** An agent def's mutation prohibitions must be categorical
  ("never edit, never push") — never softened with an explicit-task exception ("unless the task
  says otherwise"): task text is data-adjacent, and a poisoned task would satisfy the exception.

## Native child execution — the two-boolean policy (background reports, foreground writer)

`docs/design/pi-subagents-child-execution-policy.md` is the **binding record**; this section is the
map, not a copy. Two booleans decide everything a perk child may do:

- **The runner bit** — `PI_SUBAGENT_CHILD === "1"`, read at every `session_start`
  (`extension/substrate/childRestrictions.ts::isRunnerChild`). pi-subagents stamps it on every
  background (runner-hosted) child — the only kind of child in which perk's extension activates.
- **The report restriction packet** — the constant `extensionBindings`
  `{"perk.parent-restrictions/1": {readOnly: true}}` (`extension/waves/reportWave.ts::
  REPORT_CHILD_RESTRICTIONS`), embedded on every rendered report child together with
  `worktree: false` (caller-checkout placement so the plan-ref-dependent readers keep working).
  Nothing is sampled from the parent gate, handoff, task or assignment data.

`decodeReadOnlyFloor(runner, raw)` is the consumer: no packet ⇒ no floor (the
delegation-dispatched writer's case); malformed — invalid JSON, a non-object envelope, any
`perk.parent-restrictions/` key other than exactly `/1`, or `/1` with anything but exactly
`{readOnly: boolean}` — ⇒ **floor (fail closed)**; valid ⇒ the boolean. A non-runner never gets a
floor. `extension/index.ts` reads both at the top of every `session_start` and **latches** the floor
for the activation (a re-emitted `session_start`, a gate `exit()`, or a `session_tree` navigation
cannot clear it); it composes into `toolGating.ts` as `isActive = active || hasFloor()` plus the
all-names `tool_call` backstop, and a throwing floor supplier is restrictive for that observation.

**The JSON-boundary gotcha:** "exactly one own key" ≠ "the expected key". The decoder asserts the
named key with `Object.hasOwn` *before* honoring the value — a polluted `Object.prototype.readOnly`
would otherwise have satisfied a `keys.length === 1 && value.readOnly === false` check and un-floored
the child. Any decoder that reads a named property off a parsed-JSON object should do the same.

**What the two booleans replaced** (all deleted — do not look for them): the advisory
`<active_agent name="…"/>` system-prompt prefix parser and `childIdentity.ts`, the
physical-session-key binding (`nativeSessionKey.ts`), the sampled `parentReadOnly` snapshot supplier
with its `unavailable` capture arm, `ReportWaveRequest.execution`, the six-reason envelope
classification, and the ten-name report-only scratch census (every perk report child is a runner
child — the runner bit IS the census).

**Runner children provision no scratch and receive no authoring guidance — the gate-riding model.**
Plan guidance rides the read-only gate behind ONE predicate,
`extension/pi/v1/contextInjection.ts::isPlanGuidanceStage` over `PLAN_GUIDANCE_EXCLUDED_STAGES`
(stages another authoring context owns, plus read-only stages that author nothing), fenced by
`installInjectedContext`'s `runnerChild: () => boolean` supplier — no `plan_authoring` bit, no
eligibility module. Two lessons from wiring it: when ONE fence protects many call sites, prove the
real composition-root wiring end-to-end at least once (a constant `() => false` supplier at any site
compiles and passes every unit test); and pin set members directly rather than through a filtered
iteration — the read-write `OBJECTIVE_SAVE_STAGE` exclusion is invisible to a test that iterates
only the read-only registry stages.

**Execution profile (one remains):** child execution mode is orthogonal to workflow scheduling —
an omitted child `async` under the engine's `workflowAwaitAsync: true` selects *background*; an
explicit child `async: true` is *detached launch*. All report roles run background (definition-owned
`async: true`, child calls OMIT `async`); the writer (`conflict-resolver`) runs foreground through
the delegation bridge with `async: false` and the worktree as the request's typed `cwd` — it has
**no perk activation** (foreground children have no ambient discovery) and receives no packet, so
it is floor-less by construction. Every role sets `inheritGlobalContext: false` and OMITS both
`extensions` and `subagentOnlyExtensions` (an empty array ≠ omitted). Test convention: assert a
**closed census independent of `PERK_AGENTS`**; the repo-local `perk-dev.session-auditor` lives
outside the tuple and is tested separately.

Bounded posture: not an OS sandbox, not authentication between malicious host extensions; a manual
`subagent` call is outside the channel; losing the runner env across a `/reload` is unsupported.

## The v1 extension RPC seam (`extension/waves/reportWave.ts` is the consumer)

pi-subagents exposes an extension-to-extension RPC bridge on pi's in-process event bus, and
perk's report-wave module (`extension/waves/reportWave.ts` + `rpcAdapter.ts`) launches report
waves through it — the mechanics below are source-read in
`.pi/npm/node_modules/pi-subagents/src/extension/rpc.ts` (same upstream-drift caveat: re-verify
the adapter on every pi-subagents bump; the doctor `subagent-compat` version `warn` is the only
automated tripwire — nothing reads `rpc.ts`):

- **The envelope**: requests arrive on `subagents:rpc:v1:request` as
  `{version: 1, requestId, method, params?, source?}`; the reply is emitted once on
  `subagents:rpc:v1:reply:<requestId>` as `{…, success: true, data}` or
  `{…, success: false, error: {code, message}}`. Methods: `ping`, `status`, `spawn`, `steer`,
  `interrupt`, `stop`, `resume`.
- **`ping` is the capability check** — it works even with no active session context and returns
  `{methods[], capabilities: {asyncSpawn: true, …}, events: {…, asyncComplete}, session}`.
  `events.asyncComplete` is the ADVERTISED async-complete channel name (currently
  `"subagent:async-complete"`); perk's adapter takes it from ping rather than pinning it.
- **RPC `spawn` is async-only** (`async: false` ⇒ `invalid_params`); params go through
  `normalizePublicSubagentExecution`, which since 0.49 ACCEPTS a direct `{agent, task}` —
  normalized as structured single-child execution, never rejected (a prior "rejected" claim
  here was stale). perk's adapter always sends workflowScript, so nothing perk-side changes.
  The success `data.details` carries `asyncId` + `asyncDir` identifying the detached run.
- **The async-complete event** payload spreads the result-file data plus `runId`/`triggerTurn`;
  match a spawned run via `asyncDir` (fall back to `id` — both optional, at least one present).
  Since 0.45.0 the payload also carries a normalized per-child `results` array (child `runId`,
  `success`, `outputState`, artifact paths), which perk's `rpcAdapter` normalizes into
  output-free receipt children (`output`/`summary`/`structuredOutput` never copied; malformed
  rows dropped). At installed 0.66.0 (source-read — source/offline corroborated, not the
  verified baseline) `results[].agent` is the **agent name**; the workflow assignment identity
  rides `workflowChildren.children[].childId`, correlated by the unique child `runId` plus the
  enclosing workflow run identity (`extension/waves/rpcAdapter.ts` header comment). A
  present-but-malformed, mismatched, or ambiguous inventory **withholds** correlation; only
  inventory-absent legacy payloads fall back to the overloaded `agent` mapping. Receipts stay
  output-free telemetry — missing correlation changes neither report coverage nor posting
  authority; `status.json.workflow.value` remains the report source. The discovery shape: a
  live receipt keyed `perk.pr-reviewer` where the assignment key was `protected`. And
  the historical `subagent_wait` surfaced slim `details.completions` (identity/artifact trail — never
  output; that is historical wait-tool behavior, not the current parent collection protocol).
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
  per-request reply subscriptions are cleanly disposed. The plannotator plan-review bridge now
  rides the same mechanic: it disposes a per-review `plannotator:review-result` listener via
  the unsubscribe `EventBus.on` returns (`requestPlannotatorPlanReview` in
  `extension/pi/v1/providers/plannotator.ts`; `createPlannotatorBridge` is its thin
  wrapper).

## Engine-coupling posture — public surfaces only

perk reaches pi-subagents only through **public surfaces**: the v1 RPC envelope, the delegation
events, agent-def frontmatter, and the engine's public package exports. The installed-engine
harnesses that loaded `.pi/npm/node_modules/pi-subagents/src/**` through a replacement jiti loader
(scripted native children, the plan-bound review and child-execution compat suites, the shared
fixture) are **deleted** — they proved mechanisms that no longer exist and coupled `just ci` to an
unpinned package's private tree. Two guards keep the posture honest:

- `extension/bareImportGuard.test.ts` — `pi-subagents` is not an allowed bare import; the versioned
  envelope literals are perk module constants (`extension/waves/rpcAdapter.ts`).
- `extension/installedPackageGuard.test.ts` — no extension source spells a path into
  `.pi/npm/node_modules/` except Ponytail's manifest-declared preflight root. The guard matches the
  **whole path token** and asserts **equality** with the one sanctioned root: a prefix-strip residue
  check would have admitted a prefix-matching fork of that root (`…/ponytail-evil`), so the test
  carries a synthetic prefix-match control that must NOT be classified as the sanctioned root.

**The accepted coverage reduction, stated plainly:** there is no automated engine-level proof that
`completionGuard: false` still completes a report-only lane, that the runner stamps
`PI_SUBAGENT_CHILD=1`, or that `extensionBindings` reaches the child env; `run_ci` will not catch an
upstream semantics change in any of these. The mitigations are the `subagent-compat` version `warn`
(above), the fake-RPC composition proofs (`workflow/report-waves.md` § "Test machinery"), and — as the
re-verify step on every version bump — a live report wave from a read-write session with the
per-child artifacts inspected (`docs/developers/pi-subagents-reverify.md`).

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
- **The always-present usage surface is the per-child artifact set.** Since 0.66.0 it lives under
  the **pi session directory**, not the cwd:
  `<pi session dir>/subagent-artifacts/<runId>_<agent>_{input,meta,output,transcript}.*` — no
  `_<i>` index, no `.pi-subagents/` directory in the checkout. Assistant records in the transcript
  carry per-message `usage` (`input`/`cacheRead`/`cacheWrite`); `_meta.json` carries aggregate
  usage and model but **no duration** — `status.json`'s `steps[0].durationMs` is the timing source.
- Measured through that surface: back-to-back spawns of the same agent show spawn-time
  **cross-process provider-cache prefix affinity** — later spawns read the shared agent prefix as
  `cacheRead` on their first assistant message.
- *(Dated history.)* The SDK-level in-process child was deleted with the stage-execution
  confinement (PR #2100); while it existed it was structurally unobservable live — in-memory
  session manager, no production call sites.
- **Report-only children can trip the `acceptance: auto` heuristic** ("no edits made") despite
  returning a well-formed report — the report is still usable; don't discard it on that signal.

## Wave artifact cleanup — the receipt is an identity trail, not an inventory

Two cleanup traps for anything that sweeps up after a wave:

- **A wave receipt is an identity trail, not a complete artifact inventory.** Since pi-subagents
  0.45.2, `children[].artifactPaths` names child session JSONLs under the **parent session store**,
  while the metadata/transcript/input/output set + structured-output captures live **separately**,
  run-id-keyed (since 0.66.0 under `<pi session dir>/subagent-artifacts/`; earlier under a cwd
  `.pi-subagents/artifacts/`). Exact cleanup derives BOTH sets, validates every resolved path
  against approved roots, and deletes only that union — never treat one receipt field as
  exhaustive, and never glob-delete.
- **Temporary-agent wave residue blocks submit.** A successful wave can leave an untracked
  `.pi/subagents/` runtime directory that the repo's ignore rules (`/.pi-subagents/`) don't cover.
  Wave cleanup = delete the temp agent def AND sweep the runtime artifacts, then check
  `git status` — an unswept runtime dir dirties the tree and blocks the submit gate.

## Residual

The Python-parsed `[models.subagents]` keys `pr-reviewer`, `review-classifier`, and
`objective-explorer` (`src/perk/substrate/config.py`) are parsed-but-unused on the Python plane
today (the TS flow tools consume them at execute time — no cold twins). (A prior "no workflow-state record of a `/pr-review`" note here was stale:
the `post_pr_review` tool turn + the `last_pr_review` record have existed since the #660 reshape.)

## Sources

- GitHub Pull Request Reviews API: `POST /repos/{owner}/{repo}/pulls/{n}/reviews` (the `event` /
  `comments[].line` shape) and `POST /repos/{owner}/{repo}/issues/{n}/comments` (the comment
  fallback). The 422-on-out-of-diff-line behavior is the documented reason for the fallback.

## Cross-references

- `extension/pi/v1/codeReview/automated.ts` — `prReviewGuidance` (judgment-bearing inputs only — the guidance no longer carries wave mechanics), `installAutomatedReviewBindings` (the flow-scoped `run_pr_review_wave` tool + the `post_pr_review` clean guard); defers the review rubric to the agent prompt
- `extension/waves/reportWave.ts` (+ `rpcAdapter.ts`; the first-class test double is `extension/testing/memoryAdapter.ts`) — the Perk-owned report-wave module over the v1 RPC seam; `/pr-review` rides it via `extension/waves/prReviewWave.ts` (`PR_REVIEW_REPORT_SCHEMA`, `runPrReviewWave` — the bounded-retry entrypoint behind `run_pr_review_wave`)
- `docs/learned/workflow/report-waves.md` — the perk-side report-wave module doc (flow migrations, lane semantics, guard state, wave test machinery); this doc keeps the upstream mechanics
- `docs/learned/workflow/mergeability-and-conflict-resolution.md` — the `/submit` orchestration that drives the `conflict-resolver` agent
- `extension/pi/v1/delivery/conflictResolverEngine.ts` — the foreground structured-delegation dispatch the writer role rides
- `extension/substrate/childRestrictions.ts` — `isRunnerChild` + `decodeReadOnlyFloor` (the two booleans' consumer)
- `docs/design/pi-subagents-child-execution-policy.md` — the binding record for the two-boolean child policy
- `extension/pi/v1/contextInjection.ts` — `isPlanGuidanceStage` + the `runnerChild` fence (the gate-riding model)
- `extension/installedPackageGuard.test.ts` / `extension/bareImportGuard.test.ts` — the public-surfaces-only guards
- `extension/waves/scoutWave.ts` / `extension/pi/v1/scoutWave.ts` — the `perk.scout` wave mechanism + installer (`run_scout_wave`)
- `docs/design/archive/scout-launcher-*` — the scout launcher gate record (lane evidence pitfalls)
- `src/perk/convergence/doctor/checks.py` — `_subagent_compat_check` (version tripwire), `_subagent_host_tools_check` (the 0.67.0 range gate)
- `agents/*.md` — the SSOT agent-def sources (delivered into `.pi/agents/perk/` by `perk init`); `agents/pr-reviewer.md` carries the entire reviewer rubric
- `skills/perk-pr-review/SKILL.md` — the orchestration skill that defers to the agent prompt (not where review logic lives)
- `extension/waves/reviewClassifierWave.ts` / `extension/waves/objectiveExplorerWave.ts` — the single-lane wave entrypoints (schema SSOT constants) behind the flow-scoped `classify_review_feedback` / `explore_objective_node` tools
- `src/perk/convergence/init/agents.py` — `PERK_AGENTS`, `_converge_subagent_agents` (the committed managed convergence)
- `docs/learned/workflow/init-doctor.md` — the committed-convergence-vs-symlink-mirror contrast
- `docs/user-docs/how-to/write-a-custom-subagent.md` — user agents set `model:` in frontmatter (the fixed-key `[models.subagents]` boundary)
- `src/perk/cli/commands/pr/review_post_cmd.py` — the canonical Python mutation (D1)
- `shared/contracts.md` §8.3 — the corrected `agentOverrides` note, the agent-def delivery design, + workflow-state schema
- `docs/learned/workflow/warm-door-commands.md` — the driving-command shape `/pr-review` departs from
- `docs/learned/workflow/skill-bindings.md` — the `command:<id>` binding checklist (`/pr-review` is one)
- the `pi-subagents` skill — single-agent, scripted-workflow (`workflowScript`), async, and forked-context delegation
