---
title: "Headless and remote: how it works, and how proven it is"
description: "How perk's headless and remote pieces fit together, and how proven each of them is."
sidebar:
  order: 4020
---

# Headless and remote: how it works, and how proven it is

[How perk thinks](./how-perk-thinks.md) establishes the headless model in one line: there is no
separate headless workflow — headless is simply the cold door pointed at a remote target. This page
assumes that model and goes deeper, on two fronts that matter once you actually lean on the surface:
**how the pieces fit together**, and **how proven each of them is.**

## How the pieces actually fit

The thing that makes a remote run legible is a durable correlation key. Every dispatch triggers the
managed workflow with a **run-name that embeds the correlation** — `perk <stage> · plan #<plan> ·
<run_id>` — so the GitHub Actions run itself is the **canonical record that the run exists**. The
supervisor and `perk workflow run list` enumerate those runs directly, which is why any machine — a
second clone, a teammate's checkout — can see, gate on, and control a run it never dispatched.
Alongside that, the dispatching machine writes a local **dispatch record** —
`scratch/runs/<run_id>/dispatch.json` — tying the perk `run_id` to the plan, the stage, and the
triggered run. That record is a **cache and correlation accelerator**: it enriches the listing (the
plan URL, the objective backlink, the precise dispatch time) and it is the only durable trace of a
dispatch that **failed or never triggered** (a run that never started has no GitHub run to
discover). Deleting it forgets nothing that exists remotely. Nothing about a remote run lives in a
terminal you have to keep open.

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

## What is identical across the doors, and what intentionally differs

"No separate headless workflow" is not a slogan — it is test-enforced. A remotely dispatched
stage runs the **same implementation** a warm or cold-local run does: the same stage prompts, the
same skill guidance content, the same tools with the same side effects (a remote implement opens
its PR through the very same submit door), the same next-step classifier, and the same plan-ref
reconstruction from the plan issue. Each of those identities is pinned by a parity test (the
matrix lives in `shared/contracts.md` §8.38), so the paths cannot silently drift apart.

A few things *do* differ between the doors — deliberately, and worth knowing as a user:

- **`learn` never runs remotely.** The supervisor will tell you to run `perk plan resume <id>`
  locally instead; `submit`, `land`, and `learn` are local-only by design.
- **Skill guidance arrives differently, but reads identically.** A cold-local launch appends it
  to the opening prompt; warm and remote sessions receive the same content injected in-session.
  You may notice the placement, never a content difference. The skills themselves also *arrive*
  differently: the remote runner installs the `skills` CLI and syncs the repo's declared skills
  into the checkout before driving, and a skills-delivery failure **fails the run** rather than
  silently degrading it (locally a missing skill only warns — you can see the warning; remotely
  nobody would).
- **`address --preview` (classify-only) is a local flag.** A remote address always acts on the
  feedback.
- **Conflict resolution rides the session.** The in-session submit (warm or remote) drives the
  conflict-resolver when the PR is unmergeable; a bare `perk pr submit` from a shell reports the
  conflicts and leaves resolution to you.
- **Only the remote worker declares a run "complete" by machine.** Local stages end with you
  observing the same tool results — no classifier stands between you and the session.
- **Run reporting (the PR comments and job summaries) is remote-only.** Local runs are observed
  directly in the terminal or the session, so nothing is posted for them.

## The maturity story

Here is the honest state of the remote surface: **the live end-to-end chain is proven on both
worker-entry paths.** On 2026-07-04 a real remote `implement` run and a real remote `address` run
were driven through perk's own dispatch doors, start to finish, on an actual CI runner —
`dispatch → checkout → setup → drive → submit / thread-resolution → terminal reporting` — with each
verification point mapped to a captured artifact. The procedure and the evidence live in the
[remote-runner e2e dogfood record](https://github.com/mattgiles/perk/blob/main/docs/design/remote-runner-e2e-dogfood.md).

The **consumer-repo** path is proven too. On 2026-07-06 a real remote `implement` run (it submitted
its PR) and a real remote `address` run (it resolved the review thread) executed in a scratch
consumer repo on released perk 1.1.0, through the published distributions (PyPI `perk`, npm
`@mgiles/perk`) and the staged `consumer-npm` worker entry — the procedure and evidence live in the
[consumer dogfood record](https://github.com/mattgiles/perk/blob/main/docs/design/remote-runner-consumer-dogfood.md).
One nuance for honesty's sake: that proof ran with two labeled pre-release fixes (PR #1156)
hand-applied to the scratch repo, so the fully canonical published-registry path re-proves
implicitly at the first dispatch after the next release.

Both proofs are **point-in-time**: there is no recurring CI-gated live E2E. What guards the surface
is each record's documented, repeatable procedure plus its captured evidence — not a standing gate.

`perk doctor workflow smoke-test` still sits exactly where it always did: it proves the **wiring** —
that a run can be dispatched, that the runner starts, and that its secrets are readable. It
deliberately short-circuits before doing any real work, so passing it means "the runner can
start" — the full-chain proof above is what says a stage can *complete* remotely.

The worker's tool-loading risk stayed closed under live fire: the disk-layered settings load (the
worktree's managed `.pi/settings.json` package list — the same package set a warm session loads)
resolved `@mgiles/perk` on the runner, the drive's tools registered, and the fail-fast
`no_extension_tools` guard never had to fire. The dogfood also caught and fixed real defects the
declarative tests could not see (a fresh-plan checkout failure; a stale default-model pick) — the
defect log in the evidence record is part of the story.

## A per-surface maturity tiering

Not every headless surface carries the same risk. It helps to tier them:

- **Proven-safe (read-only / static).** `perk workflow run list` mutates nothing — it enumerates
  GitHub's runs (best-effort, fail-soft) and merges in the local dispatch-record cache. `perk doctor
  workflow check` is purely static prerequisite checking. You can lean on these freely.
- **Proven live on the self-repo.** The remote runner itself — the live
  `dispatch → checkout → setup → drive → report` chain — has completed real `implement` and
  `address` runs end-to-end through perk's own doors (the
  [dogfood record](https://github.com/mattgiles/perk/blob/main/docs/design/remote-runner-e2e-dogfood.md)).
  `perk objective run` (the supervisor) and `perk workflow run cancel`/`retry` (the control
  commands) have deterministic, unit-tested logic of their own and now hand off into a chain with
  a live proof behind it.
- **Proven live on the consumer path.** The **consumer-repo** remote drive — the `consumer-npm`
  worker entry plus the pinned `@mgiles/perk` install — completed real `implement` and `address`
  runs in a consumer repo on 2026-07-06 (the
  [consumer dogfood record](https://github.com/mattgiles/perk/blob/main/docs/design/remote-runner-consumer-dogfood.md)).
  Like the self-repo proof, it is point-in-time evidence, not a recurring gate.

---

For the concrete recipes, see the how-to guides:
[set up the remote runner](../how-to/set-up-the-remote-runner.md),
[dispatch a stage to CI](../how-to/dispatch-a-stage-to-ci.md),
[observe and control dispatched runs](../how-to/supervise-dispatched-runs.md), and
[advance an objective with the run supervisor](../how-to/advance-an-objective-headlessly.md).

← Back to the [explanation router](index.md).
