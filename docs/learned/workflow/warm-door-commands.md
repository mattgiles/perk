---
title: Warm-door commands — the four laws (visible commands vs gated write tools, no direct GitHub mutation, render every cold-door outcome, guidance-named tools in every stage scope)
read_when: You are building or fixing a warm perk slash-command (/plan-save, /address, …), debugging a door that dead-ends or false-succeeds, a drive naming a stage-scoped tool, or a human-facing gesture.
cluster: doors-and-launch
---

# Warm-door commands

perk's warm doors are the TS slash-commands registered through `registerPerkCommand`
(`extension/substrate/command.ts`) and their sibling tools, in front of the cold Python doors that
own every durable GitHub mutation. Four laws govern them; breaking any one yields a **false
success** or a **dead end** no single file reveals. The cold-door client's decode/envelope
semantics are owned by `docs/learned/workflow/cold-door-client.md` — this doc only points there.

## Distillation

- **Law 1 — commands stay visible while write tools are gated.** No write-capable tool rides the
  gate-ON allowlist; a command delegates directly only when a validated artifact / committed state
  carries the full payload, else it writes nothing and drives the session — "Law 1".
- **Law 2 — warm handlers never issue a GitHub mutation directly**: `runColdDoor` with a validated
  payload, or `pi.sendUserMessage` guidance so the model works through the canonical tool — "Law 2".
- **Law 3 — render EVERY cold-door outcome** — success / failure / absent, nonfatal sub-step failure
  included — through `report()`, which owns the headless fallback — "Law 3".
- **Law 4 — every tool a drive's guidance names must be active in every stage the drive can land
  in**; a stage-list widening audits the dispatch arms it makes reachable — "Law 4".
- Human-facing gestures are emitted deterministically by the door, never left to model-facing
  guidance — "Human-facing gestures belong in the door".

## Law 1 — visible commands, gated write tools, the payload test

Gate on, `extension/substrate/toolGating.ts` installs exactly `gatedToolsFor(stage)` —
`READ_ONLY_TOOLS` (builtins + the carve-outs justified in place; never enumerate them elsewhere) or
the refinement stage's own selection. **No save/mutation tool ever rides the gate-ON set**; a custom
tool is hidden unless carved in; a `pi.registerCommand` command stays **visible regardless of
mode**. A gated `/command` is thus often the only save affordance the agent sees, and only a human
gesture toggles the gate (`/plan`, `Ctrl+Alt+P`: `installPlanMode`, `extension/pi/v1/plan.ts`).

**The payload test.** Can the command *carry or recover* the tool's full payload? Recovery is
artifact-first. A plan is its prose, so `/plan-save` resolves the validated `plan-draft` artifact →
explicit reviewed text → transcript scrape (`resolvePlanSource`, `extension/authoring/plan/source.ts`
— legitimate because prose can live in one assistant message). An objective's roadmap is
structured data no message can carry, so `/objective-save` saves **only** a validated
`objective_draft` artifact (`objectiveApprovalSave`, `extension/authoring/objective/save.ts`); with no
draft it writes nothing, exits the gate if active (the on-ramp) and drives the structured save
through the tool. Never half-write — and never merely *print an instruction to the agent*: a human
typed the command, so it reads as "do it manually" and nothing happens. When a command's behavior
flips, delete the dead helper and correct the surfaces that describe it in the same turn —
`shared/contracts.md`, the in-session context constant (`OBJECTIVE_AUTHORING_CONTEXT`,
`extension/authoring/objective/prose.ts`), the owning `SKILL.md`.

**Gate on the effective mode floor.** Warm-minted sessions leave `perk:workflow-state.mode`
undefined (the mint arm of `establishSessionIdentity`, `extension/session/lifecycle.ts`, appends
identity fields only) and `isReadOnlyMode` treats anything but the literal `"read-only"` as
writable. Deny only that explicit floor; never require a positive `"read-write"` token the warm
path never writes (`docs/learned/workflow/mergeability-and-conflict-resolution.md` § "Two
authorization gaps only review caught").

**Enter is distributed, exit rides the save.** A door seeding a read-only turn enters with
`if (!gating.isActive()) gating.enter(ctx)` — after input resolution, before `sendUserMessage` — so
the seeded turn picks up the read-only injections and a cold-door `mode: read-only` handoff is never
double-appended (`/objective-plan`, `/objective-refine`, the `--plan` cold start). Exit is owned by
the approval→save seam (`saveThroughApprovalGate`, `extension/authoring/review/approvalGate.ts`:
exit only after a successful save while read-only), the sanctioned no-save exits
(`/implement-here`), the draftless on-ramp arms and the `/plan` toggle. A seeding door adds **zero**
exit logic, or it forks the mode lifecycle.

## Law 2 — no direct GitHub mutation: cold door or drive the session

Composing a `gh`/API mutation in TS never happens (`extension/coldDoorGuard.test.ts` pins that
perk-CLI execs leave only through `extension/substrate/coldDoor.ts`). Two shapes remain:

- **Direct cold delegation (artifact-first).** A validated artifact or committed workflow state
  carries the payload, so the handler runs the cold door synchronously through `runColdDoor`
  (`/plan-save` via `approvalSave`, `/gist-save`'s valid-draft arm via `gistApprovalSave`, `/land`
  via `landPr` — keyed off the worktree's plan-ref).
- **Session-driving.** The model must produce the payload, so the handler sets up state and injects
  `pi.sendUserMessage(<x>Guidance(...) + bindingSuffix(ctx.cwd, "<trigger>"))`; the model works
  through the canonical tool, which carries the structure. The command itself mutates nothing.

Driving-command conventions:

- **Guidance is a pure, exported `*Guidance(...)` function** rendering a `prompts/` template
  (`factoryGuidance`, `reconcileGuidance`, `extension/authoring/objective/prose.ts`) — unit-testable
  offline. **No hardcoded skill pointer in the body** — it rides `bindingSuffix(cwd, trigger)`
  (`extension/substrate/bindingDelivery.ts`) with the owning `stage:<id>` / `command:<name>` trigger.
- **Headless behavior is a decision.** Report through `report()` and drive in both branches —
  unless the command leaves a durable artifact a headless run can consume: the learn factory door
  (`registerLearnFactoryDoor` — `/learn-docs`, `/learn-code`) gathers the inbox and returns headless.
- **A terminating tool can still drive the next pass.** `terminate: true` only skips the automatic
  follow-up call; `pi.sendUserMessage(msg, { deliverAs: "followUp" })` is a separate deliberate turn
  — orthogonal mechanisms. One helper serves both surfaces and branches on `ctx.isIdle()`: idle
  (the command) → plain `sendUserMessage`; streaming (the tool's `execute`) → `deliverAs: "followUp"`.
  Keep the pure impl drive-free (`landPr` vs `driveReconcileAfterLand`, `extension/pi/v1/delivery/land.ts`).
- **Self-healing drives are gated on a structured sub-result and capped.** `/submit`'s conflict
  drive (`decideConflictFollowUp`, `extension/delivery/submit.ts`) fires only on
  `ok && mergeable === false`, bounded by `conflict_resolution_attempts` against
  `CONFLICT_RESOLUTION_ATTEMPT_CAP` and reset on every clean outcome.
- **Fresh-context waves are still session-driving.** `/pr-review` drives the parent, whose guidance
  names `run_pr_review_wave`; children report, the parent posts once (`post_pr_review`) —
  `docs/learned/workflow/report-waves.md`.

**Test shape.** Registration + headless-safe load (`loadPerkSession({ headful: false })`); pure
`*Guidance` unit tests (tool + required args named, optional args rendered/omitted, no skill-pointer
string); drive-helper spy tests over the `isIdle()` branches and the not-called arms;
`spyInjections` / `runCommandHandler` (`extension/testing/harness.ts`) when the handler itself must
run under `invokeCommand` — the keyless harness cannot service an injected turn.

## Law 3 — render EVERY cold-door outcome

A warm door wrapping a cold door that returns a **structured non-fatal sub-result** owns rendering
every outcome — success / failure / absent. A truthy ternary collapsing "failed" into `""` makes a
real failure indistinguishable from "nothing to do": a silent partial failure that *looks like an
unwired feature*. When "X isn't working", confirm whether X **ran and was discarded** before
concluding it never fired.

- **One text field, two doors.** Render the three-way branch (`linked === true` / `false` / absent)
  into one `content[0].text` both the tool and the `/command` consume (`renderSavePlanOutcome`,
  `extension/pi/v1/plan.ts`) — one site fixes both paths.
- **Severity ladder.** A nonfatal sub-step failure on a successful op is `warning` (not `error`: the
  op succeeded; not `info`: something needs attention): `!ok → error / linked === false → warning /
  else info`.
- **Headless fallback is the seam's job.** Every user-facing notice goes through `report()`
  (`extension/surfaces/report.ts`): headful → `ui.notify(headline, severity)`; headless →
  `console.error` of the full line at every severity. A bare `ctx.ui.notify` loses the headless
  signal (and fails the surfaces guard).
- **Boundary discipline.** The sub-step failure never alters the primary op's control flow:
  `details.ok` stays `true`, `terminate` stays `true`, the gate exit still fires. The standard is
  **loud-but-non-fatal + idempotent manual re-run**; no in-call retry loop around the mutation.
- **Typed refusals are rendered, never re-derived** — branch on the client's `errorType` (the
  `/stack-review-browser` `no_objective` arm, `extension/pi/v1/codeReview/stack.ts`); partial-failure
  detail follows `cold-door-client.md`'s fail-arm narrowing or is dropped.
- **Tests capture severity, not just text** (`notifyEvents` beside `notifies`,
  `extension/testing/harness.ts`); a fallback path asserts the stderr line itself.

## Law 4 — guidance-named tools in every stage scope

Gate-OFF sessions are stage-scoped: `STAGE_TOOLS` (`toolGating.ts`) subtractively filters the scoped
universe `PERK_TOOLS ∪ BORROWED_TOOLS` per registry stage. A drive names companion tools by name, so
**every tool a drive's guidance names must be in `STAGE_TOOLS[stage]` for every stage the drive can
land in**, or it dead-ends (observed live: a post-land auto-drive in a worktree session whose list
had filtered the reconcile trio off).

- **The drive-coverage guard** (`extension/substrate/stageTools.test.ts`): the static `DRIVE_COVERAGE`
  table pairs each gate-OFF drive with every stage it can land in; `referencedScopedTools`
  word-boundary-scans the rendered guidance (all optional params set) against the scoped universe;
  every name must be in each listed stage. A row extracting **zero** names fails unless it opts out
  with `namesNoTools: true` — a tool-free drive still joins the table. Gated-landing drives are
  excluded: gate-ON ignores stage lists (the gated-stage test + the `READ_ONLY_TOOLS` exact-set pin
  cover that surface).
- **Maintenance.** A new drive joins the table; a changed stage list must satisfy every drive that
  can land there. When the scanner demands a tool, first ask whether the prompt should stop naming
  gesture tokens (retry guidance belongs on human-facing surfaces) before widening. The scan is
  word-boundary, so natural-language use of a tool-named word ("before the browser is **ready**")
  reads as the `ready` tool — reword the prose ("browser readiness"), never widen the stage list;
  other risky bare words: `land`, `learn`, `submit` (#2522).
- **Widening audits reachability.** When stage S gains tool T, audit T's execute core for
  stage-conditional dispatch — an arm that assumed "T can't run at S" is now live. A "no routing
  change" non-goal is settled by what the change makes reachable, never by intent.
- **Zero-argument, selector-dependent tools never ride unbound (main-root) sessions** — the cached
  plan selector can point at a different plan than the one the session launched for.
- **Plan census.** A plan adding any warm tool names its `toolGating.ts` rows (`PERK_TOOLS` + the
  stage lists) beside its bindings/skills census. `PERK_TOOLS` is pinned set-equal to what a session
  registers, so the census doubles as a dormancy enforcer: a dormant-by-design tool rides the same
  PR as its registration (`report-waves.md`).

## Human-facing gestures belong in the door

Anything a human must *act on* — a command to run, a URL, a checkout line — is emitted
deterministically on a human-facing surface **by the door** (loud `report()` + a clipboard copy),
never left inside model-facing guidance. The live shape splits: `handleHunkLaunch`
(`extension/pi/v1/codeReview/checkout.ts`, serving `/pr-review-terminal`) prints the launch line,
copies it (`extension/substrate/clipboard.ts`) and auto-launches raced against a soft deadline —
non-blocking — while the *wait for the human, degrade only on their explicit choice* rule lives in
the injected `pr-review-terminal` guidance.

**Key the rendered gesture on the door's STRUCTURED fact**, never a rendered suffix
(`extension/pi/v1/delivery/address.ts::renderAddressHandoff` keys on `PublishedChange.delivery`,
contracts §8.47). Make the worker emit an explicit value for the common case
(`delivery: "incremental"`) so absent ≠ default, and a version-skewed envelope degrades to "confirm
first", never the destructive gesture; the skill relays the emitter's line verbatim; the unknown
arm diagnoses truthfully (ABSENT vs UNRECOGNIZED, one fail-safe tail) (#2471).

## The `registerPerkCommand` wrapper

Every warm perk command registers through `registerPerkCommand` (vendored `/btw` is the one direct
`pi.registerCommand`): one entry toast — `perk: <cmd> — running…`, `info`, via `report()` —
synchronously before the first `await`, then the handler awaited with no try/catch. Test
corollaries: notify-count pins gain one `info` entry; a `.find((m) => m.includes("<cmd>"))` finder
now matches the toast and passes vacuously — grep **all** finder sites (the status line carries `·`,
the toast does not); a synchronous spy cannot prove an `await` (yield inside the handler, flag after
the yield); cross-door **ordering** rides the fake-router `argvFile` capture
(`extension/testing/harness.ts`).

## History (dated by PR)

- `/objective-save` scraped a message and minted node-less objectives while reporting success
  (#109/#110); its first fix printed an instruction to the agent (#112/#113).
- `/plan-save` rendered only the `linked === true` branch of the objective-node sub-result, so a
  failed `planning → in_progress` advance read as "nothing to do" (#124/#126).
- The `/objective-sync` retained resolver required an explicit `"read-write"` token and refused every
  warm session. Two dogfood runs of the retired `/review` door, whose hunk launch line lived only in
  guidance, set the gesture rule.
- Adding `plan_review` to the objective-save stage (forced by the guard) made a plan-arm fallthrough
  reachable from an objective session (#2028); `/stack-review-browser` set the warm/cold parity
  template — cold `--stack` checkout via `runColdDoor`, one parameterless opener, entry-neutral
  guidance (#2033).
- The `/address` hand-off line keyed on a rendered publication suffix, which proves nothing when
  absent; it was re-keyed on the structured `delivery` field with an explicit incremental value
  (#2468).

## Cross-references

- `extension/substrate/toolGating.ts` — `READ_ONLY_TOOLS` / `gatedToolsFor`, `STAGE_TOOLS`,
  `PERK_TOOLS`; `extension/substrate/stageTools.test.ts` — the drive-coverage guard
- `extension/substrate/coldDoor.ts` + `docs/learned/workflow/cold-door-client.md` — the client;
  `docs/learned/workflow/mergeability-and-conflict-resolution.md` — the mode floor, the capped drive
