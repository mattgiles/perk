# Proposal: make perk available as a Zed External Agent through ACP

Status: research/proposal  
Date: 2026-06-24  
Audience: perk maintainers

## Executive summary

perk can fit Zed, but it should not be flattened into "one normal chat agent".
The core product value of perk is the stage machine: read-only planning,
canonical plan storage, cold-only implementation, worktree positioning,
GitHub/Linear-backed resumability, and remote dispatch for selected stages. Zed's
External Agent surface gives us a good editor-native shell for that workflow, but
ACP should be treated as a **client transport** around perk's existing exterior
and interior, not as a replacement workflow runtime.

The recommended path is:

1. Support **Terminal Threads** immediately as the "native Pi/perk TUI in Zed"
   path. This requires little or no code and matches Zed's guidance for direct
   CLI/TUI usage.
2. Document that the existing **Pi Coding Agent ACP adapter** is a useful
   baseline, but not a first-class perk integration. It can run Pi in Zed and may
   load perk's Pi package when the project is initialized, but it does not
   understand perk stages, worktrees, plan refs, remote dispatch, or extension
   slash command discovery as product concepts.
3. Build a **perk-owned ACP adapter** as the first-class External Agent. The
   adapter should reuse Pi's RPC protocol path rather than reimplementing agent
   execution. Its job is to translate Zed/ACP sessions into perk stage-aware
   launches, expose perk commands in Zed, preserve cold-door session boundaries,
   and surface workflow state as ACP updates.

Concretely, add a new executable such as `perk-acp` or `perk zed-agent`. It
should be an ACP server process registered in Zed's `agent_servers`, backed by
Pi RPC and perk's existing Python CLI/library surfaces. It should initially ship
outside the PyPI wheel if that keeps dependency boundaries clean, then graduate
into a registry-installable adapter once the UX is proven.

## Source snapshot

External docs checked on 2026-06-24:

- Zed External Agents: <https://zed.dev/docs/ai/external-agents>
- Zed Agent Panel: <https://zed.dev/docs/ai/agent-panel>
- Zed Parallel Agents and Threads Sidebar: <https://zed.dev/docs/ai/parallel-agents#threads-sidebar>
- Zed Terminal Threads: <https://zed.dev/docs/ai/terminal-threads>
- Zed Agent Settings: <https://zed.dev/docs/ai/agent-settings>
- ACP introduction: <https://agentclientprotocol.com/get-started/introduction>
- ACP architecture: <https://agentclientprotocol.com/get-started/architecture>
- ACP initialization: <https://agentclientprotocol.com/protocol/v1/initialization>
- ACP session setup: <https://agentclientprotocol.com/protocol/v1/session-setup>
- ACP prompt turn: <https://agentclientprotocol.com/protocol/v1/prompt-turn>
- ACP session config options: <https://agentclientprotocol.com/protocol/v1/session-config-options>
- ACP tool calls: <https://agentclientprotocol.com/protocol/v1/tool-calls>
- ACP TypeScript SDK: <https://agentclientprotocol.com/libraries/typescript>
- ACP Python SDK: <https://agentclientprotocol.com/libraries/python>
- `pi-acp` repository, inspected through `gh`: <https://github.com/svkozak/pi-acp>

Repo docs and code consulted:

- `docs/user-docs/explanation/how-perk-thinks.md`
- `docs/user-docs/explanation/headless-and-remote.md`
- `docs/user-docs/reference/cli.md`
- `docs/user-docs/reference/in-session.md`
- `shared/registry.yaml`
- `shared/contracts.md`
- `perk/run/launch/prompts.py`
- `perk/run/runner.py`
- `pyproject.toml`
- `package.json`

## What Zed and ACP actually provide

### Zed External Agents

Zed External Agents are ACP-integrated agent processes. Zed owns the thread
surface in the Agent Panel and Threads Sidebar. The external agent usually owns
runtime, auth, model selection, tools, and native configuration.

Important implications:

- The agent process is separate from Zed and communicates over ACP.
- Zed provider settings are not automatically the external agent's provider
  settings.
- Zed Skills do not become native agent skills.
- Zed MCP servers may be forwarded over ACP, but native MCP configuration may
  still be read by the agent.
- Tool permission behavior is split between ACP-facing permissions and the
  agent's native tool permissions.
- Custom agents are configured through `agent_servers` with a command, args, and
  env.
- Zed's ACP logs are the debugging surface.

For perk, this is good: perk already wants the agent runtime to own its own
skills, stage gates, GitHub access, Pi package set, and model/tool behavior. The
Zed settings boundary aligns with perk's existing "session exterior/interior"
split.

### Zed Terminal Threads

Terminal Threads are not ACP. They are terminal-backed threads in the same Zed
agent UI, intended for directly running a CLI/TUI. Zed explicitly says to use
Terminal Threads when the desired experience is a native command-line tool.

For perk, this is the right zero-integration path:

- A user can run `perk plan`, `perk implement`, `perk pr address`, or raw `pi`
  inside a Zed-managed terminal thread.
- Pi's TUI surfaces remain exactly Pi's surfaces.
- perk does not need to translate rich Pi UI into ACP.
- Zed still groups the terminal with other agent threads.

This path does not make perk an External Agent, but it is useful and honest. It
should be documented once the ACP work starts, because some users will prefer
the native Pi TUI.

### ACP

ACP is JSON-RPC between a client/editor and an agent. For local agents, the
editor starts the agent as a subprocess and communicates over stdio. One
connection can support multiple concurrent sessions. The agent returns
capabilities during `initialize`, creates or loads sessions through
`session/new` and `session/load`, receives prompts through `session/prompt`, and
streams updates back through `session/update`.

Relevant primitives:

- `initialize`: version negotiation, agent info, capabilities, auth methods.
- `session/new`: creates a session with a working directory and forwarded MCP
  server configuration.
- `session/load`: optional session restoration, including replaying history.
- `session/prompt`: one user turn, containing text/resources/images according
  to negotiated capabilities.
- `session/update`: assistant chunks, plans, usage, tool calls, command
  availability, session info.
- `session/request_permission`: optional agent-to-client permission request for
  tool calls.
- `configOptions`: the preferred current surface for session-level
  configuration. ACP says clients should prefer this over the older `modes`
  field.
- Tool calls: typed as read/edit/delete/move/search/execute/think/fetch/other,
  with optional locations and raw input/output.

For perk, ACP is most useful for:

- Making Zed show perk as a first-class thread source.
- Streaming Pi output and tool calls with file locations/diffs where possible.
- Advertising perk-specific slash commands or command-like affordances.
- Surfacing plan/checkpoint/workflow progress as structured updates.
- Loading/importing sessions into Zed's Thread History if we can map IDs
  correctly.

ACP is not a workflow engine. It has no native concept of perk's stage graph,
canonical plan issue, branch binding, worktree creation, read-only plan gate, or
remote run supervisor. Those stay perk concepts.

## Existing `pi-acp` baseline

The current `pi-acp` adapter is the closest prior art and likely the codebase to
reuse or fork. As of the inspected version:

- It communicates ACP JSON-RPC over stdio and spawns `pi --mode rpc`.
- It streams assistant output as ACP message chunks.
- It maps Pi tools into ACP tool calls and tool-call updates, including file
  locations and structured diffs where it can infer them.
- It supports session persistence by mapping ACP session IDs to Pi session files.
- It loads file-based slash commands from Pi prompt directories.
- It exposes built-in commands such as `/compact`, `/session`, `/model`, and
  `/thinking`.
- It supports terminal auth for ACP registry flows.
- It advertises Pi in Zed's External Agent path, and Zed's docs list Pi Coding
  Agent as a common External Agent.

The important limitation is explicit in the README: **slash commands provided by
Pi extensions are not currently supported.** The source also calls
`toAvailableCommandsFromPiGetCommands(..., { includeExtensionCommands: false })`.

That means `pi-acp` is likely sufficient to make "Pi with perk installed" usable
in Zed, but it is not enough to make "perk" a clear agent product:

- Zed will not know the stage graph.
- Zed will not advertise perk's warm `/...` doors as first-class commands.
- Zed will not steer cold-only stages into fresh sessions or worktrees.
- Zed will not know that `implement` should be a new cold context, not the
  continuation of the planning thread.
- Zed will not surface GitHub/Linear canonical state as workflow state.
- Zed will not distinguish "plan draft in scratch" from "saved canonical plan".

This strongly suggests that the adapter should be perk-owned even if it reuses
`pi-acp` internals.

## The shape of perk that must survive the translation

The ACP adapter has to preserve these invariants from perk, or the integration
is only a cosmetic wrapper:

1. The unit of work is a durable plan.
2. Planning is read-only and structurally gated.
3. Saving crosses the read-only -> read-write boundary and writes canonical
   state to the configured backend.
4. `implement` is cold-only and must start from fresh context.
5. Worktree positioning is exterior-owned.
6. The session interior owns stage behavior once a Pi session exists.
7. GitHub or Linear is canonical, `.pi/workflow/` is cache, session entries are
   transient.
8. A warm door keeps context and run identity; a cold door mints a new run ID and
   launches a new session.
9. Remote/headless dispatch is the cold door pointed at another runner. It is
   not a separate workflow.
10. Stage availability is registry-driven, not hand-maintained in another
    routing table.

This matters most at the planning-to-implementation boundary. In a normal Zed
agent thread, the user might expect to plan and then say "go implement that" in
the same conversation. perk deliberately does not want that for the saved-plan
implementation path. The ACP adapter must make the right thing the easy thing:
after saving a plan, starting implementation should create or switch to a
separate Zed External Agent thread backed by a fresh Pi session in the plan
worktree.

## Integration options

### Option 0: Terminal Threads only

This is not an External Agent, but it should be supported immediately.

Possible docs:

```json
{
  "agent": {
    "terminal_init_command": "pi"
  }
}
```

or for a repo already initialized with perk:

```json
{
  "agent": {
    "terminal_init_command": "perk plan"
  }
}
```

Pros:

- No protocol adapter work.
- Preserves Pi TUI exactly.
- Best compatibility with current perk extension surfaces.
- Good for users who already understand `perk` and `pi`.

Cons:

- Not a Zed External Agent.
- No ACP tool call rendering, structured diffs, Thread History import, or agent
  command discovery.
- The user still has to run shell commands for stage transitions.

Use this as the fallback and "native terminal" path, not the strategic
integration.

### Option 1: Tell users to install Pi Coding Agent from the ACP registry

This is the lowest-effort ACP path. Users install Pi from Zed's ACP registry,
run `perk init` in the repo, and use the Pi External Agent in the project.

Pros:

- Works with existing Zed registry behavior.
- Reuses the maintained `pi-acp` bridge.
- Gives ACP message/tool streaming today.
- Does not add another adapter to maintain.

Cons:

- The product is "Pi", not "perk".
- Extension slash commands are not advertised by `pi-acp`.
- perk-specific stage state, plan refs, worktrees, and cold doors are invisible
  to Zed.
- There is no first-class way to start "implement plan #42" as a Zed thread
  that follows perk's cold-door contract.
- It cannot fix the biggest UX issue: preserving fresh context between plan and
  implementation.

This is a useful compatibility story. It is not the desired end state.

### Option 2: Add perk file-based slash command prompts for `pi-acp`

Because `pi-acp` loads file-based prompts from `.pi/prompts/**/*.md`, perk could
install project prompt files that call or describe `/plan`, `/submit`,
`/address`, and similar warm doors.

Pros:

- Small change.
- Commands would appear in Zed through existing `pi-acp`.
- Helps discoverability.

Cons:

- Prompt files are only text expansion. They cannot create worktrees, mint
  run IDs, write handoff blobs, or launch fresh Pi sessions.
- They risk turning stage transitions into prompt-instruction theater rather
  than structural workflow moves.
- They duplicate command summaries already owned by the registry/docs.
- They do not solve cold-only `implement`.

This is acceptable as a temporary affordance for simple warm commands, but it
should not be the architecture.

### Option 3: Extend `pi-acp` upstream to support Pi extension commands

This would make Pi's adapter more capable generally. If `pi --mode rpc`
can expose extension command metadata and invoke extension commands, `pi-acp`
could include them in `available_commands_update`.

Pros:

- Benefits all Pi extension users.
- Reduces perk-specific adapter code.
- Keeps Pi ACP support centralized.

Cons:

- Still Pi-oriented, not perk-stage-oriented.
- Still does not know which perk commands must be cold launches.
- Still does not own worktree creation or stage relaunch UX.
- Requires upstream coordination and may be bounded by Pi RPC support.

This is worth pursuing as an upstream contribution, but it is not sufficient for
perk's first-class External Agent.

### Option 4: Build a perk-owned ACP adapter around Pi RPC

This is the recommended product architecture.

The adapter should act like `pi-acp` plus a perk control plane:

- It implements ACP over stdio.
- It spawns `pi --mode rpc` for actual agent execution.
- It ensures the repo is perk-initialized before starting workflow sessions.
- It reads `shared/registry.yaml` to know stage IDs, modes, doors, and command
  labels.
- It calls existing `perk` CLI/library code for exterior operations:
  worktree positioning, run ID minting, handoff writing, plan-ref resolution,
  remote dispatch, workflow observation.
- It launches or restores Pi sessions with the same environment and handoff
  semantics as the normal cold doors.
- It exposes perk commands through ACP command availability.
- It emits ACP session updates that reflect workflow state, not just raw model
  text.

Pros:

- Makes the Zed agent feel like perk, not generic Pi.
- Preserves the cold/warm distinction.
- Can make "save plan -> start implement thread" a deliberate UI transition.
- Can surface checkpoint and remote-run progress in Zed.
- Can use ACP session loading/import to bridge Zed Thread History with Pi
  session files and perk run IDs.
- Keeps the agent runtime in Pi, where perk already has its interior.

Cons:

- More code and packaging.
- Must track ACP and Pi RPC evolution.
- Needs careful session mapping across ACP session ID, Pi session file, and
  perk run ID.
- Must avoid creating a second implementation of stage behavior.

This option has the best long-term fit.

### Option 5: Reimplement perk directly as a non-Pi ACP agent

This would make the ACP process the agent runtime and port perk's interior away
from Pi.

Pros:

- Maximum control over ACP behavior.
- No Pi RPC bridge limitations.

Cons:

- Violates the current design: TypeScript Pi extension owns the session
  interior.
- Duplicates or abandons significant existing work.
- Requires reimplementing tool gates, session entries, warm doors, surfaces,
  skills, subagents, and model/tool runtime behavior.
- High drift risk.

This should be rejected unless perk decides to stop being Pi-native.

## Recommended architecture

### Name and packaging

Use a separate executable name rather than overloading the normal `perk` stage
commands:

- `perk-acp`: direct ACP server binary; best for Zed `agent_servers`.
- `perk zed-agent`: possible CLI alias for discoverability.

The adapter should probably be TypeScript at first, because:

- `pi-acp` is TypeScript and already uses `@agentclientprotocol/sdk`.
- Pi RPC integration examples are already TypeScript.
- perk already ships a TypeScript package for the Pi extension.
- Reusing or vendoring `pi-acp` translation code is more practical in TS.

The Python wheel should remain the source of exterior workflow logic. The TS ACP
adapter can shell to `perk ... --json` for deterministic operations, or call a
small Python helper through the CLI. Do not port exterior logic to TS just for
ACP.

A possible package split:

- Keep `perk` PyPI package as the canonical CLI.
- Add `@perk/acp` npm package for the adapter.
- Let `perk init` optionally write suggested Zed settings, but do not make Zed
  configuration a mandatory part of repo convergence.
- Later register `@perk/acp` in the ACP registry once stable.

### Process model

Zed starts the adapter:

```json
{
  "agent_servers": {
    "perk": {
      "type": "custom",
      "command": "npx",
      "args": ["-y", "@perk/acp"],
      "env": {}
    }
  }
}
```

For local development:

```json
{
  "agent_servers": {
    "perk-dev": {
      "type": "custom",
      "command": "node",
      "args": ["/path/to/perk/acp/dist/index.js"],
      "env": {
        "PERK_COMMAND": "uv run perk"
      }
    }
  }
}
```

The adapter maintains a session table:

| ACP concept | Pi/perk concept |
| --- | --- |
| ACP connection | One Zed-launched adapter process |
| ACP session ID | Adapter-owned ID, stable in Zed |
| Pi session file | Actual agent conversation/history |
| `PERK_RUN_ID` | Workflow correlation key for cold/warm lineage |
| `cwd` | Repo root or plan worktree path |
| stage | Registry stage ID |
| plan ref | Provider-agnostic plan binding |

Do not use the ACP session ID as the perk run ID. They have different lifecycles.
The adapter should store a mapping file, similar to `pi-acp`, but extended with
perk metadata:

```json
{
  "schema_version": 1,
  "sessions": {
    "zed-session-id": {
      "cwd": "/repo-or-worktree",
      "pi_session_file": "/Users/me/.pi/agent/sessions/...",
      "run_id": "01J...",
      "stage": "plan",
      "plan_ref": {
        "provider": "github",
        "pr_id": "42",
        "url": "https://github.com/org/repo/issues/42"
      }
    }
  }
}
```

Suggested location: `~/.perk/acp/session-map.json`, not `.pi/workflow/`.
This is client adapter state, not canonical workflow state.

### Session creation

On `session/new(cwd)`:

1. Verify `cwd` is absolute.
2. Find the repo root.
3. Determine whether the repo is perk-initialized.
4. If not initialized, return a short actionable message in the new thread:
   `This repository is not initialized for perk. Run perk init first.`
5. Load `shared/registry.yaml` from the installed perk package, not by scraping
   docs.
6. Default to a **planning session** in the repo root unless the user command or
   session restore says otherwise.
7. Spawn `pi --mode rpc` with the same package/settings environment the normal
   perk launch would use.

Do not automatically run `perk init` on `session/new`. `init` mutates the repo.
Zed opening an agent thread should not silently mutate project wiring.

### Commands exposed to Zed

The adapter should advertise a compact command set, not every raw CLI subcommand.
In ACP payloads these are `AvailableCommand.name` values without a leading slash;
the examples below use the slash-prefixed spelling because that is what the user
types in Zed. The point is to expose workflow doors:

- `/perk-plan`: start or enter read-only plan mode in the current thread.
- `/perk-save`: save the current draft/reviewed plan.
- `/perk-resume <plan>`: resolve a plan and open the right stage.
- `/perk-implement [plan]`: launch a fresh implementation thread/worktree.
- `/perk-submit`: push and open draft PR.
- `/perk-ready`: mark draft PR ready.
- `/perk-address [--preview]`: address review feedback.
- `/perk-land`: land the PR.
- `/perk-learn [skip|summary]`: capture learnings.
- `/perk-objective-author`: author a new objective.
- `/perk-objective-plan <objective> [--node <id>]`: plan next/specific node.
- `/perk-status`: show active plan, stage, branch, PR, and run ID.
- `/perk-workflow-runs`: list remote runs.
- `/perk-dispatch <implement|address> [plan]`: remote dispatch where available.

The command names should probably be prefixed (`perk-*`) even though the agent
itself is "perk". ACP command namespaces are per agent, but user memory benefits
from explicitness and copied instructions remain readable outside Zed. If Zed
renders commands under the selected agent clearly enough, short aliases can be
added later.

The adapter should derive availability from the registry and current state:

- Hide or mark unavailable cold-remote commands when `doors.cold_remote` is
  false.
- Hide `/perk-implement` as an in-thread continuation; treat it as a launch
  command.
- Show `/perk-submit` only in a plan worktree with an active plan ref.
- Show `/perk-address` only when a PR exists.
- Show `/perk-land` only when a PR exists and is in a landable state, or let the
  underlying command refuse loudly.

### Cold-door handling in Zed

This is the crux.

When the user asks to implement from a planning thread, the adapter should not
send "implement it now" into the same Pi session. Instead:

1. Call the existing exterior logic for `perk implement <plan> --dry-run` or a
   new JSON resolver to compute the target worktree, stage, prompt, and handoff.
2. Create/position the worktree using the same implementation as the CLI.
3. Mint a new `PERK_RUN_ID` and write the handoff blob.
4. Create a new ACP session backed by a new Pi RPC process in the plan worktree.
5. Seed it with the same initial prompt that `perk implement` would pass to Pi.
6. Emit a message in the planning thread pointing to the new thread/session.

Potential ACP/Zed limitation: ACP itself does not appear to define a standard
"agent creates a sibling client-visible thread" operation. If Zed cannot be
asked to open a new External Agent thread programmatically, use a two-step
fallback:

- The current thread emits the exact action and target:
  `Implementation must start in a fresh perk thread. Start a new perk thread in
  /path/to/worktree and run /perk-implement #42.`
- The adapter records the prepared handoff so that the next session in that
  worktree claims it.

This is less polished, but it preserves the invariant. The adapter must not take
the shortcut of continuing in the planning session.

### Warm-door handling

Warm doors can be sent into the live Pi session if the stage supports
`doors.warm: true` and the current session has the right identity. Examples:

- `/perk-plan` maps to the Pi extension's plan-mode command or equivalent RPC
  input.
- `/perk-save` maps to `/plan-save` or to the model-facing save tool flow if the
  extension exposes it.
- `/perk-submit`, `/perk-address`, `/perk-land`, `/perk-learn` can flow to their
  warm slash command twins when running inside the right worktree.

If Pi RPC cannot invoke extension commands cleanly, the adapter should not fake
them with natural language prompts for mutating operations. It should use the
deterministic `perk ... --json` worker surfaces where they exist, and otherwise
fall back to an actionable refusal until Pi RPC exposes the needed command path.

### Session config options

ACP says `configOptions` are preferred for session-level configuration. perk can
use these for adapter-level choices, not workflow state:

- `model`: delegate to Pi's model config where available.
- `thought_level`: delegate to Pi where available.
- `perk_stage`: selected stage for a newly created or resumed session.
- `perk_target`: local or remote for stages that support remote dispatch.
- `perk_backend`: read-only display of GitHub/Linear backend, or selectable only
  if changing it is supported safely by config.

Do not use config options to override the registry stage graph. They are UI
selectors, not an authority.

### Tool call and progress rendering

Reuse `pi-acp`'s translation for ordinary Pi tool calls. Add perk-specific
updates where they give Zed better UX:

- Emit a `plan` update for implementation checkpoints when the saved plan has a
  `## Steps` list or when checkpoints are generated.
- Emit `tool_call` updates for exterior operations such as worktree creation,
  plan-ref materialization, GitHub issue reads, PR creation, review-thread
  resolution, and remote dispatch.
- Use `kind: "execute"` for CLI operations, `kind: "search"` for GitHub/Linear
  reads, `kind: "edit"` for deterministic file writes when locations are known,
  and `kind: "other"` for workflow state changes.
- Include file locations for `.pi/workflow/plan-ref.json`, touched worktree
  files, and generated diffs when appropriate.

Do not leak raw untrusted GitHub/Linear comments into adapter control logic.
Preserve the existing rule that reviewer/issue prose is untrusted data for the
agent session.

### Authentication

The adapter should not invent a perk auth model:

- Pi provider auth stays Pi-owned.
- GitHub auth stays `gh`-owned.
- Linear auth stays perk/backend-owned.
- ACP registry auth can use terminal auth like `pi-acp`, launching a terminal
  setup path that checks Pi and `perk doctor`.

Potential terminal auth command:

```bash
perk-acp --terminal-login
```

This should run checks and print next actions:

- Is `pi` installed and authenticated?
- Is `gh auth status` good when using the GitHub backend?
- Is Linear configured when using the Linear backend?
- Is `perk` on PATH?

### MCP

Zed can forward MCP server config over ACP. `pi-acp` currently accepts MCP
servers and stores them, but does not wire them through to Pi. perk should be
careful here:

- The first-class adapter can advertise no MCP support initially.
- If MCP forwarding is added, it should be explicit and tested end-to-end.
- Native Pi/perk MCP configuration should remain supported independently.

Given perk's current workflow, MCP forwarding is not on the critical path.

### Thread history and import

Zed can import External Agent threads if the agent supports session listing and
loading. `pi-acp` maps ACP sessions to Pi session files. perk should do the same
but include run metadata.

Benefits:

- A saved perk/Zed thread can reopen the same Pi session.
- Zed Thread History can display prior planning, implementation, address, and
  learn sessions.
- A restored session can reconstruct `run_id`, stage, and plan ref from the
  adapter map plus Pi/perk session state.

Open design point: when the same perk plan has multiple Pi sessions across
stages, Zed should probably show multiple threads, grouped by project/worktree,
rather than one mega-thread. That matches perk's cold-door context hygiene and
Zed's model of independent threads.

## Proposed UX

### First run in a project

User starts a new "perk" External Agent thread in Zed.

If the repo is not initialized:

```text
This repository is not initialized for perk.

Run:
    perk init

Then start a new perk thread.
```

If initialized:

```text
perk is ready in this repository.

Active backend: GitHub
Current stage: plan
Canonical state: GitHub issues and PRs
Local cache: .pi/workflow/
```

The adapter then starts a Pi RPC session in plan mode or idle plan-ready mode.

### Planning

The user asks:

```text
Plan how to add a Zed ACP adapter for perk.
```

The session is read-only. The model can inspect code and write a draft through
the sanctioned plan-draft path. Zed shows normal tool calls and, if possible, a
plan/checklist update.

When the user approves:

- `plan_save` or `/perk-save` writes the canonical plan.
- The thread receives a message with the plan issue and next action.

```text
Saved plan github #42.

Implementation requires a fresh context. Start:
    /perk-implement #42
```

If Zed supports opening a sibling ACP thread programmatically, offer or perform
that transition. If not, the command prepares and reports the exact next action.

### Implementation

The user runs `/perk-implement #42`.

The adapter:

- Creates/reuses `plan-42` worktree.
- Writes the cold-door handoff.
- Starts a new Pi RPC session in that worktree.
- Seeds it with the existing implement prompt from `perk/run/launch/prompts.py`.

The implementation thread is separate in Zed's Threads Sidebar. It has its own
context, history, and status.

### Submit/address/land/learn

These stages can be warm commands inside the implementation/PR thread where the
registry permits warm doors:

- `/perk-submit` opens a draft PR.
- `/perk-ready` marks it ready.
- `/perk-address --preview` classifies feedback without action.
- `/perk-address` fixes actionable feedback and resolves threads.
- `/perk-land` merges and sets pending learn.
- `/perk-learn` captures durable learnings and clears the marker.

Remote-capable stages should be explicit:

```text
/perk-dispatch implement #42
/perk-dispatch address #42
```

The adapter should surface remote run URLs and status by reading the existing
dispatch records and GitHub Actions handles.

## Implementation plan outline

This is not a detailed task plan, but the likely implementation sequence is:

1. Spike an adapter by forking or depending on `pi-acp`.
2. Add a `perk-acp` binary that initializes ACP, starts Pi RPC sessions, and
   advertises `agentInfo.title = "perk"`.
3. Add a minimal session map with ACP ID -> Pi session file -> cwd.
4. Add repo detection and `perk doctor --json`/initialization checks.
5. Add registry loading and command advertisement for read-only status plus
   `/perk-status`.
6. Implement plan-session startup in repo root.
7. Implement deterministic cold-door resolver calls for `/perk-implement`.
8. Implement new-session/worktree handoff for `implement`.
9. Add warm command passthrough for safe stages, or worker-command fallback where
   possible.
10. Add remote dispatch/readback commands for `implement` and `address`.
11. Add session load/list/import support with run metadata.
12. Package as `@perk/acp` and document Zed custom-agent setup.
13. Once stable, prepare ACP registry metadata and terminal auth.

## Testing strategy

Adapter tests should not require Zed:

- Unit-test ACP `initialize`, `session/new`, command advertisement, and config
  options using the ACP SDK types.
- Use fake Pi RPC processes for prompt/tool streaming tests.
- Use fixture `shared/registry.yaml` to ensure command availability follows the
  registry.
- Add golden tests for stage command lists.
- Add integration tests that spawn the adapter and speak JSON-RPC over stdio.
- Add a smoke test that runs against real `pi --mode rpc` only when explicitly
  enabled.
- Add a Zed manual dogfood checklist once basic functionality lands.

Important drift guards:

- Command availability must derive from `shared/registry.yaml`.
- Initial stage prompts must keep parity with `perk/run/launch/prompts.py` and
  the TypeScript interior twins, not become adapter-local copies.
- Session mapping must distinguish ACP session ID, Pi session file, and
  `PERK_RUN_ID`.
- Mutating exterior operations must go through the existing CLI/library paths,
  not TS reimplementations.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Pi RPC cannot invoke extension slash commands | Use deterministic `perk --json` worker surfaces where they exist; add Pi RPC support upstream; avoid fake natural-language command prompts for mutating operations. |
| Zed cannot be asked to create a sibling thread from an agent | Preserve the invariant by preparing the handoff and instructing the user to start the fresh thread manually. Do not continue implement in the planning thread. |
| Adapter duplicates stage behavior | Keep the adapter as transport/control plane only. Stage graph from registry; exterior operations via Python CLI/library; interior behavior via Pi extension. |
| Session identity becomes confused | Store explicit mapping: ACP session ID, Pi session file, run ID, stage, cwd, plan ref. Add tests for reload, fork, and cold relaunch cases. |
| `pi-acp` evolves or ACP changes | Keep adapter boundary small; depend on ACP SDK; preserve compatibility tests against current Zed behavior. |
| Remote/headless runner remains immature | Surface current maturity caveat in Zed. Treat remote dispatch as explicit and observable, not the default path. |
| Zed MCP forwarding creates unexpected tool surface | Start with no ACP MCP support, or store-only behavior like `pi-acp`; wire forwarding only after a focused design/test pass. |

## Recommended decision

Build a perk-owned ACP adapter, backed by Pi RPC and perk's existing exterior
CLI/library. Do not reimplement the agent runtime. Do not treat `pi-acp` alone
as the product surface. Do not let ACP's single-thread chat shape erase perk's
cold-door boundaries.

The first shippable milestone should be modest:

- Zed custom External Agent named "perk".
- New plan thread in an initialized repo.
- ACP command discovery for `/perk-status`, `/perk-plan`, `/perk-save`, and
  `/perk-implement`.
- Fresh implementation thread/worktree for a saved plan.
- Normal Pi tool streaming through ACP.

That milestone proves the hardest integration question: whether Zed can host
perk's workflow without weakening the plan -> fresh implementation boundary.
Everything after that is an incremental surface expansion.
