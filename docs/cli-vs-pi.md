# CLI vs Pi: separation of concerns

How responsibilities split between the **`perk` CLI** (a Python command-line tool, the
spiritual successor to `erk`) and the **Pi extension** (TypeScript, loaded into a running
`pi` session). This is a foundational architecture decision; everything in
[ROADMAP.md](./ROADMAP.md) is built on top of it.

See [PRIOR_ART.md](./PRIOR_ART.md) for the erk learnings this is derived from, and
[RESEARCH.md](./RESEARCH.md) for the Pi-native rationale.

---

## 1. Background: why erk's CLI looked the way it did

erk was a Python CLI driving Claude Code. Sorting what it did by *why* it did it is the
key to designing perk correctly.

**Genuinely good — independent of Claude's limits (the CLI was the right home):**

- `erk init` / `erk doctor` — you bootstrap and diagnose a repo *before/around* an agent
  session. The agent can't bootstrap itself (chicken-and-egg).
- Worktree (and stack) management — filesystem/git layout whose lifecycle *spans*
  sessions.
- Launching the agent — something has to be the entry process; the agent can't exec
  itself.
- Supervising many sessions — a queue / headless fleet is a supervisor concern.

**Inelegant — existed *only because* Claude Code was a black box:**

- `erk exec …` shelled-out scripts — typed tool calls faked through a bash command + JSON
  schema, because Claude had no first-class custom tools.
- Prompt-hook markdown injected at workflow points *to steer behavior* — text injected in
  hope of compliance, because mode transitions couldn't be enforced.
- `allowed-tools` static allowlists — Claude's only gating lever; no dynamic, stateful
  gating.
- `CLAUDE_SESSION_ID` dependence, silently-failing workflow markers, reminder-consolidation
  gymnastics — side-channel state, because Claude couldn't hold or verify state inline.

**The pattern:** erk pushed *agent-behavior* concerns **out** into the CLI and into
injected text because Claude's interior was uncustomizable. The CLI became a
pseudo-agent-runtime. Pi removes that pressure — so in perk those concerns move **back
inside**, into the extension, where they can be *enforced* rather than *suggested*.

---

## 2. The core principle

> **The boundary is the session; authority follows the actor.**

### 2.1 The Pi extension owns the session *interior* — the agent's behavior plane

Everything that happens *while the agent is reasoning/acting*, or *in reaction to* it:

- commands, tools, modes
- tool gating (plan mode, read-only CI) via `setActiveTools` + `tool_call` blocking
- context injection (ambient / per-prompt / just-in-time)
- reactive hooks (`tool_call`, `tool_result`, post-edit formatting)
- the GitHub / state mutations that **workflow steps** perform (plan-save, objective
  updates, PR submission, thread resolution)

If the actor is *"the agent, or something responding to the agent within a turn,"* it's
the extension. **This is precisely the surface Claude denied erk, and it is where Pi's
customizability gets spent.**

### 2.2 The `perk` CLI owns the session *exterior* — the host & orchestration plane

Everything that sets up, launches, and coordinates sessions *from the outside*. Grouped so
nothing gets forgotten:

- **Setup & config** — `perk init`, `perk doctor`, `perk config`, secret/credential
  management for the CI integration (erk's `admin gh-actions-api-key`).
- **Worktree lifecycle** — create / list / delete; `prepare` (materialize a worktree +
  impl-context from a plan — the *positioning half* of a stage, see §4).
- **Navigation / movement primitives** — `br co`, `up`, `down`, checkout/teleport. These
  are **CLI-only by nature**: only a shell command using the *shell-activation pattern*
  (`source <(perk … --script)`) can change the **parent shell's** working directory. An
  agent inside a turn cannot `cd` your shell — this is a hard boundary, not a preference.
- **Read / status surface** — `dash`, `plan list / view / log`. Surveying workflow state
  from a cold shell (mirrors erk's plan-oriented dashboard).
- **Process launching** — exec `pi` (interactive) or `pi -p …` / RPC (headless), primed
  for a stage.
- **Local↔remote dispatch** — launching a stage on the *local machine* or on a *remote CI
  runner* (erk's `launch` / `dispatch` / `one-shot`); see §4.5.
- **Git-state maintenance** — `reconcile` (clean up branches whose PRs merged elsewhere),
  `sync` (rebase branch onto its base), conflict resolution, `rewrite` (squash / regenerate
  commit message). Mechanical repo hygiene around sessions.
- **Multi-session / headless supervision** — the Phase 3 queue and `workflow run`
  management (list / cancel / retry).
- **Remote dev environments** — codespace orchestration, if/when needed.

If the actor is *"a human at a shell, or a supervisor process managing sessions,"* it's the
CLI. (Note: several of these — `reconcile`, `sync`, conflict resolution, `address` — have a
*local* CLI variant and a *remote CI* variant; that duality is the subject of §4.5.)

### 2.3 Corrective rule (the erk lesson)

> **The CLI may *initiate* a stage, but it never *steers* a live turn.**

The CLI positions the environment and launches `pi`, then **hands off** — its authority
ends there. Once the turn is running, only the extension governs behavior. erk's `exec`
scripts and injected behavioral markdown were Claude-imposed hacks; perk does all
in-session steering natively in the extension. The CLI stays a pure host.

---

## 3. Coordination: how the two halves talk

The CLI is **Python**; Pi extensions are **TypeScript**. They share **no in-process
coupling** — neither imports the other's library and there are no direct function calls
across the boundary. They coordinate through three channels:

- **Durable state** — GitHub (canonical) + `.pi/workflow/` (cache), whose on-disk format is
  a language-neutral schema (JSON / TOML / markdown). Runtime workflow state both runtimes
  read/write through the *same documented artifacts*.
- **Process launch** — the CLI execs `pi` (interactive) or shells `pi -p …` / RPC mode
  (headless). The extension does the work inside.
- **A shared static contract** — the language-neutral stage registry / schema (§4.2),
  checked in once and *consumed by both planes*: the Python CLI generates its subcommands
  from it, the TS extension drives its transitions from it. This is shared
  source-of-truth (often via codegen), **not** shared runtime code.

Two consequences:

1. The **state-tiering contract becomes a *published, language-neutral* contract**, not an
   internal convention — because two runtimes in two languages depend on it. That is a
   feature: it's the same property that makes the workflow resumable and queue-able.
2. It cleanly resolves the **cross-session case** (see §4.5): an in-session step that needs a
   *new* worktree+agent does not spawn a sibling process itself (that's supervisor
   authority it must not hold). It **records intent in durable state**; the CLI/supervisor
   materializes and launches. A single user gesture decomposes along the boundary by actor
   — and that decomposition *is* the queue.

### 3.2 The agent-facing CLI surface *dissolves* — but JSON survives for the supervisor

erk made every command **dual-surface**: human output to stderr, structured `--json` to
stdout, plus `erk schema` introspection and an MCP server — *so that Claude could consume
the CLI as if it were a tool.* That entire surface existed because **Claude had no
first-class custom tools.**

In perk it largely **dissolves**: the agent calls **extension tools** natively, so it never
needs to shell out to `perk --json` or an MCP wrapper to do workflow work. This is the same
lesson as "don't reintroduce `erk exec`" — applied to the read/query side.

What *survives*, and why, follows directly from §2.3 (actor): the **supervisor/headless
consumer** still parses CLI output. So:

- Keep `--json` (and stable exit-code/`{success,error_type,message}` semantics) on the
  commands a **supervisor** drives — `init`, `doctor`, dispatch/launch, `workflow run`,
  status/list. The consumer is a *process orchestrating sessions*, not the agent.
- Do **not** rebuild `erk schema` / an MCP server as an agent affordance. If the agent
  needs structured workflow data mid-turn, that's an **extension tool**, not a JSON CLI
  call.
- Net: `--json` is for *machines that launch perk*, never for *the agent perk launches*.

---

## 4. CLI ↔ Pi stage parity

erk had hard break points where you ejected from the agent back to the shell (to
prepare/implement, to land). Two things happened at those moments:

1. **Environment positioning** — get into the right worktree/branch with state
   materialized. *(Exterior work.)*
2. **A fresh agent context** for the next kind of work — implement shouldn't inherit the
   planning conversation. *(A new session, not just a new mode.)*

Part of that ejection was essential; part was Claude-imposed — Claude gave you **no door on
the inside**, so the CLI was the *only* place a transition could happen. The break points
were **walls**.

Pi gives perk a door on the inside. So break points become **checkpoints with two doors**:
you can flow stage→stage *in-session*, or drop to the shell and *re-enter any stage cold*.
This symmetry is a direct payoff of the state-tiering contract — because every stage's
inputs/outputs are canonical, **any stage is re-enterable from a cold shell** (resumed from
a checkpoint, or initiated from a known input).

### 4.1 The parity, precisely

> **The stage is the unit of parity.**

Decompose the workflow into a small set of *named, resumable* stages (the natural break
points). Each stage has:

- **Exactly one implementation** — the extension command (interior). The stage logic is
  written once.
- **Two entry points, one mechanism:**
  - **Warm (in-session):** the agent/user invokes the command directly; **continues the
    current context.** Best for tight iterative flow.
  - **Cold (CLI):** `perk <stage> <plan>` positions the environment (resolve/create
    worktree, materialize state) and **launches `pi` primed to run that same extension
    command.** Best for resuming after a break, starting a stage with clean context, or
    running elsewhere / headless.
- The CLI entry is a **launcher that delegates, never a reimplementation.** Positioning +
  launch + hand-off, then done.

The two doors are **deliberately not identical in effect:** cold = fresh session positioned
at the stage; warm = continue without losing your seat. **Same stage logic, different
session semantics** — and that difference is the point.

**But the warm door is not always safe.** §4 noted that some transitions *require* a fresh
context — `implement` should not inherit the planning conversation. For those, the warm
door is a context-pollution footgun, and the stage should be **cold-only**, exactly as some
stages are remote-blocked on the cold side (§4.5). The asymmetry is itself symmetric: per
transition, *either* door may be disallowed. The registry records which (§4.2).

### 4.2 What keeps parity from rotting: one declarative stage registry

Two entry points must not drift into two behaviors. The guarantee is a **single declarative
stage registry** in the language-neutral shared schema, consumed by both planes:

- It enumerates the stages and, per stage, a **stage descriptor**:
  - the worktree/branch the stage needs
  - the state it reads/writes
  - the extension command it maps to
  - its legal predecessors/successors (the transition map)
  - **which entry doors are legal** — warm (in-session), cold-local, cold-remote; a stage
    may forbid a warm entry (requires fresh context) or a remote target (needs coordinated
    local setup)
- The **Python CLI generates its subcommands** from it (positioning + launch rules).
- The **TS extension drives its in-session transitions** from it.

Parity is therefore **by construction, not by discipline.** This is the one-backend analog
of erk's lesson ("keep a declarative registry that generates per-backend artifacts") —
except here the registry generates **two entry planes for one backend.**

### 4.3 Where parity stops

Parity applies only to **coarse stages that can be entered cold** — the erk break points.
Fine-grained in-session micro-ops (preview a feedback classification, resolve one thread,
toggle a sub-mode) stay **interior-only**; launching them cold from a shell would be
meaningless.

> **Rule of thumb:** a stage earns a cold (CLI) door if it can be either *initiated* from a
> known input (an objective or a plan ref) **or** *resumed* from durable state. Early stages
> (`plan`, `objective-plan`) are **initiate-cold**; later stages (`implement` … `land`) are
> **resume-cold**. A pure in-session micro-op — no durable input to start from, no
> checkpoint to resume — stays interior-only.

### 4.4 Candidate stage set (to be finalized)

Derived from the erk loop + the natural break points. **Not yet locked** — the exact set
and descriptors are the next thing to nail down.

| Stage | Warm (in-session) | Cold (CLI) | Reads / writes |
|---|---|---|---|
| `plan` | `/plan` | `perk plan` | objective context → new plan draft |
| `save` | `/plan-save` | (usually warm) | plan draft → GitHub canonical + plan-ref |
| `objective-plan` | `/objective-plan` | `perk objective-plan` | objective node → bounded plan (the "factory" step) |
| `prepare` | (implicit in `/implement`) | `perk prepare <plan>` | plan-ref → worktree/branch + impl-context (positioning only) |
| `implement` | `/implement` | `perk implement <plan>` | prepared worktree → code changes |
| `submit` | `/pr-submit` | `perk submit <plan>` | branch → PR (draft) |
| `address` | `/pr-address` | `perk address <plan>` | review threads → code/plan edits |
| `land` | `/ship` | `perk land <plan>` | ready PR → merge + objective reconciliation |
| `learn` | `/learn` | `perk learn <plan>` | landed session → captured knowledge + parent-plan metadata |

`prepare` is the *positioning half* of a stage made explicit: erk split worktree/context
setup (`prepare`) from execution (`implement`). Cold `perk implement` does prepare +
launch; warm `/implement` assumes the worktree is already current. `learn` is a genuine
post-land stage (session-capture / knowledge extraction), not an afterthought — it feeds
ROADMAP Phase 3's session-capture work and writes bidirectional metadata back to the parent
plan.

Plus a cold-only convenience: `perk resume <plan>` / `perk status`, which reads the state
tiers, finds the plan's current stage, positions the worktree, and launches `pi` at the
right command.

### 4.5 The cold door has two targets: local vs remote

The cold door (`perk <stage>`) does not only mean "a fresh local session." It is the same
seam erk productized as **local↔remote duality**: a stage can be launched on the **local
machine** (exec `pi` here) or on a **remote CI runner** (trigger a GitHub Actions workflow
that runs the *same* package). erk shipped both — e.g. local `pr address` (runs the agent
locally) vs `launch pr-address` (runs it in Actions); plus `dispatch` / `one-shot` for
fire-and-forget remote execution.

This is the *headless story* stated precisely: **a stage launcher is parameterized by
target.**

- **Local target:** `perk <stage> <plan>` — position the worktree, exec `pi` on this
  machine.
- **Remote target:** `perk <stage> <plan> --remote` (or `dispatch`) — record intent in the
  durable state tiers and trigger a runner that executes the same stage via the same
  extension command. The runner reports back through GitHub (comments/checks) and the run
  is observable via `workflow run list`.

Both targets drive the **same single stage implementation** (the extension command) over
the **same durable state**. The only difference is *where the process runs* — which is,
exactly, a host/orchestration concern the CLI owns. Two lessons carried from erk:

- **Some stages are local-only or remote-blocked.** erk blocks `plan-implement` via
  `launch` because it needs a coordinated branch/PR/metadata setup that the submit path
  owns. So the stage registry (§4.2) must record, per stage, **which targets are legal** —
  not every stage gets both doors.
- **Dispatching a remote stage writes linkage metadata** (run id → plan) back into durable
  state, so a later cold resume or a supervisor can correlate the run with its plan. This
  is the same "coordinate through artifacts" rule from §3.

> **Status (P2.T8c) — the resolver + registered targets are built; the runner is not.** The cold
> door's target parameterization is now real: `perk/launch.py` `resolve_target(stage, remote)` is a
> pure step returning a **local** or **remote** `Target`, with the legal targets recorded per stage
> in the registry (`doors.cold_remote: true` on `implement` + `address`; `false` on
> `plan`/`save`/`submit`/`land`/`learn`). A `--remote` launch on a drivable stage **resolves and
> surfaces** a `RemoteTarget` descriptor (runner ref + run_id→plan linkage) over the `--json`
> supervisor channel, then exits with a stable `remote_not_driven` — it does **not** yet persist
> intent or trigger a runner. **Phase 2 builds and resolves the target; the Phase-3 worker drives
> it** (and is the consumer that writes the linkage metadata above).

---

## 5. The payoff

- **Cold resume from anywhere.** `perk resume <plan>` / `perk <stage>` reconstructs and
  re-enters the workflow at any node, on any machine — because state is canonical in
  GitHub.
- **Headless is just the cold door with the remote target (§4.5), driven by a supervisor.**
  The Phase 3 queue launches the *same* stages via the *same* CLI launchers, parameterized
  to run on a CI runner. There is no separate headless workflow — **the parity *is* the
  headless story.**
- **No drift, no doubled logic.** One stage registry; one implementation per stage; the CLI
  is a thin launcher.

---

## 6. Consolidated principle

1. **Boundary = the session; authority follows the actor.** Extension owns the interior
   (behavior, modes, gating, workflow mutations); CLI owns the exterior (init, doctor,
   worktrees, launch, supervision).
2. **The CLI never steers a live turn** — it may *initiate* a stage by positioning +
   launching, then hands off; in-session steering is the extension's, done natively (the
   erk hacks were Claude-imposed).
3. **Coordination is through three channels — durable state, process launch, and a shared
   static schema/registry — never in-process coupling** (Python CLI / TS extension); the
   state-tiering contract is the language-neutral interop boundary.
4. **The stage is the unit of CLI↔Pi parity.** Each stage has one implementation
   (extension) and up to three entry doors (warm in-session; cold-local; cold-remote),
   generated from **one declarative stage registry** so parity cannot drift. The registry
   records which doors each stage allows — a stage may be cold-only (fresh context required)
   or local-only (no remote target). A stage earns a cold door if it can be *initiated* from
   a known input or *resumed* from durable state; pure in-session micro-ops stay
   interior-only.
5. **The cold door is parameterized by target — local or remote CI.** The same stage
   launcher runs `pi` locally or triggers a runner that executes the same extension command
   on the same durable state; the registry records which targets each stage allows.
   Headless = the cold door with the remote target.
6. **The agent-facing JSON/MCP surface dissolves; JSON survives only for the supervisor.**
   The agent uses extension tools natively (erk's `--json`/`schema`/MCP existed only because
   Claude lacked tools). `--json` is for *machines that launch perk*, never for *the agent
   perk launches*.

---

## 7. Application quick-reference

| Concern | Owner | Why |
|---|---|---|
| `perk init`, `perk doctor`, `perk config`, secrets | CLI | runs before/around a session; agent can't bootstrap itself |
| worktree create/rm/list/`prepare`, launch `pi` | CLI | filesystem/process lifecycle spanning sessions |
| navigation (`br co`, `up`, `down`) via shell-activation | CLI **only** | only a shell command can `cd` the parent shell; agent can't |
| read/status surface (`dash`, `plan list/view/log`) | CLI (read) | survey workflow state from a cold shell |
| git-state maintenance (`reconcile`, `sync`, conflict-fix, `rewrite`) | CLI | mechanical repo hygiene around sessions |
| headless queue / fleet supervision / `workflow run` | CLI | supervisor of N sessions |
| cold stage entry, local or remote target (`perk implement`, `perk land`, `perk learn`, `--remote`) | CLI | positions env + launches `pi` (here or in CI); delegates to the extension command |
| `--json` / structured output | CLI, **for the supervisor only** | machines that *launch* perk parse it; the agent uses extension tools, not JSON CLI |
| `/plan` `/implement` `/ship`, plan-save, objective ops | extension | in-session workflow boundaries + their GitHub mutations |
| plan mode / read-only CI gating, post-edit formatting, context injection | extension | shaping/reacting to the agent *during* a turn (Pi's superpower) |
| fine-grained in-session micro-ops | extension | not resumable from durable state alone — interior-only |
| reading/writing plan-ref, `.pi/workflow/`, GitHub state | **both**, via the shared schema | the interop contract — no in-process coupling |
| the stage registry (stages, descriptors, transition map) | **both**, single source | generates CLI subcommands *and* extension transitions |
