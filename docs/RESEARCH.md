# Pi Native Roadmap for Rebuilding the erk Workflow

## Bottom line

The best way to bring the erk workflow into Pi is **not** to do a literal Claude Code port. It should become a **Pi package** that combines three layers: **skills** for reusable procedural knowledge, **extensions** for stateful workflow control and UI, and a small amount of **project-local configuration** under `.pi/` plus your existing `AGENTS.md`. That recommendation follows directly from Pi’s architecture: Pi is intentionally small at the core, pushes workflow behavior into extensions, skills, prompt templates, and packages, and explicitly does **not** ship built-in plan mode, to-dos, or background bash. At the same time, Pi gives you the primitives to build those things yourself: commands, tools, event hooks, persistent session metadata, custom UI, dynamic tool activation, and headless SDK/RPC entry points.

That packaging boundary matters because erk is not just “a CLI plus some prompts.” The current repository spans a plan-oriented workflow end to end: README-level workflow guidance, `.claude` skills and commands, Claude hook wiring in `.claude/settings.json`, GitHub-backed plan storage, PR submission and review handling, scratch/impl directories, remote planner setup, and GitHub Actions queue support. In other words, it mixes **knowledge**, **policy**, and **orchestration**. Pi can absorb all three, but only if you put the right kind of behavior in the right Pi primitive.

The most important design principle for the migration is already visible inside erk’s own newer thinking about non-Claude backends: **do not try to fake Claude-specific affordances when the target harness has different strengths**. An erk objective for Codex explicitly argues for a backend-native experience rather than a degraded “Claude clone,” and Pi’s design philosophy points in exactly the same direction. For Pi, that means recreating the *workflow guarantees* of erk, not reproducing the `.claude/` file tree one-for-one.

## What erk is doing today

At the highest level, erk describes itself as a CLI for **plan-oriented agentic engineering**. The repository README defines the primary loop as **plan → save → implement → ship**, with Claude used for planning, `erk implement` for execution, `erk pr submit` for PR creation, `/erk:pr-address` for review response, and `erk land` for completion. The same README also says the project installs and depends on `.claude` artifacts and positions the workflow as something that often completes without opening an IDE.

The Claude-specific wiring is substantial, not incidental. The repository’s `.claude/settings.json` registers a `UserPromptSubmit` hook that shells out to `erk exec user-prompt-hook`, a `PreToolUse` hook on `Write|Edit` that shells out to `erk exec pre-tool-use-hook`, a `PreToolUse` hook on `ExitPlanMode` that shells out to `erk exec exit-plan-mode-hook`, and a `PostToolUse` hook that formats edited Python files with Ruff. That file is a good snapshot of what must move into Pi’s extension event system: prompt interception, write-policy checks, plan-mode transitions, and post-edit formatting.

The command surface is also large. Under `.claude/commands/erk/`, the repo ships commands like `objective-plan`, `plan-save`, `plan-implement`, `pr-submit`, `pr-address`, `pr-dispatch`, and `replan`. The current `plan-save` command is GitHub-backed: its documented backend creates a branch, pushes a plan commit, opens a planned draft PR, and returns structured JSON including `pr_number`, `pr_url`, and `branch_name`. The `plan-implement` command is even more orchestration-heavy: it sets up local implementation context, reads `plan.md`, loads related skills/docs, creates todo items, signals lifecycle stages, executes phases sequentially, runs CI, and only then submits the PR. 

Some of the procedural knowledge already lives in skills, but not all of it should be ported blindly. The `objective` skill defines objectives as **human-first coordination documents** for work that spans multiple plans or PRs, with the body as the current source of truth and comments acting as a changelog. The `pr-operations` skill encodes a “use only the sanctioned commands” rule for review-thread operations. By contrast, the `erk-planning` skill has already been marked as **removed**, with planning moved into slash commands and `AGENTS.md`. That tells you the future Pi design should keep **knowledge-heavy, harness-agnostic** content in skills, but keep **stateful workflow control** out of skills. 

The project setup docs reinforce that erk’s workflow is broader than an interactive prompt. Repositories are expected to contain `.erk/config.toml`, `.erk/prompt-hooks/`, and transient scratch/implementation directories; maintainers are told to commit `.claude/` artifacts into the repo; and there are explicit docs for a **remote planner** running in a GitHub Codespace plus a **queue** that relies on GitHub Actions permissions to create and update PRs. That remote surface should not be treated as an afterthought in the Pi port, but it should be built later than the interactive workflow.

There is also a structural clue in the source tree itself. Under `src/erk/`, the repo separates `capabilities`, `hooks`, `cli`, `review`, `status`, and `tui`, and under `src/erk/capabilities/` it now has folders for agents, reminders, reviews, skills, and workflows. Paired with the internal “plan lifecycle improvements” document—which proposes simplifying metadata, collapsing dual local state, leaning harder on native GitHub concepts, and reducing workflow complexity—the direction is clear: the durable value is the **workflow model**, not the original Claude-specific shell around it.

## Why Pi is the right substrate

Pi’s core design lines up unusually well with what you want to preserve from erk. Pi keeps the core small and explicitly expects advanced behavior to be built as **extensions, skills, prompt templates, and packages**. It auto-loads `AGENTS.md` and `CLAUDE.md` as context files, supports project-level `SYSTEM.md` and `APPEND_SYSTEM.md`, and can install shared resources from npm, git, or local packages. That means a Pi-native replacement can reuse your existing repository instructions while moving workflow mechanics into a versioned package.

Pi skills are also a strong fit for the parts of erk that are really reusable procedures. Skills are directories with `SKILL.md`; only their names and descriptions stay in prompt context at startup; the full body loads on demand; references and helper scripts sit alongside the skill. Pi explicitly follows the Agent Skills standard closely enough that many harness-neutral erk skills can be ported with modest cleanup. The crucial caveat is in Pi’s own docs: models do **not always** auto-read the full `SKILL.md`, so critical workflow transitions should not depend on passive skill triggering alone.

Where Pi really opens up new room is extensions. Pi extensions can register slash commands, custom tools, flags, keyboard shortcuts, and custom message renderers; they can intercept raw input before skill expansion; they can inject per-turn system prompt changes via `before_agent_start`; they can control or override tools via `setActiveTools`, built-in tool overrides, and `tool_call` / `tool_result` event handlers; and they can persist workflow state outside model context with `appendEntry`. They can also customize compaction and session-tree summaries, which matters a great deal for a long-lived plan-oriented workflow. 

Pi’s weak spots are exactly why this should be a Pi-native redesign rather than a straight port: Pi intentionally omits built-in plan mode, to-dos, and background bash. But those omissions are not blockers here. They are an architectural hint that the equivalent workflow behavior belongs in extension-owned commands, tool gating, session state, and optional custom UI. The fact that Pi’s own extension docs use “toggle plan mode” as an example for `registerShortcut` and `registerFlag` makes this even more explicit: Pi expects you to build modes like this yourself.

## The target Pi architecture

The cleanest target is a **single distributable Pi package**—for example, conceptually, `pi-erk`—with bundled extensions and skills, plus a project-local `.pi/settings.json` that enables the package and points to any repo-specific overrides. Pi packages are designed for exactly this use case: they can bundle extensions, skills, prompt templates, and themes, and project settings can selectively load them. Because Pi’s command registration is flat and duplicate names are disambiguated numerically rather than namespaced by directory, I would use either a short, unique command set like `/plan`, `/implement`, `/ship`, `/objective`, `/pr-address`, or a consistent hyphenated prefix like `/erk-plan-save` rather than trying to preserve Claude’s `.claude/commands/erk/...` namespace model. 

A workable package layout would look like this:

```text
pi-erk/
  package.json
  extensions/
    workflow-core.ts
    plan-mode.ts
    github.ts
    review.ts
    ci.ts
    queue.ts
  skills/
    objective/
    implementation/
    pr-operations/
    ci-iteration/
    coding-standards/
  prompts/
    plan-review.md
    plan-update.md
```

The **skills layer** should carry over the harness-agnostic parts of erk. That includes objective framing, PR review-response practices, CI iteration guidance, testing/coding standards, and learned reference material. The existing `objective` and `pr-operations` skills are excellent seeds for this. By contrast, anything whose primary job is to mutate GitHub state, flip modes, create branches/worktrees, or sequence the workflow should move out of `SKILL.md` and into extension commands or tools. Pi skills are best used for “how to do this well,” not “what system state should change now.”

The **extension layer** should become the control plane. In Pi terms, your current Claude hooks map naturally as follows:

- `.claude/settings.json` `UserPromptSubmit` behavior maps to Pi’s `input` and `before_agent_start` events. 
- Claude `PreToolUse` logic maps to Pi `tool_call`, plus runtime tool activation/deactivation and, where needed, overrides of built-in `write`, `edit`, or `bash`. 
- Claude `PostToolUse` logic maps to Pi `tool_result`, which can act like middleware and modify results or trigger deterministic side effects such as formatting. 
- `ExitPlanMode` behavior maps not to a hidden tool but to explicit Pi-owned commands such as `/implement` or `/approve-plan`, optionally paired with a follow-up injected user message. 

For **state**, I would use three tiers. First, keep **GitHub** as the canonical store for durable workflow artifacts: objectives, plans, and PR review state. Second, keep a small **local cache** under `.pi/workflow/` for materialized `plan.md`, run metadata, generated summaries, and repo-specific config. Third, keep **session-local workflow state**—current mode, active objective, active plan ID, checkpoints, last review batch—inside Pi’s session file as custom entries via `appendEntry`, plus labels and session names for navigation. Pi’s session format is explicitly built for custom entries, tree-based branching, and compaction summaries, which is much closer to what you need than continuing to depend on `CLAUDE_SESSION_ID`.

For **plan mode**, I would build a Pi-native version rather than emulating Claude’s permission UI. Concretely: register a `--plan` flag and a keyboard shortcut; persist the mode in session state; show a footer status like `PLAN MODE`; restrict active tools to read-oriented tools like `read`, `grep`, `find`, and `ls`; optionally provide a safe read-only shell wrapper; and block `write`, `edit`, and unsafe `bash` paths in `tool_call`. Use `before_agent_start` to inject mode-specific instructions into the system prompt for each turn. When the user approves the plan, let `/implement` restore the full toolset, materialize the plan locally, set the session name, and queue the implementation kickoff as a follow-up message. That delivers the real value of plan mode—no code changes before approval—without trying to recreate Claude’s built-in mode switch exactly.

For **GitHub integration**, I would be deliberately pragmatic. In the first release, let the extension shell out to `gh` for plan creation, PR updates, and issue/objective management, because current erk docs already assume GitHub CLI auth, and Pi extensions can run shell commands or ship npm dependencies. Once the workflow is stable, move the metadata-sensitive operations—especially plan creation/update and review-thread resolution—behind dedicated extension tools backed by an API client so that the model always uses a deterministic surface rather than hand-composed shell commands. That change mirrors what erk’s own `pr-operations` skill was trying to enforce with `erk exec`: the *principle* is what matters, not the old binary name.

Finally, for **remote execution and queueing**, Pi’s SDK and RPC mode are the right primitives. The remote planner and GitHub queue in erk should become a **headless Pi worker**—running either via the SDK in-process or `pi --mode rpc` in a subprocess—inside GitHub Actions, a Codespace, or another controlled environment. That worker can load the same package, process queued objectives/plans, and stream structured events back into GitHub comments or checks. Pi’s docs make clear that this kind of embedding is first-class, and it is a much better foundation than trying to recreate Claude’s session-specific hook behavior in a remote shell. 

## Implementation roadmap

1. **Build the package foundation first.** Create the Pi package, add project-level installation through `.pi/settings.json`, define the local `.pi/workflow/` directory layout, and write a bootstrap command that can inspect an existing erk repo and generate Pi config from what it finds in `AGENTS.md`, `.erk/`, and `.claude/`. Use `resources_discover` if you want the extension to contribute skill/prompt paths dynamically, but keep the default install path simple enough that a maintainer can understand it by reading one settings file. Also decide here whether you will preserve draft-PR plan storage for migration compatibility in v1, or immediately adopt the simpler “single canonical body plus workflow-created PR” direction discussed in erk’s architecture docs.

2. **Implement planning and objective management before coding automation.** Port the `objective` skill, add a custom Pi plan mode, and ship the first deterministic commands: `/plan`, `/plan-save`, `/replan`, `/objective`, and `/objective-plan`. The extension should own mode state, tool gating, footer/status display, and approval transitions; the skills should provide the reasoning and document structures. This is the point where you should also port any high-value “learned docs” reference content that improves planning quality, because Pi’s on-demand skill loading lets you keep those references cheap until needed. Do **not** rely on passive skill triggering for any critical action; make every workflow boundary an explicit command or tool.

3. **Then rebuild implement, review, and ship as extension-owned orchestration.** Replace `plan-implement`, `pr-submit`, and `pr-address` with Pi commands and tools that own branch/worktree setup, local plan materialization, review-thread fetch/resolve, commit/PR generation, and CI policy. Reuse the *shape* of erk’s current implementation flow—read the plan, load related docs, execute phases, run CI, submit PR—but stop depending on the Python CLI as the workflow engine. Project-specific equivalents of `.erk/prompt-hooks/post-plan-implement-ci.md` and `.erk/prompt-hooks/commit-message-prompt.md` should become extension-readable config or project-local markdown that the extension injects at the right point in the Pi workflow. If you need checklists, build them as either extension tools or custom session messages instead of trying to recreate Claude’s internal todo abstractions.

4. **Only after the interactive path is solid should you add queueing and remote workers.** At that point, build a headless runner with the Pi SDK or RPC mode, wire it to GitHub Actions or a Codespace-based worker, and let it process queued work using the same extension package the local user runs. This is also the right phase to add migration helpers: import existing planned PRs, translate old objective markers, and map any remaining `.claude` references to Pi-native state. Finish by adding automated tests at two levels: extension/command tests using Pi’s SDK and in-memory session facilities, and end-to-end worker tests using RPC or print/JSON mode. 

## Risks and non-goals

The biggest risk is trying to make Pi behave *exactly* like Claude Code. That is the wrong target. Claude has a built-in `EnterPlanMode` / `ExitPlanMode` tool path and a full hook system around session and tool lifecycle; Pi gives you extension events, commands, tool gating, and UI components instead. You should preserve the **behavioral contract**—plan before writing, deterministic review operations, durable GitHub-backed workflow state—not the Claude-specific mechanism. 

The second major risk is putting too much weight on skills. Pi skills are valuable, but Pi’s own docs say the model may not always load the full skill body automatically. That makes them ideal for reusable expertise and reference material, but not for authoritative workflow transitions. If a step mutates state, touches GitHub, changes modes, or must happen consistently, it belongs in an extension command or tool. In practical terms: port `objective` and review guidance as skills, but make `/plan-save`, `/implement`, `/ship`, and review resolution deterministic extension surfaces.

A third risk is carrying forward too much of erk’s old complexity. I would explicitly **not** port the full Textual-style dashboard/TUI surface in the first release, even though erk’s changelog shows the project invested heavily in rich UI. Pi already gives you lightweight status lines, widgets, custom messages, and optional custom UI; use those first. Likewise, I would not make the initial release dependent on separate remote-planner flows, queueing, or elaborate multi-location local state. Interactive local workflow first, headless worker second, rich dashboard last.

The final design decision I would make up front is this: **do not port “erk the binary”; port “erk the workflow.”** Use Pi packages for distribution, Pi skills for portable expertise, Pi extensions for hook-like control and deterministic commands, GitHub as canonical durable storage, and Pi session metadata for transient workflow state. That gives you a Pi-native system that can still feel recognizably like erk where it matters, while staying aligned with both Pi’s extension model and erk’s own newer backend-aware design direction.
