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
// This seam is LIVE in production: render is imported by the worker, the warm doors, the
// factories, and the mode/adapter context modules (the `prompts/contexts/` injections).
//
// Besides the render seam itself, the module carries ONE cross-plane selector wrapping it:
// `planReadInstruction`, the per-backend plan-read arm shared by the doors and the
// stage-execution seam.

import { render as miniJinjaRender } from "./miniJinja.ts";

/** Render the template at `name` (root-relative under `prompts/`) with `vars`. */
export function render(name: string, vars: Record<string, unknown>): string {
  return miniJinjaRender(name, vars);
}

/**
 * The per-backend plan-read instruction — the prompt SSOT for "how do I read the saved
 * plan". Byte-identical to `src/perk/run/launch/prompts.py::_plan_read_instruction` (the Python
 * twin — likewise a prompts module); drift in either plane fails the paired parity suites.
 * `github` reads via `gh`; `linear` points at the pi-mono-linear tools with an `open <url>`
 * fallback; any other provider falls back to opening the url.
 *
 * The wording lives in the canonical templates `prompts/common/plan-read/*.md`, rendered
 * identically by both planes via the shared render seam (contracts.md §8.31); branching stays in
 * code — only the arm chosen and the vars passed differ. Golden-fixture parity (the three
 * `plan-read-*` cases) plus a thin per-arm selection test replace the dedicated substring parity.
 */
export function planReadInstruction(provider: string, prId: string, url: string): string {
  if (provider === "github") return render("common/plan-read/github.md", { pr_id: prId, url });
  if (provider === "linear") return render("common/plan-read/linear.md", { pr_id: prId, url });
  return render("common/plan-read/other.md", { pr_id: prId, url });
}
