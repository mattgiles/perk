// The TS plane's prompt render seam — the twin of perk/prompts.py::render.
//
// Templates are loaded by explicit `name` (root-relative under `prompts/`) via promptsDir(),
// the same directory the Python twin reads. The feature surface is the frozen mini-jinja subset
// (`shared/contracts.md §8.31`): `{{ var }}` substitution, `{% include %}`, and
// `{% if %}`/`{% elif %}`/`{% else %}`/`{% endif %}` conditionals. A missing (or non-string)
// variable fails loudly rather than rendering an empty string.
//
// jinja2 is the REFERENCE engine: the committed golden bytes under prompts/_fixtures/golden/
// ARE jinja2's output, and this seam must reproduce them byte-for-byte (enforced by prompts.test.ts
// + tests/test_prompts.py). Rendering is delegated to the vendored, zero-dependency
// ./miniJinja.ts renderer — which bakes in the frozen render config (trim_blocks on so a block
// tag on its own line emits no spurious newline, lstrip off, trailing newline preserved) and
// owns the filesystem (resolving `name` and every `{% include %}` under promptsDir()). Vendoring
// keeps the extension zero-runtime-dep / loadable from a bare git clone (guarded by
// extension/bareImportGuard.test.ts).
//
// This seam is LIVE in production: render is imported by extension/worker/worker.ts, the
// learn/address/learnDocs/lifecycleGates doors, and extension/factories/objectivePlan.ts.

import { render as miniJinjaRender } from "./miniJinja.ts";

/** Render the template at `name` (root-relative under `prompts/`) with `vars`. */
export function render(name: string, vars: Record<string, unknown>): string {
  return miniJinjaRender(name, vars);
}
