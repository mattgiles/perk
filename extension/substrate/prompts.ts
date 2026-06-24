// The TS plane's prompt render seam — the twin of perk/prompts.py::render.
//
// Templates are loaded by explicit `name` (root-relative under `prompts/`) via promptsDir(),
// the same directory the Python twin reads. The feature surface is intentionally small —
// `{{ var }}` substitution and `{% include %}` — and `throwOnUndefined` makes a missing
// variable fail loudly rather than render an empty string.
//
// jinja2 is the REFERENCE engine: the committed golden bytes under prompts/_fixtures/golden/
// ARE jinja2's output, and this nunjucks twin must reproduce them byte-for-byte. Golden parity
// is enforced by prompts.test.ts + tests/test_prompts.py. The Environment config below is the
// parity baseline both engines share (autoescape off, trimBlocks on so a block tag on its own
// line emits no spurious newline — letting conditional templates keep their tags off the content
// lines while preserving indentation — lstripBlocks off; nunjucks keeps the trailing newline,
// matching jinja2's keep_trailing_newline=True).
//
// This module is imported ONLY by its test in this node — there is no real prompt to render
// until Phase 2, so wiring it into extension/index.ts would be dead code. The runtime nunjucks
// dependency is removed and the zero-dep / bare-clone-loadable invariant restored when the
// renderer is vendored (node 4.2).

import nunjucks from "nunjucks";

import { promptsDir } from "./resources.ts";

const env = new nunjucks.Environment(new nunjucks.FileSystemLoader(promptsDir()), {
  throwOnUndefined: true,
  autoescape: false,
  trimBlocks: true,
  lstripBlocks: false,
});

/** Render the template at `name` (root-relative under `prompts/`) with `vars`. */
export function render(name: string, vars: Record<string, unknown>): string {
  return env.render(name, vars);
}
