# perk docs — research, design & learnings index

**perk** is a Pi-native rebuild of the [erk](https://github.com/dagster-io/erk)
plan-oriented engineering workflow — a Python CLI (the session *exterior*) plus a TypeScript
Pi extension (the session *interior*), sequenced so that **perk bootstraps itself**. The
documents below are perk's internal research, design notes, and durable learnings — written
for perk's own developers, not shipped behavior.

> **Using perk on your own repo?** Start at [docs/user-docs/](./user-docs/index.mdx) —
> the operator-facing documentation, organized by the
> [Divio system](https://docs.divio.com/documentation-system/) (tutorials, how-to guides,
> reference, explanation). Everything below this line is perk's internal record.
>
> **Developing perk itself?** Developer-facing product docs for self-repo-only surfaces live in
> [docs/developers/](./developers/index.md), distinct from the internal record below.

## Placement rules

This section is the authoritative statement of where a document belongs in the `docs/` tree —
one entry per canonical location:

- [`docs/user-docs/`](./user-docs/index.mdx) — the **operator-facing documentation** for repos
  using perk, organized by the Divio system (tutorials, how-to guides, reference, explanation).
- [`docs/developers/`](./developers/index.md) — **developer-facing product docs** for
  self-repo-only surfaces (indexed by `docs/developers/index.md`).
- [`docs/site/`](./site/README.md) — the **website machinery** (the Astro/Starlight docs-site
  workspace that renders `docs/user-docs/`).
- [`docs/learned/`](./learned/index.md) — **durable cross-cutting learnings** distilled from
  landed work, written only via `/learn` — never authored ad hoc. The catalog is
  `docs/learned/index.md`; the compressed ambient routing index lives in `.pi/APPEND_SYSTEM.md`.
- `docs/library/` — **git-ignored ad hoc material** (scratch references, local-only working
  documents).
- [`docs/planning/`](./planning/) — **ALL planning documents**. Planning docs for implemented
  work live in [`docs/planning/archive/`](./planning/archive/).
- [`docs/design/`](./design/) — **current design records only**: binding blueprints, charters,
  contracts, and live design sketches.
  [`docs/design/first-principles/`](./design/first-principles/) holds the grounding-principles
  corpus (research inputs, pattern studies, and principle docs).
  [`docs/design/archive/`](./design/archive/) holds the
  dogfood/spike/evidence/baseline/audit/provider-smoke and executed records.

**Archive conventions:** the archive location is itself the status signal — no banners, no
content rewrites. Dogfood/spike/evidence/validation records are **authored directly into
`docs/design/archive/`** — currency notwithstanding.

## First principles ([`docs/design/first-principles/`](./design/first-principles/))

The grounding corpus: the **research inputs** that ground the design, the **pattern studies**
that show how to build it in Pi, and the **architecture/design principle** docs.

### Research inputs (grounding; mostly stable)

| Doc | What it is |
|---|---|
| [prior_art.md](./design/first-principles/prior_art.md) | erk distilled into findings for perk (12 sections: state tiers, plan storage, objectives, PR operations, CI/review, context injection, hooks, capability model, etc.). |
| [erk-subagent-usage.md](./design/first-principles/erk-subagent-usage.md) | How erk used subagents, and the governing principle perk adopts: a subagent is a **context-and-capability device, not a parallelism trick** (11 sections — route-don't-relay, double-delivery, the three never-delegate boundaries, model tiering). |

### Pattern studies (how to build it in Pi)

| Doc | What it is |
|---|---|
| [pi-best-practices.md](./design/first-principles/pi-best-practices.md) | The **authoritative** patterns, from Pi's own `examples/` and the SDK (plan-mode recipe, presets, subagent spawn, handoff, goal/loop/review controllers, `createAgentSession`/`SessionManager`). The templates perk follows. |
| [agent-stuff-best-practices.md](./design/first-principles/agent-stuff-best-practices.md) | Corroborating real-world patterns from `mitsuhiko/agent-stuff` (packaging idiom, structural command safety, `go-to-bed.ts`/`uv.ts`, `goal.ts` budget + completion-audit). Independent confirmation of the same bets. |

### Principle docs

| Doc | What it is |
|---|---|
| [python-cli-guidelines.md](./design/first-principles/python-cli-guidelines.md) | House style for perk's **Click**-based Python CLI: the three-layer command pattern, context DI, option/flag conventions, two-tier validation, `UserFacingCliError`, `\b` help text, human-vs-machine output, group structure, and testing. Distilled from the erk prior art. |
| [cli-vs-pi.md](./design/first-principles/cli-vs-pi.md) | The CLI/extension separation: **boundary = the session; authority follows the actor.** The CLI owns the exterior, the extension owns the interior; they coordinate only through durable state, process launch, and a shared static schema. Defines **stage parity** (warm/cold-local/cold-remote doors from one stage registry). |

## Current design records ([`docs/design/`](./design/))

| Doc | What it is |
|---|---|
| [design/headless-worker.md](./design/headless-worker.md) | The Phase-1 autonomy spike (Objective #137 node 1.1): the gap list for the in-process SDK headless drive pathway, and the headless-worker contract — inputs, terminal-signal, outcome shape — that node 1.2 builds against. |
| [design/tui-charter.md](./design/tui-charter.md) | The **binding visual design charter** for perk's pi-TUI presence (Objective #251 node 1.1): the UI-emission inventory, surface taxonomy + placement rules, height/width budgets, glyph + severity vocabulary, and the adopted/declined richer pi surfaces (footer ownership, themed widgets, working indicator). Nodes 2.1–3.1 implement it. |
| [design/docs-site-blueprint.md](./design/docs-site-blueprint.md) | The **binding content/IA blueprint** for the local docs site (Objective #1622 node 1.1): the five-section reader hierarchy with the complete route/sidebar map, the page-by-page disposition inventory over the 47-file `docs/user-docs/` corpus (5 replace / 4 split / 38 keep-and-polish), the hub/anchor migration map, the Divio/voice/metadata authoring contract, the objective's acceptance matrices with executing-node assignments, and the credential/Actions readiness record. Nodes 1.2–4.6 implement it. |
| [design/docs-site-visual-blueprint.md](./design/docs-site-visual-blueprint.md) | The **binding visual and authoring blueprint** for the local docs site (Objective #1622 node 1.3): contrast-verified light/dark tokens mapped onto Starlight, exact local Inter Variable + IBM Plex Mono pins and type rules, annotated home/landing/reference compositions, the accessible five-diagram legend, responsive/200%-zoom behavior, and a zero-entry component-override set under a cap of three. Nodes 2.1–5.2 execute it. |
| [design/prose-review-stack.md](./design/prose-review-stack.md) | The **binding stack selection + security envelope** for the Prose Review Workbench (Objective #1764 node 1.1): FastAPI + uvicorn behind a pure-ASGI outermost security guard, the exact-pinned Vite + React + TS workspace (`tools/prose-review/`), the rebuild-on-every-launch policy, and the pinned invariant → enforcement → test envelope (Host/Origin/CSRF, repo-rooted read containment, text-only rendering, CSP + header stamping). Later workbench nodes build on it without revisiting the stack. |

The remaining `docs/design/*` notes (adapter-architecture, pluggability-taxonomy,
provider-contract, prose-prompt-map, prose-review-app-prd, session-introspection)
are current design sketches read directly from the [`docs/design/`](./design/) directory.

## How the documents relate

- **first-principles/prior_art** holds the source findings;
  **pi- / agent-stuff best-practices** are the build templates.
- **first-principles/cli-vs-pi.md** feeds the CLI/extension split throughout the design.
- **docs/learned/** distills durable cross-cutting findings from landed work; its
  [index](./learned/index.md) is the full catalog and `.pi/APPEND_SYSTEM.md` carries the
  compressed ambient routing index.

## External references (not in this repo)

- erk source — `~/dev/github/dagster-io/erk` (workflow being ported).
- erk learned-docs corpus — the erk repo's `docs/learned/` (the prior-art corpus).
- Pi docs — `~/dev/docs/pi/` and the npm install under `@earendil-works/pi-coding-agent/docs`.
- Pi examples — `~/dev/github/earendil-works/pi/packages/coding-agent/examples/` (authoritative pattern source).
- `mitsuhiko/agent-stuff` — `~/dev/github/mitsuhiko/agent-stuff/` (corroborating patterns).
- `pi-subagents` — `~/dev/github/nicobailon/pi-subagents` (the delegation engine perk borrows in Phase 2).
