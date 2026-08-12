import starlight from "@astrojs/starlight";
import { defineConfig } from "astro/config";

export default defineConfig({
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
    }),
  ],
});
