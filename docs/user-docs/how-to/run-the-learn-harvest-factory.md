# How to run the learn-harvest factory

Mine your accumulated `docs/learned/` knowledge as lenses into the code and curate ONE bounded
improvement objective by running the learn-harvest objective factory.

## Steps

1. **Start the factory.** From the shell run
   [`perk learn harvest`](../reference/cli.md#perk-learn-harvest) (cold-only — there is no warm
   `/learn-harvest`). Bound the run with a repeatable `--from` (a file or directory inside
   `docs/learned/`), e.g. `perk learn harvest --from docs/learned/workflow`; the default is the
   full corpus.
2. **It gathers at one revision.** The door fast-forwards the checkout you run it from (normally
   the main checkout; `--no-sync` skips it), gathers the selected `docs/learned` docs into a
   run-scoped manifest, and opens a **read-only objective-authoring session** that reads the docs
   as lenses into the code — following each doc's source pointers and verifying its claims on the
   real checkout.
3. **It curates ONE objective — or honestly stops.** The session grounds every mined opportunity,
   ranks the survivors, and drafts one bounded improvement objective (a single theme, ≤ 8 roadmap
   nodes, everything else recorded in a backlog-with-reasons). When nothing survives grounding it
   reports the evidence and stops — a **zero-opportunity outcome**, never a placeholder objective.
4. **Review and approve.** The objective rides the normal review-first authoring loop; approval
   saves (creates + activates) it like any other objective.
5. **Drive the nodes.** Generate per-node plans with
   [`perk objective plan`](../reference/cli.md#perk-objective-plan-number) and take each through the
   ordinary implement → submit → land spine.

> **It is an objective factory.** Like [`/objective-plan`](../reference/in-session.md#objective-plan)
> is a plan factory, `perk learn harvest` produces an *objective* — it never edits `docs/learned/`
> and never writes code.

**The phase-1 single-lane ceiling:** the door accepts a selection that partitions to exactly one
lane (one `docs/learned/<category>/` group, at most 8 docs). A larger selection is refused with
`selection_too_large` — narrow it with `--from` (multi-lane harvests arrive with the phase-2
analyst wave).

---

← Back to the [how-to router](index.md).
