---
title: Warm-door commands — the read-only gating trap, drive-the-session discipline, and rendering every cold-door outcome
read_when: You are building or fixing a warm perk slash-command (`/plan-save`, `/objective-save`, `/address`, `/learn-docs`, …), debugging a command that dead-ends or false-succeeds, or wiring how a warm TS door renders a cold Python door's structured sub-result.
---

# Warm-door commands

perk's warm doors are the TS slash-commands registered via `pi.registerCommand` (and their sibling
custom tools). They sit in front of cold Python doors (`perk plan-save`, `perk objective-save`, …)
that own the durable GitHub mutations. Three cross-cutting disciplines govern how a warm command must
behave; getting any one wrong produces a **false-success** or **dead-end** that no single file
reveals.

## The read-only tool-gating trap (why command/tool pairs are asymmetric)

In a read-only session, `extension/toolGating.ts` calls `pi.setActiveTools(READ_ONLY_TOOLS)`
(`read`/`grep`/`find`/`ls`/`bash`) which **hides every custom tool**. But `pi.registerCommand`
commands stay **visible regardless of mode**. So a canonical tool gated behind read-only is
invisible while its sibling `/command` is the *only* save affordance the agent can see.

This is the structural reason a warm command and its tool are **not symmetric**, and why you cannot
toggle the gate from inside a model turn (`/plan off` is a user/keyboard action — `planMode.ts`
registers it as a command + `Ctrl+Alt+P`). The danger: if the visible command cannot carry the
hidden tool's full payload, it becomes a **trap that produces junk and returns false success**.

**Plan-vs-objective asymmetry — the diagnostic test.** A *plan is its prose*, so `/plan-save` can
legitimately scrape one assistant message and save inline. An *objective's roadmap is structured
data* that cannot be scraped from a message — so `/objective-save` can never validly save. Before
treating a command/tool pair as symmetric, ask: **can the command carry the tool's full payload?**
If not, it must not half-write.

## Two correct shapes when the command can't carry the payload

When a command-fallback is *structurally* incapable of the full write, never let it half-write.
There are two correct shapes, both of which preserve the read-only→read-write "one gesture"
ergonomics without exposing the tool during read-only (which would break the no-writes invariant):

- **On-ramp (write nothing, redirect):** flip the read-only gate so the real tool becomes visible,
  and emit just-in-time guidance redirecting to the tool. Kills the false-success signal. (This is
  what `/objective-save` became in #109/#110 — it had been minting node-less garbage objectives
  while reporting `"Saved objective #N"`.)
- **Drive-the-session (inject a driving message):** the strictly better move when a downstream skill
  owns the step. See next section.

A redirect that merely **prints an instruction to the agent** ("call the `objective_save` tool with
your prose and roadmap") is itself a bug: a *human* typed the command, so the printed instruction
reads as "do it manually" and nothing happens (#109's regression, fixed in #112/#113).

## Warm commands DRIVE the session; they don't dead-end or do work in the handler

The durable pattern shared by **every** warm perk workflow command (`/address`, `/objective-plan`,
`/objective-reconcile`, `/objective-save`, `/learn-docs`, `/learn`): the handler does **not** do the
durable work itself. It **drives the session** —

```
pi.sendUserMessage(<pureGuidance>(...) + bindingSuffix(ctx.cwd, "<trigger>"))
```

The handler's only job is to set up state (e.g. `gating.exit(ctx)` to make a gated tool reachable)
and inject guidance; the **model then performs the work by calling the canonical tool**, which
carries the structure. Structured-write integrity is preserved because the durable write still flows
through the tool, never a scrape — the command performs no GitHub mutation itself. When you find a
perk command that *prints an instruction to the agent* instead of injecting a driving message,
that's the bug — convert it to the driving pattern.

Conventions that generalize:

- **Factor the injected text into a pure, exported `*Guidance(...)` function** (mirror
  `learnDocsGuidance` / `factoryGuidance`): terse numbered/bulleted `[...].join("\n")`. Pure +
  exported so it is unit-testable offline.
- **Never hardcode a skill pointer in the guidance body** — it rides `bindingSuffix(cwd, trigger)`.
  Use the `stage:<id>` trigger of the skill that owns the step (e.g. `stage:objective-author`),
  surfaced warm-from-anywhere like `/objective-plan` uses `stage:objective-plan`.
- **Headless behavior is a deliberate choice, not boilerplate.** Drive the turn unconditionally
  (notify on `ctx.hasUI`, else `console.error`, then `sendUserMessage` in **both** branches) —
  **unless** the command produced a durable artifact a headless run can leave behind. `/learn-docs`
  is the exception: it early-returns on headless because its durable artifact is the pre-gathered
  inbox.

**Test-coverage shape for driving commands.** They CANNOT be exercised via `h.invokeCommand(...)` in
the keyless offline harness, because `pi.sendUserMessage` triggers a real model turn the harness
can't service. Cover them with (a) a **registration + headless-safe test** (load `headful: false`,
assert `h.registeredCommands().includes("<cmd>")`), and (b) **pure `*Guidance` unit tests** (the
rendered text names the tool + required args, renders/omits optional args like `title`, and contains
no hardcoded skill-pointer string). The canonical tool tests remain the behavioral coverage.

## A terminating surface can drive the *next* pass

The section above covers "warm commands DRIVE the session." This adds the case where the driving
surface is **terminating** (the `land` tool returns `{ terminate: true }`): `/land` (and the `land`
tool) auto-drives `/objective-reconcile` instead of printing a copy-pasteable nudge.

- **`terminate` + `followUp` compose.** `terminate: true` only skips the *automatic* follow-up LLM
  call; an injected `pi.sendUserMessage(msg, { deliverAs: "followUp" })` is a *separate* deliberate
  new turn delivered once the agent has no more tool calls. So a terminating tool can still hand off
  into a fresh driven turn — the two are **orthogonal mechanisms**, not in conflict.
- **Delivery mode branches on `ctx.isIdle()`.** One shared helper serves both surfaces: idle (the
  `/land` *command* path) → plain `pi.sendUserMessage(msg)` (immediate turn); streaming (the `land`
  *tool* `execute` path) → `deliverAs: "followUp"`. `isIdle()` lives on the base `ExtensionContext`
  shared by tool-`execute` ctx and command-handler ctx.
- **Reuse the guidance, don't re-invoke the slash command.** Inject
  `reconcileGuidance(String(n)) + bindingSuffix(cwd, "command:objective-reconcile")` — byte-for-byte
  what `/objective-reconcile` injects — rather than sending literal `"/objective-reconcile #5"` text.
  Avoids relying on slash-command expansion of an injected message and skips redundant re-resolution
  (the land result already carries `objective.number`). Required exporting the previously
  module-private `reconcileGuidance` from `objectivePlan.ts` (no circular import: `objectivePlan.ts`
  does not import `land.ts`).
- **Keep the pure-impl function drive-free.** `landPr` merges / sets-marker / builds text and
  returns; the drive lives in a *separate* exported helper called by both `execute` and the command
  handler — preserving the pure function as directly unit-testable. The drive condition mirrors the
  old nudge condition exactly (`ok === true`, objective present, `number !== null`,
  `nodes_marked.length > 0`), so non-objective plans / skipped node-marks drive nothing.

**Test-shape consequence.** Once `execute` routes through the drive helper, it can **no longer** be
harness-routed via `h.invokeTool(...)` (it fires a real model turn the keyless offline harness can't
service — same limitation as `invokeCommand` on driving commands, already noted above). Replace it
with (a) a **direct pure-function unit test** for the merge/report path (a stub `pi` whose `exec`
resolves a fixture + a minimal `ctx` over a `scaffoldRepo()` cwd, asserting on `result.details` +
success text), and (b) **drive-helper decision/delivery spy tests** (a spy `pi.sendUserMessage`
recording `{ content, options }`: no objective → not called; failed land → not called; idle → called
once with `options` undefined; streaming → called once with `options.deliverAs === "followUp"`). The
non-driving land tests stay on the harness because their fixtures short-circuit the helper.

**`/pr-review` is a different driving shape.** It does **not** drive the same session — it spawns a
fresh-context subagent that posts its own review. See `docs/learned/pi/subagents.md` for that
orchestration (project-vs-builtin agents, child-posts-own-mutation vs read-only-child-parent-mutates).

## A warm door must render EVERY cold-door outcome, not just the success case

When a warm TS surface wraps a cold Python door that returns a **structured non-fatal sub-result**,
the warm door owns rendering **every** outcome of that sub-result — success / failure / absent — not
just the happy path. A truthy/falsy ternary that collapses "failed" into `""` is the trap: it makes
a real failure indistinguishable from "nothing to do", a textbook **silent partial failure** living
entirely in the warm door.

This was the `/plan-save` objective-node bug (#124/#126). The Python cold door correctly attempted
the node `planning → in_progress` advance and reported it as `objective_node: { linked, node, status,
error }`. But the warm door only rendered the success branch
(`linkSuffix = nodeLink?.linked ? "… → in_progress" : ""`), so a `linked: false` failure rendered as
empty — the contract's "warn + retriable" signal never reached the user. The fix was a **three-way
branch** over `nodeLink` (`linked === true` / `linked === false` / `null`).

- **One text field, two doors.** Feed that three-way result into a single `content[0].text` that
  BOTH surfaces (the `plan_save` tool and the `/plan-save` command) render — so fixing one site
  fixes both paths at once. Reach for this "one text field, two doors" shape deliberately.
- **Severity mapping.** A non-fatal sub-step failure on an otherwise-successful op is **`warning`**
  (not `error` — the primary op succeeded; not `info` — something needs attention). The command
  computes `!ok → error / linked===false → warning / else info`.
- **Headless mirror.** Mirror `warning`/`error` to `console.error` in the `!ctx.hasUI` branch so
  headless runs aren't silent either. Rule: **any user-facing notify in an extension needs a
  headless `console.error` fallback for non-info severities**, or headless agents lose the signal.
- **Boundary discipline.** A failed sub-step must **not** alter the primary op's control flow:
  `details.ok` stays `true`, `terminate` stays `true`, the read-only→read-write `gating.exit` still
  fires. The save genuinely succeeded; only the link is loud-but-non-fatal. Don't leak a
  cosmetic/secondary failure into success semantics.
- **Test-harness note.** When a fix's correctness hinges on a UI attribute the harness drops (the
  `fakePerk`/`loadPerkSession` harness captured notify *messages* but not *severity*), extend the
  capture (a parallel `notifyEvents: {message, severity}[]` alongside `notifies: string[]`) rather
  than asserting only on the surviving substring.

perk's standard for the sub-step failure itself is **loud-but-non-fatal + idempotent manual
re-run** — the rendered warning enables the retry. Deliberately *not* added: an in-call retry loop
around the GitHub mutation.

## Honesty hygiene when converting a command

When converting away from a scrape-based command, **delete the now-dead scrape helper** (e.g.
`extractObjectiveMarkdown`, referenced only by its own def + test). Leaving a vestigial scrape
affordance contradicts "the command never scrapes"; tsc/Biome catch the orphaned import. And when a
command's behavior flips, the surfaces that *describe* it drift together and must be corrected in the
same turn: `shared/contracts.md`, the in-session context constant (e.g. `OBJECTIVE_AUTHORING_CONTEXT`
in `objectiveAuthor.ts`), and the owning `SKILL.md`.

## Diagnosis meta-lesson

A swallowed warm-door failure *looks* like an unwired feature. The #126 bug looked like
"node-advance isn't wired," but the advance *was* automatic and on `main`; the failure was discarded
downstream in the warm door. When "feature X isn't working," confirm whether X **ran and was
discarded** before concluding it **never fired** — trace the full handoff → cold-door → warm-door
chain.

## Cross-references

- `extension/planSave.ts` — `savePlan`, the three-way `nodeLink` render, the "one text field, two
  doors" shape
- `extension/objectiveSave.ts` — the on-ramp / drive-the-session conversion (dead `extractObjectiveMarkdown`)
- `extension/toolGating.ts` — `READ_ONLY_TOOLS`, the gate that hides custom tools but not commands
- `extension/planMode.ts` — `/plan off` / `Ctrl+Alt+P` (the gate is a user gesture, not a turn action)
- `docs/learned/workflow/plan-save-surfaces.md` — the two-surface fidelity gap + `handoff_extra` carrier
- `docs/learned/workflow/objective-lifecycle.md` — the authoring/save loop the driving commands feed
- `docs/learned/workflow/skill-bindings.md` — `bindingSuffix` (the skill pointer the guidance rides)
- `docs/learned/pi/context-injection.md` — the conditional inject-and-strip lifecycle
- `docs/learned/pi/subagents.md` — the spawn-fresh-context driving shape `/pr-review` uses
- `extension/land.ts` — `landPr` (drive-free) + the separate drive helper; the terminating-drive case
