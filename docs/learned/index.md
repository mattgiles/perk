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
| workflow | [objective-lifecycle.md](workflow/objective-lifecycle.md) | Working on objective node status transitions, objective-plan selection, the authoring/save loop, the deterministic `perk objective run` supervisor loop, or a node stuck in planning |
| workflow | [warm-door-commands.md](workflow/warm-door-commands.md) | Building or fixing a warm perk slash-command (/plan-save, /objective-save, /address, /learn-docs), debugging a command that dead-ends or false-succeeds, or wiring how a warm TS door renders a cold Python door's structured sub-result |
| workflow | [skill-bindings.md](workflow/skill-bindings.md) | Working on skill-binding config, the cold/warm delivery doors, the resolver, doctor validation of bindings + the injection-presence mirror, or debugging double-delivered / missing binding context |
| workflow | [shared-contracts.md](workflow/shared-contracts.md) | Adding parsed shared/ data files, registry stages, prose contracts maintenance (§-numbering grep), post-merge objective roadmap reconciliation, or tracing shared contract ripples |
| workflow | [init-doctor.md](workflow/init-doctor.md) | Adding a managed piece (doctor checks), adding a transient file to gitignore, doctor migration, templates reconvergence, Click bottom-of-file imports and register_with_aliases arity, doctor-disk vs selfcheck-prompt, _GROUP_ORDER trap, or report-only pre-flights |
| workflow | [init-external-cli.md](workflow/init-external-cli.md) | Making perk init shell out to an external CLI, declaring a committed manifest fragment, pinning a self-repo vs consumer ref, or scoping a cross-repo plan to the perk slice |
| workflow | [config-tables.md](workflow/config-tables.md) | Adding a [table] to perk.toml, choosing where a knob is consumed (TS interior gate vs init→settings.json convergence), or a config value silently vanishing (string-only / bool-is-int) |
| workflow | [cli-command-groups.md](workflow/cli-command-groups.md) | Adding/folding a `perk` CLI command group (the §8.1 group-dir template), resolving a stage-launcher/group name collision (hybrid default-dispatch), the sectioned root `--help` taxonomy, per-group `fail()` byte-compat across folds, or a structural CLI refactor's parity smoke + test patterns |
| workflow | [cold-door-client.md](workflow/cold-door-client.md) | Migrating a warm door onto `runColdDoor`, writing a cold-door envelope decode (strict core vs advisory validated-but-dropped), composing the narrowing helpers, the legacy-label byte-compat lever, or door-test assertion churn after a migration |
| workflow | [borrowed-packages.md](workflow/borrowed-packages.md) | Adding/removing a borrowed Pi package (the `BORROWED_PACKAGES` lockstep-surfaces recipe), allowlisting a borrowed package's tools in read-only mode, or deciding between a provider seam and a plain borrow |
| workflow | [cold-door-launch.md](workflow/cold-door-launch.md) | Touching launch_stage argv/--approve trust injection, wrapping a last-wins CLI, or composing/testing a Python surface that nests a machine_output command |
| workflow | [worktree-lifecycle.md](workflow/worktree-lifecycle.md) | Writing a worktree-batch CLI, matching git worktree paths (the .resolve() trap), split --force semantics, or a worktree test that is unexpectedly dirty |
| workflow | [provider-seam.md](workflow/provider-seam.md) | Working on the plan/todo provider seam — the selection substrate, deferring perk's own authoring surface under a foreign selection, the cross-plane resolver, wiring a foreign plan/todo adapter, or an augment-posture provider (the plannotator bridge + persisted-mode gate read) |
| workflow | [remote-runner.md](workflow/remote-runner.md) | Working on remote execution (runner, work_worker, GHA workflows), cancel/retry supervisor controls, GHA rerun reuse, universal zero-spend smoke short-circuit, fail-soft orchestrator overlays vs local records truth, or subprocess monkeypatching traps |
| pi | [context-system.md](pi/context-system.md) | Surfacing information to a plan session, building a factory, debugging why a bash command is blocked, or adding a read-only bash allowlist entry |
| pi | [extension-api.md](pi/extension-api.md) | Live system-prompt inputs in extensions, registerTool execute results details requirement, custom tool read-only gating traps, tsconfig strict-mode index access in tests, command vs event handlers, injected-message persistence, or testing `pi.events`-bridge logic / flag-shortcut non-registration from the harness |
| pi | [extension-seams.md](pi/extension-seams.md) | Collapsing a repeated context-dependent extension idiom into one tested seam (the `report()`/`branchOf` minimal-structural-interface recipe), the seam-owned-prefix trap, or the P1/P2/P3 site triage for what a single-message seam can absorb |
| pi | [context-injection.md](pi/context-injection.md) | Injecting context into a session (planMode/objectiveAuthor/bindings) and stripping it later, or disambiguating two stages that share a read-only mode |
| pi | [structured-output.md](pi/structured-output.md) | Getting typed/structured output from a model in an extension, gating a model call offline in tests, or writing offline tests for provider-calling code |
| pi | [headless-session-drive.md](pi/headless-session-drive.md) | Constructing or driving a headless (non-TUI) Pi session via the SDK — the runtime-factory path, bindExtensions, session.subscribe event facts, a single-prompt drive + budget watchdog, the structured run-event stream, offline model-availability determinism, or driving the real runtime with a faux model (the nested-pi-ai per-instance registry trap) |
| pi | [subagents.md](pi/subagents.md) | Spawning subagents for fresh-context work, flat agent/seam-keyed config, TS TOML backslash continuation restriction, cross-plane model/prompt literal parity, exported guidance unit-testing, or child-posts-own-mutation vs parent-mutates |
| toolchain | [ruff.md](toolchain/ruff.md) | Ruff check vs format split, silent-failure commit-reformat traps, RUF100 unused noqa rules, template string E501 multiline limits, or SIM105 exception suppressions |
| toolchain | [biome.md](toolchain/biome.md) | Hitting a Biome lint or tsc error in the extension (incl. TS parameter-property stripping under `node --test`, the `organizeImports` assist-only-under-`check`, the `let x = undefined` trap, forEach expression-body assertions), or a CI lint iteration on TS formatting (new files: `biome check --write` first) |
| toolchain | [worktree-node-modules.md](toolchain/worktree-node-modules.md) | CI failing in files your diff never touched, a fresh worktree failing `tsc`/`node --test` before `npm ci`, a pinned Pi/SDK version bump in a worktree seeming to do nothing, or a `shared/` change not reflected when smoked via the stale global `perk` (and the worktree self-converge trap) |
| toolchain | [ty.md](toolchain/ty.md) | Hitting a ty invalid-argument-type / no-matching-overload error narrowing untyped or object-form values parsed from JSON/settings |
