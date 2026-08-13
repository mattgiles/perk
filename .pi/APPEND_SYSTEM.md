<!--
  This file is appended to every perk session's system prompt (Pi's project-scoped
  .pi/APPEND_SYSTEM.md). It holds the COMPRESSED, ambient routing index into docs/learned/ —
  the realization of the "compressed index must be ambient" finding (a retrieval-tier index is
  too brittle to rely on). Keep it SMALL: one line per cluster — id + rollup cue + member
  doc slugs; the full per-doc cues live in the catalog at docs/learned/index.md (read on
  demand).

  The routing block below is GENERATED from docs/learned/clusters.yaml + each doc's frontmatter
  by `perk learn docs-sync` — edit the registry / the docs' frontmatter, not this block.
  `perk learn docs-check` reports drift on demand.
-->

## Durable learnings (docs/learned)

Cross-cutting reasoning captured for future agents lives in `docs/learned/`. The full catalog is
`docs/learned/index.md`; read a specific doc when its cluster's rollup cue matches your task.

<!-- BEGIN perk docs-sync (generated — do not edit between these markers) -->
- **pi-extension** — Pi SDK/extension substrate craft — API facts, context injection/loading, seams, TUI surfaces, tool-param decode, structured output, headless session driving. (pi/context-injection, pi/context-system, pi/extension-api, pi/extension-seams, pi/headless-session-drive, pi/structured-output, pi/tool-param-decode, pi/tui-surfaces)
- **subagent-orchestration** — Spawning and orchestrating subagents — pi-subagents mechanics, agent defs, report waves, lane semantics, streaming. (pi/subagents, workflow/report-waves)
- **toolchain-gotchas** — Lint/typecheck/test toolchain gotchas — Biome/tsc, ruff, ty, node:test determinism, test parallelism, worktree node_modules, Astro/Starlight docs-site. (toolchain/biome, toolchain/docs-site-astro-starlight, toolchain/node-test-async-determinism, toolchain/pytest-prompt-hermeticity, toolchain/ruff, toolchain/test-parallelism, toolchain/ty, toolchain/worktree-node-modules)
- **code-migration** — Moving code shapes safely — Python module→package splits, TS module moves, src-layout conversion, dot-directory path-root migrations. (toolchain/python-package-splits, toolchain/ts-module-moves, toolchain/uv-workspace-src-layout, workflow/dot-directory-migration)
- **doors-and-launch** — CLI↔session plumbing — cold-door launch/client, warm-door commands, CLI command groups, factory/seeded doors, write-capable doors, the remote runner. (workflow/cli-command-groups, workflow/cold-door-client, workflow/cold-door-launch, workflow/plan-factories, workflow/remote-runner, workflow/warm-door-commands, workflow/write-capable-cold-doors)
- **plan-lifecycle** — The plan artifact's life — plan-ref linkage, review→approval→save surfaces, worktree lifecycle, session data/run identity, mergeability + conflict resolution. (workflow/mergeability-and-conflict-resolution, workflow/plan-ref-lifecycle, workflow/plan-review-flow, workflow/plan-save-surfaces, workflow/session-data, workflow/worktree-lifecycle)
- **objective-system** — Objectives — the node state machine and authoring loop, objective storage Protocol, stacked delivery trains. (workflow/objective-delivery, workflow/objective-lifecycle, workflow/objective-store)
- **backends-and-integrations** — Issue backends and external integrations — the issue-tier Protocol, GitHub gateway, Linear backend, human-engagement reads, in-place adoption. (workflow/github-gateway, workflow/human-engagement-reads, workflow/in-place-adoption, workflow/issue-backend, workflow/linear-backend)
- **config-and-convergence** — Repo wiring and convergence — config tables, init/doctor, external CLIs, borrowed packages, provider seams, skill bindings/exposure, distribution. (workflow/borrowed-packages, workflow/config-tables, workflow/distribution, workflow/init-doctor, workflow/init-external-cli, workflow/provider-seam, workflow/skill-bindings)
- **cross-plane-contracts** — Cross-plane/cross-path agreement — shared/ parsed contracts, prompt-template render parity, execution-path parity testing, §8.57 prompt-carrier layering. (workflow/execution-path-parity, workflow/prompt-carrier-layering, workflow/prompt-templates, workflow/shared-contracts)
- **knowledge-stewardship** — Keeping the record true — the /learn evidence pipeline and harvest core, doc-reconciliation craft, session-audit expectation curation, binding design records. (workflow/binding-design-records, workflow/doc-reconciliation, workflow/learn-evidence-pipeline, workflow/session-audit-expectations)
- **quality-and-guards** — Code-quality disciplines — source-scan guard tests, test-pin sweeps, broad-catch narrowing, Pydantic boundary models, lease-fenced outbox delivery. (workflow/broad-catch-narrowing, workflow/lease-outbox-delivery, workflow/pydantic-boundary-models, workflow/source-scan-guards, workflow/test-pin-sweeps)
<!-- END perk docs-sync -->
