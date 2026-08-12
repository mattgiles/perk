import { defineCollection } from "astro:content";
import { docsSchema } from "@astrojs/starlight/schema";
import { glob } from "astro/loaders";

// External-tree bridge (docs/design/docs-site-bridge-spike.md §5): the docs collection loads
// `docs/user-docs/` in place — no staging tree, no custom loader. `base` is resolved against
// the site root. The pattern excludes `_`-prefixed basenames (unrouted authoring files) and
// deliberately admits only the blueprint-approved `.md`/`.mdx` formats.
export const collections = {
  docs: defineCollection({
    loader: glob({ base: "../user-docs", pattern: "**/[^_]*.{md,mdx}" }),
    schema: docsSchema(),
  }),
};
