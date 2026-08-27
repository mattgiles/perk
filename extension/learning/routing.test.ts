// The learn routing vocabulary's offline suite: the four-arm `decideLearnLaunch` matrix and the
// kind-constant pins (the cross-plane mirror of Python `factory_common.py` — the fields the cold
// argv, templates, binding triggers, and report scopes are derived from). The two user-facing
// kind strings are byte-pinned by the adapter baseline test (pi/v1/learning/factory.test.ts).

import assert from "node:assert/strict";
import { test } from "node:test";
import { CODE_FACTORY, DOCS_FACTORY, decideLearnLaunch } from "./routing.ts";

// --- decideLearnLaunch (the pure bare-/learn routing) --------------------------------------------

test("decideLearnLaunch: a gather failure falls back (gather_failed)", () => {
  assert.deepEqual(decideLearnLaunch({ ok: false }), {
    kind: "fallback",
    reason: "gather_failed",
  });
});

test("decideLearnLaunch: a learn-docs plan short-circuits to consumed_skip", () => {
  // `skipped` wins even when a bundle dir is present — branch order is contract.
  assert.deepEqual(decideLearnLaunch({ ok: true, skipped: true, bundleDir: "/abs/bundle" }), {
    kind: "consumed_skip",
  });
  assert.deepEqual(decideLearnLaunch({ ok: true, skipped: true, bundleDir: null }), {
    kind: "consumed_skip",
  });
});

test("decideLearnLaunch: a success envelope with no bundle dir falls back (no_bundle)", () => {
  assert.deepEqual(decideLearnLaunch({ ok: true, skipped: false, bundleDir: null }), {
    kind: "fallback",
    reason: "no_bundle",
  });
});

test("decideLearnLaunch: a gathered bundle orchestrates with the derived manifest path", () => {
  assert.deepEqual(decideLearnLaunch({ ok: true, skipped: false, bundleDir: "/abs/bundle" }), {
    kind: "orchestrate",
    bundleDir: "/abs/bundle",
    manifestPath: "/abs/bundle/manifest.json",
  });
});

// --- the kind constants (the factory_common.py mirror) -------------------------------------------

test("DOCS_FACTORY: the learned-docs kind bundle", () => {
  assert.equal(DOCS_FACTORY.name, "learn-docs");
  assert.equal(DOCS_FACTORY.subcommand, "docs");
  assert.equal(DOCS_FACTORY.seedTemplate, "stages/learn-docs.md");
  assert.equal(DOCS_FACTORY.bindingTrigger, "command:learn-docs");
  assert.equal(DOCS_FACTORY.emptyMessage, "nothing to consolidate (no open perk:learn issues).");
});

test("CODE_FACTORY: the learn-code kind bundle", () => {
  assert.equal(CODE_FACTORY.name, "learn-code");
  assert.equal(CODE_FACTORY.subcommand, "code");
  assert.equal(CODE_FACTORY.seedTemplate, "stages/learn-code.md");
  assert.equal(CODE_FACTORY.bindingTrigger, "command:learn-code");
  assert.equal(
    CODE_FACTORY.emptyMessage,
    "nothing to route into code (no SHOULD_BE_CODE perk:learn issues).",
  );
});
