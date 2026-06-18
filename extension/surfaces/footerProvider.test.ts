// Footer-seam helper tests (the install-site / runtime vacating decision). `isPerkFooterReferenceSelected`
// resolves the `[providers] footer` selection keyed off `cwd` (no `process.chdir` — `ctx.cwd` flows
// through the `session_start` event), fail-safe to the perk-footer reference on any config-read error.
// Mirror of extension/doors/askUser.test.ts's `isPerkAskUserReferenceSelected` coverage.

import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { scaffoldRepo } from "../testing/harness.ts";
import { isPerkFooterReferenceSelected, resolvedFooterProviderId } from "./footerProvider.ts";

function writePerkToml(cwd: string, body: string): void {
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  writeFileSync(join(cwd, ".pi", "perk.toml"), body, "utf8");
}

test("resolvedFooterProviderId: default repo resolves to perk-footer (reference selected)", () => {
  const cwd = scaffoldRepo();
  assert.equal(resolvedFooterProviderId(cwd), "perk-footer");
  assert.equal(isPerkFooterReferenceSelected(cwd), true);
});

test("isPerkFooterReferenceSelected: explicit footer = perk-footer is the reference", () => {
  const cwd = scaffoldRepo();
  writePerkToml(cwd, '[providers]\nfooter = "perk-footer"\n');
  assert.equal(isPerkFooterReferenceSelected(cwd), true);
});

test("isPerkFooterReferenceSelected: a foreign footer selection is NOT the reference", () => {
  const cwd = scaffoldRepo();
  writePerkToml(cwd, '[providers]\nfooter = "pi-bar-footer"\n');
  assert.equal(resolvedFooterProviderId(cwd), "pi-bar-footer");
  assert.equal(isPerkFooterReferenceSelected(cwd), false);

  writePerkToml(cwd, '[providers]\nfooter = "powerline-footer"\n');
  assert.equal(resolvedFooterProviderId(cwd), "powerline-footer");
  assert.equal(isPerkFooterReferenceSelected(cwd), false);

  writePerkToml(cwd, '[providers]\nfooter = "pi-status-footer"\n');
  assert.equal(resolvedFooterProviderId(cwd), "pi-status-footer");
  assert.equal(isPerkFooterReferenceSelected(cwd), false);

  // pi-default = "install nothing / pi stock footer": perk still vacates (gate false).
  writePerkToml(cwd, '[providers]\nfooter = "pi-default"\n');
  assert.equal(resolvedFooterProviderId(cwd), "pi-default");
  assert.equal(isPerkFooterReferenceSelected(cwd), false);
});

test("isPerkFooterReferenceSelected: a corrupt config fails safe to the reference (perk installs)", () => {
  const cwd = scaffoldRepo();
  // A malformed perk.toml: resolution throws → the helper's try/catch returns perk-footer so perk
  // keeps installing its own footer (the default path is the hard guarantee).
  writePerkToml(cwd, "[providers\nfooter = ");
  assert.equal(isPerkFooterReferenceSelected(cwd), true);
});
