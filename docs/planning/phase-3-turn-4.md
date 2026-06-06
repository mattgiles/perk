# Phase 3 · Turn 4 — make `/objective-save` drive the structured save

GitHub plan **#112**. `/objective-save` was the lone outlier among perk's warm workflow commands: a
**dead-end redirect**. Issue #109's fix turned the command into a gate-flip + a printed message
("call the `objective_save` tool with your `prose` and `roadmap`. Nothing was written yet.") — but
that message is addressed to the *agent* while a *human* typed the command, so from the user's seat
it read as "do it manually," and nothing happened.

## The missed move

The redirect's reasoning was sound but stopped one step short. A plan *is* its prose (so `/plan-save`
can scrape one message and save), but an objective's roadmap is **structured data** that can't be
scraped — so the command can't carry it inline. The conclusion drawn was "therefore the command
can't save." The missed move: every *other* perk warm command (`/address`, `/objective-plan`,
`/objective-reconcile`, `/learn-docs`, `/learn`) doesn't do the work in the handler either — it
**drives the session** via `pi.sendUserMessage(guidance + bindingSuffix(...))`. `/objective-save`
was the lone command that dead-ended instead of driving. That's the bug.

## Decisions (locked)

- **Rewire `/objective-save` to the sibling driving pattern.** Exit the read-only gate (so the
  `objective_save` tool is reachable), notify/log on the `ctx.hasUI` split, then unconditionally
  `pi.sendUserMessage(objectiveSaveGuidance(title) + bindingSuffix(ctx.cwd, "stage:objective-author"))`.
  Headless drives the turn too (like `/address` / `/objective-plan`, unlike `/learn-docs` which
  early-returns because its durable artifact is the pre-gathered inbox) — `/objective-save` has no
  pre-gather artifact, so the only useful action is the gate-exit + drive.
- **Structured-roadmap integrity preserved.** The durable write still flows through the
  `objective_save` tool, never a scrape. The command is a trigger, not a save path — it performs no
  GitHub mutation itself.
- **Add a pure, exported `objectiveSaveGuidance(title?)`** mirroring `learnDocsGuidance` /
  `factoryGuidance`: terse numbered instructions to call the tool with `prose` + the structured
  `roadmap`, render the `title` when given (else note it is optional), guard on
  decision-completeness, and never hardcode a skill pointer (that rides the binding suffix).
- **Use the `stage:objective-author` binding trigger** — the binding registered for
  `perk-objective-author` (the skill that owns the save step), surfacing it warm-from-anywhere
  mirrors `/objective-plan`'s use of `stage:objective-plan`.
- **Remove the now-dead `extractObjectiveMarkdown`** scrape helper (referenced only by its own
  definition + test) — keeps the module honest: no vestigial scrape affordance contradicting "the
  command never scrapes."
- **Re-point the command tests to the driving shape.** The two `invokeCommand("objective-save")`
  harness tests are removed (the handler now calls `pi.sendUserMessage`, which the offline keyless
  harness can't service — exactly why the sibling driving commands aren't exercised via
  `invokeCommand`). Replaced by a registration + headless-safe test (mirroring `/objective-plan`)
  and pure `objectiveSaveGuidance` unit tests. The three `objective_save` **tool** tests stay
  unchanged.
- **Same-turn doc updates:** `shared/contracts.md` (cross-plane behavior), the in-session
  `OBJECTIVE_AUTHORING_CONTEXT`, and `skills/perk-objective-author/SKILL.md` all corrected to say
  both the direct tool call and `/objective-save` reach the same place (neither hand-writes roadmap
  YAML).

## Out of scope

- The non-upsert re-save gap (`create_objective_issue` idempotent-on-`run_id`-but-no-update,
  documented in `docs/learned/workflow/objective-lifecycle.md` / `plan-save-surfaces.md`) is
  untouched — this is TS command behavior + docs only.

## Outcomes

Landed as planned, no deviations. All five planned files changed plus this turn doc; the
`objective_save` tool path and the Python cold door were untouched. `just ci` green.
