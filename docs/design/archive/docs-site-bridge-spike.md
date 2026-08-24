# Docs-site content-bridge spike record

This is the committed record of the Starlight content-bridge compatibility spike
(Objective #1622, node 1.2). It binds the bridge mechanism and exact version pair that
carry `docs/user-docs/` — the sole checked-in content source — into a local Starlight
site, without a second checked-in content tree.

## §1 Binding scope

**What this record binds:**

- The **bridge mechanism**: direct external-tree collection loading — Astro's `glob()`
  loader with `base: '../user-docs'` in the `docs` collection, `schema: docsSchema()`,
  Starlight `markdown.processedDirs` pointed at the same directory, and a repo-owned
  remark plugin stripping the first depth-1 heading (evaluation order's approach 1;
  approaches 2 and 3 were not reached).
- The **exact version pair**: `astro@7.2.1` + `@astrojs/starlight@0.41.7`.

**Who consumes it:** node 1.3 (visual blueprint), node 2.1 (site shell), and node 2.2
(bridge implementation) treat the selection as decided input. Node 2.2 applies §5 as
config without re-derivation.

**Reconciliation rule:** changing the bridge mechanism or moving off the recorded
version pair requires an explicit objective reconciliation on Objective #1622 — the same
rule the node 1.1 blueprint applies to its binding decisions.

## §2 Candidate & environment

| Item | Value |
|---|---|
| `@astrojs/starlight` | **0.41.7** (exact pin; latest 0.41.x patch and the registry `latest` dist-tag at spike time — no newer minor/major was skipped) |
| `astro` | **7.2.1** (exact resolution of Starlight's peer range `^7.0.2` at install) |
| `@astrojs/markdown-remark` | 7.2.2 (installed as a Starlight peer dependency; load-bearing — see §5) |
| Node | v26.3.0 (repo engines: `>=22`) |
| npm | 11.16.0 |
| Platform | macOS 26.5, Darwin arm64 |
| Spike date | 2026-08-12 |

The plan cited 0.41.5 as the latest patch at planning time; 0.41.6 and 0.41.7 landed
before implementation and 0.41.7 was taken per the "latest 0.41.x patch at spike time"
rule. The spike scaffold lived at `docs/site/` (the final node-2.1 layout position, so
the `../user-docs` content-relative path is representative) with its own
`package.json`/`package-lock.json`; the root npm lock was untouched.

## §3 Pass contract

A candidate approach passes only if **all** criteria pass. Verification as run:

| # | Criterion | Concrete verification used |
|---|---|---|
| 1 | Clean build | Fresh scaffold: `npm install` then `npx astro build` exits 0; `dist/<route>/index.html` exists for all 8 representative routes |
| 2 | Dev-watch | With `npx astro dev` running, append a marker line to `docs/user-docs/how-to/resume-a-plan.md`; re-fetch the page over HTTP — marker present with no copy step or restart |
| 3 | Schema | `docsSchema()` validates all simulated frontmatter during the clean build (schema failures fail the build — proven by criterion 9a) |
| 4 | Route + sidebar/TOC | Built route paths compared against blueprint §2; sidebar `<a href>` set extracted from `dist/index.html`; `starlight-toc` + body-heading anchor links extracted from `dist/reference/cli/index.html` |
| 5 | Markdown/MDX | `<table>` count in configuration page; `<pre>` count in get-started page; `sl-anchor-link` + `<h2 id=…>` in cli page (Starlight pipeline via `processedDirs`); evaluated MDX expression in the temp `.mdx` page's HTML |
| 6 | Assets | Built `<img>` tag references an emitted `dist/_astro/` file; dev-server image URL fetched with HTTP 200 `image/webp` |
| 7 | Pagefind | `dist/pagefind/` emitted; a Node script loads `dist/pagefind/pagefind.js` and queries `worktree` (primary Node-API check used; browser fallback not needed) |
| 8 | Single-rendered-H1 | `grep -o '<h1'` count per built page = 1; `<h1>` text compared to frontmatter title; canonical sources keep their standalone H1 |
| 9 | Error precision | Breakage (a): delete `title:` from one page; breakage (b): malform its YAML; run `npx astro build`; verbatim error captured, file restored |
| 10 | Cleanup | Post-teardown `git status --porcelain` shows only this record + the `docs/index.md` row (§7) |
| 11 | No-duplicate | Structural: approach 1 uses no staging directory; the scaffold imports/reads nothing from `docs/library/` |

## §4 Evaluations in order

### Approach 1 — direct external-tree collection loading: **PASS (selected)**

Configuration as evaluated: §5 verbatim. All 11 criteria passed; no criterion required
a mechanism outside approach 1's boundary (glob/config/remark tuning only). The one
in-approach adjustment: the remark plugin was first registered via top-level
`markdown.remarkPlugins`, which works but triggers an Astro 7 deprecation warning and
auto-coerces the processor; it was moved to the non-deprecated
`markdown.processor: unified({ remarkPlugins: […] })` form (§5), after which the build
is warning-free and criterion 8 still passes.

**1 — Clean build.** From the fresh scaffold, `npm install` (`added 352 packages in 32s`)
then `npx astro build` exited 0:

```text
10:16:07   ├─ /index.html (+37ms)
10:16:08   ├─ /tutorials/index.html (+5ms)
10:16:08   ├─ /tutorials/get-started/index.html (+18ms)
...
10:16:13 [build] 10 page(s) built in 8.89s
10:16:13 [build] Complete!
```

All 8 representative routes (plus the temp MDX route) exist under `dist/`:

```text
OK  dist/index.html
OK  dist/tutorials/index.html
OK  dist/tutorials/get-started/index.html
OK  dist/how-to/resume-a-plan/index.html
OK  dist/how-to/recover-a-dirty-worktree/index.html
OK  dist/reference/cli/index.html
OK  dist/reference/configuration/index.html
OK  dist/explanation/how-perk-thinks/index.html
OK  dist/spike-mdx-test/index.html
```

**2 — Dev-watch.** With `npx astro dev` running, a marker line appended to
`docs/user-docs/how-to/resume-a-plan.md` appeared in the served page ~3s later with no
copy step or restart. Dev log:

```text
10:18:27 [glob-loader] Reloaded data from how-to/resume-a-plan.md
```

The glob loader watches the external `base` directory directly, so edit-pickup is
native (nothing to regenerate).

**3 — Schema.** `docsSchema()` validated the simulated `title` + `description`
frontmatter on all 8 pages plus the MDX page during the clean build; criterion 9a shows
the same schema rejecting a missing `title` with a file-precise error.

**4 — Route + sidebar/TOC.** Built routes match blueprint §2 exactly: root `index.md` →
`/index.html` (`/`), `tutorials/index.md` → `/tutorials/index.html` (`/tutorials/`),
`how-to/resume-a-plan.md` → `/how-to/resume-a-plan/index.html`. (Mechanics: the glob
loader's default id generation strips a trailing `/index`, and Starlight maps the
residual root id `index` to `/`.) The explicit sidebar over the 8 pages renders — the
sidebar link set extracted from `dist/index.html`:

```text
/
/explanation/how-perk-thinks/
/how-to/recover-a-dirty-worktree/
/how-to/resume-a-plan/
/reference/cli/
/reference/configuration/
/tutorials/
/tutorials/get-started/
```

The page TOC renders from body headings: `starlight-toc` markup present on
`dist/reference/cli/index.html` with 191 in-page anchor links (`#orientation`,
`#perk-init`, `#perk-doctor`, …) over the 1,297-line monolith.

**5 — Markdown/MDX.** `dist/reference/configuration/index.html` contains 14 `<table>`
elements (GFM tables render); `dist/tutorials/get-started/index.html` contains 19
`<pre>` blocks (code fences render). Starlight's Markdown pipeline applied to the
external directory via `markdown.processedDirs`: heading anchors exist in built HTML —
88 `sl-anchor-link` occurrences and slugged heading ids (`<h2 id="orientation">`,
`<h2 id="setup--health">`) on the cli page. The temp `.mdx` page rendered through the
same bridge with its expression evaluated:

```html
evaluated at build time: <strong>42</strong>
```

**6 — Assets.** The relative `![Spike test image](./spike-test-image.png)` reference in
`tutorials/get-started.md` resolved in build — the image was emitted and referenced:

```html
<img alt="Spike test image" loading="lazy" decoding="async" width="1" height="1"
  src="/_astro/spike-test-image.5vcyeoBI_Z1Skb.webp" srcset="">
```

and in dev — fetching the dev-served image URL (`/_image?href=…spike-test-image.png…`)
returned `HTTP 200 content-type=image/webp`. Note: the asset is emitted through Astro's
image service as an optimized, content-hashed file (webp), not a verbatim copy.

**7 — Pagefind.** `astro build` emitted `dist/pagefind/`
(`[starlight:pagefind] Found 10 HTML files.`). The primary Node-API check was used: a
Node script imported `dist/pagefind/pagefind.js` and queried the built index for
`worktree`. One wrinkle: the Pagefind bundle loads its index chunks via `fetch()`, which
cannot read bare file paths in Node, so the script serves `dist/` over a loopback HTTP
server and sets `pagefind.options({ basePath })` accordingly. Query output:

```text
results: 6
- …/how-to/recover-a-dirty-worktree/ :: How to recover a dirty worktree
- …/reference/cli/ :: CLI commands
- …/reference/configuration/ :: Configuration files
- …/explanation/how-perk-thinks/ :: How perk thinks
- …/tutorials/get-started/ :: Get started with perk
```

The dirty-worktree page is the top result. The browser fallback was not needed.

**8 — Single-rendered-H1.** With the repo-owned remark plugin registered (§5), every
built page has exactly one `<h1>` whose text equals the frontmatter title, while every
canonical source file keeps its standalone `# H1` unchanged:

```text
index: count=1 title=perk user docs
tutorials: count=1 title=Tutorials
tutorials/get-started: count=1 title=Get started with perk
how-to/resume-a-plan: count=1 title=How to resume a plan at its current stage
how-to/recover-a-dirty-worktree: count=1 title=How to recover a dirty worktree
reference/cli: count=1 title=CLI commands
reference/configuration: count=1 title=Configuration files
explanation/how-perk-thinks: count=1 title=How perk thinks
spike-mdx-test: count=1 title=Spike MDX test
```

**9 — Error precision.** Both breakages applied to
`docs/user-docs/explanation/how-perk-thinks.md`, captured via `npx astro build`, then
restored. (a) `title:` line deleted — the error names the file and the problem:

```text
[InvalidContentEntryDataError] docs → explanation/how-perk-thinks data does not match collection schema.
  title**: **title: Required
  Location:
    …/docs/user-docs/explanation/how-perk-thinks.md:0:0
```

(b) YAML malformed (closing quote removed from the `title` value) — the error names the
file, line, and the parse problem:

```text
can not read a block mapping entry; a multiline key may not be an implicit key
  Location:
    …/docs/user-docs/explanation/how-perk-thinks.md:3:0
```

**10 — Cleanup.** All generated state (`node_modules/`, `dist/`, the `.astro` cache)
lives inside the untracked, disposable `docs/site/` scaffold (`node_modules/` and
`dist/` are additionally root-gitignored at any depth); approach 1 has no staging
directory. Teardown proof in §7.

**11 — No-duplicate.** No second checked-in content tree existed at any point: the
collection reads `docs/user-docs/` in place (no copy), the scaffold was never staged,
and nothing in the scaffold imports or reads from `docs/library/` (offline reference
material only).

### Approach 2 — repo-owned custom loader: **not reached (earlier approach selected)**

### Approach 3 — automatic ignored staging: **not reached (earlier approach selected)**

## §5 Selected bridge

The bridge node 2.2 applies without re-derivation. Project root is `docs/site/`; the
canonical corpus stays at `docs/user-docs/` (`../user-docs` from the project root).

**`docs/site/src/content.config.ts`** — the `docs` collection loads the external tree
directly:

```ts
import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

export const collections = {
	docs: defineCollection({
		loader: glob({
			base: '../user-docs',
			pattern: [ /* spike: explicit list of the 8 representative pages + temp MDX page */ ],
		}),
		schema: docsSchema(),
	}),
};
```

The spike pinned an explicit pattern list to scope the contract run; the mechanism is
pattern-independent, and node 2.2 widens it to the corpus-wide equivalent of Starlight's
own default (`'**/[^_]*.{md,mdx}'`).

**`docs/site/astro.config.mjs`** — the relevant fragments:

```js
import { unified } from '@astrojs/markdown-remark';
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import remarkStripFirstH1 from './src/remark-strip-first-h1.mjs';

export default defineConfig({
	markdown: {
		processor: unified({ remarkPlugins: [remarkStripFirstH1] }),
	},
	integrations: [
		starlight({
			title: 'perk',
			markdown: {
				processedDirs: ['../user-docs'],
			},
			sidebar: [ /* explicit sidebar; blueprint §3 binds the real map */ ],
		}),
	],
});
```

**The H1-strip plugin** (`docs/site/src/remark-strip-first-h1.mjs`): removes the first
depth-1 heading from each document's mdast tree, so Starlight's frontmatter-title `<h1>`
is the only rendered `<h1>` while canonical sources keep their standalone H1:

```js
export default function remarkStripFirstH1() {
	return (tree) => {
		const index = tree.children.findIndex(
			(node) => node.type === 'heading' && node.depth === 1,
		);
		if (index !== -1) tree.children.splice(index, 1);
	};
}
```

**Caveats discovered (binding context for 2.1/2.2):**

- **Remark plugins need the unified processor.** Astro 7's default Markdown processor
  (Sätteri) does not run remark plugins; top-level `markdown.remarkPlugins` is
  deprecated (it auto-coerces onto `unified()` with a console warning). Use
  `markdown.processor: unified({ remarkPlugins: […] })` from `@astrojs/markdown-remark`
  — already present as a Starlight peer dependency (7.2.2), but it becomes a direct
  import, so node 2.1 should declare it explicitly in `docs/site/package.json`.
- **Intra-corpus relative `.md` links are not rewritten.** Links like
  `[…](../reference/cli.md#anchor)` pass through verbatim into built HTML (broken as
  site links). The pass contract has no link-rewrite criterion, so this is a recorded
  gap, not a failure: node 2.2 must close it inside approach 1's boundary (a remark
  link-rewrite plugin alongside the H1-strip plugin, mapping source-relative `.md`
  paths onto the blueprint §2 route convention) or the corpus link convention must be
  reconciled.
- **Route mapping mechanics.** The glob loader's default id generation strips a
  trailing `/index` (`tutorials/index.md` → `tutorials`) and leaves the root as
  `index`, which Starlight itself maps to `/` — no `generateId` override needed for
  blueprint §2 conformance.
- **Asset handling.** Relative image references route through Astro's image service:
  emitted as optimized, content-hashed files under `dist/_astro/` (webp by default),
  served in dev via the `/_image` endpoint — not verbatim copies.
- **Dev-watch scope.** Verified for edits to already-loaded files (native glob-loader
  reload). Pickup of files newly added to the external directory mid-dev was not
  exercised by the contract.
- **Benign build noise.** `Entry docs → 404 was not found.` (Starlight probes for an
  optional custom 404 entry, then emits its default) and a sitemap WARN (needs the
  `site` config option — node 2.1's concern).

## §6 Install/build cost

| Measurement | Value |
|---|---|
| `npm install` wall time | 32.5s (`added 352 packages in 32s`) |
| `du -sh docs/site/node_modules` | 213M |
| `npx astro build`, first run (cold caches) | 19.2s wall; astro-reported `10 page(s) built in 8.89s` (image optimization 2.97s + Pagefind 1.78s inside that) |
| `npx astro build`, warm rebuild | 4.4s wall; astro-reported `10 page(s) built in 2.27s` (Pagefind 99ms) |
| Environment | Node v26.3.0, npm 11.16.0, macOS 26.5 / Darwin arm64 |

## §7 Simulations & disposal

Three temporary, worktree-only simulations were applied for the contract run and fully
reverted at teardown — none reached the commit:

- **Frontmatter** — `title` (byte-equal to each page's H1 text, per blueprint §6) + a
  one-sentence `description` prepended to each of the 8 representative pages,
  simulating the post-node-2.3 canonical state.
- **Asset** — a 1×1 PNG at `docs/user-docs/tutorials/spike-test-image.png` plus one
  relative `![…](…)` reference appended to `tutorials/get-started.md` (the corpus has
  no assets today; the criterion needs one).
- **MDX** — a throwaway `docs/user-docs/spike-mdx-test.mdx` page with the same
  simulated frontmatter.

Teardown: `rm -rf docs/site`, `git checkout -- docs/user-docs`, delete the temp image
and MDX files. Post-teardown `git status --porcelain` (the criterion-10 proof — exactly
the two committed files):

```text
 M docs/index.md
?? docs/design/docs-site-bridge-spike.md
```

No disposable alternative machinery was committed: approaches 2 and 3 were never
reached, nothing scaffold-shaped lands in the repo, and the "remove disposable
alternatives" requirement is satisfied structurally.
