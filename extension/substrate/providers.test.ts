// Node 2.1 — loadProviders against the REAL bundled providers.yaml. The shipped supported set is
// the two reference entries (perk-plan, perk-checkpoints — both default) plus one REAL foreign
// entry per seam (tombell-plan, Node 2.3; juicesharp-todo, Node 3.2). The Python plane
// (tests/test_providers.py) is the authoritative validator; this is the thin TS-side structural
// parse (mirror of extension/substrate/bindings.test.ts).

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  JUICESHARP_ASK_USER_PROVIDER_ID,
  loadProviders,
  PERK_ASK_USER_PROVIDER_ID,
  PERK_CHECKPOINTS_PROVIDER_ID,
  PERK_PLAN_PROVIDER_ID,
  PLANNOTATOR_PLAN_PROVIDER_ID,
  PROVIDER_SEAMS,
  resolveProviders,
} from "./providers.ts";

test("PROVIDER_SEAMS includes the askuser seam", () => {
  assert.deepEqual([...PROVIDER_SEAMS], ["plan", "todo", "askuser"]);
});

test("loadProviders: returns the shipped supported-set entries", () => {
  const providers = loadProviders();
  assert.deepEqual(
    providers.map((p) => [p.id, p.seam, p.package, p.default]),
    [
      ["perk-plan", "plan", null, true],
      ["perk-checkpoints", "todo", null, true],
      ["perk-ask-user", "askuser", null, true],
      ["tombell-plan", "plan", "npm:@tombell/pi-plan", false],
      ["plannotator-plan", "plan", "npm:@plannotator/pi-extension", false],
      ["juicesharp-todo", "todo", "npm:@juicesharp/rpiv-todo", false],
      ["juicesharp-ask-user", "askuser", "npm:@juicesharp/rpiv-ask-user-question", false],
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

test("loadProviders: the real plannotator-plan entry carries adapter + NO package_filter", () => {
  // Augment posture: planAdapterPlannotator bridges the browser review via the plan_review tool;
  // perk's plan surface + gate stay registered. No `package_filter` (`pi.extensions: ["./"]` —
  // the sole extension is the package root), so omitting the filter loads exactly that one.
  const plannotator = loadProviders().find((p) => p.id === PLANNOTATOR_PLAN_PROVIDER_ID);
  assert.equal(plannotator?.adapter, "planAdapterPlannotator");
  assert.equal(plannotator?.package, "npm:@plannotator/pi-extension");
  assert.equal(plannotator?.seam, "plan");
  assert.equal(plannotator?.default, false);
  assert.equal(plannotator?.packageFilter, undefined);
});

test("loadProviders: the real juicesharp-todo entry carries adapter + NO package_filter", () => {
  // Node 3.2: `juicesharp-todo` is now a REAL todo provider (todoAdapterJuicesharp bridges it). No
  // `package_filter` (single-concern checklist overlay) — mirrors the tombell case.
  const juicesharp = loadProviders().find((p) => p.id === "juicesharp-todo");
  assert.equal(juicesharp?.adapter, "todoAdapterJuicesharp");
  assert.equal(juicesharp?.package, "npm:@juicesharp/rpiv-todo");
  assert.equal(juicesharp?.seam, "todo");
  assert.equal(juicesharp?.default, false);
  assert.equal(juicesharp?.packageFilter, undefined);
});

test("loadProviders: the real juicesharp-ask-user entry is VACATE-ONLY (null adapter, no filter)", () => {
  // Interface seam: the foreign tool shares the exact name `ask_user_question`, so there is no
  // artifact to bridge — adapter is null (vacate-only). No `package_filter` (manifest is
  // `{"extensions": ["./index.ts"]}`) — mirrors the tombell/juicesharp-todo cases.
  const juiceAsk = loadProviders().find((p) => p.id === JUICESHARP_ASK_USER_PROVIDER_ID);
  assert.equal(juiceAsk?.adapter, null);
  assert.equal(juiceAsk?.package, "npm:@juicesharp/rpiv-ask-user-question");
  assert.equal(juiceAsk?.seam, "askuser");
  assert.equal(juiceAsk?.default, false);
  assert.equal(juiceAsk?.packageFilter, undefined);
});

// --- resolveProviders (the pure resolver, mirror of tests/test_providers.py) ------------------

test("resolveProviders: absent keys fall back to the seam defaults silently", () => {
  const resolved = resolveProviders({}, loadProviders());
  assert.equal(resolved.plan.id, PERK_PLAN_PROVIDER_ID);
  assert.equal(resolved.todo.id, PERK_CHECKPOINTS_PROVIDER_ID);
  assert.equal(resolved.askuser.id, PERK_ASK_USER_PROVIDER_ID);
  assert.deepEqual(resolved.issues, []);
});

test("resolveProviders: the askuser seam resolves selection / mismatch / unknown", () => {
  const set = loadProviders();
  assert.equal(
    resolveProviders({ askuser: JUICESHARP_ASK_USER_PROVIDER_ID }, set).askuser.id,
    JUICESHARP_ASK_USER_PROVIDER_ID,
  );
  const mismatch = resolveProviders({ askuser: "perk-plan" }, set);
  assert.equal(mismatch.askuser.id, PERK_ASK_USER_PROVIDER_ID);
  assert.equal(mismatch.issues.length, 1);
  assert.match(mismatch.issues[0] ?? "", /is a `plan` provider, not `askuser`/);
  const unknown = resolveProviders({ askuser: "ghost" }, set);
  assert.equal(unknown.askuser.id, PERK_ASK_USER_PROVIDER_ID);
  assert.equal(unknown.issues.length, 1);
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
