# prompts — canonical cross-plane prompt templates

perk's prompt templates, authored once and **bundled into every build artifact**
(the Python wheel as package data `perk/_prompts/`; the npm package under `prompts/`),
exactly like `shared/`. Each plane locates this directory at runtime through its own
resolver — `prompts_dir()` (`perk/_resources.py`) and `promptsDir()`
(`extension/substrate/resources.ts`): installed bundle → editable repo-sibling fallback.

Templates are rendered by jinja2 (Python) and a vendored TS subset (the extension), and
are loaded by explicit name through the resolver — never by scanning the directory, so
this README is a durable doc, not a template.

The render seam, the frozen template-grammar spec, and the real prompt content land in
later nodes; for now this file is the bundling/resolution probe that gives the directory
tracked content.
