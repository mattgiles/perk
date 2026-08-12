import { fileURLToPath } from "node:url";
import { unified } from "@astrojs/markdown-remark";
import starlight from "@astrojs/starlight";
import { defineConfig } from "astro/config";
import { corpusLinkGate, createCorpusLinkAudit } from "./src/corpus-link-audit.mjs";
import remarkRewriteCorpusLinks from "./src/remark-rewrite-corpus-links.mjs";
import remarkStripFirstH1 from "./src/remark-strip-first-h1.mjs";

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
      customCss: [
        "@fontsource-variable/inter/index.css",
        "@fontsource/ibm-plex-mono/latin-400.css",
        "@fontsource/ibm-plex-mono/latin-500.css",
        "@fontsource/ibm-plex-mono/latin-600.css",
        "./src/styles/tokens.css",
      ],
      // The corpus lives outside the site tree — let Starlight process it in place.
      markdown: { processedDirs: ["../user-docs"] },
    }),
    corpusLinkGate(audit, { corpusDir }),
  ],
});
