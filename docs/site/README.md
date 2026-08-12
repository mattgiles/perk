# perk docs site (`docs/site/`)

The **local Starlight documentation-site shell** for perk (Astro + Starlight). This package is
dev-only tooling: it is `private`, never published, and never enters the npm tarball or the
Python wheel/sdist (guarded by `tests/test_packaging.py`).

Until node 2.2 wires the external-tree bridge, the site renders **disposable fixture content**
under `src/content/docs/` — `docs/user-docs/` remains the canonical operator-content source and
is not read by this shell yet.

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

Two committed records bind this shell's decisions; changing a bound value requires an explicit
objective reconciliation (their shared reconciliation rule):

- [`docs/design/docs-site-bridge-spike.md`](../design/docs-site-bridge-spike.md) — the exact
  `astro@7.2.1` + `@astrojs/starlight@0.41.7` pair and the external content-tree bridge
  (applied by node 2.2). It also names `@astrojs/markdown-remark` as a direct dependency here
  because node 2.2's unified processor imports it.
- [`docs/design/docs-site-visual-blueprint.md`](../design/docs-site-visual-blueprint.md) — the
  Fontsource pins, `customCss` order, and the §2/§3 token and font values transcribed into
  `src/styles/tokens.css` (guarded byte-exactly by `tests/test_docs_site_tokens.py`).

## Deliberately local-only

Astro's default static output is kept: **no `site` option, no adapter, no sitemap or deployment
machinery** (an Objective #1622 boundary). Starlight's build-time WARN about the missing `site`
option (sitemap generation) is therefore expected and harmless.

## Deferred to node 2.4

Docs checks are not wired yet: no `@astrojs/check` / `docs-check`, no site type-checking in
`just typecheck`, no docs validation/build/search in `just test`, and no docs `[[ci.checks]]`
row. (Site *lint* is already covered: the root `lint` script runs
`biome check extension docs/site`.)
