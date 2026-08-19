# perk docs site (`docs/site/`)

The **local Starlight documentation-site shell** for perk (Astro + Starlight). This package is
dev-only tooling: it is `private`, never published, and never enters the npm tarball or the
Python wheel/sdist (guarded by `tests/test_packaging.py`).

The site renders **`docs/user-docs/` in place** — the sole checked-in content source. The
`docs` collection loads the external tree directly (Astro `glob()` loader with
`base: "../user-docs"`, pattern `**/[^_]*.{md,mdx}`; `_`-prefixed basenames are unrouted
authoring files), Starlight's `markdown.processedDirs` points at the same directory, and the
glob loader watches the external base natively — dev edits to corpus pages hot-reload without
extra wiring. Two repo-owned remark plugins run through the single
`markdown.processor: unified({ remarkPlugins })` registration (which the pinned `@astrojs/mdx`
inherits — never add a `markdown.remarkPlugins` key alongside; it would double-register for
`.md`):

- `src/remark-strip-first-h1.mjs` — sources keep their standalone `#` H1 for GitHub; the site
  renders exactly one H1 from frontmatter `title`.
- `src/remark-rewrite-corpus-links.mjs` — rewrites intra-corpus relative `.md`/`.mdx` links
  onto the site's route convention (query strings and fragments preserved); out-of-corpus
  relative links pass through verbatim. A **dangling** in-corpus link is left verbatim but
  recorded into `src/corpus-link-audit.mjs`'s audit and logged loudly in dev; the
  `perk-corpus-link-gate` integration **fails `astro build`** naming every source file +
  offending URL + reason. Because the glob loader serves cached renders for unchanged sources
  (a target-only deletion never re-renders its dependents), the gate re-sweeps the **whole
  corpus from disk** at build completion — render-cache-independent — rather than trusting
  render-time records alone. (`tests/test_user_docs_findability.py` guards the inbound side:
  the repo's entry points — `README.md`, `docs/index.md` — keep resolving into the corpus.)

The build-completion sweep validates two more link families beyond dangling targets:

- **Anchors** — every in-corpus `#fragment` link (fragment-only links included) must name a
  heading slug on the target's *rendered* page (the same `rehypeHeadingIds`/github-slugger
  path the site uses, post-H1-strip). `.mdx` targets are the documented fidelity bound: their
  heading sets come from the best-effort markdown parse, so headings emitted by imported
  components are invisible. The corpus has exactly four MDX pages — the home (`index.mdx`),
  the objective tutorial (`tutorials/drive-an-objective.mdx`), the stage matrix
  (`reference/in-session/stages-and-doors.mdx`), and the headless/remote explanation
  (`explanation/headless-and-remote.mdx`) — and their markdown-syntax links and headings
  ARE swept (they parse as mdast, so link rewriting, the dangling-link audit, and inbound-anchor
  validation all cover them). JSX attribute hrefs bypass the sweep; the post-build
  component-href integrity check in `checks/built-site.test.mjs` covers the built output of all
  four pages. A fully MDX-faithful sweep stays deferred with
  that recorded justification.
- **Escapes** — a relative link that path-resolves *outside* `docs/user-docs/` fails the
  build unless it is a recorded deferral in `ESCAPE_BASELINE`
  (`src/corpus-link-audit.mjs`). The known-dangling anchors live in `ANCHOR_BASELINE`
  likewise. Both baselines are exact `{ source, url }` pairs and **ratcheted**: an entry
  that stops matching a live finding fails the build as stale. The burn-down is complete —
  both baselines are empty — and any new entry must record the owner of its removal.

An exact-match Vite alias resolves the bare `@astrojs/starlight/components` specifier from the
site tree so corpus `.mdx` pages can import Starlight components (Starlight's own internal
`components/…` subpaths are deliberately not captured). Repo-owned content components live in
`src/components/` — currently five prop-free diagram components: four static inline-SVG
components (the home imports `TwoPlanesDiagram.astro`, the objective tutorial imports
`PlansInsideObjectivesDiagram.astro`, the stage matrix imports `WarmColdDoorsDiagram.astro`,
and the headless/remote explanation imports `HeadlessRemoteDiagram.astro`) plus the
**interactive semantic-HTML `CoreFlowDiagram.astro`** (home band 2), all imported by relative
path and all conforming to the visual blueprint's §5 diagram legend and its two rendering
contracts.

Each **static SVG component** renders two content-equal SVG variants and exposes exactly one at
any width via a **container query on the actual content column**: `figure.perk-diagram`
(compositions.css) is an `inline-size` container, the narrow variant is the default, and an
`@container (min-width: 736px)` block flips to the wide variant only where the column fits its
736-unit viewBox at scale 1. With each variant's `max-width` equal to its own viewBox width (no
upscaling) and narrow viewBoxes ≤ 288 units (the content width at the 320px acceptance floor),
every SVG label renders at its declared ≥16 CSS px at every width — including 200% zoom — by
construction, not by viewport heuristics. Browsers without container-query support keep the
content-identical narrow variant.

The **core-flow component** holds the §5 interactive semantic-HTML contract instead: **zero
inline SVG** (all semantics are source-order text; connectors are decorative CSS-generated
glyphs/rules), three satellite `<details>` shipping `open` in source (the unenhanced page is
content-complete), and layout container-keyed with no viewport media query — the shared
`figure.perk-diagram` container drives exactly the bound **640px** (horizontal spine) and
**960px** (three-up satellite row) thresholds, and each satellite card is its own **named
inline-size container** (`satellite`) flipping its summary hint inline↔stacked on the card's
own width at one intentional 440px threshold (the container-queries sub-layout pattern).
`tests/test_docs_site_system.py` guards both shapes: the SVG four's geometry
(variant/viewBox/max-width/@container shape, no viewport-media-query exposure, every `<text>`
resolving to a ≥16px rule in its component's own `<style>`) and the core-flow source contract
(zero SVG, details-open, the 640/960 figure + 440 satellite thresholds, every declared
font-size px ≥ 16).

**Client-script convention (deliberately narrow):** the core-flow component mounts the site's
first — and only — client script, one processed module `<script>` importing the extracted
framework-free controller `src/core-flow-controller.mjs` (enhance = collapse the disclosures,
drive the supplementary tooltips, re-open around print). The controller is jsdom-unit-tested
by `src/core-flow-controller.test.mjs`, which rides the existing `docs/site/src/**/*.test.mjs`
glob run by `just test` and `just docs-check` — the site's `scripts.check` stays deliberately
unchanged (an asymmetry recorded here: unit tests need no build, so they never run inside
`check`).

## Visual system stylesheet (`src/styles/system.css`)

The third repo-owned stylesheet applies the visual blueprint's remaining bound decisions beyond
tokens (tokens.css) and compositions (compositions.css); `customCss` is unlayered, so its rules
beat Starlight's `@layer starlight.*` styles without specificity games:

- **§3 type scale + consumers** — `--sl-text-base` 17px **plus the `body { font-size }`
  consuming rule** (Starlight's body sets no font-size, so the token alone would be dead; a
  root font-size change would rescale every rem), `--sl-text-h1..h4` narrow/`>=768px` values,
  per-level heading line heights, small/meta + eyebrow line-height consumers, and the home
  hero H1 (the sole display-sized text).
- **§2 measure** — `--sl-content-width: 72ch` (`ch` resolves at the consuming container,
  landing inside the blueprint's accepted 68–74ch rendered range).
- **§2 inline code** — `--sl-color-bg-inline-code` set to the blueprint's prose-bound hexes
  (`#ECEFE9` light / `#233029` dark): the one sanctioned literal-hex exception in the file
  (tokens.css cannot host them — its no-stray-token guard).
- **§2 focus** — a universal `:focus-visible` rule (3px `--perk-accent-strong`, 3px offset)
  plus exactly one pinned inset exception: the mobile ToC's full-width `<summary>` keeps
  Starlight's inside offset so the outline is not clipped at the viewport edge.
- **§6 reduced motion** — a value-complete `prefers-reduced-motion: reduce` block
  (`animation-iteration-count: 1`, not 0, so JS `animationend` contracts still fire while
  motion collapses to a single ~0ms cycle).
- **§4C table containment** — a visible border frame on `.sl-markdown-content table`, keeping
  Starlight's block-contained horizontal scroll (the page never widens).
- **§11 article-page & shell-chrome finish** — code-frame surface/border/radius onto the bound
  tokens (one element-level `.expressive-code` rule whose custom-property declarations beat
  Expressive Code's layered theme arms in both themes — dark values are inherited from `:root`,
  light values are layered; code scrolling and syntax token themes stay on EC defaults), the
  3px neutral blockquote rule, mono table-header eyebrows, H2/H3 heading rhythm onto the §2
  24–32px interval (overriding Starlight's layered 1.5em wrapper rule), balanced heading wraps
  (progressive enhancement), shell hairline edges onto `--perk-border` (dark's stock default
  resolves to the canvas — a nearly invisible edge), and the 6px control radius on the search
  button and sidebar entry links (the current-page pill keeps its native accent fill). Bound
  value-exact in the blueprint's §11, with dated code-palette contrast evidence recomputed by
  live WCAG math in `tests/test_docs_site_system.py`.
- **§12 home & landing finish (the system.css share)** — the CSS-generated home hero eyebrow
  (`.hero h1#_top::before`, reusing the shared eyebrow block's typography below). The rest of
  the §12 home/landing treatments — the imageless-hero column fix under the radial accent-low
  wash, the muted balanced tagline, the duo seam + eyebrow→content band rhythm, the
  low-elevation (`--perk-shadow-low`) intent/recommended cards with symmetric hover/focus
  finish, the stretched-link recommended cards, and the hero-action hover finish — live in
  compositions.css; the two-planes exchange-line pass lives in its component. Bound value-exact
  in the blueprint's §12 (with dated hero-wash contrast evidence recomputed by live WCAG math
  in `tests/test_docs_site_system.py`). The §12 set carries the repo's two sanctioned
  non-token CSS value forms: the `transparent` gradient stop in the hero wash
  (compositions.css) and the `rgba()` components inside the §2-bound `--perk-shadow-low`
  token value (tokens.css).
- **§4B landing eyebrows + §4C path eyebrow/92ch wide mode** — pure CSS keyed on the
  sidebar's `aria-current="page"` link via `:has()`: the four quadrant landings render their
  section eyebrow above the H1, and exactly the five `reference/configuration/*` children
  (enumerated route-exact — a future sixth child must be enrolled deliberately) get a
  monospaced `.perk/config.toml` eyebrow plus the 92ch wide mode with prose re-capped at 72ch.
  The `content: … / ""` alt-text form keeps eyebrows out of the accessibility tree; browsers
  without `:has()` support gracefully render no eyebrow. Zero corpus edits, zero component
  overrides (the §7 set stays empty). The CSS↔sidebar coupling is pinned two ways:
  `checks/built-site.test.mjs` asserts each keyed route's built page carries the exact
  `aria-current` href, and `tests/test_docs_site_system.py` pins the enumerations.

`tests/test_docs_site_system.py` guards the whole stylesheet spec↔artifact against the
blueprint (values AND consuming rules), and carries the committed **WCAG-math contrast check**
over the live tokens — all 28 §9 pairs plus the inline-code backgrounds in both themes.

## Static accessibility gate (`checks/a11y.test.mjs`)

`axe-core` runs in `jsdom` against **every routed built page** (enumerated exactly like the
other post-build checks): any `serious`/`critical` violation fails the gate; lower-impact
violations and jsdom-`incomplete` rules print but never fail. Pages load with
`runScripts: "outside-only"` and no subresources — a deterministic static-DOM check, not a
browser. Exactly one rule is disabled: `color-contrast` (it needs real layout); its substitute
is the deterministic WCAG-math check in `tests/test_docs_site_system.py`. Belt-and-suspenders
per page: exactly one `<main>` landmark and the `#_top` skip link. The gate lives in `checks/`,
so the site `check` script runs it after `astro build` with no extra wiring.

The pins: `axe-core` and `jsdom` are exact, dev-only, plan-selected accessibility tooling
(guarded with the rest of the `devDependencies` literal in `tests/test_packaging.py`). jsdom
stays on **29.x** deliberately: 30.x declares an engines floor (`^22.22.2 || …`) above the
repo's documented effective dev floor (>=22.19.0, below) and would be rejected under the root
`.npmrc`'s `engine-strict=true`; 29.1.1's floor (`^22.13.0 || …`) fits with no manifest/README
floor change.

Because pages load with `runScripts: "outside-only"`, the axe gate exercises exactly the
**unenhanced** core-flow state — details open, tooltips hidden — i.e. the no-JS/print-complete
source DOM; enhanced-state behavior is covered by the controller unit tests and rendered
review.

**What is machine-proven here vs. rendered review:** local fonts, both themes' values,
contrast (the §9 pairs and the §11 code-palette evidence — the full emitted syntax palette
against the code-frame surfaces), type scale/measure/focus/reduced-motion/containment/finish
structure, diagram geometry and labeling, landmark/skip-link/name rules, and the full-corpus
axe bar are all deterministic gates in CI. The rendered residue — visual theme review, in-situ
scroll/reflow/zoom QA, real keyboard traversal, screen-reader listen-through — is assigned to
the objective's final-gate human review (node 5.2), a recorded split, not a silent deferral.

## Sidebar & pagination

Navigation is the **explicit sidebar** in `src/sidebar.mjs` — never autogenerated. The
ordering/membership SSOT is `docs/design/docs-site-blueprint.md` §3, realized as: "Home" is
the one label override, section labels are non-linking group headings (stock Starlight groups
cannot link — the §3 amendment recorded 2026-08-12), each landing page is its group's
position-0 entry, all other entries are bare slug shorthands labeled by page titles, and the
five how-to subgroups mirror `sidebarGroup`. `src/sidebar.test.mjs` (unit-level, in the
ordinary `test-js` glob) asserts sidebar↔frontmatter agreement over the live corpus: slug set
equality, `sidebar.order` ascent, subgroup membership, and the single label override.

`pagination: false` is deliberate: Starlight's default prev/next links follow sidebar order
across section boundaries, implying a linear reading order that is wrong for how-to/reference
content. Pages opt in per-page (frontmatter `prev`/`next: true`) only where a deliberately
linear reading sequence exists — currently exactly the tutorials chain. The four rendered
edges are pinned by `checks/built-site.test.mjs`, and the frontmatter opt-ins themselves by
`tests/test_user_docs_findability.py` (the source mirror).

## Corpus metadata contract

Every routed corpus page carries validated frontmatter (the blueprint §6 contract, in force
since the corpus-wide migration):

- **`title`** — required by stock `docsSchema()`, **byte-equal to the source's standalone `#`
  H1** (which every page keeps for GitHub — the dual-presentation rule).
- **`description`** — required via the schema extension in `src/content.config.ts`; one
  sentence, unique corpus-wide.
- **`sidebar.order`** — the per-page record of the blueprint §3 sidebar position, in
  1000-blocks per section (home `0`, tutorials `1000`, how-to `2000`, reference `3000`,
  explanation `4000`; each section index page (`index.*` by stem) = the block base, children
  in steps of 10).
- **`sidebarGroup`** — on how-to guide pages only: the ownership record for the five §3
  operator groups the flat `how-to/` tree does not express; validated against the closed
  group set by the schema extension.

Enforcement is two-surface: the live-corpus pytest guard `tests/test_user_docs_metadata.py`
(accounting, uniqueness, title↔H1, order/group discipline — runs in `just test`) and this
site's build (`docsSchema()` + the schema extension, file-precise errors). The excluded
`docs/user-docs/_authoring.md` is the maintainer-facing authoring reference.

## Expected build noise

The build logs a benign `Entry docs → 404 was not found.` line (Starlight probing for an
optional custom 404 page), alongside the expected sitemap WARN noted below.

## Entry points

From the repo root:

```sh
just docs-dev      # Starlight dev server (astro dev)
just docs-build    # static build to docs/site/dist (local-only; Pagefind included)
just docs-preview  # serve the built site (the Pagefind-accurate acceptance surface)
just docs-check    # the standalone docs gate (pytest guards, lint, typecheck, unit tests, build + checks)
```

Each delegates to the root npm scripts (`docs:dev` / `docs:build` / `docs:preview` /
`docs:typecheck` / `docs:check`), which run the workspace scripts here. Two workspace scripts
carry the site's own gates:

- **`typecheck`** — `astro sync && tsc --noEmit`: sync regenerates the gitignored
  `.astro/types.d.ts` first, so a fresh checkout typechecks. The site's five `.astro`
  components remain prop-free with no frontmatter logic (the core-flow component's
  interactivity lives entirely in its processed module script + the extracted, unit-tested
  controller), so `@astrojs/check` stays unwired: the accepted coverage is Astro's build-time
  compilation (a malformed component fails `astro build`, which `just docs-build`/`docs:check`
  run in CI) plus the post-build structural assertions below — a component gaining props or
  frontmatter logic wires `@astrojs/check` then. `checkJs` stays off; the `.mjs` plugins and
  the core-flow controller are unit-tested instead. Runs inside `just typecheck-js`. (`.astro`
  files also sit outside Biome's `files.includes` — the same accepted-coverage record.)
- **`check`** — `astro build && node --test "src/in-session-reference.test.mjs"
  "checks/**/*.test.mjs"`: the static build (which enforces the schema and link/anchor/escape
  gates), the source/runtime in-session vocabulary guard, and the **post-build checks** in
  `checks/` — deliberately outside `src/`, so the unit-test glob never runs them without a
  build. `built-site.test.mjs` asserts the complete corpus is routed, the single-rendered-H1
  contract (H1 text = frontmatter `title`), the Starlight TOC landmark on sectioned pages,
  Expressive Code markup, the exact tutorials-chain pagination edges, the exclusion proofs
  (no built output for `_authoring`; the `data-pagefind-body` page set — the search-index
  membership — equals the routed corpus), and the
  home/landing/objective-tutorial/stage-matrix/headless-remote
  structure (hero actions, the five band anchors, the four static diagram figures'
  two-labeled-variant shape, the core-flow figure's interactive semantic-HTML contract —
  zero SVG, the three details-open satellites, stage/loop/feed labels, the 9 colocated
  tooltip pairs with bound copy — component-href integrity, recommended-start regions, the
  how-to group anchors, and the eyebrow/wide-mode `aria-current` coupling);
  `a11y.test.mjs` runs the full-corpus static axe gate (above);
  `pagefind.test.mjs` runs the loopback-served **ten-query relevance matrix** (blueprint §7,
  top-5 bar, sharing `src/pagefind-ranking.mjs` with the browser UI so the two can never
  disagree on ranking) plus the `Divio` exclusion sentinel proving the authoring file never
  enters the search index. Runs inside `just test` and `just docs-check`.

CI reaches every docs gate through `just lint`/`just typecheck`/`just test`;
`tests/test_docs_gates.py` is the structural proof of that wiring (scripts, recipes,
workflow steps, and the scope-aware `docs-check` `[[ci.checks]]` row — whose triggers include
the canonical/site docs, perk-expert mirror, and shared provider/schema authorities, keeping
catalog- or mirror-only changes verified when code-suffix globs skip). `just docs-check` runs the
site's Biome lint and typecheck itself for the same reason: docs-scoped files like
`src/styles/tokens.css` or `tsconfig.json` match no code-suffix check glob, so the docs row
must reach every gate GitHub CI would run for them.

## Workspace and lock layout

`docs/site` is an npm **workspace** of the root `package.json`: dependencies are declared in
`docs/site/package.json` and locked in the root `package-lock.json` (exact pins via the root
`.npmrc`'s `save-exact`). A root `npm install` / `npm ci` installs the site toolchain along with
the extension dev deps; there is no separate lockfile here.

## Node floors

- This package declares `engines.node >=22.12.0` — mirroring `astro@7.2.1`'s own engines floor.
- The repo's *effective* dev install floor is **>=22.19.0**: the pinned
  `@earendil-works/pi-coding-agent` / `@earendil-works/pi-ai` dev deps declare it, and the root
  `.npmrc`'s `engine-strict=true` enforces it at install time. The root manifest's advertised
  `>=22` is the published extension's *runtime* floor (pi loading `@mgiles/perk` from a bare
  clone), a separate contract.

## Binding design records

Three committed records bind this shell's decisions; changing a bound value requires an
explicit objective reconciliation (their shared reconciliation rule):

- [`docs/design/docs-site-bridge-spike.md`](../design/docs-site-bridge-spike.md) — the exact
  `astro@7.2.1` + `@astrojs/starlight@0.41.7` pair and the external content-tree bridge
  (applied by node 2.2). It also names `@astrojs/markdown-remark` as a direct dependency here
  because node 2.2's unified processor imports it.
- [`docs/design/docs-site-blueprint.md`](../design/docs-site-blueprint.md) — the reader
  IA/content blueprint: the §2 route convention the link rewrite maps onto and the §6
  dual-presentation rule behind the H1 strip (plus the plain-`.md`-default / MDX-by-exception
  format policy the collection pattern encodes).
- [`docs/design/docs-site-visual-blueprint.md`](../design/docs-site-visual-blueprint.md) — the
  Fontsource pins, `customCss` order, and the §2/§3 token and font values transcribed into
  `src/styles/tokens.css`. `tests/test_docs_site_tokens.py` guards value-exact agreement with
  the blueprint — for both the stylesheet and the `customCss` wiring order — normalizing only
  quote style, whitespace, and hex case (Biome formats the CSS); `tests/test_docs_site_system.py`
  guards the §2/§3/§4/§6/§11 system rules in `src/styles/system.css`, the §9 and §11 contrast
  evidence by live WCAG math, and the §5 diagram-geometry label floor.

## Deliberately local-only

Astro's default static output is kept: **no `site` option, no adapter, no sitemap or deployment
machinery** (an Objective #1622 boundary). Starlight's build-time WARN about the missing `site`
option (sitemap generation) is therefore expected and harmless.

## Deferred to later nodes

- **Label polish** — all non-Home sidebar entries take their labels from page titles; display
  label overrides are a migration-time decision under the blueprint §6 rule.
- **`@astrojs/check` and an MDX-faithful link sweep** — both deferred with recorded
  justification above (static prop-free components; four MDX pages whose markdown links are
  swept and whose built hrefs are post-build-checked).
