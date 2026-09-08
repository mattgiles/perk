// Non-vacuity controls for the policy-free import-graph machinery (`importGraph.ts`): fully
// synthetic fixtures through the same pure functions the import-direction guard's production
// assertions call. The policy-coupled controls (corpus floors, the resurrection mutation, the
// rule matrices over the real constants) stay in `extension/importDirectionGuard.test.ts`.

import assert from "node:assert/strict";
import { test } from "node:test";
import { buildEdges, checkDirCensus, extractSpecifiers, findCycles } from "./importGraph.ts";

test("extractSpecifiers: sees all five specifier forms and ignores comments", () => {
  const fixture = [
    'import a from "./static.ts";',
    'import type { B } from "./typeOnly.ts";',
    'export { c } from "./reExport.ts";',
    'const d = await import("./dynamic.ts");',
    'const e = require("./required.ts");',
    '// import x from "./commented.ts";',
    '/* import y from "./blockCommented.ts"; */',
  ].join("\n");
  const specs = extractSpecifiers(fixture);
  assert.deepEqual([...specs].sort(), [
    "./dynamic.ts",
    "./reExport.ts",
    "./required.ts",
    "./static.ts",
    "./typeOnly.ts",
  ]);
});

test("findCycles: fixtures (2-cycle, 3-cycle, self-loop, acyclic)", () => {
  const twoCycle = new Map([
    ["a.ts", ["b.ts"]],
    ["b.ts", ["a.ts"]],
  ]);
  assert.deepEqual(findCycles(twoCycle), [["a.ts", "b.ts"]]);

  const threeCycle = new Map([
    ["a.ts", ["b.ts"]],
    ["b.ts", ["c.ts"]],
    ["c.ts", ["a.ts"]],
  ]);
  assert.deepEqual(findCycles(threeCycle), [["a.ts", "b.ts", "c.ts"]]);

  const selfLoop = new Map([["a.ts", ["a.ts"]]]);
  assert.deepEqual(findCycles(selfLoop), [["a.ts"]]);

  const acyclic = new Map([
    ["a.ts", ["b.ts", "c.ts"]],
    ["b.ts", ["c.ts"]],
    ["c.ts", []],
  ]);
  assert.deepEqual(findCycles(acyclic), []);
});

test("buildEdges: an extensionless relative import is reported, never a phantom-node bypass", () => {
  // The discriminating case: a.ts → "./b" (extensionless), b.ts → "./a.ts". Without corpus
  // resolution the cycle would thread through a phantom `b` node and vanish from Tarjan's view;
  // with it, the unresolvable specifier is a reported failure.
  const lax = buildEdges(["a.ts", "b.ts"], (file) =>
    file === "a.ts" ? 'import { x } from "./b";' : 'import { y } from "./a.ts";',
  );
  assert.deepEqual(
    lax.unresolved,
    ['a.ts: "./b" → b'],
    "the extensionless specifier must be reported",
  );
  assert.deepEqual(findCycles(lax.edges), [], "the phantom edge must not fabricate a cycle");

  // The properly-extensioned twin IS the cycle — resolution, not detection, was the gap.
  const strict = buildEdges(["a.ts", "b.ts"], (file) =>
    file === "a.ts" ? 'import { x } from "./b.ts";' : 'import { y } from "./a.ts";',
  );
  assert.deepEqual(strict.unresolved, []);
  assert.deepEqual(findCycles(strict.edges), [["a.ts", "b.ts"]]);
});

test("checkDirCensus: fixtures (unknown, stale, overlap, anchor floor, valid entry)", () => {
  const frozen = ["alpha", "beta"];
  const inCorpus = (anchor: string) => anchor === "gamma/anchor.ts";

  const unknown = checkDirCensus(["alpha", "beta", "gamma"], frozen, {}, inCorpus);
  assert.deepEqual(unknown.unknown, ["gamma"], "an unknown extra top-level dir must fail");

  const stale = checkDirCensus(["alpha"], frozen, {}, inCorpus);
  assert.deepEqual(stale.stale, ["beta"], "a census entry with no live dir must fail");

  const overlap = checkDirCensus(
    ["alpha", "beta"],
    frozen,
    { beta: ["beta/anchor.ts"] },
    () => true,
  );
  assert.deepEqual(
    overlap.overlap,
    ["beta"],
    "a dir in both the frozen census and the anchored map must fail",
  );

  const emptyAnchors = checkDirCensus(["alpha", "beta", "gamma"], frozen, { gamma: [] }, inCorpus);
  assert.deepEqual(
    emptyAnchors.anchorIssues,
    ["gamma: no anchor files registered (≥1 required)"],
    "an empty anchor registration must fail — a future dir can never become expected anchor-free",
  );
  assert.deepEqual(emptyAnchors.unknown, [], "an anchored dir is a registered dir");

  const outsideAnchor = checkDirCensus(
    ["alpha", "beta", "gamma"],
    frozen,
    { gamma: ["alpha/anchor.ts"] },
    () => true,
  );
  assert.deepEqual(
    outsideAnchor.anchorIssues,
    ["gamma: anchor alpha/anchor.ts is not inside the directory"],
    "an anchor outside its registered directory must fail",
  );

  const uncorpusedAnchor = checkDirCensus(
    ["alpha", "beta", "gamma"],
    frozen,
    { gamma: ["gamma/missing.ts"] },
    inCorpus,
  );
  assert.deepEqual(
    uncorpusedAnchor.anchorIssues,
    ["gamma: anchor gamma/missing.ts is not a scanned production .ts file"],
    "an anchor absent from the scanned corpus must fail",
  );

  const valid = checkDirCensus(
    ["alpha", "beta", "gamma"],
    frozen,
    { gamma: ["gamma/anchor.ts"] },
    inCorpus,
  );
  assert.deepEqual(valid.unknown, []);
  assert.deepEqual(valid.stale, []);
  assert.deepEqual(valid.overlap, []);
  assert.deepEqual(
    valid.anchorIssues,
    [],
    "a registered dir with a valid in-directory corpus anchor must pass",
  );
});
