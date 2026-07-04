# perk mental model (orientation)

Four ideas make perk's commands stop feeling arbitrary.

## 1. perk is plan-oriented

perk's unit of work is a **plan**: a written, reviewed, durable description of a change, authored
*before* any code is written. It is a first-class artifact stored on the canonical issue tier
(GitHub issue by default), so it outlives the session that wrote it and can be read, linked, and
resumed later. Authoring happens in a deliberately **read-only** mode — the agent can read, search,
and reason but not edit — and editing only becomes possible after the plan is reviewed and saved.
That gate forces understanding before doing.

The **spine** a plan travels: *explore → plan → save → implement → submit → (address) → land →
learn*. `address` is conditional (only when a reviewer leaves feedback). A longer-running
**objective** — a roadmap that emits bounded plans as it advances — can feed plans into this same
spine.

## 2. Two planes: exterior and interior

- **Python `perk` CLI — the session exterior.** Everything *outside* a session: scaffolding a repo,
  managing the git worktrees each plan lives on, minting run identifiers, and **launching** a primed
  `pi` session. It may *start* a stage but never *steers* a live turn.
- **TypeScript Pi extension — the session interior.** Everything *inside* a running session: driving
  stage transitions, gating which tools the agent may use, injecting context, and performing the
  workflow's GitHub mutations.

The boundary is the session, and authority follows the actor: in-session reasoning/acting ⇒
extension; setup/launch/coordination from outside ⇒ CLI. The planes share **no in-process code** —
they coordinate through durable artifacts, a process launch, and a shared static workflow
description both read independently.

## 3. The three state tiers

- **GitHub — canonical.** The source of truth under the default backend (plans, PRs, review threads,
  objectives, learnings). On a **Linear** backend the canonical issue tier moves to Linear and
  objectives live as **Linear Projects**, while PRs / review threads / CI / merge stay
  GitHub-universal. When tiers disagree, the canonical issue tier wins.
- **`.perk/workflow/` — cache.** A local, per-repo, gitignored mirror (materialized plan body, the
  active-plan→branch pointer). Derivable from and reconcilable against the canonical tier; safe to
  lose and repairable.
- **Session entries — transient.** In-session working state (current stage, read-only vs read-write)
  that evaporates when the session ends.

Operator rule: **durable truth is canonical; the local cache is convenience; session state is
throwaway.** You can delete a worktree, switch machines, or hand a plan to a colleague without
losing anything important.

## 4. Stages and doors

The workflow is a small set of named, resumable **stages** (the spine, plus an objective-planning
stage). Each stage has exactly one implementation both planes agree on, entered through **two
doors**:

- **Warm (in-session):** invoke the stage from inside a running `pi` session, **keeping current
  context** — best for tight iterative flow.
- **Cold (from a shell):** run a `perk` command that **positions the environment** (resolves/creates
  the worktree, materializes state) and **launches a fresh `pi` session** primed for that stage —
  best for resuming or starting with clean context.

Some stages are **cold-only** — notably **implement**, which must not inherit the planning
conversation (context hygiene). The cold door is parameterized by *where* the process runs: your
local machine, or a **remote CI runner** (headless = the cold door pointed at a remote target).
Only *agentic but bounded* stages (`implement`, `address`) are remotely runnable; the remote surface
is the newest part of perk — the live chain is proven end-to-end on perk's own repo, but consumer
repos have not yet exercised it.

## Published schemas

perk's cross-plane contracts — the shared YAML contracts (registry/bindings/providers), the machine
batch inputs, and the `--json` output envelopes — have **published JSON Schemas** under
`shared/schemas/`, generated from the Pydantic boundary models (`perk/boundary.py`). They are
reference artifacts (bundled into both planes, read at runtime by neither). The canonical reference
is `docs/user-docs/reference/json-schemas.md`.

## Discover the live surface

The reference shape is here; for the exact current commands/flags run `perk --help` /
`perk <group> --help`, `perk doctor` (validates config + bindings, reports provider/backend
resolution), and `perk registry show` (the stage graph); `perk release-notes` shows the bundled
changelog's release notes (defaults to the running version). Inside a session, the warm `/…`
commands are the interior surface.

---

*Canonical source: `docs/user-docs/explanation/how-perk-thinks.md` (+ the `reference/{cli,in-session}.md` orientations).*
