---
title: docs/learned catalog
read_when: You need to find a durable learned doc, or you are authoring/refreshing one via /learn-docs.
---

# `docs/learned/` — the durable learnings catalog

This is the **full catalog** of perk's learned docs: token caches of cross-cutting reasoning for
future AI agents, consolidated from terminal `perk:learn` issues by the `/learn-docs` plan factory
(see the `perk-learn-docs` skill). Each doc lives under `docs/learned/<category>/` with light
frontmatter (`title` + `read_when`).

A **compressed routing index** of these docs is kept ambient in `.pi/APPEND_SYSTEM.md` (appended to
every session's system prompt); this file is the on-demand full listing that ambient index points
into. Both are maintained by `/learn-docs` plans — never by `perk init`.

## Documents

| Category | Document | Read when |
|---|---|---|
| workflow | [plan-factories.md](workflow/plan-factories.md) | Building or debugging a perk plan factory (learn-docs, objective-plan, any on-demand factory launching a read-only session) |
| workflow | [plan-ref-lifecycle.md](workflow/plan-ref-lifecycle.md) | Debugging plan-ref linkage, adding a worktree stage, extending PlanRef schema, or implementing on-land secondary bookkeeping |
| workflow | [plan-save-surfaces.md](workflow/plan-save-surfaces.md) | Working on plan-save / objective-node linkage, debugging a dropped objective_id / consumed_learn, or adding context that must survive a model's save-surface choice |
| workflow | [objective-lifecycle.md](workflow/objective-lifecycle.md) | Working on objective node status transitions, objective-plan selection, the authoring/save loop, or a node stuck in planning |
| workflow | [warm-door-commands.md](workflow/warm-door-commands.md) | Building or fixing a warm perk slash-command (/plan-save, /objective-save, /address, /learn-docs), debugging a command that dead-ends or false-succeeds, or wiring how a warm TS door renders a cold Python door's structured sub-result |
| workflow | [skill-bindings.md](workflow/skill-bindings.md) | Working on skill-binding config, the cold/warm delivery doors, the resolver, doctor validation of bindings + the injection-presence mirror, or debugging double-delivered / missing binding context |
| workflow | [shared-contracts.md](workflow/shared-contracts.md) | Adding a parsed shared/ data file, adding a registry stage, or tracing how a shared contract ripples into both planes + tests |
| workflow | [init-doctor.md](workflow/init-doctor.md) | Adding a managed piece (so a doctor check), adding a transient file to gitignore, writing a doctor migration, extending init's managed gitignore block, or the doctor-disk vs selfcheck-prompt division |
| workflow | [init-external-cli.md](workflow/init-external-cli.md) | Making perk init shell out to an external CLI, declaring a committed manifest fragment, pinning a self-repo vs consumer ref, or scoping a cross-repo plan to the perk slice |
| workflow | [provider-seam.md](workflow/provider-seam.md) | Working on the plan/todo provider seam — the selection substrate, deferring perk's own authoring surface under a foreign selection, the cross-plane resolver, or wiring a foreign plan/todo adapter |
| workflow | [remote-runner.md](workflow/remote-runner.md) | Working on `perk/runner.py` / `perk/run_worker.py`, the `perk-run.yml` workflow + `perk-remote-setup` composite action, the remote `--remote` dispatch path, the verify-by-discovery poll, or the worker-entry resolver |
| pi | [context-system.md](pi/context-system.md) | Surfacing information to a plan session, building a factory, debugging why a bash command is blocked, or adding a read-only bash allowlist entry |
| pi | [extension-api.md](pi/extension-api.md) | Needing live system-prompt inputs in an extension, choosing a command vs lifecycle-event handler, importing a Pi type, or reasoning about injected-message persistence |
| pi | [context-injection.md](pi/context-injection.md) | Injecting context into a session (planMode/objectiveAuthor/bindings) and stripping it later, or disambiguating two stages that share a read-only mode |
| pi | [structured-output.md](pi/structured-output.md) | Getting typed/structured output from a model in an extension, gating a model call offline in tests, or writing offline tests for provider-calling code |
| pi | [headless-session-drive.md](pi/headless-session-drive.md) | Constructing or driving a headless (non-TUI) Pi session via the SDK — the runtime-factory path, bindExtensions, session.subscribe event facts, a single-prompt drive + budget watchdog, the structured run-event stream, or offline model-availability determinism |
| pi | [subagents.md](pi/subagents.md) | Spawning a subagent for fresh-context work, configuring a project agent's model, choosing read-only-child-then-parent-mutates vs child-posts-own-mutation, or working on the `/pr-review` / `/address` orchestration |
| toolchain | [ruff.md](toolchain/ruff.md) | Debugging a CI-green / commit-rejected discrepancy, or a commit that silently didn't advance after a pre-commit hook |
| toolchain | [biome.md](toolchain/biome.md) | Hitting a Biome lint or tsc error in the extension (incl. TS parameter-property stripping under `node --test`, the `organizeImports` assist-only-under-`check`, the `let x = undefined` trap), or a CI lint iteration on TS formatting |
| toolchain | [worktree-node-modules.md](toolchain/worktree-node-modules.md) | CI failing in files your diff never touched, a pinned Pi/SDK version bump in a worktree seeming to do nothing, or a `shared/` change not reflected when smoked via the stale global `perk` (and the worktree self-converge trap) |
| toolchain | [ty.md](toolchain/ty.md) | Hitting a ty invalid-argument-type / no-matching-overload error narrowing untyped or object-form values parsed from JSON/settings |
