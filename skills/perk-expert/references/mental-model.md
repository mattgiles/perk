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
spine. An objective's reviewed **delivery** choice is how its plans land: **incremental** (the
recommended default — each plan lands as its own PR) or **stacked** (a supported authoring
choice: all non-skipped nodes land as one atomic PR train of parent-targeted draft PRs,
capability-checked at save; committed published-layer changes propagate automatically from
`/submit`/`finalize_address`, while explicit `perk objective stack sync` owns base advancement,
adoption, continuation, and repair; the train lands atomically via `perk objective stack
land` / `/objective-land` — `perk pr land` still refuses stacked layers individually;
limitations in `docs/user-docs/reference/objectives.md`).

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
losing anything canonical — the durable tier is the saved plan plus pushed branches; uncommitted
worktree edits (and unpushed commits) are machine-local, outside the cross-machine contract.

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
The settled claim triple: **every stage is locally resumable** (cold local door + canonical plan);
only the *agentic but bounded* stages (`implement`, `address`) are additionally **remotely
runnable**; the human-gate stages (`submit`, `land`, `learn`) are **local-only by design**. The
remote surface
is the newest part of perk — the live chain is proven end-to-end on both the self-repo and
consumer worker-entry paths (point-in-time dogfood proofs, 2026-07-04 and 2026-07-06; there is no
recurring live-E2E gate). A remote run is the **same stage implementation** as a local one
— same prompts, same guidance content, same tools and side effects, same classifier, same plan-ref
reconstruction — and that identity is enforced by parity tests, not prose. The named intentional
differences: `learn`/`submit`/`land` never run remotely; skill guidance is injected in-session
remotely (appended to the prompt cold-locally, identical content); `address --preview` is
local-only; only the remote worker machine-classifies completion; and run reporting (PR comments +
job summaries) exists only for remote runs.

## Schema snapshots

perk's cross-plane contracts — the shared YAML contracts (registry/bindings/providers), the machine
batch inputs, and the `--json` output envelopes — have **committed JSON Schema golden snapshots**
under `shared/schemas/`, generated from the Pydantic boundary models (`perk/boundary.py`). Their
function is making machine-surface shape changes reviewable (drift-guarded); they are bundled into
both planes, read at runtime by neither. The canonical reference is
`docs/user-docs/reference/json-schemas.md`.

## Discover the live surface

The reference shape is here; for the exact current commands/flags run `perk --help` /
`perk <group> --help`, `perk doctor` (validates config + bindings, reports provider/backend
resolution), and `perk registry show` (the stage graph); `perk release-notes` shows the bundled
changelog's release notes (defaults to the running version). Inside a session, the warm `/…`
commands are the interior surface.

---

*Canonical source: `docs/user-docs/explanation/how-perk-thinks.md` (+ the `reference/{cli,in-session}.md` orientations).*
