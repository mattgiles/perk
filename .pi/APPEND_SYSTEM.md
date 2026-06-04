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

- **workflow/** — plan factories, plan-ref lifecycle, init/doctor division & managed-convergence SSOT, init shelling out to external CLIs (skills manifest); read when working on perk internals, factory sessions, doctor checks, external-CLI integration, or gitignore/worktree mechanics → `docs/learned/workflow/`
- **pi/** — Pi context system: no transclusion, ambient index split, bash allowlist in read-only sessions → `docs/learned/pi/`
- **toolchain/** — ruff check vs ruff format, CI vs pre-commit hook, silent-commit trap → `docs/learned/toolchain/`
