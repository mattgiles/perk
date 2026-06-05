<!--
  This file is appended to every perk session's system prompt (Pi's project-scoped
  .pi/APPEND_SYSTEM.md). It holds the COMPRESSED, ambient routing index into docs/learned/ —
  the realization of the "compressed index must be ambient" finding (a retrieval-tier index is
  too brittle to rely on). Keep it SMALL: one terse routing line per durable doc/category,
  pointing into the full catalog at docs/learned/index.md (read on demand).

  Maintained by /learn-docs consolidation plans (the perk-learn-docs skill) — NEVER by `perk init`.
-->

## Durable learnings (docs/learned)

Cross-cutting reasoning captured for future agents lives in `docs/learned/`. The full catalog is
`docs/learned/index.md`; read a specific doc when its routing cue matches your task.

<!-- routing index — one terse line per doc/category; empty until the first /learn-docs plan lands -->

- **workflow/** — plan factories, plan-ref lifecycle, plan-save surfaces (fidelity gap & handoff_extra carrier), objective lifecycle (resumable-lease nodes & authoring loop), skill bindings (two-plane delivery), shared `shared/` contracts recipe, init/doctor division & managed-convergence SSOT & doctor-disk-vs-selfcheck-prompt, init shelling out to external CLIs; read when working on perk internals, factories, planning/objective/binding subsystems, doctor checks, contracts, or gitignore mechanics → `docs/learned/workflow/`
- **pi/** — Pi extension API (getSystemPromptOptions/ctx.mode/injected-message persistence), context injection (conditional inject-and-strip, stage-field disambiguation), context system (no transclusion, ambient index split, read-only bash allowlist) → `docs/learned/pi/`
- **toolchain/** — ruff check vs format (silent-commit trap), Biome/tsc gotchas, worktree node_modules stale-SDK trap → `docs/learned/toolchain/`
