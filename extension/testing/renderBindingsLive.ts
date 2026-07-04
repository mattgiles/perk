// The TS side of the live cross-plane binding-render parity tier (dev-only; excluded from the
// published tarball via the `!extension/testing/` rule in package.json `files`). NOT a `.test.ts` —
// it is never picked up by `node --test "extension/**/*.test.ts"`; it is invoked once, as a
// subprocess, by the Python-owned `tests/test_binding_render_parity.py`.
//
// argv: <repoRoot> <trigger> [<trigger> ...]. Renders each trigger's resolved skill bindings
// (defaults ⊕ the repo's user overlay) with the warm renderer (`renderBindings` — the content
// Mechanism A injects in warm/worker sessions) and prints the `text` results (string | null) as a
// JSON array on stdout IN ARGV ORDER. The Python test renders the same triggers with
// `render_cold_bindings` (the cold-door prompt suffix) and asserts byte-equality per trigger —
// proving the two delivery mechanisms carry identical guidance content (contracts.md §8.38).

import { renderBindings } from "../substrate/bindingDelivery.ts";

const [cwd, ...triggers] = process.argv.slice(2);
if (!cwd || triggers.length === 0) {
  process.stderr.write("usage: node renderBindingsLive.ts <repoRoot> <trigger> [...]\n");
  process.exit(2);
}

const results = triggers.map((trigger) => renderBindings(cwd, trigger).text);
process.stdout.write(JSON.stringify(results));
