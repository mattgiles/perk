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
  offending URL. Because the glob loader serves cached renders for unchanged sources (a
  target-only deletion never re-renders its dependents), the gate re-sweeps the **whole
  corpus from disk** at build completion — render-cache-independent — rather than trusting
  render-time records alone.

An exact-match Vite alias resolves the bare `@astrojs/starlight/components` specifier from the
site tree so corpus `.mdx` pages can import Starlight components (Starlight's own internal
`components/…` subpaths are deliberately not captured).

## Red window (until node 2.3)

**`just docs-build` currently fails with file-precise `InvalidContentEntryDataError`s** — no
corpus page has frontmatter yet, and `docsSchema()` requires `title`. That is the schema gate
working, not a regression: node 2.3's metadata migration adds the frontmatter. `astro dev`
runs with the errors reported. The build also logs a benign
`Entry docs → 404 was not found.` line (Starlight probing for an optional custom 404 page),
alongside the expected sitemap WARN noted below.

## Entry points

From the repo root:

```sh
just docs-dev      # Starlight dev server (astro dev)
just docs-build    # static build to docs/site/dist (local-only; Pagefind included)
just docs-preview  # serve the built site (the Pagefind-accurate acceptance surface)
```

Each delegates to the root npm scripts (`docs:dev` / `docs:build` / `docs:preview`), which run
the workspace scripts here.

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
  quote style, whitespace, and hex case (Biome formats the CSS).

## Deliberately local-only

Astro's default static output is kept: **no `site` option, no adapter, no sitemap or deployment
machinery** (an Objective #1622 boundary). Starlight's build-time WARN about the missing `site`
option (sitemap generation) is therefore expected and harmless.

## Deferred to node 2.4

- The **explicit initial sidebar** — navigation is Starlight's autogenerated default until
  then (no `sidebar` key in `astro.config.mjs`).
- Docs checks: no `@astrojs/check` / `docs-check`, no site type-checking in `just typecheck`,
  no docs validation/build/search in `just test`, and no docs `[[ci.checks]]` row. (Site
  *lint* is already covered — the root `lint` script runs `biome check extension docs/site` —
  and the bridge plugins' own `node:test` unit tests run in `just test`.)
