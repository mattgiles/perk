# AGENTS

<!-- BEGIN perk managed -->
## perk conventions (managed by `perk init` — do not edit between these markers)

This repo is wired for the **perk** plan-oriented workflow on Pi.

- **`perk init` owns all Pi wiring and the `.perk/` dot-directory** — `.pi/settings.json`
  package entries, `.perk/config.toml`, `.gitignore` entries, this block. Re-run `perk init`
  to converge (idempotent); `perk doctor --fix` repairs oddities.
- **GitHub access goes through the `gh` CLI.** Never fetch `github.com` over raw HTTPS
  (curl/fetch) — private repos reject unauthenticated requests. Read-only `gh` query
  subcommands (view/list/diff/status/checks/search) work even in perk read-only sessions.
- **Prefer ast-grep for code search.** Structural/AST queries go through `ast-grep` (see the
  `ast-grep` skill); plain `grep` stays fine for literal text.

perk version: 2.1.0
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
- **Amend the contract, don't drift.** If an implementation changes cross-plane *behavior*, amend
  `shared/contracts.md` in the **same turn**.
- **Update the user docs, don't drift.** A change to user-facing behavior — a command, an
  in-session tool/door, a config key, a provider/backend — updates `docs/user-docs/` in the
  **same turn**, in the matching Divio quadrant. The operator-facing mirror of "amend the
  contract, don't drift." perk's config/provider surface has a **second self-contained mirror**
  in the delivered `perk-expert` skill references (`skills/perk-expert/references/`): a change to a
  config key / provider / backend updates the canonical `docs/user-docs/` reference **and** the
  matching `perk-expert` reference in the **same turn**.
- **Comments express intent, not provenance.** Comments and docstrings carry the *why* + invariants +
  gotchas — never plan history or a restatement of the code. Strip plan-provenance breadcrumbs
  (`Node X.Y`, `Phase N`, `P#.T#`, `Q#`, `Objective #N`, bare issue/PR `#N`, `PRIOR_ART`, and `erk-*`
  historical pointers); keep `contracts.md §X` references and `hop-N` concept names
  (contracts-anchored vocabulary — e.g. the hop-2 learn consumers — not provenance) — on a mixed
  line, strip only the breadcrumb:
  `(contracts.md §8.4; PRIOR_ART §2)` → `(contracts.md §8.4)`. Touch **comments and docstrings only** —
  never string literals, registry vocabulary, or test assertion/fixture data (which may legitimately
  contain `#NNN` / `§X` text). One carve-in: `#`-comment lines inside managed-artifact templates
  (e.g. `workflow_artifacts.py`'s YAML) count as comments — clean them and reconverge the
  materialized artifacts; runtime message strings and injected-prompt literals stay untouchable.
  This bullet is the single reference every comment-hygiene sweep applies;
  it is a prose convention with **no CI guard**.
- **Rich UI goes through the surfaces module.** In the extension, `ctx.ui.notify`/`setStatus`/
  `setWidget`/`setFooter`/`setWorkingMessage` and `pi.registerEntryRenderer` are called only inside
  `extension/surfaces/surfaces.ts` + `extension/surfaces/report.ts`; everything else uses their
  seams (`report()`, `createPerkStatus`, `setStandingWidget`, `installPerkFooter`,
  `setWorkingMessage`, `registerTranscriptRenderer`). `@earendil-works/pi-tui` imports are likewise
  confined to the surfaces module (which re-exports the vocabulary other modules need, e.g. `Key`),
  with `extension/vendor/btw/` as the one named exception (the D6 `ctx.ui.custom` overlay's real
  TUI components). `setWorkingIndicator` is never
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
