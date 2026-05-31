# AGENTS

<!-- BEGIN perk managed -->
## perk conventions (managed by `perk init` — do not edit between these markers)

This repo is wired for the **perk** plan-oriented workflow on Pi.

- **`perk init` owns all Pi wiring.** Every managed piece — `.pi/settings.json`
  package entries, `.pi/workflow/` dirs, `.gitignore` entries, this block — is
  written by `perk init`. Converge any repo by (re-)running `perk init`; it is
  idempotent (a no-op on an already-converged repo).
- **`init` converges *forward*; `doctor --fix` repairs oddities.** Do not bake
  backwards-compat migrations into `init`.
- **Headless-fail-safe.** In extensions, guard every rich-UI call with `ctx.hasUI`
  and block dangerous operations when `!ctx.hasUI`.
- **State tiers:** GitHub (canonical) / `.pi/workflow/` (cache) / session entries
  (transient). Cross-plane contracts live in `shared/`.

perk version: 0.0.1
<!-- END perk managed -->
