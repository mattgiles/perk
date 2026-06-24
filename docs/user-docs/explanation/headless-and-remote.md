# Headless and remote: how it works, and how proven it is

[How perk thinks](./how-perk-thinks.md) establishes the headless model in one line: there is no
separate headless workflow — headless is simply the cold door pointed at a remote target. This page
assumes that model and goes deeper, on two fronts that matter once you actually lean on the surface:
**how the pieces fit together**, and **how proven each of them is.** The maturity story here is
load-bearing — read it before you depend on a remote run.

## How the pieces actually fit

The thing that makes a remote run legible is a durable correlation key. When perk dispatches a stage,
it writes a **dispatch record** — `scratch/runs/<run_id>/dispatch.json` — that ties a perk `run_id` to
the plan, the stage, and the triggered GitHub Actions run. That record is the spine everything else
hangs off: the supervisor reads it to know what is in flight, and `perk workflow run list` reads it to
render the table you watch. Nothing about a remote run lives in a terminal you have to keep open.

That is the deliberate shape: **coordination happens through GitHub, not through a watched process.**
A dispatched stage reports its progress and outcome back as PR comments and checks — the canonical tier
from the mental model — so the run is observable by anyone, from anywhere, without a console to stare
at. The local supervisor and the remote worker never talk directly; they meet in GitHub.

On top of that substrate sits the supervisor, `perk objective run`. Its defining property is that it is
**deterministic** — it does no agentic reasoning. It reports the budget, advances the backlog by exactly
**one autonomously-safe step**, and stops. It will dispatch the next ready `implement`/`address` step
remotely, or pause cleanly at a boundary that needs a human (a plan is required, a PR is ready for
review, a run is still in flight), but it **never lands** — readying and merging a PR stays a human act.
This is a design choice, not a limitation: a scheduler that loops unattended must be predictable, so the
judgement is kept on the human side of the line and the machine side is kept boring.

## The maturity story (the load-bearing caveat)

Here is the honest state of the remote surface: it is **declarative-correct but execution-untested.**

The runner artifact (`perk-run.yml`) and the worker entrypoint are wired, declaratively complete, and
unit-tested — the pieces are all in place and each piece is checked in isolation. What has **not** been
proven is the live, end-to-end chain: a real `dispatch → checkout → setup → drive` run, start to finish,
on an actual CI runner. No test and no dogfood run executes that whole chain; it waits on a live
`--remote` smoke run to exercise it for real.

This is exactly the boundary that `perk doctor workflow smoke-test` sits on. It proves the **wiring** —
that a run can be dispatched, that the runner starts, and that its secrets are readable. It deliberately
short-circuits before doing any real work, so it proves **none** of: the composite environment setup, or
the worker actually driving a stage with a model. Passing the smoke test means "the runner can start,"
not "a stage will complete remotely."

There is also a specific, named open risk worth stating plainly: a real remote launch may register
**zero extension tools.** The worker builds its runtime through `defaultCreateRuntime`, whose in-memory
settings ignore the disk `.pi/settings.json` package list — so as currently written, a remote worker may
come up with none of perk's own tools loaded. Whether a real launch loads `@mgiles/perk` at all is an open
question that only a live run will answer.

So: treat this surface as **emerging, not battle-tested** — the same tone [How perk thinks](./how-perk-thinks.md)
already sets. The wiring is real and the design is settled; the proof is not yet in.

## A per-surface maturity tiering

Not every headless surface carries the same risk. It helps to tier them:

- **Proven-safe (read-only / static).** `perk workflow run list` mutates nothing — it only reads the
  dispatch records and overlays a best-effort GitHub view. `perk doctor workflow check` is purely static
  prerequisite checking. You can lean on these freely.
- **Tested logic, acting on the unproven runner.** `perk objective run` (the supervisor) and
  `perk workflow run cancel`/`retry` (the control commands) have deterministic, unit-tested logic of
  their own — but they *dispatch into* or *act on* the remote runner. Their own behavior is trustworthy;
  what they hand off to is not yet proven.
- **Execution-untested.** The remote runner itself — the live `dispatch → checkout → setup → drive`
  chain — has not been run end-to-end. This is the tier the caveat is about.

This page will be updated to drop the caveat once a live `--remote` smoke proves the chain end-to-end.
Until then, the wiring is ready to be exercised, and exercising it is how it gets proven.

---

For the concrete recipes, see the how-to guides:
[set up the remote runner](../how-to/set-up-the-remote-runner.md),
[dispatch a stage to CI](../how-to/dispatch-a-stage-to-ci.md),
[observe and control dispatched runs](../how-to/supervise-dispatched-runs.md), and
[advance an objective with the run supervisor](../how-to/advance-an-objective-headlessly.md).

← Back to the [explanation router](index.md).
