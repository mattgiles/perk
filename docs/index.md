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

This tree holds four kinds of internal material: the **research inputs** that ground the
design, the **pattern studies** that show how to build it in Pi, the **architecture/design**
notes that record specific decisions, and the **durable learnings** distilled from landed work
(under [`docs/learned/`](./learned/index.md), with a compressed ambient index in
`.pi/APPEND_SYSTEM.md`).

## Research inputs (grounding; mostly stable)

| Doc | What it is |
|---|---|
| [prior_art.md](./guiding-principles/prior_art.md) | erk distilled into findings for perk (12 sections: state tiers, plan storage, objectives, PR operations, CI/review, context injection, hooks, capability model, etc.). |
| [erk-subagent-usage.md](./guiding-principles/erk-subagent-usage.md) | How erk used subagents, and the governing principle perk adopts: a subagent is a **context-and-capability device, not a parallelism trick** (11 sections — route-don't-relay, double-delivery, the three never-delegate boundaries, model tiering). |

## Pattern studies (how to build it in Pi)

| Doc | What it is |
|---|---|
| [pi-best-practices.md](./guiding-principles/pi-best-practices.md) | The **authoritative** patterns, from Pi's own `examples/` and the SDK (plan-mode recipe, presets, subagent spawn, handoff, goal/loop/review controllers, `createAgentSession`/`SessionManager`). The templates perk follows. |
| [agent-stuff-best-practices.md](./guiding-principles/agent-stuff-best-practices.md) | Corroborating real-world patterns from `mitsuhiko/agent-stuff` (packaging idiom, structural command safety, `go-to-bed.ts`/`uv.ts`, `goal.ts` budget + completion-audit). Independent confirmation of the same bets. |

## Architecture / design principle

| Doc | What it is |
|---|---|
| [python-cli-guidelines.md](./guiding-principles/python-cli-guidelines.md) | House style for perk's **Click**-based Python CLI: the three-layer command pattern, context DI, option/flag conventions, two-tier validation, `UserFacingCliError`, `\b` help text, human-vs-machine output, group structure, and testing. Distilled from the erk prior art. |
| [cli-vs-pi.md](./guiding-principles/cli-vs-pi.md) | The CLI/extension separation: **boundary = the session; authority follows the actor.** The CLI owns the exterior, the extension owns the interior; they coordinate only through durable state, process launch, and a shared static schema. Defines **stage parity** (warm/cold-local/cold-remote doors from one stage registry). |
| [design/headless-worker.md](./design/headless-worker.md) | The Phase-1 autonomy spike (Objective #137 node 1.1): the gap list for the in-process SDK headless drive pathway, and the headless-worker contract — inputs, terminal-signal, outcome shape — that node 1.2 builds against. |
| [design/migration-adoption-audit.md](./design/migration-adoption-audit.md) | The migration/adoption audit (Objective #137 node 4.2): erk's four migration surfaces audited against perk's issue-canonical Pi-native model — adopt-nothing outcome with per-surface drop rationale and record-only follow-on. |
| [design/dignified-convergence.md](./design/dignified-convergence.md) | The **dignified-Python convergence checklist + per-module friction backlog** (Objective #225 node 4.1): the ten-axis audit checklist with enforcement tiers, the candidate-ruff-rule rulings with measured violation counts, one backlog entry per non-CLI `perk/` module bucketed by sweep node, the erk-pattern adopt/drop table, and the `github.py` rebalancing ruling. Nodes 4.2–4.5 implement it. |
| [design/tui-charter.md](./design/tui-charter.md) | The **binding visual design charter** for perk's pi-TUI presence (Objective #251 node 1.1): the UI-emission inventory, surface taxonomy + placement rules, height/width budgets, glyph + severity vocabulary, and the adopted/declined richer pi surfaces (footer ownership, themed widgets, working indicator). Nodes 2.1–3.1 implement it. |
| [design/stacked-publication-dogfood.md](./design/stacked-publication-dogfood.md) | The **stacked-publication dogfood gate** validation record (Objective #1431 node 2.4): the repeatable three-layer live protocol (authoring → parent-aware fresh-clone implement → native stack create + append → pristine-clone verification → unconditional teardown), the dated captured evidence + defect log from the 2026-08-10 pass, and the basis on which the stacked-delivery development write gate was retired. |
| [design/stacked-delivery-dogfood.md](./design/stacked-delivery-dogfood.md) | The **stacked-delivery dogfood gate** validation record (Objective #1431 node 6.2): the repeatable live full-lifecycle protocol — warm stacked authoring → build-readiness planning → second-clone layer implementation → lower-layer feedback + suffix cascade → ready → the atomic merge-async landing, deliberately interrupted after the journal's `accepted` event and concluded from the second clone by `stack recover` → reconcile → census — driven on a real 3-layer docs train whose merged layers ARE the node's documentation deliverables; dated 2026-08-13 evidence + defect log — overall **`PASS`** (all planned arms, including interruption→`all_after` conclusion; follow-ups #1709/#1710 for two non-blocking defects). |
| [design/learn-harvest-dogfood.md](./design/learn-harvest-dogfood.md) | The **learn-harvest dogfood** validation record (Objective #1538 node 3.1): the repeatable two-leg live acceptance protocol for `perk learn harvest` (a file-scoped single-lane direct-analysis session and an unscoped full-corpus analyst-wave session), the bounded attempt/fix state machine with deterministic verdict aggregation, and the dated 2026-08-11 evidence — overall **`PASS`** (both legs attempt 1, saved objectives #1593 and #1594 retained as real backlog, full wave coverage, two environment/friction D-rows, no perk defect, no successor node). |
| [design/session-audit-dogfood.md](./design/session-audit-dogfood.md) | The **session-audit dogfood** validation record (Objective #1410 node 4.1): the repeatable full-pass procedure over the live local corpus (census → deterministic run → baseline judgment wave → fold → calibration with machinery-fixes-first sequencing), the three-layer degradation-arm checklist template, and the dated 2026-08-10/11 evidence — per-arm table, two-defect log (the wave lane-key dispatch failure; the era-anachronistic classifier payload gate), and the eight-row calibration log (four operator-confirmed sharpens, no culls). |
| [design/learned-curation-map.md](./design/learned-curation-map.md) | The **`docs/learned/` curation map** (Objective #1610 node 2.1): the reviewed per-doc disposition inventory over the 62-doc snapshot — one disposition row per doc (keep / merge-into / retire / fold, with signals and rationale), the 12-cluster taxonomy draft, the four execution units with the balanced two-batch partition, the 2.3-finalized (actual-bytes) over-12,288 B read-cost list, the count/byte predictions, and the recorded ambient-tier actual (3,583 raw region bytes, node 2.4) with its guarded 5,120-byte budget derivation. Nodes 2.2/2.3 executed it (Batches A/B); §5 finalized + §6 actuals recorded by 2.3; 2.4 consumes the clusters; 4.1 consumes the 2.3-finalized over-threshold list; 5.1 consumes the ambient actual/budget derivation. |
| [design/context-payload-baseline-2.md](./design/context-payload-baseline-2.md) | The **transcript-composition before/after record** (Objective #1610): the Phase-1 baseline and the closing audit bracketing the context diet — the pinned #1263 census recipe re-run across the three session shapes at both brackets, the self-contained measurement protocol with freeze + attribution steps, unit definitions (census UTF-16 `c` vs attribution code-point `c`), the frozen-copy manifests, the four `perk-dev audit attribution` report blocks, and the three soft-target verdicts. Predecessor: [design/context-payload-baseline.md](./design/context-payload-baseline.md) (the closed #1263 before/after record). |
| [design/docs-site-blueprint.md](./design/docs-site-blueprint.md) | The **binding content/IA blueprint** for the local docs site (Objective #1622 node 1.1): the five-section reader hierarchy with the complete route/sidebar map, the page-by-page disposition inventory over the 47-file `docs/user-docs/` corpus (5 replace / 4 split / 38 keep-and-polish), the hub/anchor migration map, the Divio/voice/metadata authoring contract, the objective's acceptance matrices with executing-node assignments, and the credential/Actions readiness record. Nodes 1.2–4.6 implement it. |
| [design/docs-site-walkthrough-evidence.md](./design/docs-site-walkthrough-evidence.md) | The **executable docs walkthrough evidence record**, completed by the node 5.2 launch gate: the dated disposable-repo credential/Actions preflight with cleanup proof, the five passed 2026-08-13 walkthrough rows with their 2026-08-15 change-audit dispositions, the per-step **source-verification records** for both tutorials (live execution waived by the operator's no-live-run directive — never claimed as live-run passes), and the defect/rerun log. |
| [design/docs-site-launch-gate.md](./design/docs-site-launch-gate.md) | The **docs-site launch-gate record** (Objective #1622 node 5.2): dated evidence for the complete local launch gate — clean-checkout install/develop/check/build/preview, the full local check surface, the new no-runtime-network sweep, the actual GitHub and in-session CI paths, walkthrough-evidence completion, the 10/10 search matrix, three isolated cold-context sessions (6/6 tasks), the operator's rendered human review, and the machinery-sweep/deployment-absence proofs — with the clause→leg accounting table, defect/rerun log, and residue statement. |
| [design/docs-site-bridge-spike.md](./design/docs-site-bridge-spike.md) | The **binding bridge selection** from the Starlight content-bridge compatibility spike (Objective #1622 node 1.2): direct external-tree collection loading of `docs/user-docs/` (Astro `glob()` loader + `docsSchema()` + Starlight `markdown.processedDirs` + a repo-owned remark H1-strip plugin) on the pinned `astro@7.2.1` + `@astrojs/starlight@0.41.7` pair, with the 11-criterion pass-contract evidence, install/build-cost measurements, and caveats. Nodes 1.3, 2.1, and 2.2 consume it as decided input. |
| [design/docs-site-visual-blueprint.md](./design/docs-site-visual-blueprint.md) | The **binding visual and authoring blueprint** for the local docs site (Objective #1622 node 1.3): contrast-verified light/dark tokens mapped onto Starlight, exact local Inter Variable + IBM Plex Mono pins and type rules, annotated home/landing/reference compositions, the accessible five-diagram legend, responsive/200%-zoom behavior, and a zero-entry component-override set under a cap of three. Nodes 2.1–5.2 execute it. |
| [design/prose-review-stack.md](./design/prose-review-stack.md) | The **binding stack selection + security envelope** for the Prose Review Workbench (Objective #1764 node 1.1): FastAPI + uvicorn behind a pure-ASGI outermost security guard, the exact-pinned Vite + React + TS workspace (`tools/prose-review/`), the rebuild-on-every-launch policy, and the pinned invariant → enforcement → test envelope (Host/Origin/CSRF, repo-rooted read containment, text-only rendering, CSP + header stamping). Later workbench nodes build on it without revisiting the stack. |
| [releasing.md](./releasing.md) | The **maintainer release policy + recurring runbook**: the **version graph** naming every version-bearing surface and its owner (SSOT `pyproject.toml` `[project] version` → `perk.__version__` → `package.json`), semver/pre-1.0 policy, the **two-phase changelog convention** (`<!-- As of <hash> -->` marker + parenthesized short-hash tokens, stripped at release), the coordinated dual-plane (PyPI + npm) release runbook — bump/roll through tag, approval order, and post-publish verification — and the **incident-handling** runbook behind the `validate-release-versions` tag gate. |
| [release-checklist.md](./release-checklist.md) | The **one-time publishing setup + rehearsal** checklist: account setup, package-name checks, the npm scope + `NPM_TOKEN`, GitHub environments, PyPI/TestPyPI trusted publishers, and the TestPyPI rehearsal. Recurring releases point back to [releasing.md](./releasing.md). |
| [release/changelog-categorizer.md](./release/changelog-categorizer.md) | The **canonical categorizer instruction**: how a classifying agent (or maintainer) turns `perk-dev changelog-commits` facts into a reviewed changelog proposal — the input/output contracts, the user-visibility test, include/verify/filter rules, categories (incl. the `Major Changes` higher bar), roll-up, backend qualifiers, confidence flags, and entry-shape examples. Referenced by the [releasing.md](./releasing.md) accrual loop. |

The remaining `docs/design/*` notes (adapter-architecture, extension-layout,
pluggability-taxonomy, provider-contract, the provider-smoke runbooks, the
remote-runner-e2e-dogfood validation record, session-introspection)
are point design sketches read directly from the [`docs/design/`](./design/) directory.

## How the documents relate

- **guiding-principles/prior_art** holds the source findings;
  **pi- / agent-stuff best-practices** are the build templates.
- **guiding-principles/cli-vs-pi.md** feeds the CLI/extension split throughout the design.
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
