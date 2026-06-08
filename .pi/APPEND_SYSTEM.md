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

- **workflow/** — plan factories, plan-ref lifecycle, plan-save surfaces (fidelity gap & handoff_extra carrier), warm-door commands (read-only gating trap, drive-the-session, rendering every cold-door outcome), objective lifecycle (resumable-lease nodes & authoring loop), skill bindings (two-plane delivery & doctor validation/injection mirror), shared `shared/` contracts recipe (incl. `contracts.md` §-numbering not contiguous — grep `## §8.` before assigning), provider seam (owned-surface deferral vs always-registered substrate, registration-time vacating vs runtime deferral two-node split, injection-only adapter shim, `package_filter` omission, cross-plane resolver mirror, `cache.plan-ref.provider`== issue-backend `github` not seam id), init/doctor division & managed-convergence SSOT & doctor-disk-vs-selfcheck-prompt & the `_GROUP_ORDER` human-render trap, init shelling out to external CLIs; read when working on perk internals, factories, planning/objective/binding/provider subsystems, doctor checks, contracts, or gitignore mechanics → `docs/learned/workflow/`
- **pi/** — Pi extension API (getSystemPromptOptions/ctx.mode/injected-message persistence), context injection (conditional inject-and-strip, stage-field disambiguation), context system (no transclusion, ambient index split, read-only bash allowlist), structured output (pi-ai tool-calling not JSON mode, faux-provider offline tests, `PERK_NO_LLM` gate), headless session construction & driving (runtime-factory builds the loader internally, explicit `bindExtensions` `mode:"json"`, `session.subscribe` raw-AgentEvent facts, single-prompt drive + budget watchdog & premature-idle gap, offline model-availability determinism) → `docs/learned/pi/`
- **toolchain/** — ruff check vs format (silent-commit trap), Biome/tsc gotchas, Biome param-property type-stripping under `node --test` / `organizeImports` assist-only-under-`check` / `let x = undefined` trap, worktree node_modules stale-SDK trap & package-lock churn cleanup & stale-global-`perk`/self-converge smoke trap (use worktree `.venv/bin/perk` for `shared/` changes; init smokes in a scratch dir), ty narrowing of untyped/JSON dict values (cast vs truthiness guard) → `docs/learned/toolchain/`
