import { defineCollection } from "astro:content";
import { docsSchema } from "@astrojs/starlight/schema";
import { glob } from "astro/loaders";
import { z } from "astro/zod";

// External-tree bridge (docs/design/archive/docs-site-bridge-spike.md §5): the docs collection loads
// `docs/user-docs/` in place — no staging tree, no custom loader. `base` is resolved against
// the site root. The pattern excludes `_`-prefixed basenames (unrouted authoring files) and
// deliberately admits only the blueprint-approved `.md`/`.mdx` formats.
//
// The schema extension makes the build validate the blueprint §6 metadata contract with
// file-precise errors: `description` is required on every routed page (stock `docsSchema()`
// already requires `title`), and `sidebarGroup` — the navigation-ownership record for the flat
// `how-to/` tree, whose sidebar renders as the five §3 operator groups — is validated against
// that closed group set. Per-directory requiredness/absence of `sidebarGroup` and `sidebar.order`
// presence live in the pytest guard (`tests/test_user_docs_metadata.py`): re-defining Starlight's
// own nested `sidebar` shape here is deliberately avoided.
export const collections = {
  docs: defineCollection({
    loader: glob({ base: "../user-docs", pattern: "**/[^_]*.{md,mdx}" }),
    schema: docsSchema({
      extend: z.object({
        description: z.string().min(1),
        sidebarGroup: z
          .enum([
            "Core workflow",
            "Objectives & learnings",
            "Headless & remote",
            "Customization",
            "Providers & backends",
          ])
          .optional(),
      }),
    }),
  }),
};
