// Node 2.1 — loadProviders against the REAL bundled providers.yaml. The shipped supported set is
// the two reference entries (perk-plan, perk-checkpoints — both default) plus one illustrative
// foreign entry per seam. The Python plane (tests/test_providers.py) is the authoritative
// validator; this is the thin TS-side structural parse (mirror of extension/bindings.test.ts).

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  loadProviders,
  PERK_CHECKPOINTS_PROVIDER_ID,
  PERK_PLAN_PROVIDER_ID,
  resolveProviders,
} from "./providers.ts";

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

test("loadProviders: the real tombell-plan entry carries adapter + NO package_filter", () => {
  // Node 2.3: the real entry drops `package_filter` (the illustrative `extensions/*.ts` matched
  // nothing — `@tombell/pi-plan`'s sole extension is root `index.ts`). Omitting it loads all.
  const tombell = loadProviders().find((p) => p.id === "tombell-plan");
  assert.equal(tombell?.adapter, "planAdapterTombell");
  assert.equal(tombell?.package, "npm:@tombell/pi-plan");
  assert.equal(tombell?.seam, "plan");
  assert.equal(tombell?.default, false);
  assert.equal(tombell?.packageFilter, undefined);
});

// --- resolveProviders (the pure resolver, mirror of tests/test_providers.py) ------------------

test("resolveProviders: absent keys fall back to the seam defaults silently", () => {
  const resolved = resolveProviders({}, loadProviders());
  assert.equal(resolved.plan.id, PERK_PLAN_PROVIDER_ID);
  assert.equal(resolved.todo.id, PERK_CHECKPOINTS_PROVIDER_ID);
  assert.deepEqual(resolved.issues, []);
});

test("resolveProviders: a valid selection picks the named provider; absent todo -> default", () => {
  const resolved = resolveProviders({ plan: "tombell-plan" }, loadProviders());
  assert.equal(resolved.plan.id, "tombell-plan");
  assert.equal(resolved.todo.id, PERK_CHECKPOINTS_PROVIDER_ID);
  assert.deepEqual(resolved.issues, []);
});

test("resolveProviders: an unknown id falls back with one issue", () => {
  const resolved = resolveProviders({ plan: "ghost" }, loadProviders());
  assert.equal(resolved.plan.id, PERK_PLAN_PROVIDER_ID);
  assert.equal(resolved.issues.length, 1);
  assert.match(resolved.issues[0] ?? "", /unknown provider `ghost`/);
});

test("resolveProviders: a seam mismatch falls back with one issue", () => {
  // juicesharp-todo is a `todo` provider; selecting it for `plan` is a seam mismatch.
  const resolved = resolveProviders({ plan: "juicesharp-todo" }, loadProviders());
  assert.equal(resolved.plan.id, PERK_PLAN_PROVIDER_ID);
  assert.equal(resolved.issues.length, 1);
  assert.match(resolved.issues[0] ?? "", /is a `todo` provider, not `plan`/);
});

test("resolveProviders: loads the bundled set when the set is omitted", () => {
  const resolved = resolveProviders({});
  assert.equal(resolved.plan.id, PERK_PLAN_PROVIDER_ID);
  assert.equal(resolved.todo.id, PERK_CHECKPOINTS_PROVIDER_ID);
});
