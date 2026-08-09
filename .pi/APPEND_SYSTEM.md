<!--
  This file is appended to every perk session's system prompt (Pi's project-scoped
  .pi/APPEND_SYSTEM.md). It holds the COMPRESSED, ambient routing index into docs/learned/ —
  the realization of the "compressed index must be ambient" finding (a retrieval-tier index is
  too brittle to rely on). Keep it SMALL: one terse routing line per durable doc, pointing into
  the full catalog at docs/learned/index.md (read on demand).

  The routing block below is GENERATED from each doc's title + read_when frontmatter by
  `perk learn docs-sync` — edit the docs' frontmatter, not this block. `perk learn docs-check`
  reports drift on demand.
-->

## Durable learnings (docs/learned)

Cross-cutting reasoning captured for future agents lives in `docs/learned/`. The full catalog is
`docs/learned/index.md`; read a specific doc when its routing cue matches your task.

<!-- BEGIN perk docs-sync (generated — do not edit between these markers) -->
- **pi/context-injection** — You are injecting context into a session (planMode/objectiveAuthor/bindings) and stripping it later, deduplicating an injection via branchCarries, or serving two stages from one adapter.
- **pi/context-system** — You are surfacing information to a session, debugging a blocked bash command in read-only, extending the read-only bash allowlist (five-surface lockstep), or the worktree AGENTS.md double-load.
- **pi/extension-api** — You need live system-prompt inputs, a command vs lifecycle-event handler choice, session_compact, pi.exec, dogfooding just-changed extension code, or offline-testing through the harness.
- **pi/extension-seams** — You are collapsing a repeated extension idiom into one tested seam (report()/branchOf/branchCarries), extracting a tool's execute core, or evacuating survivor code from a retiring module.
- **pi/headless-session-drive** — You are constructing or driving a headless (non-TUI) Pi session via the SDK — the runtime-factory path, bindExtensions, a single-prompt drive, offline model determinism, or worker extension scoping.
- **pi/structured-output** — You need a model to return structured/typed data in an extension, are gating a model call offline in tests (PERK_NO_LLM is the only gate), or are writing offline tests for provider-calling code.
- **pi/subagents** — You are spawning a subagent, configuring an agent's model, re-enabling a disabled builtin, supervisor-channel streaming, observing child token/cache usage, /pr-review or /address, or perk agent defs.
- **pi/tool-param-decode** — You are decoding registered-tool params, adding a tool handler, choosing strict vs lenient decode semantics at a boundary, or adding a backend-agnostic id param (idParam/idArrayParam).
- **pi/tui-surfaces** — You are touching extension/surfaces/surfaces.ts or any perk-rendered TUI surface (footer, status slot), adding a rich-UI call, or testing footer rendering through the harness.
- **toolchain/biome** — You hit a Biome or tsc error in the extension, a discriminated-union narrowing surprise, a `--write` formatting trap (template-literal prose, new-file collapse), or the JS object-shape guard idiom.
- **toolchain/python-package-splits** — You are splitting a `perk/<mod>.py` into a `perk/<mod>/` package, folding a flat module into a package / relocating across packages, or fixing monkeypatch or source-scan-guard fallout from a move.
- **toolchain/ruff** — You are debugging a CI-green / commit-rejected discrepancy, a commit that seems not to advance after a pre-commit hook, UP047 on a generic function, or an ambiguous-unicode lint on a semantic glyph.
- **toolchain/test-parallelism** — You are making `just test` / `just ci` faster, adding pytest-xdist config, or splitting a harness-heavy `node:test` file into siblings.
- **toolchain/ts-module-moves** — You are moving extension TS modules into a subdirectory (the extension-layout tranches), auditing a path-rewrite sweep, or a justfile/Node test glob is dropping nested tests.
- **toolchain/ty** — You hit a ty invalid-argument-type, no-matching-overload, or invalid-assignment (subscript write) on untyped/JSON values, need the _require_*/_opt_* narrowing helpers, or tightening Any→object.
- **toolchain/uv-workspace-src-layout** — You are converting or maintaining the uv-workspace root-package `src`-layout (`src/perk`), hit the ty-root/pytest dotted-import trap, or editing the lockstep config surfaces (wheel/sdist/ty/ruff).
- **toolchain/worktree-node-modules** — CI surfaces failures in files your diff never touched, a fresh worktree fails `tsc`/`node --test` before `npm ci`, a pinned Pi/SDK bump seems inert, or you hit lockfile churn / an already-red main.
- **workflow/borrowed-packages** — You are adding, retiring, or changing a borrowed Pi package (`BORROWED_PACKAGES`), vetting a borrow candidate, allowlisting its tools in read-only mode, or weighing a provider seam vs a plain borrow.
- **workflow/broad-catch-narrowing** — You are narrowing broad `except Exception` catches to typed expected failures, choosing a typed catch set for a fail-open boundary, or planning an exception-posture sweep.
- **workflow/cli-command-groups** — You are adding or folding a `perk` CLI command group, touching the sectioned root `--help` taxonomy, wrapping an upstream CLI as a pass-through noun-group, or running a structural CLI refactor.
- **workflow/cold-door-client** — You are adding a warm door that shells to a `--json` cold door, writing or strictening a cold-door envelope decode, consuming a fail-arm payload, or hardening a door against cold/warm version skew.
- **workflow/cold-door-launch** — You are touching launch_stage's argv construction, child env injection at the launch seam, the `[worktree] setup` hook, worktree positioning, or the `io_step` leveled progress-log discipline.
- **workflow/config-tables** — You are adding a [table] or key to .perk/config.toml, deciding where a knob is consumed, anchoring a committed read to the main checkout, a `local.toml` secret fallback, or CI-check gating.
- **workflow/distribution** — You are working on perk's release workflow (`perk-dev release-*`), the version SSOT, PyPI/npm publishing, version parity, the `@mgiles/perk` install path, or the CHANGELOG bullet-token grammar.
- **workflow/doc-reconciliation** — You are reconciling a guidelines/design/validation doc against reality, sweeping prose after a symbol retires, staging a dogfood record, sequencing work around /submit, or objective roadmap prose.
- **workflow/dot-directory-migration** — You are relocating a perk-owned dot-directory path root, using the centralized path seam (`paths.py`/`paths.ts`), answering "where does X live?", or dogfooding a gitignored cache-root move mid-flight.
- **workflow/execution-path-parity** — You are adding or auditing a warm/cold-local/remote surface, enforcing one-implementation-per-stage, writing a cross-plane or cross-path parity test, or naming vs converging a path difference.
- **workflow/extension-clone-lifecycle** — You need pi's `git:`-package loading internals, or are retiring an orphaned substrate lifecycle — NOTE the git-clone extension delivery is RETIRED (perk ships via npm; see `distribution.md`).
- **workflow/github-gateway** — You are touching `perk/github/`, adding a REST/GraphQL call, designing a mutation-posting policy or failure ladder, debugging a phantom-`None` lookup, or parsing diffs into review-comment anchors.
- **workflow/human-engagement-reads** — You are working on the §8.25 human-engagement read contract — a read seam (issue-keyed vs node-keyed), a flow consumer, the `perk/backends/engagement.py` renderers, or the delivery asymmetry.
- **workflow/in-place-adoption** — You are adopting an existing issue or Linear project as a perk plan/objective in place (`plan from`, `objective author --from`), seeding authoring from a file/URL, or byte-preserving a foreign field.
- **workflow/init-doctor** — You are adding a managed piece (so a doctor check), growing `managed_artifacts()`, touching the managed-state file, init's gitignore block, or adding a doctor migration, gated probe, or repair.
- **workflow/init-external-cli** — You are making perk init shell out to an external CLI (skills, gh, …), choosing its failure posture (best-effort vs load-bearing), or promoting an external skill into the managed manifest.
- **workflow/issue-backend** — You are touching perk/backends/issue_backend.py, its GitHub adapter, the resolver in perk/backends/resolve.py, an issue-tier consumer, adding a backend, or the boundary/import-direction tests.
- **workflow/learn-evidence-pipeline** — You are touching any stage of the `/learn` evidence pipeline — session pointers, JSONL export, the evidence bundle, the multi-angle orchestrator — or the Pi session-file/JSONL-grammar facts.
- **workflow/linear-backend** — You are touching `perk/backends/linear/`, Linear GraphQL queries or test fakes, perk metadata (attachments or inline markers), init/doctor readiness, or the project-backed objective store.
- **workflow/mergeability-and-conflict-resolution** — You are touching the merge-tree conflict probe (`perk/substrate/git.py`), the `/submit` warm reactive drive, the conflict-resolver subagent, a PR-mergeability gotcha, or a post-rebase prose sweep.
- **workflow/objective-lifecycle** — You are working on objective node status transitions, objective-plan factory selection, the authoring/save loop, the `perk objective run` supervisor, design-only nodes, or a node stuck in planning.
- **workflow/objective-store** — You are touching `perk/backends/objective_store.py`, its GitHub/Linear stores, an objective-storage consumer, the node↔plan unification protocol, objective replan/supersede, or Protocol growth.
- **workflow/plan-factories** — You are building or debugging a perk plan factory (learn-docs, objective-plan, or any new read-only planning launcher), extracting an N-sibling factory family, or wiring a new sibling's lockstep.
- **workflow/plan-ref-lifecycle** — You are debugging plan-ref linkage or a clobbered worktree binding, adding a worktree stage, the PlanRef/PlanHeader schema, a non-default base, a replan reusing plan-<N>, or on-land bookkeeping.
- **workflow/plan-review-flow** — Working on plan_review / a review backend (plannotator, first-party, tombell), the approvalSave seam, plan-source resolution, Plannotator Direct Edits / the diff apply, or the `pi.events` bridge.
- **workflow/plan-save-surfaces** — You are working on plan-save / objective-node linkage, debugging a dropped objective_id / consumed_learn, touching resolvePlanSource's chain, or prepending a copyable command callout to an artifact.
- **workflow/prompt-templates** — You are bundling a top-level resource dir, working the cross-plane jinja2/miniJinja render seam, the CRLF byte-parity hazard, or moving an inline prompt literal onto a `prompts/` template.
- **workflow/provider-seam** — You are working on a provider seam (plan/footer/web) — classifying a seam-vs-borrow candidate, wiring or widening a provider, vacating a collision, retiring a seam, or the cross-plane resolver.
- **workflow/pydantic-boundary-models** — Converting a config/registry/objective/cache or external-API boundary onto the lenient-parse-model → frozen-`@dataclass` → `validate()` pattern, or pinning a `--json` envelope onto `OutputModel`.
- **workflow/remote-runner** — You are working on `perk/run/` (runner, run_worker, discovery), the `perk-run.yml` workflow + `perk-remote-setup` action, the `--remote` dispatch path, or the worker-entry resolver.
- **workflow/report-waves** — You are touching extension/waves/, migrating flow prompt mechanics onto a code-owned wave tool, debugging lane coverage or wave guard state, or writing wave tests.
- **workflow/seeded-door-pipeline** — You are adding or converting a seeded cold door (a launcher that materializes untrusted data into scratch and execs pi with a seeded prompt), or touching `perk/cli/commands/seeded_door.py`.
- **workflow/session-data** — You are working on run_id minting/claiming, `extension/substrate/sessionData.ts` / `perk/state/cache.py`, provenance pointers, a session-data producer/consumer, or `perk state prune` / cache-gc.
- **workflow/shared-contracts** — You are adding a cross-plane data file under shared/, a registry stage (or its `writes`), dieting an overgrown contracts.md section, or making a prompt fragment agree byte-for-byte across planes.
- **workflow/skill-bindings** — You are working on skill bindings (.pi/perk.toml [[bindings]]), the delivery doors and resolver, the worktree skill mirror, a single-delivery test pin, or double-delivered/missing binding context.
- **workflow/skills-exposure** — You are touching the layered skills-exposure model (skill_exposure.py, stages frontmatter, [skills] config), scoping launch skill discovery, or designing an engagement-gated zero-change rollout.
- **workflow/source-scan-guards** — You are adding or extending a test that enforces call-site or string-literal confinement by scanning source (the surfaces guard), or deciding whether to allowlist a firing guard.
- **workflow/test-pin-sweeps** — You are editing prose or constants that tests pin — planning an editorial rewrite of tested prose, a wrap-bisected substring pin, or an exact-set deepEqual pin on a grown constant.
- **workflow/warm-door-commands** — You are building or fixing a warm perk slash-command (/plan-save, /address, …), debugging a door that dead-ends or false-succeeds, a drive naming a stage-scoped tool, or a human-facing gesture.
- **workflow/worktree-lifecycle** — You are writing a worktree-batch command, extending `perk worktree wipe`'s residue sweep, the `[worktree] setup` hook, locating the main checkout via `main_worktree_root`, or a dirty worktree test.
- **workflow/write-capable-cold-doors** — You are building or debugging a write-capable cold door (`perk skills create`/`refine`), the repo-authored-skills lifecycle verbs, main-checkout resolution from a worktree, or the dogfood-gate test.
<!-- END perk docs-sync -->
