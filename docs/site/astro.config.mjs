import { fileURLToPath } from "node:url";
import { unified } from "@astrojs/markdown-remark";
import starlight from "@astrojs/starlight";
import { defineConfig } from "astro/config";
import { corpusLinkGate, createCorpusLinkAudit } from "./src/corpus-link-audit.mjs";
import { ranking } from "./src/pagefind-ranking.mjs";
import remarkRewriteCorpusLinks from "./src/remark-rewrite-corpus-links.mjs";
import remarkStripFirstH1 from "./src/remark-strip-first-h1.mjs";
import { sidebar } from "./src/sidebar.mjs";

const corpusDir = fileURLToPath(new URL("../user-docs/", import.meta.url));
const audit = createCorpusLinkAudit();

export default defineConfig({
  // The single `markdown.processor` registration is the FINAL configuration shape for both
  // pipelines: the pinned @astrojs/mdx copies the processor's remarkPlugins into the MDX
  // pipeline, and a top-level `markdown.remarkPlugins` key alongside would be appended into
  // this same processor — double-registering the plugins for `.md`. Never add one; on any
  // contradiction with observed behavior, stop and take it to objective reconciliation.
  markdown: {
    processor: unified({
      remarkPlugins: [remarkStripFirstH1, [remarkRewriteCorpusLinks, { corpusDir, audit }]],
    }),
  },
  vite: {
    resolve: {
      alias: [
        // Visual blueprint §8: an MDX page loaded from the external corpus tree imports
        // `@astrojs/starlight/components` as a bare specifier, which must resolve from the
        // site tree. Regex EXACT match so Starlight's own internal
        // `@astrojs/starlight/components/…` subpath imports are not captured; the replacement
        // resolves from this config file via ordinary parent-directory (walk-up) lookup into
        // the hoisted root node_modules — the workspace hoists the site's deps there.
        {
          find: /^@astrojs\/starlight\/components$/,
          replacement: fileURLToPath(import.meta.resolve("@astrojs/starlight/components")),
        },
      ],
    },
  },
  // Local-only static site: deliberately no `site`, no adapter, no deployment
  // machinery (Objective #1622 boundary). Starlight's sitemap WARN about the
  // missing `site` option is expected — see README.md.
  integrations: [
    starlight({
      title: "perk",
      // The explicit blueprint-§3 sidebar (src/sidebar.mjs; agreement with the corpus
      // frontmatter is guarded by src/sidebar.test.mjs).
      sidebar,
      // Pagination policy: globally OFF — Starlight's default prev/next links follow sidebar
      // order across section boundaries, implying a linear reading order that is wrong for
      // how-to/reference content. Pages opt in per-page (frontmatter `prev`/`next: true`)
      // only where a deliberately linear reading sequence exists — currently exactly the
      // three-tutorial chain (guarded by checks/built-site.test.mjs and
      // tests/test_user_docs_findability.py).
      pagination: false,
      // The shared ranking object (src/pagefind-ranking.mjs) keeps this UI and the relevance
      // matrix (checks/pagefind.test.mjs) in exact agreement — see that module's comment.
      pagefind: { ranking },
      customCss: [
        "@fontsource-variable/inter/index.css",
        "@fontsource/ibm-plex-mono/latin-400.css",
        "@fontsource/ibm-plex-mono/latin-500.css",
        "@fontsource/ibm-plex-mono/latin-600.css",
        "./src/styles/tokens.css",
        "./src/styles/compositions.css",
        "./src/styles/system.css",
      ],
      // The corpus lives outside the site tree — let Starlight process it in place.
      markdown: { processedDirs: ["../user-docs"] },
    }),
    corpusLinkGate(audit, { corpusDir }),
  ],
});
