// Node 2.1 — loadProviders against the REAL bundled providers.yaml. The shipped supported set is
// the two reference entries (perk-plan, perk-checkpoints — both default) plus one illustrative
// foreign entry per seam. The Python plane (tests/test_providers.py) is the authoritative
// validator; this is the thin TS-side structural parse (mirror of extension/bindings.test.ts).

import assert from "node:assert/strict";
import { test } from "node:test";
import { loadProviders } from "./providers.ts";

test("loadProviders: returns the four shipped supported-set entries", () => {
  const providers = loadProviders();
  assert.deepEqual(
    providers.map((p) => [p.id, p.seam, p.package, p.default]),
    [
      ["perk-plan", "plan", null, true],
      ["perk-checkpoints", "todo", null, true],
      ["tombell-plan", "plan", "npm:@tombell/pi-plan", false],
      ["juicesharp-todo", "todo", "npm:@juicesharp/rpiv-todo", false],
    ],
  );
});

test("loadProviders: reference provider has null package/adapter and no filter", () => {
  const perkPlan = loadProviders().find((p) => p.id === "perk-plan");
  assert.deepEqual(perkPlan, {
    id: "perk-plan",
    seam: "plan",
    package: null,
    adapter: null,
    default: true,
  });
});

test("loadProviders: foreign entry carries adapter + nested package_filter", () => {
  const tombell = loadProviders().find((p) => p.id === "tombell-plan");
  assert.equal(tombell?.adapter, "planAdapterTombell");
  assert.deepEqual(tombell?.packageFilter, { extensions: ["extensions/*.ts"], skills: [] });
});
