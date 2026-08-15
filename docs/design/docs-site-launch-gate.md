# Docs-site launch gate (node 5.2)

## Purpose and governing decisions

This is the launch-gate record for Objective #1622 node 5.2: the executed, dated evidence
that the local docs site satisfies the objective's completion criteria for **local launch**.
Each leg below records what ran, on what tree, and what it proved. The companion record for
walkthrough evidence is
[`docs-site-walkthrough-evidence.md`](./docs-site-walkthrough-evidence.md), which this gate
completed (the two tutorial rows and the five-row change audit).

The gate ran under one binding operator decision:

> **Reviewer directive (binding, supersedes the planning-round protocol for walkthroughs):**
> this gate runs **no live walkthrough reproductions and no perk commands as gate evidence**.
> Tutorial and walkthrough evidence is completed by **following the code as documented** —
> verifying every published step's claims against the current source. If runtime behavior
> diverges from what the docs and source together say, that is explicitly **not this node's
> responsibility**.

The only perk surface touched at all is the repo-mandated final pre-submit `run_ci` (leg E) —
standard implement-session procedure, not a reproduction.

| Field | Value |
|---|---|
| Date | 2026-08-15 |
| Gate SHA (leg A clone) | `5f5c98ee57fec007a11862bc12f5ace93136e162` |
| Executor | Implementing agent (plan #1779) |
| Operator (leg I) | `mattgiles` |
| Host | macOS (Darwin 25.5.0, arm64); node v26.3.0; npm 11.16.0; uv 0.12.3; just 1.58.0 |

Commits after the gate SHA in this node's PR are evidence records only (this file, the
walkthrough-evidence completion, `docs/index.md` rows); the PR's required green `ci.yml` run
re-proves the full check surface on the final head SHA before merge.

## Clause → leg accounting

The objective's ten completion criteria, mapped to the leg(s) and executing surfaces that
carry each one's launch-gate evidence:

| # | Objective clause (abridged) | Executing surface | Leg(s) |
|---|---|---|---|
| 1 | Clean checkout installs, develops, checks, builds, previews with Pagefind working | disposable clone: `uv sync --all-packages` + `npm ci`, `just docs-dev`/`docs-check`/`docs-build`/`docs-preview` | A |
| 2 | Sole content source; direct + built structurally correct; routed-or-excluded accounting | `tests/test_user_docs_metadata.py` (byte-equal frontmatter-title ↔ standalone source H1; routed-or-excluded accounting); `built-site.test.mjs` (exactly one built H1 equal to the title; `_authoring` exclusion) | B |
| 3 | Coherent journeys (home, sidebar, landings, search, TOC, pagination, related links) | `built-site.test.mjs` (sidebar/TOC/pagination/landing/intent-router tests); `sidebar.test.mjs`; cold-context tasks; rendered human review | B, H, I |
| 4 | New pages + five diagrams complete, grounded, accessible, reviewed | diagram content-equality tests (`built-site.test.mjs`); `a11y.test.mjs`; `tests/test_docs_site_system.py` contrast math; rendered human review (the 4.5/5.1 residue) | B, I |
| 5 | Tutorials + walkthrough matrix evidence; search + cold-context scenarios pass | source-verification records + five-row change audit (walkthrough-evidence file, per the directive); `pagefind.test.mjs` 10/10; three isolated sessions covering all six tasks | F, G, H |
| 6 | Metadata, link/anchor, navigation, search relevance, a11y automation, responsive/theme review, type/config, static build, actual GitHub CI, in-session CI, packaging isolation | `just lint` / `just typecheck` / `just test` / `just docs-check` (surface-by-surface table in leg B); latest green `ci.yml` on `main`; final pre-submit `run_ci`; human review | B, D, E, I |
| 7 | No runtime network request from required assets and functionality | the new `built-site.test.mjs` external-origin sweep (all dist HTML fetching positions + all dist CSS); operator offline load | C, I |
| 8 | README and internal entry points resolve to canonical pages | `tests/test_user_docs_findability.py` entry-point link checks (inside `docs-check`) | B |
| 9 | Unselected temporary machinery removed | tracked-file review + repo grep sweep | J |
| 10 | No deployment machinery introduced | config/workflow/dist inspection | J |

## Leg A — clean-checkout install / develop / check / build / preview

Executed 2026-08-15 in a disposable clone of this worktree (deliberate: the gate certifies
the tree being landed, including this node's own fixes) at SHA
`5f5c98ee57fec007a11862bc12f5ace93136e162`.

1. **Clone:** `git clone <worktree> /tmp/perk-launch-gate-NyoNli/clone` — clean checkout,
   no shared state.
2. **Install:** `uv sync --all-packages` (workspace env built from the lock) and `npm ci`
   (650 packages, ~9 s). Versions: node v26.3.0, npm 11.16.0, uv 0.12.3, just 1.58.0 on
   Darwin 25.5.0 arm64. `just setup`'s `hooks`/`install-cli` steps were deliberately
   skipped: they mutate global machine state (prek hook install, `uv tool install`) and are
   irrelevant to the docs product.
3. **Develop:** `just docs-dev` served the home page **HTTP 200** at `http://localhost:4321/`
   (~6 s after launch). Editing one corpus page (`tutorials/get-started.md`, an appended
   comment, reverted afterward) produced the hot-reload log line:
   `[glob-loader] Reloaded data from tutorials/get-started.md`.
4. **Check:** `just docs-check` — **exit 0** (58 docs-scoped pytest tests; biome over 18 site
   files clean; `docs:typecheck` green; 55 site unit tests; `docs:check` build + 21
   post-build tests, including the new no-runtime-network sweep and the 10/10 relevance
   matrix).
5. **Build:** `just docs-build` — **exit 0**; `docs/site/dist/` and `docs/site/dist/pagefind/`
   both exist.
6. **Preview:** `just docs-preview` — **HTTP 200** for `/` and for `/pagefind/pagefind.js`
   (the interactive search proof is leg I).
7. **`docs/library` structural proof:** the clean clone's `docs/library/` contains only
   `.gitkeep` (`.gitignore` line `docs/library/**`), so nothing in the checked, built, and
   previewed site can depend on library content — the no-`docs/library`-dependency proof.
8. **Cleanup:** the temp clone was deleted (`ls` afterwards: `No such file or directory`).

## Leg B — the full local check surface

All four surfaces ran to completion in this worktree on 2026-08-15 (post-fix tree; the same
surfaces also ran green inside the leg-A clone at the gate SHA):

| Surface | Result | Counts |
|---|---|---|
| `just lint` | **pass** (exit 0) | ruff: "All checks passed!"; biome: 242 files, no fixes |
| `just typecheck` | **pass** (exit 0) | ty: "All checks passed!"; extension tsc, `docs:typecheck` (astro sync + tsc), prose-review tsc all green |
| `just test` | **pass** (exit 0) | pytest: **5514 passed**; node:test (extension + tools + docs-site unit): **1911 tests, 0 failures**; `docs:check`: build + **21/21** post-build tests |
| `just docs-check` | **pass** (exit 0) | 58 docs pytest tests; biome 18 files; `docs:typecheck`; 55 site unit tests; `docs:check` 21/21 |

Check-family → executing-surface accounting (every family green in the runs above):

| Objective check family | Executing surface |
|---|---|
| Search relevance | `docs/site/checks/pagefind.test.mjs` — the executable ten-query matrix, **10/10** (leg G) |
| Source/route + metadata + direct-source H1 | `tests/test_user_docs_metadata.py` (byte-equal frontmatter `title` ↔ standalone source H1; routed-or-excluded accounting) |
| Link/anchor | the build-failing corpus-link gate (`remark-rewrite-corpus-links` + `corpus-link-audit`); `built-site.test.mjs` MDX-href test; `tests/test_user_docs_findability.py` entry-point links |
| Navigation | `docs/site/src/sidebar.test.mjs`; `built-site.test.mjs` sidebar/TOC/pagination tests |
| Built H1 | `built-site.test.mjs` "exactly one H1 equal to the frontmatter title" |
| Type/configuration | `npm run docs:typecheck` (astro sync + tsc) |
| Static build | `astro build` inside `docs:check` (schema/link/anchor/escape/sidebar-slug gates fail the build) |
| No runtime network | the new `built-site.test.mjs` sweep (leg C) |
| Packaging isolation | `tests/test_packaging.py` (wheel/sdist/npm-tarball; `test_docs_site_publish_isolation`) |
| Accessibility automation | `docs/site/checks/a11y.test.mjs` (full-corpus static axe, serious/critical fail); `tests/test_docs_site_system.py` WCAG contrast math |

The check wiring itself is guard-tested end to end by `tests/test_docs_gates.py`
(root/site `package.json` scripts, the `justfile` recipes, `.github/workflows/ci.yml`, and
the scope-aware `docs-check` `[[ci.checks]]` row).

## Leg C — no runtime network

**Committed half:** a new test in `docs/site/checks/built-site.test.mjs` — *"built assets and
functionality reference no external origin"* — implemented **before** leg B so it executed
inside every subsequent check run. For every built HTML file under `dist/` (including
`404.html`), it parses with jsdom and asserts zero external references (`http://`, `https://`,
protocol-relative `//`) in fetching positions: `script[src]`, every `link[href]`,
`img[src]`/`img[srcset]`, `source[src]`/`source[srcset]`, `video[src]`/`video[poster]`,
`audio[src]`, `track[src]`, `iframe[src]`, `embed[src]`, `object[data]`, `form[action]`, and
`meta[http-equiv="refresh"]` URLs. For every built CSS file under `dist/` it asserts no
external `url(…)` or `@import`. `data:` URIs and same-origin-relative paths pass; plain
`<a href>` external links are deliberately allowed (content links, not runtime requests) —
which is why the check parses attributes rather than grepping page text. No new dependency
(jsdom is already a site dev-dependency) and zero wiring changes: it rides the site `check`
script into `docs:check`, `just test`, `just docs-check`, GitHub CI, and the `docs-check`
`[[ci.checks]]` row. A mutation check (injected external `script[src]` + CSS `@import`)
verified the sweep fails loudly on offenders before the clean state was confirmed.

**Manual half:** the operator's offline preview load (network disabled) rides leg I; its
result is recorded there.

## Leg D — actual GitHub CI path

Latest green `ci.yml` run on `main` at gate time:

| Field | Value |
|---|---|
| Run id | `31908412642` |
| URL | `https://github.com/mattgiles/perk/actions/runs/31908412642` |
| Head SHA | `8b5ee3c2178d47c90fdcafb7b6e48a300a9f02fa` (the `main` this branch is based on) |
| Created | 2026-08-15T21:04:13Z |
| Conclusion | `success` |

The run log proves the docs gates executed inside the workflow's `just lint` / `just
typecheck` / `just test`: the Typecheck step invoked `npm run docs:typecheck`; the Test step
invoked `npm run docs:check` (Pagefind indexed 75 HTML files) and reported
`5514 passed` (pytest), the docs post-build node:test suite green (`# tests 20 / # pass 20 /
# fail 0` — 20 on that pre-gate SHA; this node adds the 21st, the leg-C sweep), including
`ok 1 - every routed page passes static axe (no serious/critical violations)`,
`ok 2 - the complete corpus is routed, with exactly one H1 equal to the frontmatter title`,
and `ok 15 - the ten-query relevance matrix holds over the built index (top-5 bar)`.

This node's own PR must also go green on the same workflow before land — the standard merge
gate re-proves the surface on the final head SHA (which includes the new sweep).

## Leg E — in-session CI dispatch

The in-session CI evidence is the repo-mandated final pre-submit run-all `run_ci` (the
AGENTS.md gate — standard implement-session procedure, not a reproduction). This node's diff
touches `docs/site/**`, `docs/user-docs/**`, and `docs/design/**`, so the scope-aware
`docs-check` `[[ci.checks]]` row **executes** rather than glob-skipping. Forward reference,
by design: the ordered per-check report with `docs-check ✓` is produced immediately before
submit, and this record does not paste post-hoc output (which would re-dirty the tree) — the
PR's green GitHub run on the same SHA is the committed corroboration.

## Leg F — walkthrough evidence completion (static source verification)

Executed per the reviewer directive — no live runs, no perk commands. Full records live in
[`docs-site-walkthrough-evidence.md`](./docs-site-walkthrough-evidence.md):

- **F1 — change audit of the five passed rows.** Every guide behind a passed 2026-08-13 row
  was diffed since its evidence date. All changes across all five rows are related-link
  retargeting from the reference splits (#1749, #1753, #1759, #1763, #1767) — zero step,
  command, or expected-output changes. **All five dispositions: evidence stands** (the
  objective's "do not need to be repeated unless later content changes invalidate them" rule).
- **F2 — get-started tutorial, source-verified.** Every step's commands, flags, output
  claims, preconditions, and refusals traced to the owning source (per-step table in the
  evidence file). One defect found and fixed (D6 below). Outcome: **Source-verified; live
  execution waived by operator directive.**
- **F3 — objective tutorial, source-verified.** Same method over authoring, node planning,
  implement/land, auto-done, and reconcile claims; all verified (per-step table in the
  evidence file). Same outcome labeling.
- **D1 resolved.** The walkthrough file's D1 row (deferred live tutorial evidence) is
  resolved by the directive: source verification replaces live execution; runtime divergence
  is out of this gate's scope.

## Leg G — search relevance

`pagefind.test.mjs` — the blueprint §7 ten-query matrix encoded verbatim over the built local
index (top-5 bar) — passed **10/10** in every leg-B invocation (`✔ the ten-query relevance
matrix holds over the built index (top-5 bar)`), plus the `/land` sub-result granularity
proof and the authoring-governance exclusion sentinel. The shared ranking object
(`docs/site/src/pagefind-ranking.mjs`) keeps the test and the browser search UI in agreement
by construction; the live search-UI spot check rides leg I.

## Leg H — three cold-context sessions

**Isolation.** The freshly built `dist/` was copied to `/tmp/perk-cold-context-6PkI0I/`
containing nothing else — top-level listing (8 entries, 5.8 MB):
`_astro  404.html  explanation  how-to  index.html  pagefind  reference  tutorials`.

**Evaluators.** Three isolated fresh-context agent sessions (`diag-runner`, a user-level
read-only reporter agent: fresh context, no project-context or skill inheritance, read-only
acceptance role), spawned via the subagent tool with `cwd` set to the temp directory — no
repo access, no AGENTS.md, no maintainer vocabulary. Model: the default configured model
(recorded per session below). Each task text contained only the isolation preamble and its
two reader goals:

> Your working directory contains a built static documentation site (HTML files). Start at
> `index.html`; navigate only by following links/reading files under this directory; you have
> no other knowledge of perk. For each goal below, report the page (file path) you chose and
> your answer.

Task pairing (chosen so neither task coaches its session-mate): S1 = tasks 1+4, S2 = tasks
2+6, S3 = tasks 3+5.

**Results (2026-08-15; model `anthropic/claude-fable-5` in all three sessions; all first
attempts — no reruns needed):**

| Session / task | Chosen page(s) | Answer summary | Verdict |
|---|---|---|---|
| S1 (`c351880e`), task 1 — explain the workflow from home | `index.html` (intended) | Accurate own-words account of the seven-stage spine plan → save → implement → submit → address (correctly read as conditional, "if review asks", from the dashed connector) → land → learn, plus the two-planes/durable-state architecture and the reviewed-plan/review gates | **Pass** |
| S1 (`c351880e`), task 4 — CI trust default | `reference/configuration/workflow-and-ci/index.html` (intended), corroborated by the two CI how-tos | "No — by default it will NOT run them without asking": `[ci] trusted` unset ⇒ untrusted; changed by committed native-boolean `trusted = true`, `--allow-project-ci`, an interactive confirm, or the per-session approval latch; headless with no grant refuses | **Pass** |
| S2 (`9f4b8a86`), task 2 — first-time start | `tutorials/get-started/index.html` (intended) + `reference/requirements-and-compatibility/` | Named the full prerequisite set (git, authenticated gh, node ≥ 22, pi, skills, uv, optional ast-grep) and the first step (`uv tool install perk`, then `perk init`/`perk doctor`, then the spine) | **Pass** |
| S2 (`9f4b8a86`), task 6 — dirty-tree refusal | `how-to/recover-a-dirty-worktree/index.html` (intended) | The keep path: inspect (`git status`/`git diff`), then commit or stash before removal; explicitly warned off `--force` except for confirmed-expendable work | **Pass** |
| S3 (`35f057a8`), task 3 — pick interrupted work back up | `how-to/resume-a-plan/index.html` (intended) | `perk plan resume <plan-id>` from a cold shell; perk resolves the plan's current stage automatically (implement/address/learn; gate states reported, not launched) | **Pass** |
| S3 (`35f057a8`), task 5 — gist vs plan vs objective | `explanation/gists-plans-and-objectives/index.html` (intended) | "An objective" — with the intent-ladder reasoning (commitment not size; a plan is one bounded change; an objective coordinates the multi-plan goal as roadmap nodes, each emitting one plan) | **Pass** |

**6/6 pass.** No content/IA defect surfaced; no rebuild or fresh-session rerun was required. The
temp directory was deleted after the sessions completed.

## Leg I — human visual / keyboard / screen-reader review (operator)

Executed by the operator (`mattgiles`) against `just docs-preview` (an npm/astro surface, not
a perk command) per settled decision 5: both themes on every listed page; 320/768/1280/wide
widths; 200% zoom reflow; reduced motion; real keyboard traversal; VoiceOver in Safari;
everything else in Chrome. This leg explicitly discharges **node 5.1's recorded rendered
residue** (visual theme review, in-situ scroll/reflow/zoom QA, real keyboard traversal,
screen-reader listen-through, Expressive Code syntax-token contrast) and **node 4.5's
deferred rendered inspection** of `explanation/headless-and-remote.mdx`.

Executed by the operator on 2026-08-15 against the running preview (Chrome; VoiceOver item
in Safari). Reported result: **all items pass.**

| # | Item | Result |
|---|---|---|
| 1 | Home page — both themes, 320/768/1280/wide, visual theme review | **Pass** |
| 2 | Sidebar + search interaction — open/operate/close, one live search (leg G's UI half) | **Pass** |
| 3 | `explanation/headless-and-remote` — both themes, multi-width/zoom (the 4.5 residue), diagram rendering | **Pass** |
| 4 | `reference/in-session/stages-and-doors` — both themes, widths, matrix diagram | **Pass** |
| 5 | `reference/configuration/workflow-and-ci` — wide-mode child treatment | **Pass** |
| 6 | `tutorials/get-started` — Expressive Code syntax-token contrast, both themes | **Pass** |
| 7 | 200% zoom reflow on the listed pages | **Pass** |
| 8 | Reduced-motion behavior (macOS Reduce Motion) | **Pass** |
| 9 | Keyboard traversal — skip link, sidebar, search open/operate/close, TOC, diagram pages, focus visibility (incl. the pinned mobile-ToC inset exception) | **Pass** |
| 10 | VoiceOver listen-through (Safari) — home + `explanation/headless-and-remote` (diagram semantics + adjacent textual equivalent) | **Pass** |
| 11 | Offline load — home + one search interaction with the network disabled; no asset request fails (leg C's manual half) | **Pass** |

With item 11 the manual half of leg C is discharged; with items 1–10 node 5.1's rendered
residue and node 4.5's deferred rendered inspection are discharged.

## Leg J — machinery sweep + deployment absence

**Machinery sweep (2026-08-15): none found.**

- `git ls-files docs/site` (26 files) reviewed: every file is selected durable machinery —
  the Astro/Starlight config, the five diagram components, the bridge plugins + their unit
  tests, the three post-build check files, styles, and workspace config. `git ls-files
  docs/user-docs` (75 files) is the routed corpus plus the deliberately excluded
  `_authoring.md` (exclusion guard-tested).
- Repo grep for spike/staging/fixture leftovers: the only matches are intentional references
  to the bridge-spike *design record* in comments and the unrelated `prompts/_fixtures/`
  golden tests. The node-1.2 spike alternatives, node-2.1 fixture content, and the session-audit
  escape baselines remain removed.
- Stray `docs/library` references: none in tracked files outside `.gitignore`
  (`docs/library/**`); the tracked directory holds only `.gitkeep`.
- Nothing removed — the sweep confirms prior removals still hold.

**Deployment absence (2026-08-15):**

- `docs/site/astro.config.mjs` sets **no `site`** and **no adapter** (the config comments the
  boundary explicitly); Starlight's bundled sitemap support therefore stays inert — the
  build-time `[@astrojs/sitemap] … Skipping.` WARN is expected and documented in
  `docs/site/README.md`, and the built `dist/` contains **no sitemap file and no CNAME**.
- No analytics and no production URL anywhere in `docs/site/` (the only "production" matches
  are code comments about hermetic test seams).
- `.github/workflows/` holds `ci.yml`, the managed `perk-run.yml`, and `release.yml`. The
  planning-session state note listed only the first two; `release.yml` is the pre-existing
  perk **package** release pipeline (PyPI/npm trusted publishing, present since #1161) — it
  contains no docs-site deployment and never touches `docs/site/`, whose exclusion from
  published artifacts is separately guard-tested by
  `tests/test_packaging.py::test_docs_site_publish_isolation`. **No deploy/publish workflow
  for the docs site exists.**

## Defect and rerun log

| ID | Surface | Observation | Resolution | Full rerun required? |
|---|---|---|---|---|
| D6 | Tutorial prerequisites (both tutorials) | Leg F source verification: the get-started lead-in claimed the prerequisite list is "the same environment `perk init` checks for" while including `uv`, and the objective tutorial's Before-you-start parenthetical repeated the claim — but `check_environment()` (`src/perk/convergence/env.py`) never probes `uv`; it is only the Step-1 installer. | Bounded prose fix in both tutorials: `uv` is now stated as the Step-1 installer, outside the init-checked set. Steps re-verified against source (pass). | No product/check change — the affected leg (F) was re-verified, and the full local surface (leg B: `just lint`/`typecheck`/`test`/`docs-check`) ran green after the fix, per the node's finish-with-the-full-surface rule; leg E's final run-all `run_ci` closes the gate. |

## Residue / incompleteness statement

**Empty — the gate passed in full.** Every leg (A–J) executed with a pass outcome on
2026-08-15; the one defect the gate exposed (D6) was bounded, fixed in this PR, and
re-verified; the machinery sweep found nothing to remove; no materially larger failure
occurred, so no successor nodes were added and the node is not left incomplete. The only
forward reference is leg E's by-design one: the final pre-submit run-all `run_ci` report
(`docs-check` executing) is produced immediately before submit, corroborated by the PR's
required green `ci.yml` run on the head SHA.
