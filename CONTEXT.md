# perk

The plan-oriented agent workflow: a Python CLI (the session exterior) and a Pi extension (the
session interior) drive written, reviewed, durable plans through a staged spine.

## Language

**Gist**:
A rough, problem-space-focused statement of intent ("something we would likely want to do")
tracked in the issue backend — upstream of both plans and objectives, carrying no implementation
detail.
_Avoid_: idea, note, ticket, seed

**Scope** (of a gist):
A gist's intended consumption tier — `plan` (a bounded, single-plan-sized intent) or `objective`
(a long-running, multi-plan-sized goal). A routing hint for the adoption doors: a storage
discriminator on Linear (objective scope stores the gist as a project), a header hint elsewhere.
_Avoid_: kind, type, size

### Model-facing prose

**Prose unit**:
The smallest named behavior-shaping fragment that perk treats as one reviewable identity, such as
a template body, Markdown section, tool description, or injected guidance block.
_Avoid_: prompt file, sentence, copy block

**Session shape**:
A concrete delivery variant whose model context differs from its siblings, such as a cold, warm,
headless, ambient, or subagent path through the same capability.
_Avoid_: stage, door when the delivery variant is what matters

**Prompt assembly**:
The ordered prose units and external context boundaries that shape one session shape under a named
scenario.
_Avoid_: full prompt, transcript, concatenated string

**Prompt concern**:
A recurring behavioral instruction with one canonical carrier and explicitly related prose units.
_Avoid_: duplicated phrase, tag, topic

**Agent scratch**:
A run-owned, disposable directory for non-authoritative command and model intermediate files,
distinct from pointer-validated session data and host-global temporary space; never provisioned
in a runner child.
_Avoid_: session data, evidence store, temp directory

**Runner child**:
A pi-subagents background child (`PI_SUBAGENT_CHILD=1`), the only kind in which perk's extension
activates as a child; every perk report child is one.
_Avoid_: native child, report identity, `<active_agent>` name

**Report restriction packet**:
The constant `perk.parent-restrictions/1 = {readOnly: true}` binding perk's `ReportWave` stamps on
every report child; with the runner bit it is the whole authorization input for the child's
read-only floor.
_Avoid_: parent-restriction snapshot, captured parent gate, caller-read-only policy

**Read-only floor**:
The activation-latched restriction a runner child derives from the packet; it composes into the
tool gate and cannot be cleared by gate exit, tree navigation or a same-activation restart.
_Avoid_: child mode, inherited mode

### Tool gating

**Plan mode**:
The toggleable read-only authoring mode a session enters through `/plan`, `--plan` or a warm plan
factory; a `mode`, never a recorded `stage`. A stage-less session in plan mode resolves to the
`plan` stage for plan guidance and skill-binding delivery (`stage:plan`); a runner child never
counts.
_Avoid_: plan stage (for the toggle), warm plan session, stage-less plan

**Transition result**:
The typed outcome of a gate `enter`/`exit`/`syncFromState` (`GateTransition`): *applied*,
*restricted* (the runner restriction floor kept the gate on) or *failed* (the mode append or the
tool install threw — fail-closed), each carrying the access it left in force. Callers render
it, never their intent; `gateExited` is derived from it (true only for an applied read-write
release).
_Avoid_: gate outcome, exit flag, `gateExited` (as the transition itself)

**Tool catalog**:
The process-wide record of every perk tool and its policy descriptor, filled by the one registration
seam `registerPerkTool`; every gate and stage view, each tool's Pi exposure metadata, the read-only
context's writer list and the golden tool matrix (`shared/fixtures/tool-matrix.json`) derive from it.
_Avoid_: PERK_TOOLS, perk tool list, tool census (for perk's own tools)

**Policy descriptor**:
A perk tool's registration-time record — the stages it belongs to, its gate posture (`allowed`,
`blocked`, or a **carve-out** naming its one bounded write), whether it is mode-over-stage, its
kind (`terminal` / `interactive` / `orchestration` / `query` / `action`, plus `host` reserved for
the loadout host; the first three and `host` are declared model-only, as is every carve-out),
whether it is a
discovery-pilot family member (`declared: deferred`), and — for `kind: query` only — its `result`:
the success details' schema. The tool's Pi metadata
(`exposure`, `annotations`, a query's `outputSchema`) is derived from it, never hand-set.
_Avoid_: tool config, tool metadata, tool flags

**Bounded writer**:
A perk tool whose gate posture is a carve-out — its one sanctioned write while read-only
(`plan_draft`, `objective_draft`, `objective_refinement_draft`, `objective_node`, `gist_draft`).
Registered model-only: declared to the model and called directly, but never a member of a codemode
script's `tools` and never reachable through `ctx.executeTool` — so Pi's codemode `only` mode,
which hides only direct tools, cannot take one from the model, which is why `only` can lift.
_Avoid_: draft tool (a gate-blocked save is not one), sanctioned writer

**Structured result**:
The Pi-facing shape the registration seam derives on every perk tool result: `structuredContent`
(the result's `details`) and `isError` (forced when `details.ok === false`, else the tool's own
flag). Programmatic callers — a nested `ctx.executeTool`, a codemode script — read it; only
`kind: query` tools declare its schema (`outputSchema`, composed from the descriptor's `result`),
so only queries hand a script a structured value.
_Avoid_: structured details, typed result, output schema (for the result itself)

**Gate-eligible query**:
A `kind: query` perk tool whose descriptor is `gated: "allowed"`, so the read-only gate admits it
in every landing it is staged in — today exactly `objective_stack_status` (the worktree family
plus the read-only planning/refinement stages `plan`, `objective-plan`, `objective-refine`).
"Read-only" is the gate's guarantee — no working-tree, index, local-branch or remote mutation —
not "no Git call": the stacked status read's single remote-tracking-only fetch of origin is
inside it. The only perk tools the **nested policy** admits under the gate (contracts §8.40
"The nested policy") — a lifted codemode's script calls included.
_Avoid_: gated read tool, read-only query (ambiguous with `readOnlyHint`, a hint and never a grant)

**Nested policy**:
The read-only backstop's narrowing of a nested call — one another tool issued through
`ctx.executeTool` (Pi's `parentToolCallId`). Under an effective read-only gate a nested call
reaches only a **gate-eligible query**, a core builtin read (`bash` by its verdict) and a foreign
tool by its gate posture; every other perk kind and the extension builtins (`tool_search`,
`codemode`) are refused, though the same tools may be admitted direct. A **bounded writer** never
even reaches it nested — Pi refuses a model-only tool first (a script's
`tools.<name> does not exist.`, agent-core's `Tool <name> not found`), the policy's writer arm
staying behind both. Derived from a tool's classification (`nestedPostureFor`), never from its name
or annotations.
_Avoid_: nested grant — a hidden, deferred or `readOnlyHint` tool is never one

**Eligibility formula**:
The one rule deciding whether a tool may be active in a (stage, mode) landing:
`(stage ∈ stages ∧ (read-write ∨ not gate-blocked)) ∨ (read-only ∧ mode-over-stage)`, an unscoped or
unknown stage being eligible for everything the mode allows. Over perk's own tools its read-only
result is a stage's **gated view** and its read-write result the **stage diet** — the perk-side
activation views; a foreign tool's eligibility (by its provenance posture) is presented, never
installed.
_Avoid_: gate-ON allowlist, READ_ONLY_TOOLS, STAGE_TOOLS, stage list

**Mode gesture**:
A session action that changes the mode but records no stage — the `/plan` toggle. The tools its
flow needs are mode-over-stage, so the flow completes wherever the gesture lands.
_Avoid_: mode switch, plan stage (for the toggle)

**Own-names-only activation**:
perk's activation rule: at every reconciliation point it installs the live active set with only
its own names replaced — the eligible always-declared perk tools plus, inside the discovery
cohort, the live eligible deferred ones — and never activates or deactivates a foreign tool (of
the builtins, the read-only gate only suspends `codemode` — never where the **codemode lift**
holds — and restores it at release); a session
whose live set already matches gets no install. Door-primed activation is perk's only activation
of a deferred tool.
_Avoid_: snapshot restore, baseline, admitted set, perk-owned allowlist

**Codemode lift**:
The read-only gate keeping a user-enabled codemode on instead of suspending it: in a registry
read-only stage (`READ_ONLY_STAGES`) when the session's codemode mode is `on`, or is `only` with no
**stranded writer**. Never unscoped, never a read-write stage's `/plan` toggle, never a child
floor; it keeps or restores a codemode the user enabled and never activates one, and a lifted
landing consumes the suspension memo (so a later deactivation is never undone). A lifted
codemode's scripts stay bounded by the **nested policy**.
_Avoid_: un-suspension, codemode allowlist

**Stranded writer**:
A perk tool registered in this session, gate-eligible in the stage, exposed `direct` there and
nested-blocked — what Pi's codemode `only` mode would hide from the model with no script path back,
so its presence keeps `only` suspended (`strandedWriters`). Coined for the bounded writers, now
model-only; today's members are the mode-over-stage actions `push_annotations` and
`collect_draft_review_wave` in every gated stage of a discovery nonparticipant (deferred, hence
never stranded, in the cohort).
_Avoid_: `only`-strand, hidden writer

**Discovery cohort**:
The sessions in which perk re-registers the pilot family (`declared: deferred`) deferred and
switches it off once: those where Pi's builtin `tool_search` is registered and active at
`session_start` (the init-converged `defaultTools: ["+tool_search"]`; opt-out `-tool_search`,
effective at the next launch) — the headless worker included, through its own builtin
`tool_search`. `/btw` and any session whose *resolved* selection leaves `tool_search` out (a project `-tool_search`, or an empty resolved selection — a
project `[]` alone suppresses only perk's seed) or whose `tool_search` is a foreign namesake are
nonparticipants by construction and keep every perk tool declared.
_Avoid_: pilot sessions, tool_search sessions, opt-in

**Door-primed activation**:
A warm door (or a wave launcher) activating the deferred perk tools its carrier names, at the
moment it primes its other surfaces (a launcher: on a successful launch) — before the carrier
reaches the model; a no-op outside the discovery cohort.
_Avoid_: auto-activation, lazy load

**Provenance posture**:
How a foreign tool is governed — by who registered it (Pi's `sourceInfo`: a package spec, an exact
synthetic path, or the builtin registrar), never by its name: `research`, `universal`,
`delegation`, `never` or `child-engine`, with `unknown` (passes every diet, blocked under the gate)
for anything else.
_Avoid_: borrowed census, foreign tool list, lazy loader, lazy-owned tool

**Loadout host**:
The always-active perk tool `perk_stage`, declared to Pi but hidden from every request by its own
`prepareLoadout`, which also hides every declared tool ineligible in the session's (stage, mode)
landing — presentation only (it hides; it never rewrites a description); the read-only `tool_call`
backstop stays the enforcement. The prose map discovers it and records it as an excluded candidate.
_Avoid_: stage tool, gate tool, presenter

### Read-only bash gate

The verdict (`readOnlyBashVerdict`) lives in `extension/substrate/readOnlyBash.ts`; the gate applies
it to `bash` under the builtin row's `verdict` posture.

**Command position**:
A place in a bash command string where bash reads the next word as a command to run — the start
of input and after a sequencing operator, newline, substitution opener, assignment prefix, leading
redirection, shell keyword, known wrapper, or `find -exec`; the read-only gate applies
`SAFE_PATTERNS` at every one.
_Avoid_: segment, leading word, first token

**Simple-command text**:
The raw text from a command word to the end of its simple command (the next same-frame
operator/newline/closer) — the unit the allowlist regexes match.
_Avoid_: segment, argv, command line

**Argument-level writer**:
An allowlisted command whose *argument* turns the read into a write (`find -delete`, `sed -i`,
`git branch -D`, `git remote add`, `sort -o`); closed by one whole-string veto row each, never by
removing the command from the allowlist.
_Avoid_: destructive command, mutating command

**Exec-bearing input**:
A submitted environment assignment, literal executable-word suffix, or option that makes an
otherwise admitted read launch another program (`GIT_EXTERNAL_DIFF=… git diff`, `rg=payload`,
`rg --pre …`, `git diff --ext-diff`). Assignment/command-word routes are walker refusals; scoped
selector/helper options are whole-string veto rows. Unlike an argument-level writer, the effect is
choosing code to run, not making the admitted program itself write.
_Avoid_: command injection, executable argument, environment exploit

**List form**:
The argument shape under which an argument-sensitive `git` subcommand only reads: every word an
enumerated option or a positional, with a list-implying option among them (positionals are then
patterns), or the bare subcommand with display modifiers and no positional.
_Avoid_: read-only form, safe form

**Veto view**:
The text the whole-string destructive veto reads: the command with every substitution, `${…}` and
heredoc body collapsed out of the text that holds it, then each substitution's own text (collapsed
the same way) on a line of its own.
_Avoid_: scanned text, flattened command

### Report-wave lane identity

**Semantic lane id**:
The producer-owned identity a learn-flow manifest gives one lane (a harvest `<category>-<n>`, a
dream cluster id, an audit `expectation_id`) — what analysts match byte-exact against the manifest
and what typed outcomes report on.
_Avoid_: lane key, run key, label

**Routing token**:
Any producer-owned identity rendered into a report child's task prose for byte-exact lane
selection or verbatim echo — usually the semantic lane id, plus the audit wave's pair-level
`session_basename` (a token, not a lane id) — untrusted DATA, never an instruction; admitted only
through the `waves/laneIdentity.ts` fence (a refusal rule, never escaping).
_Avoid_: escaped id, sanitized id, lane key

**Orchestration key**:
The code-owned `runs.all` item key a producer-lane learn wave (harvest, audit, dream analyst) gives
one lane — the fixed `lane.<ordinal>` (a global 1-based ordinal in lane-plan order) from
`waves/laneIdentity.ts`; opaque, never derived from producer bytes, never surfaced as a lane
identity (it appears only in attempt receipts' `requestedKeys`, receipt children, and failure
details). Closed slug-enum waves (learn analyst, dream reducer) key by the slug and have none.
_Avoid_: lane id, label, sanitized key, run key (when the identity is meant)

### Report-wave settlement

**Engine deadline**:
The spawned `timeoutMs` pi-subagents enforces on a report-wave run (`WAVE_TIMEOUT_MS`, 30 minutes;
`PERK_WAVE_TIMEOUT_MS` overrides) — inherited by every runner child, settled `partial/timeout`
against, and the orphan insurance.
_Avoid_: wave timeout, module timeout (when the engine's bound is meant)

**Settlement grace**:
Perk's fixed slack beyond the engine deadline (`WAVE_SETTLEMENT_GRACE_MS`, 60 s; not an operator
knob) before its own `timeout` fires — long enough for the engine's partial settlement and its
completion carrier to arrive.
_Avoid_: collect grace (the separate `PERK_WAVE_COLLECT_GRACE_MS` bound on a premature collect)

**Deadline partial**:
A native partial settlement with reason `timeout` whose completed lanes' reports are retained and
whose still-running lane(s) surface as `lane-failed` — a normal collected outcome, never a cue to
recover reports from `status.json` or child artifacts.
_Avoid_: timeout (perk's own empty expiry), partial timeout

**Termination proof**:
The engine's workflow terminal proof as perk projects it after its own stop request — `observed` /
`pending` / `unknown`, or `unavailable` when the one `status` query yields none. `observed` means
the engine recorded dispatch closed and resolved process evidence for every async child (an
observed runner exit, or a never-started launch failure) — quiescence, never inferred from a stop
reply, a freed slot, a complete report or `endedAt`.
_Avoid_: stopped (perk never confirms a stop), slot freed, exited (a never-started child has no exit)

**Stop acknowledgement**:
The engine's RPC `stop` success reply (`state: "stopping"`, `Stop requested for async run <id>.`):
an acknowledged request, never termination and never durable — for a live in-process workflow the
engine only aborts its in-memory run controller, writing no control request. A typed refusal (`not_found` / `invalid_state` /
`execution_failed`) is a **refused stop**, reported with the engine's reason.
_Avoid_: best-effort stop (the old wording that read as a verdict), the model-facing stop action's
seal (a different implementation perk never calls)

**Launch token**:
The per-launch `args.launch` UUID every report-wave spawn carries (minted at the transport's one
spawn site). Its only job is to keep pi-subagents' runtime-replaced workflow reuse (same session,
script digest and args digest) from ever matching a perk wave; it is never identity (that stays
the spawn handle) and never read back.
_Avoid_: wave nonce, reuse key

**Relaunch freshness**:
The guarantee that a wave launched again — after `/reload` included — inspects anew: new
children over current inputs, never the earlier wave's finished or still-running children.
_Avoid_: re-attach, resume

**Wake turn**:
The parent run that pi-subagents (≥ 0.80.0) starts by sending its `subagent-notify` completion
notice with `triggerTurn: true` while the parent is idle — a custom-message start
(`before_agent_start` with `messageType: "custom"`, no prompt) whose notice carries a
`Parent action:` line. A held parent (Escape) gets the notice appended without a wake. In print
mode the wake turn runs while a command handler is still pending; if the handler returns first,
the host's dispose aborts it.
_Avoid_: wake message (the notice text alone), completion turn

**Pre-spawn lane failure**:
A `runs.all` item that fails in the parent before any runner process exists — for example at
model resolution or worktree admission. It leaves no child directory, or one holding only
`recovery-descriptor.json` / `run-fanout-budget.json`. It still wakes the parent.
_Avoid_: refused child, failed child (a runner that started and failed)

### Plan save

**Save reconciliation**:
The two best-effort workflow-state writes a plan save performs after the backend save landed —
the session link (`active_plan_ref`) and, only once that link landed, the planning-claim clear
(`objective_node_claim`) — each reported as the session seam's change result (`applied` /
`unchanged` / `unverified` / `rejected`) and carried verbatim into the save result's `details`
(`linkage`, `claim_clear`). A held result is repair guidance on a SAVED plan, never a save failure;
`/plan-save` is the retry (the same `plan_save` call when the save's explicit inputs are beyond the
command's recovery), and a held link leaves the claim standing as that retry's link carrier.
_Avoid_: save failure (for a held reconciliation), linkage error (as the save's outcome), unlinked
save

### Review

**Approval guidance**:
Nonblocking advice accompanying an approval. It neither changes the verdict into a request for
changes nor establishes that a platform review was posted.
_Avoid_: change request, posting confirmation

**Activity**:
The optional second half of perk's one composed `perk` status value (`<objective> · <activity>`):
a short plain-text phrase naming a Perk-owned wait the operator cannot otherwise see — today only
`waiting on browser review`, begun by the two plannotator browser waits (the browser doors' open
core on readiness, the warm `plan_review` bridge on entry), ended when each wait settles, and
shown while any begun wait is unended. Never a spinner, a working state, a liveness signal, or a
per-interaction record.
_Avoid_: status, working indicator, spinner, liveness

**Browser-operation owner**:
The one per-activation object, above the current-review slot and the Plannotator handoff, that
owns a browser review's start, companion priming, readiness and decision observation,
replacement, background tasks, console interception and cleanup for all four browser doors
(the plan/objective draft doors and the PR/stack code-review doors — one owner, so any door's
open replaces any other's). Subjects keep save, Direct-Edits, destination and publication rules;
the slot keeps decision authority.
_Avoid_: door session, review controller

**Detached review**:
A browser review whose perk wait is over while its tab stays open — replaced by a newer door
open, interrupted by a turn abort, or orphaned by a session reload/replacement. Perk marks it so
in the tab's `perk:wave` slot after draining any admitted decision; nothing is persisted, nothing
resumed, and Plannotator's server is never stopped.
_Avoid_: superseded review (that is the slot's term), stopped review, closed server

**Prepared snapshot**:
The parent-fetched, code-owned feedback set a classifier lane is bound to (`/address`: the
strictly decoded `perk pr feedback --json` payload); membership, uniqueness, coverage and counts
are derived from it, never from the lane.
_Avoid_: the child fetches, lane counts, raw feedback (for the decoded snapshot)

**Classification subjects**:
Exactly the items of a prepared snapshot the lane must classify, once each: the unresolved review
threads (outdated-but-unresolved included) and every discussion comment. Resolved threads and
PR-level review bodies are excluded by decision — only counted.
_Avoid_: feedback items (for the unfiltered set), review comments (ambiguous with inline comments)

**Bound classification**:
The parent-validated result of binding a lane's judgment-only report to the classification
subjects — snapshot order, anchors (`path`/`line`/`is_outdated`) attached from the snapshot,
counts derived in code. Held per activation; it is what `finalize_address` binds to (the thread
ids it may resolve and the PR it may resolve them on).
_Avoid_: lane report (for the bound result), lane counts, classifier output

### Objective delivery

**Incremental delivery**:
The default objective delivery policy in which each plan integrates independently when it is
ready.
_Avoid_: serial delivery, ordinary delivery

**Stacked delivery**:
An objective delivery policy in which plans remain separate review units but integrate together at
the objective boundary.
_Avoid_: stack mode, chained delivery

**Delivery train**:
The ordered set of layers belonging to one stacked-delivery lineage, including across objective
replans.
_Avoid_: stack, branch chain

**Layer** (of a delivery train):
The delivery unit formed by one non-skipped roadmap node and its plan.
_Avoid_: commit, phase, arbitrary pull request

**Published prefix**:
The contiguous initial portion of a delivery train whose layers have established review artifacts.
_Avoid_: open plans, published set

**Delivery lineage**:
The stable identity of a delivery train across superseding objectives.
_Avoid_: objective lineage, stack number

**Delivery order**:
The deterministic topological order of a train's non-skipped roadmap nodes, derived with
`node_sort_key` as tie-breaker and never persisted.
_Avoid_: roadmap order, stack position

**Predecessor layer**:
The immediately preceding layer in delivery order, identified durably by plan identity (the
bottom layer has none).
_Avoid_: parent branch

**Parent checkpoint**:
The verified parent commit a published layer head was built from (the objective base for the
bottom layer).
_Avoid_: planning provenance, the parent's current head

**Published-head checkpoint**:
The layer branch head last verified after publication or synchronization.
_Avoid_: desired future head, local HEAD

**Dynamic singleton**:
A delivery train reduced by later cancellation to one remaining layer after having been validly
authored with multiple layers.
_Avoid_: one-node stacked objective, standalone plan

**Cancellation projection**:
The read-side handling of a backend-native node cancellation (a Linear node-issue moved to a
canceled workflow state): the node projects as skipped only when positively proven to be
unpublished future work — a clean, coherent plan backlink is acceptable, but any identity
conflict, checkpoint or PR claim, completed/unresolved publication history, remote branch, or
branch-owned PR is not; anything unprovable stays a visible `canceled` layer with blockers,
and the persisted attachment status is never changed by the read (doctor `--fix` owns
persisting a proven-safe skip).
_Avoid_: auto-skip, native skip, cancellation sync

**Adoption** (of a layer head):
Accepting one layer's manually-pushed remote head as the intended stack state and cascading the
layers above it (`stack sync --adopt`).
_Avoid_: force-sync, overwrite

**Transfer manifest**:
The predecessor-carried TRANSFER journal record whose `before`/`after` payloads are the sole
durable authority for re-driving an interrupted replan transfer (the complete successor
materialization intent plus the recorded claimed prefix).
_Avoid_: successor manifest, session artifact

**Continuation manifest**:
The lineage-keyed, machine-local record of a mid-conflict sync stop — the disposable pointer to
the retained worktree and captured inputs that `--continue`/`--abort` consume.
_Avoid_: transaction log, checkpoint file

**Orphaned sync residue**:
Machine-local `sync-*` worktrees or `refs/perk/sync/*` temp refs whose operation no parseable
continuation manifest claims — inert until `stack recover`'s sweep collects them.
_Avoid_: garbage, stale worktrees

**Landed layer**:
A train layer classified terminal by the prepared⋈completed LAND-journal coverage join
(node/plan/PR identity equal AND the recorded head equal to the published-head checkpoint)
plus fresh merged corroboration of its PR — a merged PR without journal coverage is never
adopted.
_Avoid_: merged layer, finished node

**External prefix breach**:
The recorded degraded-atomicity conclusion of an interrupted LAND: a bottom-contiguous prefix
of the recorded layers was merged outside the operation while every remaining layer stayed
open at its recorded head, accepted explicitly (`stack recover --accept-prefix`) as a
completed record covering only the merged prefix (`external_prefix: true` + the remainder
proof).
_Avoid_: partial land, broken stack

### Objective refinement

**Refinement** (of a roadmap node):
A dated, reviewed, advisory elaboration of one existing roadmap node, persisted as a single
marked comment on the node's carrier (the Linear node-issue, or on GitHub the objective issue
itself) with its authoring provenance and the node source it was written against. Content only: neither an executable plan, a node
status, a claim, nor a readiness or freshness proof; stored metadata never authenticates human
approval.
_Avoid_: pre-plan, draft plan, node body, elaboration

**Refined** (a roadmap node):
The presence of a valid saved refinement record for the node — derived from the carrier's
comment, never a node state, header, manifest, or plan-ref field. A refined node stays exactly
as selectable for planning as before; a changed source reads as advisory drift, not absence.
_Avoid_: pre-planned, unblocked, ready

### Learned-corpus curation

**Learned corpus**:
The tracked `docs/learned/` doc set (minus the generated index) that `/learn` grows and the
curation factories read.
_Avoid_: knowledge base, notes

**Dream**:
The whole-corpus curation audit at one stamped commit (`perk learn dream`), reading the corpus
inward to curate the corpus itself; contrast **harvest**, the bounded outward mine that reads
docs as lenses into the code.
_Avoid_: full harvest, corpus scan

**Dream report**:
The reviewed, durable companion record of a dream (one row per doc, stances, selections,
overflow, follow-ups), persisted as immutable marker-keyed comments on the objective's report
carrier.
_Avoid_: audit log, wave output

**Disposition**:
The one final per-doc curation verdict from the closed set `keep` / `revise` / `merge-into` /
`retire`.
_Avoid_: action, fate, status

**Curation unit**:
One coherent plan-sized bundle of curation work (e.g. a merge source + survivor + forced
repoints), selected or ranked into overflow, mapping many-to-one onto roadmap nodes.
_Avoid_: task, work item

**Curation objective**:
The ONE bounded objective a dream authors (≤ 12 distinct roadmap nodes), carrying
`origin: learn-dream`.
_Avoid_: cleanup epic

**Harvest follow-up**:
A report-only code-improvement lead surfaced during a dream, citing a **surviving destination**
(a final-`keep`/`revise` doc, or a cluster named by one); never curation-roadmap work and never
a minted issue.
_Avoid_: code TODO, side quest

**System-state evidence**:
The bounded projection of a Pi system message's prompt sections and tool-name deltas (and a
compaction's prompt snapshot) that `/learn` renders as `<system_state>` in its session chunks;
context about what the model was told — never a user turn, user authorization, or workflow event.
_Avoid_: system prompt dump, tool manifest, user instruction

**Execution lock**:
The per-worktree `perk-submit-conflict.lock` (`worktreeResolverLock.ts`) that serializes
participating conflict resolvers on one canonical Git directory; busy for any incumbent, never
reclaimed; released by a correlated native `completed` terminal or a pre-launch refusal
(`invalid_request`/`unavailable_context`/`duplicate_node`) with no start evidence, otherwise
retained for a human.
_Avoid_: resolver lock, file claim, lease

**Resolver session claim**:
The `<manifest>.resolver-lock` lease (`resolverLease.ts`) a `/objective-sync` invocation holds for
the retained operation; same-PID reacquire and dead-PID reclamation permitted; never bypasses the
execution lock.
_Avoid_: lock, resolver lock

**Native worktree default**:
pi-subagents' global `worktree` setting in `<agent dir>/extensions/subagent/config.json`, applied
to every delegation that omits the field and read by both engines once at activation; perk
observes and refuses, never converges it.
_Avoid_: worktree allocation default, perk-managed worktree setting

### Headless worker

**Worker model request**:
The worker's unresolved model input — the raw `--model` pattern (Pi CLI semantics, including a
`:thinking` suffix) plus, for tests, the model runtime; resolved only after the worktree's
extensions have registered their providers.
_Avoid_: model selection (the resolved pick), model token

**Worker selection ladder**:
The fixed order inside the worker's runtime factory — extension registration → explicit
resolution → admission (`no_model` / `model_not_found` / `model_auth`) → session construction
with Pi's default chain → bind.
_Avoid_: auth preflight, model preflight

**Fresh tokens**:
The worker's budgeted token sum, read from Pi's usage records at the boundary that produces each —
per turn the assistant's input + output plus every tool result's reported usage (Pi has already
folded nested calls into the parent result), and per `compaction_end` the compaction summary's
usage; never cache reads/writes, reasoning breakdowns, branch summaries or report-wave children.
Equal to Pi's `getSessionStats()` input + output for a worker session.
_Avoid_: total tokens, context tokens, cost

**Selected model**:
The session's model selection — `ctx.model` / `AgentSession.model`, recorded by `model_change`
entries; a virtual model names the router, never its physical target.
_Avoid_: active model, current model (ambiguous between selection and dispatch)

**Dispatched model**:
The physical model recorded on an assistant message — `provider/model`, with `→responseModel` when
the provider reported another id. Only successful responses count; an `error` or `aborted` response
never does (a failed routing leaves the selected identity on its error message).
_Avoid_: routed model, response model (that is only the provider-reported id)

**Usage ledger**:
The once-counted fold over Pi's usage records at their own boundaries (assistant and tool-result
messages, `compaction` / `branch_summary` entries, `usage` entries; nested calls never summed):
records, input, output, cacheRead, cacheWrite and cost (Pi's recorded `cost.total`). `unavailable`
when no record exists — never zero; a recorded zero cost stays a number. The worker's ledger has
`input + output` equal to its fresh tokens; selfcheck's covers the selected branch.
_Avoid_: budget, total tokens, fresh tokens

**Model-call policy**:
The worker's fixed rule for model calls from its own codemode — no `models` namespace
(`WORKER_CODEMODE_MODELS = false`, the worker's own codemode only), and any `codemode` call,
whatever its registrar, naming `models.classify(` or `models.generateImages(` refused before it
runs with a typed reason.
_Avoid_: model gate, classifier opt-out

**Constrained capability**:
A capability shipped narrower than intended because public interfaces cannot deliver its safety
bar; recorded with its retirement condition, never a floor hold.
_Avoid_: hold, deferral

**Worker builtin factories**:
The three Pi builtin tool extensions the worker supplies beside its hidden policy extension, with
the CLI's identity (`builtin:codemode` — built with `models: false` — `builtin:tool-search` and
`builtin:mcp`): disabled by `-builtin:<name>`, replaced by a project registration of the same
tool (for MCP, the `/mcp` command). Codemode and tool-search register inactive and are activated
by configuration (the repo's `defaultTools`, and the project MCP config's server exposure —
`codemode` under `autoEnableCodemode`, `deferred` for tool-search — which activates over a
`defaultTools` opt-out); MCP connects only the trusted project's `.pi/mcp.json` servers, under
factory-scoped isolation. A project extension that brings its own MCP support is outside that
guarantee.
_Avoid_: native factories, worker extensions

**Factory-scoped isolation**:
Confining the SDK worker's MCP resources (config, credentials, log, sign-in) through
`McpExtensionOptions` adapters rather than the process environment, so model auth, supplier
children and session persistence keep the real agent dir. Headless MCP problem reporting is
silence by design — Pi reports server problems only in its UI and offers no status hook — except
the worker's empty-store OAuth sign-in line.
_Avoid_: agent-dir override, MCP sandbox

### Host admission

**Host floor**:
The enforced minimum supported host version — Pi and Node — declared once in
`shared/host-floor.yaml` and compared with semver precedence (`>=`; a prerelease of the floor
triple is below it). Each host observation is admitted against it independently. Pi's floor is a
single minimum; Node's is a closed table of supported release lines, each with its own line floor.
_Avoid_: pin, requirement, gate (when the minimum is meant)

**Supported release line / line floor**:
One Node major perk admits, with the minimum release on that line (`node.min_version` for the
lowest line, `node.line_floors` for the others); a major outside the table is refused as
unsupported.
_Avoid_: version range, LTS list

**Admission**:
The decision about one host observation against the host floor — the PATH `pi` at the launch
boundary, the loaded Pi SDK at the extension entry and at the worker entry — `admitted`,
`unsupported` (`pi_version_unsupported`) or `unverifiable` (`pi_version_unverifiable`), taken
before any workflow, resource or provider work on that path.
_Avoid_: version check, gate

**Adopted Pi pin**:
The exact Pi version perk adopted (`PI_ADOPTED_VERSION`, `perk/substrate/pi_host.py`), named by
every install-guidance string and carried by the remote install pin; never below the host floor;
an exact pin, not a minimum. A PATH `pi` admitted at another version is not refused, only reported
(an environment-row advisory). Pi 1.4.0 + pi-subagents 0.81.0 are adopted
(`docs/design/archive/pi-1.4.0-adoption.md`); their live certification is owed, and the previous
certification record (`docs/design/archive/pi-1.1.0-certification.md`, Pi 1.1.0 + pi-subagents
0.76.1) holds 3 required FAILs (W4, W6, W7a), so the support claim stays held.
_Avoid_: floor, latest

**Pinned install set**:
The one exact `@earendil-works/pi-coding-agent` spec at the adopted Pi pin (`PI_INSTALL_SPECS`,
installed by `PI_INSTALL_COMMAND`) whose exact internal declarations place its six companions at
the same version — since Pi 1.3.0 the package declares them exactly, so no shrinkwrap or sibling
specs are needed. The companions remain the coherence family the host probe verifies.
_Avoid_: eight packages, sibling specs, companions alone, dependencies

**Remote install pin**:
The exact Pi the managed remote artifacts install (`REMOTE_PI_VERSION`) for both the global CLI
and the consumer worker SDK — the adopted Pi pin under its remote name; both remote installs name
the pinned install set. Never below the host floor; an exact pin, not a minimum (it may equal the
floor's version).
_Avoid_: floor

**Dev pins**:
The exact `@earendil-works/*` `devDependencies` of perk's own checkout — four packages moved in
lockstep by `just bump-pi` — that the repo's tsc, node:test and pytest resolve and that the
self-repo remote worker runs on (its `npm ci` install). They certify nothing and gate nothing:
the host floor is the admission minimum, and the remote install pin is what consumer repos
install.
_Avoid_: floor, supported version, host version, remote pin

### TUI surfaces

**Display sink**:
A place where perk itself renders text into the terminal (a transcript marker row, a footer
segment, a `/btw` overlay row); every one passes untrusted text through the surfaces module's
display sanitizer, folded when its renderer emits a single row.
_Avoid_: output, render site, surface (when the sanitization boundary is meant)

**Display projection**:
The render-time copy of persisted or in-memory text after the display sanitizer; the stored bytes
are never altered.
_Avoid_: sanitized payload, rendered text, cleaned entry

### The perk library

**Librarian**:
The shipped `librarian` skill — the model-facing rules for consulting, checking, refreshing and
adding library entries, plus the documentation crawl workflow — paired with the `perk librarian`
CLI group, the deterministic workers it drives. The skill decides; the workers act.
_Avoid_: library skill, docs skill

**Awareness carrier**:
A §8.57 pointer surface that makes a session aware of the `librarian` skill without restating
its rules or mandating its use — the `perk-plan` grounding sentence, the skill's ambient
`description`, the operator pages. The skill decides; carriers only point.
_Avoid_: second carrier, summary, mandatory step

**Docs door**:
`perk librarian add docs <url>` and the human `perk librarian refresh <slug>` on a documentation
entry: the write-capable cold doors (the `save`-descriptor borrow) that claim a staging directory
and launch the curating session, as opposed to the `--json` workers.
_Avoid_: docs worker, crawl command

**Staging claim**:
The docs door's atomic `mkdir` of the session's empty `.staging/<slug>[-N]` directory; the door
never deletes a staging directory.
_Avoid_: staging lock (there is none — the library lock covers publish, not crawling)

**Redirect stub**:
A page that is only an HTML redirect — a meta refresh or a script `location` assignment, every
anchor pointing at the target — served `200`, so `curl --location` cannot follow it (a mike
`/latest/` version alias). The crawl refuses one as a seed with the typed `seed-redirect` blocker
(exit 3) when its target is a reissuable http(s) URL; a non-seed stub is mirrored as served.
_Avoid_: HTTP redirect (curl follows those), alias page (the mike term for the same thing)

**Seed probe**:
The docs doors' and the prepare worker's one-page dry run of the seed (`--max-pages 1
--dry-run`) before the staging claim; it refuses `seed_redirect` and is otherwise advisory (a
`warning:` / `warnings[]` entry).
_Avoid_: dry-run (the human `--dry-run` is the full discovery), check (the catalog freshness
probe)

**Prepare worker**:
`perk librarian prepare docs|refresh … --json`: the docs doors' pre-session half plus the staging
claim, emitted as the crawl plan the `run_librarian` tool dispatches its child with; launches
nothing.
_Avoid_: docs door (that launches a session)

**Writer child**:
A foreground, fresh-context, floor-less subagent perk dispatches to mutate on the parent's behalf
(`perk.conflict-resolver`, `perk.librarian`), through the one foreground-delegation transport;
contrast the read-only report lanes.
_Avoid_: writer lane, worker

**Bracket**:
The fail-closed clean-start / end-state check around `run_librarian`'s child on the main
checkout (HEAD, tracked cleanliness, index flags, the non-ignored untracked inventory with content
digests); it detects violations after the fact, never prevents them, never reverts. Its claim is
end-state equality, not mid-window immutability.
_Avoid_: sandbox, guard

**Clean-start policy**:
The precondition the bracket requires before dispatch — HEAD resolvable, tracked tree clean, no
assume-unchanged/skip-worktree flags, the non-ignored untracked files inventoried; an unclean
start is the typed `unclean-start` refusal naming the terminal door.
_Avoid_: clean tree (untracked non-ignored paths are allowed at start — inventoried, not
forbidden)

**Corroboration** (of a librarian publish):
The parent's machine evidence for a `published` claim: the catalog entry present via
`list --json` AND this run's claimed staging directory moved into place. The child's record
alone is never proof.
_Avoid_: verification (the child's own checks), confirmation

**Staging handshakes**:
`sources.json` (the per-page inventory) and `failed-pages.json` (the crawl's failure report),
written by the `librarian` skill's crawl script into the staging directory and consumed by
`perk librarian record --publish` (markers seeded from the inventory; a non-empty report refused
unless accepted).
_Avoid_: manifest, crawl log

**Adoption** (of a library directory):
The orphan-only `perk librarian record --adopt` gesture that catalogs a pre-existing uncatalogued
directory as a docs entry at `documentation/<slug>/` (the slug defaults to the directory name): a
top-level directory is moved there, and an orphan already under `documentation/` stays put only
when its name is the slug — a different `--slug` renames it. It never renames a catalogued entry
(`directory_catalogued`) and, unlike publish, validates no `index.md`. Distinct from the delivery
glossary's **Adoption** (of a layer head).
_Avoid_: import, migration

**Repo-ref**:
The user-facing spelling of a source repository (`owner/repo`, `host/org/repo`, `https://…`,
`ssh://…`, `git@host:org/repo`), normalised by `parse_repo_ref` to a `RepoRef` (host/org/repo plus
the clone URL the catalog records).
_Avoid_: repo URL (when any accepted spelling is meant), slug

**Pin / re-pin**:
`--ref` detaches a source checkout at a tag/branch/commit and records it as the entry's `ref`; a
pinned entry is drift-exempt (`pinned`), refused by `refresh`, restored only with an explicit
`--ref`, and moved only by another `add source … --ref`. Unpinning is `remove` + `add source`.
_Avoid_: lock, freeze

**Baseline** (of a marker):
The first observation of a marker the catalog did not yet hold (a page's ETag, the inventory
fingerprint, a source `head_sha`), recorded as the mirror's revision; later probes compare
against it and never overwrite it.
_Avoid_: snapshot, refresh

**Inventory fingerprint**:
The `weak` evidence tier: a hash of a docs site's sitemap `(loc, lastmod)` set and/or its
`llms.txt` body — never an HTML body.
_Avoid_: content hash, page hash

**Throttle**:
`check` skipping an entry whose `checked_at` is inside its `stale_after` window (`recent`) unless
`--force`.
_Avoid_: cache, rate limit

**Config-pinned git**:
The library's executing git operations, run without global/system config and with hooks
disabled, so nothing a cloned tree or the user's global/system config selects can execute; env
config and a checkout's own repo-local config remain trusted (unaudited).
_Avoid_: sandboxed git, safe clone
