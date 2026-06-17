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
- **GitHub access goes through the `gh` CLI.** Never fetch `github.com` /
  `api.github.com` over raw HTTPS (curl/fetch) — private repos reject
  unauthenticated requests; `gh` is already authenticated. Read-only `gh`
  query subcommands (view/list/diff/status/checks/search) work even in perk
  read-only sessions.
- **State tiers:** GitHub (canonical) / `.pi/workflow/` (cache) / session entries
  (transient). Cross-plane contracts live in `shared/`.
- **Prefer ast-grep for code search.** Use `ast-grep` (structural/AST search) over plain
  `grep` when searching for code structures or language constructs; see the `ast-grep` skill.
  Plain `grep` remains fine for literal text.

perk version: 0.0.1
<!-- END perk managed -->

## Developing perk

*Conventions for working **on** perk itself (distinct from the managed block above, which is for
repos **using** perk and is owned by `perk init` — never hand-edit between its markers).*

- **Two planes, one contract.** The Python `perk` CLI is the session **exterior** (scaffolding,
  worktrees, run-id minting, launching `pi`); the TypeScript extension is the **interior**
  (in-session stage transitions + state). Anything both planes must agree on lives in `shared/`
  (the stage registry + `contracts.md`) and is read directly by each — no codegen. Put logic in the
  plane that owns its lifecycle; reach across only through `shared/`.
- **Regression-testing discipline.** Regression coverage lives in the two framework suites —
  **`pytest` (preferred) and `node:test`** — run by `just test` and gated by `just ci` (which must
  stay green). Grow a Python test harness when it widens what the suite checks (e.g.
  `tests/test_packaging.py` builds the wheel + runs `npm pack --dry-run` to guard the publish
  surface). Each phase still ends on a **dogfood gate** — perk must be able to drive the next phase
  before that phase starts (Phase 1's is `docs/planning/phase-1-gate.md`) — but its automatable
  preconditions are ordinary test cases, not bespoke `scripts/verify-*.sh`.
- **Per-turn doc + §-outcomes.** Plan a turn (decisions + prior-art pass) in
  `docs/planning/phase-N-turn-M.md` **before** implementing; after it lands, record what *actually*
  got built (deviations, refinements, deferrals) in that doc's final “outcomes” section. Plan bodies
  are historical records once written — reconcile via outcomes, don't rewrite history.
- **Amend the contract, don't drift.** If an implementation changes cross-plane *behavior*, amend
  `shared/contracts.md` in the **same turn**.
- **Update the user docs, don't drift.** A change to user-facing behavior — a command, an
  in-session tool/door, a config key, a provider/backend — updates `docs/user-docs/` in the
  **same turn**, in the matching Divio quadrant. The operator-facing mirror of "amend the
  contract, don't drift."
- **Rich UI goes through the surfaces module.** In the extension, `ctx.ui.notify`/`setStatus`/
  `setWidget`/`setFooter`/`setWorkingMessage` are called only inside `extension/surfaces/surfaces.ts`
  + `extension/surfaces/report.ts`; everything else uses their seams (`report()`, `createPerkStatus`,
  `setStandingWidget`, `installPerkFooter`, `setWorkingMessage`). `setWorkingIndicator` is never
  called (charter D5 rescinded); `setWorkingMessage` (text-only, headless-no-op) is permitted and
  flavors pi's default spinner via `whimsical`. `ctx.ui.custom` stays declined for every workflow
  surface — the one sanctioned exception is `/btw`, a human-only, `hasUI`-gated side-chat that is
  never machine-reachable (no model tool, not a stage/door). `extension/surfacesGuard.test.ts` fails
  CI on violations — extend the surfaces module rather than allowlisting a new file.
- **`init` converges forward; `doctor --fix` repairs.** New desired state goes into `init`'s
  idempotent convergence; one-off/legacy repairs go into `doctor --fix` — keep `init` a clean
  forward path, never a pile of version branches.
- **Don't author fiction for unbuilt components.** Lock *shapes* (the registry's stage graph, the
  contract specs) but leave drift-prone detail (per-stage `requires`/`reads`/`writes` values) empty
  until the handler exists. Flag deferrals explicitly rather than silently omitting.
- **dignified-python is the Python standard** (see `.agents/skills/dignified-python/`): modern type
  syntax, no `from __future__ import annotations` (3.13), pathlib, explicit `check=`/`timeout=` on
  every `subprocess.run` routed through one wrapper, error boundaries that report (never silent).
- **Two pinned toolchains, wired through `just`.** Python = uv + ruff + ty; TypeScript = npm + Biome
  + tsc. Use `uv run` / `uvx` (never bare `python`/`pip`); scope `ruff` to `perk tests`.
