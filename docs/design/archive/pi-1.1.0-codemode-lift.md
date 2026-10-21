# Record: the codemode lift in the read-only stages on Pi 1.1.0 + pi-subagents 0.76.1

**Status:** measured offline; the live usefulness leg is **DEFERRED** to node 7.1 (operator
decision 2026-10-21, below) and is not reported as met. Authored 2026-10-21 (UTC) on branch
`plan-2738` (base `b394d82d`). It implements plan #2738 (Objective #2707, node 4.3) on the adopted
pair. This node moves no pin, floor, stamp, agent-definition body, setting, context template,
selfcheck line or doctor check.

It covers three moves:

1. **The bounded writers register `exposure: "model-only"`.** `derivePiMetadata` derives it for
   every `gated: { carveOut }` policy — the five action carve-outs `plan_draft`, `objective_draft`,
   `objective_refinement_draft`, `objective_node`, `gist_draft` (the three orchestration
   carve-outs already were).
2. **The lift, derived.** A user-enabled codemode stays active, declared and directly callable
   under the gate in every registry read-only stage (`READ_ONLY_STAGES`) when the session's
   codemode mode is `on`, or is `only` with no stranded writer.
3. **Everything else stands.** The nested policy is unchanged; a script under the gate reaches the
   matrix's `eligible.<stage>.nested` set plus foreign tools by posture.

**Verdict:** every offline clause PASSES on real Pi 1.1.0 sessions (below). The live leg is a
bounded 7.1 protocol (§ "The deferred live leg").

## Versions

| Component | Version |
| --- | --- |
| PATH `pi` (`pi --version`) | `1.1.0` |
| Root SDK (`node_modules/@earendil-works/pi-coding-agent/package.json`) | `1.1.0` |
| `@earendil-works/pi-codemode` (the sandbox prelude) | `1.1.0` |
| Worktree engine (`.pi/npm/node_modules/pi-subagents/package.json`) | `0.76.1` |
| Node | `v26.3.0` |

## The design

### Why `model-only` is the honest exposure for a bounded writer

Pi's `only` mode (`prepareCodemodeLoadout`, `dist/extensions/codemode/tool.js`) hides
`callable.filter(isDirect && declared)`. A `direct` bounded writer is therefore hidden from the
model in `only`, while the nested policy refuses it to a script — no path is left. Pi already has
the vocabulary for "declared to the model, never callable through another tool": `model-only`.
`_getCallableTools` is the active direct tools plus every codemode/deferred-exposure tool, with
model-only excluded; the codemode executor builds the sandbox's `tools` from that callable set.
So a model-only writer:

- stays declared (`only` hides only direct tools), and mode `on`'s description rewrite
  (`Codemode: tools.<name>(args) …`) never touches it;
- is never a member of a script's `tools` — reading `tools.plan_draft` throws the prelude's
  `TypeError` `tools.plan_draft does not exist.` before any `ctx.executeTool` or hook;
- is never reachable through `ctx.executeTool` — agent-core's `prepareToolCall` answers
  `Tool <name> not found` before `beforeToolCall` (the `tool_call` hook).

The 4.2 hook arm for the writers stays behind both, as defense in depth (like the model-only
kinds).

### Why a `deferred` tool cannot also be model-only

`exposure` is one enum. A discovery-family member is re-registered `deferred` in the cohort; a
model-only tool could never be script-callable. The validator already refuses
`declared: "deferred"` on a carve-out (the read-only context names the writers, and an undeclared
writer would dead-end), so the two derivations never compete.

### The stranded-writer rule over registered names

`strandedWriters(stage, landing)` (pure, catalog order): a perk tool registered in this session,
eligible under the gate in the stage, exposed `direct` here (not in this activation's deferred
memo, not model-only) and nested-blocked. With the writers model-only, today's members are the two
mode-over-stage actions `push_annotations` and `collect_draft_review_wave` — gate-eligible in
every known stage — whenever they are registered and not deferred. A catalogued name Pi's registry
filter left out can never strand (§8.40's exclusion contract: only registered names exist in a
session). Absent facts fail closed: no codemode mode → no lift; no deferred memo → nothing
deferred; no registered list → the whole catalog is a candidate.

The census, from `shared/fixtures/tool-matrix.json` (`tools.codemode.suspended.stranded_writers`,
the whole catalog registered):

| Lifted stage | nonparticipant (nothing deferred) | cohort (the family deferred) |
| --- | --- | --- |
| `gist-author` | `collect_draft_review_wave`, `push_annotations` | — |
| `objective-author` | `collect_draft_review_wave`, `push_annotations` | — |
| `objective-plan` | `collect_draft_review_wave`, `push_annotations` | — |
| `plan` | `collect_draft_review_wave`, `push_annotations` | — |
| `audit` | `collect_draft_review_wave`, `push_annotations` | — |
| `objective-refine` | `collect_draft_review_wave`, `push_annotations` | — |

So `only` lifts in every lifted stage of a discovery-cohort session and stays suspended in every
gated stage of a nonparticipant — unless Pi's registry filter (`--exclude-tools`) left both
actions out.

### The memo-consumption rule, and the mixed-install hazard it closes

The gate remembers a codemode it suspended and restores it at release. A lifted landing
**consumes** the memo: every remembered name that is a registered suspended builtin and lifted
there leaves the memo, restored when inactive (once — perk never adds a name the memo does not
hold) and forgotten when already active. An unregistered remembered name is retained.

The hazard: inside the restoration window an install that adds codemode back beside pending stage
removals commits no memo. Without consumption, the closing `agent_start` apply would keep the
stale entry, and a later user or host deactivation would be undone — by the next lifted
reconciliation (a restore-on-lift rule) or by the gate's exit (the read-write restore). With
consumption, the closing apply meets an already-active, lifted codemode and drops the entry;
nothing in the memo, and eligibility alone never activates. Pinned by `toolGating.test.ts`
("consumes the suspension memo", both openers and a `/tree` restore that already carries codemode)
and shown failing with consumption disabled (below).

### The settings source

Pi's builtin reads `pi.getSettings().codemode?.mode === "only" ? "only" : "on"`; perk reads it the
same way, inside `try/catch` — a throw or an absent `getSettings` is an unread mode, which never
lifts. A codemode factory's own `mode` option shadows the setting and is invisible to perk: only
test factories and the worker's factory pass options, and the worker passes `models` only.

## Observed offline evidence

Every suite ran on this branch against the installed Pi 1.1.0 (TAP summaries as observed, each
file on its own):

| Suite | Tests | Result | What it pins |
| --- | --- | --- | --- |
| `extension/substrate/toolPolicy.test.ts` | 24 | 24 pass | `READ_ONLY_STAGES`; the carve-out exposure; `strandedWriters` (registered / deferred / filtered / carve-out / query / blocked / mode-over-stage); `isEligible` per stage × landing; `gateSuspends`/`suspensionStep` (no suspension, restore once, memo consumed, unregistered retained, read-write arm unchanged); `hiddenDeclarationsFor`; the matrix row |
| `extension/substrate/toolGating.test.ts` | 50 | 50 pass | fake host: `on` in all six stages; `only` cohort vs nonparticipant (`plan` and `audit`) vs filtered registry; throwing / absent settings; child floor; worktree `/plan` toggle; `plan → implement → plan`; restoration window (both openers); the mixed case |
| `extension/substrate/toolMatrix.test.ts` | 5 | 5 pass | golden drift; `lifted_in`; both stranded views; the five carve-outs `model-only`/`nested: blocked`; `eligible` never lists `codemode` read-only |
| `extension/pi/perkTool.test.ts` | 8 | 8 pass | exposure census (model-only iff model-only kind or carve-out); the nested probe — `plan_draft` answers `Tool plan_draft not found`, no carve-out in `getCallableToolNames()` |
| `extension/substrate/discoveryNested.test.ts` | 2 | 2 pass | re-expressed: a nested `plan_draft` errors `Tool plan_draft not found` and never reaches `tool_call` |
| `extension/substrate/ownNamesActivation.test.ts` | 12 | 12 pass | re-expressed nested writer; the direct twin admitted; "codemode (A)" (implement × `only`) still suspended — the non-lifted control |
| `extension/substrate/codemodeLift.test.ts` | 17 | 17 pass | real sessions: 6 stages × `on`/`only` (census, script, draft loop) + 5 shared rows |
| `extension/substrate/mcpReadOnlyFloor.test.ts` | 5 | 5 pass | T1–T4 unchanged; T5: MCP-activated codemode lifted in a cohort `/plan` gate, the script's MCP call `BLOCKED` with the codemode parent id, `calls() === 0`; read-write reaches the server once |
| `extension/substrate/restorationWindow.test.ts` | 3 | 3 pass | guard, unedited |
| `just test-js-slow` | 1,044 | all pass (exit 0, 3 m 55 s wall) | the slow tier, `discoveryPilot.test.ts` and `stageExecutionE2e.test.ts` (worker `models: false`) included |

`codemodeLift.test.ts` took 20.8 s on its own (21.4 s in the first measurement), over the 20 s
membership rule, so it joined `SLOW_JS_TEST_FILES` in this change. Each session's first codemode
call loads the QuickJS sandbox.

### The real-session cells

Pi's builtin codemode is loaded as the CLI loads it (`{ name: "codemode", factory:
createCodemodeExtension(), builtin: true }`, no factory `mode`), with `settings.defaultTools:
["+tool_search", "+codemode", "+grep", "+find", "+ls"]` and `codemode.mode` per cell. Per cell, one
prompt runs four model calls: the codemode script, writer v1, `plan_review`, writer v2.

- **Census (first request):** `codemode`, `tool_search`, `plan_review` and the stage's writers
  (`objective_node` too in `objective-plan`) declared in both modes; `read`/`bash`/`grep`/`find`/`ls`
  declared in `on`, absent in `only`; `edit`/`write`/`perk_stage`/the unknown tool absent; no
  writer's description carries `Codemode:` while `read`'s does in `on`.
- **Script:** admitted — `tools.read` of a planted file, `tools.bash({ command: "ls" })`, and
  `tools.objective_stack_status` resolving to `{ ok: true, objective: "7", status }` in `plan`,
  `objective-plan`, `objective-refine` (in `objective-author`, `gist-author` and `audit` it rejects
  `tool not allowlisted`); refused at the hook — `tools.write` (`write is blocked (file
  modifications disabled)`), `touch script-x` (the veto wording; no file), the unknown tool
  (`tool not allowlisted`); absent from the sandbox — the writer, `plan_review` and
  `run_scout_wave` each throw a `TypeError` matching `/^tools\.<name> does not exist\./`. Every call
  that reached `tool_call` carried the codemode call's id; none for a model-only name; the codemode
  result `isError: false`.
- **Draft loop:** writer v1 `ok`; `plan_review` DENIED through the real door (`[providers] plan =
  "plannotator-plan"`, a fake Plannotator answering `plannotator:request` then `approved: false`),
  the text naming the writer; writer v2 `ok` with a distinct digest, the writer declared in that
  request. `audit` routes to the plan arm like `plan`; `objective-refine` imports the golden
  refinement context through its cold claim.
- **Shared rows:** nonparticipant `plan` × `only` suspended (not declared; a direct call `tool not
  allowlisted`; `plan_draft`/`read`/`bash`/`push_annotations` declared); nonparticipant `plan` × `on`
  lifted; nonparticipant `plan` × `only` with `excludeTools: ["push_annotations",
  "collect_draft_review_wave"]` lifted; cohort `plan` × `only` with `push_annotations`
  host-activated — declared (exposure `deferred`), codemode still lifted; cohort `plan` × `on`
  across `/reload` — codemode active before and after the next `agent_start`, every perk install
  kept it; the read-write control's script write lands.

### Shown failing against the pre-change policy

- `toolGating.ts` at the pre-change commit (policy kept): the five fake-host lift rows fail; the
  fail-closed row passes (a guard). `codemodeLift.test.ts`: 16 of 17 fail — the read-write control
  passes. `mcpReadOnlyFloor.test.ts` T5 fails; T1–T4 pass.
- The carve-out exposure reverted to `direct` (runtime lift kept): `codemodeLift.test.ts` 15 of 17
  fail (all 12 cells, the cohort deferred-member row, the registry-filter row, the read-write
  control's missing-member assertion); the nonparticipant and reload rows pass (they do not depend
  on the exposure).
- Memo consumption disabled: the `toolGating.test.ts` memo row and the `toolPolicy.test.ts`
  suspension-step row fail.
- The new `toolPolicy.test.ts` pins import `READ_ONLY_STAGES`/`strandedWriters`, which the
  pre-change module lacks; the carve-out exposure pin fails on `direct`.
- The 4.2 nested-writer rows, unmodified, failed against the new exposure (the observed `Tool
  plan_draft not found`, no `tool_call` event) — the converse direction, which is what prompted the
  re-expression.

## The deferred live leg (node 7.1)

A bounded protocol for 7.1's "planning composition per enabled codemode mode" row. Fresh host
process; PATH `pi` 1.1.0; a perk-initialized repo with the seeded `+tool_search`; codemode enabled
for the session (`--tools +codemode`, or `defaultTools: ["+codemode"]` in the user-scope settings
where the launcher forwards no Pi flags). One gated session per mode (`codemode.mode` `on`, then
`only`), each launched into a recorded read-only stage — bare `perk plan` (stage `plan`). A bare
`/plan` toggle records no stage and never lifts, so it is not a vehicle for this leg:

1. **Script batch.** Ask the model for one codemode script that batches `objective_stack_status`
   (on an objective with a stack, or the soft `no_objective` value), a `read` and
   `bash({ command: "git log -1 --oneline" })`. Pass: one codemode call, every nested call admitted,
   the query resolving to a structured `{ ok, … }` value.
2. **Refused write control.** Ask for a script that calls `tools.write`. Pass: the call rejects
   with `write is blocked (file modifications disabled)`; no file appears.
3. **Draft and revision.** Draft with the stage writer (a direct call — never via the script),
   deny the review, and revise. Pass: v1 and v2 land with distinct digests, the DENIED text names the
   writer, and codemode stays declared throughout.

A cell that cannot be run is recorded as NOT RUN with its reason, never as met.

## Deviations (dated)

All recorded at planning, operator decisions of 2026-10-21:

- (a) mode `only` lifts by the stranded-writer rule rather than staying suspended — ledger item 3's
  resolution.
- (b) the "proven useful through codemode scripts in real sessions" leg is deferred to 7.1 (above)
  — ledger item 6.
- (c) the lift family is every registry read-only stage, wider than the node text's
  "planning/refinement" — `audit` included, whose draft loop runs through the mode-over-stage
  `plan_draft` (reachable there, unsaveable — the `objective-refine` precedent) — ledger item 6.
- (d) `contexts/read-only.md` is unchanged: the writers leave Pi's callable set, and the nested
  refusal corrects any other script attempt.
- (e) the ledger gets item 3's resolution and a new item 6 in this change (item 5, node 2.2's,
  is 7.2's to enter).
- (f) the glossary terms **Codemode lift** and **Stranded writer** (code identifiers follow:
  `strandedWriters`, matrix `stranded_writers`); **Bounded writer** entered beside them.

## Residuals

- A codemode factory `mode` option shadows the setting and is invisible to perk (documented limit).
- In `only`, codemode's own description lists every callable tool, `edit`/`write` included —
  presentation only; the backstop refuses them.
- A script's `store()`/`load()` append `codemode-store` session entries and `image()` writes a temp
  file — outside the gate's worktree guarantee. The interactive builtin's `models.*` is model spend
  outside the read-only guarantee; there is no budget mechanism (the worker's factory passes
  `models: false`).
- Pi's `only` keeps a foreign `universal`/`research` direct tool (`ask_user_question`, web reads)
  script-reachable under the gate — Pi's semantics plus 4.2's foreign-posture decision, not a perk
  grant.
- Pi's `only` hides `read`/`bash` from direct calls by design — the user's selection.
- A discovery nonparticipant keeps `only` suspended in every gated stage while its mode-over-stage
  actions stay direct.

## `/learn` candidates (not authored here)

- `docs/learned/pi/tool-loadout.md`: codemode `only` hides every declared direct tool;
  `model-only` is Pi's "declared, never callable through another tool"; the two refusal oracles (a
  script's sandbox missing-member `TypeError` before any call; agent-core's `Tool <name> not found`
  for `ctx.executeTool`) both precede the `tool_call` hook.
- Test craft: drive a codemode script that wraps each nested call in `try`/`catch` and returns one
  JSON record; load Pi's codemode exactly as the CLI does (no factory `mode`) so the settings path
  is what is tested; the QuickJS sandbox costs about a second per session (a slow-tier signal).
- Test craft: the harness's headful UI context lacks `setWorkingMessage`, so headful prompt turns
  log `target.ui.setWorkingMessage is not a function` (stderr noise only).
