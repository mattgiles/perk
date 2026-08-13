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

perk version: 2.3.0
<!-- END perk managed -->

## Developing perk

*Conventions for working **on** perk itself (the managed block above is for repos **using** perk
and is owned by `perk init` — never hand-edit between its markers).*

- **Two planes, one contract.** The Python `perk` CLI is the session **exterior** (scaffolding,
  worktrees, run-id minting, launching `pi`); the TypeScript extension is the **interior**
  (in-session stage transitions + state). Anything both planes must agree on lives in `shared/`
  (the stage registry + `contracts.md`), read directly by each — no codegen. Put logic in the
  plane that owns its lifecycle; reach across only through `shared/`.
- **Regression-testing discipline.** Regression coverage lives in the two framework suites —
  **`pytest` (preferred) and `node:test`** — run by `just test` and gated by `just ci` (which
  must stay green). In perk sessions the gate is ONE run-all `run_ci` immediately before
  submitting (never bare `just ci` in bash; the `[[ci.checks]]` rows mirror `just ci`'s targets,
  `setup` being env prep owned by the `[worktree] setup` hook), and its green report is
  definitive — no re-verification. While iterating, use narrow targeted checks. Grow a Python
  test harness when it widens what the suite checks. Each phase ends on a **dogfood gate** —
  perk must drive the next phase before it starts — whose automatable preconditions are
  ordinary test cases, not bespoke scripts.
- **Amend the contract, don't drift.** A change to cross-plane *behavior* amends
  `shared/contracts.md` in the **same turn**.
- **Update the user docs, don't drift.** A change to user-facing behavior — a command, an
  in-session tool/door, a config key, a provider/backend — updates `docs/user-docs/` in the
  same turn (matching Divio quadrant). Config/provider/backend changes also update the matching
  `perk-expert` reference (`skills/perk-expert/references/`) in the same turn — the second,
  self-contained mirror.
- **Where decisions are recorded.** Day-to-day decisions → the plan issue's `## Assumptions`;
  cross-plane behavior → `shared/contracts.md` (same turn); a design decision worth a durable
  standalone record → a `docs/design/*.md` note (indexed in `docs/index.md` when table-worthy);
  durable cross-cutting learnings reach `docs/learned/` only via `/learn` — never authored ad
  hoc. This is the routing map the `perk-domain-modeling` skill's discovery step lands on.
- **Comments express intent, not provenance.** Comments and docstrings carry the *why* +
  invariants + gotchas — never plan history or a restatement of the code. Strip plan-provenance
  breadcrumbs (`Node X.Y`, `Phase N`, `P#.T#`, `Q#`, `Objective #N`, bare issue/PR `#N`,
  `PRIOR_ART`, `erk-*` pointers); keep `contracts.md §X` references and `hop-N` concept names
  (contracts-anchored vocabulary, not provenance); on a mixed line strip only the breadcrumb.
  Touch **comments and docstrings only** — never string literals, registry vocabulary, or test
  assertion/fixture data. One carve-in: `#`-comment lines inside managed-artifact templates
  (e.g. `workflow_artifacts.py`'s YAML) count as comments — clean them and reconverge the
  materialized artifacts; runtime message strings and injected-prompt literals stay
  untouchable. This bullet is the single reference every comment-hygiene sweep applies; a prose
  convention with **no CI guard**.
- **Rich UI goes through the surfaces module.** In the extension, `ctx.ui.notify`/`setStatus`/
  `setWidget`/`setFooter`/`setWorkingMessage` and `pi.registerEntryRenderer` are called only
  inside `extension/surfaces/surfaces.ts` + `extension/surfaces/report.ts`; everything else
  uses their seams, and `@earendil-works/pi-tui` imports stay confined to the surfaces module
  (which re-exports the vocabulary other modules need, e.g. `Key`) — `extension/vendor/btw/`
  is the one named exception. `setWorkingIndicator` is never called (charter D5 rescinded);
  `setWorkingMessage` (text-only, headless-no-op) is permitted. `ctx.ui.custom` stays declined
  for every workflow surface — the one sanctioned exception is `/btw` (human-only,
  `hasUI`-gated, never machine-reachable). `extension/surfacesGuard.test.ts` fails CI on
  violations — extend the surfaces module rather than allowlisting a new file (charter:
  `docs/design/tui-charter.md`).
- **`init` converges forward; `doctor --fix` repairs.** New desired state goes into `init`'s
  idempotent convergence; one-off/legacy repairs into `doctor --fix` — never a pile of version
  branches in `init`.
- **Don't author fiction for unbuilt components.** Lock *shapes* (the registry's stage graph,
  the contract specs); leave drift-prone detail empty until the handler exists. Flag deferrals
  explicitly rather than silently omitting.
- **dignified-python is the Python standard** (see `.agents/skills/dignified-python/`): modern
  type syntax, no `from __future__ import annotations` (3.13), pathlib, explicit
  `check=`/`timeout=` on every `subprocess.run` routed through one wrapper, error boundaries
  that report (never silent).
- **Two pinned toolchains, wired through `just`.** Python = uv + ruff + ty; TypeScript = npm +
  Biome + tsc. Use `uv run` / `uvx` (never bare `python`/`pip`); scope `ruff` to `perk tests`.
