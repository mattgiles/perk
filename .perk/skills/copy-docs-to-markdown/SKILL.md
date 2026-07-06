---
name: copy-docs-to-markdown
description: Mirror technical documentation from a website URL into a local directory of organized Markdown files (default docs/library/<name>/), preserving the site's section structure, rewriting internal links to local relative links, and generating an index.md entrypoint. Use when asked to copy or mirror docs locally, vendor a library's documentation into the repo, crawl a documentation site into Markdown, or build a local Markdown reference of an external doc set.
---

# Copy docs to Markdown

Create a local Markdown reference copy of technical documentation from a documentation URL, so
future agents can read it without network access. Keep the result readable: preserve the site
structure, retain source URLs, and write a practical `index.md` that explains where to look for
each topic.

**Prerequisites:** `curl` and `html2markdown` must be on `PATH` (e.g.
`brew install html2markdown`). The bundled script is stdlib-only Python.

**Default destination:** `docs/library/<name>/`, where `<name>` is a short slug for the doc set
(e.g. `docs/library/pydantic-validation/`). Use a different destination only when the user asks
for one.

## Workflow

Use the bundled script for the standard pipeline; resolve its path relative to this skill's
directory.

1. **Dry-run first** when the crawl scope is uncertain — it lists the URL → file mapping without
   writing anything:

   ```bash
   uv run python scripts/copy_docs_to_markdown.py URL docs/library/NAME --dry-run
   ```

2. **Choose the crawl scope.** By default the script scopes to the seed URL's origin + parent
   path. If the site hosts multiple doc products or versions, pass an explicit prefix such as
   `--scope-prefix /docs/validation/latest/`. Assets, anchor-only links, external sites,
   `mailto:`, and non-HTML extensions are skipped automatically.

3. **Run the copy** with a page cap:

   ```bash
   uv run python scripts/copy_docs_to_markdown.py URL docs/library/NAME \
     --scope-prefix /docs/validation/latest/ \
     --max-pages 100
   ```

   The script fetches each page with `curl`, converts it with `html2markdown`, writes files that
   preserve the scoped URL hierarchy (`/concepts/models/` → `concepts/models.md`), rewrites
   internal links to local relative `.md` links, and generates `index.md` with grouped local
   links and short per-page notes.

4. **Prune** generated files that are obviously outside the requested doc set — unrelated product
   areas, alternate versions, marketing pages, changelogs, blog posts, or pages that only contain
   navigation/search boilerplate — unless the user explicitly asked for them. After pruning,
   update `index.md` and remove links to deleted files.

5. **Inspect and fix artifacts.** Spot-check the generated Markdown for site-specific noise:
   duplicate nav blocks, broken local links, cookie/search boilerplate. Fix what a future reader
   would trip over.

## Report when done

- Destination directory
- Number of pages copied
- Scope prefix used
- Any skipped or failed URLs
- The best entrypoint (usually `index.md`)
