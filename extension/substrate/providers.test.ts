// loadProviders against the REAL bundled providers.yaml. The shipped supported set is
// the two reference entries (perk-plan, perk-checkpoints — both default) plus one REAL foreign
// entry per seam (tombell-plan; juicesharp-todo). The Python plane
// (tests/test_providers.py) is the authoritative validator; this is the thin TS-side structural
// parse (mirror of extension/substrate/bindings.test.ts).

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  JUICESHARP_WEB_PROVIDER_ID,
  loadProviders,
  OLLAMA_WEB_PROVIDER_ID,
  PERK_CHECKPOINTS_PROVIDER_ID,
  PERK_FOOTER_PROVIDER_ID,
  PERK_PLAN_PROVIDER_ID,
  PI_BAR_FOOTER_PROVIDER_ID,
  PI_DEFAULT_FOOTER_PROVIDER_ID,
  PI_STATUS_FOOTER_PROVIDER_ID,
  PI_WEB_ACCESS_PROVIDER_ID,
  PLANNOTATOR_PLAN_PROVIDER_ID,
  POWERLINE_FOOTER_PROVIDER_ID,
  PROVIDER_SEAMS,
  resolveProviders,
} from "./providers.ts";

test("PROVIDER_SEAMS is the four seams (review and askuser are retired)", () => {
  // review → the surface-named doors; askuser → a required borrow (built-in questionnaire tool).
  assert.deepEqual([...PROVIDER_SEAMS], ["plan", "todo", "footer", "web"]);
});

test("loadProviders: returns the shipped supported-set entries", () => {
  const providers = loadProviders();
  assert.deepEqual(
    providers.map((p) => [p.id, p.seam, p.package, p.default]),
    [
      ["perk-plan", "plan", null, true],
      ["perk-checkpoints", "todo", null, true],
      ["tombell-plan", "plan", "npm:@tombell/pi-plan", false],
      ["plannotator-plan", "plan", "npm:@plannotator/pi-extension", false],
      ["juicesharp-todo", "todo", "npm:@juicesharp/rpiv-todo", false],
      ["perk-footer", "footer", null, true],
      ["powerline-footer", "footer", "npm:pi-powerline-footer", false],
      ["pi-bar-footer", "footer", "npm:pi-bar", false],
      ["pi-status-footer", "footer", "npm:@tombell/pi-status", false],
      ["pi-default", "footer", null, false],
      ["pi-web-access", "web", "npm:pi-web-access", true],
      ["ollama-web-search", "web", "npm:@ollama/pi-web-search", false],
      ["juicesharp-web-tools", "web", "npm:@juicesharp/rpiv-web-tools", false],
    ],
  );
});

test("loadProviders: the web seam DEFAULT is the FOREIGN pi-web-access (non-null-package default)", () => {
  // The novelty: the web seam's behavior-preserving default carries a non-null `package` because
  // perk owns no native web implementation. The two foreign alts are VACATE-ONLY (null adapter).
  const web = loadProviders().find((p) => p.id === PI_WEB_ACCESS_PROVIDER_ID);
  assert.equal(web?.seam, "web");
  assert.equal(web?.package, "npm:pi-web-access");
  assert.equal(web?.adapter, null);
  assert.equal(web?.default, true);
  assert.equal(web?.packageFilter, undefined);
  const ollama = loadProviders().find((p) => p.id === OLLAMA_WEB_PROVIDER_ID);
  assert.equal(ollama?.adapter, null);
  assert.equal(ollama?.package, "npm:@ollama/pi-web-search");
  assert.equal(ollama?.seam, "web");
  assert.equal(ollama?.default, false);
  assert.equal(ollama?.packageFilter, undefined);
  const rpivWeb = loadProviders().find((p) => p.id === JUICESHARP_WEB_PROVIDER_ID);
  assert.equal(rpivWeb?.adapter, null);
  assert.equal(rpivWeb?.package, "npm:@juicesharp/rpiv-web-tools");
  assert.equal(rpivWeb?.seam, "web");
  assert.equal(rpivWeb?.default, false);
  assert.equal(rpivWeb?.packageFilter, undefined);
});

test("loadProviders: the foreign footer entries are VACATE-ONLY (null adapter, no filter)", () => {
  // Interface seam #2: the footer produces no durable artifact, so there is nothing to bridge —
  // adapter is null (vacate-only). No `package_filter` (each ships a single footer extension).
  const powerline = loadProviders().find((p) => p.id === POWERLINE_FOOTER_PROVIDER_ID);
  assert.equal(powerline?.adapter, null);
  assert.equal(powerline?.package, "npm:pi-powerline-footer");
  assert.equal(powerline?.seam, "footer");
  assert.equal(powerline?.default, false);
  assert.equal(powerline?.packageFilter, undefined);
  const piBar = loadProviders().find((p) => p.id === PI_BAR_FOOTER_PROVIDER_ID);
  assert.equal(piBar?.adapter, null);
  assert.equal(piBar?.package, "npm:pi-bar");
  assert.equal(piBar?.seam, "footer");
  assert.equal(piBar?.default, false);
  assert.equal(piBar?.packageFilter, undefined);
  // pi-status-footer: vacate-only foreign footer (no extension-status rendering, accepted limit).
  const piStatus = loadProviders().find((p) => p.id === PI_STATUS_FOOTER_PROVIDER_ID);
  assert.equal(piStatus?.adapter, null);
  assert.equal(piStatus?.package, "npm:@tombell/pi-status");
  assert.equal(piStatus?.seam, "footer");
  assert.equal(piStatus?.default, false);
  assert.equal(piStatus?.packageFilter, undefined);
  // pi-default: the "install nothing / pi stock footer" option (null package, vacate-only).
  const piDefault = loadProviders().find((p) => p.id === PI_DEFAULT_FOOTER_PROVIDER_ID);
  assert.equal(piDefault?.adapter, null);
  assert.equal(piDefault?.package, null);
  assert.equal(piDefault?.seam, "footer");
  assert.equal(piDefault?.default, false);
  assert.equal(piDefault?.packageFilter, undefined);
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
  // The real entry drops `package_filter` (the illustrative `extensions/*.ts` matched
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
  // `juicesharp-todo` is now a REAL todo provider (todoAdapterJuicesharp bridges it). No
  // `package_filter` (single-concern checklist overlay) — mirrors the tombell case.
  const juicesharp = loadProviders().find((p) => p.id === "juicesharp-todo");
  assert.equal(juicesharp?.adapter, "todoAdapterJuicesharp");
  assert.equal(juicesharp?.package, "npm:@juicesharp/rpiv-todo");
  assert.equal(juicesharp?.seam, "todo");
  assert.equal(juicesharp?.default, false);
  assert.equal(juicesharp?.packageFilter, undefined);
});

// --- resolveProviders (the pure resolver, mirror of tests/test_providers.py) ------------------

test("resolveProviders: absent keys fall back to the seam defaults silently", () => {
  const resolved = resolveProviders({}, loadProviders());
  assert.equal(resolved.plan.id, PERK_PLAN_PROVIDER_ID);
  assert.equal(resolved.todo.id, PERK_CHECKPOINTS_PROVIDER_ID);
  assert.equal(resolved.footer.id, PERK_FOOTER_PROVIDER_ID);
  assert.equal(resolved.web.id, PI_WEB_ACCESS_PROVIDER_ID);
  assert.deepEqual(resolved.issues, []);
});

test("resolveProviders: the footer seam resolves selection / mismatch / unknown", () => {
  const set = loadProviders();
  assert.equal(
    resolveProviders({ footer: PI_BAR_FOOTER_PROVIDER_ID }, set).footer.id,
    PI_BAR_FOOTER_PROVIDER_ID,
  );
  assert.equal(
    resolveProviders({ footer: POWERLINE_FOOTER_PROVIDER_ID }, set).footer.id,
    POWERLINE_FOOTER_PROVIDER_ID,
  );
  const mismatch = resolveProviders({ footer: "perk-plan" }, set);
  assert.equal(mismatch.footer.id, PERK_FOOTER_PROVIDER_ID);
  assert.equal(mismatch.issues.length, 1);
  assert.match(mismatch.issues[0] ?? "", /is a `plan` provider, not `footer`/);
  const unknown = resolveProviders({ footer: "ghost" }, set);
  assert.equal(unknown.footer.id, PERK_FOOTER_PROVIDER_ID);
  assert.equal(unknown.issues.length, 1);
});

test("resolveProviders: the web seam resolves selection / mismatch / unknown", () => {
  const set = loadProviders();
  assert.equal(
    resolveProviders({ web: OLLAMA_WEB_PROVIDER_ID }, set).web.id,
    OLLAMA_WEB_PROVIDER_ID,
  );
  assert.equal(
    resolveProviders({ web: JUICESHARP_WEB_PROVIDER_ID }, set).web.id,
    JUICESHARP_WEB_PROVIDER_ID,
  );
  const mismatch = resolveProviders({ web: "perk-plan" }, set);
  assert.equal(mismatch.web.id, PI_WEB_ACCESS_PROVIDER_ID);
  assert.equal(mismatch.issues.length, 1);
  const unknown = resolveProviders({ web: "ghost" }, set);
  assert.equal(unknown.web.id, PI_WEB_ACCESS_PROVIDER_ID);
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

test("resolveProviders: a missing seam default is PER-SEAM fail-open (the version-skew incident pin)", () => {
  // The incident's shape: a live-edited providers.yaml lost ONE seam's `default: true` entry
  // under old in-memory code (a seam add/retire skew). Every OTHER seam must keep resolving —
  // no throw, no cross-seam collapse (a throw here once collapsed the plan seam to first-party
  // through the callers' fail-safe catches).
  const set = loadProviders().filter((p) => !(p.seam === "footer" && p.default));
  const resolved = resolveProviders({ plan: PLANNOTATOR_PLAN_PROVIDER_ID }, set);
  assert.equal(
    resolved.plan.id,
    PLANNOTATOR_PLAN_PROVIDER_ID,
    "the plan seam still resolves its selection",
  );
  assert.deepEqual(
    resolved.footer,
    { id: PERK_FOOTER_PROVIDER_ID, seam: "footer", package: null, adapter: null, default: true },
    "the gapped seam resolves the synthesized built-in reference",
  );
  assert.equal(resolved.issues.length, 1);
  assert.match(
    resolved.issues[0] ?? "",
    /seam `footer` has no default in the bundled catalog \(version skew\?\)/,
  );
});

test("resolveProviders: a fully-empty catalog resolves every seam to its reference fallback", () => {
  const resolved = resolveProviders({}, []);
  assert.equal(resolved.plan.id, PERK_PLAN_PROVIDER_ID);
  assert.equal(resolved.todo.id, PERK_CHECKPOINTS_PROVIDER_ID);
  assert.equal(resolved.footer.id, PERK_FOOTER_PROVIDER_ID);
  assert.equal(resolved.web.id, PI_WEB_ACCESS_PROVIDER_ID);
  assert.equal(resolved.web.package, "npm:pi-web-access", "the web fallback keeps its package");
  assert.equal(resolved.issues.length, PROVIDER_SEAMS.length, "one loud issue per gapped seam");
});
